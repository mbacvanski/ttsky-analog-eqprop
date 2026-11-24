"""Capacitance of the important nodes and their coupling to digital lines, one chip beside another, from Magic's flat
extraction with every coupling (magic_flows.py cap, the accepted wired_extract.cap() sequence) of each GDS (project Python).

  PY -I cap_compare.py SEL_GDS SEL_EXT SEL_ROLES CTRL_GDS CTRL_EXT CTRL_ROLES OUT.json [BASE_EXT]

ROLES: over_blocks.py's output for that GDS (block roles and outlines). A Magic flat name is "<instance>.<path>"; the
instance's role (H1, H2, Z, BUF_REF ...) is found by place: the node records named after an instance lie inside one role's
outline. The victims are the earlier chip's own list (programmable_weights_v4_20261114/floorplan/scripts/cost.py VICTIMS,
the same labels under the role names), plus the six-weight chip's new nodes where they exist: each stored gate of the
programmable resistor words (<bank>.XC<k>.gn), the two stored bias words' gates (BIAS.sg1, sg2), the midpoints of the two
new fixed arrays. "Total" is every extracted capacitor on the net: to the substrate and to every other net (devices
not counted, as cost.py). "Digital" is the sum of its couplings to nets that carry a Tiny Tapeout digital pin
(ui_in, uio_in, uo_out, clk, ena, rst_n), a standard cell's pin (names with XSTD or sky130_fd_sc), or a control label
(write strobes we*, iso, clampw, six, park, weak, en, sel...). A node is flagged when the selected chip's value is more than
twice the earlier chip's (or above 1 fF where the earlier chip has none).
"""
import collections
import gzip
import json
import re
import sys
from pathlib import Path

DIGITAL_PIN = re.compile(r"^(ui_in|uio_in|uo_out)\[\d\]$|^(clk|ena|rst_n)$")
DIGITAL_WORD = re.compile(r"XSTD\.(Y|A|B|C)$|sky130_fd_sc_hd__\w+\.(Y|A|B|C)$|^ne_mode_bank_gates_\d+\.[zab]\d$|"
                          r"(^|\.)(we\d|v4_we\d|iso|v4_iso|isog|clampw|v4_clampw|clamp_b|six|park|weak|weak_b|"
                          r"weak_src|weak_b_src|res_filtered|en|en_b|sel\d?|sel_[a-z]|free_on|cue_on|state_on|state_b|reset_b|clamp|"
                          r"nbp|ne1|ne2|armed|narmed|nwrite|bp|bp_b|wb\d|ne\d)$")
SUPPLY = re.compile(r"^(VDPWR|VGND)$|\.(VPB|VNB|VPWR|VGND)$")


def read_ext(path):
    t = (gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)).read()
    names = collections.defaultdict(set)
    pos = {}
    for m in re.finditer(r'^(node|substrate) "([^"]+)" \S+ (\S+)(?: (-?\d+) (-?\d+) (\S+))?', t, re.M):
        names[m[2]].add(m[2])
        if m[4] is not None:
            pos[m[2]] = (int(m[4]) * 0.005, int(m[5]) * 0.005)
    sub = re.search(r'^substrate "([^"]+)"', t, re.M)[1]
    for a, b in re.findall(r'^equiv "([^"]+)" "([^"]+)"', t, re.M):
        names[a].add(b)
    rep = {x: n for n, s in names.items() for x in s}
    lump = collections.defaultdict(float)
    for m in re.finditer(r'^node "([^"]+)" \S+ (\S+)', t, re.M):
        lump[m[1]] += float(m[2])
    coup = collections.defaultdict(lambda: collections.defaultdict(float))
    for m in re.finditer(r'^cap "([^"]+)" "([^"]+)" (\S+)', t, re.M):
        a, b, v = rep.get(m[1], m[1]), rep.get(m[2], m[2]), float(m[3])
        coup[a][b] += v
        coup[b][a] += v
    return dict(names=names, rep=rep, lump=lump, coup=coup, sub=sub, pos=pos)


