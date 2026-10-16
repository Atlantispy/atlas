#!/usr/bin/env bash
# Final parity tag f2 (candidate now includes q2_zero_test + jets_convolution) under the shared
# heavy-run lock. PYTHONHASHSEED=0 is set inside run_final_parity.sh.
set -u
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
G="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/geometry-growth-r1"
PY="$T/.r44-env/Scripts/python.exe"
cd "$G/scripts"
HEAVY_LOCK_WINPID=$(cat /proc/$$/winpid) "$PY" -B heavy_lock.py acquire $$ 4.0 "geometry chat: final parity f2 (IV1/IV2 rebuilds with growth; 6-shard replays)" || { echo "lock busy; not started"; exit 3; }
trap '"$PY" -B heavy_lock.py release $$' EXIT
echo "start $(date +%H:%M:%S)"
bash run_final_parity.sh f2 > "$G/work/final-f2.log" 2>&1
echo "final parity f2 exit $? $(date +%H:%M:%S)"
