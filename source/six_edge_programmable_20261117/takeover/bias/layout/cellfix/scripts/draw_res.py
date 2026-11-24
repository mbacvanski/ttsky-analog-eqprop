"""pw4_shunt and pw4_bridge: a programmable resistor of v4 (circuit/v4_netlist.py), 28.35 x 14.90 um each.

Drawn with the bus end `a` on the east capacitor and `b` on the west one (cells 0 and 1 of the row; cells 2 and 3 are
these mirrored). From the bottom:
  rails      ground (metal1, y 0.6), the supply (metal2, y 1.1), the DAC line (metal2, y 1.6); the metal4 frame is
             grounded at the bottom centre
  row A      the writer's 1.8 V part: the gate PMOS (LVT 1/1, its drain on the stored gate), the transmission gate to
             the DAC line, the inverter (standard cell) that makes we_b; one n-well on the supply
  row B      the 5 V NMOS at the gate (0.42/4) and the long hold of wm (0.42/8)
  chain      the LVT PMOS chain in its own n-well (the well is `mid`, tapped at both ends)
  top band   REF (metal2, y 12.95) and the clamp line (metal2, y 13.5); the well's clamp (native 1/0.5) and the
             pocket where the row puts a bus clamp, west; the pins on the north edge
The stored gate `gn` is one metal1 column at x = 14.175 between the two capacitors, from the chain's gates down to the
two writer transistors, with one via stack up to the metal4 that joins the two capacitors' upper plates. No other net
crosses it; the DAC line stays below its lower end. The two capacitors are 10.99 um square; the gap between them is
3.2 um so that the column's metal3 is 1.34 um from both (rule capm.11).

Since 2026-11-15, 17:00 (the design lead's go, after item 8 passed with 0.012 mV of room): a metal4 ring round each upper
plate, on that capacitor's own end, takes the plates' edge field, and the bridge's chain well reaches under its gate
bar and past its gate ends. Each stored gate's capacitance to fixed nodes fell from 2.36 / 3.70 fF (shunt / bridge)
to 0.67 / 1.30 fF in place. The row as delivered at 15:20 that day (frame only) stays buildable:

  python draw_res.py [shunt|bridge ...]               the current cells
  python draw_res.py --row1520 [shunt|bridge ...]     the cells of the row delivered at 15:20
  PW4_ROW=1520 bash run_all.sh                        that row with every check, in one command
"""
from __future__ import annotations

import os
import sys

from lib import Cell, build

W, H = 28.35, 14.9
XC = 14.175
CAPW = (1.585, 1.955, 12.575, 12.945)
CAPE = (15.775, 1.955, 26.765, 12.945)
Y_VSS, Y_VDD, Y_DAC = 0.6, 1.1, 1.6           # bottom rails
Y_REF, Y_CLW = 12.65, 13.75                    # top rails (metal2)
X_WE, X_A, X_REF, X_VSSR = 24.8, 27.2, 27.85, 1.0
X_B, X_A2 = 1.25, 26.85                        # the bridge's bus pins (west b, east a), as the plan's cell 1
YA_N, YA_P = 1.465, 3.2                       # row A: NMOS and PMOS origins
YB = 5.26                                     # row B origin (diffusion 4.895 .. 5.315)
# Bias layout work, 2026-11-23, the n-well/lvtn fix (Tiny Tapeout's lvtn.10: n-well encloses lvtn by 0.38 um, with
# Magic's 0.825 um from 5 V diffusion to a low-voltage n-well). PW4_WELLFIX=1: the writer's 5 V NMOS XW1N stands
# 0.03 um higher (its gate bar and via with it), and the bridge's chain well recedes 0.045 um above that NMOS only.
# Unset, every cell is drawn exactly as frozen.
# PW4_WELLFIX=2 (2026-11-24, lock2_h): every drawn HVI at least 0.64 um (0.645 where free) from a low-voltage n-well:
# pw4_shunt's XW1N 0.035 and its chain 0.005 up; pw4_bridge's XW1N 0.05 up, its chain well's recess 0.08 deep out to
# 0.315 um past XW1N's HVI, its well clamp XCLM 0.005 up; PW4_WRITER_SRC=1 draws pw4_shunt's writer as the bridge's
# (XW1N 0.05 up), the source of the bias words' writers.
# PW4_WELLFIX=3 (2026-11-24, lock2_r, the 0.70 backup): every drawn HVI at least 0.70 um (0.705) from a low-voltage
# n-well, lvtn enclosed by 0.385 or more, inside the cells. pw4_shunt's XW1N leaves the stack between the two wells for
# the empty lower left of the cell (under the west capacitor's lower plate), turned over (gate strip below), its drain
# on the gn column by 1.53 um of metal1; we reaches its gate in li from the transmission gate's gate contact, wm its
# source in metal1 under the supply rail (two short crossings of the DAC line); the old gate bar stays as a we stub
# (the top-level we0 landing of rows 1 and 2 sits on it). The shunt's chain 0.03 down from frozen (0.035 from lock2_h),
# its gn via stack where lock2_h has it, the b line 0.30 wide under row 2's res_sel pad; the wells' lvtn enclosure drawn
# in the cell (writer well 0.40, chain well 0.39 below and 0.385 above). The bridge's XW1N 0.12 up, its recess 0.21
# deep to 0.505 past XW1N's HVI, its XCLM 0.07 up; PW4_WRITER_SRC=1 draws pw4_shunt's writer as the bridge's.
WELLFIX = os.environ.get("PW4_WELLFIX", "") if os.environ.get("PW4_WELLFIX") in ("1", "2", "3") else ""
LEVEL = int(WELLFIX or 0)
DY_W1N = {0: 0.0, 1: 0.03, 2: 0.035, 3: 0.0}[LEVEL]
DY_W1N_BRIDGE = {0: 0.0, 1: 0.03, 2: 0.05, 3: 0.12}[LEVEL]
if LEVEL in (2, 3) and os.environ.get("PW4_WRITER_SRC") == "1":
    DY_W1N = DY_W1N_BRIDGE
