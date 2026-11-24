"""Geometry helpers for the AH core auto-zero amplifier cell (az_core).

All coordinates are micrometres in the parent cell, snapped to the 5 nm grid.
Device cells come from the PDK generators (gen_devices.py) and are centred on
their own origin. The helper classes below reproduce the generator geometry
(verified against the generated .mag files) so that routing can refer to
source/drain stripes, gate bars and guard rings by name.
"""
from __future__ import annotations

from geom import Tcl, snap, ports


class Mos:
    """A generator MOSFET placed at (x, y), orientation 0.

    Stripes s0..s_nf are vertical metal1 (0.23 wide) spanning y +/- w/2.
    Gate pads sit at y +/- (w/2 + 0.16 .. w/2 + 0.39); with conn_gates the pads
    of each row form one continuous metal1 bar from stripe 0 to stripe nf.
    The guard ring is a 0.17 um local-interconnect ring on the cell bbox.
    """

    def __init__(self, t: Tcl, cell: str, inst: str, x: float, y: float, w: float, l: float, nf: int,
                 pmos: bool = False, conn: bool = False):
        self.cell, self.inst = cell, inst
        self.x, self.y = snap(x), snap(y)
        self.w, self.l, self.nf, self.pmos, self.conn = w, l, nf, pmos, conn
        geo = ports()[cell]
        U = 0.005
        dc = geo["rects"]["pdiffc" if pmos else "ndiffc"]
        cx = sorted({(r[0] + r[2]) / 2 * U for r in dc})
        assert len(cx) == nf + 1, (cell, cx)
        self.sx = [snap(self.x + c) for c in cx]
        self.p = round(cx[1] - cx[0], 3)
        self.gx = [snap((a + b) / 2) for a, b in zip(self.sx[:-1], self.sx[1:])]
        bb = geo["fixed_bbox"]
        self.hx, self.hy = round(bb[2] * U, 3), round(bb[3] * U, 3)
        self.top, self.bot = self.y + w / 2, self.y - w / 2          # stripe extent
        self.pad_top = (self.y + w / 2 + 0.16, self.y + w / 2 + 0.39)
        self.pad_bot = (self.y - w / 2 - 0.39, self.y - w / 2 - 0.16)
        self.ring = (self.x - self.hx, self.y - self.hy, self.x + self.hx, self.y + self.hy)
        # gate contacts actually drawn: (x centre, side) for every polycont
        self.gc = sorted(((r[0] + r[2]) / 2 * U + self.x, "top" if r[1] > 0 else "bot") for r in geo["rects"]["polycont"])
        t.box(self.x, self.y, self.x, self.y)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {inst}")

    def pad(self, k: int, side: str):
        """Metal1 gate pad of finger k (x1, y1, x2, y2)."""
        y1, y2 = self.pad_top if side == "top" else self.pad_bot
        if self.l < 0.5:
            hw = 0.145
        else:
            hw = self.l / 2 - 0.02
        return (self.gx[k] - hw, y1, self.gx[k] + hw, y2)

    def pad_y(self, side: str):
        y1, y2 = self.pad_top if side == "top" else self.pad_bot
        return (y1 + y2) / 2


