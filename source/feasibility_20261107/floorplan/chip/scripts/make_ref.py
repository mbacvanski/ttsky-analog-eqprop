"""LVS references for the chip's blocks, written from variant AI's netlist.

Source: ref/ai_native.spice, Mesa's native Xschem netlist of
variants/test_features/xor_staged_tb.sch (AI = AH + the three approved test features). Its
subcircuits are identical to the deck of AI's archived runs (checked when it was fetched).

Every reference is built the same way as amp_layout/scripts/make_ref.py builds the
activation blocks: amplifier instances become the verified amplifier cells (matched by
subcircuit and parameters), standard cells stay sky130_fd_sc_hd instances, and every other
device is flattened with its deck parameters. A block is a subset of one subcircuit's
flattened items (selected by instance path); its ports are the nets it shares with the rest
of that subcircuit, named as in the subcircuit. Grounded dummy devices that exist only in
the layout (end strips of resistor arrays) are listed per block as layout additions.

Usage: python make_ref.py [block ...]     (default: every block)
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import sys
from pathlib import Path

from magic_util import FEAS, REF

DECK = REF / "ai_native.spice"
SUFFIX = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9}
STD = Path(os.environ.get("PDK_ROOT", Path.home() / ".ciel")) / "sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
AMP_REF = FEAS / "amp_layout" / "ref"

# (subcircuit, parameters that identify it, verified cell)
AMP_CELLS = [("cd_signal_az", dict(COMP=1e-12, RZERO=5e3, DRIVE=1.0), "az_core"),
             ("cd_ref_az", dict(COMP=1.2e-12, DRIVE=1.0), "az_ref1"),
             ("cd_ref_az", dict(COMP=4e-12, DRIVE=4.0), "az_ref4"),
             ("pdk_amp", dict(COMP=4e-12, DRIVE=4.0), "az_pad"),
             ("cd_act_pos_az", {}, "act_pos"),
             ("xor_activation_negative", {}, "act_neg")]


def num(tok: str) -> float:
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(meg|[fpnumkg])?", tok.lower())
    if not m:
        raise ValueError(tok)
    return float(m[1]) * SUFFIX.get(m[2] or "", 1.0)


def ev(expr, env: dict) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    e = expr.strip()
    if e.startswith("{") and e.endswith("}"):
        e = e[1:-1]
    e = e.replace("^", "**")
    e = re.sub(r"(?<![\w.])((?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(meg|[fpnumkg])\b",
               lambda m: repr(num(m[1] + m[2])), e, flags=re.I)
    return float(eval(e, {"sqrt": math.sqrt, "floor": math.floor, "__builtins__": {}}, dict(env)))


def subckts(text: str) -> dict:
    text = re.sub(r"\n\+\s*", " ", text)
    out = {}
    for m in re.finditer(r"(?ms)^\.subckt (\S+) ([^\n]*)\n(.*?)^\.ends", text):
        head = m[2].split()
        pins = [t for t in head if "=" not in t]
        defaults = dict(t.split("=", 1) for t in head if "=" in t)
        lines = [l for l in m[3].splitlines() if l.strip() and not l.startswith("*")]
        out[m[1]] = (pins, defaults, lines)
    return out


def deck_params(text: str) -> dict:
    env = {}
    for line in re.sub(r"\n\+\s*", " ", text).splitlines():
        if line.lower().startswith(".param"):
            for k, v in re.findall(r"(\w+)=(\{[^}]*\}|\S+)", line[6:]):
                env[k] = ev(v, env)
    return env


def walk(subs, name, nets, params, prefix, out, genv):
    """Flatten `name`: amplifier instances become cells, std cells stay instances, the rest devices.

    Items: (kind, path, model, connections, values); path uses '/' between hierarchy levels and
    connections are the parent's net names."""
    pins, defaults, lines = subs[name]
    env = dict(genv)
    for k, v in defaults.items():
        env[k] = ev(v, env)
    env.update(params)
    local = dict(zip(pins, nets))

    def node(n):
        return local.get(n, prefix + n)

    for line in lines:
        tok = line.split()
        inst, rest = tok[0], tok[1:]
        kv = dict(t.split("=", 1) for t in rest if "=" in t)
        pos = [t for t in rest if "=" not in t]
        model = pos[-1]
        conns = [node(n) for n in pos[:-1]]
        path = prefix + inst
        if model.startswith("sky130_fd_pr__"):
            vals = {k.lower(): ev(v, env) for k, v in kv.items() if k.lower() in ("w", "l", "m", "mult")}
            out.append(("dev", path, model, conns, vals))
        elif model.startswith("sky130_fd_sc_"):
            out.append(("std", path, model, conns, {}))
        else:
            child = {k: ev(v, env) for k, v in kv.items()}
            cell = next((c for m, p, c in AMP_CELLS if m == model and
                         all(abs(child.get(k, 0) - v) < 1e-9 * max(1, abs(v)) for k, v in p.items())), None)
            if cell:
                out.append(("cell", path, cell, conns, child))
            elif model in ("cd_signal_az", "cd_amp_az_biased", "cd_ref_az", "pdk_amp"):
                raise ValueError(f"no laid-out cell for {model} {child}")
            else:
                walk(subs, model, conns, child, path + "/", out, genv)


