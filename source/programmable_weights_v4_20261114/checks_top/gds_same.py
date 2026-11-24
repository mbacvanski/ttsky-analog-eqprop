"""Design check comparing two GDS files (not the layout strand's gds_equal.py).

Each file's one top cell is flattened; on every layer the two sets of shapes are XORed (as merged regions, so how a
shape is cut into polygons or which cell holds it does not matter), and the labels are compared as a multiset of
(layer, text, x, y). Prints the layers that differ; exit status 0 only if nothing differs.

  ~/.local/opt/klayout-py/bin/python gds_same.py A.gds B.gds [result.json]
"""
import json
import sys
from collections import Counter

import klayout.db as kdb


def load(path):
    ly = kdb.Layout()
    ly.read(path)
    tops = ly.top_cells()
    assert len(tops) == 1, (path, [t.name for t in tops])
    layers = {(i.layer, i.datatype): idx for idx, i in zip(ly.layer_indexes(), ly.layer_infos())}
    return ly, tops[0], layers


def texts(ly, top, layers):
    out = Counter()
    for key, idx in layers.items():
        it = top.begin_shapes_rec(idx)
        it.shape_flags = kdb.Shapes.STexts
        while not it.at_end():
            t = it.shape().text.transformed(it.trans())
            out[(key, t.string, t.x, t.y)] += 1
            it.next()
    return out


if __name__ == "__main__":
    a, ta, la = load(sys.argv[1])
    b, tb, lb = load(sys.argv[2])
    assert a.dbu == b.dbu, (a.dbu, b.dbu)
    differ, shapes = [], [0, 0]
    for key in sorted(set(la) | set(lb)):
        ra = kdb.Region(ta.begin_shapes_rec(la[key])) if key in la else kdb.Region()
        rb = kdb.Region(tb.begin_shapes_rec(lb[key])) if key in lb else kdb.Region()
        shapes[0] += ra.count()
        shapes[1] += rb.count()
        x = ra ^ rb
        if not x.is_empty():
            differ.append(dict(layer=list(key), pieces=x.count(), area_um2=round(x.area() * a.dbu * a.dbu, 4)))
    xa, xb = texts(a, ta, la), texts(b, tb, lb)
    only_a, only_b = xa - xb, xb - xa
    res = dict(a=sys.argv[1], b=sys.argv[2], top_cells=[ta.name, tb.name], cells=[a.cells(), b.cells()],
               layers=[len(la), len(lb)], shapes_flattened=shapes, layers_that_differ=differ,
               labels=[sum(xa.values()), sum(xb.values())], labels_only_in_a=sum(only_a.values()),
               labels_only_in_b=sum(only_b.values()))
    res["same"] = not differ and not only_a and not only_b and set(la) == set(lb)
    print(json.dumps({k: v for k, v in res.items() if k != "layers_that_differ"}))
    print(f"layers that differ: {len(differ)}" + ("" if not differ else " " + json.dumps(differ[:6])))
    print("THE SAME LAYOUT" if res["same"] else "DIFFERENT")
    if len(sys.argv) > 3:
        open(sys.argv[3], "w").write(json.dumps(res, indent=1) + "\n")
    raise SystemExit(0 if res["same"] else 1)
