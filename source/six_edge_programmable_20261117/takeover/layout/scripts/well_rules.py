"""Tiny Tapeout's three n-well rules, measured directly where their decks measure less (KLayout's Python; reads the
layout, writes one JSON file).

  KPY -I well_rules.py GDS OUT.json      exit 0: the layout passes and every planted fault is found; 1: not; 2: usage

The whole layout flat and merged: n-well 64/20, lvtn 125/44, hvtp 78/44, urpm 79/20.
  lvtn  lvtn.10, n-well around lvtn 0.38 um (SkyWater flagged it on ttsky25b and ttsky26d): every lvtn shape lies wholly
        inside an n-well or wholly outside all of them, and inside one at least 0.38 um from its edge. Tiny Tapeout's
        deck (nwell.enclosing(lvtn, 0.38)) never flags an lvtn shape that crosses a well's edge: KLayout's enclosing
        check ignores a shape that is not inside.
  hvtp  hvtp and n-well slivers (SkyWater flagged them on ttsky26c): hvtp AND n-well at least 0.38 um wide (Tiny
        Tapeout's deck) and at least 0.38 um apart, notches included; hvtp outside the n-wells only where SkyWater's own
        standard cells put it, i.e. each placed sky130_fd_sc_* cell's hvtp beyond its own n-well (the hd cells draw hvtp
        0.055 um below their well, so every row of them has such a strip). Any other hvtp outside a well fails.
  urpm  Tiny Tapeout's deck (from a thread with SkyWater): n-well at least 0.70 um from urpm; no urpm over an n-well
        either, which the deck's separation check ignores.
Planted faults: the same reading and judgement on the layout with eight test patterns beside it (a cell of their own,
outside the layout's box), each with its own n-well: lvtn across the well's edge; lvtn 0.37 um inside the edge, and
0.38 um (at the limit); hvtp past the edge by 0.055 um in a cell that is not a standard cell; hvtp AND n-well 0.30 um
wide; urpm over the well; urpm 0.65 um from the well, and 0.70 um (at the limit). Each must give exactly its planted
fault, none at the limit, and the layout's own judgement must not change.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

import klayout.db as db

NWELL, LVTN, HVTP, URPM = (64, 20), (125, 44), (78, 44), (79, 20)
UM = dict(lvtn_enclosure=0.38, hvtp_width=0.38, hvtp_space=0.38, urpm_space=0.70)
SLOT, GAP = 10.0, 20.0
W = (0, 0, 4, 4)                       # each pattern's n-well, um within its slot
# (what, {layer: [boxes]}, the faults it must give)
PLANTS = [
    ("lvtn across the well's edge", {LVTN: [(3, 1, 5, 3)]}, ["lvtn across a well's edge"]),
    ("lvtn 0.37 um inside the well's edge", {LVTN: [(1, 1, 3.63, 3)]}, ["lvtn enclosure"]),
    ("lvtn 0.38 um inside the well's edge, at the limit", {LVTN: [(1, 1, 3.62, 3)]}, []),
    ("hvtp 0.055 um past the well's edge, not in a standard cell", {HVTP: [(1, -0.055, 3, 2)]}, ["hvtp outside a well, not a standard cell's"]),
    ("hvtp AND n-well 0.30 um wide", {HVTP: [(1, 1, 3, 1.3)]}, ["hvtp AND n-well width"]),
    ("urpm over the well", {URPM: [(3, 1, 6, 3)]}, ["urpm over a well"]),
    ("urpm 0.65 um from the well", {URPM: [(4.65, 1, 7, 3)]}, ["urpm spacing"]),
    ("urpm 0.70 um from the well, at the limit", {URPM: [(4.7, 1, 7, 3)]}, []),
]


def region(ly, top, ld):
    li = ly.find_layer(*ld)
    r = db.Region() if li is None else db.Region(top.begin_shapes_rec(li))
    r.merge()
    return r


def std_strips(ly, top):
    """Each placed standard cell's own hvtp beyond its own n-well, in top coordinates."""
    hli, nli = ly.find_layer(*HVTP), ly.find_layer(*NWELL)
    out = db.Region()
    if hli is None:
        return out
    local = {}
    it = top.begin_shapes_rec(hli)
    while not it.at_end():
        c = ly.cell(it.cell_index())
        if c.name.startswith("sky130_fd_sc_"):
            if c.cell_index() not in local:
                h = db.Region(c.begin_shapes_rec(hli)).merged()
                n = db.Region(c.begin_shapes_rec(nli)).merged() if nli is not None else db.Region()
                local[c.cell_index()] = h - n
            out.insert(local[c.cell_index()].transformed(it.trans()))
        it.next()
    return out.merged()


