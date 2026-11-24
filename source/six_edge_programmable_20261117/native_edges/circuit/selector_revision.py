"""Assemble the two-switch correction against the archived, LVS-matched resistor circuit."""
from pathlib import Path
import gzip
import hashlib
import json
import re

HERE=Path(__file__).resolve().parent
CONTROL="c5554a58fa7d128c18185dd1f5825c9cba79dd4629cd8095ec77fa5924a65075"


def build(fingers=3):
    if fingers not in (3,8):
        raise ValueError("Only the metrologically checked three- and eight-finger selectors are supported")
    source=gzip.decompress((HERE.parent/"verification/evidence/threshold/source_c555.spice.gz").read_bytes())
    if hashlib.sha256(source).hexdigest()!=CONTROL:
        raise ValueError("Wrong fixed-offset parent")
    net=source.decode()
    old_return="XRETURN end1 end2 vss vss six vss pw4_mid"
    old_path=("XH1BIAS bias1 fixed1 six h1bias vdd vss ext_bias_switch\n"
              "XH2BIAS bias2 fixed2 six h2bias vdd vss ext_bias_switch\n")
    if net.count(old_return)!=1 or net.count(old_path)!=1:
        raise ValueError("Unrecognized selector or ground return")
    mid=re.search(r"(?ims)^\.subckt pw4_mid .*?^\.ends[^\n]*\n",net)[0]
    stock_device="sky130_fd_pr__nfet_03v3_nvt"
    if mid.count(stock_device)!=2:
        raise ValueError("Invalid reference dual switch")
    grounding=mid.replace(".subckt pw4_mid ", ".subckt native_ground_return ").replace(stock_device,"sky130_fd_pr__nfet_01v8")
    grounding="\n".join(line for line in grounding.splitlines() if not line.startswith("*"))+"\n"
    count = "three" if fingers == 3 else "eight"
    selects=[f"* Two sets of {count} native switches select the fixed or legacy H bias branches."]
    for i in range(1,fingers+1):
        selects.append(f"XSEL_RAW{i} bias1 bias2 h1bias h2bias park vss pw4_mid")
        selects.append(f"XSEL_FIXED{i} fixed1 fixed2 h1bias h2bias six vss pw4_mid")
    net=net.replace(old_path,"\n".join(selects)+"\n").replace(old_return,old_return.replace("pw4_mid","native_ground_return"))
    result=net+"\n"+grounding
    return result,dict(assembled_sha256=hashlib.sha256(result.encode()).hexdigest(),parent_schematic_sha256=CONTROL,selector_fingers=fingers,
                       scope="Integrated switch-repair schematic under test. Six weight circuits, holding capacitors and buffered input paths are inherited.")


if __name__=="__main__":
    import argparse
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("path",type=Path)
    cli.add_argument("--fingers",type=int,choices=(3,8),default=3)
    args=cli.parse_args()
    out=args.path
    text,register=build(args.fingers)
    out.write_text(text)
    out.with_suffix(".json").write_text(json.dumps(register,indent=2)+"\n")