def roles_by_records(gds, blocks):
    """Magic names an unnamed instance <cell>_<k>, k counting that cell's records in REVERSE file order (checked on the
    selected GDS: all 45 instances that could be placed by their own nets agree, none disagrees)."""
    import subprocess
    here = Path(__file__).resolve().parent
    o = json.loads(subprocess.run([sys.executable, "-I", str(here / "gds_sref_order.py"), str(gds)], capture_output=True, text=True, check=True).stdout)
    disp = {}
    for role, b in blocks.items():
        x, y = map(int, b["trans"].split()[1].split(","))
        disp[(b["cell"], x, y)] = role
    n = collections.Counter(c for c, *_ in o["instances"])
    return {f"{c}_{n[c] - 1 - k}": disp.get((c, x, y)) for c, x, y, k in o["instances"]}


def roles_of(ext, blocks):
    """Magic instance name -> role. A GDS instance with a name (the earlier chip's) is its role. An unnamed one is called
    <cell>_<k> by Magic: among the blocks of that cell, the one whose outline holds the points of the instance's own nets
    (nets that do not leave the instance)."""
    insts = {nm.split(".")[0] for s in ext["names"].values() for nm in s if "." in nm}
    out = {i: i for i in insts if i in blocks}
    by_cell = collections.defaultdict(list)
    for r, b in blocks.items():
        by_cell[b["cell"]].append(r)
    votes = collections.defaultdict(collections.Counter)
    for n, (x, y) in ext["pos"].items():
        own = {nm.split(".")[0] for nm in ext["names"][n]}
        if len(own) != 1 or any("." not in nm for nm in ext["names"][n]):
            continue                                  # a net that leaves its instance can lie anywhere: no vote
        inst = own.pop()
        cands = by_cell.get(inst.rsplit("_", 1)[0], [])
        inside = [r for r in cands if (lambda bx: bx[0] - 0.01 <= x <= bx[2] + 0.01 and bx[1] - 0.01 <= y <= bx[3] + 0.01)(blocks[r]["outline_chip_um"])]
        if len(inside) == 1:
            votes[inst][inside[0]] += 1
    for i in insts:
        if i in out:
            continue
        cands = by_cell.get(i.rsplit("_", 1)[0], [])
        if len(cands) == 1:
            out[i] = cands[0]
        elif votes[i]:
            out[i] = votes[i].most_common(1)[0][0]
    return out


V4_VICTIMS = [("f1", "H1.y"), ("f2", "H2.y"), ("z", "Z.y"), ("p1", "H1.XU3.plus"), ("q1", "H1.XU3.minus"), ("p2", "H2.XU3.plus"), ("q2", "H2.XU3.minus"),
              ("pz", "Z.XU3.plus"), ("qz", "Z.XU3.minus"), ("ref", "BUF_REF.out"), ("h1", "H1.h"), ("h2", "H2.h"), ("hz", "Z.h"),
              ("natural1", "H1.natural"), ("natural2", "H2.natural"), ("bias1", "OBS.bias1"), ("bias2", "OBS.bias2"), ("vbn", "LEAN.XLB.vbn"),
              ("bias1_in", "EXT1.out"), ("bias2_in", "EXT2.out"), ("sense", "RSENSE.sense"), ("obs_out", "RSENSE.inp"), ("sense2", "OBS2.sense"),
              ("ext_in", "PINRES.ext_in"), ("mid1", "RW.XARRAY.R2_1"), ("mid2", "RW.XARRAY.R2_3")]
# (cost.py's seven amplifier hold nodes carry labels only in the .mag hierarchy; a GDS read names them on neither chip)
NEW = [("stored gate %s XC%d" % (b, k), f"{b}.XC{k}.gn") for b in ("RBLOCK", "ROWS_A", "ROWS_B") for k in range(4)]
NEW += [("stored bias word 1", "BIAS.sg1"), ("stored bias word 2", "BIAS.sg2"), ("A midpoint 1", "RW_A.rw_res_0.XARRAY.R2_1"),
        ("A midpoint 2", "RW_A.rw_res_0.XARRAY.R2_3"), ("B midpoint 1", "RW_B.rw_res_0.XARRAY.R2_1"), ("B midpoint 2", "RW_B.rw_res_0.XARRAY.R2_3")]


def find(ext, role2inst, label):
    role, rest = label.split(".", 1)
    for inst in role2inst.get(role, [role]):
        want = f"{inst}.{rest}"
        if want in ext["rep"]:
            return ext["rep"][want]
    return None


def is_digital(ext, n):
    names = ext["names"].get(n, {n})
    if n == ext["sub"] or any(SUPPLY.search(x) for x in names):
        return False
    return any(DIGITAL_PIN.match(x) or DIGITAL_WORD.search(x) for x in names)


