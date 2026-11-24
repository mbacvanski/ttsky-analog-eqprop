"""Repair the precision-resistor implant and limit HOLD gate metal area on the checked four-passive board."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import klayout.db as db

from quiet_route import BUILD, INDEX, LAYERS, METALS, polygon_of, route, save
from rc_passives import L
from route_split import circuit

PARENT="b411c5009c27f06c0dda9cd1e303c1f1f4d2517bd3a99b24caeb66921d7bb570"
TARGETS="quiet_rc_targets.json"
WIRES=("weak_b","weak")


def prepare():
    archive=L/"results/quiet_rc_provisional"
    raw=gzip.decompress((archive/"die.gds.gz").read_bytes())
    if hashlib.sha256(raw).hexdigest()!=PARENT:
        raise ValueError("The precise four-passive layout changed")
    ly=db.Layout()
    ly.read_bytes(raw);top=ly.top_cell()
    bank=ly.cell("ne_rc_high_poly")
    markers=bank.shapes(ly.layer(94,20))
    old=db.Region(markers)
    closed=old.sized(195).sized(-195).merged()
    changed=closed-old
    if not changed.area() or (old-closed).area():
        raise ValueError("The isolated resistor implant candidates are not the expected three")
    poly=db.Region(bank.begin_shapes_rec(ly.layer(66,20)))
    if (poly & changed).area():
        raise ValueError("Implant bridge covers precision resistor material")
    markers.insert(changed)
    targets=json.loads((BUILD/TARGETS).read_bytes())
    nets,shorts,con=circuit(ly,top,targets)
    if shorts or any(len(g)!=1 for g in nets.values()):
        raise ValueError("The reference GDS must be fully connected")
    owners={next(iter(nets[n])):n for n in WIRES}
    keep={}
    for n in WIRES:
        _,_,_,x,y=next(t for t in targets if t[0]==n and t[1]=="R:"+n)
        q=db.Point(round(x*1000),round(y*1000));keep[n]=db.Region(db.Box(q,q).enlarged(220))
    for layer in LAYERS:
        geometry=top.shapes(ly.layer(*METALS[layer]));drops=[];retained=db.Region()
        before={node:con.region(node,layer) for node in owners} if layer in INDEX else {}
        for s in geometry.each():
            copper=db.Region(polygon_of(s))
            for node,name in owners.items():
                if layer in INDEX:
                    if not (before[node]&copper).area():
                        continue
                else:
                    x,y=s.bbox().center().x,s.bbox().center().y
                    if con.probe('m'+str(int(layer[-1])+1),.001*x,.001*y)!=node:
                        continue
                if (copper-keep[name]).area():
                    retained+=copper & keep[name]
                    drops.append(s)
                break
        for s in drops:s.delete()
        geometry.insert(retained.merged())
    after,bad,_=circuit(ly,top,targets)
    if bad or any(len(g)!=(4 if n in WIRES else 1) for n,g in after.items()):
        raise ValueError(("Only the six junctions on the two three-switch hold rails can be open",bad,{k:len(g) for k,g in after.items() if len(g)!=1}))
    out=BUILD/"quiet_rc_release_open.gds";save(ly,top,out)
    print("Added PSD implant area in um2",changed.area()/1e6,"open control groups",[(n,len(after[n])) for n in WIRES],flush=True)


def verify_geometry():
    """Check the completed die against the exact electrical-control mask, at every physical layer."""
    from overlay import count_instances,region,texts,top_ports
    parent=L/"results/quiet_rc_provisional"
    result=L/"results/quiet_rc_release"
    dies=[];pins=json.loads((BUILD/TARGETS).read_bytes())
    for folder in (parent,result):
        raw=gzip.decompress((folder/"die.gds.gz").read_bytes())
        sha=hashlib.sha256(raw).hexdigest()
        manifest=json.loads((folder/"manifest.json").read_bytes())
        if sha!=manifest["gds_sha256"]:
            raise ValueError("GDS digest mismatch")
        layout=db.Layout();layout.read_bytes(raw);cell=layout.top_cell()
        groups,shorts,connectivity=circuit(layout,cell,pins)
        if shorts or any(len(v)!=1 for v in groups.values()):
            raise ValueError("Unintended physical open or short on a registered conductor")
        dies.append((layout,cell,groups,connectivity,sha))
    old,src,before,past,osh=dies[0];new,dst,after,present,nsh=dies[1]
    if osh!=PARENT or count_instances(src)!=count_instances(dst) or top_ports(old,src)!=top_ports(new,dst) or src.bbox()!=dst.bbox():
        raise ValueError("Placement, package or outer boundary changed")
    layers={str(layer):layer for layout in (old,new) for layer in layout.layer_infos()}
    copper={str(db.LayerInfo(*METALS[n])):n for n in LAYERS}
    total_labels=0;report={}
    for key,layer in layers.items():
        left=region(old,src,layer);right=region(new,dst,layer)
        original=texts(old,src,layer)
        if original!=texts(new,dst,layer):raise ValueError(("Changed physical text",key))
        total_labels+=sum(original.values())
        removed,added=left-right,right-left
        if not removed.area() and not added.area():continue
        if (layer.layer,layer.datatype)==(94,20):
            if removed.area() or added.area()!=22245600:
                raise ValueError(("Unexpected P+ implant delta",removed.area(),added.area()))
            for number,purpose in [(65,20),(65,44),(66,20),(66,13)]:
                active=region(new,dst,db.LayerInfo(number,purpose))
                if (added&active).area():raise ValueError(("New implant intersects a device material",number,purpose))
        elif key in copper:
            metal=copper[key]
            for delta,nets,connect in [(removed,before,past),(added,after,present)]:
                allowed=db.Region()
                for n in WIRES:
                    owner,=nets[n]
                    if metal in INDEX:
                        allowed+=connect.region(owner,metal)
                    else:
                        upper="m"+str(int(metal[-1])+1)
                        allowed+=connect.layers[metal]&connect.region(owner,upper)
                if (delta-allowed).area():
                    raise ValueError(("Metal outside the two gate conductors changed",key,(delta-allowed).area()))
        else:
            raise ValueError(("Unexpected changed process layer",key))
        report[key]={"added_um2":added.area()/1e6,"removed_um2":removed.area()/1e6}
    evidence=dict(parent_gds=osh,candidate_gds=nsh,matched_terminal_sites=len(pins),matched_port_label_locations=len(top_ports(new,dst)),
                  matched_existing_placements=sum(count_instances(dst).values()),all_labels_identical=total_labels,
                  layers_checked=len(layers),changes_um2=report,unchanged_other_control_wires=True,
                  implanted_empty_space_um2=22.2456)
    (result/"repair_geometry.json").write_text(json.dumps(evidence,indent=2)+"\n")
    return evidence


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["prepare","route","verify"]);parser.add_argument("--stem",default="quiet_rc_release_routed")
    parser.add_argument("--cost",type=int,default=800)
    parser.add_argument("--m3-cost",type=int,default=70)
    parser.add_argument("--n-m3",type=int,default=0)
    args=parser.parse_args()
    if args.action=="verify":print(verify_geometry()["candidate_gds"])
    elif args.action=="prepare":prepare()
    else:
        route(args.stem,220,110,85,True,source="quiet_rc_release_open",target_file=TARGETS,wires=WIRES,physical_points=True,m4_cost=args.cost,m3_cost=args.m3_cost,
              per_wire_m3={"weak_b":args.m3_cost,"weak":args.n_m3} if args.n_m3 is not None else None)
