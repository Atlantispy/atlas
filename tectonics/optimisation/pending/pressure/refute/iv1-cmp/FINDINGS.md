# Refuter findings: iv1/dump_arm.py 7732c38c, iv1/compare_arms.py 29a8459b (16 Oct 2026, 18:45-19:00)

The refuter wrote the reproducers and logs here. The parent chat saved this file from the refuter's report, because
sub-agents cannot write .md files. Reproducers ran in the small lane: exit 0, peak RSS 0.08 GiB.
- Logs: repro_cmp.log and repro_cmp2.log.
- Verdicts: cases/<case>/verdict.json and cases2/<case>/verdict.json.
- cases/summary.json pins the compare_arms sha.

- BROKEN 1. Any 64-hex value change is accepted as an expected identity change.
  - A face re-pointed to another existing, unchanged cell PASSes (A1).
  - A face's two owners swapped PASSes (A3), though the orientation flips.
  - A different input identity PASSes (A2, mesh.source.material_id).
  - Cause: learn() records only before->after pairs whose value changed. It flags a conflict only when one before maps
    to two afters. Unchanged ids never enter the map, and a permutation is consistent, so nothing conflicts.
  - Repro: repro_cmp.py A1, A2; repro_cmp2.py A3. All run on the real i0 mesh: identity_changes 1/1/2, structure 0.
- BROKEN 2. The RADIUS regex `error|deviation|radius|tolerance|uncertainty` matches the geometric `radius_m` (and would
  match `reference_radius_m`).
  - radial_layer depths are judged against the layer radius, and radius_m gets the lax 2**-11 radius-field limit.
  - bottom_depth_m 3 -> 3.00375 (ratio 3.75e-4) and radius_m +2.4e-4 relative both PASS.
  - Repro: repro_cmp.py B, on the real mesh (331 differential_supports carry radial_layer).
  - Caveat: a real geometric change would likely also move cell volumes and REVIEW there.
- BROKEN 3. field() sets 'kind' only on the first leaf.
  - After a float change makes the field 'binary64', judge_fields skips the relative check for later int or rational
    changes (`unassociated_changes and kind != 'binary64'`).
  - int 7 -> 9 and rational 1/3 -> 2/3 PASS.
  - Repro: repro_cmp.py D, D2 (synthetic).
  - scan_real.json finds no mixed-kind field in i0; i1 is unknown. The >20k overflow bucket mixes kinds by construction.
- BROKEN 4. The i1 dump 'partition' entry (identity, nbytes) is never read, so arms with different partitions PASS.
  Repro: repro_cmp.py E.
- BROKEN 5. HEX64_ANY matches the 64 digits inside a standalone exact integer "0x<64 hex>" (width_gate rows carry these).
  It is treated as an identity: a 50% growth PASSes with identity_changes 1.
  Repro: repro_cmp.py F (synthetic; no such field in i0).
- BROKEN 6. Nothing checks that the arms differ: the same attempt, dumps and profile given as --before and --after
  PASS. Repro: repro_cmp.py G.
- RISK 7. geometry_volume_max_deviation_m3 262.25 -> 275.37 (+5%) is judged against max_geometry_volume_error_m3
  (32000) as its radius, ratio 4.1e-4: PASS. A growing certified bound reads as noise.
  Repro: repro_cmp.py C, on the real mesh. Per-cell volumes would normally move too.
- RISK 8. Deterministic, workload-caused after-arm stops class as environment, giving VOID rather than FAIL.
  - Covered stops: rss_limit, live_descendants_at_exit, a native crash, or a check_imported/verify/guard.check raise in
    run_fresh_interval's finally before guard.close (which becomes parent_exited_without_guard_close).
  - Repro: repro_cmp2.py V1 (VOID, exit 4).
  - Conversely, MemoryError or CANTOPEN inside the runner seals as refusal, giving FAIL.
- RISK 9. compare trusts dump.json's declarations.
  - What it checks: the binding shas against the stage steps, and the bytes against dump.json.
  - What it does not do: re-derive record identities or the profile from reader-<stage>/reopen.json, or pin
    dump_arm.py's sha.
  - So a hand-edited or wrong-version dump.json with copied binding shas would PASS.
  - dump_arm's arrays come from the head manifest and are not bound to the reader proof.
- RISK 10. dump_arm does not use FreshSources.selected()'s pinned-bytes Loader.
  - It prepends the roots to sys.path. loaded_audit checks pins only: no data_only check and no first-resolution check.
    .r44-env, non-.py files and dump_arm itself are exempt.
  - It checks -B, the hash seed and isolation, but not -s/-P.
  - Records stay sha-bound to the reader proof; derived arrays and widths are exposed.
- RISK 11. Arrays pair positionally with no tie to the state.cells ids.
  - A reordered state.cells PASSes (repro_cmp2.py A4; 539 cells, 539-row exterior-fv arrays).
  - Real cells are sorted by cell_id, so this needs a reordering cell-id change, which usually gives a spurious REVIEW.
  - Float arrays are judged by ulps only (512), with no relative or radius alternative.
- NOTE 12. The equality shortcut and int/float coercion hide True -> 1, 7 -> 7.0 and 0.0 -> -0.0 (all PASS;
  repro_cmp.py J), so schema or encoding drift goes unreported.
- NOTE 13. An array max_abs that overflows to inf makes json.dump(allow_nan=False) raise outside the try, leaving a
  partial verdict.json and exit 1 (repro_cmp.py K). This is fail-closed only if callers check the exit code, not the
  file's existence.
- NOTE 14. The width gate holds: an after-arm GATE_STOP, or a False or None gate, gives FAIL.
  - The bindings suffice against accidental mix-ups, not against a forged dump.json. They are the adopted, verdict and
    receipt shas, receipt parent == attempt, interval, and profile.
- NOTE 15. Lax by design: the vector-scale radius, and the 'bounds' radius taken from the before arm's half-width only.
- NOTE 16. dump_arm needs head_entry.interval == interval, so i0 must be dumped before interval 1 is adopted.
- NOTE 17. Expect REVIEW on real IV1 data: the i0 mesh has 'basal:<hex>' keys and 396 weak positional pairings
  (scan_real.json).
