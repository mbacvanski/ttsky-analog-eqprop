"""The cells that stand beside a neuron's wires y, p and q (its "west" cell): its switches and the strips next to them.

pw4_nrn_h, in each hidden neuron:
  three lying 4 um switch devices in a row at the bottom, left to right:
      helper beside R4   y - hs4     (then hs4 - three units - p)
      bus and damping    two fingers on ONE diffusion of the wire: from the top the stripes are bus, y, dn. The upper
                         finger is the bus switch (y - bus), the lower one the damping switch (y - dn; its strip and
                         its capacitor are in the neighbour cell). The wire has one diffusion and one via for both.
      helper beside R7   q - qs     (its three units are in the neighbour cell pw4_units3d)
  above them eight lying strips: a dummy, six legs (the three units of the helper beside R4), a dummy.
  One ground ring round all of it.

Wires (nothing over a strip's body):
  the gate line iso   metal1 straight through the three gates, out to the right
  y                   metal2 from the left along the row's lower stripes
  q                   metal1 from the left along the lower ring bar to the right switch
  p                   metal1 from the top leg's left end out to the left
  bus, qs             out to the right: metal2 and metal1 between the switches and the strips
  dn                  metal2 out to the right along the bottom, below the row (as nm leaves the output neuron's cell)

  python cell_nrn.py [pw4_nrn_h]
"""
from __future__ import annotations

import sys

import magic_util
from devices import L_LEG
from lib import GAP_R, GAP_SW, RW, Cell, Strips, Switch, build

SW_PITCH = 5.3            # switch to switch along the row (0.42 um between their polysilicon ends)
DROP = 0.79               # a hidden neuron's damping switch: the bus switch's second finger, one stripe pitch below the row


def tab_via(c, sw, k, x, up):
    """A metal1 tab on stripe k of a switch, towards the strips (up) or towards the ring (down), with a via to metal2
    on it, clear of the gate line; returns the via's centre."""
    x1, y1, x2, y2 = sw.stripe(k)
    if up:
        c.rect("metal1", x - 0.2, y1, x + 0.2, y2 + 0.42)
        yv = y2 + 0.2
    else:
        c.rect("metal1", x - 0.2, y1 - 0.34, x + 0.2, y2)
        yv = y1 - 0.14
    c.via("via1", x, yv)
    return x, yv


