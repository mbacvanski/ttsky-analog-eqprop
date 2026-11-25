# The design files of the chip

Everything in this repository is licensed under Apache-2.0, see LICENSE; the SKY130 cells inside the layouts and the
Tiny Tapeout template files are Apache-2.0 from their sources.

This folder holds what is needed to do three things:
- build the chip's layout again from its design files;
- package the layout as `../gds/` and `../lef/`;
- run the layout checks again.

Each file sits at its path under the design repository's folder `hardware/mesa/xor_sky130/`, so the scripts find each
other as they do there. `MANIFEST.json` lists every file of the repository with its SHA-256 and why it is here.

| Folder | What it holds |
| --- | --- |
| `six_edge_programmable_20261117/` | This chip, listed below. |
| `programmable_weights_v4_20261114/` | Cell generators, the circuit library and floorplan scripts that the build stages read: the stored-word resistor cells, decoders and neuron cells. Also one stored layout, and the Tiny Tapeout project template that packaging copies. |
| `feasibility_20261107/` | The base analog cells: amplifiers, neurons, resistor banks, read-out buffers and pin resistors, with their reference netlists and layout scripts. Also Tiny Tapeout's 2x2 analog tile definition, with its licence (`floorplan/template/TT_SUPPORT_TOOLS_LICENSE`) beside it. |

`six_edge_programmable_20261117/` holds:
- the circuit netlists;
- the submitted layout;
- the layout generators and the build stages, with the inputs they read;
- the stored routing shapes and the intermediate layouts of the recorded stages;
- the check scripts;
- the rebuild driver, with the traces of what each stage and each check reads.

## The files to start from

| File (under `six_edge_programmable_20261117/`) | What it is |
| --- | --- |
| `takeover/bias/layout/rzero/variant_reference_v5.spice` | The chip's circuit, the netlist the layout is checked against. In the same folder, `make_variant_v5.py` generates it from `takeover/bias/circuit/variant_reference_v4.spice`. The file `variant_v5_manifest.json` records the changed line and the SHA-256 of both netlists. |
| `takeover/bias/layout/lock5_r/die.gds.gz` | The submitted layout (GDS SHA-256 `a824cbba9893dea3b56fac57a8f40094b938535fb2297f5cce189347a2ad665d`). The rebuilt layout is compared with it. |
| `takeover/layout/freeze/from_source.py` | The rebuild: it runs the recorded build stages, makes the netlists from their generators, packages the layout, compares it with `../gds/` and `../lef/`, and runs the checks |
| `takeover/layout/freeze/traces/` | What the last build stage and the checks read, recorded file by file |
| `takeover/layout/scripts/check_all.sh` | The layout checks, as one command: rule deck, antenna (on the finished layout and at each etch stage), layout against circuit with planted faults, ties, Tiny Tapeout's precheck and n-well rules, pin ties, thick-oxide geometry and the count of gate ends crossing its edge over field oxide, resistor contact-bar spacing and body length, direct n-well measurements, MIM capacitors over lower-layer edges, nitride poly cut around contacts and resistor spacing from NMOS transistors |
| `takeover/bias/layout/scripts/rebuild.py` | The last build stage. It adds the two offset words with their transistors and write logic, H1's offset network, the supply strips, the stored-word cells, the n-well rectangles and the offset words' ground strap to the stored layout of the stage before, draws the reference buffer's zero resistor, and carries four metal 2 runs over short metal 3 bridges so that no gate is exposed while metal 2 is etched. |
| `takeover/bias/layout/inputs/` | What that stage reads: the supply strips, the n-well rectangles, the ground strap, the placement targets, the reference buffer's resistor cell (`ar4_rzero_l070.gds`) and the metal 3 bridges (`antenna_patch.json`) |
| `drawn/ports.py` | The pin map: which pad carries which signal |

The datasheet (`../docs/info.md`) describes the chip from the outside: pins, modes, write and read sequences,
calibration and limits.

The two sections below are written when the repository is assembled. "Rebuilding from this folder alone" gives the
command, the settings it reads, and the result of the rebuild made on this very tree. "What is not here" lists what
the repository leaves out.

## Rebuilding from this folder alone

    PY=<Python 3.11 with numpy and scipy> KPY=<Python with the klayout module> python3 source/six_edge_programmable_20261117/takeover/layout/freeze/from_source.py

run from the repository's top folder, with Magic 8.3.685, netgen 1.5.325, KLayout, g++ and the SKY130A PDK
(`PDK_ROOT`, default `~/.ciel`) and Tiny Tapeout's tools (`TT_PRECHECK_DIR`). It runs every stage, compares each result
with the stored layout byte for byte, packages the last one, compares the GDS with `gds/` record for record and the LEF
with `lef/` byte for byte, and runs the rule check, the layout-against-circuit comparison with its planted faults, Tiny
Tapeout's precheck with its planted faults and their three n-well rules, the pin ties, the three thick-oxide (HVI)
limits, the metal check of the bias block's ground (the one proof of its strap, which the comparison cannot see), and two
rules that SkyWater measures otherwise than Tiny Tapeout's deck, each with planted faults: the contact bars of the poly
resistors as mask generation grows them (at least 0.64 um apart end to end as drawn) and every poly resistor body at least
0.66 um long along its current; and, each with planted faults too, Tiny Tapeout's three n-well rules measured directly
(no lvtn across a well's edge, hvtp outside the wells only as the standard cells' own strips, no urpm over a well) and
the precision resistors' distances from NMOS transistors held to this layout's. Result: `from_source.json` in the top folder.

Last rebuild from this snapshot: 2026-11-24T18:47-05:00: the rebuild agrees (see MANIFEST.json, rebuild_from_this_snapshot).

## What is not here

The PDK and the tools; the design repository's reports, working notes and simulation results; extracted circuit models
and run folders.
