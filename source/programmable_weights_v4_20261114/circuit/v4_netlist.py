"""The v4 additions (revision 7 of the netlist: revision 6 of DESIGN.md with the damping network) as a netlist, with the sizes as parameters, grouped as the layout is: every
layout cell is a subcircuit of its own, so that a drawn cell can be compared against it.

The circuit is also drawn as native Xschem sheets in sheets/; `python make_sheets.py check` proves that the netlist of
the sheets and this generator describe the same circuit. `python flatten_check.py` proves that this grouping, taken
apart to its devices, is the circuit the revision-5 study simulated (v4_netlist_rev5.py) plus the RES_SEL gate, the bias
block's own inverse of WRITE, and nothing else.

What is added to the accepted chip (every accepted subcircuit is used unchanged):

  cd_core_two_az_pq    the accepted neuron core, element for element, with its nodes p and q brought out as ports
  pdk_rfixed2_m, pdk_rfixed2_h_m   the accepted 200 kohm edge resistor (two 100 kohm strips) with its midpoint brought out
  xor_network_v4       the accepted network, element for element, with f1 f2 z p1 q1 p2 q2 pz qz m1 m2 brought out
  xor_chip_v4          the accepted chip's top level plus one instance per layout cell (all of it off unless WEIGHT_PROG is high):
     XMID        pw4_mid       the two midpoints' isolation switches
     XNH1 XNH2   pw4_nrn_h     a hidden neuron's west cell: bus switch, the damping network's switch (a second finger of
                               the bus switch), the helper beside R4, the switch of the helper beside R7
     XUE1 XUE2   pw4_units3d   a hidden neuron's east cell: the three units of the helper beside R7, the damping network's
                               unit and its plate (0.49 pF) to REF
     XNZ         pw4_nrn_z     the output neuron's west cell: bus switch, helper beside R4, switch and one branch of the
                               helper beside R7, the DAC edge's switch at z
     XUZ         pw4_units5    the output neuron's east cell: the DAC edge's strips, the other branch of the helper beside R7
     XDG         pw4_dacgate   the DAC edge's transmission gate, hold and inverter
     XRB         pw4_rblock4   the four programmable resistors (pw4_shunt x 2, pw4_bridge x 2) and the five bus clamps
     XDEC        pw4_decoder   the decoder in the strip (13 gates) with the pull-downs of RES_SEL and WEIGHT_PROG
     XBW         pw4_bias      the bias block: two stored bias words, their current reference, the gating of their two
                               strobes (7 gates), the pull-downs of BIAS_PROG and WRITE
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from v4lib import accepted_parts

DEFAULT = dict(
    iso_w=4.0,            # isolation switch, native NMOS, L = 0.5 (model bins: W = 0.42, 0.7, 1, 4, 10); 1 kohm on, 2 fF off
    clamp_w=1.0,          # bus and well clamps to REF, native NMOS, L = 0.5
    br_n=4, br_w=4.0, br_l=2.0,     # BRIDGE: LVT PMOS in series, W, L of each (0 to 2.5 uS)
    sh_n=2, sh_w=16.0, sh_l=2.0,    # SHUNT (0 to 20 uS)
    res_cap=10.99,        # side of each of the two capacitors that hold a resistor's gate (um)
    wr_w=0.42, wr_l=4.0,   # 5 V NMOS writer of a programmable resistor
    wr_hold_l=8.0,        # length of the weak NMOS (W = 0.42) that holds a resistor writer's middle node at REF
    unit='133333',        # one helper unit: the accepted two-strip resistor pdk_rbias2 at this value (two 0.35 um legs of 11.56 um in series)
    help_w=4.0,           # switch of a hidden neuron's helper (in series with 400 kohm)
    helpz_w=4.0, helpz_m=3,   # switch of an output-neuron helper (in series with 133 kohm): three 4 um fingers (what fits; the floorplan strand)
    dac_sw_w=4.0,         # native NMOS at the z end of the DAC edge
    dac_tg_units=8,       # the accepted transmission gate at the DAC end of the DAC edge
    dac_trim=11033,       # ohms taken off the DAC edge's third strip: the 10 kohm pin resistor, the board's 500 ohm and the two switches are part of the edge
    bias_cap=10.99,       # side of the bias word's storage capacitor (um)
    bias_fw=40.0, bias_fl=1.0,   # the bias word's follower (LVT PMOS)
    bias_wr_l=1.0,        # length of the bias word's 5 V NMOS writer (W = wr_w)
    bias_rref='286k',     # resistor that sets the bias words' own reference current (about 3.7 uA into the diode)
    bias_unit_w=2.0, bias_unit_l=1.0, bias_ref_m=8,     # reference diode = bias_ref_m units, each sink = 1 unit (about 0.46 uA); 2/1 (was 4/2): the cells strand's area, accepted with the wider pw4_tg
    bias_p_w=2.0, bias_p_l=2.0,                         # the PMOS mirror (XMP0 and each word's top source XIT); 2/2 (was 4/4)
    tg_n_w=4.0, tg_p_w=8.0, tg_l=0.5,                   # pw4_tg, between the DAC line and a bias word's read line: the mirrors' mismatch current crosses it during a write (was 1 and 2 um: 30 to 120 kohm near mid-supply)
    pd_l=8.0,             # pull-down: 5 V NMOS, W = 0.42, gate at the supply
    damp_l=10.4,          # revision 7: the damping network's plate, 23.1 um x damp_l (10.4: 0.49 pF; None: revision 6, no network)
)
# Revision 7 (adopted by the design lead 2026-11-16 02:40, with the 0.49 pF plate): the damping network inside each
# hidden neuron, on in programmed mode only (gate on iso, the line of the helpers' switches). DEFAULT['damp_l'] = 10.4;
# REVISION 6 IS generated(damp_l=None) (the same netlist without the network, byte for byte as published until then):
#   pw4_nrn_h (west cell)  XSWD, a second finger of the bus switch XSWB on the wire's one diffusion (y to dn, gate iso);
#                          both fingers with the shared diffusion as drawn: 0.58 um2 and 4.29 um on the wire side
#   pw4_units3d (east cell, in place of pw4_units3 in the hidden neurons)  the three units of the helper beside R7, a
#                          fourth unit from dn to dc, and the plate XCD (MIM, 23.1 um x damp_l) from dc to b = REF, its
#                          lower plate on REF
DAMP_W = 23.1
NODES = ['f1', 'f2', 'z', 'p1', 'q1', 'p2', 'q2', 'pz', 'qz', 'm1', 'm2']      # the network nodes brought out
BUSED = ['f1', 'f2', 'z', 'm1', 'm2']                                           # those with an isolation switch and a bus
WORDS = dict(sh1=0, sh2=1, br1=2, br2=3)                                        # resistor words: address a0 = ui[7] (SEL2), a1 = uio[2]


def mos(name, d, g, s, b, model, w, l, m=1):
    return (f'{name} {d} {g} {s} {b} sky130_fd_pr__{model} L={l:g} W={w:g} nf=1 ad={w * 0.29:.4g} as={w * 0.29:.4g} '
            f'pd={2 * (w + 0.29):.4g} ps={2 * (w + 0.29):.4g} nrd={0.29 / w:.4g} nrs={0.29 / w:.4g} sa=0 sb=0 sd=0 mult={m} m={m}')


def mos_geo(name, d, g, s, b, model, w, l, ad, as_, pd, ps, m=1):
    """mos() with the diffusions as drawn (a diffusion shared by two fingers)."""
    return (f'{name} {d} {g} {s} {b} sky130_fd_pr__{model} L={l:g} W={w:g} nf=1 ad={ad:g} as={as_:g} pd={pd:g} ps={ps:g} '
            f'nrd={0.29 / w:.4g} nrs={0.29 / w:.4g} sa=0 sb=0 sd=0 mult={m} m={m}')


def mim(name, top, bottom, side):
    return f'{name} {top} {bottom} sky130_fd_pr__cap_mim_m3_1 W={side:g} L={side:g} MF=1 m=1'


def core_pq():
    """The accepted neuron core with p and q as two more ports. Body unchanged."""
    _, subs = accepted_parts()
    m = re.search(r'(?ms)^\.subckt cd_core_two_az natural bpin reset hold_in y h ref vdd vss  DPROG=2\.5\n(.*?)^\.ends', subs)
    assert m
    return '.subckt cd_core_two_az_pq natural bpin reset hold_in y h ref vdd vss p q  DPROG=2.5\n*.iopin p\n*.iopin q\n' + m[1] + '.ends\n'


def edge_mid():
    """The accepted 200 kohm edge resistor (two 100 kohm strips in series) with the node between the strips as a port."""
    _, subs = accepted_parts()
    m = re.search(r'(?ms)^\.subckt pdk_rfixed2 p n bulk  RVALUE=100k\n(.*?)^\.ends', subs)
    assert m and m[1].count('net1') == 2
    inner = '.subckt pdk_rfixed2_m p n bulk m  RVALUE=100k\n*.iopin m\n' + m[1].replace('net1', 'm') + '.ends\n'
    return inner + ('.subckt pdk_rfixed2_h_m p n bulk m  RVALUE=100k\n*.iopin p\n*.iopin n\n*.iopin bulk\n*.iopin m\n'
                    'XDEVICE p n bulk m pdk_rfixed2_m RVALUE={RVALUE}\n.ends\n')


def network_v4():
    """The accepted network with eleven nodes as ports. Element lines unchanged except the cell names of the three cores
    and of the two hidden-to-output resistors, which gain pins."""
    _, subs = accepted_parts()
    m = re.search(r'(?ms)^\.subckt xor_network (reset hold_in bias1 bias2 vbn ref pad vdd vss obs_sel0 obs_sel1 obs_sel2 pad2 obs2_sel0 obs2_sel1)  (CORE_MATCH=1 READ_MATCH=1)\n(.*?)^\.ends', subs)
    assert m
    body = m[3]
    for inst, ports, p, q in (('XH1', 'natural1 bias1 reset hold_in f1 h1 ref vdd vss', 'p1', 'q1'),
                              ('XH2', 'natural2 bias2 reset hold_in f2 h2 ref vdd vss', 'p2', 'q2'),
                              ('XZ', 'hz ref reset hold_in z hz ref vdd vss', 'pz', 'qz')):
        old = f'{inst} {ports} cd_core_two_az DPROG='
        assert body.count(old) == 1, old
        body = body.replace(old, f'{inst} {ports} {p} {q} cd_core_two_az_pq DPROG=')
    for inst, f, mid in (('XRW4', 'f1', 'm1'), ('XRW5', 'f2', 'm2')):
        old = f'{inst} z {f} vss pdk_rfixed2_h RVALUE=200k'
        assert body.count(old) == 1, old
        body = body.replace(old, f'{inst} z {f} vss {mid} pdk_rfixed2_h_m RVALUE=200k')
    return (f".subckt xor_network_v4 {m[1]} {' '.join(NODES)}  {m[2]}\n"
            + ''.join(f'*.iopin {n}\n' for n in NODES) + body + '.ends\n')


def cells(o):
    s = []
    s.append(f""".subckt pw4_clamp a ref en vss
