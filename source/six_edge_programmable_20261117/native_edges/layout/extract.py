"""Collect a physically pin-matched, MIM-accounted, full-die capacitance netlist for the native board tests."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import os
import subprocess
import sys

HERE=Path(__file__).resolve().parent
SIX=HERE.parents[1]
sys.path.insert(0,str(SIX/"drawn"))
# account_flat imports drawn.extract by its module name.
import account_flat
from ports import board_names
from reduce_capacitance import reduce

def digest(data):
    return hashlib.sha256(data).hexdigest()

def additional_mim(path, table, devices, expected_instances=1):
    """Read the isolated physical plate component for a new MIM size present on this die."""
    physical=path.read_bytes()
    lines=re.sub(r"\n\+\s*"," ",physical.decode()).splitlines()
    card,=[line.split() for line in lines if line.startswith("X")]
    if card[3]!=account_flat.MIM or len(card)!=6:
        raise ValueError("The additional unit must contain one stand-alone two-terminal foundry MIM")
    parameters=dict(s.split("=") for s in card[4:])
    if set(parameters)!={"w","l"}:
        raise ValueError("Unknown isolated MIM dimensions")
    w,l=map(float,(parameters["w"],parameters["l"]))
    key=str(min(w,l))
    matches=sum(n for (_,model,params),n in devices.items()
                if model==account_flat.MIM and {p.lower() for p in params}=={p.lower() for p in card[4:]})
    if expected_instances < 1 or key in table or matches!=expected_instances:
        raise ValueError(("Unexpected number of physical devices with this additional MIM size",
                          key, matches, expected_instances))
    body=[line.split() for line in lines if re.match(r"^C\d+\s",line)]
    unit,=[c for c in body if set(c[1:3])==set(card[1:3])]
    value=account_flat.fraction_ff(unit[3])
    if not math.isfinite(value) or value<=0:
        raise ValueError("Isolated inter-plate parasitic must be positive")
    table[key]=dict(w=w,l=l,plate_fF=value)
    return dict(unit_spice_sha256=digest(physical),foundry_device=card,capacitance_records=body,
                additional_unit_sizes={key:table[key]},instances_on_die=matches)


def run(source,archive,schematic=None,unit_mim=None,unit_mim_count=1):
    build=HERE/"build"; run=build/(source+"_checks")
    receipt=json.loads((run/"receipt.json").read_text())
    check=receipt["comparisons"]["reference"]
    if check["result"]!="Circuits match uniquely." or check["property_errors"] or not check["same_name_port_pairs"]:
        raise ValueError("The full named-pin LVS gate must pass")
    folder=build/(source+"_pex");folder.mkdir(exist_ok=True)
    shutil.copyfile(run/"native_flat.ext",folder/"native_flat.ext")
    script=folder/"extract.tcl"
    script.write_text("ext2spice lvs\next2spice hierarchy off\next2spice subcircuit top on\next2spice cthresh 0\next2spice -o raw.spice native_flat\nquit -noprompt\n")
    with (folder/"magic.log").open("w") as log:
        subprocess.run([account_flat.MAGIC,"-dnull","-noconsole","-rcfile",str(account_flat.MAGICRC),str(script)],cwd=folder,env={**os.environ,"PDK_ROOT":str(account_flat.MAGICRC.parents[3])},stdout=log,stderr=subprocess.STDOUT,check=True)
    path=folder/"raw.spice";ports,devices,measured=account_flat.parse_spice(path)
    p0,d0,_=account_flat.parse_spice(run/"flat.spice")
    if ports!=p0 or d0!=devices:raise ValueError("Raw physical device or port list changed")
    aliases=board_names(ports)
    expected,names,ground=account_flat.ext_caps(folder/"native_flat.ext")
    accuracy=account_flat.check_extraction(expected,names,measured)
    if accuracy["pairs_over_0p012fF"]:raise ValueError(accuracy)
    if digest(account_flat.PLATE.read_bytes())!="44a4396119c04befc88755c3aa7f89a847c3d5f0ca3963380bc78dc0f4d24c98":raise ValueError("MIM reference unit changed")
    plates=json.loads(account_flat.PLATE.read_text())
    if not unit_mim and unit_mim_count!=1:
        raise ValueError("A physical isolated MIM export is required to check its specified instance count")
    new_unit=additional_mim(unit_mim,plates,devices,unit_mim_count) if unit_mim else None
    caps,mims=account_flat.apply_plate(plates,devices,measured)
    mapping={p:"pin_"+str(i) for i,p in enumerate(ports)};mapping["0"]="0"
    def node(n):
        if n not in mapping:mapping[n]="n_"+str(len(mapping)-len(ports))
        return mapping[n]
    lines=[".subckt sx_drawn "+" ".join(node(n) for n in ports)]
    for l in re.sub(r"\n\+\s*"," ",path.read_text()).splitlines():
        if l.startswith("X"):
            f=l.split();i=next(i for i,v in enumerate(f) if v.startswith("sky130_fd_pr__"))
            lines.append(" ".join([f[0],*[node(n) for n in f[1:i]],*f[i:]]))
    for i,((a,b),v) in enumerate(sorted(caps.items())):
        if v>0:lines.append(f"Cpar{i} {node(a)} {node(b)} {v:.15g}f")
    lines.append(".ends sx_drawn")
    full="\n".join(lines)+"\n";inert={f"ua[{i}]" for i in range(3,8)}
    reduced,audit=reduce(full,[mapping[p] for p in sorted(inert)])
    electrical=(schematic or HERE.parent/"circuit/native_six.spice").read_text()
    provenance=run/"reference_model.json"
    if provenance.is_file() and json.loads(provenance.read_text())["native_chip_sha256"]!=digest(electrical.encode()):raise ValueError("LVS compared a different circuit")
    header=next(l for l in electrical.splitlines() if l.startswith(".subckt xor_chip_native_six "))
    pins=header.split()[2:header.split().index("CORE_MATCH=1")]
    if set(aliases[p] for p in ports if p not in inert)!=set(pins):raise ValueError("Mismatch between external board and applied deck")
    board="\n".join([reduced,header,"XFLAT "+" ".join(aliases[p] for p in ports if p not in inert)+" sx_drawn",".ends xor_chip_native_six",""])
    (folder/"native_six_pex.spice").write_text(board)
    (folder/"flat_parasitics.spice").write_text(full)
    (folder/"nodes.json.gz").write_bytes(gzip.compress(json.dumps(mapping,sort_keys=True).encode(),mtime=0))
    result={"scope":"Complete named-pin LVS-matched die with flat Magic capacitance and PDK MIM overlap accounting; interconnect resistance is excluded.",
        "gds_sha256":receipt["gds_sha256"],"source_circuit_sha256":digest(electrical.encode()),"Magic_full_DRC":receipt["Magic_full_DRC"],
        "raw_flat_device_count":sum(devices.values()),"reduced_LVS_node_count":int(re.findall(r"Number of nets:\s*(\d+)\s*\|Number of nets:",(run/"reference_lvs.txt").read_text())[-1]),"actual_named_physical_terminals":ports,
        "same_name_LVS_pin_check":True,"extraction_vs_ext":accuracy,"physical_board_pin_mapping":aliases,"unconnected_analog_ports_quasistatically_eliminated":sorted(inert),
        "floating_elimination":audit,"MIM_unit_table_sha256":digest(account_flat.PLATE.read_bytes()),"MIM_accounting":mims,
        "modelled_interconnect":"substrate and coupling capacitance; ideal conductors","ext_sha256":digest((folder/"native_flat.ext").read_bytes()),
        "raw_spice_sha256":digest(path.read_bytes()),"whole_flat_sha256":digest(full.encode()),"board_spice_sha256":digest(board.encode()),"LVS":receipt["comparisons"]}
    if new_unit:
        result["additional_isolated_MIM"]=new_unit
    (folder/"manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    if archive:
        published=HERE/"results"/archive;published.mkdir(exist_ok=True)
        for n in ("native_six_pex.spice","flat_parasitics.spice","native_flat.ext"):
            (published/(n+".gz")).write_bytes(gzip.compress((folder/n).read_bytes(),mtime=0))
        for n in ("manifest.json","nodes.json.gz"):shutil.copyfile(folder/n,published/n)
        (published/"die.gds.gz").write_bytes(gzip.compress((build/(source+".gds")).read_bytes(),mtime=0))
        shutil.copyfile(run/"receipt.json",published/"LVS.json")
    print(result["gds_sha256"],result["board_spice_sha256"],audit,accuracy["maximum_absolute_error_fF"],flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("source");p.add_argument("--archive");p.add_argument("--schematic",type=Path)
    p.add_argument("--unit-mim",type=Path,help="Measured isolated cell export for an additional MIM geometry")
    p.add_argument("--unit-mim-count",type=int,default=1,help="Exact number of physically extracted instances of that single additional MIM size")
    a=p.parse_args();run(a.source,a.archive,a.schematic,a.unit_mim,a.unit_mim_count)
