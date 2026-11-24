"""The v4 chip for REVISION 6 of the design, as data (plan r6; the revision-5 draft with outlines is rev5/v4_plan.py): the new cells (outline, pins, capacitor plates), where they stand,
the metal drawn by hand inside the three neurons and inside Z's input resistor block (the taps), and the new nets.

Nothing here moves or redraws anything of the accepted chip. Every coordinate is in um in the chip's frame unless it
says "local" (a neuron cell's own frame, as in feasibility_20261107/floorplan/chip2x2/scripts/aj_neuron_layout.py).

The new cells: seven drawn by this strand (cellwork/: sizes and pins from their own result files) and two drawn by the
cells strand (its delivery in cells_in/: outline, pins and capacitor rectangles from its interface.json): the row of the four
programmable resistors (_rblock()) and, since 2026-11-15 14:05, the bias block pw4_bias (_bias()). No stand-in is left:
every cell on the chip is a drawn cell.

Plan r5: four programmable resistors in the strip above H2 (two bridges between the z bus and the f1, f2 buses, two
shunts from the two midpoints' buses to REF), an isolation switch on each midpoint beside Z's input resistor block, the
fixed helpers of identical unit strips inside the neurons, the DAC edge at Z, two bias words, the control.

The unit strip of this draft is 133 kohm (23.3 um of 0.35 um strip, drawn as two legs), NOT the 400 kohm of DESIGN.md: a
hidden neuron's helper and the DAC edge are three units in series; the output neuron's helper on p is one unit, its
helper on q four units (two in series, twice in parallel). Seven units of 400 kohm do not fit in the output neuron's
free floor (REPORT.md, step 3). The design lead agreed to the unit on 2026-11-14.

Since 2026-11-15 the draft follows the circuit strand's revised netlist (circuit/v4_netlist.py): each programmable resistor
has the two-stage writer and therefore a supply pin (the row takes VDD from the decoder's supply); the helper beside R4
has its switch on the neuron's wire and its strips on p (inside the west cell: no change to the taps); the DAC edge is
z - switch - three strips - nd - transmission gate of 8 units - DAC line, and that gate stands in a cell of its own inside
the output neuron (DACG below), with the clamp of nd and the inverter that makes its `off` from the gate line; the output
neuron's two helper switches are three 4 um fingers each. The last two were settled with the circuit strand for the
layout's sake (REPORT.md, decisions 3 and 4).

(The scripts of revision 1 and of revision 4 of the design are kept in rev1/ and rev4/.)
"""
from __future__ import annotations

import json
import os

import magic_util  # noqa: F401
from magic_util import OUT
import chip

PLAN = os.environ.get("V4_PLAN", "r6")
assert PLAN in ("r6",)
GP, GOFF = 0.8, 0.4                                # the accepted router's grid: pitch and offset (router.P, router.OFF)


def ongrid(v):
    return round(round((v - GOFF) / GP) * GP + GOFF, 4)


# ---------------------------------------------------------------- the pins (REPORT.md, "The pin assignment")
PIN = dict(weight_prog="uio_in[7]", res_sel="uio_in[6]", write="uio_in[5]", bias_prog="uio_in[4]")

# ---------------------------------------------------------------- the three neurons, local geometry
NW = 114.25                                        # neuron width
X_P, X_Q, X_Y = 63.45, 64.15, 66.95                # metal2 wires of p, q, y in the inner channel (local x)
END_P, END_Q = 21.9, 25.4                          # where the accepted p and q wires end (local y, top of the metal)
X_GND = 113.865                                    # centre of the ground line in the amplifier-side margin (metal2)
X_REF2 = 89.07                                     # the control block's ref wire (metal2, local x), from local y 56.75 up
# rows of metal1 between the upper amplifier (top edge at local y 54.1) and the control block (from 69.0): local y,
# before the per-neuron shift DY that puts them on the chip router's grid
NH = 83.5                                          # neuron height
# The drawn cells inside each neuron (cellwork/). Local frame; the cells stand as drawn (their left edge towards the
# inner channel), so on the chip they are mirrored in Z and upside down in H2 with their neuron.
#   west cell (pw4_nrn_h / pw4_nrn_z): the switches and the strips beside y, p, q, in the smaller piece of free floor
#   east cell (pw4_units3d / pw4_units5): strips, in the larger piece; in a hidden neuron also the damping capacitor on
#   top of them, whose plate is that cell's outline: it reaches 3.45 um west and 1.4 um south of the cell's ground ring
#   (the cell's result file says where its ring is: "ring_outer")
# Between them, 5.3 um wide, runs the control block's ref wire (metal2, from local y 56.75 up); the links between the
# cells and the wires to the neuron's edge cross there.
XW, XE = 68.2, 90.6                                # the west cell's left edge; the east cell's RING, outer left edge
YW = {"H1": 54.42, "H2": 54.42, "Z": 54.5}        # H: the gate line leaves the west cell exactly on the row 56.4 (0.79 um lower than
                                                   # before the damping switch: the cell grew downwards by one stripe pitch)
YE = {"H1": 57.0, "H2": 57.0, "Z": 55.6}          # the east cell's ring, outer lower edge (H: ten strips; 0.5 um above the gate line)
WEST = {"H1": "pw4_nrn_h", "H2": "pw4_nrn_h", "Z": "pw4_nrn_z"}
EASTC = {"H1": "pw4_units3d", "H2": "pw4_units3d", "Z": "pw4_units5"}
ROW_LOW, ROW_BUS = 54.8, 55.6                      # rows to the neuron's edge (on the router's grid; +DY)
DY = {"H1": 0.0, "Z": 0.0, "H2": -0.2}             # H2 is upside down: its rows fall on the grid 0.2 um lower in its own frame
# The DAC edge's gate (pw4_dacgate) stands in the output neuron's third piece of free floor, beside the control block,
# 3 um under the accepted DAC line (metal3 in the channel above Z). Chip frame; it is not mirrored: its REF pad lies under
# the accepted metal3 REF wire that crosses that floor, and the chip puts one via there.
DG_X, DG_Y = 166.75, 72.6
VDD_ROW = 70.02                                    # Z local: the control block's VDD feed (metal1) along the gate's lower edge
VSS_RAIL, X_VSS_END = 69.24, 79.55                 # Z local: the control block's ground rail (ends at x 79.27), continued to the gate

