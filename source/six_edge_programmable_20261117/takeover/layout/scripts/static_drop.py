"""Steady voltage drop on ground, supply and REF at every block, from an extraction with wire resistance on those nets and the
blocks' currents (project Python, numpy/scipy).

  PY -I static_drop.py NETLIST RES_EXT NAME_MAP|- BLOCKS.json GND_PIN VDD_PIN OUT.json [GDS]

With GDS, a supply is tied only at the mesh points ON its metal4 stripes (scripts/stripe_points.py: the net's metal4
covers the point and none of its lower layers do, or a via3 of the net lies within 0.3 um); the pin's own name point is
tied only if it is one of them. Without it, every mesh point inside a stripe's rectangle is tied, and the pin's name
point too (the first method, which also ties lower-layer shapes that only pass under a stripe).

NETLIST: a flat netlist with wire resistors (R lines) and devices (X lines), e.g. the base flow's distributed/native_six_wire.spice.gz
or the accepted flow's res/tt_flat_rc.spice; RES_EXT: Magic's .res.ext of it (rnode records give each mesh point's place);
NAME_MAP: JSON {Magic name: netlist name} when the netlist renamed its nodes (the base flow's distributed/nodes.json.gz), or "-".
Currents: the accepted chip's own table (feasibility_20261107/floorplan/chip2x2/scripts/supply_table.py ROWS: each block's
current in the simulation of the drawn chip, typical while computing and the largest at any time) and the stored-bias block's
5.6 uA (programmable_weights_v4_20261114/floorplan/scripts/chip_wired.py BIAS_SUPPLY); every other block draws none here.
A block's current enters its current-carrying terminals (NMOS source/drain on ground, PMOS source/drain on the supply)
inside its outline (a terminal inside two outlines belongs to the smaller), split equally; all blocks draw at once; the
network is solved from the pin node. Magic's values include its contact resistances (185 ohm per n+ contact, 585 per p+),
so the worst terminal's figure is above what the circuit sees; compare chip with chip, as the accepted table did.
REF: no table of REF currents exists; the REF buffer's own REF terminals (inside BUF_REF) are tied together as the source and
the table gives the resistance to each block's worst REF terminal, i.e. the drop in mV per uA that block draws.
"""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as sla


def opentext(p):
    return (gzip.open(p, "rt") if str(p).endswith(".gz") else open(p)).read()


netlist, resext, namemap, blocks_f, gnd_pin, vdd_pin, out = sys.argv[1:8]
gds = sys.argv[8] if len(sys.argv) > 8 else None
BL = json.loads(Path(blocks_f).read_text())["blocks"]
CUR = {"H1": {"vdd": (110, 190), "vss": (109, 189)}, "H2": {"vdd": (110, 192), "vss": (109, 189)}, "Z": {"vdd": (110, 190), "vss": (109, 189)},
       "LEAN": {"vdd": (28, 30), "vss": (28, 52)}, "LADDER": {"vdd": (22, 25), "vss": (22, 78)}, "BUF_REF": {"vdd": (353, 374), "vss": (355, 364)},
       "PADBUF": {"vdd": (352, 353), "vss": (351, 353)}, "BUF_BIAS1": {"vdd": (110, 131), "vss": (110, 124)},
       "BUF_BIAS2": {"vdd": (108, 131), "vss": (109, 124)}, "BUF2": {"vdd": (55, 111), "vss": (54, 117)}, "BIAS": {"vdd": (5.6, 5.6), "vss": (5.6, 5.6)}}
txt = re.sub(r"\n\+\s*", " ", opentext(netlist))
R = [l.split() for l in txt.splitlines() if l[:1] == "R"]
X = [l.split() for l in txt.splitlines() if l[:1] == "X"]
nm = json.loads(opentext(namemap)) if namemap != "-" else None
xy = {}
for m in re.finditer(r'^rnode "([^"]+)" \S+ \S+ (-?\d+) (-?\d+)', opentext(resext), re.M):
    n = nm.get(m[1]) if nm is not None else m[1]
    if n is not None:
        xy[n] = (int(m[2]) * 0.005, int(m[3]) * 0.005)
