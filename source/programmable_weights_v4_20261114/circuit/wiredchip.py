"""The drawn chip of a frozen set, for the v4 benches (2026-11-15).

flat/build/<run>/wired/decks/xor_matched_tb__wired.spice holds `wired__chip`: the chip strand's extraction mapped
onto the schematic's hierarchy with all its wiring (the flat pipeline's deck). This module gives the v4 benches that
chip in place of the schematic one:

  subckts(run)            the wired chip's own subcircuits (every one the accepted bench also defines is checked
                          identical) and the sha256 of the deck they come from
  deck(run, cond, **kw)   v4lib.deck('v4', ...) with the wired chip as the device under test
  node(run, path)         the name a schematic node (e.g. 'xdut.xbw.xw1.sg') has in the flattened wired chip: a net that
                          the extraction passes up as a port takes the name of the highest level it reaches
"""
import hashlib
import re

import v4lib as L

FLAT = L.HERE / 'flat'
_SUBS, _TREE = {}, {}


def _deck_text(run):
    return (FLAT / 'build' / run / 'wired' / 'decks' / 'xor_matched_tb__wired.spice').read_text()


def subckts(run):
    if run in _SUBS:
        return _SUBS[run]
    text = _deck_text(run)
    _, acc = L.accepted_parts()
    blocks = lambda t: {m[1].lower(): m[0] for m in re.finditer(r'(?ms)^\.subckt\s+(\S+)[^\n]*\n.*?^\.ends[^\n]*\n', t)}
    A, W = blocks(acc), blocks(text)
    norm = lambda s: re.sub(r'\s+', ' ', s).strip().lower()
    for k in W:                                   # shared cells must be the same (v4's top is replaced: not used)
        if k in A and k != 'xor_chip_staged':
            assert norm(W[k]) == norm(A[k]), f'{run}: subcircuit {k} differs from the accepted bench'
    assert 'wired__chip' in W, run
    keep = ''.join(v for k, v in W.items() if k not in A and k != 'xor_chip_staged_accepted')
    _SUBS[run] = (keep, hashlib.sha256(text.encode()).hexdigest())
    return _SUBS[run]


def deck(run, cond, **kw):
    subs, _ = subckts(run)
    text = L.deck('v4', cond, v4_subckts=subs, **kw)
    assert text.count(' xor_chip_v4 ') == 1
    return text.replace(' xor_chip_v4 ', ' wired__chip ')


def _tree(run):
    """{subckt: (ports, {instance: (nodes, subckt)})}, names lower-case."""
    if run in _TREE:
        return _TREE[run]
    text = re.sub(r'\n\+\s*', ' ', _deck_text(run))
    out, cur = {}, None
    for line in text.splitlines():
        t = line.split()
        if not t:
            continue
        low = [x.lower() for x in t]
        if low[0] == '.subckt':
            cur = low[1]
            out[cur] = ([x for x in low[2:] if '=' not in x], {})
        elif low[0].startswith('.ends'):
            cur = None
        elif cur and low[0].startswith('x'):
            args = [x for x in low[1:] if '=' not in x]
            out[cur][1][low[0]] = (args[:-1], args[-1])
    _TREE[run] = out
    return out


def node(run, path):
    """'xdut.a.b.n' -> its flattened name in the wired chip (lower case)."""
    tree = _tree(run)
    parts = path.lower().split('.')
    assert parts[0] == 'xdut', path
    insts, name = parts[1:-1], parts[-1]
    chain, sub = [], 'wired__chip'                 # (subckt holding the instance, instance name, instance's subckt)
    for i in insts:
        nodes, child = tree[sub][1][i]
        chain.append((sub, i, child))
        sub = child
    # walk back up while the name is a port of the subcircuit it is in
    level = len(chain)
    while level > 0:
        holder, inst, child = chain[level - 1]
        ports = tree[child][0]
        if name not in ports:
            break
        name = tree[holder][1][inst][0][ports.index(name)]
        level -= 1
    if level == 0 and name in tree['wired__chip'][0]:
        raise ValueError(f'{path} is a pin of the chip ({name})')
    return '.'.join(['xdut'] + insts[:level] + [name])
