#!/usr/bin/env bash
# Post-merge batch for the storage generation (S1 + G8 + 9(a) + WP10 rev2), 16 Oct 2026:
# one module per process, PYTHONHASHSEED=0; then the same-call heat re-proof on fresh layouts
# g12l0/g12l1 (segment_store and interval_store_set are heat-captured). Output: tests-gen1.log
# and g12-*.json beside this script.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
C="$R/compact-geometry-r1"
PY="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe"
LOG="$HERE/tests-gen1.log"
export PYTHONHASHSEED=0
: > "$LOG"
for module in test_s1_sealed_read test_g8_chunk_binding test_step9a_pending test_segment_store \
              test_step7b_segments test_w1_segment_fixes test_interval_store_set test_interval_quarantine \
              test_content_cache test_record_views test_private_heat_snapshot_store_r4 test_heat_cold_patch \
              test_heat_ledger_tables test_compact_contracts test_raw_sidecar_store \
              test_storage_codec_patch test_wp10_integration test_native_codec_integration test_codec_measure \
              test_storage_codec_followups test_codec_dictionaries test_codec_training \
              test_bounded_preseal test_capacity_failure_chain test_r1a_export_booking test_live_mesh_published \
              test_heat_ledger_issuer_patch test_spatial_records_patch test_live_composite \
              test_wp6_streamed_validation; do
  echo "=== $module" >> "$LOG"
  (cd "$C" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
for module in test_restart_orphan_quarantine test_step8_store test_seal_pending test_step8_reader \
              test_step8_materialise test_run_prepared_restart test_reopen_prepared_restart \
              test_run_fresh_interval test_reopen_fresh_restart test_launch_fresh_interval \
              test_fresh_interval_driver test_width_gate; do
  echo "=== R $module" >> "$LOG"
  (cd "$R" && "$PY" -B -m unittest "$module" >> "$LOG" 2>&1)
  echo "exit $?" >> "$LOG"
done
for live in 0 1; do
  layout="$R/probes/step8/g12l$live"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --prepare "$layout" "$live" > "$HERE/g12-prepare-$live.log" 2>&1)
  echo "=== g12 prepare $live exit $?" >> "$LOG"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --child "$layout" "$HERE/g12-same-call-live$live.json" > "$HERE/g12-child-$live.log" 2>&1)
  echo "=== g12 child $live exit $?" >> "$LOG"
done
echo "=== done" >> "$LOG"
