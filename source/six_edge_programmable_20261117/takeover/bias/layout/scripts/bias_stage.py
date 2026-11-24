"""One more stage of the base flow on top of the selected layout: the programmable hidden offsets (bias variant).

  KPY bias_stage.py FOLDER W1 L1 W2 L2 [--schematic VARIANT.spice]

Starts from EV/layout_bbf78759_gate_p897/die.gds.gz (hash-checked). Every existing block and wire stays where it is,
except four top-level shapes at `ne_return` that tied the two return switches' sources (b1, b2) to VSS (replaced so that
the guard ring and both neighbours stay on VSS through metal: scripts/free_returns.py). Adds the words block
(two writers copied from pw4_shunt, two 8.97 um capacitors, XPROG1/XPROG2) in the pocket inside the reference buffer's
outline and the strobe logic above it, then routes only the new nets with the base flow's router (quiet_route.route, imported
unchanged) and its analog costs, plus keepouts on every resistor body, every MIM plate and the new stored-node areas.
Writes FOLDER/chip.gds, chip_targets.json, placement.json, routing.json; the checks follow in rebuild.py.
"""
import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
LAYOUT_DIR = HERE.parent
SIX = HERE.parents[3]
NE = SIX / 'native_edges'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(NE / 'layout/hold_mode'))
import quiet_route                      # noqa: E402  the base flow's router, unchanged
from route_split import circuit         # noqa: E402
from connectivity import METALS, Connectivity  # noqa: E402
import cells                            # noqa: E402
import free_returns                     # noqa: E402

PARENT = NE / 'verification/evidence/layout_bbf78759_gate_p897/die.gds.gz'
PARENT_SHA = 'bbf7875934448644dfa0c871103ef1f93f6e8285dfba6d05863c42baaddbf41b'
BASE_TARGETS = LAYOUT_DIR / 'inputs/base_targets.json'
BASE_TARGETS_SHA = '7899a072becbbccb3afcaeffb05bc2d5b8cf961366a0ea0f911149667d27900f'
CAP_SHA = '15e06a8bac27fc7179ed0459bf7b4eb2a2ee35bd37e3c3690cc7e8efd7ba9adf'     # = the selected layout's 8.97 um leaf
LOGIC_AT = (274.00, 28.30)
PY = os.environ.get('PY') or sys.executable   # rebuild.py sets PY to the interpreter it runs under

# windows through which routes may reach the new blocks' pins (everything else of the blocks is kept out)
WORDS_KEEPOUT = db.Box(267000, 1800, 300100, 22400)
WORDS_WINDOWS = [db.Box(270150, 12850, 272600, 25000),      # pin row: bstb1, ret1, ret2 (bg1 stack left of it is kept out)
                 db.Box(285520, 8500, 287200, 25000),       # REF and bstb2 pins (wire centres 0.55 from both wide plates)
                 db.Box(283000, 0, 285050, 3500)]           # VDD and DAC pins, from below


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def new_targets(lx, ly_):
    """Terminals of the new nets: existing metal they join and the new pins."""
    T = []
    T += [['ret1', 'RETURN:b1', 'm2', 176.68, 41.505], ['ret1', 'WORDS:ret1', 'm3', 271.35, 13.15]]
    T += [['ret2', 'RETURN:b2', 'm2', 175.58, 42.688], ['ret2', 'WORDS:ret2', 'm3', 272.15, 13.15]]
    T += [['bstb1', 'WORDS:bstb1', 'm3', 270.55, 13.15], ['bstb1', 'LOGIC:bstb1', 'm3', lx + 5.29, ly_ - 0.95]]
    T += [['bstb2', 'WORDS:bstb2', 'm3', 286.85, 8.89], ['bstb2', 'LOGIC:bstb2', 'm3', lx + 6.67, ly_ - 0.95]]
    T += [['dac', 'WORDS:dac', 'm3', 284.65, 3.20], ['dac', 'BIAS:dac', 'm1', 158.74, 36.25]]
    T += [['bit_a', 'LOGIC:bit_a', 'm3', lx + 1.565, ly_ - 0.95], ['bit_a', 'BANK:bit_a', 'm2', 126.84, 217.47]]
    T += [['bit_b', 'LOGIC:bit_b', 'm3', lx + 0.72, ly_ - 0.95], ['bit_b', 'BANK:bit_b', 'm2', 126.84, 216.09]]
    T += [['we0', 'LOGIC:we0', 'm3', lx + 2.30, ly_ - 0.95], ['we0', 'DEC:we0', 'm3', 280.0, 204.53]]
    T += [['we1', 'LOGIC:we1', 'm3', lx + 3.68, ly_ - 0.95], ['we1', 'DEC:we1', 'm3', 280.0, 205.48]]
    T += [['ref', 'WORDS:ref', 'm3', 285.65, 8.85]]
    T += [['vdd', 'WORDS:vdd', 'm3', 283.45, 2.60], ['vdd', 'LOGIC:vdd', 'm2', lx + 8.20, ly_ + 2.72]]
    T += [['vss', 'WORDS:vss', 'm3', 299.70, 2.20], ['vss', 'LOGIC:vss', 'm2', lx + 8.20, ly_ + 0.0]]
    return T


