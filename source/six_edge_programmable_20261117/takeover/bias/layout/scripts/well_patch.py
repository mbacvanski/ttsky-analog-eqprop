"""The n-well patch for Tiny Tapeout's lvtn.10 rule (n-well encloses lvtn by 0.38 um, Euclidean; tools 7d2d2ef):
n-well rectangles added at top level, nothing else changed.

  KPY well_patch.py design IN.gds PATCH.json      derive the rectangles from a layout (flat geometry), with a record
  KPY well_patch.py apply  IN.gds PATCH.json OUT.gds    add them to a layout (top cell, layer 64/20), deterministic save
  KPY well_patch.py design2 IN.gds PATCH.json [HVI_NM]   per-side design with drawn HVI kept HVI_NM away (default 640)

Design, for every n-well (flat, merged) that holds lvtn closer than 0.38 um to its edge: grow it around its lvtn by the
first of these that keeps every neighbour rule with at least 0.01 um to spare:
  0.40 square, 0.39 square, 0.40 stepped, 0.39 stepped, 0.38 square, 0.38 stepped
(square: the lvtn's corners grown square; stepped: each corner grown by d in one direction and d/sqrt(2), rounded up to
the grid, in the other, both ways, so that every point of the new edge is at least d from the lvtn, Euclidean); if none
keeps the spare, the first that meets the rules exactly (recorded as at the limit). Only what lies outside every
existing n-well is added. Neighbour rules (Magic's sky130A deck, drc(full)): n+ diffusion 0.34 um, 5 V / native
diffusion and taps under hvi 0.825 um (MV diffusion to LV n-well, hvi.5 + nsd/psd.5), substrate p-tap 0.13 um, any
other n-well 1.27 um (2.0 um if either holds hvi), deep n-well 4.5 um. Every coordinate is on the 0.005 um grid.
"""
import hashlib
import json
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / 'layout'))

GRID = 5          # nm
MODES = [('square', 400, 400), ('square', 390, 390), ('stepped', 400, 285), ('stepped', 390, 280),
         ('square', 380, 380), ('stepped', 380, 270)]
SPARE = 10        # nm kept beyond every neighbour rule where possible
RULES = {'n+ diffusion': 340, '5V/native diffusion (MV diffusion to LV n-well)': 825, 'substrate p-tap': 130, 'other n-well': 1270,
         'other n-well (5V)': 2000, 'deep n-well': 4500}


def R(ly, top, l, d):
    return db.Region(top.begin_shapes_rec(ly.layer(l, d))).merged()


def grown(lv, d, a):
    """lvtn grown by d with square corners (a == d) or stepped corners (a < d)."""
    out = db.Region()
    for p in lv.decompose_trapezoids_to_region().each():
        b = p.bbox()
        out.insert(db.Box(b.left - d, b.bottom - a, b.right + d, b.top + a))
        out.insert(db.Box(b.left - a, b.bottom - d, b.right + a, b.top + d))
    return out.merged()


def min_space(a, b, limit):
    """Smallest Euclidean distance (nm) between a and b if under `limit`, 0 on overlap, None if all farther."""
    if a.is_empty() or b.is_empty():
        return None
    if not (a & b).is_empty():
        return 0
    ep = a.separation_check(b, limit + 1, False, db.Metrics.Euclidian)
    d = [e.distance() for e in ep.each()]
    return min(d) if d else None


