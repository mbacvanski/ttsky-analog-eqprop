"""The Tiny Tapeout project folder for one GDS, one command (project Python; KLayout and Magic as tt_precheck.py).

  PY -I make_tt_project.py GDS TAG          -> takeover/layout/tt_project/, results/tt_project_TAG.json,
                                               results/precheck_logs/tt_project_TAG/

1. Stage (tt_precheck.py stage(), the accepted rule): the top cell renamed tt_um_mbacvanski_analog_eqprop, every other cell
   but the PDK's standard cells prefixed "tt_um_mbacvanski_analog_eqprop__"; LEF by Magic `lef write -hide -pinonly`, every
   pin's layer and rectangles checked equal to the earlier chip's LEF, DIRECTION and USE taken from it.
2. The folder: from the earlier chip's template (programmable_weights_v4_20261114/floorplan/tt_project_v4) only what is
   not reader text: LICENSE, .gitignore, .github/workflows, test/requirements.txt; the reader texts README.md, info.yaml,
   docs/info.md and src/project.v from their one home, takeover/docs/ (tt_precheck.public_texts(): repo/README.md, info.yaml,
   info.md, project.v; since 24 Nov); then the staged GDS in gds/ (and gzip -9n beside it, since the folder's .gitignore
   keeps gds/*.gds out of git), the LEF in lef/, and tt_submission/ (GDS, LEF, Verilog stub) as Tiny Tapeout's action
   builds it.
3. Proof that no shape or label moved: the design lead's programmable_weights_v4_20261114/checks_top/gds_same.py, the
   input GDS against tt_project/gds/ (flattened, every layer XORed, labels compared as (layer, text, x, y)).
4. Pins against Tiny Tapeout's template (feasibility_20261107/floorplan/template/tt_analog_2x2.def, the analog 2x2 tile):
   every template pin must be in the LEF with the template's layer and rectangle, exactly once, and in the GDS as a pin
   shape (purpose 16) and a drawn shape (purpose 20) covering that rectangle with a label of the pin's name inside it.
   The LEF's supply stripes are listed (the template leaves them to the design).
5. Tiny Tapeout's precheck (tt_precheck.py run_precheck) on tt_project/tt_submission itself, with their tools at GitHub's
   main (since 23 Nov, 22:00; tt_precheck.tools_state: fetched and fast-forwarded first, the commit and whether it equals
   GitHub's main printed and recorded; TT_PRECHECK_OFFLINE=1 skips the fetch).
"""
from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tt_precheck as tp  # noqa: E402

OUT = tp.OUT
PROJ = OUT / "tt_project"
GDS_SAME = tp.X / "programmable_weights_v4_20261114/checks_top/gds_same.py"
PINCHECK = r'''
import json, sys, klayout.db as db
gds, pins_json = sys.argv[1:3]
pins = json.loads(open(pins_json).read())
LAY = {"met1": 68, "met2": 69, "met3": 70, "met4": 71, "met5": 72}
ly = db.Layout(); ly.read(gds); top = ly.top_cell(); dbu = ly.dbu
def reg(l, d):
    li = ly.find_layer(l, d)
    r = db.Region() if li is None else db.Region(top.begin_shapes_rec(li)); r.merge(); return r
texts = {}
for li in ly.layer_indexes():
    info = ly.get_info(li)
    it = top.begin_shapes_rec(li)
    while not it.at_end():
        s = it.shape()
        if s.is_text():
            t = s.text.transformed(it.trans())
            texts.setdefault(s.text.string, []).append((info.layer, info.datatype, t.x * dbu, t.y * dbu))
        it.next()
cache = {}
out = {}
for name, p in pins.items():
    l = LAY[p["layer"]]
    for d in (16, 20):
        cache.setdefault((l, d), reg(l, d))
    box = db.Box(*[round(v / dbu) for v in p["rect"]])
    R = db.Region(box)
    cov = {d: round((cache[(l, d)] & R).area() / R.area(), 4) for d in (16, 20)}
    lab = [t for t in texts.get(name, []) if t[0] == l and p["rect"][0] <= t[2] <= p["rect"][2] and p["rect"][1] <= t[3] <= p["rect"][3]]
    out[name] = dict(pin_shape_cover=cov[16], drawn_cover=cov[20], labels_inside=len(lab), label_purposes=sorted({t[1] for t in lab}))
print(json.dumps(out))
'''


