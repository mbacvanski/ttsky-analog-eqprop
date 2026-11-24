"""What the host knows and does (revision 5): the rule that turns a weight into a shunt and a bridge, the code tables of
the two cells, the fit of weights and self-terms from settled states, and the correction of the codes.

All conductances in uS, weights and states in the network's units (weight 1 = 10 uS = 1 / 100 kohm; one unit of
voltage = supply / 18).

The rule (DESIGN.md D2). An edge is two 100 kohm strips; the SHUNT Gs goes from their midpoint to REF, the BRIDGE gb
straight across. With u = 1 / (20 + Gs):

    conductance between the two neurons      100 u + gb          weight  w = 0.1 (100 u + gb)
    conductance each wire sees in the edge   c = 10 - 100 u + gb

The helpers match every bank for c = 7.5, so the host keeps gb = 100 u - 2.5; then w = 20 u - 0.25.
A wire that sees c instead of 7.5 gives its neuron a self-term (the neuron's own output fed back to it):
e = K x 0.1 (c - 7.5) with K = -1: more conductance on the wire than the bank is matched for makes the self-term
negative (from the neuron's equations: o = b + sum w v + (R G - 1 - R sum G_edges) y, G = the bank, R = 100 kohm).
Corrections for a measured error (dw = wanted - measured weight, de = wanted - measured self-term):

    dgb = 5 (dw + K de)           d(100 u) = 5 (dw - K de)   ->   dGs = -(dw - K de) / (20 u^2)
"""
from __future__ import annotations

import json

import numpy as np

import v4lib as L

OFF = 1.3                # code (V) that shuts a programmable resistor off at every corner
# OFF stays 1.3 V (design lead, 2026-11-16 13:50: every run so far used it, and no limit hangs on an OFF part's
# movement). The quieter choice at hot conditions is about 1.45 V (item7_off.py, drawn ring cells; results/item7_off.json):
#   at 1.3 V an OFF part conducts 0.0054 nS (shunt) / 0.0047 nS (bridge) at fs 50 C 1.89 V and 0.035 / 0.017 nS at
#   ff 85 C, and its gate rides on its slowly settling well: 0.22 / 1.04 mV (fs 50 C), 0.63 / 1.83 mV (ff 85 C) in a
#   computation; at 1.45 V: 0.017 / 0.087 mV (fs 50 C), 0.25 / 0.56 mV (ff 85 C). From about 1.6 V another path
#   charges the gate (fs 50 C bridge 2.46 mV; shunt 0.11 nS at 1.7 V). The writer puts every code up to 1.7 V on the
#   gate within 0.005 mV at every condition.
K = -1.0                 # sign of the self-term for more conductance on the wire


def parts(w):
    """Shunt and bridge (uS) for weight w, each wire at 7.5 uS."""
    u = (10 * w + 2.5) / 200
    return 1 / u - 20, 100 * u - 2.5


def weight_of(gs, gb):
    u = 1 / (20 + gs)
    return 0.1 * (100 * u + gb), 10 - 100 * u + gb


def cell_map(cond, file='cell_res_corners.json'):
    """Code table of the two cells at a condition, from the cell bench (results/cell_res_corners.json)."""
    c = L.CONDS[cond]
    rows = json.loads((L.RESULTS / file).read_text())
    r = next(x for x in rows if x['corner'] == c['corner'] and abs(x['temp'] - c['temp']) < .5 and abs(x['vdd'] - c['vdd']) < 1e-3)
    return dict(codes=np.array(r['codes']), br=np.array(r['br_g50']) * 1e6, sh=np.array(r['sh_g50']) * 1e6)


def code_for(cmap, role, g):
    """Code (V) for conductance g (uS); g <= 0 -> OFF."""
    if g <= 1e-3:
        return OFF
    c, y = cmap['codes'], cmap[role]
    keep = y > 1e-4
    c, y = c[keep], np.log(y[keep])
    o = np.argsort(y)
    assert y[o][0] <= np.log(g) <= y[o][-1], (role, g, np.exp(y[o][0]), np.exp(y[o][-1]))
    return float(np.interp(np.log(g), y[o], c[o]))


