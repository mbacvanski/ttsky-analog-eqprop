"""Reconstruct the reference-side capacitor placement, route and complete extracted die in an empty directory."""
import argparse
from pathlib import Path
import subprocess
import sys

import filter_reservoir_source
import filter_gate_source
from filter_source_rebuild import HERE, LAYOUT
from rebuild_check import compare
import quiet


def rebuild(archive, folder, klayout_python):
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('Reconstruction needs an empty output directory')
    folder.mkdir(parents=True,exist_ok=True)
    expected=quiet.read(archive/'reservoir.json')
    part, count=expected['electrode'], expected['added_count']
    gate=part in ('weak','weak_b')
    size=f"{expected['metal_plate_width_length_um']:g}"
    source=filter_gate_source.source(part,size) if gate else filter_reservoir_source.circuit(part,count)
    assert quiet.sha(source)==expected['source_sha256']
    stem=folder/'chip'
    repaired=folder/'chip_fill'
    circuit=folder/'reference.spice'
    commands=[
        [klayout_python,HERE/('filter_gate_layout.py' if gate else 'filter_reservoir_layout.py'),part,size if gate else count,folder],
        [sys.executable,LAYOUT/'check_die.py',stem,'--negative','--schematic',circuit],
        [klayout_python,LAYOUT/'repair.py',stem,repaired,'--fill','--targets',folder/'cap_targets.json'],
        [sys.executable,LAYOUT/'check_die.py',repaired,'--negative','--schematic',circuit],
        [sys.executable,LAYOUT/'extract.py',repaired,'--schematic',circuit,
            '--unit-mim',LAYOUT/'results/quiet_rc_release/mim_unit.spice','--unit-mim-count',3 if gate else 1+count],
    ]
    for i,step in enumerate(commands):
        runner, script,*args=step
        with (folder/f'{i:02d}_{Path(script).stem}.log').open('wb') as log:
            subprocess.run([str(runner),'-B',str(script),*[str(v) for v in args]],
                           cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=True)
    summary=compare(archive,folder,'chip_fill')
    assert summary['byte_identical_outputs']['gds_sha256']==expected['gds_sha256']
    assert (folder/'placement.json').read_bytes()==(archive/'placement.json').read_bytes()
    assert (folder/'chip_tracks.json').read_bytes()==(archive/'routing.json').read_bytes()
    (archive/'rebuild.json').write_bytes(quiet.dump(summary))
    print(summary,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive',type=Path);p.add_argument('scratch',type=Path)
    p.add_argument('--klayout-python',type=Path,default=Path.home()/'.local/opt/klayout-py/bin/python')
    a=p.parse_args();rebuild(a.archive.resolve(),a.scratch.resolve(),a.klayout_python)
