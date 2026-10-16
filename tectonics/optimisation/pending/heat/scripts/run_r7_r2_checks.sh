#!/bin/bash
# 16 Oct (pause-safe, 1 core): check_gate_r7 r2 (harness r7: fallback records raise only, pre-flight, overflow, layout).
T=/c/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
PY=$T/.r44-env/Scripts/python.exe
export PYTHONHASHSEED=0
"$PY" -B $T/hs/scripts/check_gate_r7_r2.py > $T/hs/evidence/check-gate-r7-r2.log 2>&1
echo "check_gate_r7_r2 exit $?" >> $T/hs/evidence/check-gate-r7-r2.log