B_LEFT = LEVEL == 3 and os.environ.get("PW4_WRITER_SRC") != "1"    # pw4_shunt's XW1N in the lower left (level 3)
DY_CHAIN = {0: 0.0, 1: 0.0, 2: 0.005, 3: -0.03}[LEVEL]
Y0_SHUNT = 8.9 + DY_CHAIN
BRIDGE_RECESS = {0: 0.0, 1: 0.045, 2: 0.08, 3: 0.21}[LEVEL]
DY_XCLM_BRIDGE = {0: 0.0, 1: 0.0, 2: 0.005, 3: 0.07}[LEVEL]
# level 3: XW1N of pw4_shunt, origin and orientation ("v": gate strip below); its HVI x 7.94 .. 12.89, 0.71 um from the
# writer well's west edge (13.6); diffusion y 2.495 .. 2.915
XW1N_BL = (10.415, 3.3)
DY_STUB = 0.035                                                    # level 3: the we stub where lock2_h's gate bar is


def m1pad(c, x, y, w=0.29, h=0.29):
    c.rect("metal1", x - w / 2, y - h / 2, x + w / 2, y + h / 2)


FRAME_W = 0.3        # the grounded metal4 frame: 0.3 um wide along the outline itself
FRAME = os.environ.get("PW4_FRAME", "outline")   # "outline": a grounded ring on the outline; "none": no frame (D8 budget)


def frame(c):
    if FRAME == "none":
        c.info["edge_note"] = "no frame: everything stays 0.3 um inside the outline except the pins"
        return
    if FRAME == "inset":                                         # the first frame (benched 2026-11-15), for comparison
        o = (0.3, 0.3, W - 0.3, H - 0.3)
        for r in ((o[0], o[1], o[2], o[1] + 0.5), (o[0], o[3] - 0.5, o[2], o[3]), (o[0], o[1], o[0] + 0.5, o[3]), (o[2] - 0.5, o[1], o[2], o[3])):
            c.rect("metal4", *r)
        c.rect("metal3", XC - 0.21, 0.35, XC + 0.21, 0.95)
        c.stack(XC, 0.6, top="metal4", bottom="metal1")
        return
    """The grounded metal4 frame round the two plates, along the outline (pulled back on 2026-11-15: the circuit
    strand's bench showed the first frame's stored-gate capacitance to ground, about 3 fF, in the network). The plates'
    edges are now 1.48 um from it on the outer sides and 1.85 um on the north and south (were 0.98 and 1.35)."""
    for r in ((0, 0, W, FRAME_W), (0, H - FRAME_W, W, H), (0, 0, FRAME_W, H), (W - FRAME_W, 0, W, H)):
        c.rect("metal4", *r)
    c.rect("metal4", XC - 0.2, 0.0, XC + 0.2, 0.8)              # down to its ground stack
    c.rect("metal3", XC - 0.21, 0.35, XC + 0.21, 0.95)
    c.stack(XC, 0.6, top="metal4", bottom="metal1")            # frame to ground at the bottom centre
    c.info["edge_note"] = ("the grounded metal4 frame (0.3 um wide) runs along the whole outline; everything else stays "
                           "0.3 um inside it except the pins")


