#!/usr/bin/env bash
# q10 split, part A (16 Oct ~15:45; coordinator ~15:40 "BOOKING CHECK"): proofs and D-b compares only.
# Run: T/q/runq.py run <ticket> -- bash job_h1c_r4a.sh. Part B (job_h1c_r4b.sh: timing + profile) starts only
# after this job wrote RESULT = PASS.
# Why split: each arm is a whole W4 control, MEASURED 1,167-1,304 s per arm in q03 (h12-r1). Job r3's 16 arms
# come to about 5.8 h, which would block the queue.
# Same harness (ab_heat_r5.py 790be928), layouts, checks and compares as job r3 (c7023460), minus its timing and
# profile arms. It also replaces the separate smoke (smoke_r4.sh, 3 whole controls): arm 0 is the lw proof, and
# compare-observer-q03 is the smoke's observer check (byte-identical to q03 arm-0). ab_heat_r5 stops at the
# first arm that does not complete, so a broken harness costs one arm, not five.
# Proof arms: lw ld3 le3 lf3 lh. D-b compares: lw-ld3 (H1a r3 + H2), ld3-le3 (H1c r3), le3-lf3 (L1 r4),
# ld3-lf3, lf3-lh (H5a). Plus lw vs q03 arm-0 (observer). All layouts and both flags are required; nothing is
# selected at run time.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/h1c-r4a"
export PYTHONHASHSEED=0
for L in lw ld3 le3 lf3 lh; do [ -f "$HS/$L/control.json" ] || { echo "layout $L missing"; exit 4; }; done
for F in l1-approved.flag h5a-approved.flag; do [ -f "$HS/scripts/$F" ] || { echo "$F missing"; exit 4; }; done
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite"; exit 5; }
echo "job_h1c_r4a start $(date +%H:%M:%S)"
ARMS=(proof:base:"$HS/lw" proof:h12:"$HS/ld3" proof:h12c:"$HS/le3" proof:h12cl1:"$HS/lf3" proof:h5a:"$HS/lh")
"$PY" -B "$HS/scripts/ab_heat_r5.py" run "$OUT" --history "$HS/evidence/h12-r1/summary.json" "${ARMS[@]}" || exit $?
W() { cygpath -w "$1"; }
s=0
"$PY" -B "$HS/scripts/check_arms.py" "$OUT" "${#ARMS[@]}" > "$OUT/check-arms.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$HS/evidence/h12-r1/arm-0" > "$OUT/compare-observer-q03.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-0" "$OUT/arm-1" "$(W "$HS/lw")" "$(W "$HS/ld3")" > "$OUT/compare-base-h12r3.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-1" "$OUT/arm-2" "$(W "$HS/ld3")" "$(W "$HS/le3")" > "$OUT/compare-h12-h1c.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-2" "$OUT/arm-3" "$(W "$HS/le3")" "$(W "$HS/lf3")" > "$OUT/compare-h1c-l1.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-1" "$OUT/arm-3" "$(W "$HS/ld3")" "$(W "$HS/lf3")" > "$OUT/compare-h12-l1.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab_r2.py" "$OUT/arm-3" "$OUT/arm-4" "$(W "$HS/lf3")" "$(W "$HS/lh")" > "$OUT/compare-l1-h5a.txt" || s=1
tail -n 1 "$OUT"/check-arms.txt "$OUT"/compare-*.txt
if [ $s -eq 0 ]; then echo PASS > "$OUT/RESULT"; else echo FAIL > "$OUT/RESULT"; fi
echo "job_h1c_r4a end $(date +%H:%M:%S) exit $s"
exit $s
