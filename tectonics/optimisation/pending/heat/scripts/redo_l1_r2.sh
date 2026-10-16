#!/usr/bin/env bash
# L1 r2: unit tests, then re-prepare lf from scratch and regenerate the generation note.
set -e
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
export PYTHONHASHSEED=0
cd "$HS/tests"
"$PY" -B -m unittest -v test_l1_low_ledger_op
cd "$HS"
rm -rf "$HS/lf"
bash "$HS/scripts/prep_lf.sh"
"$PY" -B "$HS/scripts/l1_generation_note.py" "$(cygpath -w "$HS/le/helpers")" "$(cygpath -w "$HS/lf/helpers")" "$(cygpath -w "$HS/evidence/l1-generation-note.md")"
grep -c "_inline_resources" "$HS/lf/helpers/private_heat_low_ledger_inventory_r1.py"
