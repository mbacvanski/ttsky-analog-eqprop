"""Measure actual MIM footprint and candidate distances to UIO6 on the occupied pad-escape die."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import subprocess
import tempfile

import klayout.db as db

from filter_placement_survey import HERE, rc_layout
from rc_passives import MAGIC, PDK
from quiet_route import save

ROOT = HERE / 'evidence/entry_driver/layout_survey'
GDS = HERE / 'evidence/layout_5dd21c71_pad_escape/die.gds.gz'
CORNERS = (('cap_7',7.), ('cap_11',11.), ('cap_157',15.7))


def leaves(sizes=CORNERS, output=ROOT):
    with tempfile.TemporaryDirectory(prefix='native_mim_entry_') as scratch:
        t = Path(scratch)
        tcl = ['random seed 20261118', 'snap internal', 'load entry -force']
        for i,(name, side) in enumerate(sizes):
            tcl += [f'box {100*i}um 0um {100*i}um 0um', f'magic::gencell sky130::sky130_fd_pr__cap_mim_m3_1 I_{name} w {side} l {side} nx 1 ny 1 dummy 0 doports 1',
                    f'select cell I_{name}', 'set cname [instance list celldef]', f'cellname rename $cname {name}']
        tcl += ['writeall force']
        for name,_ in sizes:
            tcl += [f'load {name}', 'select top cell', f'gds write {t/(name+".gds")}', 'expand', 'drc euclidean on',
                'drc style drc(full)', 'drc check', 'drc catchup', 'box -100um -100um 100um 100um', 'set num 0',
                'foreach {r boxes} [drc listall why] {incr num [llength $boxes]}', f'puts "UNIT_DRC {name} $num"',
                'extract all', 'ext2spice lvs', 'ext2spice cthresh 0',f'ext2spice -o {t/(name+".spice")} {name}']
        (t/'generate.tcl').write_text('\n'.join([*tcl, 'quit -noprompt'])+'\n')
        with (t/'magic.log').open('wb') as log_stream:
            subprocess.run([str(MAGIC),'-dnull','-noconsole','-rcfile',str(PDK/'libs.tech/magic/sky130A.magicrc'),str(t/'generate.tcl')],
                    cwd=t,env={**os.environ,'PDK_ROOT':str(PDK.parent)},stdout=log_stream,stderr=subprocess.STDOUT,check=True)
        log=(t/'magic.log').read_text()
        for name, side in sizes:
            assert re.search(r'(?m)^UNIT_DRC '+name+r' 0$',log)
            lay=db.Layout()
            lay.read(str(t/(name+'.gds')))
            save(lay,lay.top_cell(),t/(name+'.gds'))
            unit=(t/(name+'.spice')).read_text()
            assert 'sky130_fd_pr__cap_mim_m3_1' in unit and re.search(r'\bl='+f'{side:g}'+r'(?:u)?\b',unit,re.I), unit[:400]
            (output/(name+'.gds.gz')).write_bytes(gzip.compress((t/(name+'.gds')).read_bytes(),mtime=0))
            (output/(name+'.spice')).write_text(unit.rstrip()+'\n')


def footprint(lay, top, cap, layers):
    # Test each of the relevant same-layer and MIM-edge keepouts independently.
    # Unlike combining them into one global silhouette, this permits unrelated
    # lower routing and upper metal outside the actual terminal/plate geometry.
    ports={s.text.string:db.Point(s.text.x,s.text.y) for s in cap.shapes(cap.layout().layer(71,5)).each() if s.is_text()}
    assert ports.keys()=={'C1','C2'}
    candidates=[]
    for rot in range(4):
        rot_tr=db.Trans(rot,False,0,0)
        allowed=db.Region(rc_layout.BOUNDARY)
        parts=[]
        for number,purpose,spacing in layers:
            leaf_layer = cap.layout().find_layer(number,purpose)
            if leaf_layer is None:
                continue
            shape=db.Region(cap.begin_shapes_rec(leaf_layer)).merged()
            if shape.is_empty():
                continue
            boxes=[p.bbox() for p in shape.each()]
            free=rc_layout.clear_floor(lay,top,[(number,purpose,spacing)])
            # Enclosing each connected plate/bar is conservative for nonrectangular masks.
            allowed &= rc_layout.translations(free,boxes,rot)
            parts.append((boxes,free))
        if allowed.is_empty():
            continue
        c1=rot_tr*ports['C1']
        target=rc_layout.PAD
        wants=[target-c1]
        best=None
        for origin in rc_layout.nearest_candidates(allowed,wants):
            x,y=(int(round(v/5))*5 for v in (origin.x,origin.y))
            tr=db.Trans(rot,False,x,y)
            p=tr*ports['C1']
            d=abs(p.x-target.x)+abs(p.y-target.y)
            key=(d,x,y)
            if best is not None and key>=best[0]:
                continue
            if any(not (db.Region(b.transformed(tr))-free).is_empty() for boxes,free in parts for b in boxes):
                continue
            best=(key,tr)
        if best:
            candidates.append((best[0][0],rot,best[1]))
    if not candidates:
        return None
    dist,rot,tr=min(candidates,key=lambda v:(v[0],v[1]))
    return dict(C1_to_pad_minimum_Manhattan_um=dist/1000,transform=tr.to_s(),
          bounds_nm=cap.bbox().transformed(tr).to_s(), original_cell_bounds_nm=cap.bbox().to_s(),
          ports_nm={k:[(tr*p).x,(tr*p).y] for k,p in ports.items()})


def survey():
    ROOT.mkdir(parents=True,exist_ok=True)
    leaves()
    raw=gzip.decompress(GDS.read_bytes())
    sha=hashlib.sha256(raw).hexdigest()
    assert sha=='5dd21c7163f4b8b119669090c4fa9834be422aaff571bd2990243136b4eaa71f'
    lay=db.Layout()
    lay.read_bytes(raw)
    results={}
    for name,side in CORNERS:
        leaf=db.Layout()
        data=gzip.decompress((ROOT/(name+'.gds.gz')).read_bytes())
        leaf.read_bytes(data)
        site=footprint(lay,lay.top_cell(),leaf.top_cell(),[(70,20,1400),(70,44,600),(71,20,430),(89,44,1100)])
        results[name]=dict(nominal_side_um=side, leaf_sha256=hashlib.sha256(data).hexdigest(),
                isolated_Magic_DRC_violations=0,candidate=site)
        print(name,site,flush=True)
    (ROOT/'placement.json').write_text(json.dumps(dict(GDS_sha256=sha,measured_port='internal TT UIO6', studies=results,
            scope='Per-layer physical obstruction and spacing search for real MIM leaves. The shortest placement distance is from the actual C1 electrode to the package pad. Connected routes, isolating supply or ground and full in-context mask checks remain separate.'),indent=1)+'\n')


if __name__=='__main__':
    survey()
