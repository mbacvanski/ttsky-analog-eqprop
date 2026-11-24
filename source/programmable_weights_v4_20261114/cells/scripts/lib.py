"""Drawing helpers of the cells strand: Magic Tcl through the accepted flow's geom.Tcl, the PDK generators' devices
placed with Magic's own orientation matrices, hand-drawn MIM capacitors, taps and rings, build with Magic's rule check
and extraction (the accepted build.py's procedures). Coordinates are micrometres in the cell's own frame.
"""
from __future__ import annotations

import json
import re

import magic_util
from magic_util import BUILD, LAYOUT, RESULTS, UNIT, run_magic
from geom import Tcl, snap
import build as accepted_build

# Magic's getcell orientations as read back from saved cells: (a, b, d, e) of x' = a x + b y, y' = d x + e y
ORIENT = {"0": (1, 0, 0, 1), "90": (0, 1, -1, 0), "180": (-1, 0, 0, -1), "270": (0, -1, 1, 0),
          "h": (-1, 0, 0, 1), "v": (1, 0, 0, -1), "90h": (0, -1, -1, 0), "90v": (0, 1, 1, 0)}
MIRROR = {"0": "h", "h": "0", "90": "90h", "90h": "90", "180": "v", "v": "180", "270": "90v", "90v": "270"}
VMIRROR = {"0": "v", "v": "0", "90": "90v", "90v": "90", "180": "h", "h": "180", "270": "90h", "90h": "270"}
_PORTS = None


def ports():
    global _PORTS
    if _PORTS is None:
        _PORTS = json.loads((BUILD / "device_ports.json").read_text())
    return _PORTS


class Placed:
    """A generator device placed with its origin at (x, y) in orientation o."""

    def __init__(self, cell, inst, x, y, o):
        self.cell, self.inst, self.x, self.y, self.o = cell, inst, snap(x), snap(y), o
        self.p = ports()[cell]

    def pt(self, lx, ly):
        a, b, d, e = ORIENT[self.o]
        return snap(self.x + a * lx + b * ly), snap(self.y + d * lx + e * ly)

    def box(self, r):
        """A rectangle (x1, y1, x2, y2) in device units -> cell um."""
        p1, p2 = self.pt(r[0] * UNIT, r[1] * UNIT), self.pt(r[2] * UNIT, r[3] * UNIT)
        return min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])

    def rects(self, layer):
        return [self.box(r) for r in self.p["rects"].get(layer, [])]

    def label(self, name):
        l = next(l for l in self.p["labels"] if l["text"] == name)
        r = l["rect"]
        return self.pt((r[0] + r[2]) / 2 * UNIT, (r[1] + r[3]) / 2 * UNIT)

    def bbox(self, layers=None):
        bs = [self.box(r) for k, rs in self.p["rects"].items() if layers is None or k in layers for r in rs]
        return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)

    def stripes(self):
        """Metal1 rectangles over the source/drain contacts (from the device's viali over diffusion), sorted."""
        out = []
        for c in self.rects("pdiffc") + self.rects("ndiffc") + self.rects("mvndiffc") + self.rects("mvpdiffc"):
            out.append(c)
        return sorted(out)

    def gates(self):
        return sorted(self.rects("polycont"))


