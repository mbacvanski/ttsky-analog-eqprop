"""Place the three precision resistors and MIM on the 1b die and route the six filter conductors."""
import argparse
from collections import Counter
import hashlib
import json

import klayout.db as db

from quiet_route import BUILD, GDS, INDEX, LAYERS, METALS, WIRES, physical_parent, points, polygon_of, route, save
from rc_passives import SOURCE, WORK
from route_split import circuit

BOUNDARY = db.Box(1800, 1800, 333080, 223960)
PAD = db.Point(99820, 225260)
LOCAL_N = db.Point(71575, 164095)
LOCAL_P = db.Point(73180, 164075)


def write(path, data):
    path.write_text(json.dumps(data, indent=2)+"\n")


def remove_launches(ly, top, pins):
    groups, shorts, con = circuit(ly, top, pins)
    if shorts or any(len(g) != 1 for g in groups.values()):
        raise ValueError("The parent must begin fully connected")
    owners = {next(iter(groups[name])):name for name in WIRES}
    # Removing these three original trunks splits the board input and two logic outputs
    # from their loads. All original cell conductors and physical package ports remain.
    changed = Counter()
    for metal in LAYERS:
        keys = {name: con.region(k,metal) for k,name in owners.items()} if metal in INDEX else {}
        shapes = top.shapes(ly.layer(*METALS[metal]))
        kl = ly.find_layer(METALS[metal][0],16)
        keep = db.Region(top.shapes(kl)).merged() if kl is not None and metal in INDEX else db.Region()
        erase = []
        put = db.Region()
        for shape in shapes.each():
            bbox = shape.bbox()
            copper = db.Region(polygon_of(shape))
            for n in WIRES:
                if metal in INDEX:
                    if not (copper & keys[n]).area():
                        continue
                    cut = copper - keep
                    if not cut.area():
                        continue
                    put += copper - cut
                else:
                    m = int(metal[-1]); p = bbox.center()
                    node = con.probe("m"+str(m+1),p.x/1000,p.y/1000)
                    if owners.get(node) != n:
                        continue
                erase.append(shape)
                changed[n,metal] += 1
                break
        for shape in erase:
            shape.delete()
        shapes.insert(put)
    targets = []
    for name, marker, metal, x, y in pins:
        if name == "res_sel" and not marker.startswith("TT:"):
            name = "res_filtered"
        if name in ("weak", "weak_b") and marker.startswith("SELECT:"):
            name += "_src"
        targets.append([name,marker,metal,x,y])
    nets, blocked, _ = circuit(ly,top,targets)
    if blocked:
        raise ValueError(("A physical source and its downstream trunk are still joined",blocked))
    if any(len(nets[n]) != 1 for n in ("weak_src","weak_b_src","res_sel")):
        raise ValueError("The three source terminals are not isolated")
    return targets, {n:{m:changed[n,m] for m in LAYERS} for n in WIRES}


def clear_floor(ly, top, spacing):
    blocked = db.Region()
    for number, purpose, gap in spacing:
        ix = ly.find_layer(number,purpose)
        if ix is not None:
            blocked += db.Region(top.begin_shapes_rec(ix)).sized(gap)
    return db.Region(BOUNDARY) - blocked.merged()


