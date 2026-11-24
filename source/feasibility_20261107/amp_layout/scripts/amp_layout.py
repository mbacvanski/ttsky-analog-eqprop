"""Place and route az_core: the AH core auto-zero amplifier (cd_signal_az for U1/U3).

Ports (cd_signal_az order): plus minus out az az_b ref vdd vss.

Floorplan (x right, y up, um; cell 44.73 x 48.34):
  MIM, all generator unit cells:
    Miller 1 pF = 3 x 2 units of 8.97 um, lower left (bottom plate = out, top = comp)
    hold   2 pF = 3 x 2 units of 12.75 um, across the top (bottom plate = ref, top = nul)
    Top plates of each array are joined by a metal4 strap in a channel between the unit
    rows; each unit's own bottom-plate strip blocks a direct metal4 join between columns.
    The column x > 33.7, y < 19.8 has no MIM: it holds the metal4->metal2 via stacks of
    the two top-plate nets (comp, nul), which must keep 1.34 um from any capacitor.
  FEOL, under the MIM:
    left column  MNLOAD (two 8-finger rows) and MNBIAS/MNTAIL/MATAIL (one 6-finger row),
                 all W4/L2 with aligned gates, joined by metal1 gate jumpers
    middle       PMOS mirror + output row (bottom), input pair A B B A A B B A (top)
    right        RZERO (horizontal), auxiliary pair MAM/MAP
    upper middle auto-zero switches XSA/XSN/XSH (NMOS row, PMOS row), RBIAS above
Routing: device stripes metal1 (vertical), horizontal bars metal2, metal1 risers where a
vertical run must cross metal2 bars. The Miller bottom plate (metal3) is the out net and
the hold bottom plate is the ref net, so those two nets reach devices through via2 drops
in the plate margins. No via2 lies under a capacitor.
"""
from __future__ import annotations

from cell import Cap, Mos, Res
from geom import Tcl, snap

MIL_X = [5.565, 16.695, 27.825]
MIL_Y = [4.685, 15.135]
HOLD_X = [7.455, 22.365, 37.275]
HOLD_Y = [27.535, 41.765]
W2 = 0.30     # metal2 bar width
W1 = 0.30     # metal1 riser width

# Variants of the cd_signal_az cell that share az_core's transistors and floorplan.
CORE = dict(name="az_core", mil_cell="az_cmil", mil_side=8.97, mil_fill="rows", mil_x=MIL_X, mil_y=MIL_Y,
            hold_cell="az_caz", hold_side=12.75, hold_x=HOLD_X, hold_y=HOLD_Y, hold_bottom="ref", y_pm=4.2,
            drop_load=9.915, drop_pout=(21.045, 32.175), drop_xsh=32.175,
            rzero=dict(cell="az_rzero", x=36.9, y=9.60, a=1.625, b=3.73, hx=1.27, hy=4.325, gain1="bar"))
# Gain stage (COMP=600f, RZERO=25k): smaller Miller units at the same centres with the Miller
# plate filled solid; the 25 kohm strip lies in the band between the PMOS row (lowered 0.3 um)
# and the input pair; plate drops moved clear of the small units' bottom-plate strips.
GAIN = dict(CORE, name="az_gain", mil_cell="ag_cmil", mil_side=6.91, mil_fill=(0, 0, 33.39, 19.82), y_pm=3.9,
            drop_load=8.64, drop_pout=(30.90, 33.0), drop_xsh=33.0,
            rzero=dict(cell="ag_rzero", x=32.4, y=9.375, a=8.675, b=10.78, hx=1.27, hy=11.375, gain1="stub"))
