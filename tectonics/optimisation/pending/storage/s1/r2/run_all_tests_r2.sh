#!/bin/bash
# S1 r2: the relocated owner test on base then r2, the r2 S1 tests, then the S1 tests against each r2 mutant.
# One process per module; each folder's own run_fresh_interval.py is first on sys.path (the loaded line shows it).
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s1
export PYTHONHASHSEED=0
summary() { grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:|[A-Za-z]*Error)" | head -30; }
loaded() { $P -B -c "import sys; sys.path.insert(0, '.'); import test_run_fresh_interval as T; print('loaded', T.F.__file__)" 2>&1 | tail -1; }
for run in "base test_run_fresh_interval" "r2 test_run_fresh_interval" "r2 test_s1_query_stages"; do
  set -- $run; dir=$S/r2; [ $1 = base ] && dir=$S/base
  echo "== $1 $2"; (cd $dir && $P -B -m unittest $2 2>&1 | summary; loaded)
done
for m in $S/r2/mutants/*/; do
  name=$(basename $m)
  out=$(cd $m && $P -B -m unittest test_s1_query_stages 2>&1)
  if echo "$out" | grep -qE "^OK"; then verdict=SURVIVED; else verdict=KILLED; fi
  echo "== $name $verdict :: $(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_s1_query_stages\./ /' | tr '\n' ';' | cut -c1-240)"
done
