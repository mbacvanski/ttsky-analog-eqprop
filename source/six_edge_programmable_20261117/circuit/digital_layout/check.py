"""Check the actual decoder stream with Magic, SKY130A transistor LVS and TT rule decks."""
from collections import Counter
import argparse
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BUILD=HERE/"build"
PDK=Path(os.environ.get("PDK_ROOT",Path.home()/".ciel"))/"sky130A"
MAGIC=os.environ.get("MAGIC",str(Path.home()/".local/bin/magic-8.3.685"))
NETGEN=os.environ.get("NETGEN",str(Path.home()/".local/bin/netgen-1.5.325"))
TOP="sx_input_control"


def run(command,log):
    with (BUILD/log).open("w") as stream:
        subprocess.run(command,cwd=BUILD,stdout=stream,stderr=subprocess.STDOUT,
                       env={**os.environ,"PDK_ROOT":str(PDK.parent)},check=True,timeout=180)


def magic(gds,top,output,extract):
    script=BUILD/(output+".tcl")
    tcl=f"""gds read {gds}
load {top}
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
set total 0
foreach {{rule boxes}} [drc listall why] {{
  puts "RULE [llength $boxes] $rule $boxes"
  incr total [llength $boxes]
}}
puts "DRCTOTAL $total"
"""
    if extract:
        tcl+="""flatten sx_flat
load sx_flat
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o layout.spice
"""
    script.write_text(tcl+"quit -noprompt\n")
    log=output+".log"
    run([MAGIC,"-dnull","-noconsole","-rcfile",str(PDK/"libs.tech/magic/sky130A.magicrc"),str(script)],log)
    body=(BUILD/log).read_text()
    rules=re.findall(r"(?m)^RULE .*",body)
    print(output,rules,flush=True)
    return int(re.search(r"(?m)^DRCTOTAL (\d+)$",body)[1])


def devices(text):
    return Counter(re.findall(r"(?m)^X[^\n]*?(sky130_fd_pr__\S+)",text))


def lvs(reference,extracted,ports):
    if not re.search(r"(?im)^\.subckt sx_flat ",extracted):
        extracted="\n".join(line for line in extracted.splitlines() if line.startswith(("X","+")))
        extracted=".subckt sx_flat "+" ".join(ports)+"\n"+extracted+"\n.ends sx_flat\n"
    path=BUILD/"flat.spice"
    path.write_text(extracted)
    counts=devices(extracted)
    assert counts==devices(reference),(counts,devices(reference))
    edits={"correct":reference,
           "short_weights_selects":re.sub(r"\bsel1\b","sel0",reference),
           "wrong_gate_width":reference.replace("w=650000u","w=850000u",1)}
    checks={}
    for name,body in edits.items():
        if name!="correct":
            assert body!=reference
        ref=BUILD/(name+".spice")
        # Keep the reference's original external port list in the shorted control.
        body=body.replace(next(s for s in body.splitlines() if s.startswith(".subckt ")),
                          ".subckt ref "+" ".join(ports))
        ref.write_text(body)
        report=BUILD/(name+".lvs.txt")
        run([NETGEN,"-batch","lvs",str(path)+" sx_flat",str(ref)+" ref",
             str(PDK/"libs.tech/netgen/sky130A_setup.tcl"),str(report)],name+".log")
        out=report.read_text()
        clean="Final result: Circuits match uniquely." in out and "Property errors were found" not in out
        verdict=out[out.rfind("Final result:"):].strip()
        print(name,verdict[:120],flush=True)
        if clean!=(name=="correct"):
            raise RuntimeError(f"{name}: {report}")
        checks[name]={"unique_property_clean_match":clean,"final_result":verdict}
        if clean:
            port_table=out.rsplit("Subcircuit pins:",1)[1].split("Cell pin lists are equivalent.",1)[0]
            pairs=re.findall(r"(?m)^\s*(\w+)\s*\|\s*(\w+)\s*$",port_table)
            assert sorted(pairs)==[(p,p) for p in sorted(ports)],(pairs,ports)
            checks[name]["same_name_external_port_pairs"]=len(pairs)
    return counts,checks


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def truth_table(extracted):
    """Drive the 11 physical primary inputs; resolve ideal switches from flat GDS extraction."""
    devices=[]
    for line in extracted.splitlines():
        if line.startswith("X"):
            _,d,g,s,b,model,*_=line.split()
            is_nmos=model=="sky130_fd_pr__nfet_01v8"
            assert is_nmos or model=="sky130_fd_pr__pfet_01v8_hvt"
            assert b==("vss" if is_nmos else "vdd"),(line,b)
            devices.append((d,g,s,is_nmos))
    inputs="a b addr0 addr1 write rs wp bp ext_en1 ext_en2 ref_reset".split()
    observed=hashlib.sha256()
    for bits in product((0,1),repeat=len(inputs)):
        pins=dict(zip(inputs,bits))
        values={**pins,"vss":0,"vdd":1}
        while True:
            additions={}
            for left,gate,right,active in devices:
                if values.get(gate)!=active:
                    continue
                for known,other in ((left,right),(right,left)):
                    if known in values:
                        expected=values[known]
                        assert values.get(other,expected)==additions.get(other,expected)==expected,("short",bits,gate,other)
                        if other not in values:
                            additions[other]=expected
            if not additions:
                break
            values.update(additions)
        a,b,a0,a1,wr,rs,wp,bp,ext1,ext2,rz=bits
        expected={f"sel{i}":i==a0+2*a1 for i in range(4)}
        expected["inwrite"]=wr and not (rs or wp)
        for letter,bit in (("a",a),("b",b)):
            expected["s"+letter]=bp and bit
            expected["ns"+letter]=not (bp and bit)
        for hidden,ext in ((1,ext1),(2,ext2)):
            expected[f"avg{hidden}"]=bp and not(ext or rz)
            expected[f"navg{hidden}"]=not expected[f"avg{hidden}"]
            expected[f"use{hidden}"]=bp or ext
        assert len(expected)==15 and all(values.get(n)==v for n,v in expected.items()),(bits,expected,values)
        observed.update(bytes(bits)+bytes(values[n] for n in sorted(expected)))
    return {"method":"Static switch connectivity of Magic-extracted FETs and physical bulk pins",
            "exhaustive_primary_input_combinations":2**len(inputs),"outputs_per_combination":15,
            "failed_outputs":0,"detected_rail_contentions":0,"input_output_bitstream_sha256":observed.hexdigest()}


