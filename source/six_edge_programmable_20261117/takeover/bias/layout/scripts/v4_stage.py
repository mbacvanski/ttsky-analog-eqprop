"""Second candidate (netlist version 4): H1's six-weight bias network made H2's, as one more stage on top of the lock build.

  KPY v4_stage.py IN.gds FOLDER

IN.gds must be the lock build (GDS sha256 23388cc1..., hash-checked). Changes, and nothing else:
 1. ne_g1, H1's chain to ground (16 strips of L 26.15 um), gets ne_g2's contents (H2's chain, 8 strips of L 22.40 um):
    ne_g1 and its child ne_g1_xpoly are cleared and filled with copies of ne_g2's and ne_g2_xpoly's shapes, the child at
    ne_g2's own position; the pin labels p2, end2 become p1, end1. Placed right-aligned in the old outline, r0 at
    (301.92, 206.85) (was 298.17): there the two metal-1 wires that cross the block (y 212.6 and 214.4) still pass
    between its end links, and the VSS via stack of the RC filter's capacitor (331.29, 207.99) still lands on its
    bottom-right dummy link. Three top-level pieces reconnect the pins that moved (end1, p1, the VSS feed from below).
 2. ne_r1, H1's trim (2 strips of L 1.49 um), gets ne_r2's contents (2 strips of L 4.12 um); fixed2 becomes fixed1.
    Placed r0 at (118.20, 166.11) (was 118.25): its pins land on the existing ref, fixed1 and VSS feeds unchanged; it
    reaches 2.58 um further right, its p-tap 0.30 um from the H2 neuron block's p-tap. The two p-implants are then 0.05 um
    apart, so one psdm rectangle merges them.
 3. XPROG1 regenerated at W 1 / L 3.5 by Magic's PDK generator (gen_devices.py, as in bias_stage.py); it must come out
    identical to XPROG2's leaf. The words block is redrawn by cells.words_block with L1 3.5 and W1 1 into the same cell.
Writes FOLDER/chip_v4.gds (the base flow's timestamp-free writer) and FOLDER/v4_stage.json (what changed, where, and checks).
"""
import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[3]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIX / 'layout'))
from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer
import cells                     # noqa: E402

LOCK_SHA = '23388cc15420fe29a9e8a0674d7a3ab2265cfd8cab6c9b919df192bc03f43ad0'
PY = os.environ.get('PY') or sys.executable   # rebuild.py sets PY to the interpreter it runs under
W1, L1, W2, L2 = '1', '3.5', '1', '3.5'
SWAPS = [  # cell that stays (its name, its instance), cell whose contents it takes, new origin (r0), label renames
    ('ne_g1', 'ne_g2', (301.92, 206.85), {'p2': 'p1', 'end2': 'end1'}),
    ('ne_r1', 'ne_r2', (118.20, 166.11), {'fixed2': 'fixed1'}),
]
ADD = [  # top-level rectangles, die um
    ('m2', (69, 20), 299.08, 208.765, 303.17, 209.145, 'end1: the existing m2 feed (x 299.08..299.23, from below) to the moved end1 pad'),
    ('m1', (68, 20), 299.08, 214.635, 299.23, 221.33, 'p1: down from the end of the existing m1 feed (y 221.18..221.33)'),
    ('m1', (68, 20), 299.08, 214.635, 302.90, 214.895, 'p1: along to the moved p1 link, 0.145 um above the m1 wire at y 214.34..214.49'),
    ('m1', (68, 20), 300.60, 208.00, 304.30, 208.25, 'VSS: the existing m1 feed (x 300.60..300.75, from below) to the bottom-left dummy link'),
    ('psdm', (94, 20), 130.25, 166.435, 130.41, 170.825, 'p-implant of the new ne_r1 merged with the H2 neuron block\'s (0.05 um apart)'),
]
# every difference from the input must lie inside these windows (die um): old and new outlines of the two resistor
# cells with the added pieces, and XPROG1 with its bar and drain wiring in the words block
WINDOWS = {'ne_g1': (298.10, 206.80, 332.55, 223.40), 'ne_r1': (118.15, 166.05, 130.60, 171.05),
           'xprog1': (269.55, 9.30, 279.20, 11.70)}
LAYERS = [(64, 20), (65, 20), (65, 44), (66, 20), (66, 44), (66, 13), (67, 20), (67, 44), (68, 20), (68, 44), (69, 20),
          (69, 44), (70, 20), (70, 44), (71, 20), (71, 44), (72, 20), (89, 44), (93, 44), (94, 20), (95, 20), (79, 20),
          (75, 20), (78, 44), (81, 4), (235, 4), (67, 16), (68, 16), (69, 16), (70, 16)]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def instance_of(top, ly, name):
    found = [i for i in top.each_inst() if ly.cell(i.cell_index).name == name]
    assert len(found) == 1, (name, len(found))
    return found[0]