def keepout_fields(layout, top, logic_box, cost=20000):
    """Resistor bodies and MIM plates of the whole die (0.6 um halo) on all four metals; the words block on metal 1 and 2
    everywhere and on metal 3 and 4 outside its pin windows; the logic block outside its pin row and its supply pads."""
    ix = lambda l, d: layout.layer(l, d)
    bodies = (db.Region(top.begin_shapes_rec(ix(66, 13))) & db.Region(top.begin_shapes_rec(ix(66, 20)))).merged()
    plates = db.Region(top.begin_shapes_rec(ix(89, 44))).merged()
    common = (bodies + plates).merged().sized(600)
    # metal 3 wider than 3 um needs 0.4 um to unrelated metal 3 (met3.3d), which the router does not know: keep wire
    # centres 0.56 um from every wide metal-3 shape (plates of capacitors, wide buses)
    m3 = db.Region(top.begin_shapes_rec(ix(70, 20))).merged()
    wide_m3 = m3.sized(-1500).sized(1500).merged().sized(560)
    lb = logic_box
    logic = db.Region(lb) - db.Region(db.Box(lb.left, lb.bottom - 2000, lb.right, lb.bottom + 1500)) \
        - db.Region(db.Box(lb.right - 600, lb.bottom, lb.right + 1000, lb.top))
    words_low = db.Region(WORDS_KEEPOUT)
    words_high = db.Region(WORDS_KEEPOUT)
    for w in WORDS_WINDOWS:
        words_high -= db.Region(w)
    out = []
    regions = {}
    for dst in range(4):
        keep = (common + logic + (words_low if dst < 2 else words_high) + (wide_m3 if dst == 2 else db.Region())).merged()
        regions[dst] = keep
        for b in quiet_route.grid.boxes(keep):
            out.append((dst, *b, cost))
    return out, regions


def route_pass(folder, stem, source, targets, wires, weight, extra):
    quiet_route.BUILD = folder
    (folder / f'{stem}_targets.json').write_text(json.dumps(targets, indent=1) + '\n')
    ordinary = quiet_route.analog_cost

    def fields(con, groups, w):
        # a net that is still in pieces (REF before its new pin is joined) is costed by its largest piece
        g = dict(groups)
        for name in ('ref',):
            if name in g and len(g[name]) > 1:
                g[name] = {max(g[name], key=lambda n: con.region(n, 'm2').area() + con.region(n, 'm3').area())}
        f = ordinary(con, g, w)
        for item in extra:
            f.extend(item)
        return f
    quiet_route.analog_cost = fields
    try:
        quiet_route.route(stem, 220, 110, weight, True, source=source, target_file=f'{stem}_targets.json',
                          wires=wires, physical_points=True)
    finally:
        quiet_route.analog_cost = ordinary
    return json.loads((folder / f'{stem}.json').read_text())


