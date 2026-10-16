#!/bin/bash
# S9 focused tests, base runtime then candidate runtime; one fresh process per module
# (the owner's heat tests refuse a process that already imported atlas_tectonics).
T=C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10
P=$T/.r44-env/Scripts/python.exe
S=$T/so/s9
export PYTHONHASHSEED=0
cd $S
for side in base new; do
  for m in test_private_heat_indexed_runtime test_differential_mesh_v3 test_ram_context_indexed_patch test_s9_seal_reuse; do
    echo "== $side $m"; $P -B $S/run_tests.py $side $m 2>&1 | grep -E "^(Ran |OK|FAILED|FAIL:|ERROR:|loaded |[A-Za-z]*Error|  File)" | head -24
  done
done
