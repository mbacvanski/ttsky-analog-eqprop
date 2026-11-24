"""The metal3 sheet over the weight resistors, checked on the GDS alone: it covers all six strips of rw_res with
overhang, it is on ground by metal, and it is only a sheet (no capacitor layer, nothing through it).

LVS cannot see this sheet: it is a piece of metal on the ground net with no device on it, so a sheet that floats,
or one that is missing, matches just as well. This reads the final GDS and
  * finds the cell rw_res and the bodies of its resistor strips (polysilicon under the resistor marker), dummies included;
  * takes the one metal3 polygon that lies over them and measures how far it reaches beyond the bodies on each side;
  * follows metal only (local interconnect, contacts, metal1 to metal4 and the vias, as amp_layout/scripts/metal_islands.py
    does) from the sheet and from the chip's ground and supply pins: the sheet must be the ground pin's metal;
  * checks that no capacitor layer and no via3 lies on the sheet, and lists the metal4 that crosses above it.

  <KLayout Python> sheet_check.py [GDS]      (default: the Tiny Tapeout project's GDS)
        -> results/rw_sheet.json, exit status 1 if any of this does not hold
"""
import json
import sys
from pathlib import Path

import klayout.db as db

import magic_util

HERE = Path(__file__).resolve().parents[1]
TOP = "tt_um_mbacvanski_denseam_xor"
METAL = [("li", 67, 20), ("mcon", 67, 44), ("m1", 68, 20), ("via", 68, 44), ("m2", 69, 20), ("via2", 69, 44), ("m3", 70, 20),
         ("via3", 70, 44), ("m4", 71, 20)]
LABEL_LAYER = {67: "li", 68: "m1", 69: "m2", 70: "m3", 71: "m4"}
OVERHANG = 0.7          # um; the neurons' bottom plates reach 0.73 um beyond their nine strips at the least