def gz(src: Path, dst: Path):
    with open(src, "rb") as fi, open(dst, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw, mtime=0) as fo:
            shutil.copyfileobj(fi, fo)


def def_pins():
    txt = tp.DEF.read_text()
    pins = {}
    for m in re.finditer(r"- (\S+) \+ NET \S+ \+ DIRECTION (\S+) \+ USE (\S+)\s+\+ PORT\s+\+ LAYER (\S+) \( (\S+) (\S+) \) \( (\S+) (\S+) \)\s+\+ PLACED \( (\S+) (\S+) \)", txt):
        n, d, u, l, x1, y1, x2, y2, ox, oy = m.groups()
        pins[n] = dict(direction=d, use=u, layer=l, rect=[(int(ox) + int(x1)) / 1000, (int(oy) + int(y1)) / 1000,
                                                          (int(ox) + int(x2)) / 1000, (int(oy) + int(y2)) / 1000])
    return pins


def lef_pins(text):
    out = {}
    for m in re.finditer(r"(?ms)^  PIN (\S+)\n(.*?)^  END \1\n", text):
        ports, layer = [], None
        for line in m[2].splitlines():
            t = line.strip()
            if t.startswith("LAYER"):
                layer = t.split()[1]
            elif t.startswith("RECT"):
                ports.append((layer, [float(v) for v in t.split()[1:5]]))
        d = re.search(r"DIRECTION (\S+)", m[2])
        u = re.search(r"USE (\S+)", m[2])
        out[m[1]] = dict(rects=ports, direction=d[1] if d else None, use=u[1] if u else None)
    return out


