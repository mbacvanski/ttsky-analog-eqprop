"""Assemble the split-pair front end in a copy of the frozen TT GDS and export terminals for routing.

Terminal groups are read directly from the original lower-to-upper-metal connectivity before replacing
anything. They preserve nets severed by new placements as well as all unchanged hardwired circuitry.
"""
from collections import defaultdict
import gzip
import json
import re

import klayout.db as db

from baseline import BUILD, HERE, TOP, V4, source_gds
from connectivity import Connectivity, INDEX, METALS, as_boxes, labels

SPLIT = 'tt_um_mbacvanski_denseam_six'
V = 'vdd'; G = 'vss'
def complete(pins):
    return dict(pins, vdd=V,vss=G)

ASSIGN = {
    'WH1':complete({'dac':'dac','bw1':'wa1','bw2':'wb1','e1':'sel0','e2':'sel1','bias_prog':'bp','write':'inwrite','ref':'ref'}),
    'BIAS':{'bw1':'wa2','bw2':'wb2','e1':'sel2','e2':'sel3','write':'inwrite'},
    'EXT1':{'ext':'override1','en':'use1'}, 'EXT2':{'ext':'override2','en':'use2'},
    'MODE1':complete({'ladder':'sum1','ext':'dac','en':'ext_en1','out':'override1'}),
    'MODE2':complete({'ladder':'sum2','ext':'dac','en':'ext_en2','out':'override2'}),
    'BUF_BIAS1':{'plus_b':'second1'},'BUF_BIAS2':{'plus_b':'second2'},
}
for j in (1,2):
    for k,letter in enumerate('AB'):
        b=letter.lower()
        ASSIGN['X'+letter+str(j)]=complete({'base':'base'+str(j),'word':'w'+b+str(j),'bit':'s'+b,
                                        'bit_b':'ns'+b,'lane':('sum' if b=='a' else 'lane_b')+str(j)})
    ASSIGN['AVG'+str(j)]=complete({'base':'bias'+str(j)+'_in','word':'lane_b'+str(j),'bit':'avg'+str(j),
                                'bit_b':'navg'+str(j),'lane':'second'+str(j)})
CTRL_PINS='a b addr0 addr1 write rs wp bp ext_en1 ext_en2 ref_reset sel0 sel1 sel2 sel3 inwrite sa nsa sb nsb avg1 navg1 avg2 navg2 use1 use2 vdd vss'.split()
ASSIGN['CTRL']={k:k for k in CTRL_PINS}
EXTERNAL={'VDPWR':V,'VGND':G,'ui_in[0]':'a','ui_in[1]':'b','ui_in[4]':'ref_reset','ui_in[7]':'addr0',
          'uio_in[2]':'addr1','uio_in[4]':'bp','uio_in[5]':'write','uio_in[6]':'rs','uio_in[7]':'wp',
          'uio_in[0]':'ext_en1','uio_in[1]':'ext_en2'}
DIRECT={'LADDER:d1_tap':'base1','LADDER:d0_tap':'base2','BIAS:dac':'dac','BIAS:ref':'ref',
        'EXT1:out':'bias1_in','EXT2:out':'bias2_in'}

def read_net_locations(ly,top):
    saved=json.loads((HERE/'frozen_instances.json').read_text())
    names={(v['cell'],v['x_um'],v['y_um']):n for n,v in saved.items()}
    mag=V4/'floorplan/build/r6/layout'/f'{TOP}.mag'
    if mag.is_file():
        drawn={(c,round(int(x)*.005,3),round(int(y)*.005,3)):n
               for c,n,sx,x,sy,y in re.findall(
                   r'^use (\S+)\s+(\S+)\ntimestamp \d+\ntransform (-?1) 0 (-?\d+) 0 (-?1) (-?\d+)$',
                   mag.read_text(),re.M)}
        assert names==drawn
    mapping={}
    for i in top.each_inst():
        p=i.dtrans.disp
        key=(i.cell.name,round(p.x,3),round(p.y,3))
        mapping[names[key]]=i
    return mapping

def attach_new(ly,path,name):
    other=db.Layout();other.read(str(path))
    merged=ly.create_cell(name);merged.copy_tree(other.cell(name))
    return merged

def true_labels(cell_name,pinmap):
    # A duplicated word bank contains diagnostic names on internal gates as well as
    # pins. Its external words have labels at the M2 internal wire and the M1 pad.
    return {name:vals for name,vals in pinmap.items() if name in ASSIGN[cell_name]}

def real_sources():
    return {'sx_avg_ref':HERE.parent/'split_pair/layout/sx_avg_ref.gds',
            'sx_input_mux':HERE.parent/'layout_cells/gds/sx_input_mux.gds'}

def transform_at_box(cell,box,q):
    r=db.DTrans(q,False,0,0)
    bb=cell.dbbox().transformed(r)
    return db.DTrans(q,False,box[0]-bb.left,box[1]-bb.bottom)

def save(ly,top,path):
    opt=db.SaveLayoutOptions();opt.add_cell(top.cell_index());opt.gds2_write_timestamps=False
    ly.write(str(path),opt)

