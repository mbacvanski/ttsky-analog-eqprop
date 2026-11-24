"""Measure full-die rule violations, flatten the real transistors, and compare independent SPICE and a broken midpoint."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
BUILD=HERE/"build"
sys.path.insert(0,str(HERE.parents[1]/"layout"))
from baseline import MAGIC,NETGEN,PDK,sha

def check(source,control=False,schematic=None):
    path=BUILD/(source+".gds");out=BUILD/(source+"_checks");out.mkdir(exist_ok=True)
    top="tt_um_mbacvanski_native_edges_place"
    tcl=out/"flat.tcl"
    tcl.write_text(f"""snap internal
gds read {path}
load {top}
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
set total 0
foreach {{reason boxes}} [drc listall why] {{
 puts "CHECKRULE [llength $boxes] $reason"
 puts "BOXES $boxes"
 incr total [llength $boxes]
}}
puts "DRCTOTAL $total"
flatten native_flat
load native_flat
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o {out/'flat.spice'}
quit -noprompt
""")
    env={**os.environ,"PDK_ROOT":str(PDK.parent)}
    with (out/"magic.log").open("w") as log:
        subprocess.run([MAGIC,"-dnull","-noconsole","-rcfile",str(PDK/"libs.tech/magic/sky130A.magicrc"),str(tcl)],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    body=(out/"magic.log").read_text()
    drc={"total":int(re.search("DRCTOTAL (\\d+)",body)[1]),"rules":{why:int(num) for num,why in re.findall(r"(?m)^CHECKRULE (\d+) (.*)$",body)}}
    network=(out/"flat.spice").read_text();flat=re.sub(r"\n\+\s*"," ",network)
    ports=re.search(r"(?m)^\.subckt native_flat (.*)$",flat)[1].split()
    devices=Counter(re.findall(r"(?m)^X[^\n]*? (sky130_fd_pr__\S+)",flat))
    comparisons={}
    for rx in ("reference","reference_bad") if control else ("reference",):
        ref=BUILD/(rx+".spice")
        if schematic:
            from reference import generate
            reference, provenance=generate(None if rx=="reference" else "wrong_A_mid",schematic)
            ref=out/(rx+".spice");ref.write_text(reference)
            (out/(rx+"_model.json")).write_text(json.dumps(provenance,indent=2)+"\n")
        txt=out/(rx+"_lvs.txt")
        with (out/(rx+"_netgen.log")).open("w") as log:
            subprocess.run([NETGEN,"-batch","lvs",str(out/"flat.spice")+" native_flat",str(ref)+" native_edge_reference",
                       str(PDK/"libs.tech/netgen/sky130A_setup.tcl"),str(txt)],cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        report=txt.read_text()
        verdict=re.search(r"(?m)^Final result: (.*)$",report)
        pairs=False
        if verdict and "match uniquely" in verdict[1]:
            pin_table=report.rsplit("Subcircuit pins:",1)[-1].split("Cell pin lists are equivalent.",1)[0]
            pins=re.findall(r"(?m)^\s*([A-Za-z0-9_\[\]]+)\s*\|\s*([A-Za-z0-9_\[\]]+)\s*$",pin_table)
            pairs=set(pins)=={(p,p) for p in ports}
        comparisons[rx]={"result":verdict[1] if verdict else "Comparison did not finish","same_name_port_pairs":pairs,"property_errors":"Property errors were found" in report,
                          "expected_netlist_sha256":sha(ref),"comparison_sha256":sha(txt)}
    record={"gds_sha256":sha(path),"Magic_full_DRC":drc,"flat_extracted_sha256":sha(out/"flat.spice"),"physical_devices":devices,
            "external_ports":ports,"comparisons":comparisons}
    (out/"receipt.json").write_text(json.dumps(record,indent=2)+"\n")
    print(json.dumps(record,indent=2),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("stream");p.add_argument("--negative",action="store_true")
    p.add_argument("--schematic",type=Path)
    args=p.parse_args();check(args.stream,args.negative,args.schematic)
