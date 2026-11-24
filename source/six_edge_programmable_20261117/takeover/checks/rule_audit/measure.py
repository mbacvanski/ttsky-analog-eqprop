"""Rule audit (2026-11-23): measure the actual geometry behind each rule the open decks flag, on the flattened layout.

  ~/.local/opt/klayout-py/bin/python -I measure.py <gds> <staged gds> <staged lef> <out json>

Everything is measured on flat merged layers of the whole die (die coordinates, um). Each block prints what it measured
and stores it in the JSON. Layers (SKY130 GDS numbers): nwell 64/20, diff 65/20, tap 65/44, poly 66/20, licon 66/44,
li 67/20, m1 68/20, via1 68/44, m2 69/20, via2 69/44, m3 70/20, via3 70/44, m4 71/20, via4 71/44, m5 72/20, hvi 75/20,
npc 95/20, capm 89/44, cap2m 97/44, rpm 86/20, urpm 79/20, psdm 94/20, poly_rs 66/13, lvtn 125/44.
"""
import json
import re
import sys

import klayout.db as db

gds, staged_gds, staged_lef, out = sys.argv[1:5]
ly = db.Layout()
ly.read(gds)
top = ly.top_cell()
dbu = ly.dbu
U = lambda v: v / 1000.0 if isinstance(v, int) else v      # noqa: E731
res = {}


def R(l, d, lay=None, cell=None):
    lay = lay or ly
    cell = cell or lay.top_cell()
    li = lay.find_layer(l, d)
    r = db.Region(cell.begin_shapes_rec(li)) if li is not None else db.Region()
    r.merge()
    return r


def um(x):
    return round(x * dbu, 4)


def box(b):
    return [um(b.left), um(b.bottom), um(b.right), um(b.top)]


nwell, diff, tap, poly, licon = R(64, 20), R(65, 20), R(65, 44), R(66, 20), R(66, 44)
li, m1, via1, m2, via2, m3, via3, m4, via4, m5 = R(67, 20), R(68, 20), R(68, 44), R(69, 20), R(69, 44), R(70, 20), R(70, 44), R(71, 20), R(71, 44), R(72, 20)
hvi, npc, capm, cap2m = R(75, 20), R(95, 20), R(89, 44), R(97, 44)
rpm, urpm, psdm, poly_rs, lvtn = R(86, 20), R(79, 20), R(94, 20), R(66, 13), R(125, 44)

# ---------------------------------------------------------------- hvi.5: drawn HVI to n-well (SkyWater 0.70, excluding coincident edges)
ep = hvi.separation_check(nwell, int(0.70 / dbu), False, db.Metrics.Euclidian)
d = sorted(e.distance() for e in ep.each())
places = ep.polygons(1).sized(100).merged()
ex = []
for p in list(places.each())[:200]:
    sub = db.EdgePairs([e for e in ep.each() if e.bbox().overlaps(p.bbox()) or p.bbox().contains(e.bbox().center())])
    if sub.count():
        ex.append(dict(place=box(p.bbox()), min_distance_um=um(min(e.distance() for e in sub.each()))))
ex.sort(key=lambda x: x["min_distance_um"])
res["hvi.5"] = dict(rule_um=0.70, edge_pairs=ep.count(), distinct_places=places.count(), measured_min_max_um=[um(d[0]), um(d[-1])] if d else None,
                    worst=ex[:3], all_places=ex)
print("hvi.5: drawn HVI to nwell < 0.70:", ep.count(), "edge pairs,", places.count(), "places, distance", res["hvi.5"]["measured_min_max_um"], "e.g.", ex[:2])

# ---------------------------------------------------------------- HVI minimum width 0.84 (foundry "special" rule4 on ttsky25b; public hvi.1 is 0.60)
w84 = hvi.width_check(int(0.84 / dbu), False, db.Metrics.Euclidian)
w60 = hvi.width_check(int(0.60 / dbu), False, db.Metrics.Euclidian)
wd = sorted(e.distance() for e in w84.each())
res["hvi_width_0.84"] = dict(rule_um=0.84, public_hvi1_um=0.60, violations_084=w84.count(), violations_060=w60.count(),
                              narrowest_um=um(wd[0]) if wd else None, examples=[dict(box=box(e.bbox()), width_um=um(e.distance())) for e in list(w84.each())[:4]],
                              hvi_shapes=hvi.count(), hvi_min_bbox_side_um=min(min(um(p.bbox().width()), um(p.bbox().height())) for p in hvi.each()) if hvi.count() else None)