# Reference buffer (cd_ref_az COMP=1.2p): same transistors and RZERO as az_core. Larger Miller units
# (9.84 um, pitch 12.0 x 11.32) and a 1 pF hold array of 8.97 um units whose bottom plate is vss,
# right-aligned above the Miller array with 1.34 um between each capacitor and the other plate.
# ref is then only the MAP gate: a metal3 tab on the right edge.
REF1 = dict(CORE, name="az_ref1", mil_cell="ar_cmil", mil_side=9.84, mil_x=[6.0, 18.0, 30.0], mil_y=[5.12, 16.44],
            hold_cell="ar_caz", hold_side=8.97, hold_x=[16.905, 28.035, 39.165], hold_y=[27.385, 37.835],
            hold_bottom="vss", drop_load=10.6, drop_pout=(22.6, 34.6), drop_xsh=34.6, ring_straps=True)
# Core of the DRIVE=4 REF buffer (cd_ref_az COMP=4p RZERO=1k): az_ref1 without Miller units (the 4 pF
# array and the extra output fingers sit in a booster region below, see bigamp_layout.py). The out
# plate stays as plain metal3; RZERO is the 0.54 um strip, gain1 from the MPOUT gate bar, and comp
# leaves on a metal4 stub to the right edge.
REF4CORE = dict(REF1, name="ref4_core", mil_cell=None, mil_fill=(0, 0, 36.0, 21.56),
                rzero=dict(cell="ar4_rzero", x=36.9, y=9.60, a=0.215, b=2.32, hx=1.27, hy=2.915, gain1="small"),
                comp_export=44.73)