def judge(ly, top, n):
    nw, lv, hv, ur = (region(ly, top, ld) for ld in (NWELL, LVTN, HVTP, URPM))
    found = []                                         # (kind, box, distance or None)
    for p in (lv.interacting(nw) - lv.inside(nw)).each():
        found.append(("lvtn across a well's edge", p.bbox(), None))
    for ep in nw.enclosing_check(lv.inside(nw), n["lvtn_enclosure"]).each():
        found.append(("lvtn enclosure", ep.bbox(), ep.distance()))
    a = (hv & nw).merged()
    for ep in a.width_check(n["hvtp_width"]).each():
        found.append(("hvtp AND n-well width", ep.bbox(), ep.distance()))
    for ep in a.space_check(n["hvtp_space"]).each():
        found.append(("hvtp AND n-well space", ep.bbox(), ep.distance()))
    outside = (hv - nw).merged()
    own = std_strips(ly, top)
    for p in (outside - own).merged().each():
        found.append(("hvtp outside a well, not a standard cell's", p.bbox(), None))
    for p in (ur & nw).merged().each():
        found.append(("urpm over a well", p.bbox(), None))
    for ep in nw.separation_check(ur, n["urpm_space"]).each():
        found.append(("urpm spacing", ep.bbox(), ep.distance()))
    near = lambda chk: min((ep.distance() for ep in chk.each()), default=None)
    readings = dict(lvtn_shapes=lv.count(), lvtn_inside_wells=lv.inside(nw).count(), lvtn_outside_wells=lv.outside(nw).count(),
                    lvtn_enclosure_smallest_within_1um=near(nw.enclosing_check(lv.inside(nw), 1000 * n["u"])),
                    hvtp_shapes=hv.count(), hvtp_and_nwell_width_smallest_within_1um=near(a.width_check(1000 * n["u"])),
                    hvtp_outside_wells_pieces=outside.count(), hvtp_outside_wells_area_dbu2=outside.area(),
                    standard_cell_strips_area_dbu2=own.area(), urpm_shapes=ur.count(),
                    urpm_nwell_spacing_smallest_within_2um=near(nw.separation_check(ur, 2000 * n["u"])))
    return found, readings


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    gds, out = argv[1], argv[2]
    ly = db.Layout()
    ly.read(gds)
    tops = ly.top_cells()
    if len(tops) != 1:
        print("the layout must have one top cell:", [t.name for t in tops])
        return 2
    top = tops[0]
    dbu = ly.dbu
    n = {k: round(v / dbu) for k, v in UM.items()}
    n["u"] = round(0.001 / dbu) or 1
    u = lambda v: None if v is None else round(v * dbu, 4)
    bbox = top.bbox()
    f0, r0 = judge(ly, top, n)
    # planted patterns: a cell of their own beside the layout
    x0, y0 = bbox.right + round(GAP / dbu), bbox.bottom + round(GAP / dbu)
    pc = ly.create_cell("planted_well_rule_faults")
    for k, (_, shapes, _) in enumerate(PLANTS):
        for ld, boxes in [(NWELL, [W])] + list(shapes.items()):
            for b in boxes:
                pc.shapes(ly.layer(*ld)).insert(db.DBox(*b).moved(k * SLOT, 0).to_itype(dbu).moved(db.Vector(x0, y0)))
    top.insert(db.CellInstArray(pc.cell_index(), db.Trans()))
    f1, _ = judge(ly, top, n)
    inside = lambda b: b.right <= bbox.right
    own = lambda f: sorted((k, (b.left, b.bottom, b.right, b.top), d) for k, b, d in f if inside(b))
    unchanged = own(f0) == own(f1)
    got = defaultdict(list)
    stray = []
    for k, b, d in f1:
        if not inside(b):
            slot = (b.left - x0 + round(1 / dbu)) // round(SLOT / dbu) if b.left >= x0 - round(1 / dbu) else -1
            (got[slot].append(k) if 0 <= slot < len(PLANTS) else stray.append(k))
    planted = []
    for k, (what, _, expect) in enumerate(PLANTS):
        planted.append(dict(pattern=k + 1, what=what, faults_planted=sorted(expect), faults_found=sorted(got.get(k, [])),
                            ok=sorted(got.get(k, [])) == sorted(expect)))
    planted_ok = unchanged and not stray and all(p["ok"] for p in planted)
    own_faults = [dict(kind=k, box_um=[u(v) for v in (b.left, b.bottom, b.right, b.top)], distance_um=u(d)) for k, b, d in f0]
    by_kind = defaultdict(int)
    for f in own_faults:
        by_kind[f["kind"]] += 1
    ok = not own_faults and planted_ok
    rd = dict(r0)
    for k in list(rd):
        if k.endswith("_dbu2"):
            rd[k.replace("_dbu2", "_um2")] = round(rd.pop(k) * dbu * dbu, 4)
        elif "smallest" in k:
            rd[k] = u(rd[k])
    n_faults = sum(len(p[2]) for p in PLANTS)
    result = (f"RESULT: {'PASS' if ok else 'FAIL'} | lvtn across a well's edge {by_kind['lvtn across a well' + chr(39) + 's edge']}, "
              f"lvtn enclosure under 0.38 {by_kind['lvtn enclosure']}, hvtp AND n-well under 0.38 wide {by_kind['hvtp AND n-well width']} or apart "
              f"{by_kind['hvtp AND n-well space']}, hvtp outside a well beyond the standard cells' own strips {by_kind['hvtp outside a well, not a standard cell' + chr(39) + 's']}, "
              f"urpm over a well {by_kind['urpm over a well']}, urpm under 0.70 from a well {by_kind['urpm spacing']} | planted faults: "
              f"{sum(len(p['faults_found']) for p in planted if p['ok'] and p['faults_planted'])} of {n_faults} found, "
              f"{sum(1 for p in PLANTS if not p[2])} patterns at the limit pass" + ("" if planted_ok else " -- THE PLANTED FAULTS DO NOT COME OUT AS PLANTED"))
    res = dict(check="Tiny Tapeout's three n-well rules (lvtn, hvtp, urpm), measured directly", layout=Path(gds).name,
               layout_sha256=hashlib.sha256(Path(gds).read_bytes()).hexdigest(), top=top.name, rules_um=UM, readings=rd,
               faults=own_faults[:50], faults_by_kind=dict(by_kind), planted_faults=planted, planted_faults_ok=planted_ok,
               stray_planted_findings=stray, layout_judgement_unchanged_by_the_plants=unchanged, ok=ok, result=result)
    Path(out).write_text(json.dumps(res, indent=1) + "\n")
    print(result)
    print("  readings:", json.dumps(rd))
    for f in own_faults[:10]:
        print("  ", f)
    for p in planted:
        print(f"  planted {p['pattern']} {'ok ' if p['ok'] else 'BAD'} {p['what']}: planted {p['faults_planted']}, found {p['faults_found']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
