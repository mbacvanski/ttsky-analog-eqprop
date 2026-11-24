"""pw4_bias: the bias block of v4 (circuit/v4_netlist.py): two stored bias words, their current reference, the gating
of their write strobes and the pull-downs of BIAS_PROG and WRITE. 12 x 68 um (agreed with the chip strand on
2026-11-15: the plan's 12 x 50 could not hold it), lower-left corner at chip (321.85, 157.0); seven pins on the west
edge at the top, ref (metal3), vdd, vss on the south edge.

From the bottom: word 1 (its 10.99 um capacitor over it), the shared part (the two current mirrors, the 286 kohm
reference strips, the series switches of the read and write currents, the seven gates and the two words' inverters,
the two pull-downs), word 2 (word 1 mirrored top to bottom), the pins.

A word under its capacitor: the follower XF (LVT PMOS 40/1 as four 10 um fingers, lying across the cell, in its own
n-well = the read line), and above it four columns, each an NMOS under a PMOS with the same two nets: the DAC switch
XDL (dac | line), the writer's switch to the drain XW2 (drn | wm), the writer's switch to REF XWC (wm | ref), the
writer at the stored gate XW1N (5 V) / XW1P (LVT) (wm | sg). Between the NMOS and PMOS rows run the four gate lines
(we, we_b, bp, bp_b); above the PMOS row the word's drain, line and wm wires. The stored gate sg is the follower's four
gates, contacted at the east end, one metal1 line down the east edge to the writer and up to the capacitor.

  python draw_bias.py [word]          word: one word by itself (test cell pw4_bias_wtest)
"""
from __future__ import annotations

import sys

from lib import Cell, build
import os
# PW4_WELLFIX=2 (bias layout work, 2026-11-24): XW1N (hv1t) 0.03 um further from the follower's well, its gate contact
# with it, so that its drawn HVI keeps 0.645 um from that low-voltage n-well; unset (or 1), drawn as frozen
DY_HV1T = 0.03 if os.environ.get("PW4_WELLFIX") == "2" else 0.0
# PW4_WELLFIX=3 (2026-11-24, lock2_r): XW1N where level 2 has it (a further move would bring word 2's gate strip within
# 0.14 um of a top-level metal1 wire); instead the read line's well tap stops 0.18 um short of x 7.33 and the follower's
# n-well is 0.06 um lower (y 6.69) over x 7.33 .. 9.87, so that XW1N's HVI keeps 0.705 um from it (0.709 at the corners)
LEVEL3 = os.environ.get("PW4_WELLFIX") == "3"
if LEVEL3:
    DY_HV1T = 0.03
DY_W1_VIA = 0.0

W, H = 12.0, 68.0
# word 1, absolute y (word 2 is the mirror: y -> H - y)
CX, CY = 6.09, 3.205         # follower (lying): stripes drn 5.785, line 4.495, drn 3.205, line 1.915, drn 0.625; gates contacted at x 11.13
Y_TAP = (6.2, 6.57)          # the read line's well tap (the follower's n-well reaches y 6.75)
YN = 7.09                    # NMOS diffusions start (0.34 above the follower's well)
GL = {"bp_b": 8.74, "bp": 9.18, "we_b": 9.62, "we": 10.06}   # gate lines (metal1), NMOS side first
GL_X0 = {1: {"bp_b": 1.0, "bp": 1.4, "we_b": 1.8, "we": 2.2}, 2: {"bp_b": 1.0, "bp": 1.4, "we_b": 1.8, "we": 2.2}}
YP = 10.84                   # PMOS diffusions start
TRK = {"wm": 12.0, "drn": 12.5, "line": 13.0}             # the word's wires above the PMOS row (metal2)
X_COL = {"dl": 3.6, "w2": 5.3, "wc": 6.6, "w1": 8.6}
X_DRN, X_LINE, X_SG = 9.9, 10.4, 11.23
X_VDDW, X_VSSW = 9.85, 10.35                               # the word's supply and ground taps
X_VDD, X_VSS = 10.85, 11.35                                # supply and ground lanes up the east edge (metal2)
# lanes up the west strip (metal2): word 1's signals pass word 2 and the shared part on these
LANE = {"bw1": 0.45, "dac": 0.89, "bp_b": 1.33, "bp": 1.77, "we1_b": 2.21, "we1": 2.65}
X_FEED = {"bp_b": 1.11, "bp": 1.51, "we_b": 1.91, "we": 2.31}   # word 2's strobe feeds (metal1, a staircase)
X_DRNW = 1.35
CAPM = (0.55, 1.255, 11.54, 12.245)   # word 1's capacitor layer
X_PAD = 9.4
MY = 68.0                             # word 2 = word 1 mirrored: y -> MY - y


