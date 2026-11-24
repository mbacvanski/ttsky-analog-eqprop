"""Cold whole-schematic controls with physical raw readbacks under HOLD and fixed Z/REF during compute."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile

import cluster_storage
from cluster_storage import HOME_RUNS, RUNS
from edge_math import HERE, SIX
from pin_wave import pwls
from threshold_load import RAILS

ROOT = HERE/'evidence'/'quiet'
BASE = ROOT/'input'
CASES = ('hold_release','staged_reset_release')
REMOTE_PDK = '$CLUSTER_HOME/eda/pdk/sky130_792ef67/sky130A'
REMOTE_STDCELL = '$CLUSTER_HOME/eda/runs/ah_amp_layout/pdk_extra/sky130_fd_sc_hd.spice'
DIGITAL = ('bit_a','bit_b','reset','hold_in','ref_reset','obs_sel0','obs_sel1','obs_sel2','obs2_sel0','obs2_sel1',
           'ext_en1','ext_en2','bias_prog','write','res_sel','weight_prog')
EXTRA = ('xdut.xbw.xw1.sg','xdut.xbw.xw2.sg','xdut.bw1','xdut.bw2','xdut.xnet.h1','xdut.xnet.h2','xdut.xnet.hz')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(data):
    return (json.dumps(data,indent=1)+'\n').encode()


def read(path):
    return json.loads(path.read_text())


def verify_return(folder):
    receipt={}
    for line in (folder/'completed.sha256').read_text().splitlines():
        wanted,name=line.split()
        assert name in ('pins.dat.gz','log.gz') and name not in receipt
        assert sha((folder/name).read_bytes())==wanted,(folder,name)
        receipt[name]=wanted
    assert set(receipt)=={'pins.dat.gz','log.gz'}
    return receipt


def map_model_paths(deck):
    old='$PDK_ROOT/sky130A'
    standard=old+'/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice'
    assert deck.count(standard)==1 and deck.count(old)>=5
    return deck.replace(standard,REMOTE_STDCELL).replace(old,REMOTE_PDK)


def archive_template(folder):
    folder=Path(folder)
    plan=read(folder/'protocol.json')
    assert plan['source']['schematic_sha256']==RAILS
    deck=(folder/'run.spice').read_bytes()
    candidate=gzip.decompress((HERE/'evidence/threshold/source_c555.spice.gz').read_bytes())
    assert deck.count(candidate)==1 and sha(candidate)==RAILS
    BASE.mkdir(parents=True,exist_ok=True)
    for dst,data in [('run.spice.gz',gzip.compress(deck,mtime=0)),('protocol.json',dump(plan)),('.spiceinit',(folder/'.spiceinit').read_bytes())]:
        if (BASE/dst).exists():
            assert (BASE/dst).read_bytes()==data
        else:
            (BASE/dst).write_bytes(data)


def make(case,remote=True):
    assert case in CASES
    template=gzip.decompress((BASE/'run.spice.gz').read_bytes()).decode()
    original=read(BASE/'protocol.json')
    pw= pwls(template)
    # Retain all 24 coefficient writes and the first pair's two raw writes, through final SIX enable.
    cutoff=854.
    signals={k:[(float(t),float(v)) for t,v in arr if t<cutoff] for k,arr in pw.items()}
    writes=[x for x in original['writes'] if x['end_us']<cutoff]
    assert len(writes)==26
    samples=[];intervals=[];actions=[]
    def drive(pin,t,value):
        points=signals[pin]
        if abs(points[-1][1]-value)<1e-9:return
        slew=.4 if pin=='board' else .01
        assert t-slew>points[-1][0],(pin,t,points[-1])
        points.extend([(t-slew,points[-1][1]),(t+slew,value)])
    def logic(pin,t,bit):
        drive(pin,t,1.8*bool(bit))
    def select(t,ch):
        for i in range(3):logic('obs_sel'+str(i),t,(ch>>i)&1)
    def sample(row,label,ch,from_us,to_us):
        samples.append(dict(row=row,stage=label,channel=ch,from_us=from_us,to_us=to_us))
    def cue_write(t,row):
        for j,voltage in enumerate(row):
            logic('ext_en1',t,j==0);logic('ext_en2',t,j==1)
            v=round(voltage/(3.3/16384))*(3.3/16384)
            drive('board',t+1,v);logic('write',t+5,1);logic('write',t+25,0)
            writes.append(dict(bank='raw_'+('A' if j==0 else 'B'),address=j,DAC_V=v,start_us=t+5,end_us=t+25))
            t+=30
        drive('board',t+1,round(.9/(3.3/16384))*(3.3/16384))
        logic('bias_prog',t+3,1);logic('ext_en1',t+5,1);logic('ext_en2',t+5,1)
        return t+18
    t=856.
    phase_us=500.
    for row in (0,1):
        if row:
            logic('hold_in',t,1);logic('reset',t+2,1);logic('bias_prog',t+4,0)
            t=cue_write(t+12,[1.035,.940])
        logic('reset',t,0)
        acquisitions=t+75
        for label,ch in [('ref_in',3),('a_held',6),('b_held',7),('ref_out',3),('z_held',0)]:
            select(acquisitions,ch)
            sample(row,label,ch,acquisitions+49,acquisitions+65)
            acquisitions+=75
        last_read=acquisitions
        if case=='staged_reset_release':
            logic('reset',last_read,1)
            logic('hold_in',last_read+40,0)
            logic('reset',last_read+80,0)
            actions.extend([dict(row=row,action='RESET rises while HOLD asserted',at_us=last_read),
                            dict(row=row,action='HOLD falls while RESET asserted',at_us=last_read+40),
                            dict(row=row,action='RESET falls; compute begins',at_us=last_read+80)])
        else:
            logic('hold_in',last_read+80,0)
            actions.append(dict(row=row,action='HOLD falls; compute begins',at_us=last_read+80))
        start=last_read+80
        for j,(label,vdac) in enumerate((('free',.9),('nudge',.94),('resettle',.9))):
            if j:
                drive('board',start+j*phase_us,round(vdac/(3.3/16384))*(3.3/16384))
            sample(row,label,0,start+(j+1)*phase_us-23,start+(j+1)*phase_us-7)
        finish=start+3*phase_us
        intervals.append(dict(row=row,preparation_start_us=t-.01,raw_aperture_start_us=last_read-4*75+49,
            final_Z_select_precompute_us=last_read-75-.01,settled_Z_hold_guard_start_us=last_read-10,
            preparation_control_start_us=last_read-.01,compute_start_us=start-.01,nudge_start_us=start+phase_us-.4,
            resettle_start_us=start+2*phase_us-.4,compute_end_us=finish-.01))
        t=finish
    stop=t
    def make_pwl(match):
        k=match[1];points=signals[k]
        payload='PWL('+' '.join(f'{t:.8g}u {v:.12g}' for t,v in points)+')' if len(points)>1 else str(points[0][1])
        return f'V_{k} {k} 0 '+payload
    deck,n=re.subn(r'^V_(\w+) \w+ 0 [^\n]+',make_pwl,template,flags=re.M)
    assert n==len(signals)
    deck,n=re.subn(r'^\.tran [^\n]+',f'.tran .25u {stop:g}u 0 .25u',deck,flags=re.M);assert n==1
    vectors=next(x.split()[1:] for x in deck.splitlines() if x.startswith('.save '))+['v('+v+')' for v in EXTRA]
    deck=re.sub(r'^\.save [^\n]+','.save '+' '.join(vectors),deck,flags=re.M)
    deck=re.sub(r'^wrdata pins.dat [^\n]+','wrdata pins.dat '+' '.join(vectors),deck,flags=re.M)
    if remote:
        deck=map_model_paths(deck)
    return deck.encode(),dict(case=case,candidate_sha256=RAILS,original_input_deck_sha256=sha(template.encode()),
        writes=writes,pin_apertures=samples,intervals=intervals,preparation_edges=actions,stop_us=stop,
        measurements=vectors,policy='Two independent fixed absolute raw commands per row. Prior to release, 17 simultaneous package ADC pairs for each physical A and B, incoming and returning REF. Output selector Z and secondary REF fixed through free, nudge and resettle. No decision depends on an internal node. All preparation and compute edges are retained.')


def package():
    files={'cases.txt':('\n'.join(CASES)+'\n').encode(),'.spiceinit':(BASE/'.spiceinit').read_bytes()}
    for case in CASES:
        physical,plan=make(case)
        files[case+'.spice.gz']=gzip.compress(physical,mtime=0)
        files[case+'.json']=dump(plan)
    files['run.sh']=(HERE/'quiet_batch.sh').read_bytes()
    files['inputs.sha256']=''.join(sha(v)+'  '+k+'\n' for k,v in sorted(files.items())).encode()
    return files


def register(files,dest,tag,cases,*,scratch_only=False):
    sys.path.insert(0,str(SIX/'analog_clamps/pin_clamp_control'))
    from campaign import ssh
    m=sha(files['inputs.sha256'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+', tag):
        raise ValueError("Invalid native study tag")
    name=tag+'_'+m[:14]
    allowed_roots=(RUNS/name,) if scratch_only else (HOME_RUNS/name,RUNS/name)
    previous=read(dest/'job.json') if (dest/'job.json').is_file() else None
    if previous and previous['manifest_sha256']==m and Path(previous['remote']).name==name:
        if (Path(previous['remote']) not in allowed_roots or
                list(previous['cases'])!=list(cases) or not re.fullmatch(r'\d+',previous['job'])):
            raise ValueError("Existing native registration differs")
        for filename,body in files.items():
            if filename=='.spiceinit':continue
            archived=dest/filename
            if not archived.exists():archived.write_bytes(body)
            elif archived.read_bytes()!=body:raise ValueError("Registered input changed: "+filename)
        print(previous['job'],previous['remote'])
        return
    legacy=str(HOME_RUNS/name)
    scratch=str(RUNS/name)
    transport={}
    launcher='run.sh'
    if any(re.fullmatch(pattern,name) for pattern in cluster_storage.PIN_JOBS.values()):
        launcher='storage-job.sh'
        transport={launcher:cluster_storage.pin_launcher(files['run.sh']),
                   'cluster_storage.py':Path(cluster_storage.__file__).read_bytes()}
        transport['storage.sha256']=''.join(sha(data)+'  '+path+'\n' for path,data in transport.items()).encode()
    blob=io.BytesIO()
    with tarfile.open(fileobj=blob,mode='w:gz') as archive:
        for k,v in {**files,**transport}.items():
            item=tarfile.TarInfo(k);item.size=len(v);archive.addfile(item,io.BytesIO(v))
    stream=blob.getvalue()
    # An older controller may use the home spelling concurrently. ln -sT cannot replace
    # that directory. Whichever creates it first, both launchers acquire the same job.lock.
    if scratch_only:
        setup=f"""scratch={shlex.quote(scratch)}
