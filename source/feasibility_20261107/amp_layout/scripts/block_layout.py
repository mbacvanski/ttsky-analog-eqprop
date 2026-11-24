"""Activation blocks built from the verified cells.

act_pos  = cd_act_pos_az: XGAIN (az_gain), RG 10k (fb-ref), RF 70k (fb-raw), the limiter, and an
           inverter pair (reset -> az_b -> az) for XGAIN.
act_neg  = xor_activation_negative: XBUFFER (az_core as a unity buffer of h), XGAIN (az_gain with
           plus = ref), RIN 10k (buffered-fb), RF 80k (fb-raw), the limiter, one inverter pair
           shared by both amplifiers.

Common structure (x right, y up, um): every cell sits on y = YB = 7.0. Below that is a bottom strip
with RF and four metal1 buses (vss 3.5, vdd 4.2, reset 4.9, raw 5.6). The limiter's pins
leave its bottom edge and drop through the strip. Amplifier pins on a cell's left or right edge face a
routing channel; the hold plates (ref) are joined by metal3 bridges at y = YB + 32, where the
clamp's right-side via stacks leave room. Ports: h on the left edge, ref (metal3) and vdd on the top
edge, vss vdd act vhi vlo reset on the bottom edge.
"""
from __future__ import annotations

import json

from cell import Res
from geom import Tcl
from magic_util import RESULTS

YB = 7.0
Y_VSS, Y_VDD, Y_RST, Y_RAW = 3.5, 4.2, 4.9, 5.6
W2 = 0.30
PINS = {c: {p["name"]: p for p in json.loads((RESULTS / f"{c}_pins.json").read_text())["pins"]}
        for c in ("az_gain", "az_core", "limiter")}
SIZE = {c: json.loads((RESULTS / f"{c}_pins.json").read_text())["size_um"] for c in ("az_gain", "az_core", "limiter")}


class Router:
    def __init__(self, t: Tcl):
        self.t = t

    def v1p(self, x, y):
        self.t.via("via1", x, y)

    def mcon(self, x, y):
        self.t.via("mcon", x, y)

    def h1(self, x1, x2, y, w=W2):
        self.t.hwire("metal1", min(x1, x2), max(x1, x2), y, w)

    def h2(self, x1, x2, y, w=W2):
        self.t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    def v2(self, x, y1, y2, w=W2):
        self.t.vwire("metal2", x, min(y1, y2), max(y1, y2), w)

    def m(self, layer, x1, y1, x2, y2):
        self.t.paint(layer, x1, y1, x2, y2)

    def stack(self, x, y, top="metal3"):
        """via1 (+ via2 (+ via3)) at one point."""
        self.v1p(x, y)
        if top in ("metal3", "metal4"):
            self.t.via("via2", x, y)
        if top == "metal4":
            self.t.via("via3", x, y)


def place(t, cell, inst, x, y, mirror=False):
    """Place a verified cell with its lower-left at (x, y); mirror flips it left-right in place."""
    w = SIZE[cell][0]
    t.box(x + w if mirror else x, y, x + w if mirror else x, y)
    t.add(f"getcell {cell}{' h' if mirror else ''} child 0 0")
    t.add(f"identify {inst}")

    def tr(lx, ly):
        return (x + w - lx if mirror else x + lx, y + ly)
    return tr


def inverter_row(t, r: Router, xr, y0):
    """tap | inv (A=reset, Y=az_b) | inv (A=az_b, Y=az); returns pin points and the rail y values."""
    for name, cell, x in (("XTAP", "sky130_fd_sc_hd__tapvpwrvgnd_1", xr), ("XAZB_XSTD", "sky130_fd_sc_hd__inv_1", xr + 0.46),
                          ("XAZ_XSTD", "sky130_fd_sc_hd__inv_1", xr + 1.84)):
        t.box(x, y0, x, y0)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {name}")
    ya, yy = y0 + 1.195, y0 + 2.17
    a1, y1, a2, y2 = xr + 0.945, xr + 1.345, xr + 2.325, xr + 2.725
    r.mcon(a1, ya)
    r.mcon(a2, ya)
    r.mcon(y1, yy)
    r.mcon(y2, yy)
    r.m("metal1", y1 - 0.145, yy - 0.145, a2 + 0.105, yy + 0.145)       # az_b: Y of the first -> A of the second
    r.m("metal1", a2 - 0.145, ya - 0.145, a2 + 0.105, yy + 0.145)
    return dict(reset=(a1, ya), az_b=(xr + 1.75, yy), az=(y2 + 0.03, yy), vgnd=y0, vpwr=y0 + 2.72, x0=xr, x1=xr + 3.22)


