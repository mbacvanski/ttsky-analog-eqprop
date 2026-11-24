"""Assemble az_core, run Magic DRC, extract LVS and parasitic netlists, write GDS.

Usage: python build.py            (always assembles from scratch)
Outputs:
  layout/az_core.mag, layout/az_core.gds
  build/az_core_drc.txt                    full DRC listing
  build/ext/az_core_lvs.spice              extraction for LVS (no parasitics)
  build/ext/az_core_pex.spice              extraction with all wiring capacitance (cthresh 0)
  results/az_core_drc.json                 DRC summary
"""
from __future__ import annotations

import json
import re
import sys

from geom import Tcl
from magic_util import BUILD, LAYOUT, RESULTS, run_magic

DRC_TCL = r"""
proc cell_drc {cell report} {
  load $cell
  select top cell
  expand
  drc euclidean on
  drc style drc(full)
  drc check
  drc catchup
  set res [drc listall why]
  set fout [open $report w]
  set total 0
  foreach {why boxes} $res {
    puts $fout "RULE\t[llength $boxes]\t$why"
    foreach b $boxes {
      puts $fout "  [expr {[lindex $b 0]*0.005}] [expr {[lindex $b 1]*0.005}] [expr {[lindex $b 2]*0.005}] [expr {[lindex $b 3]*0.005}]"
    }
    incr total [llength $boxes]
  }
  close $fout
  puts "DRCTOTAL $cell $total"
}
proc cell_extract {cell extdir} {
  load $cell
  select top cell
  file mkdir $extdir
  set olddir [pwd]
  cd $extdir
  extract all
  ext2spice lvs
  ext2spice -o ${cell}_lvs.spice
  ext2spice cthresh 0
  ext2spice -o ${cell}_pex.spice
  cd $olddir
}
"""


def builder(cell):
    import amp_layout
    import clamp_layout
    import limiter_layout
    import block_layout
    import bigamp_layout
    import aj_amp_layout
    import lean_layout
    return {"aj_core": aj_amp_layout.build,
            "aj_core1p": lambda t: aj_amp_layout.build(t, "aj_core1p"),
            "lean_act": lean_layout.build_act,
            "lean_bias": getattr(lean_layout, "build_bias", None),
            "lean_block": getattr(lean_layout, "build_block", None),
            "az_clamp": clamp_layout.build,
            "az_ref4": bigamp_layout.build_ref4,
            "pad_core": bigamp_layout.build_pad_core,
            "az_pad": bigamp_layout.build_pad,
            "act_pos": block_layout.build_act_pos,
            "act_neg": block_layout.build_act_neg,
            "limiter": limiter_layout.build,
            "az_core": lambda t: amp_layout.build(t, amp_layout.CORE),
            "az_gain": lambda t: amp_layout.build(t, amp_layout.GAIN),
            "az_ref1": lambda t: amp_layout.build(t, amp_layout.REF1),
            "ref4_core": lambda t: amp_layout.build(t, amp_layout.REF4CORE)}[cell]


def main(cell="az_core", extract=True):
    (LAYOUT / f"{cell}.mag").unlink(missing_ok=True)
    t = Tcl()
    t.add("random seed 20261108")
    info = builder(cell)(t)
    t.add(f"save {cell}")
    t.add(DRC_TCL)
    t.add(f"cell_drc {cell} {BUILD / (cell + '_drc.txt')}")
    if extract:
        t.add(f"cell_extract {cell} {BUILD / 'ext'}")
    t.add(f"load {cell}")
    t.add(f"gds write {LAYOUT / (cell + '.gds')}")
    t.add("quit -noprompt")
    out = run_magic(t.text(), f"build_{cell}")
    m = re.search(rf"DRCTOTAL {cell} (\d+)", out)
    total = int(m.group(1)) if m else -1
    rules = []
    for line in (BUILD / f"{cell}_drc.txt").read_text().splitlines():
        if line.startswith("RULE"):
            _, n, why = line.split("\t", 2)
            rules.append(dict(rule=why, count=int(n)))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{cell}_drc.json").write_text(json.dumps(
        dict(cell=cell, tool="magic 8.3.685, drc(full), euclidean", total=total, rules=rules), indent=1) + "\n")
    print(f"{cell}: DRC errors {total}")
    for r in rules:
        print(f"   {r['count']:4d}  {r['rule']}")
    errs = [l for l in out.splitlines() if re.search(r"(?i)error|unknown|can't|cannot", l)]
    if errs:
        print("magic messages:", *errs[:20], sep="\n  ")
    return info


if __name__ == "__main__":
    cells = [a for a in sys.argv[1:] if not a.startswith("--")] or ["az_core"]
    for c in cells:
        main(c, extract="--no-extract" not in sys.argv)
