"""Reinforce same-net landings and minimum-area islands at measured Magic marker coordinates."""
from collections import Counter, defaultdict
import argparse
import json
import re
import klayout.db as db
from source import BUILD, save
from connectivity import Connectivity, METALS
from route_split import circuit

def tables(log):
    entries=[]
    for why,boxes in re.findall(r"CHECKRULE \d+ (.*?)\nBOXES (.*?)\n",log):
        hit=re.match(r"Metal([1-4]) (spacing|width|minimum area|> 3um spacing)",why)
        if not hit:continue
        for coords in re.findall(r"\{([^{}]+)\}",boxes):
            entries.append(("m"+hit[1],hit[2],db.Box(*(5*int(v) for v in coords.split()))))
    return entries

def main(source,out,fill,targets_path="targets.json"):
    ly=db.Layout();ly.read(str(BUILD/(source+".gds")));top=ly.top_cell()
    log=BUILD/(source+"_drc")/"magic.log"
    if not log.exists():log=BUILD/(source+"_checks")/"magic.log"
    entries=tables(log.read_text()); con=Connectivity(ly,top)
    caps=db.Region(top.begin_shapes_rec(ly.layer(89,44)));grouped=defaultdict(db.Region)
    for metal,reason,box in entries:grouped[metal,reason].insert(box)
    used=Counter()
    for (metal,reason),mark in grouped.items():
        spacing=140 if metal in ("m1","m2") else 300
        width=150 if metal in ("m1","m2") else 300
        if reason=="> 3um spacing":continue
        for chunk in mark.sized(190).merged().each():
            site=db.Region(chunk.bbox().enlarged(240))
            window=db.Region(chunk.bbox().enlarged(2200))
            actual=(con.layers[metal]&window).merged(); comps=set()
            for p in (actual&site).decompose_trapezoids_to_region().each():
                c=p.bbox().center();n=con.probe(metal,.001*c.x,.001*c.y)
                if n is not None:comps.add(n)
            for net in comps:
                copper=(con.region(net,metal)&window).merged()
                other=actual-copper
                allowed=site-other.sized(spacing+5)
                if metal=="m3":allowed-=caps.sized(1340)
                if reason=="minimum area":
                    for piece in copper.interacting(mark).each():
                        cr=db.Region(piece); b=piece.bbox()
                        if cr.area()>=240000:continue
                        # Extend one side of the existing rectangular landing just far enough
                        # to pass the 0.24 square-micron rule, on the same conductor.
                        trials=[]
                        for growing in range(50,801,25):
                            for x,y,X,Y in ((-growing,0,0,0),(0,0,growing,0),(0,-growing,0,0),(0,0,0,growing),
                                             (-growing//2,0,growing//2,0),(0,-growing//2,0,growing//2)):
                                rect=db.Region(db.Box(b.left+x,b.bottom+y,b.right+X,b.top+Y))
                                add=rect-cr
                                if rect.area()>=248000 and (add-allowed).is_empty():trials.append((add.area(),add))
                            if trials:break
                        if trials:
                            area,solution=min(trials,key=lambda a:a[0])
                            top.shapes(ly.layer(*METALS[metal])).insert(solution);used[metal+":"+reason]+=1
                    continue
                if fill and reason=="width":
                    need=width//2+20
                    # Grow by a full line width locally to absorb subwidth slivers at T-junctions.
                    add=(copper.sized(need)-copper)&mark.sized(need)&allowed
                else:
                    size=spacing//2+35
                    add=(copper.sized(size).sized(-size)-copper)&allowed
                for p in add.each():
                    if db.Region(p).area():
                        top.shapes(ly.layer(*METALS[metal])).insert(p);used[metal+":"+reason]+=1
    targets=json.loads((BUILD/targets_path).read_text())
    groups,shorts,_=circuit(ly,top,targets)
    if shorts:raise ValueError(shorts)
    save(ly,top,BUILD/(out+".gds"))
    print("Added",dict(used),"remaining intended joins",sum(len(g)-1 for g in groups.values()),flush=True)
if __name__=="__main__":
    cli=argparse.ArgumentParser();cli.add_argument("source");cli.add_argument("out");cli.add_argument("--fill",action="store_true")
    cli.add_argument("--targets",default="targets.json")
    a=cli.parse_args();main(a.source,a.out,a.fill,a.targets)
