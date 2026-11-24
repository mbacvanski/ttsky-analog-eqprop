"""Read-only access to the frozen physical reference for this independent design."""
import gzip
import hashlib
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
V4 = HERE.parents[1] / 'programmable_weights_v4_20261114'
FROZEN = V4 / 'floorplan/build/frozen/r6_20261116_0329'
TOP = 'tt_um_mbacvanski_denseam_xor'
GDS_HASH = '4161a93647aba3dfd9799bf1255d7b7104d26d5cd5153aa0329316bd9a240d9b'
PDK = Path(os.environ.get('SKY130A', Path.home()/'.ciel/sky130A'))
MAGIC = os.environ.get('MAGIC', str(Path.home()/'.local/bin/magic-8.3.685'))
NETGEN = os.environ.get('NETGEN', str(Path.home()/'.local/bin/netgen-1.5.325'))
KLAYOUT = os.environ.get('KLAYOUT', str(Path.home()/'.local/bin/klayout-0.30.0'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_gds():
    path = FROZEN / (TOP + '.gds')
    if not path.is_file():
        BUILD.mkdir(exist_ok=True)
        path = BUILD / 'frozen_baseline.gds'
        packed = V4 / 'explainer/site_static/evidence/layout.gds.gz'
        data = gzip.decompress(packed.read_bytes())
        assert hashlib.sha256(data).hexdigest() == GDS_HASH
        path.write_bytes(data)
    assert sha(path) == GDS_HASH
    return path
