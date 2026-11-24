"""The new cells of the programmable-bias variant, drawn into a KLayout layout that already holds the selected die's cells.

  ne_bias_writer  the write circuit of `pw4_shunt` copied as drawn: its seven device sub-cells at their own positions and
                  every li/m1/m2 shape of the writer's own nets inside its outline (gn, wm, we, we_b, dac, ref, vdd, vss).
                  Nothing of the shunt's capacitors, PMOS resistor or clamp comes along. Pins: gn we ref dac vdd vss.
Further cells (XPROG, capacitors, the words block, the strobe logic) are added below as they are drawn.
"""
import sys
from pathlib import Path

import klayout.db as db

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[3]
sys.path.insert(0, str(SIX / 'layout'))
from connectivity import Connectivity  # noqa: E402

UM = 1000
LI, MCON, M1, V1, M2, V2, M3, V3, M4, CAPM = (67, 20), (67, 44), (68, 20), (68, 44), (69, 20), (69, 44), (70, 20), (70, 44), (71, 20), (89, 44)
LABEL = {LI: (67, 5), M1: (68, 5), M2: (69, 5), M3: (70, 5), M4: (71, 5)}
PINL = {LI: (67, 16), M1: (68, 16), M2: (69, 16), M3: (70, 16), M4: (71, 16)}
METAL_NAME = {LI: 'li', M1: 'm1', M2: 'm2', M3: 'm3', M4: 'm4'}
VIA_BELOW = {MCON: LI, V1: M1, V2: M2}

# --- the writer of pw4_shunt (cell coordinates of pw4_shunt) ---------------------------------------------------------
WRITER_BOX = db.Box(13600, 300, 28350, 6500)
WRITER_DEVICES = ('sky130_fd_sc_hd__tapvpwrvgnd_1', 'hv4t', 'lvt1b', 'tgnb', 'tgpt', 'n8t', 'sky130_fd_sc_hd__inv_1')
SHUNT_LABELS = {'gn': ('m1', 14.175, 4.2), 'wm': ('m1', 15.465, 4.0), 'we': ('m2', 24.8, 14.55), 'we_b': ('m1', 18.94, 2.8),
                'ref': ('m2', 28.0, 12.65), 'dac': ('m2', 28.0, 1.6), 'vdd': ('m2', 28.0, 1.1), 'vss': ('m1', 28.0, 0.6)}
WRITER_NETS = set(SHUNT_LABELS)
# writer pins in writer-local coordinates (origin = WRITER_BOX lower left), layer, position
WRITER_PINS = {'gn': (M1, 14.19 - 13.6, 6.40 - 0.3), 'we': (M1, 24.80 - 13.6, 6.40 - 0.3), 'ref': (M1, 27.74 - 13.6, 6.40 - 0.3),
               'dac': (M2, 28.20 - 13.6, 1.60 - 0.3), 'vdd': (M2, 28.20 - 13.6, 1.12 - 0.3), 'vss': (M1, 28.20 - 13.6, 0.60 - 0.3)}


def box(x1, y1, x2, y2):
    return db.Box(round(x1 * UM), round(y1 * UM), round(x2 * UM), round(y2 * UM))


def label(cell, layer, name, x, y, half=0.07, pin=True):
    """Text on the label purpose; with pin=True also a small square on the pin purpose (Magic then makes it a port)."""
    ly = cell.layout()
    cell.shapes(ly.layer(*LABEL[layer])).insert(db.Text(name, round(x * UM), round(y * UM)))
    if pin:
        cell.shapes(ly.layer(*PINL[layer])).insert(box(x - half, y - half, x + half, y + half))


def _interior_point(region):
    """A point inside a Manhattan region: the centre of its largest rectangle piece."""
    pieces = sorted(region.decompose_trapezoids_to_region().each(), key=lambda p: -p.area())
    return pieces[0].bbox().center()


