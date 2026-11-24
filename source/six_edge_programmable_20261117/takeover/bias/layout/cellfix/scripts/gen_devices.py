"""Generate devices.py's devices with the PDK's Magic generators; record geometry (build/device_ports.json) and sizes
(results/device_sizes.json).   python gen_devices.py [name ...]"""
from __future__ import annotations

import json
import sys

from magic_util import BUILD, LAYOUT, RESULTS, extent, parse_mag, run_magic
from devices import DEVICES


def tcl_generate(names) -> str:
    lines = ["random seed 20261115", "load gen_scratch -force", "snap internal"]
    y = 0.0
    for name in names:
        gen, params = DEVICES[name]
        args = " ".join(f"{k} {v}" for k, v in params.items())
        lines += [f"box 0um {y:.3f}um 0um {y:.3f}um", f"magic::gencell sky130::{gen} I_{name} {args}", f"select cell I_{name}",
                  "set cn [instance list celldef]", f"cellname rename $cn {name}", f'puts "GEN {name} [box values]"']
        y += 200.0
    lines += ["writeall force", "quit -noprompt"]
    return "\n".join(lines) + "\n"


def main(names=None):
    names = names or list(DEVICES)
    for n in names:
        (LAYOUT / f"{n}.mag").unlink(missing_ok=True)
    run_magic(tcl_generate(names), "gen_devices")
    path = BUILD / "device_ports.json"
    ports = json.loads(path.read_text()) if path.exists() else {}
    sizes_path = RESULTS / "device_sizes.json"
    sizes = json.loads(sizes_path.read_text()) if sizes_path.exists() else {}
    for name in names:
        mag = parse_mag(LAYOUT / f"{name}.mag")
        ports[name] = dict(fixed_bbox=mag["fixed_bbox"], labels=mag["labels"], rects=mag["rects"])
        b = extent(mag)
        sizes[name] = dict(generator=DEVICES[name][0], parameters=DEVICES[name][1], paint_bbox_um=b,
                           size_um=[round(b[2] - b[0], 3), round(b[3] - b[1], 3)], layers=sorted(mag["rects"]))
        print(f"{name:9s} {b[2] - b[0]:7.3f} x {b[3] - b[1]:7.3f}  bbox {b}  layers {sorted(mag['rects'])}  labels {[l['text'] for l in mag['labels']]}")
    path.write_text(json.dumps(ports, indent=1))
    RESULTS.mkdir(exist_ok=True)
    sizes_path.write_text(json.dumps(sizes, indent=1) + "\n")
    (LAYOUT / "gen_scratch.mag").unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1:])