# ---------------------------------------------------------------- Z's input resistor block: the two midpoints
# The block (instance RW, cell rw_res) holds six 100 kohm strips; strips 1 and 2 are the edge from H1, strips 3 and 4 the
# edge from H2. Each pair is joined at the block's TOP end by a piece of metal1 over the strips' end contacts (not over
# a strip's body, which ends at y = 163.67): that metal is the midpoint. The tap is metal1 drawn from an end contact of
# the pair straight up past the guard ring and then east, above the ring and inside the block's outline, to the block's
# east edge. No cut, no via, nothing over a strip's body; all of it under the grounded metal3 sheet.
# The two rows are the two lowest that clear the strips' end contacts (metal1 up to y = 165.72) and the ground pin's
# metal1 (up to 166.515): a row is 0.26 um wide there, so that it keeps 0.15 um from both. They are 1.3 and 2.1 um below
# the accepted metal1 wire above the block (the selected ladder tap of BIAS2). A first version used the rows 166.8 and
# 167.6: the upper one ran 0.44 um under that wire for 20 um and put 0.61 fF between a midpoint and the bias path.
# East of the block each tap turns down by three rows on metal1 (between the block's edge and the accepted metal2 wire of
# the selected ladder tap of BIAS1 at x = 220.4, which both then cross at right angles) and the router takes over from there:
# left to itself the router put one of the two turns directly under that wire.
RW_EAST = 218.32
MID_TAPS = dict(mid1=dict(x=210.8, y_head=165.5, row=166.8, w=0.26, x_jog=219.6, y_exit=164.4),
                mid2=dict(x=214.8, y_head=165.5, row=166.0, w=0.26, x_jog=218.8, y_exit=163.6))

# ---------------------------------------------------------------- the two ext_in stubs, cut
# On the accepted chip the DAC line ext_in ends on the `ext` pin of each external-bias switch (EXT1, EXT2) with a short
# piece of metal2 (the accepted router's stub from the pin up to its first grid point). In v4 those pins are fed by the
# stored biases' read lines (bw1 -> EXT1.ext, bw2 -> EXT2.ext; circuit/v4_netlist.py XEXT1, XEXT2), and ext_in must not
# reach them. The build leaves exactly these two accepted rectangles out (v4_build.py; gds_same.py expects them, and only
# them, missing). The rest of each accepted branch (the via pad at the grid point, the via up and the metal3/metal2 piece
# back to the metal4 trunk at x 197.2) stays: ext_in still ends there, 0.67 um (EXT1) and 0.87 um (EXT2) above the pin.
CUT_ACCEPTED = [["metal2", 194.7, 190.55, 195.0, 191.75, "ext_in", "EXT1.ext"],
                ["metal2", 194.7, 209.55, 195.0, 210.95, "ext_in", "EXT2.ext"]]
# bw1, bw2 join the pins instead: a hand-drawn metal2 piece on top of the pin (where the cut stub began), 0.52 um (EXT1) and
# 0.72 um (EXT2) below the remaining ext_in pad, going 0.85 um west; from its west end the router's stub goes straight up
# to the grid, 0.42 um west of that pad (terminal "E", EXT_JOIN).
EXT_JOIN = {"bw1": "EXT1", "bw2": "EXT2"}


# ---------------------------------------------------------------- new cells: name -> size, pins, plates
# pin: (edge, position along the edge, layer, width); plates: capacitor plates in the cell's own frame
RB_X0, RB_Y0 = 4.4, 195.5


# The cells strand's cells are read from a COPY of its last delivery, floorplan/cells_in/ (layout/, interface.json, ref/,
# extracted/; taken on purpose by scripts/take_cells.py, with checksums in cells_in/MANIFEST.json), never from its live
# folder ../cells, which its scripts rewrite while the chip is being built.
CELLS_STRAND = OUT / "cells_in"
EDGE_LAYER = {"metal1": "met1", "metal2": "met2", "metal3": "met3", "metal4": "met4"}


def _edge_pins(d):
    """The pins of a cell of the cells strand (interface.json: one rectangle per pin, on the cell's edge) in the plan's
    form (edge, position along the edge, layer, width). A second pin of one port ("zx (second pin, same net)") gets the
    key `name.2`."""
    w, h = d["size_um"]
    pins = {}
    for name, q in d["pins"].items():
        key = name.split(" (")[0]
        if key != name:
            assert "second pin" in name and key in d["pins"], name
            key += ".2"
        x1, y1, x2, y2 = q["rect"]
        if abs(y2 - h) < 1e-6:
            e, pos, pw = "T", (x1 + x2) / 2, x2 - x1
        elif abs(x2 - w) < 1e-6:
            e, pos, pw = "R", (y1 + y2) / 2, y2 - y1
        elif abs(y1) < 1e-6:
            e, pos, pw = "B", (x1 + x2) / 2, x2 - x1
        elif abs(x1) < 1e-6:
            e, pos, pw = "L", (y1 + y2) / 2, y2 - y1
        else:
            raise AssertionError(f"pin {name} is not on an edge: {q}")
        pins[key] = (e, round(pos, 4), EDGE_LAYER[q["layer"]], round(pw, 4))
    return pins


