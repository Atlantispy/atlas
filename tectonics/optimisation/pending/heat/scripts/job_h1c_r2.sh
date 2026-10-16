#!/usr/bin/env bash
# q10: H1 r3 (+ L1 r4 when approved) in ONE job (run via T/q/runq.py run q10 -- bash job_h1c_r2.sh).
# job r2 (16 Oct 14:30): job_h1c.sh with harness ab_heat_r5.py (per-arm predicted start gate, Michael 14:05/14:08)
# in place of ab_heat_r2.py, output evidence/h1c-r2, and --history from q03 and the r4 smoke. Arms
# without a measured record of their route use the ticket's RUNQ_PRED_PEAK_GIB; without it they refuse.
# Layouts (scripts/prep_r3.sh): ld3 = H1a r3 + H2, le3 = + H1c r3, lf3 = + L1 r4; lw = base.
# L1 arms are included only if scripts/l1-approved.flag exists (created 13:37 after both re-refutes
# passed) and lf3 is prepared; the choice is made when the job starts.
# Harness: ab_heat_r5.py (r2's sys.monitoring proof observer, unchanged; checked by
# check_monitor_observer.py, check_gate_r5.py and the smoke evidence/smoke-r4). Proof arms: lw, ld3, le3 [, lf3].
# Timing (coordinator 13:40: base included, symmetric): lw ld3 le3 [lf3 lf3] le3 ld3 lw. One worker
# profile of the newest layout. Fail closed: check_arms.py (every arm PASS, no leaks, 6 workers on
# both calls, no fallback) and compare_ab_r2.py (arm status, non-empty capture, D-b).
# D-b compares: lw-ld3 (H1a r3 + H2), ld3-le3 (H1c r3) [, le3-lf3 (L1), ld3-lf3]; plus the lw proof
# arm against q03's lw arm-0 (r1 observer): the same layout and call, so the arrays must be identical.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/h1c-r2"
export PYTHONHASHSEED=0
for L in lw ld3 le3; do [ -f "$HS/$L/control.json" ] || { echo "layout $L missing (run prep_r3.sh)"; exit 4; }; done
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
MODE=h1c
[ -f "$HS/scripts/l1-approved.flag" ] && [ -f "$HS/lf3/control.json" ] && MODE=with-l1
echo "job_h1c mode: $MODE"
if [ "$MODE" = with-l1 ]; then
  ARMS=(proof:base:"$HS/lw" proof:h12:"$HS/ld3" proof:h12c:"$HS/le3" proof:h12cl1:"$HS/lf3"
        time:base:"$HS/lw" time:h12:"$HS/ld3" time:h12c:"$HS/le3" time:h12cl1:"$HS/lf3"
        time:h12cl1:"$HS/lf3" time:h12c:"$HS/le3" time:h12:"$HS/ld3" time:base:"$HS/lw"
        prof:h12cl1:"$HS/lf3")
else
  ARMS=(proof:base:"$HS/lw" proof:h12:"$HS/ld3" proof:h12c:"$HS/le3"
        time:base:"$HS/lw" time:h12:"$HS/ld3" time:h12c:"$HS/le3" time:h12c:"$HS/le3" time:h12:"$HS/ld3"
        time:base:"$HS/lw" prof:h12c:"$HS/le3")
fi
"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT" --history "$HS/evidence/h12-r1/summary.json" \
  --history "$HS/evidence/smoke-r4/summary.json" "${ARMS[@]}" || exit $?
W() { cygpath -w "$1"; }
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" "${#ARMS[@]}" > "$OUT/check-arms.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$OUT/arm-1" "$(W "$HS/lw")" "$(W "$HS/ld3")" > "$OUT/compare-base-h12r3.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-1" "$OUT/arm-2" "$(W "$HS/ld3")" "$(W "$HS/le3")" > "$OUT/compare-h12-h1c.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$HS/evidence/h12-r1/arm-0" > "$OUT/compare-observer-q03.txt" || s=1
if [ "$MODE" = with-l1 ]; then
  "$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-2" "$OUT/arm-3" "$(W "$HS/le3")" "$(W "$HS/lf3")" > "$OUT/compare-h1c-l1.txt" || s=1
  "$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-1" "$OUT/arm-3" "$(W "$HS/ld3")" "$(W "$HS/lf3")" > "$OUT/compare-h12-l1.txt" || s=1
fi
tail -n 1 "$OUT"/check-arms.txt "$OUT"/compare-*.txt
exit $s
