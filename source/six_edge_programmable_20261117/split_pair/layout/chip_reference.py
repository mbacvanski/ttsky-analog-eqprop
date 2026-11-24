"""Build a device-level Tiny Tapeout LVS reference from the frozen electrical design."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import sys

HERE=Path(__file__).resolve().parent
SIX=HERE.parents[1]
OLD=SIX.parent/'programmable_weights_v4_20261114'
sys.path.insert(0,str(OLD/'floorplan/scripts'))
# chip_lvs reads the legacy floorplan mode from argv at module import.
command_line=sys.argv[1:]
sys.argv=sys.argv[:1]
import chip_lvs as legacy
import v4_plan
M=legacy.M
sys.argv.extend(command_line)


def generate(path, top, frozen=False, fault=None):
    source=OLD/'floorplan/build/frozen/r6_20261116_0329/native_r4_xor_matched_tb.spice'
    frozen_text=source.read_text()
    if frozen:
        root='xor_chip_v4'
        text=frozen_text
    else:
        root='xor_chip_six'
        with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
            buf=Path(scratch)/'source.spice'
            subprocess.run([sys.executable,'-B',str(SIX/'split_pair/prototype.py'),'--netlist',str(buf)],check=True)
            text=buf.read_text()
    # The same transistor walker and evaluated dimensions as the accepted
    # whole-chip check. All gates in the candidate are electrically present.
    subs=M.subckts(text)
    tt=dict(M.TT_MAP,**legacy.V4_PINS)
    assert set(tt)==set(subs[root][0])
    assert len(M.TT_PORTS)==37
    items=[]
    M.walk(subs,root,[tt[p] for p in subs[root][0]],{},'',items,M.deck_params(frozen_text))
    # Accepted standard cells, known amplifier dummies and all previous
    # array-end dummies are inherited explicitly from the verified reference.
    # The two new split buffers were expanded through their actual electronic
    # definitions, so each needs its own grounded 38.40-um amplifier dummy.
    dummies=[(spec.split()[0],spec.split()[1],count,where) for spec,count,where in M.CHIP_DUMMIES]
    by_cell=Counter((cell,length) for name,cell,*rest in v4_plan.ALL_PLACE
                    for length in legacy.CELL_DUMMIES.get(cell,[]))
    dummies += [(legacy.RX,f'L={length:g}',count,cell) for (cell,length),count in by_cell.items()]
    if not frozen:
        split_gates=[it[1] for it in items if it[1].endswith('XAMP/XMNPLUSB')]
        assert len(split_gates)==2,split_gates
        dummies.append((legacy.RX,'L=38.4',len(split_gates),'grounded split reference amplifier strips'))
    if fault:
        target={'b_open':'XREF/XBUF2/XAMP/XMNPLUSB','dimensions':'XREF/XBUF1/XAMP/XMNMINUSB',
                'wrong_word':'XINPUT/XH2/XB2/XSTD'}[fault]
        hits=[i for i,item in enumerate(items) if item[1]==target]
        assert len(hits)==1,(target,hits)
        i=hits[0]
        kind,name,model,conns,params=items[i]
        if fault=='dimensions':
            params=dict(params,w=params['w']*2)
        else:
            conns=list(conns)
            conns[1 if fault=='b_open' else 0]='VGND'
        items[i]=(kind,name,model,conns,params)
    allocated=set()
    lines=[f'* {root} walked from its authored transistor schematic, independent of the candidate layout.']
    lines+=M.std_defs({it[2] for it in items if it[0]=='std'},allocated)
    lines+=M.amp_defs(sorted({it[2] for it in items if it[0]=='cell'}),allocated)
    lines+=[f'.subckt {top} '+' '.join(M.TT_PORTS),*[M.fmt(*it) for it in items]]
    index=0
    for model,length,number,where in dummies:
        lines.append(f'* {number} grounded array dummies from {where}')
        for _ in range(number):
            lines.append(f'XDUMMY{index} VGND VGND VGND {model} {length}')
            index+=1
    lines.append('.ends '+top)
    path.write_text('\n'.join(lines)+'\n')
    return dict(root=root,top=top,tt_unique_ports=len(set(M.TT_PORTS)),pin_map=tt,fault=fault,
                original_source_sha256=hashlib.sha256(frozen_text.encode()).hexdigest(),
                assembly_sha256=hashlib.sha256(text.encode()).hexdigest(),reference_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                expanded_instances=dict(Counter(it[0] for it in items)),dummies=dummies,black_boxes=[])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=HERE/'build'/'chip_reference.spice')
    p.add_argument('--top',default=legacy.TOP)
    p.add_argument('--frozen',action='store_true')
    p.add_argument('--fault',choices=['b_open','dimensions','wrong_word'])
    args=p.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    receipt=generate(args.output,args.top,args.frozen,args.fault)
    args.output.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(args.output,receipt['reference_sha256'],receipt['expanded_instances'])
