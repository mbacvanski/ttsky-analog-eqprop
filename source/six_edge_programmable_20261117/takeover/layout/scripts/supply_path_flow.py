"""Where a block's supply resistance lies: the current through every wire resistor when 1 A flows from the supply's stripes
(all of their metal one node) into the block (all of its own mesh points one node, the accepted "chip wiring only" figure).
Project Python.

  PY -I supply_path_flow.py RES_DIR BLOCKS.json OUT.json BLOCK[,BLOCK...] [vdd|vss] [GDS]

With GDS, the supply is tied only at the mesh points that lie ON the metal4 stripes (scripts/stripe_points.py on the
GDS: the net's metal4 covers the point and none of its lower layers do, or a via3 of the net is within 0.3 um).
Without it, every mesh point inside a stripe's rectangle is tied, the net's own name point too (the first method;
it also ties lower-layer shapes that only pass under a stripe).

For each block: the chip-wiring resistance, and every resistor that carries at least 2% of the current, with its share
of the current, its share of the drop (I*R / total), its two end points (Magic's mesh points, um), and whether it is a
contact or via (both ends at one place) or a stretch of wire.
"""
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as sla

res_dir, blocks_f, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
which = sys.argv[4].split(";") if ";" in sys.argv[4] else sys.argv[4].split(",")  # ';' for role names with commas (NEW:cell@x,y)
rail = sys.argv[5] if len(sys.argv) > 5 else "vdd"
gds = sys.argv[6] if len(sys.argv) > 6 else None
pin = "VDPWR" if rail == "vdd" else "VGND"
BL = json.loads(Path(blocks_f).read_text())["blocks"]
which = [w if w in BL else next((k for k in BL if k.startswith(w)), w) for w in which]  # a role, or the first role it begins
STRIPES = {"vss": [(121.0, 122.6), (128.4, 130.0), (260.0, 261.2), (263.7, 265.3)], "vdd": [(124.0, 127.0), (261.9, 263.1), (265.9, 267.5)]}
spx = re.sub(r"\n\+\s*", " ", (res_dir / "tt_flat_rc.spice").read_text())
R = [l.split() for l in spx.splitlines() if l[:1] == "R"]
xy = {m[1]: (int(m[2]) * 0.005, int(m[3]) * 0.005) for m in re.finditer(r'^rnode "([^"]+)" \S+ \S+ (-?\d+) (-?\d+)', (res_dir / "tt_flat.res.ext").read_text(), re.M)}
par = {}


def find(n):
    par.setdefault(n, n)
    while par[n] != n:
        par[n] = par[par[n]]
        n = par[n]
    return n


for r in R:
    par[find(r[1])] = find(r[2])
root = find(pin)
mesh = [(r[0], r[1], r[2], float(r[3])) for r in R if find(r[1]) == root and float(r[3]) > 0]
boxes = sorted(((role, b["outline_chip_um"]) for role, b in BL.items()), key=lambda rb: (rb[1][2] - rb[1][0]) * (rb[1][3] - rb[1][1]))


def block_at(p):
    for role, (x0, y0, x1, y1) in boxes:
        if x0 - 0.2 <= p[0] <= x1 + 0.2 and y0 - 0.2 <= p[1] <= y1 + 0.2:
            return role
    return None


def in_footprint(n):
    if n not in xy:
        return False
    x, y = xy[n]
    return 5.0 <= y <= 220.76 and any(a <= x <= b for a, b in STRIPES[rail])


