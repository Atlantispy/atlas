#!/usr/bin/env bash
# H3 same-call proof and ABBA timing on the genuine W4 call (T/hs/scripts/ab_heat.py, read-only).
# l2 = fresh --prepare + H1a + H2 (identical to T/hs/ld); l3 = l2 + H3. Run under run_locked.sh.
# Usage: job_h3.sh <outdir name under T/ck>
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
CK="$T/ck"
OUT="$CK/$1"
"$PY" -B "$T/hs/scripts/ab_heat.py" run "$OUT" proof:h2:"$CK/l2" proof:h3:"$CK/l3" \
  time:h2:"$CK/l2" time:h3:"$CK/l3" time:h3:"$CK/l3" time:h2:"$CK/l2" || exit $?
"$PY" -B "$T/hs/scripts/compare_ab.py" "$OUT/arm-0" "$OUT/arm-1" "$(cygpath -w "$CK/l2")" "$(cygpath -w "$CK/l3")"