def main(gds, tag):
    gds = Path(gds).resolve()
    res = dict(input_gds=str(gds), input_gds_sha256=tp.sha(gds), method=__doc__.strip())
    res["tools_state"] = tp.tools_state()
    st = tp.stage(gds, tag)
    res["stage"] = st
    staged_gds, staged_lef = OUT / st["gds"], OUT / st["lef"]
    # 2. the folder: the template's non-text files, then the public texts from their one home
    if PROJ.exists():
        shutil.rmtree(PROJ)
    for f in ("LICENSE", ".gitignore", ".github/workflows/docs.yaml", ".github/workflows/gds.yaml", "test/requirements.txt"):
        (PROJ / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tp.TEMPLATE / f, PROJ / f)
    texts = tp.public_texts()
    for f, src in texts.items():
        (PROJ / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, PROJ / f)
    (PROJ / "lef").mkdir(exist_ok=True)
    res["public_texts"] = {f: str(src.relative_to(tp.X)) if src.is_relative_to(tp.X) else f"(the tree's top folder) {f}" for f, src in texts.items()}
    (PROJ / "gds").mkdir()
    shutil.copyfile(staged_gds, PROJ / "gds" / f"{tp.TOP}.gds")
    gz(PROJ / "gds" / f"{tp.TOP}.gds", PROJ / "gds" / f"{tp.TOP}.gds.gz")
    shutil.copyfile(staged_lef, PROJ / "lef" / f"{tp.TOP}.lef")
    lef_text = staged_lef.read_text()
    sub_gds = tp.submission(PROJ, PROJ, PROJ / "gds" / f"{tp.TOP}.gds", lef_text)
    files = sorted(str(p.relative_to(PROJ)) for p in PROJ.rglob("*") if p.is_file())
    res["folder"] = dict(path=str(PROJ.relative_to(OUT)), files={f: tp.sha(PROJ / f) for f in files},
                         public_texts_equal_their_sources={f: tp.sha(PROJ / f) == tp.sha(src) for f, src in texts.items()})
    # 3. the design check's proof
    p = subprocess.run([str(tp.KPY), str(GDS_SAME), str(gds), str(PROJ / "gds" / f"{tp.TOP}.gds"), str(OUT / "results" / f"tt_project_gds_same_{tag}.json")],
                       capture_output=True, text=True)
    res["gds_same"] = dict(exit_code=p.returncode, output=p.stdout.strip().splitlines()[-3:], verdict="THE SAME LAYOUT" in p.stdout)
    # 4. pins against the template
    tpins = def_pins()
    lp = lef_pins(lef_text)
    lef_vs = {}
    for n, t in tpins.items():
        got = lp.get(n)
        ok = bool(got) and len(got["rects"]) == 1 and got["rects"][0][0] == t["layer"] and all(abs(a - b) < 1e-6 for a, b in zip(got["rects"][0][1], t["rect"]))
        lef_vs[n] = dict(ok=ok, template=[t["layer"], t["rect"]], lef=got["rects"] if got else None,
                         direction_ok=bool(got) and got["direction"] == t["direction"], use_ok=bool(got) and got["use"] == t["use"])
    pj = OUT / "build" / tag / "tt" / "template_pins.json"
    pj.write_text(json.dumps(tpins))
    gp = json.loads(tp.kpy(PINCHECK, PROJ / "gds" / f"{tp.TOP}.gds", pj))
    gds_vs = {n: dict(v, ok=v["pin_shape_cover"] >= 0.9999 and v["drawn_cover"] >= 0.9999 and v["labels_inside"] >= 1) for n, v in gp.items()}
    res["pins"] = dict(template=str(tp.DEF.relative_to(tp.X)), template_pins=len(tpins),
                       lef_matches_template=sum(v["ok"] for v in lef_vs.values()), lef_direction_and_use_match=sum(v["direction_ok"] and v["use_ok"] for v in lef_vs.values()),
                       gds_matches_template=sum(v["ok"] for v in gds_vs.values()),
                       lef_pins_not_in_template=sorted(set(lp) - set(tpins)),
                       supply_stripes={n: lp[n]["rects"] for n in lp if n not in tpins},
                       mismatches_lef={n: v for n, v in lef_vs.items() if not (v["ok"] and v["direction_ok"] and v["use_ok"])},
                       mismatches_gds={n: v for n, v in gds_vs.items() if not v["ok"]})
    # 5. the precheck on the folder's own submission
    tools = tp.tool_copy()
    pc = tp.run_precheck(tools, sub_gds, OUT / "results" / "precheck_logs" / f"tt_project_{tag}")
    res["precheck"] = pc
    res["precheck_all_pass"] = pc["exit_code"] == 0 and bool(pc.get("checks")) and all(v == "✅" for v in pc["checks"].values())
    res["all_good"] = (res["gds_same"]["verdict"] and res["precheck_all_pass"] and not res["pins"]["mismatches_lef"] and not res["pins"]["mismatches_gds"]
                       and res["pins"]["lef_matches_template"] == len(tpins))
    (OUT / "results" / f"tt_project_{tag}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(dict(gds_same=res["gds_same"], pins={k: v for k, v in res["pins"].items() if k != "supply_stripes"},
                          supply_stripes={k: len(v) for k, v in res["pins"]["supply_stripes"].items()},
                          precheck=pc.get("checks"), precheck_all_pass=res["precheck_all_pass"],
                          public_texts_equal_their_sources=res["folder"]["public_texts_equal_their_sources"], all_good=res["all_good"],
                          tt_support_tools=res["tools_state"]["commit"], equals_github_main=res["tools_state"]["equals_github_main"]), indent=1, ensure_ascii=False))
    return 0 if res["all_good"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
