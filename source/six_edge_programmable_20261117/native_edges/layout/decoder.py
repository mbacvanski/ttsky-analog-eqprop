"""Draw the candidate's physical bank-address and six-mode logic from the assembled chip netlist."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import klayout.db as db

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "circuit/digital_layout"))
import control

SUB = "native_bank_enable"
TOP = "xor_chip_native_six"
PORTS = "bit_a bit_b we0 we1 we2 we3 bias_prog ext_en1 ext_en2 clampw z0 z1 z2 z3 a0 a1 a2 a3 b0 b1 b2 b3 six park vdd vss".split()


def gates_from(deck):
    gates={}
    for section in (SUB, TOP):
        for line in control.block(deck,section).splitlines():
            words=line.split()
            if not words or words[-1] not in ("cmos_inv","cmos_nor2","cmos_nor3"): continue
            name,*signals,vdd,vss,cell=words
            kind=cell.removeprefix("cmos_")
            if (vdd,vss)!=("vdd","vss") or len(signals)!=len(control.ACCESS[kind]):raise ValueError(line)
            pins={k:(v if v in PORTS else section+"/"+v) for k,v in zip(control.ACCESS[kind],signals)}
            gates[section+"/"+name]=(kind,pins)
    return gates


def draw(ly):
    gates=gates_from((HERE.parent/"circuit/native_six.spice").read_text())
    control.assert_access()
    cell=ly.create_cell("ne_mode_bank_gates")
    row=.86; x=1.2; nets=defaultdict(list)
    # Body contacts run across every gate in the original standard cell row.
    for j,(name,(kind,pins)) in enumerate(gates.items()):
        if j%7==0:
            tap=ly.cell("sky130_fd_sc_hd__tapvpwrvgnd_1")
            cell.insert(db.CellInstArray(tap.cell_index(),db.Trans(round(x*1000),round(row*1000))))
            x=round(x+.46,3)
        gate=ly.cell("sky130_fd_sc_hd__"+kind+"_1")
        cell.insert(db.CellInstArray(gate.cell_index(),db.Trans(round(x*1000),round(row*1000))))
        for pin,net in pins.items():
            dx,dy=control.ACCESS[kind][pin];xx=round(x+dx,3);yy=round(row+dy,3)
            control.lift(cell,xx,yy);nets[net].append((xx,yy))
        x=round(x+control.WIDTH[kind],3)
    intervals={n:(min(v)[0]-.175,max(v)[0]+.175) for n,v in nets.items() if len(v)>1}
    track={n:round(1.52+.70*i,3) for n,i in control.color_intervals(intervals).items()}
    low=round(max(track.values())+.94,3); py={}; last=-1.; previous=False
    for xp,net in sorted((min(v)[0],n) for n,v in nets.items() if n in PORTS):
        high=xp-last<.66 and not previous
        py[net]=low+(1.12 if high else 0);last=xp;previous=high
    access={}
    def port(net,x1,y1,x2,y2):
        box=[x1,y1,x2,y2];control.rectangle(cell,control.M2,*box);control.rectangle(cell,(69,16),*box)
        cell.shapes(ly.layer(69,5)).insert(db.Text(net,round(500*(x1+x2)),round(500*(y1+y2))))
        access[net]={"layer":"m2","rect_um":[round(v,3) for v in box]}
    for net,points in nets.items():
        if net in track:
            left,right=intervals[net];yt=track[net];control.rectangle(cell,control.M3,left,yt-.17,right,yt+.17)
        for i,(xx,yy) in enumerate(sorted(points)):
            ends=[yy]
            if net in track:
                control.m3_via(cell,xx,track[net]);ends.append(track[net])
            if i==0 and net in py:
                yport=py[net];port(net,xx-.15,yport-.19,xx+.15,yport+.19);ends.append(yport)
            control.rectangle(cell,control.M2,xx-.14,min(ends)-.025,xx+.14,max(ends)+.025)
    for xx in (1.48,x-.41):
        control.pad(cell,(68,44),xx,row,.075,.075);control.pad(cell,control.M2,xx,row,.13,.16)
    control.rectangle(cell,control.M2,1.20,row-.16,x,row+.16)
    control.rectangle(cell,control.M1,.16,row+2.72-.14,1.48,row+2.72+.14)
    control.pad(cell,(68,44),.32,row+2.72,.075,.075)
    control.rectangle(cell,control.M2,.18,.22,.46,row+2.72+.16)
    control.rectangle(cell,control.M2,.15,.06,x,.38)
    port("vdd",.16,.04,.48,.42);port("vss",1.32,row-.19,1.64,row+.19)
    if set(access)!=set(PORTS):raise ValueError(set(access)^set(PORTS))
    control.rectangle(cell,(235,4),0,0,x+.25,max(py.values())+.2)
    (HERE/"build/decoder.json").write_text(json.dumps({"ports":access,"gates":gates,"counts":Counter(k for k,v in gates.values())},indent=2)+"\n")
    return cell
