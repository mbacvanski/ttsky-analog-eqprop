"""Canonical complete native circuit with a separately addressed pad or reference bypass."""
import gzip
import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = '521b0f942a8a8dfc408ef1165621026c4febcbdd5e4f9f8b9aa09725a834dd91'


def circuit(electrode, count):
    if electrode not in ('ref', 'res_sel') or count not in (1,2):
        raise ValueError('Expected one or two grounded capacitors on the native REF or package UIO6 conductor')
    data = gzip.decompress((HERE/'evidence/filtered_complete/source.spice.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest() == BASE
    original = data.decode()
    marker, = [line for line in original.splitlines() if line.startswith('XRCIN_C ')]
    cards = [f'XRESERVOIR{i+1} {electrode} vss sky130_fd_pr__cap_mim_m3_1 W=15.7 L=15.7 MF=1 m=1' for i in range(count)]
    assert 'XRESERVOIR' not in original and original.count(marker+'\n') == 1
    return original.replace(marker+'\n','\n'.join([marker,*cards])+'\n').encode()


def configuration(digest):
    for n in (1,2):
        for port in ('ref','res_sel'):
            data = circuit(port,n)
            if hashlib.sha256(data).hexdigest() == digest:
                return port,n
    return None
