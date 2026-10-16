#!/usr/bin/env bash
# g14: same-call heat re-proof after the B17 rev4 + item 14 merge into the compact folder (16 Oct 2026 18:15:47).
# segment_store.py and record_views.py changed, and both are heat-captured (the g12 and g13 precedents). Same
# harness as g12/g13: step7_same_call_heat_control.py --prepare/--child from the compact folder, live memory 0
# and 1, on fresh layouts g14l0/g14l1. Seed 0 (coordinator rule): no -I, a cleaned environment with
# PYTHONHASHSEED=0, and the fail-closed seed check before any child starts. Output beside this script:
# g14-prepare-*.log, g14-child-*.log, g14-same-call-live*.json; then each arm's checks, and every line that
# differs from the g13 result of the same arm (g13 ran on the R1-generation tree at 10:31).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
T="$(cd "$R/../../../.." && pwd)"
C="$R/compact-geometry-r1"
PY="$T/.r44-env/Scripts/python.exe"
for name in $(env | sed -n 's/^\([Pp][Yy][Tt][Hh][Oo][Nn][^=]*\)=.*/\1/p'); do
  [ "$name" = PYTHONDONTWRITEBYTECODE ] || unset "$name"
done
export PYTHONHASHSEED=0
"$PY" -B "$HERE/seed_zero_check.py" || exit 3
for live in 0 1; do
  if [ -e "$R/probes/step8/g14l$live" ]; then echo "g14 layout g14l$live exists; refusing"; exit 4; fi
done
for live in 0 1; do
  layout="$R/probes/step8/g14l$live"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --prepare "$layout" "$live" > "$HERE/g14-prepare-$live.log" 2>&1)
  status=$?; echo "g14 prepare $live exit $status $(date +%H:%M:%S)"; [ $status -eq 0 ] || exit 5
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --child "$layout" "$HERE/g14-same-call-live$live.json" > "$HERE/g14-child-$live.log" 2>&1)
  status=$?; echo "g14 child $live exit $status $(date +%H:%M:%S)"; [ $status -eq 0 ] || exit 6
done
for live in 0 1; do
  out="$HERE/g14-same-call-live$live.json"
  checks="$(sed -n '/"checks": {/,/}/p' "$out")"
  echo "g14 live$live checks: $(printf '%s\n' "$checks" | grep -c ': true') true, $(printf '%s\n' "$checks" | grep -c ': false') false"
  echo "--- g14 live$live lines that differ from g13 live$live:"
  diff "$R/probes/step8/claude-20261015/g13-same-call-live$live.json" "$out"
done
exit 0
