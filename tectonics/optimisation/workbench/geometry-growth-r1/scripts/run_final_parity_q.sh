#!/usr/bin/env bash
# run_final_parity.sh for the coordinator's run queue (T/q/runq.py run qNN -- bash <this> ...).
# Same as run_final_parity_locked.sh WITHOUT its own lock: runq takes the same lock file, so a
# second acquire here would wait on itself. Every output line is time-stamped (per-stage times =
# gaps between lines). Usage: run_final_parity_q.sh <tag> <candidate src> [<candidate helpers>]
# With a helpers folder, only the candidate composition loads it (rc1_env RC1_ENV_TEST_HELPERS).
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
TAG=$1; CAND=$2; HELP=${3:-}
[ -n "$HELP" ] && export RC1_ENV_TEST_HELPERS="$CAND|$HELP"
cd "$G/scripts"
echo "$(date +%H:%M:%S) started under the run queue; available $("$PY" -B -I -c "import psutil; print(round(psutil.virtual_memory().available/2**30,1))") GiB"
bash run_final_parity.sh "$TAG" "$CAND" 2>&1 | while IFS= read -r line; do echo "$(date +%H:%M:%S) $line"; done
status=${PIPESTATUS[0]}
echo "$(date +%H:%M:%S) final parity exit $status"
exit $status
