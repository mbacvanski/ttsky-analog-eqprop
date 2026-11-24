"""Audit the exact parent polygons, switch pin locations and material added by the routed HOLD overlay."""
from collections import Counter
import gzip
import hashlib
import json

import klayout.db as db

from res_select import BUILD, GDS, RECORDS, REPORT, DESIGN, PARENT, parent_anchors
from connectivity import Connectivity, labels
from route_split import circuit


def open_archive(path,digest):
    GDS.mkdir(parents=True,exist_ok=True)
    file=GDS/(digest[:16]+".gds")
    raw=gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError("Incorrect archived layout")
    file.write_bytes(raw)
    layout=db.Layout();layout.read(str(file))
    return layout,layout.top_cell()


def count_instances(top):
    return Counter((i.cell.name,i.trans.to_s(),i.na,i.nb,i.a.to_s(),i.b.to_s()) for i in top.each_inst())


def top_ports(ly,top):
    return sorted((n,metal,x,y) for n,items in labels(ly,top).items() for metal,x,y in items)


def region(ly,top,layer):
    ix=ly.find_layer(layer)
    return db.Region(top.begin_shapes_rec(ix)) if ix is not None else db.Region()


def texts(ly,top,layer):
    ix=ly.find_layer(layer)
    out=Counter()
    if ix is not None:
        it=top.begin_shapes_rec(ix)
        it.shape_flags=db.Shapes.STexts
        while not it.at_end():
            s=it.shape().text
            out[(s.string,(it.trans()*s.trans).to_s())]+=1
            it.next()
    return out


def run():
    dest=REPORT/"res_hold_provisional"
    manifest=json.loads((dest/"manifest.json").read_bytes())
    old,baseline=open_archive(REPORT/"selector8_signoff/die.gds.gz",PARENT)
    cur,top=open_archive(dest/"die.gds.gz",manifest["gds_sha256"])
    if manifest["source_circuit_sha256"]!=DESIGN:raise ValueError("Wrong electrical source")
    placed=json.loads((RECORDS/"res_hold_placement.json").read_bytes())
    if placed["parent_gds_sha256"]!=PARENT or placed["source_schematic_sha256"]!=DESIGN:
        raise ValueError("Unrelated placement")
    a,b=count_instances(baseline),count_instances(top)
    if a-b or sum(a.values())!=59 or sum(b.values())!=63:
        raise ValueError("A parent macro was dropped or moved")
    extension=Counter()
    for (master,*_),count in (b-a).items():extension[master]+=count
    if extension!={"ne_res_hold_select":1,"sx_reset_tg":3}:raise ValueError(extension)
    if baseline.bbox()!=top.bbox() or top_ports(old,baseline)!=top_ports(cur,top):
        raise ValueError("Die box or original package label changed")
    layers={str(ly.get_info(i)):ly.get_info(i) for ly in (old,cur) for i in ly.layer_indexes()}
    added={}; retained_labels=0
    for key,layer in layers.items():
        parent=region(old,baseline,layer);now=region(cur,top,layer)
        if (parent-now).area():raise ValueError(("Removed parent material",key))
        old_labels=texts(old,baseline,layer)
        if old_labels-texts(cur,top,layer):raise ValueError(("Removed or moved label",key))
        retained_labels+=sum(old_labels.values())
        area=(now-parent).area()
        if area:added[key]=area/1e6
    anchors=parent_anchors(old,baseline)
    target=[[name,*pin] for name,pin in anchors.items()]
    instances={i.trans.to_s():i for i in top.each_inst()}
    for name,placement in placed["placements"].items():
        instance=instances[placement["transform"]]
        if instance.cell.name!=placement["master"]:raise ValueError((name,placement))
        pins=labels(cur,instance.cell,instance.dtrans)
        for pin,net_name in placement["pins"].items():
            pos,=pins[pin];target.append([net_name,name+":"+pin,*pos])
    if hashlib.sha256((json.dumps(target,indent=2)+"\n").encode()).hexdigest()!=placed["target_sha256"]:
        raise ValueError("Reconstructed terminal join list differs from placement")
    net,short,con=circuit(cur,top,target)
    if short or len(net)!=10 or any(len(x)!=1 for x in net.values()):raise ValueError("Routed topology changed")
    original=Connectivity(old,baseline)
    by_net={}
    for name,current in net.items():
        o=original.probe(*anchors[name][1:]) if name in anchors else None
        c=next(iter(current))
        extra={}
        for layer in ("m1","m2","m3","m4"):
            preserve=original.region(o,layer) if o is not None else db.Region()
            current=con.region(c,layer)
            if (preserve-current).area():raise ValueError(("Original copper lost",name,layer))
            new=(current-preserve).area()
            if new:extra[layer]=new/1e6
        by_net[name]=extra
    return dict(parent_gds_sha256=PARENT,gds_sha256=manifest["gds_sha256"],source_circuit_sha256=DESIGN,
                original_instances_preserved=sum(a.values()),additional_instances=dict(extension),
                same_die_box_nm=[top.bbox().left,top.bbox().bottom,top.bbox().right,top.bbox().top],
                original_polygons_preserved_layers=len(layers),original_hierarchical_label_locations=retained_labels,
                original_unique_package_names=len({port[0] for port in top_ports(old,baseline)}),
                original_package_label_locations=len(top_ports(old,baseline)),
                added_layer_area_um2=added,added_metal_area_by_net_um2=by_net,
                registered_connections=len(target),fully_connected_nets=len(net),physical_joins=sum(placed["unrouted_branches"].values()),
                purpose="Full parent-to-candidate polygon containment, macro transforms, package labels and added electrode connections from the two physical GDS files.")


if __name__=="__main__":
    report=run()
    (REPORT/"res_hold_provisional/overlay.json").write_text(json.dumps(report,indent=2)+"\n")
    print(report["gds_sha256"],report["original_polygons_preserved_layers"],"preserved GDS layers")
