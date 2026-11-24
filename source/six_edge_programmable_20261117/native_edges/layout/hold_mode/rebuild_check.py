"""Compare an independently rebuilt mask, extraction and board with the immutable physical archive."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re


def normalized_ext(text):
    records=Counter()
    couplings=0
    for line in text.splitlines():
        if line.startswith("cap "):
            match=re.fullmatch(r'cap "([^"]+)" "([^"]+)" (\S+)',line)
            if not match:raise ValueError(line)
            a,b,value=match.groups()
            record=("cap",*sorted((a,b)),value)
            couplings+=1
        else:
            record=("other",line)
        records[record]+=1
    return records,couplings


def compare(archive,build,stem):
    stored=json.loads((archive/"manifest.json").read_bytes())
    fresh=json.loads((build/(stem+"_pex")/"manifest.json").read_bytes())
    expected={
        "gds_sha256":build/(stem+".gds"),
        "whole_flat_sha256":build/(stem+"_pex")/"flat_parasitics.spice",
        "board_spice_sha256":build/(stem+"_pex")/"native_six_pex.spice",
    }
    for name,path in expected.items():
        if fresh[name]!=stored[name] or hashlib.sha256(path.read_bytes()).hexdigest()!=stored[name]:
            raise ValueError(("Rebuilt physical output differs",name))
    if fresh["source_circuit_sha256"]!=stored["source_circuit_sha256"] or fresh["LVS"]!=stored["LVS"]:
        raise ValueError("Different source circuit or transistor LVS result")
    raw=gzip.decompress((archive/"native_flat.ext.gz").read_bytes())
    new=(build/(stem+"_pex")/"native_flat.ext").read_bytes()
    if hashlib.sha256(raw).hexdigest()!=stored["ext_sha256"] or hashlib.sha256(new).hexdigest()!=fresh["ext_sha256"]:
        raise ValueError("Incorrect raw extraction")
    old_records,old_caps=normalized_ext(raw.decode())
    new_records,new_caps=normalized_ext(new.decode())
    if old_records!=new_records:
        raise ValueError(("Electrical extraction record differs",old_records-new_records,new_records-old_records))
    return dict(source_circuit_sha256=fresh["source_circuit_sha256"],
                byte_identical_outputs={name:fresh[name] for name in expected},
                all_ext_record_count=sum(old_records.values()),ext_coupling_record_count=old_caps,
                ordered_raw_ext_digest_equal=raw==new,flat_LVS_identical=True,
                electrical_comparison="Every Magic .ext record agrees after permitting order of records and order of the two electrodes of a coupling capacitor.")


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("build",type=Path)
    cli.add_argument("--stem",default="res_hold_heal")
    cli.add_argument("--output",type=Path)
    args=cli.parse_args()
    records=Path(__file__).resolve().parents[1]/"results/res_hold_provisional"
    data=compare(records,args.build,args.stem)
    report=json.dumps(data,indent=2)+"\n"
    if args.output:args.output.write_text(report)
    print(report,end="")
