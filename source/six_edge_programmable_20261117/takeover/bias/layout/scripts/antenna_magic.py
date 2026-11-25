"""Run Magic's native antenna deck on etch-stage copies of a die.

Preserve substrate, FEOL recognition, the hierarchy and the current conductor.
Drop every higher routing layer and its ports, and the cuts leading to it.
A second set of copies omits the resistor recognition marker, making resistor
poly conduct in Magic. Logs and exact input GDS files are retained per stage.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import klayout.db as db

sys.path.insert(0, str(Path(__file__).resolve().parent))
from antenna_stage import RULES, read_gds
from strap_patch import save, sha


def etch_for(layer, purpose):
    # Metal and LI labels/ports belong to the wire, cut datatypes to their etch.
    if 66 <= layer <= 72:
        if purpose == 44:
            return {66: 'licon', 67: 'mcon', 68: 'via1', 69: 'via2', 70: 'via3',
                    71: 'via4', 72: 'm5'}[layer]
        return {66: 'poly', 67: 'li', 68: 'm1', 69: 'm2', 70: 'm3', 71: 'm4', 72: 'm5'}[layer]
    return {89: 'via3', 97: 'via4'}.get(layer)


def run_stage(ly, stage, model, dest, magic, rc, pdk):
    dest.mkdir(parents=True, exist_ok=True)
    order = list(RULES)
    top = ly.top_cell()
    removed = []
    for li in ly.layer_indexes():
        lp = ly.get_info(li)
        belongs = etch_for(lp.layer, lp.datatype)
        if ((belongs and order.index(belongs) > order.index(stage)) or
                (model == 'conducting' and (lp.layer, lp.datatype) == (66, 13))):
            ly.clear_layer(li)
            removed.append(str(lp))
    path = dest / 'etch.gds'
    save(ly, top, path)
    tcl = dest / 'check.tcl'
    tcl.write_text(f"""gds read etch.gds
load {top.name}
select top cell
expand
flatten etch_flat
load etch_flat
select top cell
extract all
feedback clear
antennacheck debug
antennacheck run -p . etch_flat
puts "ANTENNA_FEEDBACK [feedback count]"
quit -noprompt
""")
    log = dest / 'magic.log'
    with log.open('w') as f:
        subprocess.run([str(magic), '-dnull', '-noconsole', '-rcfile', str(rc), tcl.name],
                       cwd=dest, env=dict(os.environ, PDK_ROOT=str(pdk), TMPDIR=str(dest)),
                       stdout=f, stderr=subprocess.STDOUT, check=True)
    body = log.read_text()
    feedback = re.findall(r'^ANTENNA_FEEDBACK (\d+)$', body, re.M)
    if 'Running antenna checks.' not in body or 'antennacheck finished.' not in body or len(feedback) != 1:
        raise RuntimeError(f'Magic did not complete {stage}: {log}')
    ext = (dest / 'etch_flat.ext').read_text()
    mos = sum(line.startswith('device msubckt ') for line in ext.splitlines())
    if not mos:
        raise ValueError(f'Magic did not extract any transistors at {stage}')
    events = re.findall(r'Antenna violation detected at plane ([^\n]+)\nEffective antenna ratio ([\d.eE+-]+).*?'
                        r'Gate rect \((-?\d+) (-?\d+)\) to \((-?\d+) (-?\d+)\)', body, re.S)
    flags = body.count('Antenna violation detected at plane ')
    if flags != len(events):
        raise ValueError(f'could not parse all Magic flags in {log}')
    return dict(stage_gds_sha256=sha(path.read_bytes()), removed_layers=sorted(removed), extracted_mos=mos,
                feedback=int(feedback[0]), violations=flags,
                events=sorted([dict(layer=layer, ratio=float(ratio), gate_um=[round(int(v)*.005, 4) for v in xy])
                               for layer, ratio, *xy in events], key=lambda r: (r['gate_um'], r['layer'])))


def main(src, work, out):
    lp, digest = read_gds(src)
    used = [k for k, (l, d, *_) in RULES.items() if lp.find_layer(l, d) is not None
            and not db.Region(lp.top_cell().begin_shapes_rec(lp.find_layer(l, d))).is_empty()]
    pdk = Path(os.environ.get('PDK_ROOT', Path.home() / '.ciel')).resolve()
    rc = pdk / 'sky130A/libs.tech/magic/sky130A.magicrc'
    magic = Path(os.environ.get('MAGIC', Path.home() / '.local/bin/magic-8.3.685'))
    rec = dict(gds_sha256=digest, technology_sha256=sha(rc.with_name('sky130A.tech').read_bytes()),
               models={}, violations=0, feedback=0)
    for model in ('recognized', 'conducting'):
        rows = {}
        for stage in used:
            s = run_stage(lp.dup(), stage, model, work.resolve() / model / stage, magic, rc, pdk)
            rows[stage] = s
            rec['violations'] += s['violations']
            rec['feedback'] += s['feedback']
            print(model, stage, s['violations'], s['feedback'], flush=True)
        rec['models'][model] = rows
    out.write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n')
    return rec['violations'] or rec['feedback']


if __name__ == '__main__':
    raise SystemExit(1 if main(*map(Path, sys.argv[1:])) else 0)
