"""Paths and batch Magic for the 2x2 chip (variant AJ). Same interface as ../../chip/scripts/magic_util.py.

The 2x2 chip lives in floorplan/chip2x2 (scripts, layout, ref, results, build). It reuses, unchanged:
  - the generic helpers of the 3x2 chip (lib.py, geom.py, cell.py ...), found through sys.path;
  - the 3x2 chip's verified block cells (bias_sel, ext_sw, obs_mux, echo, ref_inv, rsense, rw_res, rout,
    ladder, neuron_ctrl, neuron_res, z_passives and their device cells), found through Magic's search path;
  - the amplifier cells of ../../../amp_layout (az_ref1, az_ref4, az_pad, and variant AJ's aj_core, lean_block).
Nothing here writes into those folders: every Magic run only saves its own cell, in chip2x2/layout.
Import this module before any module of ../../chip/scripts, so that they pick up these paths.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent                      # floorplan/chip2x2
FLOORPLAN = PILOT.parent                 # floorplan
FEAS = FLOORPLAN.parent                  # feasibility_20261107
CHIP3X2 = FLOORPLAN / "chip"             # the 3x2 chip (variant AI): cells and helpers reused from here
LAYOUT = PILOT / "layout"
BUILD = PILOT / "build"
RESULTS = PILOT / "results"
REF = PILOT / "ref"
AMP = FEAS / "amp_layout"
# The Tiny Tapeout project folder (info.yaml, src/, docs/, gds/, lef/): beside this chip's folder in the design repository;
# in the Tiny Tapeout repository, where this tree is the source/ snapshot, it is the repository's top folder.
TT_PROJECT = (Path(os.environ["TT_PROJECT"]) if os.environ.get("TT_PROJECT") else
              FLOORPLAN / "tt_project_2x2" if (FLOORPLAN / "tt_project_2x2").is_dir() else FEAS.parent)
EXTRA_PATHS = [CHIP3X2 / "layout", AMP / "layout", FEAS / "physical_state65" / "layout", FEAS / "physical_ladder" / "layout"]
PIN_FOLDERS = [RESULTS, CHIP3X2 / "results", AMP / "results"]     # where <cell>_pins.json is looked up, in this order

if str(CHIP3X2 / "scripts") not in sys.path:
    sys.path.append(str(CHIP3X2 / "scripts"))     # after this folder: our chip.py, router.py ... win

HOME = Path.home()
PDK_ROOT = Path(os.environ.get("PDK_ROOT", HOME / ".ciel"))
MAGIC = os.environ.get("MAGIC", str(HOME / ".local/bin/magic-8.3.685"))
NETGEN = os.environ.get("NETGEN", str(HOME / ".local/bin/netgen-1.5.325"))
MAGICRC = PDK_ROOT / "sky130A/libs.tech/magic/sky130A.magicrc"
NETGEN_SETUP = PDK_ROOT / "sky130A/libs.tech/netgen/sky130A_setup.tcl"
KLAYOUT_PY = Path(os.environ.get("KLAYOUT_PY", HOME / ".local/opt/klayout-py/bin/python"))

UNIT = 0.005  # um per Magic internal unit for sky130A (magscale 1 2)


def addpaths() -> str:
    return "\n".join(f"addpath {p}" for p in EXTRA_PATHS) + "\n"


def run_magic(tcl: str, name: str, cwd: Path = LAYOUT, timeout: int = 3600) -> str:
    """Run a Tcl script in batch Magic with the SKY130 rc file; return stdout+stderr."""
    BUILD.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    script = BUILD / f"{name}.tcl"
    script.write_text(addpaths() + tcl)
    env = dict(os.environ, PDK_ROOT=str(PDK_ROOT))
    proc = subprocess.run(
        [MAGIC, "-dnull", "-noconsole", "-rcfile", str(MAGICRC), str(script)],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
    )
    out = proc.stdout + proc.stderr
    (BUILD / f"{name}.magic.log").write_text(out)
    if proc.returncode != 0:
        raise RuntimeError(f"magic {name} exited {proc.returncode}; see build/{name}.magic.log")
    return out


def parse_mag(path: Path) -> dict:
    """Return rectangles per layer, labels, uses and FIXED_BBOX of one .mag file (internal units)."""
    rects: dict[str, list[tuple[int, int, int, int]]] = {}
    labels = []
    uses = []
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
    """Drop the directory Magic records on `use` lines for cells found through EXTRA_PATHS (it records this
    worktree's absolute path); every build adds those folders to the search path, so the bare name is enough."""
    for mag in folder.glob("*.mag"):
        text = mag.read_text()
        new = re.sub(r"(?m)^(use \S+ +\S+) +\S+/\S*$", r"\1", text)
        if new != text:
            mag.write_text(new)
