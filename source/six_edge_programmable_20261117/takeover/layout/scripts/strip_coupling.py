"""Metal over polysilicon resistor bodies: the coupling no extraction holds (KLayout Python).

  KPY strip_coupling.py GDS FLAT.ext OUT.json

Magic's SKY130 extraction defines metal-to-polysilicon capacitance only for polysilicon that is not a resistor
(sky130A.tech, extract style ngspice: `defaultoverlap allmX metalX allpolynonres active ...`), so a wire over a resistor
strip couples to it in silicon but in no extracted netlist. This measures, for every resistor body (poly 66/20 under the
resistor marker 66/13) of the GDS:
  - every piece of li1 / metal1..metal4 over it that reaches the body directly: the metal's overlap with the body less any
    conductor of a lower layer in between (a lower conductor shields; Magic treats ordinary poly the same way);
  - whether that metal is the body's own block's (the top-level instance the strip is drawn in) or not (the chip's routing,
    or another block's metal);
  - the aggressor net: a metal-only trace (li1..metal4 with contacts and vias, poly and diffusion through licon) probed at
    the overlap, named by the nodes of FLAT.ext (Magic's flat extraction of this GDS; its node records give a point per node);
  - the capacitance Magic WOULD extract if the strip were ordinary poly, from the PDK's own values for that metal over
    allpolynonres (nominal style; aF/um2 area, aF/um fringe from the metal's edges over the body and from the body's edges
    under the metal);
  - where along the strip it sits: the fraction of the way from the strip's end on terminal 1 to its end on terminal 2
    (terminals as FLAT.ext's device record lists them).
"""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

import klayout.db as db

gds, extf, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
AREA = {"li": 94.16, "m1": 44.81, "m2": 24.50, "m3": 16.06, "m4": 10.01}          # aF/um2, metal over allpolynonres
SIDE_M = {"li": 51.85, "m1": 46.72, "m2": 41.22, "m3": 43.53, "m4": 38.11}        # aF/um, metal edge over poly
SIDE_P = {"li": 25.14, "m1": 16.69, "m2": 11.17, "m3": 9.18, "m4": 6.35}          # aF/um, poly edge under metal
ORDER = ["li", "m1", "m2", "m3", "m4"]

ly = db.Layout()
ly.read(gds)
top, dbu = ly.top_cell(), ly.dbu


def reg_of(cell, l, d, flat=True):
    li = ly.find_layer(l, d)
    if li is None:
        return db.Region()
    r = db.Region(cell.begin_shapes_rec(li)) if flat else db.Region(cell.shapes(li))
    r.merge()
    return r


LD = dict(poly=(66, 20), rmark=(66, 13), licon=(66, 44), li=(67, 20), mcon=(67, 44), m1=(68, 20), via=(68, 44), m2=(69, 20),
          via2=(69, 44), m3=(70, 20), via3=(70, 44), m4=(71, 20), capm=(89, 44), diff=(65, 20), tap=(65, 44))
R = {k: reg_of(top, *v) for k, v in LD.items()}
body = R["poly"] & R["rmark"]
body.merge()
pcond = R["poly"] - R["rmark"]
dcond = R["diff"] - R["poly"]
via3c = R["via3"] - R["capm"]
conn = dict(pcond=pcond, dcond=dcond, tap=R["tap"], licon=R["licon"], li=R["li"], mcon=R["mcon"], m1=R["m1"], via=R["via"], m2=R["m2"],
            via2=R["via2"], m3=R["m3"], via3=via3c, m4=R["m4"])
flat = db.Layout()
flat.dbu = dbu
ft = flat.create_cell("FLAT")
idx = {}
for k, (n, r) in enumerate(conn.items()):
    idx[n] = flat.layer(k + 1, 0)
    ft.shapes(idx[n]).insert(r)
l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(flat, ft, []))
L = {n: l2n.make_layer(idx[n], n) for n in conn}
for n in conn:
    l2n.connect(L[n])
for a, b in [("pcond", "licon"), ("dcond", "licon"), ("tap", "licon"), ("licon", "li"), ("li", "mcon"), ("mcon", "m1"), ("m1", "via"),
             ("via", "m2"), ("m2", "via2"), ("via2", "m3"), ("m3", "via3"), ("via3", "m4")]:
    l2n.connect(L[a], L[b])
l2n.extract_netlist()


def probe(layer, x_um, y_um):
    n = l2n.probe_net(L[layer], db.DPoint(x_um, y_um))
    return None if n is None else n.cluster_id


