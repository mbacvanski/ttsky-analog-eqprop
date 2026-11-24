"""Variant AJ (the lean-neuron chip) in the Tiny Tapeout 2x2 analog tile: placement, supplies, connectivity, pins.

Tile 334.88 x 225.76 um. Coordinates in um, lower-left corner of each placed cell, orientation in Magic's words.

Arrangement (see ../../CHIP_2X2.md for the picture and the reasons):
  left column    H1 at the bottom, H2 above it upside down, the 8-channel observer in the band between them;
                 the echo buffers under the digital pins at the top
  middle channel x 120.5..130.5: three supply stripes (ground, VDD, ground) on metal4, over the tile's full height.
                 Every neuron amplifier's VDD line lies on this channel: H1 and H2 from the left, Z from the right
  bottom middle  Z, mirrored, so its amplifiers face the same channel
  above Z        the lean activation block (its pins face the channel, where the three neurons' control blocks
                 are), Z's two input resistors, the two bias selectors; above them the BIAS1 and BIAS2 buffers
                 with the external-bias switches between them
  right column   pad buffer (bottom), REF buffer, reference ladder with the 4 pF bypass capacitor on top of it
  second output  its selector (with the sense resistor) at the left end of the observer band, its buffer (a
                 seventh neuron amplifier) in the strip between the lean block and the BIAS1 buffer
  analog pins    ua[0], ua[1], ua[2] sit under the neurons on the bottom edge; their three series resistors stand
                 together at the bottom of the middle channel, the nearest free spot
  right channel  x 260..268: four more stripes (a ground and a VDD used by the ladder alone, then ground and VDD
                 for the buffers of the right column, VDD outermost so that wide metal4 straps run from it to the
                 REF and pad buffers' VDD pins on their far edge without crossing another stripe)
Connectivity follows variant AJ's xor_chip_staged (../../../amp_layout/ref/aj_native.spice) net for net.
"""
from __future__ import annotations

import json
import re

from magic_util import AMP, FLOORPLAN, PILOT, PIN_FOLDERS, RESULTS

TOP = "tt_um_mbacvanski_denseam_xor"
TILE = (334.88, 225.76)
DEF = FLOORPLAN / "template" / "tt_analog_2x2.def"
# AJ's chip bench (xor_matched_tb) as Mesa netlists it from main's sheets (wired_deck.py fetch --write-deck, round
# 1p): the netlist the layout is checked against.
DECK = PILOT / "ref" / "aj_native_chip.spice"

# ---------------------------------------------------------------- supplies
# Tiny Tapeout: supply pins are vertical metal4 stripes, at least 1.2 um wide, from within 10 um of the bottom
# edge to within 10 um of the top edge; a design may have several stripes per net (tinytapeout.com/specs/analog).
# name: (TT pin, x1, x2, who uses it)
STRIPE_Y = (5.0, 220.76)
STRIPE = {
    "GND_M1": ("VGND", 121.0, 122.6, "H1 and H2 ground; unused Tiny Tapeout outputs tied low"),
    "VDD_M": ("VDPWR", 124.0, 127.0, "all six neuron amplifiers, the control logic, BIAS1 buffer, lean block, observer"),
    "GND_M2": ("VGND", 128.4, 130.0, "Z ground; the lean block's own ground wire; BIAS1 buffer"),
    "GND_LAD": ("VGND", 260.0, 261.2, "bottom end of the reference ladder and its bypass capacitor, nothing else"),
    "VDD_LAD": ("VDPWR", 261.9, 263.1, "top end of the reference ladder, nothing else"),
    "GND_R": ("VGND", 263.7, 265.3, "REF, pad and BIAS2 buffers, bias selectors"),
    "VDD_R": ("VDPWR", 265.9, 267.5, "REF, pad and BIAS2 buffers, bias selectors, lean block"),
}
# Routing nets and the stripes each may end on. The ladder's two ends and the lean block's ground are nets of
# their own in the router, so that no other block's supply wire can share metal with them; electrically they
# are VDPWR and VGND (joined in Tiny Tapeout's grid, outside the tile).
SUPPLY_NETS = {
    "vdd": ["VDD_M", "VDD_R"],
    "vss": ["GND_M1", "GND_M2", "GND_R"],
    "vdd_lad": ["VDD_LAD"],
    "vss_lad": ["GND_LAD"],
    "vss_lean": ["GND_M2"],
}
SUPPLY_OF = {"vdd": "VDPWR", "vdd_lad": "VDPWR", "vss": "VGND", "vss_lad": "VGND", "vss_lean": "VGND"}
# Drawn supply straps, placed before any signal is routed (filled in by supply_straps() below):
#   STRAPS          (routing net, layer, x1, y1, x2, y2)   metal
#   STRAP_CONTACTS  (kind, x1, y1, x2, y2, routing net)    via areas; Magic fills each with as many cuts as fit
STRAPS: list = []
STRAP_CONTACTS: list = []
LAYER_NAME = {"met1": "metal1", "met2": "metal2", "met3": "metal3", "met4": "metal4"}

