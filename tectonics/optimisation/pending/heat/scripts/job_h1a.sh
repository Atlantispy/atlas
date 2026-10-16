#!/usr/bin/env bash
# H1a: proof (base vs H1a), ABBA timing, worker profiles. Run under run_locked.sh.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/h1a-r1"
"$PY" -B "$HS/scripts/ab_heat.py" run "$OUT" proof:base:"$HS/lw" proof:h1a:"$HS/lc" \
  time:base:"$HS/lw" time:h1a:"$HS/lc" time:h1a:"$HS/lc" time:base:"$HS/lw" \
  prof:base:"$HS/lw" prof:h1a:"$HS/lc" || exit $?
"$PY" -B "$HS/scripts/compare_ab.py" "$OUT/arm-0" "$OUT/arm-1" "$(cygpath -w "$HS/lw")" "$(cygpath -w "$HS/lc")"
