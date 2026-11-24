"""Tiny Tapeout's precheck on one GDS, the way the accepted chip's flow runs it, with every raw log kept.

  PY -I tt_precheck.py GDS TAG            -> build/TAG/tt/ (staged project), results/precheck_TAG.json,
                                             results/precheck_logs/TAG/ (each run's full log, gzipped, and Tiny Tapeout's reports)

1. Stage (chip2x2/scripts/prefix_gds.py's rule, done here on a copy): the top cell gets the project's name
   tt_um_mbacvanski_analog_eqprop; every other cell but the PDK's standard cells (sky130_fd_sc_*) gets the prefix
   "tt_um_mbacvanski_analog_eqprop__", so that no cell name can clash with another project on the shuttle. Checked: on every
   layer the flattened shapes equal the input's (XOR empty) and the text labels are the same (layer, text, x, y).
   LEF: Magic `lef write -hide -pinonly` of the staged GDS read back (as programmable_weights_v4_20261114/floorplan/scripts/
   chip_tt.py stage). Project folder: the public texts info.yaml, src/project.v and docs/info.md from their one home,
   takeover/docs/ (public_texts(); since 24 Nov, before: the earlier chip's template's), the staged GDS and LEF.
2. Precheck: tt-support-tools/precheck at GitHub's main, as Tiny Tapeout's own CI runs it (since 23 Nov, 22:00; before:
   the pinned commit 9d13ff3 of 5 November, which lacks four later rules). Tools: ~/.local/opt/tt_proof/precheck_main
   (or TT_PRECHECK_DIR). Each run first fetches GitHub's main there and fast-forwards the checkout when it is behind
   (TT_PRECHECK_OFFLINE=1 skips the fetch, for runs without network); the commit used, GitHub's main at that moment and
   whether they are equal are printed and recorded. Run as feasibility_20261107/floorplan/scripts/run_checks.py
   run_precheck does: GDS, LEF and Verilog stub in <project>/tt_submission, `precheck.py --gds ... --tech sky130A`, Magic
   and KLayout shims, the installed venv, from a copy of the tool folder in build/precheck/ (it writes reports beside itself).
3. The accepted four planted faults (chip2x2/scripts/tt_checks.py), each in its own copy, each of which must be caught:
   a metal1 sliver (10 x 0.1 um) and a metal5 shape, both placed here at an empty spot found on the GDS (the accepted spot
   lies on a resistor block in this layout), a metal4 stub on the unused analog pin ua[3], and the first VGND stripe made to
   start 12 um up in the LEF.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
X = OUT.parents[2]                                         # hardware/mesa/xor_sky130
HOME = Path.home()
TOP = "tt_um_mbacvanski_analog_eqprop"
PREFIX = TOP + "__"
TEMPLATE = X / "programmable_weights_v4_20261114/floorplan/tt_project_v4"     # only its LEF (pin reference), LICENSE, workflows
TEMPLATE_LEF = "tt_um_mbacvanski_denseam_xor.lef"   # the template's own file name: the pin reference keeps the earlier chip's name
DOCS = X / "six_edge_programmable_20261117/takeover/docs"                    # the one home of every public text


def public_texts() -> dict:
    """The project folder's reader texts, {path in the project: source}: README.md, info.yaml, docs/info.md, src/project.v.
    In the design repository they come from takeover/docs/ (repo/README.md, info.yaml, info.md, project.v; src/project.v from
    the template when takeover/docs has none), and the datasheet's table docs/word_conductance.csv when takeover/docs has
    it. In the Tiny Tapeout repository's tree, whose top folder TT_PUBLIC_TEXTS_ROOT names, they are that tree's own
    top-level files."""
    root = os.environ.get("TT_PUBLIC_TEXTS_ROOT")
    if root:
        r = Path(root)
        out = {"README.md": r / "README.md", "info.yaml": r / "info.yaml", "docs/info.md": r / "docs/info.md", "src/project.v": r / "src/project.v"}
    else:
        out = {"README.md": DOCS / "repo/README.md", "info.yaml": DOCS / "info.yaml", "docs/info.md": DOCS / "info.md",
               "src/project.v": DOCS / "project.v" if (DOCS / "project.v").is_file() else TEMPLATE / "src/project.v"}
    missing = [k for k, v in out.items() if not v.is_file()]
    assert not missing, f"public texts missing: {missing} (from {root or DOCS})"
    csv = Path(root) / "docs/word_conductance.csv" if root else DOCS / "word_conductance.csv"
    if csv.is_file():                                   # the datasheet's table, beside it, when there is one
        out["docs/word_conductance.csv"] = csv
    return out
DEF = X / "feasibility_20261107/floorplan/template/tt_analog_2x2.def"
INSTALLED = Path(os.environ.get("TT_PRECHECK_DIR", HOME / ".local/opt/tt_proof/precheck_main"))
KPY = Path(os.environ.get("KLAYOUT_PY", HOME / ".local/opt/klayout-py/bin/python"))
MAGIC = Path(os.environ.get("MAGIC", HOME / ".local/bin/magic-8.3.685"))
KLAYOUT = Path(os.environ.get("KLAYOUT", HOME / ".local/bin/klayout-0.30.0"))
PDK_ROOT = Path(os.environ.get("PDK_ROOT", HOME / ".ciel"))
PRE = OUT / "build" / "precheck"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


STAGE = r'''
import json, sys, klayout.db as db
src, dst, top_name, prefix = sys.argv[1:5]
def texts(ly):
    top, out = ly.top_cell(), []
    for li in ly.layer_indexes():
        lp = ly.get_info(li)
        it = top.begin_shapes_rec(li)
        while not it.at_end():
            if it.shape().is_text():
                t = it.shape().text.transformed(it.trans())
                out.append((lp.layer, lp.datatype, it.shape().text.string, t.x, t.y))
            it.next()
    return sorted(out)
ly = db.Layout(); ly.read(src)
assert len(ly.top_cells()) == 1
old_top = ly.top_cell().name
renamed = {}
for c in ly.each_cell():
    if c.cell_index() == ly.top_cell().cell_index():
        if c.name != top_name:
            renamed[c.name] = top_name
            c.name = top_name
    elif not c.name.startswith("sky130_fd_sc_") and not c.name.startswith(prefix):
        renamed[c.name] = prefix + c.name
        c.name = prefix + c.name
opt = db.SaveLayoutOptions(); opt.gds2_write_timestamps = False   # the same input gives the same bytes
ly.write(dst, opt)
a, b = db.Layout(), db.Layout()
a.read(src); b.read(dst)
diff = {}
for li in a.layer_indexes():
    lp = a.get_info(li)
    lj = b.find_layer(lp.layer, lp.datatype)
    ra = db.Region(a.top_cell().begin_shapes_rec(li)); rb = db.Region(b.top_cell().begin_shapes_rec(lj)) if lj is not None else db.Region()
    x = ra ^ rb
    if not x.is_empty():
        diff[f"{lp.layer}/{lp.datatype}"] = x.count()
names = [c.name for c in b.each_cell()]
print(json.dumps(dict(old_top=old_top, cells=len(names), renamed=len(renamed), kept=sorted(n for n in names if n.startswith("sky130_fd_sc_")),
                      longest_name=max(map(len, names)), layers_compared=len(list(a.layer_indexes())), layers_that_differ=diff,
                      same_text_labels=texts(a) == texts(b))))
'''

EMPTY = r'''
import json, sys, klayout.db as db
gds = sys.argv[1]
ly = db.Layout(); ly.read(gds); top = ly.top_cell()
allm = db.Region()
for l, d in ((68, 20), (69, 20), (70, 20), (71, 20), (72, 20), (67, 20)):
    li = ly.find_layer(l, d)
    if li is not None:
        allm += db.Region(top.begin_shapes_rec(li))
allm.merge()
b = top.bbox()
for y in range(int(b.top - 8000), int(b.bottom + 8000), -500):
    for x in range(int(b.left + 8000), int(b.right - 20000), 500):
        box = db.Box(x - 1000, y - 1000, x + 11000, y + 1100)
        if (allm & db.Region(box)).is_empty():
            print(json.dumps([x / 1000, y / 1000, x / 1000 + 10.0, y / 1000 + 0.1])); sys.exit(0)
sys.exit("no empty spot")
'''

FAULT = r'''
import sys, klayout.db as db
src, dst, l, d, x0, y0, x1, y1 = sys.argv[1:9]
ly = db.Layout(); ly.read(src); top = ly.top_cell()
top.shapes(ly.layer(int(l), int(d))).insert(db.DBox(float(x0), float(y0), float(x1), float(y1)))
ly.write(dst)
'''


def kpy(code, *args):
    p = subprocess.run([str(KPY), "-c", code, *map(str, args)], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    lines = p.stdout.strip().splitlines()
    return lines[-1] if lines else ""


def template_pins():
    txt = DEF.read_text()
    pins = {}
    for m in re.finditer(r"- (\S+) \+ NET \S+ \+ DIRECTION (\S+) \+ USE (\S+)\s+\+ PORT\s+\+ LAYER (\S+) \( (\S+) (\S+) \) \( (\S+) (\S+) \)\s+\+ PLACED \( (\S+) (\S+) \)", txt):
        n, d, u, l, x1, y1, x2, y2, ox, oy = m.groups()
        pins[n] = ((int(ox) + int(x1)) / 1000, (int(oy) + int(y1)) / 1000, (int(ox) + int(x2)) / 1000, (int(oy) + int(y2)) / 1000)
    return pins


def stage(gds, tag):
    tt = OUT / "build" / tag / "tt"
    proj = tt / "project"
    if proj.exists():
        shutil.rmtree(proj)
    for d in ("src", "docs", "gds", "lef"):
        (proj / d).mkdir(parents=True, exist_ok=True)
    texts = public_texts()
    for f in ("info.yaml", "src/project.v", "docs/info.md"):
        shutil.copyfile(texts[f], proj / f)
    staged = proj / "gds" / f"{TOP}.gds"
    pre = json.loads(kpy(STAGE, gds, staged, TOP, PREFIX))
    assert not pre["layers_that_differ"] and pre["same_text_labels"], pre
    lefdir = tt / "lef_magic"
    lefdir.mkdir(parents=True, exist_ok=True)
    (lefdir / "tmp").mkdir(exist_ok=True)
    tcl = lefdir / "lef.tcl"
    lef = proj / "lef" / f"{TOP}.lef"
    tcl.write_text(f"gds read {staged}\nload {TOP}\nlef write {lef} -hide -pinonly\nquit -noprompt\n")
    env = dict(os.environ, PDK_ROOT=str(PDK_ROOT), TMPDIR=str(lefdir / "tmp"))
    p = subprocess.run([str(MAGIC), "-dnull", "-noconsole", "-rcfile", str(PDK_ROOT / "sky130A/libs.tech/magic/sky130A.magicrc"), str(tcl)],
                       cwd=lefdir, env=env, capture_output=True, text=True, timeout=1800)
    (lefdir / "lef.magic.log").write_text(p.stdout + p.stderr)
    assert p.returncode == 0 and lef.exists(), "Magic did not write the LEF"
    # Magic reads no port direction or use from a GDS. Every pin's layer and rectangles must equal the earlier chip's LEF
    # (Tiny Tapeout's template interface); then each pin's DIRECTION and USE lines are taken from that LEF.
    raw = lef.read_text()
    (lefdir / "from_magic.lef").write_text(raw)
    blk = re.compile(r"(?ms)^  PIN (\S+)\n(.*?)^  END \1\n")

    def pins(text):
        return {m[1]: m[2] for m in blk.finditer(text)}

    def geom(body):                     # the pin's ports as a multiset of (layer, rectangles): LEF order does not matter
        ports, cur, layer = [], [], None
        for l in body.splitlines():
            t = l.strip()
            if t.startswith("LAYER"):
                layer = t
            elif t.startswith("RECT"):
                cur.append((layer, t))
            elif t == "END" and cur:
                ports.append(tuple(sorted(cur)))
                cur = []
        return sorted(ports)

    def decl(body):
        return [l for l in body.splitlines() if re.match(r"\s*(DIRECTION|USE)\b", l)]
    mine, ref = pins(raw), pins((TEMPLATE / "lef" / TEMPLATE_LEF).read_text())
    assert not set(ref) - set(mine), ("template pins missing from the layout", sorted(set(ref) - set(mine)))
    extra = sorted(set(mine) - set(ref))      # top-level net labels Magic reads as ports from a GDS (the earlier chip has v4_* ones)
    if extra:
        raw = blk.sub(lambda m: "" if m[1] in extra else m[0], raw)
        mine = pins(raw)
    bad = [n for n in ref if geom(mine[n]) != geom(ref[n])]
    assert not bad, f"pins whose geometry differs from the earlier chip's LEF: {bad[:10]}"
    for n, b in mine.items():         # a declaration Magic did write must agree with the earlier chip's
        assert all(l.strip() in [x.strip() for x in decl(ref[n])] for l in decl(b)), (n, decl(b), decl(ref[n]))

    def add(m):
        have = [x.strip() for x in decl(m[2])]
        extra = [l for l in decl(ref[m[1]]) if l.strip() not in have]
        return f"  PIN {m[1]}\n" + "".join(l + "\n" for l in extra) + m[2] + f"  END {m[1]}\n"
    declared = blk.sub(add, raw)
    lef.write_text(declared)

    def pin_lines(path):
        out, inside = [], False
        for l in Path(path).read_text().splitlines():
            if re.match(r"\s*PIN ", l):
                inside = True
            if inside and "ANTENNA" not in l:
                out.append(l)
            if inside and re.match(r"  END \S", l):
                inside = False
        return out
    mine, theirs = pin_lines(lef), pin_lines(TEMPLATE / "lef" / TEMPLATE_LEF)
    return dict(project=str(proj.relative_to(OUT)), gds=str(staged.relative_to(OUT)), gds_sha256=sha(staged), input_gds_sha256=sha(gds),
                prefix=pre, lef=str(lef.relative_to(OUT)), lef_sha256=sha(lef),
                lef_extra_ports_dropped=extra,
                lef_method="Magic `lef write -hide -pinonly` of the staged GDS (ports that are not Tiny Tapeout pins dropped); every pin's layer and rectangles checked equal to the earlier chip's LEF "
                           "(tt_project_v4); then each pin's DIRECTION and USE lines taken from that LEF (Magic reads none from a GDS)",
                lef_pin_lines_identical_to_the_earlier_chips=mine == theirs, lef_pin_lines=len(mine),
                lef_pin_line_differences=[(a, b) for a, b in zip(mine, theirs) if a != b][:10] + ([("length", len(mine), len(theirs))] if len(mine) != len(theirs) else []))


def git(d, *args, timeout=120):
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=timeout)


def tools_state():
    """The installed tools' commit against GitHub's main at this moment; fast-forward when behind (printed and recorded)."""
    src = INSTALLED / "tt-support-tools"
    head = git(src, "rev-parse", "HEAD").stdout.strip()
    st = dict(folder=str(INSTALLED).replace(str(HOME), "~"), commit_before=head)
    if os.environ.get("TT_PRECHECK_OFFLINE") == "1":
        st.update(github_main=None, checked="no: TT_PRECHECK_OFFLINE=1 (no network)")
    else:
        f = git(src, "fetch", "--quiet", "origin", "main")
        if f.returncode != 0:
            st.update(github_main=None, checked="no: git fetch failed: " + (f.stderr or f.stdout).strip()[-300:])
        else:
            remote = git(src, "rev-parse", "origin/main").stdout.strip()
            st.update(github_main=remote, checked=time.strftime("%Y-%m-%d %H:%M:%S %Z"))
            if remote != head and git(src, "merge-base", "--is-ancestor", head, remote).returncode == 0:
                m = git(src, "merge", "--ff-only", "--quiet", "origin/main")
                st["fast_forwarded"] = m.returncode == 0
                if m.returncode != 0:
                    st["fast_forward_error"] = (m.stderr or m.stdout).strip()[-300:]
            elif remote != head:
                st["note"] = "the installed checkout is not behind GitHub's main (it is ahead or has diverged); left as it is"
    st["commit"] = git(src, "rev-parse", "HEAD").stdout.strip()
    st["commit_date"] = git(src, "log", "-1", "--format=%cI").stdout.strip()
    st["equals_github_main"] = None if st.get("github_main") is None else st["commit"] == st["github_main"]
    print(f"precheck tools: tt-support-tools {st['commit'][:7]} ({st['commit_date']}); GitHub main "
          + ("not checked (" + st["checked"] + ")" if st["github_main"] is None else
             f"{st['github_main'][:7]} at {st['checked']}: " + ("EQUAL" if st["equals_github_main"] else "DIFFERENT")
             + (f"; fast-forwarded from {head[:7]}" if st.get("fast_forwarded") else "")), flush=True)
    return st


def tool_copy():
    src, dst = INSTALLED / "tt-support-tools", PRE / "tt-support-tools"
    head = lambda d: subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()   # noqa: E731
    TT_REF = head(src)
    if not (dst / ".git").exists() or head(dst) != TT_REF:
        if dst.exists():
            shutil.rmtree(dst)
        PRE.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("reports", "__pycache__"))
    assert head(dst) == TT_REF == head(src), (head(dst), head(src))
    assert all(sha(dst / "precheck" / f.name) == sha(f) for f in (src / "precheck").iterdir() if f.is_file()), "the copy differs from the installed tool"
    return dst


def run_precheck(tools, gds, logdir):
    shim = PRE / "bin"
    shim.mkdir(parents=True, exist_ok=True)
    for name, target in (("magic", MAGIC), ("klayout", KLAYOUT)):
        link = shim / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)
    pdir = tools / "precheck"
    reports = pdir / "reports"
    if reports.exists():
        shutil.rmtree(reports)
    reports.mkdir()
    (PRE / "tmp").mkdir(exist_ok=True)
    venv = INSTALLED / "venv"
    env = dict(os.environ, PATH=f"{shim}:{venv / 'bin'}:{os.environ['PATH']}", PDK_ROOT=str(PDK_ROOT), PDK="sky130A", TMPDIR=str(PRE / "tmp"),
               PYTHONDONTWRITEBYTECODE="1")
    t0 = time.time()
    p = subprocess.run([str(venv / "bin" / "python"), "precheck.py", "--gds", str(gds), "--tech", "sky130A"], cwd=pdir, env=env,
                       capture_output=True, text=True, timeout=7200)
    logdir.mkdir(parents=True, exist_ok=True)
    with gzip.open(logdir / "precheck_log.txt.gz", "wt") as f:
        f.write(p.stdout + p.stderr)
    if (logdir / "reports").exists():
        shutil.rmtree(logdir / "reports")
    shutil.copytree(reports, logdir / "reports")
    for big in (logdir / "reports").rglob("*"):
        if big.is_file() and big.stat().st_size > 1_000_000:
            with open(big, "rb") as fi, gzip.open(str(big) + ".gz", "wb") as fo:
                fo.write(fi.read())
            big.unlink()
    out = dict(exit_code=p.returncode, seconds=round(time.time() - t0, 1), gds_sha256=sha(gds))
    md = reports / "results.md"
    if md.exists():
        rows = re.findall(r"^\| (.+?) \| (.+?) \|$", md.read_text(), re.M)
        out["checks"] = {k.strip(): v.strip() for k, v in rows if k.strip() not in ("Check", "-----------")}
    xml = reports / "results.xml"
    if xml.exists():
        fails = {}
        for tc in ET.parse(xml).getroot().iter("testcase"):
            f = tc.find("failure")
            if f is not None:
                fails[tc.get("name")] = (f.get("message") or f.text or "")[:500]
        out["failures"] = fails
    mdrc = reports / "magic_drc.txt"
    if mdrc.exists():
        m = re.search(r"COUNT: (\d+)", mdrc.read_text())
        out["magic_drc_count"] = int(m.group(1)) if m else None
    for xmlf in sorted(reports.glob("drc_*.xml")):
        out.setdefault("klayout_items", {})[xmlf.stem] = len(re.findall(r"<item>", xmlf.read_text()))
    out["log"] = str((logdir / "precheck_log.txt.gz").relative_to(OUT))
    return out


def submission(proj, base, gds_src, lef_text):
    sub = base / "tt_submission"
    if sub.exists():
        shutil.rmtree(sub)
    sub.mkdir(parents=True)
    if base != proj:
        shutil.copyfile(proj / "info.yaml", base / "info.yaml")
    shutil.copyfile(gds_src, sub / f"{TOP}.gds")
    (sub / f"{TOP}.lef").write_text(lef_text)
    shutil.copyfile(proj / "src" / "project.v", sub / f"{TOP}.v")
    return sub / f"{TOP}.gds"


def main(gds, tag):
    gds = Path(gds).resolve()
    res = dict(input_gds=str(gds), method=__doc__.strip())
    res["tools_state"] = tools_state()
    st = stage(gds, tag)
    res["stage"] = st
    print(json.dumps(st, indent=1)[:1500], flush=True)
    tools = tool_copy()
    proj = OUT / st["project"]
    lef = (OUT / st["lef"]).read_text()
    logs = OUT / "results" / "precheck_logs" / tag
    g = submission(proj, proj, OUT / st["gds"], lef)
    pc = run_precheck(tools, g, logs / "precheck")
    res["precheck"] = pc
    res["all_pass"] = pc["exit_code"] == 0 and bool(pc.get("checks")) and all(v == "✅" for v in pc["checks"].values())
    print(json.dumps(pc, indent=1, ensure_ascii=False), flush=True)
    spot = json.loads(kpy(EMPTY, OUT / st["gds"]))
    ua3 = template_pins()["ua[3]"]
    faults = {"met1_sliver": ((68, 20), spot, ["Magic DRC", "KLayout BEOL"]),
              "met5_shape": ((72, 20), [spot[0], spot[1], spot[0] + 2.0, spot[1] + 1.0], ["KLayout Checks"]),
              "ua3_touched": ((71, 20), [ua3[0], ua3[3], ua3[2], ua3[3] + 1.5], ["Analog pin check"]),
              "vgnd_starts_at_12um": (None, None, ["Pin check"])}
    neg = {}
    for name, (ld, rect, expect) in faults.items():
        base = OUT / "build" / tag / "tt" / "planted" / name
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True)
        text = lef
        src = OUT / st["gds"]
        if ld is None:
            text, n = re.subn(r"(PIN VGND.*?RECT \S+ )(\S+)", lambda m: m.group(1) + "12.000", lef, count=1, flags=re.S)
            assert n == 1
        else:
            src = base / "faulty.gds"
            kpy(FAULT, OUT / st["gds"], src, *ld, *rect)
        g = submission(proj, base, src, text)
        r = run_precheck(tools, g, logs / name)
        failed = sorted(k for k, v in r.get("checks", {}).items() if v != "✅")
        neg[name] = dict(layer=f"{ld[0]}/{ld[1]}" if ld else "LEF", rect_um=rect, expected=expect, failed=failed, caught=all(e in failed for e in expect),
                         log=r["log"])
        print(name, neg[name], flush=True)
    res["planted_faults"] = neg
    res["all_planted_faults_caught"] = all(v["caught"] for v in neg.values())
    res["supply_pin_rectangles"] = {p: len(re.findall(r"\bRECT\b", re.search(rf"PIN {p}\b.*?END {p}", lef, re.S)[0])) for p in ("VGND", "VDPWR")}
    res["tools"] = dict(tt_support_tools=res["tools_state"]["commit"], tt_support_tools_equals_github_main=res["tools_state"]["equals_github_main"], magic="8.3.685 (Tiny Tapeout's action: 8.3.568)", klayout="0.30.0 (action: 0.30.4)",
                        pdk="sky130A from ~/.ciel (action: ciel sky130A 0536d02)")
    (OUT / "results" / f"precheck_{tag}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print("ALL PASS" if res["all_pass"] else "PRECHECK FAILED", "| planted faults caught:", res["all_planted_faults_caught"],
          f"| tools {res['tools_state']['commit'][:7]}, equal to GitHub's main: {res['tools_state']['equals_github_main']}")
    return 0 if res["all_pass"] and res["all_planted_faults_caught"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