def main(with_klayout):
    BUILD.mkdir(exist_ok=True)
    gds=HERE/(TOP+".gds")
    geometry=json.loads((HERE/"geometry.json").read_text())
    assert digest(gds)==geometry["gds_sha256"]
    errors=magic(gds,TOP,"magic",True)
    assert errors==0,BUILD/"magic.log"
    access_errors=magic(BUILD/"access.gds","sx_access_coupon","access",False)
    assert access_errors==0,BUILD/"access.log"
    ref=(HERE/"reference.spice").read_text()
    ports=next(s for s in ref.splitlines() if s.startswith(".subckt ")).split()[2:]
    extracted=(BUILD/"layout.spice").read_text()
    counts,checks=lvs(ref,extracted,ports)
    data={"gds_sha256":digest(gds),"reference_sha256":digest(HERE/"reference.spice"),
          "magic_full_drc":errors,"all_28_simultaneous_M2_to_M3_cuts_magic_full_drc":access_errors,
          "physical_transistors":counts,"lvs":checks,"boolean_logic":truth_table(extracted)}
    if with_klayout:
        sys.path.insert(0,str(ROOT.parent/"feasibility_20261107/amp_layout/scripts"))
        import run_klayout_drc as deck
        deck.BUILD=BUILD
        deck.DECKS=Path(os.environ.get("TT_DRC_DIR",Path.home()/".local/opt/tt_proof/precheck/tt-support-tools/precheck/tech-files"))
        assert all(digest(deck.DECKS/name)==value for name,value in deck.PINNED.items())
        data["klayout"]=deck.run(gds,TOP)
        data["pinned_decks"]=deck.PINNED
        print("klayout",{key:value["ok"] for key,value in data["klayout"].items()},flush=True)
        assert all(value["ok"] for value in data["klayout"].values())
        (HERE/"verification.json").write_text(json.dumps(data,indent=2)+"\n")
        (HERE/"extracted.spice").write_bytes((BUILD/"flat.spice").read_bytes())


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--magic-only",action="store_true")
    main(not parser.parse_args().magic_only)
