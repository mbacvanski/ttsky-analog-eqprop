"""Rebuild the source-adjacent filter and compare physical GDS, SPICE and every flat extraction record."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


HERE=Path(__file__).resolve().parent
LAYOUT=HERE.parent/"layout"
ARCHIVE=HERE/"evidence/layout_d6e87b40_at_driver"
sys.path.insert(0,str(LAYOUT/"hold_mode"))
from rebuild_check import compare


def rebuild(folder,kpython,at_pad=False):
    if any(folder.iterdir()):
        raise ValueError("The independent source reconstruction requires an empty scratch directory")
    raw=gzip.decompress((HERE/"evidence/filtered_complete/source.spice.gz").read_bytes())
    assert hashlib.sha256(raw).hexdigest()=="521b0f942a8a8dfc408ef1165621026c4febcbdd5e4f9f8b9aa09725a834dd91"
    schematic=folder/"reference.spice"
    schematic.write_bytes(raw)
    step=0
    def use(interpreter,script,*args):
        nonlocal step
        cmd=[str(interpreter),"-B",str(script),*[str(a) for a in args]]
        logfile=folder/f"task_{step:02d}_{Path(script).stem}.log"
        step+=1
        # Each process independently loads the register and the specified physical files.
        with logfile.open("wb") as log:
            subprocess.run(cmd,cwd=HERE,stdout=log,stderr=subprocess.STDOUT,check=True,
                env={**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1"})
    def check(stem):
        use(sys.executable,LAYOUT/"check_die.py",folder/stem,"--negative","--schematic",schematic)
    def repair(old,new):
        use(kpython,LAYOUT/"repair.py",folder/old,folder/new,"--fill","--targets",folder/"source_coupon_targets.json")
    unit=LAYOUT/"results/quiet_rc_release/mim_unit.spice"
    if at_pad:
        parent=gzip.decompress((ARCHIVE/"die.gds.gz").read_bytes())
        assert hashlib.sha256(parent).hexdigest()=="d6e87b40feaf784e2dba1889b8a49a23bdc38dd75f7d94ecab580f4ec15468b9"
        (folder/"parent.gds").write_bytes(parent)
        use(kpython,HERE/"filter_source_coupon.py",folder,"--staging-only")
        use(kpython,HERE/"filter_source_layout.py",folder,"--reroute","res_sel","--source","parent",
            "--stem","entry","--strip-only")
        use(kpython,HERE/"filter_pad_escape.py",folder/"entry_open.gds",folder/"source_coupon_targets.json",
            folder/"near_pad.gds")
        check("near_pad")
        repair("near_pad","near_pad_filled")
        check("near_pad_filled")
        use(sys.executable,LAYOUT/"extract.py",folder/"near_pad_filled","--schematic",schematic,"--unit-mim",unit)
        archive=HERE/"evidence/layout_5dd21c71_pad_escape"
        data=compare(archive,folder,"near_pad_filled")
        data["parent_full_gds"]=hashlib.sha256(parent).hexdigest()
        data["package_lead"]=json.loads((folder/"near_pad.json").read_bytes())
        (archive/"rebuild.json").write_text(json.dumps(data,indent=1)+"\n")
        print(json.dumps(data,indent=1))
        return
    use(kpython,HERE/"filter_source_coupon.py",folder,"--magic","--staging-only")
    use(kpython,HERE/"filter_source_layout.py",folder)
    check("at_source")
    repair("at_source","at_source_fill1")
    use(kpython,HERE/"filter_source_layout.py",folder,"--reroute","res_filtered","--stem","at_source_entry1",
        "--prices",0,300,20,30)
    use(kpython,HERE/"filter_source_layout.py",folder,"--reroute","weak","--source","at_source_entry1",
        "--stem","at_source_balance1","--prices",0,25,360,160)
    check("at_source_balance1")
    repair("at_source_balance1","at_source_balanced")
    check("at_source_balanced")
    use(sys.executable,LAYOUT/"extract.py",folder/"at_source_balanced","--schematic",schematic,"--unit-mim",unit)
    data=compare(ARCHIVE,folder,"at_source_balanced")
    tracks=json.loads((folder/"at_source_tracks.json").read_bytes())
    paths=[row for row in tracks["paths"] if row["net"] in ("res_sel","weak_src","weak_b_src")]
    assert len(paths)==3
    data["initial_upstream_wire_paths"]=paths
    data["upstream_path_scope"]=tracks["scope"]
    data["source_later_reroutes"]=["res_filtered","weak"]
    (ARCHIVE/"rebuild.json").write_text(json.dumps(data,indent=1)+"\n")
    print(json.dumps(data,indent=1))


if __name__=="__main__":
    opt=argparse.ArgumentParser(description=__doc__)
    opt.add_argument("--scratch",type=Path)
    opt.add_argument("--at-pad",action="store_true",help="Rebuild the separate local-interconnect entry route")
    opt.add_argument("--klayout-python",type=Path,default=Path(os.environ.get("KLAYOUT_PYTHON",Path.home()/".local/opt/klayout-py/bin/python")))
    args=opt.parse_args()
    if args.scratch:
        args.scratch.mkdir(parents=True,exist_ok=True)
        rebuild(args.scratch.resolve(),args.klayout_python,args.at_pad)
    else:
        with tempfile.TemporaryDirectory(prefix="native_source_filter_rebuild_") as temp:
            rebuild(Path(temp),args.klayout_python,args.at_pad)
