"""The order of the top cell's instance records (SREF/AREF) in a GDS file: Magic names an unnamed instance <cell>_<k>,
k counting that cell's uses in this order. -> JSON [[cell, x_dbu, y_dbu, index_k], ...] on stdout.
  PY -I gds_sref_order.py GDS [TOPNAME]"""
import json
import struct
import sys

data = open(sys.argv[1], "rb").read()
want_top = sys.argv[2] if len(sys.argv) > 2 else None
i, cur, structs = 0, None, {}
sname, rec = None, None
while i + 4 <= len(data):
    n, rt, dt = struct.unpack(">HBB", data[i:i + 4])
    if n < 4:
        break
    p = data[i + 4:i + n]
    if rt == 0x06:                                   # STRNAME
        cur = p.rstrip(b"\0").decode()
        structs[cur] = []
    elif rt in (0x0A, 0x0B):                         # SREF, AREF
        rec = dict(kind="SREF" if rt == 0x0A else "AREF")
    elif rt == 0x12 and rec is not None:             # SNAME
        rec["cell"] = p.rstrip(b"\0").decode()
    elif rt == 0x10 and rec is not None:             # XY
        rec["xy"] = struct.unpack(">ii", p[:8])
    elif rt == 0x11 and rec is not None:             # ENDEL
        structs[cur].append(rec)
        rec = None
    i += n
children = {c["cell"] for v in structs.values() for c in v}
tops = [s for s in structs if s not in children]
top = want_top or tops[0]
count, out = {}, []
for r in structs[top]:
    k = count.get(r["cell"], 0)
    count[r["cell"]] = k + 1
    out.append([r["cell"], r["xy"][0], r["xy"][1], k])
print(json.dumps(dict(top=top, instances=out)))