LOWER = os.environ.get("PW4_LOWER", "tight")    # "wide": the lower plates (the part's own ends) reach 0.5 um from the outline
# Which cells: "rings" (current) or "1520" (the row delivered at 15:20 on 2026-11-15, before the rings).
ROW = "1520" if (os.environ.get("PW4_ROW") == "1520" or "--row1520" in sys.argv) else "rings"
RING = "none" if ROW == "1520" else "own"      # "own": a metal4 ring round each upper plate, on that plate's own end
WELL = "tight" if ROW == "1520" else "ext2"    # "ext2": the bridge's chain well (mid) under its gate bar and gate ends


def own_ring(c, m4, y_gn, open_side, m3):
    """A metal4 ring 0.4 um wide, 0.4 um outside an upper plate's metal4 (met4.5b: 0.4 um from metal4
    wider than 3 um), joined by via3 to that plate's lower plate, the part's own end, wherever the lower plate reaches
    under the ring (via3 0.155 um from the capacitor layer; capm.5 asks 0.08); open where the gn bar leaves the plate
    (open_side 'e' or 'w'). The plate's edge field then ends on its own end instead of the grounded frame and the
    substrate: 1.75 fF of the bridge gate's 3.36 fF to ground was there."""
    g, w = 0.4, 0.4
    i = (m4[0] - g, m4[1] - g, m4[2] + g, m4[3] + g)
    o = (i[0] - w, i[1] - w, i[2] + w, i[3] + w)
    c.rect("metal4", o[0], o[1], o[2], i[1])                    # south
    c.rect("metal4", o[0], i[3], o[2], o[3])                    # north
    for side, (x1, x2) in (("w", (o[0], i[0])), ("e", (i[2], o[2]))):
        if side == open_side:
            c.rect("metal4", x1, o[1], x2, y_gn - 0.3 - g)
            c.rect("metal4", x1, y_gn + 0.3 + g, x2, o[3])
        else:
            c.rect("metal4", x1, o[1], x2, o[3])
    cx_w, cx_e, cy_s, cy_n = (o[0] + i[0]) / 2, (i[2] + o[2]) / 2, (o[1] + i[1]) / 2, (i[3] + o[3]) / 2
    n = 5
    for k in range(n):
        x = i[0] + 0.6 + k * (i[2] - i[0] - 1.2) / (n - 1)
        y = i[1] + 0.6 + k * (i[3] - i[1] - 1.2) / (n - 1)
        for (vx, vy) in ((x, cy_s), (x, cy_n)) + (((cx_w, y), (cx_e, y)) if abs(y - y_gn) > 1.0 else ()):
            if m3[0] + 0.16 <= vx <= m3[2] - 0.16 and m3[1] + 0.16 <= vy <= m3[3] - 0.16:   # via3 0.2 + 0.06 in metal3
                c.via("via3", vx, vy)