print("HVI width < 0.84:", w84.count(), "< 0.60:", w60.count(), "narrowest", res["hvi_width_0.84"]["narrowest_um"], "min bbox side", res["hvi_width_0.84"]["hvi_min_bbox_side_um"])

# ---------------------------------------------------------------- hvpoly.14: poly must not straddle hvi (2020 deck text)
cross = (hvi & poly).edges() - poly.edges()          # HVI edges running across poly
fingers = poly.interacting(cross)
out_part = poly.interacting(hvi) - hvi                # poly of HV gates that lies outside HVI
beyond = sorted({(um(p.bbox().width()), um(p.bbox().height())) for p in out_part.each()})
plic = licon & poly
plic_out = plic.interacting(out_part)
gates_hv = (diff & poly & hvi)
res["hvpoly.14"] = dict(crossing_edges=cross.count(), poly_shapes_crossing=fingers.count(), hv_gates=gates_hv.count(),
                        poly_outside_hvi_pieces=out_part.count(), outside_piece_sizes_um=beyond[:12],
                        poly_licons_touching_outside_part=plic_out.count(),
                        examples=[box(e.bbox()) for e in list(cross.each())[:3]])
print("hvpoly.14: HVI edges crossing poly:", cross.count(), "poly shapes crossing:", fingers.count(), "poly pieces outside HVI (w,h)", beyond[:8],
      "; poly contacts on the outside part:", plic_out.count())

# ---------------------------------------------------------------- capm.10: capm must not straddle nwell, diff, tap, poly, li1, met1 (2020 deck text)
c10 = {}
for name, lay in (("nwell", nwell), ("diff", diff), ("tap", tap), ("poly", poly), ("li1", li), ("met1", m1), ("met2", m2)):
    n = 0
    edges_len = 0
    for p in capm.each():
        pr = db.Region(p)
        inter = pr & lay
        if inter.is_empty():
            continue
        e = inter.edges() - pr.edges()
        if not e.is_empty():
            n += 1
            edges_len += e.length()
    c10[name] = dict(capm_shapes_with_edges_under=n, edge_length_um=round(edges_len * dbu, 1))
clean = sum(1 for p in capm.each() if all(((db.Region(p) & lay).edges() - db.Region(p).edges()).is_empty() for lay in (nwell, diff, tap, poly, li, m1)))
res["capm.10"] = dict(capm_shapes=capm.count(), capm_area_um2=round(capm.area() * dbu * dbu, 1), cap2m_shapes=cap2m.count(), per_layer=c10,
                      capm_shapes_free_of_all_six=clean)
print("capm.10: capm shapes", capm.count(), "cap2m", cap2m.count(), "| shapes with an edge of the layer underneath:", {k: v["capm_shapes_with_edges_under"] for k, v in c10.items()},
      "| free of all six:", clean)

# ---------------------------------------------------------------- capm rules with the right layers (the 2020 deck writes them with met2/via1)
c3 = m3.enclosing_check(capm, int(0.14 / dbu), False, db.Metrics.Euclidian)
c3b = capm - m3
c8 = via2.separation_check(capm, int(0.14 / dbu), False, db.Metrics.Euclidian)
c8o = via2 & capm
m3_not = m3.not_interacting(capm)
c11 = m3_not.separation_check(capm, int(0.5 / dbu), False, db.Metrics.Euclidian)
plates = (capm & m3).sized(int(0.14 / dbu))
c2b = plates.space_check(int(1.2 / dbu), False, db.Metrics.Euclidian)
c5 = via3.separation_check(capm, int(0.14 / dbu), False, db.Metrics.Euclidian)
c4 = capm.enclosing_check(via3, int(0.14 / dbu), False, db.Metrics.Euclidian)
res["capm_right_layers"] = {"capm.3 met3 encl 0.14": c3.count() + c3b.count(), "capm.8 via2 space 0.14": c8.count(), "via2 under capm": c8o.count(),
                            "capm.11 unrelated met3 space 0.5": c11.count(), "capm.2b plate space 1.2 (MR form)": c2b.count(),
                            "capm.4 via3 encl 0.14": c4.count(), "capm.5 via3 space 0.14": c5.count()}