def design(src, dst):
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell(); dbu = ly.dbu
    nw, lvtn = R(ly, top, 64, 20), R(ly, top, 125, 44)
    diff, tap, nsdm, psdm, hvi, dnw = (R(ly, top, *x) for x in ((65, 20), (65, 44), (93, 44), (94, 20), (75, 20), (64, 18)))
    ndiff = ((diff & nsdm) - nw).merged()
    ndiff_lv = (ndiff - hvi).merged()
    mvdiff = (((diff + tap) & hvi) - nw).merged()      # Magic's allmvdiffnowell: MV n-diffusion and MV p-taps
    ptap = ((tap & psdm) - nw).merged()
    hv_wells = nw.interacting(hvi)
    wells, patch = [], db.Region()
    for w in nw.each():
        W = db.Region(w)
        lv = lvtn & W
        if lv.is_empty() or nw.enclosing_check(lv, 380, False, db.Metrics.Euclidian).is_empty():
            continue
        others = nw - W
        rec = None
        for spare in (SPARE, 0):
            for mode, d, a in MODES:
                add = (grown(lv, d, a) - nw).merged()
                checks = {'n+ diffusion': min_space(add, ndiff_lv, 2000),
                          '5V/native diffusion (MV diffusion to LV n-well)': min_space(add, mvdiff, 2000),
                          'substrate p-tap': min_space(add, ptap, 2000),
                          'other n-well': min_space(add, others - hv_wells, 2000), 'other n-well (5V)': min_space(add, others & hv_wells, 2500),
                          'deep n-well': min_space(add, dnw, 5000)}
                if all(v is None or v >= RULES[k] + spare for k, v in checks.items()):
                    rec = dict(mode=mode, enclosure_um=d / 1000, stepped_corner_um=a / 1000 if a != d else None, add=add,
                               spare_um=spare / 1000, at_a_limit=(spare == 0),
                               spacing_after_um={k: (v / 1000 if v is not None else None) for k, v in checks.items()})
                    break
            if rec:
                break
        if rec is None:
            raise SystemExit(f'no added-well shape fits for the well at {w.bbox().to_dtype(dbu)}')
        add = rec.pop('add')
        neww = (W + add).merged()
        if not nw.enclosing_check(lv, 380, False, db.Metrics.Euclidian).is_empty() and \
           not (neww + others).merged().enclosing_check(lv, 380, False, db.Metrics.Euclidian).is_empty():
            raise SystemExit(f'patch does not reach 0.38 at {w.bbox().to_dtype(dbu)}')
        p_old, p_new = w.perimeter(), sum(p.perimeter() for p in neww.each())
        rec.update(well_bbox_um=str(w.bbox().to_dtype(dbu)), lvtn_bbox_um=str(lv.bbox().to_dtype(dbu)),
                   well_area_um2=round(w.area() * dbu * dbu, 3), added_area_um2=round(add.area() * dbu * dbu, 4),
                   area_growth_pct=round(100 * add.area() / w.area(), 2), well_perimeter_um=round(p_old * dbu, 3),
                   perimeter_change_um=round((p_new - p_old) * dbu, 3), perimeter_growth_pct=round(100 * (p_new - p_old) / p_old, 2),
                   added_boxes_um=[[round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)]
                                   for b in (q.bbox() for q in add.decompose_trapezoids_to_region().each())])
        wells.append(rec)
        patch += add
    patch = patch.merged()
    boxes = [[round(v * dbu, 3) for v in (b.left, b.bottom, b.right, b.top)]
             for b in (q.bbox() for q in patch.decompose_trapezoids_to_region().each())]
    for b in boxes:
        assert all(round(v * 1000) % GRID == 0 for v in b), b
    out = dict(layer='nwell 64/20', source_gds_sha256=hashlib.sha256(Path(src).read_bytes()).hexdigest(), rule='lvtn.10: nwell encloses lvtn by 0.38 um, Euclidean',
               boxes_um=boxes, n_boxes=len(boxes), added_area_um2=round(patch.area() * dbu * dbu, 4), wells=wells)
    Path(dst).write_text(json.dumps(out, indent=1) + '\n')
    print(len(wells), 'wells,', len(boxes), 'rectangles,', out['added_area_um2'], 'um2 ->', dst)


HVI_RULE, HVI_SPARE = 640, 5   # lock2_h: drawn HVI at least 0.64 um from a low-voltage n-well, 0.645 where free
SIDES = ('left', 'bottom', 'right', 'top')