def _rblock():
    """Four programmable resistors side by side, drawn by the cells strand (cells/layout/pw4_rblock4.mag and the cells under
    it; v4_build.py copies them into the build area). Each resistor is a chain of transistors, so its two ends are at the
    two ends of its cell. The order puts the pins of each bus next to each other:
      cell 0  shunt of edge 1   m1x - REF          cell 1  bridge of edge 1   zx - f1x
      cell 2  bridge of edge 2  zx - f2x           cell 3  shunt of edge 2    m2x - REF
    Outline, pins and capacitor rectangles are read from cells/interface.json (key pw4_rblock4): nothing of the cell is
    written here. Pins carry the netlist's port names (circuit/v4_netlist.py, pw4_rblock4); the strobes are numbered by
    address (we0 shunt of edge 1, we1 shunt of edge 2, we2 bridge of edge 1, we3 bridge of edge 2). The bus zx has two pins
    (one per bridge), joined inside the row: keys `zx` and `zx.2`. The supply pin vdd is on the EAST edge (since
    2026-11-15; it was on the north edge under the decoder's supply pin while the row was a stand-in).
    plates: the capacitor-layer rectangles; the router keeps chip metal3 1.6 um from each (v4_route.py)."""
    d = json.loads((CELLS_STRAND / "interface.json").read_text())["pw4_rblock4"]
    assert d["outline"][:2] == [0, 0] and tuple(d["size_um"]) == (113.4, 14.9), ("the row's outline changed: a decision, not a rerun", d["size_um"])
    pins = _edge_pins(d)
    want = {"we0": 24.8, "m1x": 27.2, "f1x": 29.6, "we2": 32.0, "zx": 55.2, "zx.2": 57.6, "we3": 60.0, "f2x": 84.0, "m2x": 86.4, "we1": 88.8, "clampw": 50.4}
    for name, x in want.items():                       # the agreed places on the north edge (on the router's grid)
        assert pins[name] == ("T", x, "met2", 0.3), (name, pins[name])
    assert pins["vdd"] == ("R", 0.9, "met2", 0.3) and pins["dac"] == ("R", 1.7, "met1", 0.3), (pins["vdd"], pins["dac"])
    assert pins["ref"] == ("R", 4.9, "met2", 0.3) and pins["vss"] == ("R", 6.5, "met1", 0.3), (pins["ref"], pins["vss"])
    # the metal4 frames are the cells strand's to choose (DESIGN.md D8 as revised on 2026-11-15: a capacitance budget per
    # stored gate instead of the closed frame); the plan takes whatever the delivery lists and asks for no number of them
    assert len(pins) == 15 and len(d["capacitors_capm"]) == 8
    return dict(size=tuple(d["size_um"]), pins=pins, plates=[tuple(q) for q in d["capacitors_capm"]], stored=True, real=True,
                source="cells", lower_plates=[tuple(q) for q in d["lower_plates_metal3"]], frames=[tuple(q) for q in d["frames_metal4"]],
                d8_keep_um=3.0,                        # D8: new metal4, and switching metal3, stay this far from a plate edge
                what="drawn cell of the cells strand, cells/layout/pw4_rblock4.mag: four programmable resistors side by side (shunt, bridge, "
                     "bridge, shunt; 28.35 x 14.90 each, two 10.99 x 10.99 um capacitors each, a grounded metal4 frame on each cell's "
                     "outline and, round each upper plate, a metal4 ring tied to that capacitor's own end) and the five buses' clamps")


BIAS_X0, BIAS_Y0 = 321.85, 157.0                   # the bias block's lower-left corner (unchanged since revision 5)
# the ten pin rectangles agreed with the cells strand on 2026-11-15 (12:10, confirmed 13:23), in the cell's own frame:
# seven on the west edge at the top (metal1, 0.7 long, 0.3 wide), three on the south edge
BIAS_PINS = {"dac": ("metal1", (0.0, 61.05, 0.7, 61.35)), "bw1": ("metal1", (0.0, 61.85, 0.7, 62.15)), "bw2": ("metal1", (0.0, 62.65, 0.7, 62.95)),
             "bias_prog": ("metal1", (0.0, 65.05, 0.7, 65.35)), "e1": ("metal1", (0.0, 65.85, 0.7, 66.15)),
             "write": ("metal1", (0.0, 66.65, 0.7, 66.95)), "e2": ("metal1", (0.0, 67.45, 0.7, 67.75)),
             "ref": ("metal3", (1.85, 0.0, 2.45, 0.7)), "vdd": ("metal2", (10.4, 0.0, 10.7, 0.7)), "vss": ("metal2", (11.2, 0.0, 11.5, 0.7))}


def _bias():
    """The bias block, drawn by the cells strand (cells/layout/pw4_bias.mag and the cells under it; v4_build.py copies
    them into the build area): two bias words (each: a 10.99 x 10.99 um capacitor, its follower and its writer), their
    current reference (the 286 kohm strip pair), the gates that make the two write strobes from WRITE and the two
    external-bias enable lines, and the pull-downs of BIAS_PROG and WRITE.
    Outline, pins and capacitor rectangles are read from cells/interface.json (key pw4_bias): nothing of the cell is
    written here but what was AGREED, and the run stops if the delivered cell differs from it: the outline 12 x 68 um
    (lower-left corner at chip (321.85, 157.0), top at chip y 225.0) and the ten pin rectangles of BIAS_PINS. The seven
    signal pins are on the WEST edge at the top, above the reference ladder (whose metal3 and metal4 reach chip x 321.01
    up to y 216.5); REF (metal3) and the two supplies (metal2) on the south edge.
    plates: the two capacitor-layer rectangles (the router keeps chip metal3 1.6 um from each, v4_route.py). The second
    one lies at the top of the block beside the west pins (cell y 55.755 .. 66.745; the outline of 12:10 had it at
    46.555 .. 57.545). The cell uses metal1 to metal4 across its whole outline: no chip wire crosses it (the router
    closes every placed cell's box on all four metals)."""
    d = json.loads((CELLS_STRAND / "interface.json").read_text())["pw4_bias"]
    assert d["outline"] == [0, 0, 12.0, 68.0] and tuple(d["size_um"]) == (12.0, 68.0), ("the bias block's outline changed: a decision, not a rerun", d["outline"])
    got = {name: (q["layer"], tuple(q["rect"])) for name, q in d["pins"].items()}
    assert got == BIAS_PINS, ("the bias block's pins are not the agreed rectangles", {k: (got.get(k), BIAS_PINS.get(k)) for k in set(got) | set(BIAS_PINS) if got.get(k) != BIAS_PINS.get(k)})
    pins = _edge_pins(d)
    assert set(pins) == set(BIAS_PINS) and all(pins[k][0] == ("B" if k in ("ref", "vdd", "vss") else "L") for k in pins), pins
    plates = [tuple(q) for q in d["capacitors_capm"]]
    assert len(plates) == 2 and all(abs((x2 - x1) - 10.99) < 1e-6 and abs((y2 - y1) - 10.99) < 1e-6 and 0 < x1 and x2 < 12.0 and 0 < y1 and y2 < 68.0
                                    for x1, y1, x2, y2 in plates), plates
    return dict(size=tuple(d["size_um"]), pins=pins, plates=plates, stored=True, real=True, source="cells",
                lower_plates=[tuple(q) for q in d["lower_plates_metal3"]], metal4=[tuple(q) for q in d["metal4_shapes"]],
                what="drawn cell of the cells strand, cells/layout/pw4_bias.mag: two bias words (each a 10.99 x 10.99 um capacitor, its follower "
                     "and writer), their current reference (the 286 kohm strip pair), the gates that make the two write strobes from WRITE "
                     "and the two external-bias enable lines, and the pull-downs of BIAS_PROG and WRITE")