print("capm rules on the right layers:", res["capm_right_layers"])

# ---------------------------------------------------------------- licon.15 / licon.18: npc must enclose poly licon by 0.10 (issue 179)
prec = (rpm | urpm) & psdm & poly.interacting(poly_rs)
plic = licon & poly
plic_res = plic.interacting(prec) | plic.interacting(poly_rs)
plic_dev = plic - plic_res
for tag, L in (("gate_contacts", plic_dev), ("resistor_head_contacts", plic_res)):
    notin = L - npc
    enc = npc.enclosing_check(L, int(0.10 / dbu), False, db.Metrics.Euclidian)
    dd = sorted(e.distance() for e in enc.each())
    # enclosure actually achieved: grow each contact until it leaves npc (0.005 steps up to 0.2)
    worst = None
    for k in range(0, 41):
        g = L.sized(k * 5)
        if not (g - npc).is_empty():
            worst = k * 0.005
            break
    res[f"licon.15_{tag}"] = dict(contacts=L.count(), not_covered_by_npc=notin.count(), enclosure_below_0p10=enc.count(),
                                  enclosure_min_um=um(dd[0]) if dd else None, all_contacts_min_enclosure_um=worst,
                                  examples=[box(e.bbox()) for e in list(enc.each())[:3]] + [box(p.bbox()) for p in list(notin.each())[:3]])
    print(f"licon.15 {tag}: {L.count()} contacts, {notin.count()} not inside npc, {enc.count()} with npc enclosure < 0.10 (min {res[f'licon.15_{tag}']['enclosure_min_um']}),"
          f" smallest enclosure over all contacts ~{worst}")
licon18 = npc.not_interacting(plic)
res["licon.18_npc_without_poly_licon"] = licon18.count()

# ---------------------------------------------------------------- licon.1 / licon.7 (2020 deck): the resistor head contacts
heads = licon.interacting(urpm) - licon.interacting(rpm)
sizes = sorted({(um(p.bbox().width()), um(p.bbox().height())) for p in heads.each()})
res["licon.1_licon.7"] = dict(licons_in_urpm=heads.count(), sizes_um=sizes[:6],
                             in_prec_resistor=(heads & prec).count(), non_017_licons_outside_resistors=sum(
                                 1 for p in (licon - licon.interacting(urpm | rpm)).each() if (um(p.bbox().width()), um(p.bbox().height())) != (0.17, 0.17)))
print("licon.1/licon.7: licons in urpm (not rpm):", heads.count(), "sizes", sizes[:4], "| non-0.17 licons outside resistors:", res["licon.1_licon.7"]["non_017_licons_outside_resistors"])

# ---------------------------------------------------------------- m3.3ab / m4.5ab: wide metal (> 3 um) spacing 0.40 to other metal
for name, lay in (("m3", m3), ("m4", m4)):
    sp = lay.space_check(int(0.4 / dbu), False, db.Metrics.Euclidian)
    wide = lay.sized(-1500).sized(1500)
    wide_pairs = [e for e in sp.each() if not (wide & db.Region(e.polygon(0).bbox().enlarged(1, 1))).is_empty()]
    allsp = sorted(e.distance() for e in sp.each())
    res[f"{name}_wide_spacing"] = dict(space_pairs_below_0p40=sp.count(), involving_wide_metal=len(wide_pairs),
                                       distances_um=[um(x) for x in allsp[:5]], examples=[box(e.bbox()) for e in wide_pairs[:3]])
    print(f"{name}: spacing pairs < 0.40 (any width): {sp.count()} (distances {[um(x) for x in allsp[:5]]}), of them next to metal wider than 3 um: {len(wide_pairs)}")

