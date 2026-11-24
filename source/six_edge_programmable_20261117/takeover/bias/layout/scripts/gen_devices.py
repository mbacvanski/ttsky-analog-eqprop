"""Generate the two programmable transistors (XPROG) with Magic's SKY130 PDK generator, deterministically.

  python gen_devices.py OUT_DIR W1 L1 W2 L2
Writes xprog_h1.gds, xprog_h2.gds (one nfet_01v8 each, no guard ring, gate contacted on both sides) and their
extracted SPICE; prints each cell's outline. Same generator and settings style as the base flow's capacitor leaves
(native_edges/verification/filter_entry_floor.py).
"""
import os, re, subprocess, sys
from pathlib import Path
PDK = Path(os.environ.get('PDK_ROOT', Path.home() / '.ciel')) / 'sky130A'
MAGIC = os.environ.get('MAGIC', str(Path.home() / '.local/bin/magic-8.3.685'))
out = Path(sys.argv[1]).resolve(); out.mkdir(parents=True, exist_ok=True)
w1, l1, w2, l2 = sys.argv[2:6]
tcl = ['snap internal', 'load xp_lib -force']
for i, (name, w, l) in enumerate((('xprog_h1', w1, l1), ('xprog_h2', w2, l2))):
    tcl += [f'box {20*i}um 0um {20*i}um 0um',
            f'magic::gencell sky130::sky130_fd_pr__nfet_01v8 I_{name} w {w} l {l} nf 1 m 1 guard 0 viasrc 100 viadrain 100 viagate 100 full_metal 1',
            f'select cell I_{name}', 'set cname [instance list celldef]', f'cellname rename $cname {name}']
for name in ('xprog_h1', 'xprog_h2'):
    tcl += [f'load {name}', 'select top cell', f'gds write {out/(name+".gds")}', 'extract all', 'ext2spice lvs',
            f'ext2spice -o {out/(name+".spice")} {name}']
(out / 'gen.tcl').write_text('\n'.join(tcl + ['quit -noprompt']) + '\n')
with (out / 'gen.log').open('w') as f:
    subprocess.run([MAGIC, '-dnull', '-noconsole', '-rcfile', str(PDK / 'libs.tech/magic/sky130A.magicrc'), str(out / 'gen.tcl')],
                   cwd=out, stdout=f, stderr=subprocess.STDOUT, check=True, env={**os.environ, 'PDK_ROOT': str(PDK.parent)})
for name in ('xprog_h1', 'xprog_h2'):
    print(name, re.findall(r'(?m)^X.*$', (out / (name + '.spice')).read_text()))
