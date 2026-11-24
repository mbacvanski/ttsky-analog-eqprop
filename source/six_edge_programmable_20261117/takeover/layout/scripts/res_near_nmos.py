"""Precision resistors beside NMOS transistors, held to this layout's distances (KLayout's Python; reads the layout,
writes one JSON file).

  KPY -I res_near_nmos.py GDS OUT.json      exit 0: no distance below lock4_r's and every planted fault found; 1: not; 2: usage

On ttsky26a SkyWater asked one project to move a precision resistor "up a minimum of 0.18um" (Tiny Tapeout's pull
request 446): that rpm resistor's edge had been 0.75 um from an NMOS's gate poly and 0.875 um from its nsdm. The rule
behind it is not public, nor whether it covers urpm. This layout has urpm resistors only, and SkyWater accepted urpm
closer than ours in that same run. So the distances are reported and held where lock4_r has them (lock3_r's are the
same): no layout may bring a precision resistor closer to an NMOS than they are now.
For the precision-resistor markers (rpm 86/20 or urpm 79/20 over a poly resistor body 66/13), flat, Euclidean, the
smallest distance from the marker, from the resistors' poly and from their contacts (licon on that poly) to NMOS gate
poly (poly that crosses diffusion AND nsdm and is no resistor's) and to nsdm; and from the marker to PMOS gate poly,
reported only. Limits (lock4_r's, um): marker to NMOS gate poly 0.69, resistor poly to NMOS gate poly 0.89, contacts to
NMOS gate poly 0.97, marker to nsdm 0.275, contacts to nsdm 0.555.
Planted faults: three urpm resistors with an NMOS beside each, beside the layout (a cell of their own), measured each in
its own window: the NMOS's nsdm 0.25 um from the marker (must be found), the same at 0.275 um (the limit: must pass),
and nsdm at 0.30 um with the gate's poly reaching 0.60 um from the marker (must be found, as the gate-poly distance).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import klayout.db as db

POLY, RES, LICON, RPM, URPM, NSDM, PSDM, DIFF = (66, 20), (66, 13), (66, 44), (86, 20), (79, 20), (93, 44), (94, 20), (65, 20)
LIMITS = dict(marker_to_nmos_gate_poly=0.69, respoly_to_nmos_gate_poly=0.89, contacts_to_nmos_gate_poly=0.97, marker_to_nsdm=0.275,
              contacts_to_nsdm=0.555)
SLOT, GAP = 12.0, 20.0


def nmos(dx, stub=None):
    """A urpm resistor (marker 0..2 x 0..4 um) and an NMOS whose nsdm starts dx um to its right; stub: the gate's poly
    reaching that close to the marker."""
    x = 2.0 + dx
    shapes = {URPM: [(0, 0, 2, 4)], RES: [(0.5, 1.0, 1.5, 3.0)], POLY: [(0.5, 0.2, 1.5, 3.8), (x + 0.9, 0.5, x + 1.05, 3.5)],
              NSDM: [(x, 0.5, x + 2.0, 3.5)], DIFF: [(x + 0.13, 0.7, x + 1.87, 3.3)]}
    if stub is not None:
        shapes[POLY].append((2.0 + stub, 3.35, x + 1.05, 3.5))
    return shapes


PLANTS = [("nsdm 0.25 um from the marker", nmos(0.25), ["marker_to_nsdm"]),
          ("nsdm 0.275 um from the marker, at the limit", nmos(0.275), []),
          ("nsdm 0.30 um away, the gate's poly 0.60 um from the marker", nmos(0.30, stub=0.60), ["marker_to_nmos_gate_poly"])]


def regions(ly, top, window=None):
    out = {}
    for ld in (POLY, RES, LICON, RPM, URPM, NSDM, PSDM, DIFF):
        li = ly.find_layer(*ld)
        r = db.Region() if li is None else db.Region(top.begin_shapes_rec(li))
        if window is not None:
            r = r & db.Region(window)
        out[ld] = r.merged()
    return out


def distances(r, dbu):
    marker = (r[RPM] + r[URPM]).merged()
    respoly = r[POLY].interacting(r[RES]).interacting(marker)
    m = marker.interacting(respoly)
    nmos_poly = r[POLY].not_interacting(respoly).interacting(r[DIFF] & r[NSDM])
    pmos_poly = r[POLY].not_interacting(respoly).interacting(r[DIFF] & r[PSDM])
    contacts = r[LICON].interacting(respoly)
    reach = round(3.0 / dbu)

    def md(a, b):
        if a.is_empty() or b.is_empty():
            return None
        if not (a & b).is_empty():
            return 0.0
        ep = a.separation_check(b, reach, False, db.Metrics.Euclidian)
        return round(min(e.distance() for e in ep.each()) * dbu, 4) if not ep.is_empty() else None

    return dict(markers=m.count(), marker_to_nmos_gate_poly=md(m, nmos_poly), respoly_to_nmos_gate_poly=md(respoly, nmos_poly),
                contacts_to_nmos_gate_poly=md(contacts, nmos_poly), marker_to_nsdm=md(m, r[NSDM]), contacts_to_nsdm=md(contacts, r[NSDM]),
                marker_to_pmos_gate_poly=md(m, pmos_poly))


def below(d):
    """The judged distances under their limits (None: nothing within 3 um)."""
    return sorted(k for k, lim in LIMITS.items() if d.get(k) is not None and d[k] < lim - 1e-9)


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
    bbox = top.bbox()
    own = distances(regions(ly, top), dbu)
    bad = below(own)
    x0, y0 = bbox.right + round(GAP / dbu), bbox.bottom + round(GAP / dbu)
    pc = ly.create_cell("planted_res_near_nmos_faults")
    for k, (_, shapes, _) in enumerate(PLANTS):
        for ld, boxes in shapes.items():
            for b in boxes:
                pc.shapes(ly.layer(*ld)).insert(db.DBox(*b).moved(k * SLOT, 0).to_itype(dbu).moved(db.Vector(x0, y0)))
    top.insert(db.CellInstArray(pc.cell_index(), db.Trans()))
    again = distances(regions(ly, top, bbox), dbu)           # the layout's own window, with the plants beside it
    planted = []
    for k, (what, _, expect) in enumerate(PLANTS):
        win = db.Box(x0 + round((k * SLOT - 1) / dbu), y0 - round(1 / dbu), x0 + round((k * SLOT + SLOT - 2) / dbu), y0 + round(5 / dbu))
        d = distances(regions(ly, top, win), dbu)
        got = below(d)
        planted.append(dict(pattern=k + 1, what=what, distances=d, below_the_limits=got, must_be_below=expect, ok=got == sorted(expect)))
    unchanged = again == own
    planted_ok = unchanged and all(p["ok"] for p in planted)
    ok = not bad and planted_ok
    n_faults = sum(len(p[2]) for p in PLANTS)
    result = (f"RESULT: {'PASS' if ok else 'FAIL'} | {own['markers']} precision-resistor markers | marker to NMOS gate poly {own['marker_to_nmos_gate_poly']}, "
              f"to nsdm {own['marker_to_nsdm']}; resistor poly to NMOS gate poly {own['respoly_to_nmos_gate_poly']}; contacts to NMOS gate poly "
              f"{own['contacts_to_nmos_gate_poly']}, to nsdm {own['contacts_to_nsdm']} um" + (f" | BELOW lock4_r's: {bad}" if bad else " | none below lock4_r's")
              + f" | planted faults: {sum(1 for p in planted if p['ok'] and p['must_be_below'])} of {n_faults} found, "
              f"{sum(1 for p in planted if p['ok'] and not p['must_be_below'])} at the limit pass" + ("" if planted_ok else " -- THE PLANTED FAULTS DO NOT COME OUT AS PLANTED"))
    res = dict(check="precision resistors beside NMOS, held to lock4_r's distances", layout=Path(gds).name,
               layout_sha256=hashlib.sha256(Path(gds).read_bytes()).hexdigest(), top=top.name, limits_um=LIMITS, distances_um=own,
               below_the_limits=bad, planted_faults=planted, planted_faults_ok=planted_ok, layout_judgement_unchanged_by_the_plants=unchanged,
               ok=ok, result=result)
    Path(out).write_text(json.dumps(res, indent=1) + "\n")
    print(result)
    for p in planted:
        print(f"  planted {p['pattern']} {'ok ' if p['ok'] else 'BAD'} {p['what']}: below {p['below_the_limits']} (must be {p['must_be_below']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
