"""Drawing helpers for the chip strand's cells: Magic Tcl through the accepted flow's geom.Tcl, the PDK generators'
devices, one shared ground ring per cell.

Coordinates are micrometres in the cell's own frame; the origin is the lower-left corner of the ring's outer edge.
Devices are generated standing (strips and channels along y) and placed lying: rotated 90 degrees clockwise, so that
a generator point (x, y) lands at (cx + y, cy - x).

What the generators draw (read from the generated cells, see gen_devices.py):
  res_xhigh_po_0p35, nx strips at 0.83 um pitch, 0.35 um wide; body l - 0.16 um; an end contact of 2.16 um at each
      end; on each contact a metal1 pad 0.25 um wide from 0.025 to 2.13 um into the contact
  nfet_03v3_nvt w 4, l 0.5: diffusion 1.08 x 4.0, poly 0.5 x 4.88; source/drain metal1 stripes 0.23 wide at +-0.395,
      3.88 long; a gate pad (metal1 0.46 x 0.23) on the poly at each end, centre 2.275 from the middle;
      nf fingers: stripes at 0.79 um pitch
Ring (as the generators' own): contact bars 0.17 um wide that stop 0.31 um before each inner corner, the corners
filled with tap diffusion and local interconnect.
"""
from __future__ import annotations

import json
import re

import magic_util
from magic_util import BUILD, LAYOUT, RESULTS, run_magic
from geom import Tcl, snap
import build as accepted_build

PITCH = 0.83            # strip pitch
ENDC = 2.16             # end contact of a strip
RW = 0.17               # ring bar
GAP_R = 0.48            # strip to ring, strip to diffusion (rule poly.9)
GAP_SW = 0.60           # strip array to a native switch's diffusion (rules rpm.3 + rpm.9 + hvntm.3 ask 0.585)
M1, M2 = 0.23, 0.30     # wire widths used inside the cells


class Cell:
    def __init__(self, name):
        self.name = name
        self.t = Tcl()
        self.t.add("random seed 20261115")
        self.t.add(f"load {name} -force")
        self.t.add("snap internal")
        self.ports = []
        self.info = dict(cell=name, pins={})

    # ---- paint
    def rect(self, layer, x1, y1, x2, y2):
        self.t.paint(layer, x1, y1, x2, y2)

    def h(self, layer, x1, x2, y, w=None):
        w = w or (M1 if layer == "metal1" else M2)
        self.t.paint(layer, min(x1, x2), y - w / 2, max(x1, x2), y + w / 2)

    def v(self, layer, x, y1, y2, w=None):
        w = w or (M1 if layer == "metal1" else M2)
        self.t.paint(layer, x - w / 2, min(y1, y2), x + w / 2, max(y1, y2))

    def via(self, kind, x, y, nx=1, ny=1):
        self.t.via(kind, x, y, nx, ny)

    def ring(self, x1, y1, x2, y2, kind="psubdiff"):
        """Ground ring whose inner edge is the box (x1, y1, x2, y2); returns its outer box."""
        c, d, w, k = kind + "cont", kind, RW, 0.31
        t = self.t
        t.paint(c, x1 + k, y1 - w, x2 - k, y1)
        t.paint(c, x1 + k, y2, x2 - k, y2 + w)
        t.paint(c, x1 - w, y1 + k, x1, y2 - k)
        t.paint(c, x2, y1 + k, x2 + w, y2 - k)
        for cx1, cx2 in ((x1 - w, x1 + k), (x2 - k, x2 + w)):
            for cy1, cy2 in ((y1 - w, y1), (y2, y2 + w)):
                for layer in (d, "locali"):
                    t.paint(layer, cx1, cy1, cx2, cy2)
        for cx1, cx2 in ((x1 - w, x1), (x2, x2 + w)):
            for cy1, cy2 in ((y1, y1 + k), (y2 - k, y2)):
                for layer in (d, "locali"):
                    t.paint(layer, cx1, cy1, cx2, cy2)
        return (x1 - w, y1 - w, x2 + w, y2 + w)

    def place(self, cell, inst, x, y, rot=90):
        self.t.box(snap(x), snap(y), snap(x), snap(y))
        self.t.add(f"getcell {cell}{'' if rot == 0 else ' ' + str(rot)} child 0 0")
        self.t.add(f"identify {inst}")

    def port(self, name, layer, x1, y1, x2, y2, use="signal"):
        """A pin: a rectangle of metal on `layer` with the port label in its middle."""
        self.t.paint(layer, x1, y1, x2, y2)
        self.ports.append(name)
        self.t.label(name, layer, (x1 + x2) / 2, (y1 + y2) / 2, len(self.ports), use)
        self.info["pins"][name] = dict(layer=layer, rect=[round(v, 3) for v in (x1, y1, x2, y2)])

    def label(self, name, layer, x, y):
        self.t.label(name, layer, x, y)

    def outline(self, x1, y1, x2, y2):
        self.info["outline"] = [round(v, 3) for v in (x1, y1, x2, y2)]
        self.info["size_um"] = [round(x2 - x1, 3), round(y2 - y1, 3)]
        u = magic_util.UNIT
        self.t.add(f"property FIXED_BBOX \"{round(x1 / u)} {round(y1 / u)} {round(x2 / u)} {round(y2 / u)}\"")