def caps(c, y_gn):
    ow = 1.085 if LOWER == "wide" else (0.6 if RING == "own" else 0.14)   # outer side of each lower plate
    w = c.mim(*CAPW, plate_ext=(ow, 0.64, 0.99, 0.6))        # south to 1.315: over the DAC rail         # west: lower plate b (gap side to 13.565, north to 13.545)
    e = c.mim(*CAPE, plate_ext=(0.99, 0.64, ow, 0.6 if LOWER == "wide" else 0.14))   # east: lower plate a (gap side from 14.785)
    if RING == "own":
        c.info["interface_note"] = (
            "Inside the grounded metal4 frame on the outline, a metal4 ring 0.4 um wide runs 0.4 um round each capacitor's "
            "upper plate and is joined by via3 to that capacitor's lower plate, the part's own end (a on the east "
            "capacitor, b on the west; b is REF in the shunt). Each ring's net reaches diffusion inside the cell through "
            "metal3, metal2 and metal1 (the chain's end); no transistor gate is on it inside the cell.")
        own_ring(c, w, y_gn, "e", (CAPW[0] - ow, CAPW[1] - 0.64, CAPW[2] + 0.99, CAPW[3] + 0.6))
        own_ring(c, e, y_gn, "w", (CAPE[0] - 0.99, CAPE[1] - 0.64, CAPE[2] + ow, CAPE[3] + (0.6 if LOWER == "wide" else 0.14)))
    c.rect("metal4", w[2] - 0.4, y_gn - 0.3, e[0] + 0.4, y_gn + 0.3)   # gn: the two upper plates joined
    c.rect("metal3", XC - 0.21, y_gn - 0.3, XC + 0.21, y_gn + 0.3)
    c.stack(XC, y_gn, top="metal4", bottom="metal1")
    return w, e


def rails(c):
    c.rect("metal1", 0.3, Y_VSS - 0.24, W - 0.3, Y_VSS + 0.24)
    c.h("metal2", 0.3, W - 0.3, Y_VDD)
    c.h("metal2", 0.3, W - 0.3, Y_DAC)
    c.h("metal2", 0.3, W - 0.3, Y_REF)
    c.h("metal2", 0.3, W - 0.3, Y_CLW)


