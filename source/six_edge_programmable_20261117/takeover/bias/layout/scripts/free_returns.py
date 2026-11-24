"""Free the sources of the two ground-return switches in `ne_return` (pins b1, b2) from VSS, at top level only.

On the selected die (bbf78759) three top-level shapes tie them: an m2 strap joining b1 to b2, an m1 strap joining b2 to
the cell's guard-ring tap, and two L-shaped m1 VSS straps (from `pw4_mid` on the left and `ext_sw` on the right) that
end on b2's m1 bar. This removes the two straps, trims the two L pieces back to 0.14 um from b2's bar, and joins them
again over the top of the cell through the guard-ring tap's m1, so that the tap and both neighbours stay on VSS through
metal. Nothing inside `ne_return` changes.

  free(layout, top) -> record      (used by bias_stage.py)
  KPY free_returns.py PARENT.gds.gz OUT.gds     (stand-alone, with the connectivity audit)
"""
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[3]
sys.path.insert(0, str(SIX / 'layout'))
from connectivity import Connectivity, METALS  # noqa: E402

# ne_return at r180 180090,45005: die = (180.09 - x, 45.005 - y)
PIN = {'b1': ('m2', 176.68, 41.505), 'b2': ('m2', 175.58, 42.688), 'tap': ('m1', 176.88, 44.92)}
STRAP_M2 = db.Box(175580, 41060, 176680, 41210)          # b1 - b2
STRAP_M1 = db.Box(176340, 44100, 176490, 45010)          # b2 - tap
L_LEFT = db.Polygon([db.Point(*p) for p in ((175010, 44100), (175010, 44290), (171780, 44290), (171780, 44440),
                                            (175160, 44440), (175160, 44100))])
L_RIGHT = db.Polygon([db.Point(*p) for p in ((178620, 44100), (178620, 44440), (182000, 44440), (182000, 44290),
                                             (178770, 44290), (178770, 44100))])
# replacement VSS path: left piece, riser, bar through the tap's m1, riser, right piece (m1 spacing 0.14 to b2's bar,
# which is 174880..178880 x 44080..44340)
NEW_M1 = [db.Box(171780, 44290, 174740, 44440), db.Box(174440, 44290, 174740, 45060), db.Box(174440, 44780, 179320, 45060),
          db.Box(179020, 44290, 179320, 45060), db.Box(179020, 44290, 182000, 44440)]


def _take(shapes, want):
    found = [s for s in shapes.each_overlapping(want.bbox()) if
             (s.is_box() and isinstance(want, db.Box) and s.box == want) or
             (not isinstance(want, db.Box) and s.polygon == want)]
    if len(found) != 1:
        raise ValueError(('expected exactly one top-level shape', want.to_s(), len(found)))
    return found[0]


def free(layout, top):
    m1 = top.shapes(layout.layer(*METALS['m1']))
    m2 = top.shapes(layout.layer(*METALS['m2']))
    removed = []
    for shapes, want, name in ((m2, STRAP_M2, 'm2 strap b1-b2'), (m1, STRAP_M1, 'm1 strap b2-tap'),
                               (m1, L_LEFT, 'm1 VSS piece from pw4_mid'), (m1, L_RIGHT, 'm1 VSS piece from ext_sw')):
        s = _take(shapes, want)
        removed.append([name, s.bbox().to_s()])
        s.delete()
    for b in NEW_M1:
        m1.insert(b)
    return dict(removed=removed, added_m1=[b.to_s() for b in NEW_M1])


def label_nets(layout, top, con):
    """Every label of every hierarchy level, mapped to the die net it sits on."""
    lbl = {67: 'li', 68: 'm1', 69: 'm2', 70: 'm3', 71: 'm4'}
    out = {}
    for num, metal in lbl.items():
        for dt in (5, 16):
            ix = layout.find_layer(num, dt)
            if ix is None:
                continue
            it = top.begin_shapes_rec(ix)
            while not it.at_end():
                s = it.shape()
                if s.is_text():
                    p = it.trans() * db.Point(s.text.x, s.text.y)
                    path = '/'.join(f'{e.inst().cell.name}@{e.inst().trans.to_s()}' for e in it.path()) or 'TOP'
                    out[f'{path}:{s.text.string}:{p.x}:{p.y}:{metal}'] = con.probe(metal, p.x / 1000, p.y / 1000)
                it.next()
    return out


def audit(before_layout, after_layout):
    """Compare label-to-net partitions: only b1 and b2 of ne_return may leave VSS, nothing else may change."""
    b = label_nets(before_layout, before_layout.top_cell(), Connectivity(before_layout, before_layout.top_cell()))
    a = label_nets(after_layout, after_layout.top_cell(), Connectivity(after_layout, after_layout.top_cell()))
    assert b.keys() == a.keys()
    def groups(m):
        g = defaultdict(set)
        for k, v in m.items():
            g[v].add(k)
        return {frozenset(v) for v in g.values()}
    gb, ga = groups(b), groups(a)
    lost = [sorted(x)[:3] for x in gb - ga]
    new = [sorted(x)[:3] for x in ga - gb]
    moved = sorted(k for k in b if k.startswith('ne_return@') and k.split(':')[1] in ('b1', 'b2'))
    return dict(label_count=len(b), changed_groups_before=len(gb - ga), changed_groups_after=len(ga - gb),
                examples_before=lost[:4], examples_after=new[:6], ne_return_source_labels=moved)


if __name__ == '__main__':
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    raw = gzip.decompress(src.read_bytes()) if src.suffix == '.gz' else src.read_bytes()
    before = db.Layout(); before.read_bytes(raw)
    after = db.Layout(); after.read_bytes(raw)
    rec = free(after, after.top_cell())
    con = Connectivity(after, after.top_cell())
    nets = {k: con.probe(*v) for k, v in PIN.items()}
    old = Connectivity(before, before.top_cell())
    vss = old.probe('m1', 176.88, 44.92)
    rec['nets_after'] = nets
    rec['tap_on_global_vss'] = nets['tap'] == con.probe('m2', 116.265, 99.5)
    rec['b1_b2_free'] = len({nets['b1'], nets['b2'], nets['tap']}) == 3
    rec['audit'] = audit(before, after)
    after.write(str(out))
    print(json.dumps(rec, indent=1))
