"""Shared harness of the v4 circuit study.

Everything is simulated with ngspice 45.2 on two netlists under ONE bench:
  - the accepted chip: `feasibility_20261107/floorplan/chip2x2/ref/aj_native_chip.spice` (bench + subcircuits, as committed),
  - v4: the same file with the chip instance replaced by `xor_chip_v4` (v4_netlist.py or, once drawn, the netlist of
    the native sheets in sheets/), four more pin sources, and the v4 subcircuits appended. Every accepted subcircuit is
    used as it stands.
A deck is prepared the way the accepted flow prepares one (feasibility_20261107/scripts/ai_runs.py `prepare`):
supply and output step set through the bench's own .param line, the "moderate" solver line
(reltol=1e-4 abstol=1e-12 vntol=1e-7 gear, the default Sparse matrix solver), `.temp`, `.options seed`, the PDK library
reduced to its one section, and the PDK's .spiceinit in the run folder.

Run folders: runs/<tag>/ (git-ignored). Nothing outside this folder is written.
"""
from __future__ import annotations

import gzip
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
X = HERE.parents[1]                                   # .../xor_sky130
ACCEPTED = X / 'feasibility_20261107' / 'floorplan' / 'chip2x2' / 'ref' / 'aj_native_chip.spice'
RUNS = HERE / 'runs'
BUILD = HERE / 'build'
RESULTS = HERE / 'results'
FIGS = HERE / 'figures'
# A frozen set's DRAWN chip in place of the schematic one (2026-11-15, DESIGN.md section 4 on the final set):
# PW_DRAWN=<flat run, e.g. r6_2019_std> makes every v4 deck use that set's `wired__chip` (wiredchip.py) and puts the
# runs, results, figures, the cluster stage and the remote folder under drawn/<run>/, so nothing of the schematic work
# is touched. Inputs a script reads from RESULTS must be put there first (drawn_setup.py).
DRAWN = os.environ.get('PW_DRAWN')
if DRAWN:
    RUNS, RESULTS, FIGS = (HERE / 'drawn' / DRAWN / x for x in ('runs', 'results', 'figures'))
PDK = os.environ.get('PDK_ROOT', str(Path.home() / '.ciel')) + '/sky130A'
STD = PDK + '/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice'
NGSPICE = os.environ.get('NGSPICE', str(Path.home() / '.local/opt/denseam-eda/20261105/root/usr/bin/ngspice'))
SPICEINIT = ('* Match the compatibility mode recommended by this installed SKY130 PDK.\n'
             'set ngbehavior=hsa\nset skywaterpdk\nset ng_nomodcheck\nset num_threads=1\n')

# The four conditions of round r4 without mismatch, and the cold slow one the kick test of the audit used.
CONDS = {
    'nominal': dict(corner='tt', temp=27.0, vdd=1.8),
    'sf0': dict(corner='sf', temp=0.0, vdd=1.71),       # fast NMOS, slow PMOS, 0 C, 1.71 V
    'fs50': dict(corner='fs', temp=50.0, vdd=1.89),     # slow NMOS, fast PMOS, 50 C, 1.89 V
    'ss50': dict(corner='ss', temp=50.0, vdd=1.71),
    'ss0': dict(corner='ss', temp=0.0, vdd=1.71),
    'ff0': dict(corner='ff', temp=0.0, vdd=1.89),
    # hot conditions with fast NMOS (where a native NMOS switch leaks most), for the drawing stage's item 3
    'ff50': dict(corner='ff', temp=50.0, vdd=1.89),
    'sf50': dict(corner='sf', temp=50.0, vdd=1.89),
    'sf50l': dict(corner='sf', temp=50.0, vdd=1.71),
    'ff85': dict(corner='ff', temp=85.0, vdd=1.89),
}