TRUE = None
if gds:
    import subprocess
    cand = {n: xy[n] for n in {q for r in mesh for q in (r[1], r[2])} if in_footprint(n)}
    cj, oj = out.with_name(out.stem + f"_{rail}_candidates.json"), out.with_name(out.stem + f"_{rail}_stripe_points.json")
    cj.write_text(json.dumps({rail: dict(label=pin, points=cand)}))
    subprocess.run([str(Path.home() / ".local/opt/klayout-py/bin/python"), "-B", str(Path(__file__).resolve().parent / "stripe_points.py"),
                    gds, str(cj), str(oj)], check=True, capture_output=True, text=True)
    cls = json.loads(oj.read_text())[rail]
    TRUE = {n for n, v in cls["points"].items() if v["kind"] in ("stripe", "stack")}
    print(f"stripe points: {len(cand)} in the footprints, {len(TRUE)} on the stripes ({cls['counts']})")


def on_stripe(n):
    return (n in TRUE) if TRUE is not None else in_footprint(n)


result = {}
for blk in which:
    def rep(n):
        if (n == pin and TRUE is None) or on_stripe(n):
            return "__PIN__"
        if n in xy and block_at(xy[n]) == blk:
            return "__BLK__"
        return n
    rs = [(name, rep(a), rep(b), v, a, b) for name, a, b, v in mesh]
    rs = [q for q in rs if q[1] != q[2]]
    nodes = sorted({x for q in rs for x in (q[1], q[2])})
    idx = {n: i for i, n in enumerate(nodes)}
    rows, cols, vals = [], [], []
    for _, a, b, v, _, _ in rs:
        i, j, g = idx[a], idx[b], 1.0 / v
        rows += [i, j, i, j]
        cols += [i, j, j, i]
        vals += [g, g, -g, -g]
    L = sp.csc_matrix((vals, (rows, cols)), shape=(len(nodes), len(nodes)))
    p = idx["__PIN__"]
    keep = np.array([i for i in range(len(nodes)) if i != p])
    pos = {i: k for k, i in enumerate(keep)}
    e = np.zeros(len(keep))
    e[pos[idx["__BLK__"]]] = 1.0
    x = sla.splu(L[keep][:, keep].tocsc()).solve(e)
    V = lambda n: 0.0 if idx[n] == p else float(x[pos[idx[n]]])   # noqa: E731
    total = V("__BLK__")
    segs = []
    for name, a, b, v, a0, b0 in rs:
        i = (V(a) - V(b)) / v
        if abs(i) >= 0.02:
            pa, pb = xy.get(a0), xy.get(b0)
            segs.append(dict(r_ohm=round(v, 3), current_share=round(abs(i), 3), drop_share=round(abs(i) * v / total, 4),
                             a=[round(c, 3) for c in pa] if pa else a, b=[round(c, 3) for c in pb] if pb else b,
                             kind="contact/via" if pa and pb and abs(pa[0] - pb[0]) < 0.02 and abs(pa[1] - pb[1]) < 0.02 else "wire",
                             a_end="block" if a == "__BLK__" else "stripe" if a == "__PIN__" else "", b_end="block" if b == "__BLK__" else "stripe" if b == "__PIN__" else ""))
    segs.sort(key=lambda s: -s["drop_share"])
    result[blk] = dict(rail=rail, chip_wiring_ohm=round(total, 2), segments_carrying_2pct=len(segs),
                       drop_in_contacts_and_vias=round(sum(s["drop_share"] for s in segs if s["kind"] != "wire"), 3),
                       drop_in_wire=round(sum(s["drop_share"] for s in segs if s["kind"] == "wire"), 3), segments=segs[:80])
    print(f"== {blk} {rail}: {total:.2f} ohm chip wiring; {len(segs)} resistors carry >= 2%; drop in contacts/vias {result[blk]['drop_in_contacts_and_vias']:.2f}, in wire {result[blk]['drop_in_wire']:.2f}")
    for s in segs[:14]:
        print(f"   {s['kind']:11s} R {s['r_ohm']:8.3f}  I share {s['current_share']:5.3f}  drop share {s['drop_share']:6.4f}  {s['a']} -> {s['b']} {s['a_end']}{s['b_end']}")
out.write_text(json.dumps(result, indent=1) + "\n")
