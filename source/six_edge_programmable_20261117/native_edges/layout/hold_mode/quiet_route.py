"""Move the three release-control conductors on the 1b die while preserving every placed device."""
import argparse
from array import array
from collections import Counter
import ctypes as ct
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import klayout.db as db

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from res_select import BUILD, REPORT, SIX, parent_anchors, save, schematic
from connectivity import Connectivity, INDEX, METALS, labels
import route_split as grid

GDS = "1b2984a374e8c637086f901c59c330eb34c85f835001764f758f63b65b91646e"
WIRES = ("res_sel", "weak", "weak_b")
LAYERS = tuple(INDEX) + ("v1", "v2", "v3")


def physical_parent():
    raw = gzip.decompress((REPORT / "res_hold_provisional/die.gds.gz").read_bytes())
    if hashlib.sha256(raw).hexdigest() != GDS:
        raise ValueError("The routing control is for a different die")
    layout = db.Layout()
    layout.read_bytes(raw)
    return layout, layout.top_cell()


def points(layout, top, include_analog=False):
    placed = json.loads((REPORT / "placement.json").read_bytes())["physical_instances"]
    extra = json.loads((REPORT / "hold_mode/res_hold_placement.json").read_bytes())["placements"]
    instances = {i.trans.to_s(): i for i in top.each_inst()}

    def at(name, record, pin):
        inst = instances[record["transform"]]
        point, = labels(layout, inst.cell, inst.dtrans)[pin]
        return [name + ":" + pin, *point]

    terminals = [[net, *pin] for net, pin in parent_anchors(layout, top).items()]
    for name, record in extra.items():
        for pin, net in record["pins"].items():
            terminals.append([net, *at(name, record, pin)])
    terminals.append(["res_sel", *at("DEC", placed["DEC"], "res_sel")])
    sense = [
        ("h2_feedback_bus", "NRN_H2", "bus"), ("b_h1_weight_bus", "ROWS_B", "f1x"),
        ("z_feedback_bus", "NRN_Z", "bus"), ("A", "BUF_BIAS1", "out"),
        ("B", "BUF_BIAS2", "out"), ("f1", "H1", "y"), ("f2", "H2", "y"),
    ]
    for net, name, pin in sense:
        terminals.append([net, *at(name, placed[name], pin)])
    if include_analog:
        for net, name, pin in [
            ("h1_threshold", "H1", "bpin"), ("h2_threshold", "H2", "bpin"), ("Zbuf", "Z", "y"),
            ("A_store", "BIAS", "sg1"), ("B_store", "BIAS", "sg2"),
            ("A_follower", "BIAS", "bw1"), ("B_follower", "BIAS", "bw2"),
            ("h1_feedback_bus", "NRN_H1", "bus"),
        ]:
            instance = instances[placed[name]["transform"]]
            for site in labels(layout, instance.cell, instance.dtrans)[pin]:
                terminals.append([net, name + ":" + pin, *site])
    return terminals


def polygon_of(shape):
    if shape.is_box():
        return db.Polygon(shape.box)
    if shape.is_polygon():
        return shape.polygon
    if shape.is_path():
        return shape.path.polygon()
    raise ValueError("Unexpected top-level conductor object")


