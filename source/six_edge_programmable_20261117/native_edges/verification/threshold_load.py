"""Measure native hidden-threshold load with matched PDK reference ladders and identical forced F1/F2 sweeps."""
import argparse
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import numpy as np

from native_fixture import HERE, digest, lib, pwl


DIRECT = 'd2eeab63e650601db8bb17cd740653614042bd54f6862b82d6ca53e8e863a584'
RAILS = 'c5554a58fa7d128c18185dd1f5825c9cba79dd4629cd8095ec77fa5924a65075'
ORDER = [(0, 0), (-100, -100), (-100, 100), (100, -100), (100, 100),
         (0, 0), (0, 100), (0, -100), (-100, 0), (100, 0), (0, 0)]
VECTORS = ['v(vdd)', 'v(az)', 'v(ref)', 'v(xref.ref_tap)', 'v(tap1)', 'v(tap2)',
           'v(f1)', 'v(f2)', 'v(p1)', 'v(p2)', 'v(q1)', 'v(q2)', 'v(h1bias)', 'v(h2bias)',
           'v(raw1)', 'v(raw2)', 'i(vbias1)', 'i(vbias2)', 'i(vtail1)', 'i(vtail2)']
EVIDENCE = HERE / 'evidence' / 'threshold'


def blocks(text):
    return {body.split()[1]: body for body in re.findall(r'^\.subckt\s+.*?^\.ends[^\n]*\n', text, re.I | re.M | re.S)}


def source(mode):
    if mode in ('rails','trimmed'):
        snap = EVIDENCE / 'source_c555.spice.gz'
        active = HERE.parent / 'circuit' / 'native_six.spice'
        data = gzip.decompress(snap.read_bytes()) if snap.exists() else active.read_bytes()
        assert digest(data) == RAILS
        models = blocks(data.decode())
        if mode == 'trimmed':
            offsets = models['native_fixed_offsets']
            for old, new in (('18181.81818','14065'),('48275.86207','44300')):
                assert offsets.count('RVALUE='+old) == 1
                offsets = offsets.replace('RVALUE='+old, 'RVALUE='+new)
            models['native_fixed_offsets'] = offsets
        return models, RAILS

    data = gzip.decompress((EVIDENCE / 'source_d2ee.spice.gz').read_bytes())
    assert digest(data) == DIRECT
    return blocks(data.decode()), DIRECT


