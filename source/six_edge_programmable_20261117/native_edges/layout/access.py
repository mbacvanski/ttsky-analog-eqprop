"""Provide legal via landing area on narrow package fingers and new decoder signals before global routing."""
import argparse
import json
import klayout.db as db

from source import BUILD, REPORT, pins, save
from connectivity import METALS
from route_split import circuit

def main():
    cli=argparse.ArgumentParser();cli.add_argument("--source",default="base");cli.add_argument("--out",default="access")
    opt=cli.parse_args()
    ly=db.Layout();ly.read(str(BUILD/(opt.source+".gds")));top=ly.top_cell()
    def rect(layer,b,move=None):
        box=db.Box(*b)
        if move is not None:box=box.transformed(move)
        top.shapes(ly.layer(*METALS[layer])).insert(box)
    for name,items in pins().items():
        if name in ("VGND","VDPWR"):continue
        for _,l,b,r,t in items:
            if t<220000:continue
            x=(l+r)//2;y=223975
            # The 0.3 um native M4 pin fingers cannot accept a cut on their original outline.
            rect("m4",(x-150,y,x+150,t-300));rect("m4",(x-260,y-260,x+260,y+260))
            rect("v3",(x-100,y-100,x+100,y+100));rect("m3",(x-250,y-260,x+250,y+260))
    pl=json.loads((REPORT/"placement.json").read_text())["physical_instances"]
    move=db.Trans.from_s(pl["DEC_MODE"]["transform"])
    for n,info in json.loads((BUILD/"decoder.json").read_text())["ports"].items():
        l,b,r,t=[round(z*1000) for z in info["rect_um"]];x=(l+r)//2;y=(b+t)//2
        if n in ("vdd","vss"):continue
        rect("m2",(x-140,y-185,x+140,y+185),move)
        rect("v2",(x-100,y-100,x+100,y+100),move)
        rect("m3",(x-170,y-365,x+170,y+365),move)
    targets=json.loads((BUILD/"targets.json").read_text())
    _,shorts,_=circuit(ly,top,targets)
    if shorts:raise ValueError(shorts)
    save(ly,top,BUILD/(opt.out+".gds"))

if __name__=="__main__":main()
