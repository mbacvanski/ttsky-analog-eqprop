"""The amplifier macros of the layout-against-circuit reference, checked against the netlist version.

The base flow's reference generator (native_edges/layout/reference.py) walks the netlist version down to devices, except that
an amplifier instance matching one of make_ref's AMP_CELLS (a subcircuit name and some of its parameters: COMP and
DRIVE, and RZERO for cd_signal_az only) becomes a macro whose devices come from the amp generator's own reference file,
AMP_REF/<cell>_ref.spice (feasibility_20261107/amp_layout/ref), not from the netlist. So the comparison checks those
macros of the layout against these files, not against the netlist we simulate and publish.

This script closes that gap for one netlist version and one amp reference folder. For every macro instance the
reference generator makes (its own walk and AMP_CELLS, on this netlist version), it expands the netlist version's own
subcircuit with that instance's parameters down to devices (the walk's evaluation, with nothing stopped at a macro),
prints each device as the reference generator prints it (its fmt), and compares device by device with the reference
file:
  - the same device names;
  - the same model;
  - the same connections, with the file's ports taken by position as the subcircuit's pins;
  - the same values, as the reference prints them (W, L, m), with `mult` 1 or equal to m (the netlist's sky130
    convention: mult carries the unit count for the model's mismatch scaling, m the multiplicity).
Devices the file declares as layout additions (its "Layout addition" header line) are listed apart, not as
differences. Every other input of the reference that comes from a side file rather than the netlist is listed with how
it is tied to the netlist version.

  PY -I macro_check.py SCHEMATIC.spice AMP_REF_DIR OUT.json [EXPECTED_DIFFERENCES]

EXPECTED_DIFFERENCES (default 0) is the number of device differences that must be found over all macro instances; the
script fails otherwise.
"""
import gzip
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[3]
LAY = SIX / 'native_edges' / 'layout'
ROOT = 'xor_chip_native_six'

schematic, amp_ref, out = (Path(a).resolve() for a in sys.argv[1:4])
expected = int(sys.argv[4]) if len(sys.argv) > 4 else 0
os.chdir(LAY)
sys.argv = sys.argv[:1]                       # chip_reference reads the command line at import
sys.path.insert(0, str(SIX / 'split_pair/layout'))
from chip_reference import M, legacy, v4_plan  # noqa: E402  the reference generator's own modules


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expand(subs, name, nets, params, prefix, out, genv):
    """M.walk without the macro stop: every non-primitive instance is expanded."""
    pins, defaults, lines = subs[name]
    env = dict(genv)
    for k, v in defaults.items():
        env[k] = M.ev(v, env)
    env.update(params)
    local = dict(zip(pins, nets))
    for line in lines:
        tok = line.split()
        inst, rest = tok[0], tok[1:]
        kv = dict(t.split('=', 1) for t in rest if '=' in t)
        pos = [t for t in rest if '=' not in t]
        model = pos[-1]
        conns = [local.get(n, prefix + n) for n in pos[:-1]]
        path = prefix + inst
        if model.startswith('sky130_fd_pr__'):
            vals = {k.lower(): M.ev(v, env) for k, v in kv.items() if k.lower() in ('w', 'l', 'm', 'mult')}
            out.append(('dev', path, model, conns, vals))
        elif model.startswith('sky130_fd_sc_'):
            out.append(('std', path, model, conns, {}))
        else:
            expand(subs, model, conns, {k: M.ev(v, env) for k, v in kv.items()}, path + '/', out, genv)


def parse_line(line):
    tok = line.split()
    pos = [t for t in tok[1:] if '=' not in t]
    vals = {k.lower(): float(M.num(v)) for k, v in (t.split('=', 1) for t in tok[1:] if '=' in t)}
    return tok[0], pos[:-1], pos[-1], vals


def read_ref(path, cell):
    text = path.read_text()
    additions = set()
    for l in text.splitlines():
        m = re.match(r'\*\s*Layout additions?:\s*(.*)', l)
        if m:
            additions |= set(re.findall(r'\b(X\w+)', m.group(1)))
    pins, _, lines = M.subckts(text)[cell]
    devs = {}
    for l in lines:
        name, conns, model, vals = parse_line(l)
        devs[name] = (conns, model, vals)
    return pins, devs, additions


