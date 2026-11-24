"""Draw the exact folded high-R strips and feedback helpers, and count their extracted devices."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import shutil
import sys

HERE = Path(__file__).resolve().parent
SIX = HERE.parents[1]
V4 = SIX.parent / "programmable_weights_v4_20261114"
WORK = HERE / "build/resistor_cells"
sys.path.insert(0, str(V4 / "floorplan/cellwork/scripts"))
import magic_util
from lib import Cell, GAP_R, PITCH, RW, Strips
from geom import snap

MATERIAL = "sky130_fd_pr__res_xhigh_po_0p35"
# Number of active strips and equivalent resistance per original two-strip unit.
DESIGNS = {
    "ne_help": (8, 133333., ("sw4", "p", "sw7", "ref")),
    "ne_r1": (2, 18181.81818, ("ref", "fixed1")),
    "ne_r2": (2, 48275.86207, ("ref", "fixed2")),
    "ne_g1": (16, 300000., ("p1", "end1")),
    "ne_g2": (8, 257142.85714, ("p2", "end2")),
}


def leg(value):
    return .01 * math.floor(((value / 2 - 587.80457142857) * .35 / 2000) / .01 + .5)


def normalize_stream(path):
    data=bytearray(path.read_bytes())
    i=0
    while i<len(data):
        size,record=struct.unpack_from(">HH",data,i)
        if record in (0x0102,0x0502):
            assert size==28
            data[i+4:i+28]=struct.pack(">12h",*([2000,1,1,0,0,0]*2))
        i+=size
    if i!=len(data):raise ValueError("Truncated GDS")
    path.write_bytes(data)


def check_graph(physical, name, device, rows, ports, useful):
    expanded=re.sub(r"\n\+\s*"," ",physical)
    formal=re.search(r"(?m)^\.subckt "+device+r" (.*)$",expanded)[1].split()
    actual=re.search(r"(?m)^XXRARRAY (.*) "+device+"$",expanded)[1].split()
    if len(formal)!=len(actual):raise ValueError("Incorrect port count on the drawn resistor geometry")
    bind=dict(zip(formal,actual)); adj=defaultdict(list); dummies=0
    for _,one,two,bulk,_ in rows:
        a,b=bind[one],bind[two]
        if bind[bulk]!="vss":raise ValueError("Ungrounded resistor substrate")
        if a==b=="vss":dummies+=1
        else:adj[a].append(b);adj[b].append(a)
    if dummies!=2 or "vss" in adj:raise ValueError("Unexpected dummy or resistor ground connection")
    paths=[]
    for a in ports:
        for n in adj[a]:
            if n in ports: paths.append((a,n,1)); continue
            prev,cur,steps=a,n,1
            while cur not in ports:
                if len(adj[cur])!=2 or steps>useful:raise ValueError("An internal node branches or floats")
                x,y=adj[cur];prev,cur=cur,(x if y==prev else y);steps+=1
            if a<cur:paths.append((a,cur,steps))
    if name=="ne_help":
        expected=sorted([("p","sw4",2)]*2+[("ref","sw7",2)]*2)
    else:expected=[(*sorted(ports),useful)]
    if sorted(paths)!=expected:raise ValueError((paths,expected))
    return {"verified_endpoint_paths":paths,"grounded_edge_dummies":dummies}


def draw(name, useful, value, ports):
    length = leg(value)
    count = useful + 2
    device = f"{name}_xpoly"
    cell = Cell(name)
    half = (length - .16) / 2 + 2.16
    # Extra space on the left accommodates the independent feedback pair connections.
    left = 2.4 + RW
    bottom = .45 + RW
    cx = snap(left + GAP_R + half)
    cy = snap(bottom + GAP_R + Strips.height(count) / 2)
    right = snap(cx + half + GAP_R)
    top = snap(cy + Strips.height(count) / 2 + GAP_R)
    outer = cell.ring(left, bottom, right, top)
    strips = Strips(cell, device, "XRARRAY", cx, cy, count, length)
    for i in (0, count - 1):
        strips.to_ring(i, "L", left - RW / 2)
        strips.to_ring(i, "R", right + RW / 2)
    for i in range(1, count - 2, 2):
        strips.link(i, i + 1, "R")
    if name == "ne_help":
        # Two pairs of native 133.333k units in parallel, separate R4 and R7.
        # The alternating left ends cannot be joined on one metal stripe.
        for pin, ends, column in zip(ports, ((1, 3), (2, 4), (5, 7), (6, 8)), (.6, 1.55, .6, 1.55)):
            ys = []
            for index in ends:
                p = strips.pad(index, "L")
                y = strips.y(index)
                ys.append(y)
                cell.rect("metal1", column - .17, p[1], p[0] + .12, p[3])
                cell.via("via1", column, y)
            cell.v("metal2", column, min(ys), max(ys), .30)
            cell.port(pin, "metal2", column - .15, min(ys) - .19, column + .15, min(ys) + .19)
    else:
        for i in range(2, count - 2, 2):
            strips.link(i, i + 1, "L")
        for index, pin in zip((1, count - 2), ports):
            p = strips.pad(index, "L")
            x = 1.1
            y = strips.y(index)
            cell.rect("metal1", x - .17, p[1], p[0] + .12, p[3])
            cell.via("via1", x, y)
            cell.port(pin, "metal2", x - .15, y - .19, x + .15, y + .19)
    yg = strips.y(1) - .40
    xg = right + RW / 2
    cell.via("mcon", xg, yg)
    cell.port("vss", "metal1", xg-.15, yg-.18, xg+.15, yg+.18, use="ground")
    cell.outline(0, 0, outer[2]+.30, outer[3]+.30)
    # Keep the PDK array's as-drawn end contacts and the exact target model length.
    header = f"""snap internal
