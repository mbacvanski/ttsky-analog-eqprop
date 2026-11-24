"""Layout against circuit for the whole chip by the earlier chip's own method, with planted faults (project Python).

  PY -I lvs_check.py GDS NETLIST ROOT TAG        -> results/lvs_TAG.json, build/TAG/lvs_check/ (references, netgen reports)

The method of programmable_weights_v4_20261114/floorplan/scripts/chip_lvs.py:
  layout     Magic's flat extraction of the whole top cell (`extract all`, `ext2spice lvs`), here from the GDS
             (magic_flows.py lvs; the same command sequence as chip_lvs.extract with `gds read` in place of the .mag);
  reference  NETLIST walked from ROOT by the accepted flow's walker (feasibility_20261107/floorplan/chip2x2/scripts/make_ref.py
             and the 3x2 module it loads, imported, nothing written there): ROOT's pins under Tiny Tapeout pin names (the
             accepted map plus the four pins of v4: bias_prog, write, res_sel, weight_prog), amplifier instances as the
             verified amplifier cells, standard cells kept, every other device flattened with its parameters EVALUATED;
             global parameters from the accepted deck (as chip_lvs.reference);
  dummies    the grounded dummy strips the layout adds: the accepted chip's list (make_ref CHIP_DUMMIES), the drawn v4
             cells' end strips per placed copy (chip_lvs.CELL_DUMMIES), and for every other cell the strips the layout
             itself holds with all three terminals on ground beyond those two lists (counted from the extraction and named
             in the result: these the comparison cannot catch missing or extra);
  netgen     1.5.325 with the PDK's sky130A_setup.tcl; a match must be unique with no property errors.
Netlist version 5 (takeover/bias/layout/rzero/make_variant_v5.py, 24 Nov: XBUF3's RZERO 1k -> 1225, its zero resistor
0.54 -> 0.70 um long): the walker takes every amplifier cell's devices from the amp generator's reference files (amp_defs
reads AMP_REF/<cell>_ref.spice), not from the netlist, so XBUF3 would still be expected at L 0.54. For version 5, known by
its sha256, the reference reads a copy of that folder (build/TAG/lvs_check/amp_ref/) in which az_ref4_ref.spice (sha256
checked) has its one zero-resistor line at the length version 5 gives, by the PDK's fixed-resistor formula on XBUF3's
RZERO (0.7). Every other file is copied unchanged. This is the patch the bias layout's check_die_v4.py makes; it is
derived here independently, and the copy's sha256 must equal that one's. Any other netlist reads the generator's folder.
Planted faults: each changes the reference so that it no longer describes the drawn chip, and must be detected (a wrong
size as a property error on an otherwise unique match, anything else as no match). The earlier chip's 25 are carried
over wherever the netlist has their lines (each edit must occur exactly once, else that fault is reported as not
applicable); the six-weight chip adds its own.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OUT = HERE.parent
X = OUT.parents[2]
ACC = X / "feasibility_20261107/floorplan/chip2x2/scripts"
sys.path.insert(0, str(ACC))
import make_ref as MR  # noqa: E402   the accepted 2x2 module (imports chip2x2's magic_util and chip: no writes on import)
import chip  # noqa: E402

M = MR.m
TOP = "tt_um_mbacvanski_analog_eqprop"
NETGEN = os.environ.get("NETGEN", str(Path.home() / ".local/bin/netgen-1.5.325"))
SETUP = Path(os.environ.get("PDK_ROOT", Path.home() / ".ciel")) / "sky130A/libs.tech/netgen/sky130A_setup.tcl"
V4_PINS = {"bias_prog": "uio_in[4]", "write": "uio_in[5]", "res_sel": "uio_in[6]", "weight_prog": "uio_in[7]"}
RX = "sky130_fd_pr__res_xhigh_po_0p35"
L_LEG, L_LEG_DAC = 11.56, 10.60                     # programmable_weights_v4_20261114/floorplan/cellwork/scripts/devices.py
CELL_DUMMIES = {"pw4_units3d": [L_LEG, L_LEG], "pw4_nrn_h": [L_LEG, L_LEG], "pw4_nrn_z": [L_LEG, L_LEG], "pw4_units5": [L_LEG_DAC, L_LEG]}

V5_SHA = "399eac539f89319920f6f0921f33a6454fbd4b10d10704f1164dfca0bb13a8c6"          # netlist version 5
AZ_REF4_SHA = "1f32e799b4d9c23236db08aa562bb1ca71a0bf2519bc2b78dc4944748d1aae94"     # the generator's az_ref4_ref.spice
AZ_REF4_V5_SHA = "95948d35e7601c326868ea9c4b5e8a09971d29c12c235bc7ba34b5d72f1f393d"  # its version-5 copy (check_die_v4.py's)
RZ_LINE = "XAMP_XRZERO_XDEVICE_XR0 XAMP_comp XAMP_gain1 vss sky130_fd_pr__res_xhigh_po_1p41 L=0.54"


def amp_reference(raw, d):
    """The amplifier reference folder this netlist needs, and a record: the generator's own, or for version 5 a copy
    with az_ref4's zero resistor at version 5's length."""
    src = Path(M.AMP_REF)
    if hashlib.sha256(raw).hexdigest() != V5_SHA:
        return src, dict(folder=str(src), patched=None)
    rz = re.findall(r"(?m)^XBUF3 .* cd_ref_az .*\bRZERO=([0-9.]+)\s", raw.decode())
    assert len(rz) == 1, rz
    # the PDK's res_xhigh_po_1p41 for a fixed value: L = (R - 232.396 ohm of the heads) x W / 2000 ohm per square, on 0.01 um
    length = round(0.01 * math.floor(((float(rz[0]) - 232.3959788743) * 1.41 / 2000) / 0.01 + 0.5), 2)
    assert length == 0.7, length
    raw4 = (src / "az_ref4_ref.spice").read_bytes()
    assert hashlib.sha256(raw4).hexdigest() == AZ_REF4_SHA, "az_ref4_ref.spice is not the one checked"
    lines = raw4.decode().split("\n")
    hit = [i for i, l in enumerate(lines) if l == RZ_LINE]
    assert len(hit) == 1, hit
    lines[hit[0]] = RZ_LINE.replace("L=0.54", f"L={length:g}")
    cp = d / "amp_ref"
    if cp.exists():
        shutil.rmtree(cp)
    cp.mkdir(parents=True)
    for f in sorted(src.iterdir()):
        if f.is_file():
            (cp / f.name).write_bytes(f.read_bytes())
    (cp / "az_ref4_ref.spice").write_bytes("\n".join(lines).encode())
    after = hashlib.sha256((cp / "az_ref4_ref.spice").read_bytes()).hexdigest()
    assert after == AZ_REF4_V5_SHA, f"the version-5 copy of az_ref4_ref.spice is {after[:16]}, not check_die_v4.py's"
    return cp, dict(folder=str(cp.relative_to(OUT)), patched=dict(file="az_ref4_ref.spice", line=hit[0] + 1, old=RZ_LINE, new=lines[hit[0]],
                                                                  xbuf3_rzero=rz[0], length_um=length, sha256_before=AZ_REF4_SHA, sha256_after=after))


def read(p):
    p = Path(p)
    return (gzip.open(p, "rt") if p.suffix == ".gz" else open(p)).read()


def layout(gds, tag):
    flat = OUT / "build" / tag / "lvs" / "flat_lvs.spice"
    if not flat.exists():
        subprocess.run([sys.executable, "-I", str(HERE / "magic_flows.py"), "lvs", str(gds), str(OUT / "build" / tag)], check=True)
    text = re.sub(r"\n\+\s*", " ", flat.read_text())
    text = re.sub(r"(?m)^\.subckt flat_lvs ", f".subckt {TOP} ", text)
    text = re.sub(r"(?m)^\.ends flat_lvs", f".ends {TOP}", text)
    d = OUT / "build" / tag / "lvs_check"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{TOP}_layout.spice"
    out.write_text(text)
    return out, text


def layout_dummies(text):
    """resistors of the layout with all three terminals on the ground port: Counter of (model, L um)"""
    gnd = [p for p in re.search(rf"(?m)^\.subckt {TOP} (.*)$", text)[1].split() if p.upper() == "VGND"][0]
    c = collections.Counter()
    for l in text.splitlines():
        if l.startswith("X") and "res_" in l:
            t = [x for x in l.split() if "=" not in x]
            if t[1] == t[2] == t[3] == gnd:
                lv = float(re.search(r"\bl=(\S+)", l, re.I)[1])
                c[(t[-1], round(lv, 2))] += 1
    return c


def internal_dummies(netlist_text, root):
    """grounded resistor strips the walked reference already holds inside its amplifier cells (the verified amplifier
    references carry their own dummies): Counter of (model, L um), found by walking the reference with those cells
    expanded from their definitions."""
    subs = M.subckts(netlist_text)
    genv = M.deck_params(chip.DECK.read_text())
    tt = dict(M.TT_MAP, **V4_PINS)
    items = []
    M.walk(subs, root, [tt[p] for p in subs[root][0]], {}, "", items, genv)
    written: set = set()
    defs = "\n".join(M.amp_defs(sorted({it[2] for it in items if it[0] == "cell"}), written))
    cells = {n: (p.split(), [l for l in b.splitlines() if l.strip() and not l.startswith("*")])
             for n, p, b in re.findall(r"(?ms)^\.subckt (\S+) ([^\n]*)\n(.*?)^\.ends", re.sub(r"\n\+\s*", " ", defs))}
    c = collections.Counter()

    def visit(cell, conns):
        ports, body = cells[cell]
        local = dict(zip(ports, conns))
        for l in body:
            t = [x for x in l.split() if "=" not in x]
            model = t[-1]
            nodes = [local.get(n, "__int__" + n) for n in t[1:-1]]
            if model.startswith("sky130_fd_pr__res") and all(n == "VGND" for n in nodes):
                lv = re.search(r"\bl=(\S+)", l, re.I)
                c[(model, round(float(M.ev(lv[1], {})), 2))] += 1
            elif model in cells:
                visit(model, nodes)
    for it in items:
        if it[0] == "cell":
            visit(it[2], list(it[3]))
    return c


def placed_counts(gds):
    code = ("import sys, json, collections, klayout.db as db\nly = db.Layout(); ly.read(sys.argv[1])\n"
            "print(json.dumps(collections.Counter(i.cell.name for i in ly.top_cell().each_inst())))")
    kpy = os.environ.get("KLAYOUT_PY", str(Path.home() / ".local/opt/klayout-py/bin/python"))
    p = subprocess.run([kpy, "-c", code, str(gds)], capture_output=True, text=True, check=True)
    return json.loads(p.stdout.strip().splitlines()[-1])


def reference(netlist_text, root, name, d, extra_dummies, placed, edits=(), item_edits=()):
    text = netlist_text
    m = re.search(rf"(?ms)^\.subckt {re.escape(root)} .*?^\.ends", text)
    for old, new in edits:
        if text.count(old) == 1:
            text = text.replace(old, new)
        elif m and m[0].count(old) == 1:              # a top-level line that the file also holds in another top cell
            body = m[0].replace(old, new)
            text = text[:m.start()] + body + text[m.end():]
            m = re.search(rf"(?ms)^\.subckt {re.escape(root)} .*?^\.ends", text)
        else:
            raise LookupError(f"{old!r} occurs {text.count(old)} times in the file, {m[0].count(old) if m else 0} in {root}")
    subs = M.subckts(text)
    genv = M.deck_params(chip.DECK.read_text())
    tt = dict(M.TT_MAP, **V4_PINS)
    pins = subs[root][0]
    missing = [p for p in pins if p not in tt]
    assert not missing, f"no Tiny Tapeout pin for {missing}"
    items = []
    M.walk(subs, root, [tt[p] for p in pins], {}, "", items, genv)
    for path, k, net in item_edits:
        hit = [i for i, it in enumerate(items) if it[1] == path]
        if len(hit) != 1:
            raise LookupError(f"device {path}: {len(hit)} found")
        kind, p, model, conns, vals = items[hit[0]]
        conns = list(conns)
        conns[k] = net
        items[hit[0]] = (kind, p, model, conns, vals)
    dummies = [(m.split()[0], m.split()[1], n, w) for m, n, w in M.CHIP_DUMMIES]
    per = collections.Counter()
    for cell, ls in CELL_DUMMIES.items():
        for l in ls:
            per[(cell, l)] += placed.get(cell, 0)
    dummies += [(RX, f"L={l:g}", n, f"{c} (end strips of its arrays), {placed.get(c, 0)} placed") for (c, l), n in per.items() if n]
    dummies += [(m, f"L={l:g}", n, "counted in the layout beyond the two lists (other cells' grounded strips)") for (m, l), n in extra_dummies.items() if n]
    lines = [f"* LVS reference for {TOP} ({name}), takeover/layout/scripts/lvs_check.py: {root} walked by the accepted flow's make_ref",
             "* under Tiny Tapeout pin names. Layout additions, all three terminals on VGND:", *[f"*   {n} x {m} {l} ({w})" for m, l, n, w in dummies]]
    lines += [f"* PLANTED FAULT edit: {o!r} -> {n!r}" for o, n in edits] + [f"* PLANTED FAULT device {p} terminal {k} -> {n}" for p, k, n in item_edits]
    written: set = set()
    lines += M.std_defs({it[2] for it in items if it[0] == "std"}, written)
    lines += M.amp_defs(sorted({it[2] for it in items if it[0] == "cell"}), written)
    lines.append(f".subckt {TOP} " + " ".join(M.TT_PORTS))
    lines += [M.fmt(*it) for it in items]
    k = 0
    for model, lp, n, _ in dummies:
        for _ in range(n):
            lines.append(f"XDUMMY{k} VGND VGND VGND {model} {lp}")
            k += 1
    lines.append(f".ends {TOP}")
    path = d / f"{TOP}_{name}.spice"
    path.write_text("\n".join(lines) + "\n")
    return path, dummies, items


def netgen(lay, ref, name, d):
    rep = d / f"{name}.out"
    rep.unlink(missing_ok=True)
    p = subprocess.run([NETGEN, "-batch", "lvs", f"{lay} {TOP}", f"{ref} {TOP}", str(SETUP), str(rep)], capture_output=True, text=True, timeout=3600, cwd=d)
    (d / f"{name}_netgen.log").write_text(p.stdout + p.stderr)
    text = rep.read_text() if rep.exists() else ""
    final = re.findall(r"Final result:\s*(.*)", text)
    devs = re.findall(r"Number of devices:\s*(\d+)\s*\|\s*Number of devices:\s*(\d+)", text)
    nets = re.findall(r"Number of nets:\s*(\d+)\s*\|\s*Number of nets:\s*(\d+)", text)
    prop = "property errors" in text.lower()
    unique = bool(final) and "Circuits match uniquely" in final[-1]
    return dict(final=final[-1] if final else None, unique_match=unique, property_errors=prop, match=unique and not prop,
                devices_layout_reference=[int(x) for x in devs[-1]] if devs else None, nets_layout_reference=[int(x) for x in nets[-1]] if nets else None,
                report=str(rep.relative_to(OUT)))


# planted faults: (what, edits, item_edits, expect)
V4 = [  # the earlier chip's 25 (chip_lvs.CONTROLS), in their own words; the edits where its netlist lines differ in form are adapted
    ("bw1 and bw2 swapped at the external-bias switches", [("XEXT1 sel1_ladder bw1 ", "XEXT1 sel1_ladder bwX "), ("XEXT2 sel2_ladder bw2 ", "XEXT2 sel2_ladder bw1 "), ("XEXT1 sel1_ladder bwX ", "XEXT1 sel1_ladder bw2 ")], [], "no match"),
    ("ext_in back on EXT1's ext pin", [("XEXT1 sel1_ladder bw1 ", "XEXT1 sel1_ladder ext_in ")], [], "no match"),
    ("write strobes swapped at the Z row (the earlier chip's row; z0, z1 here, we0, we1 there)", [("ext_in z0 z1 z2 z3 clampw vdd vss pw4_rblock4", "ext_in z1 z0 z2 z3 clampw vdd vss pw4_rblock4")], [], "no match"),
    ("inside the row: the two bridges' f ends swapped", [("XBR1 zx f1x ref dac we2", "XBR1 zx f2x ref dac we2"), ("XBR2 zx f2x ref dac we3", "XBR2 zx f1x ref dac we3")], [], "no match"),
    ("inside the row: a strobe on the wrong word", [("XSH1 m1x ref ref dac we0", "XSH1 m1x ref ref dac we2"), ("XBR1 zx f1x ref dac we2", "XBR1 zx f1x ref dac we0")], [], "no match"),
    ("inside the Z row: a stored gate's capacitor on the wrong bus", [], [("XRB/XBR1/XCB", 1, "f2x")], "no match"),
    ("inside the row: the shunts' first chain transistor 12 um wide instead of 16 (written here as fingers: 2 x 6 instead of 2 x 8)", [("XPA a gn mid mid sky130_fd_pr__pfet_01v8_lvt L=2 W=8", "XPA a gn mid mid sky130_fd_pr__pfet_01v8_lvt L=2 W=6")], [], "property error"),
    ("the bias block's two enable pins swapped", [("XBW ext_in bw1 bw2 ext_en1 ext_en2 bias_prog", "XBW ext_in bw1 bw2 ext_en2 ext_en1 bias_prog")], [], "no match"),
    ("inside the bias block: the two read lines swapped", [("XW1 dac bw1 wb1 bp bp_b", "XW1 dac bw2 wb1 bp bp_b"), ("XW2 dac bw2 wb2 bp bp_b", "XW2 dac bw1 wb2 bp bp_b")], [], "no match"),
    ("inside the bias block: word 2's strobe made from the other enable", [("XB2 nwrite ne2 bias_prog wb2", "XB2 nwrite ne1 bias_prog wb2")], [], "no match"),
    ("inside the bias block: its pull-down of WRITE on BIAS_PROG", [("XPD5 write vdd vss pw4_pulldown", "XPD5 bias_prog vdd vss pw4_pulldown")], [], "no match"),
    ("inside the bias block: the DAC gates driven the wrong way round", [("XDL dac line bp_b bp vdd vss pw4_tg", "XDL dac line bp bp_b vdd vss pw4_tg")], [], "no match"),
    ("inside the bias block: one mirror unit 2 um long instead of 1 um", [("XMN0 pref nref vss vss sky130_fd_pr__nfet_01v8 L=1 W=2", "XMN0 pref nref vss vss sky130_fd_pr__nfet_01v8 L=2 W=2")], [], "property error"),
    ("inside the bias block: the followers 30 um wide instead of 40 (written here as fingers: 4 x 7.5 instead of 4 x 10)", [("XF drn sg line line sky130_fd_pr__pfet_01v8_lvt L=1 W=10", "XF drn sg line line sky130_fd_pr__pfet_01v8_lvt L=1 W=7.5")], [], "property error"),
    ("the decoder's pull-down of RES_SEL on WRITE", [("XPD6 res_sel vdd vss pw4_pulldown", "XPD6 write vdd vss pw4_pulldown")], [], "no match"),
    ("the decoder's pull-down of WEIGHT_PROG missing", [("XPD7 weight_prog vdd vss pw4_pulldown\n", "")], [], "no match"),
    ("write strobes we2 and we3 swapped at the decoder", [("we0 we1 we2 we3 iso clampw vdd vss pw4_decoder", "we0 we1 we3 we2 iso clampw vdd vss pw4_decoder")], [], "no match"),
    ("H1's helper beside R4 moved to H2's wire (XSW4 on f2)", [], [("XNH1/XSW4", 0, "f2")], "no match"),
    ("the DAC edge's gate on the wrong side", [("XDG nd ext_in ref iso vdd vss pw4_dacgate", "XDG ext_in nd ref iso vdd vss pw4_dacgate")], [], "no match"),
    ("the midpoints' switches crossed", [("XMID m1 m2 m1x m2x iso vss pw4_mid", "XMID m1 m2 m2x m1x iso vss pw4_mid")], [], "no match"),
    ("one unit of the hidden neurons' east cells 120 kohm instead of 133 kohm", [("XU3 n3 b vss pdk_rbias2 RVALUE=133333\nXU4 dn dc", "XU3 n3 b vss pdk_rbias2 RVALUE=120000\nXU4 dn dc")], [], "property error"),
    ("H1's damping switch on its bus instead of its wire", [], [("XNH1/XSWD", 0, "f1x")], "no match"),
    ("H1's east cell fed the wrong way round", [("XUE1 qs1 ref dn1 vss pw4_units3d", "XUE1 dn1 ref qs1 vss pw4_units3d")], [], "no match"),
    ("the damping capacitors' lower plates on ground instead of REF", [("XCD dc b sky130_fd_pr__cap_mim_m3_1", "XCD dc vss sky130_fd_pr__cap_mim_m3_1")], [], "no match"),
    ("the damping capacitors 1 um shorter", "DAMP_L", [], "property error"),
]
SIX = [
    ("the A and B rows' write strobes exchanged", [("XROW_A bias1 ax f1 f2 ref ext_in a0 a1 a2 a3", "XROW_A bias1 ax f1 f2 ref ext_in b0 b1 b2 b3"), ("XROW_B bias2 bx f1 f2 ref ext_in b0 b1 b2 b3", "XROW_B bias2 bx f1 f2 ref ext_in a0 a1 a2 a3")], [], "no match"),
    ("the A row fed from B's raw input", [("XROW_A bias1 ax ", "XROW_A bias2 ax ")], [], "no match"),
    ("the A row's two hidden ends crossed (f1 and f2)", [("XROW_A bias1 ax f1 f2 ", "XROW_A bias1 ax f2 f1 ")], [], "no match"),
    ("the B row's strobe of word 3 on word 2", [("XROW_B bias2 bx f1 f2 ref ext_in b0 b1 b2 b3", "XROW_B bias2 bx f1 f2 ref ext_in b0 b1 b3 b2")], [], "no match"),
    ("the fixed offsets of H1 and H2 exchanged", [("XSTATIC ref fixed1 fixed2 p1 p2 six vss", "XSTATIC ref fixed1 fixed2 p2 p1 six vss")], [], "no match"),
    ("one raw selector arm on SIX instead of PARK", [("XSEL_RAW1 bias1 bias2 h1bias h2bias park vss", "XSEL_RAW1 bias1 bias2 h1bias h2bias six vss")], [], "no match"),
    ("H2's added feedback on f1", [("XH2FEEDBACK f2 p2 q2 ", "XH2FEEDBACK f1 p2 q2 ")], [], "no match"),
    ("the clamp bus switch crossed (ax, bx)", [("XCLAMP_BUS bias1 bias2 ax bx ", "XCLAMP_BUS bias1 bias2 bx ax ")], [], "no match"),
    ("the RES_SEL filter's resistor 8.0 um instead of 6.9 um", [("XRCIN_R res_sel res_filtered vss sky130_fd_pr__res_xhigh_po_0p35 L=6.90", "XRCIN_R res_sel res_filtered vss sky130_fd_pr__res_xhigh_po_0p35 L=8.00")], [], "property error"),
    ("the gate-load capacitor on weak instead of weak_b", [("XGATELOAD weak_b vss ", "XGATELOAD weak vss ")], [], "no match"),
    ("one REF reservoir capacitor turned round (plates exchanged)", [("XRESERVOIR1 ref vss ", "XRESERVOIR1 vss ref ")], [], "no match"),
    ("the hold logic's NAND fed from RES_SEL before its filter", [("XHOLD_AND_B res_filtered six ", "XHOLD_AND_B res_sel six ")], [], "no match"),
    ("the bank enable's Z row strobe 0 on the A row's", [("XENABLE bit_a bit_b we0 we1 we2 we3 z0 z1 z2 z3 a0 a1 a2 a3", "XENABLE bit_a bit_b we0 we1 we2 we3 a0 z1 z2 z3 z0 a1 a2 a3")], [], "no match"),
    # the programmable-offset variant (takeover/bias/circuit/variant_reference.spice): not applicable to the selected netlist
    ("variant: the two offset words' gates exchanged at the programmable transistors", [("XOPROG ret1 ret2 bg1 bg2 vss", "XOPROG ret1 ret2 bg2 bg1 vss")], [], "no match"),
    ("variant: H1's offset word written by H2's strobe", [("XOWORD1 bg1 ext_in bstb1 ", "XOWORD1 bg1 ext_in bstb2 ")], [], "no match"),
    ("variant: the offset strobes' word lines exchanged (we0, we1)", [("XOSTROBE bit_a bit_b we0 we1 ", "XOSTROBE bit_a bit_b we1 we0 ")], [], "no match"),
    ("variant: XPROG1 2 um long instead of 4", [("XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=4 W=0.42", "XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=2 W=0.42")], [], "property error"),
    ("variant: H2's mode switch source back on ground (XPROG2 bypassed)", [("XRETURN end1 end2 ret1 ret2 six vss", "XRETURN end1 end2 ret1 vss six vss")], [], "no match"),
    ("variant: an offset word's storage capacitor on REF instead of ground", [("XC bg vss sky130_fd_pr__cap_mim_m3_1 W=8.97", "XC bg ref sky130_fd_pr__cap_mim_m3_1 W=8.97")], [], "no match"),
    ("variant: the offset strobe's NAND from bit_a twice", [("XSAB bit_a bit_b vss vss vdd vdd nab", "XSAB bit_a bit_a vss vss vdd vdd nab")], [], "no match"),
    # the delivered variant (version 3, XPROG1 L 3.2, XPROG2 L 3.5): fault 41 at the final lengths
    ("variant v3: XPROG1 1.6 um long instead of 3.2", [("XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=3.2 W=0.42", "XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=1.6 W=0.42")], [], "property error"),
    ("variant v3: XPROG2 0.5 um wide instead of 1", [("XPROG2 ret2 bg2 vss vss sky130_fd_pr__nfet_01v8 L=3.5 W=1 ", "XPROG2 ret2 bg2 vss vss sky130_fd_pr__nfet_01v8 L=3.5 W=0.5 ")], [], "property error"),
    # netlist version 4 (takeover/bias/circuit/variant_reference_v4.spice: H1's bias network made H2's; 23 Nov): the three
    # parts the v4 stage changed, each at its version-3 value or half its length; not applicable to version 3
    ("variant v4: H1's trim at its version-3 value (18.18 kohm instead of 48.28)", [("XR1 ref bias1 vss pdk_rbias2 RVALUE=48275.86207", "XR1 ref bias1 vss pdk_rbias2 RVALUE=18181.81818")], [], "property error"),
    ("variant v4: one strip of H1's chain at 300 kohm (version 3) instead of 257 kohm", [("XG12 a1 a2 vss pdk_rbias2 RVALUE=257142.85714", "XG12 a1 a2 vss pdk_rbias2 RVALUE=300k")], [], "property error"),
    ("variant v4: XPROG1 1.75 um long instead of 3.5", [("XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=3.5 W=1 ", "XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=1.75 W=1 ")], [], "property error"),
    # netlist version 5: the amplifier reference as it was (XBUF3's zero resistor 0.54 um long); not applicable to others
    ("v5: XBUF3's zero resistor expected at its version-4 length, 0.54 um (the amp reference unpatched)", "AMP_UNPATCHED", [], "property error"),
]


def main(gds, netlist, root, tag):
    gds = Path(gds).resolve()
    d = OUT / "build" / tag / "lvs_check"
    d.mkdir(parents=True, exist_ok=True)
    lay, ltext = layout(gds, tag)
    ntext = read(netlist)
    raw = Path(netlist).read_bytes()
    amp_src = Path(M.AMP_REF)
    amp_dir, amp_rec = amp_reference(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw, d)
    M.AMP_REF = amp_dir
    placed = placed_counts(gds)
    design = collections.Counter()
    for m, n, w in M.CHIP_DUMMIES:
        mod, lp = m.split()
        design[(mod, round(float(lp.split("=")[1]), 2))] += n
    for cell, ls in CELL_DUMMIES.items():
        for l in ls:
            design[(RX, round(l, 2))] += placed.get(cell, 0)
    have = layout_dummies(ltext)
    inside = internal_dummies(ntext, root)
    for k, v in inside.items():
        design[k] += v
    extra = collections.Counter({k: have[k] - design.get(k, 0) for k in have if have[k] > design.get(k, 0)})
    short = {f"{k[0]} L={k[1]}": design[k] - have.get(k, 0) for k in design if design[k] > have.get(k, 0)}
    ref, dummies, items = reference(ntext, root, "ref", d, extra, placed)
    res = dict(method=__doc__.strip(), gds=str(gds), netlist=str(netlist), root=root, layout=str(lay.relative_to(OUT)), reference=str(ref.relative_to(OUT)),
               reference_devices_walked=len(items), dummies_by_design=sum(design.values()), dummies_in_the_layout=sum(have.values()),
               dummies_inside_the_verified_amplifier_cells={f"{k[0]} L={k[1]}": v for k, v in inside.items()},
               dummies_added_from_the_layout={f"{k[0]} L={k[1]}": v for k, v in extra.items()}, design_dummies_missing_in_the_layout=short,
               amplifier_reference=amp_rec)
    res["lvs"] = netgen(lay, ref, "lvs", d)
    print("LVS:", res["lvs"]["final"], "| property errors", res["lvs"]["property_errors"], "| devices", res["lvs"]["devices_layout_reference"], "| nets", res["lvs"]["nets_layout_reference"], flush=True)
    ctl = {}
    for k, (what, edits, item_edits, expect) in enumerate(V4 + SIX):
        origin = "earlier chip" if k < len(V4) else "six-weight"
        try:
            if edits == "DAMP_L":
                m = re.search(r"(XCD dc b sky130_fd_pr__cap_mim_m3_1 W=(\S+) L=)(\S+)( MF=1 m=1)", ntext)
                if not m:
                    raise LookupError("no damping capacitor line")
                edits = [(m[0], f"{m[1]}{float(m[3]) - 1:g}{m[4]}")]
            if edits == "AMP_UNPATCHED":
                if amp_rec["patched"] is None:
                    raise LookupError("not netlist version 5: the amp reference is the generator's own")
                M.AMP_REF = amp_src
                try:
                    r, _, _ = reference(ntext, root, f"fault{k}", d, extra, placed)
                finally:
                    M.AMP_REF = amp_dir
            else:
                r, _, _ = reference(ntext, root, f"fault{k}", d, extra, placed, edits, item_edits)
        except LookupError as e:
            ctl[what] = dict(origin=origin, applicable=False, why=str(e)[:200])
            print(f"  fault {k} ({origin}): {what}: not applicable ({e})", flush=True)
            continue
        n = netgen(lay, r, f"fault{k}", d)
        n.update(origin=origin, applicable=True, expected=expect,
                 detected=(n["unique_match"] and n["property_errors"]) if expect == "property error" else not n["match"])
        ctl[what] = n
        print(f"  fault {k} ({origin}): {what}: {'detected' if n['detected'] else 'NOT DETECTED'} ({n['final']}, property errors {n['property_errors']})", flush=True)
    app = [v for v in ctl.values() if v["applicable"]]
    res["planted_faults"] = dict(total=len(ctl), applicable=len(app), detected=sum(v["detected"] for v in app),
                                 earlier_chip_applicable=sum(1 for v in app if v["origin"] == "earlier chip"), controls=ctl)
    res["ok"] = bool(res["lvs"]["match"] and all(v["detected"] for v in app))
    (OUT / "results" / f"lvs_{tag}.json").write_text(json.dumps(res, indent=1) + "\n")
    print(f"planted faults: {res['planted_faults']['detected']} of {len(app)} applicable detected ({res['planted_faults']['earlier_chip_applicable']} of the earlier chip's 25 apply)")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
