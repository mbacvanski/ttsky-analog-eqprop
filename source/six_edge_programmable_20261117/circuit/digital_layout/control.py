"""Place and wire the 24 original SKY130 HD gates of the six-edge decoder."""
from collections import defaultdict
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import klayout.db as k

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[1]
PDK = Path(os.environ.get("PDK_ROOT", Path.home()/".ciel"))/"sky130A"
STD = PDK/"libs.ref/sky130_fd_sc_hd"
LEF = STD/"lef/sky130_fd_sc_hd.lef"
GDS = STD/"gds/sky130_fd_sc_hd.gds"
SPICE = STD/"spice/sky130_fd_sc_hd.spice"
TOP = "sx_input_control"
PORTS = "a b addr0 addr1 write rs wp bp ext_en1 ext_en2 ref_reset sel0 sel1 sel2 sel3 inwrite sa nsa sb nsb avg1 navg1 avg2 navg2 use1 use2 vdd vss".split()
ORDER = (
    "XIA XSEL1 XSEL0 XIB XSEL2 XSEL3 XIW XWR "
    "XIAB XSA XSAB XIP XIBB XSB XSBB "
    "XUSE1 XNMODE1 XAVGNEG1 XAVGEN1 XAVGINV XAVGEN2 XAVGNEG2 XNMODE2 XUSE2"
).split()
WIDTH = {"inv":1.38, "nor2":1.38, "nor3":1.84}
# The chosen local coordinates lie inside the official LEF LI pin rectangles.
# Separate vertical columns permit over-cell routing without moving cell pins.
ACCESS = {
    "inv":{"A":(.46,1.19), "Y":(.925,1.77)},
    "nor2":{"A":(1.135,1.20), "B":(.245,1.20), "Y":(.69,.62)},
    "nor3":{"A":(1.62,1.19), "B":(.705,1.17), "C":(.245,1.17), "Y":(1.16,1.58)},
}
M1, M2, M3 = (68,20), (69,20), (70,20)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def block(text, name):
    match = re.search(r"(?ims)^\.subckt "+name+r"\b[^\n]*\n.*?^\.ends[^\n]*",text)
    if not match:
        raise ValueError(f"Missing SPICE subcircuit {name}")
    return match.group()


def sources():
    python = os.environ.get("SPICE_PYTHON") or next(
        (str(p/".venv/bin/python") for p in HERE.parents if (p/".venv/bin/python").is_file()),sys.executable)
    netlist = subprocess.check_output([python,"-B","-c",
        "from prototype import build,convert; print(convert(build.build()[0]),end='')"],
        cwd=SIX/"split_pair",text=True)
    gates = {}
    for scope in ("six_input_bank","xor_chip_six"):
        for line in block(netlist,scope).splitlines():
            words = line.replace("bias_prog","bp").split()
            if not words or words[0] not in ORDER:
                continue
            name, *signals, vdd, vss, cell = words
            assert (vdd,vss)==("vdd","vss") and name not in gates
            kind = cell.removeprefix("cmos_")
            pins = list(ACCESS[kind])
            assert len(pins)==len(signals)
            gates[name] = (kind,dict(zip(pins,signals)))
            wrapper = block(netlist,cell)
            assert ("XSTD "+" ".join([*list("abc"[:len(pins)-1]),"vss vss vdd vdd y",f"sky130_fd_sc_hd__{kind}_1"])) in wrapper
    assert set(gates)==set(ORDER) and len(gates)==24
    return gates,sha256(netlist.encode()).hexdigest()


def reference(gates):
    """Flatten the independent PDK transistor SPICE, keeping FET widths and bulks."""
    std = SPICE.read_text()
    result = ["* Flat reference from chip instance connectivity and original standard-cell SPICE.",
              ".subckt ref "+" ".join(PORTS)]
    for name in ORDER:
        kind, signals = gates[name]
        ports = {**signals,"VGND":"vss","VNB":"vss","VPB":"vdd","VPWR":"vdd"}
        for line in block(std,f"sky130_fd_sc_hd__{kind}_1").splitlines():
            if line.startswith("X"):
                dev,*rest = line.split()
                terminals = [ports.get(t,name+"_"+t) for t in rest[:4]]
                result.append(" ".join([name+"_"+dev,*terminals,*rest[4:]]))
    return "\n".join([*result,".ends ref",""])


