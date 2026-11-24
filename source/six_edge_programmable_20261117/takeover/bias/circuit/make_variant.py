"""Programmable hidden offsets: the variant netlist, made from the selected layout's circuit and nothing else.

    python -I make_variant.py [REFERENCE.spice.gz] [OUT.spice] [--wprog1 W --lprog1 L --wprog2 W --lprog2 L]

Input (read only, checked by hash): EV/layout_bbf78759_gate_p897/reference.spice.gz.
Output: variant_reference.spice beside this script (or OUT), and variant_manifest.json (hashes, every changed line,
every added device and net). The size options exist for the screens' sweeps; the published file uses XPROG below.

Version 3 (2026-11-23): version 2 (after the design lead's change of 14:35; takeover/bias/SPEC.md and
layout/INTERFACE.md) with the XPROG sizes made final by screen 1:
per hidden neuron k
    p_k --[chain, unchanged]-- end_k --| XSW_k (gate six, unchanged) |-- ret_k --| XPROG_k (gate bg_k) |-- vss
What is added, each group one subcircuit because each becomes a layout cell:
  native_offset_prog    the pair XPROG1, XPROG2: drain ret_k, gate bg_k, source and body vss
  native_offset_word    one stored word (two instances): the storage MIM from bg to ground and a copy of the
                        two-stage writer of pw4_shunt, device for device
  native_offset_strobe  bstb1 = bit_a & bit_b & we0, bstb2 = bit_a & bit_b & we1, as the layout work draws it:
                        one NAND2 (bit_a, bit_b), one inverter per we line, two NOR2
What is changed in the original (and nothing else):
  - native_fixed_offsets: two ports ret1 ret2 added; XRETURN's source pins b1 b2 (vss vss) -> ret1 ret2
  - xor_chip_native_six: XSTATIC gets ret1 ret2; four instances appended (XOPROG, XOWORD1, XOWORD2, XOSTROBE)
The chains' ends end1, end2 are not touched.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[2]
REFERENCE = SIX / 'native_edges/verification/evidence/layout_bbf78759_gate_p897/reference.spice.gz'
REFERENCE_SHA = '6a4914949436474a194d8c3b3386713eb179511f5ee10c41911b647b57e85a3d'   # of the decompressed text
VERSION = 3

# ---- sizes (the only numbers a later revision may change; ADDED.md says when they are final)
XPROG = {1: dict(W=0.42, L=3.2), 2: dict(W=1.0, L=3.5)}     # FINAL (version 3), chosen by screen 1 at all conditions
# (version 2 had the SPEC's starting sizes W 0.42 / L 4 and W 1 / L 4: worst full-current error 2.60%, against 2.11% now)
CSTORE = 8.97                                                # MIM side, um (161 fF)


def nfet_geometry(w: float) -> str:
    """ad/as/pd/ps as the reference writes them for a single finger (0.29 um of diffusion beyond the gate)."""
    a = round(w * 0.29, 6)
    p = round(2 * (w + 0.29), 6)
    nr = round(0.29 / w, 4)
    return f'ad={a:g} as={a:g} pd={p:g} ps={p:g} nrd={nr:g} nrs={nr:g} sa=0 sb=0 sd=0 mult=1 m=1'


def new_subckts(xprog) -> str:
    w1, l1, w2, l2 = xprog[1]['W'], xprog[1]['L'], xprog[2]['W'], xprog[2]['L']
    return f"""
* ==== Programmable hidden offsets (variant v{VERSION} of 2026-11-23, takeover/bias/SPEC.md); everything below is new ====

.subckt native_offset_prog ret1 ret2 bg1 bg2 vss
* The pair of programmable offset transistors. Each sits between the source of the existing mode switch (XSW_k of
* native_ground_return, gate six) and ground: end_k -- XSW_k -- ret_k -- XPROG_k -- vss. Gate bg_k = the stored word;
* source and body on the same ground as the storage capacitor, so the stored voltage is the gate-to-source voltage.
* Long-channel 1.8 V NMOS: with bg_k at the supply the chain draws today's current; lower bg_k lowers the offset.
XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L={l1:g} W={w1:g} nf=1 {nfet_geometry(w1)}
XPROG2 ret2 bg2 vss vss sky130_fd_pr__nfet_01v8 L={l2:g} W={w2:g} nf=1 {nfet_geometry(w2)}
.ends

.subckt native_offset_word bg dac bstb ref vdd vss
* One stored hidden offset (two instances): the stored gate bg on a MIM to the local ground, and a copy of the
* two-stage writer of pw4_shunt, device for device. At bg a 5 V NMOS (XW1N) beside an LVT PMOS (XW1P), then a
* transmission gate (XW2) to the DAC line; when not writing, the middle node wm is held at REF by the long weak
* NMOS XWC, so the stored gate has REF behind its off writer whatever the DAC line does. XWI: the strobe's inverter
* (bstbb). Stored node on the MIM's first terminal (top plate), as in the existing words. No clamp on bg.
XC bg vss sky130_fd_pr__cap_mim_m3_1 W={CSTORE:g} L={CSTORE:g} MF=1 m=1
XW1N bg bstb wm vss sky130_fd_pr__nfet_g5v0d10v5 L=4 W=0.42 nf=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 nrd=0.6905 nrs=0.6905 sa=0 sb=0 sd=0 mult=1 m=1
XW1P bg bstbb wm vdd sky130_fd_pr__pfet_01v8_lvt L=1 W=1 nf=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0 mult=1 m=1
XW2 wm dac bstb bstbb vdd vss cd_tg_small
XWC wm bstbb ref vss sky130_fd_pr__nfet_01v8 L=8 W=0.42 nf=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 nrd=0.6905 nrs=0.6905 sa=0 sb=0 sd=0 mult=1 m=1
XWI bstb bstbb vdd vss cmos_inv
.ends

