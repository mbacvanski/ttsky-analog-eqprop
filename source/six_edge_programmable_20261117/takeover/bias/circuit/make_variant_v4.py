"""Version 4 (second candidate; the locked layout stays on version 3): H1's six-weight bias network made H2's.

    python -I make_variant_v4.py

From variant_reference.spice (version 3, checked by sha256), the design lead's change of 2026-11-23 19:20, and
nothing else:
  1. H1's trim resistor on the REF side, XSTATIC.XR1, takes H2's value: 48275.86207 ohm (was 18181.81818), so that
     the summing node still sees 5.000 uS: 1/(200k + 48.276k) + 1/1.0286M = 4.028 + 0.972 uS.
  2. H1's chain to ground becomes H2's: four pdk_rbias2 of 257142.85714 ohm (1.0286 Mohm), XG11..XG14 from p1 to end1
     (was eight of 300k, XG11..XG18, 2.4 Mohm); nets a4..a7 go.
  3. XPROG1 takes XPROG2's size: W 1, L 3.5 (was W 0.42, L 3.2), with XPROG2's diffusion parameters.
Fixed mode does not use these parts (XSEL_FIXED and XSW1 are off when six is low).

Writes variant_reference_v4.spice and variant_v4_manifest.json (both sha256s and every changed line, with its line
number in version 3 and in version 4), and checks the result instance by instance against version 3: every instance
of every subcircuit equal (nets, model, parameters, RVALUE included) except the ones listed above.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V3 = HERE / 'variant_reference.spice'
V4 = HERE / 'variant_reference_v4.spice'
V3_SHA = '6a2a42fc3d91af2ce725c2ff8647c76e6124bff3ae3fa3f13d97577ea8dae9cf'
R2 = '257142.85714'
EDITS = [
    (['XR1 ref bias1 vss pdk_rbias2 RVALUE=18181.81818'],
     ['* version 4: H1 trim as H2 (48.28 kohm, was 18.18 kohm), so that p1 still sees 5.000 uS',
      'XR1 ref bias1 vss pdk_rbias2 RVALUE=48275.86207']),
    ([f'XG1{i} {a} {b} vss pdk_rbias2 RVALUE=300k' for i, (a, b) in
      enumerate(zip(['p1', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7'], ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'end1']), 1)],
     ['* version 4: H1 chain as H2 (4 x 257142.85714 ohm = 1.029 Mohm, was 8 x 300k = 2.4 Mohm)'] +
     [f'XG1{i} {a} {b} vss pdk_rbias2 RVALUE={R2}' for i, (a, b) in
      enumerate(zip(['p1', 'a1', 'a2', 'a3'], ['a1', 'a2', 'a3', 'end1']), 1)]),
    (['XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=3.2 W=0.42 nf=1 ad=0.1218 as=0.1218 pd=1.42 ps=1.42 '
      'nrd=0.6905 nrs=0.6905 sa=0 sb=0 sd=0 mult=1 m=1'],
     ['* version 4: XPROG1 the size of XPROG2 (W 1, L 3.5; was W 0.42, L 3.2)',
      'XPROG1 ret1 bg1 vss vss sky130_fd_pr__nfet_01v8 L=3.5 W=1 nf=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 '
      'nrd=0.29 nrs=0.29 sa=0 sb=0 sd=0 mult=1 m=1']),
]


def instances(text):
    """{(subckt, instance): (nets, model, params)} for every X line of every subcircuit, + lines joined."""
    lines = []
    for raw in text.splitlines():
        if raw.startswith('+') and lines:
            lines[-1] += ' ' + raw[1:]
        else:
            lines.append(raw)
    out, cur = {}, None
    for l in lines:
        s = l.strip()
        if not s or s.startswith('*'):
            continue
        low = s.lower()
        if low.startswith('.subckt'):
            cur = s.split()[1]
            out[(cur, '.ports')] = tuple(s.split()[2:])
        elif low.startswith('.ends'):
            cur = None
        elif cur is not None and s[0] in 'Xx':
            tok = s.split()
            nodes = [t for t in tok[1:] if '=' not in t]
            out[(cur, tok[0])] = (tuple(nodes[:-1]), nodes[-1], tuple(sorted(t for t in tok[1:] if '=' in t)))
    return out


def main():
    v3 = V3.read_text()
    assert hashlib.sha256(v3.encode()).hexdigest() == V3_SHA, 'variant_reference.spice is not version 3'
    lines = v3.split('\n')
    changed = []
    for old, new in EDITS:                       # positions in version 3 as it is
        idx = [i for i in range(len(lines)) if lines[i:i + len(old)] == old]
        assert len(idx) == 1, (old[0], idx)
        changed.append(dict(version3_lines=[idx[0] + 1, idx[0] + len(old)], old=old, new=new))
    for c in sorted(changed, key=lambda c: -c['version3_lines'][0]):     # applied from the bottom up
        i = c['version3_lines'][0] - 1
        lines[i:i + len(c['old'])] = c['new']
    v4 = '\n'.join(lines)
    # line numbers in version 4
    v4l = v4.split('\n')
    for c in changed:
        j = [i for i in range(len(v4l)) if v4l[i:i + len(c['new'])] == c['new']]
        assert len(j) == 1
        c['version4_lines'] = [j[0] + 1, j[0] + len(c['new'])]
    # instance-by-instance check against version 3
    a, b = instances(v3), instances(v4)
    S = 'native_fixed_offsets'
    expect_changed = {(S, 'XR1'), (S, 'XG11'), (S, 'XG12'), (S, 'XG13'), (S, 'XG14'), ('native_offset_prog', 'XPROG1')}
    expect_gone = {(S, f'XG1{i}') for i in range(5, 9)}
    problems = []
    for k in a:
        if k in expect_gone:
            if k in b:
                problems.append(f'still there: {k}')
        elif k not in b:
            problems.append(f'missing: {k}')
        elif (a[k] != b[k]) != (k in expect_changed):
            problems.append(f'{"changed" if a[k] != b[k] else "unchanged"}: {k} {a[k]} -> {b[k]}')
    problems += [f'new: {k}' for k in b if k not in a]
    want = {(S, 'XR1'): (('ref', 'bias1', 'vss'), 'pdk_rbias2', ('RVALUE=48275.86207',)),
            (S, 'XG14'): (('a3', 'end1', 'vss'), 'pdk_rbias2', (f'RVALUE={R2}',)),
            (S, 'XG21'): (('p2', 'b1', 'vss'), 'pdk_rbias2', (f'RVALUE={R2}',))}
    for k, v in want.items():
        if b.get(k) != v:
            problems.append(f'{k}: {b.get(k)} != {v}')
    p1 = b[('native_offset_prog', 'XPROG1')][2]
    p2 = b[('native_offset_prog', 'XPROG2')][2]
    if p1 != p2:
        problems.append(f'XPROG1 {p1} != XPROG2 {p2}')
    if problems:
        raise SystemExit('FAIL\n' + '\n'.join(problems))
    V4.write_text(v4)
    man = dict(version=4, made_by='make_variant_v4.py', made_from='variant_reference.spice (version 3)',
               version3_sha256=V3_SHA, version4_sha256=hashlib.sha256(v4.encode()).hexdigest(),
               change='H1 six-weight bias network made H2\'s (design lead, 2026-11-23 19:20): trim XR1 48275.86207 ohm, '
                      'chain 4 x 257142.85714 ohm, XPROG1 W 1 L 3.5; nothing else',
               check='instance by instance against version 3 (nets, model, parameters incl. RVALUE): only XR1, '
                     'XG11..XG14 and XPROG1 differ, XG15..XG18 removed; XPROG1 parameters equal XPROG2\'s: PASS',
               changed_lines=changed)
    (HERE / 'variant_v4_manifest.json').write_text(json.dumps(man, indent=1) + '\n')
    print('PASS', man['version4_sha256'])
    for c in changed:
        print(f"version 3 lines {c['version3_lines']} -> version 4 lines {c['version4_lines']}")
        for l in c['old']:
            print('  -', l)
        for l in c['new']:
            print('  +', l)


if __name__ == '__main__':
    main()