# Names of the nine network nodes: as the accepted bench records them -> as they are called in v4, where they are
# nets of the chip (ports of xor_network_v4) instead of internal nodes.
NODEMAP = {
    'xdut.xnet.f1': 'xdut.f1', 'xdut.xnet.f2': 'xdut.f2', 'xdut.xnet.z': 'xdut.z',
    'xdut.xnet.xh1.p': 'xdut.p1', 'xdut.xnet.xh1.q': 'xdut.q1',
    'xdut.xnet.xh2.p': 'xdut.p2', 'xdut.xnet.xh2.q': 'xdut.q2',
    'xdut.xnet.xz.p': 'xdut.pz', 'xdut.xnet.xz.q': 'xdut.qz',
    'xdut.xnet.xrw4.xdevice.net1': 'xdut.m1', 'xdut.xnet.xrw5.xdevice.net1': 'xdut.m2',     # the midpoints of the two edges
}
NEW_PINS = ('bias_prog', 'write', 'res_sel', 'weight_prog')       # uio[4], uio[5], uio[6], uio[7] (as the floorplan routed them)
STATES = ('h1', 'h2', 'hz')


def pdk_lib(corner: str, passive: str = 'res_typical__cap_typical') -> str:
    """One section of the SKY130 library by itself: the same lines as the accepted flow's copy."""
    ng = f'{PDK}/libs.tech/ngspice'
    base, mm = (corner[:-3], 1) if corner.endswith('_mm') else (corner, 0)       # tt_mm: the PDK's section with mismatch on
    return (f'* Section {corner} of {ng}/sky130.lib.spice by itself, include paths absolute.\n'
            f'.lib {corner}\n.param mc_mm_switch={mm}\n.param mc_pr_switch=0\n'
            f'.include "{ng}/corners/{base}.spice"\n'
            f'.include "{ng}/r+c/{passive}.spice"\n.include "{ng}/r+c/{passive}__lin.spice"\n'
            f'.include "{ng}/corners/{base}/specialized_cells.spice"\n.endl {corner}\n')


def pwl(points, scale=1.0) -> str:
    """PWL source text from (time, level) points; one point = DC. `scale` multiplies the levels (logic 0/1 -> volts)."""
    points = list(points)
    if len(points) == 1:
        return f'DC {points[0][1] * scale:.9g}'
    assert all(b[0] > a[0] for a, b in zip(points, points[1:])), points
    return 'PWL(' + ' '.join(f'{t:.12g} {v * scale:.9g}' for t, v in points) + ')'


def accepted_parts():
    """(bench, subcircuits) of the accepted native netlist."""
    text = ACCEPTED.read_text()
    i = text.index('* expanding   symbol:  xor_chip_staged.sym')
    return text[:i], text[i:]


def _sub(pattern, repl, text, count=1, flags=re.M):
    out, n = re.subn(pattern, repl, text, flags=flags)
    assert n == count, (pattern, n, count)
    return out


def map_nodes(text: str) -> str:
    """Accepted node names -> v4 node names (longest first; `xdut.xnet.z` must not eat `xdut.xnet.xz...`)."""
    for old in sorted(NODEMAP, key=len, reverse=True):
        text = re.sub(re.escape(old) + r'(?![\w.])', NODEMAP[old], text)
    return text