def main():
    ly=db.Layout();ly.read(str(source_gds()));top=ly.top_cell()
    old=Connectivity(ly,top)
    original=read_net_locations(ly,top)
    old_labels={n:labels(ly,i.cell,i.dtrans) for n,i in original.items()}
    outside=labels(ly,top)
    primary={}
    for pin,k in EXTERNAL.items():
        loc=outside[pin][0]; cluster=old.probe(*loc)
        assert cluster is not None and cluster not in primary,(pin,cluster)
        primary[cluster]=k
    for field,k in DIRECT.items():
        n,pin=field.split(':')
        clu=old.probe(*old_labels[n][pin][0])
        assert clu is not None and clu not in primary,(field,clu)
        primary[clu]=k
    orig_anchors=[]
    for n,ports in old_labels.items():
        for pin,locs in ports.items():
            # Debug labels inside replaced macro gates may legitimately change during
            # the split. Its eight original true ports all have explicit GDS labels.
            if n.startswith('BUF_BIAS') and pin not in ('plus','minus','az','az_b','vdd','vss','out','ref'):continue
            for k,loc in enumerate(locs):
                cluster=old.probe(*loc)
                if cluster is None:continue
                desired=ASSIGN.get(n,{}).get(pin,primary.get(cluster,'old_'+str(cluster)))
                orig_anchors.append((n,pin,k,desired))
    targets=[]
    for pin,locs in outside.items():
        if not re.fullmatch(r'(VGND|VDPWR|clk|ena|rst_n|(?:ua|ui_in|uo_out|uio_in|uio_out|uio_oe)\[\d+\])',pin):continue
        for k,loc in enumerate(locs):
            cluster=old.probe(*loc)
            if cluster is not None:
                targets.append([primary.get(cluster,'old_'+str(cluster)), 'TT:'+pin,*loc])
    src=real_sources()
    parts=json.loads((HERE/'split_placement.json').read_text())
    sources={name:attach_new(ly,path,name) for name,path in src.items()}
    reserve={}
    layers={n:ly.layer(*pr) for n,pr in METALS.items()}
    clear={n:db.Region() for n in METALS}
    hard_m4=db.Region()
    lef=(V4/'floorplan/tt_project_v4/lef'/f'{TOP}.lef').read_text().split('  OBS')[0]
    for coords in re.findall(r'\bRECT\s+([\d.− -]+)\s+;',lef):
        bounds=[float(v) for v in coords.split()]
        hard_m4.insert(db.DBox(*bounds).to_itype(ly.dbu))
    tform={}
    master={}
    for n,i in list(original.items()):
        if n not in ('BUF_BIAS1','BUF_BIAS2'):
            tform[n]=i.dtrans;master[n]=i.cell;continue
        dest=i.dtrans if n=='BUF_BIAS1' else transform_at_box(sources['sx_avg_ref'],parts[n]['box_um'],0)
        tform[n]=dest;master[n]=sources['sx_avg_ref']
        i.delete()
        top.insert(db.CellInstArray(master[n].cell_index(),dest.to_itype(ly.dbu)))
        reserve[n]=(n=='BUF_BIAS2')
    for n,p in parts.items():
        if n=='BUF_BIAS2':continue
        cellname=p['cell']
        if n=='CTRL':
            ctrl=HERE.parent/'circuit/digital_layout/sx_input_control.gds'
            if not ctrl.exists():continue
            sources[cellname]=attach_new(ly,ctrl,cellname)
        cell=sources[cellname] if cellname in sources else ly.cell(cellname)
        dest=transform_at_box(cell,p['box_um'],p['quarter_turns'])
        tform[n]=dest;master[n]=cell
        top.insert(db.CellInstArray(cell.cell_index(),dest.to_itype(ly.dbu)))
        reserve[n]=True
    # Remove parent metal only where it could hit new geometry. The GDS port stripes
    # and physical I/O terminals have their geometric positions fixed by Tiny Tapeout.
    width={'m1':.45,'m2':.45,'m3':.7,'m4':.7,'li':.3}
    for n,moved in reserve.items():
        tr=tform[n].to_itype(ly.dbu);cell=master[n]
        for k in ('li','m1','m2','m3','m4'):
            geom=db.Region(cell.begin_shapes_rec(layers[k])).transformed(tr)
            if not moved: # first split amplifier has all original external port positions
                base=db.Region(ly.cell('az_ref1').begin_shapes_rec(layers[k])).transformed(tr)
                geom=geom-base
            clear[k]+=geom.sized(round(width[k]/ly.dbu))
    # MIM top/bottom plates have a larger exclusion than ordinary M3.
    for n,moved in reserve.items():
        if moved:
            tr=tform[n].to_itype(ly.dbu)
            cap=db.Region(master[n].begin_shapes_rec(ly.layer(89,44))).transformed(tr)
            clear['m3']+=cap.sized(1500)
    # Reserve access above the digital pads, using the same vias and enclosures
    # as the standalone full-DRC controller access coupon.
    access_pads=[]
    if 'CTRL' in master:
        info=json.loads((HERE.parent/'circuit/digital_layout/geometry.json').read_text())
        for pin,pd in info['pins'].items():
            xmin,ymin,xmax,ymax=pd['rect'];local=db.DPoint((xmin+xmax)/2,(ymin+ymax)/2)
            pt=tform['CTRL']*local
            for lname,hw,hh in [('m2',.14,.185),('v2',.10,.10),('m3',.17,.17)]:
                geom=db.DBox(pt.x-hw,pt.y-hh,pt.x+hw,pt.y+hh).to_itype(ly.dbu)
                if lname=='m3':
                    if pin in ('vdd','vss'):
                        geom=db.DBox(pt.x-.17,pt.y-.17,pt.x+.55,pt.y+.17).to_itype(ly.dbu)
                    else:
                        geom=db.DBox(pt.x-.17,pt.y-.36,pt.x+.17,pt.y+.36).to_itype(ly.dbu)
                access_pads.append((lname,geom))
                if lname in ('m2','m3'):
                    clear[lname].insert(geom.enlarged(500 if lname=='m3' else 230))
    for n,names in [('BIAS',['e1','e2','write','bw1','bw2']),('EXT1',['ext','en']),('EXT2',['ext','en'])]:
        for p in names:
            for lay,x,y in old_labels[n][p]:
                if n=='BIAS' and lay!='m1':continue # only detach the external metal1 landing
                clear[lay].insert(db.DBox(x-.75,y-.37,x+.75,y+.37).to_itype(ly.dbu))
    for v,a,b in [('mcon','li','m1'),('v1','m1','m2'),('v2','m2','m3'),('v3','m3','m4')]:
        clear[v]=clear[a]+clear[b]
    clear['m4']-=hard_m4 # do not move or cut top-level rail and port shapes
    cut_info={}
    kept={}
    for k in METALS:
        ix=layers[k]
        before=db.Region(top.shapes(ix))
        # GDS may encode each net as one long polygon. Removing the offending
        # parent shape entire avoids unmanufacturable cut fragments and half vias.
        keep=before.not_interacting(clear[k])
        if k=='m4':keep+=before & hard_m4
        cut_info[k]=round((before-keep).area()*ly.dbu**2,3)
        kept[k]=keep.merged()
    # An original via whose parent landing was removed elsewhere on the same
    # parent polygon may now be at an open end. Drop the entire cut.
    total={}
    for k in ('li','m1','m2','m3','m4'):
        total[k]=kept[k].dup()
        for i in top.each_inst():
            total[k]+=db.Region(i.cell.begin_shapes_rec(layers[k])).transformed(i.trans)
        total[k].merge()
    for v,a,b in [('mcon','li','m1'),('v1','m1','m2'),('v2','m2','m3'),('v3','m3','m4')]:
        keep=db.Region()
        for poly in kept[v].each():
            box=poly.bbox()
            test=db.Region(box.enlarged(15))
            if (test-total[a]).is_empty() and (test-total[b]).is_empty():keep.insert(poly)
        kept[v]=keep
    for k in METALS:
        shapes=top.shapes(layers[k]);shapes.clear();shapes.insert(kept[k])
    for k,box in access_pads:top.shapes(layers[k]).insert(box)
    # Parent diagnostic text can be stranded by cutting a wire. TT port text, which
    # defines the package interface, always remains. Cell pin labels live in children.
    for metal in INDEX:
        ix=ly.layer(METALS[metal][0],5)
        for shape in list(top.shapes(ix).each()):
            if (shape.is_text() and shape.text.string.startswith('v4_')) or (not shape.is_text() and metal!='m4'):
                shape.delete()
    target_labels={n:labels(ly,cell,tform[n]) for n,cell in master.items()}
    for n,p,k,dest in orig_anchors:
        locs=target_labels[n].get(p,[])
        if k>=len(locs):continue
        targets.append([dest,f'{n}:{p}',*locs[k]])
    for n,pins in ASSIGN.items():
        if n not in master:continue
        for name,dest in pins.items():
            if (n in original and name in old_labels[n]):continue
            locs=target_labels[n].get(name,[])
            assert locs,(n,name)
            for loc in locs:targets.append([dest,f'{n}:{name}',*loc])
    top.name=SPLIT
    path=BUILD/'base.gds';save(ly,top,path)
    (BUILD/'targets.json').write_text(json.dumps(targets))
    print('baseline',len(old.nets),'metal networks. Candidate',len(targets),'landings; parent metal/via area cut',cut_info)
    after=Connectivity(ly,top)
    groups=defaultdict(lambda:defaultdict(list))
    for net,name,layer,x,y in targets:
        comp=after.probe(layer,x,y)
        if comp:groups[comp][net].append(name)
        else:print('stranded label',net,name,layer,x,y)
    bad={k:dict(v) for k,v in groups.items() if len(v)>1}
    (BUILD/'base_shorts.json').write_text(json.dumps(bad,indent=1))
    bynet=defaultdict(set)
    for k,gs in groups.items():
        for net in gs:bynet[net].add(k)
    print('unexpected connected nets',len(bad),'disconnected required nets',
          {k:len(v) for k,v in bynet.items() if len(v)>1})


if __name__=='__main__':
    main()
