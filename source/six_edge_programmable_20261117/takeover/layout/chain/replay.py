#!/usr/bin/env python3
"""Rebuild the layout chain of the selected six-weight mask (bbf78759) from a clean, sparse git worktree of `main`.

Creates ~/.cache/six-chain-replay (detached, sparse on hardware/mesa/xor_sky130), runs the base flow's own scripts there
unchanged, the way their READMEs say (`-B`, from the directory they expect), each command under strace so that every
file it opens is recorded, compares every output with the archive stored in the repository, writes replay.json beside
this file, copies gzipped logs and traces to ../runs/chain/<step>/, and removes the worktree.

  $DESIGN_REPO/.venv/bin/python -I replay.py [--commit main] [--steps id,id] [--keep-worktree]
                                                             [--replace-worktree]

Unattended; about 13 minutes on this machine, one process at a time. Needs strace, Magic 8.3.685 and netgen 1.5.325
in ~/.local/bin, KLayout's Python in ~/.local/opt/klayout-py, g++, /usr/bin/python3 and the PDK at ~/.ciel/sky130A.
Writes only in this folder, in ../runs/chain/ and inside the worktree."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

HOME = Path.home()
CHAIN = Path(__file__).resolve().parent
RUNS = CHAIN.parent / 'runs' / 'chain'
WT = HOME / '.cache' / 'six-chain-replay'
X = 'hardware/mesa/xor_sky130'
SIX = X + '/six_edge_programmable_20261117'
NE = SIX + '/native_edges'
L = NE + '/layout'
B = L + '/build'
R = L + '/results'
EV = NE + '/verification/evidence'
KPY = HOME / '.local/opt/klayout-py/bin/python'
SYSPY = Path('/usr/bin/python3')
TRACE = 'trace=openat,open,creat,execve,mkdir,mkdirat,rename,renameat,renameat2'
# Variables that would redirect the base flow's scripts to other tools, PDKs or build areas.
SCRUB = ('MAGIC', 'NETGEN', 'KLAYOUT', 'KLAYOUT_PY', 'KLAYOUT_PYTHON', 'SKY130A', 'PDK_ROOT', 'PDK', 'V4_AREA',
         'V4_PLAN', 'PYTHONPATH', 'PYTHONHOME', 'TT_DRC_DIR')


# Steps in run order: the last step of the chain first, then backwards. b411c500 runs before 313444d1 because the
# latter's commands read build files written by the former's; the placement runs before the c555 and selector steps
# for the same reason (build/targets.json, build/reference.spice).
STEPS = [
    dict(id='bbf78759', parent='5c5dfd43 (EV/layout_5c5dfd43_reference_reservoir/die.gds.gz)',  mask='bbf78759', title='Gate capacitor (8.97 um MIM) on weak_b: the selected mask',
         doc=f'{SIX}/takeover/README.md; {NE}/verification/filter_reservoir_rebuild.py',
         cwd=f'{NE}/verification',
         commands=[['{PPY}', '-B', 'filter_reservoir_rebuild.py', 'evidence/layout_bbf78759_gate_p897', '{work}']],
         product='{work}/chip_fill', archive=f'{EV}/layout_bbf78759_gate_p897',
         pairs=[('{work}/placement.json', f'{EV}/layout_bbf78759_gate_p897/placement.json'),
                ('{work}/chip_tracks.json', f'{EV}/layout_bbf78759_gate_p897/routing.json'),
                ('{work}/reference.spice', f'{EV}/layout_bbf78759_gate_p897/reference.spice.gz')]),
    dict(id='5c5dfd43', parent='5dd21c71 (EV/layout_5dd21c71_pad_escape/die.gds.gz)',  mask='5c5dfd43', title='Two 15.7 um reference-reservoir MIMs on REF',
         doc=f'{EV}/layout_5c5dfd43_reference_reservoir/README.md; filter_reservoir_rebuild.py',
         cwd=f'{NE}/verification',
         commands=[['{PPY}', '-B', 'filter_reservoir_rebuild.py', 'evidence/layout_5c5dfd43_reference_reservoir',
                    '{work}']],
         product='{work}/chip_fill', archive=f'{EV}/layout_5c5dfd43_reference_reservoir',
         pairs=[('{work}/placement.json', f'{EV}/layout_5c5dfd43_reference_reservoir/placement.json'),
                ('{work}/chip_tracks.json', f'{EV}/layout_5c5dfd43_reference_reservoir/routing.json'),
                ('{work}/reference.spice', f'{EV}/layout_5c5dfd43_reference_reservoir/reference.spice.gz')]),
    dict(id='5dd21c71', parent='d6e87b40 (EV/layout_d6e87b40_at_driver/die.gds.gz)',  mask='5dd21c71', title='Package-side filter lead rerouted (pad escape)',
         doc=f'{NE}/verification/filter_source_rebuild.py --at-pad',
         cwd=f'{NE}/verification',
         commands=[['{PPY}', '-B', 'filter_source_rebuild.py', '--at-pad', '--scratch', '{work}']],
         product='{work}/near_pad_filled', archive=f'{EV}/layout_5dd21c71_pad_escape', pairs=[]),
    dict(id='d6e87b40', parent='1b2984a3 (results/res_hold_provisional/die.gds.gz) as the die; the two RC macros copied from 313444d1 (results/quiet_rc_release/die.gds.gz)',  mask='d6e87b40', title='Filter passives moved next to their drivers (at driver)',
         doc=f'{NE}/verification/filter_source_rebuild.py',
         cwd=f'{NE}/verification',
         commands=[['{PPY}', '-B', 'filter_source_rebuild.py', '--scratch', '{work}']],
         product='{work}/at_source_balanced', archive=f'{EV}/layout_d6e87b40_at_driver', pairs=[]),
    dict(id='b411c500', parent='1b2984a3 (results/res_hold_provisional/die.gds.gz)',  mask='b411c500', title='Drawn control-line RC filter (first drawing)',
         doc=f'{L}/hold_mode/README.md, "Drawn control-line filter" (without --archive)',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_passives.py', 'generate'],
                   ['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_layout.py', 'place'],
                   ['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_layout.py', 'route'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'quiet_rc_routed', '--negative', '--schematic',
                    'native_edges/layout/build/quiet_rc_cells/circuit.spice'],
                   ['{KPY}', '-B', 'native_edges/layout/repair.py', 'quiet_rc_routed', 'quiet_rc_preheal', '--fill',
                    '--targets', 'quiet_rc_targets.json'],
                   ['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_layout.py', 'finish'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'quiet_rc_healed', '--negative', '--schematic',
                    'native_edges/layout/build/quiet_rc_cells/circuit.spice'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'quiet_rc_healed', '--schematic',
                    'native_edges/layout/build/quiet_rc_cells/circuit.spice', '--unit-mim',
                    'native_edges/layout/build/quiet_rc_cells/ne_rc_mim.spice']],
         product=f'{B}/quiet_rc_healed', archive=f'{R}/quiet_rc_provisional',
         pairs=[(f'{B}/quiet_rc_placement.json', f'{R}/quiet_rc_provisional/placement.json'),
                (f'{B}/quiet_rc_routed.json', f'{R}/quiet_rc_provisional/routing.json'),
                (f'{B}/quiet_rc_cells/bank.json', f'{R}/quiet_rc_provisional/resistor_bank.json'),
                (f'{B}/quiet_rc_cells/isolated.json', f'{R}/quiet_rc_provisional/filter_cells.json'),
                (f'{B}/quiet_rc_cells/ne_rc_mim.spice', f'{R}/quiet_rc_provisional/mim_unit.spice')]),
    dict(id='313444d1', parent='b411c500 (results/quiet_rc_provisional/die.gds.gz) and build files of step b411c500',  mask='313444d1', title='Antenna and implant repair of the RC filter (release)',
         doc=f'{L}/hold_mode/README.md, "Antenna and implant repair" (without --archive)',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_release.py', 'prepare'],
                   ['{KPY}', '-B', 'native_edges/layout/hold_mode/rc_release.py', 'route'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'quiet_rc_release_routed', '--negative',
                    '--schematic', 'native_edges/layout/build/quiet_rc_cells/circuit.spice'],
                   ['{KPY}', '-B', 'native_edges/layout/repair.py', 'quiet_rc_release_routed', 'quiet_rc_release',
                    '--fill', '--targets', 'quiet_rc_targets.json'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'quiet_rc_release', '--negative',
                    '--schematic', 'native_edges/layout/build/quiet_rc_cells/circuit.spice'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'quiet_rc_release', '--schematic',
                    'native_edges/layout/build/quiet_rc_cells/circuit.spice', '--unit-mim',
                    'native_edges/layout/build/quiet_rc_cells/ne_rc_mim.spice']],
         product=f'{B}/quiet_rc_release', archive=f'{R}/quiet_rc_release',
         pairs=[(f'{B}/quiet_rc_release_routed.json', f'{R}/quiet_rc_release/routing.json'),
                (f'{B}/quiet_rc_placement.json', f'{R}/quiet_rc_release/placement.json'),
                (f'{B}/quiet_rc_cells/bank.json', f'{R}/quiet_rc_release/resistor_bank.json'),
                (f'{B}/quiet_rc_cells/isolated.json', f'{R}/quiet_rc_release/filter_cells.json'),
                (f'{B}/quiet_rc_cells/ne_rc_mim.spice', f'{R}/quiet_rc_release/mim_unit.spice')]),
    dict(id='1b2984a3', parent='2ff6bb34 (results/selector8_signoff/die.gds.gz)',  mask='1b2984a3', title='Mode-qualified HOLD switches and their logic (res_hold)',
         doc=f'{L}/hold_mode/README.md, "Independent mode-qualified hold" (without --archive)',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/hold_mode/res_select.py', '--place'],
                   ['{KPY}', '-B', 'native_edges/layout/route.py', '--source', 'res_hold_base', '--out',
                    'res_hold_routed', '--targets', 'res_hold_targets.json', '--pitch', '220', '--offset', '110',
                    '--priority', 'H1,H2,Z,weak,weak_b,res_sel,six,ref,vdd,vss'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'res_hold_routed', '--negative', '--schematic',
                    'native_edges/layout/build/hold_mode/res_select.spice'],
                   ['{KPY}', '-B', 'native_edges/layout/repair.py', 'res_hold_routed', 'res_hold_heal', '--fill',
                    '--targets', 'res_hold_targets.json'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'res_hold_heal', '--negative', '--schematic',
                    'native_edges/layout/build/hold_mode/res_select.spice'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'res_hold_heal', '--schematic',
                    'native_edges/layout/build/hold_mode/res_select.spice']],
         product=f'{B}/res_hold_heal', archive=f'{R}/res_hold_provisional', pairs=[]),
    dict(id='placement', parent='frozen two-weight chip 4161a936 (V4/explainer/site_static/evidence/layout.gds.gz) and the accepted cells under feasibility_20261107',  mask='6864c5c6', title='Unrouted placement of the frozen chip\'s macros and the new cells',
         doc=f'{L}/README.md, "Reproduction" (first block)',
         cwd=SIX,
         commands=[['{SYSPY}', '-B', 'native_edges/layout/resistors.py'],
                   ['{KPY}', '-B', 'native_edges/layout/source.py'],
                   ['{SYSPY}', '-B', 'native_edges/layout/floorplan.py', '--aligned', '--seed', '1186', '--trials',
                    '300'],
                   ['{KPY}', '-B', 'native_edges/layout/draw.py'],
                   ['{KPY}', '-B', 'native_edges/layout/check_decoder.py'],
                   ['{KPY}', '-B', 'native_edges/layout/targets.py'],
                   ['{KPY}', '-B', 'native_edges/layout/access.py'],
                   ['{PPY}', '-B', 'native_edges/layout/reference.py']],
         product=f'{B}/native_edges_placement', archive=None,
         stored_gds=f'{R}/native_edges_placement.gds.gz',
         pairs=[(f'{B}/placement.json', f'{R}/placement.json#floorplan')]),
    dict(id='c555_intermediate', parent='placement 6864c5c6 (results/native_edges_placement.gds.gz) plus the stored top-level metal results/c555_intermediate/parent_metal.json.gz',  mask='39e84fe3', title='First routed six-weight die (stored metal on the placement)',
         doc=f'{L}/README.md, "Reproduction" (second block)',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/stream.py', 'c555_intermediate', '--out',
                    'native_edges/layout/build/replay.gds'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'replay', '--negative'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'replay']],
         product=f'{B}/replay', archive=f'{R}/c555_intermediate', pairs=[]),
    dict(id='c555_signoff', parent='placement 6864c5c6 (results/native_edges_placement.gds.gz) plus the stored top-level metal results/c555_signoff/parent_metal.json.gz',  mask='963630e8', title='Signed-off c555 die (stored metal on the placement)',
         doc=f'{L}/README.md, "Regenerating physical signoff"',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/stream.py', 'c555_signoff', '--out',
                    'native_edges/layout/build/release.gds'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'release', '--negative'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'release']],
         product=f'{B}/release', archive=f'{R}/c555_signoff', pairs=[]),
    dict(id='selector8', parent='963630e8 (build/release.gds of step c555_signoff) plus the stored top-level metal results/selector8_signoff/parent_metal.json.gz',  mask='2ff6bb34', title='Eight-finger selector cells on the c555 die (stored metal)',
         doc=f'{L}/README.md, "Reproducing the repaired selector mask"',
         cwd=SIX,
         commands=[['{PPY}', '-B', 'native_edges/layout/physical_selector.py', 'ne_return'],
                   ['{PPY}', '-B', 'native_edges/layout/physical_selector.py', 'ne_threshold8'],
                   ['{KPY}', '-B', 'native_edges/layout/selector_chip.py', '--fingers', '8'],
                   ['{KPY}', '-B', 'native_edges/layout/stream.py', 'selector8_signoff', '--template',
                    'native_edges/layout/build/selector8_base.gds', '--out',
                    'native_edges/layout/build/selector8_release.gds'],
                   ['{PPY}', '-B', 'native_edges/circuit/selector_revision.py', '--fingers', '8',
                    'native_edges/layout/build/selector8.spice'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'selector8_release', '--negative', '--schematic',
                    'native_edges/layout/build/selector8.spice'],
                   ['{PPY}', '-B', 'native_edges/layout/extract.py', 'selector8_release', '--schematic',
                    'native_edges/layout/build/selector8.spice']],
         product=f'{B}/selector8_release', archive=f'{R}/selector8_signoff',
         keep=[f'{B}/selector8_release.gds'],
         pairs=[(f'{B}/selector_cells/ne_return/ne_return.gds', f'{R}/selector_cells/ne_return/ne_return.gds.gz'),
                (f'{B}/selector_cells/ne_return/actual.spice', f'{R}/selector_cells/ne_return/actual.spice'),
                (f'{B}/selector_cells/ne_return/measurement.json', f'{R}/selector_cells/ne_return/measurement.json'),
                (f'{B}/selector_cells/ne_threshold8/ne_threshold8.gds',
                 f'{R}/selector_cells/ne_threshold8/ne_threshold8.gds.gz'),
                (f'{B}/selector_cells/ne_threshold8/actual.spice', f'{R}/selector_cells/ne_threshold8/actual.spice'),
                (f'{B}/selector_cells/ne_threshold8/measurement.json',
                 f'{R}/selector_cells/ne_threshold8/measurement.json')]),
    dict(id='selector8_route', parent='selector8_base.gds of step selector8 (from 963630e8), routed again',  mask='2ff6bb34', title='Selector8 routing re-run by the router (arguments inferred)',
         doc='not documented; grid 200/100 and net priority "park" inferred from the base flow\'s own route log and segment '
             'coordinates in its (git-ignored) build folder',
         cwd=SIX,
         commands=[['{KPY}', '-B', 'native_edges/layout/route.py', '--source', 'selector8_base', '--out',
                    'selector8_routed', '--targets', 'selector8_targets.json', '--pitch', '200', '--offset', '100',
                    '--priority', 'park'],
                   ['{PPY}', '-B', 'native_edges/layout/check_die.py', 'selector8_routed', '--negative', '--schematic',
                    'native_edges/layout/build/selector8.spice'],
                   ['{KPY}', '-B', 'native_edges/layout/repair.py', 'selector8_routed', 'selector8_heal', '--fill',
                    '--targets', 'selector8_targets.json'],
                   ['{KPY}', '-B', 'native_edges/layout/selector_chip.py', '--close']],
         product=f'{B}/selector8_release', archive=None, stored_gds=f'{R}/selector8_signoff/die.gds.gz',
         extra_gds=[(f'{B}/selector8_routed.gds', f'{R}/selector8_sample/die.gds.gz')], pairs=[]),
]


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout.strip()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def content(path):
    data = Path(path).read_bytes()
    return gzip.decompress(data) if data[:2] == b'\x1f\x8b' else data


def sha_file(path):
    try:
        return sha_bytes(Path(path).read_bytes())
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None


# ------------------------------------------------------------------ file-access traces
OPEN = re.compile(r'^(\d+)\s+(openat|open|creat)\((.*)\)\s+=\s+(\d+)<(.*)>$')
MKDIR = re.compile(r'^(\d+)\s+(mkdir|mkdirat)\((?:(?:AT_FDCWD|\d+)<([^>]*)>, )?"([^"]*)"')
RENAME = re.compile(r'^(\d+)\s+(rename|renameat|renameat2)\((?:(?:AT_FDCWD|\d+)<([^>]*)>, )?"([^"]*)", '
                    r'(?:(?:AT_FDCWD|\d+)<([^>]*)>, )?"([^"]*)"')
EXEC = re.compile(r'^(\d+)\s+execve\("([^"]+)"')
SYSTEM = ('/proc/', '/sys/', '/dev/', '/etc/', '/usr/', '/lib', '/run/', '/var/', '/snap/', '/tmp/', 'pipe:', 'socket:',
          'anon_inode:')


def parse_traces(paths, cwd):
    """Files the step read before (or without) writing them, files it wrote, directories it made, programs run."""
    reads, writes, made, execs, n = {}, {}, set(), set(), 0
    for path in paths:
        for line in Path(path).read_text(errors='replace').splitlines():
            n += 1
            m = OPEN.match(line)
            if m:
                args, target = m.group(3), m.group(5)
                if 'O_DIRECTORY' in args or target.startswith(SYSTEM):
                    continue
                writing = m.group(2) == 'creat' or any(f in args for f in ('O_WRONLY', 'O_RDWR', 'O_CREAT', 'O_TRUNC',
                                                                            'O_APPEND'))
                (writes if writing else reads).setdefault(target, n)
                continue
            m = MKDIR.match(line)
            if m and line.rstrip().endswith('= 0'):
                made.add(os.path.normpath(os.path.join(m.group(3) or str(cwd), m.group(4))))
                continue
            m = RENAME.match(line)
            if m and line.rstrip().endswith('= 0'):
                new = os.path.normpath(os.path.join(m.group(5) or m.group(3) or str(cwd), m.group(6)))
                writes.setdefault(new, n)
                continue
            m = EXEC.match(line)
            if m:
                execs.add(m.group(2))
    inputs = sorted(p for p, order in reads.items()
                    if not (p in writes and writes[p] < order) and p not in made and not os.path.isdir(p))
    return inputs, sorted(writes), sorted(execs)


GROUPS = [('PDK', str(HOME / '.ciel') + '/'), ('KLayout Python', str(HOME / '.local/opt/klayout-py') + '/'),
          ('Magic', str(HOME / '.local/opt/magic-')), ('netgen', str(HOME / '.local/opt/netgen-')),
          ('Tcl library used by Magic and netgen', str(HOME / '.local/opt/xschem-build-deps') + '/'),
          ('tool wrappers', str(HOME / '.local/bin') + '/'), ('uv-managed CPython', str(HOME / '.local/share/uv') + '/')]


def classify(inputs, tracked, writers, venv):
    repo, outside, summaries = [], [], {}
    root = str(WT) + '/'
    for p in inputs:
        if p.startswith(root):
            rel = p[len(root):]
            if rel.startswith('replay_work/'):
                continue
            entry = dict(path=rel, sha256=sha_file(p), in_git=rel in tracked)
            if not entry['in_git']:
                entry['written_by_step'] = writers.get(p)
            entry['kind'] = 'code' if rel.endswith(('.py', '.cpp', '.c', '.sh')) else 'data'
            repo.append(entry)
            continue
        group = next((g for g, prefix in GROUPS if p.startswith(prefix)), None)
        if group is None and p.startswith(str(venv) + '/'):
            group = 'project virtual environment'
        elif group is None and p.startswith(str(venv.parent) + '/'):
            group = 'a working checkout of this repository (must not happen)'
        if group in ('PDK', 'Magic', 'netgen', 'Tcl library used by Magic and netgen', 'tool wrappers',
                     'a working checkout of this repository (must not happen)'):
            outside.append(dict(path=p.replace(str(HOME), '~'), group=group, sha256=sha_file(p)))
        elif group:
            s = summaries.setdefault(group, [0, hashlib.sha256()])
            s[0] += 1
            s[1].update(f'{p} {sha_file(p)}\n'.encode())
        else:
            outside.append(dict(path=p.replace(str(HOME), '~'), group='other', sha256=sha_file(p)))
    return repo, outside, {g: dict(files=c, digest_of_paths_and_sha256=h.hexdigest()) for g, (c, h) in summaries.items()}


# ------------------------------------------------------------------ comparisons
def ext_records(text):
    """Magic .ext records as a multiset; a coupling capacitor's two electrodes are unordered (as rebuild_check.py)."""
    records = Counter()
    for line in text.splitlines():
        m = re.fullmatch(r'cap "([^"]+)" "([^"]+)" (\S+)', line)
        records[('cap', *sorted(m.groups()[:2]), m.group(3)) if m else ('other', line)] += 1
    return records


