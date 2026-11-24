"""The unmodelled wire-to-strip coupling of one GDS as a table, a SPICE fragment in the capacitance-only model's node names,
and totals per victim node (project Python).

  PY -I coupling_tables.py STRIP.json FLAT.ext NODES.json OVER_BLOCKS.json OUTSTEM

STRIP.json is strip_coupling.py's measurement; FLAT.ext the Magic flat extraction it was named by (the base flow's native_flat.ext.gz
for the selected layout, whose node names the base flow's nodes.json maps to the model's names); NODES.json that map (a missing map
keeps Magic's names); OVER_BLOCKS.json gives each block's role. Writes OUTSTEM.csv (one row per strip, aggressor and layer),
OUTSTEM.spice (one pair of capacitors per strip and aggressor), OUTSTEM_summary.json.

Only metal that is NOT the strip's own block's is counted ("chip wiring": the routing and other blocks' metal). The blocks'
own metal over their own strips is the same as on the earlier chip and equally unmodelled; its total is in the summary.
Capacitance = what Magic would extract if the strip were ordinary poly (PDK nominal per-area and fringe values, the lowest
conductor above the strip only). Each aggressor is put in one class:
  compute   switches during a computation: observer selects (ui_in[5..7], uio_in[2..3]), their uo_out echoes (uo_out[5..7]),
            and the DAC line (it steps for the output nudge)
  edge      switches only at RESET / HOLD / mode or write edges: bit_a, bit_b, reset, hold_in, ref_reset and their echoes
            uo_out[0..4], ext_en1/2, bias_prog, write, res_sel, weight_prog, the write strobes, clampw, iso, six, park,
            weak / weak_b
  static    ground, supply, REF, the ladder taps and bias voltages
  analog    an analog node that moves with the network during a computation (states, activations, f1/f2/z and their
            buses, midpoints, summing and feedback nodes, the observer chain)
"""
import collections
import csv
import gzip
import json
import re
import sys
from pathlib import Path

sj, extf, nodesf, obf, stem = sys.argv[1:6]
S = json.loads(Path(sj).read_text())
ext = (gzip.open(extf, "rt") if extf.endswith(".gz") else open(extf)).read()
nodes = json.loads((gzip.open(nodesf, "rt") if nodesf.endswith(".gz") else open(nodesf)).read()) if nodesf != "-" else {}
OB = json.loads(Path(obf).read_text())["blocks"]
# ground: the substrate node's representative name is an alias of VGND
equiv = collections.defaultdict(set)
for a, b in re.findall(r'^equiv "([^"]+)" "([^"]+)"', ext, re.M):
    equiv[a].add(b)
    equiv[b].add(a)
sub = re.search(r'^substrate "([^"]+)"', ext, re.M)[1]


def model_name(n):
    if n in nodes:
        return nodes[n]
    for e in equiv.get(n, ()):
        if e in nodes:
            return nodes[e]
    return n


# unnamed clusters (their Magic node record lies in a well): match a node whose name and an alias end in labels of the cluster
unplaced = {}
for m in re.finditer(r'^node "([^"]+)" \S+ \S+ \S+ \S+ nw', ext, re.M):
    unplaced[m[1]] = {m[1].split(".")[-1]} | {e.split(".")[-1] for e in equiv.get(m[1], ())}
for c, n in S["nets"].items():
    if not n["magic_names"]:
        labs = set(n["labels"])
        hit = [k for k, ends in unplaced.items() if k.split(".")[-1] in labs and len(ends & labs) >= 2]
        if len(hit) == 1:
            n["magic_names"] = hit
            n["named_by"] = "labels (its Magic node record lies in a well)"
# block roles by outline
roles = {(b["cell"], b["trans"]): role for role, b in OB.items()}


def role_of(block):
    cell, tr = block.split(" ", 1)
    return roles.get((cell, tr), block)


TT = {f"ui_in[{i}]": n for i, n in enumerate(["bit_a", "bit_b", "reset", "hold_in", "ref_reset", "obs_sel0", "obs_sel1", "obs_sel2"])}
TT.update({f"uio_in[{i}]": n for i, n in enumerate(["ext_en1", "ext_en2", "obs2_sel0", "obs2_sel1", "bias_prog", "write", "res_sel", "weight_prog"])})
TT.update({f"uo_out[{i}]": f"echo of {TT[f'ui_in[{i}]']}" for i in range(8)})
COMPUTE_PINS = {"ui_in[5]", "ui_in[6]", "ui_in[7]", "uio_in[2]", "uio_in[3]", "uo_out[5]", "uo_out[6]", "uo_out[7]"}
EDGE_PINS = {"ui_in[0]", "ui_in[1]", "ui_in[2]", "ui_in[3]", "ui_in[4]", "uio_in[0]", "uio_in[1]", "uio_in[4]", "uio_in[5]", "uio_in[6]",
             "uio_in[7]", "uo_out[0]", "uo_out[1]", "uo_out[2]", "uo_out[3]", "uo_out[4]"}
