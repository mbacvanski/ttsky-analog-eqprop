"""Place and route aj_core: variant AJ's core auto-zero amplifier (cd_signal_az DRIVE=0.5, hold 0.5 pF; U1/U3).

Ports (cd_signal_az order): plus minus out az az_b ref vdd vss.  Cell 44.73 x 21.2 um.

What differs from az_core (amp_layout.py), and why:
  * half the output stage: one 8-finger MNLOAD row and a 4-finger MPOUT;
  * hold capacitor 0.5 pF: six 6.29 um units;
  * both capacitor arrays are hand-drawn units (cell.MimUnit) on shared plates at the 0.84 um minimum spacing,
    side by side: hold 2 x 3 on the `ref` plate over the left 13.9 um (the switches and the hold node's
    wiring lie under it, so the hold node couples to ref and not to the output), Miller 3 x 2 on the `out`
    plate over the right 29.4 um. The strip above the Miller plate (y > 20.4) holds the two top-plate via
    stacks (comp, nul), which must stay 1.34 um from every capacitor;
  * VDD is a metal2 rail along the whole bottom edge (1.5 um; 2.45 um where the PMOS sources drop onto it with
    two vias each) instead of a 0.3 um line, VSS a 1.0 um metal2 line on the right edge.

Floorplan, left to right (x right, y up, um):
  switches   XSA/XSN/XSH as in az_core (same relative placement), pins enter from the left edge
  middle     PMOS mirror + output row on the VDD rail, input pair above it (A B B A A B B A)
  right      MNLOAD row, MNBIAS/MNTAIL/MATAIL row above it (gates aligned, metal1 jumpers), then the
             auxiliary pair and RZERO
  top        RBIAS (220 kohm with its grounded dummy strip), lying across the cell. In aj_core1p: 286 kohm as two
             143 kohm strips side by side at the right end of that row, joined at their left ends; the lower
             strip's right end is the bias node (where the 220 kohm strip ended), the upper strip's right end VDD,
             which comes up the left edge and along the top of the cell on metal1 (y 23.15 to 23.45)
Routing: device stripes metal1 (vertical), bars metal2, as in az_core. Nets that must cross a metal2 bar use
metal1 for the crossing (tail, comp, the plus riser, the left VDD link to RBIAS).

aj_core1p (build(t, "aj_core1p")): the same amplifier with a 1 pF hold capacitor and both capacitors drawn as
single rectangles (20.52 x 24.01 um each), side by side: hold on the `ref` plate over the left half, Miller on
the `out` plate over the right half. Everything below metal3 is aj_core's up to y 19.5, except where a net meets
its plate. The 3.18 um between the two capacitors holds the two top-plate via stacks (each 1.34 um from both
capacitors), the metal4 guard on ref beside the hold top plate, and the via2 margins of both bottom plates.
`out` reaches its plate at the plate's left margin (MPOUT's drain bar and the hold switch's bar), `ref` at its
right margin; comp runs on metal2 above the ref line to its stack.
"""
from __future__ import annotations

from cell import MimUnit, Mos, Res
from geom import Tcl, snap

W, H = 44.73, 21.2
DX, DY = -18.95, -15.3          # az_core's switch-block coordinates -> this cell
W2 = 0.30

MIL_S, HOLD_S = 8.97, 6.29
HOLD_X = [3.445, 10.575]
HOLD_Y = [3.445, 10.575, 17.705]
MIL_X = [20.415, 30.225, 40.035]
MIL_Y = [4.785, 14.595]
REF_PLATE = (0.0, 0.0, 14.5, 20.99)           # hold bottom plate, over the switches and the hold node's wiring
OUT_PLATE = (15.26, 0.0, 44.66, 19.22)        # Miller bottom plate, over the output devices