def measure(ext, n):
    tot = ext["lump"][n] + sum(ext["coup"][n].values())
    dig = {o: v for o, v in ext["coup"][n].items() if is_digital(ext, o)}
    return dict(net=n, total_fF=round(tot / 1000, 3), to_substrate_fF=round(ext["lump"][n] / 1000, 3),
                digital_fF=round(sum(dig.values()) / 1000, 4),
                digital_top=[(o, round(v / 1000, 4)) for o, v in sorted(dig.items(), key=lambda kv: -kv[1])[:6]])


def main(sg, se, sr, cg, ce, cr, out, base=None):
    S, C = read_ext(se), read_ext(ce)
    sb = json.loads(Path(sr).read_text())["blocks"]
    cb = json.loads(Path(cr).read_text())["blocks"]
    s_roles, c_roles = roles_of(S, sb), roles_of(C, cb)
    for roles, g, b in ((s_roles, sg, sb), (c_roles, cg, cb)):
        rec = roles_by_records(g, b)
        bad = {i: (r, rec.get(i)) for i, r in roles.items() if i in rec and rec[i] != r and i not in b}
        assert not bad, ("instance roles by their nets and by record order disagree", bad)
        for i, r in rec.items():
            roles.setdefault(i, r)
    s_r2i, c_r2i = collections.defaultdict(list), collections.defaultdict(list)
    for i, r in s_roles.items():
        s_r2i[r].append(i)
    for i, r in c_roles.items():
        c_r2i[r].append(i)
    K = read_ext(base) if base else None
    k_r2i = collections.defaultdict(list)
    if K:
        kr = roles_of(K, sb)
        for i, r in roles_by_records(sg, sb).items():
            kr.setdefault(i, r)
        for i, r in kr.items():
            k_r2i[r].append(i)
    rows, flags = [], []
    # the programmable-offset variant's stored gates (bg, bg1, bg2 in its new cells): found by name, whatever their instance
    extra = sorted({S["rep"][n] for n in S["rep"] if re.search(r"(^|\.)bg\d?$", n)})
    for n in extra:
        rows.append(dict(node=f"variant stored offset gate {n}", label=n, selected=measure(S, n), earlier_chip=None))
    for name, label in V4_VICTIMS + NEW:
        ns, nc = find(S, s_r2i, label), find(C, c_r2i, label)
        r = dict(node=name, label=label, selected=measure(S, ns) if ns else None, earlier_chip=measure(C, nc) if nc else None)
        if K:
            nk = find(K, k_r2i, label)
            r["selected_base_extraction"] = measure(K, nk) if nk else None
        for key in ("total_fF", "digital_fF"):
            a = r["selected"][key] if r["selected"] else None
            b = r["earlier_chip"][key] if r["earlier_chip"] else None
            if a is not None and ((b and a > 2 * b) or (not b and a > 1.0)):
                flags.append(dict(node=name, quantity=key, selected=a, earlier_chip=b))
        rows.append(r)
    res = dict(method=__doc__.strip(), selected_ext=se, earlier_chip_ext=ce, base_ext=base, instance_roles_selected=s_roles,
               rows=rows, flagged_more_than_twice=flags)
    Path(out).write_text(json.dumps(res, indent=1) + "\n")
    print(f"{'node':26s} {'total fF sel / earlier':>24s}   {'digital fF sel / earlier':>26s}  base total   top digital (selected)")
    for r in rows:
        s, c = r["selected"], r["earlier_chip"]
        k = r.get("selected_base_extraction")
        st = f"{s['total_fF']:9.2f}" if s else "        -"
        ct = f"{c['total_fF']:9.2f}" if c else "        -"
        sd = f"{s['digital_fF']:9.3f}" if s else "        -"
        cd = f"{c['digital_fF']:9.3f}" if c else "        -"
        kt = f"{k['total_fF']:9.2f}" if k else "        -"
        top = ", ".join(f"{o.split('.')[-1] if len(o) > 30 else o} {v}" for o, v in (s["digital_top"][:3] if s else []))
        print(f"{r['node']:26s} {st} / {ct}      {sd} / {cd}   {kt}   {top}")
    print("flagged:", json.dumps(flags))


if __name__ == "__main__":
    main(*sys.argv[1:9])
