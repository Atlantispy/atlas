#!/usr/bin/env bash
# run_trace_p20.sh with the composition and output names as arguments: one real heat call with a loaded-file trace.
#   bash run_trace_r4.sh WORKSPACE COMPOSITION NAME   (COMPOSITION under ac/; writes rm/fold/NAME, NAME-out.json,
#                                                       NAME-trace.json)
# r3 = run_trace_r2.sh with hcf_prepare_r14.py (reviewed records p20c-r1 and p20c-r2) in place of r13.
# r4 = r3 with hcf_prepare_r15.py (reviewed records p20c-r1, p20c-r2 and, once staged, p20c-r3) in place of r14.
set -e
T="$1"
PY="$T/.r44-env/Scripts/python.exe"
RR="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
HCF="$RR/probes/step9/claude-20261016/heat_control_on_frozen.py"
P="$T/ac/$2"
F="$T/rm/fold"
N="$3"
export PYTHONHASHSEED=0
echo "prepare $(date +%H:%M:%S)"
"$PY" -B "$F/hcf_prepare_r15.py" "$HCF" "$P/composition.json" "$F/$N" "$P/src" "$P/helpers"
echo "child $(date +%H:%M:%S)"
"$PY" -B "$F/trace_frozen.py" "$HCF" "$F/$N" "$F/$N-out.json" - "$F/$N-trace.json"
echo "end $(date +%H:%M:%S)"
