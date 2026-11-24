"""Independent full-chip hold and package-aperture audit of the two continuous native bring-up rows."""
import argparse
import gzip
import json
from pathlib import Path
import re

import numpy as np

from native_fixture import HERE, digest


ADC = 2.048 / 65536
DIGITAL = ['bit_a','bit_b','obs_sel0','obs_sel1','obs_sel2','obs2_sel0','obs2_sel1','reset',
           'hold_in','weight_prog','bias_prog','write','res_sel','ext_en1','ext_en2','ref_reset']
MASK = {'a':'v(xdut.bias1)','b':'v(xdut.bias2)','z':'v(xdut.z)','ref':'v(xdut.ref)'}


def pwls(deck):
    data={}
    for line in deck.splitlines():
        if not line.startswith('V_'):
            continue
        fields=line.split(maxsplit=3)
        name=fields[1]
        field=fields[3]
        if not field.startswith('PWL('):
            data[name]=np.array([[0.,float(field)]])
            continue
        parts=field.removeprefix('PWL(').removesuffix(')').split()
        data[name]=np.array([(float(t.removesuffix('u')),float(v)) for t,v in zip(parts[::2],parts[1::2])])
    return data


def transitions(knots):
    out=[]
    for previous,current in zip(knots,knots[1:]):
        if abs(current[1]-previous[1])>1e-8:
            out.append(dict(start_us=previous[0],end_us=current[0],old_V=previous[1],new_V=current[1]))
    return out


def wave_slice(t,y,lo,hi):
    i0=np.searchsorted(t,lo,side='right')
    i1=np.searchsorted(t,hi,side='left')
    return np.r_[lo,t[i0:i1],hi],np.r_[np.interp(lo,t,y),y[i0:i1],np.interp(hi,t,y)]


def stats(t,y,lo,hi):
    x,v=wave_slice(t,y,lo,hi)
    imin,imax=int(np.argmin(v)),int(np.argmax(v))
    return dict(start_V=float(v[0]),end_V=float(v[-1]),min_V=float(v[imin]),max_V=float(v[imax]),
                peak_to_peak_mV=float(1000*np.ptp(v)),time_of_min_us=float(x[imin]),time_of_max_us=float(x[imax]),
                max_individual_step_mV=float(1000*np.max(abs(np.diff(v)))),mean_V=float(np.trapezoid(v,x)/(hi-lo)))


def out_of_band(t,y,lo,hi,baseline,tolerance_mV=.5):
    """Exact piecewise-linear time outside a fixed band through every solver interval."""
    x,v=wave_slice(t,y,lo,hi)
    relative=v-baseline
    boundaries=[lo,hi]
    margin=tolerance_mV/1000
    for level in (-margin,margin):
        mask=(relative[:-1]>level)!=(relative[1:]>level)
        left=np.flatnonzero(mask)
        boundaries.extend((x[left]+(level-relative[left])*(x[left+1]-x[left])/
                            (relative[left+1]-relative[left])).tolist())
    cuts=np.unique(boundaries)
    mid=(cuts[1:]+cuts[:-1])/2
    missed=abs(np.interp(mid,x,relative))>margin
    widths=np.diff(cuts)[missed]
    intervals=np.stack((cuts[:-1][missed],cuts[1:][missed]),axis=1)
    knots=np.union1d(x,cuts)
    excess=np.maximum(abs(np.interp(knots,x,relative))-margin,0)
    area_V_us=np.trapezoid(excess,knots)+margin*np.sum(widths)
    return dict(guard_V=float(baseline),threshold_mV=tolerance_mV,
                peak_absolute_departure_mV=float(1000*np.max(abs(relative))),
                total_ns=float(1000*np.sum(widths)),longest_ns=float(1000*np.max(widths,initial=0)),
                absolute_excursion_area_outside_band_mV_ns=float(1e6*area_V_us),
                excursion_count=int(len(widths)),last_return_us=float(intervals[-1,1]) if len(widths) else None)


