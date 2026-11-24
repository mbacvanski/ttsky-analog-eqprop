"""DRIVE=4 amplifiers: the REF buffer az_ref4 (cd_ref_az DRIVE=4 COMP=4p RZERO=1k, XBUF3) and the
pad buffer az_pad (pdk_amp DRIVE=4 COMP=4p, the plain two-stage amplifier without auto-zero).

The cell is az_ref1's floorplan without Miller units (subcell ref4_core, built by amp_layout.py)
sitting on a booster region that holds what DRIVE=4 adds:
  * the 4 pF Miller array: 3 x 2 units of 18.09 um, 60.75 x 38.06 um, bottom plate = out, which
    abuts the core's plain out plate;
  * 6 more MNLOAD rows (48 fingers) stacked under the core's MNLOAD column, gates jumpered to it;
  * 3 more MPOUT rows (24 fingers) stacked under the core's MPOUT, gates jumpered, n-wells merged.
Every out drain drops onto the Miller plate through via2 in the gaps between unit columns; comp
leaves the core on its metal4 stub, runs down the right edge (clear of the array) and along the
channel between the unit rows. The core keeps az_core's capacitor-free column for its nul/comp
stacks, which is why the array sits below it rather than over it.
"""
from __future__ import annotations

from cell import Cap, Mos, Res
from geom import Tcl, snap

YC = 38.06                                     # ref4_core lower-left y (on top of the Miller array)
MX, MY = [10.125, 30.375, 50.625], [9.245, 28.815]
NL_Y = [6.22, 11.79, 17.36, 22.93, 28.5, 34.07]
PO_Y = [20.88, 27.54, 34.2]
X_DROP_N, X_DROP_P = 19.95, 39.2               # via2 columns between Miller unit columns
X_COMP = 61.5
W2 = 0.30


def booster(t: Tcl, comp_stub) -> float:
    """The DRIVE=4 output booster below a core cell placed at (0, YC); comp_stub = (x, y) of the end
    of the core's metal4 comp stub. Returns the channel y of the Miller array (the out label point)."""

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

    # ---------------- 4 pF Miller array ----------------
    mil = [Cap(t, "big_cmil", f"XCMIL_{r}{c}", x, y, 18.09) for r, y in enumerate(MY) for c, x in enumerate(MX)]
    t.paint("metal3", mil[0].m3[0], mil[0].m3[3], mil[2].m3[2], mil[3].m3[1])

    # ---------------- extra output fingers ----------------
    nl = [Mos(t, "az_nload_a", f"XMNLOAD_X{k}", 10.13, y, 4, 2, 8, conn=True) for k, y in enumerate(NL_Y)]
    po = [Mos(t, "az_pout", f"XMPOUT_X{k}", 30.45, y, 5, 1, 8, pmos=True, conn=True) for k, y in enumerate(PO_Y)]
    t.paint("nwell", po[-1].ring[0] - 0.265, po[-1].ring[3], po[-1].ring[2] + 0.265, YC + 1.0)   # merge with the core's

    # MNLOAD: gates (ibias) jumpered row to row and up to the core's MNLOAD bottom gate bar
    for k in range(len(nl)):
        top = nl[k + 1].pad_bot[1] if k + 1 < len(nl) else YC + 1.24
        for x in (nl[k].gx[0], nl[k].gx[7]):
            m1(x - 0.3, nl[k].pad_top[0], x + 0.3, top)
        yo, ys = nl[k].y + 1.2, nl[k].y - 1.2
        for i in range(0, 9, 2):                         # drains -> out
            v1p(nl[k].sx[i], yo)
        h2(nl[k].sx[0] - 0.18, X_DROP_N + 0.15, yo)
        t.via("via2", X_DROP_N, yo)
        for i in (1, 3, 5, 7):                           # sources -> vss trunk
            v1p(nl[k].sx[i], ys)
        h2(0.1, nl[k].sx[7] + 0.18, ys)
        mcon(0.4, ys)
        v1p(0.4, ys)
    v2(0.25, NL_Y[0] - 1.35, YC + 0.4)

    # MPOUT: gates (gain1) jumpered row to row and up to the core's MPOUT bottom gate bar
    for k in range(len(po)):
        ytop = po[k + 1].y - 2.705 if k + 1 < len(po) else YC + 1.495
        for x in (po[k].gx[0], po[k].gx[7]):
            m1(x - 0.3, po[k].y + 2.705, x + 0.3, ytop)
        yo, yv = po[k].y - 1.8, po[k].y + 1.4
        for i in range(0, 9, 2):                         # drains -> out
            v1p(po[k].sx[i], yo)
        h2(po[k].sx[0] - 0.18, X_DROP_P + 0.15, yo)
        t.via("via2", X_DROP_P, yo)
        for i in (1, 3, 5, 7):                           # sources -> vdd trunk
            v1p(po[k].sx[i], yv)
        h2(po[k].sx[1] - 0.18, 44.55, yv)
        xt = po[k].ring[2] - 0.085                       # n-well ring tie
        mcon(xt, yv)
        v1p(xt, yv)
    v2(44.4, PO_Y[0] + 1.25, YC + 5.6)

    # ---------------- comp: core's metal4 stub -> right edge -> channel between unit rows ----------------
    ych = (MY[0] + MY[1]) / 2
    xs, yc = comp_stub
    t.paint("metal4", xs - 0.2, yc - 0.25, X_COMP + 0.3, yc + 0.25)
    t.paint("metal4", X_COMP - 0.3, ych - 0.25, X_COMP + 0.3, yc + 0.25)
    t.paint("metal4", 1.0, ych - 0.25, X_COMP + 0.3, ych + 0.25)
    for c in mil:
        if c.y < ych:
            t.paint("metal4", c.x - 2.0, c.top_m4[3] - 0.1, c.x, ych + 0.1)
        else:
            t.paint("metal4", c.x - 2.0, ych - 0.1, c.x, c.top_m4[1] + 0.1)

    return ych


