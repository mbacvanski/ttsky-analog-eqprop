"""Three-terminal characterization of two original H--Z weights sharing one clamped input driver."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import numpy as np
from edge_math import EXPECTED, FROZEN, HERE, V4, parts

sys.path.insert(0,str(V4/'circuit'))
import host
import v4lib as lib

PROGRAMS=((.25,.75),(.5,.5),(.75,.25),(.75,.75),(.25,.25))
PORTS=('a','h1','h2')
NODES=['a','h1','h2','driver','w0','w1','w2','w3','wp','clampw','iso','wr','dac','ref','vdd',
       'bank.xsh1.gn','bank.xsh2.gn','bank.xbr1.gn','bank.xbr2.gn']
CHANNELS=[*['v(x'+k+')' if k.startswith('bank.') else 'v('+k+')' for k in NODES],*['i(vsense'+k+')' for k in PORTS]]
NOMINAL=1.8
QUANT=3.3/16384


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Sequence:
    def __init__(self):
        self.sources={name:[(0.,0.)] for name in ('a','h1','h2','dac','addr0','addr1','wr','rs','wp','az')}
        self.writes=[]
        self.rows=[]
        self.set('az',1,1.8)
        self.set('az',32,0)
        self.set('rs',33,1.8)

    def set(self,pin,t,value):
        knots=self.sources[pin]
        if abs(knots[-1][1]-value)<1e-12:
            return
        half=.02 if pin in ('dac','a','h1','h2') else .005
        assert t-half>knots[-1][0]
        knots.extend([(t-half,knots[-1][1]),(t+half,value)])

    def word(self,t,address,voltage):
        for i in (0,1):
            self.set('addr'+str(i),t,(address>>i&1)*1.8)
        code=round(voltage/QUANT)
        self.set('dac',t+1,code*QUANT)
        self.set('wr',t+4,1.8)
        self.set('wr',t+24,0.)
        self.writes.append(dict(address=address,target_DAC_code=code,terminal_V=code*QUANT,from_us=t+4,to_us=t+24))
        return t+30

    def present(self,t,point,group):
        for pin,v in zip(PORTS,point):
            self.set(pin,t,v/1000.)
        self.rows.append(dict(program=group,target_port_mV=point,t0_us=t,end_us=t+28))
        return t+30


def schedules(wide=False):
    d=Sequence();t=40
    cmap=host.cell_map('nominal')
    for j,w in enumerate(PROGRAMS):
        for pin in PORTS:
            d.set(pin,t,0)
        d.set('wp',t+6,0)
        t+=12
        wanted=[parts(x) for x in w]
        for addr,(role,g) in enumerate([('sh',wanted[0][0]),('sh',wanted[1][0]),('br',wanted[0][1]),('br',wanted[1][1])]):
            for v in (.2,host.code_for(cmap,role,g)):
                t=d.word(t,addr,v)
        d.set('dac',t+1,.9);d.set('wp',t+5,1.8);t+=20
        t=d.present(t,[0,0,0],j)
        for size in (10.,40.):
            for port in range(3):
                for sign in (-1.,1.):
                    q=[0.,0.,0.];q[port]=size*sign;t=d.present(t,q,j)
        for level in (-100.,100.):
            for raw in (-25.,25.):
                t=d.present(t,[raw,level,level],j)
        if wide:
            for raw,h1,h2 in [(100,100,-100),(200,-100,-100),(200,0,0),(200,100,100),(0,-100,100)]:
                t=d.present(t,[raw,h1,h2],j)
        t=d.present(t,[0,0,0],j)
    return d,t+2


def pwl(knots):
    if len(knots)==1:return str(knots[0][1])
    return 'PWL('+' '.join(f'{t:.6f}u {v:.12g}' for t,v in knots)+')'


def make(buffered, fault, assembled=False, candidate='d2ee'):
    src=gzip.decompress(FROZEN.read_bytes())
    assert digest(src)==EXPECTED
    circuit=src
    if assembled:
        circuit=gzip.decompress((HERE/'evidence'/'threshold'/f'source_{candidate}.spice.gz').read_bytes())
        expected={'d2ee':'d2eeab63e650601db8bb17cd740653614042bd54f6862b82d6ca53e8e863a584',
                  'c555':'c5554a58fa7d128c18185dd1f5825c9cba79dd4629cd8095ec77fa5924a65075'}
        assert digest(circuit)==expected[candidate]
    blocks=re.findall(r'^\.subckt\s+.*?^\.ends[^\n]*\n',circuit.decode(),re.M|re.S|re.I)
    d,stop=schedules(assembled)
    root=Path(lib.PDK)
    models=lib.pdk_lib('tt')
    models='\n'.join(x for x in models.splitlines() if not x.startswith(('.lib ','.endl ')))
    seq=['* Two unmodified native edges. No digital or analog coefficient multiply.',models,
         f'.include "{lib.STD}"','.param VDD=1.8 VREF=.9 VUNIT=.1 CORE_SCALE=1 TAU_R=6.5meg STATE_C=6.5p MODEL_TAU=43.5u',
         '.param ACT_SLOPE=11.5 ACT_LIMIT=.99','.temp 27',
         '.options method=gear maxord=2 reltol=3e-5 abstol=3e-13 vntol=3e-8 gmin=1e-15 pivrel=.1',*blocks,
         'Vrail vdd 0 PWL(0 0 0.1u 0 4u 1.8)','Vreference ref 0 PWL(0 0 0.1u 0 4u .9)']
    for n,knots in d.sources.items():
        if n in PORTS:
            target='driver' if n=='a' else 'drive_'+n
            seq.append(f'Vtarget{n} {target} ref '+pwl(knots))
        else:
            seq.append(f'Vinput{n} {n} 0 '+pwl(knots))
    if buffered:
        seq+=['XAZINV az azb vdd 0 cmos_inv','XBUF driver out out az azb ref vdd 0 cd_ref_az COMP=1.2p DRIVE=1 RZERO=5k HEADROOM=1',
              'Vsensea out a 0']
    else:seq.append('Vsensea driver a 0')
    seq+=['Vsenseh1 drive_h1 h1 0','Vsenseh2 drive_h2 h2 0','XRpin dac d 0 pdk_rpin_h RVALUE=10k',
          'Xdecode addr0 addr1 wr rs wp w0 w1 w2 w3 iso clampw vdd 0 pw4_decoder',
          'Xmid m1 m2 m1x m2x iso 0 pw4_mid',
          'Xmidalt a h1 ax h1x iso 0 pw4_mid','Xthird h2 unused h2x dummy iso 0 pw4_mid',
          'Rtieunused unused 0 1','Rtiedummy dummy 0 1',
          'Xleft a h1 0 m1 pdk_rfixed2_h_m RVALUE=200k','Xright a h2 0 m2 pdk_rfixed2_h_m RVALUE=200k',
          'Xbank h1x h2x ax m1x m2x ref d w0 w1 w2 w3 clampw vdd 0 pw4_rblock4']
    if assembled:
        start=seq.index('Xmid m1 m2 m1x m2x iso 0 pw4_mid')
        seq=seq[:start]+['Xsourcebus a spare ax sx iso 0 pw4_mid','Rspare spare ref 1','Rsx sx ref 1',
             'Xbank a ax h1 h2 ref d w0 w1 w2 w3 iso clampw vdd 0 native_clamped_row']
    if fault=='crossed_bridge':
        seq[-1]=seq[-1].replace('d w0 w1 w2 w3','d w0 w1 w3 w2')
    if fault=='open_shunt':
        if assembled:
            nominal='XRB fx1 fx2 raw_bus mx1 mx2 ref dac we0 we1 we2 we3 park vdd vss pw4_rblock4'
            switched=nominal.replace('raw_bus mx1 mx2','raw_bus ref mx2')
            assert sum(x.count(nominal) for x in seq)==1
            seq=[x.replace(nominal,switched) for x in seq]
        else:seq[-1]=seq[-1].replace('ax m1x m2x','ax ref m2x')
    vectors=' '.join(CHANNELS).replace('xbank.x','xbank.xrb.x') if assembled else ' '.join(CHANNELS)
    seq.extend([f'.tran .10u {stop:g}u 0 .10u','.control','set wr_singlescale','set wr_vecnames','set numdgt=16',
                'save '+vectors,'run','wrdata data.txt '+vectors,'echo NATIVE_EDGE_COMPLETE','quit','.endc','.end'])
    return '\n'.join(seq)+'\n',dict(frozen_sha256=EXPECTED,assembled_sha256=digest(circuit),assembled=assembled,buffered=buffered,fault=fault,
                sources=d.sources,all_program_writes=d.writes,measurement_rows=d.rows,weight_programs=PROGRAMS,stop_us=stop,
                saved_vectors=vectors.split(),wave_archive_keys=CHANNELS)


def analyze(mat,plan):
    t=mat[0]*1e6
    assert np.isfinite(mat).all() and t[-1]>=plan['stop_us']-.002
    w=dict(zip(CHANNELS,mat[1:]))
    writes=[]
    for row in plan['all_program_writes']:
        clocks=np.arange(row['from_us']+1,row['to_us']-1)
        assert np.max(abs(np.interp(clocks,t,w['v(dac)'])-row['terminal_V']))<1e-7
        for i in range(4):
            expect=(i==row['address'])*1.8
            np.testing.assert_allclose(np.interp(clocks,t,w['v(w'+str(i)+')']),expect,atol=5e-4)
        writes.append(row)
    rows=[]
    for row in plan['measurement_rows']:
        lo=row['end_us']-4;hi=row['end_us'];clk=np.linspace(lo,hi,17)
        assert np.min(np.interp(clk,t,w['v(iso)']))>1.79 and np.max(np.interp(clk,t,w['v(clampw)']))<.01
        assert max(np.ptp(np.interp(clk,t,w[k])) for k in ('v(a)','v(h1)','v(h2)'))<1e-4
        volts=[1000*np.mean(np.interp(clk,t,w['v('+k+')']-w['v(ref)'])) for k in PORTS]
        current=[1e6*np.mean(np.interp(clk,t,w['i(vsense'+k+')'])) for k in PORTS]
        rows.append(dict(**row,measured_ports_mV=volts,source_into_network_uA=current))
    programs=[]
    for j,weights in enumerate(PROGRAMS):
        selected=[x for x in rows if x['program']==j]
        zero=selected[0]['measured_ports_mV'][0]
        results={}
        for scale in (10,40):
            axis=[r for r in selected if sum(abs(x)>0 for x in r['target_port_mV'])==1 and max(map(abs,r['target_port_mV']))==scale]
            voltage=np.asarray([r['measured_ports_mV'] for r in axis]);amps=np.asarray([r['source_into_network_uA'] for r in axis])
            dv=(voltage[1::2]-voltage[::2])*.001;di=amps[1::2]-amps[::2]
            g=np.linalg.solve(dv,di).T
            expect=np.array([[15,-10*weights[0],-10*weights[1]],[-10*weights[0],7.5,0],[-10*weights[1],0,7.5]])
            results[str(scale)]=dict(measured_matrix_uS=g.tolist(),expected_matrix_uS=expect.tolist(),
                max_absolute_cross_error_uS=float(max(abs(g[1,0]-expect[1,0]),abs(g[2,0]-expect[2,0]))),
                maximum_diagonal_error_uS=float(np.max(abs(np.diag(g-expect)))),
                maximum_reciprocity_error_uS=float(np.max(abs(g-g.T))))
        extremes=[r for r in selected if abs(r['target_port_mV'][0])==25 and r['target_port_mV'][1]==r['target_port_mV'][2] and abs(r['target_port_mV'][1])==100]
        wide=[r for r in selected if r['target_port_mV'][0] in (100,200)]
        maxerr=max(abs(r['measured_ports_mV'][0]-r['target_port_mV'][0]) for r in extremes)
        maxdelta=max(abs(r['measured_ports_mV'][0]-r['target_port_mV'][0]-zero) for r in extremes)
        swing=[]
        for raw in (-25,25):
            pair=[r for r in extremes if r['target_port_mV'][0]==raw]
            dv=pair[1]['measured_ports_mV'][0]-pair[0]['measured_ports_mV'][0]
            di=pair[1]['source_into_network_uA'][0]-pair[0]['source_into_network_uA'][0]
            swing.append(dict(fixed_target_mV=raw,actual_clamp_droop_mV=dv,source_current_change_uA=di,
                              inferred_output_resistance_ohm=-1000*dv/di))
        programs.append(dict(target_weights=weights,finite_difference=results,zero_driver_offset_mV=zero,
            max_clamp_absolute_error_at_opposed_load_mV=maxerr,max_clamp_error_after_subtracting_center_mV=maxdelta,
            wide_driver_points=[dict(requested_raw_mV=r['target_port_mV'][0],H1_H2_mV=r['target_port_mV'][1:],
                    actual_buffer_mV=r['measured_ports_mV'][0],delivered_uA=r['source_into_network_uA'][0]) for r in wide],
            load_swings=swing,zero_return_mV=selected[-1]['measured_ports_mV'][0]))
    return dict(port_order=PORTS,all_40_addresses_verified=len(writes)==40,ordinary_native_time_points=len(t),programs=programs,
                all_measurements=rows)


def execute(mode,fault,assembled,candidate):
    buffered=(mode=='buffer')
    text,plan=make(buffered,fault,assembled,candidate)
    tag=mode if not fault else mode+'_'+fault
    prefix=('assembled_' if candidate=='d2ee' else 'assembled_'+candidate+'_') if assembled else ''
    dest=HERE/'evidence'/(prefix+tag);dest.mkdir(exist_ok=True,parents=True)
    with tempfile.TemporaryDirectory(prefix='native-edge-',dir='/tmp') as tmp:
        work=Path(tmp)
        (work/'run.spice').write_text(text);(work/'.spiceinit').write_text(lib.SPICEINIT)
        with (work/'solver.log').open('wb') as log:
            run=subprocess.run(['nice','-n','15',lib.NGSPICE,'-b','run.spice'],cwd=work,stdout=log,stderr=subprocess.STDOUT,
                               env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
        log=(work/'solver.log').read_bytes()
        if run.returncode or b'NATIVE_EDGE_COMPLETE' not in log or b'Timestep too small' in log:
            print(log.decode(errors='replace')[-1800:]);return 1
        with (work/'data.txt').open('rb') as f:
            expected=[c.replace('xbank.x','xbank.xrb.x') if assembled else c for c in CHANNELS]
            assert f.readline().decode().split()==['time',*expected]
            table=np.loadtxt(f).T
        report=analyze(table,plan)
        report.update(physical_deck_sha256=digest(text.encode()),ordinary_solver_text_sha256=digest((work/'data.txt').read_bytes()),
                      source_map_sha256=digest((V4/'circuit/results/cell_res_corners.json').read_bytes()))
        (dest/'run.spice.gz').write_bytes(gzip.compress(text.encode(),mtime=0))
        (dest/'solver.log.gz').write_bytes(gzip.compress(log,mtime=0))
        np.savez_compressed(dest/'wave.npz',time_s=table[0],**dict(zip(CHANNELS,table[1:])))
        (dest/'plan.json').write_text(json.dumps(plan,indent=1)+'\n')
        (dest/'result.json').write_text(json.dumps(report,indent=1)+'\n')
        print([(q['target_weights'],np.round(np.array(q['finite_difference']['10']['measured_matrix_uS'])[:,0],3),
                round(q['max_clamp_absolute_error_at_opposed_load_mV'],3)) for q in report['programs']],flush=True)
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('ideal','buffer'))
    p.add_argument('--fault',choices=('crossed_bridge','open_shunt'))
    p.add_argument('--assembled',action='store_true')
    p.add_argument('--candidate',choices=('d2ee','c555'),default='d2ee')
    a=p.parse_args();sys.exit(execute(a.mode,a.fault,a.assembled,a.candidate))