def nrn_h(name="pw4_nrn_h"):
    c = Cell(name)
    n = 8
    half = (L_LEG - 0.16) / 2 + 2.16
    xi1, yi1 = RW, RW
    cx = xi1 + GAP_R + half
    y_sw = yi1 + GAP_R + 0.54 + DROP                    # the row's gate line; the lowest diffusion edge is 0.54 + 0.79 below it
    cy = y_sw + 0.54 + GAP_SW + Strips.height(n) / 2
    xi2, yi2 = cx + half + GAP_R, cy + Strips.height(n) / 2 + GAP_R
    ox1, oy1, ox2, oy2 = c.ring(xi1, yi1, xi2, yi2)
    s = Strips(c, "strips8", "XS", cx, cy, n, L_LEG)
    s4 = Switch(c, "sw4", "XSW4", cx - SW_PITCH, y_sw)
    sb = Switch(c, "sw8", "XISO", cx, y_sw - DROP / 2, nf=2)       # stripes from the top: bus, y, dn; gates at y_sw and y_sw - 0.79
    s7 = Switch(c, "sw4", "XSW7", cx + SW_PITCH, y_sw)

    for i, j, side in ((1, 2, "R"), (2, 3, "L"), (3, 4, "R"), (4, 5, "L"), (5, 6, "R")):
        s.link(i, j, side)
    for i in (0, 7):
        s.to_ring(i, "L", xi1 - RW / 2)
        s.to_ring(i, "R", xi2 + RW / 2)

    # gate line: metal1 straight through the three upper gates, out to the right (as in pw4_nrn_h); the second finger's
    # gate is joined to it over the gate pads at both ends of the middle device
    c.port("iso", "metal1", s4.gate_pad(0, "L")[0], y_sw - 0.115, ox2 + 0.06, y_sw + 0.115)
    for side in ("L", "R"):
        a, b = sb.gate_pad(0, side), sb.gate_pad(1, side)
        c.rect("metal1", a[0], b[1], a[2], a[3])

    # y: metal2 from the left edge along the lower stripe of the left switch and the MIDDLE stripe of the middle device
    xa, ya = tab_via(c, s4, 1, s4.cx - 1.4, up=False)
    xb, _ = tab_via(c, sb, 1, sb.cx - 1.4, up=False)
    c.port("y", "metal2", ox1 - 0.06, ya - 0.15, xb + 0.2, ya + 0.15)

    # hs4: left switch's upper stripe -> metal2 -> the bottom leg's left end
    xn, yn = tab_via(c, s4, 0, s4.cx - 1.4, up=True)
    c.via("via1", xn, s.y(6))
    c.v("metal2", xn, yn - 0.15, s.y(6) + 0.15)
    c.label("hs4", "metal2", xn, (yn + s.y(6)) / 2)

    # p: the top leg's left end, out to the left on metal1
    p1 = s.pad(1, "L")
    c.port("p", "metal1", ox1 - 0.06, p1[1], p1[0] + 0.1, p1[3])

    # q: metal1 along the lower ring bar from the left edge to the right switch's lower stripe
    yq = yi1 - RW / 2
    xq = s7.cx - 1.4
    c.rect("metal1", xq - 0.115, yq - 0.115, xq + 0.115, s7.stripe(1)[1] + 0.05)
    c.port("q", "metal1", ox1 - 0.06, yq - 0.115, xq + 0.115, yq + 0.115)

    # bus: the middle device's upper stripe -> metal2 out to the right, between the switches and the strips
    xu, yu = tab_via(c, sb, 0, sb.cx + 1.4, up=True)
    c.port("bus", "metal2", xu - 0.2, yu - 0.15, ox2 + 0.06, yu + 0.15)

    # dn: the middle device's bottom stripe, a via on the stripe, metal2 down and out to the right below the row
    x_dn = sb.cx + 1.1
    ydn = yi1 + 0.11
    yb = sb.ys(2)
    c.via("via1", x_dn, yb)
    c.v("metal2", x_dn, ydn - 0.15, yb + 0.18)
    c.port("dn", "metal2", x_dn - 0.15, ydn - 0.15, ox2 + 0.06, ydn + 0.15)

    # qs: right switch's upper stripe -> metal1 out to the right
    x1, y1, x2, y2 = s7.stripe(0)
    xt = s7.cx + 1.6
    c.rect("metal1", xt - 0.2, y1, xt + 0.2, y2 + 0.4)
    c.port("qs", "metal1", xt - 0.2, y2 + 0.17, ox2 + 0.06, y2 + 0.4)

    # vss: the ring, a metal1 pad on its right bar above the exits
    yv = s.y(3) + 0.415
    c.via("mcon", xi2 + RW / 2, yv, ny=3)
    c.port("vss", "metal1", xi2 - 0.06, yv - 0.5, ox2 + 0.06, yv + 0.5, use="ground")
    c.outline(ox1, oy1, ox2, oy2)
    c.info["gate_line_above_the_lower_edge_um"] = round(y_sw - oy1, 3)
    return c