def writer(ly, name='ne_bias_writer', pins=True):
    """Copy the write circuit out of pw4_shunt (which must exist in `ly`)."""
    shunt = ly.cell('pw4_shunt')
    con = Connectivity(ly, shunt)
    nets = {k: con.probe(m, x, y) for k, (m, x, y) in SHUNT_LABELS.items()}
    if None in nets.values() or len(set(nets.values())) != len(nets):
        raise ValueError(('pw4_shunt writer nets not distinct', nets))
    keep_ids = {v: k for k, v in nets.items()}
    cell = ly.create_cell(name)
    shift = db.Trans(-WRITER_BOX.left, -WRITER_BOX.bottom)
    placed = []
    for inst in shunt.each_inst():
        if inst.cell.name in WRITER_DEVICES:
            cell.insert(db.CellInstArray(inst.cell_index, shift * inst.trans))
            placed.append(inst.cell.name)
    if sorted(placed) != sorted(WRITER_DEVICES):
        raise ValueError(('writer device cells', placed))
    clip = db.Region(WRITER_BOX)
    kept = {}
    metal_layers = {LI: 'li', M1: 'm1', M2: 'm2', M3: 'm3'}
    for (l, d), metal in metal_layers.items():
        src = db.Region(shunt.shapes(ly.layer(l, d))).merged() & clip
        out = db.Region()
        for poly in src.each():
            piece = db.Region(poly)
            c = _interior_point(piece)
            net = con.probe(metal, c.x / UM, c.y / UM)
            tag = keep_ids.get(net)
            if tag is None:
                continue
            if tag == 'ref' and poly.bbox().center().x < 23000:
                continue          # the shunt's left REF bus to its clamp, not the writer's
            if (l, d) == M3:
                continue          # the shunt's ring tie on metal 3 stays behind: the writer uses li..m2 only
            out.insert(poly)
        if not out.is_empty():
            cell.shapes(ly.layer(l, d)).insert(out.transformed(shift))
            kept[metal] = out.count()
    # vias: keep a cut if both of its landings are kept writer metal
    for (l, d), lower in ((MCON, LI), (V1, M1)):
        cuts = db.Region(shunt.shapes(ly.layer(l, d))) & clip
        good = db.Region()
        for poly in cuts.each():
            c = poly.bbox().center()
            n = con.probe(METAL_NAME[lower], c.x / UM, c.y / UM)
            if n in keep_ids and not (keep_ids[n] == 'ref' and c.x < 23000):
                good.insert(poly)
        if not good.is_empty():
            cell.shapes(ly.layer(l, d)).insert(good.transformed(shift))
            kept[f'{l}/{d}'] = good.count()
    # wells and implants drawn in pw4_shunt itself for the writer devices
    for (l, d) in ((64, 20), (94, 20), (93, 44), (75, 20)):
        src = db.Region(shunt.shapes(ly.layer(l, d))).merged()
        out = db.Region()
        for poly in src.each():
            b = poly.bbox()
            if WRITER_BOX.contains(b.p1) and WRITER_BOX.contains(b.p2):
                out.insert(poly)
        if not out.is_empty():
            cell.shapes(ly.layer(l, d)).insert(out.transformed(shift))
            kept[f'{l}/{d}'] = out.count()
    for pin, (layer, x, y) in WRITER_PINS.items():
        label(cell, layer, pin, x, y, pin=pins)
    return cell, dict(nets=nets, kept=kept, devices=placed)


WRITER_REFERENCE = """* ne_bias_writer: the write circuit of pw4_shunt (we = strobe, gn = stored node)
.subckt cd_tg_small a b en en_b vdd vss
XMN a en b vss sky130_fd_pr__nfet_01v8 L=0.15 W=0.5 nf=1 m=1
XMP a en_b b vdd sky130_fd_pr__pfet_01v8 L=0.15 W=1 nf=1 m=1
.ends
.subckt sky130_fd_sc_hd__inv_1 A VGND VNB VPB VPWR Y
X0 VGND A Y VNB sky130_fd_pr__nfet_01v8 w=0.65 l=0.15
X1 VPWR A Y VPB sky130_fd_pr__pfet_01v8_hvt w=1 l=0.15
.ends
.subckt ne_bias_writer gn we ref dac vdd vss
XW1N gn we wm vss sky130_fd_pr__nfet_g5v0d10v5 L=4 W=0.42 nf=1 m=1
XW1P gn we_b wm vdd sky130_fd_pr__pfet_01v8_lvt L=1 W=1 nf=1 m=1
XW2 wm dac we we_b vdd vss cd_tg_small
XWC wm we_b ref vss sky130_fd_pr__nfet_01v8 L=8 W=0.42 nf=1 m=1
XWI we vss vss vdd vdd we_b sky130_fd_sc_hd__inv_1
.ends
"""


