"""Read the frozen chip, identify the two true resistor midpoints and prepare physical placement inputs."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

import klayout.db as db

HERE=Path(__file__).resolve().parent
SIX=HERE.parents[1]
sys.path.insert(0,str(SIX/"layout"))
from baseline import GDS_HASH, PDK, V4, sha, source_gds
from connectivity import Connectivity, labels
from prepare_split import read_net_locations, save

BUILD=HERE/"build"
REPORT=HERE/"results"
NATIVE=V4/"floorplan/tt_project_v4/lef/tt_um_mbacvanski_denseam_xor.lef"
GROUPS={"H1":("H1","NRN_H1","U3_H1"),"H2":("H2","NRN_H2","U3_H2"),"Z":("Z","NRN_Z","U3_Z","DACG")}
NEW={"ROWS_A":"pw4_rblock4","ROWS_B":"pw4_rblock4","RW_A":"ne_rw_native","RW_B":"ne_rw_native",
     "MID_A":"pw4_mid","MID_B":"pw4_mid","END_A":"pw4_mid","END_B":"pw4_mid","RAW_BUS":"pw4_mid",
     "LEAF_A":"pw4_mid","LEAF_B":"pw4_mid","HELP_1":"ne_help","HELP_2":"ne_help",
     **{f"HELP_SW_{j}_{n}":"pw4_mid" for j in (1,2) for n in (1,2,3)},
     "R_FIXED1":"ne_r1","R_FIXED2":"ne_r2","G_FIXED1":"ne_g1","G_FIXED2":"ne_g2","FIXED_SW":"pw4_mid",
     "THRESH1":"ext_sw","THRESH2":"ext_sw","DEC_MODE":"ne_mode_bank_gates"}


def pins():
    result={}
    for name,body in re.findall(r"(?ms)^  PIN (\S+)\n(.*?)^  END \1$",NATIVE.read_text()):
        entries=re.findall(r"(?ms)LAYER (met\d) ;\s*RECT ([^;]+?) ;",body)
        result[name]=[(int(layer[-1]),*[round(1000*float(n)) for n in coords.split()]) for layer,coords in entries]
    if len(result)!=53 or sum(map(len,result.values()))!=58:
        raise ValueError("Frozen interface differs from its 53 pins and 58 rectangles")
    return result


def read_source():
    src=source_gds()
    if sha(src)!=GDS_HASH:raise ValueError("Unrecognized frozen GDS")
    ly=db.Layout();ly.read(str(src))
    return ly,ly.top_cell()


def midpoint_copy(ly,top,original):
    rw=original["RW"];mid=original["MID"];a,=list(rw.cell.each_inst())
    if a.cell.name!="cp_r100x6":raise ValueError("Different fixed resistor macro")
    local=Connectivity(ly,rw.cell);tile=Connectivity(ly,top)
    receiving=labels(ly,mid.cell,mid.dtrans)
    t={shape.text.string:a.trans*db.Point(shape.text.x,shape.text.y) for shape in a.cell.shapes(ly.layer(67,5)).each() if shape.is_text()}
    donor=ly.create_cell("ne_rw_native")
    donor.insert(db.CellInstArray(rw.cell.cell_index(),db.Trans()))
    info={}
    for j,terms in ((1,("R2_1","R2_2")),(2,("R2_3","R2_4"))):
        metal={local.probe("li",t[n].x*ly.dbu,t[n].y*ly.dbu) for n in terms}
        final={tile.probe("li",(rw.trans*t[n]).x*ly.dbu,(rw.trans*t[n]).y*ly.dbu) for n in terms}
        end,=receiving["m"+str(j)]
        if len(metal)!=1 or None in metal or final!={tile.probe(*end)}:
            raise ValueError("The named two frozen strip ends do not reach the original isolation-switch pin")
        node,=metal; pad=local.region(node,"m1");q=t[terms[0]]
        landing=db.Box(q.x-75,q.y-75,q.x+75,q.y+75)
        if not (db.Region(landing)-pad).is_empty():raise ValueError("Midpoint landing misses actual donor metal")
        donor.shapes(ly.layer(68,16)).insert(landing)
        donor.shapes(ly.layer(68,5)).insert(db.Text("m"+str(j),q.x,q.y))
        info["m"+str(j)]={"original_array_members":list(terms),"existing_M1_landing_local_nm":[q.x,q.y],
                          "original_connected_switch":f"MID:m{j}","original_global_landing_nm":[(rw.trans*q).x,(rw.trans*q).y]}
    # The four original boundary pins are re-exposed on their original metal without changing the conductor.
    for k,vals in labels(ly,rw.cell).items():
        if k not in ("z","f1","f2","vss"):continue
        for metal,x,y in vals:
            if metal!="m2":raise ValueError("Unexpected physical RW port")
            donor.shapes(ly.layer(69,5)).insert(db.Text(k,round(x/ly.dbu),round(y/ly.dbu)))
    return donor,info


def add_local_cells(ly):
    import decoder
    from resistors import DESIGNS, WORK
    for n in DESIGNS:
        p=WORK/n/(n+".gds")
        if not p.exists():raise FileNotFoundError("Run resistors.py to regenerate the extracted high-R cell "+n)
        ly.read(str(p))
    decoder.draw(ly)


def rects(region):
    return [[b.left,b.bottom,b.right,b.top] for s in region.merged().decompose_trapezoids_to_region().each() for b in [s.bbox()]]


def setup():
    ly,top=read_source();ins=read_net_locations(ly,top)
    rw,mid=midpoint_copy(ly,top,ins);add_local_cells(ly)
    allgroups={**GROUPS,**{k:(k,) for k in ins if all(k not in l for l in GROUPS.values())}}
    groups={}
    for k,members in allgroups.items():
        groups[k]=[(n,ins[n].cell,ins[n].trans) for n in members]
    groups.update({k:[(k,ly.cell(name),db.Trans())] for k,name in NEW.items()})
    return ly,top,groups,mid


def export():
    BUILD.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    ly,top,groups,mid=setup()
    inventory={}
    items={}
    for key,group in groups.items():
        bbox=db.Box();m4=db.Region()
        for n,cell,t in group:
            bbox+=cell.bbox().transformed(t)
            for pair in ((71,20),(70,44)):
                m4+=db.Region(cell.begin_shapes_rec(ly.layer(*pair))).transformed(t)
        translate=db.Trans(-bbox.left,-bbox.bottom)
        items[key]={"w_nm":bbox.width(),"h_nm":bbox.height(),"origin_nm":[bbox.left,bbox.bottom],
                    "m4_geometry_nm":rects(m4.transformed(translate)),
                    "members":[{"name":n,"cell":c.name,"original_transform":t.to_s()} for n,c,t in group],
                    "is_original":key not in NEW}
        for _,c,_ in group:
            if c.name not in inventory:
                b=c.bbox();inventory[c.name]={"bbox_nm":[b.left,b.bottom,b.right,b.top],
                    "children":dict(Counter(i.cell.name for i in c.each_inst()))}
    p=pins()
    result={"frozen_gds_sha256":GDS_HASH,"frozen_schematic_sha256":hashlib.sha256(gzip.decompress((SIX/"circuit/frozen_native.spice.gz").read_bytes())).hexdigest(),
            "frozen_LEF_sha256":sha(NATIVE),"candidate_schematic_sha256":sha(HERE.parent/"circuit/native_six.spice"),
            "outline_nm":[0,0,334880,225760],"original_macro_instances":len(read_net_locations(ly,top)),
            "separate_native_R200k_midpoints":mid,"ports_nm":p,"physical_templates":inventory,"instances":items,
            "new_macro_details":{"HELP_1/2":"Digitally extracted SKY130 eight 11.56 µm legs plus two grounded dummies, four pairs implement two parallel R4 and two parallel R7 branches.",
                "DEC_MODE":"Real frozen standard-cell donor instances for all inverters and NOR2/NOR3 gates in native_bank_enable and the six-mode decoder; 26 labelled, locally routed ports.",
                "THRESH1/2":"Two actual 15.0×14.2 µm native transmission-gate muxes for H1/H2 old buffered source versus six-edge fixed threshold."}}
    (BUILD/"native_placement_inputs.json").write_text(json.dumps(result,separators=(",",":"))+"\n")
    (REPORT/"frozen_inventory.json").write_text(json.dumps({k:v for k,v in result.items() if k not in ("instances","ports_nm")},indent=2)+"\n")
    save(ly,ly.cell("ne_rw_native"),BUILD/"ne_rw_native.gds")
    for n,dat in mid.items():print(n,dat)
    print("original",result["original_macro_instances"],"candidate groups",len(items))


if __name__=="__main__":export()
