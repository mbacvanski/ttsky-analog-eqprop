"""Place and route the lean activation cells of variant AJ: lean_act, lean_bias and the block of all three.

Both cells are 68.0 um wide and stack by abutment. Shared conventions (x right, y up, um):
  * metal1 rails: VSS along the bottom (y 0.2 to 1.0), VDD along the top;
  * metal2 lines through the whole height, at the same x in both cells: ref (x 0.2 to 0.9), vss (62.3 to 63.3),
    vbn (63.9 to 64.5), vdd (65.1 to 66.1). Stacked cells join these lines;
  * signal pins are metal1 stubs to the left edge; they pass under the ref line, so tying one to ref is one via;
  * metal1 and metal2 only, except the bias-line capacitor of lean_bias (metal3 and metal4, x 19.2 to 51.4).

Matching (LEAN_NEURON.md section 7):
  * MT2 (lean_act) and its copy MR (lean_bias) are the same generator cell (la_tail2) at the same x, same
    orientation, each 0.53 um from a W5 L1 pair on its left, nothing on its right, with the same wiring on it:
    drain via on the left stripe, source strap to the vss line on the right, gate by metal1 from the top pad
    to the vbn line. No other metal crosses either transistor.
  * RL (lean_act) and RU (lean_bias) are 1.41 um strips lying in the same direction, ref end on the left, each
    alone in its own ring, with no metal above metal1 over either (the capacitor of lean_bias stops below RU and
    left of MR).
  * M1/M2, M3/M4 and MA/MB are A BB AA ... A rows with shared drains; M5/M6 are A B B A; R1A and R1B are the two
    strips of one array.

lean_act (inp inn act ref vbn vdd vss), 68.0 x 18.5:
  bottom row  MT1 | first pair M1/M2 (24 fingers) | second pair M3/M4 (8 fingers) | MT2
  middle      R1A/R1B (115 kohm, o1 ends on the left over the pair's first drains) | mirror M5/M6 (PMOS, at the
              right, above the second pair and MT2, two rows high)
  above       RL (50 kohm; ref end left, act end right), left of the mirror
  top         RX (55 kohm, a 1.41 um strip 38.61 um long; VDD end left, x end right, over the gap between RL and
              the mirror)
lean_bias (ref tap vbn vdd vss), 68.0 x 15.4:
  bottom row  mirror MPA/MPB | MNB/MTO | amplifier pair MA/MB (16 fingers) | MR
  middle      RB (220 kohm with its dummy strip), then the VDD rail (inside the cell, not on its top edge)
  top         RU (87.5 kohm; ref end left, vr end right, across the whole cell)
  over it     CVBN (vbn to vss, one 30.0 x 12.29 um MIM rectangle): bottom plate (metal3, vss) from the cell's
              bottom edge to just below RU, right edge on the amplifier pair's ring; it covers MA/MB whole and
              stays off MPA/MPB, MR and RU
"""
from __future__ import annotations

from cell import MimUnit, Mos, Res
from geom import Tcl, snap

W = 68.0
X_REF = (0.2, 0.9)
X_VSS = (62.3, 63.3)
X_VBN = (63.9, 64.5)
X_VDD = (65.1, 66.1)
Y_VSS = (0.2, 1.0)
W2 = 0.30
X_TAIL = 56.665            # MT2 and MR: same x in both cells
GAP = 0.53                 # between guard rings of different size (their tap strips may not partly overlap)
NGAP = 0.62                # between the mirror's n-well ring and a substrate ring (n-well 0.265 beyond its ring)
CV_W, CV_L = 30.0, 12.29   # CVBN of lean_bias: wide (x), tall (y); 368.7 um2, 0.751 pF
Y_ROW = 4.6                # centre of the W5 pairs in the bottom row (ring bottom at 1.315)


