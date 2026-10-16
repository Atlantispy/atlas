#!/usr/bin/env bash
# Smoke of the exact q10 harness, ab_heat_r5.py ("review before you queue", item 3). Run it as
#   runq.py small --cores 7 --gib 1.1 -- bash smoke_r4.sh
# r4 of the smoke (16 Oct 14:30) follows Michael's 14:05/14:08 decisions: no blanket 10 GiB wait. ab_heat_r5 gates
# each arm on its predicted peak x 1.2 + 2 GiB:
#   - the proof arm is predicted from q03's measured lw proof arm (--history evidence/h12-r1, 1031 MiB);
#   - the time and prof arms have no measured record yet, so they fall back to --pred-peak-gib 1.1 (q03's
#     1.03 GiB tree peak, rounded up). runq small sets no RUNQ_PRED_PEAK_GIB.
# The arms are one of each mode on lw (the real W4 call; no smaller heat fixture exists). Then the same
# fail-closed checks q10 uses. It gives per-arm wall time, tree, parent and worker peaks for the q10 booking.
# It also proves the sys.monitoring observer on the real case: its lw capture must be byte-identical to q03's
# lw arm-0 (r1 setprofile observer).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/smoke-r4"
export PYTHONHASHSEED=0
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
echo "smoke r4 start $(date +%H:%M:%S)"
"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT" --history "$HS/evidence/h12-r1/summary.json" --pred-peak-gib 1.1 \
  proof:base:"$HS/lw" time:base:"$HS/lw" prof:base:"$HS/lw" || exit $?
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" 3 > "$OUT/check-arms.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$HS/evidence/h12-r1/arm-0" > "$OUT/compare-observer-q03.txt" || s=1
cat "$OUT/check-arms.txt"; tail -n 3 "$OUT/compare-observer-q03.txt"
echo "smoke r4 end $(date +%H:%M:%S) exit $s"
exit $s
