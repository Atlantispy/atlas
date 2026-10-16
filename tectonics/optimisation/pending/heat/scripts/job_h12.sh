#!/usr/bin/env bash
# H1a + H2 in ONE job (run via T/q/runq.py run qNN -- bash job_h12.sh):
# proof arms (base, H1a, H1a+H2), timing base/H1a/H1a+H2/H1a+H2/H1a/base, one worker profile of H1a+H2;
# then the D-b compares (base-H1a, H1a-H1a+H2, base-H1a+H2).
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/h12-r1"
export PYTHONHASHSEED=0
"$PY" -B "$HS/scripts/ab_heat.py" run "$OUT" \
  proof:base:"$HS/lw" proof:h1a:"$HS/lc" proof:h1a_h2:"$HS/ld" \
  time:base:"$HS/lw" time:h1a:"$HS/lc" time:h1a_h2:"$HS/ld" time:h1a_h2:"$HS/ld" time:h1a:"$HS/lc" time:base:"$HS/lw" \
  prof:h1a_h2:"$HS/ld" || exit $?
W() { cygpath -w "$1"; }
s=0
"$PY" -B "$HS/scripts/compare_ab.py" "$OUT/arm-0" "$OUT/arm-1" "$(W "$HS/lw")" "$(W "$HS/lc")" > "$OUT/compare-base-h1a.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab.py" "$OUT/arm-1" "$OUT/arm-2" "$(W "$HS/lc")" "$(W "$HS/ld")" > "$OUT/compare-h1a-h2.txt" || s=1
"$PY" -B "$HS/scripts/compare_ab.py" "$OUT/arm-0" "$OUT/arm-2" "$(W "$HS/lw")" "$(W "$HS/ld")" > "$OUT/compare-base-h12.txt" || s=1
tail -n 1 "$OUT"/compare-*.txt
exit $s
