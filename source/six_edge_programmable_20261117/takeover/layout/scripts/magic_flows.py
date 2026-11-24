"""Batch Magic on a GDS, with the command sequences of the accepted chip flow (feasibility_20261107/floorplan/chip/scripts/
wired_extract.py cap/res/antenna and programmable_weights_v4_20261114/floorplan/scripts/chip_lvs.py extract), except that the
layout is read from the GDS (`gds read`) instead of from Magic's own .mag files: the selected chip exists only as a GDS.

  PY -I magic_flows.py lvs     GDS OUTDIR        flat extraction for LVS        -> OUTDIR/lvs/flat_lvs.spice (+ .ext)
  PY -I magic_flows.py cap     GDS OUTDIR        flat extraction, every coupling -> OUTDIR/wired/tt_flat.ext, tt_flat_pex.spice
  PY -I magic_flows.py res     GDS OUTDIR NET..  the same plus extresist on NETs -> OUTDIR/wired/res/tt_flat.res.ext, tt_flat_rc.spice
  PY -I magic_flows.py antenna GDS OUTDIR        antennacheck, PDK rules and near-zero limits -> OUTDIR/antenna*/, OUTDIR/antenna.json
  PY -I magic_flows.py drc     GDS OUTDIR        Magic's full rule deck          -> OUTDIR/drc.json
  PY -I magic_flows.py wire    GDS OUTDIR        the res sequence on every device-bearing net -> OUTDIR/wired/wire/tt_flat_rc.spice
Every run writes its Tcl and its full log beside its output. Magic 8.3.685 and the PDK's sky130A.magicrc, as the accepted flow.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
PDK_ROOT = Path(os.environ.get("PDK_ROOT", HOME / ".ciel"))
MAGIC = os.environ.get("MAGIC", str(HOME / ".local/bin/magic-8.3.685"))
MAGICRC = PDK_ROOT / "sky130A/libs.tech/magic/sky130A.magicrc"
KPY = os.environ.get("KLAYOUT_PY", str(HOME / ".local/opt/klayout-py/bin/python"))


def top_of(gds):
    p = subprocess.run([KPY, "-c", f"import klayout.db as db; l=db.Layout(); l.read({str(gds)!r}); print(l.top_cell().name)"],
                       capture_output=True, text=True, check=True)
    return p.stdout.strip().splitlines()[-1]


def run_magic(tcl: str, name: str, cwd: Path, timeout: int = 4 * 3600) -> str:
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "tmp").mkdir(exist_ok=True)
    script = cwd / f"{name}.tcl"
    script.write_text(tcl)
    env = dict(os.environ, PDK_ROOT=str(PDK_ROOT), TMPDIR=str(cwd / "tmp"))
    t0 = time.time()
    p = subprocess.run([MAGIC, "-dnull", "-noconsole", "-rcfile", str(MAGICRC), str(script)], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=timeout)
    out = p.stdout + p.stderr
    (cwd / f"{name}.magic.log").write_text(out)
    if p.returncode != 0:
        raise RuntimeError(f"magic {name} exited {p.returncode}; see {cwd / (name + '.magic.log')}")
    print(f"magic {name}: {time.time() - t0:.0f} s", flush=True)
    return out


def head(gds, top):
    return f"gds read {gds}\nload {top}\n"


def lvs(gds, out):
    d = out / "lvs"
    top = top_of(gds)
    t = f"""snap internal
{head(gds, top)}select top cell
expand
flatten flat_lvs
load flat_lvs
select top cell
cd {d}
extract do local
extract all
ext2spice lvs
ext2spice -o flat_lvs.spice
quit -noprompt
"""
    log = run_magic(t, "lvs_extract", d)
    text = re.sub(r"\n\+\s*", " ", (d / "flat_lvs.spice").read_text())
    assert len(re.findall(r"(?m)^\.subckt ", text)) == 1, "more than one subcircuit: a cell was not flattened"
    return d / "flat_lvs.spice"


def cap(gds, out):
    d = out / "wired"
    top = top_of(gds)
    t = f"""{head(gds, top)}flatten tt_flat