def deck():
    text = DECK.read_text()
    return text, hashlib.sha256(text.encode()).hexdigest(), subckts(text), deck_params(text)


# Blocks: (root subcircuit, its parameters, instance-path patterns, port order, layout dummies, note).
# Patterns are regular expressions matched against the item path inside the root.
NEURON_H = dict(DPROG=0.5, CORE_SCALE=1.0)
NEURON_Z = dict(DPROG=1.0, CORE_SCALE=1.0)
BLOCKS = {
    "cp_tg1": ("transmission_gate", dict(UNITS=1.0), [r".*"], ["a", "b", "en", "en_b", "vdd", "vss"], [],
               "transmission gate, UNITS=1"),
    "cp_tg4": ("transmission_gate", dict(UNITS=4.0), [r".*"], ["a", "b", "en", "en_b", "vdd", "vss"], [],
               "transmission gate, UNITS=4"),
    "cp_tgs": ("cd_tg_small", {}, [r".*"], ["a", "b", "en", "en_b", "vdd", "vss"], [], "observer switch"),
    "ext_sw": ("ext_bias_switch", {}, [r".*"], ["ladder", "ext", "en", "out", "vdd", "vss"], [],
               "external-bias two-way switch"),
    "bias_sel": ("bias_selector", {}, [r".*"], ["v0", "v1", "v2", "out", "a", "b", "vdd", "vss"], [],
                 "bias selector (AH, unchanged)"),
    "obs_mux": ("observe_mux", {}, [r".*"],
                ["z", "h1", "h2", "ref", "f1", "f2", "bias1", "bias2", "sel0", "sel1", "sel2", "vdd", "vss", "out"], [],
                "8-channel observer"),
    "echo": ("echo_buffers", {}, [r".*"],
             [f"in{i}" for i in range(8)] + [f"out{i}" for i in range(8)] + ["vdd", "vss"], [], "echo buffers"),
    "rw_res": ("xor_network", {}, [r"XRW4/.*", r"XRW5/.*"], ["z", "f1", "f2", "vss"],
               ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2,
               "Z's input resistors XRW4 (z-f1) and XRW5 (z-f2), 200k = two strips each, two end dummies"),
    "rsense": ("xor_readout", {}, [r"XRSENSE/.*"], ["inp", "sense", "vss"],
               ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2, "readout sense resistor, 100k, two end dummies"),
    "ref_inv": ("xor_references_stiff", {}, [r"XAZB/.*", r"XAZ/.*"], ["reset", "az", "az_b", "vdd", "vss"], [],
                "reference buffers' auto-zero inverter pair (ref_reset -> az_b -> az)"),
    "bypass": ("xor_references_stiff", {}, [r"XCBYPASS/.*"], ["ref", "vss"], [], "4 pF REF bypass capacitor"),
    "rout": ("xor_readout", {}, [r"XROUT/.*"], ["buffered", "pad"], [], "readout's 100 ohm output resistor"),
    "readout": ("xor_readout", {}, [r"XRSENSE/.*", r"XROUT/.*", r"XBUF"], ["inp", "pad", "vdd", "vss"],
                ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2,
                "readout: 100k sense resistor, the pad buffer (az_pad) and the 100 ohm output resistor"),
    "neuron_h": ("cd_core_two_az", NEURON_H, [r".*"],
                 ["natural", "bpin", "reset", "hold_in", "y", "h", "ref", "vdd", "vss"],
                 ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2 + ["sky130_fd_pr__res_xhigh_po_2p85 L=47.31"] * 2,
                 "hidden neuron (cd_core_two_az, DPROG=0.5) with its control"),
    "neuron_z": ("cd_core_two_az", NEURON_Z, [r".*"],
                 ["reset", "hold_in", "y", "h", "ref", "vdd", "vss"],
                 ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2 + ["sky130_fd_pr__res_xhigh_po_2p85 L=35.44"] * 2,
                 "output neuron Z (cd_core_two_az, DPROG=1); natural is its own state h and bpin is ref, as in xor_network"),
    "neuron_ctrl": ("cd_core_two_az", NEURON_H, [r"XCTRL/.*", r"XAZB/.*", r"XAZ/.*"],
                    ["natural", "ref", "reset", "hold_in", "cmd", "h", "az", "az_b", "vdd", "vss"], [],
                    "neuron control (xor_control) and the amplifiers' auto-zero inverter pair"),
    "neuron_res": ("cd_core_two_az", NEURON_H, [r"XR1/.*", r"XR6/.*", r"XR8/.*", r"XR3/.*", r"XR5/.*"],
                   ["y", "m", "p", "q", "o", "bpin", "ref", "vss"],
                   ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2,
                   "neuron resistors R1 R6 R8 (100k) and R3 R5 (200k, two strips each), two end dummies"),
}


