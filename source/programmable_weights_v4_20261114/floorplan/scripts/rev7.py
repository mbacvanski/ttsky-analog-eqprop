"""The circuit strand's netlist with the damping network on f1 and f2 (its revision 7).

  netlist()  ->  (text, where it came from)

If circuit/v4_netlist.py generated() already holds the cell pw4_units3d, that text is returned as it is ("published").
If it does not, but the function takes the setting damp_l (the circuit strand's revision 7, kept behind that parameter
until the design lead's go; its message of 2026-11-15 23:20), generated(damp_l=<the plate's L>) is returned.
Failing both, the text is generated() with exactly the lines the circuit strand named on 2026-11-15 (its message of 22:55,
confirmed by the chip strand at 22:58) added, nothing else touched ("stand-in"; the run prints which it used, and every
result file that rests on it says so):
  pw4_nrn_h     one more pin, dn, after qs; one more switch, XSWD y iso dn vss, a copy of the bus switch's line XSWB
  pw4_units3d   new, pins a b dn vss: pw4_units3's three units a - b, XU4 dn dc vss pdk_rbias2 RVALUE=133333, and the
                capacitor XCD dc b sky130_fd_pr__cap_mim_m3_1 W=23.1 L=10.4 MF=1 m=1 (upper plate dc, lower plate b = REF;
                L=13 with PW4_LANE=1: the plate over the lane)
  xor_chip_v4   XNH1 ... qs1 dn1 iso vss pw4_nrn_h, XUE1 qs1 ref dn1 vss pw4_units3d, the same with 2
No file of the circuit strand is written or changed: this works on the text its function returns.
"""
import os
import re
import sys
from pathlib import Path

CIRCUIT = Path(__file__).resolve().parents[2] / "circuit"
PLATE_W, PLATE_L = 23.1, (13.0 if os.environ.get("PW4_LANE", "0") == "1" else 10.4)


def _once(text, old, new):
    assert text.count(old) == 1, (text.count(old), old)
    return text.replace(old, new)


def netlist():
    if str(CIRCUIT) not in sys.path:
        sys.path.append(str(CIRCUIT))
    import v4_netlist as N
    g = N.generated()
    if re.search(r"(?m)^\.subckt pw4_units3d ", g):
        return g, "published (circuit/v4_netlist.py generated())"
    try:                                                                 # written by the circuit strand, not yet its default output
        g7 = N.generated(damp_l=PLATE_L)
    except TypeError:
        g7 = ""
    if g7:
        if re.search(r"(?m)^\.subckt pw4_units3d ", g7):
            return g7, f"the circuit strand's revision 7 as its function writes it, generated(damp_l={PLATE_L:g}); not yet its default output"
    g = _once(g, ".subckt pw4_nrn_h y p q bus qs iso vss", ".subckt pw4_nrn_h y p q bus qs dn iso vss")
    h = re.search(r"(?ms)^\.subckt pw4_nrn_h .*?^\.ends", g)[0]
    bus = re.search(r"(?m)^XSWB y iso bus vss .*$", h)[0]
    g = g.replace(h, _once(h, bus, bus + "\n" + _once(_once(bus, "XSWB", "XSWD"), " bus ", " dn ")))
    u3 = re.search(r"(?ms)^\.subckt pw4_units3 a b vss\n(.*?)^\.ends", g)
    body = "\n".join(l for l in u3[1].splitlines() if l and not l.startswith("*"))
    g = _once(g, u3[0], u3[0] + "\n.subckt pw4_units3d a b dn vss\n"
              "* A hidden neuron's east cell: the helper beside R7 (three units, a to b), the damping unit dn - dc and the damping\n"
              "* capacitor from dc (upper plate) to b (lower plate; b is REF on the chip).\n" + body
              + f"\nXU4 dn dc vss pdk_rbias2 RVALUE=133333\nXCD dc b sky130_fd_pr__cap_mim_m3_1 W={PLATE_W:g} L={PLATE_L:g} MF=1 m=1\n.ends")
    for k in "12":
        g = _once(g, f"XNH{k} f{k} p{k} q{k} f{k}x qs{k} iso vss pw4_nrn_h", f"XNH{k} f{k} p{k} q{k} f{k}x qs{k} dn{k} iso vss pw4_nrn_h")
        g = _once(g, f"XUE{k} qs{k} ref vss pw4_units3", f"XUE{k} qs{k} ref dn{k} vss pw4_units3d")
    return g, "stand-in (generated() with the lines agreed on 2026-11-15 added; revision 7 not yet published)"


if __name__ == "__main__":
    t, src = netlist()
    print(src)
    for name in ("pw4_nrn_h", "pw4_units3d"):
        print(re.search(rf"(?ms)^\.subckt {name} .*?^\.ends", t)[0][:900])
    print("\n".join(l for l in t.splitlines() if l.startswith(("XNH", "XUE"))))
