#!/bin/bash
# S1 r4 delta refuter: owner test (base, r4), r4 S1 tests, r3 probes + r4 double-interrupt/dis probes, 24 mutants.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
D=$T/so/refute/s1/delta-r4
export PYTHONHASHSEED=0
summary() { grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:)" | head -20; }
$P -B -c "import sys; print('python', sys.version.split()[0])"
echo "== base owner test"; (cd $T/so/refute/s1/base && $P -B -m unittest test_run_fresh_interval 2>&1 | summary)
echo "== r4 owner test + S1"; (cd $D && $P -B -m unittest test_run_fresh_interval test_s1_query_stages 2>&1 | summary)
echo "== r3 probes on r4"; (cd $D && $P -B -m unittest -v test_delta_r3_probes 2>&1 | grep -E "\.\.\. |DOUBLE|^(Ran|OK|FAILED|FAIL:|ERROR:|AssertionError|Traceback)" | head -40)
echo "== r4 probes"; (cd $D && $P -B -m unittest -v test_delta_r4_probes 2>&1 | grep -vE "^\s*$|^-+$|^=+$" | head -80)
echo "== plant"; (cd $D && rm -rf mutants && $P -B make_mutants_r4.py 2>&1 | tail -2)
for m in $D/mutants/*/; do
  name=$(basename $m)
  out=$(cd $m && $P -B -m unittest test_s1_query_stages 2>&1)
  if echo "$out" | grep -qE "^OK"; then verdict=SURVIVED; else verdict=KILLED; fi
  echo "== $name $verdict :: $(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_s1_query_stages\./ /' | tr '\n' ';' | cut -c1-140)"
done