def close(a, b):
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def where(p):
    """p for the record: relative to the chips' folder or to this folder; outside both (a rebuild's own empty folder, as
    in the freeze's trace and its proof) its last two parts, v5_reference/amp_ref."""
    for base in (SIX.parent, HERE.parents[0]):
        if p.is_relative_to(base):
            return str(p.relative_to(base))
    return str(Path(*p.parts[-2:]))


def main():
    text = schematic.read_text()
    subs = M.subckts(text)
    frozen = gzip.decompress((SIX / 'circuit/frozen_native.spice.gz').read_bytes()).decode()
    genv_frozen, genv_own = M.deck_params(frozen), M.deck_params(text)
    pins = dict(M.TT_MAP, **legacy.V4_PINS)
    items = []
    M.walk(subs, ROOT, [pins[p] for p in subs[ROOT][0]], {}, '', items, genv_frozen)   # as reference.py does
    model_of = {}
    for m, p, c in M.AMP_CELLS:
        model_of.setdefault(c, []).append(dict(subcircuit=m, matched_on=p))
    rec = dict(schematic=schematic.name, schematic_sha256=sha(schematic), amp_ref=where(amp_ref),
               amp_cells_matching_rule=[dict(subcircuit=m, matched_on=p, cell=c) for m, p, c in M.AMP_CELLS],
               global_parameters=dict(
                   note='the reference evaluates with the frozen deck\'s .param values (circuit/frozen_native.spice.gz); '
                        'the expansion here uses the netlist version\'s own',
                   only_in_frozen=sorted(set(genv_frozen) - set(genv_own)), only_in_netlist=sorted(set(genv_own) - set(genv_frozen)),
                   differing={k: [genv_frozen[k], genv_own[k]] for k in sorted(set(genv_frozen) & set(genv_own))
                              if not close(genv_frozen[k], genv_own[k])}),
               macros={}, instances=[], differences=[])
    genv = dict(genv_frozen, **genv_own)
    for kind, path, cell, conns, child in items:
        if kind != 'cell':
            continue
        model = next(c['subcircuit'] for c in model_of[cell])
        f = amp_ref / f'{cell}_ref.spice'
        mac = rec['macros'].setdefault(cell, dict(file=f.name, sha256=sha(f), subcircuit=model, instances=[]))
        mac['instances'].append(path)
        mpins = subs[model][0]
        devs = []
        expand(subs, model, mpins, child, '', devs, genv)
        stds = [d for d in devs if d[0] == 'std']
        want = {}
        for d in devs:
            if d[0] != 'dev':
                continue
            name, dconns, dmodel, vals = parse_line(M.fmt(*d))
            want[name] = (dconns, dmodel, vals, d[4].get('mult', 1.0))
        fpins, have, additions = read_ref(f, cell)
        port = dict(zip(fpins, mpins))
        diffs = []
        if len(fpins) != len(mpins):
            diffs.append(dict(what='port count', file=fpins, netlist=mpins))
        elif fpins != mpins:
            diffs.append(dict(what='port names', file=fpins, netlist=mpins))
        for name in sorted(set(want) | set(have)):
            if name not in have:
                diffs.append(dict(device=name, what='in the netlist, not in the file', netlist=str(want[name][:3])))
                continue
            if name not in want:
                if name not in additions:
                    diffs.append(dict(device=name, what='in the file, not in the netlist (not declared a layout addition)',
                                      file=str(have[name])))
                continue
            wc, wm, wv, mult = want[name]
            hc, hm, hv = have[name]
            hc = [port.get(n, n) for n in hc]
            if wm != hm:
                diffs.append(dict(device=name, what='model', netlist=wm, file=hm))
            if wc != hc:
                diffs.append(dict(device=name, what='connections', netlist=wc, file=hc))
            if set(wv) != set(hv) or not all(close(wv[k], hv[k]) for k in wv):
                diffs.append(dict(device=name, what='values', netlist=wv, file=hv))
            if not (close(mult, 1.0) or close(mult, wv.get('m', 1.0))):
                diffs.append(dict(device=name, what='mult neither 1 nor m (the reference prints m only)', netlist=mult))
        inst = dict(instance=path, cell=cell, subcircuit=model,
                    parameters={k: v for k, v in sorted(child.items())}, devices_netlist=len(want),
                    devices_file=len(have), layout_additions=sorted(additions & set(have)),
                    std_cells_inside=len(stds), differences=diffs)
        rec['instances'].append(inst)
        rec['differences'] += [dict(d, instance=path, cell=cell) for d in diffs]
    rec['side_sources'] = side_sources()
    rec['expected_differences'] = expected
    rec['verdict'] = len(rec['differences']) == expected
    out.write_text(json.dumps(rec, indent=1, default=str) + '\n')
    for i in rec['instances']:
        print(f"{i['instance']:24s} {i['cell']:10s} {i['devices_netlist']:3d} devices in the netlist, {i['devices_file']:3d} "
              f"in the file (additions {i['layout_additions']}): {len(i['differences'])} differences")
    for d in rec['differences']:
        print('  DIFF', json.dumps(d, default=str)[:300])
    gp = rec['global_parameters']
    print('global parameters: only in frozen', len(gp['only_in_frozen']), '| only in netlist', len(gp['only_in_netlist']),
          '| differing', gp['differing'])
    print(f"differences {len(rec['differences'])}, expected {expected}: {'PASS' if rec['verdict'] else 'FAIL'}")
    if not rec['verdict']:
        raise SystemExit(1)