# ---------------------------------------------------------------- cells
# Planned outlines for cells that are not drawn yet (um). A measured <cell>_pins.json replaces the entry.
PLANNED = {
}

# Planned pins of those cells (edge, position along the edge, layer), used until the cell is measured.
# Neurons: every signal leaves at the top edge near the amplifier side (x 67..112 of 119); VDD and ground leave
# on the amplifier-side edge as metal3 tabs that the supply bridges below meet (they are not routed).
PLANNED_PINS = {
    "aj_neuron_h": dict(bpin=("T", 67.48, "met2"), y=("T", 71.68, "met2"), reset=("T", 90.5, "met2"),
                        hold_in=("T", 92.375, "met2"), h=("T", 100.0, "met2"), ref=("T", 104.0, "met3"),
                        natural=("T", 112.06, "met2")),
    "aj_neuron_z": dict(y=("T", 71.68, "met2"), reset=("T", 90.5, "met2"), hold_in=("T", 92.375, "met2"),
                        ref=("T", 104.0, "met3")),
    "lean_block": dict(h1=("L", 6.0, "met1"), act1=("L", 14.0, "met1"), tap=("L", 28.0, "met1"), h2=("L", 42.0, "met1"),
                       act2=("L", 50.0, "met1"), ref=("B", 0.7, "met2"), vss=("B", 66.0, "met2"), vdd=("B", 68.3, "met2")),
}
# Supply pins that the router does not connect, because drawn metal (STRAPS) does, planned with the supplies
# before any signal wire: the neurons' VDD and ground (bridges to the middle stripes) and the VDD of the REF and
# pad buffers (metal4 straps around each buffer; they draw a quarter of the chip's current each).
BRIDGED = {"H1", "H2", "Z"}
STRAPPED = {("BUF_REF", "vdd"), ("PADBUF", "vdd")}

# orientation -> (a, b, d, e): x' = a*x + b*y, y' = d*x + e*y  (Magic getcell orientations)
ORIENT = {"N": (1, 0, 0, 1), "h": (-1, 0, 0, 1), "v": (1, 0, 0, -1), "180": (-1, 0, 0, -1),
          "90": (0, 1, -1, 0), "270": (0, -1, 1, 0)}

XL, YB = 1.5, 1.6            # left and bottom margins
XM = (120.5, 130.5)          # the middle channel
NEURON_W = 114.25            # the re-packed neuron (119.0 before 2026-11-10); its amplifier edge stays on the middle
XN = XM[0] - NEURON_W        # channel, so H1 and H2 start 4.75 um further right and Z ends 4.75 um earlier
PLACE = [
    # name, cell, x, y, orient
    ("H1", "aj_neuron_h", XN, YB, "N"),
    # second output's selector (with the 100k sense resistor under it) at the left end of the observer band, the
    # first observer 4.2 um further right: its four taps branch off beside the first observer's inputs, and the
    # band's right end, where every wire between the band and the middle channel fans out, stays open (with the
    # selector there, BIAS1, BIAS2 and RESET had to go round a neuron: 600 to 730 um each)
    ("OBS2", "obs2_mux", 4.5, 87.1, "N"),         # 4.5 um from the tile edge: supply and select pins on its left edge
    ("OBS", "obs_mux", 36.2, 90.1, "N"),
    ("H2", "aj_neuron_h", XN, 110.7, "v"),
    ("ECHO", "echo", 96.0, 213.5, "h"),
    ("Z", "aj_neuron_z", XM[1], YB, "h"),
    ("LEAN", "lean_block", 133.0, 93.1, "N"),
    # second output's buffer (a seventh aj_core1p as a follower, with its inverter pair) in the strip between
    # the lean block and the BIAS1 buffer. x 147.5: a 14.5 um corridor stays between it and the middle channel
    # for the BIAS1 buffer's output and the other wires that come down from the bias row, and the BIAS1 buffer's
    # bottom-edge pin stub (x 143.5) stays clear of this amplifier's capacitors
    ("BUF2", "buf2", 147.5, 146.6, "N"),
    # the three analog pins' series resistors, at the bottom of the middle channel (see pin_cells.py)
    ("PINRES", "pin_res", 120.9, 3.6, "N"),
    ("RW", "rw_res", 205.5, 89.1, "v"),
    ("SEL1", "bias_sel", 223.3, 91.0, "N"),
    ("SEL2", "bias_sel", 223.3, 125.0, "N"),
    ("BUF_BIAS1", "az_ref1", 134.5, 174.5, "h"),
    ("EXT1", "ext_sw", 184.4, 176.5, "N"),
    ("EXT2", "ext_sw", 184.4, 195.5, "N"),
    ("BUF_BIAS2", "az_ref1", 204.5, 174.5, "N"),
    ("REFINV", "ref_inv", 190.0, 212.0, "v"),
    ("RSENSE", "rsense", 252.0, 3.2, "N"),
    ("PADBUF", "az_pad", 269.0, 2.0, "v"),
    ("BUF_REF", "az_ref4", 269.0, 66.0, "N"),
    ("LADDER", "aj_ladder", 269.0, 155.0, "v"),
]
GROUP = {"aj_neuron_h": "Neurons", "aj_neuron_z": "Neurons", "rw_res": "Neurons", "lean_block": "Activation",
         "az_ref4": "References", "az_ref1": "References", "aj_ladder": "References", "bias_sel": "References",
         "ref_inv": "References", "az_pad": "Readout", "rsense": "Readout", "pin_res": "Readout",
         "obs_mux": "Test features", "ext_sw": "Test features", "echo": "Test features",
         "obs2_mux": "Test features", "buf2": "Test features"}