TIES = {"neuron_z": {"natural": "h", "bpin": "ref"}}     # nets joined inside the cell, as XZ is wired


def block_items(name):
    root, params, pats, ports, extra, note = BLOCKS[name]
    text, sha, subs, genv = deck()
    pins = subs[root][0]
    tie = TIES.get(name, {})
    items = []
    walk(subs, root, [tie.get(p, p) for p in pins], params, "", items, genv)
    pins = [tie.get(p, p) for p in pins]
    sel = [it for it in items if any(re.fullmatch(p, it[1]) for p in pats)]
    rest = [it for it in items if it not in sel]
    inside = {n for it in sel for n in it[3]}
    outside = {n for it in rest for n in it[3]} | set(pins)
    boundary = inside & outside
    missing = boundary - set(ports)
    assert not missing, f"{name}: boundary nets {missing} not in the port list"
    unused = [p for p in ports if p not in inside]
    assert not unused, f"{name}: ports {unused} touch no device"
    return sel, ports, extra, note, sha


def fmt(kind, iname, model, conns, vals):
    name = "X" + iname.replace("/", "_").lstrip("X")
    conns = [c.replace("/", "_") for c in conns]
    if kind == "dev":
        if "fet" in model:
            p = [f"L={vals['l']:g}", f"W={vals['w']:g}", f"m={vals.get('m', 1):g}"]
        elif "res_" in model:
            p = [f"L={vals['l']:g}"] + ([f"W={vals['w']:g}"] if "generic" in model else [])
        else:
            p = [f"W={vals['w']:g}", f"L={vals['l']:g}"]
        return " ".join([name] + conns + [model] + p)
    return " ".join([name] + conns + [model])


def std_defs(models, written):
    text = re.sub(r"\n\+\s*", " ", STD.read_text())
    out = []
    for m in sorted(models):
        if m not in written:
            out += [re.search(r"(?ms)^\.subckt " + m + r" .*?^\.ends", text)[0], ""]
            written.add(m)
    return out


def amp_defs(cells, written):
    """The verified amplifier cells' own references, each subcircuit once."""
    out = []
    for cell in cells:
        body = (AMP_REF / f"{cell}_ref.spice").read_text()
        keep, skipping = [], False
        for l in body.splitlines():
            if l.startswith("*"):
                continue
            m = re.match(r"\.subckt (\S+)", l)
            if m:
                skipping = m[1] in written
                written.add(m[1])
            if not skipping:
                keep.append(l)
            if l.startswith(".ends"):
                skipping = False
        out += keep + [""]
    return out


def write_block(name) -> Path:
    sel, ports, extra, note, sha = block_items(name)
    lines = [f"* LVS reference for {name}: {note}.",
             f"* From {DECK.relative_to(FEAS)} (sha256 {sha}), subcircuit {BLOCKS[name][0]}.",
             "* Layout additions: " + (", ".join(extra) + " (both terminals and bulk on vss)" if extra else "none"), ""]
    written: set = set()
    lines += std_defs({it[2] for it in sel if it[0] == "std"}, written)
    lines += amp_defs(sorted({it[2] for it in sel if it[0] == "cell"}), written)
    lines.append(f".subckt {name} " + " ".join(ports))
    for it in sel:
        lines.append(fmt(*it))
    for k, d in enumerate(extra):
        model, *p = d.split()
        lines.append(f"XDUMMY{k} vss vss vss {model} " + " ".join(p))
    lines.append(f".ends {name}")
    path = REF / f"{name}_ref.spice"
    path.write_text("\n".join(lines) + "\n")
    return path