def deck(dut='accepted', cond='nominal', corner=None, temp=None, vdd=None, step='500n', stop=None, profile='moderate',
         seed=1, params=(), pins=None, dac=None, stim=None, extra_top='', saves=(), v4_subckts=None, body=None,
         options='', bench_edits=(), drawn_subckts=None):
    """A whole-chip deck on the accepted bench.

    dut        'accepted' or 'v4'
    pins       v4 only: {pin: 'float' | level 0/1 | [(t, level), ...]} for bias_prog, weight_prog, write, nudge
               (default: all four driven low). 'float' leaves the pin with no source (only the on-chip pull-down).
    dac        None: ua[1] as in the accepted bench (500 ohm to a 10 Mohm pull-down). Else [(t, volts), ...]: a source
               behind the bench's 500 ohm.
    stim       {source name: replacement line} for the bench's own sources (VA, VB, VRESET, VHOLD, VREFRESET, VDD_SRC ...)
    extra_top  lines added at the top level (accepted node names; mapped for v4)
    saves      more vectors to record (accepted names)
    body       replaces the bench's `run ... wrdata` block: ngspice commands between `set` lines and `quit`
    """
    c = dict(CONDS[cond])
    corner = corner or c['corner']; temp = c['temp'] if temp is None else temp; vdd = vdd or c['vdd']
    bench, subs = accepted_parts()
    for key, val in [('VDD', f'{vdd:g}'), ('TSTEP', step)] + [p.split('=', 1) for p in params]:
        bench = _sub(r'(^\.param[^\n]*?\b' + re.escape(key) + r'=)([^\s]+)', lambda m: m[1] + val, bench)
    if stop:
        bench = _sub(r'^\.tran \S+ \S+ .*$', f'.tran {step} {stop:.9g} 0 {step}', bench)
    if profile == 'moderate':
        bench = _sub(r'^\.options reltol=.*$', '.options reltol=1e-4 abstol=1e-12 vntol=1e-7 method=gear maxord=2 itl4=100', bench)
    else:
        assert profile == 'strict'                        # the bench's own line: reltol=1e-5 abstol=1e-13 vntol=1e-8 gear
    bench = bench.replace('.control', f'.temp {temp}\n.options seed={seed}\n{options}\n.control', 1)
    bench = _sub(r'^\.lib \S+ \w+$', f'.lib pdk.lib.spice {corner}', bench)
    for name, line in (stim or {}).items():
        bench = _sub(r'^' + re.escape(name) + r' [^\n]*(?:\n\+[^\n]*)*', lambda m: line, bench)
    for old, new in bench_edits:
        assert bench.count(old) == 1, old
        bench = bench.replace(old, new)
    if dac is not None:
        bench = _sub(r'^R_EXT_PULL ext_board 0 10Meg$', f'VDAC ext_board 0 {pwl(dac)}', bench)
        saves = tuple(saves) + ('i(VDAC)',)
    saves = tuple(saves) + ('v(xdut.ext_in)',)
    if saves:
        add = ' ' + ' '.join(saves)
        bench = _sub(r'^(\.save [^\n]*)$', lambda m: m[1] + add, bench)
        bench = _sub(r'^(wrdata xor_matched_tb\.dat [^\n]*)$', lambda m: m[1] + add, bench)
    bench = _sub(r'^write xor_matched_tb\.raw\n', '', bench)
    if body is not None:
        bench = _sub(r'^run\n.*?^(?=echo DEMO_COMPLETE)', lambda m: body.rstrip('\n') + '\n', bench, flags=re.M | re.S)
    top = extra_top.rstrip('\n') + '\n' if extra_top else ''
    if dut == 'v4':
        pins = dict({p: 0 for p in NEW_PINS}, **(pins or {}))
        new = []
        for p in NEW_PINS:
            v = pins[p]
            if isinstance(v, str):
                assert v == 'float'
                new.append(f'C_{p}_FLOAT {p} 0 20f')          # the wire from the pin, with nothing driving it
            else:
                new.append(f'V_{p} {p} 0 {pwl([(0, v)] if not isinstance(v, (list, tuple)) else v, vdd)}')
        bench = _sub(r'^(XDUT [^\n]*\n\+ [^\n]*?) xor_chip_staged (CORE_MATCH=1 READ_MATCH=1)$',
                     lambda m: m[1] + ' ' + ' '.join(NEW_PINS) + ' xor_chip_v4 ' + m[2] + '\n' + '\n'.join(new), bench)
        bench = map_nodes(bench)
        top = map_nodes(top)
        if DRAWN:
            # the drawn chip: its own subcircuits; every chip node named in the recording and in the added top-level
            # lines translated to its name in the flattened drawn chip (wiredchip.node; unchanged for nearly all)
            import wiredchip
            # an edited chip (a failure case, a variant) would be replaced by the drawn chip unedited, unseen: refuse
            if v4_subckts is not None and v4_subckts not in _plain_v4():
                raise ValueError('PW_DRAWN puts the drawn chip in place of the schematic one, so these edited v4 subcircuits '
                                 'would be dropped unseen: make the edit on the drawn chip (wiredchip.subckts) instead')
            # drawn_subckts: the drawn chip itself edited (drawn_edit.apply: a failure case on the drawn devices)
            v4_subckts = drawn_subckts if drawn_subckts is not None else wiredchip.subckts(DRAWN)[0]
            assert bench.count(' xor_chip_v4 ') == 1
            bench = bench.replace(' xor_chip_v4 ', ' wired__chip ')
            tr = lambda m: wiredchip.node(DRAWN, m[0])
            bench = re.sub(r'(?m)^(\.save |wrdata ).*$', lambda m: re.sub(r'xdut\.[\w.#]+', tr, m[0]), bench)
            top = re.sub(r'xdut\.[\w.#]+', tr, top)
        assert v4_subckts is not None
        assert drawn_subckts is None or DRAWN, 'drawn_subckts needs PW_DRAWN'
        subs = subs + '\n' + v4_subckts
    else:
        assert dut == 'accepted' and not pins
    if top:
        bench = bench.replace('**** end user architecture code', top + '**** end user architecture code', 1)
    return bench + subs + '\n.end\n'


