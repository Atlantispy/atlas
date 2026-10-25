# Plan21: lazy carried-start rows (S3) and sealed-mesh identity reuse (S9)

WORKING NON-CANON.

- S3 port-r4 carries the corrected r5 implementation with an explicit exporter-preflight binding and current carried-page fallback controls. Real interval-1 read parity was measured on r4 and carried to the private r5 successor by source analysis; the current combined gate passes; final frozen-generation IV1 parity remains pending.
- S9 is **not selected**: real interval-1 identity passed, but the synthetic timing checks did not demonstrate the required gain. It stays disabled; this gain assessment is closed.
- This source publication does not enable a programme default, admit a runtime or establish scientific acceptance.
- [Issue #47](https://github.com/Atlantispy/atlas/issues/47) remains open.

## S3: lazy rows

`spatial_validation_patch.py` serves an interval's carried start to the native spatial owner through two mappings:
- `_StartRows`, for the plain family;
- `_CarriedRows`, for the differential family, whose children are renamed copies of their start rows.

Each mapping used to export the whole row on every access. In `close_graph` and `transport`, the owner reads only three things: `volume_m3`, `geometry_volume_error_m3` and one `exact` entry.

**What S3 returns.** Each access now gets a per-row lazy mapping:
- **Single fields.** The three reads the owner uses export only the field they name; `exact` is itself a lazy mapping.
- **Admission.** A single field answers only while every row of the mapping passes the whole-row export's own refusals before decode: its logical width, its decoded-object stats walk and the charge it books. This is checked once per bound, with one stats walk a row and no decode. In r5, `_admits` funds the same **262,144 B scratch** as the whole-row exporter. Successful walks release that booking. If a failure propagates, the booking remains held while its traceback can retain the scratch. For a caught `ContractError`, garbage collection runs after the exception handler while the scratch is still funded. If admission refuses, reads use the whole-row export.
- **Budget.** A budget refusal on the single-field path falls back to the whole row. This covers admission scratch, a text or hex scalar's own allocation charge, the key search's scratch and the field's holders. Before the whole row answers, garbage collection runs outside the exception handler. On a sealed segment a failed chunk read keeps its leases in a reference cycle until it is collected, so without the collection the whole row would answer with less budget than the base read gets. The r5 repair keeps this retained scratch funded until it can be released.
- **Whole-row fallback.** Every other access exports the whole row once: `get()`, iteration, `len`, `items`, `values`, membership, any other key, iterating `exact`, an absent field or a non-object `exact`. The export is cached on that row object only.

**What is preserved.** The whole-row logical bound and its refusal text are kept, and so is the decode-error order. A carried child is still the booked `copy_row` copy of its start row, with its key-derived cell identity. Physical quantities and tolerances do not change. A single field answers wherever the whole row answers, with the same value. It may answer where only the whole row's own work refuses: its larger booking, or decoding a field the read does not touch, which the packer refuses to write.

**Members.** The current [SOURCE-MAP-r4.json](SOURCE-MAP-r4.json) replaces two helpers and adds two tests. The additive `build_selection_r4.py` constructor builds **647 members: 240 native files and 407 helpers**, including the stored-segment fallback case. The earlier `build_selection.py`, [SOURCE-MAP.json](SOURCE-MAP.json) and its three historical rows remain unchanged for existing pinned consumers; that route still constructs 646 members. The new rows live in receiving-r4; the final private assembly has its own source/profile/manifest identity.
- The public predecessor differs from the private predecessor by a published comment change; private hashes must not be treated as public hashes. The constructor checks the selected public base entries.
- Every other member is preserved from its selected base, including the native owner, the capacity probe, the heat runtime and the three protected heat identities. Final private assembly remains separate from this public source construction.

### Construct the complete public source layout

Run from the repository root, choosing a new output directory:

```text
python -B tectonics/optimisation/workbench/plan21/build_selection_r4.py --repo . --output NEW_DIRECTORY
```

The constructor authenticates the combined source map, all predecessor members and the four-member overlay before writing. It also checks the private exporter preflight AST so a changed exporter cannot silently reuse the copied admission policy. It refuses changed inputs, unknown or duplicate overlay members, linked paths and occupied outputs. It publishes a new directory atomically with a `SOURCE-MANIFEST.json` containing every file hash, the new selection identity and the base and overlay map identities. The resulting `src` and `helpers` directories must stay together. No selected scientific source is imported; construction grants no runtime, installed-package, default or scientific authority.

**Historical public checkpoint.** The earlier constructor passed **12 standard-library fixture checks**. Its separate materialisation verified **646 files**, producing selection `680348d14707be0273f6930cfd5fcf21acc946f39f6e956c8dac6304c0a8d221`; **19 lazy-row checks** passed against that historical public selection using the compatible science environment and an adapted test-loader path. These are predecessor counts and evidence, not the current receiving result.

### Current public receiving checks

The current public-base materialisation authenticates **647 files: 240 native files and 407 helpers**, with selection `caf669f9c928b4048511cbac5d64daf73c26492959c626d0e4fcbfc661e09107`. The retained private `CHECKS-FINAL.json`, SHA-256 `48388715c2522e91d470346cd3a0428d938906aeabcd3c1b048ebc747468edfc`, binds **20/20 lazy-row checks and 17/17 selected-owner consumer checks**. It records no source-pin bypass, foreign project imports or temporary residue, and unchanged materialised source bytes. These public-base checks do not qualify current L3/S1A, IV, a runtime or final assembly; their execution records are not supplied in this source publication.

### Earlier private r5 checks

The focused r5 selection passes **36/36 checks across two runs**: 19 lazy-row tests, including the new scratch-funding and failure-frame checks, followed by 17 consumer tests. The initial run's two setup failures remain recorded: those fixtures expected an untransformed native owner, while the selected composition already carries that transformation. A reviewed adapter corrected fixture loading without changing the assertions. The 17 consumer tests call the actual selected owner's `_issue`, `_bound`, `restore` and `_carried_start_cells`; the frozen legacy owner supplies only the reference side. This is combined coverage from two runs, not a new single-run 36-test result.

The negative control substituted only r4's `_admits` method in memory. All three new funding tests rejected it as expected: two assertion failures and one error. Ruff reported no findings across four changed files under `F821`, `F841` and `B905`. The separately described interval-1 read-parity carry is source analysis; the historical mutant and fault-injection results remain r4 evidence.

The checked private source identities are `beb695322b5d184a71e537a1a3092090487c731e721d82439c1e57f94f589cab` for `spatial_validation_patch.py` and `69492c3bef071d0769520ddcfa37cfaca2a54d135a3ddc8e4297cf51241adb13` for `test_s3_lazy_rows.py`.

### Historical r4 checks

[RETAINED-RESULTS.json](RETAINED-RESULTS.json) separates the current r5 check from the retained private **r4** evidence below. The retained records are not execution receipts for r5 or its public source layout.

- **Base against candidate.** The 14 helper modules present on both r4 arms gave identical outcome sets. The historical **33/33 count covered three suites combined**, not 33 tests in the new lazy-row module. Earlier candidates failed tests added after them, as intended.
- **Mutants.** The r4 clean control passed; 27 of 28 faulted versions were killed. The remaining mutant, m24, moved the admission walk outside the budget fallback and was classified equivalent for r4. **That equivalence cannot automatically carry through r5's scratch-funding change.** The historical mutants covered:
  - the field list and nested `exact`;
  - `get` and decode-error handling;
  - child identity;
  - the row-local cache;
  - `len`, `items` and membership;
  - `copy_row` booking;
  - the whole-row bound;
  - re-export after a whole row;
  - the admission's logical early exit, booked charge, bound tracking and once-per-bound check;
  - the scalar fallback and the budget fallback (scalar charge, key search and holders);
  - the collection before the fallback, and its placement outside the handler;
  - decode `KeyError`s, which must propagate rather than read as absent.
- **Independent review.** Three r4 refuter rounds found refusal-parity gaps in earlier candidates. The first two involved inputs the native owner cannot produce; the third affected owner-shaped sealed rows. No returned value differed.
  - Round one: single fields skipped the whole-row booked charge, and wide text or hex scalars were refused where the whole row answers.
  - Round two: a single field could need more budget than the whole row. The causes were a wide scalar's charge, a very wide key's search scratch, and holders on minimal rows. A field could also answer where decoding another field refuses.
  - Round three: on sealed segments, the representation spatial records are opened from, a failed chunk read kept its leases until the next collection. The whole-row fallback then had less budget than the base read; owner-shaped rows hit a window of about 570 bytes of retained budget.
  - The r4 reproducers found no remaining case where a field refused and the whole row answered. Historical fault injection at every booking of the field path gave 0 bad results in 3,608 trials. These results have not been rerun on r5 and do not establish its scratch-funding behaviour.
- **Synthetic parity.** On r4, the owner's verbatim `close_graph` and `transport` reads were checked over 40 rows, including:
  - an over-wide row;
  - a non-object `exact`;
  - a missing field;
  - an unencoded value.

  Both families gave byte-identical outcomes. Historical r4 exports per family:

  | | Whole-row exports | Field exports |
  | --- | ---: | ---: |
  | Base | 226 | 0 |
  | S3 | 82 | 144 (71 volume, 34 error, 39 `exact` entries); 2 more answered by the whole row |

  R4 also made 40 admission walks, one per row and no decode. These are historical synthetic counts, not r5 or real-data counts.
- **Lint.** The retained r4 Ruff and Pyright comparison reported no introduced finding. It does not cover the r5 changes.


### Current receiving qualification

The stored-segment case uses current L3 and published S1A: it adopts the same paid carried registry into the admission batch, injects a traceback-held memory failure, and checks that failed workspace is released before whole-row fallback. The settled run and retained ledgers match their durable baseline exactly; absent-field/name and non-object-exact fallbacks have bounded outcome comparisons. Removing collection or fallback is detected. The in-memory interval-1 parity harness remains a separate S3 read-value check and does not exercise L3. Its arm records and comparison bind the harness and interpreter. The retained private combined gate for the current S3 port passed 359/359 checks across 96 unique jobs (result SHA-256 `aefc072290be8865f21297f10c45783eb61acba129286deec5a42170c18fab76`); it is separate from the public-base receiving checks above. Final frozen-generation binding and admitted parity remain outstanding.

A callable/code replacement of the exporter uses the current whole-row route even after cached admission. Transient budget refusals remain uncached; unrelated admission exceptions still surface. These limits and Mapping/get/lazy-exact semantics remain explicit. The new test cleanup releases closed source owners before deleting only its verified temporary directory, including read-only sealed files.

The explicit [B source arms](b/README.md) apply the current L3 and S3 rows to the authenticated complete Plan39/S1A parent before B, retain Plan39 hooks, parse the descriptor once, feed the stored hash in parts, and offer the separately attributable lazy-CASE query. The [A1 overlay](a1/README.md) restores requested bytes/category through the actual diagnostic consumers while retaining reservation accounting and generator-frame contracts. The combined source route adds three tests to the 694-member parent and requires 697 members (287 native files and 410 helpers). Historical Plan21/Plan22/Plan39/S1A builders and maps remain unchanged. Its source constructors and checks do not select the controlled D31r/D31s chain. Selected final source/profile/manifest integration and acceptance remain required; no timing saving is claimed.

### Private storage-chain disposition

The source-bound private interval-1 reopen chain selects repaired S1A and full B1+B2+B3. A1 remains **UNCERTAIN / NOT ENABLED**: one of its two blocks fails the retained selection rule. The second-block slowdown is below that block's range threshold, so this is uncertainty rather than regression. No rerun or rule change follows.

The measurements below use fresh copies, two mirrored blocks, four timed samples per arm, CPU index 3 and quiet EXCLUSIVE conditions. Each reduction uses its immediate predecessor. Evidence is the valid q129 result, SHA-256 `1ced0e22e0fd214ab5189b6ab68efd276d5f07be0ce7ddfea6bc42d98ac34617`.

| Increment | Predecessor mean | Candidate mean | Reduction | Disposition |
| --- | ---: | ---: | ---: | --- |
| S1A | 12.282150 s | 10.095125 s | 2.187025 s / 17.806532% | SELECTED; both blocks pass |
| Full B1+B2+B3 | 10.095125 s | 9.457000 s | 0.638125 s / 6.321120% | SELECTED; both blocks pass |
| Private five-row A1 | 9.457000 s | 9.415725 s | 0.041275 s / 0.436449% | UNCERTAIN / NOT ENABLED; PASS/FAIL |

These are measured private reopen increments on a lineage retaining the preceding S3 source. They are not summable or transferable to this public source layout, final S3/n12f or whole-interval performance. Final private receiving must carry full B and its WP10 helper while omitting the five-row A1 overlay. The separately constructed public 22-row A1 receiver remains an explicit source candidate; readiness does not select it. Actual final S3/source/profile/manifest, folded bindings and IV1 qualification remain outstanding.

### Not yet established

- **Final-generation parity.** The retained real interval-1 comparison passed on r4: the values read by the `close_graph` and `transport` expressions were byte-identical over 847 rows. It did not execute those complete owner functions. Whole-row exports fell from 5,082 to 1,694 per pass (66.7%); both families together made 10,164 versus 3,388 exports. Review accepts carry of those read values to the private r5 successor: r5 funds the admission walk and collects unreachable failure frames after a refused walk; the downstream read logic is unchanged. This replaces the earlier requirement for a new request only for that bounded read-parity claim. It is not an r5 rerun, an admission-rate measurement or qualification of the public selection. The final combined generation still needs its own dependency checks and interval-1 parity run.
- **Gain is PROJECTED.** The retained interval-1 profile suggested roughly 1.27 → 0.82 ms per row per `close_graph` + `transport` pair, about 4–6 s at interval 2, less the admission walk's unmeasured cost. This historical projection does not measure r5's funding change or the integrated route.
- **Diagnostic meaning.** The capacity probe samples before each single-field read, and that read releases its export inside the read. Its `peak_retained_delta_bytes` therefore now equals the index size and records no export peak. It is a diagnostic; no scientific value or acceptance limit reads it.

## S9: not selected

`private_heat_indexed_runtime.metric_identity` streams an unscoped compact mesh in full again on every call. The candidate reuses the identity that the mesh's constructor streamed and sealed in the same process.

**Conditions for reuse.** The candidate reuses the seal only when all of these hold:
- the arrays are still one funded read-only allocation;
- there is no segment;
- the reader is a plain blob reader;
- any file source is unchanged;
- the seal names this geometry.

**What is kept.** Every support-blob read with its type, length and SHA-256 refusal, and every cancellation check. Only the row re-encoding is skipped.

**Status.**
- **Controls.** Its unit tests pass on the selected base. The four-arm measurement checker has two clean controls and 24 known faults; the separate launcher limitations below remain.
- **Coverage gap.** Two owner test modules could not run on either arm: one fixture predates the current heat issuer, and one import closure lacks a lazily imported helper. Their repairs belong to final assembly and are a condition of any later selection.
- **Real-data identity.** The interval-1 mesh comparison passed: all 2,024 support reads retained their order and digest, one repeated row stream was removed, and the injected corrupt support blob produced the same refusal. This establishes identity for that tested mesh.
- **Synthetic timing.** Two valid, predeclared comparisons did not meet the gain rule. The decisive repeat saved 2.6807521 s on average (2.4032896%), against a base-arm spread of 6.9315675 s. The rule required every candidate sample to beat every base sample, a mean saving at least twice the largest within-arm spread, and at least 0.5% saving. The first two conditions failed; the third passed. These are synthetic component timings, separate from the real-data identity result. S9 stays disabled, the gain assessment is closed, and no further repeat is selected.
- **Harness limits.** Recorded resource peaks remained within the bookings, but the supervisor enforced a 12 GiB tree cap rather than the smaller booking. The known launcher-control and import-coverage gaps are not closed by these results; repair them before any future reuse or enablement.

## Limits

No real interval data, profile, checkpoint, capture, execution receipt or measurement log is supplied. The scientific test sources are owner-layout tests: their fixtures resolve the selected private layout, and they are not portable passing public tests. The source constructor has separate standard-library fixtures. No complete public runtime suite or real-interval run was performed for this export.

S3 r5 repairs admission scratch funding; its current focused result and the historical r4 evidence are scoped above. S9 stays disabled, issue #47 stays open, and final private assembly remains separate. No new scientific research, full interval, Windows acceptance or default enablement is claimed.

The combined current-L3/S3/B3/A1 source route is checked separately at 697 members. Its final LF receiver passes 20 lazy-row, 17 selected-owner consumer and two stored-fallback checks; [B receiving evidence](b/EVIDENCE.json) records the exact manifests. These results do not replace final selected-generation IV1 parity.