def word(c, k, y_lo, y_hi):
    """Word k (1 or 2), drawn in word 1's frame; for word 2 the caller sets c.my = MY. y_hi: where the feeds from the
    shared part start (word 1's frame)."""
    s = f"W{k}_"
    dy = 0.0
    xd, xw2, xwc, xw1 = X_COL["dl"], X_COL["w2"], X_COL["wc"], X_COL["w1"]
    R = lambda *a: c.rect(a[0], a[1], a[2] + dy, a[3], a[4] + dy)
    V = lambda lay, x, y1, y2, w=0.3: c.v(lay, x, y1 + dy, y2 + dy, w)
    Hh = lambda lay, x1, x2, y, w=0.3: c.h(lay, x1, x2, y + dy, w)
    VIA = lambda kind, x, y: c.via(kind, x, y + dy)
    DEV = lambda cell, inst, x, y, o="0": c.dev(cell, s + inst, x, y + dy, o)
    # ---- the follower, lying; its n-well is the read line
    DEV("lvt40t", "XF", CX, CY, "90")
    if LEVEL3:
        R("nwell", 0.5, 0.3, 7.33, Y_TAP[1] + 0.18)
        R("nwell", 7.33, 0.3, 9.87, Y_TAP[1] + 0.12)
        R("nwell", 9.87, 0.3, 11.31, Y_TAP[1] + 0.18)
        c.tap_strip("nsubdiff", 1.2, Y_TAP[0] + dy, 7.15, Y_TAP[1] + dy)
        R("locali", 7.11, sum(Y_TAP) / 2 - 0.085, 10.36, sum(Y_TAP) / 2 + 0.085)    # the tap's li on to the line's mcon
    else:
        R("nwell", 0.5, 0.3, 11.31, Y_TAP[1] + 0.18)
        c.tap_strip("nsubdiff", 1.2, Y_TAP[0] + dy, 10.4, Y_TAP[1] + dy)
    ys = {"D0": CY + 2.58, "S1": CY + 1.29, "D2": CY, "S3": CY - 1.29, "D4": CY - 2.58}
    for y in (ys["D0"], ys["D2"]):
        VIA("via1", X_DRN, y)
    for y in (ys["S1"], ys["S3"]):
        VIA("via1", X_LINE, y)
    VIA("via1", X_DRN, ys["D4"])
    V("metal2", X_DRN, ys["D4"], TRK["drn"])                     # the three drain stripes
    V("metal2", X_LINE, ys["S3"], TRK["line"])
    VIA("mcon", X_LINE, sum(Y_TAP) / 2)
    VIA("via1", X_LINE, sum(Y_TAP) / 2)                          # the well tap on the line
    gy = [CY + 1.935, CY + 0.645, CY - 0.645, CY - 1.935]
    V("metal1", X_SG, gy[3] - 0.35, 6.85, 0.23)                  # sg: the four gate contacts, up to the writer's level
    # ---- columns: NMOS (contacts above) under PMOS (contacts below)
    # (the DAC switch XDL is drawn in the block's middle part, not here: it is NMOS 4 / PMOS 8 um wide)
    for x, nm in ((xw2, "XW2"), (xwc, "XWC")):
        DEV("tgnt", nm + "_XMN", x, YN + 0.405)
        DEV("tgpb", nm + "_XMP", x, YP + 0.32)
    DEV("hv1t", "XW1N", xw1, 7.575 + 0.365 + DY_HV1T)          # 5 V: 0.825 from the follower's well (frozen)
    DEV("lvt1b", "XW1P", xw1, YP + 0.32)
    R("nwell", 2.7, YP - 0.5, 10.25, YP + 2.18)
    c.tap_strip("nsubdiff", X_VDDW - 0.15, YP + 0.1 + dy, X_VDDW + 0.15, YP + 1.1 + dy)   # PMOS row's well on vdd
    VIA("mcon", X_VDDW, YP + 0.6)
    Hh("metal1", X_VDDW - 0.115, X_VDD + 0.13, YP + 0.6, 0.23)
    VIA("via1", X_VDD, YP + 0.6)
    c.tap_strip("psubdiff", X_VSSW - 0.15, YN + 0.25 + dy, X_VSSW + 0.15, YN + 1.0 + dy)  # NMOS row's substrate on vss
    VIA("mcon", X_VSSW, YN + 0.6)
    Hh("metal1", X_VSSW - 0.115, X_VSS + 0.13, YN + 0.6, 0.23)
    VIA("via1", X_VSS, YN + 0.6)
    # NMOS and PMOS terminals of each column joined on metal2 (the TG columns' two vias staggered)
    joins = [(xw2 - 0.22, YN - 0.15, YP + 0.25), (xw2 + 0.22, YN + 0.3, YP + 0.65),
             (xwc - 0.22, YN - 0.15, YP + 0.25), (xwc + 0.22, YN + 0.3, YP + 0.65),
             (xw1 - 0.645, 7.785 + DY_W1_VIA, YP + 0.5), (xw1 + 0.645, 7.785 + DY_W1_VIA, YP + 0.5)]
    for x, y1, y2 in joins:
        if y1 < YN:
            V("metal1", x, y1 - 0.13, YN + 0.3, 0.23)
        if y2 > YP + 0.68:
            V("metal1", x, YP + 0.7, y2 + 0.13, 0.23)
        VIA("via1", x, y1)
        VIA("via1", x, y2)
        V("metal2", x, y1, y2, 0.26)
    # gate contacts onto their lines: local interconnect from the contact to the line, mcon there
    ycn = {"dl": YN + 0.655 + 0.62, "w2": YN + 0.405 + 0.37, "wc": YN + 0.405 + 0.37, "w1": 7.94 + DY_HV1T + 0.33}
    ycp = {"dl": YP + 0.82 - 1.14, "w2": YP + 0.32 - 0.64, "wc": YP + 0.32 - 0.64, "w1": YP + 0.32 - 0.64}
    nets = {"dl": ("bp_b", "bp"), "w2": ("we", "we_b"), "wc": ("we_b", "we"), "w1": ("we", "we_b")}
    for col, x in X_COL.items():
        if col == "dl":
            continue
        nn, pn = nets[col]
        if col != "dl":                                       # small gate contacts' metal1 brought to minimum area
            R("metal1", x - 0.145, ycn[col] - 0.1, x + 0.145, ycn[col] + 0.19)
            R("metal1", x - 0.145, ycp[col] - 0.145, x + 0.145, ycp[col] + 0.145)
        R("locali", x - 0.085, ycn[col], x + 0.085, ycn[col] + 0.25)
        R("locali", x - 0.385, ycn[col] + 0.08, x + 0.085, ycn[col] + 0.25)
        R("locali", x - 0.385, ycn[col] + 0.08, x - 0.215, GL[nn] + 0.085)
        VIA("mcon", x - 0.3, GL[nn])
        R("locali", x - 0.085, ycp[col] - 0.25, x + 0.085, ycp[col])
        R("locali", x - 0.085, ycp[col] - 0.25, x + 0.385, ycp[col] - 0.08)
        R("locali", x + 0.215, GL[pn] - 0.085, x + 0.385, ycp[col] - 0.08)
        VIA("mcon", x + 0.3, GL[pn])
    for net in ("we_b", "we"):                                  # the word's two write strobes (bp, bp_b: only XDL, moved out)
        Hh("metal1", GL_X0[k][net], 9.3, GL[net], 0.23)
    if k == 1:                                                  # word 1: strobes from the west lanes
        for net, lane in (("we", "we1"), ("we_b", "we1_b")):
            VIA("via1", LANE[lane], GL[net])
    else:                                                       # word 2: both on metal1 from the shared part
        for net in ("we_b", "we"):
            V("metal1", X_FEED[net], GL[net] - 0.115, y_hi, 0.23)
    # wires above the PMOS row (metal2) and the PMOS terminals up to them (metal1)
    for x, net in ((xw2 + 0.22, "wm"), (xwc - 0.22, "wm"), (xw1 - 0.645, "wm"), (xw2 - 0.22, "drn")):
        V("metal1", x, YP + 0.9, TRK[net] + 0.13, 0.23)
        VIA("via1", x, TRK[net])
    VIA("via1", xd + 0.395, TRK["line"])                        # the line wire's west end (word 1: bw1's jumper lands here)
    V("metal1", xd + 0.395, TRK["line"] - 0.2, TRK["line"] + 0.13, 0.23)
    Hh("metal2", xw2 + 0.22, xw1 - 0.645, TRK["wm"])
    Hh("metal2", xw2 - 0.22, X_DRN, TRK["drn"])
    Hh("metal2", 3.3, X_LINE, TRK["line"])
    V("metal1", xwc + 0.22, YP + 0.9, 13.75, 0.23)               # REF: XWC's east terminal up to the plate's tab
    # sg: XW1's east terminal down and over to the follower's gates, and up to the capacitor's via
    V("metal1", xw1 + 0.645, 6.85, 7.7, 0.23)
    Hh("metal1", xw1 + 0.645 - 0.115, X_SG + 0.115, 6.85, 0.23)
    V("metal1", xw1 + 0.645, YP + 0.9, 13.9, 0.23)
    Hh("metal1", xw1 + 0.645 - 0.115, X_PAD + 0.13, 13.9, 0.26)
    for name, (x, y, lay) in {"sg": (X_SG, CY, "metal1"), "wm": ((xw2 + xwc) / 2, TRK["wm"], "metal2"),
                              "drn": (8.0, TRK["drn"], "metal2"), "line": (8.0, TRK["line"], "metal2")}.items():
        c.label(name + str(k) if name != "line" else ("bw1" if k == 1 else "bw2"), lay, x, y + dy)
    # ---- the capacitor: lower plate REF (metal3), upper plate sg (metal4); the stored gate's via above it
    c.mim(CAPM[0], CAPM[1] + dy, CAPM[2], CAPM[3] + dy, plate_ext=(0.14, 0.14, 0.14, 0.14))
    R("metal3", xwc + 0.22 - 0.35, CAPM[3], xwc + 0.22 + 0.35, 13.95)   # the plate's tab north for REF
    VIA("via2", xwc + 0.22, 13.6)
    VIA("via1", xwc + 0.22, 13.6)
    y_pad = CAPM[3] + 1.34 + 0.3
    R("metal4", X_PAD - 0.3, CAPM[3] - 0.5, X_PAD + 0.3, y_pad + 0.3)
    R("metal3", X_PAD - 0.21, y_pad - 0.3, X_PAD + 0.21, y_pad + 0.3)
    c.stack(X_PAD, y_pad + dy, top="metal4", bottom="metal1")
    return dict(y_pad=y_pad)