def check_z_banks():
    """ref/z_passives_ref.spice is candidate_passives' reference with Z's bank length; confirm the length."""
    text, sha, subs, genv = deck()
    items = []
    walk(subs, "cd_core_two_az", subs["cd_core_two_az"][0], NEURON_Z, "", items, genv)
    banks = {round(it[4]["l"], 4) for it in items if it[1].startswith(("XR4/", "XR7/"))}
    assert banks == {35.44}, banks
    body = (REF / "z_passives_ref.spice").read_text()
    assert body.count("res_xhigh_po_2p85 L=35.44") == 6, "z_passives reference out of date"


if __name__ == "__main__":
    check_z_banks()
    for b in sys.argv[1:] or list(BLOCKS):
        p = write_block(b)
        n = sum(1 for l in p.read_text().splitlines() if l.startswith("X") and not l.startswith("XSTD"))
        print(f"{b}: {p.name}")


# ---------------------------------------------------------------- the whole chip, under Tiny Tapeout pin names
TT_MAP = {"bit_a": "ui_in[0]", "bit_b": "ui_in[1]", "reset": "ui_in[2]", "hold_in": "ui_in[3]", "ref_reset": "ui_in[4]",
          "obs_sel0": "ui_in[5]", "obs_sel1": "ui_in[6]", "obs_sel2": "ui_in[7]", "ext_en1": "uio_in[0]",
          "ext_en2": "uio_in[1]", "pad": "ua[0]", "ext_bias": "ua[1]", "vdd": "VDPWR", "vss": "VGND",
          **{f"uo_out{i}": f"uo_out[{i}]" for i in range(8)}}
TT_PORTS = (["clk", "ena", "rst_n"] + [f"ua[{i}]" for i in range(8)] + [f"ui_in[{i}]" for i in range(8)]
            + [f"uio_in[{i}]" for i in range(8)] + [f"uo_out[{i}]" for i in range(8)] + ["VGND", "VDPWR"])
# grounded dummy strips that exist only in the layout: (model and length, count, where)
CHIP_DUMMIES = [("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 6, "neuron_res x3"),
                ("sky130_fd_pr__res_xhigh_po_2p85 L=47.31", 4, "candidate_passives x2 (H1, H2)"),
                ("sky130_fd_pr__res_xhigh_po_2p85 L=35.44", 2, "z_passives (Z)"),
                ("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 2, "rw_res"),
                ("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 2, "rsense"),
                ("sky130_fd_pr__res_xhigh_po_2p85 L=1.42", 12, "reference ladder edge dummies")]
# uio_out[0..7] and uio_oe[0..7] are tied to VGND in the layout; Magic merges them into VGND's port.


def write_chip(top="tt_um_mbacvanski_denseam_xor"):
    text, sha, subs, genv = deck()
    pins = subs["xor_chip_staged"][0]
    items = []
    walk(subs, "xor_chip_staged", [TT_MAP[p] for p in pins], {}, "", items, genv)
    lines = [f"* LVS reference for the whole chip ({top}): variant AI's xor_chip_staged under Tiny Tapeout pin names.",
             f"* From {DECK.relative_to(FEAS)} (sha256 {sha}). Amplifier instances are the verified amplifier",
             "* cells (their references follow); standard cells stay sky130_fd_sc_hd instances; every other device",
             "* is flattened with its deck parameters. Layout additions, all three terminals on VGND:",
             *[f"*   {n} x {m} ({w})" for m, n, w in CHIP_DUMMIES],
             "* uio_out[*] and uio_oe[*] are tied to VGND (Tiny Tapeout: every output driven); Magic merges them",
             "* into VGND's port. clk, ena, rst_n, uio_in[2..7] and ua[2..7] are unused.", ""]
    written: set = set()
    lines += std_defs({it[2] for it in items if it[0] == "std"}, written)
    lines += amp_defs(sorted({it[2] for it in items if it[0] == "cell"}), written)
    lines.append(f".subckt {top} " + " ".join(TT_PORTS))
    for it in items:
        lines.append(fmt(*it))
    k = 0
    for model_l, n, where in CHIP_DUMMIES:
        model, lp = model_l.split()
        for _ in range(n):
            lines.append(f"XDUMMY{k} VGND VGND VGND {model} {lp}")
            k += 1
    lines.append(f".ends {top}")
    path = REF / f"{top}_ref.spice"
    path.write_text("\n".join(lines) + "\n")
    return path