# Nets the router keeps apart (as in the 3x2 chip): digital wires pay extra near analog ones, and HOLD and RESET
# pay much more near the neuron state and activation wires.
ANALOG = {"h1", "h2", "f1", "f2", "z", "natural1", "natural2", "ref", "ref_tap", "d0_tap", "d1_tap", "d2_tap", "d3_tap",
          "bias1", "bias2", "sel1_ladder", "sel2_ladder", "bias1_in", "bias2_in", "obs_out", "sense", "buffered",
          "sense2", "buf2", "ext_in"}
DIGITAL = {"bit_a", "bit_b", "reset", "hold_in", "ref_reset", "obs_sel0", "obs_sel1", "obs_sel2", "ext_en1", "ext_en2",
           "raz", "raz_b", "obs2_sel0", "obs2_sel1"} | {f"uo_out{i}" for i in range(8)}
GATE_ONLY = {"bit_a", "bit_b", "reset", "hold_in", "ref_reset", "obs_sel0", "obs_sel1", "obs_sel2", "ext_en1", "ext_en2",
             "obs2_sel0", "obs2_sel1"}

# Pin access for the amplifier cells (local um): edge, point on the edge, layer (as in the 3x2 chip).
AMP_PINS = {
    "az_ref1": dict(plus=("L", 19.5, "met2"), minus=("L", 32.4, "met2"), az=("L", 24.115, "met2"),
                    az_b=("L", 30.595, "met2"), vss=("L", 7.0, "met2"), out=("B", 35.75, "met3"),
                    ref=("R", 19.4, "met3"), vdd=("R", 20.0, "met2")),
    "az_ref4": dict(plus=("L", 57.56, "met2"), minus=("L", 70.46, "met2"), az=("L", 62.175, "met2"),
                    az_b=("L", 68.655, "met2"), vss=("L", 28.0, "met2"), out=("L", 49.45, "met3"),
                    ref=("R", 57.475, "met3"), vdd=("R", 68.06, "met2")),
    "az_pad": dict(plus=("L", 56.56, "met2"), minus=("L", 55.78, "met2"), vss=("L", 28.0, "met2"),
                   out=("L", 47.6, "met3"), vdd=("R", 50.06, "met2")),
}
EDGE_NAME = {"left": "L", "right": "R", "bottom": "B", "top": "T"}
NORMAL = {"L": (-1, 0), "R": (1, 0), "B": (0, -1), "T": (0, 1)}


def pins_file(cell):
    for folder in PIN_FOLDERS:
        p = folder / f"{cell}_pins.json"
        if p.exists():
            return p
    return None


def cell_size(cell):
    p = pins_file(cell)
    if p:
        return tuple(json.loads(p.read_text())["size_um"])
    return PLANNED[cell]


def measured(cell):
    return pins_file(cell) is not None


