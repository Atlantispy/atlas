#!/usr/bin/env bash
# r3 layouts for q10 (run via runq.py small): unit tests first, then three fresh step7 prepares.
#   ld3 = H1a r3 + H2;  le3 = H1a r3 + H1c r3 + H2;  lf3 = le3 + L1 r4 (with the 5-pinner repin).
# Supersedes prep_r2.sh (never ran; the H1 refuter's r2 re-check found the identity-constant drift).
# Checks: each fresh prepare equals lw apart from control.json; ld3/le3 differ only in exact_growth;
# le3/lf3 differ only in low_ledger + its 5 pinners (l1_generation_note.py refuses anything else).
set -e
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
C="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1"
export PYTHONHASHSEED=0
cd "$HS/tests"
"$PY" -B -m unittest test_h1a_r3 test_h1_r3 test_l1_low_ledger_op
cd "$HS"
for L in ld3 le3 lf3; do
  [ -e "$HS/$L" ] && { echo "$L already exists; refusing to overwrite"; exit 2; }
  "$PY" -B "$C/step7_same_call_heat_control.py" --prepare "$HS/$L" 1 | tail -n 1
  if diff -r -q "$HS/lw" "$HS/$L" | grep -v control.json; then echo "fresh prepare $L differs from lw"; exit 3; fi
  f="$HS/$L/helpers/private_heat_exact_growth_r1.py"
  "$PY" -B "$HS/transforms/h1a_growth_reserve_r3.py" "$f" "$f.a"
  if [ "$L" = ld3 ]; then mv "$f.a" "$f"; else
    "$PY" -B "$HS/transforms/h1c_growth_inline_r3.py" "$f.a" "$f.c"; mv "$f.c" "$f"; rm "$f.a"; fi
  "$PY" -B "$HS/transforms/h2_fused_dot.py" "$(cygpath -w "$HS/$L/helpers")"
done
"$PY" -B "$HS/transforms/l1_low_ledger_op.py" "$(cygpath -w "$HS/lf3/helpers")"
echo "ld3 vs le3:"; diff -r -q "$HS/ld3/helpers" "$HS/le3/helpers" || true
"$PY" -B "$HS/scripts/l1_generation_note.py" "$(cygpath -w "$HS/le3/helpers")" "$(cygpath -w "$HS/lf3/helpers")" \
  "$(cygpath -w "$HS/evidence/l1-generation-note-r4.md")"
sha256sum "$HS"/l?3/helpers/private_heat_exact_growth_r1.py "$HS"/lf3/helpers/private_heat_low_ledger_inventory_r1.py
rm -rf "$HS/transforms/__pycache__" "$HS/tests/__pycache__"
