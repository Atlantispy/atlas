#!/bin/bash
# S1 focused tests: the relocated owner test on base then candidate RFI, then the S1 tests (candidate only).
# One process per module; each test folder's own run_fresh_interval.py is first on sys.path.
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s1
export PYTHONHASHSEED=0
for run in "base test_run_fresh_interval" "new test_run_fresh_interval" "new test_s1_query_stages"; do
  set -- $run; dir=$S; [ $1 = base ] && dir=$S/base
  echo "== $1 $2"; (cd $dir && $P -B -m unittest $2 2>&1 | grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:|[A-Za-z]*Error)" | head -30)
done