# ---------------------------------------------------------------- floating metal (MR deck floating_met group)
fm2 = m2.not_interacting(via1 | via2)
fm4 = m4.not_interacting(via3 | via4)
labels = []
for li_ in ly.layer_indexes():
    lp = ly.get_info(li_)
    it = top.begin_shapes_rec(li_)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text.transformed(it.trans())
            for p in fm2.each():
                if p.bbox().enlarged(200, 200).contains(db.Point(t.x, t.y)):
                    labels.append((lp.layer, lp.datatype, s.text.string))
        it.next()
ctx = {}
for p in fm2.each():
    b = p.bbox()
    win = db.Region(b.enlarged(1000, 1000))
    ctx[str(box(b))] = dict(area_um2=round(p.area() * dbu * dbu, 3), m1_under=(m1 & db.Region(p)).count(), m3_over=(m3 & db.Region(p)).count(),
                            m2_within_1um=(m2 & win).count() - 1, via1_within_1um=(via1 & win).count(), via2_within_1um=(via2 & win).count(), labels=labels)
pins_x = [round(151.81 - 19.32 * n, 2) for n in range(8)]
res["floating_metal"] = dict(m2=ctx, m4=[box(p.bbox()) for p in fm4.each()], tt_analog_pin_x=dict(zip([f"ua[{n}]" for n in range(8)], pins_x)))
print("floating m2:", ctx, "| floating m4:", res["floating_metal"]["m4"], "| TT analog pin x:", pins_x)

# ---------------------------------------------------------------- layer 64/44 (issue 136) and other layers present
res["layers_present"] = sorted(f"{ly.get_info(i).layer}/{ly.get_info(i).datatype}" for i in ly.layer_indexes() if not top.bbox_per_layer(i).empty())
print("layer 64/44 present:", "64/44" in res["layers_present"])

# ---------------------------------------------------------------- issue 186: GDS metal outside the LEF OBS (+ pins), on the staged GDS/LEF pair
sl = db.Layout()
sl.read(staged_gds)
lef = open(staged_lef).read()
obs = re.search(r"(?ms)^  OBS\n(.*?)^  END", lef).group(1)
layer_rects, cur = {}, None
for line in obs.splitlines():
    m = re.match(r"\s*LAYER (\S+) ;", line)
    if m:
        cur = m.group(1)
        continue
    m = re.match(r"\s*RECT (\S+) (\S+) (\S+) (\S+) ;", line)
    if m and cur:
        layer_rects.setdefault(cur, []).append(tuple(map(float, m.groups())))
pins = {}
for m in re.finditer(r"(?ms)^  PIN (\S+)\n(.*?)^  END \1", lef):
    for lm in re.finditer(r"LAYER (\S+) ;\s*((?:\s*RECT [^;]+;)+)", m.group(2)):
        for r in re.findall(r"RECT (\S+) (\S+) (\S+) (\S+) ;", lm.group(2)):
            pins.setdefault(lm.group(1), []).append(tuple(map(float, r)))
gdsl = dict(nwell=(64, 20), li1=(67, 20), met1=(68, 20), met2=(69, 20), met3=(70, 20), met4=(71, 20), met5=(72, 20))
outside = {}
for name, (l, d) in gdsl.items():
    g = R(l, d, sl)
    allowed = db.Region()
    for r in layer_rects.get(name, []) + pins.get(name, []):
        allowed.insert(db.DBox(*r).to_itype(sl.dbu))
    allowed.merge()
    o = g - allowed
    outside[name] = dict(gds_shapes=g.count(), obs_rects=len(layer_rects.get(name, [])), pin_rects=len(pins.get(name, [])),
                         outside_obs_and_pins=o.count(), outside_area_um2=round(o.area() * sl.dbu * sl.dbu, 3), examples=[[round(x * sl.dbu, 3) for x in (p.bbox().left, p.bbox().bottom, p.bbox().right, p.bbox().top)] for p in list(o.each())[:3]])
res["lef_obs_cover"] = dict(foreign="FOREIGN tt_um_mbacvanski_analog_eqprop ;" in lef, obs_layers=sorted(layer_rects), met5_obs=bool(layer_rects.get("met5")), per_layer=outside)
print("LEF: FOREIGN", res["lef_obs_cover"]["foreign"], "OBS layers", sorted(layer_rects), "| GDS metal outside OBS+pins:", {k: v["outside_obs_and_pins"] for k, v in outside.items()})

json.dump(res, open(out, "w"), indent=1)