def strip():
    (BUILD / "hold_mode").mkdir(parents=True, exist_ok=True)
    schematic()
    layout, top = physical_parent()
    pins = points(layout, top)
    nets, conflicts, con = grid.circuit(layout, top, pins)
    if conflicts or any(len(nets[n]) != 1 for n in nets):
        raise ValueError(("Parent conductor topology differs", conflicts))
    groups = {next(iter(nets[n])): n for n in WIRES}
    counts = Counter()
    for metal in LAYERS:
        shapes = top.shapes(layout.layer(*METALS[metal]))
        erase = []
        keep = db.Region()
        if metal in INDEX:
            electrodes = {n: con.region(net, metal).merged() for net, n in groups.items()}
            pins_layer = layout.find_layer(METALS[metal][0], 16)
            ports = db.Region(top.shapes(pins_layer)) if pins_layer is not None else db.Region()
        for s in shapes.each():
            poly = polygon_of(s)
            r = db.Region(poly)
            if metal in INDEX:
                hits = [n for n, region in electrodes.items() if not (r & region).is_empty()]
                if not hits:
                    continue
                n, = hits
                if not (r - electrodes[n]).is_empty():
                    raise ValueError(("Partially attributed metal", n, metal, s.bbox()))
                keep += r & ports
            else:
                point = poly.bbox().center()
                idx = int(metal[-1]) - 1
                lower = con.probe(LAYERS[idx], point.x / 1000, point.y / 1000)
                upper = con.probe(LAYERS[idx + 1], point.x / 1000, point.y / 1000)
                if lower not in groups and upper not in groups:
                    continue
                if lower != upper:
                    raise ValueError(("Disputed via", metal, point, lower, upper))
                n = groups[lower]
            counts[n, metal] += 1
            erase.append(s)
        for s in erase:
            s.delete()
        for p in keep.merged().each():
            shapes.insert(p)
    after, conflicts, _ = grid.circuit(layout, top, pins)
    if conflicts or any(len(after[n]) <= 1 for n in WIRES):
        raise ValueError(("Expected three separate interrupted controls", dict(after), conflicts))
    if any(len(after[n]) != 1 for n in after if n not in WIRES):
        raise ValueError("The selected metal cut another measured conductor")
    out = BUILD / "quiet_hold_unrouted.gds"
    save(layout, top, out)
    (BUILD / "quiet_hold_targets.json").write_text(json.dumps(pins, indent=2) + "\n")
    report = dict(parent_gds_sha256=GDS,
                  removed_top_shapes={n: {m: counts[n, m] for m in LAYERS} for n in WIRES},
                  initial_groups={n: list(after[n].values()) for n in WIRES})
    (BUILD / "quiet_hold_unrouted.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report, flush=True)


def engine():
    source = (SIX / "layout/trace_route.cpp").read_text()
    before = 'extern "C" int route(int net,int *counts,int maxcounts){'
    field = """
namespace { vector<int> risk; }
extern "C" void fields(int *arr, int count) {
    risk.assign(nodes, 0);
    for (int i=0; i<count; ++i) {
        int* r=arr+6*i;
        Box b{r[0],r[1],r[2],r[3],r[4],0,0};
        boxpoints(b,0,[&](int x,int y) {
            risk[point(b.l,x,y)] += r[5];
        });
    }
}
"""
    change = "int nd=dist[p]+weight;"
    if source.count(before) != 1 or source.count(change) != 1:
        raise ValueError("The routing engine no longer matches the checked placement conventions")
    source = source.replace(before, field + before).replace(change, "int nd=dist[p]+weight+risk[next];")
    source = source.replace("if(end<0)return -100000-start;", """if(end<0){
        int reached=0,nearest=2147483647;
        for(int k=0;k<nodes;++k)if(dist[k]<2147483647){++reached;nearest=min(nearest,lower(k));}
        fprintf(stderr,"No route from group %d: %d reachable grid sites, closest target-box distance %.2f um\\n",
                start,reached,nearest*step/8000.0);return -100000-start;}""")
    path = BUILD / "quiet_hold_routes.cpp"
    lib = BUILD / "quiet_hold_routes.so"
    if not path.exists() or path.read_text() != source or not lib.exists():
        path.write_text(source)
        subprocess.run(["g++", "-O3", "-std=c++17", "-fPIC", "-shared", "-DLOCAL_ROUTING",
                        "-o", str(lib), str(path)], check=True)
    return ct.CDLL(str(lib))


def charge_cost(con, nets, weight):
    """Geometric heuristic only. Extract capacitances anew on the drawn result."""
    fields = array("i")
    metals = ("li", *INDEX)
    strong = ("ref", "h2_feedback_bus", "b_h1_weight_bus", "z_feedback_bus", "A", "B")
    other = ("H1", "H2", "Z", "f1", "f2", "six")
    for names, cost in [(strong, weight), (other, max(1, weight // 3))]:
        for layer_index, layer in enumerate(metals):
            sensitive = db.Region()
            for name in names:
                component, = nets[name]
                sensitive += con.region(component, layer)
            sensitive = sensitive.merged()
            for distance, halo, price in [(0, 1200, cost), (1, 260, cost), (2, 160, max(1, cost // 5))]:
                region = sensitive.sized(halo)
                for dst in range(4):
                    if abs(dst + 1 - layer_index) == distance:
                        for bounds in grid.boxes(region):
                            fields.extend((dst, *bounds, price))
    return fields


def analog_cost(con, nets, weight):
    """Penalize exposed crossings over quiet analog wires and favor existing supply metal."""
    fields = array("i")
    physical = ("li", *INDEX)
    groups = [
        (("ref",), 4),
        (("A", "B", "A_store", "B_store", "A_follower", "B_follower"), 4),
        (("H1", "H2", "Z", "f1", "f2", "Zbuf", "h1_threshold", "h2_threshold"), 3),
        (("h1_feedback_bus", "h2_feedback_bus", "b_h1_weight_bus", "z_feedback_bus", "six"), 2),
    ]
    def apply(region, source, lateral_nm, vertical, cost):
        destinations = [layer for layer in range(4) if abs(layer + 1 - source) == vertical]
        if not destinations:
            return
        rectangles = list(grid.boxes(region.sized(lateral_nm)))
        for dst in destinations:
            for rect in rectangles:
                fields.extend((dst, *rect, cost))
    for number, layer in enumerate(physical):
        supply = db.Region()
        for name in ("vdd", "vss"):
            for component in nets[name]:
                supply += con.region(component, layer)
        # Unknown local nets include high-impedance transistor gates inside macros.
        # An adjacent, connected power or ground roof is cheaper than an exposed crossing.
        ordinary = con.layers[layer] - supply
        for lateral, vertical, divisor in [(650, 0, 5), (220, 1, 3), (100, 2, 12)]:
            apply(ordinary, number, lateral, vertical, max(1, weight // divisor))
        for names, force in groups:
            region = db.Region()
            for name in names:
                component, = nets[name]
                region += con.region(component, layer)
            for lateral, vertical, divisor in [
                (1900, 0, 2), (850, 0, 1), (900, 1, 2), (260, 1, 1), (260, 2, 6),
            ]:
                apply(region, number, lateral, vertical, max(1, weight * force // divisor))
    return fields


def route(stem, pitch, offset, weight, avoid_analog=False, *, source="quiet_hold_unrouted",
          target_file="quiet_hold_targets.json", wires=WIRES, physical_points=False, m4_cost=0, m3_cost=0, per_wire_m3=None):
    layout = db.Layout()
    layout.read(str(BUILD / (source + ".gds")))
    top = layout.top_cell()
    pins = json.loads((BUILD / target_file).read_bytes())
    if avoid_analog and not physical_points:
        pins = points(layout, top, include_analog=True)
    nets, shorts, con = grid.circuit(layout, top, pins)
    if shorts:
        raise ValueError(shorts)
    ids = {name: i + 1 for i, name in enumerate(wires)}
    geometry = array("i")
    for index, metal in enumerate(INDEX):
        routed = db.Region()
        for n in wires:
            for component in nets[n]:
                region = con.region(component, metal)
                routed += region
                for b in grid.boxes(region):
                    geometry.extend((index, *b, ids[n], component))
        for b in grid.boxes(con.layers[metal] - routed):
            geometry.extend((index, *b, 0, 0))
    for index, via in enumerate(("v1", "v2", "v3")):
        for b in grid.boxes(con.layers[via]):
            geometry.extend((index + 4, *b, 0, 0))
    for b in grid.boxes(db.Region(top.begin_shapes_rec(layout.layer(89, 44)))):
        geometry.extend((7, *b, 0, 0))
    solver = engine()
    nx = (334880 - offset) // pitch + 1
    ny = (225760 - offset) // pitch + 1
    solver.setup(pitch, offset, nx, ny, grid.carray(geometry), len(geometry) // 7)
    fields = analog_cost(con, nets, weight) if avoid_analog else charge_cost(con, nets, weight)
    if m3_cost and not per_wire_m3:
        fields.extend((2,0,0,334880,225760,m3_cost))
    if m4_cost:
        fields.extend((3,0,0,334880,225760,m4_cost))
    solver.fields(grid.carray(fields), len(fields) // 6)
    grid.WIRE_HALF = (75, 75, 150, 150)
    grid.PAD_HALF = (165, 185, 205, 205)
    log = {}
    for n in wires:
        if per_wire_m3:
            adjusted=array("i",fields)
            adjusted.extend((2,0,0,334880,225760,per_wire_m3[n]))
            solver.fields(grid.carray(adjusted),len(adjusted)//6)
        counts = (ct.c_int * 800)()
        joins = solver.route(ids[n], counts, len(counts))
        if joins != len(nets[n]) - 1:
            raise ValueError(("Unable to complete routing", n, joins, list(counts)[:2 * len(nets[n])]))
        added = array("i")
        for j in range(joins):
            length = solver.path_length(j)
            path = (ct.c_int * length)()
            solver.path_read(j, path)
            for layer, x, y, xx, yy in grid.draw(path, nx, ny, pitch, offset):
                top.shapes(layout.layer(*METALS[LAYERS[layer]])).insert(db.Box(x, y, xx, yy))
                added.extend((layer, x, y, xx, yy, ids[n], 0))
        solver.add(grid.carray(added), len(added) // 7)
        log[n] = dict(joins=joins, new_rectangles=len(added) // 7)
        print(n, log[n], flush=True)
    connected, shorts, _ = grid.circuit(layout, top, pins)
    if shorts or any(len(values) != 1 for values in connected.values()):
        raise ValueError("Unintended short or open on the rerouted physical die")
    out = BUILD / (stem + ".gds")
    save(layout, top, out)
    result = dict(gds_sha256=hashlib.sha256(out.read_bytes()).hexdigest(), original_gds_sha256=GDS,
                  pitch_nm=pitch, offset_nm=offset, field_search_weight=weight, results=log)
    if avoid_analog:
        result["additional_analog_keepouts"] = True
    if per_wire_m3:
        result["m3_cost_by_wire"] = per_wire_m3
    if m3_cost:
        result["m3_additional_cost"] = m3_cost
    if m4_cost:
        result["m4_additional_cost"] = m4_cost
    (BUILD / (stem + ".json")).write_text(json.dumps(result, indent=2) + "\n")
    print(result["gds_sha256"], flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=["strip", "route"])
    cli.add_argument("--out", default="quiet_hold_routed")
    cli.add_argument("--pitch", type=int, default=220)
    cli.add_argument("--offset", type=int, default=110)
    cli.add_argument("--weight", type=int, default=85)
    cli.add_argument("--avoid-analog", action="store_true", help="Protect held states, thresholds and internal-gate fields")
    options = cli.parse_args()
    if options.operation == "strip":
        strip()
    else:
        route(options.out, options.pitch, options.offset, options.weight, options.avoid_analog)
