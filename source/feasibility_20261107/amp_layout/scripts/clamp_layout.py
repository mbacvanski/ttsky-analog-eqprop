"""Place and route az_clamp: the limiter clamp amplifier (cd_amp_az_biased, COMP=350f RZERO=40k).

Ports (cd_amp_az_biased order): plus minus out az az_b ref vdd vss ibias.

The clamp has twice az_core's tail and input pair, a 2+2 mirror, a 28 um RZERO strip, small
capacitors (350 fF Miller, 1 pF hold) and no RBIAS (ibias is a port). Floorplan (x right, y up):
  left column   MNLOAD rows a/b (8 fingers each), MNBIAS/MNTAIL/MATAIL (10 fingers), and on top
                the input pair (16 fingers, A B B A repeated), all aligned at x = 0.4
  right of pair MAM/MAP (auxiliary pair), as in az_core
  above pair    the auto-zero switches, az_core's block translated by (DX, DY), with az_core's
                port bars on the left edge and its nul/out/ref exits to the right
  bottom middle PMOS mirror (4 fingers) and output (8 fingers)
  right edge    RZERO, vertical: gain1 end at the bottom beside the MPOUT gate bar, comp end at
                the top with the metal4 via stack
MIM: the Miller units (3 x 2 of 5.24 um) sit at the lower left inside one metal3 out plate that
also covers the PMOS row, so every out drain drops onto it with a via2. The hold array (3 x 2 of
8.97 um, bottom plate ref) covers the upper left, 1.34 um clear of the out plate. comp runs on
metal4 from the RZERO stack down the right edge and along the Miller channel; nul's via stack
sits right of the hold array.
Plus is a metal2 bar over the input pair's top gate pads (via1 on every B pad), so it reaches
both the left-edge port and the XSA switch without a riser.
"""
from __future__ import annotations

from cell import Cap, Mos, Res
from geom import Tcl, snap

W2 = 0.30
DX, DY = -9.2, 7.27          # az_core switch block -> clamp switch block
MX, MY = [3.70, 11.10, 18.50], [2.82, 9.54]              # Miller unit centres (5.24 um)
HX, HY = [5.565, 16.695, 27.825], [18.185, 28.635]       # hold unit centres (8.97 um)
OUT_PLATE = (0.0, 0.0, 41.4, 12.36)