def build_ref4(t: Tcl) -> dict:
    t.add("load az_ref4")
    t.box(0, YC, 0, YC)
    t.add("getcell ref4_core child 0 0")
    t.add("identify XCORE")
    ych = booster(t, (44.73, YC + 9.6))

    def h2(x1, x2, y, w=W2):
        t.hwire("metal2", min(x1, x2), max(x1, x2), y, w)

    # ---------------- ports (cd_ref_az order) ----------------
    xr = X_COMP + 0.3
    for name, y, idx in (("plus", 19.5, 1), ("minus", 32.4, 2), ("az", 24.115, 4), ("az_b", 30.595, 5)):
        t.paint("metal2", 0.3, YC + y - 0.15, 0.7, YC + y + 0.15)      # parent paint on the core's pin bar
        t.label(name, "metal2", 0.45, YC + y, idx)
    t.label("out", "metal3", 0.4, ych, 3)
    t.paint("metal3", 43.6, YC + 19.0, xr, YC + 19.8)                    # ref tab carried to the right edge
    t.label("ref", "metal3", xr - 0.3, YC + 19.4, 6)
    h2(44.25, xr, YC + 30.0)                                            # vdd stub to the right edge
    t.label("vdd", "metal2", xr - 0.3, YC + 30.0, 7, use="power")
    t.label("vss", "metal2", 0.25, NL_Y[0], 8, use="ground")
    return {}