def cell_pins(cell):
    """{pin: (edge, position along the edge, layer, (lx, ly) point on the edge, metal width across the stub)}."""
    w, h = cell_size(cell)
    widths, labels = {}, {}
    if cell in AMP_PINS or pins_file(cell) is None:
        raw = AMP_PINS[cell] if cell in AMP_PINS else PLANNED_PINS[cell]
        widths = {n: (0.6 if v[2] == "met3" else 0.3) for n, v in raw.items()}
    else:
        raw = {}
        for p in json.loads(pins_file(cell).read_text())["pins"]:
            e = EDGE_NAME[p["nearest_edge"]]
            x, y = p["label_xy"]
            b = p["shape_bbox"]
            if e in "LR" and b[2] - b[0] > 0.8 * w:      # a full-width rail: leave on the label's side
                e = "L" if x < w / 2 else "R"
            raw[p["name"]] = (e, y if e in "LR" else x, p["layer"])
            labels[p["name"]] = (x, y)
            widths[p["name"]] = min(b[3] - b[1], 1.0) if e in "LR" else min(b[2] - b[0], 1.0)
    out = {}
    for name, (e, pos, layer) in raw.items():
        pt = {"L": (0.0, pos), "R": (w, pos), "B": (pos, 0.0), "T": (pos, h)}[e]
        if name in labels:
            lx, ly = labels[name]
            start = (lx, pt[1]) if e in "TB" and abs(ly - pt[1]) < 0.3 else (pt[0], ly) if e in "LR" and abs(lx - pt[0]) < 0.3 else (lx, ly)
        else:
            nx, ny = NORMAL[e]
            start = (pt[0] - 0.35 * nx, pt[1] - 0.35 * ny)
        out[name] = (e, pos, layer, start, widths.get(name, 0.3))
    return out


def placed(name):
    for n, cell, x, y, o in PLACE:
        if n == name:
            return cell, x, y, o
    raise KeyError(name)


def transform(name):
    """(a, b, d, e, c, f) with x' = a x + b y + c, y' = d x + e y + f, so the placed bbox's lower left is (x, y)."""
    cell, x, y, o = placed(name)
    w, h = cell_size(cell)
    a, b, d, e = ORIENT[o]
    xs = [a * cx + b * cy for cx, cy in ((0, 0), (w, 0), (0, h), (w, h))]
    ys = [d * cx + e * cy for cx, cy in ((0, 0), (w, 0), (0, h), (w, h))]
    return a, b, d, e, x - min(xs), y - min(ys)


# A grounded metal3 sheet over the two weight resistors (cell rw_res, instance RW). Every other resistor strip that forms a
# ratio in the network lies under an unbroken metal3 sheet (the state capacitors' bottom plates over the neurons' strips,
# the bypass capacitor's over the ladder); the weight resistors had no metal above them at all. If the nearest metal changes
# a strip, that difference alone would be a weight error (BOARD_CHECKS.md part 7), and one rectangle removes it.
#   sheet   0.78 um beyond the outer strips' bodies on both sides (the neuron's plate overhangs its nine strips by 0.73 um
#           at the top and 1.40 um at the side; the two outer strips here are dummies, so the four used ones have 2.67 um
#           of sheet beside them) and from 3.83 um beyond the strips' bodies at the ground end to 3.03 um beyond them at
#           the pin end, so the contact heads are covered too. Not the cell's whole width: a routed via pad on metal3
#           stands 0.23 um from the cell's right edge, and metal this wide must keep 0.40 um from other metal3.
#   ground  two via2 on the cell's own ground stub (metal2, 0.3 um wide, at its bottom edge), under the sheet's end.
#           Ground and not REF (the net of the neurons' sheets): no wire has to be routed for it, nothing is added to REF,
#           and a sheet's potential plays no part in what metal cover is known to do to polysilicon resistors.
# Cell coordinates of rw_res; drawn in the top cell after the routing (build_chip.py full), so that no route can move.
RW_SHEET = dict(inst="RW", rect=(0.2, 0.4, 12.62, 77.6), via2=(8.41, 1.05, 1, 2))


def rw_sheet():
    """The sheet in chip coordinates: ([(layer, x1, y1, x2, y2)], [(kind, x, y, nx, ny)]); empty if AJ_RW_SHEET=0."""
    import os
    if os.environ.get("AJ_RW_SHEET", "1") == "0":
        return [], []
    a, b, d, e, c, f = transform(RW_SHEET["inst"])
    at = lambda x, y: (a * x + b * y + c, d * x + e * y + f)
    x1, y1, x2, y2 = RW_SHEET["rect"]
    (p1x, p1y), (p2x, p2y) = at(x1, y1), at(x2, y2)
    vx, vy, nx, ny = RW_SHEET["via2"]
    cx, cy = at(vx, vy)
    if b or d:
        nx, ny = ny, nx
    return ([("metal3", round(min(p1x, p2x), 3), round(min(p1y, p2y), 3), round(max(p1x, p2x), 3), round(max(p1y, p2y), 3))],
            [("via2", round(cx, 3), round(cy, 3), nx, ny)])


