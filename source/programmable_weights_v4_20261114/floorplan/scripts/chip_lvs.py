"""Layout against schematic of the whole v4 chip (plan r6), and its negative controls.

  python chip_lvs.py              extraction of build/r6, netgen against xor_chip_v4, then the negative controls
                                  -> results/r6_lvs.json, results/r6_lvs_negative_controls.json
  python chip_lvs.py control      the same method on the accepted chip rebuilt here (build/acc) against the accepted
                                  xor_chip_staged: it must match as the accepted flow's own LVS does -> results/acc_lvs_flat.json

Layout. Magic (8.3.685, the PDK's rc file) loads the built top cell, flattens it and extracts (`extract all`,
`ext2spice lvs`). So everything drawn is one flat netlist: the hand-drawn taps over the accepted neurons and over the
resistor block (a flat extraction joins top-level metal to the metal under it), the row of the four programmable
resistors (RBLOCK = pw4_rblock4, the cells strand's drawn cell: 57 devices after netgen joins fingers) and, since
2026-11-15 14:15, the bias block (BIAS = pw4_bias, the cells strand's drawn cell: 64 devices). No cell is a black box
any more; netgen runs without -blackbox.

Reference. The accepted flow's reference handling (chip2x2/scripts/make_ref.py and the 3x2 module it loads, imported, not
copied; nothing is written into the accepted folder): the accepted native deck (aj_native_chip.spice) followed by the
circuit strand's v4 subcircuits (circuit/v4_netlist.py generated()) is walked from xor_chip_v4 under the Tiny Tapeout pin
names; amplifier instances become the verified amplifier cells, standard cells stay standard-cell instances, every other
device is flattened with its parameters EVALUATED (netgen does not evaluate formulas: pdk_rbias2, transmission_gate and
the resistor banks get their numbers here). Said in the reference's header and in the result file:
  - pw4_rblock4 and pw4_bias are walked like every other cell, from the same subcircuits that the cells strand's own
    references hold (cells/ref/pw4_rblock4_ref.spice, cells/ref/pw4_bias_ref.spice, against which each cell alone
    matched): strand_reference() compares the texts device line by device line and the run stops if they differ. One
    line is allowed to differ in form, and is checked: the cells strand writes the bias block's 286 kohm strip pair as
    a subcircuit with its length evaluated (pdk_rbias2_r286000, two legs of 24.92 um), the netlist as pdk_rbias2_v
    RVALUE=286k; the formula is evaluated here and must give the same two lines. Neither cell has a dummy device;
  - the decoder's two pull-downs XPD6, XPD7 (pw4_pulldown, the cells strand's cell, two copies inside the drawn decoder
    since Nov 15, 13:30) are walked like every other device; PULLDOWNS is empty (a line put there is taken out of the
    reference, as it was while the decoder had none);
  - the layout's grounded dummy strips are added as layout additions: the accepted chip's list, and the dummies at the
    ends of the strip arrays of the drawn cells (as cellwork/scripts/compare_circuit.py adds them per cell).

The result must be a unique match with no property errors (the report text is searched for "property errors").
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "r6"
assert MODE in ("r6", "control"), MODE
os.environ["V4_AREA"] = "r6" if MODE == "r6" else "acc"
sys.dont_write_bytecode = True                       # nothing is written beside another strand's or the accepted scripts

import magic_util  # noqa: E402
from magic_util import BUILD, LAYOUT, NETGEN, NETGEN_SETUP, OUT, OUT_RESULTS, TOP, X, run_magic  # noqa: E402
import chip  # noqa: E402
from geom import Tcl  # noqa: E402
import make_ref  # noqa: E402   the accepted 2x2 module (chip2x2/scripts/make_ref.py); make_ref.m is the 3x2 module it configures

M = make_ref.m
CIRCUIT = OUT.parent / "circuit"
WORK = BUILD / "lvs"
CELLS_REF = OUT / "cells_in" / "ref"                    # the cells strand's own references, each for its cell alone (the delivery in cells_in/)
V4_PINS = {"bias_prog": "uio_in[4]", "write": "uio_in[5]", "res_sel": "uio_in[6]", "weight_prog": "uio_in[7]"}
RX = "sky130_fd_pr__res_xhigh_po_0p35"
L_LEG, L_LEG_DAC = 11.56, 10.60                      # cellwork/scripts/devices.py
# grounded dummy strips of the drawn cells (cellwork/scripts/compare_circuit.py DUMMIES), per instance on the chip
CELL_DUMMIES = {"pw4_units3d": [L_LEG, L_LEG], "pw4_nrn_h": [L_LEG, L_LEG], "pw4_nrn_z": [L_LEG, L_LEG], "pw4_units5": [L_LEG_DAC, L_LEG]}
PULLDOWNS = ()                                       # instance lines of pw4_decoder to leave out of the reference (none)


NETLIST_FROM = []                                    # where the v4 subcircuits came from (rev7.netlist()), for the result file


def v4_text():
    import rev7
    text, src = rev7.netlist()
    NETLIST_FROM[:] = [src]
    return text


# ---------------------------------------------------------------- layout
def extract():
    """Flat extraction of the built top cell; returns (path of the layout netlist, Magic's messages)."""
    WORK.mkdir(parents=True, exist_ok=True)
    t = Tcl()
    t.add("snap internal")
    t.add(f"load {TOP}")
    t.add("select top cell")
    t.add("expand")
    t.add("flatten v4_lvs_flat")
    t.add("load v4_lvs_flat")
    t.add("select top cell")
    t.add(f"cd {WORK}")
    t.add("extract do local")
    t.add("extract all")
    t.add("ext2spice lvs")
    t.add("ext2spice -o v4_lvs_flat.spice")
    t.add(f"cd {LAYOUT}")
    t.add("quit -noprompt")
    log = run_magic(t.text(), "chip_lvs_extract", timeout=6 * 3600)
    text = (WORK / "v4_lvs_flat.spice").read_text()
    text = re.sub(r"\n\+\s*", " ", text)
    assert len(re.findall(r"(?m)^\.subckt ", text)) == 1, "the flat extraction holds more than one subcircuit: a cell was not flattened"
    text = re.sub(r"(?m)^\.subckt v4_lvs_flat ", f".subckt {TOP} ", text)
    text = re.sub(r"(?m)^\.ends v4_lvs_flat", f".ends {TOP}", text)
    out = WORK / f"{TOP}_lvs.spice"
    out.write_text(text)
    warn = [l for l in log.splitlines() if re.search(r"(?i)error|can't|cannot|not found", l)]
    return out, warn


# ---------------------------------------------------------------- reference
def reference(name="ref", edits=(), item_edits=()):
    """The reference netlist. edits: (old, new) text replacements in the v4 subcircuits (each must occur once);
    item_edits: (instance path, connection index, new net) on the walked devices. Returns (path, notes)."""
    acc_text = chip.DECK.read_text()
    if MODE == "control":
        root, v4, tt = "xor_chip_staged", "", dict(M.TT_MAP)
    else:
        root, tt = "xor_chip_v4", dict(M.TT_MAP, **V4_PINS)
        v4 = v4_text()
        for line in PULLDOWNS:
            assert v4.count(line) == 1, line
            v4 = v4.replace(line + "\n", "")
        for old, new in edits:
            assert v4.count(old) == 1, (old, v4.count(old))
            v4 = v4.replace(old, new)
    subs = M.subckts(acc_text + "\n" + v4)
    genv = M.deck_params(acc_text)
    items = []
    M.walk(subs, root, [tt[p] for p in subs[root][0]], {}, "", items, genv)
    for path, k, net in item_edits:
        hit = [i for i, it in enumerate(items) if it[1] == path]
        assert len(hit) == 1, path
        kind, p, model, conns, vals = items[hit[0]]
        conns = list(conns)
        conns[k] = net
        items[hit[0]] = (kind, p, model, conns, vals)
    dummies = [(m.split()[0], m.split()[1], n, w) for m, n, w in M.CHIP_DUMMIES]
    if MODE == "r6":
        import v4_plan as plan
        per = {}
        for n, c, *_ in plan.ALL_PLACE:
            for l in CELL_DUMMIES.get(c, []):
                per[(c, l)] = per.get((c, l), 0) + 1
        dummies += [(RX, f"L={l:g}", n, f"{c} (end strips of its arrays)") for (c, l), n in per.items()]
    cells = sorted({it[2] for it in items if it[0] == "cell"})
    lines = [f"* LVS reference for the whole chip ({TOP}), made by floorplan/scripts/chip_lvs.py ({name}).",
             f"* Root {root}: the accepted deck feasibility_20261107/floorplan/chip2x2/ref/aj_native_chip.spice"
             + (" followed by programmable_weights_v4_20261114/circuit/v4_netlist.py generated()" if v4 else "") + ",",
             "* walked by the accepted flow's make_ref (amplifiers = verified cells, standard cells kept, other devices flattened",
             "* with their parameters evaluated), under Tiny Tapeout pin names.",
             "* Layout additions, all three terminals on VGND:", *[f"*   {n} x {m} {l} ({w})" for m, l, n, w in dummies]]
    if MODE == "r6":
        lines += ["* No black box: pw4_rblock4 and pw4_bias are walked like every other cell.",
                  *(["* Taken out of pw4_decoder: " + "; ".join(PULLDOWNS) + "."] if PULLDOWNS else [])]
    for old, new in edits:
        lines.append(f"* NEGATIVE CONTROL edit: '{old}' -> '{new}'")
    for path, k, net in item_edits:
        lines.append(f"* NEGATIVE CONTROL edit: device {path}, terminal {k} -> {net}")
    lines.append("")
    written: set = set()
    lines += M.std_defs({it[2] for it in items if it[0] == "std"}, written)
    lines += M.amp_defs(cells, written)
    lines.append(f".subckt {TOP} " + " ".join(M.TT_PORTS))
    lines += [M.fmt(*it) for it in items]
    k = 0
    for model, lp, n, _ in dummies:
        for _ in range(n):
            lines.append(f"XDUMMY{k} VGND VGND VGND {model} {lp}")
            k += 1
    lines.append(f".ends {TOP}")
    path = WORK / f"{TOP}_{name}.spice"
    WORK.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path, dict(root=root, black_boxes=[], dummies=[f"{n} x {m} {l} ({w})" for m, l, n, w in dummies],
                      left_out_of_pw4_decoder=list(PULLDOWNS) if MODE == "r6" else [])


def strand_reference(cell):
    """Is the reference the cells strand checked its cell against the netlist this chip reference is walked from? Every
    subcircuit of cells/ref/<cell>_ref.spice (but the PDK's standard cells) against the subcircuit of the same name in
    the accepted deck + circuit/v4_netlist.py generated(): ports and device lines, comments aside. The run stops on a
    difference. Allowed, and checked, for pw4_bias: its 286 kohm strip pair (see the head of this file)."""
    def body(text):
        return {n: (p.split(), [l for l in b.splitlines() if l.strip() and not l.startswith("*")])
                for n, p, b in re.findall(r"(?ms)^\.subckt (\S+) ([^\n]*)\n(.*?)^\.ends", re.sub(r"\n\+\s*", " ", text))}
    file = CELLS_REF / f"{cell}_ref.spice"
    theirs = body(file.read_text())
    ours = body(chip.DECK.read_text() + "\n" + v4_text())
    note = None
    if cell == "pw4_bias":
        # theirs: XRREF vdd nref vss pdk_rbias2_r286000, a subcircuit of two strips with L written out;
        # ours:   XRREF vdd nref vss pdk_rbias2_v RVALUE=286k -> pdk_rbias2 with L as a formula of RVALUE
        a, b = "XRREF vdd nref vss pdk_rbias2_r286000", "XRREF vdd nref vss pdk_rbias2_v RVALUE=286k"
        assert theirs[cell][1].count(a) == 1 and ours[cell][1].count(b) == 1, "the bias block's reference resistor is not written as expected"
        theirs[cell] = (theirs[cell][0], [b if l == a else l for l in theirs[cell][1]])
        ports, strips = theirs.pop("pdk_rbias2_r286000")
        evaluated = []
        for l in ours["pdk_rbias2"][1]:
            expr = re.search(r"L=(\{[^}]*\})", l)[1]
            evaluated.append(l.replace(expr, f"{M.ev(expr, dict(RVALUE=286e3)):g}"))
        assert ports == ours["pdk_rbias2"][0][:3] and strips == evaluated and ours["pdk_rbias2_v"][1] == ["XDEVICE p n bulk pdk_rbias2 RVALUE={RVALUE}"], \
            ("the cells strand's 286 kohm strip pair is not the netlist's pdk_rbias2 at RVALUE=286k", strips, evaluated)
        note = "pdk_rbias2_r286000 (cells strand: " + "; ".join(strips) + ") = the netlist's pdk_rbias2_v RVALUE=286k with the PDK's length formula evaluated"
    same = {n: ours.get(n) == v for n, v in theirs.items() if not n.startswith("sky130_fd_sc_")}
    assert same.get(cell) and all(same.values()), f"the cells strand's reference for {cell} is not the netlist's: {same}"

    def count(name):                                     # devices under a subcircuit: a transistor, strip or capacitor each; a standard cell by its own transistors
        n = 0
        for l in ours[name][1] if name in ours else theirs[name][1]:
            model = [x for x in l.split() if "=" not in x][-1]
            n += 1 if model.startswith("sky130_fd_pr__") else count(model)
        return n
    return dict(file=str(file.relative_to(OUT.parent)), subcircuits_equal_to_the_netlists=same, devices_the_reference_writes=count(cell),
                **({"allowed_difference_in_form": note} if note else {}))


# ---------------------------------------------------------------- netgen
def netgen(lay, ref, name):
    rep = WORK / f"{name}.out"
    rep.unlink(missing_ok=True)
    cmd = [NETGEN, "-batch", "lvs", f"{lay} {TOP}", f"{ref} {TOP}", str(NETGEN_SETUP), str(rep)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=WORK)
    (WORK / f"{name}_netgen.log").write_text(p.stdout + p.stderr)
    text = rep.read_text() if rep.exists() else ""
    final = re.findall(r"Final result:\s*(.*)", text)
    devs = re.findall(r"Number of devices:\s*(\d+)\s*\|\s*Number of devices:\s*(\d+)", text)
    nets = re.findall(r"Number of nets:\s*(\d+)\s*\|\s*Number of nets:\s*(\d+)", text)
    prop = "property errors" in text.lower()
    unique = bool(final) and "Circuits match uniquely" in final[-1]
    return dict(final=final[-1] if final else None, unique_match=unique, property_errors=prop, match=unique and not prop,
                devices_layout_reference=[int(x) for x in devs[-1]] if devs else None,
                nets_layout_reference=[int(x) for x in nets[-1]] if nets else None,
                report=str(rep.relative_to(OUT)), reference=str(ref.relative_to(OUT)))


# the negative controls: each changes the reference so that it no longer describes the drawn chip; each must fail
import rev7 as _rev7
rev7_w, rev7_l = _rev7.PLATE_W, _rev7.PLATE_L
CONTROLS = {
    "bw1 and bw2 swapped at the external-bias switches": dict(edits=[("XEXT1 sel1_ladder bw1 ", "XEXT1 sel1_ladder bwX "),
                                                                     ("XEXT2 sel2_ladder bw2 ", "XEXT2 sel2_ladder bw1 "),
                                                                     ("XEXT1 sel1_ladder bwX ", "XEXT1 sel1_ladder bw2 ")]),
    "ext_in back on EXT1's ext pin (bw1 left on the bias block only)": dict(edits=[("XEXT1 sel1_ladder bw1 ", "XEXT1 sel1_ladder ext_in ")]),
    "write strobes we0 and we1 swapped at the resistor row": dict(edits=[("ext_in we0 we1 we2 we3 clampw vdd vss pw4_rblock4", "ext_in we1 we0 we2 we3 clampw vdd vss pw4_rblock4")]),
    # inside the row (drawn by the cells strand, flat in this comparison)
    "inside the row: the two bridges' f ends swapped (bridge 1 from zx to f2x, bridge 2 from zx to f1x)": dict(
        edits=[("XBR1 zx f1x ref dac we2", "XBR1 zx f2x ref dac we2"), ("XBR2 zx f2x ref dac we3", "XBR2 zx f1x ref dac we3")]),
    "inside the row: a strobe on the wrong word (shunt of edge 1 written by we2, bridge of edge 1 by we0)": dict(
        edits=[("XSH1 m1x ref ref dac we0", "XSH1 m1x ref ref dac we2"), ("XBR1 zx f1x ref dac we2", "XBR1 zx f1x ref dac we0")]),
    "inside the row: a stored gate's capacitor on the wrong bus (bridge 1: from its gate to f2x instead of f1x)": dict(item_edits=[("XRB/XBR1/XCB", 1, "f2x")]),
    # a size: must come out as a property error (the layout has two fingers of 8 um, netgen adds them to 16)
    "inside the row: the shunts' first chain transistor 12 um wide instead of 16": dict(expect="property error",
        edits=[("XPA a gn mid mid sky130_fd_pr__pfet_01v8_lvt L=2 W=16", "XPA a gn mid mid sky130_fd_pr__pfet_01v8_lvt L=2 W=12")]),
    # the bias block (drawn by the cells strand, flat in this comparison since 2026-11-15 14:15)
    "the bias block's two enable pins swapped (e1 and e2 at pw4_bias)": dict(
        edits=[("XBW ext_in bw1 bw2 ext_en1 ext_en2 bias_prog", "XBW ext_in bw1 bw2 ext_en2 ext_en1 bias_prog")]),
    "inside the bias block: the two read lines swapped (word 1 on bw2, word 2 on bw1)": dict(
        edits=[("XW1 dac bw1 wb1 bp bp_b", "XW1 dac bw2 wb1 bp bp_b"), ("XW2 dac bw2 wb2 bp bp_b", "XW2 dac bw1 wb2 bp bp_b")]),
    "inside the bias block: a word's write strobe made from the other enable (word 2's gate fed by the inverse of e1)": dict(
        edits=[("XB2 nwrite ne2 bias_prog wb2", "XB2 nwrite ne1 bias_prog wb2")]),
    "inside the bias block: its pull-down of WRITE on BIAS_PROG instead": dict(edits=[("XPD5 write vdd vss pw4_pulldown", "XPD5 bias_prog vdd vss pw4_pulldown")]),
    "inside the bias block: the words' DAC gates driven the wrong way round (on while the word reads)": dict(
        edits=[("XDL dac line bp_b bp vdd vss pw4_tg", "XDL dac line bp bp_b vdd vss pw4_tg")]),
    # sizes: each must come out as a property error
    "inside the bias block: one mirror unit 2 um long instead of 1 um (XMN0)": dict(expect="property error",
        edits=[("XMN0 pref nref vss vss sky130_fd_pr__nfet_01v8 L=1 W=2", "XMN0 pref nref vss vss sky130_fd_pr__nfet_01v8 L=2 W=2")]),
    "inside the bias block: the followers 30 um wide instead of 40 (the layout's four fingers of 10 um are added up)": dict(expect="property error",
        edits=[("XF drn sg line line sky130_fd_pr__pfet_01v8_lvt L=1 W=40", "XF drn sg line line sky130_fd_pr__pfet_01v8_lvt L=1 W=30")]),
    # the decoder's two pull-downs (the cells strand's pw4_pulldown inside the drawn decoder)
    "the decoder's pull-down of RES_SEL on WRITE instead": dict(edits=[("XPD6 res_sel vdd vss pw4_pulldown", "XPD6 write vdd vss pw4_pulldown")]),
    "the decoder's pull-down of WEIGHT_PROG missing": dict(edits=[("XPD7 weight_prog vdd vss pw4_pulldown\n", "")]),
    "write strobes we2 and we3 swapped at the decoder": dict(edits=[("we0 we1 we2 we3 iso clampw vdd vss pw4_decoder", "we0 we1 we3 we2 iso clampw vdd vss pw4_decoder")]),
    "H1's helper beside R4 moved to H2's wire (its switch XSW4 on f2)": dict(item_edits=[("XNH1/XSW4", 0, "f2")]),
    "the DAC edge's gate on the wrong side (nd and the DAC line swapped at pw4_dacgate)": dict(edits=[("XDG nd ext_in ref iso vdd vss pw4_dacgate", "XDG ext_in nd ref iso vdd vss pw4_dacgate")]),
    "the midpoints' switches crossed (m1 to the bus of m2 and back)": dict(edits=[("XMID m1 m2 m1x m2x iso vss pw4_mid", "XMID m1 m2 m2x m1x iso vss pw4_mid")]),
    # a size, not a wire: must come out as a property error (a hidden neuron's east cell: first unit 120 kohm, legs 10.4 um)
    "one unit of the hidden neurons' east cells 120 kohm instead of 133 kohm": dict(expect="property error", edits=[
        ("XU3 n3 b vss pdk_rbias2 RVALUE=133333\nXU4 dn dc", "XU3 n3 b vss pdk_rbias2 RVALUE=120000\nXU4 dn dc")]),
    # the damping network on f1 and f2 (revision 7)
    "H1's damping switch on its bus instead of its wire (XSWD on f1x)": dict(item_edits=[("XNH1/XSWD", 0, "f1x")]),
    # (crossing the two networks, H1's switch onto H2's strip and back, is NOT an error: the two are alike and the result
    # is the same circuit; netgen says so, tried on 2026-11-15)
    "H1's east cell fed the wrong way round (the helper's three units on the damping switch, the damping strip on the helper's switch)": dict(edits=[
        ("XUE1 qs1 ref dn1 vss pw4_units3d", "XUE1 dn1 ref qs1 vss pw4_units3d")]),
    "the damping capacitors' lower plates on ground instead of REF": dict(edits=[("XCD dc b sky130_fd_pr__cap_mim_m3_1", "XCD dc vss sky130_fd_pr__cap_mim_m3_1")]),
    "the damping capacitors 1 um shorter": dict(expect="property error", edits=[(f"W={rev7_w:g} L={rev7_l:g} MF=1 m=1\n.ends", f"W={rev7_w:g} L={rev7_l - 1:g} MF=1 m=1\n.ends")]),
}


def main():
    lay, warn = extract()
    ref, notes = reference()
    res = netgen(lay, ref, "lvs")
    res.update(layout=str(lay.relative_to(OUT)), method="Magic flat extraction of the whole top cell (no cell kept apart), netgen 1.5.325, PDK sky130A_setup.tcl",
               reference_notes=notes, v4_netlist_from=(NETLIST_FROM or [None])[0], magic_messages=warn[:10])
    if MODE == "r6":
        res["references_of_the_cells_strand"] = {c: strand_reference(c) for c in ("pw4_rblock4", "pw4_bias")}
        text = lay.read_text()
        res["extracted_devices_before_netgen_joins_them"] = len(re.findall(r"(?m)^X", text))
    if MODE == "control":
        (OUT_RESULTS / "acc_lvs_flat.json").write_text(json.dumps(res, indent=1) + "\n")
        print(json.dumps(res, indent=1))
        return
    (OUT_RESULTS / "r6_lvs.json").write_text(json.dumps(res, indent=1) + "\n")
    print("r6:", res["final"], "| property errors", res["property_errors"], "| devices", res["devices_layout_reference"], "| nets", res["nets_layout_reference"], flush=True)
    neg = {}
    for k, (what, spec) in enumerate(CONTROLS.items()):
        r, _ = reference(f"neg{k}", spec.get("edits", ()), spec.get("item_edits", ()))
        n = netgen(lay, r, f"neg{k}")
        # a wrong size must show as a property error on an otherwise matching netlist; anything else as no match
        n["expected"] = spec.get("expect", "no match")
        n["detected"] = (n["unique_match"] and n["property_errors"]) if n["expected"] == "property error" else not n["match"]
        neg[what] = n
        print(f"  control {k}: {what}: {'detected' if n['detected'] else 'NOT DETECTED'} ({n['final']}, property errors {n['property_errors']})", flush=True)
    out = dict(all_detected=all(v["detected"] for v in neg.values()), number=len(neg), controls=neg)
    (OUT_RESULTS / "r6_lvs_negative_controls.json").write_text(json.dumps(out, indent=1) + "\n")
    if not res["match"] or not out["all_detected"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
