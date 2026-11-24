"""What lies over and under every block of a chip, device by device, from the GDS alone (KLayout Python).

  KPY over_blocks.py sel|ctrl GDS OUT.json

For every top-level instance (a "block": a neuron, an amplifier, a resistor array, a capacitor ...), in the block's OWN
frame (so that the same block on two chips compares device for device):
  devices      every transistor channel (poly over diffusion), every poly-resistor body (poly under the 66/13 marker) and
               every MIM top plate (capm 89/44) drawn inside the block (its whole sub-hierarchy);
  foreign      metal that is not the block's own: the top cell's own shapes (the chip's routing) and the shapes of every
               other top-level instance, on li1 and metal1..metal4, inside the block's outline;
  per device   the share of its area under foreign metal on each layer, and under any capacitor plate (its own or not).
Each foreign piece over a block is listed with its layer, area, place, the devices it covers and the net it is on (metal-only
trace, as amp_layout/scripts/metal_islands.py does; the net is named by the labels found on it and by VGND / VDPWR).
The accepted chip's router kept chip wiring off every block (outline + 0.3 um closed on metal1..metal4, chip2x2/scripts/
router.py load_obstacles) except metal4 over the small logic and resistor cells (bias_sel ext_sw obs_mux obs2_mux echo
ref_inv rsense rw_res pin_res); that rule is checked per block and layer ("accepted_rule_broken").
Roles: the control's instances carry their names (GDS property 61, H1, H2, Z ...); the selected chip's are the base flow's floorplan
roles (native_edges/layout/results/placement.json, physical_instances), matched by cell, transform and outline, and for the
nine instances added after that placement, names given here by place.
"""
import collections
import json
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[2]
tag, gds, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
ly = db.Layout()
ly.read(gds)
top, dbu = ly.top_cell(), ly.dbu
M4_OK = {"bias_sel", "ext_sw", "obs_mux", "obs2_mux", "echo", "ref_inv", "rsense", "rw_res", "pin_res"}
LAYERS = {"li": (67, 20), "met1": (68, 20), "met2": (69, 20), "met3": (70, 20), "met4": (71, 20)}
CONNECT = [("li", 67, 20), ("mcon", 67, 44), ("met1", 68, 20), ("via", 68, 44), ("met2", 69, 20), ("via2", 69, 44), ("met3", 70, 20),
           ("via3", 70, 44), ("met4", 71, 20)]
LABEL_LAYER = {67: "li", 68: "met1", 69: "met2", 70: "met3", 71: "met4"}
ADDED = {("sx_reset_tg", "r180 80650,166500"): "HOLDSW_H1", ("sx_reset_tg", "r0 203850,144250"): "HOLDSW_H2",
         ("sx_reset_tg", "r270 2955,91260"): "HOLDSW_Z", ("ne_res_hold_select", "r180 106090,207665"): "HOLD_SELECT",
         ("ne_rc_high_poly", "r270 62965,206335"): "RC_POLY", ("ne_rc_mim", "r0 322615,215905"): "RC_MIM",
         ("nr_reservoir_15p7", "r90 320795,157705"): "RESERVOIR1", ("nr_reservoir_15p7", "r270 289625,152575"): "RESERVOIR2",
         ("nr_gate_load", "r90 249260,216035"): "GATE_LOAD"}


def li_of(l, d):
    return ly.find_layer(l, d)


def chip_region(l, d):
    i = li_of(l, d)
    r = db.Region() if i is None else db.Region(top.begin_shapes_rec(i))
    r.merge()
    return r


# ---- roles
roles = {}
if tag == "sel":
    plj = json.loads((SIX / "native_edges/layout/results/placement.json").read_text())
    pl = plj["physical_instances"]
    want = {(v["cell"], v["transform"]): k for k, v in pl.items()}
    want.update(ADDED)
    by_box = {tuple(v["bbox_nm"]): k for k, v in plj["floorplan"]["placements"].items()}
for inst in top.each_inst():
    key = (inst.cell.name, str(inst.trans).replace(" ", " "))
    if tag == "ctrl":
        name = inst.property(61)
        roles[inst] = str(name)
    else:
        t = inst.trans
        k2 = (inst.cell.name, f"{str(t).split()[0]} {t.disp.x},{t.disp.y}")
        b = inst.bbox()
        if k2 in want:
            roles[inst] = want[k2]
        elif (b.left, b.bottom, b.right, b.top) in by_box:
            roles[inst] = by_box[(b.left, b.bottom, b.right, b.top)]
        else:                                  # an instance the selected layout does not have (a variant's new cell)
            roles[inst] = f"NEW:{inst.cell.name}@{b.left * dbu:.2f},{b.bottom * dbu:.2f}"
assert len(set(roles.values())) == len(roles), "two instances with one role"

# ---- metal-only nets, for naming the foreign pieces
regs = {n: chip_region(l, d) for n, l, d in CONNECT}
capm = chip_region(89, 44)
regs["via3"] = regs["via3"] - capm
flat = db.Layout()
flat.dbu = dbu
ft = flat.create_cell("FLAT")
idx = {}
for k, (n, r) in enumerate(regs.items()):
    idx[n] = flat.layer(k + 1, 0)
    ft.shapes(idx[n]).insert(r)
l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(flat, ft, []))
R = {n: l2n.make_layer(idx[n], n) for n in regs}
for n in regs:
    l2n.connect(R[n])
