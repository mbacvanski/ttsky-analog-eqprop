"""Pack actual frozen macro groups and all new native-edge cells inside the unchanged Tiny Tapeout pin geometry."""
import argparse
import json
from pathlib import Path
import random

HERE=Path(__file__).resolve().parent
GAP=1600
EDGE=2400


def disjoint(a,b):
    return a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1]


def remove(free,occupied):
    result=[]
    x,y,X,Y=occupied
    for r in free:
        if disjoint(r,occupied):
            result.append(r);continue
        a,b,A,B=r
        if x>a:result.append((a,b,x,B))
        if X<A:result.append((X,b,A,B))
        if y>b:result.append((a,b,A,y))
        if Y<B:result.append((a,Y,A,B))
    result=sorted(set(result),key=lambda r:-(r[2]-r[0])*(r[3]-r[1]))
    out=[]
    for r in result:
        if r[2]-r[0]<1500 or r[3]-r[1]<1500:continue
        if not any(v[0]<=r[0] and v[1]<=r[1] and v[2]>=r[2] and v[3]>=r[3] for v in out):out.append(r)
    return out


def orientations(part,rails):
    w,h=part["w_nm"],part["h_nm"]
    out=[]
    for q in range(4):
        W,H=(w,h) if q%2==0 else (h,w)
        covered=[]
        for x,y,X,Y in part["m4_geometry_nm"]:
            covered.append(((x,X),(h-Y,h-y),(w-X,w-x),(y,Y))[q])
        banned=[]
        for a,A in rails:
            for b,B in covered:banned.append((a-B-650,A-b+650))
        merged=[]
        for a,b in sorted(banned):
            if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
            else:merged.append((a,b))
        valid=[];pos=EDGE
        for a,b in merged:
            if a>pos:valid.append((pos,a))
            pos=max(pos,b)
        if pos<=334880-EDGE-W:valid.append((pos,334880-EDGE-W))
        out.append((q,W,H,[(max(EDGE,x),min(334880-EDGE-W,X)) for x,X in valid
                              if max(EDGE,x)<=min(334880-EDGE-W,X)]))
    return out


def run(trials,seed,only,output,aligned):
    scene=json.loads((HERE/"build/native_placement_inputs.json").read_text())
    parts=scene["instances"]
    rails=[(p[1],p[3]) for net in ("VGND","VDPWR") for p in scene["ports_nm"][net]]
    orientations_by={k:orientations(v,rails) for k,v in parts.items()}
    rand=random.Random(seed)
    best=None
    for i in range(trials):
        # When possible conserve placements of original large blocks. Other trials
        # can move any macro, including complete H1/H2/Z with native helpers intact.
        hold=only if only else (("H1","H2","Z","BUF_REF","PADBUF","LADDER") if i%4==0 else
                                ("H1","H2","Z") if i%4==1 else ())
        placed={};free=[(EDGE-GAP//2,EDGE-GAP//2,334880-EDGE+GAP//2,225760-EDGE+GAP//2)]
        def insert(k,x,y,q,W,H):
            nonlocal free
            placed[k]={"x_nm":x,"y_nm":y,"rotation":q,"bbox_nm":[x,y,x+W,y+H]}
            free=remove(free,(x-GAP//2,y-GAP//2,x+W+GAP//2,y+H+GAP//2))
        for k in hold:
            v=parts[k];x,y=v["origin_nm"];insert(k,x,y,0,v["w_nm"],v["h_nm"])
        ranks={}
        for k,p in parts.items():
            w,h=p["w_nm"],p["h_nm"]
            rank=(max(w,h)**.7*(w*h)**.65 if i%5 else w*h)
            ranks[k]=rank*rand.uniform(.7,1.4)
        order=sorted((k for k in parts if k not in placed),key=ranks.get,reverse=True)
        mode=i%5
        for k in order:
            orig=parts[k]["origin_nm"]
            scores=[]
            for q,W,H,intervals in orientations_by[k]:
                if aligned and q%2 and (parts[k]["is_original"] or k.startswith(("ROWS","RW","R_FIXED","G_FIXED","HELP_1","HELP_2"))):continue
                for r in free:
                    l,b,R,T=r;a,z=l+GAP//2,R-GAP//2-W
                    if z<a or H+GAP>T-b:continue
                    for m,M in intervals:
                        lo=max(a,m);hi=min(z,M)
                        if lo>hi:continue
                        for x in {lo,hi}:
                            for y in {b+GAP//2,T-GAP//2-H}:
                                w=r[2]-r[0]-W-GAP;h=r[3]-r[1]-H-GAP
                                if mode in (0,1):score=min(w,h)+.015*max(w,h)
                                elif mode==2:score=(R-l)*(T-b)/(W*H)*12500
                                else:score=y+.07*x
                                edge= (min(abs(x-a),abs(z-x))*.4+
                                       min(y-b-GAP//2,T-GAP//2-H-y)*.2)
                                cost=score+edge+rand.random()*(80 if i<4 else 2400)
                                if parts[k]["is_original"]:cost+=.015*(abs(x-orig[0])+abs(y-orig[1]))
                                scores.append((cost,q,x,y,W,H))
            if scores:
                _,q,x,y,W,H=min(scores);insert(k,x,y,q,W,H)
        key=(sum(parts[k]["w_nm"]*parts[k]["h_nm"] for k in placed),len(placed))
        if best is None or key>best[0]:
            best=(key,placed)
            missing=[k for k in parts if k not in placed]
            result={"frozen_gds_sha256":scene["frozen_gds_sha256"],"schematic_sha256":scene["candidate_schematic_sha256"],
                    "all_costed_instances":list(parts),"floorplan_only":True,"trial_seed":seed,"trial":i,
                    "hold_fixed_groups":list(hold),"gap_nm":GAP,"outer_inset_nm":EDGE,"placements":placed,
                    "omitted":missing,"complete":not missing,
                    "scope":"Constructive envelope packing with real donor shapes; all 53 package pin coordinates and seven original supply/ground stripes. Rectangles can rotate as groups. Signal and supply connections between groups require new routing."}
            output.write_text(json.dumps(result,indent=2)+"\n")
            print(i, len(placed),"/",len(parts),"missing",missing,flush=True)
            if not missing: return


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--trials",type=int,default=1500);p.add_argument("--seed",type=int,default=20261118)
    p.add_argument("--hold",nargs="*",default=[]);p.add_argument("--output",type=Path,default=HERE/"build/placement.json");p.add_argument("--aligned",action="store_true");args=p.parse_args();run(args.trials,args.seed,tuple(args.hold),args.output,args.aligned)
