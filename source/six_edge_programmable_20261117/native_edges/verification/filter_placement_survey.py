"""Measure possible filter-source stub lengths on the occupied native tile, before routing."""
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

import klayout.db as db

HERE = Path(__file__).resolve().parent
CAD = HERE.parent / "layout" / "hold_mode"
RELEASE = HERE.parent / "layout/results/quiet_rc_release"
EVIDENCE = HERE / "evidence/filter_fields_313444d1"
sys.path.insert(0, str(CAD))
import rc_layout
import quiet_route
import res_select


DEVICE_LAYERS = [(64, 20, 1300), (65, 20, 650), (65, 44, 550), (66, 20, 510),
                 (66, 44, 390), (67, 20, 190), (67, 44, 200), (68, 20, 210),
                 (79, 20, 1300), (86, 20, 1300)]
M2_LANDING = [(68, 20, 390), (69, 20, 400), (68, 44, 320)]
M4_LANDING = M2_LANDING + [(70, 20, 560), (71, 20, 560), (69, 44, 370),
                          (70, 44, 400), (89, 44, 1650)]


def micron(point):
    return [round(i / 1000, 3) for i in (point.x, point.y)]


def distance(a, b):
    return (abs(a.x - b.x) + abs(a.y - b.y)) / 1000


def measured_cell(name):
    raw = gzip.decompress((EVIDENCE / "measured_cells" / (name + ".gds.gz")).read_bytes())
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == json.loads((RELEASE / "filter_cells.json").read_bytes())[name]["gds_sha256"]
    layout = db.Layout()
    layout.read_bytes(raw)
    cell = layout.top_cell()
    labels = {s.text.string: db.Point(s.text.x, s.text.y)
              for s in cell.shapes(layout.layer(67, 5)).each() if s.is_text()}
    assert len(labels) == 2 and layout.dbu == .001
    return layout, cell, labels, digest


def layer_aware_logic_site(layout, top, logic, free_lower, blocked, pads, ends):
    """Reserve the entire cell on front-end/M1 and its actual upper-metal shapes above M1."""
    target = ends["weak"]
    roi = db.Region(db.Box(target.x-60000, target.y-60000, target.x+60000, target.y+60000))
    floor = (free_lower - blocked) & roi
    layers = [((68, 44), (68, 44), 320), ((69, 20), (69, 20), 400),
              ((69, 44), (69, 44), 400), ((70, 20), (70, 20), 850),
              ((70, 20), (89, 44), 1400)]
    rules = []
    for new, old, space in layers:
        moving = db.Region(logic.begin_shapes_rec(layout.layer(*new))).merged()
        fixed = (db.Region(top.begin_shapes_rec(layout.layer(*old))) & roi.sized(6000)).sized(space)
        rules.append((moving, fixed))
    best = None
    for rot in range(4):
        allowed = rc_layout.translations(floor, [logic.bbox()], rot)
        mirror = db.Trans((rot+2) % 4, False, 0, 0)
        no = db.Region()
        for moving, fixed in rules:
            for p in moving.transformed(mirror).each():
                no += fixed.minkowski_sum(p)
        allowed = allowed - no.merged()
        spin = db.Trans(rot, False, 0, 0)
        wanted = [v - db.Vector(spin*db.Point(*pads[k])) for k, v in ends.items()]
        for point in rc_layout.nearest_candidates(allowed, wanted):
            tr = db.Trans(rot, False, round(point.x/5)*5, round(point.y/5)*5)
            values = {k: distance(tr*db.Point(*pads[k]), v) for k, v in ends.items()}
            score = (sum(values.values()), rot, tr.disp.x, tr.disp.y)
            if best is not None and best[0] <= score:
                continue
            if not (db.Region(logic.bbox().transformed(tr))-floor).is_empty():
                continue
            if any((moving.transformed(tr) & fixed).area() for moving, fixed in rules):
                continue
            best = (score, tr, values)
    if best is None:
        return {"searched_radius_um": 60, "found": False}
    _, tr, values = best
    return {"searched_radius_um": 60, "found": True, "bbox_nm": logic.bbox().transformed(tr).to_s(),
            "transform": tr.to_s(), "switch_driver_to_resistor_M1_source_lower_bound_um": values,
            "reserve_entire_bbox_through_M1": True,
            "upper_geometry_clearances_nm": [[list(i), list(j), k] for i, j, k in layers]}


