#!/usr/bin/env bash
# Prepare layout T/hs/lf = fresh step7 prepare + H1a + H1c + H2 + L1 (run via runq.py small).
# Checks: the fresh prepare equals lw apart from control.json; after H1a/H1c/H2 it equals le's helpers;
# after L1 only low_ledger and its 5 pinners differ from le.
set -e
T="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10"
PY="$T/.r44-env/Scripts/python.exe"
HS="$T/hs"
C="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/compact-geometry-r1"
export PYTHONHASHSEED=0
L="$HS/lf"
[ -e "$L" ] && { echo "lf already exists; refusing to overwrite"; exit 2; }
cd "$HS"
"$PY" -B "$C/step7_same_call_heat_control.py" --prepare "$L" 1 | tail -n 1
if diff -r -q "$HS/lw" "$L" | grep -v control.json; then echo "fresh prepare differs from lw"; exit 3; fi
f="$L/helpers/private_heat_exact_growth_r1.py"
"$PY" -B "$HS/transforms/h1_growth_reserve.py" "$f" "$f.a"
"$PY" -B "$HS/transforms/h1c_growth_inline.py" "$f.a" "$f.c"
mv "$f.c" "$f"; rm "$f.a"
"$PY" -B "$HS/transforms/h2_fused_dot.py" "$(cygpath -w "$L/helpers")"
diff -r -q "$HS/le/helpers" "$L/helpers" && echo "lf matches le before L1"
"$PY" -B "$HS/transforms/l1_low_ledger_op.py" "$(cygpath -w "$L/helpers")"
diff -r -q "$HS/le/helpers" "$L/helpers" || true
rm -rf "$HS/transforms/__pycache__"
