"""Physical weak transmission-gate capacitors on the unchanged two-reference-plate design."""
import hashlib
from pathlib import Path
import filter_reservoir_source as parent


BASE=Path(__file__).resolve().parent/'evidence/layout_5c5dfd43_reference_reservoir'
MASK='5c5dfd43e737b3b68a14ce2e2e48ed1101f673e7037ca79a42e95670e79d071b'
SOURCE='cfc0e02f03141889013c84c6cb083ebc4963ac5ab0a810238b7ee3edca3d79fa'


def source(electrode,side):
    if electrode not in ('weak','weak_b') or side not in ('8.97','10.99'):
        raise ValueError((electrode,side))
    old=parent.circuit('ref',2)
    assert hashlib.sha256(old).hexdigest()==SOURCE
    marker,=[l for l in old.splitlines(keepends=True) if l.startswith(b'XRWEAK_P ')]
    new=f'XGATELOAD {electrode} vss sky130_fd_pr__cap_mim_m3_1 W={side} L={side} MF=1 m=1\n'.encode()
    assert b'XGATELOAD' not in old
    return old.replace(marker,marker+new)


def configuration(digest):
    for net in ('weak','weak_b'):
        for side in ('8.97','10.99'):
            if hashlib.sha256(source(net,side)).hexdigest()==digest:
                return net,side
    return None
