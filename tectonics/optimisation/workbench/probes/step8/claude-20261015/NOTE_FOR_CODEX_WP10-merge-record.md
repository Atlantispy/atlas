# WP10 merge record (addendum to the fix chat's NOTE_FOR_CODEX_WP10.md)

From the Steps 8-9 Claude chat (the single writer in compact-geometry-r1), 16 Oct 2026, 04:18 BST. This records what was actually merged into your files, and how. The change descriptions are in `claude-review-steps1-7-20261015/fixes/handoff-wave2-storage/NOTE_FOR_CODEX_WP10.md`.

## Authority and conditions

Michael approved the merge in the Step 8 chat ("I approve merging"). The Atlas coordinator ruled that the approval covers the revised bundle. Michael's four conditions were applied as follows:

1. **Live equalled origin before copying.** Checked for every file by `apply_wave2.py`. Any mismatch refuses before the first write.
2. **Bundle tests and the existing storage tests run on the merged tree.** Results are in `tests-wave2.log`, one module per process.
3. **File, origin hash, new hash and tests recorded.** See the table below, `apply-wave2.json`, and decision-05 at 04:18.
4. **codec_*, cold_archive* and native/* untouched.** None of them is in the package.

## Your files as merged (sha256, first 8 hex)

| File | Before (= origin) | After |
|---|---|---|
| segment_store.py | db0aa9ab | 93af04cf |
| interval_store_set.py | aefb2925 | f0070d26 |
| interval_catalog.py | 5f0f7bd4 | 51a5010e |
| compact_interfaces.pyi | d341e02a | e179bcb9 |
| test_segment_store.py | a1074361 | 2a15702b |
| test_interval_store_set.py | e756f6f4 | a9e89b3a |
| test_compact_contracts.py | 6a6f2182 | 4f41e989 |
| test_interval_quarantine.py | (new) | 9b3eff40 |
| test_w1_segment_fixes.py | (new) | c6927a04 |

All files were copied byte for byte from the package. No 3-way merge was needed in any WP10 file.

Before copies: `R/probes/step8/claude-20261015/before-src/<name>.before-wave2`.

## Related merges in the same captured generation (not your files)

- spatial_validation_patch, heat_ledger_tables, mesh_tables, partition_v2, spatial_records_patch.
- The runner's `compact_restart_store.py`, which also gained:
  - the opt-in `resume_after_failure=` hook from this bundle;
  - route (1)'s v2 root-metadata references;
  - a success-only close in `_segment`.

The heat issuer captures segment_store, interval_store_set and interval_catalog. The same-call heat re-proof for this generation is recorded in decision-05 once it finishes.

## Second merge: 16 Oct 2026, 06:58-07:24 BST

Same authority: Michael's "I approve merging", applied by the coordinator to the storage generation, the bounded_preseal hotfix and the re-pin. The change descriptions are in `claude-review-steps1-7-20261015/fixes/storage-gen/NOTE_FOR_CODEX_WP10.md` and `fixes/wp10-followups/NOTE_FOR_CODEX_WP10.md`.

1. **Live equalled origin before copying.** `apply_gen1.py` (06:58) and `apply_files.py` (07:19, 07:24) check every file and refuse before the first write. The four r1a-export-booking rows in `apply-gen1.json` were already live (live = new) and were not rewritten.
2. **Tests on the merged tree**, one module per process: `tests-gen1.log`, `tests-gen1-pythonpath.log` and `tests-repin.log`.
3. **Records:** `apply-gen1.json`, `merge-bpfix.json`, `merge-repin.json` and decision-05.
4. **codec_*, cold_archive* and native/* untouched.** None of them is in these packages.

### Your files as merged (sha256, first 8 hex)

| File | Before (= origin) | After | Package |
|---|---|---|---|
| segment_store.py | 93af04cf | 1f503604 | storage-gen |
| interval_store_set.py | f0070d26 | 8888fcaa | storage-gen |
| compact_interfaces.pyi | e179bcb9 | ad5aa229 | storage-gen |
| test_s1_sealed_read.py | (new) | f8f79705 | storage-gen |
| test_g8_chunk_binding.py | (new) | ea0bee32 | storage-gen |
| test_step9a_pending.py | (new) | d8795063 | storage-gen |
| storage_codec_runtime.py | 45292cc8 | 8c1a15f0 | wp10-followups rev2 |
| storage_codec_integration_patch.py | 1b5cb27c | 8440be33, then 13e5ac91 (re-pin, 07:24) | wp10-followups rev2, bpfix/repin |
| test_storage_codec_patch.py | 531e542d | 5529eb9c | wp10-followups rev2 |
| test_wp10_integration.py | 71f3a80c | dcdcd4c3 | wp10-followups rev2 |
| test_native_codec_integration.py | 3bea5357 | c07b5c2b | wp10-followups rev2 |
| test_codec_measure.py | f0d9d644 | 45014434 | wp10-followups rev2 |
| test_storage_codec_followups.py | (new) | dd253353, then 4c78d3f0 (re-pin, 07:24) | wp10-followups rev2, bpfix/repin |

Every file was copied byte for byte. No 3-way merge was needed.

Before copies are in `before-src/`.

### Test results on the merged tree

- **storage-gen suites:** pass.
  - test_g8_chunk_binding 6, test_step9a_pending 22, test_segment_store 13, test_step7b_segments 7, test_w1_segment_fixes 7, test_interval_quarantine 18, test_compact_contracts 21, test_raw_sidecar_store 29 (1 skip).
  - test_s1_sealed_read, test_interval_store_set and test_content_cache import atlas_tectonics. With PYTHONPATH set to runtime-src they pass 24 (1 skip), 34 and 29.
- **WP10 follow-ups:** test_storage_codec_followups failed one test at 06:58, because it pinned interval_store_set at aefb2925, before wave 2. After the 07:24 re-pin it passes 16/16.
  - test_storage_codec_patch passes 27 (6 skips), test_codec_measure 20 and test_codec_training 8. test_native_codec_integration skips all 4.
  - test_wp10_integration (6) and test_codec_dictionaries (7) fail under the default temporary root, because those paths exceed the Windows 260-character limit. With `WP10_TEST_ROOT=R/L/w10` both pass.
- **bounded_preseal (not your file):** it refused every interval against the merged G8 helpers (13 failures and 4 errors). Storage's hotfix (fixes/bpfix, 07:19) changed bounded_preseal.py cf734749 -> a7691876 and test_bounded_preseal.py 34fe7719 -> 7221c402. It then passes 29/29.
- **Same-call heat re-proof g12:** needed because segment_store and interval_store_set are heat-captured. It passed both arms (`g12-same-call-live0.json`, `g12-same-call-live1.json`).
  - Compact call: 33.5 s and 30.4 s.
  - Whole check: 95.0 s and 86.0 s.
  - Peak working set: 272 MB.
