#!/usr/bin/env bash
# By-need start gate: test_start_gate, then the planted mutants (start_gate_mutants.py). Seed 0 (coordinator
# rule): no -I, a cleaned environment with PYTHONHASHSEED=0, and the fail-closed seed check first.
# Output beside this script: start-gate-tests.log and start-gate-mutants.log.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
T="$(cd "$R/../../../.." && pwd)"
PY="$T/.r44-env/Scripts/python.exe"
for name in $(env | sed -n 's/^\([Pp][Yy][Tt][Hh][Oo][Nn][^=]*\)=.*/\1/p'); do
  [ "$name" = PYTHONDONTWRITEBYTECODE ] || unset "$name"
done
export PYTHONHASHSEED=0
"$PY" -B "$HERE/seed_zero_check.py" || exit 3
(cd "$R" && "$PY" -B -m unittest -v test_start_gate) > "$HERE/start-gate-tests.log" 2>&1
status=$?; echo "start gate tests exit $status"; tail -4 "$HERE/start-gate-tests.log"
"$PY" -B "$HERE/start_gate_mutants.py" > "$HERE/start-gate-mutants.log" 2>&1
mutants=$?; echo "start gate mutants exit $mutants"; cat "$HERE/start-gate-mutants.log"
[ $status -eq 0 ] && [ $mutants -eq 0 ]
