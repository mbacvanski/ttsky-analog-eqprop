"""Route the unchanged four-passive circuit with its three resistor inputs near their actual drivers."""
import argparse
from array import array
from collections import Counter
import json
from pathlib import Path
import klayout.db as db

from filter_placement_survey import quiet_route
from route_split import circuit


NETS = ("weak_src", "weak_b_src", "res_sel", "six", "weak_b", "weak", "res_filtered", "vdd", "vss")


def record_tracks(folder, stem, joined, call):
    """Measure the actual routed paths separately from the placement lower bounds."""
    original=quiet_route.grid.draw
    links=[]
    def draw(path,nx,ny,pitch,offset):
        name=joined[len(links)]
        walk=[]
        for node in path:
            layer, within=divmod(node,nx*ny)
            y,x=divmod(within,nx)
            walk.append((layer,x*pitch+offset,y*pitch+offset))
        lengths=Counter()
        vias=Counter()
        for (layer,x,y),(other,X,Y) in zip(walk,walk[1:]):
            if layer==other:
                lengths["m"+str(layer+1)]+=abs(X-x)+abs(Y-y)
            else:
                assert (x,y)==(X,Y) and abs(layer-other)==1
                vias["v"+str(min(layer,other)+1)]+=1
        links.append(dict(net=name,new_parallel_to_wafer_travel_um=sum(lengths.values())/1000,
                          by_layer_um={k:v/1000 for k,v in lengths.items()},via_count=dict(vias),
                          start_and_end_layer_xy_nm=[walk[0],walk[-1]]))
        return original(path,nx,ny,pitch,offset)
    quiet_route.grid.draw=draw
    try:
        call()
    finally:
        quiet_route.grid.draw=original
    assert len(links)==len(joined)
    (folder/(stem+"_tracks.json")).write_text(json.dumps(dict(
        paths=links, scope="Length of each added grid path between actual existing GDS contact-metal regions. Includes detours, separate conductor layers and via counts. The pre-existing terminal metal and device interiors are outside these new lengths."), indent=1)+"\n")


def route(folder, stem, pitch, offset, m4_cost):
    quiet_route.BUILD = folder
    old = quiet_route.analog_cost

    def protect_existing_core(con, nets, weight):
        # Moving the decoder temporarily opens its one SIX input. The six-weight
        # analog circuit is attached to the larger of the two M2 conductor trees.
        # Keep that entire tree in the routing proximity penalty.
        branches = nets["six"]
        assert len(branches) == 2
        main = max(branches, key=lambda node: con.region(node, "m2").area())
        return old(con, {**nets, "six": {main}}, weight)

    quiet_route.analog_cost = protect_existing_core
    try:
        counts=json.loads((folder/"source_coupon_joins.json").read_bytes())
        links=[n for n in NETS for _ in range(counts[n])]
        record_tracks(folder,stem,links,lambda:quiet_route.route(
            stem,pitch,offset,85,True,source="source_coupon",target_file="source_coupon_targets.json",
            wires=NETS,physical_points=True,m4_cost=m4_cost,
            per_wire_m3={name:(70 if name=="weak_b" else 0) for name in NETS}))
    finally:
        quiet_route.analog_cost = old


def reroute(folder, source, stem, net, pitch, offset, prices, field_weight, strip_only=False):
    """Keep every other conductor in place, including the two already-short CMOS stubs."""
    quiet_route.BUILD = folder
    base = db.Layout()
    base.read(str(folder/"source_coupon.gds"))
    layout = db.Layout()
    layout.read(str(folder/(source+".gds")))
    top = layout.top_cell()
    pins = json.loads((folder/"source_coupon_targets.json").read_bytes())
    nets, shorts, copper = circuit(layout, top, pins)
    assert not shorts and all(len(v)==1 for v in nets.values())
    owner, = nets[net]
    for layer in quiet_route.LAYERS:
        li = quiet_route.METALS[layer]
        shapes = top.shapes(layout.layer(*li))
        protected = db.Region(base.top_cell().shapes(base.layer(*li))).merged()
        if layer in quiet_route.INDEX:
            selected = copper.region(owner, layer) - protected
        else:
            selected = db.Region()
            for via in shapes.each():
                center = via.bbox().center()
                if copper.probe("m"+str(int(layer[-1])+1), center.x/1000, center.y/1000) == owner:
                    selected.insert(quiet_route.polygon_of(via))
            selected -= protected
        moves=[]
        for shape in shapes.each():
            if shape.is_text():
                continue
            one = db.Region(quiet_route.polygon_of(shape))
            if (one & selected).area():
                moves.append((shape, one-selected))
        for shape, rest in moves:
            shape.delete()
            shapes.insert(rest)
    after, shorts, _ = circuit(layout, top, pins)
    want=2 if net=="res_sel" else 4
    assert not shorts and all(len(v)==(want if k==net else 1) for k,v in after.items()), (after, shorts)
    opened=stem+"_open"
    quiet_route.save(layout,top,folder/(opened+".gds"))
    if strip_only:
        return
    old=quiet_route.analog_cost
    def costs(con,nets,weight):
        data=old(con,nets,weight) if field_weight else array("i")
        for i,price in enumerate(prices):
            if price:
                data.extend((i,0,0,334880,225760,price))
        return data
    quiet_route.analog_cost=costs
    try:
        record_tracks(folder,stem,[net]*(want-1),lambda:quiet_route.route(
            stem,pitch,offset,field_weight,True,source=opened,target_file="source_coupon_targets.json",
            wires=(net,),physical_points=True))
    finally:
        quiet_route.analog_cost=old


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch_folder", type=Path)
    parser.add_argument("--stem", default="at_source")
    parser.add_argument("--pitch", default=180, type=int)
    parser.add_argument("--offset", default=90, type=int)
    parser.add_argument("--m4-cost", default=180, type=int)
    parser.add_argument("--reroute", choices=("weak","weak_b","res_filtered","res_sel"))
    parser.add_argument("--source", default="at_source_fill1")
    parser.add_argument("--prices", nargs=4, type=int, default=(0,0,0,0))
    parser.add_argument("--field-weight", type=int, default=85)
    parser.add_argument("--strip-only", action="store_true",
                        help="Keep the verified terminals and remove just the selected top-level route")
    args = parser.parse_args()
    if args.reroute:
        reroute(args.scratch_folder.resolve(),args.source,args.stem,args.reroute,args.pitch,args.offset,
                args.prices,args.field_weight,args.strip_only)
    else:
        route(args.scratch_folder.resolve(), args.stem, args.pitch, args.offset, args.m4_cost)