def writer(c, dy_w1n=None, b_left=False):
    dy_w1n = DY_W1N if dy_w1n is None else dy_w1n
    # ---- row B: 5 V NMOS at the gate (drain on the column), hold of wm to REF; gate contacts above
    if b_left:      # level 3: in the lower left, turned over: D (gn) 12.56 east, S (wm) 8.27 west, gate strip below
        w1n = c.dev("hv4t", "XW1N", XW1N_BL[0], XW1N_BL[1], "v")
    else:
        w1n = c.dev("hv4t", "XW1N", XC + 0.1 + 2.145, YB + dy_w1n)   # D (gn) 14.275, S (wm) 18.565
    wc = c.dev("n8t", "XWC", 23.49, YB)                           # D (wm) 19.345, S (ref) 27.635
    # ---- row A: gate PMOS (contact below), transmission gate (NMOS contact below, PMOS contact above), inverter
    w1p = c.dev("lvt1b", "XW1P", XC + 0.645, YA_P - 0.36)         # pdiff 2.52 .. 3.52; D (gn) 14.175, S (wm) 15.465
    xg = 16.55
    tgn = c.dev("tgnb", "XW2_XMN", xg, YA_N)                      # D (wm) 16.33, S (dac) 16.77
    tgp = c.dev("tgpt", "XW2_XMP", xg, YA_P)
    xt, xi = 17.6, 18.06
    c.std("tapvpwrvgnd_1", "TAPW", xt, Y_VSS)
    c.std("inv_1", "XWI_XSTD", xi, Y_VSS)
    c.rect("nwell", 13.6, 2.21, xi + 1.57, YA_P + 0.82)                  # one n-well: XW1P, the gate's PMOS, the standard cells
    if LEVEL == 3:      # lvtn.10 in the cell: XW1P's lvtn (14.14 .. 15.50, 2.34 .. 3.70) enclosed by 0.40 below (stepped
        # corners clear of the transmission gate's n+, as lock2_h's patch) and 0.40 above (XW1N is no longer there)
        c.rect("nwell", 13.855, 1.94, 15.785, 2.02)
        c.rect("nwell", 13.74, 2.055, 13.85, 2.21)
        c.rect("nwell", 15.79, 2.06, 15.89, 2.21)
        c.rect("nwell", 13.87, YA_P + 0.82, 15.77, 4.10)
    # supply: from the metal2 rail up to the standard cells' rail (metal1, y 3.32)
    xv = xi + 1.38 + 0.31                                         # riser east of the inverter
    c.via("via1", xv, Y_VDD + 0.02)
    c.v("metal1", xv, Y_VDD - 0.08, Y_VSS + 2.72 + 0.24, 0.3)
    c.rect("metal1", xi + 1.2, Y_VSS + 2.72 - 0.24, xv + 0.15, Y_VSS + 2.72 + 0.24)
    # wm: XW1P's source, both halves of the gate, up to row B (XW1N's source, XWC's drain)
    xs = XC + 1.29                                                # 15.465
    c.h("metal1", xs - 0.1, xg - 0.22 + 0.1, 3.3, 0.23)
    c.v("metal1", xg - 0.22, YA_N + 0.3, YA_P - 0.4, 0.23)
    c.v("metal1", xs, 3.3, 4.4, 0.23)
    c.h("metal1", xs - 0.115, 19.345 + 0.115, 4.4, 0.23)
    for x in ((19.345,) if b_left else (18.565, 19.345)):
        c.v("metal1", x, 4.4, YB - 0.1, 0.23)
    c.label("wm", "metal1", xs, 4.0)
    if b_left:
        # wm to XW1N's source in li, crossing neither gn nor (lengthwise) the DAC line: down from XW1P's source (0.18
        # clear of its gate contact), west under the grounded metal1 rail (y 0.36 .. 0.84, which shields it from the
        # DAC line above), up west of XW1N and onto its source contact from the west
        c.rect("locali", 15.495, 0.50, 15.665, 3.54)                  # beside XW1P's source li, its full height
        c.rect("locali", 7.90, 0.50, 15.665, 0.67)
        c.rect("locali", 7.90, 0.50, 8.07, XW1N_BL[1] + 0.385)
        c.rect("locali", 7.90, XW1N_BL[1] - 0.075, 8.355, XW1N_BL[1] + 0.385)   # over XW1N's source li, its full height
        # gn: XW1N's drain pad east to the gn column, at the pad's height (1.6 um above the DAC line)
        c.rect("metal1", 12.53, XW1N_BL[1] + 0.04, 14.29, XW1N_BL[1] + 0.27)
    # dac: both halves of the gate, down onto the rail
    c.v("metal1", xg + 0.22, YA_N + 0.3, YA_P - 0.4, 0.23)
    c.via("via1", xg + 0.22, Y_DAC)
    # we: inverter input, NMOS gate of the gate (contact below), XW1N's gate (bar above it), and the pin's wire
    xa, ya = xi + 0.485, Y_VSS + 1.16                             # inverter A (li)
    c.via("mcon", xa, ya)
    m1pad(c, xa, ya + 0.2, 0.29, 0.69)
    c.via("via1", xa, ya + 0.45)
    c.rect("metal1", xg - 0.3, YA_N - 0.485, 17.445, YA_N - 0.25)  # NMOS gate contact out to the east
    c.v("metal1", 17.3, YA_N - 0.485, 2.3, 0.29)
    c.via("via1", 17.3, 2.3)
    c.h("metal2", 17.3, X_WE, 2.3)
    c.v("metal2", xa, ya + 0.45, 2.3)
    c.v("metal2", X_WE, 2.3, 6.3)
    if b_left:
        # the gate bar of lock2_h's XW1N kept as a we stub (its metal1, via and metal2 as there; the top-level we0 route
        # of rows 1 and 2 lands on it at x 14.46 .. 14.79); XW1N's own gate strip gets we in li from the transmission
        # gate's gate contact, west of the gate's wm li and under the DAC line, clear of wm
        dy_w1n = DY_STUB
        c.rect("metal1", 14.44, YB + dy_w1n + 0.215, 18.40, YB + dy_w1n + 0.445)
        # we: the transmission gate's gate contact pad west in metal1 over the wm li, then li under the supply rail, up
        # across the DAC line onto the middle of XW1N's gate strip (2.3 um from its drain)
        c.rect("metal1", 15.04, 0.98, 16.25, 1.215)
        c.via("mcon", 15.185, 1.095)
        c.rect("locali", 9.90, 1.01, 15.30, 1.18)
        c.rect("locali", 9.90, 1.01, 10.07, XW1N_BL[1] - 0.245)
    c.rect("metal1", 18.3, YB + dy_w1n + 0.245, 18.95, YB + dy_w1n + 0.415)   # XW1N's gate bar, lengthened east
    c.h("metal2", 18.75, X_WE, 6.1)
    c.via("via1", 18.75, YB + dy_w1n + 0.33)
    c.v("metal2", 18.75, YB + dy_w1n + 0.33, 6.1)
    c.label("we_int", "metal2", 20.0, 2.3)
    # we_b: inverter output, PMOS gate of the gate (contact above), XW1P's gate (contact below), XWC's gate (bar above)
    xy, yy = xi + 0.885, Y_VSS + 2.2                              # inverter Y (li)
    c.via("mcon", xy, yy)
    c.via("via1", xy, yy)
    c.h("metal2", XC + 0.9, 19.8, yy)
    c.via("via1", xg, YA_P + 0.64)
    c.v("metal2", xg, yy, YA_P + 0.64)
    c.via("via1", XC + 0.9, YA_P - 0.36 - 0.64)
    c.v("metal2", XC + 0.9, YA_P - 0.36 - 0.64, yy)
    c.v("metal2", 19.8, yy, YB + 0.33)
    c.via("via1", 19.8, YB + 0.33)
    return dict(w1n=w1n, wc=wc, w1p=w1p, tgn=tgn, tgp=tgp)