class Cell:
    def __init__(self, name):
        self.name = name
        self.t = Tcl()
        self.t.add("random seed 20261115")
        self.t.add(f"load {name} -force")
        self.t.add("snap internal")
        self.ports = []
        self.info = dict(cell=name, pins={})
        self.devs = {}
        self.mx = None               # when set to a width W, everything drawn is mirrored: x -> W - x
        self.my = None               # likewise in y: y -> H - y

    def X(self, x):
        return x if self.mx is None else self.mx - x

    def Y(self, y):
        return y if self.my is None else self.my - y

    def XR(self, x1, x2):
        return (x1, x2) if self.mx is None else (self.mx - x2, self.mx - x1)

    def YR(self, y1, y2):
        return (y1, y2) if self.my is None else (self.my - y2, self.my - y1)

    # ---- paint
    def rect(self, layer, x1, y1, x2, y2):
        x1, x2 = self.XR(min(x1, x2), max(x1, x2))
        y1, y2 = self.YR(min(y1, y2), max(y1, y2))
        self.t.paint(layer, x1, y1, x2, y2)

    def erase(self, layer, x1, y1, x2, y2):
        x1, x2 = self.XR(x1, x2)
        y1, y2 = self.YR(y1, y2)
        self.t.box(x1, y1, x2, y2)
        self.t.add(f"erase {layer}")

    def h(self, layer, x1, x2, y, w=0.3):
        self.rect(layer, min(x1, x2), y - w / 2, max(x1, x2), y + w / 2)

    def v(self, layer, x, y1, y2, w=0.3):
        self.rect(layer, x - w / 2, min(y1, y2), x + w / 2, max(y1, y2))

    def via(self, kind, x, y, nx=1, ny=1):
        self.t.via(kind, self.X(x), self.Y(y), nx, ny)

    def stack(self, x, y, top="metal2", bottom="metal1"):
        """Vias from `bottom` up to `top` at one point (li, metal1..metal4)."""
        order = ["locali", "metal1", "metal2", "metal3", "metal4"]
        kinds = {"locali": "mcon", "metal1": "via1", "metal2": "via2", "metal3": "via3"}
        for lay in order[order.index(bottom):order.index(top)]:
            self.via(kinds[lay], x, y)

    def dev(self, cell, inst, x, y, o="0"):
        if self.mx is not None:
            x, o = self.mx - x, MIRROR[o]
        if self.my is not None:
            y, o = self.my - y, VMIRROR[o]
        self.t.box(snap(x), snap(y), snap(x), snap(y))
        self.t.add(f"getcell {cell}{'' if o == '0' else ' ' + o} child 0 0")
        self.t.add(f"identify {inst}")
        d = Placed(cell, inst, x, y, o)
        self.devs[inst] = d
        return d

    def std(self, cell, inst, x, y):
        """A standard cell with its origin (lower-left, on the VGND rail's centre line) at (x, y)."""
        o = {(False, False): "", (True, False): " h", (False, True): " v", (True, True): " 180"}[(self.mx is not None, self.my is not None)]
        x, y = self.X(x), self.Y(y)
        self.t.box(snap(x), snap(y), snap(x), snap(y))
        self.t.add(f"getcell sky130_fd_sc_hd__{cell}{o} child 0 0")
        self.t.add(f"identify {inst}")

    def port(self, name, layer, x1, y1, x2, y2, use="signal"):
        self.rect(layer, x1, y1, x2, y2)
        x1, x2 = self.XR(x1, x2)
        y1, y2 = self.YR(y1, y2)
        self.ports.append(name)
        self.t.label(name, layer, (x1 + x2) / 2, (y1 + y2) / 2, len(self.ports), use)
        self.info["pins"][name] = dict(layer=layer, rect=[round(v, 3) for v in (x1, y1, x2, y2)])

    def label(self, name, layer, x, y):
        self.t.label(name, layer, self.X(x), self.Y(y))

    def outline(self, x1, y1, x2, y2):
        self.info["outline"] = [round(v, 3) for v in (x1, y1, x2, y2)]
        self.info["size_um"] = [round(x2 - x1, 3), round(y2 - y1, 3)]
        self.t.add(f"property FIXED_BBOX \"{round(x1 / UNIT)} {round(y1 / UNIT)} {round(x2 / UNIT)} {round(y2 / UNIT)}\"")

    # ---- composite shapes
    def mim(self, x1, y1, x2, y2, plate_ext=(0.14, 0.14, 0.14, 0.14)):
        """A MIM capacitor whose capacitor layer is (x1, y1, x2, y2): lower plate metal3 around it (extensions
        west, south, east, north), contacts 0.2 inside, metal4 over the contacts. Returns the metal4 rectangle."""
        w, s, e, n = plate_ext
        self.rect("metal3", x1 - w, y1 - s, x2 + e, y2 + n)
        self.rect("mimcap", x1, y1, x2, y2)
        self.rect("mimcapcontact", x1 + 0.2, y1 + 0.2, x2 - 0.2, y2 - 0.2)
        m4 = (x1 + 0.195, y1 + 0.195, x2 - 0.195, y2 - 0.195)
        self.rect("metal4", *m4)
        return m4

    def tap_strip(self, kind, x1, y1, x2, y2, li=True, m1=True):
        """A tap (kind psubdiff or nsubdiff) rectangle with one row of contacts along its long side and li/metal1 over
        them. The contacts stop 0.12 short of each end (licon in tap)."""
        self.rect(kind, x1, y1, x2, y2)
        horiz = (x2 - x1) >= (y2 - y1)
        c = kind + "cont"
        if horiz:
            yc = (y1 + y2) / 2
            self.rect(c, x1 + 0.12, yc - 0.085, x2 - 0.12, yc + 0.085)
            if li:
                self.rect("locali", x1 + 0.04, yc - 0.085, x2 - 0.04, yc + 0.085)
        else:
            xc = (x1 + x2) / 2
            self.rect(c, xc - 0.085, y1 + 0.12, xc + 0.085, y2 - 0.12)
            if li:
                self.rect("locali", xc - 0.085, y1 + 0.04, xc + 0.085, y2 - 0.04)

    def ring(self, x1, y1, x2, y2, kind="psubdiff"):
        """A tap ring whose inner edge is (x1, y1, x2, y2) (the chip strand's Cell.ring: bars 0.17 wide, contacts stop
        0.31 before each inner corner, corners filled with tap and li). Returns the outer box."""
        c, d, w, k = kind + "cont", kind, 0.17, 0.31
        t = self
        t.paint = self.rect
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
    rules = []
    lines = (BUILD / f"{name}_drc.txt").read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("RULE"):
            _, n, why = line.split("\t", 2)
            boxes = [l.split() for l in lines[i + 1:i + 1 + min(int(n), 4)]]
            rules.append(dict(rule=why, count=int(n), first=[[round(float(v), 3) for v in b] for b in boxes]))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}_drc.json").write_text(json.dumps(dict(cell=name, tool="magic 8.3.685, drc(full), euclidean", total=total,
                                                               rules=rules), indent=1) + "\n")
    (RESULTS / f"{name}_cell.json").write_text(json.dumps(cell.info, indent=1) + "\n")
    print(f"{name}: size {cell.info.get('size_um')}  Magic DRC errors {total}")
    for r in rules:
        print(f"   {r['count']:4d}  {r['rule'][:100]}  at {r['first'][:3]}")
    errs = [l for l in out.splitlines() if re.search(r"(?i)error|unknown|can't|cannot", l) and "DRC" not in l]
    if errs:
        print("magic messages:", *errs[:12], sep="\n  ")
    return total
