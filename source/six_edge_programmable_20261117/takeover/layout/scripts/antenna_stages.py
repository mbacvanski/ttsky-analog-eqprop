"""Etch-stage antenna check, derived from takeover/checks/antenna_stage_20261124/stage_scan.py.

KLayout Python: antenna_stages.py DIE.gds[.gz] OUT.json
Extract a fresh physical network at each etch. A cut sees the conductor below it
and cannot join through the layer above it until that layer is deposited.
Conductor exposure is merged perimeter times thickness, cut exposure is area.
The metal limit is 400 + 2200 times connected source, drain and tap area in µm².
Use the stage-specific base limits and diffusion slopes for poly, LI and cuts.
"""
import argparse
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path

import klayout.db as db

# Etch order, GDS layer/purpose, sidewall thickness in µm (None for openings),
# base ratio and allowance per µm² of connected source, drain or tap.
RULES = {
    "poly": (66, 20, .18, 50, 0),     "licon": (66, 44, None, 3, 0),
    "li":   (67, 20, .10, 75, 450),   "mcon":  (67, 44, None, 3, 18),
    "m1":   (68, 20, .36, 400, 2200), "via1":  (68, 44, None, 3, 18),
    "m2":   (69, 20, .36, 400, 2200), "via2":  (69, 44, None, 6, 36),
    "m3":   (70, 20, .845, 400, 2200), "via3": (70, 44, None, 6, 36),
    "m4":   (71, 20, .845, 400, 2200), "via4": (71, 44, None, 6, 36),
    "m5":   (72, 20, 1.26, 400, 2200),
}
MIM = {"via3": (89, 44), "via4": (97, 44)}


def measure(layout, stage, model):
    top = layout.top_cell()
    through = list(RULES)[:list(RULES).index(stage) + 1]
    graph = db.LayoutToNetlist(db.RecursiveShapeIterator(layout, top, []))

    def layer(pair, name):
        return graph.make_polygon_layer(layout.layer(*pair), name)

    layers = {k: layer(RULES[k][:2], k) for k in through}
    poly = layers["poly"]
    diff = layer((65, 20), "diff")
    tap = layer((65, 44), "tap")
    gates = (poly & diff).merged()
    sd = (diff - poly).merged()
    graph.register(gates, "gate")
    graph.register(sd, "sd")
    if model == "open":
        layers["poly"] = poly - layer((66, 13), "resistor_body")
        graph.register(layers["poly"], "open_poly")

    for reg in [*layers.values(), gates, sd, tap]:
        graph.connect(reg)
    graph.connect(gates, layers["poly"])
    if "licon" in layers:
        graph.connect(sd, layers["licon"])
        graph.connect(tap, layers["licon"])

    # Where a via lands on a MIM top plate it cannot also touch the
    # underlying metal bottom plate. Keep the two populations of cuts apart.
    cap_cuts = {}
    for lower, upper in zip(through, through[1:]):
        if upper in MIM:
            electrode = layer(MIM[upper], upper + "_electrode")
            cap = layers[upper].interacting(electrode)
            if not (cap - electrode).is_empty():
                raise ValueError(f"{upper} crosses the MIM electrode edge")
            plain = layers[upper] - cap
            graph.register(plain, upper + "_plain")
            graph.register(cap, upper + "_cap")
            for reg in (electrode, plain, cap):
                graph.connect(reg)
            graph.connect(cap, electrode)
            cap_cuts[upper] = cap
            layers[upper] = plain
        graph.connect(layers[lower], layers[upper])
        if lower in cap_cuts:
            graph.connect(cap_cuts[lower], layers[upper])

    graph.extract_netlist()
    unit = Decimal(str(layout.dbu))
    area_unit = unit * unit
    _, _, thickness, base, slope = RULES[stage]
    rows = []
    seen = 0
    for net in graph.netlist().top_circuit().each_net():
        def shapes(reg):
            return graph.shapes_of_net(net, reg, True).merged()

        gate = shapes(gates)
        if gate.is_empty():
            continue
        seen += gate.count()
        exposed = shapes(layers[stage])
        if stage in cap_cuts:
            exposed = (exposed + shapes(cap_cuts[stage])).merged()
        if exposed.is_empty():
            continue
        area = gate.area() * area_unit
        discharge = (shapes(sd).area() + shapes(tap).area()) * area_unit
        perimeter = exposed.perimeter() * unit
        charge = exposed.area() * area_unit if thickness is None else perimeter * Decimal(str(thickness))
        limit = base + slope * discharge
        boxes = [g.bbox() for g in gate.each()]
        row = dict(gate_bbox_dbu=min(str(b) for b in boxes), gate_area_um2=float(area),
                   diffusion_um2=float(discharge), exposed_um2=float(charge),
                   ratio=float(charge / area), limit=float(limit), over=charge > limit * area)
        if thickness is not None:
            row["perimeter_um"] = float(perimeter)
        if stage == "m2" or row["over"]:
            row["gate_centres_um"] = sorted([float(b.center().x * unit), float(b.center().y * unit)] for b in boxes)
        rows.append(row)
    if not seen or seen != gates.count():
        raise ValueError(f"{stage}/{model}: attributed {seen} of {gates.count()} gates")
    free = [r for r in rows if not r["diffusion_um2"]]
    rows.sort(key=lambda r: r["gate_bbox_dbu"])
    result = dict(gate_shapes=seen, measured_nets=len(rows), base_limit=base, diffusion_slope=slope,
                  thickness_um=thickness, worst_without_diffusion=max(free, key=lambda r: r["ratio"], default=None),
                  largest_raw=max(rows, key=lambda r: r["ratio"], default=None),
                  over_limit=[r for r in rows if r["over"]])
    if stage == "m2":
        result["nets"] = rows
    return result


