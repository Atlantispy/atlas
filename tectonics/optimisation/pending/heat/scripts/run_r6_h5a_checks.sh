#!/bin/bash
# 16 Oct (pause-safe, 1 core): check_gate_r6 (harness r6) then H5a unit tests r2. Each to its own log.
T=/c/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
PY=$T/.r44-env/Scripts/python.exe
export PYTHONHASHSEED=0
"$PY" -B $T/hs/scripts/check_gate_r6.py > $T/hs/evidence/check-gate-r6.log 2>&1
echo "check_gate_r6 exit $?" >> $T/hs/evidence/check-gate-r6.log
"$PY" -B $T/hs/tests/test_h5a_prepare_reuse_r2.py > $T/hs/evidence/test-h5a-r2.log 2>&1
echo "test_h5a r2 exit $?" >> $T/hs/evidence/test-h5a-r2.log
