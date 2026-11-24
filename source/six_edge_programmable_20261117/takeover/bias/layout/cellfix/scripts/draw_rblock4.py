"""pw4_rblock4: the row of the four programmable resistors with the five buses' clamps (circuit/v4_netlist.py), as
the chip strand's plan places it: 113.4 x 14.9 um, cells in the order
  0  pw4_shunt            shunt of edge 1   a = m1x, b = ref       strobe we0
  1  pw4_bridge           bridge of edge 1  b (west) = f1x, a (east) = zx       strobe we2
  2  pw4_bridge           bridge of edge 2  b (west) = zx, a (east) = f2x       strobe we3   (the bridge is symmetric in a, b)
  3  pw4_shunt, mirrored  shunt of edge 2   a = m2x, b = ref       strobe we1
The bus clamps (native NMOS 1/0.5, bus -> REF, gate on the clamp line) stand in the pockets the cells leave for them:
m1x in cell 0, f1x and zx in cell 1, f2x in cell 2, m2x in cell 3. The cells' rails (ground, supply, DAC line, REF,
clamp line) are joined across the seams here. The row's pins are the plan's rectangles (chip strand's contract), except
the supply, which is on the east edge as agreed (metal2, y 0.75 to 1.05).

  python draw_rblock4.py
"""
from __future__ import annotations

from lib import Cell, build
import draw_res as R

W, H = R.W, R.H
RW = 4 * W
# (cell, x0, mirrored, the netlist's names of its strobe and of its west / east bus pins)
CELLS = [("pw4_shunt", 0.0, False, "we0", None, "m1x"), ("pw4_bridge", W, False, "we2", "f1x", "zx"),
         ("pw4_bridge", 2 * W, False, "we3", "zx", "f2x"), ("pw4_shunt", 3 * W, True, "we1", None, "m2x")]
# the plan's north pins (row x of the rectangle's west edge), contract.json
PLAN = {"we0": 24.65, "m1x": 27.05, "f1x": 29.45, "we2": 31.85, "clampw": 50.25, "zx": 55.05, "zx_2": 57.45, "we3": 59.85,
        "f2x": 83.85, "m2x": 86.25, "we1": 88.65}


def place(c, cell, inst, x0, mirrored):
    if mirrored:
        c.t.box(x0 + W, 0, x0 + W, 0)
        c.t.add(f"getcell {cell} h child 0 0")
    else:
        c.t.box(x0, 0, x0, 0)
        c.t.add(f"getcell {cell} child 0 0")
    c.t.add(f"identify {inst}")


def clamp(c, inst, x, y, ybus, via=True, yg=None):
    """A bus clamp (nvt1t, origin (x, y) in the cell's frame): D down to the bus wire (metal2 at ybus, or onto the
    cell's own metal1 there when via is False), S on REF, gate on the clamp line (its via at yg when given)."""
    c.dev("nvt1t", inst, x, y)
    xd, xs = x - 0.395, x + 0.395
    c.v("metal1", xd, ybus, y - 0.55, 0.23)
    if via:
        c.via("via1", xd, ybus)
    c.via("via1", xs, R.Y_REF)
    c.via("via1", x, y + 0.62 if yg is None else yg)


