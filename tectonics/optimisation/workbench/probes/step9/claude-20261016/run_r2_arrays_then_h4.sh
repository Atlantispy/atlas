#!/usr/bin/env bash
# 16 Oct 2026, after the frozen smoke ends: (1) composed-r2's W4 arrays, saved and checked for a
# whole-row permutation against g13l1/d1/g13l0; (2) H4, heat reconstruction workers 6/8/10/12/8/6
# on the g13l1 W4 layout, one locked job (the wrapper takes the heavy-run lock; waits up to 2 h).
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
D="$R/probes/step8/claude-20261015"
PY="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
log="$S/r2arr-h4.log"
waited=0
until grep -q '^=== done' "$S/frozen-smoke-s2.log"; do
  if [ "$waited" -ge 7200 ]; then echo "=== smoke not done after ${waited}s; nothing started" >> "$log"; exit 75; fi
  sleep 30; waited=$((waited+30))
done
echo "=== r2 arrays start $(date '+%H:%M:%S')" >> "$log"
cd "$R/compact-geometry-r1" || exit 1
"$PY" -B "$S/heat_control_on_frozen.py" child "$R/composed-checks/hc-r2" "$R/L/arr-r2.json" "$D/g13-same-call-live1.json" "$R/L/arr-r2" >> "$log" 2>&1
echo "=== r2 arrays exit $? $(date '+%H:%M:%S')" >> "$log"
"$PY" -B "$S/check_permutation.py" "$R/L/arr-g13l1" "$R/L/arr-d1" "$R/L/arr-g13l0" "$R/L/arr-r2" --digests "$R/composed-checks/r2-heat-control.json" "$R/composed-checks/hc-v1-result.json" "$R/composed-checks/hc-v2-result.json" "$R/composed-checks/hc-e1-result.json" > "$S/permutation-w4-r2.json" 2>> "$log"
echo "=== permutation exit $? $(date '+%H:%M:%S')" >> "$log"
echo "=== h4 queued $(date '+%H:%M:%S')" >> "$log"
bash "$S/run_when_lock_free.sh" 7200 "$log" -- "Steps 8-9 runner and heat" 3.5 "H4: heat reconstruction workers 6/8/10/12/8/6 on W4 g13l1, one arm at a time, parent + up to 12 workers (TOTAL)" -- "$PY" -B "$D/h4_heat_workers.py" run "$R/probes/step8/g13l1" "$R/L/h4" "$D/g13-same-call-live1.json" 6 8 10 12 8 6
echo "=== h4 exit $? $(date '+%H:%M:%S')" >> "$log"