_PLAIN = None


def _plain_v4():
    """The schematic chip unedited, revision 7 and revision 6: what drawn mode may stand in for."""
    global _PLAIN
    if _PLAIN is None:
        import v4_netlist as _N
        _PLAIN = (_N.subckts(), _N.subckts(damp_l=None))
    return _PLAIN


RECOVER = HERE / 'recovered_runs.json'       # {tag: why}: runs that failed with "timestep too small" and are run with the
#                                              accepted flow's recovery setting instead (pivot threshold 0.2 for 0.1)


def write_run(tag: str, text: str, corner: str, meta: dict | None = None, passive='res_typical__cap_typical') -> Path:
    d = RUNS / tag
    d.mkdir(parents=True, exist_ok=True)
    if RECOVER.exists() and tag in json.loads(RECOVER.read_text()):
        assert text.count('.options pivrel=0.1\n') == 1, tag
        text = text.replace('.options pivrel=0.1\n', '.options pivrel=0.2\n')
        meta = dict(meta or {}, recovery='pivot threshold 0.2')
    if (d / 'run.spice').exists() and (d / 'run.spice').read_text() == text and (d / 'pdk.lib.spice').exists() \
            and (d / 'pdk.lib.spice').read_text() == pdk_lib(corner, passive):
        return d                                   # the same deck: its results, if any, stay
    for f in list(d.glob('*.dat')) + list(d.glob('*.dat.gz')):
        f.unlink()
    (d / 'done.json').unlink(missing_ok=True)
    (d / '.spiceinit').write_text(SPICEINIT)
    (d / 'pdk.lib.spice').write_text(pdk_lib(corner, passive))
    (d / 'run.spice').write_text(text)
    (d / 'case.json').write_text(json.dumps(meta or {}, indent=1) + '\n')
    return d


RECOVERED = r'(?i)singular matrix|out of range for'       # the solver's first try at the operating point failed and a later one succeeded


def screen_log(text: str) -> list:
    """Fatal problems of a run's log. A recovered start-up warning is not one (see `warnings`): such a run is kept only if
    it finishes and passes the physical screen, as in the accepted flow (its run.json lists `recovered_solver_warnings`)."""
    bad = []
    if 'Compatibility modes selected: hs a' not in text:
        bad.append('PDK compatibility mode not selected')
    if 'DEMO_COMPLETE' not in text and 'V4_RUN_COMPLETE' not in text:
        bad.append('did not finish')
    bad += [l.strip()[:160] for l in text.splitlines()
            if re.search(r'(?i)\berror\b|timestep too small|no such vector', l) and not re.search(RECOVERED, l)][:6]
    return bad


def start_ok(tag: str) -> bool:
    """False if ngspice's search for the starting point failed its normal methods (gmin stepping) and the run began from
    elsewhere. Such a run completes and is wrong by 0.4 to 1.5 mV on every neuron (DESIGN.md D2): it is not used."""
    f = RUNS / tag / 'simulation.log'
    return f.exists() and 'gmin stepping failed' not in f.read_text(errors='replace')


