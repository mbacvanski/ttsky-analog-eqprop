"""Draw guarded SKY130 analog switches using the frozen small TG device geometries."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent/'programmable_weights_v4_20261114'
BUILD = HERE/'build'
sys.path.insert(0,str(BASE/'cells/scripts'))
from lib import Cell
from magic_util import MAGIC, MAGICRC, NETGEN, NETGEN_SETUP

def tool(args,folder,log):
    with (folder/log).open('w') as stream:
        subprocess.run(args,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120,
                       env=dict(os.environ,PDK_ROOT=str(MAGICRC.parents[3])))

def draw(mux):
    cell=Cell('sx_input_mux' if mux else 'sx_reset_tg')
    width,height=(6.50 if mux else 4.30),8.0
    cols=[2.,4.2] if mux else [2.]
    anchors=[]
    cell.ring(.5,.5,width-.5,height-.5)
    cell.rect('nwell',1.03,4.05,width-1.03,6.82)
    cell.tap_strip('nsubdiff',1.35,6.18,width-1.35,6.56)
    for x in cols:
        cell.via('mcon',x,6.37)
        cell.via('mcon',x,.415)
    cell.rect('metal1',.3,.27,width-.22,.555)
    cell.rect('metal1',1.4,6.22,width-.22,6.52)
    controls=('bit','bit_b') if mux else ('en','en_b')
    tracks=dict(zip(controls,[2.92,3.62]))
    for i,x in enumerate(cols):
        # Device placements use the native transistor origin. Connect to the
        # PDK metal1 over its contacts without changing drawn diffusion areas.
        for master,inst,y in [('tgnt','XN',2.),('tgpb','XP',5.)]:
            cell.t.box(x,y,x,y)
            cell.t.add(f'getcell {master} child 0 0')
            cell.t.add('identify '+inst+str(i))
        for side in (-1,1):
            xx=x+side*.22
            nvia,pvia=(1.445,4.93) if side==-1 else (1.895,5.33)
            if side==-1:
                cell.v('metal1',xx,nvia-.13,1.895,.23)
            cell.via('via1',xx,nvia)
            cell.via('via1',xx,pvia)
            cell.v('metal2',xx,1.14 if side==1 else nvia,pvia,.26)
            if side==-1:
                cell.v('metal2',xx,pvia,height-.18,.26)
                anchors.append(('a' if not mux else ('base','word')[i],'metal2',(xx-.14,height-.44,xx+.14,height)))
            else:
                cell.via('via2',xx,1.14)
        n,p=(controls[1],controls[0]) if mux and i==0 else controls
        for gate,yg,disp in [(n,2.37,-.36),(p,4.36,.36)]:
            y=tracks[gate]
            if disp<0:
                side=-.30
                cell.rect('metal1',x-.145,yg-.1,x+.145,yg+.19)
                cell.rect('locali',x-.085,yg,x+.085,yg+.25)
                cell.rect('locali',x-.385,yg+.08,x+.085,yg+.25)
                cell.rect('locali',x-.385,yg+.08,x-.215,y+.085)
            else:
                side=.30
                cell.rect('metal1',x-.145,yg-.145,x+.145,yg+.145)
                cell.rect('locali',x-.085,yg-.25,x+.085,yg)
                cell.rect('locali',x-.085,yg-.25,x+.385,yg-.08)
                cell.rect('locali',x+.215,y-.085,x+.385,yg-.08)
            cell.via('mcon',x+side,y)
    # Gate rails cross both columns between transistor rows. The interconnect
    # drops run on different sides of their devices, so the two polarities do
    # not touch even in the swapped column of the source mux.
    for gate,y in tracks.items():
        cell.h('metal1',.85,cols[-1]+.50,y,.28)
        cell.via('via1',.98,y)
        cell.h('metal2',0,1.13,y,.30)
        anchors.append((gate,'metal2',(0,y-.15,.45,y+.15)))
    cell.h('metal3',cols[0]+.08,width-.50,1.14,.36)
    cell.via('via2',width-.66,1.14)
    cell.h('metal2',width-.81,width,1.14,.32)
    anchors.append(('lane' if mux else 'b','metal2',(width-.44,.98,width,1.30)))
    for name,y in [('vdd',6.37),('vss',.415)]:
        cell.via('via1',width-.37,y)
        cell.h('metal2',width-.54,width,y,.32)
        anchors.append((name,'metal2',(width-.44,y-.16,width,y+.16)))
    for name,layer,coords in anchors:
        cell.port(name,layer,*coords,use={'vdd':'power','vss':'ground'}.get(name,'signal'))
    cell.outline(0,0,width,height)
    return cell


def reference(cell):
    mux=cell.name=='sx_input_mux'
    return ('.subckt ref '+' '.join(cell.info['pins'])+'\n'+
            ''.join(f'X{i} {a} {gate} {out} {body} sky130_fd_pr__{kind} L=0.15 W={w}\n'
                for i,(a,gate,out,body,kind,w) in enumerate(
                [(source,g,out,b,k,w)
                 for source,en,enb,out in ([('base','bit_b','bit','lane'),('word','bit','bit_b','lane')]
                    if mux else [('a','en','en_b','b')])
                 for g,b,k,w in [(en,'vss','nfet_01v8',.5),(enb,'vdd','pfet_01v8',1)]]))+
            '.ends ref\n')


def normalize_gds(path):
    """Normalize only library/structure timestamps so a clean rebuild is byte stable."""
    data=bytearray(path.read_bytes())
    pos=0
    date=struct.pack('>12h',*([2026,11,17,0,0,0]*2))
    while pos<len(data):
        length, record, dtype=struct.unpack_from('>HBB',data,pos)
        if length<4 or length%2 or pos+length>len(data):
            raise ValueError('Invalid GDS record')
        if record in (1,5):
            assert dtype==2 and length==28
            data[pos+4:pos+28]=date
        pos+=length
    path.write_bytes(data)


def negative_controls(cell, extracted, ref, folder):
    result={}
    text=ref.read_text()
    name='base' if cell.name=='sx_input_mux' else 'a'
    variants={'open':text.replace('X0 '+name+' ','X0 disconnected '),
              'wrong_width':text.replace(' W=0.5',' W=1',1)}
    for fault,negative in variants.items():
        assert negative!=text
        path=folder/(fault+'.spice')
        path.write_text(negative)
        report=folder/(fault+'.txt')
        tool([NETGEN,'-batch','lvs',str(extracted)+' sx_flat',str(path)+' ref',str(NETGEN_SETUP),str(report)],
             folder,fault+'.log')
        verdict=report.read_text()
        failures=('Circuits do not match','Property errors were found','Top level cell failed pin matching')
        assert any(message in verdict for message in failures), verdict[-900:]
        if fault=='wrong_width':
            assert 'Property errors were found' in verdict and 'w circuit1:' in verdict
        else:
            assert 'Final result: Circuits match uniquely.' not in verdict
        result[fault]='detected'
    return result


def main():
    BUILD.mkdir(exist_ok=True)
    for primitive in ('tgnt','tgpb'):
        shutil.copyfile(BASE/'floorplan/cells_in/layout'/(primitive+'.mag'),BUILD/(primitive+'.mag'))
    for mux in (False,True):
        cell=draw(mux)
        (BUILD/(cell.name+'.mag')).unlink(missing_ok=True)
        cell.t.add('save '+cell.name)
        cell.t.add('gds write '+str(BUILD/(cell.name+'.gds')))
        cell.t.add('quit -noprompt')
        script=BUILD/'draw.tcl';script.write_text(cell.t.text())
        tool([MAGIC,'-dnull','-noconsole','-rcfile',str(MAGICRC),str(script)],BUILD,cell.name+'_draw.log')
        folder=BUILD/(cell.name+'_readback');folder.mkdir(exist_ok=True)
        gds=BUILD/(cell.name+'.gds')
        normalize_gds(gds)
        check=folder/'readback.tcl'
        check.write_text(f"""