def g_of(cmap, role, code):
    c, y = cmap['codes'], cmap[role]
    return float(np.exp(np.interp(code, c, np.log(np.maximum(y, 1e-6)))))


def slope(cmap, role, code):
    """d ln(g) / d code (1/V) at a code."""
    return (np.log(g_of(cmap, role, code + 2e-3)) - np.log(g_of(cmap, role, code - 2e-3))) / 4e-3


def start_codes(cond, w1, w2, cmap=None):
    cmap = cmap or cell_map(cond)
    out = {}
    for k, w in ((1, w1), (2, w2)):
        gs, gb = parts(w)
        out[f'sh{k}'] = code_for(cmap, 'sh', gs)
        out[f'br{k}'] = code_for(cmap, 'br', gb)
    return out


def fit(points):
    """points: list of settled readings, each a dict with h1, h2, hz, f1, f2, z, bias1, bias2, dac (units, node - REF;
    `prog.settled`). Least squares for

        h1 = kb1 * bias1 + w1 * z + e1 * f1          (hidden neuron 1; f1 is the voltage on its own wire)
        h2 = kb2 * bias2 + w2 * z + e2 * f2
        hz = wz1 * f1 + wz2 * f2 + kf * dac            (output neuron. Its wire carries hz itself, so a self-term ez
                                                        shows as wz_i = w_i / (1 - ez): `ez` below, from both edges)

    each with a constant (an amplifier's offset, a fraction of a millivolt, which would otherwise lean on the weights).
    Returns the coefficients and the largest residual (units)."""
    A = lambda cols: np.array([[p[c] if c != 'offset' else 1.0 for c in cols] for p in points])
    out = {}
    for name, target, cols in (('h1', 'h1', ('bias1', 'z', 'f1')), ('h2', 'h2', ('bias2', 'z', 'f2')), ('hz', 'hz', ('f1', 'f2', 'dac'))):
        if all(abs(p['dac']) < 1e-3 for p in points):
            cols = tuple(c for c in cols if c != 'dac')         # no force was applied: nothing to fit there
        y = np.array([p[target] for p in points])
        M = A(cols + ('offset',))
        if np.linalg.cond(M) > 1e3:                            # the readings do not separate an offset: fit without one
            cols_used, M = cols, A(cols)
        else:
            cols_used = cols + ('offset',)
        x, *_ = np.linalg.lstsq(M, y, rcond=None)
        out[name] = dict(zip(cols_used, x.tolist()), residual=float(np.max(abs(M @ x - y))), cond=float(np.linalg.cond(M)))
        out[name].setdefault('dac', float('nan'))
    out['hz']['ez'] = 1 - 0.5 * (out['h1']['z'] / out['hz']['f1'] + out['h2']['z'] / out['hz']['f2'])
    return out


def corrections(codes, cmap, measured, wanted, gain=1.0):
    """One Newton step on the four codes. measured / wanted: {1: (w, e), 2: (w, e)} (weight and self-term of each hidden
    neuron). Uses the cell table's slopes at the present codes."""
    new = dict(codes)
    for k in (1, 2):
        (wm, em), (ww, ew) = measured[k], wanted[k]
        dw, de = gain * (ww - wm), gain * (ew - em)
        gs, gb = g_of(cmap, 'sh', codes[f'sh{k}']) if codes[f'sh{k}'] < OFF else 0.0, g_of(cmap, 'br', codes[f'br{k}']) if codes[f'br{k}'] < OFF else 0.0
        u = 1 / (20 + gs)
        gs2 = max(gs - (dw - K * de) / (20 * u * u), 0.0)
        gb2 = max(gb + 5 * (dw + K * de), 0.0)
        new[f'sh{k}'] = code_for(cmap, 'sh', gs2)
        new[f'br{k}'] = code_for(cmap, 'br', gb2)
    return new


# ---- calibration in the network (item 7): no knowledge of the corner, only the typical cell table as a prior
DAC_LSB = 3.3 / 2 ** 14      # V: a 14-bit DAC with a 3.3 V range on ua[1]
READ_LSB = 1e-4              # V: readout resolution


