"""Guard rings, wells, substrate taps and capacitor plates on their rail THROUGH METAL, on one GDS (KLayout Python).

  KPY ties.py GDS OUT.json

1. The accepted trace, imported unchanged: feasibility_20261107/amp_layout/scripts/metal_islands.py trace(gds, vss=("vgnd",),
   vdd=("vdpwr",)): local interconnect, contacts, metal1..metal4 and vias only (a via3 on a capacitor is the plate contact),
   from the top cell's VGND and VDPWR labels; every p+ substrate contact strip whose metal is not VGND's and every n+ well
   contact strip whose metal is not VDPWR's, grouped by island (outline, layers, capacitor plate on it, labels).
2. The independent reviewer's well and distance checks (chip2x2/scripts/independent/taps.py, taps3.py, taps4.py), redone here
   with the supply metal found from the labels instead of fixed probe points: every n-well polygon has an n-tap; every n-well
   has at least one tap on VDPWR by metal (or, if not, which node its taps are on and what devices it holds); n- and
   p-diffusion further than 5/10/15/20/30 um (box metric) from a tap that is on its rail by metal; deep n-well present or not.
3. Every MIM capacitor (capm 89/44): the metal cluster of its bottom plate (metal3 under it) and of its top plate (metal4
   through the via3 on it), whether that cluster is the VGND or VDPWR pin's metal, and the labels on it.
"""
import collections
import importlib.util
import json
import sys
from pathlib import Path

import klayout.db as db

X = Path(__file__).resolve().parents[4]                       # hardware/mesa/xor_sky130
spec = importlib.util.spec_from_file_location("metal_islands", X / "feasibility_20261107/amp_layout/scripts/metal_islands.py")
mi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mi)

gds, out = sys.argv[1], Path(sys.argv[2])
res = dict(gds=gds)
r = mi.trace(gds, vss_names=("vgnd",), vdd_names=("vdpwr",))
res["accepted_trace"] = r

ly = db.Layout()
ly.read(gds)
top, dbu = ly.top_cell(), ly.dbu


def reg(l, d):
    li = ly.find_layer(l, d)
    if li is None:
        return db.Region()
    x = db.Region(top.begin_shapes_rec(li))
    x.merge()
    return x


L = {n: reg(l, d) for n, l, d in mi.METAL}
capm, nwell, tap, diff, nsdm, psdm, licon, poly = reg(89, 44), reg(64, 20), reg(65, 44), reg(65, 20), reg(93, 44), reg(94, 20), reg(66, 44), reg(66, 20)
dnwell = reg(64, 18)
L["via3"] = L["via3"] - capm
flat = db.Layout()
flat.dbu = dbu
ft = flat.create_cell("FLAT")
idx = {}
for k, (n, rr) in enumerate(L.items()):
    idx[n] = flat.layer(k + 1, 0)
    ft.shapes(idx[n]).insert(rr)
l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(flat, ft, []))
R = {n: l2n.make_layer(idx[n], n) for n in L}
for n in L:
    l2n.connect(R[n])
order = [n for n, _, _ in mi.METAL]
for a, b in zip(order[:-1], order[1:]):
    l2n.connect(R[a], R[b])
l2n.extract_netlist()


def cid(layer, x, y):
    n = l2n.probe_net(R[layer], db.DPoint(x, y))
    return None if n is None else n.cluster_id


texts = []
for li in ly.layer_indexes():
    info = ly.get_info(li)
    if info.layer not in mi.LABEL_LAYER:
        continue
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text.transformed(it.trans())
            texts.append((mi.LABEL_LAYER[info.layer], s.text.string, t.x * dbu, t.y * dbu, it.cell().name == top.name))
        it.next()
label_cl = collections.defaultdict(set)
for layer, s, x, y, is_top in texts:
    c = cid(layer, x, y)
    if c is not None:
        label_cl[c].add(s)
vss = {cid(layer, x, y) for layer, s, x, y, is_top in texts if is_top and s.lower() == "vgnd"}
vdd = {cid(layer, x, y) for layer, s, x, y, is_top in texts if is_top and s.lower() == "vdpwr"}
assert len(vss) == 1 and len(vdd) == 1, (vss, vdd)
vss, vdd = vss.pop(), vdd.pop()


def name_of(c):
    return "VGND" if c == vss else "VDPWR" if c == vdd else None