if __name__ == '__main__':
    import gzip
    import json
    gds_in, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    ly = db.Layout()
    ly.read_bytes(gzip.decompress(gds_in.read_bytes()))
    cell, rec = writer(ly)
    cell.write(str(out / 'ne_bias_writer.gds'))
    (out / 'ne_bias_writer_ref.spice').write_text(WRITER_REFERENCE)
    print(json.dumps(rec))


# --- the two stored words, their capacitors and programmable transistors, drawn in die coordinates ----------------------
CAP_UNIT = SIX / 'native_edges/verification/evidence/weak_electrode_5c5dfd43/cells/gate_mim_897.gds.gz'
CAP_UNIT_SHA = None       # checked by bias_stage.py against the repository file


def rect(cell, layer, x1, y1, x2, y2):
    cell.shapes(cell.layout().layer(*layer)).insert(box(x1, y1, x2, y2))


def via1(cell, x, y):
    """A metal1-metal2 via centred at (x, y) with 0.32 um landings."""
    rect(cell, V1, x - .075, y - .075, x + .075, y + .075)
    rect(cell, M1, x - .16, y - .16, x + .16, y + .16)
    rect(cell, M2, x - .16, y - .16, x + .16, y + .16)


def via2(cell, x, y):
    rect(cell, V2, x - .1, y - .1, x + .1, y + .1)
    rect(cell, M2, x - .2, y - .2, x + .2, y + .2)
    rect(cell, M3, x - .25, y - .25, x + .25, y + .25)


def via3(cell, x, y):
    rect(cell, V3, x - .1, y - .1, x + .1, y + .1)
    rect(cell, M3, x - .25, y - .25, x + .25, y + .25)
    rect(cell, M4, x - .25, y - .25, x + .25, y + .25)


# die coordinates of the block (see REPORT.md, section "the words block")
W1_AT, W2_AT = (269.15, 1.85), (284.30, 1.85)
CAPA_AT, CAPB_AT = (274.60, 7.00), (279.40, 17.55)
XP1_AT, XP2_AT = (276.40, 10.40), (282.00, 9.56)
WORDS_PORTS = ['bstb1', 'bstb2', 'ret1', 'ret2', 'dac', 'ref', 'vdd', 'vss']