class Res:
    """A generator xhigh_po resistor placed at (x, y); orient 0 (vertical) or 90 (horizontal).

    Terminal metal1 pads: half-width hw, inner/outer distance (a, b) from the centre along
    the body axis. R1 is at +axis for orient 0 (top); for orient 90 (clockwise) R1 is at +x.
    """

    def __init__(self, t: Tcl, cell: str, inst: str, x: float, y: float, orient: int, hw: float, a: float, b: float,
                 hx: float, hy: float):
        self.x, self.y, self.orient = snap(x), snap(y), orient
        self.hw, self.a, self.b = hw, a, b
        if orient == 0:
            self.ring = (self.x - hx, self.y - hy, self.x + hx, self.y + hy)
        else:
            self.ring = (self.x - hy, self.y - hx, self.x + hy, self.y + hx)
        t.box(self.x, self.y, self.x, self.y)
        o = "" if orient == 0 else f" {orient}"
        t.add(f"getcell {cell}{o} child 0 0")
        t.add(f"identify {inst}")

    def term(self, name: str, strip_dx: float = 0.0):
        """(x1, y1, x2, y2) of terminal pad R1 or R2 of the strip at local x offset strip_dx.

        Orient 270 (counter-clockwise, used by the AJ cells): R1 is at -x and local +x maps to +y."""
        s = 1 if name == "R1" else -1
        if self.orient == 0:
            ys = sorted((self.y + s * self.a, self.y + s * self.b))
            return (self.x + strip_dx - self.hw, ys[0], self.x + strip_dx + self.hw, ys[1])
        if self.orient == 270:
            xs = sorted((self.x - s * self.a, self.x - s * self.b))
            return (xs[0], self.y + strip_dx - self.hw, xs[1], self.y + strip_dx + self.hw)
        # 90 clockwise: (x, y) -> (y, -x); R1 (top, +y) maps to +x, local +x maps to -y
        xs = sorted((self.x + s * self.a, self.x + s * self.b))
        return (xs[0], self.y - strip_dx - self.hw, xs[1], self.y - strip_dx + self.hw)

    def term_c(self, name: str, strip_dx: float = 0.0):
        x1, y1, x2, y2 = self.term(name, strip_dx)
        return ((x1 + x2) / 2, (y1 + y2) / 2)


class Cap:
    """One generator MIM unit at (x, y), orient 0. side s, capm offset per generator."""

    def __init__(self, t: Tcl, cell: str, inst: str, x: float, y: float, s: float):
        self.x, self.y, self.s = snap(x), snap(y), s
        # Generator geometry (verified): capm spans x [-hm3+0.2, -hm3+0.2+s], y +/- s/2;
        # metal3 plate x +/- hm3, y +/- (s/2+0.2); C2 strip (via3 + metal4) at the +x edge.
        self.hm3 = round(s / 2 + 1.08, 3)
        self.capm = (self.x - self.hm3 + 0.2, self.y - s / 2, self.x - self.hm3 + 0.2 + s, self.y + s / 2)
        self.m3 = (self.x - self.hm3, self.y - s / 2 - 0.2, self.x + self.hm3, self.y + s / 2 + 0.2)
        self.top_m4 = (self.capm[0] + 0.195, self.capm[1] + 0.195, self.capm[2] - 0.195, self.capm[3] - 0.195)
        self.strip_m4 = (self.x + self.hm3 - 0.5, self.y - s / 2 - 0.14, self.x + self.hm3 - 0.02, self.y + s / 2 + 0.14)
        t.box(self.x, self.y, self.x, self.y)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {inst}")


class MimUnit:
    """A hand-drawn MIM unit (variant AJ): a cell holding one s x s capacitor (mimcap + its contact) on a
    metal3 pad that surrounds it by 0.14 um. With `l` given it is a rectangle, s wide (x) and l tall (y). Unlike the generator's unit it has no bottom-plate contact
    strip of its own, so units on one plate can sit at the 0.84 um minimum spacing; the parent paints the
    shared bottom plate (metal3) and joins the top plates (metal4). Placed with its centre at (x, y)."""

    @staticmethod
    def define(t: Tcl, cell: str, s: float, l: float | None = None):
        h, v = s / 2, (s if l is None else l) / 2
        t.add(f"load {cell} -force")
        t.paint("metal3", -h - 0.14, -v - 0.14, h + 0.14, v + 0.14)
        t.paint("mimcap", -h, -v, h, v)
        t.paint("mimcc", -h + 0.2, -v + 0.2, h - 0.2, v - 0.2)
        t.paint("metal4", -h + 0.195, -v + 0.195, h - 0.195, v - 0.195)
        t.add(f"save {cell}")

    def __init__(self, t: Tcl, cell: str, inst: str, x: float, y: float, s: float, l: float | None = None):
        self.x, self.y, self.s = snap(x), snap(y), s
        h, v = s / 2, (s if l is None else l) / 2
        self.capm = (self.x - h, self.y - v, self.x + h, self.y + v)
        self.top_m4 = (self.x - h + 0.2, self.y - v + 0.2, self.x + h - 0.2, self.y + v - 0.2)
        t.box(self.x, self.y, self.x, self.y)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {inst}")
