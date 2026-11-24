"""Validate the complete physical address/mode bank at transistor level and with all 1,024 digital drives."""
from collections import Counter
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import sys

from decoder import PORTS, gates_from, control
from source import BUILD, HERE, REPORT, read_source, save, sha
import decoder
import check

def main():
    out=BUILD/"mode_qualification";out.mkdir(exist_ok=True)
    check.BUILD=out
    ly,_=read_source(); cell=decoder.draw(ly)
    file=BUILD/"mode.gds";save(ly,cell,file)
    source=HERE.parent/"circuit/native_six.spice"
    gates=gates_from(source.read_text())
    control.ORDER=list(gates);control.PORTS=PORTS
    reference=control.reference(gates)
    # Old generated references used their instance IDs as node suffixes. Our
    # hierarchy qualifies W/H/B gates; avoid the '/' path separator in SPICE node names.
    reference=reference.replace("native_bank_enable/","bank_").replace("xor_chip_native_six/","mode_")
    reference=re.sub(r"(?m)^(bank_|mode_)","X"+r"\1",reference)
    clean=check.magic(file,cell.name,"magic",True)
    text=(out/"layout.spice").read_text()
    if not re.search(r"(?im)^\.subckt sx_flat ",text):
        body="\n".join(l for l in text.splitlines() if l.startswith(("X","+")))
        text=".subckt sx_flat "+" ".join(PORTS)+"\n"+body+"\n.ends sx_flat\n"
    layout=out/"native_mode.spice";layout.write_text(text)
    count=check.devices(text)
    if count!=check.devices(reference) or clean:raise ValueError((clean,count,check.devices(reference)))
    checks={}
    for name,ref in {"correct":reference,"short_two_row_strobes":reference.replace(" a1 "," a0 "),
                     "misconnect_mos_gate":reference.replace("bit_b","we0",1).replace(" bank_nbb "," bank_nba ",1)}.items():
        p=out/(name+".spice")
        ref=re.sub(r"(?m)^\.subckt ref .*?$",".subckt ref "+" ".join(PORTS),ref)
        p.write_text(ref); log=out/(name+".lvs.txt")
        check.run([check.NETGEN,"-batch","lvs",str(layout)+" sx_flat",str(p)+" ref",str(check.PDK/"libs.tech/netgen/sky130A_setup.tcl"),str(log)],name+".log")
        data=log.read_text()
        verdict="Final result: Circuits match uniquely." in data and "Property errors were found" not in data
        if verdict!=(name=="correct"):raise ValueError((name,data[-1200:]))
        if verdict:
            pairs=re.findall(r"(?m)^\s*(\w+)\s*\|\s*(\w+)\s*$",data.rsplit("Subcircuit pins:",1)[1].split("Cell pin lists are equivalent.",1)[0])
            if set(pairs)!={(p,p) for p in PORTS}:raise ValueError(pairs)
        checks[name]=verdict
    devices=[]
    for line in text.splitlines():
        if line.startswith("X"):
            _,d,g,s,b,model,*_=line.split()
            if model not in ("sky130_fd_pr__nfet_01v8","sky130_fd_pr__pfet_01v8_hvt"):raise ValueError(model)
            active=int(model.endswith("__nfet_01v8"))
            if b!=("vss" if active else "vdd"):raise ValueError((model,b))
            devices.append((d,g,s,active))
    logic=hashlib.sha256()
    for inputs in product((0,1), repeat=10):
        val={"vss":0,"vdd":1,**dict(zip(PORTS[:10],inputs))}
        while True:
            nh={}
            for d,g,s,on in devices:
                if val.get(g)!=on:continue
                for a,b in ((d,s),(s,d)):
                    if a in val:
                        if val.get(b,val[a])!=nh.get(b,val[a]) or nh.get(b,val[a])!=val[a]:raise ValueError(("Contention",a,b))
                        if b not in val:nh[b]=val[a]
            if not nh:break
            val.update(nh)
        a,b,w0,w1,w2,w3,bp,e1,e2,clamp=inputs
        target={l+str(i):int((a,b)==row and bool(w)) for l,row in (("z",(0,0)),("a",(1,0)),("b",(0,1))) for i,w in enumerate((w0,w1,w2,w3))}
        target["six"]=int(bp and e1 and e2 and not clamp); target["park"]=1-target["six"]
        if any(val.get(k)!=v for k,v in target.items()):raise ValueError((inputs,target,val))
        logic.update(bytes(inputs)+bytes(val[n] for n in sorted(target)))
    result={"candidate_schematic_sha256":sha(source),"gds_sha256":sha(file),"Magic_full_DRC":clean,
        "flat_LVS_checks":checks,"same_name_external_pin_matches":len(PORTS),"physical_transistors":count,
        "truth_table":{"inputs":10,"outputs":14,"cases_checked":1024,"failed":0,"bitstream_sha256":logic.hexdigest()},
        "pdklib_spice_sha256":sha(control.SPICE),"extracted_netlist_sha256":sha(layout)}
    (REPORT/"decoder.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":main()
