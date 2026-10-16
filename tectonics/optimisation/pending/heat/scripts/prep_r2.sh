#!/usr/bin/env bash
# r2 layouts for q10 (run via runq.py small): unit tests first, then three fresh step7 prepares.
#   ld2 = H1a r2 + H2;  le2 = H1a r2 + H1c r2 + H2;  lf2 = le2 + L1 r3 (with the 5-pinner repin).
# Checks: each fresh prepare equals lw apart from control.json; ld2/le2 differ only in exact_growth;
# le2/lf2 differ only in low_ledger + its 5 pinners (l1_generation_note.py refuses anything else).
set -e
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
C="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1"
export PYTHONHASHSEED=0
[ -f "$HS/scripts/prep-ready.flag" ] || { echo "prep_r2: transforms not ready (no prep-ready.flag); refusing"; exit 9; }
cd "$HS/tests"
"$PY" -B -m unittest test_h1a_r2 test_h1_r2 test_l1_low_ledger_op
cd "$HS"
for L in ld2 le2 lf2; do
  [ -e "$HS/$L" ] && { echo "$L already exists; refusing to overwrite"; exit 2; }
  "$PY" -B "$C/step7_same_call_heat_control.py" --prepare "$HS/$L" 1 | tail -n 1
  if diff -r -q "$HS/lw" "$HS/$L" | grep -v control.json; then echo "fresh prepare $L differs from lw"; exit 3; fi
  f="$HS/$L/helpers/private_heat_exact_growth_r1.py"
  "$PY" -B "$HS/transforms/h1a_growth_reserve_r2.py" "$f" "$f.a"
  if [ "$L" = ld2 ]; then mv "$f.a" "$f"; else
    "$PY" -B "$HS/transforms/h1c_growth_inline_r2.py" "$f.a" "$f.c"; mv "$f.c" "$f"; rm "$f.a"; fi
  "$PY" -B "$HS/transforms/h2_fused_dot.py" "$(cygpath -w "$HS/$L/helpers")"
done
"$PY" -B "$HS/transforms/l1_low_ledger_op.py" "$(cygpath -w "$HS/lf2/helpers")"
echo "ld2 vs le2:"; diff -r -q "$HS/ld2/helpers" "$HS/le2/helpers" || true
"$PY" -B "$HS/scripts/l1_generation_note.py" "$(cygpath -w "$HS/le2/helpers")" "$(cygpath -w "$HS/lf2/helpers")" \
  "$(cygpath -w "$HS/evidence/l1-generation-note.md")"
sha256sum "$HS"/l?2/helpers/private_heat_exact_growth_r1.py "$HS"/lf2/helpers/private_heat_low_ledger_inventory_r1.py
rm -rf "$HS/transforms/__pycache__" "$HS/tests/__pycache__"
