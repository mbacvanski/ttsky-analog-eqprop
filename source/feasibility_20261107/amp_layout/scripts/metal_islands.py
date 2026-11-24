"""Metal-only trace of a cell: which substrate and well contacts reach the cell's supply pins through metal.

LVS cannot see this. Magic and netgen treat the substrate as one ground node and every n-well as one node, so a
guard ring (or a capacitor plate that lands on one) with no metal to its rail still "matches": it is joined to
the rail through the silicon only. This trace knows nothing of the silicon. It follows local interconnect,
contacts, metal1 to metal4 and the vias (a via3 standing on a capacitor is the capacitor's top-plate contact,
not a connection to metal3), starting from the cell's `vss` and `vdd` pin labels, and lists

  * every substrate contact strip (p+ tap outside n-well) whose metal is not the `vss` pin's metal, and
  * every well contact strip (n+ tap inside n-well) whose metal is not the `vdd` pin's metal,

grouped by island, with the island's outline, the layers it reaches (metal3 and metal4 mean a capacitor plate
hangs on it) and the labels found on it. The method is the independent reviewer's
(floorplan/chip2x2/scripts/independent/taps2.py, which does the same on the whole chip from its two supply pads).

  ~/.local/opt/klayout-py/bin/python metal_islands.py CELL [CELL ...] [--gds PATH]
        -> results/metal_islands.json (one entry per cell), exit status 1 if any island is left
"""
import collections
import json
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parents[1]
METAL = [("li", 67, 20), ("mcon", 67, 44), ("m1", 68, 20), ("via", 68, 44), ("m2", 69, 20), ("via2", 69, 44), ("m3", 70, 20),
         ("via3", 70, 44), ("m4", 71, 20)]
LABEL_LAYER = {67: "li", 68: "m1", 69: "m2", 70: "m3", 71: "m4"}


def trace(path, vss_names=("vss",), vdd_names=("vdd",)):
    ly = db.Layout()
    ly.read(str(path))
    top, dbu = ly.top_cell(), ly.dbu

    def reg(layer, datatype):
        r = db.Region(top.begin_shapes_rec(ly.layer(layer, datatype)))
        r.merge()
        return r

    regions = {n: reg(l, d) for n, l, d in METAL}
    capm, nwell, tap, nsdm, psdm, licon = reg(89, 44), reg(64, 20), reg(65, 44), reg(93, 44), reg(94, 20), reg(66, 44)
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
        return l2n.probe_net(R[layer], db.DPoint(x, y))

    # labels of the top cell and of every cell below it, in top-cell coordinates
    texts = []
    for li in ly.layer_indexes():
        info = ly.get_info(li)
        if info.layer not in LABEL_LAYER:
            continue
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            s = it.shape()
            if s.is_text():
                t = s.text.transformed(it.trans())
                texts.append((LABEL_LAYER[info.layer], s.text.string, t.x * dbu, t.y * dbu, it.cell().name == top.name))
            it.next()

    def supply(names):
        ids = set()
        for layer, s, x, y, is_top in texts:
            if is_top and s.lower() in names:
                n = net(layer, x, y)
                assert n is not None, (path, s, layer, x, y)
                ids.add(n.cluster_id)
        assert len(ids) == 1, f"{path}: pins {names} are on {len(ids)} pieces of metal"
        return ids.pop()

    vss, vdd = supply(vss_names), supply(vdd_names)
    assert vss != vdd
    ptap = (tap & psdm) - nwell
    ntap = (tap & nsdm) & nwell
    islands, counts = {}, {}
    for kind, taps, want in (("substrate", ptap, vss), ("well", ntap, vdd)):
        ok = bad = 0
        for p in taps.each():
            found = set()
            nets = {}
            for q in (licon & db.Region(p)).each():
                c = q.bbox().center()
                n = net("li", c.x * dbu, c.y * dbu)
                found.add(None if n is None else n.cluster_id)
                if n is not None:
                    nets[n.cluster_id] = n
            if found == {want}:
                ok += 1
                continue
            bad += 1
            for cid in found - {want}:
                e = islands.setdefault(cid, dict(kind=kind, net=nets.get(cid), strips=[]))
                b = p.bbox()
                e["strips"].append([round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)])
        counts[kind] = dict(strips=ok + bad, on_the_rail=ok, not_on_the_rail=bad)
    out = []
    for cid, e in islands.items():
        n = e["net"]
        if n is None:
            out.append(dict(kind=e["kind"], strips=e["strips"], note="contact strip without local interconnect"))
            continue
        shapes = {name: l2n.shapes_of_net(n, R[name], True) for name in regions}
        whole = db.Region()
        for r in shapes.values():
            whole += r
        b = whole.bbox()
        labels = sorted({s for layer, s, x, y, _ in texts
                         if b.contains(db.Point(round(x / dbu), round(y / dbu))) and (net(layer, x, y) or n).cluster_id == cid and net(layer, x, y) is not None})
        out.append(dict(kind=e["kind"], outline_um=[round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)], contact_strips=len(e["strips"]),
                        layers={k: r.count() for k, r in shapes.items() if r.count()},
                        carries_capacitor_plate=bool(shapes["m3"].count() or shapes["m4"].count()), labels=labels))
    out.sort(key=lambda e: (e["kind"], e.get("outline_um", [0])[1], e.get("outline_um", [0])[0]))
    # how far each transistor diffusion is from the nearest contact strip that is on its rail by metal
    return dict(counts=counts, islands=out)


def main(args):
    gds = None
    if "--gds" in args:
        gds = args[args.index("--gds") + 1]
        args = [a for a in args if a not in ("--gds", gds)]
    path = HERE / "results" / "metal_islands.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    left = 0
    for cell in args:
        r = trace(gds or HERE / "layout" / f"{cell}.gds")
        res[cell] = r
        left += len(r["islands"])
        c = r["counts"]
        print(f"{cell}: substrate contact strips {c['substrate']['on_the_rail']} of {c['substrate']['strips']} on vss by metal, "
              f"well contact strips {c['well']['on_the_rail']} of {c['well']['strips']} on vdd by metal; islands: {len(r['islands'])}")
        for e in r["islands"]:
            print("   ", e["kind"], e.get("outline_um"), "strips", e.get("contact_strips"), "layers", e.get("layers"),
                  "CAPACITOR PLATE" if e.get("carries_capacitor_plate") else "", e.get("labels"), e.get("note", ""))
    path.write_text(json.dumps(dict(sorted(res.items())), indent=1) + "\n")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