gds read {gds}
load {cell.name}
select top cell
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
set total 0
foreach {{rule boxes}} [drc listall why] {{
  puts "RULE [llength $boxes] $rule $boxes"
  incr total [llength $boxes]
}}
puts "DRCTOTAL $total"
flatten sx_flat
load sx_flat
select top cell
extract do local
extract all
ext2spice lvs
ext2spice -o layout.spice
quit -noprompt
""")
        tool([MAGIC,'-dnull','-noconsole','-rcfile',str(MAGICRC),str(check)],folder,'magic.log')
        log=(folder/'magic.log').read_text()
        rules=re.findall(r'(?m)^RULE .*$',log)
        print(cell.name,rules,flush=True)
        assert re.search(r'(?m)^DRCTOTAL 0$',log),folder
        raw=(folder/'layout.spice').read_text()
        if '.subckt sx_flat ' not in raw.lower():
            raw='.subckt sx_flat '+' '.join(cell.info['pins'])+'\n'+'\n'.join(line for line in raw.splitlines() if line.startswith(('X','+')))+'\n.ends\n'
        extracted=folder/'extracted.spice';extracted.write_text(raw)
        ref=folder/'ref.spice';ref.write_text(reference(cell))
        tool([NETGEN,'-batch','lvs',str(extracted)+' sx_flat',str(ref)+' ref',str(NETGEN_SETUP),str(folder/'lvs.txt')],folder,'netgen.log')
        lvs=(folder/'lvs.txt').read_text()
        assert 'Circuits match uniquely.' in lvs and 'Property errors were found' not in lvs,lvs[-1800:]
        faults=negative_controls(cell,extracted,ref,folder)
        cell.info.update(magic_full_DRC_errors=0,lvs_negative_controls=faults,flat_lvs='unique match',devices=4 if mux else 2,
                         gds_sha256=hashlib.sha256(gds.read_bytes()).hexdigest())
        (HERE/(cell.name+'.json')).write_text(json.dumps(cell.info,indent=2)+'\n')
        export=HERE/'gds';export.mkdir(exist_ok=True)
        shutil.copyfile(gds,export/gds.name)
        print(cell.name,cell.info['size_um'],cell.info['flat_lvs'])


if __name__=='__main__':
    main()
