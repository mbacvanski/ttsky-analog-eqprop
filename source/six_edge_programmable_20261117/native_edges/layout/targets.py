"""Transfer native metal islands from their measured donor nets and attach all new physical terminals."""
from collections import Counter, defaultdict
import json
import re
import klayout.db as db

from source import BUILD, REPORT, NEW, pins as package_pins, read_source, read_net_locations, labels, save, sha
from connectivity import Connectivity, INDEX, METALS


def point_on(region):
    # All imported copper is Manhattan. Pick a point inside a real rectangle.
    for polygon in region.merged().decompose_trapezoids_to_region().each():
        box=polygon.bbox()
        if box.width() and box.height(): return box.center()
    return None


def new_assign():
    result={}
    def mid(name, nodes):
        result[name]=dict(zip(("m1","m2","b1","b2","iso","vss"),nodes+["six","vss"]))
    for l,h in (("A",1),("B",2)):
        g=l.lower()
        mid("END_"+l,["f1","f2",g+"l1",g+"l2"])
        mid("MID_"+l,[g+"m1",g+"m2",g+"mx1",g+"mx2"])
        mid("LEAF_"+l,[g+"l1",g+"l2",g+"fx1",g+"fx2"])
        result["RW_"+l]={"z":"raw"+str(h),"f1":g+"l1","f2":g+"l2","m1":g+"m1","m2":g+"m2","vss":"vss"}
        result["ROWS_"+l]={"f1x":g+"fx1","f2x":g+"fx2","zx":g+"x","m1x":g+"mx1","m2x":g+"mx2",
            "ref":"ref","dac":"dac","clampw":"park","vdd":"vdd","vss":"vss",**{"we"+str(i):g+str(i) for i in range(4)}}
        result["THRESH"+str(h)]={"ladder":"raw"+str(h),"ext":"fixed"+str(h),"en":"six","out":"h"+str(h)+"bias","vdd":"vdd","vss":"vss"}
        for d in (1,2,3):mid(f"HELP_SW_{h}_{d}",[f"f{h}",f"q{h}",f"fsw{h}",f"qsw{h}"])
        result["HELP_"+str(h)]={"sw4":f"fsw{h}","p":f"p{h}","sw7":f"qsw{h}","ref":"ref","vss":"vss"}
        result["R_FIXED"+str(h)]={"ref":"ref",f"fixed{h}":f"fixed{h}","vss":"vss"}
        result["G_FIXED"+str(h)]={f"p{h}":f"p{h}",f"end{h}":f"end{h}","vss":"vss"}
    mid("FIXED_SW",["end1","end2","vss","vss"])
    mid("RAW_BUS",["raw1","raw2","ax","bx"])
    result["DEC_MODE"]={p:p for p in json.loads((BUILD/"decoder.json").read_text())["ports"]}
    if set(result)!=set(NEW):raise ValueError(set(result)^set(NEW))
    return result


def aliases(ly,top,ins,old):
    names={}; pinmap=labels(ly,top)
    def rec(loc,name):
        co=old.probe(*loc)
        if co is None or names.get(co,name)!=name:raise ValueError((loc,name,names.get(co)))
        names[co]=name
        return co
    for name,net in {"VDPWR":"vdd","VGND":"vss","ui_in[0]":"bit_a","ui_in[1]":"bit_b","uio_in[4]":"bias_prog",
                     "uio_in[0]":"ext_en1","uio_in[1]":"ext_en2"}.items():
        for loc in pinmap[name]:rec(loc,net)
    for cell,pin,net in [("H1","y","f1"),("H2","y","f2"),("H1","ref","ref"),("H1","bpin","raw1"),("H2","bpin","raw2"),
            ("NRN_H1","p","p1"),("NRN_H1","q","q1"),("NRN_H2","p","p2"),("NRN_H2","q","q2"),("BIAS","dac","dac"),("DEC","clampw","clampw"),
            *[("DEC","we"+str(i),"we"+str(i)) for i in range(4)]]:
        for loc in labels(ly,ins[cell].cell,ins[cell].dtrans)[pin]:rec(loc,net)
    return names


def retain_local(ly,top,oldly,old,ins,phys):
    # Native H/H/Z anchor regions retain original top-level low-metal links that
    # fit wholly inside their rigid group. The source terminal geometry is untouched.
    # Keep all three original LI-to-M1 landings on their exact rotated electrodes.
    records={}
    for key,members in (("H1",("H1","NRN_H1","U3_H1")),("H2",("H2","NRN_H2","U3_H2")),("Z",("Z","NRN_Z","U3_Z","DACG"))):
        original=ins[key].trans
        move=phys[key]*original.inverted()
        bb=db.Box()
        for n in members:bb+=ins[n].bbox()
        keep={}; area={}; total={}
        for layer in ("li","mcon","m1","v1","m2","v2","m3"):
            ix=oldly.layer(*METALS[layer])
            raw=db.Region(old.shapes(ix))
            keep[layer]=raw.inside(db.Region(bb.enlarged(-400)))
            allchild=db.Region()
            for n in members:allchild+=db.Region(ins[n].cell.begin_shapes_rec(ix)).transformed(ins[n].trans)
            total[layer]=(allchild+keep[layer]).merged()
        for layer,left,right in (("mcon","li","m1"),("v1","m1","m2"),("v2","m2","m3")):
            kept=db.Region()
            for p in keep[layer].each():
                test=db.Region(p.bbox().enlarged(20))
                if (test-total[left]).is_empty() and (test-total[right]).is_empty():kept.insert(p)
            keep[layer]=kept
        for layer,shapes in keep.items():
            area[layer]=shapes.area()*1.e-6
            top.shapes(ly.layer(*METALS[layer])).insert(shapes.transformed(move))
        records[key]=area
    return records