par = {}


def find(n):
    par.setdefault(n, n)
    while par[n] != n:
        par[n] = par[par[n]]
        n = par[n]
    return n


for r in R:
    par[find(r[1])] = find(r[2])
boxes = sorted(((role, b["outline_chip_um"]) for role, b in BL.items()), key=lambda rb: (rb[1][2] - rb[1][0]) * (rb[1][3] - rb[1][1]))


def block_at(p):
    for role, (x0, y0, x1, y1) in boxes:
        if x0 - 0.2 <= p[0] <= x1 + 0.2 and y0 - 0.2 <= p[1] <= y1 + 0.2:
            return role
    return None


def network(root, ties=()):
    """the resistor network of one net; `ties` (a set of its nodes) is merged into one node"""
    tie = set(ties)
    rep = (lambda n: "__TIE__" if n in tie else n)
    rs = [(rep(a), rep(b), float(v)) for _, a, b, v, *_ in R if find(a) == root and float(v) > 0 and rep(a) != rep(b)]
    nodes = sorted({x for a, b, v in rs for x in (a, b)})
    idx = {n: i for i, n in enumerate(nodes)}
    rows, cols, vals = [], [], []
    for a, b, v in rs:
        i, j, g = idx[a], idx[b], 1.0 / v
        rows += [i, j, i, j]
        cols += [i, j, j, i]
        vals += [g, g, -g, -g]
    L = sp.csc_matrix((vals, (rows, cols)), shape=(len(nodes), len(nodes)))
    return dict(idx=idx, L=L, rep=rep, nodes=len(nodes))


def solver(net, pin):
    idx, L = net["idx"], net["L"]
    p = idx[net["rep"](pin)]
    keep = np.array([i for i in range(L.shape[0]) if i != p])
    pos = {i: k for k, i in enumerate(keep)}
    lu = sla.splu(L[keep][:, keep].tocsc())

    def volts(inject):
        e = np.zeros(len(keep))
        for n, a in inject.items():
            i = idx.get(net["rep"](n))
            if i is not None and i != p:
                e[pos[i]] += a
        x = lu.solve(e)
        return lambda n: 0.0 if idx.get(net["rep"](n)) in (None, p) else float(x[pos[idx[net["rep"](n)]]])
    return volts


def terminals(root, kinds):
    t = collections.defaultdict(set)
    for x in X:
        pos_ = [q for q in x[1:] if "=" not in q]
        model, nets = pos_[-1], pos_[:-1]
        roles = ("sd", "g", "sd", "b") if "fet" in model else ("r", "r", "b") if "res_" in model else ("c", "c")
        for n, ro in zip(nets, roles):
            if n in par and find(n) == root and n in xy and kinds(model, ro):
                b = block_at(xy[n])
                if b:
                    t[b].add(n)
    return t


# the supplies' metal4 stripes (Tiny Tapeout's template; the same on both chips): all of a supply's stripes are one pin
# node, as the accepted supply table has it. A mesh point lying inside a stripe's rectangle is tied to the pin (the
# .res.ext gives no layer, so a lower-metal point under a stripe is tied too: an approximation, the same for both chips).
STRIPES = {"vss": [(121.0, 122.6), (128.4, 130.0), (260.0, 261.2), (263.7, 265.3)], "vdd": [(124.0, 127.0), (261.9, 263.1), (265.9, 267.5)]}


def on_stripe(rail, n):
    if n not in xy:
        return False
    x, y = xy[n]
    return 5.0 <= y <= 220.76 and any(a <= x <= b for a, b in STRIPES[rail])


