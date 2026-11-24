#!/bin/bash
# Rung 0, ties: rings, wells, substrate taps and capacitor plates on their rails through metal, for one GDS.
#   scripts/check_ties.sh GDS TAG     -> results/ties_TAG.json, results/ties_netlist_TAG.json, build/TAG/lvs/
set -e
cd "$(dirname "$0")/.."
GDS=$1; TAG=$2
PY=${PY:-$DESIGN_REPO/.venv/bin/python}; KPY=${KPY:-$HOME/.local/opt/klayout-py/bin/python}
$KPY -B scripts/ties.py "$GDS" results/ties_$TAG.json > runs/ties_$TAG.log 2>&1
$PY -I scripts/magic_flows.py lvs "$GDS" build/$TAG > runs/lvs_extract_$TAG.log 2>&1
$PY -I scripts/ties_netlist.py results/ties_$TAG.json build/$TAG/lvs/flat_lvs.spice results/ties_netlist_$TAG.json > runs/ties_netlist_$TAG.log
tail -12 runs/ties_$TAG.log
grep -E '"every_ground_plate_tied_by_metal"|bias_words_ground|wells_off|substrate_islands' results/ties_netlist_$TAG.json
