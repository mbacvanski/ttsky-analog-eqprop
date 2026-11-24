"""Integrate the independent, mode-qualified RES_SEL state switches on the measured die."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import klayout.db as db

from weak_leaf import LAYOUT, SIX, GDS, RECORDS, PARENT, load_parent, control, save, sha
from source import BUILD, REPORT
from connectivity import Connectivity, labels
from route_split import circuit


DESIGN = "229fb5826271a05a3803c2e57057c049497bcaa4fde53c8e0d85e059e2d1fc82"
LOGIC = "ne_res_hold_select"
LOGIC_PORTS = ["res_sel", "six", "weak", "weak_b", "vdd", "vss"]
NAND = "sky130_fd_sc_hd__nand2_1"
INV = "sky130_fd_sc_hd__inv_1"
TAP = "sky130_fd_sc_hd__tapvpwrvgnd_1"
M1, M2, M3 = control.M1, control.M2, control.M3


def schematic():
    p = LAYOUT.parent / "verification/evidence/res_sel_hold/source.spice.gz"
    raw = gzip.decompress(p.read_bytes())
    if hashlib.sha256(raw).hexdigest() != DESIGN:
        raise ValueError("Wrong mode-qualified HOLD source")
    text = raw.decode()
    for line in ("XHOLD_AND_B res_sel six vss vss vdd vdd weak_b "+NAND,
                 "XHOLD_AND weak_b weak vdd vss cmos_inv",
                 "XWEAK h ref weak weak_b vdd vss cd_tg_small"):
        if text.splitlines().count(line) != 1:
            raise ValueError(line)
    if text.count("weak weak_b native_res_hold_state DPROG=") != 3:
        raise ValueError("Expected three independent state switches")
    out = GDS / "res_select.spice"
    out.write_bytes(raw)
    return out


def draw_logic(ly):
    # The parent already contains the original inverter and body tap. Import only the NAND.
    std = db.Layout()
    std.read(str(control.GDS))
    if ly.cell(NAND) is None:
        ly.create_cell(NAND).copy_tree(std.cell(NAND))
    c = ly.create_cell(LOGIC)
    row = .46
    positions = [(TAP,.46), (NAND,.92), (INV,2.30), (TAP,3.68)]
    for name,x in positions:
        c.insert(db.CellInstArray(ly.cell(name).cell_index(), db.Trans(round(x*1000),round(row*1000))))
    control.ACCESS["nand2"] = {"A":(1.105,1.20), "B":(.260,1.19), "Y":(.700,1.79)}
    control.assert_access()
    points = {}
    for name,x,kind,signal in [(NAND,.92,"nand2",{"A":"res_sel","B":"six","Y":"weak_b"}),
                                (INV,2.30,"inv",{"A":"inverter_input","Y":"weak"})]:
        for pin, net in signal.items():
            dx,dy = control.ACCESS[kind][pin]
            p = round(x+dx,3),round(row+dy,3)
            control.lift(c,*p)
            points[net]=p
    for net in ("weak_b","inverter_input"):
        control.m3_via(c,*points[net])
    x,y=points["weak_b"]
    end,y2=points["inverter_input"]
    control.rectangle(c,M3,x-.17,y-.17,end+.17,y+.17)
    control.rectangle(c,M3,end-.17,y2-.17,end+.17,y+.17)
    for pin,y in [("vdd",row+2.72),("vss",row)]:
        x=3.95
        control.rectangle(c,M1,.46,y-.24,4.16,y+.24)
        control.pad(c,(68,44),x,y,.075,.075)
        control.pad(c,M2,x,y,.16,.19)
        points[pin]=(x,y)
    for port in LOGIC_PORTS:
        x,y=points[port]
        control.pad(c,(69,16),x,y,.12,.12)
        c.shapes(ly.layer(69,5)).insert(db.Text(port,round(x*1000),round(y*1000)))
    control.rectangle(c,(235,4),0,0,4.60,3.65)
    con=Connectivity(ly,c)
    ids={port:con.probe("m2",*points[port]) for port in LOGIC_PORTS}
    if (None in ids.values() or len(set(ids.values()))!=len(ids)
            or con.probe("m2",*points["inverter_input"])!=ids["weak_b"]):
        raise ValueError(("Global HOLD decoder physical connectivity",ids))
    return c


def check_logic(ly, logic):
    import check
    dest=GDS/"global"
    dest.mkdir(exist_ok=True)
    check.BUILD=dest
    path=dest/(LOGIC+".gds")
    save(ly,logic,path)
    drc=check.magic(path,logic.name,"global",True)
    if drc:
        raise ValueError(("Global decoder DRC violations",drc))
    control.ORDER=["XHOLD_AND_B","XHOLD_AND"]
    control.PORTS=LOGIC_PORTS
    ref=control.reference({"XHOLD_AND_B":("nand2",{"A":"res_sel","B":"six","Y":"weak_b"}),
                           "XHOLD_AND":("inv",{"A":"weak_b","Y":"weak"})})
    spice=(dest/"layout.spice").read_text()
    if not re.search(r"(?im)^\.subckt sx_flat ",spice):
        spice=".subckt sx_flat "+" ".join(LOGIC_PORTS)+"\n"+"\n".join(l for l in spice.splitlines() if l.startswith(("X","+")))+"\n.ends sx_flat\n"
    flat=dest/"global_extracted.spice"
    flat.write_text(spice)
    if check.devices(ref)!=check.devices(spice) or sum(check.devices(ref).values())!=6:
        raise ValueError("Incorrect physical NAND/inverter devices")
    # Resolve the four static input combinations using only the extracted FET gate and diffusion terminals.
    devices=[]
    for line in spice.splitlines():
        if line.startswith("X"):
            _,drain,gate,source,body,model,*_=line.split()
            is_n=model=="sky130_fd_pr__nfet_01v8"
            if not is_n and model!="sky130_fd_pr__pfet_01v8_hvt":raise ValueError(model)
            if body!=("vss" if is_n else "vdd"):raise ValueError((gate,body))
            devices.append((drain,gate,source,is_n))
    truth=[]
    for selected in (0,1):
        for six in (0,1):
            values={"res_sel":selected,"six":six,"vss":0,"vdd":1}
            while True:
                count=len(values)
                for left,gate,right,active in devices:
                    if values.get(gate)!=active:continue
                    for known,other in [(left,right),(right,left)]:
                        if known in values:
                            if values.get(other,values[known])!=values[known]:raise ValueError("Static rail contention")
                            values[other]=values[known]
                if len(values)==count:break
            if (values["weak"],values["weak_b"])!=(six & selected,1-(six & selected)):
                raise ValueError(("Wrong extracted HOLD control",values))
            truth.append({name:values[name] for name in ("res_sel","six","weak","weak_b")})
    results={}
    for key,reference in [("as_drawn",ref),("inverter_clock_short",ref.replace(" weak_b "," vss "))]:
        target=dest/(key+".spice")
        target.write_text(reference.replace(reference.splitlines()[1],".subckt ref "+" ".join(LOGIC_PORTS)))
        report=dest/(key+"_lvs.txt")
        check.run([check.NETGEN,"-batch","lvs",str(flat)+" sx_flat",str(target)+" ref",str(check.PDK/"libs.tech/netgen/sky130A_setup.tcl"),str(report)],key+".log")
        log=report.read_text()
        valid="Final result: Circuits match uniquely." in log and "Property errors were found" not in log
        if valid != (key=="as_drawn"):
            raise ValueError((key,log[-1400:]))
        if valid:
            table=log.rsplit("Subcircuit pins:",1)[1].split("Cell pin lists are equivalent.",1)[0]
            pairs=re.findall(r"(?m)^\s*(\w+)\s*\|\s*(\w+)\s*$",table)
            if set(pairs)!={(p,p) for p in LOGIC_PORTS}:raise ValueError(pairs)
        results[key]=valid
    return dict(full_Magic_DRC=drc,same_name_flat_LVS=results["as_drawn"],clock_short_rejected=not results["inverter_clock_short"],
                size_um=[logic.dbbox().width(),logic.dbbox().height()],ports=LOGIC_PORTS,
                gds_sha256=sha(path),flat_extracted_sha256=sha(flat),transistor_counts=dict(check.devices(spice)),
                static_switch_truth=truth,
                official_gds_sha256=sha(control.GDS),official_spice_sha256=sha(control.SPICE))


def parent_anchors(ly,top):
    """Identify package and circuit ports on the original physical conductors."""
    placement=json.loads((REPORT/"placement.json").read_bytes())["physical_instances"]
    inst={i.trans.to_s():i for i in top.each_inst()}
    def macro(name,pin):
        item=inst[placement[name]["transform"]]
        positions=labels(ly,item.cell,item.dtrans)[pin]
        if len(positions)!=1:raise ValueError((name,pin,positions))
        return [name+":"+pin,*positions[0]]
    pins=labels(ly,top)
    mapped=json.loads((REPORT/"selector8_signoff/reference_model.json").read_bytes())["explicit_board_pin_map"]
    if mapped["res_sel"]!="uio_in[6]":raise ValueError("RES_SEL pin moved")
    pad=pins[mapped["res_sel"]][0]
    return {**{n:macro(n,"h") for n in ("H1","H2","Z")},
            "ref":macro("H1","ref"),"vdd":macro("H1","vdd"),"vss":macro("H1","vss"),
            "six":macro("DEC_MODE","six"),"res_sel":["TT:"+mapped["res_sel"],*pad]}


def clearance_maps(ly,top):
    # The implant marker can extend beyond active and the well needs larger spacing.
    base=db.Region(db.Box(1800,1800,333080,223960))
    occupied=db.Region()
    for layer,space in [((64,20),1290),((65,20),480),((65,44),480),((66,20),480),
                        ((66,44),480),((67,20),480),((68,20),480),((69,20),480),
                        ((70,20),480),((89,44),480)]:
        occupied+=db.Region(top.begin_shapes_rec(ly.layer(*layer))).sized(space)
    return base-occupied.merged()


def wire_boxes(con,net):
    return [(p.bbox(),penalty) for metal,penalty in [("m1",.3),("m2",0.),("m3",.4),("m4",.8)]
            for p in con.region(net,metal).decompose_trapezoids_to_region().each()]


def wire_distance(point,boxes):
    x,y=point
    return min((max(b.left-x,x-b.right,0)+max(b.bottom-y,y-b.top,0))/1000+cost for b,cost in boxes)


def site(cell,available,signals,focus):
    """Place in unused material; favor shortest sensitive-state metal connections."""
    best=None
    for rot in range(4):
        spin=db.Trans(rot,False,0,0)
        bbox=cell.bbox().transformed(spin)
        w,h=bbox.width(),bbox.height()
        centers=available.sized(-w//2,-h//2,2)
        local=labels(cell.layout(),cell)
        candidate=[]
        for polygon in centers.each():
            b=polygon.bbox()
            for x in range(((b.left+249)//250)*250,b.right+1,250):
                for y in range(((b.bottom+249)//250)*250,b.top+1,250):
                    if (x-focus[0])**2+(y-focus[1])**2>70000**2:continue
                    if polygon.inside(db.Point(x,y)):
                        candidate.append((x,y))
            p=b.center()
            if polygon.inside(p) and (p.x-focus[0])**2+(p.y-focus[1])**2<=70000**2:
                candidate.append(((p.x//5)*5,(p.y//5)*5))
        for x,y in candidate:
            dx,dy=x-bbox.center().x,y-bbox.center().y
            t=db.Trans(rot,False,dx,dy)
            scores=[]
            for pin,boxes,weight in signals:
                _,px,py=local[pin][0]
                p=t*db.Point(round(px*1000),round(py*1000))
                scores.append(weight*wire_distance((p.x,p.y),boxes))
            cost=sum(scores)+.035*math.hypot(x-focus[0],y-focus[1])/1000
            if best is not None and cost>=best[0]:continue
            r=cell.bbox().transformed(t)
            if not (db.Region(r)-available).is_empty():continue
            best=cost,t,r
    if best is None:raise ValueError((cell.name,"No physical site with adequate clearance"))
    return best[1:]


def integrate(ly,logic):
    top=next(c for c in ly.top_cells() if c.name.startswith("tt_um_"))
    anchors=parent_anchors(ly,top)
    targets=[[name,*pin] for name,pin in anchors.items()]
    nets,shorts,con=circuit(ly,top,targets)
    if shorts or len(nets)!=8:raise ValueError(("Parent anchor mismatch",dict(nets),shorts))
    copper={name:wire_boxes(con,next(iter(groups))) for name,groups in nets.items()}
    free=clearance_maps(ly,top)
    switch=ly.cell("sx_reset_tg")
    records={}
    for name,cell in [("H1",switch),("H2",switch),("Z",switch),("SELECT",logic)]:
        raw=name!="SELECT"
        anchor=anchors[name if raw else "six"]
        focus=(round(1000*anchor[2]),round(1000*anchor[3]))
        signals=[("a",copper[name],2.),("b",copper["ref"],.3)] if raw else [
            ("six",copper["six"],1.),("res_sel",copper["res_sel"],.6)]
        t,b=site(cell,free,signals,focus)
        ins=top.insert(db.CellInstArray(cell.cell_index(),t));free-=db.Region(b).sized(1290)
        mapping = {"a":name,"b":"ref","en":"weak","en_b":"weak_b","vdd":"vdd","vss":"vss"} if raw else {n:n for n in LOGIC_PORTS}
        found=labels(ly,ins.cell,ins.dtrans)
        for pin,net in mapping.items():
            if len(found[pin])!=1:raise ValueError((name,pin,found[pin]))
            targets.append([net,name+":"+pin,*found[pin][0]])
        records[name]=dict(master=cell.name,transform=t.to_s(),bbox_um=[v/1000 for v in (b.left,b.bottom,b.right,b.top)],pins=mapping)
        print("Placed",name,t,b,flush=True)
    p=BUILD/"res_hold_base.gds"
    save(ly,top,p)
    (BUILD/"res_hold_targets.json").write_text(json.dumps(targets,indent=2)+"\n")
    nets,shorts,_=circuit(ly,top,targets)
    if shorts:raise ValueError(("Unexpected contact in placement",shorts))
    return dict(parent_gds_sha256=PARENT,source_schematic_sha256=DESIGN,placed_gds_sha256=sha(p),target_sha256=sha(BUILD/"res_hold_targets.json"),
                parent_macro_instances=59,placed_macro_instances=sum(1 for _ in top.each_inst()),die_um=[334.880,225.760],
                placements=records,original_pin_receipts=anchors,unrouted_branches={k:len(v)-1 for k,v in nets.items()},
                scope="Placed overlay. Full-chip metal routing and subsequent electrical qualification are evaluated independently.")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--place",action="store_true")
    opt=p.parse_args()
    GDS.mkdir(exist_ok=True,parents=True)
    RECORDS.mkdir(exist_ok=True,parents=True)
    schematic()
    ly=load_parent()
    logic=draw_logic(ly)
    result=check_logic(ly,logic)
    print(json.dumps(result),flush=True)
    (RECORDS/"res_select_logic.json").write_text(json.dumps(result,indent=2)+"\n")
    (RECORDS/(LOGIC+".gds.gz")).write_bytes(gzip.compress((GDS/"global"/(LOGIC+".gds")).read_bytes(),mtime=0))
    if opt.place:
        placement=integrate(ly,logic)
        (RECORDS/"res_hold_placement.json").write_text(json.dumps(placement,indent=2)+"\n")


if __name__=="__main__":
    main()