def words_block(ly, writer, cap, xp1_cell, xp2_cell, l1=4.0, l2=4.0, name='ne_bias_words', w1=None, cell=None):
    """Both bias words: writers (W1 under capacitor A, W2 under the reference buffer's grounded plate), capacitors A and
    B (top plates bg1, bg2; bottom plates on VSS), XPROG1/2 (gates bg1/bg2, drains ret1/ret2, sources VSS).
    Rules that set the geometry: unrelated metal 3 stays 1.34 um from a capacitor top plate (capm.11) and 0.4 um from a
    plate wider than 3 um (met3.3d); via2 never under a top plate (capm.8).
    w1: XPROG1's width if it is not 0.42 um (version 4: 1 um); bg1's bar then meets XPROG1's lower gate strap where it
    lies for that width, 0.16 um below the drain terminal. cell: an existing, cleared cell to draw into (v4_stage.py).
    Without them the block is drawn exactly as for the lock build."""
    c = ly.create_cell(name) if cell is None else cell
    T = lambda x, y, rot=0: db.Trans(rot, False, round(x * UM), round(y * UM))
    # XPROG geometry from the PDK generator: terminal centres at +-(L/2 + 0.145), gate straps to +-(L/2 - 0.02).
    # XPROG1's VSS terminal stays at x 278.545 whatever L1 is, so its via2 keeps 0.4 um from capacitor A's top plate.
    t1, s1, t2, s2 = l1 / 2 + .145, l1 / 2 - .02, l2 / 2 + .145, l2 / 2 - .02
    xp1 = (278.545 - t1, XP1_AT[1]); xp2 = XP2_AT
    c.insert(db.CellInstArray(writer.cell_index(), T(*W1_AT)))
    c.insert(db.CellInstArray(writer.cell_index(), T(*W2_AT)))
    c.insert(db.CellInstArray(cap.cell_index(), T(*CAPA_AT)))
    c.insert(db.CellInstArray(cap.cell_index(), T(*CAPB_AT)))
    c.insert(db.CellInstArray(xp1_cell.cell_index(), T(*xp1)))
    c.insert(db.CellInstArray(xp2_cell.cell_index(), T(*xp2)))
    w1x, w2x = W1_AT[0], W2_AT[0]
    # rails of W1 and W2 joined across the 0.4 um gap (vss m1; vdd and dac m2, 0.16 apart)
    rect(c, M1, w1x + 14.75, 1.91, w2x, 2.39)
    rect(c, M2, w1x + 14.75, 2.49, w2x, 2.83)
    rect(c, M2, w1x + 14.75, 2.99, w2x, 3.33)
    # plate A to the VSS rail, right of capacitor A's top plate
    rect(c, M3, 279.60, 1.85, 280.10, 2.40)
    rect(c, V2, 279.75, 1.95, 279.95, 2.15)
    rect(c, M2, 279.665, 1.91, 280.035, 2.19)
    rect(c, V1, 279.775, 1.975, 279.925, 2.125)
    # plate B reaches VSS through XPROG2's source line and a metal-1 line down the gap between the writers
    rect(c, M1, 284.13, 2.30, 284.31, 9.20)   # 0.15 um clear of XPROG2's lower gate strap (ends 283.98)
    # pin row left of capacitor B, 1.34 um above capacitor A's top plate: bg1 stack, bstb1, ret1, ret2
    PY0, PY1 = 12.90, 13.40
    def island(x0, via=True):
        rect(c, M3, x0, PY0, x0 + .5, PY1)
        if via:
            rect(c, V2, x0 + .15, 13.05, x0 + .35, 13.25)
    # --- bg1: W1's gn line up to its stack; bar to XPROG1's lower gate strap
    g1 = w1x + 0.46
    rect(c, M1, g1, 8.05, g1 + 0.23, PY1)
    island(269.475)
    rect(c, M2, 269.475, PY0, 269.975, PY1)
    rect(c, M1, 269.475, PY0, 269.975, PY1)
    rect(c, V1, 269.65, 13.075, 269.80, 13.225)
    rect(c, V3, 269.625, 13.05, 269.825, 13.25)
    rect(c, M4, 269.475, PY0, 269.975, PY1)
    rect(c, M4, 269.475, 11.20, 269.975, PY1)          # from capacitor A's top plate (m4 to 11.29)
    if w1 is None:
        rect(c, M1, g1, 9.45, xp1[0] - s1 + 0.28, 9.90)   # to XPROG1 lower strap (y 9.80..10.03)
    else:
        # the generator puts the lower strap at y - w1/2 - 0.39 .. y - w1/2 - 0.16 (W 1: 9.51..9.74, drain metal from 9.90)
        yb = XP1_AT[1] - w1 / 2
        rect(c, M1, g1, yb - 0.45, xp1[0] - s1 + 0.28, yb - 0.16)
    # --- XPROG1: right terminal to VSS through plate A beside the capacitor; left terminal = ret1
    sx = xp1[0] + t1
    rect(c, M1, sx - .115, 10.19, sx + .165, 10.61)
    rect(c, V1, sx - .05, 10.325, sx + .10, 10.475)
    rect(c, M2, sx - .17, 10.20, sx + .38, 10.60)
    rect(c, V2, sx + .08, 10.30, sx + .28, 10.50)
    dx = xp1[0] - t1
    rect(c, M1, dx - .165, 10.19, dx + .115, 10.61)
    rect(c, V1, dx - .10, 10.325, dx + .05, 10.475)
    rect(c, M2, dx - .18, 10.20, dx + .12, 11.60)
    rect(c, M2, 271.15, 11.30, dx + .12, 11.60)
    rect(c, M2, 271.15, 11.30, 271.55, PY1)
    island(271.10)
    label(c, M3, 'ret1', 271.35, 13.15)
    # --- bg2: stack B below capacitor B (1.34 um from its top plate); to XPROG2's upper strap and W2's gn line
    rect(c, M4, 282.00, 10.60, 282.50, 13.35)
    rect(c, V3, 282.15, 10.75, 282.35, 10.95)
    rect(c, M3, 282.00, 10.60, 282.50, 11.10)
    rect(c, V2, 282.15, 10.75, 282.35, 10.95)
    rect(c, M2, 282.00, 10.60, 282.50, 11.10)
    rect(c, V1, 282.175, 10.775, 282.325, 10.925)
    rect(c, M1, 282.00, 10.60, 282.50, 11.10)
    rect(c, M1, 282.05, 10.30, 282.45, 11.10)
    g2 = w2x + 0.46
    rect(c, M1, xp2[0] + s2 - .08, 10.22, g2 + 0.23, 10.45)
    rect(c, M1, g2, 8.05, g2 + 0.23, 10.45)
    # --- XPROG2: right terminal to VSS through plate B beside capacitor B; left terminal = ret2
    sx2 = xp2[0] + t2
    rect(c, M1, sx2 - .115, 9.06, max(sx2 + .165, 284.31), 10.06)   # reaches the VSS line between the writers
    rect(c, V1, sx2 - .05, 9.485, sx2 + .10, 9.635)
    rect(c, M2, 283.45, 9.40, sx2 + .165, 9.72)
    rect(c, M2, 283.45, 9.40, 283.75, 13.30)
    rect(c, V2, 283.50, 13.00, 283.70, 13.20)
    rect(c, M3, 283.40, 12.86, 283.80, 13.30)
    dx2 = xp2[0] - t2
    rect(c, M1, dx2 - .165, 9.06, dx2 + .115, 10.06)
    rect(c, V1, dx2 - .10, 9.485, dx2 + .05, 9.635)
    rect(c, M2, dx2 - .18, 9.40, dx2 + .12, 12.15)
    rect(c, M2, 271.95, 11.85, dx2 + .12, 12.15)
    rect(c, M2, 271.95, 11.85, 272.35, PY1)
    island(271.90)
    label(c, M3, 'ret2', 272.15, 13.15)
    # --- strobe of word 1: pin in the row, down and along W1's top to its we pin
    island(270.30)
    rect(c, M2, 270.30, PY0, 270.80, PY1)
    rect(c, M2, 270.40, 8.20, 270.70, PY1)
    rect(c, M2, 270.40, 8.20, 280.53, 8.50)
    rect(c, M1, 280.17, 7.72, 280.53, 8.50)
    rect(c, V1, 280.275, 8.275, 280.425, 8.425)
    label(c, M3, 'bstb1', 270.55, 13.15)
    # --- REF: both writers' ref pins joined along the corridor above the writers; pin right of capacitor B
    for rx in (w1x + 13.92, w2x + 13.92):
        rect(c, M1, rx, 7.95, rx + 0.445, 8.47)          # 0.145 below the buffer's VSS metal 1 at y 8.615
        rect(c, V1, rx + 0.15, 8.25, rx + 0.30, 8.40)
    rect(c, M2, w1x + 13.92, 8.17, w2x + 14.365, 8.50)
    rect(c, M2, 285.40, 8.17, 285.90, 9.10)
    rect(c, V2, 285.55, 8.75, 285.75, 8.95)
    rect(c, M3, 285.40, 8.60, 285.90, 9.10)
    label(c, M3, 'ref', 285.65, 8.85)
    # --- strobe of word 2: pin right of REF, metal 1 along the corridor to W2's we pin
    rect(c, M3, 286.60, 8.64, 287.10, 9.14)
    rect(c, V2, 286.75, 8.79, 286.95, 8.99)
    rect(c, M2, 286.60, 8.64, 287.10, 9.14)
    rect(c, V1, 286.775, 8.815, 286.925, 8.965)
    rect(c, M1, 286.60, 8.19, 287.10, 9.14)
    rect(c, M1, 286.60, 8.19, w2x + 11.38, 8.47)
    rect(c, M1, w2x + 11.02, 7.72, w2x + 11.38, 8.47)
    label(c, M3, 'bstb2', 286.85, 8.89)
    # --- DAC and VDD pins on the joined rails (reached from below); VSS to the reference buffer's grounded plate
    rect(c, M2, 284.45, 2.99, 284.85, 3.45)
    rect(c, V2, 284.55, 3.10, 284.75, 3.30); rect(c, M3, 284.40, 2.95, 284.90, 3.45)
    label(c, M3, 'dac', 284.65, 3.20)
    rect(c, M2, 283.25, 2.40, 283.65, 2.83)
    rect(c, V2, 283.35, 2.50, 283.55, 2.70); rect(c, M3, 283.20, 2.35, 283.70, 2.85)
    label(c, M3, 'vdd', 283.45, 2.60)
    rect(c, M1, w2x + 14.75, 1.91, 299.90, 2.39)
    rect(c, V1, 299.625, 2.025, 299.775, 2.175)
    rect(c, M2, 299.50, 1.95, 299.90, 2.35)
    rect(c, V2, 299.60, 2.05, 299.80, 2.25)
    rect(c, M3, 299.45, 1.95, 299.95, 2.45)
    label(c, M3, 'vss', 299.70, 2.20)
    return c