def make(mode, condition='nominal'):
    cells, sha = source(mode)
    original = cells['cd_core_two_az_pq']
    rail_mode = mode in ('rails','trimmed')
    reference = 'xor_references_stiff' if rail_mode else 'native_six_references'
    connections = '' if rail_mode else ' tap1 tap2'
    active = cells['xor_chip_native_six']
    assert 'XH1BIAS bias1 fixed1 six h1bias vdd vss ext_bias_switch' in active
    if rail_mode:
        assert 'XSTATIC ref fixed1 fixed2 p1 p2 six vss native_fixed_offsets' in active

    models = '\n'.join(line for line in lib.pdk_lib('tt').splitlines()
                       if not line.startswith(('.lib ', '.endl ')))
    deck = ['* Static source/load metrology of two physical hidden threshold networks.',
            '* f1/f2 are low-impedance differential test sources. They draw no DC current from REF.',
            '* Matched E followers q=p draw their output current from ground.',
            models, f'.include "{lib.STD}"',
            '.param VDD=1.8 VREF=.9 VUNIT=.1 CORE_SCALE=1 TAU_R=6.5meg STATE_C=6.5p MODEL_TAU=43.5u',
            '.param ACT_SLOPE=11.5 ACT_LIMIT=.99', '.temp 27',
            '.options method=gear maxord=2 reltol=3e-5 abstol=3e-13 vntol=3e-8 gmin=1e-15 pivrel=.1',
            *cells.values(), 'VDD vdd 0 PWL(0 0 .1u 0 4u 1.8)',
            'VAZ az 0 PWL(0 0 .2u 0 .205u 1.8 32u 1.8 32.005u 0)',
            'Vrawinput source_input 0 PWL(0 0 .1u 0 4u .9)',
            f'XREF vdd 0 vbn raw2 raw1 ref az 0 0 sel1 source_input sel2 source_input{connections} {reference}']
    if mode == 'stiff':
        deck += ['Xainv az az_b vdd 0 cmos_inv',
                 'Xth1 tap1 fixed1 fixed1 az az_b ref vdd 0 cd_ref_az COMP=1.2p DRIVE=1 RZERO=5k HEADROOM=1',
                 'Xth2 tap2 fixed2 fixed2 az az_b ref vdd 0 cd_ref_az COMP=1.2p DRIVE=1 RZERO=5k HEADROOM=1']
    if rail_mode:
        deck += ['XSTATIC ref fixed1 fixed2 tail1 tail2 vdd 0 native_fixed_offsets',
                 'Eview1 tap1 0 xref.d1_tap 0 1', 'Eview2 tap2 0 xref.d0_tap 0 1']

    for j in (1, 2):
        idx = str(j)
        tap_branch = 'tap' if mode == 'direct' else 'fixed'
        deck.append(f'XH{j}BIAS raw{j} {tap_branch}{j} vdd h{j}bias vdd 0 ext_bias_switch')
        if not rail_mode:
            deck.append(f'Runused{j} tail{j} 0 1e18')
        deck += [f'Vbias{j} pb{j} p{j} 0', f'Vtail{j} p{j} tail{j} 0',
                 f'E_q{j} q{j} 0 p{j} 0 1', f'E_ref_f{j} fcom{j} 0 ref 0 1']
        signals = {'y': 'f'+idx, 'p': 'p'+idx, 'bpin': 'h'+idx+'bias',
                   'q': 'q'+idx, 'ref': 'ref', 'vss': '0'}
        for label in ('XR3', 'XR4', 'XR5', 'XR7'):
            line = next(x for x in original.splitlines() if x.startswith(label+' ')).split()
            net0, net1, bulk = [signals[key] for key in line[1:4]]
            if label == 'XR3':
                net1 = 'pb'+idx
            value = line[5].replace('{100k/(1+DPROG)}', '{100k/(1+.5)}')
            deck.append(' '.join((label+'_'+idx, net0, net1, bulk, line[4], value)))
        deck += [f'XNH{j} f{j} p{j} q{j} unused{j} qs{j} dn{j} vdd 0 pw4_nrn_h',
                 f'XUE{j} qs{j} ref dn{j} 0 pw4_units3d',
                 f'XEXTRA{j} f{j} p{j} q{j} ref vdd 0 native_hidden_feedback']
        knots = [(0., 0.)]
        for i, row in enumerate(ORDER):
            t = 250 + 160 * i
            value = row[j-1]/1000
            if knots[-1][1] != value:
                knots.extend(((t-.025, knots[-1][1]), (t+.025, value)))
        deck.append(f'Vf{j} f{j} fcom{j} '+pwl(knots))

    stop = 250 + 160 * len(ORDER)
    vectors = ' '.join(VECTORS)
    deck += [f'.tran .10u {stop}u 0 .10u', '.control', 'set wr_singlescale',
             'set wr_vecnames', 'set numdgt=16', 'save '+vectors, 'run',
             'wrdata data.txt '+vectors, 'echo THRESHOLD_SWEEP_COMPLETE', 'quit', '.endc', '.end']
    text='\n'.join(deck)+'\n'
    corner=lib.CONDS[condition]
    if condition!='nominal':
        model_section='\n'.join(line for line in lib.pdk_lib(corner['corner']).splitlines()
                               if not line.startswith(('.lib ','.endl ')))
        supply=corner['vdd']
        for old,new in (
            (models, model_section),('.temp 27',f'.temp {corner["temp"]:g}'),
            ('.param VDD=1.8 VREF=.9 VUNIT=.1',f'.param VDD={supply:g} VREF={supply/2:g} VUNIT={supply/18:g}'),
            ('VDD vdd 0 PWL(0 0 .1u 0 4u 1.8)',f'VDD vdd 0 PWL(0 0 .1u 0 4u {supply:g})'),
            ('VAZ az 0 PWL(0 0 .2u 0 .205u 1.8 32u 1.8 32.005u 0)',f'VAZ az 0 PWL(0 0 .2u 0 .205u {supply:g} 32u {supply:g} 32.005u 0)'),
            ('Vrawinput source_input 0 PWL(0 0 .1u 0 4u .9)',f'Vrawinput source_input 0 PWL(0 0 .1u 0 4u {supply/2:g})')):
            assert text.count(old)==1,(old,text.count(old))
            text=text.replace(old,new)
    return text, dict(base_candidate_sha256=sha, physical_mode=mode, stop_us=stop,
        operating_condition=condition,process_temperature_supply=corner,
        fixture_only_replacement_series_ohm=([14065,44300] if mode=='trimmed' else []),
        prescribed_F1_F2_mV=ORDER, dwell_us=160, measurement_end_guard_us=2, measurement_aperture_us=16,
        saved_vectors=VECTORS, boundary='F1/F2 prescribed relative to buffered REF with a zero-input-current dependent source. q=p imposed; native R3/4/5/7 and all enabled feedback helpers, REF ladder and all three original REF-class amps are present. Raw buffer inputs fixed at 0.9 V.')