def child_ref(name):
    """The child corner that lands on the placed lower-left corner (for getcell ... child X Y)."""
    cell, x, y, o = placed(name)
    w, h = cell_size(cell)
    a, b, d, e = ORIENT[o]
    corners = [(0, 0), (w, 0), (0, h), (w, h)]
    return min(corners, key=lambda c: (a * c[0] + b * c[1], d * c[0] + e * c[1]))


def bbox(name):
    cell, x, y, o = placed(name)
    w, h = cell_size(cell)
    if o in ("90", "270"):
        w, h = h, w
    return (x, y, x + w, y + h)


def pin(name, pinname):
    """Placed pin: (x, y) on the cell edge, layer, outward normal (nx, ny), metal width."""
    cell = placed(name)[0]
    e, pos, layer, (lx, ly), width = cell_pins(cell)[pinname]
    a, b, d, ee, c, f = transform(name)
    nx, ny = NORMAL[e]
    return (round(a * lx + b * ly + c, 4), round(d * lx + ee * ly + f, 4)), layer, (a * nx + b * ny, d * nx + ee * ny), width


def tt_pins():
    """Tiny Tapeout template pins: {name: (layer, x1, y1, x2, y2)}."""
    t = DEF.read_text()
    out = {}
    for n, l, x1, y1, x2, y2, px, py in re.findall(
            r'-\s+(\S+)\s+\+\s+NET\s+\S+.*?LAYER\s+(\S+)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\).*?PLACED\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)',
            t, re.S):
        out[n] = (l, (int(px) + int(x1)) / 1000, (int(py) + int(y1)) / 1000, (int(px) + int(x2)) / 1000, (int(py) + int(y2)) / 1000)
    return out


