"""Contact bars as SkyWater makes them: every two licon bars far enough apart once mask generation has grown them
(KLayout's Python; reads the layout, writes one JSON file).

  KPY -I licon_bars.py GDS OUT.json      exit 0: the layout passes and every planted fault is found; 1: not; 2: usage

A bar is a licon (66/44) rectangle 0.19 x 2.0 um (the contacts in the heads of a precision poly resistor); every other
licon shape must be a 0.17 um square, or the check fails (a shape it cannot judge). The whole layout is taken flat.
SkyWater makes the licon mask from the drawn bars by growing them, as Tiny Tapeout's and ChipFoundry's decks give it ("per
feedback from Skywater Technology", 2025-11-21): each end of a bar grows 0.03 um; each long side grows 0.03 um unless the
bar lies closer than 0.64 um to another bar, and then its long sides stay. Grown bars must be 0.58 um apart, bars whose
facing sides stayed 0.19 um wide 0.51 um. Every two bars closer than 1 um are judged:

  end to end (their short edges face each other): 0.64 um drawn, 0.58 um once both ends have grown 0.03 um. SkyWater's
      own words on a rejected Tiny Tapeout layout (ttsky26a): "bar licon end to end spacing errors. They need to be
      0.64um apart". Tiny Tapeout's deck (tt-support-tools 7d2d2ef) does not grow the ends of bars closer than 0.64 um to
      another bar, and so passes two bars 0.54 um apart end to end.
  side by side (their long edges face each other): 0.51 um drawn where the facing sides stay (closer than 0.64 um); bars
      0.64 um apart or more grow, and are then 0.58 um apart.
  corner to corner, and two bars of different direction: 0.58 um between the two bars grown 0.03 um on every edge (the
      larger growth and the larger distance; no rule names these cases).
  bar to square contact: 0.51 um (MR_licon.SP.4) between the bar grown 0.03 um on every edge and the square.

Planted faults: the same reading and judgement on the layout with ten test patterns added beside it (in a cell of their
own, outside the layout's box): the short resistor's four bars (0.52 um side by side, 0.54 um end to end) in both
directions, end to end at 0.635 and 0.64 um, side by side at 0.505 and 0.51 um, corner to corner at 0.47 and 0.475 um
in x and in y, a square 0.535 and 0.54 um from a bar's end. Each pattern must give exactly the faults planted in it, at
the planted distance, and none where it sits at the limit; and the layout's own judgement must not change.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import klayout.db as db

LICON = (66, 44)
UM = dict(bar_w=0.19, bar_l=2.0, square=0.17, grow=0.03, keep=0.64, end_min=0.64, side_kept_min=0.51, grown_min=0.58,
          square_min=0.51, reach=1.0)
SLOT, SLOT_GAP = 10.0, 20.0          # um: the planted patterns' pitch, and their distance from the layout's box


def H(x, y):                          # a bar along x, its lower left corner at (x, y), um
    return (x, y, x + 2.0, y + 0.19)


def V(x, y):                          # a bar along y
    return (x, y, x + 0.19, y + 2.0)


def S(x, y):                          # a square contact
    return (x, y, x + 0.17, y + 0.17)


# (what, bars, squares, faults it must give as (relation, drawn um)); coordinates in um within the pattern's slot
PLANTS = [
    ("the short resistor's heads: 0.52 um side by side, 0.54 um end to end", [H(0, 0), H(0, 0.71), H(2.54, 0), H(2.54, 0.71)], [],
     [("end", 0.54), ("end", 0.54)]),
    ("the same turned 90 degrees", [V(0, 0), V(0.71, 0), V(0, 2.54), V(0.71, 2.54)], [], [("end", 0.54), ("end", 0.54)]),
    ("end to end 0.635 um (0.575 grown)", [H(0, 0), H(2.635, 0)], [], [("end", 0.635)]),
    ("end to end 0.64 um, at the limit", [H(0, 0), H(2.64, 0)], [], []),
    ("side by side 0.505 um", [H(0, 0), H(0, 0.695)], [], [("side", 0.505)]),
    ("side by side 0.51 um, at the limit", [H(0, 0), H(0, 0.70)], [], []),
    ("corner to corner 0.47 um in x and in y (0.5798 grown)", [H(0, 0), H(2.47, 0.66)], [], [("corner", 0.6647)]),
    ("corner to corner 0.475 um in x and in y (0.5869 grown)", [H(0, 0), H(2.475, 0.665)], [], []),
    ("a square 0.535 um from a bar's end (0.505 from the grown bar)", [H(0, 0)], [S(2.535, 0)], [("square", 0.535)]),
    ("a square 0.54 um from a bar's end, at the limit", [H(0, 0)], [S(2.54, 0)], []),
]


def flat(ly, top):
    """The licon shapes of the whole layout, merged, and the cell that holds each drawn shape (by its box)."""
    li = ly.find_layer(*LICON)
    if li is None:
        return db.Region(), {}
    held = {}
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        sh = it.shape()
        if sh.is_box() or sh.is_polygon() or sh.is_path():
            b = sh.polygon.transformed(it.trans()).bbox()
            held.setdefault((b.left, b.bottom, b.right, b.top), ly.cell(it.cell_index()).name)
        it.next()
    reg = db.Region(top.begin_shapes_rec(li))
    reg.merge()
    return reg, held


def gaps(a, b):
    return max(0, max(a[0], b[0]) - min(a[2], b[2])), max(0, max(a[1], b[1]) - min(a[3], b[3]))


def near(A, B, reach, same):
    """Pairs (i, j, dx, dy) of boxes of A and B closer than reach (drawn, Euclidean); i < j when A is B."""
    G = 5 * reach
    grid = defaultdict(list)
    for j, b in enumerate(B):
        for gx in range(b[0] // G, b[2] // G + 1):
            for gy in range(b[1] // G, b[3] // G + 1):
                grid[(gx, gy)].append(j)
    for i, a in enumerate(A):
        cand = set()
        for gx in range((a[0] - reach) // G, (a[2] + reach) // G + 1):
            for gy in range((a[1] - reach) // G, (a[3] + reach) // G + 1):
                cand.update(grid.get((gx, gy), ()))
        for j in sorted(cand):
            if same and j <= i:
                continue
            dx, dy = gaps(a, B[j])
            if dx * dx + dy * dy < reach * reach:
                yield i, j, dx, dy


def judge(ly, top, n):
    """Every bar pair and bar-square pair of the layout, judged. n: the rules in database units."""
    reg, held = flat(ly, top)
    bars, vert, squares, other = [], [], [], []
    for p in reg.each():
        b = p.bbox()
        box = (b.left, b.bottom, b.right, b.top)
        if p.is_box() and sorted((b.width(), b.height())) == [n["bar_w"], n["bar_l"]]:
            bars.append(box)
            vert.append(b.height() > b.width())
        elif p.is_box() and b.width() == b.height() == n["square"]:
            squares.append(box)
        else:
            other.append(box)
    pairs = []
    g2 = 2 * n["grow"]
    for i, j, dx, dy in near(bars, bars, n["reach"], True):
        if vert[i] != vert[j]:
            rel = "across"
        elif dx > 0 and dy > 0:
            rel = "corner"
        elif dx == 0 and dy == 0:
            rel = "touch"
        else:
            rel = "end" if (dy if vert[i] else dx) > 0 else "side"
        drawn2 = dx * dx + dy * dy
        if rel == "end":                       # both ends grow
            post2, need = (math.isqrt(drawn2) - g2) ** 2 if math.isqrt(drawn2) > g2 else 0, n["grown_min"]
            bad = math.isqrt(drawn2) - g2 < n["grown_min"]
        elif rel == "side" and drawn2 < n["keep"] ** 2:     # the facing sides stay
            post2, need = drawn2, n["side_kept_min"]
            bad = drawn2 < need * need
        elif rel == "side":                    # both facing sides grow
            post2, need = (math.isqrt(drawn2) - g2) ** 2, n["grown_min"]
            bad = math.isqrt(drawn2) - g2 < need
        elif rel in ("corner", "across"):      # every edge grows
            ex, ey = max(0, dx - g2), max(0, dy - g2)
            post2, need = ex * ex + ey * ey, n["grown_min"]
            bad = post2 < need * need
        else:
            post2, need, bad = 0, n["grown_min"], True
        pairs.append(dict(a=i, b=j, rel=rel, drawn2=drawn2, post2=post2, need=need, bad=bad))
    sq = []
    for i, j, dx, dy in near(bars, squares, n["reach"], False):
        ex, ey = max(0, dx - n["grow"]), max(0, dy - n["grow"])
        post2 = ex * ex + ey * ey
        sq.append(dict(a=i, b=j, rel="square", drawn2=dx * dx + dy * dy, post2=post2, need=n["square_min"], bad=post2 < n["square_min"] ** 2))
    return dict(bars=bars, vert=vert, squares=squares, other=other, pairs=pairs, sq=sq, held=held)


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
    u = lambda v: round(v * dbu, 4)
    box_um = lambda b: [u(v) for v in b]

    def report(r, p, other_list):
        a = r["bars"][p["a"]]
        b = other_list[p["b"]]
        return dict(relation=p["rel"], drawn_um=u(math.sqrt(p["drawn2"])), after_growth_um=u(math.sqrt(p["post2"])), required_um=u(p["need"]),
                    bar_um=box_um(a), other_um=box_um(b), cells=sorted({r["held"].get(a, "?"), r["held"].get(b, "?")}))

    bbox = top.bbox()
    r0 = judge(ly, top, n)
    own_bad = sorted((report(r0, p, r0["bars"]) for p in r0["pairs"] if p["bad"]), key=lambda x: (x["drawn_um"], x["bar_um"]))
    own_sq_bad = sorted((report(r0, p, r0["squares"]) for p in r0["sq"] if p["bad"]), key=lambda x: (x["drawn_um"], x["bar_um"]))
    closest = {}
    for p in r0["pairs"] + r0["sq"]:
        k, margin = p["rel"], math.sqrt(p["post2"]) - p["need"]
        if k not in closest or margin < closest[k][0]:
            closest[k] = (margin, p)
    closest = {k: report(r0, p, r0["squares"] if k == "square" else r0["bars"]) for k, (_, p) in sorted(closest.items())}
    counts = defaultdict(int)
    for p in r0["pairs"]:
        counts[p["rel"]] += 1

    # planted faults: the patterns in a cell of their own beside the layout, then the same reading and judgement
    x0 = bbox.right + round(SLOT_GAP / dbu)
    y0 = bbox.bottom + round(SLOT_GAP / dbu)
    pc = ly.create_cell("planted_licon_bar_faults")
    li = ly.layer(*LICON)
    for k, (_, bars, squares, _) in enumerate(PLANTS):
        for x1, y1, x2, y2 in bars + squares:
            pc.shapes(li).insert(db.DBox(x1, y1, x2, y2).moved(k * SLOT, 0).to_itype(dbu).moved(db.Vector(x0, y0)))
    top.insert(db.CellInstArray(pc.cell_index(), db.Trans()))
    r1 = judge(ly, top, n)
    inside = lambda b: b[2] <= bbox.right

    def own(r):
        return sorted((*sorted((tuple(r["bars"][p["a"]]), tuple(r["bars"][p["b"]]))), p["rel"], p["drawn2"], p["bad"]) for p in r["pairs"]
                      if inside(r["bars"][p["a"]]) and inside(r["bars"][p["b"]]))      # each pair by its two boxes, in either order

    unchanged = own(r0) == own(r1) and len(r1["bars"]) == len(r0["bars"]) + sum(len(p[1]) for p in PLANTS) \
        and len(r1["squares"]) == len(r0["squares"]) + sum(len(p[2]) for p in PLANTS) and sorted(r1["other"]) == sorted(r0["other"])
    found = defaultdict(list)
    for p in r1["pairs"] + r1["sq"]:
        a = r1["bars"][p["a"]]
        if p["bad"] and not inside(a):
            found[(a[0] - x0) // round(SLOT / dbu)].append((p["rel"], round(math.sqrt(p["drawn2"]) * dbu, 4)))
    planted = []
    for k, (what, bars, squares, expect) in enumerate(PLANTS):
        got = sorted(found.get(k, []))
        planted.append(dict(pattern=k + 1, what=what, faults_planted=[list(e) for e in sorted(expect)], faults_found=[list(g) for g in got],
                            ok=got == sorted(expect)))
    planted_ok = all(p["ok"] for p in planted) and unchanged and not (set(found) - set(range(len(PLANTS))))
    n_faults = sum(len(p[3]) for p in PLANTS)
    caught = sum(len(p["faults_found"]) for p in planted if p["ok"] and p["faults_planted"])
    ok = not own_bad and not own_sq_bad and not r0["other"] and planted_ok
    result = (f"RESULT: {'PASS' if ok else 'FAIL'} | {len(r0['bars'])} bars, {len(r0['squares'])} squares, {len(r0['other'])} other licon shapes | "
              f"{len(own_bad)} bar pairs and {len(own_sq_bad)} bar-square pairs too close after mask growth"
              + (f" (closest end to end {min(x['drawn_um'] for x in own_bad if x['relation'] == 'end')} um)" if any(x["relation"] == "end" for x in own_bad) else "")
              + f" | planted faults: {caught} of {n_faults} found as planted, {sum(1 for p in PLANTS if not p[3])} patterns at the limit pass"
              + ("" if planted_ok else " -- THE PLANTED FAULTS DO NOT COME OUT AS PLANTED"))
    res = dict(check="contact bars after SkyWater's mask growth (licon bars 0.19 x 2.0 um)", layout=Path(gds).name,
               layout_sha256=hashlib.sha256(Path(gds).read_bytes()).hexdigest(), top=top.name, rules_um=UM,
               bars=len(r0["bars"]), bars_along_y=sum(r0["vert"]), squares=len(r0["squares"]),
               other_licon_shapes=[box_um(b) for b in r0["other"][:20]], pairs_closer_than_1um=dict(sorted(counts.items())),
               closest_to_its_limit=closest, too_close=own_bad, bar_to_square_too_close=own_sq_bad,
               planted_faults=planted, planted_faults_ok=planted_ok, layout_judgement_unchanged_by_the_plants=unchanged,
               ok=ok, result=result)
    Path(out).write_text(json.dumps(res, indent=1) + "\n")
    print(result)
    for x in own_bad[:10] + own_sq_bad[:10]:
        print(f"  {x['relation']}: {x['drawn_um']} um drawn, {x['after_growth_um']} after growth, {x['required_um']} required: "
              f"{x['bar_um']} / {x['other_um']} in {', '.join(x['cells'])}")
    for k, x in closest.items():
        print(f"  closest {k}: {x['drawn_um']} um drawn, {x['after_growth_um']} after growth (required {x['required_um']})")
    for p in planted:
        print(f"  planted {p['pattern']:2d} {'ok ' if p['ok'] else 'BAD'} {p['what']}: planted {p['faults_planted']}, found {p['faults_found']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