CTL_X0, CTL_Y0 = 34.0, 218.2                       # the decoder (instance DEC)
MID_X0, MID_Y0 = 231.6, 162.0                      # 2.4 um east of the accepted metal2 wire of an input bit, so that the midpoints' metal2 pins can be reached
CELLS = {                                          # (the revision-5 outline of the decoder, pw4_control, is in rev5/v4_plan.py)
    "pw4_rblock4": _rblock(),
    "pw4_bias": _bias(),
}

# ---------------------------------------------------------------- the drawn cells: outline and pins from their own result files
def _real(cell):
    return json.loads((OUT / "cellwork" / "results" / f"{cell}_cell.json").read_text())


REAL = {c: _real(c) for c in ("pw4_nrn_h", "pw4_units3d", "pw4_nrn_z", "pw4_units5", "pw4_dacgate", "pw4_mid", "pw4_decoder")}


def rpin(cell, name):
    """Centre of a drawn cell's pin in the cell's own frame."""
    r = REAL[cell]["pins"][name]["rect"]
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


for _c, _d in REAL.items():
    CELLS[_c] = dict(size=tuple(_d["size_um"]), pins={}, plates=[], stored=False, real=True, what=f"drawn cell, cellwork/layout/{_c}.mag")
CELLS["pw4_mid"]["pins"] = dict(m1=("L", rpin("pw4_mid", "m1")[1], "met2", 0.3), m2=("L", rpin("pw4_mid", "m2")[1], "met2", 0.3),
                                b1=("T", rpin("pw4_mid", "b1")[0], "met2", 0.3), b2=("T", rpin("pw4_mid", "b2")[0], "met2", 0.3),
                                iso=("R", rpin("pw4_mid", "iso")[1], "met1", 0.3), vss=("B", rpin("pw4_mid", "vss")[0], "met1", 0.3))

# The drawn decoder, its pins under the netlist's names (a0 = ui[7], a1 = uio[2]; strobes by address); the order is the
# order of its bottom edge from west to east, a1 on the top edge.
_DEC = ("vss", "we0", "vdd", "we2", "clampw", "we3", "we1", "iso", "res_sel", "a0", "weight_prog", "write", "a1")
CELLS["pw4_decoder"]["pins"] = {p: (("T" if p == "a1" else "B"), rpin("pw4_decoder", p)[0], "met2", 0.3) for p in _DEC}

# ---------------------------------------------------------------- placement (lower-left corner, no rotation)
PLACE = [
    ("RBLOCK", "pw4_rblock4", RB_X0, RB_Y0),
    ("DEC", "pw4_decoder", CTL_X0, CTL_Y0),
    ("BIAS", "pw4_bias", BIAS_X0, BIAS_Y0),
    ("MID", "pw4_mid", MID_X0, MID_Y0),
    ("DACG", "pw4_dacgate", DG_X, DG_Y),
]
NEURONS = ("H1", "H2", "Z")
HAND_ONLY = ("nm", "q1s", "q2s", "qzs", "nd", "dn1", "dn2")      # nets that exist only as hand-drawn metal between drawn cells inside a neuron
ORIENT = {}                                        # instance -> "" | "h" (mirrored left-right, Z) | "v" (upside down, H2)


def to_global(inst, x, y):
    a, b, d, e, c, f = chip.transform(inst)
    return round(a * x + b * y + c, 4), round(d * x + e * y + f, 4)


def to_local(inst, gx, gy):
    a, b, d, e, c, f = chip.transform(inst)
    return round((gx - c) / a, 4), round((gy - f) / e, 4)


def gbox(inst, x1, y1, x2, y2):
    (ax, ay), (bx, by) = to_global(inst, x1, y1), to_global(inst, x2, y2)
    return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))


def ring_corner(cell):
    """Where a drawn cell's ground ring has its outer lower-left corner, in the cell's own frame: (0, 0) unless the cell's
    outline is larger than its ring (pw4_units3d: the capacitor's plate)."""
    return tuple(REAL[cell].get("ring_outer", (0.0, 0.0))[:2])


def site_cells():
    """(instance name, cell, lower-left x, y on the chip) of the drawn cells inside the neurons; ORIENT says how each is turned."""
    out = []
    for n in NEURONS:
        ax, ay = ring_corner(EASTC[n])
        for tag, cell, x0, y0 in (("NRN", WEST[n], XW, YW[n]), ("U3", EASTC[n], XE - ax, YE[n] - ay)):
            w, h = CELLS[cell]["size"]
            b = gbox(n, x0, y0 + DY[n], x0 + w, y0 + DY[n] + h)
            out.append((f"{tag}_{n}", cell, b[0], b[1]))
            ORIENT[f"{tag}_{n}"] = {"H1": "", "H2": "v", "Z": "h"}[n]
    return out


