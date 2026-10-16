#!/bin/bash
# S1 r3 delta refuter: owner test (base, r3), r3 S1 tests, interrupt probes, 22 mutants.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
D=$T/so/refute/s1/delta-r3
export PYTHONHASHSEED=0
summary() { grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:)" | head -20; }
$P -B -c "import sys; print('python', sys.version.split()[0])"
echo "== base owner test"; (cd $T/so/refute/s1/base && $P -B -m unittest test_run_fresh_interval 2>&1 | summary)
echo "== r3 owner test + S1"; (cd $D && $P -B -m unittest test_run_fresh_interval test_s1_query_stages 2>&1 | summary)
echo "== r3 interrupt probes"; (cd $D && $P -B -m unittest -v test_delta_r3_probes 2>&1 | grep -E "\.\.\. |DOUBLE|^(Ran|OK|FAILED|FAIL:|ERROR:|AssertionError|Traceback)|Error" | head -60)
echo "== plant"; (cd $D && rm -rf mutants && $P -B make_mutants_r3.py 2>&1 | tail -2)
for m in $D/mutants/*/; do
  name=$(basename $m)
  out=$(cd $m && $P -B -m unittest test_s1_query_stages 2>&1)
  if echo "$out" | grep -qE "^OK"; then verdict=SURVIVED; else verdict=KILLED; fi
  echo "== $name $verdict :: $(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_s1_query_stages\./ /' | tr '\n' ';' | cut -c1-160)"
done
