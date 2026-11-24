"""Paths and batch Magic for the floorplan strand of v4. Same interface as the accepted chip's
feasibility_20261107/floorplan/chip2x2/scripts/magic_util.py, so that the accepted scripts (chip.py, router.py,
build_chip.py and the 3x2 chip's lib.py, geom.py) run UNCHANGED when imported after this module, but write only
inside this strand's folder. Nothing here edits or patches an accepted script.

Two build areas, chosen by the environment variable V4_AREA:
  acc    (default) the accepted chip rebuilt as it is, as the control and as the frozen base:  build/acc/...
  v4     the draft with the additions:                                                          build/v4/...
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent                                        # .../programmable_weights_v4_20261114/floorplan
X = OUT.parents[1]                                       # hardware/mesa/xor_sky130
FEAS = X / "feasibility_20261107"
FLOORPLAN = FEAS / "floorplan"
ACCEPTED = FLOORPLAN / "chip2x2"                         # the accepted chip's folder (read only)
PILOT = ACCEPTED                                         # chip.py reads PILOT/ref/aj_native_chip.spice
CHIP3X2 = FLOORPLAN / "chip"
AMP = FEAS / "amp_layout"
V3 = X / "programmable_weights_v3_20261114"
V2 = X / "programmable_weights_v2_20261113"
TOP = "tt_um_mbacvanski_denseam_xor"
PREFIX = TOP + "__"
GDS_ACC = FLOORPLAN / "tt_project_2x2" / "gds" / f"{TOP}.gds"
GDS_ACC_SHA256 = "0d3d3976e17e56a9572f7e5d5bba660ff3ddf16b3d5c85103e07e858cca783cd"
GDS_V3 = V3 / "submission_review" / "gds" / f"{TOP}.gds"

AREA = os.environ.get("V4_AREA", "acc")
BUILD = OUT / "build" / AREA / "build"
LAYOUT = OUT / "build" / AREA / "layout"
RESULTS = OUT / "build" / AREA / "results"               # what the accepted scripts write as "results"
REF = ACCEPTED / "ref"
OUT_RESULTS = OUT / "results"                            # this strand's own small result files (committed)
FIGURES = OUT / "figures"
TT_PROJECT = FLOORPLAN / "tt_project_2x2"
EXTRA_PATHS = [CHIP3X2 / "layout", AMP / "layout", FEAS / "physical_state65" / "layout", FEAS / "physical_ladder" / "layout"]
PIN_FOLDERS = [ACCEPTED / "results", CHIP3X2 / "results", AMP / "results"]

for p in (str(ACCEPTED / "scripts"), str(CHIP3X2 / "scripts")):   # after this folder: this strand's modules win
    if p not in sys.path:
        sys.path.append(p)

HOME = Path.home()
PDK_ROOT = Path(os.environ.get("PDK_ROOT", HOME / ".ciel"))
MAGIC = os.environ.get("MAGIC", str(HOME / ".local/bin/magic-8.3.685"))
NETGEN = os.environ.get("NETGEN", str(HOME / ".local/bin/netgen-1.5.325"))
MAGICRC = PDK_ROOT / "sky130A/libs.tech/magic/sky130A.magicrc"
NETGEN_SETUP = PDK_ROOT / "sky130A/libs.tech/netgen/sky130A_setup.tcl"
KLAYOUT_PY = Path(os.environ.get("KLAYOUT_PY", HOME / ".local/opt/klayout-py/bin/python"))
UNIT = 0.005  # um per Magic internal unit for sky130A (magscale 1 2)


def prepare():
    """Folders; the one result file of the accepted chip that chip.py reads through RESULTS; and copies of the accepted
    chip's own cell layouts in Magic's working folder. The accepted flow runs Magic inside chip2x2/layout, where those
    cells are; Magic looks for a cell's children beside the cell first, so the same run from another folder needs the
    cells beside it (found through the search path instead, one child cell is not read). The top cell is not copied."""
    for d in (BUILD, LAYOUT, RESULTS, OUT_RESULTS, FIGURES):
        d.mkdir(parents=True, exist_ok=True)
    for src in sorted((ACCEPTED / "layout").glob("*.mag")):
        dst = LAYOUT / src.name
        if src.stem != TOP and (not dst.exists() or dst.read_bytes() != src.read_bytes()):
            dst.write_bytes(src.read_bytes())
    src = ACCEPTED / "results" / "aj_neuron_edge.json"
    dst = RESULTS / "aj_neuron_edge.json"
    if not dst.exists() or dst.read_bytes() != src.read_bytes():
        dst.write_bytes(src.read_bytes())


prepare()


def addpaths() -> str:
    return "\n".join(f"addpath {p}" for p in EXTRA_PATHS) + "\n"


def run_magic(tcl: str, name: str, cwd: Path = LAYOUT, timeout: int = 3600) -> str:
    """Run a Tcl script in batch Magic with the SKY130 rc file; return stdout+stderr (as the accepted run_magic)."""
    BUILD.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    script = BUILD / f"{name}.tcl"
    script.write_text(addpaths() + tcl)
    tmp = BUILD / "tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, PDK_ROOT=str(PDK_ROOT), TMPDIR=str(tmp))
    proc = subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile", str(MAGICRC), str(script)],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout + proc.stderr
    (BUILD / f"{name}.magic.log").write_text(out)
    if proc.returncode != 0:
        raise RuntimeError(f"magic {name} exited {proc.returncode}; see {BUILD / (name + '.magic.log')}")
    return out


def parse_mag(path: Path) -> dict:
    """Rectangles per layer, labels, uses and FIXED_BBOX of one .mag file (internal units); as the accepted parse_mag."""
    rects: dict[str, list[tuple[int, int, int, int]]] = {}
    labels, uses = [], []
    layer = None
    fixed_bbox = None
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"<< (\S+) >>", line)
        if m:
            layer = m.group(1)
        elif line.startswith("rect ") and layer not in (None, "labels", "properties", "checkpaint"):
            x1, y1, x2, y2 = map(int, line.split()[1:5])
            rects.setdefault(layer, []).append((x1, y1, x2, y2))
        elif line.startswith("rlabel ") or line.startswith("flabel "):
            parts = line.split()
            if parts[0] == "rlabel":
                lay = parts[1]
                x1, y1, x2, y2 = map(int, parts[2:6])
                text = parts[7] if len(parts) > 7 else ""
            else:
                lay = parts[1]
                nums = [p for p in parts[2:] if re.fullmatch(r"-?\d+", p)]
                x1, y1, x2, y2 = map(int, nums[:4])
                text = parts[-1]
            labels.append(dict(text=text, layer=lay, rect=(x1, y1, x2, y2)))
        elif line.startswith("use "):
            parts = line.split()
            cell, inst = parts[1], (parts[2] if len(parts) > 2 else "")
            transform = list(map(int, lines[i + 2].split()[1:7])) if lines[i + 2].startswith("transform") else None
            uses.append(dict(cell=cell, inst=inst, transform=transform))
        elif line.startswith("string FIXED_BBOX"):
            fixed_bbox = tuple(map(int, line.split()[2:6]))
        i += 1
    return dict(rects=rects, labels=labels, uses=uses, fixed_bbox=fixed_bbox)


def um(v: float) -> str:
    return f"{round(v / UNIT) * UNIT:.3f}um"


def strip_use_paths(folder: Path = LAYOUT):
    """Drop the directory Magic records on `use` lines (as the accepted strip_use_paths; only this strand's folder)."""
    assert OUT in Path(folder).resolve().parents, folder
    for mag in Path(folder).glob("*.mag"):
        text = mag.read_text()
        new = re.sub(r"(?m)^(use \S+ +\S+) +\S+/\S*$", r"\1", text)
        if new != text:
            mag.write_text(new)
