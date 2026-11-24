"""Draw the pin-aligned proper-off return and the six native threshold-selector FETs per hidden neuron."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from resistors import HERE, V4, magic_util, normalize_stream
from cell_nrn import mid
from lib import Cell, Switch

BUILD=HERE/"build/selector_cells"
STANDARD="sky130_fd_pr__nfet_01v8"
NATIVE="sky130_fd_pr__nfet_03v3_nvt"


def upper(fingers):
    c=Cell("ne_threshold8" if fingers==8 else "ne_threshold")
    gate_bus,output_bus=(11.94,12.82) if fingers==8 else (10.82,11.70)
    # These lands are in the original ext_sw coordinate frame. The two power bars
    # are retained because package routing may reach any point on their length.
    for y,p,use in ((.24,"vss","ground"),(2.96,"vdd","power")):
        c.rect("metal1",0,y-.24,15,y+.24)
        c.port(p,"metal1",0,y-.19,.3,y+.19,use=use)
    c.ring(1.25,3.85,13.65,11.45 if fingers==8 else 10.60)
    c.via("mcon",3.0,3.765,nx=3)
    c.via("via1",3.0,3.765)
    c.via("via1",3.0,.24)
    c.v("metal2",3.0,.24,3.765)
    c.rect("metal2",1.545,0,1.845,gate_bus+.08)
    c.port("en","metal2",1.545,.01,1.845,.39)
    c.via("via2",1.695,gate_bus)
    c.h("metal3",1.695,12.775,gate_bus,.30)
    for bank,xc,xd,xs,control in (("RAW",4.5,4.36,5.50,"park"),("FIXED",10.5,10.45,11.57,"en")):
        xgate=xc+2.275
        if fingers==8:
            sw=Switch(c,"ne_native8","X"+bank,xc,7.68,nf=8)
            drains=[sw.ys(i) for i in range(0,9,2)]
            sources=[sw.ys(i) for i in range(1,8,2)]
            controls=[sw.yg(i) for i in range(8)]
        else:
            lane=[Switch(c,"sw4","X"+bank+str(i+1),xc,y) for i,y in enumerate((5.15,7.15,9.15))]
            drains=[sv.ys(0) for sv in lane]
            sources=[sv.ys(1) for sv in lane]
            controls=[sv.yg(0) for sv in lane]
        for y in drains:c.via("via1",xd,y)
        for y in sources:c.via("via1",xs,y)
        c.v("metal2",xd,min(drains),14.05,.30)
        c.port("ladder" if bank=="RAW" else "ext","metal2",xd-.15,13.80,xd+.15,14.20)
        c.v("metal2",xs,min(sources),output_bus)
        c.via("via2",xs,output_bus)
        c.v("metal1",xgate,min(controls),max(controls),.24)
        c.via("via1",xgate,max(controls))
        if control=="park":
            c.v("metal2",xgate,max(controls),13.8)
            c.port("park","metal2",xgate-.15,13.6,xgate+.15,14.0)
        else:
            c.v("metal2",xgate,max(controls),gate_bus)
            c.via("via2",xgate,gate_bus)
    c.h("metal3",5.5,14.53,output_bus,.30)
    c.via("via2",14.53,output_bus)
    c.v("metal2",14.53,1.60,14.05)
    c.port("out","metal2",14.38,13.80,14.68,14.20)
    c.outline(0,0,15,14.2)
    return c


def create(name):
    upper_cell=name.startswith("ne_threshold")
    fingers=8 if name=="ne_threshold8" else 3
    c=upper(fingers) if upper_cell else mid("ne_return")
    model=NATIVE if upper_cell else STANDARD
    # Each individual native switch is the precise original PDK W4/L.5, nf=1, guard=0
    # template. Only the ground return selects the enhancement-device generator.
    primitive=("ne_native8" if fingers==8 else "sw4") if upper_cell else "ne_return_nfet"
    front=f"""snap internal
