#!/usr/bin/env bash
# Post-merge batch for the R1 generation (record_tables + record_views + R1-batch storage), 16 Oct 2026:
# one module per process, PYTHONHASHSEED=0; then the same-call heat re-proof on fresh layouts g13l0/g13l1
# (record_tables, record_views and interval_store_set are heat-captured). Output: tests-r1gen.log and
# g13-*.json beside this script. test_r1_views runs without its two long sealed tests (storage ran
# sealed_fuzz 530 s and sealed_shapes 97 s on these exact bytes).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
R="$(cd "$HERE/../../.." && pwd)"
C="$R/compact-geometry-r1"
PY="C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/.r44-env/Scripts/python.exe"
LOG="$HERE/tests-r1gen.log"
export PYTHONHASHSEED=0 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
: > "$LOG"
run() {  # DIR MODULE-OR-TESTS...
  local dir="$1"; shift
  echo "=== $(basename "$dir") $*" >> "$LOG"
  local started=$(date +%s)
  (cd "$dir" && "$PY" -B -m unittest "$@" >> "$LOG" 2>&1)
  echo "exit $? ($(( $(date +%s)-started )) s)" >> "$LOG"
}
# Storage's 29 merged-tree suites.
for module in test_s1_sealed_read test_interval_store_set test_step9a_pending test_g8_chunk_binding \
              test_interval_quarantine test_segment_store test_step7b_segments test_wp10_integration \
              test_storage_codec_followups test_storage_codec_patch test_native_codec_integration \
              test_record_views test_record_dedup_tables test_record_tables test_record_builder_honest \
              test_capacity_failure_chain test_step7b_record_reuse test_xmc_cert_export test_spatial_records_patch \
              test_spatial_validation_patch test_compact_store test_heat_ledger_issuer_patch \
              test_private_heat_snapshot_store_r4 test_live_mesh_published test_d1b_carried_start test_partition_v2 \
              test_mesh_v3 test_spatial_record_recipes test_w3_validate_stream_once; do
  run "$C" "$module"
done
# Other record consumers and this chat's recent files.
for module in test_r1a_export_booking test_capacity_state_cleanup test_capacity_preseal_timing test_live_state_cells \
              test_record_composition test_streaming_rows test_live_composite test_heat_ledger_tables \
              test_spatial_compact_cells test_mesh_tables test_live_mesh test_bounded_preseal test_publish_mesh_patch \
              test_heat_token_transform test_content_cache test_live_spatial test_wp6_streamed_validation; do
  run "$C" "$module"
done
run "$C" test_r1_views.R1ViewsTests.test_memory_shapes test_r1_views.R1ViewsTests.test_memory_fuzz \
    test_r1_views.R1ViewsTests.test_composites_and_api_reads \
    test_r1_views.R1ViewsTests.test_mutated_payloads_same_accept_or_refuse \
    test_r1_views.R1ViewsTests.test_large_route_refusals_are_the_same \
    test_r1_views.R1ViewsTests.test_sealed_freshness_and_cancellation_refusals \
    test_r1_views.R1ViewsTests.test_record_check_runs_once_per_rendered_node
for module in test_step8_store test_root_metadata_refs test_run_prepared_restart test_reopen_prepared_restart \
              test_step8_reader test_step8_materialise test_seal_pending test_run_fresh_interval \
              test_reopen_fresh_restart test_launch_fresh_interval test_fresh_interval_driver test_width_gate \
              test_original_joined_r8 test_interface_worker_selection test_ledger_fresh_interval; do
  run "$R" "$module"
done
for live in 0 1; do
  layout="$R/probes/step8/g13l$live"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --prepare "$layout" "$live" > "$HERE/g13-prepare-$live.log" 2>&1)
  echo "=== g13 prepare $live exit $?" >> "$LOG"
  (cd "$C" && "$PY" -B step7_same_call_heat_control.py --child "$layout" "$HERE/g13-same-call-live$live.json" > "$HERE/g13-child-$live.log" 2>&1)
  echo "=== g13 child $live exit $?" >> "$LOG"
done
echo "=== done" >> "$LOG"