def wtest():
    c = Cell("pw4_bias_wtest")
    word(c, 1, 0.3, 15.0)
    ends = {"bw1": 13.0, "dac": YN + 0.5, "we1": GL["we"], "we1_b": GL["we_b"], "bp_b": GL["bp_b"], "bp": GL["bp"]}
    for name, x in LANE.items():
        c.v("metal2", x, ends[name], 15.0)
    for x in (X_VDD, X_VSS):
        c.v("metal2", x, 0.5, 15.0)
    for name, x in LANE.items():
        pass
    c.outline(0, 0, W, 15.5)
    return c




# ---------------------------------------------------------------- the block
# west pins (metal1 0.7 x 0.3), as agreed with the chip strand on 2026-11-15 12:10: the three analog lines at the bottom
PINS_W = {"dac": 61.2, "bw1": 62.0, "bw2": 62.8, "bias_prog": 65.2, "e1": 66.0, "write": 66.8, "e2": 67.6}
# the four logic pins' lanes (metal2) down through word 2; a higher pin takes a lane further east, so each pin's metal2
# stub (from x 0.3 over the follower to its lane) crosses no other lane
LANE_TOP = {"bias_prog": 1.33, "e1": 1.77, "write": 2.21, "e2": 2.65}
TURN = {"bias_prog": 51.75, "e1": 52.39, "write": 53.03, "e2": 53.67}    # where each logic lane turns east on metal3
FEED_JOG = {"bp_b": 51.2, "bp": 51.85, "we_b": 52.5, "we": 53.0}        # word 2's strobe feeds (metal1) step onto the lanes
LANE_UP = {"bp_b": 47.2, "bp": 46.45, "we1_b": 45.86, "we1": 47.47}    # tops of the strobe lanes (bp_b, bp: the gates' buses)
LANE_BOT = {"bp_b": 14.85, "bp": 16.6}                                  # bp_b, bp start at word 1's switches' gates
Y_SMID = (14.4, 53.6)
X_REFS = (0.41, 0.73)            # REF: metal3 strip joining the two lower plates along the west edge


def frame_block(c):
    """Both words, the lanes through them, the supply lanes, REF, the pins."""
    word(c, 1, 0.3, Y_SMID[0] + 0.2)
    c.my = MY
    word(c, 2, 0.3, MY - (Y_SMID[1] - 0.2))
    c.my = None
    # supply lanes up the east edge, from the south pins
    c.port("vdd", "metal2", 10.4, 0.0, 10.7, 0.7, use="power")
    c.port("vss", "metal2", 11.2, 0.0, 11.5, 0.7, use="ground")
    c.rect("metal2", 10.4, 0.0, X_VDD + 0.15, 0.9)
    c.v("metal2", X_VDD, 0.5, H - 0.4)
    c.v("metal2", X_VSS, 0.5, H - 0.4)
    # REF: the south pin is part of word 1's lower plate; the two plates joined along the west edge
    c.port("ref", "metal3", 1.85, 0.0, 2.45, 0.7)
    c.rect("metal3", 1.85, 0.0, 2.45, CAPM[1] - 0.1)
    c.rect("metal3", X_REFS[0], CAPM[3], X_REFS[1], MY - CAPM[3])
    # west lanes: dac and bw1 up to their pins; word 1's strobes up to the gates (bp_b, bp on to word 2); logic pins down
    c.v("metal2", LANE["dac"], 20.9, PINS_W["dac"])
    c.v("metal2", LANE["bw1"], 13.45, PINS_W["bw1"])
    for net in ("we1", "we1_b", "bp_b", "bp"):
        y_end = {"we1": GL["we"], "we1_b": GL["we_b"], "bp_b": LANE_BOT["bp_b"], "bp": LANE_BOT["bp"]}[net]
        c.v("metal2", LANE[net], y_end, LANE_UP[net])
    for net, x in LANE_TOP.items():
        c.v("metal2", x, TURN[net], PINS_W[net])
    # bw1 joins word 1's line: metal1 from the lane to the DAC switch's line terminal (its riser, lengthened)
    c.via("via1", LANE["bw1"], 13.45)
    c.h("metal1", LANE["bw1"] - 0.13, X_COL["dl"] + 0.395 + 0.115, 13.45, 0.26)
    c.v("metal1", X_COL["dl"] + 0.395, 12.8, 13.58, 0.23)
    # pins
    for net, y in PINS_W.items():
        c.port(net, "metal1", 0.0, y - 0.15, 0.7, y + 0.15)
    c.rect("metal1", 0.0, PINS_W["dac"] - 0.15, LANE["dac"] + 0.13, PINS_W["dac"] + 0.15)
    c.via("via1", LANE["dac"], PINS_W["dac"])
    c.via("via1", LANE["bw1"], PINS_W["bw1"])
    c.rect("metal1", 0.6, PINS_W["bw2"] - 0.15, 0.98, MY - (CY + 1.29) + 0.115)   # bw2 onto word 2's line stripe
    for net, x in LANE_TOP.items():
        y = PINS_W[net]
        c.via("via1", 0.45, y)
        c.h("metal2", 0.3, x + 0.15, y)