WORDS_REFERENCE = WRITER_REFERENCE + """
.subckt ne_bias_words bstb1 bstb2 ret1 ret2 dac ref vdd vss
XW1 bg1 bstb1 ref dac vdd vss ne_bias_writer
XW2 bg2 bstb2 ref dac vdd vss ne_bias_writer
XC1 bg1 vss sky130_fd_pr__cap_mim_m3_1 W=8.97 L=8.97 m=1
XC2 bg2 vss sky130_fd_pr__cap_mim_m3_1 W=8.97 L=8.97 m=1
XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L={L1} W={W1} nf=1 m=1
XPROG2 ret2 bg2 vss vss sky130_fd_pr__nfet_01v8 L={L2} W={W2} nf=1 m=1
.ends
"""


# --- the strobe logic: bstb_k = bit_a and bit_b and we_k, from the chip's own standard cells --------------------------
LOGIC_PORTS = ['bit_a', 'bit_b', 'we0', 'we1', 'bstb1', 'bstb2', 'vdd', 'vss']
STD_ACCESS = {'inv': {'A': (.46, 1.19), 'Y': (.925, 1.77)},
              'nor2': {'A': (1.135, 1.20), 'B': (.245, 1.20), 'Y': (.69, .62)},
              'nand2': {'A': (1.105, 1.20), 'B': (.260, 1.19), 'Y': (.700, 1.79)}}   # as res_select.py
