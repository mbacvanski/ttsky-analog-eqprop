"""Install the locally extracted threshold and ground-return macros on the signed-off baseline."""
import json
from pathlib import Path
import klayout.db as db
from source import BUILD, REPORT, labels, save, sha
from route_split import circuit
from connectivity import METALS

PARENT="963630e8d72040630878be7700047258768c468c8a76c6c8f8ebad119235ccf8"


def assemble(fingers=3):
    threshold="ne_threshold8" if fingers==8 else "ne_threshold"
    stem="selector8" if fingers==8 else "selector"
    path=BUILD/"release.gds"
    if sha(path)!=PARENT:raise ValueError("Unexpected baseline layout")
    ly=db.Layout();ly.read(str(path));top=ly.top_cell()
    for name in (threshold,"ne_return"):
        folder=BUILD/"selector_cells"/name
        material=folder/(name+".gds");receipt=json.loads((folder/"measurement.json").read_text())
        if sha(material)!=receipt["gds_sha256"] or receipt["magic_drc"]:raise ValueError(name)
        test=db.Layout();test.read(str(material))
        if name=="ne_threshold":
            donor=ly.cell("sw4");same=test.cell("sw4")
            for ix in test.layer_indexes():
                info=test.get_info(ix);oi=ly.find_layer(info)
                old=db.Region(donor.begin_shapes_rec(oi)) if oi is not None else db.Region()
                if (old^db.Region(same.begin_shapes_rec(ix))).area():
                    raise ValueError(("Changed native device physical layer",str(info)))
        options=db.LoadLayoutOptions();options.cell_conflict_resolution=db.LoadLayoutOptions.CellConflictResolution.SkipNewCell
        ly.read(str(material),options)
    placed=json.loads((REPORT/"placement.json").read_text())["physical_instances"]
    targets=json.loads((BUILD/"targets.json").read_text())
    replacements={}
    clearance=db.Region()
    for name,new in (("THRESH1",threshold),("THRESH2",threshold),("FIXED_SW","ne_return")):
        info=placed[name];tr=db.Trans.from_s(info["transform"])
        ins=[i for i in top.each_inst() if i.trans==tr and i.cell.name==info["cell"]]
        if len(ins)!=1:raise ValueError((name,len(ins)))
        old=ins[0].cell;current=ly.cell(new)
        old_pins=labels(ly,old)
        new_pins=labels(ly,current)
        if not set(old_pins)<=set(new_pins):raise ValueError((name,set(old_pins)-set(new_pins)))
        # Use actual landing positions, also verified by the top-level connectivity and LVS.
        for label in old_pins:
            l,x,y=old_pins[label][0];reg=db.Region(current.begin_shapes_rec(ly.layer(*METALS[l])))
            xp=round(x/ly.dbu);yp=round(y/ly.dbu)
            if (reg&db.Region(db.Box(xp-1,yp-1,xp+1,yp+1))).area()!=4:raise ValueError((name,label,x,y))
        ins[0].cell_index=current.cell_index()
        if name.startswith("THRESH"):
            clearance.insert(ins[0].bbox().enlarged(180))
            l,x,y=labels(ly,current,ins[0].dtrans)["park"][0]
            targets.append(["park",name+":park",l,x,y])
        replacements[name]=dict(original=old.name,replacement=new,transform=tr.to_s(),old_bounds_um=old.dbbox().to_s(),new_bounds_um=current.dbbox().to_s())
    # Old parent traces crossed empty space inside the two original muxes.
    # Clear just the low metals inside their new footprint and recover every
    # severed conductor from independently named external/physical terminals.
    for layer in ("m1","m2","m3","v1","v2","v3"):
        shapes=top.shapes(ly.layer(*METALS[layer]));prior=db.Region(shapes)
        if layer.startswith("v"):
            # Keep or remove a complete via cut. A partial boundary cut is illegal.
            remaining=prior.not_interacting(clearance.sized(310))
        else:
            remaining=prior-clearance
            near=clearance.sized(550)
            radius=145 if layer=="m3" else 65
            cleaned=remaining.sized(-radius).sized(radius)
            remaining=(remaining-near)+(cleaned&near)
        shapes.clear();shapes.insert(remaining.merged())
    out=BUILD/(stem+"_base.gds");save(ly,top,out)
    (BUILD/(stem+"_targets.json")).write_text(json.dumps(targets)+"\n")
    groups,shorts,_=circuit(ly,top,targets)
    opens={k:dict(g) for k,g in groups.items() if len(g)>1}
    result=dict(gds_sha256=sha(out),parent_gds_sha256=PARENT,masters=replacements,unrouted_components=opens,shorts=shorts)
    (BUILD/(stem+"_placement.json")).write_text(json.dumps(result,indent=2)+"\n")
    print(result["gds_sha256"],shorts,{k:len(g) for k,g in opens.items()},flush=True)



def close():
    ly=db.Layout();ly.read(str(BUILD/"selector8_heal.gds"));top=ly.top_cell()
    targets=json.loads((BUILD/"selector8_targets.json").read_text())
    groups,shorts,metal=circuit(ly,top,targets)
    if shorts or any(len(v)!=1 for v in groups.values()):raise ValueError("Unrouted 8-finger candidate")
    ground,=groups["vss"]
    fill=db.Region(db.Box(160510,59920,160850,60155))
    if (fill & (metal.layers["m1"]-metal.region(ground,"m1"))).area():raise ValueError("Additional grounding would touch another net")
    # Fill the shared substrate-return notch at the original H1 VSS landing.
    # Magic and the pinned KLayout deck independently found this small space.
    top.shapes(ly.layer(*METALS["m1"])).insert(fill)
    groups,shorts,_=circuit(ly,top,targets)
    if shorts or any(len(v)!=1 for v in groups.values()):raise ValueError("Final conductor mismatch")
    save(ly,top,BUILD/"selector8_release.gds")


if __name__=="__main__":
    import argparse
    c=argparse.ArgumentParser(description=__doc__);c.add_argument("--fingers",choices=(3,8),type=int,default=3);c.add_argument("--close",action="store_true");a=c.parse_args()
    if a.close:close()
    else:assemble(a.fingers)