def measure(table, plan):
    t = table[0]*1e6
    assert np.isfinite(table).all() and t[-1] >= plan['stop_us']-.001
    waves = dict(zip(VECTORS, table[1:]))
    rows = []
    for i, f in enumerate(ORDER):
        end = 250 + 160*(i+1)-2
        clocks = np.linspace(end-16, end, 65)
        view = {name: np.interp(clocks, t, raw) for name, raw in waves.items()}
        avg = {name: float(np.mean(raw)) for name, raw in view.items()}
        ref = avg['v(ref)']
        ref_span = 1000*np.ptp(view['v(ref)'])
        actual_f = [1000*(avg[f'v(f{j})']-ref) for j in (1, 2)]
        np.testing.assert_allclose(actual_f, f, atol=1e-4)
        row = dict(f_mV=f, ref_V=ref, ref_aperture_pp_mV=ref_span,
                   actual_ref_tap_V=avg['v(xref.ref_tap)'], branches=[])
        for j in (1, 2):
            p = avg[f'v(p{j})']
            current = avg[f'i(vbias{j})']-avg[f'i(vtail{j})']
            # This ideal 5µS reference conversion is reported alongside the measured slope and true terminal currents.
            row['branches'].append(dict(p_V=p, ladder_tap_mV=1000*(avg[f'v(tap{j})']-ref),
                native_R3_farend_mV=1000*(avg[f'v(h{j}bias)']-ref),
                R3_into_p_uA=1e6*avg[f'i(vbias{j})'], parallel_p_to_VSS_uA=1e6*avg[f'i(vtail{j})'],
                net_bias_into_p_uA=1e6*current, effective_relative_mV_using_nominal_5uS=1000*(p-ref+current/5e-6)))
        rows.append(row)
    ref = np.array([row['ref_V'] for row in rows])
    summary = []
    for j in (0, 1):
        branch = [row['branches'][j] for row in rows]
        p = np.array([r['p_V'] for r in branch])
        bias_current = np.array([r['net_bias_into_p_uA'] for r in branch])
        # Physical conductances:  I_bias = (G_REF+G_GND)(REF-p) - G_GND REF.
        design = np.stack((ref-p, -ref), axis=1)
        g, *_ = np.linalg.lstsq(design, bias_current, rcond=None)
        fit = design @ g
        b_norm = np.array([r['effective_relative_mV_using_nominal_5uS'] for r in branch])
        ideal = -ref*([1/12,7/36][j])*1000
        summary.append(dict(port='H'+str(j+1), ideal_unloaded_relative_to_REF=('-REF/12','-7REF/36')[j],
            measured_bias_conductance_uS=float(g[0]), inferred_ground_conductance_uS=float(g[1]),
            effective_equivalent_conductance_fraction=float(g[1]/g[0]),
            fit_residual_nA_max=float(1000*np.max(abs(fit-bias_current))),
            effective_relative_range_mV_using_5uS=[float(b_norm.min()),float(b_norm.max())],
            deviation_from_native_ratio_mV_using_5uS=float(np.max(abs(b_norm-ideal))),
            effective_bias_at_nominal_ref_using_fitted_uS_mV=float(-900*g[1]/g[0])))
    return dict(ordinary_native_time_points=len(t), rows=rows, terminal_fit=summary,
                operating_ref_range_V=[float(ref.min()), float(ref.max())], ref_peak_to_peak_mV=float(1000*np.ptp(ref)),
                maximum_16us_REF_aperture_span_mV=float(max(row['ref_aperture_pp_mV'] for row in rows)),
                repeated_center_ref_span_mV=float(1000*np.ptp([r['ref_V'] for r in rows if r['f_mV']==(0,0)])))