def signal_nets():
    """Chip signal nets: {net: [(instance, pin) | ("TT", pin name)]} (AJ's xor_chip_staged, net for net)."""
    n = {}

    def add(net, *pins):
        n.setdefault(net, []).extend(pins)
    ins = ["bit_a", "bit_b", "reset", "hold_in", "ref_reset", "obs_sel0", "obs_sel1", "obs_sel2"]
    for i, net in enumerate(ins):
        add(net, ("TT", f"ui_in[{i}]"), ("ECHO", f"in{i}"))
        add(f"uo_out{i}", ("ECHO", f"out{i}"), ("TT", f"uo_out[{i}]"))
    add("bit_a", ("SEL1", "a"), ("SEL2", "a"))
    add("bit_b", ("SEL1", "b"), ("SEL2", "b"))
    add("reset", ("H1", "reset"), ("H2", "reset"), ("Z", "reset"))
    add("hold_in", ("H1", "hold_in"), ("H2", "hold_in"), ("Z", "hold_in"))
    add("ref_reset", ("REFINV", "reset"))
    for k in range(3):
        add(f"obs_sel{k}", ("OBS", f"sel{k}"))
    # second output (SECOND_OUTPUT.md): select bits, the selector's four taps (below), the wire behind the sense
    # resistor to the buffer, the buffer's output to its pin resistor, and from there to ua[2]
    add("obs2_sel0", ("TT", "uio_in[2]"), ("OBS2", "sel0"))
    add("obs2_sel1", ("TT", "uio_in[3]"), ("OBS2", "sel1"))
    add("sense2", ("OBS2", "sense"), ("BUF2", "sense"))
    add("buf2", ("BUF2", "buf"), ("PINRES", "buf"))
    add("pad2", ("PINRES", "pad2"), ("TT", "ua[2]"))
    add("reset", ("BUF2", "reset"))
    add("ext_en1", ("TT", "uio_in[0]"), ("EXT1", "en"))
    add("ext_en2", ("TT", "uio_in[1]"), ("EXT2", "en"))
    # every analog pin goes to its series resistor first (PIN_PROTECTION.md)
    add("ext_bias", ("TT", "ua[1]"), ("PINRES", "ext_bias"))
    add("ext_in", ("PINRES", "ext_in"), ("EXT1", "ext"), ("EXT2", "ext"))
    add("pad", ("TT", "ua[0]"), ("PINRES", "pad"))
    add("ref", ("BUF_REF", "minus"), ("BUF_REF", "out"), ("H1", "ref"), ("H2", "ref"), ("Z", "ref"),
        ("LEAN", "ref"), ("OBS", "ref"), ("OBS2", "ref"), ("LADDER", "byp"), ("BUF2", "ref"))
    add("ref_tap", ("LADDER", "ref_tap"), ("BUF_REF", "plus"), ("BUF_REF", "ref"), ("BUF_BIAS1", "ref"), ("BUF_BIAS2", "ref"))
    add("d0_tap", ("LADDER", "d0_tap"), ("SEL2", "v0"), ("LEAN", "tap"))
    add("d1_tap", ("LADDER", "d1_tap"), ("SEL1", "v0"), ("SEL2", "v1"))
    add("d2_tap", ("LADDER", "d2_tap"), ("SEL1", "v1"), ("SEL2", "v2"))
    add("d3_tap", ("LADDER", "d3_tap"), ("SEL1", "v2"))
    add("bias1", ("BUF_BIAS1", "minus"), ("BUF_BIAS1", "out"), ("H1", "bpin"), ("OBS", "bias1"))
    add("bias2", ("BUF_BIAS2", "minus"), ("BUF_BIAS2", "out"), ("H2", "bpin"), ("OBS", "bias2"))
    add("sel1_ladder", ("SEL1", "out"), ("EXT1", "ladder"))
    add("sel2_ladder", ("SEL2", "out"), ("EXT2", "ladder"))
    add("bias1_in", ("EXT1", "out"), ("BUF_BIAS1", "plus"))
    add("bias2_in", ("EXT2", "out"), ("BUF_BIAS2", "plus"))
    bufs = ["BUF_REF", "BUF_BIAS1", "BUF_BIAS2"]
    add("raz", ("REFINV", "az"), *[(b, "az") for b in bufs])
    add("raz_b", ("REFINV", "az_b"), *[(b, "az_b") for b in bufs])
    add("natural1", ("LEAN", "act1"), ("H1", "natural"))
    add("natural2", ("LEAN", "act2"), ("H2", "natural"))
    add("h1", ("H1", "h"), ("LEAN", "h1"), ("OBS", "h1"), ("OBS2", "h1"))
    add("h2", ("H2", "h"), ("LEAN", "h2"), ("OBS", "h2"), ("OBS2", "h2"))
    add("f1", ("H1", "y"), ("RW", "f1"), ("OBS", "f1"))
    add("f2", ("H2", "y"), ("RW", "f2"), ("OBS", "f2"))
    add("z", ("Z", "y"), ("RW", "z"), ("OBS", "z"), ("OBS2", "z"))
    add("obs_out", ("OBS", "out"), ("RSENSE", "inp"))
    add("sense", ("RSENSE", "sense"), ("PADBUF", "plus"))
    add("buffered", ("PADBUF", "minus"), ("PADBUF", "out"), ("PINRES", "buffered"))
    return n


def supply_net(inst, pinname):
    """The routing net of a block's supply pin (None: joined by a drawn bridge, not by the router)."""
    if inst in BRIDGED or (inst, pinname) in STRAPPED:
        return None
    if inst == "LADDER":
        return "vdd_lad" if pinname == "vdd" else "vss_lad"
    if inst == "LEAN" and pinname == "vss":
        return "vss_lean"
    return pinname


def nets():
    """Every net the router connects: the signals, then the supplies with the stripes each may end on."""
    n = signal_nets()
    for name, cell, *_ in PLACE:
        pins = cell_pins(cell)
        for p in ("vdd", "vss"):
            if p in pins and supply_net(name, p):
                n.setdefault(supply_net(name, p), []).append((name, p))
    for net, stripes in SUPPLY_NETS.items():
        n.setdefault(net, []).extend(("STRIPE", s) for s in stripes)
    n["vss"] += [("TT", f"uio_out[{i}]") for i in range(8)] + [("TT", f"uio_oe[{i}]") for i in range(8)]
    return n


def check():
    """Every instance pin is on exactly one net (or bridged); every net has >= 2 terminals."""
    used = {}
    for net, pins in nets().items():
        assert len(pins) >= 2, net
        for p in pins:
            if p[0] == "STRIPE":
                continue
            assert p not in used, (p, net, used.get(p))
            used[p] = net
    missing = [(name, p) for name, cell, *_ in PLACE for p in cell_pins(cell)
               if (name, p) not in used and not (name in BRIDGED and p in ("vdd", "vss")) and (name, p) not in STRAPPED
               and (name, p) != ("Z", "h")]            # Z's state stays inside its cell
    return dict(unconnected=missing, overlaps=overlaps(), outside=outside(), stripe_conflicts=stripe_conflicts())