EDGE_LAB = {"we0", "we1", "we2", "we3", "clampw", "clamp", "iso", "weak", "weak_b", "park", "res_filtered", "six", "on"}
STATIC_LAB = {"ref", "vbn", "v0", "v1", "v2", "ref_tap", "d1_tap", "d2_tap", "d3_tap", "ladder", "tap"}


OBSERVER_OUT = {"rsense_0.sense", "rsense_0.inp", "pin_res_0.buf", "pin_res_0.buffered", "buf2_0.sense"}   # follow the observed signal
STATIC_NAMES = {"pw4_bias_0.bw1", "pw4_bias_0.bw2"}          # the held A/B voltages: still during a computation
STATIC_LAST = {"ref", "fixed1", "fixed2", "ext", "ladder"}  # last name component: REF, the fixed bias nodes, the raw/ladder inputs


def classify(n):
    labs = set(n["labels"])
    names = set(n["magic_names"]) | set(n.get("equiv", []))
    if names & OBSERVER_OUT:
        return "compute", "observer output path (jumps when the observer selection changes)"
    if names & STATIC_NAMES:
        return "static", "held input voltage (bw1/bw2)"
    if any(x.split(".")[-1] in STATIC_LAST for x in n["magic_names"]):
        return "static", "REF / fixed bias / raw input: " + ",".join(sorted({x.split('.')[-1] for x in n['magic_names']} & STATIC_LAST))
    pins = sorted(labs & (COMPUTE_PINS | EDGE_PINS))
    if names & {"VGND", "VDPWR", sub} or any(x.endswith("XSTD.VNB") or x.endswith("XSTD.VPB") for x in names):
        return "static", "ground" if (names & {"VGND", sub} or any(x.endswith("VNB") for x in names)) else "supply"
    if pins:
        p = pins[0]
        return ("compute" if p in COMPUTE_PINS else "edge"), f"{p} ({TT.get(p, '')})"
    if "dac" in labs:
        return "compute", "DAC line ext_in (steps for the output nudge)"
    if labs & EDGE_LAB:
        return "edge", "/".join(sorted(labs & EDGE_LAB))
    if any(x.endswith(".en") for x in n["magic_names"]) and any("threshold8" in x for x in n["magic_names"]):
        return "edge", "six (mode)"
    if labs & STATIC_LAB:
        return "static", "/".join(sorted(labs & STATIC_LAB))
    return "analog", ""


rows, pairs = [], collections.defaultdict(lambda: dict(c=0.0, cf=0.0, fsum=0.0, area=0.0, layers=collections.Counter()))
own_total = collections.Counter()
for r in S["rows"]:
    for p in r["pieces"]:
        c = p["c_area_aF"] + p["c_fringe_aF"]
        if p["who"] == "own":
            own_total[p["layer"]] += c
            continue
        n = S["nets"][str(p["net"])]
        cls, why = classify(n)
        aggr = model_name(n["magic_names"][0]) if n["magic_names"] else f"cluster{p['net']}"
        v1, v2 = model_name(r["t1"]), model_name(r["t2"])
        rows.append(dict(victim_device=r["device"], victim_model=r["model"], victim_l_um=r["l_um"], victim_at_um=r["at_um"], victim_block=role_of(r["block"]),
                         t1_magic=r["t1"], t1_model=v1, t2_magic=r["t2"], t2_model=v2, aggressor_model=aggr,
                         aggressor_magic=(n["magic_names"] or ["?"])[0], aggressor_labels=" ".join(n["labels"][:10]), aggressor_class=cls, aggressor_note=why,
                         layer=p["layer"], overlap_um2=p["area_um2"], c_area_aF=p["c_area_aF"], c_fringe_aF=p["c_fringe_aF"], c_aF=round(c, 4),
                         frac_from_t1=p["frac_from_t1"], at_um=p["at_um"]))
        k = (r["device"], aggr)
        q = pairs[k]
        q.update(t1=v1, t2=v2, cls=cls, why=why, model=r["model"], l=r["l_um"], block=role_of(r["block"]), t1m=r["t1"], t2m=r["t2"], aggm=(n["magic_names"] or ["?"])[0])
        q["c"] += c
        q["cf"] += p["c_fringe_aF"]
        q["fsum"] += c * p["frac_from_t1"]
        q["area"] += p["area_um2"]
        q["layers"][p["layer"]] += 1
