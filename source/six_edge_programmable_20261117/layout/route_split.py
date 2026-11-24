"""Route the measured terminal groups of the actual split-pair tile on four metal layers.

Each inherited electrically connected metal component is a multi-source routing terminal.
The search respects actual lower- and upper-layer copper in every frozen block plus MIM
plate keepouts. The final independent whole-chip DRC and device LVS are separate checks.
"""
import argparse
from array import array
from collections import defaultdict
import ctypes as ct
import json
from pathlib import Path
import random
import subprocess
import klayout.db as db
from baseline import HERE, BUILD
from connectivity import Connectivity, INDEX, METALS
from prepare_split import save


def boxes(region):
    return [(z.left,z.bottom,z.right,z.top) for p in region.merged().decompose_trapezoids_to_region().each() for z in [p.bbox()]]


def api():
    lib=BUILD/'trace_route.so'
    if not lib.exists() or lib.stat().st_mtime<(HERE/'trace_route.cpp').stat().st_mtime:
        subprocess.run(['g++','-O3','-std=c++17','-fPIC','-shared','-o',str(lib),str(HERE/'trace_route.cpp')],check=True)
    return ct.CDLL(str(lib))


def carray(flat):
    return (ct.c_int*len(flat)).from_buffer(flat)


def circuit(ly,t,ports):
    con=Connectivity(ly,t);by_net=defaultdict(lambda:defaultdict(list)); seen=defaultdict(set)
    for net,label,lay,x,y in ports:
        c=con.probe(lay,x,y)
        if c is None:raise ValueError(f'floating {net} at {label}')
        by_net[net][c].append(label);seen[c].add(net)
    shorts={k:sorted(v) for k,v in seen.items() if len(v)>1}
    return by_net,shorts,con


WIRE_HALF=(150,150,200,200)
PAD_HALF=(230,230,270,270)


def draw(path,nx,ny,pitch,offset):
    nplane=nx*ny
    def loc(p):
        lay,k=divmod(p,nplane);iy,ix=divmod(k,nx)
        return lay,ix*pitch+offset,iy*pitch+offset
    pts=list(map(loc,path))
    # Square enclosures permit either metal exit direction.
    out=[]
    def pad(l,x,y,r):out.append((l,x-r,y-r,x+r,y+r))
    def line(l,x,y,X,Y):
        half=WIRE_HALF[l]
        out.append((l,min(x,X)-half,min(y,Y)-half,max(x,X)+half,max(y,Y)+half))
    a=pts[0];prev=a;direction=None
    for n in pts[1:]:
        l,x,y=prev;L,X,Y=n
        if l!=L:
            if a!=prev:line(l,*a[1:],x,y)
            lower=min(l,L)
            pad(l,x,y,PAD_HALF[l]);pad(L,x,y,PAD_HALF[L])
            pad(4+lower,x,y,[75,100,100][lower])
            a=n;direction=None
        else:
            vertical=y!=Y
            if direction is not None and direction!=vertical:
                line(l,*a[1:],x,y);a=prev
            direction=vertical
        prev=n
    if a!=prev:line(a[0],*a[1:],*prev[1:])
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--pitch',type=int,default=300);p.add_argument('--offset',type=int,default=150)
    p.add_argument('--width-nm',type=int,default=334880);p.add_argument('--height-nm',type=int,default=225760)
    p.add_argument('--shuffle',type=int,default=0);p.add_argument('--source',default='base');p.add_argument('--out',default='routed')
    args=p.parse_args()
    ly=db.Layout();ly.read(str(BUILD/(args.source+'.gds')));assert abs(ly.dbu-.001)<1e-9
    top=ly.top_cell();targets=json.loads((BUILD/'targets.json').read_text())
    nets,shorts,con=circuit(ly,top,targets);assert not shorts,shorts
    active=[k for k,v in nets.items() if len(v)>1];netid={n:i+1 for i,n in enumerate(active)}
    ob=array('i');met=list(INDEX)
    for i,l in enumerate(met):
        owned=db.Region()
        for n in active:
            for comp in nets[n]:
                s=con.region(comp,l);owned+=s
                for b in boxes(s):ob.extend((i,*b,netid[n],comp))
        base=con.layers[l]-owned
        for b in boxes(base):ob.extend((i,*b,0,0))
    for i,l in enumerate(['v1','v2','v3']):
        for b in boxes(con.layers[l]):ob.extend((i+4,*b,0,0))
    caps=db.Region(top.begin_shapes_rec(ly.layer(89,44)))
    for b in boxes(caps):ob.extend((7,*b,0,0))
    router=api();pitch=args.pitch;off=args.offset;nx=(args.width_nm-off)//pitch+1;ny=(args.height_nm-off)//pitch+1
    router.setup(pitch,off,nx,ny,carray(ob),len(ob)//7)
    print('obstacles',len(ob)//7,'nets',len(active),'grid',nx,ny,flush=True)
    # Route supply ties and disrupted native wires first. Subsequent access is tested from
    # all geometrically available points of an entire connected conductor.
    def priority(n):
        if n in ('vdd','vss'):return (0,n)
        if n.startswith('old_'):return (2,n)
        if n.startswith(('sel','avg','navg','s','ns','use','inwrite')):return (3,n)
        return (4,n)
    order=sorted(active,key=priority)
    if args.shuffle:random.Random(args.shuffle).shuffle(order)
    puts=[ly.layer(*METALS[l]) for l in ['m1','m2','m3','m4','v1','v2','v3']]
    receipts={};failed=[]
    for net in order:
        counts=(ct.c_int*600)();rc=router.route(netid[net],counts,600)
        access=dict(zip(counts[::2],counts[1::2]));access.pop(0,None)
        if rc<0:
            tag=-rc if rc> -100000 else -100000-rc
            failed.append(net)
            print('OPEN',net,rc,nets[net].get(tag),access,flush=True)
            receipts[net]={'code':rc,'component':tag,'labels':nets[net].get(tag),'access':access}
            continue
        added=array('i');length=0;cuts=0
        for j in range(rc):
            plen=router.path_length(j);node=(ct.c_int*plen)();router.path_read(j,node)
            drawn=draw(node,nx,ny,pitch,off)
            for l,x,y,X,Y in drawn:
                top.shapes(puts[l]).insert(db.Box(x,y,X,Y))
                added.extend((l,x,y,X,Y,netid[net],0))
                if l>=4:cuts+=1
            length+=(plen-1)*pitch
        router.add(carray(added),len(added)//7)
        receipts[net]={'connections':rc,'vias':cuts,'grid_path_steps_um':length/1000}
        print('wired',net,rc,cuts,flush=True)
    path=BUILD/(args.out+'.gds');save(ly,top,path)
    final,shorts,_=circuit(ly,top,targets)
    open_nets={n:dict(v) for n,v in final.items() if len(v)>1}
    report={'initial_groups':len(active),'initial_branches':sum(len(nets[n])-1 for n in active),
            'grid_pitch_nm':pitch,'grid_offset_nm':off,'routing':receipts,
            'unconnected':open_nets,'unintended_shorts':shorts}
    (BUILD/(args.out+'.json')).write_text(json.dumps(report,indent=1)+'\n')
    print('VERIFY',len(open_nets),'open groups,',len(shorts),'shorts',flush=True)


if __name__=='__main__':
    main()
