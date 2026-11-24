"""Rebuild the six-weight chip's layout from the Tiny Tapeout repository's source/ folder alone, and compare it with the
repository's gds/ and lef/ (any Python 3; the stages run under the interpreters given below).

  PY=<Python 3.11 with numpy and scipy> [KPY=<Python with the klayout module>] [SYSPY=/usr/bin/python3] \\
      python3 source/six_edge_programmable_20261117/takeover/layout/freeze/from_source.py [--stages id,id] [--no-checks]

Run from the repository's top folder (the one holding gds/, lef/ and source/). Tools as the scripts take them: Magic
8.3.685 and netgen 1.5.325 (MAGIC, NETGEN, default ~/.local/bin), the SKY130A PDK (PDK_ROOT, default ~/.ciel), g++ (the
routers are compiled at run time), Tiny Tapeout's tools (TT_PRECHECK_DIR; TT_PRECHECK_OFFLINE=1 without network).
Writes rebuild/ (every stage's folder and log) and from_source.json in the top folder; exit status 0 only if all agrees.

What it does, in order (source/MANIFEST.json, "rebuild", names the lock folder, its netlist and every stage):
  0. every file of the tree has the sha256 MANIFEST.json gives it
  1. the locked layout's own stage: its rebuild command (traced in freeze/traces/<lock>.json) in an empty folder; its
     result must be the lock folder's die.gds.gz byte for byte (rebuild.py also checks this itself, --expect)
  2. the recorded chain (chain/replay.py, the bias layout work's record of it): every stage from the frozen two-weight
     chip to the selected mask bbf78759 but the by-product c555_intermediate, each from the stored layout of the stage
     before it, each result compared byte for byte with the GDS the record gives for that stage (and with the stored file
     where the snapshot holds it), side files where the snapshot holds them; and no stage may change a file of the tree
  3. the netlists from their generators: version 3 from the circuit that stage bbf78759 rebuilt (make_variant.py),
     version 4 from version 3 (make_variant_v4.py) when the lock uses version 4 or 5, and version 5 from version 4
     (takeover/bias/layout/rzero/make_variant_v5.py) when it uses version 5; each byte for byte equal to the snapshot's
  4. packaging: make_tt_project.py on the rebuilt layout, taking the reader texts (README.md, info.yaml, docs/info.md,
     src/project.v) from this tree's top folder (TT_PUBLIC_TEXTS_ROOT); its GDS compared with gds/ record for record (time
     stamps aside) and byte for byte, its LEF with lef/ byte for byte, and its four reader texts with the tree's byte for byte
  5. checks on the rebuilt layout, as check_all.sh runs them: Magic's full rule deck, layout against the netlist with the
     planted faults, Tiny Tapeout's precheck with its planted faults, Tiny Tapeout's three n-well rules, the pin ties, the
     rule audit's three HVI limits (0.64 um to low-voltage n-wells, 0.84 um width, no more than 197 HVI edges across poly)
     with two more of its measurements judged (capm.10 no worse than lock4_r, npc at least 0.10 um around poly contacts),
     the bias words' ground on the VGND pin's metal (scripts/ties.py section 4; the one proof of the XPROG strap, which
     the layout-against-circuit comparison cannot see), and two rules that SkyWater measures otherwise than Tiny Tapeout's
     deck, each with its planted faults: the contact bars once mask generation has grown them (scripts/licon_bars.py: end
     to end at least 0.64 um drawn) and every poly resistor body at least 0.66 um long along the current
     (scripts/res_length.py); and Tiny Tapeout's three n-well rules measured directly (scripts/well_rules.py) and the
     precision resistors' distances from NMOS held to lock4_r's (scripts/res_near_nmos.py), each with planted faults
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "source"
X_REL = "hardware/mesa/xor_sky130/"
TOP = "tt_um_mbacvanski_analog_eqprop"
LAY = SRC / "six_edge_programmable_20261117/takeover/layout"
HOME = Path.home()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def content(p: Path) -> bytes:
    data = p.read_bytes()
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def tree_hashes(man) -> dict:
    return {k: sha_bytes((ROOT / k).read_bytes()) if (ROOT / k).is_file() else None for k in man["sha256"]}


def gds_records(data: bytes):
    """GDSII records as (type, payload); BGNLIB and BGNSTR (their 24 bytes are two time stamps) are returned without payload."""
    i, out = 0, []
    while i + 4 <= len(data):
        n, rec = struct.unpack(">HB", data[i:i + 3])
        if n < 4:
            break
        payload = data[i + 4:i + n]
        out.append((rec, b"" if rec in (0x01, 0x05) else payload))
        i += n
    return out


def mapped(path: str, work: Path) -> Path:
    """A path of the recorded chain (repository-relative, or under {work}) in this tree."""
    path = path.replace("{work}", str(work))
    if path.startswith(X_REL):
        return SRC / path[len(X_REL):]
    return Path(path)


def run_logged(argv, cwd: Path, log: Path, env) -> tuple[int, float]:
    t0 = time.time()
    with log.open("wb") as f:
        f.write(("$ cd " + os.path.relpath(cwd, ROOT) + " && " + " ".join(map(str, argv)) + "\n").encode())
        f.flush()
        p = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT)
    return p.returncode, round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stages", help="only these stage ids (default: all)")
    ap.add_argument("--no-checks", action="store_true")
    a = ap.parse_args()
    man = json.loads((SRC / "MANIFEST.json").read_text())
    rb = man["rebuild"]
    PPY = os.environ.get("PY")
    if not PPY:
        sys.exit("give PY, a Python 3.11 with numpy and scipy")
    KPY = os.environ.get("KPY", str(HOME / ".local/opt/klayout-py/bin/python"))
    SYSPY = os.environ.get("SYSPY", "/usr/bin/python3")
    env = dict(os.environ, PY=PPY, KLAYOUT_PY=KPY, PYTHONDONTWRITEBYTECODE="1", TT_PUBLIC_TEXTS_ROOT=str(ROOT))
    work_root = ROOT / "rebuild"
    if work_root.exists():
        shutil.rmtree(work_root)
    (work_root / "logs").mkdir(parents=True)
    res = dict(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"), design_repository_commit=man["design_repository_commit"], freeze=man.get("freeze"),
               interpreters=dict(PY=PPY, KPY=KPY, SYSPY=SYSPY), stages=[], ok=False)
    out_json = ROOT / "from_source.json"

    def save():
        out_json.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")

    # 0. the tree as manifested (and its bytes kept, so that a stage that rewrites a file of the tree can be undone)
    before = tree_hashes(man)
    pristine = {k: (ROOT / k).read_bytes() for k in man["sha256"] if (ROOT / k).is_file()}
    bad = sorted(k for k, v in before.items() if k not in ("source/MANIFEST.json",) and v != man["sha256"][k])
    res["tree_as_manifested"] = not bad
    res["tree_differences"] = bad[:20]
    save()
    wanted = set(a.stages.split(",")) if a.stages else None
    ok_all = not bad
    # the recorded stages (chain/replay.py, imported: its STEPS are the record's commands)
    spec = importlib.util.spec_from_file_location("six_chain_replay", LAY / "chain" / "replay.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    expected = {s["id"]: s["expected_sha256"] for s in rb["recorded_stages"]}
    steps = [s for s in rp.STEPS if s["id"] in expected]
    ls = rb["lock"]
    lock_work = work_root / "lock"
    lock_step = dict(id="lock", title=f"the locked layout's own stage ({Path(ls['lock']).name})", cwd=X_REL + ls["cwd"],
                     commands=[["{PPY}", "-B", "scripts/rebuild.py", *[("{work}" if x == "EMPTY_FOLDER" else x) for x in ls["args"]]]],
                     product="{work}/" + ls["final_stem"], expected=ls["expect_sha256"], stored=X_REL + ls["lock"] + "/die.gds.gz", pairs=[],
                     env=ls.get("env", {}))
    plan = [lock_step] + steps
    ctx = dict(PPY=PPY, KPY=KPY, SYSPY=SYSPY, W=str(SRC))
    products = {}
    for st in plan:
        if wanted and st["id"] not in wanted:
            continue
        work = work_root / st["id"]
        logs = work_root / "logs" / st["id"]
        logs.mkdir(parents=True)
        cwd = mapped(st["cwd"], work)
        st_env = dict(env, **st.get("env", {}))
        t0 = time.time()
        cmds, ok = [], True
        for i, cmd in enumerate(st["commands"]):
            argv = [x.format(**ctx, work=str(work)) for x in cmd]
            code, secs = run_logged(argv, cwd, logs / f"cmd_{i:02d}.log", st_env)
            cmds.append(dict(argv=[os.path.relpath(x, ROOT) if x.startswith(str(ROOT)) else x for x in argv], exit_code=code, seconds=secs))
            print(f"[{st['id']}] {i}: exit {code} in {secs} s", flush=True)
            if code:
                ok = False
                break
        product = Path(str(mapped(st["product"], work)) + ".gds")
        got = sha_bytes(product.read_bytes()) if product.is_file() else None
        exp = st.get("expected") or expected[st["id"]]
        stored = st.get("stored") or (st.get("stored_gds") or (st["archive"] + "/die.gds.gz"))
        stored_p = mapped(stored, work)
        stored_sha = sha_bytes(content(stored_p)) if stored_p.is_file() else None
        side = []
        for new, old in st.get("pairs", []):
            key = None
            if "#" in old:
                old, key = old.split("#")
            new_p, old_p = mapped(new, work), mapped(old, work)
            if not old_p.is_file():
                side.append(dict(stored=old[len(X_REL):], compared=False, why="the stored file is not in this snapshot"))
                continue
            if not new_p.is_file():
                side.append(dict(stored=old[len(X_REL):], compared=True, same=False, why="not rebuilt"))
                continue
            same = (json.loads(new_p.read_bytes()) == json.loads(content(old_p))[key]) if key else new_p.read_bytes() == content(old_p)
            side.append(dict(stored=old[len(X_REL):] + (f" [{key}]" if key else ""), compared=True, same=same))
        after = tree_hashes(man)
        changed = sorted(k for k in after if after[k] != before[k] and k != "source/MANIFEST.json")
        for k in changed:                         # a stage that rewrote a file of the tree: recorded, and the file put back
            (ROOT / k).write_bytes(pristine[k])
        same = bool(ok and got and got == exp and (stored_sha is None or stored_sha == exp) and all(s.get("same", True) for s in side) and not changed)
        entry = dict(id=st["id"], title=st.get("title"), completed=ok, seconds=round(time.time() - t0, 1), commands=cmds,
                     product=os.path.relpath(product, ROOT), product_sha256=got, expected_sha256=exp,
                     stored=stored[len(X_REL):] if stored.startswith(X_REL) else stored,
                     stored_in_snapshot=stored_sha is not None, stored_content_sha256=stored_sha, side_files=side,
                     tree_files_changed_by_the_stage=changed, same_bytes=same)
        res["stages"].append(entry)
        products[st["id"]] = product
        ok_all &= same
        print(f"  {st['id']}: {'SAME BYTES' if same else 'DIFFERENT OR FAILED'} ({(got or '-')[:16]}; expected {exp[:16]})", flush=True)
        save()
    # 3. netlists from their generators
    circ = SRC / "six_edge_programmable_20261117/takeover/bias/circuit"
    nets = {}
    bbf = work_root / "bbf78759" / "reference.spice"
    if bbf.is_file():
        nd = work_root / "netlists"
        nd.mkdir()
        (nd / "reference.spice.gz").write_bytes(gzip.compress(bbf.read_bytes(), mtime=0))
        code, _ = run_logged([PPY, "-I", circ / "make_variant.py", nd / "reference.spice.gz", nd / "variant_reference.spice"], nd, nd / "make_variant.log", env)
        v3 = nd / "variant_reference.spice"
        nets["version 3"] = dict(exit_code=code, same_bytes=v3.is_file() and v3.read_bytes() == (circ / "variant_reference.spice").read_bytes(),
                                 sha256=sha_bytes(v3.read_bytes()) if v3.is_file() else None)
        if rb["netlist"].endswith(("_v4.spice", "_v5.spice")) and v3.is_file():
            d4 = nd / "v4"
            d4.mkdir()
            shutil.copyfile(circ / "make_variant_v4.py", d4 / "make_variant_v4.py")
            shutil.copyfile(v3, d4 / "variant_reference.spice")
            code, _ = run_logged([PPY, "-I", d4 / "make_variant_v4.py"], d4, d4 / "make_variant_v4.log", env)
            v4 = d4 / "variant_reference_v4.spice"
            nets["version 4"] = dict(exit_code=code, same_bytes=v4.is_file() and v4.read_bytes() == (circ / "variant_reference_v4.spice").read_bytes(),
                                     sha256=sha_bytes(v4.read_bytes()) if v4.is_file() else None)
            if rb["netlist"].endswith("_v5.spice") and v4.is_file():
                # make_variant_v5.py reads ../../circuit/variant_reference_v4.spice from its own folder and writes beside
                # itself: the same two folders, in miniature, with the version 4 just made
                rz = SRC / "six_edge_programmable_20261117/takeover/bias/layout/rzero"
                d5 = nd / "v5" / "bias" / "layout" / "rzero"
                d5.mkdir(parents=True)
                (nd / "v5" / "bias" / "circuit").mkdir(parents=True)
                shutil.copyfile(rz / "make_variant_v5.py", d5 / "make_variant_v5.py")
                shutil.copyfile(v4, nd / "v5" / "bias" / "circuit" / "variant_reference_v4.spice")
                code, _ = run_logged([PPY, "-I", d5 / "make_variant_v5.py"], d5, d5 / "make_variant_v5.log", env)
                v5 = d5 / "variant_reference_v5.spice"
                nets["version 5"] = dict(exit_code=code, same_bytes=v5.is_file() and v5.read_bytes() == (rz / "variant_reference_v5.spice").read_bytes(),
                                         sha256=sha_bytes(v5.read_bytes()) if v5.is_file() else None)
    else:
        nets["note"] = "stage bbf78759 was not run, so its circuit is not there to start from"
    res["netlists"] = nets
    ok_all &= bool(nets) and all(v.get("same_bytes") for k, v in nets.items() if k != "note") and "note" not in nets
    save()
    # 4. packaging, and the comparison with gds/ and lef/
    lock_gds = products.get("lock")
    if lock_gds is not None and lock_gds.is_file():
        code, secs = run_logged([PPY, "-I", LAY / "scripts/make_tt_project.py", lock_gds, "from_source"], LAY, work_root / "logs" / "make_tt_project.log", env)
        proj = LAY / "tt_project"
        new_gds, new_lef = proj / "gds" / f"{TOP}.gds", proj / "lef" / f"{TOP}.lef"
        old_gds, old_lef = ROOT / "gds" / f"{TOP}.gds", ROOT / "lef" / f"{TOP}.lef"
        g = dict(make_tt_project_exit=code, seconds=secs)
        if new_gds.is_file():
            ra, rb_ = gds_records(new_gds.read_bytes()), gds_records(old_gds.read_bytes())
            diff = [i for i, (x, y) in enumerate(zip(ra, rb_)) if x != y]
            g.update(records=[len(ra), len(rb_)], records_differing_apart_from_time_stamps=len(diff) + abs(len(ra) - len(rb_)),
                     same_records=len(ra) == len(rb_) and not diff, byte_identical=new_gds.read_bytes() == old_gds.read_bytes(),
                     sha256_rebuilt=sha_bytes(new_gds.read_bytes()), sha256_shipped=sha_bytes(old_gds.read_bytes()))
        lef = dict(byte_identical=new_lef.is_file() and new_lef.read_bytes() == old_lef.read_bytes(),
                   sha256_rebuilt=sha_bytes(new_lef.read_bytes()) if new_lef.is_file() else None, sha256_shipped=sha_bytes(old_lef.read_bytes()))
        rec = LAY / "results" / "tt_project_from_source.json"
        if rec.is_file():
            r = json.loads(rec.read_text())
            g.update(gds_same=r.get("gds_same", {}).get("verdict"), pins_match_template=r.get("pins", {}).get("lef_matches_template"),
                     precheck_all_pass=r.get("precheck_all_pass"), tt_support_tools=r.get("tools_state", {}).get("commit"))
        res["gds"], res["lef"] = g, lef
        texts = {f: (proj / f).is_file() and (proj / f).read_bytes() == (ROOT / f).read_bytes()
                 for f in ("README.md", "info.yaml", "docs/info.md", "src/project.v") + (("docs/word_conductance.csv",) if (ROOT / "docs/word_conductance.csv").is_file() else ())}
        res["project_texts_equal_the_tree"] = texts
        ok_all &= bool(g.get("same_records")) and lef["byte_identical"] and all(texts.values())
    else:
        res["gds"] = res["lef"] = dict(note="the lock stage did not give a layout")
        ok_all = False
    save()
    # 5. checks on the rebuilt layout
    if not a.no_checks and lock_gds is not None and lock_gds.is_file():
        ch = {}
        tag = "from_source"
        code, secs = run_logged([PPY, "-I", "scripts/magic_flows.py", "drc", lock_gds, f"build/{tag}"], LAY, work_root / "logs" / "drc.log", env)
        drc = LAY / "build" / tag / "drc.json"
        ch["rule_check"] = dict(exit_code=code, seconds=secs, magic_drc_errors=json.loads(drc.read_text()).get("total") if drc.is_file() else None)
        netlist = SRC / rb["netlist"]
        code, secs = run_logged([PPY, "-I", "scripts/lvs_check.py", lock_gds, netlist, "xor_chip_native_six", tag], LAY, work_root / "logs" / "lvs.log", env)
        lv = LAY / "results" / f"lvs_{tag}.json"
        if lv.is_file():
            r = json.loads(lv.read_text())
            ch["layout_against_circuit"] = dict(exit_code=code, seconds=secs, final=r["lvs"]["final"], property_errors=r["lvs"]["property_errors"],
                                                planted_faults=r.get("planted_faults"), ok=r.get("ok"))
        else:
            ch["layout_against_circuit"] = dict(exit_code=code, seconds=secs, note="no result file")
        code, secs = run_logged([PPY, "-I", "scripts/tt_precheck.py", lock_gds, tag], LAY, work_root / "logs" / "precheck.log", env)
        pr = LAY / "results" / f"precheck_{tag}.json"
        if pr.is_file():
            r = json.loads(pr.read_text())
            ch["precheck"] = dict(exit_code=code, seconds=secs, all_pass=r.get("all_pass"), checks=r.get("precheck", {}).get("checks"),
                                  planted_faults_caught=r.get("all_planted_faults_caught"), tools=r.get("tools_state"))
        else:
            ch["precheck"] = dict(exit_code=code, seconds=secs, note="no result file")
        staged = LAY / "build" / tag / "tt" / "project" / "gds" / f"{TOP}.gds"
        code, secs = run_logged(["bash", SRC / "six_edge_programmable_20261117/takeover/checks/tt_well_rules.sh", staged, TOP], LAY, work_root / "logs" / "wellrules.log", env)
        ch["well_rules"] = dict(exit_code=code, lines=[l for l in (work_root / "logs" / "wellrules.log").read_text().splitlines() if "violations" in l])
        code, secs = run_logged([KPY, SRC / "six_edge_programmable_20261117/takeover/checks/pin_ties.py", lock_gds], LAY, work_root / "logs" / "pinties.log", env)
        ch["pin_ties"] = dict(exit_code=code, result=next((l for l in (work_root / "logs" / "pinties.log").read_text().splitlines() if l.startswith("RESULT:")), None))
        staged_lef = LAY / "build" / tag / "tt" / "project" / "lef" / f"{TOP}.lef"
        code1, _ = run_logged([KPY, "-I", SRC / "six_edge_programmable_20261117/takeover/checks/rule_audit/measure.py", lock_gds, staged, staged_lef,
                               LAY / "build" / tag / "measure.json"], LAY, work_root / "logs" / "measure.log", env)
        code, _ = run_logged([PPY, "-I", "scripts/hvi_measures.py", LAY / "build" / tag / "measure.json", LAY / "results" / f"hvi_measures_{tag}.json"],
                             LAY, work_root / "logs" / "hvi.log", env)
        ch["hvi"] = dict(exit_code=code if code1 == 0 else code1,
                         lines=[l for l in (work_root / "logs" / "hvi.log").read_text().splitlines() if l.startswith(("HVI", "capm.10", "licon.15"))])
        # the bias words' ground on the VGND pin's metal: since the XPROG strap (variant D) the strap is its only ground, and
        # the comparison above cannot see it (the writers' taps join the block's ground to the substrate, which Magic extracts
        # as one node with VGND); ties.py section 4 requires its two capacitor plates, both source landings and contacts and
        # the writers' rail on VGND through local interconnect, metal and vias alone
        code, secs = run_logged([KPY, "-B", "scripts/ties.py", lock_gds, LAY / "results" / f"ties_{tag}.json"], LAY, work_root / "logs" / "ties.log", env)
        tj = LAY / "results" / f"ties_{tag}.json"
        bw = json.loads(tj.read_text()).get("bias_words_ground", {}) if tj.is_file() else {}
        ch["bias_words_ground"] = dict(exit_code=code, seconds=secs, on_VGND_by_metal=bw.get("all_on_VGND_by_metal"),
                                       parts={p["part"]: p["on"] for p in bw.get("parts", [])})
        # two rules that SkyWater measures otherwise than Tiny Tapeout's deck (24 Nov): the contact bars with the growth mask
        # generation gives them, and every poly resistor body along its current; each script plants its own faults beside
        # the layout and must find them
        # and (24 Nov) Tiny Tapeout's three n-well rules measured directly, and the precision resistors held to lock4_r's
        # distances from NMOS; each with its planted faults
        for key, script in (("contact_bars", "licon_bars.py"), ("resistor_length", "res_length.py"), ("well_rules_direct", "well_rules.py"),
                            ("resistors_near_nmos", "res_near_nmos.py")):
            out = LAY / "results" / f"{script[:-3]}_{tag}.json"
            code, secs = run_logged([KPY, "-I", f"scripts/{script}", lock_gds, out], LAY, work_root / "logs" / f"{key}.log", env)
            r = json.loads(out.read_text()) if out.is_file() else {}
            ch[key] = dict(exit_code=code, seconds=secs, ok=r.get("ok"), planted_faults_ok=r.get("planted_faults_ok"), result=r.get("result"))
        res["checks"] = ch
        res["checks_ok"] = bool(ch["rule_check"].get("magic_drc_errors") == 0 and ch["layout_against_circuit"].get("ok")
                                and ch["precheck"].get("all_pass") and ch["precheck"].get("planted_faults_caught") and ch["well_rules"]["exit_code"] == 0
                                and (ch["pin_ties"]["result"] or "").startswith("RESULT: all sixteen tied to VGND | no two other pins")
                                and ch["hvi"]["exit_code"] == 0 and ch["bias_words_ground"]["on_VGND_by_metal"] is True
                                and all(ch[k]["exit_code"] == 0 and ch[k]["ok"] is True and ch[k]["planted_faults_ok"] is True
                                        for k in ("contact_bars", "resistor_length", "well_rules_direct", "resistors_near_nmos")))
        ok_all &= res["checks_ok"]
    res["ok"] = bool(ok_all)
    res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save()
    print("FROM_SOURCE", "AGREES" if res["ok"] else "DOES NOT AGREE", "->", out_json, flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
