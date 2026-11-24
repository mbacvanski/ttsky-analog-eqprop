"""Version 5: version 4 with the reference buffer's zero resistor long enough for SkyWater's mask rules.

    python -I make_variant_v5.py

From takeover/bias/circuit/variant_reference_v4.spice (version 4, checked by sha256), the design lead's decision of
2026-11-24 (fix A), and nothing else: XBUF3 (cd_ref_az DRIVE=4, the REF buffer) takes RZERO=1225 (was 1k). Through
cd_amp_aux -> pdk_rfixed_h -> pdk_rfixed its resistor is sky130_fd_pr__res_xhigh_po_1p41 with
L = 0.01*round((RVALUE - 232.3959788743)*1.41/2000 / 0.01) = 0.70 um (was 0.54 um: a 0.54 um body is under
SkyWater's 0.66 um, MR_poly.LEN.2, and its contact bars under 0.64 um end to end). The installed model gives
1225.30 ohm at L 0.70 (998.35 ohm at 0.54). XBUF1 and XBUF2 (RZERO=5k, L 3.36) share those subcircuits and do not
change. Exactly one line changes; no line is added or removed.

Writes variant_reference_v5.spice and variant_v5_manifest.json beside this script (both sha256s and the changed line,
with its line number), and checks the result instance by instance against version 4: every instance of every
subcircuit, and every top-level instance, equal (nets, model, parameters) except XBUF3, whose only difference is
RZERO.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
V4 = HERE.parents[1] / 'circuit' / 'variant_reference_v4.spice'
V5 = HERE / 'variant_reference_v5.spice'
V4_SHA = '3e28c62019f182bb6de4f99152b65299868b2ef1cd03eb366fc8e57e90c83bb4'
OLD = 'XBUF3 ref_tap ref ref az az_b ref_tap vdd vss cd_ref_az COMP=4p DRIVE=4 RZERO=1k HEADROOM=1'
NEW = 'XBUF3 ref_tap ref ref az az_b ref_tap vdd vss cd_ref_az COMP=4p DRIVE=4 RZERO=1225 HEADROOM=1'
RCON_1P41 = 232.3959788743


def rfixed_length(r):
    """pdk_rfixed's own formula (version 4, unchanged): L = 0.01*floor(((R/1-232.396)*1.41/2000)/0.01+0.5)."""
    return round(0.01 * math.floor(((r / 1 - RCON_1P41) * 1.41 / 2000) / 0.01 + 0.5), 2)


def instances(text):
    """{(subckt or '(top)', instance): (nets, model, params)} for every X line, + lines joined."""
    lines = []
    for raw in text.splitlines():
        if raw.startswith('+') and lines:
            lines[-1] += ' ' + raw[1:]
        else:
            lines.append(raw)
    out, cur = {}, '(top)'
    for l in lines:
        s = l.strip()
        if not s or s.startswith('*'):
            continue
        low = s.lower()
        if low.startswith('.subckt'):
            cur = s.split()[1]
            out[(cur, '.ports')] = tuple(s.split()[2:])
        elif low.startswith('.ends'):
            cur = '(top)'
        elif s[0] in 'Xx':
            tok = s.split()
            nodes = [t for t in tok[1:] if '=' not in t]
            out[(cur, tok[0])] = (tuple(nodes[:-1]), nodes[-1], tuple(sorted(t for t in tok[1:] if '=' in t)))
    return out


def main():
    v4 = V4.read_text()
    assert hashlib.sha256(v4.encode()).hexdigest() == V4_SHA, 'variant_reference_v4.spice is not version 4'
    lines = v4.split('\n')
    idx = [i for i, l in enumerate(lines) if l == OLD]
    assert len(idx) == 1, idx
    lines[idx[0]] = NEW
    v5 = '\n'.join(lines)
    assert len(v5.split('\n')) == len(v4.split('\n'))
    a, b = instances(v4), instances(v5)
    problems = []
    for k in sorted(set(a) | set(b)):
        if k not in a or k not in b:
            problems.append(f'only in one version: {k}')
        elif (a[k] != b[k]) != (k[1] == 'XBUF3'):
            problems.append(f'{"changed" if a[k] != b[k] else "unchanged"}: {k}')
    xb = [k for k in b if k[1] == 'XBUF3']
    assert len(xb) == 1, xb
    k = xb[0]
    da = set(a[k][2]) ^ set(b[k][2])
    if a[k][:2] != b[k][:2] or da != {'RZERO=1k', 'RZERO=1225'}:
        problems.append(f'XBUF3 differs in more than RZERO: {a[k]} -> {b[k]}')
    l_old, l_new = rfixed_length(1000), rfixed_length(1225)
    if (l_old, l_new) != (0.54, 0.70):
        problems.append(f'pdk_rfixed lengths {l_old} -> {l_new}, expected 0.54 -> 0.70')
    if problems:
        raise SystemExit('FAIL\n' + '\n'.join(problems))
    V5.write_text(v5)
    man = dict(version=5, made_by='make_variant_v5.py', made_from='takeover/bias/circuit/variant_reference_v4.spice (version 4)',
               version4_sha256=V4_SHA, version5_sha256=hashlib.sha256(v5.encode()).hexdigest(),
               change="XBUF3 (the REF buffer, cd_ref_az DRIVE=4) RZERO=1k -> 1225: its RZERO resistor "
                      "sky130_fd_pr__res_xhigh_po_1p41 L 0.54 -> 0.70 um (pdk_rfixed's formula), model 998.35 -> 1225.30 ohm "
                      "(design lead, 24 Nov, fix A: SkyWater's 0.66 um resistor body and 0.64 um bar end-to-end rules); nothing else",
               check='instance by instance against version 4 (nets, model, parameters), subcircuits and top level: only '
                     'XBUF3 differs, and only in RZERO; pdk_rfixed gives L 0.54 for 1k and 0.70 for 1225: PASS',
               changed_lines=[dict(line=idx[0] + 1, old=OLD, new=NEW)], lines=len(lines))
    (HERE / 'variant_v5_manifest.json').write_text(json.dumps(man, indent=1) + '\n')
    print('PASS', man['version5_sha256'])
    print(f"line {idx[0] + 1}:\n  - {OLD}\n  + {NEW}")


if __name__ == '__main__':
    main()
