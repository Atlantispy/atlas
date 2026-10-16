#!/usr/bin/env bash
# Statistical stack profiles of initial_metrics, two arms at once under the same conditions:
#   r2 = composed-r2/src + composed-r2 helpers (route (1)'s frozen checkpoint composition)
#   sh = srchandles-r2 + composed-r1 helpers/ram (the geometry chat's 285 s layout)
# Writes R/L/smp-r2/samples.json and R/L/smp-sh/samples.json only.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
HT="$T/fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests"
P="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
date '+start %H:%M:%S'
"$P" -B "$S/sample_initial_metrics.py" "$R/L/smp-r2" "$R/composed-r2/src" "$R/composed-r2/helpers" "$HT" \
    > "$S/smp-r2.log" 2>&1 &
A=$!
"$P" -B "$S/sample_initial_metrics.py" "$R/L/smp-sh" "$T/gg/srchandles-r2" "$R/composed-r1/helpers" \
    "$R/composed-r1/ram" "$HT" > "$S/smp-sh.log" 2>&1 &
B=$!
echo "pids r2 $A sh $B"
wait $B; echo "sh exit $? $(date '+%H:%M:%S')"
wait $A; echo "r2 exit $? $(date '+%H:%M:%S')"
for arm in sh r2; do echo "== $arm"; tail -2 "$S/smp-$arm.log" | cut -c1-300; done