ALL_PLACE = PLACE + site_cells()


def bbox(inst):
    for n, cell, x, y in ALL_PLACE:
        if n == inst:
            w, h = CELLS[cell]["size"]
            return (x, y, x + w, y + h)
    raise KeyError(inst)


def pin(inst, name):
    """Placed pin of a new cell, as chip.pin(): (x, y) 0.35 um inside the edge, layer, outward normal, metal width."""
    cell = next(c for n, c, *_ in ALL_PLACE if n == inst)
    x1, y1, x2, y2 = bbox(inst)
    e, pos, layer, w = CELLS[cell]["pins"][name]
    n = chip.NORMAL[e]
    pt = {"L": (x1, y1 + pos), "R": (x2, y1 + pos), "B": (x1 + pos, y1), "T": (x1 + pos, y2)}[e]
    return (round(pt[0] - 0.35 * n[0], 4), round(pt[1] - 0.35 * n[1], 4)), layer, n, w


# ---------------------------------------------------------------- hand-drawn metal inside the neurons and inside RW
W1 = 0.3


def _hwire(inst, layer, x1, x2, y, net, w=W1):
    return [layer, *gbox(inst, min(x1, x2), y - w / 2, max(x1, x2), y + w / 2), net]


def _vwire(inst, layer, x, y1, y2, net, w=W1):
    return [layer, *gbox(inst, x - w / 2, min(y1, y2), x + w / 2, max(y1, y2)), net]


