"""Check the flat Magic RC records and remove MIM overlap already modelled by the PDK."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil

from extract import MAGIC, MAGICRC, SIX, tool
from reduce_capacitance import fraction_ff


PLATE=Path(__file__).resolve().parent/"model_inputs/mim_plate.json"
MIM="sky130_fd_pr__cap_mim_m3_1"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def parse_spice(path):
    ports=[];devices=Counter();caps=defaultdict(float)
    for line in re.sub(r"\n\+\s*"," ",path.read_text()).splitlines():
        f=line.partition(";")[0].split()
        if not f or f[0].startswith("*"):continue
        if f[0]==".subckt":
            assert not ports
            ports=f[2:]
        elif f[0].startswith("X"):
            i=next(i for i,w in enumerate(f) if w.startswith("sky130_fd_pr__"))
            devices[(tuple(f[1:i]),f[i],tuple(sorted(f[i+1:])))]+=1
        elif f[0].startswith("C"):
            assert len(f)==4
            caps[tuple(sorted(f[1:3]))]+=fraction_ff(f[3])
        elif f[0]!=".ends":
            raise ValueError(f"Unrecognised flat element {line}")
    assert len(ports)==len(set(ports))==37
    return ports,devices,caps


def ext_caps(ext):
    text=ext.read_text()
    assert re.search(r"(?m)^scale \S+ 1 \S+$",text)
    names={b:a for a,b in re.findall(r'^equiv "([^"]+)" "([^"]+)"$',text,re.M)}
    ground=re.findall(r'^substrate "([^"]+)"',text,re.M)
    assert len(ground)==1 and names.get("VGND","VGND")==ground[0]
    ref=ground[0]
    values=defaultdict(float)
    for n,c in re.findall(r'^node "([^"]+)" \S+ (\S+)',text,re.M):
        n=names.get(n,n)
        if n!=ref:values[tuple(sorted((n,ref)))]+=float(c)/1000
    for a,b,c in re.findall(r'^cap "([^"]+)" "([^"]+)" (\S+)',text,re.M):
        a,b=names.get(a,a),names.get(b,b)
        if a!=b:values[tuple(sorted((a,b)))]+=float(c)/1000
    return values,names,ref


def check_extraction(expected,aliases,caps):
    observed=defaultdict(float)
    for (a,b),v in caps.items():
        a,b=aliases.get(a,a),aliases.get(b,b)
        if a!=b:observed[tuple(sorted((a,b)))]+=v
    diffs={e:observed[e]-expected.get(e,0.) for e in set(expected)|set(observed)}
    # The flat ngspice export rounds large values to 0.01 fF.
    failing=[e for e,x in diffs.items() if abs(x)>.012]
    return dict(checked_pairs=len(diffs),maximum_absolute_error_fF=max(abs(v) for v in diffs.values()),
                pairs_over_0p012fF=len(failing),
                largest_discrepancies_fF=[dict(nodes=list(k),error_fF=diffs[k]) for k in sorted(diffs,key=lambda x:abs(diffs[x]),reverse=True)[:6]])


def apply_plate(data,devices,caps):
    amount=defaultdict(float);counts=Counter()
    for (terminals,model,params),count in devices.items():
        if model!=MIM:continue
        parameters=dict(s.split("=") for s in params)
        assert set(parameters)=={"w","l"} and len(terminals)==2
        size=tuple(sorted((float(parameters["w"]),float(parameters["l"]))))
        unit=data[str(size[0])]
        assert tuple(sorted((unit["w"],unit["l"])))==size
        counts[str(size)]+=count
        amount[tuple(sorted(terminals))]+=unit["plate_fF"]*count
    out=dict(caps)
    records=[]
    for edge,wanted in sorted(amount.items()):
        present=caps.get(edge,0.)
        removed=min(wanted,present)
        out[edge]=present-removed
        records.append(dict(nodes=list(edge),before_fF=present,unit_plate_fF=wanted,
                            removed_fF=removed,remaining_fF=out[edge],available_below_unit=present<.999*wanted))
    assert min(out.values())>=0.
    return out,dict(instances=sum(counts.values()),sizes=counts,removed_fF=sum(r["removed_fF"] for r in records),
        units_fF=sum(amount.values()),pairs=records,short_pairs=[r for r in records if r["available_below_unit"]])


def export(src):
    meta=json.loads((src/"manifest.json").read_text())
    assert sha((src/"flat_parasitics.spice").read_bytes())==meta["simulation_netlist_sha256"]
    assert sha(PLATE.read_bytes())=="44a4396119c04befc88755c3aa7f89a847c3d5f0ca3963380bc78dc0f4d24c98"
    out=src/"full_flat";out.mkdir(exist_ok=True)
    shutil.copyfile(src/"six_flat.ext",out/"six_flat.ext")
    script=out/"export.tcl"
    script.write_text("ext2spice lvs\next2spice hierarchy off\next2spice subcircuit top on\next2spice cthresh 0\next2spice -o raw_cap.spice six_flat\nquit -noprompt\n")
    tool([MAGIC,"-dnull","-noconsole","-rcfile",str(MAGICRC),str(script.resolve())],out.resolve(),"magic.log")
    ports,devices,measured=parse_spice(out/"raw_cap.spice")
    oldports,olddevices,oldcaps=parse_spice(src/"raw_cap.spice")
    assert devices==olddevices and ports==oldports==meta["extracted_ports"]
    expected,aliases,ground=ext_caps(out/"six_flat.ext")
    old=check_extraction(expected,aliases,oldcaps)
    new=check_extraction(expected,aliases,measured)
    assert old["pairs_over_0p012fF"]>0 and not new["pairs_over_0p012fF"], (old,new)
    final,plate=apply_plate(json.loads(PLATE.read_text()),devices,measured)
    translate=json.loads(gzip.decompress((src/"nodes.json.gz").read_bytes()))
    next_id=1+max(int(v.split("_")[1]) for v in translate.values() if v.startswith("n_"))
    def node(n):
        nonlocal next_id
        if n not in translate:
            translate[n]=f"n_{next_id}"
            next_id+=1
        return translate[n]
    # Preserve the silicon device cards and order byte-for-byte. Only capacitance changes.
    original=(src/"flat_parasitics.spice").read_text().splitlines()
    front=[line for line in original if not line.startswith(("C",".ends"))]
    assert sum(s.startswith("X") for s in front)==sum(devices.values())
    cards=[f"Cpar{i} {node(a)} {node(b)} {v:.15g}f" for i,((a,b),v) in enumerate(sorted(final.items())) if v>0]
    flat=("\n".join(front+cards+[".ends sx_drawn"])+"\n").encode()
    (out/"flat_parasitics.spice").write_bytes(flat)
    (out/"nodes.json.gz").write_bytes(gzip.compress(json.dumps(translate,sort_keys=True).encode(),mtime=0))
    ref_net=aliases.get("BUF_REF.out","BUF_REF.out")
    check=dict(gds_sha256=meta["gds_sha256"],raw_previous_sha256=meta["simulation_netlist_sha256"],
       ext_sha256=sha((out/"six_flat.ext").read_bytes()),unadjusted_flat_spice_sha256=sha((out/"raw_cap.spice").read_bytes()),
       device_card_multiset_identical=True,device_count=sum(devices.values()),physical_terminals=ports,
       original_export=old,flat_export=new,ext_ground_name=ground,ext_reference_name=ref_net,
       reference_substrate_fF=expected[tuple(sorted((ground,ref_net)))],
       isolated_unit_table_sha256=sha(PLATE.read_bytes()),mim_accounting=plate,final_sha256=sha(flat))
    (out/"accounting.json").write_text(json.dumps(check,indent=2,allow_nan=False)+"\n")
    counts=dict(meta["element_counts"],coupling_or_substrate_capacitors=len(cards))
    newmeta=dict(meta,simulation_netlist_sha256=sha(flat),magic_flat_cap_sha256=check["unadjusted_flat_spice_sha256"],
                 element_counts=counts,parasitics="Flat Magic substrate and coupling capacitances checked against the .ext records, frozen signoff MIM overlap removed; interconnect resistance excluded.",
                 accounting_sha256=sha((out/"accounting.json").read_bytes()))
    (out/"manifest.json").write_text(json.dumps(newmeta,indent=2)+"\n")
    return out,check


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument("extractions",type=Path,nargs="+")
    for path in cli.parse_args().extractions:
        out,c=export(path)
        print(out,c["final_sha256"],c["flat_export"]["maximum_absolute_error_fF"],c["mim_accounting"]["removed_fF"])