load scratch_{name} -force
random seed 20261118
box 0um 0um 0um 0um
magic::gencell sky130::{MATERIAL} XARRAY w 0.35 l {length:.2f} nx {count} guard 0
select cell XARRAY
set pdkcell [instance list celldef]
cellname rename $pdkcell {device}
"""
    script = header + cell.t.text() + f"""
save {name}
drc euclidean on
drc style drc(full)
drc check
drc catchup
set total 0
foreach {{why boxes}} [drc listall why] {{incr total [llength $boxes]; puts "RULE [llength $boxes] $why $boxes"}}
puts "DRCTOTAL $total"
extract do local
extract all
ext2spice lvs
ext2spice subcircuit on
ext2spice -o {name}.spice
load {name}
gds write {name}.gds
quit -noprompt
"""
    folder = WORK / name
    folder.mkdir(parents=True, exist_ok=True)
    destination=folder
    scratch=tempfile.TemporaryDirectory(dir=folder)
    folder=Path(scratch.name)
    (folder / "draw.tcl").write_text(script)
    env = dict(__import__("os").environ, PDK_ROOT=str(magic_util.PDK_ROOT))
    run = subprocess.run([magic_util.MAGIC, "-dnull", "-noconsole", "-rcfile", str(magic_util.MAGICRC), "draw.tcl"],
                         cwd=folder, capture_output=True, text=True, check=True, env=env)
    log = run.stdout + run.stderr
    (folder / "magic.log").write_text(log)
    physical = (folder / (name + ".spice")).read_text()
    rows = re.findall(r"(?mi)^X(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+" + MATERIAL + r"\s+(.+)$", physical)
    normalize_stream(folder/(name+".gds"))
    for f in folder.iterdir():
        if f.is_file(): shutil.copyfile(f, destination/f.name)
    if len(rows) != count or len(re.findall(r"(?mi)^\.subckt ne_\w+_xpoly ", physical)) != 1:
        raise ValueError(f"{name} physical PDK resistor array has {len(rows)} strip records instead of {count}")
    if any(abs(float(re.search(r"(?i)\bL=([\d.]+)", row[4])[1]) - length) > .001 for row in rows):
        raise ValueError(f"{name}: wrong drawn PDK strip length")
    result = {"name": name, "gds": hashlib.sha256((folder / (name+".gds")).read_bytes()).hexdigest(),
              "active_strips":useful, "dummy_strips":2, "strip_length_um":round(length,2),
              "target_unit_ohm":value, "actual_cell_size_um":cell.info["size_um"],
              "pins":cell.info["pins"], "drc_errors":int(re.search(r"DRCTOTAL (\d+)",log)[1])}
    result.update(check_graph(physical,name,device,rows,ports,useful))
    return result


if __name__ == "__main__":
    result = [draw(name, *spec) for name, spec in DESIGNS.items()]
    print(json.dumps(result, indent=2))
    (HERE / "results/poly_cells.json").write_text(json.dumps(result,indent=2)+"\n")
    if any(x["drc_errors"] for x in result):
        raise SystemExit("A physical rule is violated; inspect each Magic receipt")