# ---- Magic's node names, by the point of each node record
ext = (gzip.open(extf, "rt") if extf.endswith(".gz") else open(extf)).read()
TYPE = {"p": ["pcond"], "xpc": ["pcond", "li"], "pc": ["pcond", "li"], "pdif": ["dcond"], "ndif": ["dcond"], "mvndif": ["dcond"], "mvpdif": ["dcond"],
        "pdc": ["dcond", "li"], "ndc": ["dcond", "li"], "psd": ["tap"], "nsd": ["tap"], "ppd": ["tap"], "nnd": ["tap"], "li": ["li"], "locali": ["li"],
        "m1": ["m1"], "metal1": ["m1"], "m2": ["m2"], "metal2": ["m2"], "m3": ["m3"], "metal3": ["m3"], "m4": ["m4"], "metal4": ["m4"]}
cl_names = collections.defaultdict(set)
unplaced = collections.Counter()
for m in re.finditer(r'^(?:node|substrate) "([^"]+)" \S+ \S+ (-?\d+) (-?\d+) (\S+)', ext, re.M):
    name, x, y, t = m[1], int(m[2]) * 0.005 + 0.0025, int(m[3]) * 0.005 + 0.0025, m[4]
    hit = None
    for layer in TYPE.get(t, []):
        hit = probe(layer, x, y)
        if hit is not None:
            break
    if hit is None:
        unplaced[t] += 1
        continue
    cl_names[hit].add(name)
equiv = collections.defaultdict(set)
for a, b in re.findall(r'^equiv "([^"]+)" "([^"]+)"', ext, re.M):
    equiv[a].add(b)
# labels found on each cluster (for readable aggressor names)
LABEL = {67: "li", 68: "m1", 69: "m2", 70: "m3", 71: "m4"}
cl_labels = collections.defaultdict(set)
for li_ in ly.layer_indexes():
    info = ly.get_info(li_)
    if info.layer not in LABEL:
        continue
    it = top.begin_shapes_rec(li_)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text.transformed(it.trans())
            c = probe(LABEL[info.layer], t.x * dbu, t.y * dbu)
            if c is not None:
                cl_labels[c].add(s.text.string)
        it.next()

# ---- resistor devices of FLAT.ext
devs = []
for m in re.finditer(r'^device rsubckt (\S+) (-?\d+) (-?\d+) (-?\d+) (-?\d+)(.*)$', ext, re.M):
    q = re.findall(r'"([^"]+)"', m[6])
    params = dict(re.findall(r"(\w+)=(\S+)", m[6]))
    devs.append(dict(model=m[1], x=int(m[2]) * 0.005, y=int(m[3]) * 0.005, l_um=round(int(params.get("l", 0)) * 0.005, 3), body_node=q[1],
                     t1=q[2], t2=q[3] if len(q) > 3 else None))

# ---- which top-level instance each body belongs to; its own metal
inst_bodies, inst_metal = [], []
for inst in top.each_inst():
    tr = inst.cplx_trans
    bi = (reg_of(inst.cell, *LD["poly"]) & reg_of(inst.cell, *LD["rmark"])).transformed(tr)
    bi.merge()
    om = {k: reg_of(inst.cell, *LD[k]).transformed(tr) for k in ORDER}
    inst_bodies.append((inst, bi))
    inst_metal.append(om)
own_top_bodies = (reg_of(top, *LD["poly"], flat=False) & reg_of(top, *LD["rmark"], flat=False))

