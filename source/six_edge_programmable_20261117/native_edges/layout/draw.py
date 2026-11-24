"""Stream a concrete unrouted placement and independently check its die, logical interfaces and overlaps."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import klayout.db as db

from source import BUILD, HERE, NEW, REPORT, pins, setup, sha, save


def write():
    data=json.loads((BUILD/"native_placement_inputs.json").read_text())
    plan=json.loads((BUILD/"placement.json").read_text())
    if not plan["complete"] or plan["omitted"] or (plan["schematic_sha256"] != sha(HERE.parent/"circuit/native_six.spice") ):
        raise ValueError("Incomplete or stale layout")
    ly,old,groups,mid=setup()
    top=ly.create_cell("tt_um_mbacvanski_native_edges_place")
    pg=db.Region()
    for name,entries in pins().items():
        for layer,*coords in entries:
            if layer!=4:raise ValueError("Changed package pin layer")
            r=db.Box(*coords)
            top.shapes(ly.layer(71,20)).insert(r)
            top.shapes(ly.layer(71,16)).insert(r)
            if name in ("VDPWR","VGND"):pg.insert(r)
    old_text=set()
    for s in old.shapes(ly.layer(71,5)).each():
        if s.is_text() and s.text.string in pins():
            top.shapes(ly.layer(71,5)).insert(s.text)
            old_text.add(s.text.string)
    if old_text!=set(pins()):raise ValueError("An external pin label is absent")
    die=db.Box(0,0,334880,225760)
    top.shapes(ly.layer(235,4)).insert(die)
    result={};boxes=[]
    for k,p in plan["placements"].items():
        info=data["instances"][k]
        ox,oy=info["origin_nm"]
        original=db.Box(ox,oy,ox+info["w_nm"],oy+info["h_nm"])
        rotate=db.Trans(p["rotation"],False,0,0)
        before=original.transformed(rotate)
        move=db.Trans(p["x_nm"]-before.left,p["y_nm"]-before.bottom)*rotate
        current=original.transformed(move)
        if current!=db.Box(*p["bbox_nm"]):raise ValueError("Actual cell location differs from packed dimensions")
        for o,other in boxes:
            if (db.Region(current).sized(plan["gap_nm"]-5)&db.Region(other)).area():
                raise ValueError("Two physical envelopes are too close: "+k+" and "+o)
        boxes.append((k,current))
        for n,c,trans in groups[k]:
            f=move*trans
            top.insert(db.CellInstArray(c.cell_index(),f))
            m4=db.Region(c.begin_shapes_rec(ly.layer(71,20))).transformed(f)
            if (m4&pg.sized(440)).area():raise ValueError("Package rail touches "+n)
            result[n]={"group":k,"cell":c.name,"transform":f.to_s(),"bbox_nm":c.bbox().transformed(f).to_s()}
    if top.bbox()!=die or len(result)!=32+len(NEW):raise ValueError("A drawing left the tile or a required macro was lost")
    suffix=""
    path=BUILD/("native_edges_placement"+suffix+".gds");save(ly,top,path)
    data=path.read_bytes();REPORT.mkdir(exist_ok=True,parents=True)
    (REPORT/("native_edges_placement"+suffix+".gds.gz")).write_bytes(gzip.compress(data,mtime=0))
    report={"scope":"Placement of all 32 original and all new circuit macros. Inter-macro signal/power routes and whole-chip LVS remain pending.",
            "gds_sha256":hashlib.sha256(data).hexdigest(),"frozen_gds_sha256":plan["frozen_gds_sha256"],
            "candidate_schematic_sha256":plan["schematic_sha256"],"groups":len(groups),"macro_instances":len(result),
            "original_instances":32,"all_53_pin_names_and_58_lands":True,"all_7_long_power_lands_kept":True,
            "minimum_group_gap_nm":plan["gap_nm"],"die_nm":[0,0,334880,225760],"floorplan":plan,"physical_instances":result}
    (REPORT/("placement"+suffix+".json")).write_text(json.dumps(report,indent=2)+"\n")
    print(report["gds_sha256"],len(groups),len(result),len(old_text),flush=True)


if __name__=="__main__":
    write()
