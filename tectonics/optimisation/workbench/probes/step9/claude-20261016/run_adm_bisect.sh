#!/usr/bin/env bash
# Bisect composed-r2's slow initial_metrics (adm1: 1,002 CPU-s) against the geometry chat's
# srchandles-r2 measurement (285 s), three arms at once under the same machine conditions:
#   a0 = srchandles-r2 + composed-r1 helpers/ram  (the geometry chat's own layout: today's control)
#   a1 = composed-r2/src + composed-r1 helpers/ram  (the native tree's effect)
#   a2 = srchandles-r2 + composed-r2 helpers        (the helpers' effect)
# Each arm stops after initial_metrics (--metrics-only). Writes R/L/adm2-a*/report.json only.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
S="$R/probes/step9/claude-20261016"
HT="$T/fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests"
P="$T/.r44-env/Scripts/python.exe"
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
date '+start %H:%M:%S'
"$P" -B "$S/time_admission_parts.py" --metrics-only "$R/L/adm2-a0" "$T/gg/srchandles-r2" \
    "$R/composed-r1/helpers" "$R/composed-r1/ram" "$HT" > "$S/adm2-a0.log" 2>&1 &
A0=$!
"$P" -B "$S/time_admission_parts.py" --metrics-only "$R/L/adm2-a1" "$R/composed-r2/src" \
    "$R/composed-r1/helpers" "$R/composed-r1/ram" "$HT" > "$S/adm2-a1.log" 2>&1 &
A1=$!
"$P" -B "$S/time_admission_parts.py" --metrics-only "$R/L/adm2-a2" "$T/gg/srchandles-r2" \
    "$R/composed-r2/helpers" "$HT" > "$S/adm2-a2.log" 2>&1 &
A2=$!
echo "pids a0 $A0 a1 $A1 a2 $A2"
wait $A0; echo "a0 exit $? $(date '+%H:%M:%S')"
wait $A1; echo "a1 exit $? $(date '+%H:%M:%S')"
wait $A2; echo "a2 exit $? $(date '+%H:%M:%S')"
for arm in a0 a1 a2; do echo "== $arm"; tail -3 "$S/adm2-$arm.log" | cut -c1-300; done