* holds a at REF while en is high
{mos('XCL', 'a', 'en', 'ref', 'vss', 'nfet_03v3_nvt', o['clamp_w'], 0.5)}
.ends
""")
    for name, n, w, l, what in (('pw4_bridge', o['br_n'], o['br_w'], o['br_l'], 'BRIDGE across an edge (z bus to f bus), 0 to 2.5 uS: raises the weight'),
                                ('pw4_shunt', o['sh_n'], o['sh_w'], o['sh_l'], "SHUNT from an edge's midpoint bus to REF, 0 to 20 uS: lowers the weight")):
        caps = mim('XCA', 'gn', 'a', o['res_cap']) + '\n' + mim('XCB', 'gn', 'b', o['res_cap'])
        if n == 2:
            chain = (mos('XPA', 'a', 'gn', 'mid', 'mid', 'pfet_01v8_lvt', w, l) + '\n'
                     + mos('XPB', 'b', 'gn', 'mid', 'mid', 'pfet_01v8_lvt', w, l))
        else:       # four in series, one well (mid), one gate
            assert n == 4
            chain = '\n'.join([mos('XPA', 'a', 'gn', 'ma', 'mid', 'pfet_01v8_lvt', w, l), mos('XPA2', 'ma', 'gn', 'mid', 'mid', 'pfet_01v8_lvt', w, l),
                               mos('XPB2', 'mb', 'gn', 'mid', 'mid', 'pfet_01v8_lvt', w, l), mos('XPB', 'b', 'gn', 'mb', 'mid', 'pfet_01v8_lvt', w, l)])
        s.append(f""".subckt {name} a b ref dac we clamp vdd vss
