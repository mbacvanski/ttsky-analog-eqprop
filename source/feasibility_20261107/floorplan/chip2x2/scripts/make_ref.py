"""LVS references for the 2x2 chip's blocks and for the whole chip, written from variant AJ's netlist.

Source: ../../../amp_layout/ref/aj_native.spice (AJ's chip bench as Mesa netlists it; the cell-layout work's
copy, sha256 834f6b89...). The work is done by the 3x2 chip's make_ref.py (../../chip/scripts), pointed at AJ's
deck and AJ's cells: amplifier instances become the verified amplifier cells (aj_core1p, az_ref1, az_ref4, az_pad,
lean_act, lean_bias), standard cells stay sky130_fd_sc_hd instances, every other device is flattened with its
deck parameters.

  python make_ref.py [block ...]     block references (default: all)
  python make_ref.py chip            the whole chip under Tiny Tapeout pin names
"""
from __future__ import annotations

import importlib.util
import re
import sys

import magic_util
from magic_util import AMP, CHIP3X2, REF
import chip

spec = importlib.util.spec_from_file_location("make_ref_3x2", CHIP3X2 / "scripts" / "make_ref.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

m.DECK = chip.DECK
m.AMP_REF = AMP / "ref"
m.AMP_CELLS = [("cd_signal_az", dict(COMP=1e-12, RZERO=5e3, DRIVE=0.5), "aj_core1p"),
               ("cd_ref_az", dict(COMP=1.2e-12, DRIVE=1.0), "az_ref1"),
               ("cd_ref_az", dict(COMP=4e-12, DRIVE=4.0), "az_ref4"),
               ("pdk_amp", dict(COMP=4e-12, DRIVE=4.0), "az_pad"),
               ("lean_act", {}, "lean_act"),
               ("lean_bias", {}, "lean_bias")]
NEURON_H = dict(DPROG=0.5, CORE_SCALE=1.0)
NEURON_Z = dict(DPROG=1.0, CORE_SCALE=1.0)
m.BLOCKS = {
    "aj_neuron_h": ("cd_core_two_az", NEURON_H, [r".*"],
                    ["natural", "bpin", "reset", "hold_in", "y", "h", "ref", "vdd", "vss"],
                    ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2 + ["sky130_fd_pr__res_xhigh_po_1p41 L=46.84"] * 2,
                    "hidden neuron of variant AJ (cd_core_two_az, DPROG=0.5, U1 and U3 = aj_core) with its control"),
    "aj_neuron_z": ("cd_core_two_az", NEURON_Z, [r".*"],
                    ["reset", "hold_in", "y", "h", "ref", "vdd", "vss"],
                    ["sky130_fd_pr__res_xhigh_po_1p41 L=70.34"] * 2 + ["sky130_fd_pr__res_xhigh_po_1p41 L=35.09"] * 2,
                    "output neuron Z of variant AJ (cd_core_two_az, DPROG=1); natural is its own state h and bpin is ref, as in xor_network"),
}
# The second output and the pin resistors. These cells hold devices of more than one subcircuit, so their blocks
# are cut from a subcircuit higher up and the nets are renamed to the cell's port names (RENAME).
m.BLOCKS["obs2_mux"] = ("xor_network", {}, [r"XOBS2/.*", r"XREAD2/XRS/.*"],
                        ["ref", "z", "h1", "h2", "obs2_sel0", "obs2_sel1", "vdd", "vss", "XREAD2/sense"],
                        ["sky130_fd_pr__res_xhigh_po_0p35 L=17.4"],
                        "four-way selector of the second analog output (second_observer) and the output's 100k sense "
                        "resistor (XRS of second_readout), one dummy strip")
m.BLOCKS["buf2"] = ("second_readout", {}, [r"XAMP", r"XAZB/.*", r"XAZ/.*"], ["sense", "buf", "reset", "ref", "vdd", "vss"], [],
                    "the second output's buffer: aj_core1p as a follower and its auto-zero inverter pair")
m.BLOCKS["pin_res"] = ("xor_chip_staged", {}, [r"XRPIN1/.*", r"XNET/XREAD/XROUT/.*", r"XNET/XREAD2/XRO/.*"],
                       ["pad", "XNET/XREAD/buffered", "ext_bias", "ext_in", "pad2", "XNET/XREAD2/buf", "vss"], [],
                       "the series resistor at each analog pin: 3k at ua[0] (XROUT), 10k at ua[1] (XRPIN1), 5k at ua[2] (XRO)")
RENAME = {"obs2_mux": {"obs2_sel0": "sel0", "obs2_sel1": "sel1", "XREAD2/sense": "sense", "XREAD2_sense": "sense"},
          "pin_res": {"XNET/XREAD/buffered": "buffered", "XNET_XREAD_buffered": "buffered",
                      "XNET/XREAD2/buf": "buf", "XNET_XREAD2_buf": "buf"}}
m.TIES = {"aj_neuron_z": {"natural": "h", "bpin": "ref"}}
# grounded dummy strips that exist only in the layout and are not inside an amplifier cell's own reference
m.CHIP_DUMMIES = [("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 6, "neuron_res x3"),
                  ("sky130_fd_pr__res_xhigh_po_1p41 L=46.84", 4, "weight-bank arrays of H1 and H2"),
                  ("sky130_fd_pr__res_xhigh_po_1p41 L=35.09", 2, "weight-bank array of Z"),
                  ("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 2, "rw_res"),
                  ("sky130_fd_pr__res_xhigh_po_1p41 L=70.34", 2, "rsense"),
                  ("sky130_fd_pr__res_xhigh_po_2p85 L=1.42", 12, "reference ladder edge dummies"),
                  ("sky130_fd_pr__res_xhigh_po_0p35 L=17.4", 1, "second output's sense resistor (obs2_mux)")]


# second analog output (SECOND_OUTPUT.md): pad2 on ua[2], its two select bits on uio[2] and uio[3]
m.TT_MAP.update({"pad2": "ua[2]", "obs2_sel0": "uio_in[2]", "obs2_sel1": "uio_in[3]"})

# the 3x2 module's helpers under this module's name (wired_map.py imports them as make_ref.*)
subckts, deck_params, ev, num, walk, STD, TT_MAP, TT_PORTS = (m.subckts, m.deck_params, m.ev, m.num, m.walk, m.STD,
                                                             m.TT_MAP, m.TT_PORTS)


def write_chip():
    p = m.write_chip(chip.TOP)
    text = p.read_text().replace("variant AI's xor_chip_staged", "variant AJ's xor_chip_staged")
    p.write_text(text)
    return p


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["chip"]:
        print(write_chip())
    else:
        for b in args or list(m.BLOCKS):
            p = m.write_block(b)
            if b in RENAME:
                text = p.read_text()
                for old, new in RENAME[b].items():
                    text = re.sub(rf"(?<![\w/]){re.escape(old)}(?![\w/])", new, text)
                p.write_text(text)
            print(b, p.name)
