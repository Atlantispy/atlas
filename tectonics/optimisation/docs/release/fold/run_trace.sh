#!/usr/bin/env bash
# FOLD §9 (1a): one real heat call on composed-r2 with a loaded-file trace. Small lane, via runq small.
set -e
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
RR="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
HCF="$RR/probes/step9/claude-20261016/heat_control_on_frozen.py"
W="$T/rm/fold/tr"
export PYTHONHASHSEED=0
echo "prepare $(date +%H:%M:%S)"
"$PY" -B "$HCF" prepare "$W" "$RR/composed-r2/src" "$RR/composed-r2/helpers"
echo "child $(date +%H:%M:%S)"
"$PY" -B "$T/rm/fold/trace_frozen.py" "$HCF" "$W" "$T/rm/fold/tr-out.json" "$RR/composed-checks/r2-heat-control.json" "$T/rm/fold/tr-trace.json"
echo "end $(date +%H:%M:%S)"
