#!/bin/bash
# S1 refuter: owner test base vs candidate, S1 tests, probes, then the S1 tests against each mutant.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/refute/s1
export PYTHONHASHSEED=0
summary() { grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:)" | head -12; }
echo "== base test_run_fresh_interval"; (cd $S/base && $P -B -m unittest test_run_fresh_interval 2>&1 | summary)
echo "== cand test_run_fresh_interval test_s1_query_stages"; (cd $S/cand && $P -B -m unittest test_run_fresh_interval test_s1_query_stages 2>&1 | summary)
echo "== probe test_refute_probes"; (cd $S/probe && $P -B -m unittest -v test_refute_probes 2>&1 | tail -40)
for m in $S/mutants/*/; do
  name=$(basename $m)
  out=$(cd $m && $P -B -m unittest test_s1_query_stages 2>&1)
  if echo "$out" | grep -qE "^OK"; then verdict=SURVIVED; else verdict=KILLED; fi
  echo "== $name $verdict :: $(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_s1_query_stages\./ /' | tr '\n' ';' | cut -c1-300)"
done
