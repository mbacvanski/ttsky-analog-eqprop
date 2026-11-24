#!/bin/bash
# Design check (2026-11-23): Tiny Tapeout's three n-well rules, from THEIR current tools, on one GDS, in seconds.
# The lvtn rule was added to their precheck on 2026-11-23 (commit 7d2d2ef); the copy in ~/.local/opt/tt_proof/precheck
# (9d13ff3, 5 November) does not have it. Current tools: ~/.local/opt/tt_proof/precheck_main (git pull there to update).
# usage: checks/tt_well_rules.sh <gds> [top cell]      prints the number of violations per rule; exit 1 if any
set -eu
GDS=$(realpath "$1"); TOP=${2:-}
# no top cell given: take the layout's own (the decks fail with an empty name)
[ -n "$TOP" ] || TOP=$("$HOME/.local/opt/klayout-py/bin/python" -I -c 'import sys, klayout.db as db; l = db.Layout(); l.read(sys.argv[1]); print(l.top_cell().name)' "$GDS")
P=${TT_PRECHECK_DIR:-$HOME/.local/opt/tt_proof/precheck_main}
OUT=$(mktemp -d "${TMPDIR:-$HOME/.local/opt/tt_proof/work}/wellrules.XXXXXX")
echo "tools: $(git -C "$P/tt-support-tools" log -1 --format='%h %cd' --date=short)  gds: $(sha256sum "$GDS" | cut -c1-16)"
bad=0
for r in nwell_urpm nwell_hvtp nwell_lvtn; do
  "$P/bin/klayout" -b -r "$P/tt-support-tools/precheck/tech-files/$r.drc" -rd input="$GDS" -rd top_cell="$TOP" \
      -rd report="$OUT/$r.xml" -rd thr=4 > "$OUT/$r.log" 2>&1 || { echo "$r: klayout failed, see $OUT/$r.log"; bad=1; continue; }
  n=$(grep -c '<item>' "$OUT/$r.xml" || true)
  echo "$r: $n violations"
  [ "$n" = 0 ] || bad=1
done
echo "reports: $OUT"
exit $bad
