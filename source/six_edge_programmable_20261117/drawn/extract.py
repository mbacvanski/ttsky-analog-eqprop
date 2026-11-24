"""Extract the complete routed GDS for direct transistor-level external-pin tests."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
SIX=HERE.parent
sys.path.insert(0,str(SIX/'layout_cells'))
from switches import tool,MAGIC,MAGICRC

TOP='tt_um_mbacvanski_denseam_six'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def export(gds,top=TOP):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",top):
        raise ValueError("Invalid GDS cell name")
    key=sha(gds)
    run=HERE/'runs'/'extraction'/key[:16]
    run.mkdir(exist_ok=True,parents=True)
    script=run/'extract.tcl'
    script.write_text(f'''snap internal
gds read {gds.resolve()}
load {top}
select top cell
expand
flatten six_flat
load six_flat
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o raw_lvs.spice
ext2spice cthresh 0
ext2spice -o raw_cap.spice
quit -noprompt
''')
    tool([MAGIC,'-dnull','-noconsole','-rcfile',str(MAGICRC),str(script)],run,'magic.log')
    # Keep all terminals and capacitances. Restrict identifiers to letters,
    # digits and underscore so spice dialects interpret internal punctuation
    # in Magic's labels identically.
    text=re.sub(r'\n\+\s*',' ',(run/'raw_cap.spice').read_text())
    head=next(l for l in text.splitlines() if l.startswith('.subckt six_flat '))
    ports=head.split()[2:]
    assert len(ports)==len(set(ports))==37
    nodes={p:'pin_'+str(i) for i,p in enumerate(ports)}
    nodes['0']='0'
    def node(n):
        if n not in nodes:nodes[n]='n_'+str(len(nodes)-len(ports))
        return nodes[n]
    counters=Counter()
    out=['.subckt sx_drawn '+' '.join(node(p) for p in ports)]
    for line in text.splitlines():
        if line.startswith('X'):
            fields=line.split()
            i=next(i for i,v in enumerate(fields) if v.startswith('sky130_fd_pr__'))
            counters[fields[i]]+=1
            out.append(' '.join([fields[0],*[node(v) for v in fields[1:i]],*fields[i:]]))
        elif line.startswith('C'):
            name,left,right,val=line.partition(';')[0].split()
            counters['coupling_or_substrate_capacitors']+=1
            out.append(' '.join([name,node(left),node(right),val]))
        elif line.strip() and not line.startswith(('*','.subckt','.ends')):
            raise ValueError(f'Unsupported extracted element: {line}')
    assert counters['coupling_or_substrate_capacitors']>1000 and sum(counters.values())>2000
    out.append('.ends sx_drawn')
    net=run/'flat_parasitics.spice'
    net.write_text('\n'.join(out)+'\n')
    (run/'nodes.json.gz').write_bytes(gzip.compress(json.dumps(nodes,sort_keys=True).encode(),mtime=0))
    meta=dict(gds_sha256=key,source_gds=gds.name,extracted_top=top,extracted_ports=ports,
              magic_flat_lvs_sha256=sha(run/'raw_lvs.spice'),magic_flat_cap_sha256=sha(run/'raw_cap.spice'),
              simulation_netlist_sha256=sha(net),element_counts=counters,
              parasitics='Magic flat cthresh 0 capacitances and physical sourced/drain diffusion areas. Interconnect resistance excluded.')
    (run/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(run,'devices',sum(counters.values())-counters['coupling_or_substrate_capacitors'],'caps',counters['coupling_or_substrate_capacitors'])
    return run

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('gds',type=Path)
    p.add_argument("--top",default=TOP)
    a=p.parse_args();export(a.gds,a.top)