.subckt native_offset_strobe bit_a bit_b we0 we1 bstb1 bstb2 vdd vss
* The two strobes of the bias row, built beside the stored words from global nets (layout/INTERFACE.md).
* Row (bit_a, bit_b) = (1, 1), unused by the resistor rows; we0 (word address 0) writes H1's offset, we1 (word
* address 1) H2's. we0, we1 come from pw4_decoder and already contain WRITE, RES_SEL, not WEIGHT_PROG and the word
* address, so six = 0 whenever bstb1 or bstb2 is high.
*   bstb1 = bit_a & bit_b & we0 = NOR2(NAND2(bit_a, bit_b), not we0);  bstb2 likewise with we1
XSAB bit_a bit_b vss vss vdd vdd nab sky130_fd_sc_hd__nand2_1
XSW0 we0 nwe0 vdd vss cmos_inv
XSW1 we1 nwe1 vdd vss cmos_inv
XSB1 nab nwe0 bstb1 vdd vss cmos_nor2
XSB2 nab nwe1 bstb2 vdd vss cmos_nor2
.ends
"""


# (old line, new lines) -- each old line must occur exactly once in the reference
EDITS = [
    ('.subckt native_fixed_offsets ref bias1 bias2 p1 p2 six vss',
     ['.subckt native_fixed_offsets ref bias1 bias2 p1 p2 six vss ret1 ret2']),
    ('XRETURN end1 end2 vss vss six vss native_ground_return',
     ['* variant: the sources of the two mode switches go to ret1, ret2 (the programmable transistors below them)',
      'XRETURN end1 end2 ret1 ret2 six vss native_ground_return']),
    ('XSTATIC ref fixed1 fixed2 p1 p2 six vss native_fixed_offsets',
     ['XSTATIC ref fixed1 fixed2 p1 p2 six vss ret1 ret2 native_fixed_offsets']),
    ('XH2FEEDBACK f2 p2 q2 ref six vss native_hidden_feedback',
     ['XH2FEEDBACK f2 p2 q2 ref six vss native_hidden_feedback',
      '* ---- variant: programmable hidden offsets (takeover/bias/SPEC.md), one instance per new layout cell',
      'XOPROG ret1 ret2 bg1 bg2 vss native_offset_prog',
      'XOWORD1 bg1 ext_in bstb1 ref vdd vss native_offset_word',
      'XOWORD2 bg2 ext_in bstb2 ref vdd vss native_offset_word',
      'XOSTROBE bit_a bit_b we0 we1 bstb1 bstb2 vdd vss native_offset_strobe']),
]

NEW_NETS = {
    'xor_chip_native_six': ['ret1', 'ret2', 'bg1', 'bg2', 'bstb1', 'bstb2'],
    'native_fixed_offsets': ['ret1', 'ret2'],
}


def subckt_body(text: str, name: str) -> list[str]:
    lines = text.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith(f'.subckt {name} '))
    j = next(k for k in range(i, len(lines)) if lines[k].startswith('.ends'))
    return lines[i:j + 1]


def build(reference: Path, xprog=None) -> tuple[str, dict]:
    xprog = xprog or XPROG
    raw = gzip.decompress(reference.read_bytes()) if reference.suffix == '.gz' else reference.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != REFERENCE_SHA:
        raise SystemExit(f'reference hash {sha} is not the selected layout\'s {REFERENCE_SHA}')
    text = raw.decode()
    for sub, nets in NEW_NETS.items():                 # the new net names must be unused where they are introduced
        body = ' '.join(subckt_body(text, sub))
        for n in nets:
            if f' {n} ' in f' {body} ':
                raise SystemExit(f'{n} already used in {sub}')
    lines = text.splitlines()
    changed = []
    for old, new in EDITS:
        hits = [k for k, l in enumerate(lines) if l == old]
        if len(hits) != 1:
            raise SystemExit(f'{old!r} occurs {len(hits)} times')
        changed.append(dict(reference_line=text.splitlines().index(old) + 1, old=old, new=new))
        k = hits[0]
        lines[k:k + 1] = new
    out = '\n'.join(lines).rstrip('\n') + '\n' + new_subckts(xprog)
    manifest = dict(
        version=VERSION,
        reference=str(reference.relative_to(SIX)) if reference.is_relative_to(SIX) else str(reference),
        reference_sha256_decompressed=sha,
        variant_sha256=hashlib.sha256(out.encode()).hexdigest(),
        xprog=xprog, cstore_um=CSTORE,
        changed_lines=changed,
        new_subckts=['native_offset_prog', 'native_offset_word', 'native_offset_strobe'],
        new_nets=NEW_NETS | {'native_offset_word (each)': ['wm', 'bstbb'],
                             'native_offset_strobe': ['nab', 'nwe0', 'nwe1']},
    )
    return out, manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('reference', nargs='?', default=str(REFERENCE))
    ap.add_argument('out', nargs='?', default=str(HERE / 'variant_reference.spice'))
    for k in (1, 2):
        ap.add_argument(f'--wprog{k}', type=float, default=XPROG[k]['W'])
        ap.add_argument(f'--lprog{k}', type=float, default=XPROG[k]['L'])
    a = ap.parse_args()
    xprog = {k: dict(W=getattr(a, f'wprog{k}'), L=getattr(a, f'lprog{k}')) for k in (1, 2)}
    out, manifest = build(Path(a.reference), xprog)
    dst = Path(a.out)
    dst.write_text(out)
    if dst.resolve() == (HERE / 'variant_reference.spice').resolve():
        (HERE / 'variant_manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    print(dst, manifest['variant_sha256'])


if __name__ == '__main__':
    main()
