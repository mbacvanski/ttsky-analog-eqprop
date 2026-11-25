![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg)

# Analog equilibrium propagation: three neurons, six learnable weights (Tiny Tapeout SKY130, 2x2 analog tile)

Everything in this repository is licensed under Apache-2.0, see LICENSE; the SKY130 cells inside the layouts and the
Tiny Tapeout template files are Apache-2.0 from their sources.

- [Read the datasheet](docs/info.md)

Three analog neurons, two hidden ones (H1, H2) and an output (Z), form a small symmetric analog network: every
connection is a resistor, so every weight acts the same way in both directions, and the network relaxes in continuous
time to a stable state.

- **Fixed mode.** With the programming pins low, the chip computes A XOR B of two input bits with fixed resistors.
- **Six-weight mode.** An external controller writes into on-chip capacitor stores, through the analog pin `ua[1]`:
  - six weights, each between 0.25 and 0.75;
  - two hidden offsets, each between 0 and −1.75 units;
  - the two analog inputs.
- **Learning.** The output's bias is the voltage on `ua[1]`. Stepping that voltage nudges the output toward a wanted
  answer, so the chip can be trained by equilibrium propagation with the controller in the loop. The datasheet gives
  what has been simulated of this.

The two outputs are on `ua[0]` and `ua[2]`. All performance figures are from simulation; nothing has been measured on
silicon. The datasheet says what was simulated, on which model, and what a board must calibrate on each chip.