def writer_pins(c):
    """REF down the writer's edge to XWC's source; the write strobe's pin and its metal1 down to row B."""
    c.via("via1", X_REF, Y_REF)
    c.v("metal1", X_REF, YB - 0.2, Y_REF, 0.23)
    c.port("we", "metal2", X_WE - 0.15, H - 0.7, X_WE + 0.15, H)
    c.via("via1", X_WE, H - 0.5)
    c.v("metal1", X_WE, 6.3, H - 0.5, 0.23)
    c.via("via1", X_WE, 6.3)


def bus_pin(c, name, x, y_from):
    """A bus pin on the north edge with its metal1 down to a metal2 wire at y_from."""
    c.port(name, "metal2", x - 0.15, H - 0.7, x + 0.15, H)
    c.via("via1", x, H - 0.5)
    c.v("metal1", x, y_from, H - 0.5, 0.23)
    c.via("via1", x, y_from)


def edge_ports(c, b_west=None):
    c.port("ref", "metal2", W - 0.7, Y_REF - 0.15, W, Y_REF + 0.15)
    c.port("dac", "metal2", W - 0.7, Y_DAC - 0.15, W, Y_DAC + 0.15)
    c.port("clamp", "metal2", W - 0.7, Y_CLW - 0.15, W, Y_CLW + 0.15)
    c.port("vdd", "metal2", W - 0.7, Y_VDD - 0.15, W, Y_VDD + 0.15, use="power")
    c.port("vss", "metal1", W - 0.7, Y_VSS - 0.24, W, Y_VSS + 0.24, use="ground")