def control_patterns():
    """One 0.18 µm² gate per pattern. Measure on, and 5 nm above, each limit.
    One pattern has a 0.10 µm² diffusion reachable only when M3 is present."""
    ly = db.Layout()
    ly.dbu = .001
    top = ly.create_cell("etch_controls")
    cases = [(99.600, "none", False), (99.605, "late", True),
             (154.600, "early", False), (154.605, "early", True),
             (99.605, "through_resistor", True)]
    for i, (length, connection, over) in enumerate(cases):
        y = i * 10
        def box(pair, x1, y1, x2, y2):
            top.shapes(ly.layer(*pair)).insert(db.DBox(x1, y+y1, x2, y+y2))
        box((65, 20), -.5, 0, .9, .5)
        box((66, 20), 0, -.1, .36, 2.4)
        for k in ("licon", "li", "mcon", "m1", "via1"):
            box(RULES[k][:2], .05, 2.05, .25, 2.25)
        box((69, 20), 0, 2, length, 2.4)
        if connection == "through_resistor":
            box((66, 13), -.1, 1, .46, 1.5)
        if connection in ("late", "early"):
            dy = 0 if connection == "early" else 1
            box((65, 20), 5, 2+dy, 5.5, 2.2+dy)
            for k in ("licon", "li", "mcon", "m1", "via1", "m2"):
                box(RULES[k][:2], 5.1, 2.01+dy, 5.2, 2.11+dy)
            if connection == "late":
                for d in (0, dy):
                    box((69, 44), 5.1, 2.01+d, 5.2, 2.11+d)
                box((70, 20), 5.1, 2.01, 5.2, 2.11+dy)
    records = []
    for model in ("conducting", "open"):
        rows = measure(ly, "m2", model)["nets"]
        m3 = measure(ly, "m3", model)
        for i, (_, connection, over) in enumerate(cases):
            row = next((r for r in rows if [.18, i * 10 + .25] in r["gate_centres_um"]), None)
            isolated = connection == "through_resistor" and model == "open"
            limit = 620 if connection == "early" else 400
            if isolated:
                ok = row is None
            else:
                ok = bool(row and row["over"] == over and row["limit"] == limit
                          and row["ratio"] == limit + (.02 if over else 0))
            if connection == "late":
                ok &= (m3["measured_nets"] == 1 and not m3["over_limit"] and m3["largest_raw"]["limit"] == 620)
            records.append(dict(model=model, connection=connection, ratio=row["ratio"] if row else None,
                                limit=row["limit"] if row else None, expected_over=over and not isolated,
                                measured_over=bool(row and row["over"]), ok=ok))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gds", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    data = args.gds.read_bytes()
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    ly = db.Layout()
    ly.read_bytes(data)
    if len(ly.top_cells()) != 1:
        raise ValueError("expected one die top")
    top = ly.top_cell()
    ly.flatten(top.cell_index(), -1, True)
    def region(layer, purpose):
        return db.Region(top.shapes(ly.layer(layer, purpose))).merged()

    gates = region(66, 20) & region(65, 20)
    markers = region(66, 13)
    if gates.is_empty() or not (gates & markers).is_empty():
        raise ValueError("expected transistor gates clear of resistor body markers")
    models = {}
    failures = 0
    for model in ("conducting", "open"):
        models[model] = {}
        for stage, (layer, purpose, *_) in RULES.items():
            if top.shapes(ly.layer(layer, purpose)).is_empty():
                models[model][stage] = {"absent": True}
                continue
            r = measure(ly, stage, model)
            models[model][stage] = r
            failures += len(r["over_limit"])
            print(f"{model} {stage}: {r['measured_nets']} exposed gate nets, {len(r['over_limit'])} over limit", flush=True)
    plants = control_patterns()
    plants_ok = all(r["ok"] for r in plants)
    ok = failures == 0 and plants_ok
    verdict = f"RESULT: {'PASS' if ok else 'FAIL'} | {failures} over-limit net-stage/model observations | controls {sum(r['ok'] for r in plants)}/{len(plants)}"
    args.report.write_text(json.dumps(dict(gds_sha256=hashlib.sha256(data).hexdigest(), top=top.name, dbu_um=ly.dbu,
                                          resistor_body_markers=markers.count(), models=models,
                                          over_limit_count=failures, planted_faults=plants,
                                          planted_faults_ok=plants_ok, ok=ok, result=verdict), indent=1) + "\n")
    print(verdict)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
