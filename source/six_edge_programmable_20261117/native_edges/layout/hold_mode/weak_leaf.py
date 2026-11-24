"""A drawn small HOLD branch sourced from the active candidate and the physical parent."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

import klayout.db as db


HERE = Path(__file__).resolve().parent
LAYOUT = HERE.parent
SIX = LAYOUT.parents[1]
sys.path.insert(0, str(LAYOUT))
from source import BUILD, REPORT, save, sha
from decoder import control
from connectivity import Connectivity, labels

CELL = "ne_hold_weak"
PARENT = "2ff6bb34d055799fa6d188924a1dc54ed6dd4a886092837138098d8da098d5cd"
CANDIDATE = "773c40dcc40a84bf6e51b9230012d8c427154194f400173f9f4ac54724ce1274"
GDS = BUILD / "hold_mode"
RECORDS = REPORT / "hold_mode"
M1, M2, M3 = control.M1, control.M2, control.M3
PORTS = ["wr", "wh", "h", "ref", "vdd", "vss"]


def net_source():
    raw = gzip.decompress((LAYOUT.parent / "verification/evidence/parked_legacy_switch/source.spice.gz").read_bytes())
    if hashlib.sha256(raw).hexdigest() != CANDIDATE:
        raise ValueError("Incorrect HOLD circuit")
    text = raw.decode()
    source = re.search(r"(?ms)^\.subckt native_hold_control .*?^\.ends", text)[0]
    calls = [line for line in source.splitlines() if line.startswith(("Xweaknor ", "Xweakinv ", "Xweak "))]
    check = ["Xweaknor wr clamp wh wstate_b vdd vss cmos_nor3",
             "Xweakinv wstate_b wstate vdd vss cmos_inv",
             "Xweak h ref wstate wstate_b vdd vss cd_tg_small"]
    if calls != check:
        raise ValueError(calls)
    kernel = re.search(r"(?ms)^\.subckt native_mode_state .*?^\.ends", text)[0]
    if "XCTRL natural ref vss reset hold_in cmd h ref vdd vss lr lh wr wh native_hold_control" not in kernel:
        raise ValueError("The neuron clamp is no longer tied to VSS")
    gate = re.search(r"(?ms)^\.subckt cd_tg_small [^\n]*\n(.*?)^\.ends", text)[1]
    transistors = []
    for line in gate.splitlines():
        if line.startswith(("XMN ", "XMP ")):
            name, *pins, model, length, width = line.split()[:8]
            mapping = dict(a="h", b="ref", en="wstate", en_b="wstate_b", vdd="vdd", vss="vss")
            transistors.append(" ".join([name, *(mapping[p] for p in pins), model, length, width]))
    if len(transistors) != 2:
        raise ValueError("Unexpected small state switch")
    gates = {"WEAKNOR": ("nor3", dict(A="wr",B="vss",C="wh",Y="wstate_b")),
             "WEAKINV": ("inv", dict(A="wstate_b",Y="wstate"))}
    control.ORDER, control.PORTS = list(gates), PORTS
    full = re.sub(r"(?m)^WEAK", "XWEAK", control.reference(gates))
    full = full.replace(".ends ref", "\n".join(transistors) + "\n.ends ref")
    return full


def load_parent():
    path = BUILD / "selector8_release.gds"
    if not path.is_file():
        raw = gzip.decompress((REPORT / "selector8_signoff/die.gds.gz").read_bytes())
        if hashlib.sha256(raw).hexdigest() != PARENT:
            raise ValueError("Incorrect routed parent")
        path = GDS / "parent.gds"
        path.write_bytes(raw)
    if sha(path) != PARENT:
        raise ValueError("Incorrect routed parent")
    layout = db.Layout()
    layout.read(str(path))
    small_file = SIX / "layout_cells/gds/sx_reset_tg.gds"
    # tgnt/tgpb are the same drawn transistor primitives in both files.
    source = db.Layout()
    source.read(str(small_file))
    for primitive in ("tgnt", "tgpb"):
        donor = source.cell(primitive)
        other = layout.cell(primitive)
        for i in source.layer_indexes():
            info = source.get_info(i)
            j = layout.find_layer(info)
            original = db.Region(other.begin_shapes_rec(j)) if j is not None else db.Region()
            if not (db.Region(donor.begin_shapes_rec(i)) ^ original).is_empty():
                raise ValueError((primitive, str(info)))
    opts = db.LoadLayoutOptions()
    opts.cell_conflict_resolution = db.LoadLayoutOptions.CellConflictResolution.SkipNewCell
    layout.read(str(small_file), opts)
    return layout


def draw(layout):
    c = layout.create_cell(CELL)
    def put(name, x, y):
        return c.insert(db.CellInstArray(layout.cell(name).cell_index(), db.Trans(round(x*1000),round(y*1000))))
    def rect(layer, x1, y1, x2, y2):
        control.rectangle(c,layer,x1,y1,x2,y2)
    def horiz(layer, x1, x2, y, half):
        rect(layer,min(x1,x2)-half,y-half,max(x1,x2)+half,y+half)
    def vert(layer, x, y1, y2, half):
        rect(layer,x-half,min(y1,y2)-half,x+half,max(y1,y2)+half)
    def label(name, xy):
        x,y=xy
        control.pad(c,(69,16),x,y,.12,.12)
        c.shapes(layout.layer(69,5)).insert(db.Text(name,round(x*1000),round(y*1000)))
    this = put("sx_reset_tg",.5,.5)
    coords = {pin:(p[0][1],p[0][2]) for pin,p in labels(layout,this.cell,this.dtrans).items()}
    yrow = 10.30
    xnor = 1.08
    xinv = 2.92
    for cell, x in [("tapvpwrvgnd",.62),("nor3",xnor),("inv",xinv),("tapvpwrvgnd",4.30)]:
        put("sky130_fd_sc_hd__"+cell+"_1",x,yrow)
    points={}
    for kind,x,net in [("nor3",xnor,{"A":"wr","B":"ground-input","C":"wh","Y":"inverted"}),
                       ("inv",xinv,{"A":"inverted-in","Y":"enabled"})]:
        for pad, key in net.items():
            dx,dy=control.ACCESS[kind][pad]
            pt=(round(x+dx,3),round(yrow+dy,3))
            points[key]=pt
            if key=="ground-input":
                control.pad(c,(67,44),*pt,.085,.085)
                control.pad(c,M1,*pt,.135,.165)
                vert(M1,pt[0],yrow,pt[1],.115)
            else:
                control.lift(c,*pt)
    # Separate M3 tracks join NOR and inverter outputs to the two physical TG gate pins.
    for keys,pin,col,track in [(("inverted","inverted-in"),"en_b",6.15,9.02),(("enabled",),"en",5.45,9.73)]:
        gx,gy=coords[pin]
        control.m3_via(c,gx,gy);horiz(M3,gx,col,gy,.165);control.m3_via(c,col,gy)
        vert(M2,col,gy,track,.14);control.m3_via(c,col,track)
        for key in keys:
            x,y=points[key];vert(M2,x,y,track,.14);control.m3_via(c,x,track)
        horiz(M3,min(points[key][0] for key in keys),col,track,.165)
    for net,col,level in [("vss",7.56,yrow),("vdd",6.85,yrow+2.72)]:
        x,y=coords[net]
        control.m3_via(c,x,y);horiz(M3,x,col,y,.165);control.m3_via(c,col,y)
        vert(M2,col,y,level,.14);control.pad(c,M2,col,level,.145,.185)
        control.pad(c,(68,44),col,level,.075,.075)
        horiz(M1,.62,col,level,.24)
        label(net,(col,level))
    for name,p in [("h",coords["a"]),("ref",coords["b"]),("wr",points["wr"]),("wh",points["wh"])]:
        label(name,p)
    rect((235,4),0,0,7.86,13.45)
    con=Connectivity(layout,c)
    ports={k:con.probe(m,x,y) for k,[(m,x,y)] in labels(layout,c).items()}
    expect={"wstate":(*coords["en"],points["enabled"]),"wstate_b":(*coords["en_b"],points["inverted"])}
    for key,(x,y,pt) in expect.items():
        p=con.probe("m2",x,y)
        if p!=con.probe("m2",*pt):raise ValueError((key,"open"))
        ports[key]=p
    if (len(ports)!=8 or None in ports.values() or len(set(ports.values()))!=8
            or con.probe("m2",*coords["a"])!=ports["h"] or con.probe("m2",*coords["b"])!=ports["ref"]
            or con.probe("m2",*points["inverted-in"])!=ports["wstate_b"]):
        raise ValueError(("Wrong physical wire mapping",ports))
    return c


def verify(file, cell, reference):
    import check
    check.BUILD=GDS
    clean = check.magic(file,cell.name,"weak",True)
    raw = (GDS/"layout.spice").read_text()
    if not re.search(r"(?im)^\.subckt sx_flat ",raw):
        raw = ".subckt sx_flat "+" ".join(PORTS)+"\n"+"\n".join(l for l in raw.splitlines() if l.startswith(("X","+")))+"\n.ends sx_flat\n"
    raw_file = GDS/"weak_extracted.spice"
    raw_file.write_text(raw)
    extracted=check.devices(raw)
    if extracted!=check.devices(reference) or sum(extracted.values())!=10:
        raise ValueError(("Device inventory",extracted,check.devices(reference)))
    results={}
    for key,ref in [("as_drawn",reference),("ground_short",reference.replace("XMN h wstate ref","XMN h vss ref"))]:
        path=GDS/(key+".spice")
        path.write_text(ref);out=GDS/(key+"_lvs.txt")
        check.run([check.NETGEN,"-batch","lvs",str(raw_file)+" sx_flat",str(path)+" ref",str(check.PDK/"libs.tech/netgen/sky130A_setup.tcl"),str(out)],key+".log")
        log=out.read_text()
        matches="Final result: Circuits match uniquely." in log and "Property errors were found" not in log
        if matches!=(key=="as_drawn"):raise ValueError((key,log[-1500:]))
        if matches:
            tail=log.rsplit("Subcircuit pins:",1)[1].split("Cell pin lists are equivalent.",1)[0]
            pins=re.findall(r"(?m)^\s*(\w+)\s*\|\s*(\w+)\s*$",tail)
            if set(pins)!={(p,p) for p in PORTS}:raise ValueError(("ports",pins))
        results[key]=matches
    if clean:raise ValueError(("DRC",clean))
    return dict(parent_gds_sha256=PARENT, source_schematic_sha256=CANDIDATE, gds_sha256=sha(file),
                size_um=[cell.dbbox().width(),cell.dbbox().height()], named_ports=PORTS,
                same_name_flat_LVS=results["as_drawn"], planted_ground_short_rejected=not results["ground_short"],
                full_Magic_DRC=clean, transistor_inventory=dict(extracted), extracted_sha256=sha(raw_file),
                switch_orientation={"a":"h","b":"ref","en":"wstate","en_b":"wstate_b"},
                scope="Standalone weak branch. The candidate's whole-chip fast-driver comparison failed and a different global control is being investigated.")


def main():
    GDS.mkdir(parents=True,exist_ok=True)
    RECORDS.mkdir(parents=True,exist_ok=True)
    reference=net_source()
    (GDS/"weak_reference.spice").write_text(reference)
    layout=load_parent()
    c=draw(layout)
    file=GDS/(CELL+".gds");save(layout,c,file)
    print(CELL, c.dbbox(), sha(file), flush=True)
    verified=verify(file,c,reference)
    (RECORDS/"weak_leaf.json").write_text(json.dumps(verified,indent=2)+"\n")
    (RECORDS/(CELL+".gds.gz")).write_bytes(gzip.compress(file.read_bytes(),mtime=0))
    print(verified,flush=True)


if __name__=="__main__":
    main()
