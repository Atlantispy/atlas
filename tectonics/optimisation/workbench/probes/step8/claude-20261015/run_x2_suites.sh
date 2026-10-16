#!/usr/bin/env bash
# Regression batch for X2 (verified-identity seals) and D4(i) (compact cells comparison), 16 Oct 2026:
# one module per process, PYTHONHASHSEED=0, then the same-call heat re-proof (live_transport_result is
# heat-captured) on fresh layouts g11l0/g11l1. Output: tests-x2.log and g11-*.json beside this script.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
C="$R/compact-geometry-r1"
PY="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe"
LOG="$HERE/tests-x2.log"
export PYTHONHASHSEED=0
: > "$LOG"
for module in test_spatial_indexed_patch test_live_transport_result test_compare_spatial_cells \
              test_private_heat_indexed_runtime test_spatial_compact_cells test_live_spatial \
              test_spatial_records_patch test_spatial_record_recipes test_pressure_indexed_patch \
              test_partition_routing_runtime test_partition_workflow_patch test_heat_cold_patch \
              test_heat_ledger_issuer_patch test_live_composite test_spatial_validation_patch \
              test_live_mesh_published test_bounded_preseal test_wp6_streamed_validation; do
  echo "=== $module" >> "$LOG"
  (cd "$C" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
for module in test_step8_reader test_step8_materialise test_run_prepared_restart test_reopen_prepared_restart \
              test_original_joined_r7 test_width_gate; do
  echo "=== R $module" >> "$LOG"
  (cd "$R" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
for live in 0 1; do
  layout="$R/probes/step8/g11l$live"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --prepare "$layout" "$live" > "$HERE/g11-prepare-$live.log" 2>&1)
  echo "=== g11 prepare $live exit $?" >> "$LOG"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --child "$layout" "$HERE/g11-same-call-live$live.json" > "$HERE/g11-child-$live.log" 2>&1)
  echo "=== g11 child $live exit $?" >> "$LOG"
done
echo "=== done" >> "$LOG"
