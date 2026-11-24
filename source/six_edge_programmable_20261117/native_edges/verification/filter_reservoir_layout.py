"""Place and connect a positive-plate capacitor at the diagnosed pad or local reference on the sealed 5dd mask."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import klayout.db as db

import filter_reservoir_source
from filter_placement_survey import HERE, quiet_route, rc_layout
from filter_source_coupon import prepare
from filter_source_layout import record_tracks
from route_split import circuit


BASE = HERE / 'evidence/layout_5dd21c71_pad_escape'
SQUARE = HERE / 'evidence/entry_driver/layout_survey/cap_157.gds.gz'
PARENT = '5dd21c7163f4b8b119669090c4fa9834be422aaff571bd2990243136b4eaa71f'
MIM = '19149a2910226583741646bc623e6083c5b102a355b704cf890e241150109584'


def sealed(path, sha):
    raw = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == sha
    return raw


def location(layout, top, cap, pins, electrode, owners):
    """Include the die's actual REF and ground locations in the choice of site."""
    cap_ports = {s.text.string:db.Point(s.text.x,s.text.y) for s in cap.shapes(layout.layer(71,5)).each() if s.is_text()}
    assert cap_ports.keys() == {'C1','C2'}
    if electrode == 'res_sel':
        targets = [rc_layout.PAD]
    else:
        targets = [db.Point(round(x*1000),round(y*1000)) for net,_,_,x,y in pins if net == electrode]
    layers = [(70,20,1400), (70,44,600), (71,20,430), (89,44,1100)]
    rules = []
    for layer,purpose,gap in layers:
        pieces = [p.bbox() for p in db.Region(cap.begin_shapes_rec(layout.layer(layer,purpose))).merged().each()]
        if pieces:
            rules.append((pieces,rc_layout.clear_floor(layout,top,[(layer,purpose,gap)])))
    original_sites = {}
    for net in (electrode,'vss'):
        items = []
        for m in ('m4','m3','m2','m1'):
            rects = list(owners[net][m].decompose_trapezoids_to_region().each())
            items += [(p.bbox(), m) for p in rects]
            if net == electrode and electrode == 'ref':
                targets.extend(p.bbox().center() for p in sorted(rects,key=lambda p:p.area(),reverse=True)[:5])
        original_sites[net] = items
    assert targets and all(original_sites.values())

    def distance(p, rects):
        return min(sum((max(b.left-p.x,0,p.x-b.right), max(b.bottom-p.y,0,p.y-b.top))) for b,_ in rects)

    results = []
    for rot in range(4):
        spin = db.Trans(rot,False,0,0)
        free = db.Region(rc_layout.BOUNDARY)
        for shapes,area in rules:
            free &= rc_layout.translations(area,shapes,rot)
        if free.is_empty():
            continue
        aims = [p-spin*cap_ports['C1'] for p in targets]
        seen = set()
        candidates = list(rc_layout.nearest_candidates(free,aims))
        for q in candidates:
            x,y = round(q.x/5)*5,round(q.y/5)*5
            if (x,y) in seen:
                continue
            seen.add((x,y))
            tr = db.Trans(rot,False,x,y)
            a,b = tr*cap_ports['C1'], tr*cap_ports['C2']
            da,dbulk = distance(a,original_sites[electrode]), distance(b,original_sites['vss'])
            # The pad route is a full-swing aggressor. For REF, both paths are quiet,
            # and short grounded bottom-plate wiring is also desirable.
            cost = 10*da + dbulk if electrode=='res_sel' else 2*da + dbulk
            key = (cost,da,dbulk,rot,x,y)
            if results and min(r[0] for r in results) <= key:
                continue
            if any((db.Region(rect.transformed(tr))-area).area() for shapes,area in rules for rect in shapes):
                continue
            results.append((key,tr,a,b))
    if not results:
        raise ValueError('No site has the required complete M3/M4 plate, via and MIM clearances')
    (cost,da,dbulk,*_),tr,a,b = min(results,key=lambda row:row[0])
    return tr,a,b,dict(pre_route_distance_to_connected_positive_net_um=da/1000,
                       pre_route_distance_to_connected_VSS_um=dbulk/1000,
                       upper_mask_bounds=cap.bbox().transformed(tr).to_s())


