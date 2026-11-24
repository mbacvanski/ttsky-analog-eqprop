"""Placement and routing primitives that emit Magic Tcl.

Coordinates are micrometres in the parent cell. Device cells come from the
PDK generators (pass 1) and are centred on their own origin; `Dev` maps their
port labels into parent coordinates for orientation 0, 90 (clockwise) or 270.
"""
from __future__ import annotations

import json

from magic_util import BUILD, UNIT

PORTS = None


def ports():
    global PORTS
    if PORTS is None:
        PORTS = json.loads((BUILD / "device_ports.json").read_text())
    return PORTS


def snap(v: float) -> float:
    return round(v / UNIT) * UNIT


def f(v: float) -> str:
    return f"{snap(v):.3f}um"


class Tcl:
    def __init__(self):
        self.lines: list[str] = []

    def add(self, s: str):
        self.lines.append(s)

    def box(self, x1, y1, x2, y2):
        xa, xb = sorted((x1, x2))
        ya, yb = sorted((y1, y2))
        self.add(f"box {f(xa)} {f(ya)} {f(xb)} {f(yb)}")

    def paint(self, layer, x1, y1, x2, y2):
        self.box(x1, y1, x2, y2)
        self.add(f"paint {layer}")

    # Wires: horizontal (h) or vertical (v) with a given width, centred on the line.
    def hwire(self, layer, x1, x2, y, w):
        self.paint(layer, x1, y - w / 2, x2, y + w / 2)

    def vwire(self, layer, x, y1, y2, w):
        self.paint(layer, x - w / 2, y1, x + w / 2, y2)

    def via(self, kind, x, y, nx=1, ny=1):
        """PDK via helper centred at (x, y); kind in mcon/via1/via2/via3.

        The centre is snapped first: an off-grid centre could round the box one grid step below the
        via size, and the PDK helper then silently draws nothing."""
        x, y = snap(x), snap(y)
        size = dict(mcon=0.17, via1=0.26, via2=0.28, via3=0.32)[kind]
        pitch = dict(mcon=0.34, via1=0.43, via2=0.48, via3=0.6)[kind]
        wx = size + (nx - 1) * pitch
        wy = size + (ny - 1) * pitch
        self.box(x - wx / 2, y - wy / 2, x + wx / 2, y + wy / 2)
        self.add(f"sky130::{kind}_draw")

    def label(self, text, layer, x, y, port_index=None, use="signal"):
        """Label a net on `layer` at (x, y); optionally make it a cell port."""
        self.box(x - 0.05, y - 0.05, x + 0.05, y + 0.05)
        self.add(f"label {text} c {layer}")
        if port_index is not None:
            self.add(f"port make {port_index}")
            self.add(f"port use {use}")
            self.add("port class inout")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class Dev:
    """A placed generator cell: centre (x, y) in the parent, orientation 0/90/270."""

    def __init__(self, tcl: Tcl, cell: str, inst: str, x: float, y: float, orient: int = 0):
        self.cell, self.inst = cell, inst
        self.x, self.y, self.orient = snap(x), snap(y), orient
        self.p = ports()[cell]
        self.labels = {l["text"]: l for l in self.p["labels"]}
        tcl.box(self.x, self.y, self.x, self.y)
        o = "" if orient == 0 else f" {orient}"
        tcl.add(f"getcell {cell}{o} child 0 0")
        tcl.add(f"identify {inst}")

    def tr(self, lx: float, ly: float):
        """Local (cell) coordinates in um -> parent coordinates."""
        if self.orient == 0:
            gx, gy = lx, ly
        elif self.orient == 90:     # clockwise: (x, y) -> (y, -x)
            gx, gy = ly, -lx
        elif self.orient == 270:    # counter-clockwise: (x, y) -> (-y, x)
            gx, gy = -ly, lx
        else:
            raise ValueError(self.orient)
        return self.x + gx, self.y + gy

    def local(self, name: str):
        r = self.labels[name]["rect"]
        return (r[0] + r[2]) / 2 * UNIT, (r[1] + r[3]) / 2 * UNIT

    def port(self, name: str):
        return self.tr(*self.local(name))

    def bbox(self):
        xs, ys = [], []
        for rs in self.p["rects"].values():
            for r in rs:
                for lx in (r[0] * UNIT, r[2] * UNIT):
                    for ly in (r[1] * UNIT, r[3] * UNIT):
                        gx, gy = self.tr(lx, ly)
                        xs.append(gx)
                        ys.append(gy)
        return min(xs), min(ys), max(xs), max(ys)


class Mos(Dev):
    """Multi-finger MOS from the generator: stripes s0..s_nf, gates g0..g_{nf-1}."""

    def __init__(self, tcl, cell, inst, x, y, w, l, nf):
        super().__init__(tcl, cell, inst, x, y, 0)
        self.w, self.l, self.nf = w, l, nf
        self.pitch = l + 0.29
        # Stripe and gate x positions from the generator's labels.
        self.sx = {}
        for name, lab in self.labels.items():
            if name[0] in "DS" and name[1:].isdigit():
                self.sx[int(name[1:])] = self.port(name)[0]
        # Fix the generator's naming quirk (last stripe may be labelled with a
        # repeated index): rebuild the stripe list from geometry.
        n0 = min(self.sx.values())
        self.sx = {i: n0 + i * self.pitch for i in range(nf + 1)}
        self.gx = {k: self.sx[k] + self.pitch / 2 for k in range(nf)}
        g0 = self.port("G0")
        self.gy_top = g0[1]                       # centre of top gate contact
        self.gy_bot = self.y - (g0[1] - self.y)  # mirrored bottom contact
        self.stripe_top = self.y + w / 2
        self.stripe_bot = self.y - w / 2
        self.pad_hw = l / 2 - 0.02 if l < 1.5 else l / 2 - 0.02
        self.ring_y_bot = self.port("B")[1]

    def stripe_via(self, tcl, i, y):
        tcl.via("via1", self.sx[i], y)

    def gate_pad_top(self, k):
        return (self.gx[k] - self.pad_hw, self.gy_top - 0.115, self.gx[k] + self.pad_hw, self.gy_top + 0.115)

    def gate_pad_bot(self, k):
        return (self.gx[k] - self.pad_hw, self.gy_bot - 0.115, self.gx[k] + self.pad_hw, self.gy_bot + 0.115)