class Kit:
    """Routing helpers bound to one Tcl script."""

    def __init__(self, t: Tcl):
        self.t = t

    def v1(self, x, y):
        t = self.t
        t.paint("metal1", x - 0.13, y - 0.165, x + 0.13, y + 0.165)
        t.paint("metal2", x - 0.13, y - 0.18, x + 0.13, y + 0.18)
        t.box(x - 0.13, y - 0.13, x + 0.13, y + 0.13)
        t.add("paint via1")

    def v1p(self, x, y, nx=1, ny=1):
        self.t.via("via1", x, y, nx=nx, ny=ny)

    def mcon(self, x, y):
        self.t.via("mcon", x, y)

    def h2(self, x1, x2, y, w=W2):
        self.t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    def v2(self, x, y1, y2, w=W2):
        self.t.vwire("metal2", x, min(y1, y2), max(y1, y2), w)

    def m1(self, x1, y1, x2, y2):
        self.t.paint("metal1", x1, y1, x2, y2)

    def li(self, x1, y1, x2, y2):
        self.t.paint("locali", x1, y1, x2, y2)

    def stripes(self, dev, idx, y, ny=1):
        for i in idx:
            self.v1p(dev.sx[i], y, ny=ny)


def frame(t: Tcl, k: Kit, h: float, y_vdd=None):
    """Rails and the four through lines shared by both cells; returns the VDD rail's y range.

    The VDD rail lies along the top edge, or at y_vdd (then it ends on the VDD line instead of the right edge)."""
    x_end = W if y_vdd is None else X_VDD[1]
    y_vdd = y_vdd or (h - 1.0, h - 0.2)
    k.m1(0.0, Y_VSS[0], W, Y_VSS[1])
    k.m1(0.0, y_vdd[0], x_end, y_vdd[1])
    for x1, x2 in (X_REF, X_VSS, X_VBN, X_VDD):
        t.paint("metal2", x1, 0.0, x2, h)
    k.v1p((X_VSS[0] + X_VSS[1]) / 2, (Y_VSS[0] + Y_VSS[1]) / 2, nx=2)
    k.v1p((X_VDD[0] + X_VDD[1]) / 2, (y_vdd[0] + y_vdd[1]) / 2, nx=2)
    return y_vdd


def tail(t: Tcl, k: Kit, inst: str):
    """MT2 / MR with the wiring both cells give it: source to the vss line, gate to the vbn line.

    Returns the transistor; its drain (left stripe) is wired by the caller with one via at y = Y_ROW - 1.5."""
    mt = Mos(t, "la_tail2", inst, X_TAIL, 4.1, 4, 8, 1)
    k.stripes(mt, (1,), 3.6, ny=2)                                      # source -> vss line
    t.paint("metal2", mt.sx[1] - 0.2, 3.35, X_VSS[1], 3.85)
    x1, y1, x2, y2 = mt.pad(0, "top")                                   # gate -> vbn line, metal1 under the vss line
    k.m1(x2 - 0.3, y1, X_VBN[1], y2)
    k.v1p((X_VBN[0] + X_VBN[1]) / 2, (y1 + y2) / 2)
    k.m1(mt.ring[2] - 0.15, Y_VSS[1] - 0.1, mt.ring[2] + 0.15, mt.ring[1] + 0.14)   # ring -> VSS rail
    k.mcon(mt.ring[2], mt.ring[1])
    return mt


def pair_gates(k: Kit, dev, nf, top_x1=None, bot_x1=None):
    """A BB AA ... A row: A gates (fingers k = 0 or 3 mod 4) on a metal1 bar above the top pads, B gates on a bar
    below the bottom pads. Returns (y range of the A bar, y range of the B bar)."""
    ya = (dev.pad_top[1] + 0.15, dev.pad_top[1] + 0.43)
    yb = (dev.pad_bot[0] - 0.43, dev.pad_bot[0] - 0.15)
    a = [i for i in range(nf) if i % 4 in (0, 3)]
    b = [i for i in range(nf) if i % 4 in (1, 2)]
    k.m1(dev.gx[a[0]] - 0.3 if top_x1 is None else top_x1, ya[0], dev.gx[a[-1]] + 0.3, ya[1])
    k.m1(dev.gx[b[0]] - 0.3 if bot_x1 is None else bot_x1, yb[0], dev.gx[b[-1]] + 0.3, yb[1])
    for i in a:
        k.m1(dev.gx[i] - 0.3, dev.pad_top[0], dev.gx[i] + 0.3, ya[1])
    for i in b:
        k.m1(dev.gx[i] - 0.3, yb[0], dev.gx[i] + 0.3, dev.pad_bot[1])
    return ya, yb


