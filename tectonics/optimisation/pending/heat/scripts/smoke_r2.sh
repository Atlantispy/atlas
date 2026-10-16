#!/usr/bin/env bash
# Smoke of the exact q10 harness ("review before you queue", item 3), run via runq.py small after
# q03 has been stopped: ab_heat_r2.py with one arm of each mode on lw (the real W4 call; no smaller
# heat fixture exists), then the same fail-closed checks q10 uses. Gives per-arm wall time and tree
# peak memory for the q10 booking, and proves the sys.monitoring observer on the real case: its lw
# capture must be byte-identical to q03's lw arm-0 (r1 setprofile observer).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/smoke-r2"
export PYTHONHASHSEED=0
# q03 ended at 13:49:49 (arm 2 refused by the 10 GiB start gate). Wait here, cheaply, until the
# machine again has the start gate's 10 GiB available (+0.5 GiB margin), so the harness's own
# 10-min gate wait does not stop the first arm.
until "$PY" -B -c "import psutil, sys; sys.exit(psutil.virtual_memory().available < 10.5*2**30)"; do sleep 30; done
echo "memory gate open at $(date +%H:%M:%S)"
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
"$PY" -B "$HS/scripts/ab_heat_r2.py" run "$OUT" proof:base:"$HS/lw" time:base:"$HS/lw" prof:base:"$HS/lw" || exit $?
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" 3 > "$OUT/check-arms.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$HS/evidence/h12-r1/arm-0" > "$OUT/compare-observer-q03.txt" || s=1
cat "$OUT/check-arms.txt"; tail -n 3 "$OUT/compare-observer-q03.txt"
exit $s
