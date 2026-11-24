"""Generate the actual SKY130 entry resistor, two clock resistors and MIM for the physical RC trial."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
L = HERE.parent
WORK = L / "build/quiet_rc_cells"
PDK = Path(os.environ.get("SKY130A", Path.home()/".ciel/sky130A"))
MAGIC = Path(os.environ.get("MAGIC", str(Path.home()/".local/bin/magic-8.3.685")))
SOURCE = "521b0f942a8a8dfc408ef1165621026c4febcbdd5e4f9f8b9aa09725a834dd91"
RES = "sky130_fd_pr__res_xhigh_po_0p35"
CAP = "sky130_fd_pr__cap_mim_m3_1"
LEAVES = {
    "ne_rc_entry": (RES, "w .35 l 6.90 nx 1 m 1 dummy 0 guard 0 doports 1 snake 0"),
    "ne_rc_rail": (RES, "w .35 l 69.90 nx 1 m 1 dummy 0 guard 0 doports 1 snake 0"),
    "ne_rc_mim": (CAP, "w 15.7 l 15.7 nx 1 ny 1 dummy 0 doports 1"),
}


def magic(tcl, cwd, log):
    path = cwd / (log + ".tcl")
    path.write_text(tcl)
    with (WORK / (log + ".log")).open("wb") as fd:
        subprocess.run([str(MAGIC), "-dnull", "-noconsole", "-rcfile", str(PDK / "libs.tech/magic/sky130A.magicrc"),
                        str(path)], cwd=cwd, stdout=fd, stderr=subprocess.STDOUT,
                       env={**os.environ, "PDK_ROOT": str(PDK.parent)}, check=True)


def generate():
    WORK.mkdir(parents=True, exist_ok=True)
    source = gzip.decompress((L.parent / "verification/evidence/filtered_complete/source.spice.gz").read_bytes())
    if hashlib.sha256(source).hexdigest() != SOURCE:
        raise ValueError("The filtered schematic differs from the registered four-device design")
    (WORK / "circuit.spice").write_bytes(source)
    lines = ["random seed 20261118", "snap internal", "load rc_generation -force"]
    for i, (name, (model, args)) in enumerate(LEAVES.items()):
        lines += [f"box {100*i}um 0um {100*i}um 0um", f"magic::gencell sky130::{model} I_{name} {args}",
                  f"select cell I_{name}", "set cname [instance list celldef]", f"cellname rename $cname {name}"]
    lines += ["writeall force"]
    for name in LEAVES:
        lines += [f"load {name}", "select top cell", f"gds write {WORK / (name + '.gds')}",
                  "drc euclidean on", "drc style drc(full)", "drc check", "drc catchup",
                  f'puts "RC_LEAF_DRC {name} [drc list count total] [drc listall why]"',
                  "extract all", "ext2spice lvs", "ext2spice cthresh 0",
                  f"ext2spice -o {WORK / (name + '.spice')} {name}"]
    lines += ["quit -noprompt"]
    with tempfile.TemporaryDirectory(dir=WORK) as scratch:
        magic("\n".join(lines) + "\n", Path(scratch), "cells")
    # A solitary foundry high-R strip has a 0.75-µm URPM indicator. The full-die
    # deck requires at least 1.27 µm. Enlarge only this nonconducting mask.
    import klayout.db as db
    from quiet_route import save
    for name in LEAVES:
        layout = db.Layout()
        path = WORK / (name + ".gds")
        layout.read(str(path))
        cell = layout.top_cell()
        if LEAVES[name][0] == RES:
            mark = layout.layer(79, 20)
            rect, = [s.bbox() for s in cell.shapes(mark).each()]
            if rect.width() != 750:
                raise ValueError(("Changed high-R indicator", name, rect))
            cell.shapes(mark).insert(db.Box(rect.left-295, rect.bottom, rect.right+295, rect.top))
        save(layout, cell, path)
        with tempfile.TemporaryDirectory(dir=WORK) as scratch:
            check = f"""gds read {path}