* Programmable resistor, {what}.
* LVT PMOS in series between a and b with one gate gn (the stored node) and one well (mid). gn is written from the DAC
* line while a, b and the well are held at REF (the buses' clamps and XCLM); afterwards it floats and rides on the
* terminals through its two capacitors. The conductance falls as the code rises; above about 1.1 V it is zero.
* Writer, in two stages as in the bias word: at the gate a 5 V NMOS (passes codes up to 0.6 to 0.8 V) beside an LVT
* PMOS (passes the codes above, so the resistor can be shut off at every corner); then a transmission gate to the DAC
* line. When not writing, the node between the stages (wm) is held at REF: the stored gate has REF behind its off
* writer whatever the DAC line does. The hold (XWC) is a long, weak NMOS on purpose: if the transmission gate to the
* DAC line ever failed shorted, REF would see at most a microampere from the DAC pin, not 80.
{chain}
{caps}
{mos('XW1N', 'gn', 'we', 'wm', 'vss', 'nfet_g5v0d10v5', o['wr_w'], o['wr_l'])}
{mos('XW1P', 'gn', 'we_b', 'wm', 'vdd', 'pfet_01v8_lvt', 1, 1)}
XW2 wm dac we we_b vdd vss cd_tg_small
{mos('XWC', 'wm', 'we_b', 'ref', 'vss', 'nfet_01v8', 0.42, o['wr_hold_l'])}
XWI we we_b vdd vss cmos_inv
{mos('XCLM', 'mid', 'clamp', 'ref', 'vss', 'nfet_03v3_nvt', o['clamp_w'], 0.5)}
.ends
""")
    # a unit is the accepted two-strip resistor (two legs in series): one straight strip of 23 um fits no floor in a neuron
    unit = lambda name, a, b: f"{name} {a} {b} vss pdk_rbias2 RVALUE={o['unit']}"
    sw = lambda name, a, b, w, m=1: mos(name, a, 'iso', b, 'vss', 'nfet_03v3_nvt', w, 0.5, m)
    if o.get('damp_l') is None:                                    # revision 6
        hidden_cells = f""".subckt pw4_nrn_h y p q bus qs iso vss
* A hidden neuron's west cell: three switches in a row and three unit strips. y is the neuron's wire (f1 or f2).
*   XSWB  isolation switch: the wire y to its bus
*   XSW4, XU1..XU3  the helper beside R4: switch AT THE WIRE, then three units in series to p (400 kohm, 2.5 uS)
*   XSW7  the switch of the helper beside R7: q to qs; its three units are the east cell (pw4_units3), qs to REF
{sw('XSWB', 'y', 'bus', o['iso_w'])}
{sw('XSW4', 'y', 'n1', o['help_w'])}
{unit('XU1', 'n1', 'n2')}
{unit('XU2', 'n2', 'n3')}
{unit('XU3', 'n3', 'p')}
{sw('XSW7', 'q', 'qs', o['help_w'])}
.ends
.subckt pw4_units3 a b vss
* A hidden neuron's east cell: three unit strips in series (the helper beside R7, from its switch to REF).
{unit('XU1', 'a', 'n2')}
{unit('XU2', 'n2', 'n3')}
{unit('XU3', 'n3', 'b')}
.ends
"""
    else:                                                          # revision 7 (proposal)
        fing = lambda name, s_: mos_geo(name, 'y', 'iso', s_, 'vss', 'nfet_03v3_nvt', o['iso_w'], 0.5, 0.58, 1.16, 4.29, 8.58)
        hidden_cells = f""".subckt pw4_nrn_h y p q bus qs dn iso vss
* A hidden neuron's west cell: four switches and three unit strips. y is the neuron's wire (f1 or f2).
*   XSWB  isolation switch: the wire y to its bus
*   XSWD  the damping network's switch (revision 7): the wire y to dn, a second finger of XSWB on the same diffusion
*         of the wire (each finger has 0.58 um2 and 4.29 um of it); its unit and plate are in the east cell
*   XSW4, XU1..XU3  the helper beside R4: switch AT THE WIRE, then three units in series to p (400 kohm, 2.5 uS)
*   XSW7  the switch of the helper beside R7: q to qs; its three units are the east cell (pw4_units3d), qs to REF
{fing('XSWB', 'bus')}
{fing('XSWD', 'dn')}
{sw('XSW4', 'y', 'n1', o['help_w'])}
{unit('XU1', 'n1', 'n2')}
{unit('XU2', 'n2', 'n3')}
{unit('XU3', 'n3', 'p')}
{sw('XSW7', 'q', 'qs', o['help_w'])}
.ends
.subckt pw4_units3d a b dn vss
* A hidden neuron's east cell (revision 7): the three units of the helper beside R7, from its switch to REF (a to b),
* and the damping network behind the west cell's XSWD: one unit from dn, then the plate to REF (b), lower plate on REF.
* In programmed mode the network lies from the wire to REF: above 1/(2 pi R C) it lowers the first amplifier's feedback
* factor, so its loop crosses over lower; it has no path at DC. In fixed mode XSWD is off and only its finger is on y.
{unit('XU1', 'a', 'n2')}
{unit('XU2', 'n2', 'n3')}
{unit('XU3', 'n3', 'b')}
{unit('XU4', 'dn', 'dc')}
XCD dc b sky130_fd_pr__cap_mim_m3_1 W={DAMP_W:g} L={o['damp_l']:g} MF=1 m=1
.ends
"""
    s.append(f""".subckt pw4_mid m1 m2 b1 b2 iso vss
* The two midpoints' isolation switches (one cell between the two hidden-to-output resistor pairs): midpoint to its bus.
{sw('XSW1', 'm1', 'b1', o['iso_w'])}
{sw('XSW2', 'm2', 'b2', o['iso_w'])}
.ends
{hidden_cells}.subckt pw4_nrn_z y p q bus qs nm ref iso vss
* The output neuron's west cell: four switches in a row and three unit strips. y is the neuron's wire (z).
*   XSWB  isolation switch: the wire y to its bus
*   XSW4, XU1  the helper beside R4: switch at the wire (three 4 um fingers), one unit to p (133 kohm, 7.5 uS)
*   XSW7  the switch of the helper beside R7 (three fingers): q to qs. XU2, XU3: one of its two branches, two units in
*         series from qs to REF; the other branch is in the east cell (pw4_units5)
*   XSZ   the DAC edge's switch at the wire: y to nm; its strips are in the east cell
{sw('XSWB', 'y', 'bus', o['iso_w'])}
{sw('XSW4', 'y', 'n1', o['helpz_w'], o['helpz_m'])}
{unit('XU1', 'n1', 'p')}
{sw('XSW7', 'q', 'qs', o['helpz_w'], o['helpz_m'])}
{unit('XU2', 'qs', 'n2')}
{unit('XU3', 'n2', 'ref')}
{sw('XSZ', 'y', 'nm', o['dac_sw_w'])}
.ends
.subckt pw4_units5 nm nd qs ref vss
* The output neuron's east cell: five strips.
*   XU1..XU3  the DAC edge, nm to nd. The third strip is shorter than a unit by what the pin resistor, the board and the
*             edge's two switches add, so that the whole edge from ua[1] to z is three units (less the 0.2% that the output
*             neuron's helpers lose in their own switches).
*   XU4, XU5  the second branch of the helper beside R7: two units in series from qs to REF
{unit('XU1', 'nm', 'n2')}
{unit('XU2', 'n2', 'n3')}
XU3 n3 nd vss pdk_rbias2 RVALUE={int(o['unit']) - o['dac_trim']}
{unit('XU4', 'qs', 'n4')}
{unit('XU5', 'n4', 'ref')}
.ends
.subckt pw4_dacgate nd dac ref iso vdd vss
* The DAC edge's gate, in the output neuron: nd -- transmission gate -- DAC line -- (pin resistor) -- ua[1].
* iso high: (V_DAC - REF) x 0.25 is added to the output neuron's drive (its bank is matched for this edge, so there is
* no spring): the output bias, and the nudge. iso low: nd is held at REF (XCL), so the switch on z has REF behind the
* strips and the DAC line cannot reach z whatever its voltage. `off` is made here from `iso`.
{mos('XCL', 'nd', 'off', 'ref', 'vss', 'nfet_03v3_nvt', o['clamp_w'], 0.5)}
XSD nd dac iso off vdd vss transmission_gate UNITS={o['dac_tg_units']}
XOFF iso off vdd vss cmos_inv
.ends
.subckt pw4_rblock4 f1x f2x zx m1x m2x ref dac we0 we1 we2 we3 clampw vdd vss
* The row of the four programmable resistors with the five buses' clamps.
XBCL_f1 f1x ref clampw vss pw4_clamp
XBCL_f2 f2x ref clampw vss pw4_clamp
XBCL_z zx ref clampw vss pw4_clamp
XBCL_m1 m1x ref clampw vss pw4_clamp
XBCL_m2 m2x ref clampw vss pw4_clamp
XSH1 m1x ref ref dac we0 clampw vdd vss pw4_shunt
XSH2 m2x ref ref dac we1 clampw vdd vss pw4_shunt
XBR1 zx f1x ref dac we2 clampw vdd vss pw4_bridge
XBR2 zx f2x ref dac we3 clampw vdd vss pw4_bridge
.ends
""")
    s.append(f""".subckt pw4_pulldown a vdd vss