def rblock4():
    c = Cell("pw4_rblock4")
    for k, (cell, x0, mir, we, west, east) in enumerate(CELLS):
        place(c, cell, f"XC{k}", x0, mir)
    # bus clamps in the pockets (drawn in each cell's own frame, mirrored for cell 3)
    ya_sh = R.Y0_SHUNT + 2.29                                     # the shunt's a wire (moves with the chain)
    for k, (cell, x0, mir, we, west, east) in enumerate(CELLS):
        c.mx = (2 * x0 + W) if mir else None
        if cell == "pw4_shunt":
            # PW4_WELLFIX=1 (bias layout work, 2026-11-23): 0.10 um further from the shunt's chain well
            # PW4_WELLFIX=3 (lock2_r): 0.12 um (the shunt's chain 0.03 down, their HVI 0.705 above its well)
            dcl = 0.12 if R.LEVEL == 3 else (0.10 if R.WELLFIX else 0.0)
            # (level 3: the clamp-line via stays where lock2_h has it, 13.725: the merged metal1 then tops out at the
            # device's own gate metal1, 13.86, 0.14 under the top-level f2x wire of row 0)
            clamp(c, f"XBCL_{east}", x0 + 6.5, 13.005 + dcl, ya_sh, via=False,
                  yg=(13.005 + 0.10 + 0.62) if R.LEVEL == 3 else None)   # onto the chain's a stripe (metal1)
            if R.WELLFIX and not mir:
                # the top-level m1x wire of the row placed at 180 degrees (rblock4 at 115.8, 204) lands on this clamp's
                # drain column from the west with a notch filler at the column's old end; the column now ends 0.10 um
                # further, so a 0.14 um square on the column's west side at its end closes the new 0.03 um notch
                yt = 13.005 + dcl + 0.345
                c.rect("metal1", x0 + 6.5 - 0.395 - 0.115 - 0.14, yt - 0.14, x0 + 6.5 - 0.395 - 0.115, yt)
        else:
            if west == "f1x":
                clamp(c, "XBCL_f1x", x0 + 5.5, 13.075, 7.8)
            clamp(c, f"XBCL_{east}", x0 + 24.5, 13.075, 7.8)
        c.mx = None
    # rails across the seams
    for xs in (W, 2 * W, 3 * W):
        c.rect("metal1", xs - 0.35, R.Y_VSS - 0.24, xs + 0.35, R.Y_VSS + 0.24)
        for y in (R.Y_VDD, R.Y_DAC, R.Y_REF, R.Y_CLW):
            c.rect("metal2", xs - 0.35, y - 0.15, xs + 0.35, y + 0.15)
    # north pins: the cells' pins joined to the plan's rectangles by a short metal2 piece at the top edge
    cellpin = {}
    for k, (cell, x0, mir, we, west, east) in enumerate(CELLS):
        fx = (lambda lx: x0 + W - lx) if mir else (lambda lx: x0 + lx)
        if cell == "pw4_shunt":
            cellpin[we] = fx(R.X_WE)
            cellpin[east] = fx(R.X_A)
        else:
            cellpin[we] = fx(W - R.X_WE)
            cellpin["zx_2" if west == "zx" else west] = fx(R.X_B)
            cellpin[east] = fx(R.X_A2)
    for name, x1 in PLAN.items():
        if name == "clampw":
            continue
        xc = cellpin[name]
        lo, hi = min(x1, xc - 0.15), max(x1 + 0.3, xc + 0.15)
        c.rect("metal2", lo, H - 0.7, hi, H)
        c.port(name.replace("_2", ""), "metal2", x1, H - 0.7, x1 + 0.3, H) if name != "zx_2" else c.rect("metal2", x1, H - 0.7, x1 + 0.3, H)
        if name == "zx_2":
            c.label("zx", "metal2", x1 + 0.15, H - 0.35)
            c.info["pins"]["zx (second pin, same net)"] = dict(layer="metal2", rect=[x1, round(H - 0.7, 3), round(x1 + 0.3, 3), H])
    # the two pins of zx joined inside the row (metal1 under the top band)
    xa, xb = cellpin["zx"], cellpin["zx_2"]
    c.h("metal1", xa - 0.115, xb + 0.115, H - 0.5, 0.23)
    # clamp line: from the rail up to its pin
    x1 = PLAN["clampw"]
    c.rect("metal2", x1, R.Y_CLW, x1 + 0.3, H)
    c.port("clampw", "metal2", x1, H - 0.7, x1 + 0.3, H)
    # east pins (cell 3 is the mirrored shunt: its ground riser stands at row x RW - X_VSSR)
    c.port("vdd", "metal2", RW - 0.7, 0.75, RW, 1.05, use="power")
    xg = RW - R.X_VSSR
    c.rect("metal1", xg - 0.15, 6.35, RW, 6.65)
    c.port("vss", "metal1", RW - 0.7, 6.35, RW, 6.65, use="ground")
    c.via("via1", RW - 0.45, R.Y_DAC)
    c.rect("metal1", RW - 0.7, 1.55, RW, 1.85)
    c.port("dac", "metal1", RW - 0.7, 1.55, RW, 1.85)
    c.v("metal2", RW - 0.45, 4.75, R.Y_REF + 0.15, 0.3)
    c.port("ref", "metal2", RW - 0.7, 4.75, RW, 5.05)
    c.outline(0, 0, RW, H)
    c.info["interface_note"] = ("Pins on the plan's rectangles (chip strand's contract), the supply on the east edge as agreed on "
                                "2026-11-15. zx has two pins, joined inside the row. Capacitors 0.315 um further apart than the plan "
                                "(rule capm.11); each cell's grounded metal4 frame, 0.3 um wide, runs along the cell's outline "
                                "(the cells' frames merge at the seams), so metal4 reaches the row's outline all round."
                                + ("" if R.ROW == "1520" else
                                   " Inside each frame a metal4 ring 0.4 um wide runs 0.4 um round each capacitor's upper plate, "
                                   "joined by via3 to that capacitor's lower plate, i.e. on that bus (or REF): metal4 on f1x, zx, "
                                   "f2x, m1x, m2x and ref, each joined down to diffusion inside the row through metal3 to metal1."))
    c.info["edge_note"] = ("the grounded metal4 frames run along the whole outline; everything else stays 0.3 um inside it "
                           "except the pins")
    return c


if __name__ == "__main__":
    build(rblock4(), extract=True)