def handmade():
    """Metal drawn by hand, on the chip's top level: dict(rects=[[layer, x1, y1, x2, y2, net]], vias=[[kind, x, y, net]], edge=[...]).

    Per neuron, between the inner channel, its two drawn cells and its amplifier-side edge:
      taps    y: metal2 straight from the accepted y wire into the west cell; p and q: each accepted wire continued up its
              own empty metal2 track in the inner channel, a via, metal1 into the west cell
      links   in the gap between the two cells: the switched side of the helper beside R7 (qs), REF from the control
              block's wire into the cells that end on it, the two cells' ground rings joined, the east ring to the
              neuron's ground line; in the output neuron also the DAC edge's node nm
      exits   to the neuron's edge, where the chip router takes over: the bus and the gate line
      output neuron only: nd along the top of the two cells and up into the DAC edge's gate; the gate line from the west
              cell's top up into it; its supply from the control block's feed, its ground from the control block's rail
              continued, one via from its REF pad to the accepted metal3 REF wire above it, and the DAC line from its top
              to the neuron's top edge
    RW: the two midpoint taps (see MID_TAPS above).
    edge:   (name, net, point 0.35 um inside the edge, layer, outward normal): the router's terminals at the cells' edges."""
    rects, vias, edge = [], [], []
    m1 = 0.23
    for n in NEURONS:
        dy = DY[n]
        k = {"H1": "1", "H2": "2", "Z": "z"}[n]
        ynet, pnet, qnet = {"H1": "f1", "H2": "f2", "Z": "z"}[n], f"p{k}", f"q{k}"
        busnet, qs = f"{ynet}x", ("qzs" if n == "Z" else f"q{k}s")
        wc, ec = WEST[n], EASTC[n]
        yw, ye = YW[n] + dy, YE[n] + dy
        wp = lambda name: (XW + rpin(wc, name)[0], yw + rpin(wc, name)[1])
        ax, ay = ring_corner(ec)
        ep = lambda name: (XE - ax + rpin(ec, name)[0], ye - ay + rpin(ec, name)[1])
        ro = REAL[ec].get("ring_outer")
        xwr, xer = XW + CELLS[wc]["size"][0], XE + (ro[2] - ro[0] if ro else CELLS[ec]["size"][0])        # the two rings' right edges
        a = chip.transform(n)[0]

        def H(layer, x1, x2, y, net, w=m1):
            rects.append(_hwire(n, layer, x1, x2, y, net, w))

        def V(layer, x, y1, y2, net, w=m1):
            rects.append(_vwire(n, layer, x, y1, y2, net, w))

        def via(kind, x, y, net):
            vias.append([kind, *to_global(n, x, y), net])

        # ---- taps
        yy, yq, yp = wp("y")[1], wp("q")[1], wp("p")[1]
        H("metal2", X_Y, XW + 0.1, yy, ynet, 0.3)
        V("metal2", X_Q, END_Q - 0.2, yq + 0.18, qnet, W1)
        via("via1", X_Q, yq, qnet)
        H("metal1", X_Q - 0.18, XW + 0.3, yq, qnet)
        V("metal2", X_P, END_P - 0.2, yp + 0.18, pnet, W1)
        via("via1", X_P, yp, pnet)
        H("metal1", X_P - 0.18, XW + 0.3, yp, pnet)
        # ---- the two ground rings joined; the east ring to the neuron's ground line
        r = REAL[wc]["pins"]["vss"]["rect"]
        ys = yw + (r[1] + r[3]) / 2
        H("metal1", xwr - 0.25, XE + 0.2, ys, "vss")
        via("mcon", XE + 0.085, ys, "vss")
        yg = ep("vss")[1]
        H("metal1", xer - 0.25, X_GND, yg, "vss")
        via("via1", X_GND, yg, "vss")
        if n != "Z":
            # gate line: straight out on its row
            yi = wp("iso")[1]
            H("metal1", xwr - 0.1, NW, yi, "iso")
            edge.append((f"{n}.iso", "iso", to_global(n, NW - 0.35, yi), "met1", (a, 0)))
            # bus: metal2 down across the gate line's row to its own row
            yb, xb, rb = wp("bus")[1], 86.2, ROW_BUS + dy
            H("metal2", xwr - 0.1, xb + 0.15, yb, busnet, 0.3)
            V("metal2", xb, rb - 0.18, yb + 0.15, busnet, 0.3)
            via("via1", xb, rb, busnet)
            H("metal1", xb - 0.18, NW, rb, busnet)
            edge.append((f"{n}.b_y", busnet, to_global(n, NW - 0.35, rb), "met1", (a, 0)))
            # qs: up to the east cell's switched end (pin a, the sixth leg from the top)
            yqs, xq, ybe = wp("qs")[1], 87.4, ep("a")[1]
            H("metal1", xwr - 0.1, xq + m1 / 2, yqs, qs)
            V("metal1", xq, yqs - m1 / 2, ybe + m1 / 2, qs)
            H("metal1", xq - m1 / 2, XE + 0.3, ybe, qs)
            # REF: the east cell's own. Its pin b ends in two vias that stand on the control block's ref wire (metal2), which
            # crosses the cell exactly there; nothing is drawn by hand.
            assert abs(XE - ax + REAL[ec]["ref_stack"][0] - X_REF2) < 1e-6, "the east cell's REF vias are not on the control block's ref wire"
            # dn (the damping switch's far side): metal2 east along the bottom from the west cell, up the gap on the column
            # of the east cell's stack of vias, one via onto the east cell's own metal1 of its damping strip. It crosses
            # the bus row, the gate line and qs on metal2; the control block's ref wire is 0.77 um east of it.
            ydn, xdn, ydp = wp("dn")[1], XE - ax + REAL[ec]["stack"][0], ep("dn")[1]
            H("metal2", xwr - 0.1, xdn + 0.15, ydn, f"dn{k}", 0.3)
            V("metal2", xdn, ydn - 0.15, ydp + 0.18, f"dn{k}", 0.3)
            via("via1", xdn, ydp, f"dn{k}")
            continue
        # ---- the output neuron
        # gate line: down in the gap to the row over the east cell's lower ring bar (not over a strip)
        yi, xi, ri = wp("iso")[1], 87.5, ROW_BUS + dy
        H("metal1", xwr - 0.1, xi + m1 / 2, yi, "iso")
        V("metal1", xi, ri - m1 / 2, yi + m1 / 2, "iso")
        H("metal1", xi - m1 / 2, NW, ri, "iso")
        edge.append(("Z.iso", "iso", to_global(n, NW - 0.35, ri), "met1", (a, 0)))
        # bus: metal2 down across the gate line to the free row under the east cell
        yb, xb, rb = wp("bus")[1], 86.7, ROW_LOW + dy
        H("metal1", xwr - 0.1, xb + 0.18, yb, busnet)
        via("via1", xb, yb, busnet)
        V("metal2", xb, rb - 0.18, yb + 0.18, busnet, 0.3)
        via("via1", xb, rb, busnet)
        H("metal1", xb - 0.18, NW, rb, busnet)
        edge.append(("Z.b_y", busnet, to_global(n, NW - 0.35, rb), "met1", (a, 0)))
        # nm: metal2 up the gap, then metal1 under the ref wire into the east cell
        ynw, yne, xn, xv = wp("nm")[1], ep("nm")[1], 85.9, 88.2
        H("metal2", xwr - 0.1, xn + 0.15, ynw, "nm", 0.3)
        V("metal2", xn, ynw - 0.15, yne + 0.15, "nm", 0.3)
        H("metal2", xn - 0.15, xv + 0.18, yne, "nm", 0.3)
        via("via1", xv, yne, "nm")
        H("metal1", xv - 0.18, XE + 0.3, yne, "nm")
        # qs
        yqw, yqe, xq = wp("qs")[1], ep("qs")[1], 87.6
        H("metal1", xwr - 0.1, xq + m1 / 2, yqw, qs)
        V("metal1", xq, yqe - m1 / 2, yqw + m1 / 2, qs)
        H("metal1", xq - m1 / 2, XE + 0.3, yqe, qs)
        # REF into both cells
        yre, yrw = ep("ref")[1], wp("ref")[1]
        H("metal1", X_REF2 - 0.18, XE + 0.3, yre, "ref")
        via("via1", X_REF2, yre, "ref")
        H("metal1", xwr - 0.1, X_REF2 + 0.18, yrw, "ref")
        via("via1", X_REF2, yrw, "ref")
        # the DAC edge's gate: its pins in Z's local frame (the gate cell is placed in the chip's frame)
        gate = lambda name: to_local(n, DG_X + rpin("pw4_dacgate", name)[0], DG_Y)
        x_nd, ybot = gate("nd")
        x_is, x_vs, x_vd, x_da = gate("iso")[0], gate("vss")[0], gate("vdd")[0], gate("dac")[0]
        ytop = to_local(n, 0.0, DG_Y + CELLS["pw4_dacgate"]["size"][1])[1]
        # nd: from the east cell's upper left along the top of both cells, then metal2 up into the gate
        ynd, xd, yr = ep("nd")[1], 89.75, yw + CELLS[wc]["size"][1] + 0.5
        H("metal1", xd - m1 / 2, XE + 0.3, ynd, "nd")
        V("metal1", xd, ynd - m1 / 2, yr + m1 / 2, "nd")
        H("metal1", x_nd - 0.18, xd + m1 / 2, yr, "nd")
        via("via1", x_nd, yr, "nd")
        V("metal2", x_nd, yr - 0.18, ybot + 0.3, "nd", 0.3)
        # gate line: from the west cell's top exit, a metal1 step above nd's row, metal2 up into the gate
        xt, ywt, yi2 = XW + rpin(wc, "iso_top")[0], yw + CELLS[wc]["size"][1], yr + 0.78
        V("metal2", xt, ywt, yi2 + 0.18, "iso", 0.3)
        via("via1", xt, yi2, "iso")
        H("metal1", xt - 0.18, x_is + 0.18, yi2, "iso")
        via("via1", x_is, yi2, "iso")
        V("metal2", x_is, yi2 - 0.18, ybot + 0.3, "iso", 0.3)
        # supply and ground of the gate
        via("via1", x_vd, VDD_ROW, "vdd")
        V("metal2", x_vd, VDD_ROW - 0.15, ybot + 0.3, "vdd", 0.3)
        H("metal1", x_vs - 0.18, X_VSS_END, VSS_RAIL, "vss", 0.3)
        via("via1", x_vs, VSS_RAIL, "vss")
        V("metal2", x_vs, VSS_RAIL - 0.15, ybot + 0.3, "vss", 0.3)
        # REF: one via from the gate's pad up to the accepted metal3 wire above it
        rx, ry = rpin("pw4_dacgate", "ref")
        vias.append(["via2", round(DG_X + rx, 4), round(DG_Y + ry, 4), "ref"])
        # the DAC line: from the gate's top to the neuron's top edge
        V("metal2", x_da, ytop - 0.3, NH, "ext_in", 0.3)
        edge.append(("Z.dacg", "ext_in", to_global(n, x_da, NH - 0.35), "met2", (0, 1)))
    # bw1, bw2 onto the external-bias switches' ext pins (see CUT_ACCEPTED)
    for net, inst in EXT_JOIN.items():
        (px, py), layer, nrm, _ = chip.pin(inst, "ext")
        assert layer == "met2" and tuple(nrm) == (0, 1), (inst, layer, nrm)
        rects.append(["metal2", round(px - 1.0, 4), round(py - 0.15, 4), round(px + 0.15, 4), round(py + 0.15, 4), net])
        edge.append((f"{inst}.{net}", net, (round(px - 0.85, 4), py), "met2", (0, 1)))
    # the midpoint taps inside RW and just east of it
    for net, t in MID_TAPS.items():
        h = t["w"] / 2
        rects += [["metal1", t["x"] - W1 / 2, t["y_head"], t["x"] + W1 / 2, t["row"] + h, net],
                  ["metal1", t["x"] - W1 / 2, t["row"] - h, t["x_jog"] + W1 / 2, t["row"] + h, net],
                  ["metal1", t["x_jog"] - W1 / 2, t["y_exit"] - W1 / 2, t["x_jog"] + W1 / 2, t["row"] + h, net]]
        edge.append((f"RW.{net}", net, (t["x_jog"], t["y_exit"]), "met1", (1, 0)))
    return dict(rects=rects, vias=vias, edge=edge, check_only=[])