def assert_access():
    lef = LEF.read_text()
    for kind,pins in ACCESS.items():
        name=f"sky130_fd_sc_hd__{kind}_1"
        macro=lef.split("MACRO "+name+"\n",1)[1].split("END "+name+"\n",1)[0]
        for pin,(x,y) in pins.items():
            section=macro.split("  PIN "+pin+"\n",1)[1].split("  END "+pin+"\n",1)[0]
            assert "LAYER li1 ;" in section
            boxes=re.findall(r"RECT ([-.\d]+) ([-.\d]+) ([-.\d]+) ([-.\d]+)",section)
            assert any(l-.0001<=x-.085 and x+.085<=r+.0001 and
                       b-.0001<=y-.085 and y+.085<=t+.0001
                       for l,b,r,t in (map(float,row) for row in boxes)),(name,pin,x,y)


def rectangle(cell, layer, x1,y1,x2,y2):
    cell.shapes(cell.layout().layer(*layer)).insert(k.Box(*(round(v*1000) for v in (x1,y1,x2,y2))))


def pad(cell,layer,x,y,dx,dy):
    rectangle(cell,layer,x-dx,y-dy,x+dx,y+dy)


def lift(cell,x,y):
    pad(cell,(67,44),x,y,.085,.085)
    pad(cell,M1,x,y,.16,.14)
    pad(cell,(68,44),x,y,.075,.075)
    pad(cell,M2,x,y,.14,.16)


def m3_via(cell,x,y):
    pad(cell,M2,x,y,.14,.185)
    pad(cell,(69,44),x,y,.1,.1)
    pad(cell,M3,x,y,.17,.17)


def color_intervals(intervals):
    """Disjoint horizontal net intervals share a track with full M3 spacing."""
    ends = []
    tracks = {}
    for net,(left,right) in sorted(intervals.items(),key=lambda item:item[1]):
        for n,end in enumerate(ends):
            if left-end>=.33:
                break
        else:
            n=len(ends)
            ends.append(None)
        tracks[net]=n
        ends[n]=right
    return tracks