order = [n for n, _, _ in CONNECT]
for a, b in zip(order[:-1], order[1:]):
    l2n.connect(R[a], R[b])
l2n.extract_netlist()


def cid(layer, x, y):
    n = l2n.probe_net(R[layer], db.DPoint(x, y))
    return None if n is None else n.cluster_id


labels = collections.defaultdict(set)
rails = {}
for li in ly.layer_indexes():
    info = ly.get_info(li)
    if info.layer not in LABEL_LAYER:
        continue
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text.transformed(it.trans())
            c = cid(LABEL_LAYER[info.layer], t.x * dbu, t.y * dbu)
            if c is not None:
                labels[c].add(s.text.string)
                if it.cell().cell_index() == top.cell_index() and s.text.string.lower() in ("vgnd", "vdpwr"):
                    rails[c] = s.text.string.upper()
        it.next()


def net_name(c):
    if c is None:
        return "?"
    if c in rails:
        return rails[c]
    lab = sorted(labels.get(c, ()), key=lambda s: (len(s), s))
    return "/".join(lab[:5]) if lab else f"unlabelled#{c}"


def point_in(poly):
    tz = db.Region(poly).decompose_trapezoids_to_region()
    return next(tz.each()).bbox().center()


# ---- per block
def own_region(cell, ld, tr):
    i = li_of(*ld)
    r = db.Region() if i is None else db.Region(cell.begin_shapes_rec(i))
    r.merge()
    return r


def foreign_region(inst, ld):
    """top-cell shapes + every other top-level instance's shapes on layer ld, in chip coordinates"""
    i = li_of(*ld)
    r = db.Region()
    if i is None:
        return r
    r.insert(top.shapes(i))
    for other in top.each_inst():
        if other == inst:
            continue
        sub = db.Region(other.cell.begin_shapes_rec(i))
        r.insert(sub.transformed(other.cplx_trans))
    r.merge()
    return r


chip_foreign_cache = {}
um = lambda b: [round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)]   # noqa: E731
blocks = {}
for inst, role in sorted(roles.items(), key=lambda kv: kv[1]):
    cell = inst.cell
    tr = inst.cplx_trans
    inv = tr.inverted()
    outline_local = cell.bbox()
    outline_chip = db.Region(outline_local).transformed(tr)
    poly = own_region(cell, (66, 20), None)
    devs = []
    for kind, reg in (("transistor", poly & own_region(cell, (65, 20), None)), ("resistor", poly & own_region(cell, (66, 13), None)),
                      ("mim plate", own_region(cell, (89, 44), None))):
        reg.merge()
        for p in reg.each():
            devs.append((kind, p))
    # foreign metal in the block's frame
    foreign = {}
    pieces = []
    for lname, ld in LAYERS.items():
        f = foreign_region(inst, ld) & outline_chip
        f.merge()
        foreign[lname] = f.transformed(inv)
        for p in f.each():
            c = p.bbox().center() if p.is_box() else point_in(p)
            lay = lname if lname != "li" else "li"
            nm = net_name(cid(lay, c.x * dbu, c.y * dbu))
            pieces.append(dict(layer=lname, area_um2=round(p.area() * dbu * dbu, 3), box_chip_um=um(p.bbox()), net=nm,
                               _local=db.Region(p).transformed(inv)))
    capm_all = (capm & outline_chip).transformed(inv)
    rows = []
    for kind, p in devs:
        pr = db.Region(p)
        a = pr.area()
        b = p.bbox()
        d = dict(kind=kind, x=round(b.center().x * dbu, 3), y=round(b.center().y * dbu, 3), w=round(b.width() * dbu, 3), h=round(b.height() * dbu, 3),
                 under_capm=round((pr & capm_all).area() / a, 4) if kind != "mim plate" else None)
        for lname in LAYERS:
            d[lname] = round((pr & foreign[lname]).area() / a, 4)
        rows.append(d)
    # which devices each foreign piece covers
    for q in pieces:
        loc = q.pop("_local")
        cov = collections.Counter()
        for kind, p in devs:
            if not (loc & db.Region(p)).is_empty():
                cov[kind] += 1
        q["covers"] = dict(cov)
    area = {l: round(foreign[l].area() * dbu * dbu, 3) for l in LAYERS}
    broken = {l: area[l] for l in ("met1", "met2", "met3", "met4") if area[l] > 0 and not (l == "met4" and cell.name in M4_OK)}
    blocks[role] = dict(cell=cell.name, outline_chip_um=um(outline_chip.bbox()), trans=str(inst.trans), devices=collections.Counter(k for k, _ in devs),
                        foreign_area_um2=area, accepted_rule_broken_um2=broken,
                        devices_under_foreign_metal={l: sum(1 for d in rows if d[l] > 0) for l in LAYERS},
                        foreign_pieces=sorted(pieces, key=lambda q: (-q["area_um2"]))[:400], device_rows=rows)
out.write_text(json.dumps(dict(gds=gds, tag=tag, method=__doc__.strip(), blocks=blocks), indent=1) + "\n")
for role, b in blocks.items():
    print(f"{role:12s} {b['cell']:20s} devices {dict(b['devices'])} foreign um2 {b['foreign_area_um2']} under-foreign {b['devices_under_foreign_metal']}")