def ceil_grid(v):
    return int(-(-v // GRID) * GRID)


def grown_sides(b, ds, mode):
    """One lvtn rectangle b grown per side by ds[side] (nm, 0 = not grown). Each grown side is a strip that reaches past
    the rectangle's ends by d (square corners) or by d/sqrt(2) rounded up (stepped corners), so that every point of the
    new edge is at least d from the lvtn, Euclidean (a side left as it is keeps its own enclosure, at least 0.38)."""
    ext = (lambda d: d) if mode == 'square' else (lambda d: ceil_grid(d * 0.70711))
    out = db.Region()
    d = ds
    if d['bottom']:
        e = ext(d['bottom']); out.insert(db.Box(b.left - e, b.bottom - d['bottom'], b.right + e, b.bottom))
    if d['top']:
        e = ext(d['top']); out.insert(db.Box(b.left - e, b.top, b.right + e, b.top + d['top']))
    if d['left']:
        e = ext(d['left']); out.insert(db.Box(b.left - d['left'], b.bottom - e, b.left, b.top + e))
    if d['right']:
        e = ext(d['right']); out.insert(db.Box(b.right, b.bottom - e, b.right + d['right'], b.top + e))
    if mode == 'square':
        for (sx, sy) in (('left', 'bottom'), ('right', 'bottom'), ('left', 'top'), ('right', 'top')):
            if d[sx] and d[sy]:
                x0, x1 = (b.left - d[sx], b.left) if sx == 'left' else (b.right, b.right + d[sx])
                y0, y1 = (b.bottom - d[sy], b.bottom) if sy == 'bottom' else (b.top, b.top + d[sy])
                out.insert(db.Box(x0, y0, x1, y1))
    return out.merged()


def design2(src, dst, hvi_rule=HVI_RULE):
    """lock2_h: as design(), but the enclosure is chosen per side (0.40, 0.39 or 0.38 on each side that needs to grow),
    and the added n-well must also keep the drawn HVI 0.64 um away (0.645 where free). lock2_r: hvi_rule 700 (0.70 um,
    0.705 where free); the default leaves lock2_h's derivation as it was."""
    import itertools
    hk = f'drawn HVI (hvi.5 at {hvi_rule / 1000:.2f})'
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell(); dbu = ly.dbu
    nw, lvtn = R(ly, top, 64, 20), R(ly, top, 125, 44)
    diff, tap, nsdm, psdm, hvi, dnw = (R(ly, top, *x) for x in ((65, 20), (65, 44), (93, 44), (94, 20), (75, 20), (64, 18)))
    ndiff_lv = (((diff & nsdm) - nw) - hvi).merged()
    mvdiff = (((diff + tap) & hvi) - nw).merged()
    ptap = ((tap & psdm) - nw).merged()
    hv_wells = nw.interacting(hvi)
    rules = dict(RULES, **{hk: hvi_rule})
    wells, patch = [], db.Region()
    for w in nw.each():
        W = db.Region(w)
        lv = (lvtn & W).merged()
        ep = nw.enclosing_check(lv, 380, False, db.Metrics.Euclidian)
        if lv.is_empty() or ep.is_empty():
            continue
        rects = list(lv.decompose_trapezoids_to_region().each())
        assert len(rects) == 1 and rects[0].is_box(), ('lvtn of one well must be one rectangle', str(w.bbox().to_dtype(dbu)))
        b = rects[0].bbox()
        need = set()
        for e in ep.each():
            g = e.second.bbox()
            if g.width() >= g.height():
                need.add('bottom' if abs(g.center().y - b.bottom) <= abs(g.center().y - b.top) else 'top')
            if g.height() >= g.width():
                need.add('left' if abs(g.center().x - b.left) <= abs(g.center().x - b.right) else 'right')
        others = nw - W
        grow = [s_ for s_ in SIDES if s_ in need]
        cands = []
        for vals in itertools.product((400, 390, 380), repeat=len(grow)):
            for mode in ('square', 'stepped'):
                ds = {s_: 0 for s_ in SIDES}
                ds.update(dict(zip(grow, vals)))
                cands.append((min(vals), sum(vals), mode == 'square', ds, mode))
        cands.sort(key=lambda c: (-c[0], -c[1], not c[2]))
        rec = None
        # every rule kept (HVI at least 0.64, every other rule at least 0.005 um clear); among those, in this order:
        # fewest sides at 0.38, HVI at 0.645 or more, every other rule 0.01 um clear, the largest enclosure, square corners
        best = None
        for mind, sumd, sq, ds, mode in cands:
            add = (grown_sides(b, ds, mode) - nw).merged()
            checks = {'n+ diffusion': min_space(add, ndiff_lv, 2000),
                      '5V/native diffusion (MV diffusion to LV n-well)': min_space(add, mvdiff, 2000),
                      hk: min_space(add, hvi, 2000),
                      'substrate p-tap': min_space(add, ptap, 2000),
                      'other n-well': min_space(add, others - hv_wells, 2000), 'other n-well (5V)': min_space(add, others & hv_wells, 2500),
                      'deep n-well': min_space(add, dnw, 5000)}
            if not all(v is None or v >= rules[k] + (0 if k == hk else 5) for k, v in checks.items()):
                continue
            hvi_spare = checks[hk] is None or checks[hk] >= hvi_rule + HVI_SPARE
            others_spare = all(v is None or v >= rules[k] + SPARE for k, v in checks.items() if k != hk)
            n38 = sum(1 for s_ in grow if ds[s_] == 380)
            score = (-n38, hvi_spare, others_spare, mind, sumd, sq)
            if best is None or score > best[0]:
                best = (score, ds, mode, add, checks, hvi_spare, others_spare)
        if best:
            score, ds, mode, add, checks, hvi_spare, others_spare = best
            limits = ([] if hvi_spare else [f'HVI at {hvi_rule / 1000:.2f}']) + ([] if others_spare else
                      [k for k, v in checks.items() if k != hk and v is not None and v < rules[k] + SPARE])
            rec = dict(mode=mode, enclosure_um={s_: ds[s_] / 1000 for s_ in SIDES if ds[s_]}, add=add,
                       sides_at_0p38=[s_ for s_ in grow if ds[s_] == 380], within_0p01_of_a_rule=limits,
                       spacing_after_um={k: (v / 1000 if v is not None else None) for k, v in checks.items()})
        if rec is None:
            raise SystemExit(f'no added-well shape fits for the well at {w.bbox().to_dtype(dbu)}')
        add = rec.pop('add')
        neww = (W + add).merged()
        assert (neww + others).merged().enclosing_check(lv, 380, False, db.Metrics.Euclidian).is_empty(), str(w.bbox().to_dtype(dbu))
        p_old, p_new = w.perimeter(), sum(p.perimeter() for p in neww.each())
        rec.update(well_bbox_um=str(w.bbox().to_dtype(dbu)), lvtn_bbox_um=str(b.to_dtype(dbu)), sides_grown=grow,
                   well_area_um2=round(w.area() * dbu * dbu, 3), added_area_um2=round(add.area() * dbu * dbu, 4),
                   area_growth_pct=round(100 * add.area() / w.area(), 2), perimeter_growth_pct=round(100 * (p_new - p_old) / p_old, 2))
        wells.append(rec)
        patch += add
    patch = patch.merged()
    boxes = [[round(v * dbu, 3) for v in (q.left, q.bottom, q.right, q.top)]
             for q in (r.bbox() for r in patch.decompose_trapezoids_to_region().each())]
    for bx in boxes:
        assert all(round(v * 1000) % GRID == 0 for v in bx), bx
    out = dict(layer='nwell 64/20', source_gds_sha256=hashlib.sha256(Path(src).read_bytes()).hexdigest(),
               rule='lvtn.10: nwell encloses lvtn by 0.38 um (0.39/0.40 per side where free); drawn HVI '
                    f'{hvi_rule / 1000:.2f} um ({(hvi_rule + HVI_SPARE) / 1000:.3f} where free)',
               boxes_um=boxes, n_boxes=len(boxes), added_area_um2=round(patch.area() * dbu * dbu, 4), wells=wells)
    Path(dst).write_text(json.dumps(out, indent=1) + '\n')
    print(len(wells), 'wells,', len(boxes), 'rectangles,', out['added_area_um2'], 'um2 ->', dst)


def apply(src, patch, dst):
    from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer
    ly = db.Layout(); ly.read(str(src)); top = ly.top_cell()
    p = json.loads(Path(patch).read_text())
    for b in p['boxes_um']:
        top.shapes(ly.layer(64, 20)).insert(db.DBox(*b))
    save(ly, top, dst)
    print(len(p['boxes_um']), 'n-well rectangles added ->', dst)


if __name__ == '__main__':
    if sys.argv[1] == 'design':
        design(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1] == 'design2':
        design2(Path(sys.argv[2]), Path(sys.argv[3]), *(int(a) for a in sys.argv[4:5]))
    else:
        apply(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
