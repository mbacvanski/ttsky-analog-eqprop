"""Every poly resistor's body at least 0.66 um long in the direction its current flows (SkyWater's MR_poly.LEN.2, as the
foundry measures it; KLayout's Python; reads the layout, writes one JSON file).

  KPY -I res_length.py GDS OUT.json      exit 0: the layout passes and every planted fault is found; 1: not; 2: usage

A body is the resistive poly: poly (66/20) under the poly-resistor marker (66/13), merged, the whole layout flat. Its two
ends are where the poly goes on beyond the marker (the heads, which hold the contacts), and the current flows from one to
the other: the length is the body's extent in that direction, the width its extent across. The ends are found from the
heads alone (for each side of the body's rectangle, the head poly just outside it); a body must be a rectangle with head
poly on exactly two opposite sides, or the check fails (to be measured by hand). Where the heads hold contact bars
(licon 0.19 x 2.0 um, which run along the current), the bars must lie in the direction found, a second reading of it.
SkyWater's rule names the high-ohm resistors (rpoly_hp, rpoly_hp2K: two ttsky26b layouts were removed for bodies of 0.52
and 0.55 um, "needs to be 0.66um"); it is applied here to every body, and each body's implant (urpm 79/20, rpm 86/20 or
none) is reported. Tiny Tapeout's deck (tt-support-tools 7d2d2ef) tests the longer side of the body's box against 0.66 um,
so that a short body on a wide resistor (1.41 um wide, 0.54 um long) passes it; its reading is reported beside ours.

Planted faults: two of the layout's own resistors (the first with contact bars, and the first without, if there is one;
else a plain one drawn here), each copied with its poly, marker, contacts and implants, cut across its body and closed up
to a chosen length, and placed beside the layout (in a cell of their own, outside the layout's box); then the same
reading and judgement on the layout with them. The barred one at 0.54 um (and the same turned 90 degrees), 0.655 um and
0.66 um; the one without bars at 0.60 and 0.66 um. Each must be measured at exactly its planted length and direction,
those under 0.66 um must fail and those at 0.66 um pass, and the layout's own judgement must not change.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import klayout.db as db

POLY, RES, LICON, URPM, RPM = (66, 20), (66, 13), (66, 44), (79, 20), (86, 20)
MIN_UM = 0.66
BAR_UM = (0.19, 2.0)
GAP_UM = 20.0                        # the planted resistors' distance from the layout's box, and from each other: 10 um
# (name, template, planted length um, turned 90 degrees)
PLANTS = [("contact bars, 0.54 um", "bars", 0.54, False), ("contact bars, 0.54 um, turned 90 degrees", "bars", 0.54, True),
          ("contact bars, 0.655 um", "bars", 0.655, False), ("contact bars, 0.66 um, at the limit", "bars", 0.66, False),
          ("no contact bars, 0.60 um", "plain", 0.60, False), ("no contact bars, 0.66 um, at the limit", "plain", 0.66, False)]


def region(ly, top, ld):
    li = ly.find_layer(*ld)
    r = db.Region() if li is None else db.Region(top.begin_shapes_rec(li))
    r.merge()
    return r


def holders(ly, top, ld):
    """(box, cell) of every drawn shape of one layer, flat."""
    li = ly.find_layer(*ld)
    out = []
    if li is None:
        return out
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        sh = it.shape()
        if sh.is_box() or sh.is_polygon() or sh.is_path():
            out.append((sh.polygon.transformed(it.trans()).bbox(), ly.cell(it.cell_index()).name))
        it.next()
    return out


def measure(ly, top):
    """Every body of the layout: its box, direction, length and width (database units), and what was found about it."""
    dbu = ly.dbu
    poly, rs, licon, urpm, rpm = (region(ly, top, ld) for ld in (POLY, RES, LICON, URPM, RPM))
    bodies = (poly & rs).merged()
    heads = (poly - rs).interacting(bodies.sized(1))          # only the head poly that touches a body
    bw, bl = round(BAR_UM[0] / dbu), round(BAR_UM[1] / dbu)
    bars = db.Region()
    bar_vert = {}
    for p in licon.each():
        b = p.bbox()
        if p.is_box() and sorted((b.width(), b.height())) == [bw, bl]:
            bars.insert(b)
            bar_vert[(b.left, b.bottom, b.right, b.top)] = b.height() > b.width()
    held = holders(ly, top, RES)
    rows = []
    for body in bodies.each():
        b = body.bbox()
        row = dict(box=(b.left, b.bottom, b.right, b.top), rect=body.is_box(), axis=None, L=None, W=None, why=None)
        near = heads.interacting(db.Region(b.enlarged(db.Vector(1, 1))))
        strips = dict(left=db.Box(b.left - 1, b.bottom, b.left, b.top), right=db.Box(b.right, b.bottom, b.right + 1, b.top),
                      bottom=db.Box(b.left, b.bottom - 1, b.right, b.bottom), top=db.Box(b.left, b.top, b.right, b.top + 1))
        touch = {s: (near & db.Region(x)).area() for s, x in strips.items()}    # strips 1 unit thick: area = length touched
        ends = sorted(s for s, v in touch.items() if v > 0)
        if not row["rect"]:
            row["why"] = "not a rectangle: measure it by hand"
        elif ends == ["left", "right"]:
            row.update(axis="x", L=b.width(), W=b.height())
        elif ends == ["bottom", "top"]:
            row.update(axis="y", L=b.height(), W=b.width())
        else:
            row["why"] = f"head poly on {', '.join(ends) if ends else 'no side'}: its ends cannot be told; measure it by hand"
        row["ends_touched"] = {s: touch[s] for s in ends}
        own_poly = poly.interacting(db.Region(body))
        inb = [bar_vert[(q.bbox().left, q.bbox().bottom, q.bbox().right, q.bbox().top)] for q in bars.inside(own_poly).each()]
        row["bars_along"] = sum(1 for v in inb if row["axis"] and v == (row["axis"] == "y"))
        row["bars_across"] = len(inb) - row["bars_along"] if row["axis"] else None
        row["n_bars"] = len(inb)
        if row["axis"] and inb and row["bars_along"] == 0:
            row["why"] = "its contact bars lie across the direction its heads give: measure it by hand"
        row["bodies_in_its_poly"] = (bodies & own_poly).merged().count()
        r1 = db.Region(body)
        row["implant"] = "urpm" if not (urpm & r1).is_empty() else ("rpm" if not (rpm & r1).is_empty() else "none")
        row["cells"] = sorted({c for bb, c in held if bb.overlaps(b)})
        row["deck_flags_it"] = max(b.width(), b.height()) < round(MIN_UM / dbu)
        row["ok"] = row["why"] is None and row["L"] >= round(MIN_UM / dbu)
        rows.append(row)
    return rows, dict(poly=poly, rs=rs, licon=licon, urpm=urpm, rpm=rpm, bodies=bodies, dbu=dbu)


def template_shapes(regs, row):
    """The layers of one resistor: its poly, its marker over that poly, the contacts inside it, the implants over it."""
    b = db.Box(*row["box"])
    own = regs["poly"].interacting(db.Region(b))
    half = round(0.5 / regs["dbu"])
    win = db.Region(own.bbox().enlarged(db.Vector(half, half)))
    return {POLY: own, RES: regs["rs"] & own, LICON: regs["licon"].inside(own), URPM: regs["urpm"] & win, RPM: regs["rpm"] & win}


def plain_template(dbu):
    """A plain poly resistor 0.35 um wide, body 1.0 um long between two heads of one square contact each."""
    u = lambda v: round(v / dbu)
    poly = db.Region(db.Box(0, 0, u(2.2), u(0.35)))
    rs = db.Region(db.Box(u(0.6), 0, u(1.6), u(0.35)))
    lic = db.Region(db.Box(u(0.2), u(0.09), u(0.37), u(0.26))) + db.Region(db.Box(u(1.83), u(0.09), u(2.0), u(0.26)))
    row = dict(box=(u(0.6), 0, u(1.6), u(0.35)), axis="x", L=u(1.0))
    return {POLY: poly, RES: rs, LICON: lic, URPM: db.Region(), RPM: db.Region()}, row


def shortened(shapes, row, length):
    """The resistor cut across its body and closed up so that the body is `length` long (database units)."""
    l0, b0, r0, t0 = row["box"]
    lo, hi = (l0, r0) if row["axis"] == "x" else (b0, t0)
    h1 = length // 2
    h2 = length - h1
    shift = (hi - lo) - length
    big = 10 ** 7
    out = {}
    for ld, reg in shapes.items():
        if row["axis"] == "x":
            nearp = reg & db.Region(db.Box(-big, -big, lo + h1, big))
            farp = (reg & db.Region(db.Box(hi - h2, -big, big, big))).moved(-shift, 0)
        else:
            nearp = reg & db.Region(db.Box(-big, -big, big, lo + h1))
            farp = (reg & db.Region(db.Box(-big, hi - h2, big, big))).moved(0, -shift)
        out[ld] = (nearp + farp).merged()
    return out


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
    u = lambda v: None if v is None else round(v * dbu, 4)
    lim = round(MIN_UM / dbu)
    bbox = top.bbox()
    rows, regs = measure(ly, top)

    def show(r):
        return dict(box_um=[u(v) for v in r["box"]], length_um=u(r["L"]), width_um=u(r["W"]), current_along=r["axis"], implant=r["implant"],
                    contact_bars=r["n_bars"], bars_across=r["bars_across"], cells=r["cells"], tiny_tapeout_deck_flags_it=r["deck_flags_it"],
                    why=r["why"])

    bad = [r for r in rows if not r["ok"]]
    # templates for the planted faults: the first resistor (by position) with contact bars, alone in its poly, long enough to
    # be cut to 0.66 um; and the first without bars, or a plain one drawn here
    usable = [r for r in sorted(rows, key=lambda r: (r["box"][1], r["box"][0])) if r["ok"] and r["bodies_in_its_poly"] == 1 and r["L"] > lim]
    t_bars = next((r for r in usable if r["n_bars"] and r["bars_across"] == 0), None)
    t_plain = next((r for r in usable if r["n_bars"] == 0), None)
    templates = {}
    if t_bars:
        templates["bars"] = (template_shapes(regs, t_bars), t_bars, "the layout's own: " + ", ".join(t_bars["cells"]))
    if t_plain:
        templates["plain"] = (template_shapes(regs, t_plain), t_plain, "the layout's own: " + ", ".join(t_plain["cells"]))
    else:
        s, r = plain_template(dbu)
        templates["plain"] = (s, r, "drawn here: 0.35 um wide, one square contact in each head")
    pc = ly.create_cell("planted_res_length_faults")
    x = bbox.right + round(GAP_UM / dbu)
    slots = []
    for name, tk, length_um, turn in PLANTS:
        if tk not in templates:
            slots.append(None)
            continue
        shapes, row, _ = templates[tk]
        s = shortened(shapes, row, round(length_um / dbu))
        if turn:
            s = {ld: reg.transformed(db.Trans(db.Trans.R90)) for ld, reg in s.items()}
        allb = db.Region()
        for reg in s.values():
            allb += reg
        bb = allb.bbox()
        mv = db.Vector(x - bb.left, bbox.bottom + round(GAP_UM / dbu) - bb.bottom)
        for ld, reg in s.items():
            pc.shapes(ly.layer(*ld)).insert(reg.moved(mv))
        slots.append((x, x + bb.width()))
        x += bb.width() + round(GAP_UM / 2 / dbu)
    top.insert(db.CellInstArray(pc.cell_index(), db.Trans()))
    rows1, _ = measure(ly, top)
    inside = lambda r: r["box"][2] <= bbox.right
    key = lambda r: (r["box"], r["axis"], r["L"], r["W"], r["ok"], r["why"], r["n_bars"])
    unchanged = sorted(map(key, filter(inside, rows1))) == sorted(map(key, rows))
    planted = []
    for (name, tk, length_um, turn), sl in zip(PLANTS, slots):
        want_axis = None
        if sl is None:
            planted.append(dict(what=name, ok=False, why="no resistor of this kind to copy"))
            continue
        base = templates[tk][1]["axis"]
        want_axis = ("y" if base == "x" else "x") if turn else base
        got = [r for r in rows1 if not inside(r) and sl[0] <= r["box"][0] and r["box"][2] <= sl[1]]
        g = got[0] if len(got) == 1 else None
        ok = bool(g) and g["L"] == round(length_um / dbu) and g["axis"] == want_axis and g["ok"] == (round(length_um / dbu) >= lim) and g["why"] is None
        planted.append(dict(what=name, copied_from=templates[tk][2], planted_length_um=length_um, current_along=want_axis,
                            must=("pass" if round(length_um / dbu) >= lim else "fail"),
                            measured=[show(r) for r in got], judged=("pass" if g and g["ok"] else "fail") if g else None, ok=ok))
    planted_ok = unchanged and all(p["ok"] for p in planted)
    n_fail = sum(1 for p in planted if p.get("must") == "fail")
    caught = sum(1 for p in planted if p.get("must") == "fail" and p["ok"])
    passes = sum(1 for p in planted if p.get("must") == "pass" and p["ok"])
    ok = not bad and planted_ok
    shortest = sorted((r for r in rows if r["L"] is not None), key=lambda r: r["L"])
    deck_misses = [r for r in bad if r["L"] is not None and not r["deck_flags_it"]]
    where = "; ".join((("%s x %s um in %s" % (u(r["L"]), u(r["W"]), ", ".join(r["cells"]))) if r["L"] else r["why"]) for r in bad[:4])
    result = (f"RESULT: {'PASS' if ok else 'FAIL'} | {len(rows)} resistor bodies, {len(bad)} shorter than {MIN_UM} um along the current or not measurable"
              + (f" ({where}), of which Tiny Tapeout's deck flags {len(bad) - len(deck_misses)}" if bad else "")
              + f" | shortest {u(shortest[0]['L']) if shortest else None} um | planted faults: {caught} of {n_fail} found at their planted length, "
              f"{passes} of {len(planted) - n_fail} at the limit pass" + ("" if planted_ok else " -- THE PLANTED FAULTS DO NOT COME OUT AS PLANTED"))
    res = dict(check="poly resistor bodies at least 0.66 um long along the current (SkyWater MR_poly.LEN.2, measured along the current)",
               layout=Path(gds).name, layout_sha256=hashlib.sha256(Path(gds).read_bytes()).hexdigest(), top=top.name, minimum_um=MIN_UM,
               bodies=len(rows), by_implant={k: sum(1 for r in rows if r["implant"] == k) for k in ("urpm", "rpm", "none")},
               along_x=sum(1 for r in rows if r["axis"] == "x"), along_y=sum(1 for r in rows if r["axis"] == "y"),
               with_contact_bars=sum(1 for r in rows if r["n_bars"]), widths_um=sorted({u(r["W"]) for r in rows if r["W"]}),
               failing=[show(r) for r in bad], shortest=[show(r) for r in shortest[:5]],
               tiny_tapeout_deck_flags=sum(1 for r in rows if r["deck_flags_it"]),
               planted_faults=planted, planted_faults_ok=planted_ok, layout_judgement_unchanged_by_the_plants=unchanged, ok=ok, result=result)
    Path(out).write_text(json.dumps(res, indent=1) + "\n")
    print(result)
    for r in bad[:10]:
        print(f"  {show(r)}")
    for r in shortest[:3]:
        print(f"  shortest: {u(r['L'])} x {u(r['W'])} um along {r['axis']} ({r['implant']}, {r['n_bars']} bars) in {', '.join(r['cells'])}")
    for p in planted:
        m = p.get("measured") or []
        print(f"  planted {'ok ' if p['ok'] else 'BAD'} {p['what']} ({p.get('copied_from')}): must {p.get('must')}, measured "
              f"{[(x['length_um'], x['width_um'], x['current_along']) for x in m]}, judged {p.get('judged')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