# aj_core1p: hold 1 pF and Miller 1 pF, one rectangle each (x1, y1, x2, y2 of the capacitor layer)
C1P_W, C1P_L = 20.52, 24.01
HOLD1P = (0.30, 0.30, 0.30 + C1P_W, 0.30 + C1P_L)                        # on the ref plate, left half
MIL1P = (44.52 - C1P_W, 0.30, 44.52, 0.30 + C1P_L)                       # on the out plate, right half
H1P = HOLD1P[3] + 0.14
REF1P = (0.0, 0.0, HOLD1P[2] + 0.75, H1P)
OUT1P = (MIL1P[0] - 0.89, 0.0, 44.66, H1P)
STACK1P_X, NUL1P_Y, COMP1P_Y = HOLD1P[2] + 1.59, 20.65, 21.60            # the two top-plate via stacks, in the gap
YVT, XVD = 23.30, 42.05                                                  # aj_core1p: VDD line along the top, its drop to RBIAS


def build(t: Tcl, cell: str = "aj_core") -> dict:
    big = cell == "aj_core1p"
    if big:
        MimUnit.define(t, "aj_cmil1p_u", C1P_W, C1P_L)
        MimUnit.define(t, "aj_caz1p_u", C1P_W, C1P_L)
    else:
        MimUnit.define(t, "aj_cmil_u", MIL_S)
        MimUnit.define(t, "aj_caz_u", HOLD_S)
    t.add(f"load {cell}")
    d = {}
    REF_PLATE, OUT_PLATE = (REF1P, OUT1P) if big else (globals()["REF_PLATE"], globals()["OUT_PLATE"])

    # ---------------- MIM ----------------
    if big:
        mid = lambda r: ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)   # noqa: E731
        mil = [MimUnit(t, "aj_cmil1p_u", "XCMILLER", *mid(MIL1P), C1P_W, C1P_L)]
        hold = [MimUnit(t, "aj_caz1p_u", "XCAZ", *mid(HOLD1P), C1P_W, C1P_L)]
    else:
        mil = [MimUnit(t, "aj_cmil_u", f"XCMIL_{r}{c}", x, y, MIL_S) for r, y in enumerate(MIL_Y) for c, x in enumerate(MIL_X)]
        hold = [MimUnit(t, "aj_caz_u", f"XCAZ_{r}{c}", x, y, HOLD_S) for r, y in enumerate(HOLD_Y) for c, x in enumerate(HOLD_X)]
    t.paint("metal3", *OUT_PLATE)
    t.paint("metal3", *REF_PLATE)
    # metal4 guard on ref along the edge of the hold top plates (the hold node), facing the out plate
    xg4 = REF_PLATE[2] - (0.34 if big else 0.35)    # 0.405 um from the hold top plate
    if big:                                      # broken where the hold node's metal4 crosses to its stack
        t.paint("metal4", xg4 - 0.2, 0.5, xg4 + 0.2, NUL1P_Y - 0.65)
        t.paint("metal4", xg4 - 0.2, NUL1P_Y + 0.65, xg4 + 0.2, H1P - 0.5)
        t.via("via3", xg4, 22.6)
    else:
        t.paint("metal4", xg4 - 0.2, 0.5, xg4 + 0.2, hold[-1].top_m4[3] - 0.75)
    for y in (2.0, 6.0, 10.0, 14.0, 18.0):
        t.via("via3", xg4, y)
    # top plates: one metal4 sheet per array, covering every unit's contact and the gaps between units
    if not big:                                  # (each rectangle of aj_core1p carries its own sheet)
        t.paint("metal4", mil[0].top_m4[0], mil[0].top_m4[1], mil[-1].top_m4[2], mil[-1].top_m4[3])
        t.paint("metal4", hold[0].top_m4[0], hold[0].top_m4[1], hold[-1].top_m4[2], hold[-1].top_m4[3])
    d.update(mil=mil, hold=hold)

    # ---------------- FEOL placement ----------------
    ypm = 4.2
    pm = d["pm"] = Mos(t, "az_pmir", "XMPMIR", 15.06, ypm, 5, 1, 2, pmos=True, conn=True)
    po = d["po"] = Mos(t, "aj_pout", "XMPOUT", 20.07, ypm, 5, 1, 4, pmos=True, conn=True)
    np_ = d["np"] = Mos(t, "az_npair", "XMNPAIR", 17.5, 13.4, 5, 1, 8)
    na = d["na"] = Mos(t, "az_nload_a", "XMNLOAD", 33.63, 3.40, 4, 2, 8, conn=True)
    nm = d["nm"] = Mos(t, "az_nbias", "XMNBIAS", 31.34, 9.57, 4, 2, 6, conn=True)
    nx = d["nx"] = Mos(t, "az_naux", "XMAUX", 26.96, 14.2, 1, 2, 2)
    rz = d["rz"] = Res(t, "az_rzero", "XRZERO", 34.675, 14.2, 270, 0.655, 1.625, 3.73, 1.27, 4.325)
    # switches: az_core's block, moved. Row 1 = gates on az, row 2 = gates on az_b.
    nsa = d["nsa"] = Mos(t, "az_nsa", "XSA_N", 22.0 + DX, 23.59 + DY, 0.5, 0.15, 1)
    nsh = d["nsh"] = Mos(t, "az_nsh", "XSH_N", 24.4 + DX, 22.84 + DY, 2, 0.15, 1)
    psn = d["psn"] = Mos(t, "az_psn", "XSN_P", 28.6 + DX, 21.84 + DY, 4, 0.15, 4, pmos=True, conn=True)
    psa = d["psa"] = Mos(t, "az_psa", "XSA_P", 22.0 + DX, 29.82 + DY, 1, 0.15, 1, pmos=True)
    psh = d["psh"] = Mos(t, "az_psh", "XSH_P", 24.4 + DX, 28.32 + DY, 4, 0.15, 1, pmos=True)
    nsn = d["nsn"] = Mos(t, "az_nsn", "XSN_N", 28.6 + DX, 29.32 + DY, 2, 0.15, 4, conn=True)
    t.paint("nwell", psa.ring[0] - 0.265, psh.ring[1] - 0.265, psh.ring[2] + 0.265, psh.ring[3] + 0.265)
    RB_REAL, RB_DUMMY = -0.415, 0.415
    if big:
        # RBIAS: two 143 kohm strips in series, both real (two strips satisfy rule rpm.1 without a dummy). The array's
        # right end is where the 220 kohm strip's was, so the link to MNBIAS's gate bar is the same.
        rb = d["rb"] = Res(t, "aj_rbias2", "XRBIAS", 44.195 - 15.105, 18.48, 270, 0.125, 12.405, 14.51, 1.155, 15.105)
    else:
        # RBIAS: the lower strip is the 220 kohm resistor, the upper one a grounded dummy (rule rpm.1).
        rb = d["rb"] = Res(t, "az_rbias", "XRBIAS", 22.35, 18.48, 270, 0.125, 19.145, 21.25, 1.155, 21.845)

    def v1(x, y):
        """Narrow via1 for the 0.44 um stripe pitch of the switches."""
        t.paint("metal1", x - 0.13, y - 0.165, x + 0.13, y + 0.165)
        t.paint("metal2", x - 0.13, y - 0.18, x + 0.13, y + 0.18)
        t.box(x - 0.13, y - 0.13, x + 0.13, y + 0.13)
        t.add("paint via1")

    def v1p(x, y, ny=1):
        t.via("via1", x, y, ny=ny)

    def mcon(x, y):
        t.via("mcon", x, y)

    def h2(x1, x2, y, w=W2):
        t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    def v2(x, y1, y2, w=W2):
        t.vwire("metal2", x, min(y1, y2), max(y1, y2), w)

    def m1(x1, y1, x2, y2):
        t.paint("metal1", x1, y1, x2, y2)

    def stripe_vias(dev, idx, y, ny=1):
        for i in idx:
            v1p(dev.sx[i], y, ny)

    # ---------------- vdd: rail along the bottom edge ----------------
    t.paint("metal2", 0.0, 0.3, W, 1.8)
    t.paint("metal2", pm.ring[0] - 0.3, 0.3, po.ring[2] + 0.3, 2.75)     # wide where the PMOS sources land
    stripe_vias(pm, (1,), 2.25, ny=2)
    stripe_vias(po, (1, 3), 2.25, ny=2)
    for x in (pm.x - 0.645, po.x - 1.935, po.x + 1.935):                 # n-well ring ties under the rail
        mcon(x, pm.ring[1])
        v1p(x, pm.ring[1])
    # thin metal1 link up the left edge: RBIAS's VDD end and the upper switch well
    v1p(0.3, 0.9)
    if big:
        # VDD reaches the upper strip's right end: up the left edge, along the top of the cell (above the via
        # stacks, 1.0 um below the top edge), down onto the pad. The two strips are joined at their left ends.
        x1, y1, x2, y2 = rb.term("R2", RB_DUMMY)
        m1(0.15, 0.6, 0.45, YVT + 0.15)
        m1(0.15, YVT - 0.15, XVD + 0.15, YVT + 0.15)
        m1(XVD - 0.15, y1, XVD + 0.15, YVT + 0.15)
        assert x1 + 0.1 < XVD - 0.15 and XVD + 0.15 < 42.6 - 0.14
        xa, ya, _, _ = rb.term("R1", RB_REAL)
        _, _, _, yb = rb.term("R1", RB_DUMMY)
        m1(xa, ya, xa + 0.45, yb)
    else:
        x1, y1, x2, y2 = rb.term("R1", RB_REAL)
        m1(0.15, 0.6, 0.45, y2)
        m1(0.15, y1, x1 + 0.1, y2)
    yt = psa.y - 0.8                                                     # psa/psh well ring, left edge
    mcon(psa.ring[0], yt)
    m1(0.15, yt - 0.15, psa.ring[0] + 0.115, yt + 0.15)
    yt = psn.y + 0.16                                                    # psn well ring -> PMOS-row well ring
    mcon(psn.ring[2], yt)
    mcon(pm.ring[0], yt)
    m1(psn.ring[2] - 0.115, yt - 0.15, pm.ring[0] + 0.115, yt + 0.15)

    # ---------------- vss: line on the right edge ----------------
    xt = 44.05
    v2(xt, 2.0, 17.3, w=1.0)
    t.paint("metal2", na.sx[1] - 0.25, 2.0, xt + 0.5, 2.9)
    stripe_vias(na, (1, 3, 5, 7), 2.45, ny=2)
    yv = nm.y - 1.54
    stripe_vias(nm, (1, 3, 5), yv)
    h2(nm.sx[1] - 0.18, xt, yv)
    for x, y in ((na.ring[2], 2.45), (nm.ring[2], yv), (rb.ring[2], rb.ring[1])):   # ring ties
        mcon(x, y)
        v1p(x, y)
    # p-tap rings joined in local interconnect, so every ring reaches the line by metal
    li = lambda x1, y1, x2, y2: t.paint("locali", x1, y1, x2, y2)   # noqa: E731
    li(np_.ring[2] - 0.085, 10.6, nm.ring[0] + 0.085, 10.9)            # input pair - MNBIAS
    li(nx.x - 0.15, nm.ring[3] - 0.085, nx.x + 0.15, nx.ring[1] + 0.085)   # aux pair - MNBIAS
    li(rz.x - 0.15, nm.ring[3] - 0.085, rz.x + 0.15, rz.ring[1] + 0.085)   # RZERO - MNBIAS
    li(nsn.ring[2] - 0.085, 13.0, np_.ring[0] + 0.085, 13.3)           # XSN nmos - input pair
    li(na.x - 0.15, na.ring[3] - 0.085, na.x + 0.15, nm.ring[1] + 0.085)   # MNLOAD - MNBIAS
    li(20.0, np_.ring[3] - 0.085, 20.3, rb.ring[1] + 0.085)            # input pair - RBIAS
    li(nsa.ring[2] - 0.085, 8.0, nsh.ring[0] + 0.085, 8.3)             # XSA nmos - XSH nmos
    # XSH's PMOS has a well ring of its own inside the switches' shared well; XSA's is on vdd by metal1 (left edge).
    # Joined, so that both reach vdd by metal and not through the well (scripts/metal_islands.py).
    li(psa.ring[2] - 0.085, psa.y - 0.15, psh.ring[0] + 0.085, psa.y + 0.15)
    xl = nsn.ring[0] - 0.535                                            # XSH nmos - XSN nmos, around the XSN pmos well
    li(nsh.ring[2] - 0.085, nsh.ring[3] - 0.085, xl + 0.085, nsh.ring[3] + 0.085)
    li(xl - 0.085, nsh.ring[3] - 0.085, xl + 0.085, nsn.ring[1] + 0.085)
    li(xl - 0.085, nsn.ring[1] - 0.085, nsn.ring[0] + 0.085, nsn.ring[1] + 0.085)

    # ---------------- out ----------------
    stripe_vias(na, range(0, 9, 2), 4.5)
    h2(na.sx[0] - 0.18, na.sx[8] + 0.18, 4.5)
    yout = 3.9
    if big:                                                             # onto the plate at its left margin, from MPOUT's bar
        t.via("via2", OUT_PLATE[0] + 0.45, yout)
    else:
        for a, b in ((0, 1), (1, 2)):                                   # onto the plate in the two gaps between Miller columns
            t.via("via2", (mil[a].capm[2] + mil[b].capm[0]) / 2, 4.5)
    stripe_vias(po, (0, 2, 4), yout)
    h2(po.sx[0] - 0.18, na.sx[0] + 0.15, yout)                          # MPOUT drains join the MNLOAD drain bar
    v2(na.sx[0], yout, 4.5)
    # XSH: both drains on one metal2 vertical. Down to the `out` pin stub on the left edge, up and across to the
    # plate's left margin. The out vertical stands 1.23 um right of its stripes, 1.6 um from the hold node's.
    xso = nsh.sx[1] + 1.23
    yos, yob, xov = 6.0, 17.1, OUT_PLATE[0] + (0.45 if big else 0.3)
    v2(xso, yos, yob)
    for y in (22.4 + DY, 27.0 + DY):                                    # from each drain stripe on metal1, away from nul
        m1(nsh.sx[1], y - 0.15, xso + 0.15, y + 0.15)
        v1p(xso, y)
    h2(0.3, xso, yos)
    h2(xso, xov + 0.2, yob)
    t.via("via2", xov, yob)

    # ---------------- ibias ----------------
    for x in (na.gx[0], nm.gx[5]):                                      # MNLOAD <-> MNBIAS gate bars
        m1(x - 0.3, na.pad_top[0], x + 0.3, nm.pad_bot[1])
    m1(nm.sx[0] - 0.115, nm.top - 0.04, nm.sx[0] + 0.33, nm.pad_top[1])   # MNBIAS diode
    xr1, yr1, xr2, yr2 = rb.term("R2", RB_REAL)
    m1(nm.sx[6], nm.pad_top[0], 42.9, nm.pad_top[1])                   # gate bar out to the RBIAS link
    m1(42.6, nm.pad_top[0], 42.9, yr2)
    m1(min(xr1, 42.6), yr1, max(xr2, 42.9), yr2)

    # ---------------- tail / atail ----------------
    ytn, ytp = nm.y - 0.54, np_.y + 0.06
    stripe_vias(nm, (2, 4), ytn)
    h2(23.55, nm.sx[4] + 0.18, ytn)
    stripe_vias(np_, (1, 3, 5, 7), ytp)
    h2(np_.sx[1] - 0.18, 23.91, ytp)
    xtl = 23.73                                                         # metal1 between the two columns
    m1(xtl - 0.15, ytn - 0.2, xtl + 0.15, ytp + 0.2)
    v1p(xtl, ytn)
    v1p(xtl, ytp)
    yat = nm.y + 1.46
    v1p(nm.sx[6], yat)
    v2(nm.sx[6], yat, 15.9)
    h2(nx.sx[1], nm.sx[6], 15.9)
    v2(nx.sx[1], nx.y - 0.2, 15.9)
    v1(nx.sx[1], nx.y)

    # ---------------- pmirror ----------------
    ypmr = np_.y - 1.14
    stripe_vias(np_, (0, 4, 8), ypmr)
    h2(np_.sx[0] - 0.18, nx.sx[0] + 0.15, ypmr)
    v2(nx.sx[0], ypmr, nx.y + 0.2)
    v1(nx.sx[0], nx.y)
    v2(pm.sx[0], ypm + 1.8, ypmr)
    v1p(pm.sx[0], ypm + 1.8)
    m1(pm.sx[0] - 0.115, pm.top - 0.05, pm.sx[0] + 0.33, pm.pad_top[1])

    # ---------------- gain1 ----------------
    yg1 = np_.y - 1.94
    xrg = snap(rz.term_c("R2")[0])
    stripe_vias(np_, (2, 6), yg1)
    h2(np_.sx[2] - 0.18, xrg + 0.15, yg1)
    v2(nx.sx[2], yg1, nx.y + 0.2)
    v1(nx.sx[2], nx.y)
    xg = po.gx[0]
    v2(xg, ypm + 2.0, yg1)
    v1p(xg, (po.pad_top[0] + po.pad_top[1]) / 2)
    h2(pm.sx[2], xg, ypm + 2.0)
    v1p(pm.sx[2], ypm + 2.0)
    v2(xrg, yg1, rz.y)                                                  # up to RZERO's gain1 end
    v1p(xrg, rz.y)

    # ---------------- comp: RZERO -> metal1 under the atail and nul bars -> stack onto the Miller top plate ----
    x1, y1, x2, y2 = rz.term("R1")
    xc, yc = 29.3, 20.65
    xm = snap((x1 + x2) / 2)
    m1(xm - 0.15, y2 - 0.1, xm + 0.15, 16.75)
    m1(xc - 0.15, 16.45, xm + 0.15, 16.75)
    m1(xc - 0.15, 16.45, xc + 0.15, yc + 0.2)
    if not big:
        v1p(xc, yc)
    if big:                                      # metal2 above the ref line to the stack in the gap, metal4 onto the top plate
        xk, yk = STACK1P_X, COMP1P_Y
        m1(xc - 0.15, yc, xc + 0.15, yk + 0.2)
        v1p(xc, yk)
        h2(xk - 0.15, xc + 0.15, yk)
        t.via("via2", xk, yk)
        t.via("via3", xk, yk)
        t.paint("metal3", xk - 0.25, yk - 0.2, xk + 0.25, yk + 0.3)
        t.paint("metal4", xk - 0.25, yk - 0.25, mil[0].top_m4[0] + 0.1, yk + 0.25)
    else:
        t.via("via2", xc, yc)
        t.via("via3", xc, yc)
        t.paint("metal3", xc - 0.25, yc - 0.2, xc + 0.25, yc + 0.3)
        t.paint("metal4", xc - 0.25, yc - 0.25, xc + 0.25, yc + 0.25)
        t.paint("metal4", xc - 0.15, mil[-1].top_m4[3] - 0.1, xc + 0.15, yc)

    # ---------------- nul and ref ----------------
    # The hold node must not pick up the output. Its metal2 lies only under the ref plate (the switches and the
    # run up to the top edge). From there it goes on metal1 along the strip above the out plate, under a metal2
    # ref line, to MAM's gate; the stack up to the hold top plates stands at the corner between the two plates.
    ynul = 20.0
    xn = OUT_PLATE[0] + 0.29
    xsn = nsh.sx[0] - 0.27
    for y in (23.3 + DY, 27.6 + DY):
        v1(nsh.sx[0], y)
        t.paint("metal2", xsn - 0.15, y - 0.18, nsh.sx[0] + 0.13, y + 0.18)
    v2(xsn, 23.1 + DY, ynul)
    v1p(xsn, ynul)
    pad = nx.pad(0, "top")
    m1(xsn - 0.15, ynul - 0.15, nx.gx[0] + 0.15, ynul + 0.15)           # along the top, metal1
    m1(nx.gx[0] - 0.15, pad[3] - 0.05, nx.gx[0] + 0.15, ynul + 0.15)    # down to MAM's gate pad
    if big:                                      # stack in the gap, below comp's; metal4 back onto the hold top plate
        xn, yn = STACK1P_X, NUL1P_Y
        m1(xn - 0.15, ynul - 0.15, xn + 0.15, yn + 0.2)
        v1p(xn, yn)
        t.via("via2", xn, yn)
        t.via("via3", xn, yn)
        t.paint("metal3", xn - 0.25, yn - 0.2, xn + 0.25, yn + 0.3)
        t.paint("metal4", hold[0].top_m4[2] - 0.1, yn - 0.25, xn + 0.25, yn + 0.25)
    else:
        m1(xn - 0.15, ynul - 0.15, xn + 0.15, yc + 0.2)                 # up to the stack
        v1p(xn, yc)
        t.via("via2", xn, yc)
        t.via("via3", xn, yc)
        t.paint("metal3", xn - 0.25, yc - 0.2, xn + 0.25, yc + 0.3)
        t.paint("metal4", xn - 0.25, yc - 0.25, xn + 0.25, yc + 0.25)
        t.paint("metal4", hold[-1].top_m4[2] - 0.1, yc - 0.3, xn + 0.25, yc)
    # ref: from the hold bottom plate's tab along the top on metal2 (over the hold node's metal1), with a finger
    # over the hold node's drop to MAM; then metal1 down to MAP's gate pad
    xrv = REF_PLATE[2] - (0.3 if big else 0.25)
    t.via("via2", xrv, ynul)
    t.paint("metal2", xrv - 0.2, ynul - 0.45, nx.gx[1] + 0.2, ynul + 0.25)
    t.paint("metal2", nx.gx[0] - 0.9, pad[3] + 0.5, nx.gx[0] + 0.7, ynul + 0.25)
    v1p(nx.gx[1], ynul)
    pad = nx.pad(1, "top")
    m1(nx.gx[1] - 0.15, pad[3] - 0.05, nx.gx[1] + 0.15, ynul + 0.15)

    # ---------------- mi: A gates, XSA, XSN ----------------
    ya1, ya2 = np_.pad_top[1] + 0.15, np_.pad_top[1] + 0.43          # bar above the A gate pads
    ymi = (ya1 + ya2) / 2
    xmi = 27.2 + DX
    m1(nsa.sx[1] - 0.15, ya1, np_.gx[7] + 0.3, ya2)
    for k in (0, 3, 4, 7):
        m1(np_.gx[k] - 0.3, np_.pad_top[0], np_.gx[k] + 0.3, ya2)
    v2(nsa.sx[1], nsa.y - 0.2, ymi + 0.15)                              # XSA mi side
    v1(nsa.sx[1], nsa.y)
    v1(psa.sx[1], psa.y)
    v1(nsa.sx[1], ymi)
    for i in (1, 3):                                                    # XSN mi side
        v1(psn.sx[i], 23.3 + DY)
        v1(nsn.sx[i], 29.8 + DY)
    h2(xmi, psn.sx[3] + 0.13, 23.3 + DY)
    h2(xmi, nsn.sx[3] + 0.13, 29.8 + DY)
    v2(xmi, 23.15 + DY, ymi + 0.15)
    v1(xmi, ymi)

    # ---------------- plus: pin -> XSA and, on metal1 between the switch rows, the B gates ----------------
    yp1, yp2 = np_.pad_bot[0] - 0.43, np_.pad_bot[0] - 0.15            # bar below the B gate pads
    ypl = 22.0 + DY
    xpr = 20.0 + DX
    m1(xpr - 0.15, yp1, np_.gx[6] + 0.3, yp2)
    for k in (1, 2, 5, 6):
        m1(np_.gx[k] - 0.3, yp1, np_.gx[k] + 0.3, np_.pad_bot[1])
    m1(xpr - 0.15, ypl - 0.15, xpr + 0.15, yp2)
    v1p(xpr, ypl)
    h2(0.3, nsa.sx[0], ypl)
    v2(nsa.sx[0], ypl, psa.y + 0.2)
    v1(nsa.sx[0], nsa.y)
    v1(psa.sx[0], psa.y)

    # ---------------- minus ----------------
    xmn = 30.55 + DX
    ymn = 18.5 + DY
    for i in (0, 2, 4):
        v1(psn.sx[i], 20.6 + DY)
        v1(nsn.sx[i], 28.8 + DY)
    h2(psn.sx[0] - 0.13, xmn, 20.6 + DY)
    h2(nsn.sx[0] - 0.13, xmn, 28.8 + DY)
    v2(xmn, ymn - 0.15, 28.95 + DY)
    h2(0.3, xmn, ymn)

    # ---------------- az / az_b gate bars ----------------
    yaz = (psn.pad_top[0] + psn.pad_top[1]) / 2
    m1(20.45 + DX, psn.pad_top[0], psn.gx[0] + 0.145, psn.pad_top[1])
    v1p(20.6 + DX, yaz)
    h2(0.3, 20.6 + DX, yaz)
    yazb = (nsn.pad_top[0] + nsn.pad_top[1]) / 2
    m1(20.45 + DX, nsn.pad_top[0], nsn.gx[0] + 0.145, nsn.pad_top[1])
    v1p(20.6 + DX, yazb)
    h2(0.3, 20.6 + DX, yazb)
    for dev in (nsa, nsh, psa, psh):                                    # unused bottom pads: metal1 minimum area
        x1, y1, x2, y2 = dev.pad(0, "bot")
        m1(x1 - 0.06, y1, x2 + 0.06, y2)

    # ---------------- RBIAS dummy strip: both ends to the vss guard ring ----------------
    for name, xr in (() if big else (("R1", rb.ring[0]), ("R2", rb.ring[2]))):
        x1, y1, x2, y2 = rb.term(name, RB_DUMMY)
        m1(min(x1, xr) - 0.115, y1, max(x2, xr) + 0.115, y2)
        mcon(xr, (y1 + y2) / 2)

    # ---------------- ports (cd_signal_az order) ----------------
    t.label("plus", "metal2", 0.45, ypl, 1)
    t.label("minus", "metal2", 0.45, ymn, 2)
    t.label("out", "metal2", 0.45, yos, 3)                               # also the Miller bottom plate (metal3)
    t.label("az", "metal2", 0.45, yaz, 4)
    t.label("az_b", "metal2", 0.45, yazb, 5)
    t.paint("metal3", 0.0, 9.7, 0.8, 10.3)                               # parent paint so the label attaches to the plate
    t.label("ref", "metal3", 0.4, 10.0, 6)
    t.label("vdd", "metal2", 44.3, 1.05, 7, use="power")      # at the right end: the 2x2 floorplan feeds it there
    t.label("vss", "metal2", xt, 10.0, 8, use="ground")
    return d
