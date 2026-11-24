"""Stage 3: the layout stream's local supply patch, added to the top cell exactly as takeover/layout/scripts/apply_patch.py
adds it (one DBox per entry on the named layer), but saved with the base flow's deterministic writer (no GDS timestamps), so that
the rebuild gives the same bytes. Input: inputs/local_patch.json (copy of takeover/layout/runs/patch/local_patch.json).
  KPY supply_patch.py IN.gds PATCH.json OUT.gds
"""
import hashlib, json, sys
from pathlib import Path
import klayout.db as db
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / 'layout'))
from prepare_split import save  # noqa: E402  the base flow's timestamp-free GDS writer
PATCH_SHA = 'a3dcd720686479fd6650c6057055bb30e070df78cbd4603e5368ed488da910d0'
LD = {"met1": (68, 20), "via": (68, 44), "met2": (69, 20), "via2": (69, 44), "met3": (70, 20), "via3": (70, 44), "met4": (71, 20)}
src, patch, dst = sys.argv[1:4]
raw = Path(patch).read_bytes()
assert hashlib.sha256(raw).hexdigest() == PATCH_SHA, 'patch file differs from the one checked'
ly = db.Layout(); ly.read(src); top = ly.top_cell()
n = 0
for group, shapes in json.loads(raw).items():
    for lay, x0, y0, x1, y1, note in shapes:
        top.shapes(ly.layer(*LD[lay])).insert(db.DBox(x0, y0, x1, y1))
        n += 1
assert n == 11
save(ly, top, dst)
print(f"{n} rectangles added -> {dst}")