class Strips:
    """An array of n lying strips (legs along x). Strip 0 is the top one. `l` is the drawn length parameter."""

    def __init__(self, c: Cell, cell, inst, cx, cy, n, l):
        self.c, self.cx, self.cy, self.n, self.l = c, snap(cx), snap(cy), n, l
        self.half = (l - 0.16) / 2 + ENDC            # centre to the end of a strip
        c.place(cell, inst, cx, cy, 90)

    @staticmethod
    def height(n):
        return n * PITCH - (PITCH - 0.35)

    def y(self, i):
        return snap(self.cy + ((self.n - 1) / 2 - i) * PITCH)

    def x_end(self, side):
        return self.cx + (self.half if side == "R" else -self.half)

    def pad(self, i, side):
        """Metal1 pad on the end contact of strip i: (x1, y1, x2, y2). side 'L' or 'R'."""
        a, b = (self.l - 0.16) / 2 + 0.025, (self.l - 0.16) / 2 + 2.13
        y = self.y(i)
        xs = (self.cx + a, self.cx + b) if side == "R" else (self.cx - b, self.cx - a)
        return (xs[0], y - 0.125, xs[1], y + 0.125)

    def link(self, i, j, side, dx=0.0):
        """Join the ends of strips i and j on one side with a metal1 bar 0.3 um wide at the outer end of their pads
        (dx moves it inward)."""
        p, q = self.pad(i, side), self.pad(j, side)
        x = (p[2] - 0.3 - dx, p[2] - dx) if side == "R" else (p[0] + dx, p[0] + 0.3 + dx)
        self.c.rect("metal1", x[0], min(p[1], q[1]), x[1], max(p[3], q[3]))

    def to_ring(self, i, side, ring_x):
        """Ground a dummy strip's end: metal1 from its pad to the ring bar whose centre line is at ring_x, and a contact there."""
        p = self.pad(i, side)
        y = self.y(i)
        if side == "L":
            self.c.rect("metal1", ring_x - 0.115, p[1], p[0] + 0.1, p[3])
        else:
            self.c.rect("metal1", p[2] - 0.1, p[1], ring_x + 0.115, p[3])
        self.c.via("mcon", ring_x, y)


class Switch:
    """A lying native switch of nf fingers (w 4, l 0.5): stripes run along x. stripe k = 0 is the top one; with the
    generator's naming the stripes are D, S, D, S from the top. Gate k lies between stripes k and k + 1."""

    def __init__(self, c: Cell, cell, inst, cx, cy, nf=1):
        self.c, self.cx, self.cy, self.nf = c, snap(cx), snap(cy), nf
        c.place(cell, inst, cx, cy, 90)

    def ys(self, k):
        return snap(self.cy + (self.nf / 2 - k) * 0.79)

    def yg(self, k):
        return snap(self.cy + ((self.nf - 1) / 2 - k) * 0.79)

    def stripe(self, k):
        y = self.ys(k)
        return (self.cx - 1.94, y - 0.115, self.cx + 1.94, y + 0.115)

    def gate_pad(self, k, side):
        y = self.yg(k)
        xs = (self.cx + 2.16, self.cx + 2.39) if side == "R" else (self.cx - 2.39, self.cx - 2.16)
        return (xs[0], y - 0.23, xs[1], y + 0.23)

    @property
    def half_len(self):
        return 2.44                                  # centre to the end of the poly

    @property
    def half_h(self):
        return (self.nf * 0.79 + 0.29) / 2           # centre to the edge of the diffusion


# ---------------------------------------------------------------- build, checks
def build(cell: Cell, extract=True):
    name = cell.name
    (LAYOUT / f"{name}.mag").unlink(missing_ok=True)
    t = cell.t
    t.add(f"save {name}")
    t.add(accepted_build.DRC_TCL)
    t.add(f"cell_drc {name} {BUILD / (name + '_drc.txt')}")
    if extract:
        t.add(f"cell_extract {name} {BUILD / 'ext'}")
    t.add(f"load {name}")
    t.add(f"gds write {LAYOUT / (name + '.gds')}")
    t.add("quit -noprompt")
    out = run_magic(t.text(), f"build_{name}")
    m = re.search(rf"DRCTOTAL {name} (\d+)", out)
    total = int(m.group(1)) if m else -1
    rules = [dict(rule=why, count=int(n)) for _, n, why in
             (line.split("\t", 2) for line in (BUILD / f"{name}_drc.txt").read_text().splitlines() if line.startswith("RULE"))]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}_drc.json").write_text(json.dumps(dict(cell=name, tool="magic 8.3.685, drc(full), euclidean", total=total, rules=rules), indent=1) + "\n")
    (RESULTS / f"{name}_cell.json").write_text(json.dumps(cell.info, indent=1) + "\n")
    print(f"{name}: size {cell.info.get('size_um')}  Magic DRC errors {total}")
    for r in rules:
        print(f"   {r['count']:4d}  {r['rule']}")
    errs = [l for l in out.splitlines() if re.search(r"(?i)error|unknown|can't|cannot", l) and "DRC" not in l]
    if errs:
        print("magic messages:", *errs[:12], sep="\n  ")
    return total