all_metal = {k: R[k] for k in ORDER}
rows, unmatched = [], []
bpolys = list(body.each())
bidx = db.Region()
for k, d in enumerate(devs):
    p = db.Point(round((d["x"] + 0.0025) / dbu), round((d["y"] + 0.0025) / dbu))
    hit = [bp for bp in bpolys if bp.inside(p)]
    if len(hit) != 1:
        unmatched.append(dict(device=k, at=[d["x"], d["y"]], hits=len(hit)))
        continue
    bp = hit[0]
    br = db.Region(bp)
    win = bp.bbox().enlarged(2000, 2000)
    # owner
    owner = None
    for j, (inst, bi) in enumerate(inst_bodies):
        if not (bi & br).is_empty():
            owner = j
            break
    own = inst_metal[owner] if owner is not None else {k: db.Region() for k in ORDER}
    # ends: the conducting poly that touches the body
    ends = [q for q in (pcond & win).interacting(br).each()]
    end_nets = []
    for q in ends:
        c = q.bbox().center()
        pt = q.bbox().center()
        # a point of the end piece next to the body
        shared = (db.Region(q).sized(1) & br)
        sp = shared.bbox().center() if not shared.is_empty() else pt
        tz = db.Region(q).decompose_trapezoids_to_region()
        inner = next(tz.each()).bbox().center()
        end_nets.append((probe("pcond", inner.x * dbu, inner.y * dbu), sp))
    names = [sorted(cl_names.get(n, set())) for n, _ in end_nets]
    # orient: end A on t1, end B on t2
    a_idx = next((i for i, nm in enumerate(names) if d["t1"] in nm), None)
    b_idx = next((i for i, nm in enumerate(names) if d["t2"] in nm and i != a_idx), None)
    if a_idx is None or b_idx is None:
        if len(end_nets) == 2:
            a_idx, b_idx = 0, 1
        oriented = False
    else:
        oriented = True
    A = end_nets[a_idx][1] if a_idx is not None and a_idx < len(end_nets) else bp.bbox().p1
    B = end_nets[b_idx][1] if b_idx is not None and b_idx < len(end_nets) else bp.bbox().p2
    ax, ay, bx, by = A.x, A.y, B.x, B.y
    L2 = float((bx - ax) ** 2 + (by - ay) ** 2) or 1.0

    def frac(pt):
        return max(0.0, min(1.0, ((pt.x - ax) * (bx - ax) + (pt.y - ay) * (by - ay)) / L2))
    below = db.Region()
    pieces = []
    for layer in ORDER:
        allw = all_metal[layer] & win
        ownw = own[layer] & win
        for who, reg in (("own", ownw), ("other", allw - ownw)):
            ov = reg & br
            if ov.is_empty():
                continue
            raw = ov.area() * dbu * dbu
            direct = ov - below
            for piece in direct.each():
                pr = db.Region(piece)
                tz = pr.decompose_trapezoids_to_region()
                c = next(tz.each()).bbox().center()
                net = probe(layer, c.x * dbu, c.y * dbu)
                a_um2 = piece.area() * dbu * dbu
                e_m = (reg.edges() & pr.sized(1)).length() * dbu      # the metal's own edges inside the piece
                e_p = (br.edges() & pr.sized(1)).length() * dbu       # the body's edges under the piece
                cent = piece.bbox().center()
                pieces.append(dict(layer=layer, who=who, net=net, area_um2=round(a_um2, 5), metal_edge_um=round(e_m, 4), body_edge_um=round(e_p, 4),
                                   c_area_aF=round(a_um2 * AREA[layer], 4), c_fringe_aF=round(e_m * SIDE_M[layer] + e_p * SIDE_P[layer], 4),
                                   frac_from_t1=round(frac(cent), 4), at_um=[round(cent.x * dbu, 3), round(cent.y * dbu, 3)]))
        below += allw
        below.merge()
    bb = bp.bbox()
    rows.append(dict(device=k, model=d["model"], l_um=d["l_um"], at_um=[round(d["x"], 3), round(d["y"], 3)], body_um2=round(bp.area() * dbu * dbu, 4),
                     body_box_um=[round(v * dbu, 3) for v in (bb.left, bb.bottom, bb.right, bb.top)],
                     block=(inst_bodies[owner][0].cell.name + " " + str(inst_bodies[owner][0].trans)) if owner is not None else "top cell",
                     t1=d["t1"], t2=d["t2"], body_node=d["body_node"], oriented=oriented, ends=len(end_nets), pieces=pieces))
# aggressor names per cluster used
used = {p["net"] for r in rows for p in r["pieces"]}
nets = {}
for c in used:
    nm = sorted(cl_names.get(c, set()))
    eq = sorted({e for n in nm for e in equiv.get(n, ())})
    nets[str(c)] = dict(magic_names=nm[:12], equiv=eq[:12], labels=sorted(cl_labels.get(c, set()), key=lambda s: (len(s), s)))
res = dict(gds=gds, ext=extf, method=__doc__.strip(), area_aF_per_um2=AREA, metal_edge_aF_per_um=SIDE_M, poly_edge_aF_per_um=SIDE_P,
           node_records_not_placed=dict(unplaced), resistor_devices=len(devs), bodies=len(bpolys), unmatched_devices=unmatched[:20],
           rows=rows, nets=nets)
out.write_text(json.dumps(res) + "\n")
tot = collections.defaultdict(float)
for r in rows:
    for p in r["pieces"]:
        tot[(p["who"], p["layer"])] += p["area_um2"]
print("devices", len(devs), "bodies", len(bpolys), "matched", len(rows), "unmatched", len(unmatched), "unplaced node records", dict(unplaced))
print("direct overlap um2 by owner and layer:", {f"{a} {b}": round(v, 2) for (a, b), v in sorted(tot.items())})
print("not oriented:", sum(1 for r in rows if not r["oriented"]))