load {name}
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
box -100um -100um 100um 100um
set num 0
foreach {{reason boxes}} [drc listall why] {{
    puts "RC_RULE $reason $boxes"
    incr num [llength $boxes]
}}
puts "VERIFIED_DRC $num"
extract do local
extract all
ext2spice lvs
ext2spice cthresh 0
ext2spice -o {WORK/(name+'.spice')} {name}
quit -noprompt
"""
            magic(check, Path(scratch), name)
        log = (WORK/(name+".log")).read_text()
        if not re.search(r"(?m)^VERIFIED_DRC 0\b", log):
            # The production placement combines the two long strips in a legal 0.83 µm pitch array.
            # An isolated unit can legitimately trigger the calculated-poly-indicator rule.
            errors = [line for line in log.splitlines() if line.startswith("RC_RULE ")]
            if LEAVES[name][0] != RES or len(errors) != 1 or "(rpm.1)" not in errors[0]:
                raise ValueError((name, "Failed isolated DRC", errors))
    receipt = {}
    for name, (model, _) in LEAVES.items():
        text = re.sub(r"\n\+\s*", " ", (WORK / (name + ".spice")).read_text())
        card, = [line for line in text.splitlines() if line.startswith("X")]
        if model not in card:
            raise ValueError((name, card))
        receipt[name] = dict(card=card, caps=[x for x in text.splitlines() if re.match(r"^C\d+\s",x)],
                             gds_sha256=hashlib.sha256((WORK/(name+".gds")).read_bytes()).hexdigest(),
                             spice_sha256=hashlib.sha256((WORK/(name+".spice")).read_bytes()).hexdigest())
    (WORK / "isolated.json").write_text(json.dumps(receipt, indent=2) + "\n")
    for name, r in receipt.items():
        print(name, r["card"], r["caps"])
    resistor_bank()


def resistor_bank():
    """Put all three working strips in a shared, solid URPM mask with real end contacts."""
    import klayout.db as db
    from quiet_route import save

    layout = db.Layout()
    layout.dbu = .001
    bank = layout.create_cell("ne_rc_high_poly")
    originals = {}
    contacts = {}
    for name in ("ne_rc_entry", "ne_rc_rail"):
        temp = db.Layout()
        temp.read(str(WORK / (name + ".gds")))
        cell = layout.create_cell(name)
        cell.copy_tree(temp.top_cell())
        port_layer = layout.layer(67, 5)
        ports = cell.shapes(port_layer)
        contacts[name] = {s.text.string: db.Point(s.text.x, s.text.y) for s in ports.each() if s.is_text()}
        if set(contacts[name]) != {"R1", "R2"}:
            raise ValueError((name, "Missing precision resistor contacts"))
        ports.clear()
        originals[name] = cell
    # The 6.9-µm strip shares the top access level of the two 69.9-µm strips.
    rows = [
        ("weak_src", "weak", "ne_rc_rail", 0, 0),
        ("weak_b_src", "weak_b", "ne_rc_rail", 830, 0),
        ("res_sel", "res_filtered", "ne_rc_entry", 1660, 31500),
    ]
    pins = {}
    for p, q, master, x, y in rows:
        transform = db.Trans(x, y)
        bank.insert(db.CellInstArray(originals[master].cell_index(), transform))
        for key, name in (("R1", p), ("R2", q)):
            point = transform * contacts[master][key]
            pins[name] = (point.x, point.y)
            bank.shapes(layout.layer(68, 5)).insert(db.Text(name, point.x, point.y))
    bank.flatten(-1, False)
    marker = layout.layer(79, 20)
    # Merge the neighboring implant pieces into a single uninterrupted indicator.
    shape = db.Region(bank.shapes(marker)).merged()
    bank.shapes(marker).clear()
    bank.shapes(marker).insert(shape)
    active = db.Region(bank.shapes(layout.layer(66, 13))).merged()
    if active.count() != 3:
        raise ValueError("The solid indicator merged separate resistor bodies")
    out = WORK / "ne_rc_high_poly.gds"
    save(layout, bank, out)
    with tempfile.TemporaryDirectory(dir=WORK) as scratch:
        script = f"""snap internal
gds read {out}
load ne_rc_high_poly
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
box -100um -100um 100um 100um
set total 0
foreach {{reason boxes}} [drc listall why] {{puts "RC_BANK_RULE $reason $boxes"; incr total [llength $boxes]}}
puts "RC_BANK_DRC $total"
extract do local
extract all
ext2spice lvs
ext2spice cthresh 0
ext2spice -o {WORK/'ne_rc_high_poly.spice'} ne_rc_high_poly
quit -noprompt
"""
        magic(script, Path(scratch), "bank")
    log = (WORK / "bank.log").read_text()
    if "RC_BANK_DRC 0" not in log:
        raise ValueError([x for x in log.splitlines() if x.startswith("RC_BANK")])
    lines = (WORK / "ne_rc_high_poly.spice").read_text().splitlines()
    devices = [line.split() for line in lines if line.startswith("X")]
    by_ports = {tuple(sorted(c[1:3])): float(next(z[2:] for z in c if z.startswith("l="))) for c in devices}
    expected = {tuple(sorted((a,b))): (6.9 if m=="ne_rc_entry" else 69.9) for a,b,m,*_ in rows}
    if by_ports != expected or any(c[3:5] != ["VSUBS", RES] for c in devices):
        raise ValueError(("Unintended extracted bank devices", devices))
    data = dict(gds_sha256=hashlib.sha256(out.read_bytes()).hexdigest(), pin_m1_nm=pins, box_nm=bank.bbox().to_s(),
                physical_devices=devices, full_magic_DRC=0)
    (WORK / "bank.json").write_text(json.dumps(data, indent=2)+"\n")
    print(data["gds_sha256"], data["box_nm"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["generate"])
    p.parse_args()
    generate()