def tap_clusters(p):
    s = set()
    for q in (licon & db.Region(p)).each():
        c = q.bbox().center()
        s.add(cid("li", c.x * dbu, c.y * dbu))
    return s


um = lambda b: [round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)]   # noqa: E731
ntap = (tap & nsdm) & nwell
ptap = (tap & psdm) - nwell
odd_n, odd_p = (tap & nsdm) - nwell, (tap & psdm) & nwell
good_p, good_n = db.Region(), db.Region()
for p in ptap.each():
    if tap_clusters(p) == {vss}:
        good_p.insert(p)
for p in ntap.each():
    if tap_clusters(p) == {vdd}:
        good_n.insert(p)
wells = []
for w in nwell.each():
    wr = db.Region(w)
    taps = list((ntap & wr).each())
    cls = [tap_clusters(p) for p in taps]
    on_vdd = sum(1 for c in cls if c == {vdd})
    pd = (diff & psdm) & wr
    gates = poly & pd
    nodes = collections.Counter()
    for c in cls:
        for x in c:
            nodes[name_of(x) or ("no local interconnect" if x is None else ",".join(sorted(label_cl.get(x, {"(unlabelled)"}))[:6]))] += 1
    e = dict(outline_um=um(w.bbox()), area_um2=round(w.area() * dbu * dbu, 2), n_taps=len(taps), taps_on_vdd_by_metal=on_vdd,
             tap_nodes=dict(nodes), pmos_gates=gates.count(), p_diffusion_polygons=pd.count(),
             mim_over_it=not (capm & wr).is_empty())
    wells.append(e)
ndiff = (diff & nsdm) - nwell - tap
pdiff = ((diff & psdm) & nwell) - tap
dist = {}
for d in (5, 10, 15, 20, 30):
    fn = ndiff - good_p.sized(d * 1000)
    fp = pdiff - good_n.sized(d * 1000)
    dist[f"{d}um"] = dict(n_diffusion_polygons_farther_from_a_VGND_metal_p_tap=fn.count(), n_area_um2=round(fn.area() * dbu * dbu, 2),
                         p_diffusion_polygons_farther_from_a_VDPWR_metal_n_tap=fp.count(), p_area_um2=round(fp.area() * dbu * dbu, 2),
                         first_n=[um(p.bbox()) for p in list(fn.each())[:8]], first_p=[um(p.bbox()) for p in list(fp.each())[:8]])
res["independent"] = dict(
    supply_clusters=dict(VGND=vss, VDPWR=vdd),
    n_taps=ntap.count(), p_taps=ptap.count(), n_taps_on_VDPWR_by_metal=good_n.count(), p_taps_on_VGND_by_metal=good_p.count(),
    n_plus_tap_outside_nwell=odd_n.count(), p_plus_tap_inside_nwell=odd_p.count(),
    nwell_polygons=nwell.count(), nwell_without_any_n_tap=[e for e in wells if e["n_taps"] == 0],
    nwell_without_a_VDPWR_metal_tap=[e for e in wells if e["n_taps"] and e["taps_on_vdd_by_metal"] == 0],
    deep_nwell_polygons=dnwell.count(), distance=dist)
# 3. capacitor plates
plates = []
via3_all = reg(70, 44)
for k, p in enumerate(capm.each()):
    pr = db.Region(p)
    b = p.bbox()
    m3 = L["m3"] & pr
    bot = set()
    for q in m3.each():
        c = q.bbox().center()
        bot.add(cid("m3", c.x * dbu, c.y * dbu))
    topc = set()
    for q in (via3_all & pr).each():
        c = q.bbox().center()
        topc.add(cid("m4", c.x * dbu, c.y * dbu))
    def desc(s):
        return [name_of(c) or sorted(label_cl.get(c, {"(unlabelled)"}))[:6] for c in s]
    plates.append(dict(k=k, plate_um=um(b), w_um=round(b.width() * dbu, 3), h_um=round(b.height() * dbu, 3),
                       bottom=desc(bot), top=desc(topc), bottom_on=[name_of(c) for c in bot], top_on=[name_of(c) for c in topc],
                       bottom_clusters=len(bot), top_clusters=len(topc)))