def refill(ly, top, keep, src, at, rename):
    """`keep` and `keep`_xpoly take the shapes of `src` and `src`_xpoly; the child instance as in `src`."""
    kc, sc = ly.cell(keep), ly.cell(src)
    kx, sx = ly.cell(keep + '_xpoly'), ly.cell(src + '_xpoly')
    assert kx.child_instances() == 0 and sx.child_instances() == 0
    kx.clear()
    kx.copy_shapes(sx)
    kc.clear()
    kc.copy_shapes(sc)
    kids = list(sc.each_inst())
    assert len(kids) == 1 and kids[0].cell_index == sx.cell_index() and not kids[0].is_complex()
    # with its properties: the GDS instance name (61, 'XRARRAY') names the strips' nodes in Magic's extraction
    kc.insert(db.CellInstArray(kx.cell_index(), kids[0].trans), kids[0].prop_id)
    assert list(kc.each_inst())[0].prop_id == kids[0].prop_id
    renamed = []
    for li in ly.layer_indexes():
        for sh in kc.shapes(li).each():
            if sh.is_text() and sh.text_string in rename:
                t = sh.text
                renamed.append([sh.text_string, rename[sh.text_string], ly.get_info(li).to_s(), t.x / 1000, t.y / 1000])
                t.string = rename[sh.text_string]
                sh.text = t
    assert sorted(r[0] for r in renamed) == sorted(rename), renamed
    inst = instance_of(top, ly, keep)
    old = inst.trans.to_s()
    inst.trans = db.Trans(round(at[0] * 1000), round(at[1] * 1000))
    return dict(cell=keep, contents_of=src, instance_was=old, instance_now=inst.trans.to_s(), labels_renamed=renamed,
                outline_um=list(map(float, str(inst.dbbox()).strip('()').replace(';', ',').split(','))))


def region(cell, ly, ld, trans=None):
    r = db.Region(cell.begin_shapes_rec(ly.layer(*ld)))
    return r.transformed(trans) if trans else r


def main(src, folder):
    folder.mkdir(parents=True, exist_ok=True)
    raw = Path(src).read_bytes()
    raw = gzip.decompress(raw) if src.suffix == '.gz' else raw
    assert sha(raw) == LOCK_SHA, 'input is not the lock build'
    rec = dict(input_gds_sha256=LOCK_SHA, xprog1=dict(W=W1, L=L1))
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell()
    ref = db.Layout(); ref.read(str(src)); rtop = ref.top_cell()
    # 1, 2: the two resistor cells
    rec['swaps'] = [refill(ly, top, k, s, at, rn) for k, s, at, rn in SWAPS]
    # 3: XPROG1 at its new size; the words block redrawn
    dev = folder / 'dev_v4'
    subprocess.run([PY, '-I', str(HERE / 'gen_devices.py'), str(dev), W1, L1, W2, L2], check=True)
    gen = {}
    for n in ('xprog_h1', 'xprog_h2'):
        g = db.Layout(); g.read(str(dev / f'{n}.gds')); gen[n] = g
    xp1, xp2 = ly.cell('ne_bias_xprog1'), ly.cell('ne_bias_xprog2')
    assert xp1.child_instances() == 0
    xp1.clear()
    xp1.copy_tree(gen['xprog_h1'].top_cell())
    same = {}
    for ld in LAYERS:   # the new XPROG1 against XPROG2's leaf in the lock build, and the regenerated XPROG2 against it
        a = region(xp1, ly, ld); b = region(xp2, ly, ld)
        g2 = db.Region(gen['xprog_h2'].top_cell().begin_shapes_rec(gen['xprog_h2'].layer(*ld)))
        if not (a.is_empty() and b.is_empty()):
            same[f'{ld[0]}/{ld[1]}'] = [(a ^ b).is_empty(), (g2 ^ b).is_empty()]
    rec['xprog1_equals_xprog2_leaf'] = all(v[0] for v in same.values())
    rec['regenerated_xprog2_equals_lock_leaf'] = all(v[1] for v in same.values())
    assert rec['xprog1_equals_xprog2_leaf'] and rec['regenerated_xprog2_equals_lock_leaf'], same
    words = ly.cell('ne_bias_words')
    words.clear()
    cells.words_block(ly, ly.cell('ne_bias_writer'), ly.cell('ne_bias_cap897'), xp1, xp2, float(L1), float(L2),
                      w1=float(W1), cell=words)
    # top-level pieces
    rec['added'] = []
    for name, ld, x0, y0, x1, y1, why in ADD:
        top.shapes(ly.layer(*ld)).insert(cells.box(x0, y0, x1, y1))
        rec['added'].append(dict(layer=name, gds=f'{ld[0]}/{ld[1]}', box_um=[x0, y0, x1, y1], why=why))
    out = folder / 'chip_v4.gds'
    save(ly, top, out)
    # where the result differs from the input (flat, per layer), and nothing outside the windows
    new = db.Layout(); new.read(str(out)); ntop = new.top_cell()
    allowed = db.Region()
    for w in WINDOWS.values():
        allowed.insert(cells.box(*w))
    diff, outside = {}, {}
    for ld in LAYERS:
        a = db.Region(rtop.begin_shapes_rec(ref.layer(*ld))).merged()
        b = db.Region(ntop.begin_shapes_rec(new.layer(*ld))).merged()
        x = a ^ b
        if x.is_empty():
            continue
        diff[f'{ld[0]}/{ld[1]}'] = dict(area_um2=round(x.area() / 1e6, 4), bbox_um=str(x.bbox().to_dtype(0.001)))
        o = x - allowed
        if not o.is_empty():
            outside[f'{ld[0]}/{ld[1]}'] = str(o.bbox().to_dtype(0.001))
    rec['difference_by_layer'] = diff
    rec['difference_outside_windows'] = outside
    rec['windows_um'] = WINDOWS
    rec['output_gds_sha256'] = sha(out.read_bytes())
    rec['generated_leaf_sha256'] = {n: sha((dev / f'{n}.gds').read_bytes()) for n in gen}
    rec['note'] = 'Magic stamps the date into the generated leaf files, so their sha256 changes from run to run; the die does not.'
    (folder / 'v4_stage.json').write_text(json.dumps(rec, indent=1) + '\n')
    print(json.dumps({k: v for k, v in rec.items() if k != 'difference_by_layer'}, indent=1))
    if outside:
        raise SystemExit(f'differences outside the windows: {outside}')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