def side_sources():
    """Every other input of the reference that does not come from the netlist version."""
    std = Path(M.STD)
    poly = LAY / 'results/poly_cells.json'
    return [
        dict(source='amplifier macros', where='make_ref AMP_REF/<cell>_ref.spice (feasibility_20261107/amp_layout/ref)',
             tied_to_netlist='by this check (macro_check.py), every build'),
        dict(source='standard cells', where=str(std.relative_to(std.parents[4])), sha256=sha(std),
             tied_to_netlist='by name: the netlist instantiates sky130_fd_sc_hd cells and the reference copies their '
                             'subcircuits from the installed PDK library, the library the simulations use'),
        dict(source='global parameters', where='circuit/frozen_native.spice.gz (.param lines)',
             sha256=sha(SIX / 'circuit/frozen_native.spice.gz'),
             tied_to_netlist='compared here with the netlist version\'s own .param lines (global_parameters)'),
        dict(source='poly cells\' grounded edge dummies', where=str(poly.relative_to(SIX)), sha256=sha(poly),
             tied_to_netlist='not tied: physical dummies (every terminal on VGND), in no netlist; the version-4 copy '
                             '(check_die_v4.py) gives ne_g1/ne_r1 the contents of ne_g2/ne_r2; matched against the layout'),
        dict(source='chip dummies (CHIP_DUMMIES)', entries=[list(map(str, d)) for d in M.CHIP_DUMMIES],
             tied_to_netlist='not tied: physical dummies in no netlist; matched against the layout'),
        dict(source='legacy cell dummies (CELL_DUMMIES over v4_plan.ALL_PLACE)',
             entries=sorted({f'{c}: {legacy.CELL_DUMMIES[c]}' for _, c, *_ in v4_plan.ALL_PLACE if c in legacy.CELL_DUMMIES}),
             tied_to_netlist='not tied: physical dummies; matched against the layout'),
        dict(source='rw_res edge dummies', entries=['sky130_fd_pr__res_xhigh_po_1p41 L=70.34 x 4'],
             tied_to_netlist='not tied: written into reference.py; matched against the layout'),
        dict(source='board pin map', where='make_ref TT_MAP + chip_lvs V4_PINS',
             tied_to_netlist='reference.py checks it against the netlist\'s top-level ports ("Board pin contract differs")'),
    ]


if __name__ == '__main__':
    main()
