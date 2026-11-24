"""Place and route the limiter: AH's pdk_limiter (precision_limiter + its two 220 kohm bias resistors).

Ports (pdk_limiter order): raw vlo vhi act vdd vss reset ref.

Floorplan (x right, y up, um):
  XHIGH  az_clamp mirrored left-right (its pins face right), x 0 .. 44.8
  ch1    9 um routing channel between the clamps' pin edges
  XLOW   az_clamp, x 53.8 .. 98.6
  Both clamps sit on top of a 13.6 um device region:
    MPHIGH (pfet W4 L0.15 x40, n-well tied to act) under XHIGH's out plate (gate_hi)
    MNLOW  (nfet W4 L0.15 x40) under XLOW's out plate (gate_lo)
    bottom row: the LO/HI bias resistors as one two-strip array (under XHIGH), RSER (under
    XLOW) and the limiter's inverter pair (reset -> az_b -> az) under the channel
    metal1 buses: vss 4.0, reset 4.7, act 5.4, vdd 6.1
  In ch1, verticals are metal2 and every horizontal is metal1, so any order works:
    act, vhi, ibhi, iblo, vlo, reset (stub), ref (metal3), lim_az_b, lim_az
Ports leave the bottom edge (act vhi vlo reset vss raw on metal2, ref on metal3); vdd leaves
the top edge on both clamps' vdd trunks.
"""
from __future__ import annotations

import json

from cell import Mos, Res
from geom import Tcl
from magic_util import RESULTS

PIN = {p["name"]: p for p in json.loads((RESULTS / "az_clamp_pins.json").read_text())["pins"]}
YL = 13.6            # device region height; both clamps sit on y = YL
XH0 = 44.81          # XHIGH child origin (mirrored, so block x = XH0 - local x)
W1 = 9.0
X2 = XH0 + W1        # XLOW lower-left x
W2 = 0.30