# the shared part, bottom to top, at the circuit strand's sizes of 2026-11-15 afternoon (mirror units NMOS 2/1 and PMOS
# 2/2; each word's DAC-line gate NMOS 4/0.5 and PMOS 8/0.5, drawn here in the middle part, not inside the word)
Y_SW1 = 14.85                      # word 1's read/write switches: NMOS diffusion bottom
Y_PA = 18.8                        # the PMOS mirror: XMP0, XIT1, XIT2 in one row, gates contacted above (one pref bar)
X_PA = {"XMP0": 3.96, "XIT1": 6.25, "XIT2": 9.1}   # terminals x: pref 2.815, vdd 5.105, top1 7.395; vdd 7.955, top2 10.245
                                   # (XMP0's well 0.7 from the resistor's implant)
Y_TGP = (20.81, 22.16, 23.51, 24.86)  # DAC-line gates' PMOS, 4/0.5 lying, two in parallel per word: word 1, 1, 2, 2
Y_TGN = (26.47, 27.82)              # their NMOS 4/0.5 lying: word 1, word 2
X_TG = 5.1                         # lying devices' centre: diffusion x 2.92 .. 6.92, gate contact x 7.24 (P) / 7.22 (N)
X_B2 = 6.0                         # word 2's gate: its read-line terminals joined on metal2, up to metal3
Y_GND = 28.9                       # ground wire across the block, a substrate tap under it
CXA, CYA = 4.0, 37.8               # NMOS mirror column A (n21x6 lying): stripes D0 41.67 (pref) ... D6 33.93 (tail1)
CXB, CYB = 6.8, 38.445             # column B (n21x5 lying): stripes D0 41.67 (tail2) ... S5 35.22
X_AV = {"vss": 3.1, "pref": 3.9, "tail1": 5.5, "tail1_via": 4.5}
X_BV = {"vss": 6.7, "tail2": 7.4}
X_TOP, X_TOP2 = 7.395, 10.245      # top1 (XIT1's drain, down to word 1's switches), top2 (XIT2's drain, up to word 2's)
Y_SW2P, Y_SW2N = 37.6, 40.9        # word 2's switches east of column B: PMOS pair (top2 | line2 | top2), NMOS pair
Y_RES = (14.9, 43.98)              # the 286 kohm strip pair, x 0.4 .. 1.58
Y_VSUP = 44.75                     # supply wire across the block above the mirrors
Y_TOPN = 42.165                    # nref wire: the resistor's nref end and both columns' gates