def build_act(t: Tcl) -> dict:
    H = 18.5
    t.add("load lean_act")
    k = Kit(t)
    y_vdd = frame(t, k, H)
    d = {}

    # ---------------- placement: MT1 | pair1 pair2 (rings abut) | MT2 ----------------
    mt1 = d["mt1"] = Mos(t, "la_tail1", "XMT1", 4.615, 6.1, 8, 4, 1)
    p1 = d["p1"] = Mos(t, "la_pair1", "XM1_M2", mt1.ring[2] + GAP + 16.05, Y_ROW, 5, 1, 24)
    p2 = d["p2"] = Mos(t, "az_npair", "XM3_M4", p1.ring[2] + 5.73, Y_ROW, 5, 1, 8)
    assert abs(p2.ring[2] + GAP + 4.715 - X_TAIL) < 1e-6
    mt2 = d["mt2"] = tail(t, k, "XMT2")
    yr = p1.ring[3] + GAP + 1.155                                       # resistor line above the pairs
    r1 = d["r1"] = Res(t, "la_r1", "XR1A_R1B", p1.ring[0] + 12.655, yr, 270, 0.125, 9.955, 12.06, 1.155, 12.655)
    rl = d["rl"] = Res(t, "la_rl", "XRL", mt1.ring[0] + 20.19, mt1.ring[3] + GAP + 1.27, 270, 0.655, 17.49, 19.595, 1.27, 20.19)
    # the mirror sits above the second pair and MT2, beside R1 and RL; RX lies above RL and the mirror's left end
    pm = d["pm"] = Mos(t, "la_pmir", "XM5_M6", 52.4, p2.ring[3] + NGAP + 2.83, 4, 4, 4, pmos=True)
    rx = d["rx"] = Res(t, "la_rx", "XRX", 0.595 + 21.95, pm.ring[3] + NGAP + 1.27, 270, 0.655, 19.25, 21.355, 1.27, 21.95)
    assert rx.ring[3] < H - 1.0 and rx.ring[1] > rl.ring[3] + GAP
    ptop = (pm.y + 2.205, pm.y + 2.435)                                 # PMOS gate pads sit 0.045 um further out
    LO, UP = -0.415, 0.415                                              # lower / upper strip of a two-strip array
    k.li(20.0, p1.ring[3] - 0.085, 20.3, r1.ring[1] + 0.085)           # resistor rings -> pair ring
    k.li(30.0, r1.ring[3] - 0.085, 30.3, rl.ring[1] + 0.085)
    k.li(30.0, rl.ring[3] - 0.085, 30.3, rx.ring[1] + 0.085)
    k.li(mt1.ring[2] - 0.085, 1.6, p1.ring[0] + 0.085, 1.9)            # MT1 ring -> pair ring
    k.li(p2.ring[2] - 0.085, 1.6, mt2.ring[0] + 0.085, 1.9)            # pair ring -> MT2 ring (as MR's in lean_bias)

    # ---------------- gates of the two pairs ----------------
    xo = p1.ring[2] - 0.06                                              # o1 verticals between the two pairs
    ya, yb = pair_gates(k, p1, 24, top_x1=7.4, bot_x1=0.0)              # inp bar above, inn bar below (to the edge)
    ya2, yb2 = pair_gates(k, p2, 8, top_x1=xo - 0.2, bot_x1=xo - 0.2)   # o1p above, o1n below
    yin = (ya[0] + ya[1]) / 2
    # inp: metal1 stub at the left edge, metal2 over MT1, down onto the A bar
    k.m1(0.0, ya[0], 1.75, ya[1])
    k.v1p(1.5, yin)
    k.h2(1.5, 7.6, yin)
    k.v1p(7.6, yin)

    # ---------------- first stage: s1, o1n, o1p ----------------
    ys, yn, yp = Y_ROW - 1.5, Y_ROW + 0.3, Y_ROW + 1.7
    odd = list(range(1, 24, 2))
    k.stripes(p1, odd, ys)
    k.h2(mt1.sx[1] - 0.18, p1.sx[23] + 0.18, ys)
    k.v1p(mt1.sx[1], ys)                                                # MT1 drain
    an = list(range(0, 25, 4))                                          # A drains (M1): o1n
    bn = list(range(2, 24, 4))                                          # B drains (M2): o1p
    k.stripes(p1, an, yn)
    k.h2(p1.sx[0] - 0.18, xo + 0.15, yn)
    k.stripes(p1, bn, yp)
    k.h2(p1.sx[2] - 0.86, xo + 0.15, yp)
    # up to the load resistors (their o1 ends are on the left)
    xa, ya_r = p1.sx[0] + 0.15, snap(r1.term_c("R1", LO)[1])
    k.v2(xa, yn, ya_r)
    k.v1p(xa, ya_r)
    xb, yb_r = p1.sx[2] - 0.71, snap(r1.term_c("R1", UP)[1])
    k.v2(xb, yp, yb_r)
    k.v1p(xb, yb_r)
    # across to the second pair: o1n -> B gates (bottom bar), o1p -> A gates (top bar)
    k.v2(xo, (yb2[0] + yb2[1]) / 2, yn)
    k.v1p(xo, (yb2[0] + yb2[1]) / 2)
    k.v2(xo, yp, (ya2[0] + ya2[1]) / 2)
    k.v1p(xo, (ya2[0] + ya2[1]) / 2)

    # ---------------- x: R1A, R1B and RX's right end ----------------
    # metal1 along the loads' row to the gap between RL's ring and the mirror's, metal2 up that gap onto RX's pad
    a1 = r1.term("R2", LO)
    b1 = r1.term("R2", UP)
    xx = rl.ring[2] + 0.22
    assert rx.term("R2")[0] + 0.3 < xx < pm.ring[0] - 0.6
    k.m1(a1[2] - 0.45, a1[1], a1[2], b1[3])
    k.m1(a1[2] - 0.45, a1[1], xx + 0.15, a1[3])
    k.v1p(xx, (a1[1] + a1[3]) / 2)
    k.v2(xx, (a1[1] + a1[3]) / 2, rx.y)
    k.v1p(xx, rx.y)

    # ---------------- second stage: s2, pm, act ----------------
    k.stripes(p2, (1, 3, 5, 7), ys)
    k.h2(p2.sx[1] - 0.18, mt2.sx[0] + 0.18, ys)
    k.v1p(mt2.sx[0], ys)                                                # MT2 drain
    k.stripes(p2, (0, 4, 8), yp)                                        # pm = M3 drains
    k.h2(p2.sx[0] - 0.18, p2.sx[8] + 0.18, yp)
    ypm = pm.bot + 0.3
    k.v2(pm.sx[0], yp, ypm)
    k.v1p(pm.sx[0], ypm)
    yg = (ptop[1] + 0.15, ptop[1] + 0.43)                               # all four mirror gates on pm
    k.m1(pm.gx[0] - 1.9, yg[0], pm.gx[3] + 1.9, yg[1])
    for i in range(4):
        k.m1(pm.gx[i] - 0.5, ptop[0], pm.gx[i] + 0.5, yg[1])
    k.m1(pm.sx[0] - 0.115, pm.top - 0.05, pm.sx[0] + 0.33, ptop[1])     # diode: both pm drains onto the gate pads
    k.m1(pm.sx[4] - 0.33, pm.top - 0.05, pm.sx[4] + 0.115, ptop[1])
    yact = rl.ring[3] + 0.425                                           # act: metal1 line to the left edge
    k.stripes(p2, (2, 6), yn)                                           # M4 drains
    xv = p2.ring[2] + GAP / 2                                           # vertical in the gap between M3/M4 and MT2
    k.h2(p2.sx[2] - 0.18, xv + 0.15, yn)
    yam, xav = pm.bot + 0.9, xx + 0.5                                   # across the mirror below its source vias,
    k.v2(xv, yn, yam)                                                   # then up the gap beside the x line
    k.h2(xav - 0.15, pm.sx[2] + 0.15, yam)
    k.v1p(pm.sx[2], yam)                                                # M6 drains
    k.v2(xav, yam, yact)
    k.v1p(xav, yact)
    k.m1(0.0, yact - 0.15, xav + 0.2, yact + 0.15)
    x1, y1, x2, y2 = rl.term("R2")
    k.m1(x2 - 0.5, y2 - 0.2, x2 - 0.2, yact + 0.15)                     # RL's act end

    # ---------------- vdd ----------------
    yv = (y_vdd[0] + y_vdd[1]) / 2
    for i in (1, 3):                                                    # mirror sources
        k.v1p(pm.sx[i], pm.top - 0.9, ny=2)
        k.v2(pm.sx[i], pm.top - 1.1, yv)
        k.v1p(pm.sx[i], yv)
    x = pm.ring[2]                                                      # n-well ring (its left end is under RX's pad)
    k.m1(x - 0.15, pm.ring[3] - 0.08, x + 0.15, y_vdd[0] + 0.1)
    k.mcon(x, pm.ring[3])
    x1, y1, x2, y2 = rx.term("R1")                                      # RX's VDD end: straight up to the rail
    k.m1(x1 + 0.4, y2 - 0.2, x2 - 0.4, y_vdd[0] + 0.1)

    # ---------------- vss, vbn, ref ----------------
    k.v1p(mt1.sx[0], mt1.bot + 0.4)                                     # MT1 source -> VSS rail
    k.v2(mt1.sx[0], (Y_VSS[0] + Y_VSS[1]) / 2, mt1.bot + 0.4)
    k.v1p(mt1.sx[0], (Y_VSS[0] + Y_VSS[1]) / 2)
    k.m1(mt1.ring[0] - 0.15, mt1.bot, mt1.sx[0] + 0.115, mt1.bot + 0.3)   # ring -> MT1 source
    k.mcon(mt1.ring[0], mt1.bot + 0.15)
    # vbn: metal1 from MT1's gate over its ring, down the gap beside the first pair, then a line between the
    # pairs' gate bars and the loads (below the mirror, above MT2) to the vbn line. It keeps 0.53 um from the
    # input's gate bar: at the 0.14 um minimum the two coupled by 2.1 fF.
    yvb = (mt1.ring[3] - 0.135, mt1.ring[3] + 0.145)
    yvl = (ya[1] + 0.53, ya[1] + 0.81)
    xvc = (mt1.ring[2] + p1.ring[0]) / 2
    k.m1(mt1.x - 0.2, mt1.pad_top[0], mt1.x + 0.2, yvb[1])
    k.m1(mt1.x - 0.2, yvb[0], xvc + 0.14, yvb[1])
    k.m1(xvc - 0.14, yvl[0], xvc + 0.14, yvb[1])
    k.m1(xvc - 0.14, yvl[0], X_VBN[1], yvl[1])
    k.v1p((X_VBN[0] + X_VBN[1]) / 2, (yvl[0] + yvl[1]) / 2)
    x1, y1, x2, y2 = rl.term("R1")                                      # RL's ref end -> ref line
    k.m1(X_REF[0] + 0.15, rl.y - 0.25, x1 + 0.1, rl.y + 0.25)
    k.v1p((X_REF[0] + X_REF[1]) / 2, rl.y, ny=1)

    # ---------------- ports (lean_act order: inp inn act ref vbn vdd vss) ----------------
    t.label("inp", "metal1", 0.1, yin, 1)
    t.label("inn", "metal1", 0.1, (yb[0] + yb[1]) / 2, 2)
    t.label("act", "metal1", 0.1, yact, 3)
    t.label("ref", "metal2", 0.55, 15.5, 4)
    t.label("vbn", "metal2", 64.2, 15.5, 5)
    t.label("vdd", "metal2", 65.6, 15.5, 6, use="power")
    t.label("vss", "metal2", 62.8, 15.5, 7, use="ground")
    d.update(H=H, yin=yin, yinn=(yb[0] + yb[1]) / 2, yact=yact)
    return d


