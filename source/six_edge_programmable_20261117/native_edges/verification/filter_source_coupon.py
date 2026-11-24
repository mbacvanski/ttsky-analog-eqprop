"""Check the real passive and decoder terminals at the proposed short source paths."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import klayout.db as db

from filter_placement_survey import EVIDENCE, RELEASE, rc_layout, quiet_route, res_select
from rc_passives import MAGIC, PDK
from route_split import circuit


def read(path):
    return json.loads(path.read_bytes())


def write(path, obj):
    path.write_text(json.dumps(obj, indent=1) + "\n")


def check_drc(folder):
    gds=folder/"source_coupon.gds"
    tcl=folder/"placement_drc.tcl"
    tcl.write_text(f"""gds read {gds}
load tt_um_mbacvanski_native_edges_place
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
box -2um -2um 337um 228um
set total 0
foreach {{text boxes}} [drc listall why] {{
    puts "COUPON_RULE [llength $boxes] $text | $boxes"
    incr total [llength $boxes]
}}
puts "COUPON_DRC $total"
quit -noprompt
""")
    command=[str(MAGIC),"-dnull","-noconsole","-rcfile",str(PDK/"libs.tech/magic/sky130A.magicrc"), str(tcl)]
    result=subprocess.run(command, cwd=folder, capture_output=True, check=True,
                          env={**os.environ,"PDK_ROOT":str(PDK.parent)})
    output=(result.stdout+result.stderr).decode()
    (folder/"placement_drc.log").write_text(output)
    total=int(re.search(r"(?m)^COUPON_DRC (\d+)$", output).group(1))
    rows=[dict(rule=s,count=int(n),boxes=b) for n,s,b in re.findall(r"(?m)^COUPON_RULE (\d+) (.*?) \| (.*?)$",output)]
    assert sum(row["count"] for row in rows)==total
    return dict(total_markers=total,rules=rows,magic_sha256=hashlib.sha256(MAGIC.read_bytes()).hexdigest(),
                scope="Full Euclidean Magic on the unconnected placement with all six complete resistor access stacks.")


def prepare(folder, run_drc, write_receipt=True):
    folder.mkdir(parents=True, exist_ok=True)
    survey_path = EVIDENCE / "placement_survey.json"
    survey = read(survey_path)
    layout, top = quiet_route.physical_parent()
    actual, _ = rc_layout.remove_launches(layout, top, quiet_route.points(layout, top, include_analog=True))
    proof = read(RELEASE / "manifest.json")
    original = gzip.decompress((RELEASE / "die.gds.gz").read_bytes())
    assert hashlib.sha256(original).hexdigest() == proof["gds_sha256"] == survey["existing_filter_gds"]
    src = db.Layout()
    src.read_bytes(original)
    pr = read(RELEASE / "placement.json")["physical"]
    target_bank = survey["geometry"]["intact_pad_priority"]["M1_M4"]
    target_logic = survey["relocated_original_two_gate_cell"]["intact_pad_priority"]["actual_upper_conductor_polygons"]
    logic = layout.cell(res_select.LOGIC)
    old, = [i for i in top.each_inst() if i.cell_index == logic.cell_index()]
    old.trans = db.Trans.from_s(target_logic["transform"])
    pins = quiet_route.labels(layout, logic, old.dtrans)
    output = []
    for net, tag, metal, x, y in actual:
        if tag.startswith("SELECT:"):
            [(metal, x, y)] = pins[tag.split(":")[1]]
        output.append([net, tag, metal, x, y])
    write_ports = read(RELEASE / "resistor_bank.json")["pin_m1_nm"]
    for role, transform in (("R", target_bank["transform"]), ("C", pr["C"]["transform"])):
        name = pr[role]["cell"]
        component = layout.create_cell(name)
        component.copy_tree(src.cell(name))
        where = db.Trans.from_s(transform)
        top.insert(db.CellInstArray(component.cell_index(), where))
        if role == "C":
            for net, pad in (("res_filtered", "C1"), ("vss", "C2")):
                p = pr[role]["pins_nm"][net]
                output.append([net, "C:"+pad, "m4", p[0]/1000, p[1]/1000])
            continue
        for net, xy in write_ports.items():
            q = where*db.Point(*xy)
            assert [round(q.x/1000,3),round(q.y/1000,3)] == target_bank["contact_um"][net]
            for layer, h in zip(("m1","v1","m2","v2","m3","v3","m4"),(170,75,190,100,205,100,205),strict=True):
                top.shapes(layout.layer(*quiet_route.METALS[layer])).insert(db.Box(q,q).enlarged(h))
            output.append([net,"R:"+net,"m1",q.x/1000,q.y/1000])
    nets, shorts, _ = circuit(layout, top, output)
    if shorts:
        raise ValueError(("Nonlocal connection at moved logic/passives", shorts))
    joins = {k: len(v)-1 for k,v in nets.items() if len(v)>1}
    intended = {"res_sel","res_filtered","weak","weak_b","weak_src","weak_b_src","vss","vdd","six"}
    if set(joins)-intended:
        raise ValueError(("An unrelated macro or pin lost continuity", joins))
    gds = folder/"source_coupon.gds"
    quiet_route.save(layout, top, gds)
    write(folder/"source_coupon_targets.json", output)
    write(folder/"source_coupon_joins.json", joins)
    record=dict(parent_gds=quiet_route.GDS, transplanted_components_from_gds=proof["gds_sha256"],
                same_logical_circuit=proof["source_circuit_sha256"],
                placement_screen_sha256=hashlib.sha256(survey_path.read_bytes()).hexdigest(),
                unrouted_gds_sha256=hashlib.sha256(gds.read_bytes()).hexdigest(),
                registered_terminal_count=len(output), unintentionally_shorted_named_nets=shorts,
                expected_remaining_joins=joins,
                original_63_macros_with_one_existing_decoder_moved=sum(1 for _ in top.each_inst())-2,
                copied_two_passive_macros=[pr[r]["cell"] for r in ("R","C")],
                scope="Real unconnected placement with six M1 to M4 landings. Substrate and implant geometry come from the previously checked 3134 mask. Global routing, device extraction and transient tests are separate qualifications.")
    assert record["original_63_macros_with_one_existing_decoder_moved"]==63
    if run_drc:
        record["placement_DRC"]=check_drc(folder)
    if write_receipt:
        write(EVIDENCE/"adjacent_source_placement.json", record)
    print(json.dumps(record, indent=1))


if __name__=="__main__":
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument("scratch_folder", type=Path)
    arg.add_argument("--magic", action="store_true")
    arg.add_argument("--staging-only", action="store_true",
                     help="Reconstruct geometry without replacing the independent placement receipt")
    args=arg.parse_args()
    prepare(args.scratch_folder.resolve(), args.magic, not args.staging_only)
