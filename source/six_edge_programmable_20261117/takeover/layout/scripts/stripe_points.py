"""Which points of a supply net's resistance network lie on its metal4 stripes (KLayout Python).

  KPY stripe_points.py GDS POINTS.json OUT.json

POINTS.json: {net: {"label": "VGND", "points": {name: [x, y], ...}}}, the candidate points (inside a stripe's footprint).
For each point: the layers of that same net (metal-only trace li..metal4 with their cuts, as corridor_check.py) that
cover it, and the cuts of the net within 0.3 um. A point is on the stripe when metal4 of the net covers it and no
lower layer of the net does (only the stripe can carry it), or when lower layers do but a via3 cut of the net lies within
0.3 um (a via stack under the stripe, where the stripe and the stack meet). Any other point is a lower-layer shape that
merely passes under the stripe; it is left on its own wires.
"""
import json
import sys
from pathlib import Path

import klayout.db as db

gds, pts_f, out = sys.argv[1:4]
CON = [("li", 67, 20), ("mcon", 67, 44), ("met1", 68, 20), ("via", 68, 44), ("met2", 69, 20), ("via2", 69, 44),
       ("met3", 70, 20), ("via3", 70, 44), ("met4", 71, 20)]
ly = db.Layout(); ly.read(gds); top = ly.top_cell(); dbu = ly.dbu
regs = {}
for n, l, d in CON:
    li = ly.find_layer(l, d)
    r = db.Region() if li is None else db.Region(top.begin_shapes_rec(li)); r.merge(); regs[n] = r
capm = db.Region(top.begin_shapes_rec(ly.layer(89, 44))); capm.merge()
regs["via3"] = regs["via3"] - capm
flat = db.Layout(); flat.dbu = dbu; ft = flat.create_cell("F"); idx = {}
for k, (n, r) in enumerate(regs.items()):
    idx[n] = flat.layer(k + 1, 0); ft.shapes(idx[n]).insert(r)
l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(flat, ft, []))
L = {n: l2n.make_layer(idx[n], n) for n in regs}
for n in regs:
    l2n.connect(L[n])
order = [c[0] for c in CON]
for a, b in zip(order[:-1], order[1:]):
    l2n.connect(L[a], L[b])
l2n.extract_netlist()
lab_net = {}
for li in ly.layer_indexes():
    info = ly.get_info(li)
    if info.layer != 71:
        continue
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        s = it.shape()
        if s.is_text() and s.text.string in ("VGND", "VDPWR"):
            t = s.text.transformed(it.trans())
            n = l2n.probe_net(L["met4"], db.DPoint(t.x * dbu, t.y * dbu))
            if n is not None:
                lab_net.setdefault(s.text.string, n)
        it.next()
cand = json.loads(Path(pts_f).read_text())
res = {}
for net, spec in cand.items():
    n = lab_net[spec["label"]]
    shapes = {lay: l2n.shapes_of_net(n, L[lay], True) for lay in regs}
    rows = {}
    counts = {"stripe": 0, "stack": 0, "under": 0}
    for name, (x, y) in spec["points"].items():
        p = db.Point(round(x / dbu), round(y / dbu))
        probe = db.Region(db.Box(p.x - 1, p.y - 1, p.x + 1, p.y + 1))
        on = [lay for lay in ("li", "met1", "met2", "met3", "met4") if not (shapes[lay] & probe).is_empty()]
        near = db.Region(db.Box(p.x - round(0.3 / dbu), p.y - round(0.3 / dbu), p.x + round(0.3 / dbu), p.y + round(0.3 / dbu)))
        v3 = not (shapes["via3"] & near).is_empty()
        if on == ["met4"]:
            kind = "stripe"
        elif "met4" in on and v3:
            kind = "stack"
        else:
            kind = "under"
        counts[kind] += 1
        rows[name] = dict(layers=on, via3_within_0p3um=v3, kind=kind)
    res[net] = dict(label=spec["label"], counts=counts, points=rows)
    print(net, spec["label"], counts)
Path(out).write_text(json.dumps(res) + "\n")