def main(gds):
    ly = db.Layout()
    ly.read(str(gds))
    top, dbu = ly.top_cell(), ly.dbu

    def reg(layer, datatype, cell=top):
        r = db.Region(cell.begin_shapes_rec(ly.layer(layer, datatype)))
        r.merge()
        return r

    # the strips of rw_res, in the top cell's coordinates
    rw = [c for c in ly.each_cell() if c.name.endswith("rw_res")]
    assert len(rw) == 1, [c.name for c in rw]
    poly = reg(66, 20)
    it = db.RecursiveInstanceIterator(ly, top)
    box = None
    while not it.at_end():
        if it.inst_cell().cell_index() == rw[0].cell_index():
            box = it.inst_cell().bbox().transformed(it.trans() * it.inst_trans())
        it.next()
    assert box is not None, "rw_res is not placed in the chip"
    marker = reg(66, 13) & db.Region(box)                       # the resistor marker
    bodies = poly & marker
    bodies.merge()
    strips = [p.bbox() for p in bodies.each()]

    regions = {n: reg(l, d) for n, l, d in METAL}
    capm, cap2m = reg(89, 44), reg(97, 44)
    regions["via3"] = regions["via3"] - capm
    flat = db.Layout()
    flat.dbu = dbu
    ft = flat.create_cell("FLAT")
    index = {}
    for k, (n, r) in enumerate(regions.items()):
        index[n] = flat.layer(k + 1, 0)
        ft.shapes(index[n]).insert(r)
    l2n = db.LayoutToNetlist(db.RecursiveShapeIterator(flat, ft, []))
    R = {n: l2n.make_layer(index[n], n) for n in regions}
    for n in regions:
        l2n.connect(R[n])
    order = [n for n, _, _ in METAL]
    for a, b in zip(order[:-1], order[1:]):
        l2n.connect(R[a], R[b])
    l2n.extract_netlist()

    def net(layer, x, y):
        n = l2n.probe_net(R[layer], db.DPoint(x, y))
        return None if n is None else n.cluster_id

    pins = {}
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if info.layer not in LABEL_LAYER:
            continue
        for s in top.shapes(li).each():
            if s.is_text() and s.text.string.lower() in ("vgnd", "vdpwr"):
                pins.setdefault(s.text.string.lower(), set()).add(net(LABEL_LAYER[info.layer], s.text.x * dbu, s.text.y * dbu))
    assert all(len(v) == 1 and None not in v for v in pins.values()) and set(pins) == {"vgnd", "vdpwr"}, pins
    ground, supply = pins["vgnd"].pop(), pins["vdpwr"].pop()

    whole = db.Region()
    for b in strips:
        whole.insert(b)
    hull = whole.bbox()
    over = [p for p in regions["m3"].each() if not (db.Region(p) & whole).is_empty()]
    out = dict(gds=Path(gds).name, strips=len(strips), strip_bodies_um=[round(v * dbu, 3) for v in (hull.left, hull.bottom, hull.right, hull.top)],
               metal3_pieces_over_the_strips=len(over))
    ok = len(strips) == 6 and len(over) == 1
    if over:
        sheet = db.Region(over[0])
        sb = sheet.bbox()
        cx, cy = hull.center().x * dbu, hull.center().y * dbu
        on = net("m3", cx, cy)
        grown = whole.sized(round(OVERHANG / dbu))
        out.update(sheet_um=[round(v * dbu, 3) for v in (sb.left, sb.bottom, sb.right, sb.top)], sheet_is_a_rectangle=sheet.area() == sb.area(),
                   sheet_area_um2=round(sheet.area() * dbu * dbu, 2),
                   cover_of_the_bodies=round((whole & sheet).area() / whole.area(), 4),
                   beyond_the_bodies_um=dict(left=round((hull.left - sb.left) * dbu, 3), right=round((sb.right - hull.right) * dbu, 3),
                                             bottom=round((hull.bottom - sb.bottom) * dbu, 3), top=round((sb.top - hull.top) * dbu, 3)),
                   at_least_um=OVERHANG, reaches_that_far_all_round=(grown - sheet).is_empty(),
                   on_ground_by_metal=on == ground, on_the_supply=on == supply,
                   via2_under_the_sheet=(reg(69, 44) & sheet).count(), via3_on_the_sheet=(reg(70, 44) & sheet).count(),
                   capacitor_layer_on_the_sheet_um2=round(((capm + cap2m) & sheet).area() * dbu * dbu, 3),
                   metal4_above_the_sheet=[dict(share_of_the_sheet=round((db.Region(p) & sheet).area() / sheet.area(), 4),
                                                on_ground=net("m4", *[(v * dbu) for v in ((db.Region(p) & sheet).bbox().center().x, (db.Region(p) & sheet).bbox().center().y)]) == ground)
                                           for p in regions["m4"].each() if not (db.Region(p) & sheet).is_empty()])
        # what sheet_figure.py draws: boxes in um, in the chip's coordinates
        um = lambda b: [round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)]
        near = db.Region(sb.enlarged(round(3 / dbu), round(3 / dbu)))
        out["drawing"] = dict(strips=sorted(um(b) for b in strips), sheet=um(sb), via2=[um(p.bbox()) for p in (reg(69, 44) & sheet).each()],
                              metal3_nearby=[um(p.bbox()) for p in ((regions["m3"] - sheet) & near).each()],
                              metal4_above=[um(p.bbox()) for p in (regions["m4"] & sheet).each()], cell=um(box))
        ok = bool(ok and out["cover_of_the_bodies"] == 1 and out["reaches_that_far_all_round"] and out["on_ground_by_metal"]
                  and not out["on_the_supply"] and out["via2_under_the_sheet"] >= 2 and out["via3_on_the_sheet"] == 0
                  and out["capacitor_layer_on_the_sheet_um2"] == 0)
    out["ok"] = ok
    (HERE / "results" / "rw_sheet.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else magic_util.TT_PROJECT / "gds" / f"{TOP}.gds"))