def survey():
    # The base already has the actual shuttle pad, three weak TGs and their logic.
    # Remove only the three verified top routes already replaced by the filter.
    layout, top = quiet_route.physical_parent()
    _, cut = rc_layout.remove_launches(layout, top, quiet_route.points(layout, top, include_analog=True))
    floor = rc_layout.clear_floor(layout, top, DEVICE_LAYERS)
    access = {name: rc_layout.clear_floor(layout, top, rules)
              for name, rules in (("M1_M2", M2_LANDING), ("M1_M4", M4_LANDING))}
    entry_layout, entry, ep, entry_hash = measured_cell("ne_rc_entry")
    rail_layout, rail, rp, rail_hash = measured_cell("ne_rc_rail")
    bank_info = json.loads((RELEASE / "resistor_bank.json").read_bytes())
    # Read both library layouts before retaining their shapes. KLayout owns the
    # referenced cell object for the lifetime of the corresponding layout.
    assert len({entry_layout, rail_layout}) == 2
    p40 = {"res_sel": ep["R1"], "res_filtered": ep["R2"]}
    p400 = {"weak_src": rp["R1"], "weak": rp["R2"],
            "weak_b_src": rp["R1"] + db.Vector(830, 0), "weak_b": rp["R2"] + db.Vector(830, 0)}
    whole = {k: db.Point(*v) for k, v in bank_info["pin_m1_nm"].items()}
    assert all(whole[k] == p for k, p in p400.items())
    shapes = {
        "short_single": (entry, [entry.bbox()], p40, {"res_sel": rc_layout.PAD}),
        "paired_long": (rail, [rail.bbox(), rail.bbox().moved(830, 0)], p400,
                        {"weak_src": rc_layout.LOCAL_N, "weak_b_src": rc_layout.LOCAL_P}),
        "intact_three": (rail, [rail.bbox(), rail.bbox().moved(830, 0),
                                entry.bbox().moved(1660, 31500)], whole,
                         {"res_sel": rc_layout.PAD, "weak_src": rc_layout.LOCAL_N,
                          "weak_b_src": rc_layout.LOCAL_P}),
    }
    intact_cell, intact_footprints, intact_names, _ = shapes["intact_three"]
    shapes["intact_pad_priority"] = (intact_cell, intact_footprints, intact_names, {"res_sel": rc_layout.PAD})
    results = {}
    for name, (cell, pieces, pins, endpoints) in shapes.items():
        rows = {}
        as_xy = {k: (p.x, p.y) for k, p in pins.items()}
        for metal, window in access.items():
            transform, _ = rc_layout.place(cell, floor, pieces, as_xy,
                                           {k: (v, 1.) for k, v in endpoints.items()}, window)
            placed = {k: transform * p for k, p in pins.items()}
            extent = db.Region()
            for piece in pieces:
                extent.insert(piece.transformed(transform))
            assert (extent - floor).is_empty()
            assert all(inside(window, p) for p in placed.values())
            rows[metal] = dict(transform=transform.to_s(), bbox_nm=extent.bbox().to_s(),
                               contact_um={k: micron(p) for k, p in placed.items()},
                               straight_Manhattan_to_physical_source_um={
                                   k: distance(placed[k], source) for k, source in endpoints.items()})
        results[name] = rows
    # The two independently placed candidates can actually coexist as footprints.
    separated = {}
    for grid in access:
        a = db.Box.from_s(results["short_single"][grid]["bbox_nm"])
        b = db.Box.from_s(results["paired_long"][grid]["bbox_nm"])
        dx = max(0, a.left - b.right, b.left - a.right)
        dy = max(0, a.bottom - b.top, b.bottom - a.top)
        separated[grid] = dict(overlap_nm2=(db.Region(a) & db.Region(b)).area(),
                               minimum_box_gap_um=round(math.hypot(dx, dy) / 1000, 3))
    # The small two-gate cell may itself move next to the serial resistors.
    # Its existing footprint still blocks candidate placement in this screen.
    logic = layout.cell(res_select.LOGIC)
    local = quiet_route.labels(layout, logic)
    assert set(local) == set(res_select.LOGIC_PORTS)
    control_pads = {k: (round(v[0][1] * 1000), round(v[0][2] * 1000)) for k, v in local.items()}
    logic_floor = res_select.clearance_maps(layout, top)
    relocated = {}
    for arrangement in ("paired_long", "intact_three", "intact_pad_priority"):
        bank = results[arrangement]["M1_M4"]
        avoid = db.Region(db.Box.from_s(bank["bbox_nm"])).sized(1290)
        if arrangement == "paired_long":
            avoid += db.Region(db.Box.from_s(results["short_single"]["M1_M4"]["bbox_nm"])).sized(1290)
        available = logic_floor - avoid
        at = {k: db.Point(*(round(1000*v) for v in bank["contact_um"][k+"_src"]))
              for k in ("weak", "weak_b")}
        tr, _ = rc_layout.place(logic, available, [logic.bbox()], control_pads,
                                {k: (v, 1.) for k, v in at.items()})
        outputs = {k: tr * db.Point(*v) for k, v in control_pads.items()}
        assert (db.Region(logic.bbox().transformed(tr))-available).is_empty()
        relocated[arrangement] = dict(control_transform=tr.to_s(),
            control_bbox_nm=logic.bbox().transformed(tr).to_s(), control_pads_um={k: micron(v) for k, v in outputs.items()},
            switch_driver_to_resistor_M1_source_lower_bound_um={k: distance(outputs[k], v) for k, v in at.items()},
            actual_upper_conductor_polygons=layer_aware_logic_site(layout, top, logic, floor, avoid, control_pads, at))
    base = json.loads((RELEASE / "filter.json").read_bytes())
    path = RELEASE / "die.gds.gz"
    check = hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()
    assert check == base["gds"]
    old = json.loads((RELEASE / "placement.json").read_bytes())["physical"]["R"]["pins_nm"]
    current = {k: distance(db.Point(*old[k]), v) for k, v in
               (("res_sel", rc_layout.PAD), ("weak_src", rc_layout.LOCAL_N), ("weak_b_src", rc_layout.LOCAL_P))}
    return dict(parent_occupied_gds=quiet_route.GDS, existing_filter_gds=check,
                existing_filter_straight_Manhattan_to_physical_source_um=current,
                source_um={k: micron(v) for k, v in (("res_sel", rc_layout.PAD),
                           ("weak_src", rc_layout.LOCAL_N), ("weak_b_src", rc_layout.LOCAL_P))},
                total_removed_top_shapes={k: sum(v.values()) for k, v in cut.items()},
                measured_library_hashes={"short": entry_hash, "rail": rail_hash, "three": bank_info["gds_sha256"]},
                lower_layer_exclusion_nm=DEVICE_LAYERS, first_landing_clearance_nm={
                    "M1_M2": M2_LANDING, "M1_M4": M4_LANDING},
                geometry=results, separated_site_checks=separated, relocated_original_two_gate_cell=relocated,
                scope="Feasibility on the full occupied 1b base with its three superseded control routes removed in memory. The numbers are lower bounds on lengths to actual edge contacts. Candidate polygons and initial landing access are tested; routes, extracted fields, area/antenna rules and electrical performance require a built GDS. The standalone single 40k strip needs a legal URPM realization. The original three-strip bank has a passing leaf DRC/LVS receipt.")


def inside(region, point):
    return any(polygon.bbox().contains(point) and polygon.inside(point) for polygon in region.each())


if __name__ == "__main__":
    result = survey()
    target = EVIDENCE / "placement_survey.json"
    target.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: {s: v["straight_Manhattan_to_physical_source_um"] for s, v in data.items()}
                      for k, data in result["geometry"].items()}, indent=1))