def draw():
    assert_access()
    gates,assembly_sha = sources()
    lib = k.Layout()
    lib.read(str(GDS))
    layout=k.Layout()
    layout.dbu=.001
    assert lib.dbu==layout.dbu
    masters={}
    for kind in WIDTH:
        old=lib.cell(f"sky130_fd_sc_hd__{kind}_1")
        masters[kind]=layout.create_cell(old.name)
        masters[kind].copy_tree(old)
    tap=layout.create_cell("sky130_fd_sc_hd__tapvpwrvgnd_1")
    tap.copy_tree(lib.cell(tap.name))
    top = layout.create_cell(TOP)
    row_y=.86
    x=1.20
    nets=defaultdict(list)
    instances=[]
    taps=[]
    for name in ORDER:
        if name in ("XSEL3","XAVGNEG1"):
            top.insert(k.CellInstArray(tap.cell_index(),k.Trans(round(x*1000),round(row_y*1000))))
            taps.append([x,row_y])
            x=round(x+.46,3)
        kind,signals=gates[name]
        top.insert(k.CellInstArray(masters[kind].cell_index(),k.Trans(round(x*1000),round(row_y*1000))))
        instances.append({"name":name,"master":masters[kind].name,"origin_um":[round(x,3),row_y]})
        for p,net in signals.items():
            dx,dy=ACCESS[kind][p]
            xx,yy=round(x+dx,3),round(row_y+dy,3)
            lift(top,xx,yy)
            nets[net].append((xx,yy))
        x=round(x+WIDTH[kind],3)
    width=x+.25
    # Each shared signal uses one M3 trunk. Independent outputs with a single
    # gate terminal reach their external M2 access directly.
    intervals={net:(points[0][0]-.175,points[-1][0]+.175)
               for net,points in ((n,sorted(p)) for n,p in nets.items()) if len(points)>1}
    tracks=color_intervals(intervals)
    track_y={net:round(1.52+.70*i,3) for net,i in tracks.items()}
    port_y={}
    low_y=round(max(track_y.values())+.94,3)
    last_x=-1.
    last_high=False
    for x_port,net in sorted((min(pts)[0],net) for net,pts in nets.items() if net in PORTS):
        high=x_port-last_x<.66 and not last_high
        port_y[net]=round(low_y+(1.12 if high else 0),3)
        last_high=high
        last_x=x_port
    height=round(max(port_y.values())+.2,3)
    access={}
    def port(net,left,bottom,right,top_y):
        box=[round(v,3) for v in (left,bottom,right,top_y)]
        rectangle(top,M2,*box)
        rectangle(top,(69,16),*box)
        top.shapes(layout.layer(69,5)).insert(k.Text(net,round((left+right)*500),round((bottom+top_y)*500)))
        access[net]={"layer":"metal2","rect":box,
                     "direction":"supply" if net in ("vdd","vss") else ("input" if net in PORTS[:11] else "output")}
    for net,points in nets.items():
        pts=sorted(points)
        ytrack=track_y.get(net)
        if ytrack is not None:
            left,right=intervals[net]
            rectangle(top,M3,left,ytrack-.17,right,ytrack+.17)
        for i,(xx,yy) in enumerate(pts):
            ends=[yy]
            if ytrack is not None:
                m3_via(top,xx,ytrack)
                ends.append(ytrack)
            if i==0 and net in PORTS:
                yp=port_y[net]
                port(net,xx-.15,yp-.19,xx+.15,yp+.19)
                ends.append(yp)
            rectangle(top,M2,xx-.14,min(ends)-.025,xx+.14,max(ends)+.025)
    # Full-length M2 supply straps, with off-row VDD rise onto the native M1
    # PMOS rail, and M1/M2 VSS contacts at both ends of the ground rail.
    for xx in (1.48,x-.41):
        pad(top,(68,44),xx,row_y,.075,.075)
        pad(top,M2,xx,row_y,.13,.16)
    rectangle(top,M2,1.20,row_y-.16,x,row_y+.16)
    vdd_x=.32
    vdd_y=row_y+2.72
    rectangle(top,M1,vdd_x-.16,vdd_y-.14,1.48,vdd_y+.14)
    pad(top,(68,44),vdd_x,vdd_y,.075,.075)
    rectangle(top,M2,vdd_x-.14,.22,vdd_x+.14,vdd_y+.16)
    rectangle(top,M2,.15,.06,x,.38)
    port("vdd",.16,.04,.48,.42)
    port("vss",1.32,row_y-.19,1.64,row_y+.19)
    assert set(PORTS)==set(access)
    rectangle(top,(235,4),0,0,width,height)
    assert top.bbox()==k.Box(0,0,round(1000*width),round(1000*height))
    gds=HERE/(TOP+".gds")
    options=k.SaveLayoutOptions()
    options.gds2_write_timestamps=False
    layout.write(str(gds),options)
    info={"cell":TOP,"units":"um","outline":[0,0,round(width,3),round(height,3)],
          "size_um":[round(width,3),round(height,3)],"pins":access,
          "physical_gate_count":len(instances),"well_tap_origins_um":taps,"placements":instances,
          "horizontal_tracks_metal3_um":track_y,"orientation":"R0, one eastward standard-cell row",
          "gds_sha256":digest(gds),"split_pair_assembly_sha256":assembly_sha,
          "standard_cell_sources_sha256":{"gds":digest(GDS),"lef":digest(LEF),"spice":digest(SPICE)}}
    (HERE/"geometry.json").write_text(json.dumps(info,indent=2)+"\n")
    (HERE/"reference.spice").write_text(reference(gates))
    # An independent physical routing coupon exercises every access window
    # at once. It lives in build/ and cannot enter the released macro.
    (HERE/"build").mkdir(exist_ok=True)
    coupon=layout.create_cell("sx_access_coupon")
    coupon.insert(k.CellInstArray(top.cell_index(),k.Trans()))
    for name,location in access.items():
        x1,y1,x2,y2=location["rect"]
        px,py=(x1+x2)/2,(y1+y2)/2
        m3_via(coupon,px,py)
        if name in ("vss","vdd"):
            rectangle(coupon,M3,px-.17,py-.17,px+.55,py+.17)
        else:
            pad(coupon,M3,px,py,.17,.36)
    layout.write(str(HERE/"build/access.gds"),options)
    print(f"{len(instances)} gates, {len(access)} ports, {len(set(tracks.values()))} shared tracks, {width:.3f} x {height:.3f} um")


if __name__=="__main__":
    draw()