with open(stem + ".csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
# SPICE fragment: per strip and aggressor, a pair at the strip's two ends; ucpl_a = share at the terminal-1 end
lines = ["* Unmodelled coupling from wires over polysilicon resistor strips (Magic extracts none to a resistor body).",
         f"* GDS {Path(S['gds']).name}; node names of the capacitance-only model (names map {Path(nodesf).name}).",
         "* Made by takeover/layout/scripts/strip_coupling.py + coupling_tables.py. Values: what Magic would extract if the strip",
         "* were ordinary poly (PDK nominal area and fringe values, lowest conductor above the strip only).",
         "* Include INSIDE the model's subcircuit (before '.ends sx_drawn'). Define at top level, before the include:",
         "*   .param ucpl_a=0.5   share placed at each strip's terminal-1 end (1: all at t1, 0: all at t2, 0.5: middle)",
         "*   .param ucpl_k=1     scale on every capacitor (0 removes them)",
         "*   .param ucpl_compute=1 ucpl_edge=1 ucpl_static=1 ucpl_analog=1   per-class switches (0 or 1)",
         "* Each line ends with: victim block, strip model and length, aggressor class, aggressor, and the crossing's own",
         "* position along the strip from t1 (pos), for a split at the true position: ucpl_a = 1 - pos for that pair.", ""]
k = 0
for (dev, aggr), q in sorted(pairs.items(), key=lambda kv: (kv[1]["block"], kv[0][0], -kv[1]["c"])):
    pos = q["fsum"] / q["c"] if q["c"] else 0.5
    cv = q["c"] * 1e-18
    sw = f"ucpl_{q['cls']}"
    lines.append(f"Cuc{k}a {aggr} {q['t1']} {{ucpl_k*{sw}*{cv:.6g}*ucpl_a}}")
    lines.append(f"Cuc{k}b {aggr} {q['t2']} {{ucpl_k*{sw}*{cv:.6g}*(1-ucpl_a)}} $ {q['block']} {q['model'].replace('sky130_fd_pr__', '')} L={q['l']:g} | {q['cls']} {q['aggm']} {q['why']} | pos {pos:.3f}")
    k += 1
lines.append("")
Path(stem + ".spice").write_text("\n".join(lines))
# the same at each crossing's true position (no ucpl_a)
pl = [l for l in lines[:4]] + ["* Variant: every pair split at the crossing's own position along its strip (C*(1-pos) at t1, C*pos at t2).",
                                "* Define .param ucpl_k and the four class switches as for unmodelled_coupling.spice.", ""]
k = 0
for (dev, aggr), q in sorted(pairs.items(), key=lambda kv: (kv[1]["block"], kv[0][0], -kv[1]["c"])):
    pos = q["fsum"] / q["c"] if q["c"] else 0.5
    cv = q["c"] * 1e-18
    sw = f"ucpl_{q['cls']}"
    pl.append(f"Cuc{k}a {aggr} {q['t1']} {{ucpl_k*{sw}*{cv * (1 - pos):.6g}}}")
    pl.append(f"Cuc{k}b {aggr} {q['t2']} {{ucpl_k*{sw}*{cv * pos:.6g}}} $ {q['block']} | {q['cls']} {q['aggm']}")
    k += 1
Path(stem + "_at_position.spice").write_text("\n".join(pl) + "\n")
# totals per victim node (middle split, and the most if every crossing on that node's strips were put at that node)
vic = collections.defaultdict(lambda: dict(middle=collections.Counter(), most=collections.Counter(), magic=set(), blocks=set(), aggressors=collections.Counter()))
for (dev, aggr), q in pairs.items():
    for node, mag in ((q["t1"], q["t1m"]), (q["t2"], q["t2m"])):
        v = vic[node]
        v["middle"][q["cls"]] += q["c"] / 2
        v["most"][q["cls"]] += q["c"]
        v["magic"].add(mag)
        v["blocks"].add(q["block"])
        v["aggressors"][f"{q['cls']}: {q['aggm']} {q['why']}".strip()] += q["c"]
vrows = []
for node, v in vic.items():
    vrows.append(dict(node=node, magic=sorted(v["magic"])[:3], blocks=sorted(v["blocks"]),
                      middle_aF={k: round(x, 1) for k, x in v["middle"].items()}, most_aF={k: round(x, 1) for k, x in v["most"].items()},
                      switching_most_aF=round(v["most"]["compute"] + v["most"]["edge"], 1),
                      top_aggressors=[(a, round(c, 1)) for a, c in v["aggressors"].most_common(6)]))
vrows.sort(key=lambda r: (r["node"] in ("pin_35", "pin_36"), -r["switching_most_aF"]))
byclass = collections.Counter()
for q in pairs.values():
    byclass[q["cls"]] += q["c"]
summ = dict(method=__doc__.strip(), gds=S["gds"], crossings=len(rows), strip_aggressor_pairs=len(pairs), strips_crossed=len({d for d, _ in pairs}),
            aggressor_nets=len({a for _, a in pairs}), total_aF_by_class={k: round(v, 1) for k, v in byclass.items()},
            own_block_metal_over_own_strips_aF={k: round(v, 1) for k, v in own_total.items()},
            aggressors=sorted({(q["aggm"], q["cls"], q["why"]) for q in pairs.values()}), victims=vrows)
Path(stem + "_summary.json").write_text(json.dumps(summ, indent=1) + "\n")
print("crossings", len(rows), "pairs", len(pairs), "strips", summ["strips_crossed"], "aggressor nets", summ["aggressor_nets"])
print("total aF by class", summ["total_aF_by_class"], "| own block metal (not counted)", summ["own_block_metal_over_own_strips_aF"])
for r in vrows[:25]:
    print(f"  {r['node']:8s} {str(r['magic'][:2])[:60]:60s} {','.join(r['blocks'])[:28]:28s} switching(most) {r['switching_most_aF']:7.1f} aF  middle {r['middle_aF']}")