def build(t: Tcl) -> dict:
    t.add("load limiter")
    d = {}

    def hi(lx, ly):
        return (XH0 - lx, YL + ly)

    def lo(lx, ly):
        return (X2 + lx, YL + ly)

    t.box(XH0, YL, XH0, YL)
    t.add("getcell az_clamp h child 0 0")
    t.add("identify XHIGH")
    t.box(X2, YL, X2, YL)
    t.add("getcell az_clamp child 0 0")
    t.add("identify XLOW")

    def v1p(x, y):
        t.via("via1", x, y)

    def mcon(x, y):
        t.via("mcon", x, y)

    def h1(x1, x2, y, w=W2):
        t.hwire("metal1", min(x1, x2), max(x1, x2), y, w)

    def h2(x1, x2, y, w=W2):
        t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    def v2(x, y1, y2, w=W2):
        t.vwire("metal2", x, min(y1, y2), max(y1, y2), w)

    def stripe_vias(dev, idx, y):
        for i in idx:
            v1p(dev.sx[i], y)

    # ---------------- devices under the clamps ----------------
    yc = 9.77
    mph = d["mph"] = Mos(t, "lim_mphigh", "XMPHIGH", 24.06, yc, 4, 0.15, 40, pmos=True, conn=True)
    mnl = d["mnl"] = Mos(t, "lim_mnlow", "XMNLOW", 74.17, yc, 4, 0.15, 40, conn=True)
    rb = d["rb"] = Res(t, "lim_rbias", "XRBIAS", 22.9, 1.6, 90, 0.125, 19.145, 21.25, 1.155, 21.845)
    rs = d["rs"] = Res(t, "lim_rser", "XRSER", 58.27, 1.57, 90, 0.655, 0.57, 2.675, 1.27, 3.27)
    y0 = 0.5                                             # inverter row: tap | inv (reset->az_b) | inv (az_b->az)
    xr = 49.9
    for name, cell, x in (("XTAP", "sky130_fd_sc_hd__tapvpwrvgnd_1", xr), ("XAZB", "sky130_fd_sc_hd__inv_1", xr + 0.46),
                          ("XAZ", "sky130_fd_sc_hd__inv_1", xr + 1.84)):
        t.box(x, y0, x, y0)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {name}")
    # inverter pins on local interconnect: input A around (0.485, 1.195), output Y bar at x 0.885 (contact at y 2.17)
    ya_in, yy_out = y0 + 1.195, y0 + 2.17
    a1, y1_, a2, y2_ = xr + 0.46 + 0.485, xr + 0.46 + 0.885, xr + 1.84 + 0.485, xr + 1.84 + 0.885

    # ---------------- channel tracks ----------------
    X_ACT, X_VHI, X_IBH, X_IBL, X_VLO, X_RST, X_REF = 45.55, 46.15, 46.75, 47.35, 47.95, 48.55, 49.15
    X_AZB, X_AZ = xr + 1.75, y2_ + 0.03                 # az via1 nudged right, clear of the az_b L
    Y_VSS, Y_RST, Y_ACT, Y_VDD = 4.0, 4.7, 5.4, 6.1

    def pin_y(name):
        b = PIN[name]["shape_bbox"]
        return YL + (b[1] + b[3]) / 2 if b[3] - b[1] < 1 else None

    xh_in, xl_in = XH0 - 0.51, X2 + 0.49                 # via1 points on the clamps' metal2 pin bars

    # act: minus bars joined across the channel (metal2), one vertical to the act bus and the port
    ya = YL + 39.67
    h2(xh_in, xl_in, ya)
    v2(X_ACT, 0.0, ya)
    v1p(X_ACT, Y_ACT)
    # lim_az / lim_az_b: metal1 across the channel, metal2 down to the inverters
    for name, xt, yb in (("az", X_AZ, YL + 31.385), ("az_b", X_AZB, YL + 37.865)):
        for x in (xh_in, xl_in, xt):
            v1p(x, yb)
        h1(xh_in, xl_in, yb)
        v2(xt, yy_out, yb)
        v1p(xt, yy_out)
    mcon(a1, ya_in)                                      # reset in
    mcon(a2, ya_in)
    for x in (y1_, y2_):
        mcon(x, yy_out)
    # az_b: first inverter's Y -> second inverter's A (metal1 L clear of both neighbours)
    t.paint("metal1", y1_ - 0.145, yy_out - 0.145, a2 + 0.105, yy_out + 0.145)
    t.paint("metal1", a2 - 0.145, ya_in - 0.145, a2 + 0.105, yy_out + 0.145)
    # vhi / vlo / ibhi / iblo: metal1 stubs from each clamp to its own track
    for xin, xt, yb in ((xh_in, X_VHI, YL + 24.585), (xl_in, X_VLO, YL + 24.585)):
        v1p(xin, yb)
        v1p(xt, yb)
        h1(xin, xt, yb)
    # ibias: each clamp already has a via1 on its ibias stub (local x 1.0); continue on its metal1
    for xin, xt in ((XH0 - 1.0, X_IBH), (X2 + 1.0, X_IBL)):
        v1p(xt, YL + 17.415)
        h1(xin, xt, YL + 17.415)
    v2(X_VHI, 0.0, YL + 24.585)
    v2(X_VLO, 0.0, YL + 24.585)
    # bias pair: strip 1 (y 1.185) -> ibhi, strip 0 (y 2.015) -> iblo; right ends are the bias ends
    for xt, sdx in ((X_IBH, 0.415), (X_IBL, -0.415)):
        x1, y1, x2, y2 = rb.term("R1", sdx)
        yb = (y1 + y2) / 2
        v2(xt, yb, YL + 17.415)
        v1p(xt, yb)
        h1(x1, xt, yb, 0.25)
    for sdx in (0.415, -0.415):                          # left ends: vdd
        x1, y1, x2, y2 = rb.term("R2", sdx)
        t.paint("metal1", x1, y1, x2, y2)
    xbv = rb.term_c("R2", 0.415)[0]
    t.paint("metal1", xbv - 0.15, rb.term("R2", 0.415)[1], xbv + 0.15, rb.term("R2", -0.415)[3])
    v1p(xbv, 1.6)
    v2(xbv, 1.6, Y_VDD)
    v1p(xbv, Y_VDD)

    # ref: metal3 across the channel joins both hold plates; metal3 down to the port
    yr = YL + 23.4
    t.paint("metal3", XH0 - 0.2, yr - 0.4, X2 + 0.2, yr + 0.4)
    t.paint("metal3", X_REF - 0.4, 0.0, X_REF + 0.4, yr)

    # ---------------- MPHIGH: sources + n-well = act, drains = vss, gates = gate_hi ----------------
    stripe_vias(mph, range(0, 41, 2), 8.4)
    h2(13.05, mph.sx[40] + 0.18, 8.4)
    mcon(mph.ring[0] + 0.085, 8.4)                      # n-well guard ring -> act (metal1 to the act via)
    t.paint("metal1", 13.05, 8.25, mph.ring[0] + 0.17, 8.55)
    v1p(13.2, 8.4)
    v2(13.2, Y_ACT, 8.4)
    v1p(13.2, Y_ACT)
    stripe_vias(mph, range(1, 40, 2), 11.1)
    h2(mph.sx[1] - 0.18, 35.05, 11.1)
    v2(34.9, Y_VSS, 11.1)
    v1p(34.9, Y_VSS)
    ygh = (mph.pad_top[0] + mph.pad_top[1]) / 2 + 0.045
    for x in (mph.gx[7], mph.gx[19], mph.gx[32]):        # gate bar -> XHIGH's out plate (metal3)
        v1p(x, ygh)
        t.via("via2", x, ygh)
        t.paint("metal3", x - 0.4, ygh - 0.3, x + 0.4, YL)

    # ---------------- MNLOW: sources = act, drains = vdd, gates = gate_lo ----------------
    stripe_vias(mnl, range(0, 41, 2), 8.4)
    h2(63.25, mnl.sx[40] + 0.18, 8.4)
    v2(63.4, Y_ACT, 8.4)
    v1p(63.4, Y_ACT)
    stripe_vias(mnl, range(1, 40, 2), 11.1)
    h2(mnl.sx[1] - 0.18, 85.15, 11.1)
    v2(85.0, Y_VDD, 11.1)
    v1p(85.0, Y_VDD)
    ygl = (mnl.pad_top[0] + mnl.pad_top[1]) / 2
    for x in (mnl.gx[7], mnl.gx[19], mnl.gx[32]):
        v1p(x, ygl)
        t.via("via2", x, ygl)
        t.paint("metal3", x - 0.4, ygl - 0.3, x + 0.4, YL)

    # ---------------- RSER: raw (left, port) - act (right) ----------------
    xraw = rs.term_c("R2")[0]
    v1p(xraw, 1.57)
    v2(xraw, 0.0, 1.57)
    xra = rs.term_c("R1")[0]
    v1p(xra, 1.57)
    v2(xra, 1.57, Y_ACT)
    v1p(xra, Y_ACT)

    # ---------------- inverter row power and reset ----------------
    t.paint("metal1", xr - 0.45, y0 + 2.48, xr + 0.2, y0 + 2.96)      # VPWR rail stub -> vdd feed
    v1p(xr - 0.3, y0 + 2.72)
    v2(xr - 0.3, y0 + 2.72, Y_VDD)
    v1p(xr - 0.3, Y_VDD)
    t.paint("metal1", xr + 3.0, y0 - 0.24, 53.75, y0 + 0.24)          # VGND rail stub -> vss feed
    v1p(53.6, y0)
    v2(53.6, y0, Y_VSS)
    v1p(53.6, Y_VSS)
    v1p(a1, ya_in)
    v2(a1, ya_in, Y_RST)
    v1p(a1, Y_RST)
    v2(X_RST, 0.0, Y_RST)
    v1p(X_RST, Y_RST)

    # ---------------- power: clamp trunks down to the buses ----------------
    xvh = XH0 - 41.5
    v2(xvh, Y_VDD, YL + 5.6)                             # XHIGH vdd trunk -> vdd bus
    v1p(xvh, Y_VDD)
    v2(X2 + 41.5, Y_VDD, YL + 5.6)                       # XLOW vdd trunk -> vdd bus
    v1p(X2 + 41.5, Y_VDD)
    xsh = XH0 - 0.25
    v2(xsh, 0.0, YL + 0.4)                               # XHIGH vss trunk -> vss bus and port
    v1p(xsh, Y_VSS)
    v2(X2 + 0.25, Y_VSS, YL + 0.4)                       # XLOW vss trunk -> vss bus
    v1p(X2 + 0.25, Y_VSS)

    # ---------------- metal1 buses ----------------
    h1(xsh, X2 + 0.25, Y_VSS)
    h1(34.9, xsh, Y_VSS)
    h1(X_RST, a1, Y_RST)
    h1(13.2, 63.4, Y_ACT)
    h1(xbv, X2 + 41.5, Y_VDD)

    # ---------------- ports (pdk_limiter order) ----------------
    t.label("raw", "metal2", xraw, 0.2, 1)
    t.label("vlo", "metal2", X_VLO, 0.2, 2)
    t.label("vhi", "metal2", X_VHI, 0.2, 3)
    t.label("act", "metal2", X_ACT, 0.2, 4)
    t.paint("metal2", xvh - 0.15, YL + 39.2, xvh + 0.15, YL + 39.82)   # parent paint on XHIGH's vdd trunk
    t.label("vdd", "metal2", xvh, YL + 39.6, 5, use="power")
    t.label("vss", "metal2", xsh, 0.2, 6, use="ground")
    t.label("reset", "metal2", X_RST, 0.2, 7)
    t.label("ref", "metal3", X_REF, 0.2, 8)
    return d