def build_bias(t: Tcl) -> dict:
    H = 15.4
    MimUnit.define(t, "lb_cvbn_u", CV_W, CV_L)
    t.add("load lean_bias")
    k = Kit(t)
    y_vdd = frame(t, k, H, y_vdd=(11.2, 12.0))                          # between RB and RU, so RU reaches the top edge
    d = {}

    # ---------------- placement: mirror | MNB/MTO | amplifier pair | MR (same place as MT2) ----------------
    mr = d["mr"] = tail(t, k, "XMR")
    pr = d["pr"] = Mos(t, "ac_npair", "XMA_MB", mr.ring[0] - GAP - 10.89, Y_ROW, 5, 1, 16)
    nb = d["nb"] = Mos(t, "pad_nbias", "XMNB_MTO", pr.ring[0] - GAP - 6.295, 4.1, 4, 2, 5, conn=True)
    pm = d["pm"] = Mos(t, "lb_pmir", "XMPA_MPB", 10.0, 4.145, 4, 4, 2, pmos=True, conn=True)
    ptop = (pm.y + 2.205, pm.y + 2.435)
    yr = pr.ring[3] + GAP + 1.155                                       # same heights as the resistor rows of lean_act
    rb = d["rb"] = Res(t, "az_rbias", "XRB", 7.86 + 21.845, yr, 270, 0.125, 19.145, 21.25, 1.155, 21.845)
    ru = d["ru"] = Res(t, "lb_ru", "XRU", 34.0, H - 0.28 - 1.27, 270, 0.655, 30.705, 32.81, 1.27, 33.405)
    LO, UP = -0.415, 0.415
    k.li(35.0, pr.ring[3] - 0.085, 35.3, rb.ring[1] + 0.085)           # resistor rings -> pair ring
    k.li(35.0, rb.ring[3] - 0.085, 35.3, ru.ring[1] + 0.085)
    k.li(nb.ring[2] - 0.085, 3.0, pr.ring[0] + 0.085, 3.3)             # MNB/MTO ring -> pair ring
    k.li(pr.ring[2] - 0.085, 1.6, mr.ring[0] + 0.085, 1.9)             # pair ring -> MR ring

    # ---------------- amplifier pair: A = MA (gate vr, drain pm), B = MB (gate tap, drain vbn) ----------------
    ya, yb = pair_gates(k, pr, 16, bot_x1=0.0)                          # tap bar below, to the left edge
    ys, ypm_, yvb_ = Y_ROW - 1.5, Y_ROW + 0.3, Y_ROW + 1.7
    k.stripes(pr, range(1, 16, 2), ys)                                  # st
    k.h2(nb.sx[5] - 0.18, pr.sx[15] + 0.18, ys)
    k.v1p(nb.sx[5], ys)                                                 # MTO drain
    k.stripes(pr, range(0, 17, 4), ypm_)                                # pm
    k.h2(pm.sx[0] - 0.18, pr.sx[16] + 0.18, ypm_)
    k.v1p(pm.sx[0], ypm_)                                               # MPA drain
    k.m1(pm.sx[0] - 0.115, pm.top - 0.05, pm.sx[0] + 0.33, ptop[1])     # MPA diode
    k.stripes(pr, range(2, 16, 4), yvb_)                                # vbn = MB drains
    xvb = pr.sx[14] + 0.93
    k.h2(pr.sx[2] - 0.18, xvb + 0.15, yvb_)

    # ---------------- vr: MR drain, MA gates, RU's right end ----------------
    xv = pr.ring[2] + GAP / 2                                           # vertical in the gap, as act's in lean_act
    yvr = (ya[0] + ya[1]) / 2
    k.v1p(mr.sx[0], ys)
    k.h2(xv - 0.15, mr.sx[0] + 0.18, ys)
    k.v2(xv, ys, yvr)
    k.v1p(xv, yvr)
    x1, y1, x2, y2 = ru.term("R2")
    k.m1(pr.gx[15] + 0.3, ya[0], x2 - 0.2, ya[1])
    k.m1(x2 - 0.5, ya[0], x2 - 0.2, y1 + 0.2)

    # ---------------- vbn: metal1 line between the resistor rows, as in lean_act ----------------
    yl = (rb.ring[3] + 0.025, rb.ring[3] + 0.305)
    xl = (pm.ring[2] + nb.ring[0]) / 2
    k.m1(xl - 0.15, yl[0], X_VBN[1], yl[1])
    k.v1p((X_VBN[0] + X_VBN[1]) / 2, (yl[0] + yl[1]) / 2)
    k.v2(xvb, yvb_, (yl[0] + yl[1]) / 2)                                # MB drains up to the line
    k.v1p(xvb, (yl[0] + yl[1]) / 2)
    k.m1(xl - 0.15, pm.y - 0.15, xl + 0.15, yl[1])                      # down beside the mirror to MPB's drain
    k.m1(pm.sx[2] - 0.115, pm.y - 0.15, xl + 0.15, pm.y + 0.15)

    # ---------------- nb: RB's right end -> MNB/MTO gate bar (metal1), MNB diodes ----------------
    x1, y1, x2, y2 = rb.term("R2", LO)
    ynb = (ya[1] + 0.18, ya[1] + 0.46)
    xnb = nb.gx[4] + 0.5
    k.m1(x2 - 0.5, ynb[0], x2 - 0.2, y1 + 0.1)
    k.m1(xnb - 0.15, ynb[0], x2 - 0.2, ynb[1])
    k.m1(xnb - 0.15, nb.pad_top[0], xnb + 0.15, ynb[1])
    for i in (1, 3):
        k.m1(nb.sx[i] - 0.33, nb.top - 0.04, nb.sx[i] + 0.33, nb.pad_top[1])   # onto the gate pads either side

    # ---------------- vss ----------------
    k.stripes(nb, (0, 2, 4), ys)
    k.h2(nb.sx[0] - 0.18, nb.sx[4] + 0.18, ys)
    k.v2(nb.sx[0], (Y_VSS[0] + Y_VSS[1]) / 2, ys)
    k.v1p(nb.sx[0], (Y_VSS[0] + Y_VSS[1]) / 2)
    k.m1(nb.ring[0] - 0.15, ys - 0.15, nb.sx[0], ys + 0.15)             # ring -> first source
    k.mcon(nb.ring[0], ys)

    # ---------------- vdd: mirror source, RB's left end, n-well ring ----------------
    yv = (y_vdd[0] + y_vdd[1]) / 2
    k.v1p(pm.sx[1], pm.top - 0.5, ny=2)
    k.v2(pm.sx[1], pm.top - 0.7, yv)
    k.v1p(pm.sx[1], yv)
    k.v1p(pm.sx[1], snap(rb.term_c("R1", LO)[1]))
    k.mcon(pm.sx[1], pm.ring[3])
    k.v1p(pm.sx[1], pm.ring[3])
    for name, xr in (("R1", rb.ring[0]), ("R2", rb.ring[2])):           # RB's dummy strip -> ring
        x1, y1, x2, y2 = rb.term(name, UP)
        k.m1(min(x1, xr) - 0.115, y1, max(x2, xr) + 0.115, y2)
        k.mcon(xr, (y1 + y2) / 2)

    # ---------------- ref ----------------
    x1, y1, x2, y2 = ru.term("R1")
    k.m1(X_REF[0] + 0.15, ru.y - 0.25, x1 + 0.1, ru.y + 0.25)
    k.v1p((X_REF[0] + X_REF[1]) / 2, ru.y)

    # ---------------- CVBN: vbn (top plate, metal4) to vss (bottom plate, metal3) ----------------
    # One rectangle over MNB/MTO, the amplifier pair and RB. Its metal3 ends on the pair's ring (MR, 0.53 um
    # further right, stays uncovered like MT2) and 0.58 um below RU's strip (uncovered like RL).
    cv = d["cv"] = MimUnit(t, "lb_cvbn_u", "XCVBN", pr.ring[2] - 0.14 - CV_W / 2, 0.14 + CV_L / 2, CV_W, CV_L)
    assert cv.capm[3] + 0.14 < ru.ring[1] and cv.capm[0] - 0.14 > pm.ring[2] + 0.265
    xs, ysk = cv.capm[0] - 1.78, (yl[0] + yl[1]) / 2                     # top plate: stack on the vbn line, 1.34 um
    k.v1p(xs, ysk)                                                      # from the capacitor, metal4 onto the plate
    t.via("via2", xs, ysk)
    t.via("via3", xs, ysk)
    t.paint("metal3", xs - 0.25, ysk - 0.25, xs + 0.25, ysk + 0.25)
    t.paint("metal4", xs - 0.25, ysk - 0.25, cv.top_m4[0] + 0.1, ysk + 0.25)
    xb, yb_ = cv.capm[0] - 0.68, (Y_VSS[0] + Y_VSS[1]) / 2               # bottom plate: tab beside the capacitor
    t.paint("metal3", xb - 0.4, 0.0, cv.capm[0], Y_VSS[1] + 0.2)         # down onto the VSS rail
    k.v1p(xb, yb_)
    t.via("via2", xb, yb_)

    # ---------------- ports (lean_bias order: ref tap vbn vdd vss) ----------------
    ytap = (yb[0] + yb[1]) / 2
    t.label("ref", "metal2", 0.55, 14.0, 1)
    t.label("tap", "metal1", 0.1, ytap, 2)
    t.label("vbn", "metal2", 64.2, 14.0, 3)
    t.label("vdd", "metal2", 65.6, 14.0, 4, use="power")
    t.label("vss", "metal2", 62.8, 14.0, 5, use="ground")
    d.update(H=H, ytap=ytap)
    return d