def warnings(text: str) -> list:
    return [l.strip()[:160] for l in text.splitlines() if re.search(RECOVERED, l)][:6]


def run(tag: str, timeout=7200, force=False) -> dict:
    """One ngspice process in runs/<tag>/. Returns and stores {tag, ok, seconds, problems}."""
    d = RUNS / tag
    done = d / 'done.json'
    if done.exists() and not force:
        return json.loads(done.read_text())
    BUILD.mkdir(exist_ok=True)
    t0 = time.time()
    env = dict(os.environ, TMPDIR=str(BUILD))
    with (d / 'simulation.log').open('w') as log:
        p = subprocess.run([NGSPICE, '-b', 'run.spice'], cwd=d, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, env=env)
    bad = screen_log((d / 'simulation.log').read_text(errors='replace'))
    text = (d / 'simulation.log').read_text(errors='replace')
    r = dict(tag=tag, ok=not bad and p.returncode == 0, returncode=p.returncode, seconds=round(time.time() - t0, 1), problems=bad,
             recovered_warnings=warnings(text), where='the workstation')
    done.write_text(json.dumps(r, indent=1) + '\n')
    return r


def run_many(tags, workers=2, force=False):
    """At most two local processes (the machine is shared)."""
    with ThreadPoolExecutor(min(workers, 2)) as pool:
        out = list(pool.map(lambda t: run(t, force=force), tags))
    for r in out:
        if not r['ok']:
            print('NOT OK', r['tag'], r['problems'])
    return out


def has_table(folder, name='xor_matched_tb.dat') -> bool:
    """A run's table is there, plain or compressed (compress_all.py gzips finished tables in place)."""
    return (folder / name).exists() or (folder / (name + '.gz')).exists()


def read(tag: str, name='xor_matched_tb.dat') -> dict:
    """wrdata table -> {column: array}; v4's node names are turned back into the accepted bench's names."""
    path = RUNS / tag / name
    if not path.exists() and path.with_name(name + '.gz').exists():
        path = path.with_name(name + '.gz')         # compressed after scoring (compress_runs.py); same table
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as f:
        cols = [c.lower() for c in f.readline().split()]
    if DRAWN:      # a node the drawn deck recorded under its flattened name (wiredchip.node): back to the schematic's name
        cols = [re.sub(r'^v\((xdut\.[^)]*)\)$', lambda m: 'v(' + m[1].replace('__', '.') + ')', c) for c in cols]
    data = np.loadtxt(path, skiprows=1, ndmin=2)
    back = {f'v({v})': f'v({k})' for k, v in NODEMAP.items()}
    out = {}
    for i, c in enumerate(cols):
        c = back.get(c, c)
        if c not in out:
            out[c] = data[:, i]
    return out


def physical(d: dict, vdd: float, hold_s=1e-6, t_after=10e-6) -> dict:
    """The accepted screen (lean_score.physical): after power-up the supply source must never absorb more than 1 mA and
    no recorded chip node may sit more than 0.3 V outside the rails, for longer than 1 us at a stretch."""
    t = d['time']
    after = t > t_after

    def longest(mask):
        best, start = 0.0, None
        for k in np.flatnonzero(np.diff(np.r_[0, mask.astype(int), 0])):
            if start is None:
                start = k
            else:
                best = max(best, t[min(k, len(t) - 1)] - t[start]); start = None
        return float(best)
    bad = {}
    if 'i(vdd_src)' in d:
        back = longest(after & (d['i(vdd_src)'] > 1e-3))
        if back >= hold_s:
            bad['supply absorbing current'] = back
    for k, v in d.items():
        if k.startswith('v(xdut.') or k in ('v(pad)', 'v(out)'):
            out = longest(after & ((v > vdd + 0.3) | (v < -0.3)))
            if out >= hold_s:
                bad[k] = out
    return bad


def state(d: dict, name: str) -> np.ndarray:
    """A chip node minus REF, in volts."""
    return d[f'v(xdut.xnet.{name})'] - d['v(xdut.ref)']