def execute(mode,condition='nominal'):
    deck, plan = make(mode,condition)
    dest = EVIDENCE/mode if condition=='nominal' else EVIDENCE/'pvt'/condition/mode
    dest.mkdir(parents=True, exist_ok=True)
    if mode == 'rails' and not (EVIDENCE / 'source_c555.spice.gz').exists():
        data = (HERE.parent / 'circuit' / 'native_six.spice').read_bytes()
        assert digest(data) == RAILS
        (EVIDENCE / 'source_c555.spice.gz').write_bytes(gzip.compress(data, mtime=0))
    with tempfile.TemporaryDirectory(prefix='sx-native-threshold-') as tmp:
        w = Path(tmp)
        (w/'run.spice').write_text(deck)
        (w/'.spiceinit').write_text(lib.SPICEINIT)
        with (w/'solver.log').open('wb') as f:
            status = subprocess.run(['nice', '-n', '15', lib.NGSPICE, '-b', 'run.spice'], cwd=w,
                stdout=f, stderr=subprocess.STDOUT, env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
        log = (w/'solver.log').read_bytes()
        assert status.returncode == 0 and b'Timestep too small' not in log and b'THRESHOLD_SWEEP_COMPLETE' in log, log[-1900:]
        with (w/'data.txt').open('rb') as f:
            assert f.readline().decode().split() == ['time',*VECTORS]
            table = np.loadtxt(f).T
        result = measure(table, plan)
        result.update(input_deck_sha256=digest(deck.encode()), ascii_output_sha256=digest((w/'data.txt').read_bytes()))
        (dest/'plan.json').write_text(json.dumps(plan,indent=1)+'\n')
        (dest/'result.json').write_text(json.dumps(result,indent=1)+'\n')
        (dest/'run.spice.gz').write_bytes(gzip.compress(deck.encode(),mtime=0))
        (dest/'solver.log.gz').write_bytes(gzip.compress(log,mtime=0))
        np.savez_compressed(dest/'wave.npz', time_s=table[0], **dict(zip(VECTORS,table[1:])))
        print(mode, result['ref_peak_to_peak_mV'], result['terminal_fit'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('rails','trimmed','direct','stiff'), nargs='+')
    parser.add_argument('--condition', nargs='+', choices=('nominal','ss0','ff85'),default=['nominal'])
    args=parser.parse_args()
    for condition in args.condition:
        for mode in args.mode:
            execute(mode,condition)