def build(folder, w1, l1, w2, l2):
    folder.mkdir(parents=True, exist_ok=True)
    raw = gzip.decompress(PARENT.read_bytes())
    assert sha(raw) == PARENT_SHA
    assert sha(BASE_TARGETS.read_bytes()) == BASE_TARGETS_SHA
    ly = db.Layout(); ly.read_bytes(raw); top = ly.top_cell()
    record = dict(parent_gds_sha256=PARENT_SHA, xprog=dict(W1=w1, L1=l1, W2=w2, L2=l2))
    # 1. free b1, b2 from VSS (top-level shapes only)
    record['free_returns'] = free_returns.free(ly, top)
    # 2. leaves: XPROG pair from the PDK generator, the 8.97 um capacitor leaf of the selected layout, the writer copy
    dev = folder / 'dev'
    subprocess.run([PY, '-I', str(HERE / 'gen_devices.py'), str(dev), w1, l1, w2, l2], check=True)
    leaves = {}
    for key, path, name in (('xp1', dev / 'xprog_h1.gds', 'ne_bias_xprog1'), ('xp2', dev / 'xprog_h2.gds', 'ne_bias_xprog2'),
                            ('cap', cells.CAP_UNIT, 'ne_bias_cap897')):
        data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        if key == 'cap':
            assert sha(data) == CAP_SHA
        src = db.Layout(); src.read_bytes(data)
        c = ly.create_cell(name); c.copy_tree(src.top_cell()); leaves[key] = c
    record['leaf_sha256'] = {k: sha((dev / f'xprog_h{1 if k == "xp1" else 2}.gds').read_bytes()) for k in ('xp1', 'xp2')}
    writer, wrec = cells.writer(ly, pins=False)
    words = cells.words_block(ly, writer, leaves['cap'], leaves['xp1'], leaves['xp2'], float(l1), float(l2))
    logic, _ = cells.logic_block(ly)
    top.insert(db.CellInstArray(words.cell_index(), db.Trans()))
    lt = db.Trans(round(LOGIC_AT[0] * 1000), round(LOGIC_AT[1] * 1000))
    top.insert(db.CellInstArray(logic.cell_index(), lt))
    logic_box = logic.bbox().transformed(lt)
    record['placement'] = dict(words=dict(cell=words.name, transform='r0 0,0', bbox_um=[v / 1000 for v in (words.bbox().left, words.bbox().bottom, words.bbox().right, words.bbox().top)]),
                               logic=dict(cell=logic.name, transform=lt.to_s(), bbox_um=[v / 1000 for v in (logic_box.left, logic_box.bottom, logic_box.right, logic_box.top)]))
    # 3. terminals; the parent's nets must be intact and the new pins must not touch anything else
    base = json.loads(BASE_TARGETS.read_text())
    new = new_targets(*LOGIC_AT)
    nets, shorts, _ = circuit(ly, top, base + new)
    if shorts:
        raise ValueError(('placement shorts', shorts))
    pre = {n: len(g) for n, g in nets.items() if len(g) > 1}
    record['pre_route_groups'] = pre
    quiet_route.save(ly, top, folder / 'open.gds')
    extra, keep = keepout_fields(ly, top, logic_box)
    # 4. route: the two return wires first, alone and with doubled analog weight; then everything else
    ret = [t for t in new if t[0] in ('ret1', 'ret2')]
    rest = [t for t in new if t[0] not in ('ret1', 'ret2')]
    record['routing'] = {}
    record['routing']['returns'] = route_pass(folder, 'routed_ret', 'open', base + ret, ('ret1', 'ret2'), 120, extra)
    wires = ('bstb1', 'bstb2', 'dac', 'ref', 'bit_a', 'bit_b', 'we0', 'we1', 'vdd', 'vss')
    record['routing']['others'] = route_pass(folder, 'chip', 'routed_ret', base + new, wires, 60, extra)
    (folder / 'chip_targets.json').write_text(json.dumps(base + new, indent=1) + '\n')
    (folder / 'placement.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps({k: v for k, v in record.items() if k != 'free_returns'}, indent=1), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('w1'); p.add_argument('l1'); p.add_argument('w2'); p.add_argument('l2')
    a = p.parse_args()
    build(a.folder.resolve(), a.w1, a.l1, a.w2, a.l2)