def event_effects(t,wave,pins,lo,hi):
    grouped={}
    for name,knots in pins.items():
        for e in transitions(knots):
            if lo-1e-5<=e['start_us']<hi-1e-4:
                grouped.setdefault(float(e['start_us']),[]).append(name)
    times=sorted(grouped)
    effects=[]
    for i,at in enumerate(times):
        end=times[i+1] if i+1<len(times) else hi
        channels={}
        for k in ('a','b','ref','a_relative','b_relative'):
            guard=stats(t,wave[k],at-.4,at-.06)['mean_V']
            channels[k]=out_of_band(t,wave[k],at,end,guard)
        effects.append(dict(edge_start_us=at,until_next_edge_us=end,changed_package_controls=grouped[at],channels=channels))
    return effects


def audit(folder):
    folder=Path(folder)
    plan=json.loads((folder/'protocol.json').read_text())
    deck_path=folder/'run.spice'
    deck=deck_path.read_text() if deck_path.exists() else gzip.decompress((folder/'run.spice.gz').read_bytes()).decode()
    path=folder/'pins.dat'
    if not path.exists():
        path=folder/'pins.dat.gz'
    raw=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    from io import BytesIO
    stream=BytesIO(raw)
    cols=stream.readline().decode().lower().split()
    table=np.loadtxt(stream).T
    assert table.shape[0]==len(cols) and len(set(cols))==len(cols) and np.isfinite(table).all()
    w=dict(zip(cols,table))
    t=w['time']*1e6
    assert np.all(np.diff(t)>0) and abs(t[-1]-plan['stop_us'])<.001
    p=pwls(deck)
    dig_error={}
    for pin in [*DIGITAL,'board']:
        exact=np.interp(t,p[pin][:,0],p[pin][:,1])
        dig_error[pin]=float(np.max(abs(exact-w['v('+pin+')'])))
        assert dig_error[pin]<1e-7,(pin,dig_error[pin])
    expected_counts={'A':4,'B':4,'Z':4,'A_precondition':4,'B_precondition':4,'Z_precondition':4,'raw_A':2,'raw_B':2}
    assert all(sum(x['bank']==q for x in plan['writes'])==n for q,n in expected_counts.items())
    strobes=transitions(p['write'])
    rising=[a for a in strobes if a['new_V']>a['old_V']]
    assert len(rising)==len(plan['writes'])
    decoded=[]
    for at,log in zip(rising,plan['writes']):
        mid=log['start_us']+10
        v={n:np.interp(mid,t,w['v('+n+')']) for n in DIGITAL}
        high=lambda n:v[n]>.9
        assert abs((at['start_us']+at['end_us'])/2-log['start_us'])<1e-8
        cmd=np.interp(mid,t,w['v(board)'])
        assert abs(cmd-log['DAC_V'])<1e-7
        if log['bank'].startswith('raw_'):
            assert high('weight_prog') and not high('res_sel') and not high('bias_prog')
            selected=[i for i in (1,2) if high('ext_en'+str(i))]
            assert selected==[1+log['address']] and log['bank']=='raw_'+'AB'[selected[0]-1]
        else:
            assert not high('weight_prog') and high('res_sel') and not high('ext_en1') and not high('ext_en2')
            row={(0,0):'Z',(1,0):'A',(0,1):'B'}[(int(high('bit_a')),int(high('bit_b')))]
            assert row==log['bank'].split('_')[0] and int(high('obs_sel2'))+2*int(high('obs2_sel0'))==log['address']
        decoded.append(dict(bank=log['bank'],address=log['address'],DAC_V=float(cmd),start_us=log['start_us'],duration_us=log['end_us']-log['start_us']))
    hold=transitions(p['hold_in'])
    releases=[e['start_us'] for e in hold if e['new_V']<e['old_V']]
    assert len(releases)==2
    modes=[]
    pairvolt={k:w[n] for k,n in MASK.items()}
    wave={**pairvolt,**{k+'_relative':array-pairvolt['ref'] for k,array in pairvolt.items() if k!='ref'}}
    board_edges=transitions(p['board'])
    phases=[];edges=[]
    for i,lo in enumerate(releases):
        next_high=next((e for e in hold if e['start_us']>lo and e['old_V']<e['new_V']),None)
        hi=next_high['start_us'] if next_high else t[-1]
        changes=[e for e in board_edges if lo<e['start_us']<hi]
        assert len(changes)==2,changes
        nudge,returned=[e['start_us'] for e in changes]
        for pin in ('weight_prog','bias_prog','ext_en1','ext_en2','write','res_sel','reset','bit_a','bit_b'):
            _,u=wave_slice(t,w['v('+pin+')'],lo,hi)
            assert np.ptp(u)<1e-7
        limits=[('all_compute',lo,hi),('free',lo,nudge),('nudge',nudge,returned),('resettle',returned,hi)]
        edges+= [dict(row=i,**x) for x in event_effects(t,wave,p,lo,hi)]
        guards={k:stats(t,wave[k],lo-2,lo-.2)['mean_V'] for k in ('a','b','ref','a_relative','b_relative')}
        for tag,start,stop in limits:
            q={key:stats(t,u,start,stop) for key,u in wave.items()}
            excursions={k:out_of_band(t,wave[k],start,stop,value) for k,value in guards.items()}
            phases.append(dict(row=i,phase=tag,start_us=float(start),end_us=float(stop),nodes=q,
                          deviations_from_pre_HOLD_guard=excursions))
        windows=[q for q in plan['samples'] if q['row']==i and q['channel']==3]
        assert len(windows)==3
        if next_high:
            raw_strobe=next(u['start_us'] for u in decoded if u['start_us']>hi)
            modes.append(dict(row=i,scope='next HOLD rising through just before next raw write',
                start_us=float(hi),end_us=float(raw_strobe-.01),nodes={key:stats(t,u,hi,raw_strobe-.01) for key,u in wave.items()}))
    readings=[]
    zero={}
    for s in plan['samples']:
        clock=np.arange(s['from_us'],s['to_us']+1,1.)
        a,b=[np.rint(np.interp(clock,t,w['v('+k+')'])/ADC).astype(int) for k in ['adc0','adc2']]
        assert min(a.min(),b.min())>=0 and max(a.max(),b.max())<=65535
        primary=sum((np.interp(clock,t,w['v(obs_sel'+str(k)+')'])>.9).astype(int)*2**k for k in range(3))
        secondary=sum((np.interp(clock,t,w['v(obs2_sel'+str(k)+')'])>.9).astype(int)*2**k for k in range(2))
        assert np.all(primary==s['channel']) and not np.any(secondary)
        differential=float(np.mean(a-b)*ADC)
        iden=(s['row'],s['stage'])
        if s['channel']==3:
            zero[iden]=differential
        corrected=differential-zero[iden]
        phys=wave[{0:'z_relative',3:'ref',6:'a_relative',7:'b_relative'}[s['channel']]]
        true=float(np.mean(np.interp(clock,t,phys))) if s['channel']!=3 else 0.
        readings.append(dict(**s,pin_clock_us=clock.tolist(),primary_codes=a.tolist(),secondary_codes=b.tolist(),
                pair_offset_mV=1000*zero[iden],reference_corrected_mV=1000*corrected,intrinsic_simultaneous_mV=1000*true,
                corrected_pin_minus_intrinsic_mV=1000*(corrected-true)))
    return dict(source_schematic_sha256=plan['source']['schematic_sha256'],input_deck_sha256=digest(deck.encode()),
                recording_sha256=digest(raw),recording_rows=len(t),checked_commands=decoded,checked_drive_PWL_max_error_V=dig_error,
                solver_stop_us=float(t[-1]),aperture_count=len(readings),clock_pairs=len(readings)*17,
                external_acquisitions=readings,phase_intervals=phases,inter_example_transition=modes,
                individual_external_command_edges=edges,
                scope='Open-loop predetermined absolute DAC commands. Two raw buffers and local REF are passive diagnostic probes; no hidden information entered a command. A/B are multiplexed in separate intervals; each is acquired simultaneously with REF and corrected with its dual-REF acquisition. Intrinsic hold metric includes every solver frame and the beginning of the HOLD falling edge.')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('out',type=Path)
    arg=ap.parse_args()
    result=audit(arg.source)
    arg.out.parent.mkdir(exist_ok=True,parents=True)
    arg.out.write_text(json.dumps(result,indent=1)+'\n')
    print([(p['row'],p['phase'],[round(p['nodes'][n]['peak_to_peak_mV'],4) for n in ('a_relative','b_relative')])
           for p in result['phase_intervals']])