mkdir -p "$scratch"
cd "$scratch"
test "$(pwd -P)" = "$scratch"
remote=$scratch
"""
    else:
        setup=f"""legacy={shlex.quote(legacy)}
scratch={shlex.quote(scratch)}
if ! test -e "$legacy"; then
    mkdir -p "$scratch" "$(dirname "$legacy")"
    ln -sT "$scratch" "$legacy" 2>/dev/null || test -d "$legacy"
fi
cd "$legacy"
if test "$legacy" -ef "$scratch"; then remote=$scratch; else remote=$legacy; fi
"""
    command = f"""set -eu
umask 077
{setup}exec 9>job.lock
flock -x 9
if ! test -s job.id; then
    tmp=$(mktemp .incoming.XXXXXXXX)
    trap 'rm -f -- "$tmp"' EXIT
    cat > "$tmp"
    echo '{sha(stream)}  '"$tmp" | sha256sum -c --status
    tar xzf "$tmp"
    sha256sum -c --quiet inputs.sha256
    sbatch --parsable {launcher} > job.new
    mv job.new job.id
fi
cat job.id
echo "$remote"
"""
    result,remote=ssh(command,input=stream).decode().splitlines()
    if not re.fullmatch(r'\d+',result) or Path(remote) not in allowed_roots:
        raise ValueError("Unexpected native registration response")
    dest.mkdir(exist_ok=True,parents=True)
    for fname,payload in files.items():
        if fname!='.spiceinit':(dest/fname).write_bytes(payload)
    (dest/'job.json').write_bytes(dump(dict(job=result,remote=remote,manifest_sha256=m,cases=cases)))
    if not previous or previous['job']!=result:
        (dest/'accounting.txt').write_text(result+'|SUBMITTED|00:00:00|\n')
    print(result,remote)


def collect(root,cases):
    sys.path.insert(0,str(SIX/'analog_clamps/pin_clamp_control'))
    from campaign import ssh
    loc=root/'registration';job=read(loc/'job.json')
    accounting=ssh('sacct -X -n -P -j '+job['job']+' --format=JobID,State,Elapsed,ExitCode')
    (loc/'accounting.txt').write_bytes(accounting)
    ready=ssh('cd '+job['remote']+' && for d in '+' '.join(cases)+'; do if test -s "$d/completed.sha256"; then echo "$d"; fi; done').decode().splitlines()
    assert all(case in cases for case in ready)
    for case in ready:
        dest=root/case
        if (dest/'completed.sha256').exists():continue
        remote=job['remote']+'/'+case
        allowed=('completed.sha256','pins.dat.gz','log.gz')
        result=ssh('cd '+remote+' && tar czf - '+' '.join(allowed))
        with tarfile.open(fileobj=io.BytesIO(result)) as arc:
            returned={f.name:arc.extractfile(f).read() for f in arc if f.isfile() and f.name in allowed}
        assert set(returned)==set(allowed)
        verified={}
        for line in returned['completed.sha256'].decode().splitlines():
            digest,f=line.split();assert f in allowed[1:] and sha(returned[f])==digest
            verified[f]=digest
        assert set(verified)==set(allowed[1:])
        dest.mkdir(parents=True,exist_ok=True)
        for name in (*allowed[1:],allowed[0]):(dest/name).write_bytes(returned[name])
    print(accounting.decode().strip())


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('action',choices=('freeze','submit','fetch'))
    a.add_argument('path',nargs='?',type=Path)
    args=a.parse_args()
    if args.action=='freeze':archive_template(args.path)
    elif args.action=='submit':register(package(),ROOT/'registration','native_passive_quiet_c555',CASES)
    else:collect(ROOT,CASES)
