"""Paths and Magic helpers for the cells strand (cells/). Stands in for the accepted flow's magic_util.py, with the
same names, so that the accepted scripts imported from feasibility_20261107/amp_layout/scripts (geom.py, build.py,
run_lvs.py, run_klayout_drc.py, metal_islands.py) read and write only in this folder.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent                                  # cells/
LAYOUT = PILOT / "layout"
BUILD = PILOT / "build"
RESULTS = PILOT / "results"
REF = PILOT / "ref"
EXTRACTED = PILOT / "extracted"
V4 = PILOT.parent                                    # programmable_weights_v4_20261114
X = V4.parent                                        # hardware/mesa/xor_sky130
ACCEPTED_CELLS = X / "feasibility_20261107" / "amp_layout" / "scripts"
ACCEPTED_CHIP = X / "feasibility_20261107" / "floorplan" / "chip2x2" / "scripts"
CIRCUIT = V4 / "circuit"
if str(ACCEPTED_CELLS) not in sys.path:
    sys.path.append(str(ACCEPTED_CELLS))             # after this folder: this magic_util wins

HOME = Path.home()
PDK_ROOT = Path(os.environ.get("PDK_ROOT", HOME / ".ciel"))
MAGIC = os.environ.get("MAGIC", str(HOME / ".local/bin/magic-8.3.685"))
NETGEN = os.environ.get("NETGEN", str(HOME / ".local/bin/netgen-1.5.325"))
NGSPICE = os.environ.get("NGSPICE", str(HOME / ".local/opt/denseam-eda/20261105/root/usr/bin/ngspice"))
KPY = os.environ.get("KPY", str(HOME / ".local/opt/klayout-py/bin/python"))
MAGICRC = PDK_ROOT / "sky130A/libs.tech/magic/sky130A.magicrc"
NETGEN_SETUP = PDK_ROOT / "sky130A/libs.tech/netgen/sky130A_setup.tcl"
UNIT = 0.005                                         # um per Magic internal unit


def run_magic(tcl: str, name: str, cwd: Path = LAYOUT, timeout: int = 1800) -> str:
    BUILD.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    script = BUILD / f"{name}.tcl"
    script.write_text(tcl)
    env = dict(os.environ, PDK_ROOT=str(PDK_ROOT))
    proc = subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile", str(MAGICRC), str(script)],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout + proc.stderr
    (BUILD / f"{name}.magic.log").write_text(out)
    if proc.returncode != 0:
        raise RuntimeError(f"magic {name} exited {proc.returncode}; see build/{name}.magic.log")
    return out


def parse_mag(path: Path) -> dict:
    """Rectangles per layer, labels, uses and FIXED_BBOX of one .mag file (internal units)."""
    rects, labels, uses = {}, [], []
    layer, fixed_bbox = None, None
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"<< (\S+) >>", line)
        if m:
            layer = m.group(1)
        elif line.startswith("rect ") and layer not in (None, "labels", "properties", "checkpaint"):
            rects.setdefault(layer, []).append(tuple(map(int, line.split()[1:5])))
        elif line.startswith(("rlabel ", "flabel ")):
            parts = line.split()
            if parts[0] == "rlabel":
                k = 3 if parts[2] == "s" else 2
                lay, (x1, y1, x2, y2), text = parts[1], map(int, parts[k:k + 4]), parts[k + 5] if len(parts) > k + 5 else ""
            else:
                lay = parts[1]
                x1, y1, x2, y2 = map(int, [p for p in parts[2:] if re.fullmatch(r"-?\d+", p)][:4])
                text = parts[-1]
            labels.append(dict(text=text, layer=lay, rect=(x1, y1, x2, y2)))
        elif line.startswith("use "):
            parts = line.split()
            tr = list(map(int, lines[i + 2].split()[1:7])) if lines[i + 2].startswith("transform") else None
            uses.append(dict(cell=parts[1], inst=parts[2] if len(parts) > 2 else "", transform=tr))
        elif line.startswith("string FIXED_BBOX"):
            fixed_bbox = tuple(map(int, line.split()[2:6]))
    return dict(rects=rects, labels=labels, uses=uses, fixed_bbox=fixed_bbox)


def extent(mag: dict, layers=None):
    bs = [r for k, rs in mag["rects"].items() if layers is None or k in layers for r in rs]
    return tuple(round(v * UNIT, 3) for v in (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)))
