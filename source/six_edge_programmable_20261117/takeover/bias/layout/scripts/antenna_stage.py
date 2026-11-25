"""Check every gate net using only the conductors present at each SKY130A etch.

Based on takeover/checks/antenna_stage_20261124/stage_scan.py. Compare unrounded
ratios, in both resistor interpretations. Cut layers use horizontal area.
Require 95% of each net's own stage allowance. Include the current etch's cuts
without allowing the next metal to connect them. A via on a MIM top plate
belongs to that electrode, even where the bottom plate overlaps in projection.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import klayout.db as db

# GDS layer, purpose, Magic sidewall thickness (None = horizontal area),
# maximum, intercept and slope of the diffusion allowance (sky130A.tech).
RULES = {
    'poly': (66, 20, .18, 50, 0, 0),
    'licon': (66, 44, None, 3, 0, 0),
    'li': (67, 20, .10, 75, 0, 450),
    'mcon': (67, 44, None, 3, 0, 18),
    'm1': (68, 20, .36, 400, 2200, 400),
    'via1': (68, 44, None, 3, 0, 18),
    'm2': (69, 20, .36, 400, 2200, 400),
    'via2': (69, 44, None, 6, 0, 36),
    'm3': (70, 20, .845, 400, 2200, 400),
    'via3': (70, 44, None, 6, 0, 36),
    'm4': (71, 20, .845, 400, 2200, 400),
    'via4': (71, 44, None, 6, 0, 36),
    'm5': (72, 20, 1.26, 400, 2200, 400),
}
EXTRA = {'diff': (65, 20), 'tap': (65, 44), 'well': (64, 20), 'res': (66, 13),
         'capm': (89, 44), 'cap2m': (97, 44)}
ELECTRODES = {'via3': 'capm', 'via4': 'cap2m'}


def read_gds(path):
    data = path.read_bytes()
    if data.startswith(b'\x1f\x8b'):
        data = gzip.decompress(data)
    ly = db.Layout()
    ly.read_bytes(data)
    if len(ly.top_cells()) != 1:
        raise ValueError('expected one die top cell')
    return ly, hashlib.sha256(data).hexdigest()


def geometry(ly):
    top = ly.top_cell()
    layers = {k: rule[:2] for k, rule in RULES.items()} | EXTRA
    shapes = {}
    for name, layer in layers.items():
        index = ly.find_layer(*layer)
        shapes[name] = db.Region(top.begin_shapes_rec(index)).merged() if index is not None else db.Region()
    shapes['gate'] = (shapes['poly'] & shapes['diff']).merged()
    shapes['sd'] = shapes['diff'] - shapes['poly']
    shapes['substrate'] = shapes['tap'] - shapes['well']
    shapes['ntap'] = shapes['tap'] & shapes['well']
    if not (shapes['res'] & shapes['gate']).is_empty():
        raise ValueError('resistor recognition marker on a gate')
    return shapes


def at_etch(shapes, stage, dbu, probes, details):
    through = list(RULES)[:list(RULES).index(stage) + 1]
    n = db.LayoutToNetlist('etch', dbu)
    # Direct use of physical geometry avoids label-based and upper-plane joins.
    regs = {}
    layer_ids = {}

    def add(name, reg):
        regs[name] = reg.dup()
        layer_ids[name] = n.register(regs[name], name)
        n.connect(regs[name])

    def join(a, b):
        n.connect(regs[a], regs[b])

    for key in ('gate', 'sd', 'ntap', 'substrate'):
        add(key, shapes[key])
    last = None
    for key in through:
        electrode = ELECTRODES.get(key)
        if electrode:
            add(electrode, shapes[electrode])
            # Separate whole cuts by landing. Reject a straddling contact.
            cuts = shapes[key].interacting(shapes[electrode])
            if not (cuts - shapes[electrode]).is_empty():
                raise ValueError(f'{key} landing crosses a MIM electrode boundary')
            add(key + '_cap', cuts)
            add(key, shapes[key] - cuts)
            join(key + '_cap', electrode)
        else:
            add(key, shapes[key])
        if last:
            join(last, key)
            if last in ELECTRODES:
                join(last + '_cap', key)
        if key == 'poly':
            join('gate', key)
        if key == 'licon':
            for lower in ('sd', 'ntap', 'substrate'):
                join(lower, key)
        last = key
    n.extract_netlist()
    wanted = {}
    for point in probes:
        net = n.probe_net(regs['gate'], db.DPoint(*point))
        if net is None:
            raise ValueError(f'probe is outside a gate: {point}')
        wanted.setdefault(net.cluster_id, []).append(','.join(map(str, point)))
    rule = RULES[stage]
    thickness, limit, intercept, slope = rule[2:]
    checked = shorts = protected = gates = 0
    worst = raw_peak = highest_utilization = None
    failures, found = [], {}
    for net in n.netlist().top_circuit().each_net():
        def metal(name):
            return n.polygons_of_net(net, layer_ids[name], True)

        gate = metal('gate')
        if gate.is_empty():
            continue
        gates += gate.count()
        area = gate.area() * dbu**2
        exposed = metal(stage)
        if stage in ELECTRODES:
            exposed += metal(stage + '_cap')
        has_metal = not exposed.is_empty()
        sample = wanted.get(net.cluster_id, [])
        if not has_metal and not sample:
            continue
        exposed.merge()
        perim = exposed.perimeter() * dbu
        charge = exposed.area() * dbu**2 if thickness is None else perim * thickness
        diffusion = (metal('sd').area() + metal('ntap').area()) * dbu**2
        substrate_area = metal('substrate').area() * dbu**2
        short = substrate_area > 0
        ratio = charge / area
        effective = ratio - (intercept + slope * diffusion if diffusion else 0)
        total_diff = diffusion + substrate_area
        # Project's stage_scan convention explicitly includes all taps in the
        # per-net metal allowance. Also check the independent PDK antenna table.
        allowance = limit + (2200 if limit == 400 else slope) * total_diff
        utilization = ratio / allowance
        margin_failed = ratio > .95 * allowance + 1e-10
        pdk_failed = not short and effective > limit + 1e-10
        gate_box = min((p.bbox().to_s() for p in gate.each()))
        row = dict(gate_bbox_dbu=gate_box, gate_area_um2=round(area, 8),
                   exposed_um2=round(charge, 8), raw_ratio=round(ratio, 8),
                   diode_um2=round(diffusion, 8), substrate_short=short,
                   substrate_tap_um2=round(substrate_area, 8), effective_ratio=round(effective, 8),
                   allowance=round(allowance, 8), acceptance=round(.95 * allowance, 8),
                   fraction_of_allowance=round(utilization, 10))
        for label in sample:
            found[label] = row
        if not has_metal:
            continue
        if raw_peak is None or ratio > raw_peak[0]:
            raw_peak = ratio, row
        if details is not None:
            details.append(row)
        if highest_utilization is None or utilization > highest_utilization[0]:
            highest_utilization = utilization, row
        if margin_failed or pdk_failed:
            failures.append(row)
        if short:
            shorts += 1
            continue
        checked += 1
        protected += int(diffusion > 0)
        if worst is None or effective > worst[0]:
            worst = effective, row
    if gates != shapes['gate'].count():
        raise ValueError(f'{stage}: attributed {gates} of {shapes["gate"].count()} gates')
    return dict(rule_limit=limit, unprotected_acceptance=.95 * limit, thickness_um=thickness,
                checked_nets=checked, with_diode=protected, substrate_short_nets=shorts,
                total_gate_shapes=gates, worst=worst[1] if worst else None,
                highest_utilization=highest_utilization[1] if highest_utilization else None,
                raw_max_including_shorted=raw_peak[1] if raw_peak else None,
                failures=sorted(failures, key=lambda r: -r['effective_ratio']), probes=found)


def scan(src, out, probes=(), nets_gz=None):
    ly, digest = read_gds(src)
    shapes = geometry(ly)
    rec = dict(gds_sha256=digest, dbu_um=ly.dbu, resistor_bodies=shapes['res'].count(), models={})
    total = 0
    all_nets = {}
    for model in ('conducting', 'open'):
        if model == 'open':
            shapes['poly'] = shapes['poly'] - shapes['res']
        stages = {}
        for stage in RULES:
            if shapes[stage].is_empty():
                stages[stage] = {'absent': True}
                continue
            details = [] if nets_gz else None
            s = at_etch(shapes, stage, ly.dbu, probes, details)
            if details is not None:
                all_nets.setdefault(model, {})[stage] = sorted(details, key=lambda r: r['gate_bbox_dbu'])
            stages[stage] = s
            total += len(s['failures'])
            print(model, stage, s['checked_nets'], 'worst', s['worst']['effective_ratio'] if s['worst'] else None,
                  'failures', len(s['failures']), flush=True)
        rec['models'][model] = stages
    rec['failed_net_stage_models'] = total
    out.write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n')
    if nets_gz:
        audit = dict(gds_sha256=digest, dbu_um=ly.dbu, models=all_nets)
        raw = json.dumps(audit, separators=(',', ':'), sort_keys=True).encode()
        nets_gz.write_bytes(gzip.compress(raw, mtime=0))
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('gds', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--nets-gz', type=Path, help='write individually measured net-stage ratios')
    parser.add_argument('--probe', type=float, nargs=2, action='append', default=[], metavar=('X', 'Y'))
    args = parser.parse_args()
    raise SystemExit(1 if scan(args.gds, args.report, args.probe, args.nets_gz) else 0)
