#!/usr/bin/env bash
# H2 on top of H1a: proof (H1a vs H1a+H2), ABBA timing, worker profile. Run under run_locked.sh.
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
OUT="$HS/evidence/h2-r1"
"$PY" -B "$HS/scripts/ab_heat.py" run "$OUT" proof:h1a:"$HS/lc" proof:h1a_h2:"$HS/ld" \
  time:h1a:"$HS/lc" time:h1a_h2:"$HS/ld" time:h1a_h2:"$HS/ld" time:h1a:"$HS/lc" \
  prof:h1a_h2:"$HS/ld" || exit $?
"$PY" -B "$HS/scripts/compare_ab.py" "$OUT/arm-0" "$OUT/arm-1" "$(cygpath -w "$HS/lc")" "$(cygpath -w "$HS/ld")"
[ -d "$HS/evidence/h1a-r1/arm-0" ] && "$PY" -B "$HS/scripts/compare_ab.py" "$HS/evidence/h1a-r1/arm-0" "$OUT/arm-1" "$(cygpath -w "$HS/lw")" "$(cygpath -w "$HS/ld")"