def nrn_z(name="pw4_nrn_z"):
    """pw4_nrn_z, in the output neuron. Four switches in a row three stripes high, left to right:
        helper beside R4   y - hs4      three 4 um fingers   (then hs4 - one unit - p)
        bus                y - bus     4 um, the upper of two stacked
        DAC edge           y - nm      4 um, the lower
        helper beside R7   q - qs      three 4 um fingers   (then qs - two units - ref here, and two more in pw4_units5)
    Above them eight lying strips, top to bottom: a dummy, four legs (qs - ref), two legs (hs4 - p), a dummy.
    The stripes of all four switches lie on four rows; the three gate rows between them carry the gate line."""
    c = Cell(name)
    n = 8
    half = (L_LEG - 0.16) / 2 + 2.16
    hh = (3 * 0.79 + 0.29) / 2                               # half height of a three-finger switch
    xi1, yi1 = RW, RW
    cx = xi1 + GAP_R + half
    y_sw = yi1 + GAP_R + hh
    cy = y_sw + hh + GAP_SW + Strips.height(n) / 2
    xi2, yi2 = cx + half + GAP_R, cy + Strips.height(n) / 2 + GAP_R
    ox1, oy1, ox2, oy2 = c.ring(xi1, yi1, xi2, yi2)
    s = Strips(c, "strips8", "XS", cx, cy, n, L_LEG)
    s4 = Switch(c, "sw12", "XSW4", cx - SW_PITCH, y_sw, nf=3)
    sb = Switch(c, "sw4", "XISO", cx, y_sw + 0.79)
    sd = Switch(c, "sw4", "XSWD", cx, y_sw - 0.79)
    s7 = Switch(c, "sw12", "XSW7", cx + SW_PITCH, y_sw, nf=3)
    row = [s4.ys(k) for k in range(4)]                       # the four stripe rows, top to bottom
    gate = [s4.yg(k) for k in range(3)]                      # the three gate rows

    # strips: qs - ref on legs 1..4 (both ends at the right), hs4 - p on legs 5, 6 (both ends at the left)
    for i, j, side in ((1, 2, "L"), (2, 3, "R"), (3, 4, "L"), (5, 6, "R")):
        s.link(i, j, side)
    for i in (0, 7):
        s.to_ring(i, "L", xi1 - RW / 2)
        s.to_ring(i, "R", xi2 + RW / 2)

    # gate line: metal1 along the three gate rows, joined over the gate pads at both ends of the row; out on the middle row
    xg1, xg2 = s4.gate_pad(0, "L")[0], s7.gate_pad(0, "R")[2]
    for k in (0, 2):
        c.h("metal1", xg1, xg2, gate[k])
    for xa, xb in ((xg1, xg1 + 0.23), (xg2 - 0.23, xg2)):
        c.rect("metal1", xa, gate[2] - 0.23, xb, gate[0] + 0.23)
    c.port("iso", "metal1", xg1, gate[1] - 0.115, ox2 + 0.06, gate[1] + 0.115)
    # a second way out for the gate line, to the DAC edge's gate above this cell: metal2 from the left end of the row
    # up over the strips' left end contacts (not over a strip's body) to the top edge
    xt = xg1 + 0.115
    c.via("via1", xt, gate[1])
    c.rect("metal2", xt - 0.15, gate[1] - 0.18, xt + 0.15, oy2 + 0.06)
    c.info["pins"]["iso_top"] = dict(layer="metal2", rect=[round(v, 3) for v in (xt - 0.15, gate[1] - 0.18, xt + 0.15, oy2 + 0.06)], note="the same net as iso; no label of its own")

    def bar(x, ka, kb, vias, net):
        """metal2 from stripe row ka down to row kb at x, with a via onto the rows listed."""
        c.v("metal2", x, row[kb] - 0.18, row[ka] + 0.18)
        for k in vias:
            c.via("via1", x, row[k])
        c.label(net, "metal2", x, (row[ka] + row[kb]) / 2)

    # y: metal2 from the left edge along the bottom row; up to the second row in the left and in the middle slot
    x_l, x_m = s4.cx + 1.2, sb.cx - 1.2
    bar(x_l, 1, 3, (1, 3), "y")
    bar(x_m, 1, 3, (1, 2), "y")
    c.port("y", "metal2", ox1 - 0.06, row[3] - 0.15, x_m + 0.15, row[3] + 0.15)

    # hs4: the left switch's first and third stripe, and up to the bottom leg's left end
    x_n = s4.cx - 1.45
    bar(x_n, 0, 2, (0, 2), "hs4")
    c.v("metal2", x_n, row[0], s.y(6) + 0.18)
    c.via("via1", x_n, s.y(6))

    # p: the second leg from the bottom, out to the left on metal1
    p5 = s.pad(5, "L")
    c.port("p", "metal1", ox1 - 0.06, p5[1], p5[0] + 0.1, p5[3])

    # q: metal1 along the lower ring bar to the right switch's bottom stripe; metal2 up to its second stripe
    yq = yi1 - RW / 2
    x_q = s7.cx - 1.4
    c.rect("metal1", x_q - 0.115, yq - 0.115, x_q + 0.115, row[3])
    bar(x_q, 1, 3, (1, 3), "q")
    c.port("q", "metal1", ox1 - 0.06, yq - 0.115, x_q + 0.115, yq + 0.115)

    # qs: the right switch's first and third stripe, up to leg 4's right end; out to the right from that end
    x_r = s7.cx + 1.2
    bar(x_r, 0, 2, (0, 2), "qs")
    c.v("metal2", x_r, row[0], s.y(4) + 0.18)
    c.via("via1", x_r, s.y(4))
    p4 = s.pad(4, "R")
    c.port("qs", "metal1", p4[2] - 0.1, p4[1], ox2 + 0.06, p4[3])

    # ref: the top leg's right end, out to the right
    p1 = s.pad(1, "R")
    c.port("ref", "metal1", p1[2] - 0.1, p1[1], ox2 + 0.06, p1[3])

    # bus: the upper middle switch's top stripe, metal1 out to the right between the switches and the strips
    x_b = sb.cx + 1.4
    yb = row[0] + 0.115 + 0.17 + 0.115
    c.rect("metal1", x_b - 0.2, row[0], x_b + 0.2, yb + 0.115)
    c.port("bus", "metal1", x_b - 0.2, yb - 0.115, ox2 + 0.06, yb + 0.115)

    # nm: the lower middle switch's bottom stripe, metal2 out to the right below the row
    x_nm = sd.cx + 1.1
    ynm = yi1 + 0.11
    c.via("via1", x_nm, row[3])
    c.v("metal2", x_nm, ynm - 0.15, row[3] + 0.18)
    c.port("nm", "metal2", x_nm - 0.15, ynm - 0.15, ox2 + 0.06, ynm + 0.15)

    # vss: the ring
    yv = s.y(2) - 0.415
    c.via("mcon", xi2 + RW / 2, yv, ny=2)
    c.port("vss", "metal1", xi2 - 0.06, yv - 0.3, ox2 + 0.06, yv + 0.3, use="ground")
    c.outline(ox1, oy1, ox2, oy2)
    return c