def build(folder,electrode,copies,grid,*,base=BASE,parent=PARENT,unit=SQUARE,unit_sha=MIM,
          cell_name='nr_reservoir_15p7',logical=None):
    folder.mkdir(parents=True,exist_ok=True)
    targets_file = folder/'source_coupon_targets.json'
    prepare(folder,False,False)
    targets = json.loads(targets_file.read_bytes())
    lay = db.Layout(); lay.read_bytes(sealed(base/'die.gds.gz',parent)); top=lay.top_cell()
    if base!=BASE:
        prior=json.loads((base/'placement.json').read_bytes())
        for i,c in enumerate(prior['capacitors']):
            for net,role,coord in [(prior['electrode'],'C1','positive_nm'),('vss','C2','ground_nm')]:
                x,y=c[coord]
                targets.append([net,f'prior_reservoir{i+1}:{role}','m4',x/1000,y/1000])
    parent_groups,shorts,con = circuit(lay,top,targets)
    assert not shorts and all(len(v)==1 for v in parent_groups.values())
    owners = {k:{m:con.region(next(iter(parent_groups[k])),m).merged() for m in ('m4','m3','m2','m1')}
              for k in (electrode,'vss')}
    other = db.Layout(); other.read_bytes(sealed(unit,unit_sha))
    assert lay.cell(cell_name) is None
    cap = lay.create_cell(cell_name);cap.copy_tree(other.top_cell())
    ingredients = []
    for i in range(copies):
        tr,a,b,survey = location(lay,top,cap,targets,electrode,owners)
        top.insert(db.CellInstArray(cap.cell_index(),tr))
        for net,xy,role in [(electrode,a,'C1'),('vss',b,'C2')]:
            targets.append([net,f'reservoir{i+1}:{role}','m4',xy.x/1000,xy.y/1000])
        ingredients.append(dict(transform=tr.to_s(),positive_nm=[a.x,a.y],ground_nm=[b.x,b.y],**survey))
    pre,shorts,_ = circuit(lay,top,targets)
    assert not shorts and all(len(g)==(1+copies if net in (electrode,'vss') else 1) for net,g in pre.items())
    (folder/'cap_targets.json').write_text(json.dumps(targets,indent=1)+'\n')
    quiet_route.save(lay,top,folder/'cap_open.gds')
    changed = logical if logical is not None else filter_reservoir_source.circuit(electrode,copies)
    (folder/'reference.spice').write_bytes(changed)
    (folder/'placement.json').write_text(json.dumps(dict(parent_GDS=parent,leaf=unit_sha,electrode=electrode,
        source_sha256=hashlib.sha256(changed).hexdigest(),positive_plates=copies,capacitors=ingredients,
        pre_route_named_groups={n:len(v) for n,v in pre.items() if len(v)>1}),indent=1)+'\n')

    quiet_route.BUILD = folder
    ordinary = quiet_route.analog_cost
    def preserve_analog(con,groups,weight):
        # The new C1 island(s) are not a third existing REF conductor. Protect the
        # pre-existing connected REF network traced from its original receiver.
        if electrode=='ref':
            largest=max(groups['ref'],key=lambda node:con.region(node,'m2').area())
            groups={**groups,'ref':{largest}}
        return ordinary(con,groups,weight)
    quiet_route.analog_cost=preserve_analog
    try:
        record_tracks(folder,'chip',[electrode]*copies+['vss']*copies,
                      lambda:quiet_route.route('chip',grid,grid//2,60,True,source='cap_open',
                      target_file='cap_targets.json',wires=(electrode,'vss'),physical_points=True,m4_cost=50))
    finally:
        quiet_route.analog_cost=ordinary
    print(ingredients,flush=True)


def compare_geometry(final_gds,archive,*,base=BASE,parent=PARENT,cell_name='nr_reservoir_15p7',added_count=None):
    original=db.Layout();original.read_bytes(sealed(base/'die.gds.gz',parent))
    final=db.Layout();final.read(str(final_gds))
    p,q=original.top_cell(),final.top_cell()
    expected=json.loads((archive/'manifest.json').read_bytes())['gds_sha256']
    assert hashlib.sha256(final_gds.read_bytes()).hexdigest()==expected
    def instances(top):
        return sorted((v.cell.name,v.trans.to_s(),v.a.to_s(),v.b.to_s(),v.na,v.nb) for v in top.each_inst())
    old, new=instances(p),instances(q)
    extras=[v for v in new if v[0]==cell_name]
    assert old==[v for v in new if v[0]!=cell_name]
    assert len(extras)==(json.loads((archive/'reservoir.json').read_bytes())['added_count'] if added_count is None else added_count)
    changes={}
    for original_id in original.layer_indexes():
        info=original.get_info(original_id)
        final_id=final.find_layer(info.layer,info.datatype)
        assert final_id is not None
        old_geometry=db.Region(p.begin_shapes_rec(original_id)).merged()
        candidate=db.Region(q.begin_shapes_rec(final_id)).merged()
        deleted=old_geometry-candidate
        added=candidate-old_geometry
        assert deleted.area()==0,(info,deleted.area())
        if added.area():
            changes[f'{info.layer}/{info.datatype}']=dict(added_area_um2=added.area()/1e6,
                bbox_um=[v/1000 for v in (added.bbox().left,added.bbox().bottom,added.bbox().right,added.bbox().top)])
    assert {(original.get_info(i).layer,original.get_info(i).datatype) for i in original.layer_indexes()}=={
        (final.get_info(i).layer,final.get_info(i).datatype) for i in final.layer_indexes()}
    report=dict(parent_gds=parent,mask=expected,existing_top_instances_with_identical_name_transform_and_array=len(old),
                additional_instances=extras,removed_polygon_area_nm2=0,by_layer=changes,
                new_bounds_um=[min(v['bbox_um'][0] for v in changes.values()),min(v['bbox_um'][1] for v in changes.values()),
                               max(v['bbox_um'][2] for v in changes.values()),max(v['bbox_um'][3] for v in changes.values())])
    (archive/'geometry_delta.json').write_text(json.dumps(report,indent=1)+'\n')
    print(report,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('electrode',choices=('res_sel','ref'));p.add_argument('copies',type=int,choices=(1,2))
    p.add_argument('folder',type=Path);p.add_argument('--grid',type=int,default=220)
    p.add_argument('--compare',nargs=2,type=Path,metavar=('FINAL_GDS','ARCHIVE'))
    a=p.parse_args()
    if a.compare:
        compare_geometry(*a.compare)
    else:
        build(a.folder.resolve(),a.electrode,a.copies,a.grid)