def smid(c, stage):
    # ---- the reference resistor (two legs in series): R1_0 (west, top) vdd, R1_1 (east, top) nref
    yr = (Y_RES[0] + Y_RES[1]) / 2
    c.dev("rref", "XRREF", 0.99, yr)
    c.h("metal1", 0.575 - 0.125, 1.405 + 0.125, yr - 14.365, 0.29)          # the two legs joined at the bottom
    yrt = yr + 14.365
    c.v("metal1", 1.405, Y_TOPN, yrt, 0.25)
    c.v("metal1", 0.575, yrt, Y_VSUP, 0.25)
    c.h("metal1", 0.45, X_VDD + 0.13, Y_VSUP, 0.26)
    c.via("via1", X_VDD, Y_VSUP)
    # ---- PMOS mirror (2/2): XMP0 (pref | vdd) and XIT1 (vdd | top1) share the source stripe; XIT2 (vdd | top2)
    for inst, x in X_PA.items():
        c.dev("p22t", inst, x, Y_PA)
    c.rect("metal1", 2.7, Y_PA + 1.025, 10.08, Y_PA + 1.255)                # pref: the three gates ...
    c.rect("metal1", 2.7, Y_PA + 0.8, 2.93, Y_PA + 1.04)                   # ... and XMP0's drain
    ysup = Y_SW1 + 2.47
    for x in (5.105, 7.955):                                               # sources down to the supply wire
        c.v("metal1", x, ysup, Y_PA - 1.1, 0.23)
    c.h("metal1", 2.6, X_VDD + 0.13, ysup, 0.23)
    c.via("via1", X_VDD, ysup)
    c.tap_strip("nsubdiff", 2.7, ysup - 0.37, 6.3, ysup)                   # the well tap, on the supply wire
    c.via("mcon", 4.0, ysup - 0.185)
    c.rect("nwell", 2.5, ysup - 0.55, 7.35, Y_PA)                          # wells 0.7 from the resistor's implant (x 1.78)
    c.rect("nwell", 2.5, Y_PA + 0.7, 7.6, Y_TGP[3] + 0.72)                 # one well under the mirror and the gates' PMOS
    c.via("via1", X_AV["pref"], Y_PA + 1.14)                               # pref up to column A's top stripe (XMN0's drain)
    # ---- the DAC-line gates: lying devices, gate contact at the east end; top stripe = dac, bottom stripe = read line
    for i, y in enumerate(Y_TGP):
        c.dev("tgp4l", f"XTG{1 + i // 2}P{i % 2}", X_TG, y, "90")
    for i, y in enumerate(Y_TGN):
        c.dev("tgn4l", f"XTG{i + 1}N", X_TG, y, "90")
    for k, y in [(1, Y_TGP[0]), (1, Y_TGP[1]), (2, Y_TGP[2]), (2, Y_TGP[3]), (1, Y_TGN[0]), (2, Y_TGN[1])]:
        c.h("metal1", LANE["dac"] - 0.13, X_TG - 1.9, y + 0.395, 0.23)       # dac: west on metal1 under the lanes
        c.via("via1", LANE["dac"], y + 0.395)
        if k == 1:                                                          # word 1's read line = the bw1 lane
            c.h("metal1", LANE["bw1"] - 0.13, X_TG - 1.9, y - 0.395, 0.23)
            c.via("via1", LANE["bw1"], y - 0.395)
        else:                                                               # word 2's: joined on metal2, metal3 east
            c.via("via1", X_B2, y - 0.395)
    c.v("metal2", X_B2, Y_TGP[2] - 0.395, Y_TGN[1] - 0.395)
    for y in Y_TGP:                                                         # PMOS gates: bp
        c.via("via1", X_TG + 2.14, y)
    c.v("metal2", X_TG + 2.14, Y_TGP[0], Y_TGP[3])
    for y in Y_TGN:                                                         # NMOS gates: bp_b
        c.via("via1", X_TG + 2.12, y)
    c.v("metal2", X_TG + 2.12, Y_TGN[0], Y_TGN[1])
    # ---- ground wire and substrate tap between the gates and the NMOS mirror
    c.h("metal1", X_AV["vss"] - 0.13, X_VSS + 0.13, Y_GND, 0.23)
    for x in (X_AV["vss"], X_BV["vss"], X_VSS):
        c.via("via1", x, Y_GND)
    c.tap_strip("psubdiff", 3.4, Y_GND - 0.16, 5.2, Y_GND + 0.16)
    for x in (3.8, 4.6):
        c.via("mcon", x, Y_GND)
    # ---- NMOS mirror (2/1): column A = XMN0, XMREF x4, XIS1; column B = XIS2, XMREF x4; lying, gates at the east edge
    c.dev("n21x6", "XNA", CXA, CYA, "90")
    c.dev("n21x5", "XNB", CXB, CYB, "90")
    ya = {n: CYA + 3.87 - 1.29 * k for k, n in enumerate(("D0", "S1", "D2", "S3", "D4", "S5", "D6"))}
    yb = {n: CYB + 3.225 - 1.29 * k for k, n in enumerate(("D0", "S1", "D2", "S3", "D4", "S5"))}
    for k in ("S1", "S3", "S5"):
        c.via("via1", X_AV["vss"], ya[k])
        c.via("via1", X_BV["vss"], yb[k])
    c.v("metal2", X_AV["vss"], Y_SW1 + 0.5, ya["S1"])
    c.v("metal2", X_BV["vss"], Y_GND, yb["S1"])
    for k in ("D2", "D4"):                                                  # the diode units: drains onto the gate column
        c.rect("metal1", CXA + 0.8, ya[k] - 0.115, CXA + 1.05, ya[k] + 0.115)
        c.rect("metal1", CXB + 0.8, yb[k] - 0.115, CXB + 1.05, yb[k] + 0.115)
    c.v("metal1", CXA + 1.12, ya["D6"] + 0.4, Y_TOPN, 0.23)               # gate columns up to the nref wire
    c.v("metal1", CXB + 1.12, yb["S5"] + 0.4, Y_TOPN, 0.23)
    c.h("metal1", 1.28, CXB + 1.12 + 0.115, Y_TOPN, 0.26)
    c.v("metal2", X_AV["pref"], Y_PA + 1.14, ya["D0"])                     # pref
    c.via("via1", X_AV["pref"], ya["D0"])
    c.via("via1", X_AV["tail1_via"], ya["D6"])                             # tail1: column A's bottom stripe (XIS1's drain)
    c.v("metal2", X_AV["tail1"], Y_SW1 + 0.5, ya["D6"] - 0.43)
    c.h("metal2", X_AV["tail1_via"], X_AV["tail1"], ya["D6"] - 0.43)
    c.v("metal2", X_AV["tail1_via"], ya["D6"] - 0.43, ya["D6"])
    c.via("via1", X_BV["tail2"], yb["D0"])                                 # tail2: column B's top stripe, over to word 2's NMOS
    c.v("metal2", X_BV["tail2"], Y_SW2N - 0.95, yb["D0"])
    c.h("metal2", X_BV["tail2"], 10.25, Y_SW2N - 0.95)
    # ---- word 1's switches: XRD1 (vss | drn1) and XSS1 (drn1 | tail1); XTS1 (top1 | line1), XTW1 (line1 | top1)
    yn = Y_SW1 + 0.655
    c.dev("n105t", "W1_XRD", X_AV["vss"] + 0.395, yn)
    c.dev("n105t", "W1_XSS", X_AV["tail1"] - 0.395, yn)
    xr, xs = X_AV["vss"] + 0.395, X_AV["tail1"] - 0.395
    c.via("via1", X_AV["vss"], Y_SW1 + 0.5)                                # XRD1's source on the ground vertical
    c.via("via1", X_AV["tail1"], Y_SW1 + 0.5)                              # XSS1's source on tail1
    for x in (xr + 0.395, xs - 0.395):                                     # drn1: the two inner terminals, down to the drain wire
        c.v("metal1", x, Y_SW1 - 0.4, Y_SW1 + 0.3, 0.23)
    ydw = Y_SW1 - 0.4
    c.h("metal1", xr + 0.395 - 0.115, X_DRN + 0.115, ydw, 0.23)
    c.v("metal1", X_DRN, TRK["drn"], ydw, 0.23)
    c.via("via1", X_DRN, TRK["drn"])
    yp = Y_SW1 + 0.32 + 0.3                                                # PMOS (contacts below): XTS1 at 8.2, XTW1 at 9.8 flipped
    c.dev("p105b", "W1_XTS", 8.2, yp)
    c.dev("p105b", "W1_XTW", 9.8, yp, "h")
    c.rect("nwell", 7.3, Y_SW1 - 0.3, 10.7, Y_PA - 1.4)
    # line1: the two inner terminals (8.595, 9.405) up to a metal2 wire; word 1's line vertical comes up to it
    yl = yp + 0.68 + 0.25
    for x in (8.595, 9.405):
        c.v("metal1", x, yp + 0.4, yl + 0.13, 0.23)
        c.via("via1", x, yl)
    c.h("metal2", 8.595, X_LINE, yl)
    c.v("metal2", X_LINE, TRK["line"], yl)
    # top1: the two outer terminals (7.805, 10.195) and XIT1's drain (X_TOP)
    yt = yl + 0.5                                                          # top1 0.175 under the supply wire
    for x in (7.805, 10.195):
        c.v("metal1", x, yp + 0.4, yt + 0.13, 0.23)
        c.via("via1", x, yt)
    c.h("metal2", X_TOP, 10.195, yt)
    c.rect("metal2", X_TOP - 0.15, yt - 0.15, 7.95, yt + 0.35)              # no notch between XIT1's riser and XTS1's via
    c.v("metal2", X_TOP, yt, Y_PA - 0.5)
    c.via("via1", X_TOP, Y_PA - 0.5)
    c.via("via1", X_TOP2, Y_PA - 0.5)                                      # top2: XIT2's drain, up to word 2's PMOS pair
    c.v("metal2", X_TOP2, Y_PA - 0.5, Y_SW2P - 1.05)
    if stage < 2:
        return
    stage2(c)


# ---------------------------------------------------------------- stage 2: gates, pull-downs, word 2's switches
ROW_C, ROW_B = 45.26, 50.70          # Row C (upright): its ground line; Row B (upside down): its ground line, at the top
PY_C, PY_B = ROW_C + 1.19, ROW_B - 1.19   # where each row's pins are contacted
PD_X, PD_Y = 7.3, (51.76, 52.96)   # (their N+ implant 0.38 above the gate row's)       # the two pull-downs, lying, above Row B (XPD4 bias_prog, XPD5 write upside down)
M4 = {"wb2": 5.55, "wb2_b": 7.8, "drn2": 10.4, "line2": 11.2}   # long metal4 verticals to word 2's switches
YP2 = (23.25, 25.3)                  # word 2's two PMOS, one above the other, west of XIT2 (x 6.28)
YN2 = 29.16                          # word 2's NMOS pair, under column B