LOGIC_ROW = [('tap', 0.00), ('nand2', 0.46, {'A': 'bit_a', 'B': 'bit_b', 'Y': 'nab'}),
             ('inv', 1.84, {'A': 'we0', 'Y': 'nwe0'}), ('inv', 3.22, {'A': 'we1', 'Y': 'nwe1'}),
             ('nor2', 4.60, {'A': 'nab', 'B': 'nwe0', 'Y': 'bstb1'}), ('nor2', 5.98, {'A': 'nab', 'B': 'nwe1', 'Y': 'bstb2'}),
             ('tap', 7.36)]
STD_NAME = {'tap': 'sky130_fd_sc_hd__tapvpwrvgnd_1', 'inv': 'sky130_fd_sc_hd__inv_1',
            'nor2': 'sky130_fd_sc_hd__nor2_1', 'nand2': 'sky130_fd_sc_hd__nand2_1'}


def lift(c, x, y):
    """li pin -> m2 (mcon, m1 pad, via1, m2 pad), as control.lift."""
    rect(c, MCON, x - .085, y - .085, x + .085, y + .085)
    rect(c, M1, x - .16, y - .14, x + .16, y + .14)
    rect(c, V1, x - .075, y - .075, x + .075, y + .075)
    rect(c, M2, x - .14, y - .16, x + .14, y + .16)


