"""Read the native six-edge GDS into the same pinned layout checks as the frozen chip."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[1]
V4 = SIX.parent / "programmable_weights_v4_20261114"
ORIGINAL = SIX.parent / "feasibility_20261107/floorplan/chip2x2/scripts"
TOP = "tt_um_mbacvanski_native_edges_place"
ORIGINAL_TOP = "tt_um_mbacvanski_denseam_xor"
KPY = Path.home() / ".local/opt/klayout-py/bin/python"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def prefix(job):
    spec = importlib.util.spec_from_file_location("accepted_prefix", ORIGINAL / "prefix_gds.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.TOP, mod.PREFIX, mod.HERE = TOP, TOP + "__", job
    mod.GDS, mod.AS_BUILT = job / "project/gds" / (TOP + ".gds"), job / "build/raw.gds"
    return mod.main()


def stage(gds, lef, job, extra_pin_roles=None):
    proj = job / "project"
    for name in ("project/src", "project/gds", "project/lef", "results", "build"):
        (job / name).mkdir(parents=True, exist_ok=True)
    ref = V4 / "floorplan/tt_project_v4"
    for name in ("src/project.v", "info.yaml"):
        text = (ref / name).read_text()
        if ORIGINAL_TOP not in text:
            raise ValueError(name)
        text = text.replace(ORIGINAL_TOP, TOP)
        if name == "info.yaml":
            text = text.replace("Analog DenseAM XOR", "Six native programmable edges")
            text = re.sub(r'(?m)^(  description:\s*)"[^"]+"',r'\1"Two held analog inputs connect to two hidden neurons and one output through six native programmable resistor pairs"',text)
            pin_roles = {"ui[0]":"A or write-bank selection bit 0", "ui[1]":"B or write-bank selection bit 1",
                         "uio[0]":"EXT_BIAS1; assert with EXT_BIAS2, BIAS_PROG and WEIGHT_PROG for six-edge operation",
                         "uio[1]":"EXT_BIAS2; assert with EXT_BIAS1, BIAS_PROG and WEIGHT_PROG for six-edge operation",
                         "ua[1]":"Shared analog DAC for stored inputs and coefficient words, output bias and nudge"}
            pin_roles.update(extra_pin_roles or {})
            for pin, role in pin_roles.items():
                text, n = re.subn(r"(?m)^  "+re.escape(pin)+': .*$',f'  {pin}: "{role}"',text)
                if n != 1:
                    raise ValueError(pin)
        (proj / name).write_text(text)
    shutil.copyfile(gds, proj / "gds" / (TOP + ".gds"))
    shutil.copyfile(lef, proj / "lef" / (TOP + ".lef"))
    subprocess.run([str(KPY), "-B", str(Path(__file__).resolve()), "prefix", str(job)], check=True)
    pr = json.loads((job / "results/prefix.json").read_text())
    if not pr["same_text_labels"] or pr["layers_that_differ"]:
        raise ValueError("The cell-name prefix changed physical artwork or labels")
    return proj, pr


def checks(src, extra_pin_roles=None):
    build = HERE / "build"
    gds, lef = build / (src + ".gds"), build / (src + "_checks") / (TOP + ".lef")
    job = build / "tt" / digest(gds)[:16]
    proj, pr = stage(gds, lef, job, extra_pin_roles)
    sys.path.insert(0, str(V4 / "floorplan/scripts"))
    old = sys.argv
    sys.argv = [old[0], "r6", "precheck"]
    try:
        import chip_tt
    finally:
        sys.argv = old
    chip_tt.BUILD, chip_tt.RESULTS, chip_tt.TT, chip_tt.PRE = job/"build",job/"results",proj,job/"pinned_tools"
    rc = chip_tt.tool_copy()
    import tt_checks
    tt_checks.TOP, tt_checks.TT = TOP, proj
    rc.TT, rc.BUILD, rc.RES = proj, job/"build", job/"results"
    if not all(job in path.parents for path in (rc.TT, rc.PRE, rc.TOOLS, rc.RES, rc.BUILD)):
        raise ValueError("Check tool writes outside its private candidate build")
    outcome = rc.precheck(TOP)
    staged = proj / "gds" / (TOP + ".gds")
    if digest(staged) != digest(proj / "tt_submission" / (TOP + ".gds")):
        raise ValueError("Candidate stream changed before TT checks")
    faults = tt_checks.negative_controls()
    result = dict(as_built_gds_sha256=digest(gds), prefixed_gds_sha256=digest(staged), lef_sha256=digest(lef), source_tool_commit=rc.TT_REF,
                  prefix=pr, precheck=outcome, planted_faults=faults)
    write(build/(src+"_checks")/"tt_precheck.json", result)
    if len(outcome["checks"]) != 15 or set(outcome["checks"].values()) != {"✅"} or len(faults) != 4 or not all(f["caught"] for f in faults.values()):
        raise ValueError((outcome["checks"],faults))
    print("15 Tiny Tapeout checks, four planted faults", digest(gds), flush=True)


def antenna(src):
    sys.path.insert(0, str(SIX/"layout"))
    from baseline import MAGIC, PDK
    build = HERE / "build"
    gds = build / (src + ".gds")
    dest = build / (src + "_checks") / "antenna"
    dest.mkdir(exist_ok=True)
    tcl = dest / "antenna.tcl"
    tcl.write_text(f"gds read {{{gds}}}\nload {TOP}\nselect top cell\nexpand\nflatten native_flat\nload native_flat\nselect top cell\nextract all\nfeedback clear\nantennacheck debug\nantennacheck run -p {{{dest}}} native_flat\nputs \"ANTENNA_FEEDBACK [feedback count]\"\nquit -noprompt\n")
    with (dest / "magic.log").open("w") as log:
        subprocess.run([str(MAGIC),"-dnull","-noconsole","-rcfile",str(PDK/"libs.tech/magic/sky130A.magicrc"),str(tcl)],cwd=dest,env={**os.environ,"PDK_ROOT":str(PDK.parent)},stdout=log,stderr=subprocess.STDOUT,check=True)
    raw=(dest/"magic.log").read_text()
    if "antennacheck finished." not in raw or "Running antenna checks." not in raw:
        raise ValueError("Antenna checker did not complete")
    violations=re.findall(r"Antenna violation detected at plane (\S+)",raw)
    result=dict(gds_sha256=digest(gds),violations=len(violations),planes=violations,feedback_entries=int(re.findall(r"ANTENNA_FEEDBACK (\d+)",raw)[-1]))
    write(dest.parent/"antenna.json",result);print(result,flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("prefix","tt","antenna"));parser.add_argument("source")
    args=parser.parse_args()
    if args.command=="prefix":
        raise SystemExit(prefix(Path(args.source).resolve()))
    (checks if args.command=="tt" else antenna)(args.source)