def build_act_pos(t: Tcl) -> dict:
    t.add("load act_pos")
    r = Router(t)
    XG, XL = 9.0, 54.73
    g = place(t, "az_gain", "XGAIN", XG, YB)
    lim = place(t, "limiter", "XLIMIT", XL, YB)
    rf = Res(t, "act_rf70", "XRF", 27.64, 1.57, 90, 0.655, 24.54, 26.645, 1.27, 27.24)   # R2 (left) = fb, R1 = raw
    rg = Res(t, "act_r10", "XRG", 4.0, 46.5, 0, 0.655, 3.39, 5.495, 1.27, 6.09)         # R2 (bottom) = fb, R1 = ref
    inv = inverter_row(t, r, 5.0, YB + 0.5)

    def gp(name):          # az_gain pin bar at its left end: (x, y of the label, which sits on the bar)
        p = PINS["az_gain"][name]
        return g(p["shape_bbox"][0], p["label_xy"][1])

    def lp(name):          # limiter pin at its bottom edge: x
        return lim(PINS["limiter"][name]["label_xy"][0], 0)[0]

    # h: metal2 port stub, metal1 across the channel, metal2 into az_gain's plus bar
    xh, yh = gp("plus")
    r.h2(0.0, 1.45, yh)
    r.v1p(1.3, yh)
    r.h1(1.3, 8.95, yh)
    r.v1p(8.95, yh)
    r.h2(8.8, xh + 0.15, yh)

    # fb: RF left pad -> metal2 up the channel -> az_gain minus and RG's lower pad
    xf = 2.3
    r.v1p(xf, 1.57)
    _, ym = gp("minus")
    yrg = (rg.term("R2")[1] + rg.term("R2")[3]) / 2
    r.v2(xf, 1.57, yrg)
    r.h2(xf, gp("minus")[0] + 0.15, ym)
    r.v1p(xf, yrg)
    r.h1(xf, rg.x, yrg)
    # RG upper pad -> metal3 onto az_gain's hold plate (ref)
    xq, yq = rg.term_c("R1")
    r.stack(xq, yq, "metal3")
    r.m("metal3", xq - 0.4, yq - 0.4, XG, yq + 0.4)

    # inverter row: power, reset, az / az_b into az_gain
    xvs = g(0.25, 0)[0]                                  # az_gain's vss trunk
    r.m("metal1", inv["x1"] - 0.2, inv["vgnd"] - 0.24, xvs + 0.15, inv["vgnd"] + 0.24)
    r.v1p(xvs, inv["vgnd"])
    r.m("metal1", inv["x1"] - 0.2, inv["vpwr"] - 0.24, 8.75, inv["vpwr"] + 0.24)
    r.v1p(8.6, inv["vpwr"])
    r.v2(8.6, Y_VDD, inv["vpwr"])
    r.v1p(8.6, Y_VDD)
    xa, ya = inv["reset"]
    r.v1p(xa, ya)
    r.v2(xa, Y_RST, ya)
    r.v1p(xa, Y_RST)
    for net in ("az", "az_b"):
        x0, y0 = inv[net]
        xp, yp = gp(net)
        r.v1p(x0, y0)
        r.v2(x0, y0, yp)
        r.h2(x0, xp + 0.15, yp)

    # vss: az_gain trunk down to the vss bus; limiter vss down to the bus and the port
    r.v2(xvs, Y_VSS, YB + 0.4)
    r.v1p(xvs, Y_VSS)
    xls = lp("vss")
    r.v2(xls, 0.0, YB + 0.3)
    r.v1p(xls, Y_VSS)
    r.h1(xvs, xls, Y_VSS)

    # vdd: az_gain trunk down to the bus (jog clear of RF's raw riser), bridge to the limiter's XHIGH trunk
    xgv = g(44.4, 0)[0]
    r.v2(xgv, YB - 0.6, YB + 5.4)
    r.h2(xgv, xgv + 0.8, YB - 0.6)
    r.v2(xgv + 0.8, Y_VDD, YB - 0.6)
    r.v1p(xgv + 0.8, Y_VDD)
    xlv = lim(3.31, 0)[0]
    r.h2(xgv - 0.15, xlv + 0.15, YB + 25.0)
    xvp = xgv + 3.1                                      # vdd port stub at the bottom edge
    r.h1(8.45, xvp + 0.15, Y_VDD)
    r.v1p(xvp, Y_VDD)
    r.v2(xvp, 0.0, Y_VDD)

    # reset: bus from the inverter row to the limiter's reset pin and the port
    xlr = lp("reset")
    r.h1(xa - 0.15, xlr + 0.15, Y_RST)
    r.v2(xlr, 0.0, YB + 0.3)
    r.v1p(xlr, Y_RST)

    # act / vhi / vlo: straight down to the bottom edge
    for name in ("act", "vhi", "vlo"):
        r.v2(lp(name), 0.0, YB + 0.3)

    # raw: RF right pad, az_gain's out plate (metal3 strap to its bottom edge), limiter raw
    xr1 = rf.term_c("R1")[0]
    r.v1p(xr1, 1.57)
    r.v2(xr1, 1.57, Y_RAW)
    r.v1p(xr1, Y_RAW)
    xo = g(33.0, 0)[0]
    r.stack(xo, Y_RAW, "metal3")
    r.m("metal3", xo - 0.4, Y_RAW - 0.3, xo + 0.4, YB)
    xlw = lp("raw")
    r.v2(xlw, Y_RAW, YB + 0.3)
    r.v1p(xlw, Y_RAW)
    r.h1(xo - 0.15, xlw + 0.15, Y_RAW)

    # ref: metal3 bridge az_gain hold plate -> limiter (XHIGH) hold plate; metal3 port at the top
    yb = YB + 32.0
    r.m("metal3", g(44.73, 0)[0] - 0.2, yb - 0.4, lim(11.42, 0)[0] + 0.2, yb + 0.4)
    top = YB + SIZE["limiter"][1]
    xrp = g(20.0, 0)[0]
    r.m("metal3", xrp - 0.4, YB + SIZE["az_gain"][1] - 0.2, xrp + 0.4, top)

    # ---------------- ports (cd_act_pos_az order: h ref vlo vhi act reset vdd vss) ----------------
    t.label("h", "metal2", 0.3, yh, 1)
    t.label("ref", "metal3", xrp, top - 0.3, 2)
    t.label("vlo", "metal2", lp("vlo"), 0.2, 3)
    t.label("vhi", "metal2", lp("vhi"), 0.2, 4)
    t.label("act", "metal2", lp("act"), 0.2, 5)
    t.label("reset", "metal2", xlr, 0.2, 6)
    t.label("vdd", "metal2", xvp, 0.2, 7, use="power")
    t.label("vss", "metal2", xls, 0.2, 8, use="ground")
    return {}