# ---------------------------------------------------------------- the neurons' supply bridges
# In the neuron cell (aj_neuron_layout.py), on its amplifier-side edge: the VDD join between the two amplifiers'
# rails (metal2) and the ground line (metal2). Their y ranges come from results/aj_neuron_edge.json.
# One ground bridge beside each amplifier's ground line, 2.8 um tall: joined to the ground line, a bridge 3 um
# or taller would make "wide metal" of it, and the amplifier's own metal2 sits 0.14 um from that line (met2.3a).
def _edge():
    p = RESULTS / "aj_neuron_edge.json"
    return json.loads(p.read_text()) if p.exists() else None


def _gnd_windows(e):
    return [(round(round((a + b) / 2, 1) - 1.4, 3), round(round((a + b) / 2, 1) + 1.4, 3)) for a, b in e["amplifier_ground_line_y"]]


NEURON_STRIPES = {"H1": ("VDD_M", "GND_M1"), "H2": ("VDD_M", "GND_M1"), "Z": ("VDD_M", "GND_M2")}


def _yspan(name, y1, y2):
    a, b, d, e, c, f = transform(name)
    w = cell_size(placed(name)[0])[0]
    ys = sorted((d * w + e * y1 + f, d * w + e * y2 + f))
    return round(ys[0], 3), round(ys[1], 3)


def supply_straps():
    """Bridges from the middle stripes to each neuron's VDD seam and ground line.

    VDD: a short metal2 stub out of the seam, a via2 area just outside the neuron (metal3 must keep 1.34 um
    from the amplifiers' capacitors, which end 1.0 um inside the neuron's edge since aj_core's Miller plate
    moved to its right side), a metal3 bridge under the ground stripe to the VDD stripe, a via3 area up into
    it. Vertical signal wires pass under the bridge on metal2.
    Ground: a metal2 stub from the ground line to under the nearest ground stripe and one via2 + via3 stack
    there, beside each amplifier."""
    straps, contacts = [], []
    info = _edge()
    for name, (vs, gs) in NEURON_STRIPES.items():
        if not measured(placed(name)[0]) or info is None:
            continue
        a, b, d, e, c, f = transform(name)
        edge = round(a * cell_size(placed(name)[0])[0] + c, 3)      # global x of the amplifier-side edge
        _, vx1, vx2, _ = STRIPE[vs]
        _, gx1, gx2, _ = STRIPE[gs]
        s = 1 if vx1 > edge else -1                                 # towards the stripes

        def xs(u1, u2):
            return tuple(sorted((round(edge + s * u1, 3), round(edge + s * u2, 3))))
        # VDD
        y1, y2 = _yspan(name, *info["vdd_seam_y"])
        m2 = xs(-0.1, 1.3)
        straps.append(("vdd", "metal2", m2[0], y1, m2[1], y2))
        v2 = xs(0.5, 1.2)
        contacts.append(("via2", v2[0], y1 + 0.15, v2[1], y2 - 0.15, "vdd"))
        far = vx2 - 0.1 if s > 0 else vx1 + 0.1
        m3 = tuple(sorted((round(edge + s * 0.42, 3), far)))
        straps.append(("vdd", "metal3", m3[0], y1 + 0.05, m3[1], y2 - 0.05))
        contacts.append(("via3", vx1 + 0.2, y1 + 0.25, vx2 - 0.2, y2 - 0.25, "vdd"))
        # ground
        for g1, g2 in _gnd_windows(info):
            y1, y2 = _yspan(name, g1, g2)
            m2 = tuple(sorted((round(edge - s * 0.1, 3), gx2 - 0.05 if s > 0 else gx1 + 0.05)))
            straps.append(("vss", "metal2", m2[0], y1, m2[1], y2))
            straps.append(("vss", "metal3", gx1 + 0.05, y1 + 0.05, gx2 - 0.05, y2 - 0.05))
            contacts.append(("via2", gx1 + 0.2, y1 + 0.2, gx2 - 0.2, y2 - 0.2, "vss"))
            contacts.append(("via3", gx1 + 0.2, y1 + 0.2, gx2 - 0.2, y2 - 0.2, "vss"))
    # VDD of the REF and pad buffers: a 1.6 um metal4 strap from the outermost VDD stripe along the channel
    # beside the buffer (above the REF buffer, above the pad buffer), down the right margin to the height of the
    # buffer's VDD pin, and a via2 + via3 stack onto a metal2 stub into the pin.
    _, sx1, sx2, _ = STRIPE["VDD_R"]
    xm = (TILE[0] - 2.9, TILE[0] - 1.3)                              # the strap in the right margin
    for name, ych in (("BUF_REF", bbox("BUF_REF")[3] + 0.9), ("PADBUF", bbox("PADBUF")[3] + 1.25)):
        (px, py), layer, n, w = pin(name, "vdd")
        assert layer == "met2" and n[0] == 1, (name, layer, n)
        straps.append(("vdd", "metal4", sx2 - 0.1, ych, xm[1], ych + 1.6))
        straps.append(("vdd", "metal4", xm[0], py - 0.8, xm[1], ych + 1.6))
        straps.append(("vdd", "metal3", xm[0] + 0.05, py - 0.75, xm[1] - 0.05, py + 0.75))
        straps.append(("vdd", "metal2", xm[0] + 0.05, py - 0.75, xm[1] - 0.05, py + 0.75))
        straps.append(("vdd", "metal2", px - 0.1, py - 0.15, xm[0] + 0.3, py + 0.15))
        for kind in ("via2", "via3"):
            contacts.append((kind, xm[0] + 0.2, py - 0.6, xm[1] - 0.2, py + 0.6, "vdd"))
    # Each supply's stripes joined inside the tile, at the top margin, so that the layout is one VDPWR net and one
    # VGND net by itself (LVS needs that, and the chip does not depend on Tiny Tapeout's grid reaching every
    # stripe). With the grid connected the joins carry no current. VGND: a metal3 bar under the stripes' top
    # ends; VDPWR: the three VDD stripes extended 1.2 um past the ground stripes' ends to a metal4 bar.
    # They are obstacles for the router, not places to connect to (their net names are not routing nets).
    gnd = [v for v in STRIPE.values() if v[0] == "VGND"]
    vdd = [v for v in STRIPE.values() if v[0] == "VDPWR"]
    yt = STRIPE_Y[1]
    straps.append(("vss_join", "metal3", min(v[1] for v in gnd) + 0.1, yt - 1.0, max(v[2] for v in gnd) - 0.1, yt - 0.2))
    for _, x1, x2, _ in gnd:
        contacts.append(("via3", x1 + 0.25, yt - 0.86, x2 - 0.25, yt - 0.34, "vss_join"))
    for _, x1, x2, _ in vdd:
        straps.append(("vdd_join", "metal4", x1, yt - 0.1, x2, yt + 1.3))
    straps.append(("vdd_join", "metal4", min(v[1] for v in vdd), yt + 0.7, max(v[2] for v in vdd), yt + 1.3))
    return straps, contacts


