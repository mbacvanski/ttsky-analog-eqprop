"""Walk the authored six-edge transistor circuit and retain only independently documented layout dummies."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
SIX=HERE.parents[1]
sys.path.insert(0,str(SIX/"split_pair/layout"))
from chip_reference import M, legacy, v4_plan

TOP="native_edge_reference"

def generate(fault=None,schematic=None):
    circuit=(schematic or HERE.parent/"circuit/native_six.spice").read_text()
    frozen=gzip.decompress((SIX/"circuit/frozen_native.spice.gz").read_bytes()).decode()
    subs=M.subckts(circuit);root="xor_chip_native_six"
    pins=dict(M.TT_MAP,**legacy.V4_PINS)
    if set(pins)!=set(subs[root][0]):raise ValueError("Board pin contract differs")
    items=[];M.walk(subs,root,[pins[p] for p in subs[root][0]],{},"",items,M.deck_params(frozen))
    if fault:
        # Choose the exact addressed endpoint in the native resistor pair; preserve the cell count.
        hit=[(i,item) for i,item in enumerate(items) if item[1].startswith("XROW_A/XR1/") and item[1].endswith("XR0")]
        if len(hit)!=1:raise ValueError(hit)
        i,item=hit[0];typ,name,model,nodes,params=item
        nodes=list(nodes);nodes[0]="VGND";items[i]=typ,name,model,nodes,params
    dummies=[(spec.split()[0],spec.split()[1],num,scope) for spec,num,scope in M.CHIP_DUMMIES]
    old=Counter((c,l) for _,c,*_ in v4_plan.ALL_PLACE for l in legacy.CELL_DUMMIES.get(c,[]))
    dummies.extend((legacy.RX,f"L={l:g}",n,c) for (c,l),n in old.items())
    dummies.append(("sky130_fd_pr__res_xhigh_po_1p41","L=70.34",4,"two native rw_res copies, two grounded edges per array"))
    new=json.loads((HERE/"results/poly_cells.json").read_text())
    dummies.extend((legacy.RX,"L="+str(c["strip_length_um"]),(4 if c["name"]=="ne_help" else 2),c["name"]) for c in new)
    seen=set()
    lines=["* Independent expected transistor circuit from the electrical model; enabled words retain their original device geometry."]
    lines+=M.std_defs({i[2] for i in items if i[0]=="std"},seen)
    lines+=M.amp_defs(sorted({i[2] for i in items if i[0]=="cell"}),seen)
    lines+=[".subckt "+TOP+" "+" ".join(M.TT_PORTS),*[M.fmt(*i) for i in items]]
    j=0
    for model,dimension,n,comment in dummies:
        lines+=["* "+comment]
        for _ in range(n):lines.append(f"XDUMMY{j} VGND VGND VGND {model} {dimension}");j+=1
    lines+=[".ends "+TOP,""]
    result="\n".join(lines)
    receipt={"native_chip_sha256":hashlib.sha256(circuit.encode()).hexdigest(),"reference_sha256":hashlib.sha256(result.encode()).hexdigest(),
             "frozen_device_library_sha256":hashlib.sha256(frozen.encode()).hexdigest(),"explicit_physical_dummy_devices":dummies,
             "ports":M.TT_PORTS,"explicit_board_pin_map":pins,"instance_classes":dict(Counter(i[0] for i in items)),"blackboxes":[],"fault":fault}
    return result,receipt


if __name__=="__main__":
    for invert in (False,True):
        s,r=generate("wrong_A_mid" if invert else None)
        n="reference_bad" if invert else "reference"
        (HERE/"build"/(n+".spice")).write_text(s);(HERE/"build"/(n+".json")).write_text(json.dumps(r,indent=2)+"\n")
        print(n,r["reference_sha256"],r["instance_classes"])