def shunt():
    c = Cell("pw4_shunt")
    y0 = Y0_SHUNT                                                 # chain: centre stripe (mid); n-well 6.285 .. 11.515 (frozen)
    y_gn = y0 - 1.145 if LEVEL != 3 else 7.76                     # gate via stack, on the lower gate's contact (level 3: lock2_h's)
    frame(c)
    caps(c, y_gn)
    rails(c)
    c.v("metal1", X_VSSR, Y_VSS, 13.3, 0.3)                       # ground up the west edge (the clamps' tap)
    writer(c, b_left=B_LEFT)
    c.dev("lvt8x2t", "XPA", XC - 4.14, y0, "90")                  # west half: stripes a (top), mid, b (bottom)
    c.dev("lvt8x2b", "XPB", XC + 4.14, y0, "90")                  # east half
    c.v("metal1", XC, y0 - 2.065, y0 + 2.065, 0.23)               # the two gates' contacts joined: gn
    c.v("metal1", XC, YA_P - 0.68, y0 - 2.065, 0.23)              # gn column down to XW1N and XW1P
    c.label("gn", "metal1", XC, 4.2)
    ya, ym, yb = y0 + 2.29, y0, y0 - 2.29
    for y in (ya, ym, yb):
        for x in (6.2, 13.5, 14.85, 22.15):
            c.via("via1", x, y)
    c.h("metal2", 3.0, X_A, ya, 0.42)                             # a: both halves, west to the clamp pocket, east to the pin
    c.h("metal2", 6.0, 22.35, ym, 0.42)                           # mid
    if LEVEL == 3:      # b: 0.30 wide (lower edge 0.12 up) where row 2's top-level res_sel pad stands below it, then
        # 0.36 wide (lower edge 0.06 up) over the we wire (metal2, y 5.95 .. 6.25) to the east end (via at 22.15: 0.075)
        c.rect("metal2", 4.3, yb - 0.21, 16.85, yb + 0.21)
        c.rect("metal2", 16.85, yb - 0.09, 17.75, yb + 0.21)
        c.rect("metal2", 17.75, yb - 0.15, 22.35, yb + 0.21)
    else:
        c.h("metal2", 4.3, 22.35, yb, 0.42)                       # b
    c.via("via2", 15.4, ya)                                       # a: east lower plate
    c.via("via2", 13.0, yb)                                       # b: west lower plate
    # b is REF in the row (XSH1, XSH2 in pw4_rblock4): the west lower plate up to the REF rail
    c.via("via2", 8.5, 13.2)
    c.v("metal2", 8.5, Y_REF, 13.2)
    # well taps at both ends, joined to mid (the centre stripe)
    for x1, x2 in ((4.9, 5.27), (23.08, 23.45)):
        c.tap_strip("nsubdiff", x1, y0 - 1.0, x2, y0 + 1.0)
        c.via("mcon", (x1 + x2) / 2, y0)
    c.rect("nwell", 4.72, y0 - 2.615, 23.63, y0 + 2.615)
    if LEVEL == 3:      # lvtn.10 in the cell: the chain's lvtn (5.675 .. 22.675, y0 -/+ 2.325) enclosed by 0.39 below and
        # 0.385 above (the bus clamps' HVI then 0.705 above the well)
        c.rect("nwell", 5.675 - 0.39, y0 - 2.325 - 0.39, 22.675 + 0.39, y0 - 2.615)
        c.rect("nwell", 5.675 - 0.385, y0 + 2.615, 22.675 + 0.385, y0 + 2.325 + 0.385)
    c.h("metal1", 4.9, 5.95, y0, 0.23)
    c.label("mid", "metal1", 5.5, y0)
    c.h("metal1", 22.4, 23.45, y0, 0.23)
    # the well's clamp XCLM (native 1/0.5): mid -> REF, gate on the clamp line; top band, west
    cl = c.dev("nvt1t", "XCLM", 3.0, 13.005)                     # diffusion 12.35 .. 13.35: 0.835 um from the chain's n-well
    c.via("via1", 3.395, Y_REF)                                   # S: REF
    c.via("via1", 3.0, 13.625)                                    # G: clamp line
    c.v("metal1", 5.085, y0, 11.95, 0.23)                         # D: mid, from the west well tap
    c.h("metal1", 2.49, 5.2, 11.95, 0.23)
    c.v("metal1", 2.605, 11.95, 12.45, 0.23)
    c.tap_strip("psubdiff", 1.3, 12.35, 1.7, 13.35)                 # substrate tap of the clamps (to the ground riser)
    c.via("mcon", 1.5, 12.8)
    c.h("metal1", X_VSSR, 1.6, 12.8, 0.23)
    # the pocket where pw4_rblock4 puts the bus clamp of `a` (native 1/0.5 at (6.5, 12.955)): left empty here
    writer_pins(c)
    bus_pin(c, "a", X_A, ya)
    edge_ports(c)
    c.outline(0, 0, W, H)
    return c