ACT_H, BIAS_H = 18.5, 15.4
ACT_PINS = dict(inp=7.78, inn=1.42, act=14.38)       # y of the metal1 stubs in lean_act
BIAS_TAP = 1.42


def build_block(t: Tcl) -> dict:
    """lean_act (H1) below, lean_bias in the middle, lean_act (H2) on top: same orientation, edges touching."""
    t.add("load lean_block")
    k = Kit(t)
    y_b, y_2 = ACT_H, ACT_H + BIAS_H
    for cell, inst, y in (("lean_act", "XACT1", 0.0), ("lean_bias", "XLB", y_b), ("lean_act", "XACT2", y_2)):
        t.box(0, y, 0, y)
        t.add(f"getcell {cell} child 0 0")
        t.add(f"identify {inst}")
    xr = (X_REF[0] + X_REF[1]) / 2
    # the input that the netlist puts on ref: one via where its stub passes under the ref line
    k.v1p(xr, ACT_PINS["inn"])                                          # XACT1: inn = ref
    k.v1p(xr, y_2 + ACT_PINS["inp"])                                    # XACT2: inp = ref
    H = y_2 + ACT_H

    def pin(name, layer, x, y, idx, use="signal"):
        t.paint(layer, x - 0.05, y - 0.07, x + 0.05, y + 0.07)
        t.label(name, layer, x, y, idx, use=use)

    pin("h1", "metal1", 0.1, ACT_PINS["inp"], 1)
    pin("act1", "metal1", 0.1, ACT_PINS["act"], 2)
    pin("h2", "metal1", 0.1, y_2 + ACT_PINS["inn"], 3)
    pin("act2", "metal1", 0.1, y_2 + ACT_PINS["act"], 4)
    pin("tap", "metal1", 0.1, y_b + BIAS_TAP, 5)
    pin("ref", "metal2", xr, 0.3, 6)
    pin("vdd", "metal2", (X_VDD[0] + X_VDD[1]) / 2, 0.3, 7, use="power")
    pin("vss", "metal2", (X_VSS[0] + X_VSS[1]) / 2, 0.3, 8, use="ground")
    return dict(H=H)