# ---------------------------------------------------------------- nets
# terminal: ("C", instance, pin) a new cell's pin | ("E", edge name) a hand-drawn row at a cell's edge |
#           ("TT", pin) a Tiny Tapeout pin | ("NEAR", instance, pin) a free grid point beside an ACCEPTED cell's pin (see REPORT.md)
# extends: the accepted net this net is part of (its new wires grow from the accepted net's own wires)
def nets():
    n = {}

    def add(name, kind, terms, extends=None, stripes=None):
        n[name] = dict(kind=kind, terms=terms, extends=extends, stripes=stripes)
    # supplies: on wires of their own to a stripe
    add("vss_strip", "supply", [("C", "RBLOCK", "vss"), ("C", "DEC", "vss")], extends="vss", stripes=["GND_M1"])
    add("vdd_strip", "supply", [("C", "DEC", "vdd"), ("C", "RBLOCK", "vdd")], extends="vdd", stripes=["VDD_M"])
    add("vss_bias", "supply", [("C", "BIAS", "vss")], extends="vss", stripes=["GND_R"])
    add("vdd_bias", "supply", [("C", "BIAS", "vdd")], extends="vdd", stripes=["VDD_R"])
    add("vss_mid", "supply", [("C", "MID", "vss")], extends="vss", stripes=["GND_R"])
    # REF and the DAC line (the accepted ext_in, behind the 10 kohm pin resistor)
    add("ref", "ref", [("C", "RBLOCK", "ref"), ("C", "BIAS", "ref")], extends="ref")
    add("ext_in", "analog", [("E", "Z.dacg"), ("C", "RBLOCK", "dac"), ("C", "BIAS", "dac")], extends="ext_in")
    # the two midpoints of the fixed hidden-to-output edges, from the block to their switches: part of the fixed network
    add("mid1", "bus", [("E", "RW.mid1"), ("C", "MID", "m1")])
    add("mid2", "bus", [("E", "RW.mid2"), ("C", "MID", "m2")])
    # the five buses: behind the isolation switches, clamped to REF in fixed mode
    add("zx", "bus", [("E", "Z.b_y"), ("C", "RBLOCK", "zx.2"), ("C", "RBLOCK", "zx")])
    add("f1x", "bus", [("E", "H1.b_y"), ("C", "RBLOCK", "f1x")])
    add("f2x", "bus", [("E", "H2.b_y"), ("C", "RBLOCK", "f2x")])
    add("m1x", "bus", [("C", "MID", "b1"), ("C", "RBLOCK", "m1x")])
    add("m2x", "bus", [("C", "MID", "b2"), ("C", "RBLOCK", "m2x")])
    # the stored biases' read lines, to the external-bias switches' ext pins (the accepted ext_in stubs there are cut)
    add("bw1", "bus", [("C", "BIAS", "bw1"), ("E", "EXT1.bw1")])
    add("bw2", "bus", [("C", "BIAS", "bw2"), ("E", "EXT2.bw2")])
    # lines that do not switch while the network computes: the mode pins, RES_SEL, the gate line of the small
    # switches, the buses' clamp, and the two external-bias enable lines (the bias words' address)
    add("bias_prog", "static", [("TT", PIN["bias_prog"]), ("C", "BIAS", "bias_prog")])
    add("weight_prog", "static", [("TT", PIN["weight_prog"]), ("C", "DEC", "weight_prog")])
    add("res_sel", "static", [("TT", PIN["res_sel"]), ("C", "DEC", "res_sel")])
    add("iso", "static", [("C", "DEC", "iso"), ("E", "H2.iso"), ("E", "H1.iso"), ("E", "Z.iso"), ("C", "MID", "iso")])
    add("clampw", "static", [("C", "DEC", "clampw"), ("C", "RBLOCK", "clampw")])
    add("ext_en1", "static", [("C", "BIAS", "e1")], extends="ext_en1")
    add("ext_en2", "static", [("C", "BIAS", "e2")], extends="ext_en2")
    # The resistor words' address is two of the accepted select lines, tapped. They DO switch while the network computes
    # (the host changes what it watches), so their new branches are routed as switching wires.
    add("obs_sel2", "switching", [("C", "DEC", "a0")], extends="obs_sel2")
    add("obs2_sel0", "switching", [("C", "DEC", "a1")], extends="obs2_sel0")
    # wires that switch: WRITE and the write strobes
    add("write", "switching", [("TT", PIN["write"]), ("C", "DEC", "write"), ("C", "BIAS", "write")])
    for we in ("we0", "we2", "we3", "we1"):          # by position in the row (as routed since r5), named by address
        add(we, "switching", [("C", "DEC", we), ("C", "RBLOCK", we)])
    return n