def translations(space, pieces, rot):
    result = None
    for piece in pieces:
        b = piece.transformed(db.Trans(rot,False,0,0))
        c = b.center()
        free = space.sized(-(b.width()//2+5), -(b.height()//2+5), 2)
        free = free.moved(-c.x, -c.y)
        result = free if result is None else result & free
    return result.merged()


def nearest_candidates(allowed, wants):
    for polygon in allowed.each():
        for point in polygon.each_point_hull():
            yield point
        for target in wants:
            if polygon.inside(target):
                yield target
            for edge in polygon.each_edge():
                a,b = edge.p1,edge.p2
                if a.x == b.x:
                    yield db.Point(a.x,min(max(target.y,min(a.y,b.y)),max(a.y,b.y)))
                elif a.y == b.y:
                    yield db.Point(min(max(target.x,min(a.x,b.x)),max(a.x,b.x)),a.y)


def place(cell, free, pieces, pins, destinations, access=None):
    best = None
    for rot in range(4):
        origin = db.Trans(rot,False,0,0)
        allowed = translations(free,pieces,rot)
        if access is not None:
            for xy in pins.values():
                pin=origin*db.Point(*xy)
                allowed=allowed & access.moved(-pin.x,-pin.y)
        wants = []
        for role,(target,weight) in destinations.items():
            pin = origin*db.Point(*pins[role])
            wants.append(db.Point(target.x-pin.x,target.y-pin.y))
        viewed = set()
        for pos in nearest_candidates(allowed,wants):
            x,y = (int(round(v/5))*5 for v in (pos.x,pos.y))
            if (x,y) in viewed:
                continue
            viewed.add((x,y))
            tr = db.Trans(rot,False,x,y)
            score = 0
            for name,(q,importance) in destinations.items():
                p=tr*db.Point(*pins[name])
                score += importance*(abs(p.x-q.x)+abs(p.y-q.y))
            order=score,rot,x,y
            if best is not None and best<=order:
                continue
            if any((db.Region(b.transformed(tr))-free).area() for b in pieces):
                continue
            best=order
    if best is None:
        raise ValueError(("Unable to fit the real passive geometry",cell.name))
    cost,rot,x,y=best
    return db.Trans(rot,False,x,y),cost


def build():
    ly,top = physical_parent()
    targets, cuts = remove_launches(ly,top,points(ly,top,include_analog=True))
    bankdata=json.loads((WORK/"bank.json").read_bytes())
    physical={}
    for key,reference in (("R","ne_rc_high_poly"),("C","ne_rc_mim")):
        library=db.Layout()
        libpath=WORK/(reference+".gds")
        library.read(str(libpath))
        cell=ly.create_cell(reference)
        cell.copy_tree(library.top_cell())
        access=None
        if key=="R":
            if hashlib.sha256(libpath.read_bytes()).hexdigest()!=bankdata["gds_sha256"]:
                raise ValueError("Precision resistor bank differs from its isolated receipt")
            pins=bankdata["pin_m1_nm"]
            floor=clear_floor(ly,top,[
                (64,20,1300),(65,20,650),(65,44,550),(66,20,510),(66,44,390),
                (67,20,190),(67,44,200),(68,20,210),(79,20,1300),(86,20,1300),
            ])
            # Below the upper supply corridor, six insulated control routes can
            # independently reach all six resistor terminals.
            floor=floor & db.Region(db.Box(1800,1800,333080,188000))
            # Each precision end gets a real M1-M4 escape. Keep its complete via
            # stack clear of existing tracks, other via cuts and MIM plate holes.
            access=clear_floor(ly,top,[(68,20,390),(69,20,400),(70,20,560),(71,20,560),
                                       (68,44,320),(69,44,370),(70,44,400),(89,44,1650)])
            pieces=[db.Box(-670,-37230,1500,37230),db.Box(990,25770,2330,37230)]
            objectives={"res_sel":(PAD,.3),"weak_src":(LOCAL_N,3),"weak_b_src":(LOCAL_P,3),
                        "weak":(db.Point(58000,104000),1),"weak_b":(db.Point(58000,104000),1)}
        else:
            pins={s.text.string:(s.text.x,s.text.y) for s in cell.shapes(ly.layer(71,5)).each() if s.is_text()}
            pins={"res_filtered":pins["C1"],"vss":pins["C2"]}
            floor=clear_floor(ly,top,[(70,20,1400),(70,44,600),(71,20,430),(89,44,1100)])
            pieces=[cell.bbox()]
            objectives={"res_filtered":(PAD,1)}
        tr,cost=place(cell,floor,pieces,pins,objectives,access)
        top.insert(db.CellInstArray(cell.cell_index(),tr))
        layout_pins={}
        for name,pos in pins.items():
            q=tr*db.Point(*pos)
            if key=="R":
                for metal,half in zip(("m1","v1","m2","v2","m3","v3","m4"),(170,75,190,100,205,100,205)):
                    top.shapes(ly.layer(*METALS[metal])).insert(db.Box(q,q).enlarged(half))
            terminal=name if key=="R" else ("C1" if name=="res_filtered" else "C2")
            targets.append([name,key+":"+terminal,"m1" if key=="R" else "m4",q.x/1000,q.y/1000])
            layout_pins[name]=[q.x,q.y]
        physical[key]=dict(cell=reference,transform=tr.to_s(),bbox_nm=cell.bbox().transformed(tr).to_s(),pins_nm=layout_pins)
    groups,shorts,_=circuit(ly,top,targets)
    if shorts:
        raise ValueError(("Physical passive collision",shorts))
    if not all(len(groups[n])>1 for n in ("res_filtered","res_sel","weak","weak_b","weak_src","weak_b_src","vss")):
        raise ValueError("A passive port did not form an independent route terminal")
    out=BUILD/"quiet_rc_unrouted.gds"
    save(ly,top,out)
    report=dict(parent_gds_sha256=GDS,source_sha256=SOURCE,physical=physical,cut_top_shapes=cuts,replaced_trunks=list(WIRES),
                gds_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),join_count={k:len(v)-1 for k,v in groups.items() if len(v)>1})
    write(BUILD/"quiet_rc_placement.json",report)
    write(BUILD/"quiet_rc_targets.json",targets)
    print(json.dumps(report,indent=1))


def finish():
    """Move one newly placed M2–M3 via landing 60 nm away from a wide existing M3 plate."""
    ly=db.Layout()
    ly.read(str(BUILD/"quiet_rc_preheal.gds"))
    top=ly.top_cell()
    targets=json.loads((BUILD/"quiet_rc_targets.json").read_bytes())
    groups,shorts,con=circuit(ly,top,targets)
    x,y=268510,134530
    memberships={n for n,g in groups.items() if con.probe("m3",x/1000,y/1000) in g}
    if shorts or len(memberships)!=1:
        raise ValueError(("Ambiguous physical RC route for the spacing repair",memberships))
    for layer,half in (("m2",185),("v2",100),("m3",205)):
        shapes=top.shapes(ly.layer(*METALS[layer]))
        old=db.Region(db.Box(x-half,y-half,x+half,y+half))
        new=old.moved(60,0)
        original=db.Region(shapes)
        if not (old-original).is_empty() or (layer=="v2" and (original & new).area()>=old.area()):
            raise ValueError(("The original via stack is not on these verified coordinates",layer))
        cut=old-new
        touched=[]
        for shape in shapes.each_touching(cut.bbox()):
            copper=db.Region(polygon_of(shape))
            if not (copper & cut).is_empty():
                touched.append((shape,copper-cut))
        for shape,kept in touched:
            shape.delete()
            shapes.insert(kept)
        shapes.insert(new)
    after,other,_=circuit(ly,top,targets)
    if other or any(len(v)!=1 for v in after.values()):
        raise ValueError("The 60 nm landing move changed a physical connection")
    save(ly,top,BUILD/"quiet_rc_healed.gds")
    print("Moved one M2–M3 landing 60 nm on",memberships.pop(),flush=True)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=["place","route","finish"])
    args=cli.parse_args()
    if args.action=="place":
        build()
    elif args.action=="finish":
        finish()
    else:
        route("quiet_rc_routed",220,110,85,True,source="quiet_rc_unrouted",target_file="quiet_rc_targets.json",
              wires=("res_sel","weak_b","weak","weak_src","weak_b_src","res_filtered","vss"),physical_points=True)
