"""The metal-only tie trace (ties.py) against the flat extraction of the same GDS (magic_flows.py lvs): is every capacitor plate
that the extraction puts on ground on the ground pin's METAL, and is every well that is off the supply a well whose
transistors' bodies the circuit puts on that well's own node?

  PY -I ties_netlist.py TIES.json FLAT_LVS.spice OUT.json
"""
import collections
import json
import re
import sys
from pathlib import Path

ties, spice, out = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]), Path(sys.argv[3])
text = re.sub(r"\n\+\s*", " ", spice.read_text())
ports = re.search(r"(?m)^\.subckt \S+ (.*)$", text)[1].split()
devs = []
for l in text.splitlines():
    if l.startswith("X"):
        t = [x for x in l.split() if "=" not in x]
        params = dict(x.split("=", 1) for x in l.split() if "=" in x)
        devs.append((t[0], t[-1], t[1:-1], params))
gnd = [p for p in ports if p.upper() == "VGND"]
vdd = [p for p in ports if p.upper() == "VDPWR"]
assert len(gnd) == 1 and len(vdd) == 1, (gnd, vdd)
G, V = gnd[0], vdd[0]
mims = [d for d in devs if "cap_mim" in d[1]]
on_g = collections.Counter(("top" if d[2][0] == G else "") + ("bottom" if d[2][1] == G else "") for d in mims)
pf = [d for d in devs if "pfet" in d[1]]
bodies = collections.defaultdict(list)
for name, model, nets, p in pf:
    bodies[nets[3]].append((model, p.get("w") or p.get("W"), nets))
off = {b: v for b, v in bodies.items() if b != V}
rows = []
for b, v in sorted(off.items()):
    rows.append(dict(body_net=b, pmos=len(v), models=dict(collections.Counter(m for m, _, _ in v)), widths=sorted({w for _, w, _ in v}),
                     source_or_drain_on_the_body_net=sum(1 for _, _, n in v if b in (n[0], n[2]))))
tr = ties["accepted_trace"]
wells_off = [i for i in tr["islands"] if i["kind"] == "well"]
subs_off = [i for i in tr["islands"] if i["kind"] == "substrate"]
res = dict(
    extraction=str(spice), devices=len(devs), mim_capacitors=len(mims),
    mim_with_a_plate_on_ground_by_the_extraction=dict(on_g),
    bottom_plates_on_the_ground_pins_metal=ties["plates"]["bottom_on_VGND"], top_plates_on_the_ground_pins_metal=ties["plates"]["top_on_VGND"],
    every_ground_plate_tied_by_metal=(on_g.get("bottom", 0) == ties["plates"]["bottom_on_VGND"] and on_g.get("top", 0) == ties["plates"]["top_on_VGND"]
                                      and on_g.get("topbottom", 0) == 0),
    bias_words_ground_on_VGND_by_metal=ties.get("bias_words_ground", {}).get("all_on_VGND_by_metal"),
    pmos_bodies_not_on_the_supply=rows,
    wells_off_the_supply_by_the_metal_trace=len(wells_off), substrate_islands_by_the_metal_trace=len(subs_off),
    well_islands=[dict(outline_um=i.get("outline_um"), strips=i.get("contact_strips"), labels=i.get("labels"), plate=i.get("carries_capacitor_plate")) for i in wells_off])
out.write_text(json.dumps(res, indent=1) + "\n")
print(json.dumps({k: v for k, v in res.items() if k not in ("well_islands",)}, indent=1))
