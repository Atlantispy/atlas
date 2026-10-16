#!/bin/bash
# S1 r2 delta refuter: owner test (base, r2), r2 S1 tests, delta probes (r2, and r1 for contrast), 20 mutants, ruff.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
D=$T/so/refute/s1/delta-r2
export PYTHONHASHSEED=0
summary() { grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:)" | head -20; }
echo "== base owner test"; (cd $T/so/refute/s1/base && $P -B -m unittest test_run_fresh_interval 2>&1 | summary)
echo "== r2 owner test + S1"; (cd $D && $P -B -m unittest test_run_fresh_interval test_s1_query_stages 2>&1 | summary)
echo "== r2 delta probes"; (cd $D && $P -B -m unittest -v test_delta_probes 2>&1 | grep -E "\.\.\. |^(Ran|OK|FAILED|FAIL:|ERROR:|AssertionError)" | head -40)
mkdir -p $D/r1probe && cp $D/r1_run_fresh_interval.py $D/r1probe/run_fresh_interval.py && cp $D/test_run_fresh_interval.py $D/test_s1_query_stages.py $D/test_delta_probes.py $D/r1probe/
echo "== r1 delta probes (contrast)"; (cd $D/r1probe && $P -B -m unittest -v test_delta_probes 2>&1 | grep -E "\.\.\. |^(Ran|OK|FAILED|AssertionError)" | head -40)
echo "== plant"; (cd $D && rm -rf mutants && $P -B make_mutants_r2.py 2>&1 | tail -3)
for m in $D/mutants/*/; do
  name=$(basename $m)
  out=$(cd $m && $P -B -m unittest test_s1_query_stages 2>&1)
  if echo "$out" | grep -qE "^OK"; then verdict=SURVIVED; else verdict=KILLED; fi
  echo "== $name $verdict :: $(echo "$out" | grep -E '^(FAIL|ERROR):' | sed 's/ (test_s1_query_stages\./ /' | tr '\n' ';' | cut -c1-200)"
done
echo "== ruff r1 vs r2 (same exe, rules, relative name)"
mkdir -p $D/ruff/r1 $D/ruff/r2 && cp $D/r1_run_fresh_interval.py $D/ruff/r1/run_fresh_interval.py && cp $D/run_fresh_interval.py $D/ruff/r2/run_fresh_interval.py
for v in r1 r2; do (cd $D/ruff/$v && C:/Users/LOCAL_USER/AppData/Local/Microsoft/WinGet/Packages/astral-sh.ruff_Microsoft.Winget.Source_8wekyb3d8bbwe/ruff.exe check --no-cache --isolated --select F,E4,E7,E9,B905 --output-format concise run_fresh_interval.py 2>&1 | tail -4 | sed "s/^/$v: /"); done
