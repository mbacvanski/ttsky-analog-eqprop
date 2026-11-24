"""Route package and macro pins on M1–M4; retain each verified join when another island is inaccessible."""
import argparse
from array import array
import ctypes as ct
import json
from pathlib import Path
import subprocess
import random
import sys
import klayout.db as db

from source import BUILD,HERE,SIX,save,sha
from connectivity import INDEX,METALS
import route_split as r

def partial_engine():
    original=SIX/"layout/trace_route.cpp"
    code=original.read_text()
    changes=[
        ("int k=0;","int k=0;set<int> inaccessible;"),
        ("if(s.empty())return -c;","if(s.empty())inaccessible.insert(c);"),
        ("int remaining=sets.size();","int remaining=sets.size()-inaccessible.size();"),
        ("for(auto &[c,s]:sets)size[dsu.root(c)]+=s.size();","for(auto &[c,s]:sets)if(!inaccessible.count(dsu.root(c)))size[dsu.root(c)]+=s.size();"),
        ("if(dsu.root(c)!=start){for(int p:s)","if(dsu.root(c)!=start&&!inaccessible.count(dsu.root(c))){for(int p:s)"),
        ("if(at[p]&&dsu.root(at[p])!=start)","if(at[p]&&dsu.root(at[p])!=start&&!inaccessible.count(dsu.root(at[p])))"),
        ("if(end<0)return -100000-start;","if(end<0){inaccessible.insert(start);--remaining;continue;}")]
    for left,right in changes:
        if code.count(left)!=1:raise ValueError("Inherited router has changed at "+left)
        code=code.replace(left,right)
    cpp=BUILD/"partial.cpp";lib=BUILD/"partial.so"
    if not cpp.exists() or cpp.read_text()!=code or not lib.exists():
        cpp.write_text(code)
        subprocess.run(["g++","-O3","-std=c++17","-fPIC","-shared","-DLOCAL_ROUTING","-o",str(lib),str(cpp)],check=True)
    return ct.CDLL(str(lib))

def run(opt):
    ly=db.Layout();ly.read(str(BUILD/(opt.source+".gds")));t=ly.top_cell()
    targets=json.loads((BUILD/getattr(opt,"targets","targets.json")).read_text());nets,shorts,con=r.circuit(ly,t,targets)
    if shorts:raise ValueError(shorts)
    order=[n for n,g in nets.items() if len(g)>1]
    if opt.only:order=[n for n in order if n in opt.only]
    prior=opt.priority.split(",") if opt.priority else []
    random.Random(opt.seed).shuffle(order)
    rank={n:i for i,n in enumerate(prior)}
    order.sort(key=lambda n:rank.get(n,len(rank)))
    ids={n:i+1 for i,n in enumerate(order)}
    obs=array("i")
    for li,lay in enumerate(INDEX):
        used=db.Region()
        for n in order:
            for group in nets[n]:
                copper=con.region(group,lay);used+=copper
                for b in r.boxes(copper):obs.extend((li,*b,ids[n],group))
        for b in r.boxes(con.layers[lay]-used):obs.extend((li,*b,0,0))
    for li,via in enumerate(("v1","v2","v3")):
        for b in r.boxes(con.layers[via]):obs.extend((li+4,*b,0,0))
    for b in r.boxes(db.Region(t.begin_shapes_rec(ly.layer(89,44)))):obs.extend((7,*b,0,0))
    nx=(334880-opt.offset)//opt.pitch+1;ny=(225760-opt.offset)//opt.pitch+1
    engine=partial_engine();engine.setup(opt.pitch,opt.offset,nx,ny,r.carray(obs),len(obs)//7)
    r.WIRE_HALF=(75,75,150,150);r.PAD_HALF=(165,185,205,205)
    lays=[ly.layer(*METALS[k]) for k in ("m1","m2","m3","m4","v1","v2","v3")]
    log={};routes={}
    for n in order:
        cnt=(ct.c_int*800)();joins=engine.route(ids[n],cnt,len(cnt));expected=len(nets[n])-1
        if joins<0:raise ValueError((n,joins))
        new=array("i");items=[]
        for j in range(joins):
            ln=engine.path_length(j);seq=(ct.c_int*ln)();engine.path_read(j,seq)
            for lay,x,y,X,Y in r.draw(seq,nx,ny,opt.pitch,opt.offset):
                t.shapes(lays[lay]).insert(db.Box(x,y,X,Y));new.extend((lay,x,y,X,Y,ids[n],0));items.append([lay,x,y,X,Y])
        if new:engine.add(r.carray(new),len(new)//7)
        log[n]={"joined":joins,"requested":expected};routes[n]=items
        print(n,joins,"/",expected,flush=True)
    final,shorts,_=r.circuit(ly,t,targets)
    opens={n:dict(v) for n,v in final.items() if len(v)>1}
    if shorts:raise ValueError(shorts)
    path=BUILD/(opt.out+".gds");save(ly,t,path)
    (BUILD/(opt.out+"_segments.json")).write_text(json.dumps(routes,separators=(",",":"))+"\n")
    (BUILD/(opt.out+".json")).write_text(json.dumps({"initial":len(order),"joins":log,"unconnected":opens,
                "unintended_shorts":shorts,"gds_sha256":sha(path)},indent=2)+"\n")
    print("VERIFY",len(opens),"open groups /",sum(len(v)-1 for v in opens.values()),"branches",flush=True)

if __name__=="__main__":
    cli=argparse.ArgumentParser();cli.add_argument("--source",default="access");cli.add_argument("--out",required=True);cli.add_argument("--targets",default="targets.json")
    cli.add_argument("--pitch",type=int,default=220);cli.add_argument("--offset",type=int,default=110)
    cli.add_argument("--priority",default="");cli.add_argument("--only",nargs="*");cli.add_argument("--seed",type=int,default=11)
    run(cli.parse_args())