def overlaps():
    boxes = [(n, bbox(n)) for n, *_ in PLACE]
    return [(a, b) for i, (a, ba) in enumerate(boxes) for b, bb in boxes[i + 1:]
            if ba[0] < bb[2] - 1e-6 and bb[0] < ba[2] - 1e-6 and ba[1] < bb[3] - 1e-6 and bb[1] < ba[3] - 1e-6]


def outside():
    return [n for n, *_ in PLACE if bbox(n)[0] < 1.0 or bbox(n)[2] > TILE[0] - 1.0 or bbox(n)[1] < 1.5 or bbox(n)[3] > 224.0]


def stripe_conflicts():
    """Blocks with metal4 of their own (capacitors) that a stripe would cross."""
    m4_free = {"bias_sel", "ext_sw", "obs_mux", "echo", "ref_inv", "rsense", "rw_res", "pin_res", "lean_block"}
    bad = []
    for sname, (_, x1, x2, _) in STRIPE.items():
        for n, cell, *_ in PLACE:
            b = bbox(n)
            if cell not in m4_free and b[0] < x2 + 0.4 and x1 - 0.4 < b[2] and b[1] < STRIPE_Y[1] and STRIPE_Y[0] < b[3]:
                bad.append((sname, n))
    return bad


STRAPS, STRAP_CONTACTS = supply_straps()


if __name__ == "__main__":
    print(json.dumps(check(), indent=1))
    for n, cell, *_ in PLACE:
        b = bbox(n)
        print(f"{n:10s} {cell:12s} x {b[0]:7.2f}..{b[2]:7.2f}  y {b[1]:7.2f}..{b[3]:7.2f}  {'measured' if measured(cell) else 'PLANNED'}")