def bridge():
    """Four LVT PMOS 4/2 in series (one diffusion, gates contacted below and joined: gn), standing at the centre;
    the writer is the shunt's mirrored (its strobe pin on the west, as the plan's); the clamps' pockets at both ends
    of the top band, the well's clamp between."""
    c = Cell("pw4_bridge")
    y0 = 9.105                                                    # chain origin: diffusion 7.285 .. 11.285, n-well from 6.785
    y_gn = 6.3
    frame(c)
    caps(c, y_gn)
    rails(c)
    c.mx = W
    writer(c, DY_W1N_BRIDGE)
    writer_pins(c)
    c.mx = None
    c.v("metal1", W - 0.75, Y_VSS, 12.0, 0.3)                    # ground up the east edge
    c.via("via1", W - 0.75, 12.0)
    c.h("metal2", 0.3, W - 0.3, 12.0)                             # ground for the clamps' taps (metal2, top band)
    c.dev("lvt4x4b", "XP", XC, y0)                                # stripes b, mb, mid, ma, a (x 9.595 .. 18.755)
    xs = [XC - 4.58, XC - 2.29, XC, XC + 2.29, XC + 4.58]
    yg = y0 - 2.14
    c.h("metal1", XC - 4.4, XC + 4.4, yg, 0.23)                   # the four gates joined: gn
    c.v("metal1", XC, YA_P - 0.68, yg, 0.23)                      # gn column down to XW1N and XW1P
    c.label("gn", "metal1", XC, 4.2)
    yab = 7.8
    for x in (xs[0], xs[4]):
        c.via("via1", x, yab)
    c.h("metal2", X_B, 13.15, yab, 0.42)                          # b: chain end, west lower plate, west pin
    c.h("metal2", 15.25, X_A2, yab, 0.42)                         # a: chain end, east lower plate, east pin
    c.via("via2", 13.0, yab)
    c.via("via2", 15.4, yab)
    # mid: the centre stripe over to the well tap at the east end of the chain, and on to the well's clamp
    xt = 19.385
    c.tap_strip("nsubdiff", xt - 0.185, y0 - 1.0, xt + 0.185, y0 + 1.0)
    c.via("mcon", xt, y0)
    y_well = 6.14 if WELL == "ext2" else y0 - 2.32
    if BRIDGE_RECESS and WELL == "ext2":
        # recess above XW1N only: from the well's west end to 0.275 um east of XW1N's diffusion (the mirrored writer's
        # XW1N: diffusion x 9.64 .. 14.22), so that its corner keeps 0.84 um from the unrecessed edge
        # level 2: 0.315 um past XW1N's drawn HVI (diffusion + 0.185), so that its corner keeps 0.645 um
        # level 3: 0.505 um past it (XW1N 0.12 up, recess 0.21: the corner keeps 0.705)
        x_r = round(W - (XC + 0.1 + 2.145) + (2.29 + 0.275 if LEVEL == 1 else 2.475 + (0.315 if LEVEL == 2 else 0.505)), 3)
        c.rect("nwell", XC - 4.905, y_well + BRIDGE_RECESS, xt + 0.365, y0 + 2.49)
        c.rect("nwell", x_r, y_well, xt + 0.365, y_well + BRIDGE_RECESS)
    else:
        c.rect("nwell", XC - 4.905, y_well, xt + 0.365, y0 + 2.49)
    if WELL == "ext2":      # south to 0.825 um from the 5 V NMOS's diffusion (the limit); north past the gates' ends,
        c.rect("nwell", XC - 4.905, y0 + 2.39, 19.0, 12.2)      # 0.98 um clear of the well clamp's diffusion
    ym = 10.6
    c.via("via1", XC, ym)
    c.v("metal1", xt, y0, ym, 0.23)
    c.via("via1", xt, ym)
    c.h("metal2", XC - 0.2, 20.3, ym)
    c.label("mid", "metal1", xt, y0 + 0.6)
    yc = 13.075 + DY_XCLM_BRIDGE                                   # clamps: diffusion 12.42 .. 13.42 (frozen)
    cl = c.dev("nvt1t", "XCLM", 20.5, yc)                          # D (mid) 20.105, S (ref) 20.895
    c.via("via1", 20.105, ym)
    c.v("metal1", 20.105, ym, yc - 0.6, 0.23)
    c.via("via1", 20.895, Y_REF)
    c.v("metal1", 20.5, yc + 0.6, Y_CLW, 0.23)
    c.via("via1", 20.5, Y_CLW)
    c.tap_strip("psubdiff", 22.0, 12.42, 22.4, 13.42)              # the clamps' substrate tap, on the ground wire
    c.via("mcon", 22.2, 12.65)
    c.v("metal1", 22.2, 12.0, 12.75, 0.23)
    c.via("via1", 22.2, 12.05)
    c.tap_strip("psubdiff", 6.6, 12.42, 7.0, 13.42)                 # substrate tap for the west pocket
    c.via("mcon", 6.8, 12.65)
    c.v("metal1", 6.8, 12.0, 12.75, 0.23)
    c.via("via1", 6.8, 12.05)
    # pockets for the bus clamps that pw4_rblock4 adds (native 1/0.5, origin y 13.075): on b at x 5.5, on a at x 24.5
    bus_pin(c, "b", X_B, yab)
    bus_pin(c, "a", X_A2, yab)
    edge_ports(c)
    c.outline(0, 0, W, H)
    return c


CELLS = {"shunt": shunt, "bridge": bridge}

if __name__ == "__main__":
    for k in [a for a in sys.argv[1:] if not a.startswith("--")] or ["shunt"]:
        build(CELLS[k](), extract=True)