def main():
    placement=json.loads((REPORT/"placement.json").read_text())
    source=BUILD/"native_edges_placement.gds"
    if sha(source)!=placement["gds_sha256"]:raise ValueError("Placement stream hash mismatch")
    ly=db.Layout();ly.read(str(source));top=ly.top_cell()
    oldly,old_chip=read_source()
    old=Connectivity(oldly,old_chip);ins=read_net_locations(oldly,old_chip)
    phys={n:db.Trans.from_s(info["transform"]) for n,info in placement["physical_instances"].items()}
    renamed=aliases(oldly,old_chip,ins,old)
    retained=retain_local(ly,top,oldly,old_chip,ins,phys)
    cache={}; sides=defaultdict(list)
    def asloc(m,p):return [m,p.x*.001,p.y*.001]
    for name,inst in ins.items():
        cell=inst.cell
        if cell.name not in cache:
            local=Connectivity(oldly,cell);records=[]
            for cluster in local.nets:
                for layer in ("m2","m1","m3","m4","li"):
                    pt=point_on(local.region(cluster,layer))
                    if pt is not None:
                        if local.probe(*asloc(layer,pt))!=cluster:raise ValueError((cell.name,cluster,layer))
                        records.append((cluster,layer,pt));break
            cache[cell.name]=records
        for own,layer,pt in cache[cell.name]:
            src=old.probe(*asloc(layer,inst.trans*pt));native=renamed.get(src,"old_"+str(src))
            if src is None:raise ValueError((name,own))
            desired=native
            if name in ("H1","H2") and native=="raw"+name[-1]:desired="h"+name[-1]+"bias"
            if name=="RBLOCK" and re.fullmatch("we[0-3]",native):desired="z"+native[-1]
            sides[src].append([desired,name+":"+str(own),*asloc(layer,phys[name]*pt)])
    pin_names=set(package_pins())
    physical_labels=labels(oldly,old_chip)
    for pin in sorted(pin_names):
        for loc in physical_labels[pin]:
            cluster=old.probe(*loc)
            if cluster is None:raise ValueError((pin,loc))
            sides[cluster].append([renamed.get(cluster,"old_"+str(cluster)),"TT:"+pin,*loc])
    targets=[p for old_id,members in sides.items()
             if len(members)>1 or old_id in renamed or any(v[1].startswith("TT:") for v in members)
             for p in members]
    if {p[1][3:] for p in targets if p[1].startswith("TT:")}!=pin_names:raise ValueError("Some wrapper pins were omitted")
    extra=new_assign()
    for name,mapping in extra.items():
        cell=ly.cell(placement["physical_instances"][name]["cell"])
        pm=labels(ly,cell)
        for pin,desired in mapping.items():
            if pin not in pm:raise ValueError((name,cell.name,pin,sorted(pm)))
            for layer,x,y in pm[pin]:
                pt=db.Point(round(1000*x),round(1000*y))
                targets.append([desired,name+":"+pin,*asloc(layer,phys[name]*pt)])
    after=Connectivity(ly,top); allnets=defaultdict(lambda:defaultdict(list));by_key=defaultdict(set)
    for desired,tag,layer,x,y in targets:
        co=after.probe(layer,x,y)
        if co is None:raise ValueError(("No physical access",tag,layer,x,y))
        allnets[desired][co].append(tag)
        by_key[co].add(desired)
    shorts={n:sorted(v) for n,v in by_key.items() if len(v)>1}
    if shorts:raise ValueError(("Conflicting source assignments",shorts))
    # The local parent LI landing must connect to M1 before intermacro routing.
    lost=[]
    for n,sets in allnets.items():
        if len(sets)<2:continue
        for group,labels_ in sets.items():
            if all(after.region(group,m).is_empty() for m in INDEX):lost.append([n,labels_])
    if lost:raise ValueError(("Local electrode without a metal access",lost))
    # Write recognized original-net names as list rather than relying on prior
    # GDS numeric extraction IDs after the physical macros have moved.
    (BUILD/"targets.json").write_text(json.dumps(targets,separators=(",",":"))+"\n")
    save(ly,top,BUILD/"base.gds")
    record={"frozen_global_metal_islands":len(old.nets),"all_original_macro_metal_islands_compared":sum(map(len,sides.values())),
        "active_named_nets":len(allnets),"targets":len(targets),"separate_required_terminal_islands":sum(map(len,allnets.values())),
        "initial_distinct_routes":sum(1 for m in allnets.values() if len(m)>1),"initial_open_branches":sum(len(m)-1 for m in allnets.values()),
        "preserved_native_parent_geometry_um2":retained,"initial_unintended_shorts":shorts,"physical_program_nets":extra,
        "frozen_identified_source_nets":renamed,"base_gds_sha256":sha(BUILD/"base.gds"),"target_list_sha256":sha(BUILD/"targets.json")}
    (REPORT/"net_targets.json").write_text(json.dumps(record,indent=2)+"\n")
    print("islands",record["targets"],"nets",len(allnets),"open",record["initial_open_branches"],"shorts",shorts,flush=True)


if __name__=="__main__":main()
