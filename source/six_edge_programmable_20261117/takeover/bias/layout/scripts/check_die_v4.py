"""The base flow's check_die.py, run unchanged, with the LVS reference's dummy-strip table brought to the version-4 cells.

  PY -B check_die_v4.py STREAM --negative --schematic VARIANT_V4.spice

The base flow's reference generator (native_edges/layout/reference.py) adds every poly cell's grounded edge dummies to the
expected circuit from native_edges/layout/results/poly_cells.json (sha256 fb9ec3aa..., checked here). In the version-4
stage ne_g1 and ne_r1 carry the contents of ne_g2 and ne_r2 (v4_stage.py), dummies included, so in a copy of that
table their entries become ne_g2's and ne_r2's (strip length, strip counts, target), names kept. The copy is written to
STREAM's folder as v4_reference/results/poly_cells.json, and reference.HERE points to v4_reference while the check runs.
Nothing of the base flow is changed; everything else is check_die.py as it stands (rule check, flat LVS, wrong-netlist control).

Netlist version 5 (rzero/make_variant_v5.py: XBUF3 RZERO=1k -> 1225, its zero resistor L 0.54 -> 0.70): the reference
takes every amplifier cell from the amp generator's own reference file (make_ref's amp_defs reads
AMP_REF/<cell>_ref.spice, feasibility_20261107/amp_layout/ref), not from the netlist version, so XBUF3's az_ref4 would
still be expected at L 0.54. With --schematic version 5 (by sha256), the amp reference folder is copied to STREAM's
folder as v5_reference/amp_ref, its az_ref4_ref.spice (sha256 1f32e799..., checked) with its one zero-resistor line at
the length version 5 gives (pdk_rfixed's formula on XBUF3's RZERO: 0.7), every other file unchanged, and make_ref's
AMP_REF points there while the check runs. With any other schematic nothing of this happens.

Every run with --schematic also checks those amplifier macros against the netlist version (macro_check.py, 24 Nov, at
the design lead's request): for each macro instance the reference makes, the netlist version's own subcircuit,
expanded with that instance's parameters, must agree device by device with the reference file the check reads (the
folder make_ref's AMP_REF points to); the result is written beside STREAM as <stream>_macro_check.json and any
difference stops the check.
"""
import hashlib
import json
import math
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAY = HERE.parents[3] / 'native_edges' / 'layout'
POLY_SHA = 'fb9ec3aaf1eae6d5f001c6d1adb138a9919b25feb9db87421da8f4affb7fef24'
TAKES = {'ne_g1': 'ne_g2', 'ne_r1': 'ne_r2'}
V5_SHA = '399eac539f89319920f6f0921f33a6454fbd4b10d10704f1164dfca0bb13a8c6'
AMP_REF = HERE.parents[4] / 'feasibility_20261107' / 'amp_layout' / 'ref'
AZ_REF4_SHA = '1f32e799b4d9c23236db08aa562bb1ca71a0bf2519bc2b78dc4944748d1aae94'
RZ_LINE = 'XAMP_XRZERO_XDEVICE_XR0 XAMP_comp XAMP_gain1 vss sky130_fd_pr__res_xhigh_po_1p41 L=0.54'


def v5_amp_ref(schematic, folder):
    """The amp reference folder with az_ref4's zero resistor at version 5's length; None for any other schematic."""
    text = Path(schematic).read_bytes()
    if hashlib.sha256(text).hexdigest() != V5_SHA:
        return None
    rz = re.findall(r'(?m)^XBUF3 .* cd_ref_az .*\bRZERO=([0-9.]+)\s', text.decode())
    assert len(rz) == 1, rz
    length = round(0.01 * math.floor(((float(rz[0]) / 1 - 232.3959788743) * 1.41 / 2000) / 0.01 + 0.5), 2)
    assert length == 0.7, length
    raw = (AMP_REF / 'az_ref4_ref.spice').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == AZ_REF4_SHA, 'az_ref4_ref.spice differs from the one checked'
    lines = raw.decode().split('\n')
    hit = [i for i, l in enumerate(lines) if l == RZ_LINE]
    assert len(hit) == 1, hit
    lines[hit[0]] = RZ_LINE.replace('L=0.54', f'L={length:g}')
    amp = folder / 'v5_reference' / 'amp_ref'
    amp.mkdir(parents=True, exist_ok=True)
    for f in sorted(AMP_REF.iterdir()):
        if f.is_file():
            (amp / f.name).write_bytes(f.read_bytes())
    (amp / 'az_ref4_ref.spice').write_text('\n'.join(lines))
    (folder / 'v5_reference' / 'amp_ref.json').write_text(json.dumps(dict(
        schematic_sha256=V5_SHA, xbuf3_rzero=rz[0], length_um=length, source=str(AMP_REF.relative_to(HERE.parents[4])),
        az_ref4_ref_sha256_before=AZ_REF4_SHA,
        az_ref4_ref_sha256_after=hashlib.sha256((amp / 'az_ref4_ref.spice').read_bytes()).hexdigest(),
        line=hit[0] + 1, old=RZ_LINE, new=lines[hit[0]]), indent=1) + '\n')
    return amp


stream = Path(sys.argv[1]).resolve()
raw = (LAY / 'results/poly_cells.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == POLY_SHA, 'poly_cells.json differs from the one checked'
table = json.loads(raw)
by_name = {c['name']: c for c in table}
assert all(k in by_name and v in by_name for k, v in TAKES.items())
copy = []
for c in table:
    if c['name'] in TAKES:
        c = dict(by_name[TAKES[c['name']]], name=c['name'], version4_contents_of=TAKES[c['name']])
    copy.append(c)
dst = stream.parent / 'v4_reference'
(dst / 'results').mkdir(parents=True, exist_ok=True)
(dst / 'results/poly_cells.json').write_text(json.dumps(copy, indent=1) + '\n')
args = sys.argv[2:]
if '--schematic' in args:          # paths given relative to the caller's folder, before moving to the base flow's
    i = args.index('--schematic') + 1
    args[i] = str(Path(args[i]).resolve())
os.chdir(LAY)
sys.path.insert(0, str(LAY))
import reference  # noqa: E402  the base flow's, unchanged
reference.HERE = dst
if '--schematic' in args:
    amp = v5_amp_ref(args[args.index('--schematic') + 1], stream.parent)
    if amp is not None:
        reference.M.AMP_REF = amp
    subprocess.run([sys.executable, '-I', '-B', str(HERE / 'macro_check.py'), args[args.index('--schematic') + 1],
                    str(Path(reference.M.AMP_REF)), str(stream.parent / f'{stream.name}_macro_check.json'), '0'],
                   check=True, stdout=subprocess.DEVNULL)
sys.argv = [str(LAY / 'check_die.py'), str(stream)] + args
runpy.run_path(str(LAY / 'check_die.py'), run_name='__main__')
