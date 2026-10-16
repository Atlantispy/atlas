#!/usr/bin/env bash
# Regression batch for the mesh publish-and-keep change (16 Oct 2026): one module per process,
# PYTHONHASHSEED=0, sequential. Output: tests-r2mesh.log beside this script.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
C="$R/compact-geometry-r1"
PY="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe"
LOG="$HERE/tests-r2mesh.log"
export PYTHONHASHSEED=0
: > "$LOG"
for module in test_live_mesh_published test_live_mesh test_mesh_tables test_mesh_v3 test_mesh_v3_header_column \
              test_mesh_v3_preparation test_differential_mesh_v3 test_xmc_mesh_shared test_xmb_mesh_booking \
              test_step7b_mesh_stream test_live_spatial test_spatial_records_patch test_spatial_workflow_patch \
              test_spatial_record_recipes test_partition_workflow_patch test_private_heat_snapshot_store_r4 \
              test_heat_ledger_tables test_bounded_preseal test_capacity_failure_chain; do
  echo "=== $module" >> "$LOG"
  (cd "$C" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
for module in test_step8_reader test_step8_materialise test_step8_store test_run_prepared_restart \
              test_reopen_prepared_restart test_root_metadata_refs test_fresh_interval_driver; do
  echo "=== R $module" >> "$LOG"
  (cd "$R" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
echo "=== done" >> "$LOG"
