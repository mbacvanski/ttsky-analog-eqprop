"""The accepted sheet_check.py (feasibility_20261107/floorplan/chip2x2/scripts/sheet_check.py), copied byte for byte into
build/protections_TAG/scripts/ and run there on GDS (it writes its result beside itself); the result is copied to
results/sheet_check_TAG.json with the copy's sha256. Exit status: the check's own (1 = no grounded sheet over rw_res).
  PY -I sheet_run.py GDS TAG"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
SRC = OUT.parents[2] / "feasibility_20261107/floorplan/chip2x2/scripts/sheet_check.py"
gds, tag = Path(sys.argv[1]).resolve(), sys.argv[2]
d = OUT / "build" / f"protections_{tag}"
(d / "scripts").mkdir(parents=True, exist_ok=True)
(d / "results").mkdir(exist_ok=True)
dst = d / "scripts" / "sheet_check.py"
shutil.copyfile(SRC, dst)
sha = hashlib.sha256(dst.read_bytes()).hexdigest()
assert sha == hashlib.sha256(SRC.read_bytes()).hexdigest()
kpy = os.environ.get("KLAYOUT_PY", str(Path.home() / ".local/opt/klayout-py/bin/python"))
p = subprocess.run([kpy, "-B", str(dst), str(gds)], env=dict(os.environ, PYTHONPATH=str(HERE / "stub")), cwd=str(d), capture_output=True, text=True)
(d / "results" / "sheet_check.log").write_text(p.stdout + p.stderr)
r = json.loads((d / "results" / "rw_sheet.json").read_text())
r.pop("drawing", None)
r["script"] = f"feasibility_20261107/floorplan/chip2x2/scripts/sheet_check.py, copied byte for byte (sha256 {sha[:16]}...), run on {gds.name}"
(OUT / "results" / f"sheet_check_{tag}.json").write_text(json.dumps(r, indent=1) + "\n")
print("sheet over rw_res:", "present and grounded" if r.get("ok") else "NOT as on the earlier chip", {k: r.get(k) for k in ("metal3_pieces_over_the_strips", "cover_of_the_bodies", "on_ground_by_metal")})
sys.exit(p.returncode)