def m3_via(c, x, y):
    rect(c, M2, x - .14, y - .185, x + .14, y + .185)
    rect(c, V2, x - .1, y - .1, x + .1, y + .1)
    rect(c, M3, x - .25, y - .25, x + .25, y + .25)


def logic_block(ly, name='ne_bias_strobe'):
    """NAND2(bit_a, bit_b) = nab; INV(we0) = nwe0; INV(we1) = nwe1; NOR2(nab, nwe0) = bstb1; NOR2(nab, nwe1) = bstb2.
    One standard-cell row (origin at the row's VGND rail); internal nets on metal-3 tracks above the row, external
    pins as metal-3 pads below it."""
    c = ly.create_cell(name)
    row = 0.0
    points = {}
    for item in LOGIC_ROW:
        kind, x = item[0], item[1]
        cell = ly.cell(STD_NAME[kind])
        if cell is None:
            raise ValueError(('standard cell missing from the die', STD_NAME[kind]))
        c.insert(db.CellInstArray(cell.cell_index(), db.Trans(round(x * UM), round(row * UM))))
        if kind == 'tap':
            continue
        for pin, net in item[2].items():
            dx, dy = STD_ACCESS[kind][pin]
            p = (round(x + dx, 3), round(row + dy, 3))
            lift(c, *p)
            points.setdefault(net, []).append(p)
    # internal nets: m2 up to a metal-3 track above the row (vias with 0.72 x 0.34 pads along the track)
    tracks = {'nab': 3.90, 'nwe0': 4.60, 'nwe1': 5.30}
    for net, ty in tracks.items():
        xs = []
        for (x, y) in points[net]:
            rect(c, M2, x - .14, y - .16, x + .14, ty + .185)
            rect(c, V2, x - .1, ty - .1, x + .1, ty + .1)
            rect(c, M3, x - .36, ty - .17, x + .36, ty + .17)
            xs.append(x)
        rect(c, M3, min(xs) - .36, ty - .17, max(xs) + .36, ty + .17)
    # external pins: m2 down to a metal-3 pad (0.34 x 0.72) below the row
    for net in ('bit_a', 'bit_b', 'we0', 'we1', 'bstb1', 'bstb2'):
        (x, y), = points[net]
        rect(c, M2, x - .14, -1.135, x + .14, y + .16)
        rect(c, V2, x - .1, -1.05, x + .1, -.85)
        rect(c, M3, x - .17, -1.31, x + .17, -.59)
        label(c, M3, net, x, -.95)
    # rails: m1 across the row, a via to an m2 pad at the right end
    for net, y in (('vdd', row + 2.72), ('vss', row)):
        rect(c, M1, 0.0, y - .24, 7.82, y + .24)
        rect(c, M1, 7.82, y - .24, 8.40, y + .24)
        rect(c, V1, 8.125, y - .075, 8.275, y + .075)
        rect(c, M2, 8.06, y - .19, 8.34, y + .19)
        label(c, M2, net, 8.20, y)
    return c, points


def logic_reference():
    import os
    pdk = Path(os.environ.get('PDK_ROOT', Path.home() / '.ciel')) / 'sky130A'
    std = (pdk / 'libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice').read_text()
    import re
    defs = [re.search(r'(?ms)^\.subckt ' + n + r' .*?^\.ends', std).group() for n in
            ('sky130_fd_sc_hd__inv_1', 'sky130_fd_sc_hd__nor2_1', 'sky130_fd_sc_hd__nand2_1')]
    body = """.subckt ne_bias_strobe bit_a bit_b we0 we1 bstb1 bstb2 vdd vss
XSAB bit_a bit_b vss vss vdd vdd nab sky130_fd_sc_hd__nand2_1
XSW0 we0 vss vss vdd vdd nwe0 sky130_fd_sc_hd__inv_1
XSW1 we1 vss vss vdd vdd nwe1 sky130_fd_sc_hd__inv_1
XSB1 nab nwe0 vss vss vdd vdd bstb1 sky130_fd_sc_hd__nor2_1
XSB2 nab nwe1 vss vss vdd vdd bstb2 sky130_fd_sc_hd__nor2_1
.ends
"""
    return '\n'.join(defs) + '\n' + body