def build(t: Tcl, V: dict = CORE) -> dict:
    t.add(f"load {V['name']}")
    d = {}
    # ---------------- MIM ----------------
    mil = [Cap(t, V["mil_cell"], f"XCMIL_{r}{c}", x, y, V["mil_side"]) for r, y in enumerate(V["mil_y"])
           for c, x in enumerate(V["mil_x"])] if V["mil_cell"] else []
    hold = [Cap(t, V["hold_cell"], f"XCAZ_{r}{c}", x, y, V["hold_side"]) for r, y in enumerate(V["hold_y"])
            for c, x in enumerate(V["hold_x"])]
    # merge the bottom plates of each array into one metal3 shape (same net; avoids capm.11)
    if V["mil_fill"] == "rows":
        t.paint("metal3", mil[0].m3[0], mil[0].m3[3], mil[2].m3[2], mil[3].m3[1])
    else:   # units smaller than the pitch: one solid plate (given box) under the whole Miller array
        t.paint("metal3", *V["mil_fill"])
    t.paint("metal3", hold[0].m3[0], hold[0].m3[3], hold[2].m3[2], hold[3].m3[1])
    d.update(mil=mil, hold=hold)
    ypm = V["y_pm"]

    # ---------------- FEOL placement ----------------
    na = d["na"] = Mos(t, "az_nload_a", "XMNLOAD_A", 10.13, 3.40, 4, 2, 8, conn=True)
    nb = d["nb"] = Mos(t, "az_nload_b", "XMNLOAD_B", 10.13, 8.97, 4, 2, 8, conn=True)
    nm = d["nm"] = Mos(t, "az_nbias", "XMNBIAS", 7.84, 15.14, 4, 2, 6, conn=True)
    pm = d["pm"] = Mos(t, "az_pmir", "XMPMIR", 22.86, ypm, 5, 1, 2, pmos=True, conn=True)
    po = d["po"] = Mos(t, "az_pout", "XMPOUT", 30.45, ypm, 5, 1, 8, pmos=True, conn=True)
    np_ = d["np"] = Mos(t, "az_npair", "XMNPAIR", 26.13, 14.54, 5, 1, 8)
    nx = d["nx"] = Mos(t, "az_naux", "XMAUX", 35.26, 14.54, 1, 2, 2)
    R = V["rzero"]
    rz = d["rz"] = Res(t, R["cell"], "XRZERO", R["x"], R["y"], 90, 0.655, R["a"], R["b"], R["hx"], R["hy"])
    # Auto-zero switches. Row 1 holds every device whose gate is az (top pads at y=24.0),
    # row 2 every device whose gate is az_b (top pads at y=30.48); columns pair each
    # switch's NMOS and PMOS so their source/drain nets run straight up on metal2.
    nsa = d["nsa"] = Mos(t, "az_nsa", "XSA_N", 22.0, 23.59, 0.5, 0.15, 1)                  # az
    nsh = d["nsh"] = Mos(t, "az_nsh", "XSH_N", 24.4, 22.84, 2, 0.15, 1)                    # az
    psn = d["psn"] = Mos(t, "az_psn", "XSN_P", 28.6, 21.84, 4, 0.15, 4, pmos=True, conn=True)  # az
    psa = d["psa"] = Mos(t, "az_psa", "XSA_P", 22.0, 29.82, 1, 0.15, 1, pmos=True)         # az_b
    psh = d["psh"] = Mos(t, "az_psh", "XSH_P", 24.4, 28.32, 4, 0.15, 1, pmos=True)         # az_b
    nsn = d["nsn"] = Mos(t, "az_nsn", "XSN_N", 28.6, 29.32, 2, 0.15, 4, conn=True)          # az_b
    t.paint("nwell", psa.ring[0] - 0.265, psh.ring[1] - 0.265, psh.ring[2] + 0.265, psh.ring[3] + 0.265)
    # RBIAS: strip 1 (lower, y = 34.585) is the 220 kohm resistor, strip 0 a grounded dummy
    rb = d["rb"] = Res(t, "az_rbias", "XRBIAS", 22.35, 35.0, 90, 0.125, 19.145, 21.25, 1.155, 21.845)
    RB_REAL, RB_DUMMY = 0.415, -0.415

    def v1(x, y):
        """Narrow via1 for 0.44 um stripe pitch: 0.26 contact, metal1/metal2 extended N/S only."""
        t.paint("metal1", x - 0.13, y - 0.165, x + 0.13, y + 0.165)
        t.paint("metal2", x - 0.13, y - 0.18, x + 0.13, y + 0.18)
        t.box(x - 0.13, y - 0.13, x + 0.13, y + 0.13)
        t.add("paint via1")

    def v1p(x, y):
        """via1 with the PDK helper's own metal1/metal2 enclosure (for pads and bars)."""
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

    # ---------------- out ----------------
    # load drains (even stripes) and PMOS output drains reach the Miller bottom plate via via2
    for dev, y in ((na, 4.6), (nb, 10.2)):
        stripe_vias(dev, range(0, 9, 2), y)
        h2(dev.sx[0] - 0.18, dev.sx[8] + 0.18, y)
        t.via("via2", V["drop_load"], y)
    yout = ypm - 1.8
    stripe_vias(po, range(0, 9, 2), yout)
    h2(20.9, po.sx[8] + 0.18, yout)
    for x in V["drop_pout"]:
        t.via("via2", x, yout)

    # ---------------- vss (left trunk, source bars, ring ties) ----------------
    for dev, y, idx in ((na, 2.2, (1, 3, 5, 7)), (nb, 7.8, (1, 3, 5, 7)), (nm, 13.6, (1, 3, 5))):
        stripe_vias(dev, idx, y)
        h2(0.1, dev.sx[idx[-1]] + 0.18, y)
        mcon(0.4, y)
        v1p(0.4, y)
    v2(0.25, 0.3, 13.75)

    # ---------------- ibias ----------------
    for x in (na.gx[0], na.gx[7]):                      # MNLOAD rows a <-> b gate bars
        m1(x - 0.3, na.pad_top[0], x + 0.3, nb.pad_bot[1])
    for x in (nb.gx[0], nm.gx[5]):                      # MNLOAD b <-> MNBIAS gate bars
        m1(x - 0.3, nb.pad_top[0], x + 0.3, nm.pad_bot[1])
    m1(nm.sx[0] - 0.115, nm.top - 0.04, nm.sx[0] + 0.33, nm.pad_top[1])   # MNBIAS diode (solid L onto the bar)
    xr2, yr2 = rb.term_c("R2", RB_REAL)
    m1(1.95, nm.pad_top[0], 2.25, yr2 + 0.125)          # RBIAS -> MNBIAS gate bar, metal1 only

    # ---------------- tail / atail ----------------
    stripe_vias(nm, (2, 4), 14.6)
    stripe_vias(np_, (1, 3, 5, 7), 14.6)
    h2(nm.sx[2] - 0.18, np_.sx[7] + 0.18, 14.6)
    v1p(nm.sx[6], 16.6)
    h2(nm.sx[6] - 0.18, nx.sx[1] + 0.15, 16.6)
    v2(nx.sx[1], nx.y - 0.2, 16.6)
    v1(nx.sx[1], nx.y)

    # ---------------- pmirror ----------------
    stripe_vias(np_, (0, 4, 8), 13.4)
    h2(np_.sx[0] - 0.18, nx.sx[0] + 0.15, 13.4)
    v2(nx.sx[0], 13.4, nx.y + 0.2)
    v1(nx.sx[0], nx.y)
    v2(pm.sx[0], ypm + 1.8, 13.4)                       # down to the PMOS mirror diode
    v1p(pm.sx[0], ypm + 1.8)
    m1(pm.sx[0] - 0.115, pm.top - 0.05, pm.sx[0] + 0.33, pm.pad_top[1])

    # ---------------- gain1 ----------------
    stripe_vias(np_, (2, 6), 12.6)
    h2(np_.sx[2] - 0.18, nx.sx[2] + 0.15, 12.6)
    v2(nx.sx[2], 12.6, nx.y + 0.2)
    v1(nx.sx[2], nx.y)
    xg = po.gx[0]                                        # riser to the MPOUT gate bar and mirror drain
    v2(xg, ypm + 2.0, 12.6)
    v1p(xg, (po.pad_top[0] + po.pad_top[1]) / 2)
    h2(pm.sx[2], xg, ypm + 2.0)
    v1p(pm.sx[2], ypm + 2.0)
    x1, y1, x2, y2 = rz.term("R2")
    if R["gain1"] == "bar":                              # RZERO gain1 end, metal1 from the gate bar
        m1(33.65, po.pad_top[0], 33.95, y1 + 0.15)
    elif R["gain1"] == "small":                          # short RZERO: gate bar extended past the last finger
        m1(po.gx[7], po.pad_top[0] + 0.045, 35.9, po.pad_top[1] + 0.045)
        m1(35.6, po.pad_top[0] + 0.045, 35.9, y1 + 0.15)
    else:                                                # long RZERO: metal2 stub from the gain1 riser
        xr2c, yr2c = (snap(v) for v in rz.term_c("R2"))
        h2(xr2c, xg, yr2c)
        v1p(xr2c, yr2c)

    # ---------------- comp: RZERO -> metal4 strap in the Miller channel ----------------
    if R["gain1"] == "bar":
        xc, yc = 39.6, 9.9
    else:                                                # via stack on the far end of the RZERO strip
        xc, yc = (snap(v) for v in rz.term_c("R1"))
    v1p(xc, yc)
    t.via("via2", xc, yc)
    t.via("via3", xc, yc)
    t.paint("metal3", xc - 0.4, yc - 0.4, xc + 0.4, yc + 0.4)
    ych = (V["mil_y"][0] + V["mil_y"][1]) / 2
    if mil:
        t.paint("metal4", 1.0, ych - 0.25, xc + 0.3, ych + 0.25)
        t.paint("metal4", xc - 0.3, yc - 0.35, xc + 0.3, ych + 0.25)
    if V.get("comp_export"):                             # Miller array elsewhere: metal4 stub to the edge
        t.paint("metal4", xc - 0.3, yc - 0.25, V["comp_export"], yc + 0.25)
    for c in mil:
        if c.y < ych:
            t.paint("metal4", c.x - 2.0, c.top_m4[3] - 0.1, c.x, ych + 0.1)
        else:
            t.paint("metal4", c.x - 2.0, ych - 0.1, c.x, c.top_m4[1] + 0.1)

    # ---------------- nul: XSH, MAM gate and the hold top plates ----------------
    yhch = (V["hold_y"][0] + V["hold_y"][1]) / 2
    t.paint("metal4", min(1.5, hold[0].x - 2.0) if V["hold_bottom"] == "ref" else hold[0].x - 2.0,
            yhch - 0.25, 43.0, yhch + 0.25)
    for c in hold:
        if c.y < yhch:
            t.paint("metal4", c.x - 2.0, c.top_m4[3] - 0.1, c.x, yhch + 0.1)
        else:
            t.paint("metal4", c.x - 2.0, yhch - 0.1, c.x, c.top_m4[1] + 0.1)
    xn, yn = 40.0, 18.2
    t.paint("metal4", xn - 0.3, yn - 0.35, xn + 0.3, hold[2].top_m4[1] + 0.15)
    t.via("via2", xn, yn)
    t.via("via3", xn, yn)
    t.paint("metal3", xn - 0.4, yn - 0.4, xn + 0.4, yn + 0.4)
    h2(nsh.sx[0], xn, yn)
    v2(nsh.sx[0], yn, 27.8)
    v1(nsh.sx[0], 23.3)
    v1(psh.sx[0], 27.6)
    m1(nx.gx[0] - 0.15, nx.pad_top[0], nx.gx[0] + 0.15, yn + 0.15)   # MAM gate pad up to the bar
    v1p(nx.gx[0], yn)

    # ---------------- out from XSH ----------------
    yo = 18.8
    v2(nsh.sx[1], yo, 27.2)
    v1(nsh.sx[1], 22.4)
    v1(psh.sx[1], 27.0)
    h2(nsh.sx[1], V["drop_xsh"], yo)
    t.via("via2", V["drop_xsh"], yo)

    # ---------------- ref: MAP gate -> hold bottom plate ----------------
    m1(nx.gx[1] - 0.15, nx.pad_top[0], nx.gx[1] + 0.15, 19.55)
    v1p(nx.gx[1], 19.4)
    h2(nx.gx[1], 43.4, 19.4)
    if V["hold_bottom"] == "ref":
        v2(43.4, 19.4, 21.9)
        t.via("via2", 43.4, 21.9)
    else:                                                # ref is only the MAP gate: metal3 tab at the right edge
        t.via("via2", 43.4, 19.4)
        t.paint("metal3", 43.0, 19.0, 44.73, 19.8)
        # hold bottom plate = vss: tie it to the RBIAS guard ring (top side) beside the last hold unit
        xt, yt = 43.5, rb.ring[3] - 0.085
        for k in ("mcon", "via1", "via2"):
            t.via(k, xt, yt)

    # ---------------- mi ----------------
    ya1, ya2 = np_.pad_top[1] + 0.15, np_.pad_top[1] + 0.43          # bar above the A gate pads
    m1(np_.gx[0] - 0.3, ya1, np_.gx[7] + 0.3, ya2)
    for k in (0, 3, 4, 7):
        m1(np_.gx[k] - 0.3, np_.pad_top[0], np_.gx[k] + 0.3, ya2)
    ymi = (ya1 + ya2) / 2
    v2(nsa.sx[1], ymi, psa.y + 0.2)                      # XSA mi side
    v1p(nsa.sx[1], ymi)
    v1(nsa.sx[1], nsa.y)
    v1(psa.sx[1], psa.y)
    xmi = 27.2                                           # XSN mi side: bars + one vertical
    for i in (1, 3):
        v1(psn.sx[i], 23.3)
        v1(nsn.sx[i], 29.8)
    h2(xmi, psn.sx[3] + 0.13, 23.3)
    h2(xmi, nsn.sx[3] + 0.13, 29.8)
    v2(xmi, 19.8, 30.0)
    v1(xmi, 19.95)
    m1(xmi - 0.15, ya1, xmi + 0.15, 20.12)               # metal1 down across the nul/out bars

    # ---------------- plus ----------------
    yp1, yp2 = np_.pad_bot[0] - 0.43, np_.pad_bot[0] - 0.15        # bar below the B gate pads
    m1(19.85, yp1, np_.gx[6] + 0.3, yp2)
    for k in (1, 2, 5, 6):
        m1(np_.gx[k] - 0.3, yp1, np_.gx[k] + 0.3, np_.pad_bot[1])
    m1(19.85, yp1, 20.15, 22.15)                          # riser left of the input pair
    v1p(20.0, 22.0)
    h2(20.0, nsa.sx[0], 22.0)
    v2(nsa.sx[0], 22.0, psa.y + 0.2)
    v1(nsa.sx[0], nsa.y)
    v1(psa.sx[0], psa.y)
    v1p(20.0, 19.5)
    h2(0.3, 20.0, 19.5)

    # ---------------- minus ----------------
    xmn = 30.55
    for i in (0, 2, 4):
        v1(psn.sx[i], 20.6)
    h2(psn.sx[0] - 0.13, xmn, 20.6)
    for i in (0, 2, 4):
        v1(nsn.sx[i], 28.8)
    h2(nsn.sx[0] - 0.13, xmn, 28.8)
    v2(xmn, 20.45, 32.4)
    h2(0.3, xmn, 32.4)

    # ---------------- az / az_b gate bars ----------------
    yaz = (psn.pad_top[0] + psn.pad_top[1]) / 2
    m1(20.45, psn.pad_top[0], psn.gx[0] + 0.145, psn.pad_top[1])
    v1p(20.6, yaz)
    h2(0.3, 20.6, yaz)
    yazb = (nsn.pad_top[0] + nsn.pad_top[1]) / 2
    m1(20.45, nsn.pad_top[0], nsn.gx[0] + 0.145, nsn.pad_top[1])
    v1p(20.6, yazb)
    h2(0.3, 20.6, yazb)
    # unused single-finger bottom pads: enlarge to the metal1 minimum area (same gate net)
    for dev in (nsa, nsh, psa, psh):
        x1, y1, x2, y2 = dev.pad(0, "bot")
        m1(x1 - 0.06, y1, x2 + 0.06, y2)

    # ---------------- vdd ----------------
    yvdd = ypm + 1.4
    stripe_vias(po, (1, 3, 5, 7), yvdd)
    stripe_vias(pm, (1,), yvdd)
    h2(pm.sx[1] - 0.18, 44.55, yvdd)
    for x in (pm.gx[1] - 0.2, po.gx[7]):                 # n-well ring ties of the output PMOS well
        mcon(x, po.ring[3])
        v1p(x, po.ring[3])
        v2(x, yvdd, po.ring[3])
    v2(44.4, yvdd - 0.15, yr2 + 0.15)
    xr1, yr1 = rb.term_c("R1", RB_REAL)
    v1p(xr1, yr1)
    h2(xr1, 44.55, yr1)
    for dev, y, x0 in ((psn, 22.0, psn.ring[2]), (psh, 26.0, psh.ring[2])):   # switch well ties
        mcon(x0, y)
        m1(x0 - 0.115, y - 0.15, 44.55, y + 0.15)
        v1p(44.4, y)

    # ---------------- RBIAS dummy strip: both ends to the vss guard ring ----------------
    for name, xr in (("R2", rb.ring[0]), ("R1", rb.ring[2])):
        x1, y1, x2, y2 = rb.term(name, RB_DUMMY)
        m1(min(x1, xr) - 0.115, y1, max(x2, xr) + 0.115, y2)
        mcon(xr, (y1 + y2) / 2)

    # ---------------- every guard ring to its rail by metal ----------------
    # LVS joins rings through the silicon (Magic's substrate is one ground node, an n-well one node), so a ring
    # with no metal to its rail still matches (scripts/metal_islands.py finds them). Only in the cells of the
    # 2x2 chip (az_ref1, ref4_core). az_core and az_gain are used by variant AI's activation blocks alone, which
    # run metal1 across this cell's left edge where the strap would be; they are left as drawn.
    if V.get("ring_straps"):
        # Substrate rings: chained in local interconnect, neighbour to neighbour, to the MNLOAD rings, which stand
        # on the vss trunk at the left edge; the RBIAS ring by a metal1 strap up the left edge from the trunk.
        # The well ring of XSA's PMOS: joined to XSH's, which is on vdd by metal1.
        li = lambda x1, y1, x2, y2: t.paint("locali", x1, y1, x2, y2)   # noqa: E731
        li(nb.ring[2] - 0.085, np_.ring[1] + 0.05, np_.ring[0] + 0.085, np_.ring[1] + 0.35)   # MNLOAD - input pair
        li(np_.ring[2] - 0.085, nx.y - 0.15, nx.ring[0] + 0.085, nx.y + 0.15)                 # input pair - auxiliary pair
        li(nx.x - 0.15, rz.ring[3] - 0.085, nx.x + 0.15, nx.ring[1] + 0.085)                  # RZERO - auxiliary pair
        li(nsh.x - 0.15, np_.ring[3] - 0.085, nsh.x + 0.15, nsh.ring[1] + 0.085)              # input pair - XSH nmos
        li(nsa.ring[2] - 0.085, nsa.y - 0.15, nsh.ring[0] + 0.085, nsa.y + 0.15)              # XSA nmos - XSH nmos
        li(nsn.x - 0.15, nsn.ring[3] - 0.085, nsn.x + 0.15, rb.ring[1] + 0.085)               # XSN nmos - RBIAS
        li(psa.ring[2] - 0.085, psa.y - 0.15, psh.ring[0] + 0.085, psa.y + 0.15)              # XSA pmos well ring - XSH's
        plate_on_ring = V["hold_bottom"] == "vss"
        m1(0.25, 13.45, 0.55, rb.ring[3] + 0.15 if plate_on_ring else rb.term("R2", RB_DUMMY)[3])   # vss trunk - RBIAS ring
        if plate_on_ring:
            # The hold capacitors' bottom plate is vss and stands on the RBIAS ring at x 43.5 (via stack above).
            # Metal1 along the ring's top side from the strap to that stack, so that the plate reaches the vss
            # trunk by metal (about 28 ohm) and not through 44 um of ring and the silicon under it.
            m1(rb.ring[0] - 0.115, rb.ring[3] - 0.15, 43.65, rb.ring[3] + 0.15)
            for x in range(2, 43, 4):
                mcon(x, rb.ring[3])

    # ---------------- ports (cd_signal_az order) ----------------
    t.label("plus", "metal2", 0.45, 19.5, 1)
    t.label("minus", "metal2", 0.45, 32.4, 2)
    t.paint("metal3", 0.0, 4.7, 0.8, 5.3)                # parent paint so the label attaches to the plate
    t.label("out", "metal3", 0.4, 5.0, 3)
    t.label("az", "metal2", 0.45, yaz, 4)
    t.label("az_b", "metal2", 0.45, yazb, 5)
    if V["hold_bottom"] == "ref":
        yref = hold[3].m3[3] - 0.84
        t.paint("metal3", 0.0, yref - 0.3, 0.8, yref + 0.3)
        t.label("ref", "metal3", 0.4, yref, 6)
    else:
        t.label("ref", "metal3", 44.3, 19.4, 6)
    t.label("vdd", "metal2", 44.4, 30.0, 7, use="power")
    t.label("vss", "metal2", 0.25, 0.5, 8, use="ground")
    return d
