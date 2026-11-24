"""The n-well/lvtn fix, part 1 (the cells): pw4_shunt, pw4_bridge and pw4_rblock4 drawn again by the earlier chip's own
generator with one switch, and swapped into the die in place; ne_bias_writer copied again from the corrected pw4_shunt.
Part 2, the added n-well, is well_patch.py.

  KPY cellfix_stage.py IN.gds OUT.gds RECORD.json [LEVEL]

LEVEL 1 (default, lock2_w): Magic's 0.825 um from 5 V diffusion to a low-voltage n-well. LEVEL 2 (lock2_h): every drawn
HVI also 0.64 um (0.645 where free) from such a well: XW1N and the shunt's chain moved further, the bridge's recess
deeper, its clamp XCLM up, pw4_bias's XW1N (hv1t) away from the follower well (pw4_bias is swapped too), and the bias
words' writers copied from pw4_shunt drawn with the bridge's XW1N position (PW4_WRITER_SRC=1).

The generator is a copy of programmable_weights_v4_20261114/cells/scripts in cellfix/scripts (it writes into cellfix/
only). PW4_WELLFIX=1 (draw_res.py, draw_rblock4.py) moves the writer's 5 V NMOS XW1N up 0.03 um (gate bar and via with
it), recedes the bridge's chain well 0.045 um above that NMOS, and moves the row's two shunt bus clamps 0.10 um away
from the shunts' chain wells.
1. Switch off: the generator's pw4_shunt, pw4_bridge and pw4_rblock4 must equal IN's cells (flat, every layer, every
   label; the one label pw4_rblock4 carries as "zx" where the generator writes "zx_uq0" excepted), and every cell they
   instantiate must equal IN's cell of that name.
2. Switch on: IN's three cells are cleared and refilled with the corrected cells' shapes and instances (children by name,
   IN's own cells; instance properties kept); "zx_uq0" becomes "zx" as in IN.
3. ne_bias_writer (the words block's two writers) is cleared and refilled from cells.writer on the corrected pw4_shunt,
   as bias_stage.py first made it.
4. Checked: the four cells' outlines and own labels (pins) unchanged, and the refilled cells equal the generator's (flat);
   labels inside a moved device move with it and are listed.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
GEN = HERE.parent / 'cellfix' / 'scripts'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3] / 'layout'))
from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer
import cells                     # noqa: E402

PY = os.environ.get('PY') or sys.executable
INPUTS = {'385756c3f254ff4a1590267aa7d282fad34e5ff206477929a7b217f3b2f96aa7': 'lock2',
          '23388cc15420fe29a9e8a0674d7a3ab2265cfd8cab6c9b919df192bc03f43ad0': 'lock'}
SWAP = ('pw4_shunt', 'pw4_bridge', 'pw4_rblock4')
SWAP2 = SWAP + ('pw4_bias',)
LABEL_FIX = {('pw4_rblock4', 'zx_uq0'): 'zx', ('pw4_bias', 'bw2_uq0'): 'bw2'}
GEN_LABEL = {'pw4_rblock4': {'zx_uq0': 'zx'}, 'pw4_bias': {'bw2_uq0': 'bw2'}}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def generate(fix, out, bias=False, writer_src=False):
    """Run the generator copy with its outputs in `out` (its own layout/, build/, results/). fix: the switch level
    (0 off). bias: also draw pw4_bias (read into the same layout). writer_src: pw4_shunt only, with PW4_WRITER_SRC=1."""
    out = out.resolve()
    (out / 'layout').mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PW4_CELLS_OUT=str(out))
    env.pop('PW4_WELLFIX', None)
    env.pop('PW4_WRITER_SRC', None)
    if fix:
        env['PW4_WELLFIX'] = str(int(fix))
    if writer_src:
        env['PW4_WRITER_SRC'] = '1'
    steps = [['gen_devices.py'], ['draw_res.py', 'shunt']] if writer_src else \
        [['gen_devices.py'], ['draw_res.py', 'shunt', 'bridge'], ['draw_rblock4.py']] + ([['draw_bias.py', 'block']] if bias else [])
    for args in steps:
        with (out / 'generator.log').open('a') as log:
            subprocess.run([PY] + args, cwd=GEN, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    ly = db.Layout(); ly.read(str(out / 'layout' / ('pw4_shunt.gds' if writer_src else 'pw4_rblock4.gds')))
    if bias:
        ly.read(str(out / 'layout' / 'pw4_bias.gds'))       # merged in: shared device cells by name
    return ly


def flat(ly, cell):
    out = {}
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        r = db.Region(cell.begin_shapes_rec(li)).merged()
        if not r.is_empty():
            out[(info.layer, info.datatype)] = r
    return out


def texts(ly, cell):
    out = set()
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        it = cell.begin_shapes_rec(li)
        while not it.at_end():
            s = it.shape()
            if s.is_text():
                p = it.trans() * db.Point(s.text.x, s.text.y)
                t = s.text_string
                out.add((info.layer, info.datatype, t, p.x, p.y))
            it.next()
    return out


def own_texts(ly, cell):
    """The cell's pins: its own labels that stand on a pin-purpose shape (layer/16) of the same layer. Labels inside its
    children, and its own labels without a pin shape (an internal net's name, which moves with its wire), are left out."""
    out = set()
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        pl = ly.find_layer(info.layer, 16)
        pins = db.Region(cell.shapes(pl)) if pl is not None else db.Region()
        for s in cell.shapes(li).each():
            if s.is_text() and not pins.interacting(db.Region(db.Box(s.text.x - 1, s.text.y - 1, s.text.x + 1, s.text.y + 1))).is_empty():
                out.add((info.layer, info.datatype, s.text_string, s.text.x, s.text.y))
    return out


def same(la, ca, lb, cb, label_fix=None):
    fa, fb = flat(la, ca), flat(lb, cb)
    diff = {f'{k[0]}/{k[1]}': round((fa.get(k, db.Region()) ^ fb.get(k, db.Region())).area() * la.dbu ** 2, 6)
            for k in set(fa) | set(fb) if not (fa.get(k, db.Region()) ^ fb.get(k, db.Region())).is_empty()}
    ta, tb = texts(la, ca), texts(lb, cb)
    if label_fix:
        ta = {(l, d, label_fix.get(t, t), x, y) for (l, d, t, x, y) in ta}
    return diff, sorted(ta ^ tb)


def refill(dst, dcell, src, scell):
    """dcell (in dst) gets scell's (in src) shapes and instances; children by name; properties translated."""
    pmap = lambda pid: dst.properties_id(src.properties(pid)) if pid else 0
    dcell.clear()
    for li in src.layer_indexes():
        dl = dst.layer(src.get_info(li))
        for s in scell.shapes(li).each():
            if s.is_polygon():
                obj = s.polygon
            elif s.is_box():
                obj = s.box
            elif s.is_path():
                obj = s.path
            elif s.is_text():
                obj = s.text
            else:
                raise ValueError(('shape type', s))
            dcell.shapes(dl).insert(obj, pmap(s.prop_id)) if s.prop_id else dcell.shapes(dl).insert(obj)
    for inst in scell.each_inst():
        child = dst.cell(src.cell(inst.cell_index).name)
        assert child is not None, src.cell(inst.cell_index).name
        a = inst.cell_inst
        arr = db.CellInstArray(child.cell_index(), a.cplx_trans if a.is_complex() else a.trans)
        assert not a.is_regular_array()
        dcell.insert(arr, pmap(inst.prop_id)) if inst.prop_id else dcell.insert(arr)


def main(src, dst, record, level=1):
    raw = Path(src).read_bytes()
    which = INPUTS.get(sha(raw))
    assert which, 'input is neither the lock build nor lock2'
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell()
    rec = dict(input=which, input_gds_sha256=sha(raw))
    if level != 1:
        rec['level'] = level
    swap = SWAP if level == 1 else SWAP2
    # 1. the generator, switch off, against the die's cells
    work = Path(dst).parent / (Path(dst).stem + '_generator')
    g0 = generate(False, work / 'switch_off', bias=(level != 1))
    check = {}
    for name in swap:
        lf = GEN_LABEL.get(name)
        d, t = same(g0, g0.cell(name), ly, ly.cell(name), lf)
        check[name] = dict(layers_differing=d, labels_differing=[list(x) for x in t])
        assert not d and not t, (name, d, t)
    children = sorted({g0.cell(i.cell_index).name for n in swap for i in g0.cell(n).each_inst()} - set(swap))
    for name in children:
        d, t = same(g0, g0.cell(name), ly, ly.cell(name))
        assert not d and not t, (name, d, t)
    rec['generator_reproduces_frozen'] = dict(cells=check, children_equal=children)
    # 2. switch on, swap
    g1 = generate(level, work / 'switch_on', bias=(level != 1))
    before = {n: (ly.cell(n).dbbox(), own_texts(ly, ly.cell(n))) for n in swap + ('ne_bias_writer',)}
    for name in swap:                                               # children first (pw4_rblock4 after the two cells)
        refill(ly, ly.cell(name), g1, g1.cell(name))
    for (cname, old), new in LABEL_FIX.items():
        c = ly.cell(cname)
        for li in ly.layer_indexes():
            for s in c.shapes(li).each():
                if s.is_text() and s.text_string == old:
                    t = s.text; t.string = new; s.text = t
    swapped = {}
    for name in swap:
        lf = GEN_LABEL.get(name)
        d, t = same(g1, g1.cell(name), ly, ly.cell(name), lf)
        assert not d and not t, (name, d, t)
        swapped[name] = 'equal to the corrected generator cell (flat, every layer and label)'
    rec['swapped'] = swapped
    # 3. the writer copy (level 2: from pw4_shunt drawn with the bridge's XW1N position, which has room above it here)
    if level == 1:
        tmp, wrec = cells.writer(ly, name='ne_bias_writer_cellfix', pins=False)
        refill(ly, ly.cell('ne_bias_writer'), ly, tmp)
        ly.delete_cell(tmp.cell_index())
    else:
        gw = generate(level, work / 'writer_source', writer_src=True)
        tmp, wrec = cells.writer(gw, name='ne_bias_writer_cellfix', pins=False)
        refill(ly, ly.cell('ne_bias_writer'), gw, tmp)
    w = ly.cell('ne_bias_writer')
    rec['writer'] = dict(source='cells.writer on the corrected pw4_shunt', devices=wrec if isinstance(wrec, (dict, list)) else str(wrec))
    # 4. outlines and labels unchanged; what differs, per cell, against IN
    old = db.Layout(); old.read(str(src))
    rec['cells'] = {}
    for name in swap + ('ne_bias_writer',):
        bb, tx = before[name]
        assert ly.cell(name).dbbox() == bb, (name, bb, ly.cell(name).dbbox())
        assert own_texts(ly, ly.cell(name)) == tx, (name, sorted(own_texts(ly, ly.cell(name)) ^ tx)[:6])
        d, t = same(old, old.cell(name), ly, ly.cell(name))
        rec['cells'][name] = dict(outline_um=str(bb), own_labels_pins='unchanged', layers_changed_um2=d,
                                  labels_moved_with_devices=[list(x) for x in t])
    save(ly, top, dst)
    rec['output_gds_sha256'] = sha(Path(dst).read_bytes())
    Path(record).write_text(json.dumps(rec, indent=1, default=str) + '\n')
    print(json.dumps({k: v for k, v in rec.items() if k != 'generator_reproduces_frozen'}, indent=1, default=str))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 1)