* weak pull-down: a long 5 V NMOS with its gate at the supply
{mos('XPD', 'a', 'vdd', 'vss', 'vss', 'nfet_g5v0d10v5', 0.42, o['pd_l'])}
.ends
""")
    s.append(f""".subckt pw4_tg a b en en_b vdd vss
* a transmission gate of 0.5 um transistors: it leaks far less when off than the 0.15 um ones
{mos('XMN', 'a', 'en', 'b', 'vss', 'nfet_01v8', o['tg_n_w'], o['tg_l'])}
{mos('XMP', 'a', 'en_b', 'b', 'vdd', 'pfet_01v8', o['tg_p_w'], o['tg_l'])}
.ends
""")
    s.append(bias_cells(o))
    s.append(control())
    return '\n'.join(s)


def bias_cells(o):
    unit = lambda name, d, m=1: mos(name, d, 'nref', 'vss', 'vss', 'nfet_01v8', o['bias_unit_w'], o['bias_unit_l'], m)
    return f""".subckt pw4_bias_word dac line we bp bp_b nref pref ref vdd vss
* One stored bias. XF is a PMOS follower: gate sg (the stored node), source = the read line, which goes to the
* EXTERNAL input of the accepted bias switch.
* Idle (bp low, we low): the DAC line is on the read line through XDL, so the accepted external-bias function is
*   unchanged; every current source is off and nothing flows.
* Write (we high, bp low): the DAC holds the line. The sink XIS pulls the read current through the follower and the
*   writer (XW1N, XW1P, XW2) joins the follower's drain to its gate, so the gate takes the value that puts the line at
*   the DAC voltage at the read current. XTW returns the same current to the line, so none flows in the DAC pin.
* Read (bp high): the DAC is off the line, the drain is grounded (XRD) and the top source XIT feeds the line (XTS).
* Not writing: the writer's middle node wm is held at REF (XWC), so the off writer has REF on its far side.
{mos('XF', 'drn', 'sg', 'line', 'line', 'pfet_01v8_lvt', o['bias_fw'], o['bias_fl'])}
{mim('XST', 'sg', 'ref', o['bias_cap'])}
{mos('XW1N', 'sg', 'we', 'wm', 'vss', 'nfet_g5v0d10v5', o['wr_w'], o['bias_wr_l'])}
{mos('XW1P', 'sg', 'we_b', 'wm', 'vdd', 'pfet_01v8_lvt', 1, 1)}
XW2 wm drn we we_b vdd vss cd_tg_small
XWC wm ref we_b we vdd vss cd_tg_small
XWI we we_b vdd vss cmos_inv
{mos('XIT', 'top', 'pref', 'vdd', 'vdd', 'pfet_01v8', o['bias_p_w'], o['bias_p_l'])}
{mos('XTS', 'line', 'bp_b', 'top', 'vdd', 'pfet_01v8', 1, 0.5)}
{mos('XTW', 'line', 'we_b', 'top', 'vdd', 'pfet_01v8', 1, 0.5)}
{unit('XIS', 'tail')}
{mos('XSS', 'drn', 'we', 'tail', 'vss', 'nfet_01v8', 1, 0.5)}
{mos('XRD', 'drn', 'bp', 'vss', 'vss', 'nfet_01v8', 1, 0.5)}
XDL dac line bp_b bp vdd vss pw4_tg
.ends
.subckt pw4_bias dac bw1 bw2 e1 e2 bias_prog write ref vdd vss
* The bias block: the two bias words, their own current reference (a resistor into a diode; nothing hangs on the
* chip's vbn), the gating of their two write strobes and the pull-downs of BIAS_PROG and WRITE.
* A bias word is written while WRITE and its external-bias enable (e1 = uio[0], e2 = uio[1]) are high and BIAS_PROG is
* low. The block makes its own inverse of WRITE (the decoder in the strip has another).
XIWB write nwrite vdd vss cmos_inv
XIE1 e1 ne1 vdd vss cmos_inv
XIE2 e2 ne2 vdd vss cmos_inv
XB1 nwrite ne1 bias_prog wb1 vdd vss cmos_nor3
XB2 nwrite ne2 bias_prog wb2 vdd vss cmos_nor3
XBPB bias_prog bp_b vdd vss cmos_inv
XBP bp_b bp vdd vss cmos_inv
XPD4 bias_prog vdd vss pw4_pulldown
XPD5 write vdd vss pw4_pulldown
XRREF vdd nref vss pdk_rbias2_v RVALUE={o['bias_rref']}
{unit('XMREF', 'nref', o['bias_ref_m'])}
{unit('XMN0', 'pref')}
{mos('XMP0', 'pref', 'pref', 'vdd', 'vdd', 'pfet_01v8', o['bias_p_w'], o['bias_p_l'])}
XW1 dac bw1 wb1 bp bp_b nref pref ref vdd vss pw4_bias_word
XW2 dac bw2 wb2 bp bp_b nref pref ref vdd vss pw4_bias_word
.ends
"""


def control():
    """The decoder in the strip. Resistor words 0..3 (shunt 1, shunt 2, bridge 1, bridge 2) are addressed by a0 = ui[7]
    (SEL2) and a1 = uio[2]; one is written only while WRITE and RES_SEL are high and WEIGHT_PROG is low, so a bias write
    (RES_SEL low) cannot store into a resistor word. Also the two mode lines iso and clampw, and the pull-downs of RES_SEL
    and WEIGHT_PROG. Every output is still unless WRITE is high or WEIGHT_PROG changes."""
    g = ['.subckt pw4_decoder a0 a1 write res_sel weight_prog we0 we1 we2 we3 iso clampw vdd vss',
         'XIW write nwrite vdd vss cmos_inv',
         'XIA0 a0 na0 vdd vss cmos_inv', 'XIA1 a1 na1 vdd vss cmos_inv',
         '* gw: writing a resistor word is allowed (WRITE high, RES_SEL high, WEIGHT_PROG low); ngw high keeps every strobe low',
         'XIRS res_sel nrs vdd vss cmos_inv',
         'XGW nwrite nrs weight_prog gw vdd vss cmos_nor3', 'XGWB gw ngw vdd vss cmos_inv']
    for k in range(4):
        g.append(f"XD{k} {'na0' if k & 1 else 'a0'} {'na1' if k & 2 else 'a1'} ngw we{k} vdd vss cmos_nor3")
    g += ['* clampw (to the many clamps) and iso (to the switches) each come from the pin through their own gates:',
          '* clampw stuck either way cannot turn a switch on',
          'XWPB weight_prog clampw vdd vss cmos_inv', 'XWN weight_prog nwp vdd vss cmos_inv', 'XWP nwp iso vdd vss cmos_inv',
          'XPD6 res_sel vdd vss pw4_pulldown', 'XPD7 weight_prog vdd vss pw4_pulldown', '.ends', '']
    return '\n'.join(g)


def chip(o):
    _, subs = accepted_parts()
    m = re.search(r'(?ms)^\.subckt xor_chip_staged (.*?)  (CORE_MATCH=1 READ_MATCH=1)\n(.*?)^\.ends', subs)
    assert m
    body = m[3]
    for old, new in (
            ('XNET reset hold_in bias1 bias2 vbn ref pad vdd vss obs_sel0 obs_sel1 obs_sel2 pad2 obs2_sel0 obs2_sel1 xor_network ',
             f"XNET reset hold_in bias1 bias2 vbn ref pad vdd vss obs_sel0 obs_sel1 obs_sel2 pad2 obs2_sel0 obs2_sel1 {' '.join(NODES)} xor_network_v4 "),
            ('XEXT1 sel1_ladder ext_in ext_en1 bias1_in vdd vss ext_bias_switch', 'XEXT1 sel1_ladder bw1 ext_en1 bias1_in vdd vss ext_bias_switch'),
            ('XEXT2 sel2_ladder ext_in ext_en2 bias2_in vdd vss ext_bias_switch', 'XEXT2 sel2_ladder bw2 ext_en2 bias2_in vdd vss ext_bias_switch')):
        assert body.count(old) == 1, old
        body = body.replace(old, new)
    add = ['* ---- v4 additions, one instance per layout cell',
           'XMID m1 m2 m1x m2x iso vss pw4_mid',
           *(('XNH1 f1 p1 q1 f1x qs1 iso vss pw4_nrn_h', 'XUE1 qs1 ref vss pw4_units3',
               'XNH2 f2 p2 q2 f2x qs2 iso vss pw4_nrn_h', 'XUE2 qs2 ref vss pw4_units3') if o.get('damp_l') is None else
             ('XNH1 f1 p1 q1 f1x qs1 dn1 iso vss pw4_nrn_h', 'XUE1 qs1 ref dn1 vss pw4_units3d',
              'XNH2 f2 p2 q2 f2x qs2 dn2 iso vss pw4_nrn_h', 'XUE2 qs2 ref dn2 vss pw4_units3d')),
           'XNZ z pz qz zx qsz nm ref iso vss pw4_nrn_z', 'XUZ nm nd qsz ref vss pw4_units5',
           'XDG nd ext_in ref iso vdd vss pw4_dacgate',
           'XRB f1x f2x zx m1x m2x ref ext_in we0 we1 we2 we3 clampw vdd vss pw4_rblock4',
           'XDEC obs_sel2 obs2_sel0 write res_sel weight_prog we0 we1 we2 we3 iso clampw vdd vss pw4_decoder',
           'XBW ext_in bw1 bw2 ext_en1 ext_en2 bias_prog write ref vdd vss pw4_bias']
    pins = m[1] + ' bias_prog write res_sel weight_prog'
    return f'.subckt xor_chip_v4 {pins}  {m[2]}\n' + body + '\n'.join(add) + '\n.ends\n'


# stored nodes (floating by design): hierarchical names under xdut
RES_GATES = {n: f'xdut.xrb.{n.lower()}.gn' for n in ('XSH1', 'XSH2', 'XBR1', 'XBR2')}
BIAS_GATES = {'XBW.XW1': 'xdut.xbw.xw1.sg', 'XBW.XW2': 'xdut.xbw.xw2.sg'}
STORED = dict(RES_GATES, **BIAS_GATES)


def generated(**over):
    """The v4 subcircuits from this generator (sizes of DEFAULT unless overridden)."""
    o = dict(DEFAULT, **over)
    return '\n'.join(['* ================= v4 (programmable_weights_v4_20261114/circuit/v4_netlist.py)',
                      chip(o), network_v4(), core_pq(), edge_mid(), cells(o)])


def subckts(**over):
    """What every bench simulates: this generator's netlist (sizes from DEFAULT unless overridden). The native sheets
    are proven to netlist to exactly this circuit by `make_sheets.py check`, which writes the sheets' own netlist to
    sheets/v4_sheets_netlist.spice for comparison; the benches do not read that file."""
    return generated(**over)


if __name__ == '__main__':
    sys.stdout.write(subckts())