def build(t: Tcl) -> dict:
    t.add("load az_clamp")
    d = {}
    # ---------------- MIM ----------------
    mil = [Cap(t, "ac_cmil", f"XCMIL_{r}{c}", x, y, 5.24) for r, y in enumerate(MY) for c, x in enumerate(MX)]
    hold = [Cap(t, "ac_caz", f"XCAZ_{r}{c}", x, y, 8.97) for r, y in enumerate(HY) for c, x in enumerate(HX)]
    t.paint("metal3", *OUT_PLATE)                                                   # out
    t.paint("metal3", hold[0].m3[0], hold[0].m3[3], hold[2].m3[2], hold[3].m3[1])   # ref, rows merged
    d.update(mil=mil, hold=hold)

    # ---------------- FEOL placement ----------------
    na = d["na"] = Mos(t, "az_nload_a", "XMNLOAD_A", 10.13, 3.40, 4, 2, 8, conn=True)
    nb = d["nb"] = Mos(t, "az_nload_b", "XMNLOAD_B", 10.13, 8.97, 4, 2, 8, conn=True)
    # D S D S ... : s0 = ibias (MNBIAS diode), s2..s8 = tail (MNTAIL x8), s10 = atail (MATAIL)
    nm = d["nm"] = Mos(t, "ac_nbias", "XMNBIAS", 12.42, 15.14, 4, 2, 10, conn=True)
    # A B B A repeated: A (MNMINUS, gate mi) drains s0,4,8,12,16 = pmirror; B drains s2,6,10,14 = gain1
    npr = d["np"] = Mos(t, "ac_npair", "XMNPAIR", 11.29, 21.81, 5, 1, 16)
    nx = d["nx"] = Mos(t, "az_naux", "XMAUX", 26.06, 21.81, 1, 2, 2)
    # S D S D S: s1 = pmirror (MPREF x2, diode), s3 = gain1 (MPMIRROR x2)
    pm = d["pm"] = Mos(t, "ac_pmir", "XMPMIR", 24.15, 4.2, 5, 1, 4, pmos=True, conn=True)
    po = d["po"] = Mos(t, "az_pout", "XMPOUT", 33.03, 4.2, 5, 1, 8, pmos=True, conn=True)
    rz = d["rz"] = Res(t, "ac_rzero", "XRZERO", 43.27, 17.265, 0, 0.655, 13.965, 16.07, 1.27, 16.665)
    nsa = d["nsa"] = Mos(t, "az_nsa", "XSA_N", 22.0 + DX, 23.59 + DY, 0.5, 0.15, 1)                  # az
    nsh = d["nsh"] = Mos(t, "az_nsh", "XSH_N", 24.4 + DX, 22.84 + DY, 2, 0.15, 1)                    # az
    psn = d["psn"] = Mos(t, "az_psn", "XSN_P", 28.6 + DX, 21.84 + DY, 4, 0.15, 4, pmos=True, conn=True)  # az
    psa = d["psa"] = Mos(t, "az_psa", "XSA_P", 22.0 + DX, 29.82 + DY, 1, 0.15, 1, pmos=True)         # az_b
    psh = d["psh"] = Mos(t, "az_psh", "XSH_P", 24.4 + DX, 28.32 + DY, 4, 0.15, 1, pmos=True)         # az_b
    nsn = d["nsn"] = Mos(t, "az_nsn", "XSN_N", 28.6 + DX, 29.32 + DY, 2, 0.15, 4, conn=True)          # az_b
    t.paint("nwell", psa.ring[0] - 0.265, psh.ring[1] - 0.265, psh.ring[2] + 0.265, psh.ring[3] + 0.265)

    def v1(x, y):
        """Narrow via1 for 0.44 um stripe pitch: 0.26 contact, metal1/metal2 extended N/S only."""
        t.paint("metal1", x - 0.13, y - 0.165, x + 0.13, y + 0.165)
        t.paint("metal2", x - 0.13, y - 0.18, x + 0.13, y + 0.18)
        t.box(x - 0.13, y - 0.13, x + 0.13, y + 0.13)
        t.add("paint via1")

    def v1p(x, y):
        t.via("via1", x, y)

    def mcon(x, y):
        t.via("mcon", x, y)

    def h2(x1, x2, y, w=W2):
        t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    def v2(x, y1, y2, w=W2):
        t.vwire("metal2", x, min(y1, y2), max(y1, y2), w)

    def m1(x1, y1, x2, y2):
        t.paint("metal1", x1, y1, x2, y2)

    def stripe_vias(dev, idx, y):
        for i in idx:
            v1p(dev.sx[i], y)

    # ---------------- out: every drain drops onto the out plate ----------------
    for dev, y in ((na, 4.6), (nb, 10.2)):
        stripe_vias(dev, range(0, 9, 2), y)
        h2(dev.sx[0] - 0.18, dev.sx[8] + 0.18, y)
        t.via("via2", 6.0, y)                     # between Miller columns 0 and 1
    stripe_vias(po, range(0, 9, 2), 2.4)
    h2(po.sx[0] - 0.18, po.sx[8] + 0.18, 2.4)
    for x in (po.sx[3], po.sx[7]):
        t.via("via2", x, 2.4)

    # ---------------- vss (left trunk, source bars, ring ties) ----------------
    for dev, y, idx in ((na, 2.2, (1, 3, 5, 7)), (nb, 7.8, (1, 3, 5, 7)), (nm, 13.6, (1, 3, 5, 7, 9))):
        stripe_vias(dev, idx, y)
        h2(0.1, dev.sx[idx[-1]] + 0.18, y)
        mcon(0.4, y)
        v1p(0.4, y)
    v2(0.25, 0.3, 13.75)

    # ---------------- ibias (port; MNBIAS diode and every current-source gate) ----------------
    for x in (na.gx[0], na.gx[7]):
        m1(x - 0.3, na.pad_top[0], x + 0.3, nb.pad_bot[1])
    for x in (nb.gx[0], nb.gx[7]):                   # nb and nm gate columns coincide
        m1(x - 0.3, nb.pad_top[0], x + 0.3, nm.pad_bot[1])
    m1(nm.sx[0] - 0.115, nm.top - 0.04, nm.sx[0] + 0.33, nm.pad_top[1])
    yib = (nm.pad_top[0] + nm.pad_top[1]) / 2
    v1p(1.0, yib)
    h2(0.3, 1.0, yib)

    # ---------------- tail / atail ----------------
    stripe_vias(nm, (2, 4, 6, 8), 16.6)
    h2(nm.sx[2] - 0.18, nm.sx[8] + 0.18, 16.6)
    stripe_vias(npr, range(1, 16, 2), 19.9)
    h2(npr.sx[1] - 0.18, npr.sx[15] + 0.18, 19.9)
    v2(nm.sx[8], 16.6, 19.9)
    v1p(nm.sx[10], 16.0)
    h2(nm.sx[10], nx.sx[1], 16.0)
    v2(nx.sx[1], 16.0, nx.y + 0.2)
    v1(nx.sx[1], nx.y)

    # ---------------- pmirror ----------------
    stripe_vias(npr, (0, 4, 8, 12, 16), 20.7)
    h2(npr.sx[0] - 0.18, nx.sx[0] + 0.15, 20.7)
    v2(nx.sx[0], 20.7, nx.y + 0.2)
    v1(nx.sx[0], nx.y)
    v2(pm.sx[1], 6.4, 20.7)                              # down to the PMOS mirror diode
    v1p(pm.sx[1], 6.4)
    # diode: solid metal1 from the via up to the gate bar, as wide as the generator's gate bridge over s1
    m1(pm.sx[1] - 0.225, 6.24, pm.sx[1] + 0.225, pm.pad_top[1] + 0.045)

    # ---------------- gain1 ----------------
    stripe_vias(npr, (2, 6, 10, 14), 23.6)
    xg = po.gx[0]                                        # riser to the MPOUT gate bar and mirror drain
    h2(npr.sx[2] - 0.18, xg + 0.15, 23.6)
    v2(nx.sx[2], nx.y - 0.2, 23.6)
    v1(nx.sx[2], nx.y)
    v2(xg, 6.2, 23.6)
    v1p(xg, (po.pad_top[0] + po.pad_top[1]) / 2)
    h2(pm.sx[3], xg, 6.2)
    v1p(pm.sx[3], 6.2)
    x1, y1, x2, y2 = rz.term("R2")                       # RZERO gain1 end, metal1 from the gate bar
    m1(po.sx[8], po.pad_top[0], 43.1, po.pad_top[1])
    m1(42.8, y2 - 0.1, 43.1, po.pad_top[1])

    # ---------------- comp: RZERO top -> metal4 down the right edge and along the Miller channel ----------------
    xc, yc = (snap(v) for v in rz.term_c("R1"))
    v1p(xc, yc)
    t.via("via2", xc, yc)
    t.via("via3", xc, yc)
    t.paint("metal3", xc - 0.4, yc - 0.4, xc + 0.4, yc + 0.4)
    ych = (MY[0] + MY[1]) / 2
    t.paint("metal4", 1.0, ych - 0.25, xc + 0.3, ych + 0.25)
    t.paint("metal4", xc - 0.3, ych - 0.25, xc + 0.3, yc + 0.35)
    for c in mil:
        if c.y < ych:
            t.paint("metal4", c.x - 2.0, c.top_m4[3] - 0.1, c.x, ych + 0.1)
        else:
            t.paint("metal4", c.x - 2.0, ych - 0.1, c.x, c.top_m4[1] + 0.1)

    # ---------------- nul: XSH, MAM gate and the hold top plates ----------------
    yhch = (HY[0] + HY[1]) / 2
    xn, yn = 35.5, 18.2 + DY
    t.paint("metal4", 1.5, yhch - 0.25, xn + 0.3, yhch + 0.25)
    t.paint("metal4", xn - 0.3, yhch - 0.25, xn + 0.3, yn + 0.35)
    for c in hold:
        if c.y < yhch:
            t.paint("metal4", c.x - 2.0, c.top_m4[3] - 0.1, c.x, yhch + 0.1)
        else:
            t.paint("metal4", c.x - 2.0, yhch - 0.1, c.x, c.top_m4[1] + 0.1)
    t.via("via2", xn, yn)
    t.via("via3", xn, yn)
    t.paint("metal3", xn - 0.4, yn - 0.4, xn + 0.4, yn + 0.4)
    h2(nsh.sx[0], xn, yn)
    v2(nsh.sx[0], yn, 27.8 + DY)
    v1(nsh.sx[0], 23.3 + DY)
    v1(psh.sx[0], 27.6 + DY)
    m1(nx.gx[0] - 0.15, nx.pad_top[0], nx.gx[0] + 0.15, yn + 0.15)   # MAM gate pad up to the bar
    v1p(nx.gx[0], yn)

    # ---------------- out from XSH: bar to the right, then down onto the out plate ----------------
    yo, xo = 18.8 + DY, 36.5
    v2(nsh.sx[1], yo, 27.2 + DY)
    v1(nsh.sx[1], 22.4 + DY)
    v1(psh.sx[1], 27.0 + DY)
    h2(nsh.sx[1], xo, yo)
    v2(xo, OUT_PLATE[3] - 0.46, yo)
    t.via("via2", xo, OUT_PLATE[3] - 0.46)

    # ---------------- ref: MAP gate -> hold bottom plate (via2 between capm and its contact strip) ----------------
    yr, xr = 19.4 + DY, 32.2
    m1(nx.gx[1] - 0.15, nx.pad_top[0], nx.gx[1] + 0.15, yr + 0.15)
    v1p(nx.gx[1], yr)
    h2(nx.gx[1], xr, yr)
    t.via("via2", xr, yr)

    # ---------------- mi: A gates (bar above the top pads) + XSA + XSN ----------------
    A, B = (0, 3, 4, 7, 8, 11, 12, 15), (1, 2, 5, 6, 9, 10, 13, 14)
    ya1, ya2 = npr.pad_top[1] + 0.3, npr.pad_top[1] + 0.58
    m1(npr.gx[A[0]] - 0.3, ya1, npr.gx[A[-1]] + 0.3, ya2)
    for k in A:
        m1(npr.gx[k] - 0.3, npr.pad_top[0], npr.gx[k] + 0.3, ya2)
    ymi = (ya1 + ya2) / 2
    v2(nsa.sx[1], ymi, psa.y + 0.2)                      # XSA mi side
    v1p(nsa.sx[1], ymi)
    v1(nsa.sx[1], nsa.y)
    v1(psa.sx[1], psa.y)
    xmi = 27.2 + DX                                      # XSN mi side: bars + one vertical
    for i in (1, 3):
        v1(psn.sx[i], 23.3 + DY)
        v1(nsn.sx[i], 29.8 + DY)
    h2(xmi, psn.sx[3] + 0.13, 23.3 + DY)
    h2(xmi, nsn.sx[3] + 0.13, 29.8 + DY)
    v2(xmi, 19.8 + DY, 30.0 + DY)
    v1(xmi, 19.95 + DY)
    m1(xmi - 0.15, ya1, xmi + 0.15, 20.12 + DY)          # metal1 down to the A bar

    # ---------------- plus: metal2 over the B top pads, to the port and to XSA ----------------
    yp = (npr.pad_top[0] + npr.pad_top[1]) / 2
    for k in B:
        v1p(npr.gx[k], yp)
    h2(0.3, npr.gx[B[-1]] + 0.16, yp)
    v2(nsa.sx[0], yp, psa.y + 0.2)
    v1(nsa.sx[0], nsa.y)
    v1(psa.sx[0], psa.y)

    # ---------------- minus ----------------
    xmn = 30.55 + DX
    for i in (0, 2, 4):
        v1(psn.sx[i], 20.6 + DY)
    h2(psn.sx[0] - 0.13, xmn, 20.6 + DY)
    for i in (0, 2, 4):
        v1(nsn.sx[i], 28.8 + DY)
    h2(nsn.sx[0] - 0.13, xmn, 28.8 + DY)
    v2(xmn, 20.45 + DY, 32.4 + DY)
    h2(0.3, xmn, 32.4 + DY)

    # ---------------- az / az_b gate bars ----------------
    yaz = (psn.pad_top[0] + psn.pad_top[1]) / 2
    m1(20.45 + DX, psn.pad_top[0], psn.gx[0] + 0.145, psn.pad_top[1])
    v1p(20.6 + DX, yaz)
    h2(0.3, 20.6 + DX, yaz)
    yazb = (nsn.pad_top[0] + nsn.pad_top[1]) / 2
    m1(20.45 + DX, nsn.pad_top[0], nsn.gx[0] + 0.145, nsn.pad_top[1])
    v1p(20.6 + DX, yazb)
    h2(0.3, 20.6 + DX, yazb)
    for dev in (nsa, nsh, psa, psh):                     # unused single-finger bottom pads: metal1 min area
        x1, y1, x2, y2 = dev.pad(0, "bot")
        m1(x1 - 0.06, y1, x2 + 0.06, y2)

    # ---------------- vdd ----------------
    yvdd, xv = 5.6, 41.5
    ytop = 32.4 + DY + 0.15
    stripe_vias(po, (1, 3, 5, 7), yvdd)
    stripe_vias(pm, (0, 2, 4), yvdd)
    h2(pm.sx[0] - 0.18, xv + 0.15, yvdd)
    for x in (pm.gx[2], po.gx[7]):                       # n-well ring ties of the PMOS row
        mcon(x, po.ring[3])
        v1p(x, po.ring[3])
        v2(x, yvdd, po.ring[3])
    for dev, y, x0 in ((psn, 22.0 + DY, psn.ring[2]), (psh, 26.0 + DY, psh.ring[2])):   # switch well ties
        mcon(x0, y)
        m1(x0 - 0.115, y - 0.15, xv + 0.15, y + 0.15)
        v1p(xv, y)
    v2(xv, yvdd - 0.15, ytop)

    # ---------------- ports (cd_amp_az_biased order) ----------------
    t.label("plus", "metal2", 0.45, yp, 1)
    t.label("minus", "metal2", 0.45, 32.4 + DY, 2)
    t.label("out", "metal3", 0.4, 1.0, 3)
    t.label("az", "metal2", 0.45, yaz, 4)
    t.label("az_b", "metal2", 0.45, yazb, 5)
    t.paint("metal3", 0.0, 29.7, 0.8, 30.3)              # parent paint so the label attaches to the hold plate
    t.label("ref", "metal3", 0.4, 30.0, 6)
    t.label("vdd", "metal2", xv, ytop - 0.3, 7, use="power")
    t.label("vss", "metal2", 0.25, 0.5, 8, use="ground")
    t.label("ibias", "metal2", 0.45, yib, 9)
    return d