def mid(name="pw4_mid"):
    """pw4_mid, beside the output neuron's input resistors: the two midpoints' isolation switches, 4 um each, lying one
    above the other in one ground ring: m1 - b1 (upper), m2 - b2 (lower). The midpoints come in from the left on the
    two inner stripes, the buses leave upwards from the two outer ones, the gate line leaves to the right."""
    c = Cell(name)
    hh = (3 * 0.79 + 0.29) / 2
    xi1, yi1 = RW, RW
    cx, y_sw = xi1 + 0.6 + 2.44, yi1 + GAP_R + hh
    xi2, yi2 = cx + 2.44 + 0.6, y_sw + hh + GAP_R
    ox1, oy1, ox2, oy2 = c.ring(xi1, yi1, xi2, yi2)
    su = Switch(c, "sw4", "XISO1", cx, y_sw + 0.79)
    sl = Switch(c, "sw4", "XISO2", cx, y_sw - 0.79)
    row = [su.ys(0), su.ys(1), sl.ys(0), sl.ys(1)]
    # gate line: the two gates joined over their pads at both ends; out to the right between them
    for side in ("L", "R"):
        a, b = su.gate_pad(0, side), sl.gate_pad(0, side)
        c.rect("metal1", a[0], b[1], a[2], a[3])
    xr = su.gate_pad(0, "R")[0]
    c.port("iso", "metal1", xr, y_sw - 0.115, ox2 + 0.06, y_sw + 0.115)
    # the midpoints: metal2 from the left edge onto the two inner stripes
    xv = cx - 1.2
    for nm, k in (("m1", 1), ("m2", 2)):
        c.via("via1", xv, row[k])
        c.port(nm, "metal2", ox1 - 0.06, row[k] - 0.15, xv + 0.18, row[k] + 0.15)
    # the buses: metal2 from the two outer stripes up to the top edge
    for nm, k, x in (("b1", 0, cx + 0.2), ("b2", 3, cx + 1.3)):
        c.via("via1", x, row[k])
        c.port(nm, "metal2", x - 0.15, row[k] - 0.18, x + 0.15, oy2 + 0.06)
    # vss: the ring, a metal1 pad on its lower bar
    c.via("mcon", cx, yi1 - RW / 2, nx=3)
    c.port("vss", "metal1", cx - 0.6, oy1 - 0.06, cx + 0.6, yi1 + 0.06, use="ground")
    c.outline(ox1, oy1, ox2, oy2)
    return c


CELLS = {"pw4_nrn_h": nrn_h, "pw4_nrn_z": nrn_z, "pw4_mid": mid}

if __name__ == "__main__":
    for name in sys.argv[1:] or ["pw4_nrn_h"]:
        build(CELLS[name]())