res = dict(method=__doc__.strip(), netlist=netlist, rails={})
for rail, pin, fet in (("vss", gnd_pin, "nfet"), ("vdd", vdd_pin, "pfet")):
    root = find(pin)
    terms = terminals(root, lambda model, ro, fet=fet: fet in model and ro == "sd")
    tie = {n for n in par if find(n) == root and on_stripe(rail, n)} | {pin}
    if gds:
        import subprocess
        cand = {n: xy[n] for n in tie if n in xy}
        cj = Path(out).with_name(Path(out).stem + f"_{rail}_candidates.json")
        oj = Path(out).with_name(Path(out).stem + f"_{rail}_stripe_points.json")
        cj.write_text(json.dumps({rail: dict(label={"vss": "VGND", "vdd": "VDPWR"}[rail], points=cand)}))
        subprocess.run([str(Path.home() / ".local/opt/klayout-py/bin/python"), "-B", str(Path(__file__).resolve().parent / "stripe_points.py"),
                        gds, str(cj), str(oj)], check=True, capture_output=True, text=True)
        cls = json.loads(oj.read_text())[rail]
        tie = {n for n, v in cls["points"].items() if v["kind"] in ("stripe", "stack")}
        print(f"{rail}: {len(cand)} points in the stripe footprints, {len(tie)} on the stripes ({cls['counts']})")
        pin = sorted(tie)[0]                       # the solver's reference node: one of the tied stripe points
    net = network(root, ties=tie)
    volts = solver(net, pin)
    rows = {}
    for which in (0, 1):
        inject = collections.defaultdict(float)
        for b, t in terms.items():
            if b in CUR:
                for n in t:
                    inject[n] += CUR[b][rail][which] * 1e-6 / len(t)
        v = volts(inject)
        for b, t in terms.items():
            vs = [v(n) for n in t]
            row = rows.setdefault(b, dict(terminals=len(t), current_uA=CUR.get(b, {}).get(rail)))
            row["typical" if which == 0 else "largest"] = dict(worst_mV=round(max(vs) * 1e3, 3), mean_mV=round(float(np.mean(vs)) * 1e3, 3))
    for b, t in terms.items():
        sample = sorted(t)[:: max(1, len(t) // 60)]
        rows[b]["pin_to_worst_terminal_ohm"] = round(max(volts({n: 1.0})(n) for n in sample), 2)
    # "chip wiring only" (the accepted table's "route"): every block taken as ideal inside, i.e. all mesh points inside a
    # block's outline (the smaller outline where two overlap) are one node; every block draws its current at that node.
    # The accepted table multiplied this by the block's current and compared it with the block's budget. On the selected
    # layout chip wiring also crosses blocks, and those crossing wires are shorted by this too: it can only understate.
    inside = collections.defaultdict(set)
    for n in par:
        if find(n) == root and n in xy and n not in tie:
            b = block_at(xy[n])
            if b in CUR:
                inside[b].add(n)
    groups = {f"__B_{b}__": ns for b, ns in inside.items()}
    rep_of = {n: g for g, ns in groups.items() for n in ns}
    rs = [(rep_of.get(a, "__TIE__" if a in tie else a), rep_of.get(b, "__TIE__" if b in tie else b), float(v)) for _, a, b, v, *_ in R
          if find(a) == root and float(v) > 0]
    rs = [(a, b, v) for a, b, v in rs if a != b]
    nodes2 = sorted({x for a, b, v in rs for x in (a, b)})
    idx2 = {n: i for i, n in enumerate(nodes2)}
    rr, cc, vv = [], [], []
    for a, b, v in rs:
        i, j, g = idx2[a], idx2[b], 1.0 / v
        rr += [i, j, i, j]
        cc += [i, j, j, i]
        vv += [g, g, -g, -g]
    L2 = sp.csc_matrix((vv, (rr, cc)), shape=(len(nodes2), len(nodes2)))
    p2 = idx2["__TIE__"]
    keep2 = np.array([i for i in range(len(nodes2)) if i != p2])
    pos2 = {i: k for k, i in enumerate(keep2)}
    lu2 = sla.splu(L2[keep2][:, keep2].tocsc())
    for which, key in ((0, "typical"), (1, "largest")):
        e = np.zeros(len(keep2))
        for b in inside:
            if f"__B_{b}__" in idx2:
                e[pos2[idx2[f"__B_{b}__"]]] += CUR[b][rail][which] * 1e-6
        x = lu2.solve(e)
        for b in inside:
            g = f"__B_{b}__"
            if g in idx2 and b in rows:
                rows[b].setdefault("chip_wiring_only", {})[key + "_mV"] = round(float(x[pos2[idx2[g]]]) * 1e3, 3)
    for b in inside:
        g = f"__B_{b}__"
        if g in idx2 and b in rows:
            e = np.zeros(len(keep2))
            e[pos2[idx2[g]]] = 1.0
            rows[b].setdefault("chip_wiring_only", {})["alone_ohm"] = round(float(lu2.solve(e)[pos2[idx2[g]]]), 2)
    res["rails"][rail] = dict(pin=f"{pin} and every mesh point on the {rail} stripes ({len(tie)} points tied)", mesh_nodes=net["nodes"],
                              blocks=dict(sorted(rows.items(), key=lambda kv: -kv[1]["typical"]["worst_mV"])))
# REF: the net that carries most device terminals inside BUF_REF besides the supplies
gr, vr = find(gnd_pin), find(vdd_pin)
cnt = collections.Counter()
bx = BL["BUF_REF"]["outline_chip_um"]
for x in X:
    pos_ = [q for q in x[1:] if "=" not in q]
    for n in pos_[:-1]:
        if n in xy and n in par and find(n) not in (gr, vr) and bx[0] <= xy[n][0] <= bx[2] and bx[1] <= xy[n][1] <= bx[3]:
            cnt[find(n)] += 1
# REF is the BUF_REF net reaching the most blocks
best = None
for root, _ in cnt.most_common(12):
    t = terminals(root, lambda model, ro: ro != "b")
    if best is None or len(t) > len(best[1]):
        best = (root, t)
root, terms = best
src = terms.get("BUF_REF", set())
net = network(root, ties=src)
volts = solver(net, next(iter(src)))
rows = {}
for b, t in terms.items():
    if b == "BUF_REF":
        continue
    sample = sorted(t)[:: max(1, len(t) // 60)]
    w = max(sample, key=lambda n: volts({n: 1.0})(n))
    ohm = volts({w: 1.0})(w)
    rows[b] = dict(terminals=len(t), buffer_to_worst_terminal_ohm=round(ohm, 2), mV_per_uA=round(ohm * 1e-3, 4), worst_at_um=[round(c, 2) for c in xy[w]])
res["rails"]["ref"] = dict(net=root, source_terminals_tied=len(src), blocks_reached=len(terms), mesh_nodes=net["nodes"],
                           blocks=dict(sorted(rows.items(), key=lambda kv: -kv[1]["buffer_to_worst_terminal_ohm"])))
Path(out).write_text(json.dumps(res, indent=1) + "\n")
for rail in ("vss", "vdd"):
    print("==", rail, "mesh nodes", res["rails"][rail]["mesh_nodes"])
    for b, r in res["rails"][rail]["blocks"].items():
        print(f"  {b:12s} {r['terminals']:4d} terminals I {str(r['current_uA']):11s} drop worst/mean {r['typical']['worst_mV']:7.3f}/{r['typical']['mean_mV']:7.3f} mV "
              f"(largest currents {r['largest']['worst_mV']:7.3f}) pin->worst {r['pin_to_worst_terminal_ohm']:7.1f} ohm")
print("== ref", res["rails"]["ref"]["net"], "source terminals", res["rails"]["ref"]["source_terminals_tied"])
for b, r in res["rails"]["ref"]["blocks"].items():
    print(f"  {b:12s} {r['terminals']:4d} terminals buffer->worst {r['buffer_to_worst_terminal_ohm']:8.2f} ohm = {r['mV_per_uA']} mV/uA")