# The two midpoints' buses are routed LAST. A midpoint sits behind 100 kohm from either neuron, so a long bus costs it
# least, and the gap under the echo buffers is full once five buses pass it: routed with the other buses they took the
# short ways, and WRITE (594 um instead of 306), the address tap of ui[7] (246 um instead of 45) and the gate line then
# went round the block (tried 2026-11-14; five orders compared, REPORT.md step 5).
#
# The supply of the row and of the decoder (vdd_strip) is routed LAST since 2026-11-15 (it was second). The row's supply pin
# moved from the north edge to the east edge (metal2, chip (117.8, 196.4)), into the 6.4 um gap between the row and the
# supply stripe that four buses and the DAC line also climb through. Routed second, its metal3 took the track y = 196.4
# across that gap (x 118.6 to 124.6); f1x, which had used that track, then changed layers at (118.8, 194.8), the one
# point through which the single free track along the row's south edge (y = 194.8; metal1 there is an accepted wire) is
# entered, on metal2, metal3 and metal4. m2x, the last net, uses that track: it found no way that keeps two tracks from
# every switching wire and went round by the west edge of the chip (598.4 um instead of 396.8, 4.8 um of it inside a
# keep-away zone). Routed last, the supply takes what is left (102.4 um, 104.8 before) and every other net is within
# 5 um of the build before the pin moved, except m2x, which is 200 um SHORTER (the north edge has one pin fewer).
# Nine orders tried (route_trials.py, results/r6_route_trials.json); ORDER_BEFORE is the order up to then.
ORDER_BEFORE = ["vss_strip", "vdd_strip", "vss_bias", "vdd_bias", "vss_mid", "ref", "ext_in",
                "mid1", "mid2", "zx", "f1x", "f2x", "bw1", "bw2",
                "bias_prog", "write", "weight_prog", "res_sel", "ext_en1", "ext_en2", "obs2_sel0", "obs_sel2",
                "we0", "we2", "we3", "we1", "iso", "clampw", "m1x", "m2x"]
ORDER = [n for n in ORDER_BEFORE if n != "vdd_strip"] + ["vdd_strip"]
# 2026-11-15, 15:12, with DESIGN.md D8's keep-away round the row's plates (new metal4, and switching metal3, 3 um from a
# plate edge): the write strobe we1 is routed just before the bus zx. With we1 in its old place (after the buses) it left
# its pin beside zx's riser, 1.6 um of zx within two tracks of it; routed first, zx keeps clear of it. Three orders tried
# (results/r6_route_trials.json, d8_*): this one keeps every rule and is the shortest (3,800.0 um against 3,856.8).
ORDER.remove("we1")
ORDER.insert(ORDER.index("zx"), "we1")
if os.environ.get("V4_ORDER") == "before":         # the order up to 2026-11-15, for route_trials.py and for looking again
    ORDER = list(ORDER_BEFORE)
# buses that also pay for running beside the quiet wires below and beside the other buses (v4_route.py): the two long ones
KEEP_FROM_QUIET = ("m1x", "m2x")
# accepted nets that every new switching wire keeps two tracks from, and may cross but not run along one layer up or down
PROTECTED_ACCEPTED = {"h1", "h2", "f1", "f2", "z", "natural1", "natural2", "bias1", "bias2", "sense2", "ref", "sense", "obs_out",
                      "bias1_in", "bias2_in", "sel1_ladder", "sel2_ladder"}
# Metal4 over the echo buffers (the accepted router allows it there) is the widest way between the strip above H2 and the
# middle channel. The four pin nets come down on metal4 right there; while they are routed that metal4 is closed to them, so
# that they leave above the echo buffers and do not cut it.
M4_KEEP = dict(box=(95.7, 212.9, 111.9, 217.9), nets=("write", "res_sel", "bias_prog", "weight_prog"))
# Under the four new pins only metal4 is open (metal1 to metal3 carry the echo buffers' wires). Each pin's net keeps its own
# column of metal4 grid points below the pin, to a depth of its own, so that the four leave without crossing: WEIGHT_PROG
# (westmost pin) west, RES_SEL west under it, BIAS_PROG (eastmost) east, WRITE both ways under all of them.
PIN_DEPTH = {PIN["weight_prog"]: 2, PIN["res_sel"]: 3, PIN["bias_prog"]: 2, PIN["write"]: 5}
# accepted cells over which the accepted router allowed metal4 and a NEW wire may not go: resistor strips lie in them,
# and in the draft also none over the bias selectors and the external-bias switches. Over the first observer the accepted
# rule is kept (metal4 allowed): with it closed as well, four connections found no way (tried 2026-11-14)
NO_NEW_M4 = ("RSENSE", "RW", "PINRES", "OBS2", "SEL1", "SEL2", "EXT1", "EXT2")


if __name__ == "__main__":
    h = handmade()
    print("placed:", [(n, c, round(x, 3), round(y, 3)) for n, c, x, y in ALL_PLACE])
    print("hand-drawn rects", len(h["rects"]), "vias", len(h["vias"]), "edge terminals", len(h["edge"]))
    for e in h["edge"]:
        print("  ", e)
    for c, v in CELLS.items():
        print(c, v["size"], {k: p[:2] for k, p in v["pins"].items()})
