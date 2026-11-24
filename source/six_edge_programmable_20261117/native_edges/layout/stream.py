"""Reproduce an accepted route stream from the verified placement plus complete, editable parent metal geometry."""
import argparse
from collections import defaultdict, deque
import struct
import gzip
import json
from pathlib import Path
import tempfile
import hashlib
import klayout.db as db

from source import BUILD,REPORT,save,sha
from connectivity import METALS

def records(data):
    cells={}; i=0;start=None;name=None;first=None
    while i<len(data):
        mark=i;sz,kind=struct.unpack_from(">HH",data,i);body=data[i+4:i+sz];i+=sz
        if kind==0x0502:
            start=mark
            if first is None:first=mark
        if kind==0x0606:
            name=body.rstrip(b"\0").decode()
            cells[name]=[data[start:i],[]]
        if kind in (0x0800,0x0900,0x0a00,0x0b00,0x0c00,0x2d00):element=mark
        if kind==0x1100:cells[name][1].append(data[element:i])
        if kind==0x0700:after=i
    return data[:first],cells,data[after:]


def reproduce_order(target,witness,source):
    # KLayout may change the serialization order of otherwise byte-identical
    # cells and boundary elements on a read/write. Restore just their ordering.
    prefix,actual,tail=records(target.read_bytes())
    if source is not None:
        pref,original,ending=records(source.read_bytes())
        if prefix!=pref or tail!=ending or set(original)!=set(actual):raise ValueError("Library identity differs")
        perms={}
        for name,(head,entries) in original.items():
            other,got=actual[name]
            if head!=other:raise ValueError(name)
            if entries==got:continue
            where=defaultdict(deque)
            for idx,item in enumerate(got):where[item].append(idx)
            perms[name]=[where[item].popleft() for item in entries]
            if any(where.values()):raise ValueError("Different GDS content in "+name)
        witness["order"]=list(original)
        witness["permutations"]=perms
    result=bytearray(prefix)
    for n in witness["order"]:
        h,items=actual[n];result+=h
        if n in witness["permutations"]:items=[items[i] for i in witness["permutations"][n]]
        result+=b"".join(items);result+=b"\x00\x04\x07\x00"
    target.write_bytes(bytes(result)+tail)

def transfer(target,record,source=None,template=None):
    out=REPORT/record
    layout=db.Layout()
    with tempfile.TemporaryDirectory(dir=BUILD) as tmp:
        ref=Path(tmp)/"place.gds"
        ref.write_bytes(template.read_bytes() if template is not None else gzip.decompress((REPORT/"native_edges_placement.gds.gz").read_bytes()))
        template_hash=sha(ref)
        layout.read(str(ref))
    top=layout.top_cell()
    if source is not None:
        routed=db.Layout();routed.read(str(source));root=routed.top_cell()
        if len(list(root.each_inst()))!=len(list(top.each_inst())):raise ValueError("Placed hierarchy differs")
        allm={}
        for l,pair in METALS.items():
            ix=routed.layer(*pair);geometries=[]
            for s in root.shapes(ix).each():
                if s.is_box():v=["b",s.box.to_s()]
                elif s.is_polygon():v=["p",s.polygon.to_s()]
                elif s.is_path():v=["w",s.path.to_s()]
                else:raise ValueError((root.name,pair,str(s)))
                geometries.append(v)
            allm[l]=geometries
        witness={"placement_sha256":template_hash,
                 "gds_sha256":sha(source),"parent_copper":allm}
    else:
        witness=json.loads(gzip.decompress((out/"parent_metal.json.gz").read_bytes()))
    if template_hash!=witness["placement_sha256"]:raise ValueError(("Different placed device library",template_hash,witness["placement_sha256"]))
    for l,geometry in witness["parent_copper"].items():
        shapes=top.shapes(layout.layer(*METALS[l]));shapes.clear()
        for typ,value in geometry:
            form={"b":db.Box,"p":db.Polygon,"w":db.Path}[typ].from_s(value);shapes.insert(form)
    save(layout,top,target)
    reproduce_order(target,witness,source)
    if source is not None:
        (out/"parent_metal.json.gz").write_bytes(gzip.compress(json.dumps(witness,separators=(",",":")).encode(),mtime=0))
    if sha(target)!=witness["gds_sha256"]:raise ValueError(("Rebuilt stream differs",sha(target),witness["gds_sha256"]))
    print(sha(target),len(witness["parent_copper"]),sum(len(v) for v in witness["parent_copper"].values()),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("stage");p.add_argument("--out",type=Path,required=True);p.add_argument("--take",type=Path)
    p.add_argument("--template",type=Path,help="Registered selector-chip placement generated from the signed-off parent")
    a=p.parse_args();transfer(a.out,a.stage,a.take,a.template)