def compare(a: dict, b: dict, names=STATES, t0=0.0, t1=None, grid=100e-9, exclude=()):
    """Largest |a - b| of each state (node minus REF) on a common time grid, in mV, with the time it occurs.
    exclude: (t_from, t_to) stretches left out."""
    t1 = min(a['time'][-1], b['time'][-1]) if t1 is None else t1
    t = np.arange(t0, t1, grid)
    keep = np.ones(len(t), bool)
    for lo, hi in exclude:
        keep &= ~((t >= lo) & (t <= hi))
    out = {}
    for n in names:
        da = np.interp(t, a['time'], state(a, n)) - np.interp(t, b['time'], state(b, n))
        k = int(np.argmax(abs(da) * keep))
        out[n] = dict(max_mV=float(abs(da[k]) * 1e3), at_us=float(t[k] * 1e6), signed_mV=float(da[k] * 1e3))
    return out


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1) + '\n')


# ---------------------------------------------------------------------------------------------- the cluster
REMOTE = os.environ.get('CLUSTER_HOME', '$CLUSTER_HOME') + '/eda/runs/pw4_circuit'
R_PDK = os.environ.get('CLUSTER_HOME', '$CLUSTER_HOME') + '/eda/pdk/sky130_792ef67/sky130A'
R_STD = os.environ.get('CLUSTER_HOME', '$CLUSTER_HOME') + '/eda/runs/ah_amp_layout/pdk_extra/sky130_fd_sc_hd.spice'   # the copy the accepted flow put there
R_NG = os.environ.get('CLUSTER_HOME', '$CLUSTER_HOME') + '/eda/ngspice-45.2-debian/bin/ngspice-run'
STAGE = BUILD / 'cluster'
if DRAWN:                                       # the drawn chip's runs keep their own stage and remote folder
    REMOTE = REMOTE + '/drawn/' + DRAWN
    STAGE = HERE / 'drawn' / DRAWN / 'stage'


# Written at the first failure of the shared connection itself (ssh's own exit code 255, or the connection closed).
# From then on no command here contacts the cluster until the file is removed, so a waiting loop that calls status() again
# and again cannot keep trying a broken connection (the workstation's rules: never retry it; run cluster-connect once).
DOWN = HERE / 'build' / 'CLUSTER_DOWN'


def _remote(cmd):
    return cmd.startswith(('ssh cluster', 'rsync ')) and 'cluster' in cmd


def _sh(cmd, **kw):
    if _remote(cmd) and DOWN.exists():
        raise SystemExit(f'the cluster connection was found down ({DOWN.read_text().strip()[:200]}); not trying again: {cmd[:120]}')
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
        if _remote(cmd) and (r.returncode == 255 or any(s in r.stderr for s in ('Connection closed', 'port 65535', 'connection unexpectedly closed'))):
            DOWN.parent.mkdir(parents=True, exist_ok=True)
            DOWN.write_text(f'{time.strftime("%Y-%m-%d %H:%M:%S")} exit {r.returncode}: {r.stderr.strip()[-300:]}\n')
        raise SystemExit(f'failed: {cmd[:200]}')          # one failure stops the script: no retries on the shared connection
    return r.stdout


