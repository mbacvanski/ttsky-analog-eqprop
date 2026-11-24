"""What a layout variant adds over the protected devices, against a reference layout (project Python).

  PY -I new_crossings.py VARIANT_OVER_BLOCKS.json REFERENCE_OVER_BLOCKS.json OUT.json

Both files are over_blocks.py's output (every block's devices in the block's own frame, with the share of each device under
metal that is not the block's own, per layer). For every block present in both, every device whose cover by foreign metal
GREW on any layer (by more than 0.1% of its area) is listed, with the variant's nets over that block; resistor bodies and MIM
plates are the protected ones (resistor arrays, the neurons' resistors, state and stored plates); transistors are listed
apart. Blocks only in the variant are listed with their own foreign cover. Exit status 1 if any protected device gained cover.
"""
import json
import sys
from pathlib import Path

V = json.loads(Path(sys.argv[1]).read_text())["blocks"]
R = json.loads(Path(sys.argv[2]).read_text())["blocks"]
LAY = ("li", "met1", "met2", "met3", "met4")
out = dict(method=__doc__.strip(), variant=sys.argv[1], reference=sys.argv[2], grown={}, new_blocks={})
bad = 0
for role, b in V.items():
    if role not in R:
        out["new_blocks"][role] = dict(cell=b["cell"], devices=b["devices"], devices_under_foreign_metal=b["devices_under_foreign_metal"])
        continue
    ref = {(d["kind"], round(d["x"], 2), round(d["y"], 2)): d for d in R[role]["device_rows"]}
    rows = []
    for d in b["device_rows"]:
        k = (d["kind"], round(d["x"], 2), round(d["y"], 2))
        r = ref.get(k)
        if r is None:
            continue
        grew = {l: [r[l], d[l]] for l in LAY if d[l] - r[l] > 1e-3}
        if grew:
            rows.append(dict(kind=d["kind"], at_in_block_um=[d["x"], d["y"]], grew=grew))
    if rows:
        nets = sorted({f"{q['layer']} {q['net']}" for q in b["foreign_pieces"] if q["covers"]})
        prot = [x for x in rows if x["kind"] in ("resistor", "mim plate")]
        bad += len(prot)
        out["grown"][role] = dict(cell=b["cell"], protected_devices_with_more_cover=len(prot), transistors_with_more_cover=len(rows) - len(prot),
                                  devices=rows[:40], variant_nets_over_devices=nets[:40])
out["protected_devices_with_more_cover"] = bad
Path(sys.argv[3]).write_text(json.dumps(out, indent=1) + "\n")
print("protected devices (resistor bodies, MIM plates) with more foreign cover than in the reference:", bad)
for role, g in out["grown"].items():
    print(f"  {role}: {g['protected_devices_with_more_cover']} protected, {g['transistors_with_more_cover']} transistors; nets {g['variant_nets_over_devices'][:6]}")
for role, g in out["new_blocks"].items():
    print(f"  new block {role}: under foreign metal {g['devices_under_foreign_metal']}")
sys.exit(1 if bad else 0)