def rel_c(r):
    return ROW_C + r


def rel_b(r):
    return ROW_B - r


def std(c, cell, inst, x, y, o=""):
    """A standard cell with its origin (the ground line's centre, at its west edge) at (x, y); o "v" = upside down."""
    c.t.box(x, y, x, y)
    c.t.add(f"getcell sky130_fd_sc_hd__{cell}{(' ' + o) if o else ''} child 0 0")
    c.t.add(f"identify {inst}")


def mcon(c, x, y):
    c.rect("mcon", x - 0.085, y - 0.085, x + 0.085, y + 0.085)


def pin(c, x, y):
    """A standard-cell pin (or any local interconnect) up to metal2: mcon and via1 on one point under a metal1 pad
    0.26 x 0.34 and a metal2 pad 0.3 x 0.36 (the chip strand's decoder pattern)."""
    mcon(c, x, y)
    c.rect("via1", x - 0.13, y - 0.13, x + 0.13, y + 0.13)
    c.rect("metal1", x - 0.13, y - 0.17, x + 0.13, y + 0.17)
    c.rect("metal2", x - 0.15, y - 0.18, x + 0.15, y + 0.18)


def v2(c, x, y):
    """metal2 to metal3 at a point: via2, a metal2 pad 0.3 x 0.4 and a metal3 pad 0.34 square."""
    c.via("via2", x, y)
    c.rect("metal2", x - 0.15, y - 0.2, x + 0.15, y + 0.2)
    c.rect("metal3", x - 0.17, y - 0.17, x + 0.17, y + 0.17)


def v3(c, x, y):
    """metal3 to metal4 at a point."""
    c.via("via3", x, y)
    c.rect("metal3", x - 0.17, y - 0.17, x + 0.17, y + 0.17)
    c.rect("metal4", x - 0.2, y - 0.2, x + 0.2, y + 0.2)


def m3(c, x1, x2, y):
    """A metal3 track 0.34 wide reaching 0.17 past both end points."""
    c.rect("metal3", min(x1, x2) - 0.17, y - 0.17, max(x1, x2) + 0.17, y + 0.17)


