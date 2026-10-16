#!/usr/bin/env bash
# t9: test_initpar.py (t8's arguments) on ip9 = gg/final-f2 + initpar_r1 + initpar/r2 module, seed 0, cleaned env.
CK="$(cygpath -m "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)")"
CK="$("$(dirname "$CK")/.r44-env/Scripts/python.exe" -B -I -c "import os,sys; print(os.path.realpath(sys.argv[1]).replace(chr(92), '/'))" "$CK")" || exit 2
T="$(dirname "$CK")"
export PYTHONHASHSEED=0
for v in $(compgen -e | grep '^PYTHON'); do [ "$v" = PYTHONHASHSEED ] || unset "$v"; done
R="$T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1"
H="$T/fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests"
cd "$CK/initpar" || exit 2
exec "$T/.r44-env/Scripts/python.exe" -B test_initpar.py "$CK/initpar/${1:-t9}" "$CK/ip9/src" "$R/composed-r2/helpers" "$H" \
  --supports=17:31 --workers=2 --batch=8 --mutants
