#!/usr/bin/env bash
# r3 of smoke_r2.sh (16 Oct 14:05). The body is the same; only the memory wait moved OUT of the runq small job.
# Why: runq small checks for exclusive tickets only when it launches. r2 slept inside the job until 10.5 GiB
# were free, so it could have started 6-worker heat work in the middle of an exclusive ticket (q13),
# disturbing that ticket's timing and CPU gate. Here the job runs only when memory is already free at launch,
# and otherwise exits 75 so scripts/smoke_launch_r3.sh can wait outside runq and try again.
# What it does: ab_heat_r2.py runs one arm of each mode on lw (the real W4 call; no smaller heat fixture
# exists), then the same fail-closed checks q10 uses. Gives per-arm wall time and tree peak memory for the
# q10 booking. Proves the sys.monitoring observer on the real case: its lw capture must be byte-identical
# to q03's lw arm-0 (r1 setprofile observer).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/smoke-r3"
export PYTHONHASHSEED=0
"$PY" -B -c "import psutil, sys; sys.exit(psutil.virtual_memory().available < 10.5*2**30)" || { echo "$(date +%H:%M:%S) under 10.5 GiB free at launch; retry"; exit 75; }
echo "memory gate open at $(date +%H:%M:%S)"
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
"$PY" -B "$HS/scripts/ab_heat_r2.py" run "$OUT" proof:base:"$HS/lw" time:base:"$HS/lw" prof:base:"$HS/lw" || exit $?
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" 3 > "$OUT/check-arms.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$HS/evidence/h12-r1/arm-0" > "$OUT/compare-observer-q03.txt" || s=1
cat "$OUT/check-arms.txt"; tail -n 3 "$OUT/compare-observer-q03.txt"
exit $s