load empty -force
random seed 20261118
box 0um 0um 0um 0um
magic::gencell sky130::{model} SW w 4 l .5 nf {8 if fingers==8 else 1} guard 0
select cell SW
set gen [instance list celldef]
cellname rename $gen {primitive}
"""
    body=c.t.text().replace("getcell sw4 ",f"getcell {primitive} ")
    tail=f"""
save {name}
drc euclidean on
drc style drc(full)
drc check
drc catchup
set num 0
foreach {{rule boxes}} [drc listall why] {{incr num [llength $boxes]; puts "RULE [llength $boxes] $rule $boxes"}}
puts "DRCTOTAL $num"
load {name}
gds write {name}.gds
flatten local_flat
load local_flat
select top cell
extract do local
extract all
ext2spice lvs
ext2spice hierarchy off
ext2spice subcircuit top on
ext2spice -o actual.spice local_flat
quit -noprompt
"""
    folder=BUILD/name;folder.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as scratch:
        w=Path(scratch);(w/"cell.tcl").write_text(front+body+tail)
        with (folder/"magic.log").open("w") as log:
            subprocess.run([magic_util.MAGIC,"-dnull","-noconsole","-rcfile",str(magic_util.MAGICRC),"cell.tcl"],cwd=w,
                           stdout=log,stderr=subprocess.STDOUT,env={**os.environ,"PDK_ROOT":str(magic_util.PDK_ROOT)},check=True)
        for fn in ("cell.tcl","actual.spice",name+".gds"):
            (folder/fn).write_bytes((w/fn).read_bytes())
    normalize_stream(folder/(name+".gds"))
    spice=re.sub(r"\n\+\s*"," ",(folder/"actual.spice").read_text())
    expected=[("ladder","park","out")]*fingers+[("ext","en","out")]*fingers if upper_cell else [("m1","iso","b1"),("m2","iso","b2")]
    actual=[]
    for line in spice.splitlines():
        if line.startswith("X"):
            f=line.split()
            if f[4]!="vss" or f[5]!=model or sorted(v.lower() for v in f[6:] if v.lower().startswith(("w=","l=")))!=["l=0.5","w=4"]:
                raise ValueError(("Device model, body or dimensions differ",f))
            actual.append((frozenset((f[1],f[3])),f[2]))
    from collections import Counter
    if Counter(actual)!=Counter((frozenset((a,b)),g) for a,g,b in expected):
        raise ValueError((name,spiceit(spice),expected))
    log=(folder/"magic.log").read_text()
    result=dict(master=name,device_model=model,count=len(actual),width_um=4,length_um=.5,
        original_footprint_um=[15,14.2] if upper_cell else [6.67,4.21],gate_endpoints=[list(x) for x in expected],
        body="vss",active_diffusion_topology=("one shared-diffusion eight-finger element per arm" if fingers==8 else "separate single-finger devices"),
        extracted_w_l_and_junctions=[q.split()[6:] for q in spice.splitlines() if q.startswith("X")],gds_sha256=hashlib.sha256((folder/(name+".gds")).read_bytes()).hexdigest(),
        extracted_sha256=hashlib.sha256((folder/"actual.spice").read_bytes()).hexdigest(),magic_drc=int(re.search(r"DRCTOTAL (\d+)",log)[1]))
    (folder/"measurement.json").write_text(json.dumps(result,indent=2)+"\n")
    print(name, result["count"],result["magic_drc"],result["gds_sha256"],flush=True)


def spiceit(text):
    return [row.split()[:8] for row in text.splitlines() if row.startswith("X")]


if __name__=="__main__":
    arguments=argparse.ArgumentParser(description=__doc__);arguments.add_argument("master",choices=("ne_threshold","ne_threshold8","ne_return","both"))
    a=arguments.parse_args()
    for n in (("ne_threshold","ne_return") if a.master=="both" else [a.master]):create(n)
