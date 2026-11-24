#!/bin/bash
# Every check of the layout stream on one layout, one command:
#
#   scripts/check_all.sh GDS TAG NETLIST ROOT [REFERENCE_TAG]
#
#   GDS            the layout (a .gds; gzip it out first)
#   TAG            a short name for this layout's outputs: results/*_TAG.*, runs/TAG/*.log, build/TAG*/
#   NETLIST ROOT   the circuit it must match (a .spice or .spice.gz) and its top subcircuit, e.g.
#                  native_edges/verification/evidence/layout_bbf78759_gate_p897/reference.spice.gz xor_chip_native_six
#   REFERENCE_TAG  the layout against which "new crossings" are judged (default: sel, the selected layout bbf78759, which
#                  has been run); the earlier chip's frozen GDS (build/control.gds, tag ctrl) is the control of every other
#                  comparison (run once, its files are in results/ and runs/).
#
# Steps (each one command of its own; a step that fails does not stop the others; the summary lists each exit status):
#   inventory   gds_inventory.py      top cell, cells, instances
#   ties        check_ties.sh         rings, wells, substrate and capacitor plates on their rails through metal, against the
#                                     extraction (exit 0 does not mean pass: read results/ties_netlist_TAG.json)
#   antenna     magic_flows.py antenna  Magic's antenna check (PDK rules and near-zero limits)
#   drc         magic_flows.py drc    Magic's full rule deck
#   lvs         lvs_check.py          layout against NETLIST by the earlier chip's method, with its 25 + 13 planted faults
#   precheck    tt_precheck.py        top cell renamed and prefixed, LEF, Tiny Tapeout's precheck and its 4 planted faults
#                                     (since 23 Nov, 22:00: their tools at GitHub's main, ~/.local/opt/tt_proof/precheck_main,
#                                     fetched and fast-forwarded first; the commit and whether it equals GitHub's main printed)
#   wellrules   ../checks/tt_well_rules.sh   a design check: Tiny Tapeout's three n-well rules (urpm, hvtp, lvtn) from
#                                     their current tools, on the staged GDS (exit 1 if any violation)
#   pinties     ../checks/pin_ties.py a design check: uio_oe[*] and uio_out[*] tied to VGND by metal, no two other pins
#                                     on one net (read RESULT in runs/TAG/pinties.log)
#   hvi         ../checks/rule_audit/measure.py + hvi_measures.py   the rule audit's geometry (23 Nov), three limits SkyWater
#                                     has enforced and no deck of ours tests: HVI at least 0.64 from a low-voltage n-well,
#                                     HVI at least 0.84 wide, HVI edges across gate poly no more than lock2's 197 (exit 1 if not)
#   bars        licon_bars.py         (24 Nov) the contact bars as SkyWater's mask generation grows them: end to end at least
#                                     0.64 um drawn (0.58 after growth), side by side 0.51 um (0.58 after growth when 0.64 um
#                                     apart or more), corners and bar to square contact judged grown; Tiny Tapeout's deck does
#                                     not grow the ends of close bars (lock3_r: 0.54 um end to end passes it); with its 10
#                                     planted patterns (exit 1 if any pair is too close or a planted fault is not found)
#   reslen      res_length.py         (24 Nov) every poly resistor body at least 0.66 um long along the current (MR_poly.LEN.2;
#                                     Tiny Tapeout's deck tests the longer side of the body's box, and passes lock3_r's
#                                     1.41 x 0.54 um body); with its 6 planted resistors (exit 1 if any body is short)
#   wells       well_rules.py         (24 Nov) Tiny Tapeout's three n-well rules measured directly where their decks measure
#                                     less: no lvtn across a well's edge, hvtp outside the wells only as the standard cells'
#                                     own strips, no urpm over a well; with its 8 planted patterns (exit 1 if any fails)
#   resnmos     res_near_nmos.py      (24 Nov) precision resistors beside NMOS gate poly and nsdm, held to lock4_r's distances
#                                     (SkyWater's unwritten ttsky26a rule); with its 3 planted patterns (exit 1 if closer)
#               (the hvi step also judges capm.10, no more than lock4_r's 105 caps, and licon.15, npc 0.10 um, since 24 Nov)
#   over        over_blocks.py        what lies over and under every block, device by device
#   newcross    new_crossings.py      devices (resistor bodies, MIM plates) with more foreign metal than in REFERENCE_TAG:
#                                     exit 1 if any
#   sheet       sheet_run.py          the accepted check of the grounded sheet over rw_res (exit 1: not there, as on bbf78759)
#   coupling    strip_coupling.py + coupling_tables.py   wire-to-strip coupling no extraction holds, table and fragment
#   cap, capcmp magic_flows.py cap + cap_compare.py      capacitance and digital coupling of the important nodes vs the
#                                     earlier chip
#   rails, drop, supplypath  magic_flows.py res + static_drop.py + supply_path_flow.py   ground, supply, REF with wire
#                                     resistance; steady drops at every block; where each supply path's resistance lies
#                                     (since 23 Nov 17:00 the supplies are tied only at points ON their metal4 stripes,
#                                     stripe_points.py; before, every point inside a stripe's rectangle was tied)
cd "$(dirname "$0")/.."
GDS=$(readlink -f "$1"); TAG=$2; NETLIST=$(readlink -f "$3"); ROOT=$4; REF=${5:-sel}
[ -f "$GDS" ] && [ -n "$TAG" ] && [ -f "$NETLIST" ] && [ -n "$ROOT" ] || { sed -n 2,14p "$0"; exit 2; }
PY=${PY:-$DESIGN_REPO/.venv/bin/python}; KPY=${KPY:-$HOME/.local/opt/klayout-py/bin/python}
mkdir -p runs/$TAG results build/$TAG
ORDER=(); declare -A ST
step() { local name=$1; shift; local t0=$SECONDS; "$@" > runs/$TAG/$name.log 2>&1; ST[$name]="exit $? ($((SECONDS - t0)) s)"; ORDER+=($name); echo "  $name: ${ST[$name]}"; }
echo "== $TAG: $GDS (sha256 $(sha256sum "$GDS" | cut -c1-16)), netlist $NETLIST ($ROOT), new crossings against $REF; $(date)"
step inventory  $KPY -B scripts/gds_inventory.py "$GDS" results/inventory_$TAG.json
step ties       bash scripts/check_ties.sh "$GDS" $TAG
step antenna    $PY -I scripts/magic_flows.py antenna "$GDS" build/$TAG
step drc        $PY -I scripts/magic_flows.py drc "$GDS" build/$TAG
step lvs        $PY -I scripts/lvs_check.py "$GDS" "$NETLIST" "$ROOT" $TAG
step precheck   $PY -I scripts/tt_precheck.py "$GDS" $TAG
STAGED=build/$TAG/tt/project/gds/tt_um_mbacvanski_analog_eqprop.gds
step wellrules  bash ../checks/tt_well_rules.sh "$STAGED" tt_um_mbacvanski_analog_eqprop
step pinties    $KPY ../checks/pin_ties.py "$GDS"
step hvi        bash -c "$KPY -I ../checks/rule_audit/measure.py '$GDS' '$STAGED' build/$TAG/tt/project/lef/tt_um_mbacvanski_analog_eqprop.lef build/$TAG/measure.json && $PY -I scripts/hvi_measures.py build/$TAG/measure.json results/hvi_measures_$TAG.json"
step bars       $KPY -I scripts/licon_bars.py "$GDS" results/licon_bars_$TAG.json
step reslen     $KPY -I scripts/res_length.py "$GDS" results/res_length_$TAG.json
step wells      $KPY -I scripts/well_rules.py "$GDS" results/well_rules_$TAG.json
step resnmos    $KPY -I scripts/res_near_nmos.py "$GDS" results/res_near_nmos_$TAG.json
step over       $KPY -B scripts/over_blocks.py sel "$GDS" runs/over_blocks_$TAG.json
step newcross   $PY -I scripts/new_crossings.py runs/over_blocks_$TAG.json runs/over_blocks_$REF.json results/new_crossings_${TAG}_vs_$REF.json
step sheet      $PY -I scripts/sheet_run.py "$GDS" $TAG
step coupling   bash -c "$KPY -B scripts/strip_coupling.py '$GDS' build/$TAG/lvs/flat_lvs.ext runs/strip_coupling_$TAG.json && $PY -I scripts/coupling_tables.py runs/strip_coupling_$TAG.json build/$TAG/lvs/flat_lvs.ext - runs/over_blocks_$TAG.json results/unmodelled_coupling_$TAG"
step cap        $PY -I scripts/magic_flows.py cap "$GDS" build/$TAG
step capcmp     $PY -I scripts/cap_compare.py "$GDS" build/$TAG/wired/tt_flat.ext runs/over_blocks_$TAG.json build/control.gds build/ctrl/wired/tt_flat.ext runs/over_blocks_control.json results/cap_compare_$TAG.json
step rails      $PY -I scripts/magic_flows.py res "$GDS" build/${TAG}_rails VGND VDPWR az_ref4_0.out
step drop       $PY -I scripts/static_drop.py build/${TAG}_rails/wired/res/tt_flat_rc.spice build/${TAG}_rails/wired/res/tt_flat.res.ext - runs/over_blocks_$TAG.json VGND VDPWR results/static_drop_$TAG.json "$GDS"
step supplypath $PY -I scripts/supply_path_flow.py build/${TAG}_rails/wired/res runs/over_blocks_$TAG.json results/supply_path_flow_$TAG.json Z,H1,H2,BUF_BIAS1,BUF_BIAS2 vdd "$GDS"
echo "== summary $TAG ($(date))"
for k in "${ORDER[@]}"; do echo "  $k: ${ST[$k]}"; done
echo "  verdicts:"
grep -h "LVS:\|planted faults" runs/$TAG/lvs.log | sed 's/^/    /'
grep -h "ALL PASS\|PRECHECK FAILED" runs/$TAG/precheck.log | sed 's/^/    precheck: /'
grep -h "^precheck tools:" runs/$TAG/precheck.log | head -1 | sed 's/^/    /'
grep -h "violations\|^tools:" runs/$TAG/wellrules.log | sed 's/^/    well rules: /'
grep -h "^RESULT:" runs/$TAG/pinties.log | sed 's/^/    pin ties: /'
grep -h "^HVI\|^capm.10\|^licon.15" runs/$TAG/hvi.log | sed 's/^/    /'
grep -h "^RESULT:" runs/$TAG/bars.log | sed 's/^/    contact bars: /'
grep -h "^RESULT:" runs/$TAG/reslen.log | sed 's/^/    resistor length: /'
grep -h "^RESULT:" runs/$TAG/wells.log | sed 's/^/    well rules, direct: /'
grep -h "^RESULT:" runs/$TAG/resnmos.log | sed 's/^/    resistors near NMOS: /'
grep -h "protected devices" runs/$TAG/newcross.log | sed 's/^/    /'
grep -h "violations" runs/$TAG/antenna.log | head -1 | sed 's/^/    antenna: /'
$PY -I -c "import json; d=json.load(open('results/ties_netlist_$TAG.json')); print('    ties: ground plates tied by metal:', d['every_ground_plate_tied_by_metal'], '| bias words\' ground on VGND by metal:', d.get('bias_words_ground_on_VGND_by_metal'), '| wells off the supply:', d['wells_off_the_supply_by_the_metal_trace'], '| substrate islands:', d['substrate_islands_by_the_metal_trace'])" 2>/dev/null
$PY -I -c "import json; d=json.load(open('build/$TAG/drc.json')); print('    Magic DRC errors:', d['total'])" 2>/dev/null