def build_pad_core(t: Tcl) -> dict:
    """pdk_amp's input and first stage plus one MPOUT/MNLOAD set, on az_core's coordinates.

    No auto-zero: the input pair's A gates (MNMINUS) are the minus pin and its B gates (MNPLUS)
    the plus pin. MNBIAS/MNTAIL are one 5-finger row (no MATAIL). RZERO is the 19.64 um generic-poly
    strip, horizontal between the PMOS row and the pair; comp leaves on a metal4 stub to the right.
    The out plate is plain metal3 (the 4 pF array is in the booster below)."""
    t.add("load pad_core")

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

    t.paint("metal3", 0, 0, 40.0, 18.0)                 # out plate
    na = Mos(t, "az_nload_a", "XMNLOAD_A", 10.13, 3.40, 4, 2, 8, conn=True)
    nb = Mos(t, "az_nload_b", "XMNLOAD_B", 10.13, 8.97, 4, 2, 8, conn=True)
    nm = Mos(t, "pad_nbias", "XMNBIAS", 6.695, 15.14, 4, 2, 5, conn=True)   # s0 bias (diode), s2 s4 tail
    pm = Mos(t, "az_pmir", "XMPMIR", 22.86, 4.20, 5, 1, 2, pmos=True, conn=True)
    po = Mos(t, "az_pout", "XMPOUT", 30.45, 4.20, 5, 1, 8, pmos=True, conn=True)
    np_ = Mos(t, "az_npair", "XMNPAIR", 26.13, 14.54, 5, 1, 8)               # A B B A A B B A
    rz = Res(t, "pad_rzero", "XRZERO", 32.935, 9.4, 90, 0.45, 9.845, 11.95, 1.065, 12.535)
    rb = Res(t, "az_rbias", "XRBIAS", 22.35, 20.5, 90, 0.125, 19.145, 21.25, 1.155, 21.845)
    RB_REAL, RB_DUMMY = 0.415, -0.415

    # out
    for dev, y in ((na, 4.6), (nb, 10.2)):
        stripe_vias(dev, range(0, 9, 2), y)
        h2(dev.sx[0] - 0.18, dev.sx[8] + 0.18, y)
        t.via("via2", 9.915, y)
    stripe_vias(po, range(0, 9, 2), 2.4)
    h2(20.9, po.sx[8] + 0.18, 2.4)
    for x in (21.045, 32.175):
        t.via("via2", x, 2.4)
    # vss
    for dev, y, idx in ((na, 2.2, (1, 3, 5, 7)), (nb, 7.8, (1, 3, 5, 7)), (nm, 13.6, (1, 3, 5))):
        stripe_vias(dev, idx, y)
        h2(0.1, dev.sx[idx[-1]] + 0.18, y)
        mcon(0.4, y)
        v1p(0.4, y)
    v2(0.25, 0.3, 13.75)
    # bias (MNBIAS diode, every current-source gate, RBIAS)
    for x in (na.gx[0], na.gx[7]):
        m1(x - 0.3, na.pad_top[0], x + 0.3, nb.pad_bot[1])
    for x in (nb.gx[0], nb.gx[4]):
        m1(x - 0.3, nb.pad_top[0], x + 0.3, nm.pad_bot[1])
    m1(nm.sx[0] - 0.115, nm.top - 0.04, nm.sx[0] + 0.33, nm.pad_top[1])
    xr2, yr2 = rb.term_c("R2", RB_REAL)
    m1(1.95, nm.pad_top[0], 2.25, yr2 + 0.125)
    # tail
    stripe_vias(nm, (2, 4), 14.6)
    stripe_vias(np_, (1, 3, 5, 7), 14.6)
    h2(nm.sx[2] - 0.18, np_.sx[7] + 0.18, 14.6)
    # pmirror
    stripe_vias(np_, (0, 4, 8), 13.4)
    h2(np_.sx[0] - 0.18, np_.sx[8] + 0.18, 13.4)
    v2(pm.sx[0], 6.0, 13.4)
    v1p(pm.sx[0], 6.0)
    m1(pm.sx[0] - 0.115, pm.top - 0.05, pm.sx[0] + 0.33, pm.pad_top[1])
    # gain1 (pair B drains, mirror drain, MPOUT gates, RZERO left pad)
    stripe_vias(np_, (2, 6), 12.6)
    h2(np_.sx[2] - 0.18, np_.sx[6] + 0.18, 12.6)
    xg = po.gx[0]
    v2(xg, 6.2, 12.6)
    v1p(xg, (po.pad_top[0] + po.pad_top[1]) / 2)
    h2(pm.sx[2], xg, 6.2)
    v1p(pm.sx[2], 6.2)
    xz2, yz = (snap(v) for v in rz.term_c("R2"))
    v1p(xz2, yz)
    h2(xz2, xg, yz)
    # comp: RZERO right pad -> via stack -> metal4 stub to the right edge
    xc, yc = (snap(v) for v in rz.term_c("R1"))
    v1p(xc, yc)
    t.via("via2", xc, yc)
    t.via("via3", xc, yc)
    t.paint("metal3", xc - 0.4, yc - 0.4, xc + 0.4, yc + 0.4)
    x_edge = rz.ring[2]
    t.paint("metal4", xc - 0.3, yc - 0.25, x_edge, yc + 0.25)
    # minus: A gates (bar above the top pads) -> metal2 to the left edge
    ya1, ya2 = np_.pad_top[1] + 0.15, np_.pad_top[1] + 0.43
    m1(np_.gx[0] - 0.3, ya1, np_.gx[7] + 0.3, ya2)
    for k in (0, 3, 4, 7):
        m1(np_.gx[k] - 0.3, np_.pad_top[0], np_.gx[k] + 0.3, ya2)
    ymn = (ya1 + ya2) / 2
    v1p(np_.gx[0], ymn)
    h2(0.3, np_.gx[0], ymn)
    # plus: B gates (bar below the bottom pads) -> metal1 riser left of the pair -> metal2 to the left edge
    yp1, yp2 = np_.pad_bot[0] - 0.43, np_.pad_bot[0] - 0.15
    m1(19.85, yp1, np_.gx[6] + 0.3, yp2)
    for k in (1, 2, 5, 6):
        m1(np_.gx[k] - 0.3, yp1, np_.gx[k] + 0.3, np_.pad_bot[1])
    ypl = 18.5
    m1(19.85, yp1, 20.15, ypl + 0.15)
    v1p(20.0, ypl)
    h2(0.3, 20.0, ypl)
    # vdd
    stripe_vias(po, (1, 3, 5, 7), 5.6)
    stripe_vias(pm, (1,), 5.6)
    h2(pm.sx[1] - 0.18, 44.55, 5.6)
    for x in (pm.gx[1] - 0.2, po.gx[7]):
        mcon(x, po.ring[3])
        v1p(x, po.ring[3])
        v2(x, 5.6, po.ring[3])
    xr1, yr1 = rb.term_c("R1", RB_REAL)
    v2(44.4, 5.45, yr1 + 0.15)
    v1p(xr1, yr1)
    h2(xr1, 44.55, yr1)
    # RBIAS dummy strip: both ends to the vss guard ring
    for name, xr in (("R2", rb.ring[0]), ("R1", rb.ring[2])):
        x1, y1, x2, y2 = rb.term(name, RB_DUMMY)
        m1(min(x1, xr) - 0.115, y1, max(x2, xr) + 0.115, y2)
        mcon(xr, (y1 + y2) / 2)
    # every substrate ring to vss by metal (see amp_layout.py): the pair's and RZERO's rings joined to the MNLOAD
    # ring beside them in local interconnect, the RBIAS ring by a metal1 strap up the left edge from the vss trunk
    li = lambda x1, y1, x2, y2: t.paint("locali", x1, y1, x2, y2)   # noqa: E731
    li(nb.ring[2] - 0.085, np_.ring[1] + 0.05, np_.ring[0] + 0.085, np_.ring[1] + 0.35)
    li(nb.ring[2] - 0.085, rz.y - 0.15, rz.ring[0] + 0.085, rz.y + 0.15)
    m1(0.25, 13.45, 0.55, rb.term("R2", RB_DUMMY)[3])
    # ports (pdk_amp order: plus minus vdd vss out)
    t.label("plus", "metal2", 0.45, ypl, 1)
    t.label("minus", "metal2", 0.45, ymn, 2)
    t.label("vdd", "metal2", 44.4, 12.0, 3, use="power")
    t.label("vss", "metal2", 0.25, 0.5, 4, use="ground")
    t.label("out", "metal3", 0.4, 5.0, 5)
    return dict(comp_stub=(x_edge, yc), ypl=ypl, ymn=ymn)


def build_pad(t: Tcl) -> dict:
    t.add("load az_pad")
    t.box(0, YC, 0, YC)
    t.add("getcell pad_core child 0 0")
    t.add("identify XCORE")
    ych = booster(t, (45.47, YC + 9.4))
    xr = X_COMP + 0.3
    ymn = YC + 14.54 + 2.5 + 0.39 + 0.29              # the pair's A bar (minus)
    for name, y, idx in (("plus", YC + 18.5, 1), ("minus", ymn, 2)):
        t.paint("metal2", 0.3, y - 0.15, 0.7, y + 0.15)
        t.label(name, "metal2", 0.45, y, idx)
    t.hwire("metal2", 44.25, xr, YC + 12.0, W2)          # vdd stub to the right edge
    t.label("vdd", "metal2", xr - 0.3, YC + 12.0, 3, use="power")
    t.label("vss", "metal2", 0.25, NL_Y[0], 4, use="ground")
    t.label("out", "metal3", 0.4, ych, 5)
    return {}