def stage2(c):
    yn, yp = Y_SW1 + 0.655, Y_SW1 + 0.32 + 0.3                  # word 1's switches (as in smid)
    ybot = CYA - 7.015 - 0.35
    yb_d0 = CYA + 7.015 - 5.87 + 5.725                          # column B's top stripe: XIS2's drain = tail2
    # ---- word 1's switches: gates from the west lanes on metal3
    ygs = yp - 0.64 + 0.02                                      # XTS1, XTW1: gate contacts below (via 0.155 above the drain wire)
    c.via("via1", 8.2, ygs)
    v2(c, 8.2, ygs)
    m3(c, LANE["bp_b"], 8.2, ygs)
    v2(c, LANE["bp_b"], ygs)
    c.via("via1", 9.8, ygs)
    c.v("metal2", 9.8, ygs, 15.5)
    v2(c, 9.8, 15.5)
    m3(c, LANE["we1_b"], 9.8, 15.5)
    v2(c, LANE["we1_b"], 15.5)
    ygt = yn + 0.62                                             # XRD1, XSS1: gate contacts above; local interconnect out
    c.rect("locali", 3.415, ygt - 0.085, 3.885, 16.685)
    pin(c, 3.8, 16.6)
    v2(c, 3.8, 16.6)
    m3(c, LANE["bp"], 3.8, 16.6)
    v2(c, LANE["bp"], 16.6)
    c.rect("locali", 4.615, ygt - 0.085, 5.19, 16.685)
    pin(c, 4.7, 16.6)
    c.v("metal2", 4.7, 16.6, 17.25)
    v2(c, 4.7, 17.25)
    m3(c, LANE["we1"], 4.7, 17.25)
    v2(c, LANE["we1"], 17.25)
    # ---- the DAC-line gates' gate lines (bp to the PMOS, bp_b to the NMOS) and word 2's read line, on metal3
    yg = (Y_TGP[1] + Y_TGP[2]) / 2
    v2(c, X_TG + 2.14, yg)
    m3(c, LANE["bp"], X_TG + 2.14, yg)
    v2(c, LANE["bp"], yg)
    yg = (Y_TGN[0] + Y_TGN[1]) / 2
    v2(c, X_TG + 2.12, yg)
    m3(c, LANE["bp_b"], X_TG + 2.12, yg)
    v2(c, LANE["bp_b"], yg)
    yg = (Y_TGP[3] + Y_TGN[0]) / 2
    v2(c, X_B2, yg)
    m3(c, X_B2, M4["line2"], yg)
    v3(c, M4["line2"], yg)
    y_l2_bottom = yg
    # ---- word 2's switches east of column B. NMOS pair: vss | bp | drn2 | wb2 | tail2, gates above
    c.dev("n105t", "W2_XRD", 9.065, Y_SW2N)
    c.dev("n105t", "W2_XSS", 9.855, Y_SW2N)
    yv = Y_SW2N - 1.4
    c.v("metal1", 8.67, yv, Y_SW2N - 0.5, 0.23)                  # vss: XRD's outer terminal down, east to the ground lane
    c.h("metal1", 8.67 - 0.115, X_VSS + 0.13, yv, 0.23)
    c.via("via1", X_VSS, yv)
    c.v("metal1", 10.25, Y_SW2N - 1.08, Y_SW2N - 0.5, 0.23)        # tail2: XSS's outer terminal down to its metal2 from column B
    c.via("via1", 10.25, Y_SW2N - 0.95)
    c.stack(9.46, Y_SW2N - 0.3, top="metal3", bottom="metal1")   # drn2: the shared terminal, metal3 east to its metal4
    m3(c, 9.46, M4["drn2"], Y_SW2N - 0.3)
    v3(c, M4["drn2"], Y_SW2N - 0.3)
    ygn = Y_SW2N + 0.62
    c.stack(9.065, ygn, top="metal3", bottom="metal1")           # XRD's gate: bp, from its lane
    m3(c, LANE["bp"], 9.065, ygn)
    v2(c, LANE["bp"], ygn)
    c.via("via1", 9.855, ygn)                                    # XSS's gate: wb2, up to metal3 and its metal4
    c.v("metal2", 9.855, ygn, ygn + 0.68)
    v2(c, 9.855, ygn + 0.68)
    m3(c, M4["wb2"], 9.855, ygn + 0.68)
    v3(c, M4["wb2"], ygn + 0.68)
    y_wb2_bottom = ygn + 0.68
    # PMOS pair: top2 | bp_b | line2 | wb2_b | top2, gates above, the outer terminals joined below onto top2's riser
    c.dev("p105t", "W2_XTS", 9.065, Y_SW2P)
    c.dev("p105t", "W2_XTW", 9.855, Y_SW2P)
    c.rect("nwell", 8.3, Y_SW2P - 1.2, 11.2, Y_SW2P + 0.85)
    c.tap_strip("nsubdiff", 10.7, Y_SW2P - 0.6, 11.0, Y_SW2P + 0.3)  # its well tap under the supply lane
    c.via("mcon", 10.85, Y_SW2P - 0.15)
    c.via("via1", 10.85, Y_SW2P - 0.15)
    yb2 = Y_SW2P - 1.05
    for x in (8.67, 10.25):
        c.v("metal1", x, yb2, Y_SW2P - 0.6, 0.23)
    c.h("metal1", 8.67 - 0.115, 10.25 + 0.115, yb2, 0.23)
    c.via("via1", X_TOP2, yb2)
    c.stack(9.46, Y_SW2P - 0.2, top="metal3", bottom="metal1")   # line2: the shared terminal, metal3 east to its metal4
    m3(c, 9.46, M4["line2"], Y_SW2P - 0.2)
    v3(c, M4["line2"], Y_SW2P - 0.2)
    ygp = Y_SW2P + 0.64
    c.stack(9.065, ygp, top="metal3", bottom="metal1")           # XTS's gate: bp_b, from its lane
    m3(c, LANE["bp_b"], 9.065, ygp)
    v2(c, LANE["bp_b"], ygp)
    c.via("via1", 9.855, ygp)                                    # XTW's gate: wb2_b, from its metal4
    c.v("metal2", 9.855, ygp, ygp + 0.66)
    v2(c, 9.855, ygp + 0.66)
    m3(c, M4["wb2_b"], 9.855, ygp + 0.66)
    v3(c, M4["wb2_b"], ygp + 0.66)
    y_wb2b_bottom = ygp + 0.66
    # ---- the two rows of standard cells: Row C upright (ground at the bottom), Row B upside down (shared supply)
    for cell, inst, x in (("inv_1", "XWI1", 3.02), ("nor3_1", "XB1", 4.40), ("inv_1", "XIE1", 6.24),
                          ("tapvpwrvgnd_1", "TAPC", 7.62), ("inv_1", "XBP", 9.46)):
        std(c, cell, inst, x, ROW_C)
    for cell, inst, x in (("inv_1", "XIE2", 3.02), ("nor3_1", "XB2", 4.40), ("inv_1", "XWI2", 6.24),
                          ("inv_1", "XIWB", 7.62), ("inv_1", "XBPB", 9.00)):
        std(c, cell, inst, x, ROW_B, "v")
    c.rect("metal1", 2.95, ROW_C - 0.24, X_VSS + 0.13, ROW_C + 0.24)          # the rails, out to the supply lanes
    c.via("via1", X_VSS, ROW_C)
    c.rect("metal1", 2.95, ROW_C + 2.48, X_VDD + 0.13, ROW_C + 2.96)
    c.via("via1", X_VDD, ROW_C + 2.72)
    c.rect("metal1", 2.95, ROW_B - 0.24, X_VSS + 0.13, ROW_B + 0.24)
    c.via("via1", X_VSS, ROW_B)
    c.rect("nwell", 2.83, rel_c(1.305), 11.03, rel_b(1.305))                 # one n-well under both rows' PMOS
    # Row C: e1 -> XIE1; ne1; we1 (XB1 -> XWI1 -> lane); we1_b (XWI1 -> lane); nwrite and bias_prog columns; XBP
    pin(c, 6.685, PY_C)
    y = rel_c(1.83)
    mcon(c, 7.145, y)
    mcon(c, 5.095, y)
    c.h("metal1", 5.095 - 0.145, 7.145 + 0.145, y, 0.23)
    y = rel_c(2.21)
    mcon(c, 5.485, y)
    c.h("metal1", LANE["we1"] - 0.13, 5.485 + 0.145, y, 0.23)
    mcon(c, 3.465, PY_C)
    c.v("metal1", 3.465, PY_C - 0.145, y + 0.115, 0.23)
    c.via("via1", LANE["we1"], y)
    y = rel_c(0.6)
    mcon(c, 3.925, y)
    c.h("metal1", LANE["we1_b"] - 0.13, 3.925 + 0.145, y, 0.23)
    c.via("via1", LANE["we1_b"], y)
    for x in (6.015, 4.635, 9.905, 10.365):
        pin(c, x, PY_C)
    v2(c, 10.365, PY_C)                                          # bp: XBP's output to its lane
    m3(c, LANE["bp"], 10.365, PY_C)
    v2(c, LANE["bp"], PY_C)
    # Row B: e2 -> XIE2; ne2; wb2 (XB2 -> XWI2, lane, metal4); wb2_b; nwrite; bias_prog; write; bp_b
    pin(c, 3.465, PY_B)
    y = rel_b(1.83)
    mcon(c, 3.925, y)
    mcon(c, 5.095, y)
    c.h("metal1", 3.925 - 0.145, 5.095 + 0.145, y, 0.23)
    y = rel_b(2.21)
    mcon(c, 5.485, y)
    c.h("metal1", LANE["we1"] - 0.13, 6.685 + 0.115, y, 0.23)
    mcon(c, 6.685, PY_B)
    c.v("metal1", 6.685, y - 0.115, PY_B + 0.145, 0.23)
    c.via("via1", LANE["we1"], y)                                # onto word 2's wb2 lane (x 2.65, down from the junction)
    c.stack(M4["wb2"], y, top="metal4", bottom="metal1")
    c.rect("metal3", M4["wb2"] - 0.17, y - 0.55, M4["wb2"] + 0.17, y + 0.17)
    c.rect("metal4", M4["wb2"] - 0.2, y - 0.2, M4["wb2"] + 0.2, y + 0.2)
    pin(c, 7.145, PY_B)                                          # wb2_b: XWI2 up to its bus (lane 2.21 and metal4)
    c.v("metal2", 7.145, PY_B, 50.0)
    v2(c, 7.145, 50.0)
    m3(c, LANE["we1_b"], M4["wb2_b"], 50.0)
    v2(c, LANE["we1_b"], 50.0)
    v3(c, M4["wb2_b"], 50.0)
    pin(c, 8.525, PY_B)                                          # nwrite: XIWB down to its bus, over to XB2/XB1's column
    c.v("metal2", 8.525, PY_B, 49.15)
    v2(c, 8.525, 49.15)
    pin(c, 6.015, PY_B)
    c.v("metal2", 6.015, PY_C, PY_B)
    v2(c, 6.015, 49.15)
    m3(c, 6.015, 8.525, 49.15)
    pin(c, 4.635, PY_B)                                          # bias_prog: XB2 (column), XBPB up to its bus
    pin(c, 9.445, PY_B)
    c.v("metal2", 9.445, PY_B, 50.65)
    v2(c, 9.445, 50.65)
    v2(c, 4.635, 50.65)
    m3(c, 4.635, 9.445, 50.65)
    pin(c, 8.065, PY_B)                                          # write: XIWB's input (its drop from the junction)
    pin(c, 9.905, PY_B)                                          # bp_b: XBPB down to XBP, and to its lane
    c.v("metal2", 9.905, PY_C, PY_B)
    v2(c, 9.905, 47.2)
    m3(c, LANE["bp_b"], 9.905, 47.2)
    v2(c, LANE["bp_b"], 47.2)
    # ---- the pull-downs (5 V NMOS 0.42/8, gate on the supply), lying above Row B
    c.dev("hv8t", "XPD4", PD_X, PD_Y[0])
    c.dev("hv8t", "XPD5", PD_X, PD_Y[1], "v")
    c.rect("metal1", PD_X - 3.98, PD_Y[0] + 0.215, PD_X + 3.98, PD_Y[1] - 0.215)   # both gates, one strip: vdd
    c.via("via1", X_VDD, (PD_Y[0] + PD_Y[1]) / 2)
    yd4, yd5 = PD_Y[0] - 0.155, PD_Y[1] + 0.155
    for yd in (yd4, yd5):
        c.via("via1", X_VSS, yd)                                 # sources (east ends) on the ground lane
    c.h("metal1", PD_X - 4.26, 4.635 + 0.13, yd4, 0.23)         # XPD4's drain to the bias_prog column
    c.via("via1", 4.635, yd4)
    c.h("metal1", PD_X - 4.26, 4.05 + 0.13, yd5, 0.23)          # XPD5's drain to its write drop
    c.via("via1", 4.05, yd5)
    c.v("metal2", 4.05, yd5, TURN["write"])
    # ---- the junction under word 2: its four strobe feeds step onto the west lanes; the logic lanes turn east
    for net, ln in (("we_b", "we1_b"), ("we", "we1")):
        y, xf, xl = FEED_JOG[net], X_FEED[net], LANE[ln]
        c.v("metal1", xf, y - 0.115, 53.4, 0.23)
        c.rect("metal1", xf - 0.115, y - 0.13, xl + 0.13, y + 0.13)
        c.via("via1", xl, y)
    c.v("metal2", LANE["we1_b"], 50.0, FEED_JOG["we_b"])         # word 2's wb2_b lane
    c.v("metal2", LANE["we1"], rel_b(2.21), FEED_JOG["we"])      # word 2's wb2 lane
    drops = {"bias_prog": [(4.635, PY_C)], "e1": [(6.685, PY_C)], "write": [(4.05, None), (8.065, PY_B)],
             "e2": [(3.465, PY_B)]}
    for net, x in LANE_TOP.items():
        y = TURN[net]
        v2(c, x, y)
        m3(c, x, max(xd for xd, _ in drops[net]), y)
        for xd, ybtm in drops[net]:
            v2(c, xd, y)
            if ybtm is not None:
                c.v("metal2", xd, ybtm, y)
    # ---- word 2's drain and line down to its switches on metal4
    yd = MY - TRK["drn"]
    c.via("via1", X_DRN, yd)                                     # the drain: on down on metal1 at x 9.9 (as word 1's)
    c.v("metal1", X_DRN, 53.3 - 0.115, yd, 0.23)
    c.h("metal1", X_DRN - 0.115, M4["drn2"] + 0.13, 53.3, 0.23)
    c.stack(M4["drn2"], 53.3, top="metal4", bottom="metal1")
    c.rect("metal3", M4["drn2"] - 0.17, 53.3 - 0.36, M4["drn2"] + 0.17, 53.3 + 0.36)
    c.v("metal2", X_LINE, 54.2, MY - TRK["line"])                # the line: its vertical on down, metal3 east
    v2(c, X_LINE, 54.2)
    m3(c, X_LINE, M4["line2"], 54.2)
    v3(c, M4["line2"], 54.2)
    c.v("metal4", M4["drn2"], Y_SW2N - 0.3, 53.3, 0.4)
    c.v("metal4", M4["line2"], y_l2_bottom, 54.2, 0.4)
    c.v("metal4", M4["wb2"], y_wb2_bottom, rel_b(2.21), 0.4)
    c.v("metal4", M4["wb2_b"], y_wb2b_bottom, 50.0, 0.4)
    for name, (x, y, lay) in {"wb1": (LANE["we1"], 30.0, "metal2"), "wb1_b": (LANE["we1_b"], 30.0, "metal2"),
                              "bp": (LANE["bp"], 40.0, "metal2"), "bp_b": (LANE["bp_b"], 40.0, "metal2"),
                              "wb2": (M4["wb2"], 45.0, "metal4"), "wb2_b": (M4["wb2_b"], 45.0, "metal4"),
                              "drn2": (M4["drn2"], 45.0, "metal4"), "tail2": (X_BV["tail2"], 40.8, "metal2"),
                              "nwrite": (6.015, 47.5, "metal2")}.items():
        c.label(name, lay, x, y)


def block(stage=9):
    c = Cell("pw4_bias")
    frame_block(c)
    smid(c, stage)
    c.outline(0, 0, W, H)
    c.info["edge_note"] = ("pins reach the outline at their rectangles only (west: seven metal1 pins; south: ref on metal3, "
                           "vdd and vss on metal2); elsewhere the cell's own metal stays inside the outline")
    c.info["interface_note"] = (
        "Uses metal1 to metal4 across the whole outline: no chip wire may cross it. The two capacitors' lower plates (REF, "
        "metal3) cover x 0.41 .. 11.68 at y 1.115 .. 12.385 and 55.615 .. 66.885, joined by a metal3 strip x 0.41 .. 0.73 "
        "along the west edge; their upper plates (the stored gates, metal4) x 0.745 .. 11.345 at y 1.45 .. 12.05 and "
        "55.95 .. 66.55. Keep the chip's switching wires at least 1 um from the outline beside the two plates (y 0 .. 14.2 "
        "and 53.8 .. 68). Stored gates in the extraction: sg1 (word 1), sg2 (word 2).")
    return c


CELLS_B = {"word": wtest, "block": block}


if __name__ == "__main__":
    for what in sys.argv[1:] or ["block"]:
        build(CELLS_B[what](), extract=True)