def gds_detail(obtained, stored):
    out = subprocess.run([str(KPY), '-I', str(CHAIN / 'gds_compare.py'), str(obtained), str(stored)],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return dict(error=(out.stdout + out.stderr)[-2000:])


def compare_gds(obtained, stored):
    obtained, stored = Path(obtained), Path(stored)
    if not obtained.is_file():
        return dict(obtained=str(obtained.relative_to(WT)), stored=str(stored.relative_to(WT)), obtained_missing=True,
                    same_bytes=False)
    a, b = sha_bytes(obtained.read_bytes()), sha_bytes(content(stored))
    result = dict(obtained=str(obtained.relative_to(WT)), stored=str(stored.relative_to(WT)), obtained_sha256=a,
                  expected_sha256=b, same_bytes=a == b)
    if a != b:
        result['difference'] = gds_detail(obtained, stored)
    return result


def compare_pex(stem, archive):
    """The rebuilt extraction against the stored one: the same files rebuild_check.py compares, without stopping."""
    pex, arch = Path(stem + '_pex'), Path(archive)
    out = {}
    if not (pex / 'manifest.json').is_file():
        return dict(missing=str(pex.relative_to(WT)))
    for name in ('flat_parasitics.spice', 'native_six_pex.spice', 'nodes.json.gz'):
        new, old = pex / name, arch / (name if name.endswith('.gz') else name + '.gz')
        if not old.is_file():
            continue
        same = (new.read_bytes() == old.read_bytes()) if name.endswith('.gz') else sha_bytes(new.read_bytes()) == sha_bytes(content(old))
        out[name] = dict(same_bytes=same, obtained_sha256=sha_file(new),
                         stored_sha256=sha_file(old) if name.endswith('.gz') else sha_bytes(content(old)))
    if (arch / 'native_flat.ext.gz').is_file():
        new, old = (pex / 'native_flat.ext').read_bytes(), content(arch / 'native_flat.ext.gz')
        a, b = ext_records(new.decode()), ext_records(old.decode())
        out['native_flat.ext'] = dict(same_bytes=new == old, same_records_ignoring_order_and_coupling_electrode_order=a == b,
                                      records=sum(b.values()), obtained_only=sum((a - b).values()),
                                      stored_only=sum((b - a).values()))
    fresh = json.loads((pex / 'manifest.json').read_bytes())
    stored = json.loads((arch / 'manifest.json').read_bytes())
    keys = ('gds_sha256', 'source_circuit_sha256', 'whole_flat_sha256', 'board_spice_sha256', 'raw_spice_sha256',
            'ext_sha256', 'Magic_full_DRC', 'LVS', 'MIM_accounting', 'floating_elimination')
    out['manifest_fields'] = {k: fresh.get(k) == stored.get(k) for k in keys if k in stored}
    out['manifest_same_bytes'] = (pex / 'manifest.json').read_bytes() == (arch / 'manifest.json').read_bytes()
    receipt = Path(stem + '_checks') / 'receipt.json'
    if (arch / 'LVS.json').is_file() and receipt.is_file():
        out['LVS.json_same_bytes'] = receipt.read_bytes() == (arch / 'LVS.json').read_bytes()
    out['all_electrical_records_agree'] = all(
        v.get('same_bytes', True) for k, v in out.items() if isinstance(v, dict) and k.endswith(('.spice', '.gz'))) and \
        out.get('native_flat.ext', {}).get('same_records_ignoring_order_and_coupling_electrode_order', True) and \
        all(v for k, v in out['manifest_fields'].items() if k not in ('ext_sha256', 'raw_spice_sha256'))
    return out


def compare_pair(new, old):
    key = None
    if '#' in old:
        old, key = old.split('#')
    new, old = WT / new, WT / old
    entry = dict(obtained=str(new.relative_to(WT)), stored=str(old.relative_to(WT)) + (f' [{key}]' if key else ''))
    if not new.is_file():
        return {**entry, 'same': False, 'obtained_missing': True}
    if key:
        entry['same'] = json.loads(new.read_bytes()) == json.loads(content(old))[key]
        entry['compared_as'] = 'JSON value'
    else:
        entry['same'] = new.read_bytes() == content(old)
        entry['compared_as'] = 'bytes (stored file decompressed if gzipped)'
    return entry


# ------------------------------------------------------------------ worktree
def repository():
    common = Path(run(['git', '-C', str(CHAIN), 'rev-parse', '--path-format=absolute', '--git-common-dir']))
    return common.parent


def remove_worktree(repo):
    subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', '--force', str(WT)], capture_output=True)
    if WT.exists() and (WT / '.git').is_file():
        shutil.rmtree(WT)
    subprocess.run(['git', '-C', str(repo), 'worktree', 'prune'], capture_output=True)


def create_worktree(repo, commit, replace):
    if WT.exists():
        listed = run(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'])
        if not replace or f'worktree {WT}' not in listed.splitlines():
            sys.exit(f'{WT} exists; pass --replace-worktree to remove it (only if it is this repository\'s worktree)')
        remove_worktree(repo)
    run(['git', '-C', str(repo), 'worktree', 'add', '--no-checkout', '--detach', str(WT), commit])
    run(['git', '-C', str(WT), 'sparse-checkout', 'set', X])
    run(['git', '-C', str(WT), 'checkout'])
    head = run(['git', '-C', str(WT), 'rev-parse', 'HEAD'])
    return head


def tracked_files():
    out = subprocess.run(['git', '-C', str(WT), 'ls-files', '-z', X], capture_output=True, check=True).stdout
    return set(p.decode() for p in out.split(b'\0') if p)


def environment(ppy, head, repo):
    def first(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[0]
        except Exception as e:  # noqa: BLE001 - recorded as text
            return f'unavailable: {e}'
    return dict(commit=head, commit_date=run(['git', '-C', str(WT), 'log', '-1', '--format=%cI']),
                worktree='~/.cache/six-chain-replay (detached, sparse: ' + X + ')',
                project_python=first([str(ppy), '-c', 'import sys;print(sys.version.split()[0])']),
                klayout_python=first([str(KPY), '-c', 'import sys,klayout;print(sys.version.split()[0],"klayout",klayout.__version__)']),
                system_python=first([str(SYSPY), '-c', 'import sys;print(sys.version.split()[0])']),
                gpp=first(['g++', '--version']), strace=first(['strace', '-V']),
                pdk=os.path.realpath(HOME / '.ciel/sky130A').replace(str(HOME), '~'),
                magic_wrapper_sha256=sha_file(HOME / '.local/bin/magic-8.3.685'),
                netgen_wrapper_sha256=sha_file(HOME / '.local/bin/netgen-1.5.325'),
                scrubbed_environment_variables=[k for k in SCRUB if k in os.environ])


# ------------------------------------------------------------------ one step
def fill(arg, ctx):
    return arg.format(**ctx)


def run_step(step, ctx, tracked, writers, venv):
    work = WT / 'replay_work' / step['id']
    logs = WT / 'replay_work' / 'logs' / step['id']
    logs.mkdir(parents=True, exist_ok=True)
    ctx = {**ctx, 'work': str(work)}
    cwd = WT / step['cwd']
    env = {k: v for k, v in os.environ.items() if k not in SCRUB}
    commands, traces, ok = [], [], True
    t_step = time.time()
    for i, cmd in enumerate(step['commands']):
        argv = [fill(a, ctx) for a in cmd]
        log, trace = logs / f'cmd_{i:02d}.log', logs / f'cmd_{i:02d}.strace'
        t0 = time.time()
        with log.open('wb') as f:
            f.write(('$ cd ' + step['cwd'] + ' && ' + ' '.join(argv) + '\n').replace(str(HOME), '~').encode())
            f.flush()
            proc = subprocess.run(['strace', '-f', '-qq', '-z', '-y', '--seccomp-bpf', '-e', TRACE, '-e', 'signal=none',
                                   '-o', str(trace), *argv], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
        seconds = round(time.time() - t0, 1)
        traces.append(trace)
        shown = [a.replace(str(WT) + '/', '').replace(str(HOME), '~') for a in argv]
        commands.append(dict(argv=shown, exit_code=proc.returncode, seconds=seconds,
                             log=f'takeover/layout/runs/chain/{step["id"]}/cmd_{i:02d}.log.gz',
                             trace=f'takeover/layout/runs/chain/{step["id"]}/cmd_{i:02d}.strace.gz'))
        print(f'  [{step["id"]}] {i}: exit {proc.returncode} in {seconds} s', flush=True)
        if proc.returncode:
            ok = False
            break
    seconds = round(time.time() - t_step, 1)
    inputs, written, execs = parse_traces(traces, cwd)

    # Tracked files a step rewrote: identical or not, then restored so that later steps read the stored versions.
    rewritten = []
    root = str(WT) + '/'
    changed = set(run(['git', '-C', str(WT), 'diff', '--name-only']).splitlines())
    for p in written:
        rel = p[len(root):] if p.startswith(root) else None
        if rel in tracked:
            rewritten.append(dict(path=rel, identical_to_git=rel not in changed))
    if changed:
        subprocess.run(['git', '-C', str(WT), 'checkout', '--', *sorted(changed)], check=True)
    repo_inputs, outside, summaries = classify(inputs, tracked, writers, venv)
    for p in written:
        writers.setdefault(p, step['id'])

    product = Path(fill(step['product'], ctx).replace('{work}', str(work)))
    product = product if product.is_absolute() else WT / product
    comparisons = {}
    stored_gds = step.get('stored_gds') or (step['archive'] + '/die.gds.gz')
    comparisons['mask'] = compare_gds(Path(str(product) + '.gds'), WT / stored_gds)
    for new, old in step.get('extra_gds', []):
        comparisons.setdefault('other_masks', []).append(compare_gds(WT / new, WT / old))
    if step.get('archive'):
        comparisons['extraction'] = compare_pex(str(product), WT / step['archive'])
    comparisons['side_files'] = [compare_pair(fill(a, ctx).replace(str(WT) + '/', ''), b) for a, b in step['pairs']]
    for keep in step.get('keep', []):
        dest = work / Path(keep).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if (WT / keep).is_file():
            shutil.copyfile(WT / keep, dest)

    # Logs and traces, gzipped, kept out of git.
    dest = RUNS / step['id']
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(logs.iterdir()):
        (dest / (f.name + '.gz')).write_bytes(gzip.compress(f.read_bytes(), mtime=0))

    # Every stored layout the step opened (masks, cells, placements, recorded metal), by the sha256 of its content.
    layouts = [dict(path=e['path'], in_git=e['in_git'], file_sha256=e['sha256'],
                    content_sha256=sha_bytes(content(WT / e['path'])))
               for e in repo_inputs if e['path'].endswith(('.gds', '.gds.gz', 'parent_metal.json.gz'))]
    same = bool(ok and comparisons['mask'].get('same_bytes'))
    written_repo = sorted(p[len(root):] for p in written if p.startswith(root) and not p[len(root):].startswith('replay_work/'))
    return dict(id=step['id'], mask=step['mask'], title=step['title'], parent=step['parent'], documented_in=step['doc'], cwd=step['cwd'],
                commands=commands, completed=ok, seconds=seconds,
                expected_sha256=comparisons['mask'].get('expected_sha256'),
                obtained_sha256=comparisons['mask'].get('obtained_sha256'), same_bytes=same,
                stored_layouts_read=layouts,
                inputs=dict(repository=repo_inputs, outside_repository=outside, interpreters=summaries,
                            not_in_git=[e for e in repo_inputs if not e['in_git']],
                            programs=[e.replace(str(HOME), '~') for e in execs]),
                writes=dict(repository_files_outside_step_folder=[w for w in written_repo
                                                                  if not w.startswith(str(work.relative_to(WT)))],
                            tracked_files_rewritten=rewritten,
                            outside_worktree=sorted(p.replace(str(HOME), '~') for p in written
                                                    if not p.startswith(root) and not p.startswith(SYSTEM))),
                comparisons=comparisons)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--commit', default='main')
    ap.add_argument('--steps', help='comma-separated step ids (default: all, in order)')
    ap.add_argument('--keep-worktree', action='store_true')
    ap.add_argument('--replace-worktree', action='store_true')
    a = ap.parse_args()
    for tool in ('strace', 'g++', 'git'):
        if shutil.which(tool) is None:
            sys.exit(f'{tool} is required')
    repo = repository()
    venv = repo / '.venv'
    ppy = venv / 'bin/python'
    commit = run(['git', '-C', str(repo), 'rev-parse', a.commit])
    print(f'worktree {WT} at {commit}', flush=True)
    head = create_worktree(repo, commit, a.replace_worktree)
    report = dict(question='How far back does the layout chain of the selected mask bbf78759 rebuild byte for byte '
                           'from the files git holds?',
                  written_by='takeover/layout/chain/replay.py', started=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                  environment=environment(ppy, head, repo), steps=[])
    out = CHAIN / 'replay.json'
    try:
        tracked = tracked_files()
        writers = {}
        ctx = dict(PPY=str(ppy), KPY=str(KPY), SYSPY=str(SYSPY), W=str(WT))
        wanted = a.steps.split(',') if a.steps else [s['id'] for s in STEPS]
        for step in STEPS:
            if step['id'] not in wanted:
                continue
            print(f'step {step["id"]}: {step["title"]}', flush=True)
            result = run_step(step, ctx, tracked, writers, venv)
            report['steps'].append(result)
            print(f'  same bytes: {result["same_bytes"]} ({result["obtained_sha256"]})', flush=True)
            out.write_text(json.dumps(report, indent=1) + '\n')
        status = run(['git', '-C', str(WT), 'status', '--porcelain', '--', X])
        report['tracked_files_modified_at_end'] = status.splitlines()
        # The ignored V4 build files that most steps read are copies that V4's magic_util.prepare() makes on import
        # from tracked files of the accepted chip; check that every one is identical to its tracked source.
        v4 = WT / X / 'programmable_weights_v4_20261114/floorplan/build/r6'
        acc = WT / X / 'feasibility_20261107/floorplan/chip2x2'
        copies = sorted(v4.glob('layout/*.mag')) + [v4 / 'results/aj_neuron_edge.json']
        report['ignored_V4_build_copies'] = dict(
            files=len(copies), source=str(acc.relative_to(WT)),
            identical_to_tracked_source=all(c.is_file() and c.read_bytes() == (acc / c.parent.name / c.name).read_bytes()
                                            for c in copies))
        report['summary'] = [dict(step=s['id'], mask=s['mask'], same_bytes=s['same_bytes'], seconds=s['seconds'],
                                  extraction_agrees=s['comparisons'].get('extraction', {}).get('all_electrical_records_agree'),
                                  inputs_not_in_git_and_not_written_by_an_earlier_step=[
                                      e['path'] for e in s['inputs']['not_in_git'] if not e.get('written_by_step')])
                             for s in report['steps']]
        report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        out.write_text(json.dumps(report, indent=1) + '\n')
    finally:
        if not a.keep_worktree:
            remove_worktree(repo)
            report['worktree_removed'] = not WT.exists()
            out.write_text(json.dumps(report, indent=1) + '\n')
    print(f'wrote {out}', flush=True)


if __name__ == '__main__':
    main()
