#!/bin/bash
# S8 focused tests, base sources then candidate sources; one process per test module
# (test_reopen_prepared_restart asserts the native package was never imported in its process).
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s8
export PYTHONHASHSEED=0
cd $S
for side in base new; do
  mods="test_reopen_fresh_restart test_reopen_prepared_restart"
  [ $side = new ] && mods="$mods test_s8_producer"
  for m in $mods; do
    echo "== $side $m"; $P -B $S/run_tests.py $side $m 2>&1 | grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:|loaded |AssertionError|  File)" | head -20
  done
done