def push(name, tags, hours=2, mem='6G', limit=16, partitions='partition,partition,partition'):
    """Copy the decks of `tags` (PDK paths rewritten) and submit one array job. One core per task."""
    for tag in tags:
        d = STAGE / tag
        d.mkdir(parents=True, exist_ok=True)
        for f in ('run.spice', 'pdk.lib.spice', '.spiceinit'):
            text = (RUNS / tag / f).read_text()
            text = text.replace(STD, R_STD).replace(PDK, R_PDK)
            live = '\n'.join(l for l in text.splitlines() if not l.startswith('*'))
            assert '$HOME/' not in live, (tag, f)
            (d / f).write_text(text)
    script = f"""#!/bin/bash
#SBATCH -J pw4c
#SBATCH -p {partitions}
#SBATCH -c 1
#SBATCH --mem={mem}
#SBATCH -t {hours:02d}:00:00
#SBATCH -a 0-{len(tags) - 1}%{limit}
#SBATCH -o {REMOTE}/slurm_{name}_%A_%a.out
TAGS=({' '.join(tags)})
TAG=${{TAGS[$SLURM_ARRAY_TASK_ID]}}
cd {REMOTE}/$TAG || exit 2
rm -f exit_code cluster_done.json *.dat *.raw
START=$(date +%s)
{R_NG} -b run.spice > simulation.log 2>&1
echo $? > exit_code
echo "{{\\"seconds\\": $(( $(date +%s) - START )), \\"node\\": \\"$(hostname)\\"}}" > cluster_done.json
"""
    (STAGE / f'submit_{name}.sh').write_text(script)
    (STAGE / f'tags_{name}.json').write_text(json.dumps(tags))
    if 'MISSING' in _sh(f'ssh cluster "mkdir -p {REMOTE}; test -s {R_STD} || echo MISSING"'):
        raise SystemExit(f'the standard-cell models are not on the cluster at {R_STD}')
    # a resubmitted run's remote folder may still hold the previous attempt's results (a pull keeps the folders of runs
    # that failed): remove them before submitting, so that neither `status` nor `pull` can see them
    _sh(f'ssh cluster "cd {REMOTE} && for t in ' + ' '.join(tags) + '; do rm -f $t/exit_code $t/cluster_done.json $t/*.dat $t/*.raw $t/simulation.log; done"')
    _sh(f"rsync -a {' '.join(str(STAGE / t) for t in tags)} {STAGE / f'submit_{name}.sh'} cluster:{REMOTE}/")
    out = _sh(f'ssh cluster "cd {REMOTE} && sbatch submit_{name}.sh"')
    job = re.search(r'(\d+)', out)[1]
    (STAGE / f'job_{name}.txt').write_text(job)
    print('submitted', job, len(tags), 'tasks')
    return job


def status(name):
    job = (STAGE / f'job_{name}.txt').read_text().strip()
    tags = json.loads((STAGE / f'tags_{name}.json').read_text())
    out = _sh(f'ssh cluster "squeue -h -j {job} -o %T | sort | uniq -c; cd {REMOTE} && ls ' + ' '.join(f'{t}/exit_code' for t in tags) + ' 2>/dev/null | wc -l"')
    lines = out.strip().splitlines()
    print(' / '.join(l.strip() for l in lines[:-1]) or 'no task queued or running', '|', lines[-1].strip(), 'of', len(tags), 'finished')
    return int(lines[-1]) == len(tags) and len(lines) == 1          # every result there and nothing of the job queued


def pull(name, clean=True):
    """Fetch tables and logs into runs/<tag>/, then delete the remote copies (the account's quota is nearly full)."""
    tags = json.loads((STAGE / f'tags_{name}.json').read_text())
    inc = "--include='*/' --include='*.dat' --include='simulation.log' --include='exit_code' --include='cluster_done.json' --exclude='*'"
    _sh(f"rsync -a {inc} " + ' '.join(f'cluster:{REMOTE}/{t}' for t in tags) + f' {RUNS}/')
    bad = []
    for t in tags:
        d = RUNS / t
        log = (d / 'simulation.log').read_text(errors='replace') if (d / 'simulation.log').exists() else ''
        secs = json.loads((d / 'cluster_done.json').read_text())['seconds'] if (d / 'cluster_done.json').exists() else None
        code = (d / 'exit_code').read_text().strip() if (d / 'exit_code').exists() else None
        problems = screen_log(log)
        r = dict(tag=t, ok=not problems and code == '0', returncode=code, seconds=secs, problems=problems, recovered_warnings=warnings(log), where='cluster')
        (d / 'done.json').write_text(json.dumps(r, indent=1) + '\n')
        if not r['ok']:
            bad.append((t, problems))
    if clean and not bad:
        _sh(f'ssh cluster "cd {REMOTE} && rm -rf ' + ' '.join(tags) + f' slurm_{name}_*.out submit_{name}.sh"')
    print('pulled', len(tags), 'not ok:', bad)
    return bad