res["plates"] = dict(count=len(plates), bottom_on_VGND=sum("VGND" in p["bottom_on"] for p in plates), top_on_VGND=sum("VGND" in p["top_on"] for p in plates),
                     bottom_on_VDPWR=sum("VDPWR" in p["bottom_on"] for p in plates), top_on_VDPWR=sum("VDPWR" in p["top_on"] for p in plates),
                     plates_with_a_plate_split_over_several_metal_pieces=[p for p in plates if p["bottom_clusters"] != 1 or p["top_clusters"] != 1],
                     each=plates)
# 4. The bias words' ground (cell ne_bias_words). Since the XPROG strap (variant D, 24 Nov) the strap is its only ground,
#    and the extraction cannot show it: the writers' taps join the block's ground to the substrate, which Magic makes one
#    node with VGND, so the layout-against-circuit comparison matches with the strap open. Each part below must be on the
#    VGND pin's metal through local interconnect, metal and vias alone (via3 on a capacitor excluded, as above).
BIAS_GROUND = [("plate A, word 1's MIM bottom plate", "m3", 274.00, 5.00),
               ("plate B, word 2's MIM bottom plate", "m3", 284.50, 18.00),
               ("XPROG1's source landing (metal-2 pad)", "m2", 278.65, 10.40),
               ("XPROG1's source contact (local interconnect)", "li", 278.545, 10.40),
               ("XPROG2's source landing (metal-2 L)", "m2", 283.60, 11.00),
               ("XPROG2's source contact (local interconnect)", "li", 283.895, 9.56),
               ("the writers' metal-1 rail", "m1", 290.00, 2.15)]
bias = []
for part, layer, x, y in BIAS_GROUND:
    c = cid(layer, x, y)
    bias.append(dict(part=part, layer=layer, at_um=[x, y], on=(name_of(c) or "another net") if c is not None else "no metal there",
                     labels=sorted(label_cl.get(c, set()))[:6] if c is not None else []))
res["bias_words_ground"] = dict(parts=bias, all_on_VGND_by_metal=all(b["on"] == "VGND" for b in bias))
out.write_text(json.dumps(res, indent=1) + "\n")
c = r["counts"]
print(gds)
print(f"accepted trace: substrate strips {c['substrate']['on_the_rail']} of {c['substrate']['strips']} on VGND by metal; well strips {c['well']['on_the_rail']} of {c['well']['strips']} on VDPWR by metal; islands {len(r['islands'])}")
for e in r["islands"]:
    print("   island", e["kind"], e.get("outline_um"), "strips", e.get("contact_strips"), "CAP PLATE" if e.get("carries_capacitor_plate") else "", e.get("labels", [])[:8], e.get("note", ""))
ind = res["independent"]
print("n-wells", ind["nwell_polygons"], "without n-tap", len(ind["nwell_without_any_n_tap"]), "without a VDPWR-metal tap", len(ind["nwell_without_a_VDPWR_metal_tap"]), "dnwell", ind["deep_nwell_polygons"])
for e in ind["nwell_without_a_VDPWR_metal_tap"]:
    print("   well", e["outline_um"], e["tap_nodes"], "pmos gates", e["pmos_gates"])
for e in ind["nwell_without_any_n_tap"]:
    print("   UNTAPPED well", e["outline_um"], e["area_um2"], "pmos gates", e["pmos_gates"])
print("taps: n", ind["n_taps"], "on VDPWR", ind["n_taps_on_VDPWR_by_metal"], "| p", ind["p_taps"], "on VGND", ind["p_taps_on_VGND_by_metal"], "| odd n+", ind["n_plus_tap_outside_nwell"], "odd p+", ind["p_plus_tap_inside_nwell"])
for k, v in dist.items():
    print("  ", k, "n-diff", v["n_diffusion_polygons_farther_from_a_VGND_metal_p_tap"], "p-diff", v["p_diffusion_polygons_farther_from_a_VDPWR_metal_n_tap"])
pl = res["plates"]
print("plates", pl["count"], "bottom on VGND", pl["bottom_on_VGND"], "top on VGND", pl["top_on_VGND"], "bottom VDPWR", pl["bottom_on_VDPWR"], "top VDPWR", pl["top_on_VDPWR"], "split", len(pl["plates_with_a_plate_split_over_several_metal_pieces"]))
bw = res["bias_words_ground"]
print("bias words' ground on VGND by metal:", bw["all_on_VGND_by_metal"], [f"{b['part']}: {b['on']}" for b in bw["parts"] if b["on"] != "VGND"])