The layout is a custom analog layout of a 2x2 tile with three analog pins. It started from Tiny Tapeout's analog
template, [TinyTapeout/ttsky-analog-template](https://github.com/TinyTapeout/ttsky-analog-template).

## What is in this repository

| Path | Content |
| --- | --- |
| `info.yaml` | Project description for Tiny Tapeout: 2x2 tiles, three analog pins, the pinout |
| `docs/info.md` | The datasheet: how the chip works, the pins in each mode, the write and read sequences, calibration, limits, the fixed-mode fallback |
| `src/project.v` | Blackbox stub with the ports only, as Tiny Tapeout requires for an analog project |
| `gds/`, `lef/` | The layout under the project's name, `tt_um_mbacvanski_analog_eqprop`, and its abstract (LEF) |
| `.github/workflows/` | Tiny Tapeout's GDS and docs actions |
| `test/requirements.txt` | From the template |
| `source/` | The design files: circuit netlists, cell layouts and generators, the stored routing shapes, the build stages and the check scripts. With them `gds/` and `lef/` can be built again and the layout checks run again. Start at [`source/README.md`](source/README.md). |
| `source/MANIFEST.json` | The SHA-256 of every file in the repository, and why each one is here |
| `LICENSE` | Apache-2.0 |

Supply pins: the layout has seven metal 4 supply stripes, three VDPWR and four VGND. Tiny Tapeout's analog
specification allows several stripes per supply, and Tiny Tapeout's power grid must connect all of them.

## Building the layout again from `source/`

The rebuild runs on open tools and the open SKY130 PDK and needs no network (Tiny Tapeout's precheck runs with
`TT_PRECHECK_OFFLINE=1`). It needs:
- Magic 8.3.685;
- netgen 1.5.325;
- KLayout's Python module 0.30.8, and KLayout 0.30.0 for Tiny Tapeout's precheck;
- the SKY130A PDK from open_pdks, installed with ciel at version 792ef670;
- Python 3.11 with numpy and scipy, and a system Python 3;
- g++, because the routers are compiled during the run;
- Tiny Tapeout's tt-support-tools at commit 7d2d2ef with its virtual environment.

For the rebuild command, its settings and the rebuild record, see "Rebuilding from this folder alone" in
`source/README.md`. The rebuild writes `from_source.json` in the top folder and exits with status 0 only if everything
agrees.

**What a successful rebuild proves.** The rebuild starts from what is in `source/`: the base cells and their layouts,
a stored layout of the base design, the stored routing shapes and the scripts. It runs again every stage of the
recorded build chain that the layout needs, each from the stored layout of the stage before it.
- Each stage gives, byte for byte, the layout recorded for it (the SHA-256 of every stage's GDS). The last stage gives
  the submitted layout byte for byte (GDS SHA-256 `a824cbba9893dea3b56fac57a8f40094b938535fb2297f5cce189347a2ad665d`).
- The circuit netlists come out of their generators byte for byte.
- Packaging the rebuilt layout under the project's name gives this repository's `gds/` record for record (the GDSII
  records apart from their two time stamps; here the bytes are identical too) and its `lef/` byte for byte.

The rebuild then runs these checks again on the rebuilt layout:
- Magic's full SKY130 rule deck: 0 errors;
- layout against the circuit: a unique match, no property errors, and every applicable planted fault detected;
- antenna exposure of every gate net at each etch stage, counting only the connections that exist at that stage, with
  resistor bodies taken both as conducting and as open: no net over its limit, and planted faults found;
- Tiny Tapeout's precheck: every check passes, and its planted faults are caught;
- Tiny Tapeout's three n-well rules: 0 violations;
- the unused output and output-enable pins tied to ground;
- the hidden-offset block's ground tied to a ground stripe by metal alone;
- the three n-well rules measured on the layout itself, each with planted faults: a well encloses the lvtn inside it
  by at least 0.38 um, regions where hvtp overlaps n-well are at least 0.38 um wide and at least 0.38 um apart, and
  urpm stays at least 0.70 um from n-well and never overlaps it;
- the poly resistors' contact bars at least 0.64 um apart end to end as drawn, SkyWater's mask-generation rule;
- every poly resistor body at least 0.66 um long, SkyWater's mask-generation rule;
- the nitride poly cut at least 0.10 um around every poly contact;
- the count of MIM capacitors over lower layers' edges kept at or below this layout's count, and the high-resistance
  resistors' distances from NMOS transistors kept at or above this layout's minima;
- three thick-oxide (HVI) checks:
  - HVI at least 0.84 um wide, a rule SkyWater has flagged on past shuttles;
  - the rebuild fails if HVI is closer than 0.64 um to a low-voltage n-well and reports every spacing below SkyWater's
    0.70 um rule (hvi.5);
  - no more HVI edges across gate poly than the recorded count. This is a number the design keeps from growing, not a
    rule limit.

The rebuild recorded in `source/README.md` is made in a sandbox, with the design repository hidden and no network.

## What was checked on this layout

| Check | Result |
| --- | --- |
| Magic, full SKY130 rule deck | 0 errors |
| Antenna rules on the finished layout (Magic) | 0 violations |
| Antenna exposure at each etch stage (only what is connected when that layer is etched) | no gate net over its limit; the largest metal 2 sidewall ratio without a diffusion on the net is 378 (limit 400) |
| Layout against circuit (netgen, against `source/six_edge_programmable_20261117/takeover/bias/layout/rzero/variant_reference_v5.spice`) | Circuits match uniquely, with no property errors; 49 of 49 applicable planted faults detected, and the check fails against a wrong netlist |
| Tiny Tapeout precheck (tt-support-tools `7d2d2ef`) | 17 of 17 checks pass; all 4 planted faults are caught |
| Tiny Tapeout's n-well rules | 0 violations of each of the three |
| Tiny Tapeout's GitHub actions on this layout | the layout build, the precheck and the documentation build pass |
| Unused outputs `uio_out`, `uio_oe` | all sixteen share the ground net through metal. Every other signal pin is on its own net. |
| Thick oxide (HVI) | at least 0.705 um from every low-voltage n-well (SkyWater rule hvi.5: 0.70 um); at least 0.84 um wide; no transistor gate straddles its edge (0 of 124 thick-oxide gates); 197 gate ends over field oxide cross it |
| Poly resistors: contact bars end to end | at least 0.70 um apart as drawn (SkyWater's mask-generation rule: 0.64 um) |
| Poly resistors: body length | every body at least 0.70 um long (SkyWater's mask-generation rule: 0.66 um) |
| The three n-well rules, measured on the layout itself (Tiny Tapeout's decks measure them less strictly) | no low-threshold implant (lvtn) across an n-well's edge, and at least 0.385 um of enclosure wherever lvtn lies inside a well (0.38 um required); the regions where high-threshold implant (hvtp) overlaps n-well are at least 0.92 um wide, with no spacing below the required 0.38 um, and hvtp outside the n-wells only as SkyWater's standard cells' own 0.055 um strips; no high-resistance implant (urpm) over an n-well, and every urpm at least 0.71 um from one (0.70 um required); 6 of 6 planted faults found |
| MIM capacitors over edges of lower layers (capm.10) | 105 of 109 capacitors have an edge of a lower layer under them; the check holds this count (below) |
| Nitride poly cut (npc) around poly contacts (licon.15) | at least 0.105 um at the transistors' gate contacts and 0.18 um at the resistors' heads (0.10 um required); no poly contact outside npc |
| Ground plates and substrate | all 31 ground plates tied; no substrate island |
| Ground of the hidden-offset block (its two transistors and storage capacitors) | tied to a ground stripe by its own metal strap alone: the metal connectivity check passes as built and fails with the strap opened (the layout-against-circuit check cannot show this, because the substrate also ties that ground); with the resistance of the chip's wiring in the model, at typical the two transistor sources sit 0.003 and 0.015 mV above the ground pin in a static solve |
| Sandbox rebuild from this repository's `source/` | see `source/README.md`, section "Rebuilding from this folder alone" |

The PDK's other open rule decks were also run on this layout. Two of their findings concern rules that Tiny Tapeout's
precheck does not test. In 105 of the layout's 109 MIM capacitors an edge of a lower layer lies under the capacitor
(capm.10). An older open deck reports 197 places where gate poly over field oxide crosses the edge of the thick oxide;
the published rule (hvpoly.14, "(poly and diff) cannot straddle Hvi") is on the transistor gate, and none of the
layout's 124 thick-oxide gates straddles that edge. The open decks do not check every rule SkyWater applies when it
makes the masks, or not as strictly, so these limits were also measured on the layout itself (the table above): the
thick oxide's width and its distance from low-voltage n-wells, the three n-well rules, the end-to-end spacing of the
resistors' contact bars, the length of every resistor body, and the nitride poly cut around poly contacts.

One rule SkyWater has applied is not published: on a recent shuttle it had a resistor of the precision type (rpm) moved
farther from an NMOS transistor whose gate poly was 0.75 um from it. This layout has no resistor of that type. The
high-resistance resistors (urpm) have markers at least 0.69 um from NMOS gate poly and 0.275 um from n+ implant.
Resistors of this type closer to NMOS transistors stayed on that shuttle after SkyWater's mask-making checks. Whether
the rule covers them is not known; the rebuild holds these distances.

The circuit was simulated: the fixed network at 27 conditions, six-weight mode, its calibration, and learning with the
chip in the loop. Part of the six-weight results come from models of the chip whose hidden offsets differ from this
chip's, marked † in the datasheet. The datasheet gives these results and the conditions behind each. The
simulation results and run folders are not in this repository (`source/README.md`, section "What is not here").

## Tiny Tapeout

Tiny Tapeout is an educational project that makes it easier and cheaper to get designs manufactured on a real chip.
Analog specifications: <https://tinytapeout.com/specs/analog/>.