def build_act_neg(t: Tcl) -> dict:
    """[az_core mirrored | channel | az_gain | limiter]: the buffer's pins face the gain stage's pins
    across one 10 um channel holding RIN (vertical), the shared inverter pair and the h, buffered,
    fb, ref, az, az_b wiring (verticals metal2, horizontals metal1)."""
    t.add("load act_neg")
    r = Router(t)
    XC, XM, XG = 0.0, 44.73, 54.73
    XL = XG + SIZE["az_gain"][0] + 1.0
    c = place(t, "az_core", "XBUFFER", XC, YB, mirror=True)
    g = place(t, "az_gain", "XGAIN", XG, YB)
    lim = place(t, "limiter", "XLIMIT", XL, YB)
    rf = Res(t, "act_rf80", "XRF", 81.2, 1.57, 90, 0.655, 28.065, 30.17, 1.27, 30.765)   # R2 (left) = fb, R1 = raw
    rin = Res(t, "act_r10", "XRIN", 48.6, 45.0, 0, 0.655, 3.39, 5.495, 1.27, 6.09)      # R2 (bottom) = buffered, R1 = fb
    inv = inverter_row(t, r, 47.5, YB + 0.5)

    def cp(name):          # az_core (mirrored) pin bar: right end x, label y
        p = PINS["az_core"][name]
        return c(p["shape_bbox"][0], p["label_xy"][1])

    def gp(name):
        p = PINS["az_gain"][name]
        return g(p["shape_bbox"][0], p["label_xy"][1])

    def lp(name):
        return lim(PINS["limiter"][name]["label_xy"][0], 0)[0]

    T_H, T_BUF, T_FB, T_REF = 45.5, 46.1, 51.6, 53.4
    xin_c, xin_g = XM - 0.45, XG + 0.45                 # via1 points on the two cells' pin bars

    def stub(xin, xt, y):
        r.v1p(xin, y)
        r.v1p(xt, y)
        r.h1(xin, xt, y)

    # h: buffer plus -> track -> bottom-edge port
    _, yh = cp("plus")
    stub(xin_c, T_H, yh)
    r.v2(T_H, 0.0, yh)
    # buffered: buffer minus, its out plate (metal3 strap onto the plate's right edge), RIN bottom pad
    _, ybm = cp("minus")
    stub(xin_c, T_BUF, ybm)
    yrb = (rin.term("R2")[1] + rin.term("R2")[3]) / 2
    yo = YB + 12.0
    r.v2(T_BUF, yo, max(ybm, (rin.term("R2")[1] + rin.term("R2")[3]) / 2))
    r.stack(T_BUF, yo, "metal3")
    r.m("metal3", XM - 0.2, yo - 0.4, T_BUF + 0.4, yo + 0.4)
    r.v1p(T_BUF, yrb)
    r.h1(T_BUF, rin.x, yrb)
    # fb: gain minus, RIN top pad, RF left pad
    _, yfm = gp("minus")
    stub(xin_g, T_FB, yfm)
    yrt = (rin.term("R1")[1] + rin.term("R1")[3]) / 2
    r.v1p(T_FB, yrt)
    r.h1(rin.x, T_FB, yrt)
    xr2 = rf.term_c("R2")[0]
    r.v1p(xr2, 1.57)
    r.h1(xr2, T_FB, 1.57)
    r.v1p(T_FB, 1.57)
    r.v2(T_FB, 1.57, yrt)
    # ref: gain plus -> track -> metal3 bar joining both hold plates; metal3 port at the top
    _, yrp = gp("plus")
    stub(xin_g, T_REF, yrp)
    yrb3 = YB + 27.5
    r.v2(T_REF, yrp, yrb3)
    r.stack(T_REF, yrb3, "metal3")
    r.m("metal3", XM - 0.2, yrb3 - 0.4, XG + 0.2, yrb3 + 0.4)
    # az / az_b: metal1 across the channel joining both cells, metal2 down to the inverter row
    for net in ("az", "az_b"):
        _, y = gp(net)
        x0, y0 = inv[net]
        r.v1p(xin_c, y)
        r.v1p(xin_g, y)
        r.h1(xin_c, xin_g, y)
        r.v1p(x0, y0)
        r.v2(x0, y0, y)
        r.v1p(x0, y)
    # inverter row power and reset
    xcs, xgs = c(0.25, 0)[0], g(0.25, 0)[0]               # the two vss trunks
    r.m("metal1", xcs - 0.15, inv["vgnd"] - 0.24, xgs + 0.15, inv["vgnd"] + 0.24)
    r.v1p(xcs, inv["vgnd"])
    r.v1p(xgs, inv["vgnd"])
    r.m("metal1", inv["x0"] - 0.65, inv["vpwr"] - 0.24, inv["x0"] + 0.2, inv["vpwr"] + 0.24)
    r.v1p(inv["x0"] - 0.5, inv["vpwr"])
    r.v2(inv["x0"] - 0.5, Y_VDD, inv["vpwr"])
    r.v1p(inv["x0"] - 0.5, Y_VDD)
    xa, ya = inv["reset"]
    r.v1p(xa, ya)
    r.v2(xa, Y_RST, ya)
    r.v1p(xa, Y_RST)

    # vss: both trunks down to the vss bus; limiter vss down to the bus and the port
    for x in (xcs, xgs):
        r.v2(x, Y_VSS, YB + 0.4)
        r.v1p(x, Y_VSS)
    xls = lp("vss")
    r.v2(xls, 0.0, YB + 0.3)
    r.v1p(xls, Y_VSS)
    r.h1(xcs, xls, Y_VSS)

    # vdd: buffer trunk (left edge) and gain trunk down to the vdd bus; gain trunk bridged to the limiter
    xcv, xgv = c(44.4, 0)[0], g(44.4, 0)[0]
    for x in (xcv, xgv):
        r.v2(x, Y_VDD, YB + 5.6)
        r.v1p(x, Y_VDD)
    r.h1(xcv, xgv, Y_VDD)
    xlv = lim(3.31, 0)[0]
    r.h2(xgv - 0.15, xlv + 0.15, YB + 25.0)
    xvp = 2.0
    r.v1p(xvp, Y_VDD)
    r.v2(xvp, 0.0, Y_VDD)

    # reset: bus from the inverter row to the limiter's reset pin and the port
    xlr = lp("reset")
    r.h1(xa - 0.15, xlr + 0.15, Y_RST)
    r.v2(xlr, 0.0, YB + 0.3)
    r.v1p(xlr, Y_RST)
    for name in ("act", "vhi", "vlo"):
        r.v2(lp(name), 0.0, YB + 0.3)

    # raw: RF right pad, the gain stage's out plate, limiter raw
    xr1 = rf.term_c("R1")[0]
    r.v1p(xr1, 1.57)
    r.v2(xr1, 1.57, Y_RAW)
    r.v1p(xr1, Y_RAW)
    xo = g(33.0, 0)[0]
    r.stack(xo, Y_RAW, "metal3")
    r.m("metal3", xo - 0.4, Y_RAW - 0.3, xo + 0.4, YB)
    xlw = lp("raw")
    r.v2(xlw, Y_RAW, YB + 0.3)
    r.v1p(xlw, Y_RAW)
    r.h1(xo - 0.15, xlw + 0.15, Y_RAW)

    # ref: metal3 bridge gain hold plate -> limiter (XHIGH) hold plate; metal3 port at the top
    yb = YB + 32.0
    r.m("metal3", g(44.73, 0)[0] - 0.2, yb - 0.4, lim(11.42, 0)[0] + 0.2, yb + 0.4)
    top = YB + SIZE["limiter"][1]
    xrp = g(20.0, 0)[0]
    r.m("metal3", xrp - 0.4, YB + SIZE["az_gain"][1] - 0.2, xrp + 0.4, top)

    # ---------------- ports (xor_activation_negative order: h ref vlo vhi act reset vdd vss) ----------------
    t.label("h", "metal2", T_H, 0.2, 1)
    t.label("ref", "metal3", xrp, top - 0.3, 2)
    t.label("vlo", "metal2", lp("vlo"), 0.2, 3)
    t.label("vhi", "metal2", lp("vhi"), 0.2, 4)
    t.label("act", "metal2", lp("act"), 0.2, 5)
    t.label("reset", "metal2", xlr, 0.2, 6)
    t.label("vdd", "metal2", xvp, 0.2, 7, use="power")
    t.label("vss", "metal2", xls, 0.2, 8, use="ground")
    return {}