def quantize_codes(codes):
    return {k: round(v / DAC_LSB) * DAC_LSB for k, v in codes.items()}


def quantize_reading(p, unit_V):
    """A settled reading (units) as a 0.1 mV instrument gives it."""
    q = READ_LSB / unit_V
    return {k: round(v / q) * q for k, v in p.items()}


def infer_parts(w, e, helper=2.5):
    """Shunt and bridge (uS) that a measured weight and self-term of a hidden neuron imply:
    10 w = 100 u + gb and -10 e = (10 - 100 u + gb) - (5 + helper)."""
    gb = 5 * (w - e) - 2.5 + 0.5 * helper
    hu = 10 * w - gb                       # 100 u
    gs = 100 / hu - 20 if hu > 0 else float('inf')
    return gs, gb


PIN_OFF_uS = 0.001       # a part whose design conductance at the wanted weight is under 1 nS is written OFF and stays OFF


def pinned_off(w):
    """Which part of an edge of design weight w the host holds OFF (the design lead's rule of 2026-11-16, DESIGN.md D12):
    the one whose design conductance at that weight is under 1 nS (the shunt at 0.75, the bridge at 0.25). Left between
    off and 1 nS, a resistor's two transistors leave their shared well floating; it settles over hundreds of
    microseconds and the stored gate rides on it (REPORT.md, item 7)."""
    gs, gb = parts(w)
    return {'sh': gs < PIN_OFF_uS, 'br': gb < PIN_OFF_uS}


def correct_log(codes, prior, measured, wanted, max_step=0.25, design=None):
    """One calibration step on the four codes from measured weights and self-terms, without knowing the corner.
    The present shunt and bridge follow from the measurement itself (`infer_parts`); the code is then moved by
    ln(wanted / present) / slope, with the slope d ln(g) / d code of the typical cell table at the present conductance
    (a property of the cell that changes little with the corner: -9 to -16 per volt over the range). A part that has to be
    off gets the OFF code; one that reads zero or negative is moved by the largest step.
    design: the design weights (w1, w2). With them a part `pinned_off` is written OFF and stays OFF, and the edge's other
    part alone sets the weight (the self-term follows): with the shunt off 10 w = 5 + gb, with the bridge off
    10 w = 100 / (20 + gs). The fixed network's deficit, in both the present and the wanted weight, cancels in
    ln(wanted / present). Without them, the rule of before."""
    new = dict(codes)
    log = {}
    for k in (1, 2):
        (wm, em), (ww, ew) = measured[k], wanted[k]
        pin = pinned_off(design[k - 1]) if design is not None else {'sh': False, 'br': False}
        assert not (pin['sh'] and pin['br']), (design, k)
        if pin['sh']:
            gs_now = gs_want = 0.0
            gb_now, gb_want = 10 * wm - 5, 10 * ww - 5
        elif pin['br']:
            gb_now = gb_want = 0.0
            gs_now = 100 / (10 * wm) - 20 if wm > 0 else float('inf')
            gs_want = 100 / (10 * ww) - 20
        else:
            gs_now, gb_now = infer_parts(wm, em)
            gs_want, gb_want = infer_parts(ww, ew)
        for role, name, now, want in (('sh', f'sh{k}', gs_now, gs_want), ('br', f'br{k}', gb_now, gb_want)):
            lo, hi = (0.3, 60.0) if role == 'sh' else (0.05, 8.0)
            if pin[role] or want <= (0.05 if role == 'sh' else 0.01):
                new[name] = OFF
            elif codes[name] >= OFF - 1e-3:
                new[name] = code_for(prior, role, want)            # it was off: start from the table
            else:
                now_c = min(max(now, lo), hi) if np.isfinite(now) else hi
                sl = slope(prior, role, code_for(prior, role, now_c))
                step = float(np.clip(np.log(want / now_c) / sl, -max_step, max_step))
                new[name] = float(np.clip(codes[name] + step, 0.0, OFF))
            log[name] = dict(now_uS=now, want_uS=want, code=codes[name], new_code=new[name], pinned_off=pin[role])
    return new, log