load tt_flat
select top cell
cd {d}
extract all
ext2spice cthresh 0
ext2spice -o tt_flat_pex.spice
quit -noprompt
"""
    run_magic(t, "wired_extract_cap", d)


REP_TCL = r"""
proc magic_rep {fname labels} {
  set f [open $fname r]; set lines [split [read $f] "\n"]; close $f
  set nodes [dict create]; set pairs {}
  foreach l $lines {
    if {[regexp {^(node|substrate) "([^"]+)"} $l -> k n]} { dict set nodes $n 1 }
    if {[regexp {^equiv "([^"]+)" "([^"]+)"} $l -> a b]} { lappend pairs [list $a $b] }
  }
  set out {}
  foreach lab $labels {
    set r ""
    if {[dict exists $nodes $lab]} { set r $lab } else {
      foreach p $pairs { lassign $p a b
        if {$b eq $lab && [dict exists $nodes $a]} { set r $a; break }
        if {$a eq $lab && [dict exists $nodes $b]} { set r $b; break } } }
    if {$r ne ""} { lappend out $r }
    puts "REPNAME $lab -> $r"
  }
  return [lsort -unique $out]
}
"""


def res(gds, out, nets):
    """As the accepted wired_extract.res(), with one difference: each listed name (a label such as VGND or az_ref4_0.out) is
    replaced, inside the same Magic run and after its `extract all`, by the name of the node record that carries it
    (Magic resists only a net's representative name, and which name represents a net can change from run to run)."""
    d = out / "wired" / "res"
    top = top_of(gds)
    labels = " ".join("{" + n + "}" for n in nets)
    t = f"""{REP_TCL}{head(gds, top)}flatten tt_flat
load tt_flat
select top cell
cd {d}
extract all
ext2sim labels on
ext2sim
extresist simplify {os.environ.get('EXTRESIST_SIMPLIFY', 'off')}
extresist minresist 10
foreach n [magic_rep tt_flat.ext [list {labels}]] {{ puts "RESIST $n"; extresist include $n; extresist force $n }}
extresist all
extresist
ext2spice extresist on
ext2spice cthresh 0
ext2spice -o tt_flat_rc.spice
quit -noprompt
"""
    run_magic(t, "wired_extract_res", d, timeout=8 * 3600)
    (d / "nets.json").write_text(json.dumps(nets, indent=1) + "\n")


DEV_TCL = r"""
proc ext_resolve {n nodes eq} {
  if {[dict exists $nodes $n]} { return $n }
  set seen [dict create $n 1]; set queue [list $n]
  while {[llength $queue]} {
    set q [lindex $queue 0]; set queue [lrange $queue 1 end]
    if {[dict exists $eq $q]} {
      foreach m [dict get $eq $q] {
        if {[dict exists $seen $m]} continue
        if {[dict exists $nodes $m]} { return $m }
        dict set seen $m 1; lappend queue $m
      }
    }
  }
  return ""
}
proc device_nodes {fname} {
  set f [open $fname r]; set lines [split [read $f] "\n"]; close $f
  set nodes [dict create]; set eq [dict create]; set used [dict create]
  foreach l $lines {
    if {[regexp {^(node|substrate) "([^"]+)"} $l -> k n]} { dict set nodes $n 1 }
    if {[regexp {^equiv "([^"]+)" "([^"]+)"} $l -> a b]} { dict lappend eq $a $b; dict lappend eq $b $a }
    if {[regexp {^(device|fet) } $l]} { foreach {all n} [regexp -all -inline {"([^"]+)"} $l] { if {$n ne "None"} { dict set used $n 1 } } }
  }
  set out [dict create]
  foreach n [dict keys $used] {
    set r [ext_resolve $n $nodes $eq]
    if {$r ne ""} { dict set out $r 1 } else { puts "UNRESOLVED $n" }
  }
  return [lsort [dict keys $out]]
}
"""


def wire(gds, out):
    """The accepted res() sequence with wire resistance on EVERY net that touches a device terminal (the device-bearing
    nets, found in the run's own .ext after `extract all`, each resolved to the node record that carries it), as the base flow's
    distributed model selects them. -> OUTDIR/wired/wire/tt_flat.ext, tt_flat.res.ext, tt_flat_rc.spice, nets.txt"""
    d = out / "wired" / "wire"
    top = top_of(gds)
    t = f"""{DEV_TCL}{head(gds, top)}flatten tt_flat
load tt_flat
select top cell
cd {d}
extract all
ext2sim labels on
ext2sim
extresist simplify off
extresist minresist 10
set nets [device_nodes tt_flat.ext]
set fo [open nets.txt w]; foreach n $nets {{ puts $fo $n }}; close $fo
puts "WIRENETS [llength $nets]"
foreach n $nets {{ extresist include $n; extresist force $n }}
extresist all
extresist
ext2spice extresist on
ext2spice cthresh 0
ext2spice -o tt_flat_rc.spice
quit -noprompt
"""
    log = run_magic(t, "wired_extract_wire", d, timeout=12 * 3600)
    m = re.search(r"WIRENETS (\d+)", log)
    print("nets with wire resistance:", m[1] if m else "?", "| unresolved device terminals:", len(re.findall(r"(?m)^UNRESOLVED ", log)))


def _antenna_run(gds, top, d: Path, tech: Path | None, name: str):
    t = (f"tech load {tech} -noprompt\n" if tech else "") + f"""{head(gds, top)}flatten tt_flat
load tt_flat
select top cell
cd {d}
extract all
feedback clear
antennacheck debug
antennacheck run -p {d} tt_flat
puts "ANTENNA_FEEDBACK [feedback count]"
quit -noprompt
"""
    log = run_magic(t, name, d)
    assert "antennacheck finished." in log and "Running antenna checks." in log, "antennacheck did not run"
    viol, plane = [], None
    lines = log.splitlines()
    for i, l in enumerate(lines):
        m = re.match(r"Antenna violation detected at plane (\S+)( contact)?", l)
        if m:
            plane = m[1] + (" contact" if m[2] else "")
            continue
        m = re.match(r"Effective antenna ratio (\S+) > limit (\S+)", l)
        if m and plane:
            g = next((x for x in lines[i + 1:i + 3] if x.startswith("Gate rect")), "")
            xy = [int(v) * 0.005 for v in re.findall(r"-?\d+", g)]
            viol.append((plane, float(m[1]), float(m[2]), [round(v, 2) for v in xy]))
            plane = None
    return int(re.findall(r"ANTENNA_FEEDBACK (\d+)", log)[-1]), viol


def antenna(gds, out):
    """As the accepted wired_extract.antenna(): the PDK's rules, then every limit set near zero (every gate-only net is
    then reported with its ratio, which proves the check runs and shows how close the worst wire is)."""
    top = top_of(gds)
    count, viol = _antenna_run(gds, top, out / "antenna", None, "antenna")
    tech = PDK_ROOT / "sky130A/libs.tech/magic/sky130A.tech"
    low = out / "antenna_low"
    low.mkdir(parents=True, exist_ok=True)
    limits, text = {}, []
    for l in tech.read_text().splitlines():
        m = re.match(r"^(\s*antenna\s+(\S+)\s+(sidewall|surface)\s+)(\S+)(.*)$", l)
        if m:
            for lay in m[2].split(","):
                limits[lay] = (m[3], float(m[4]))
            l = m[1] + "0.0001" + m[5]
        text.append(l)
    (low / "sky130A_lowlimit.tech").write_text("\n".join(text) + "\n")
    lcount, lviol = _antenna_run(gds, top, low, low / "sky130A_lowlimit.tech", "antenna_low")
    plane_rule = {"metal1": "m1", "metal2": "m2", "metal3": "m3", "metal4": "m4", "locali": "li", "poly": "poly"}
    worst = {}
    for plane, ratio, lim, rect in lviol:
        if ratio > worst.get(plane, (0,))[0]:
            worst[plane] = (ratio, rect)
    rows = {}
    for plane, (ratio, rect) in sorted(worst.items(), key=lambda kv: -kv[1][0]):
        rule = limits.get(plane_rule.get(plane.split()[0], ""), (None, None))
        rows[plane] = dict(worst_ratio=round(ratio, 2), limit=None if "contact" in plane else rule[1],
                           used=round(ratio / rule[1], 3) if rule[1] and "contact" not in plane else None, gate_rect_um=rect)
    res = dict(gds=str(gds), top=top, method=antenna.__doc__.strip(), pdk_rules={k: dict(kind=v[0], ratio=v[1]) for k, v in limits.items()},
               with_pdk_rules=dict(violations=len(viol), feedback_entries=count, list=viol),
               with_near_zero_limits=dict(reported=len(lviol), feedback_entries=lcount, worst_per_plane=rows))
    (out / "antenna.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res["with_pdk_rules"]), json.dumps(rows, indent=1))
    return res


def drc(gds, out):
    top = top_of(gds)
    d = out / "drc"
    t = f"""snap internal
{head(gds, top)}select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
set total 0
set sc [cif scale out]
foreach {{reason boxes}} [drc listall why] {{
 puts "CHECKRULE [llength $boxes] $reason"
 incr total [llength $boxes]
 foreach b $boxes {{ puts "CHECKBOX [expr {{[lindex $b 0]*$sc}}] [expr {{[lindex $b 1]*$sc}}] [expr {{[lindex $b 2]*$sc}}] [expr {{[lindex $b 3]*$sc}}] $reason" }}
}}
puts "DRCTOTAL $total"
quit -noprompt
"""
    log = run_magic(t, "drc", d)
    res = dict(gds=str(gds), top=top, total=int(re.search(r"DRCTOTAL (\d+)", log)[1]),
               rules={why: int(n) for n, why in re.findall(r"(?m)^CHECKRULE (\d+) (.*)$", log)},
               boxes_um=[[round(float(a), 3), round(float(b), 3), round(float(c), 3), round(float(e), 3), why]
                         for a, b, c, e, why in re.findall(r"(?m)^CHECKBOX (\S+) (\S+) (\S+) (\S+) (.*)$", log)][:500])
    (out / "drc.json").write_text(json.dumps(res, indent=1) + "\n")
    print({k: v for k, v in res.items() if k != "boxes_um"})
    for b in res["boxes_um"][:40]:
        print("  ", b)
    return res


if __name__ == "__main__":
    step, gds, out = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    {"lvs": lambda: lvs(gds, out), "cap": lambda: cap(gds, out), "res": lambda: res(gds, out, sys.argv[4:]),
     "antenna": lambda: antenna(gds, out), "drc": lambda: drc(gds, out), "wire": lambda: wire(gds, out)}[step]()
