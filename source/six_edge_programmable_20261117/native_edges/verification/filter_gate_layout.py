"""Draw one genuine slow-switch gate capacitor beside the relevant native post-resistor metal and ground."""
import argparse
import gzip
import hashlib
from pathlib import Path
import sys

import filter_entry_floor
import filter_gate_source as electrical
import filter_reservoir_layout as layout


ROOT=layout.HERE/'evidence/weak_electrode_5c5dfd43/cells'
SIZES=(('gate_mim_897',8.97),('gate_mim_1099',10.99))


def build(folder,electrode,side,grid):
    label='gate_mim_'+side.replace('.','')
    unit=ROOT/(label+'.gds.gz')
    unit_sha=hashlib.sha256(gzip.decompress(unit.read_bytes())).hexdigest()
    layout.build(folder,electrode,1,grid,base=electrical.BASE,parent=electrical.MASK,unit=unit,
                 unit_sha=unit_sha,cell_name='nr_gate_load',logical=electrical.source(electrode,side))


if __name__=='__main__':
    if sys.argv[1:]==['cells']:
        ROOT.mkdir(parents=True,exist_ok=True)
        filter_entry_floor.leaves(SIZES,ROOT)
    else:
        p=argparse.ArgumentParser(description=__doc__)
        p.add_argument('electrode',choices=('weak','weak_b'));p.add_argument('side',choices=('8.97','10.99'))
        p.add_argument('folder',type=Path);p.add_argument('--grid',type=int,default=220)
        p.add_argument('--compare',nargs=2,type=Path)
        a=p.parse_args()
        if a.compare:
            layout.compare_geometry(*a.compare,base=electrical.BASE,parent=electrical.MASK,cell_name='nr_gate_load',added_count=1)
        else:
            build(a.folder.resolve(),a.electrode,a.side,a.grid)
