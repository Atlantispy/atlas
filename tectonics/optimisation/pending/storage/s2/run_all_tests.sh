#!/bin/bash
# S2 focused tests: base sources then candidate sources (same harness).
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s2
export PYTHONHASHSEED=0
cd $S
echo "== base"; $P -B $S/run_tests.py base test_step8_coverage test_ledger_fresh_interval 2>&1 | tail -15
echo "== new";  $P -B $S/run_tests.py new test_step8_coverage test_ledger_fresh_interval test_wp16_preadvance 2>&1 | tail -40
