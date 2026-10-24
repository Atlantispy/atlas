# Part-implemented work (initial snapshot 16 Oct; reconciled 22 Oct 2026)

Status: WORKING NON-CANON. Work stopped at a weekly usage limit. Each entry gives the state, where the files are in
this snapshot, what is left and the acceptance gate. Paths are relative to `tectonics/optimisation/`. "Built" means
implemented and focused-tested, with its proof run still pending. Proof runs need the private inputs and pinned
identities, which are not in this snapshot.

Rules that apply to every item below:
- Exactness first. Each change keeps physical results bit-identical, or changes only listed identity fields under
  field parity. No tolerance is relaxed. No in-run guard is raised: 12 GiB RSS, 1 GiB free floor, 16 GiB logical,
  256 MiB caps, the 1 MiB integer limit and the 256 accepted-step ceiling.
- Every process that imports the runtime pins `PYTHONHASHSEED=0` and fails closed unless
  `sys.flags.hash_randomization == 0`. Do not run it under `python -I`, which ignores the variable. Production
  parallel scheduling depends on seed 0. `-I` is only for helpers that never import the runtime.
- New revisions are new files. Earlier revisions and old run records are never edited.
- A harness or comparison tool gets an independent refutation pass, with planted failures, before its proof run.

## Release policy

- **State:** [Plan39's complete source selection](workbench/plan39/README.md)
  integrates publication checks, process-lifetime holds and worker acceptance.
  Review repaired the close-race and closure-checker defects. Release remains
  non-default; #67 stays open.
- **Remaining:** E2 functional-dependency promotion and runner entry/sizing
  wiring; folded helper pins; desktop closure/manifest integration; source-bound
  resolution of ten computed imports; authentic strict peaks and real packaged
  parity. Five fixture imports also prevent closure. No held run is authorised.

## Start gate sized by need

- **State:** Route1 and Route2 callers, runner and adjacent launcher are installed
  together in the private workspace. The subsequent loader repair admits both
  current producer metadata shapes. Source copies and exact export scope are in
  [workbench/plan02](workbench/plan02/README.md); this public snapshot is not a
  native installation. Retained private checks cover local integration and the
  repair within their declared scopes.
- **Left for Plan02:** corrected positive prepared-state publication and
  independent reopen, then requested end review. Those runs remain deferred.
- **Later integration:** bind the selected generation in the actual replay/final
  assembly at its separate plan stage. That future stage does not block Plan02
  completion. All interval and individual holds remain.
- **Gate:** available memory must cover `P + ceil(P / 5) + 2 GiB` for the selected
  predicted peak `P`; in-run guards are unchanged.

## Interval-N driver (continuation)

- **State:** the interval-N chain and S1 query-stage changes are applied to this branch from `ac/r/chain-r3`, step
  `item21-r3-verdict-pin`: fresh-run, reopen and launch drivers, their three tests, and `test_s1_query_stages.py`.
  Focused private evidence is reused for those exact source bytes; method notes are in `drivers/INTERVAL_CHAIN.md`.
  This is branch code application, not live runtime replacement, a manifest re-pin or scientific acceptance.
- **Left:** finish-driver S1, geometry and S2 capture-writer work are unchanged and remain pending in the ordered
  final composition. The S1 query-stage changes do not complete the separate S1 heat-finish work. All run holds remain.
- **Gate:** a continued interval is bit-identical to one produced by the reference route from the same sealed start.

## Pose and heat-number width

- **State:** the approved pose rounding and Addendum E remain. Plan04's comparator
  r24, dump r5, independent binding/field helpers, launcher and additive assembly
  tools are installed privately; [sources and checks](workbench/plan04/README.md)
  are published separately from private runtime evidence.
- **Left:** actual selected Plan31 replay composition; authenticated producer/
  reader invocation, units, norms, history, projection and same-quantity radius
  correspondence; selected Heat schemas, correspondence and applicable error proof.
  A final manifest alone cannot supply these. Then bind the selected assembly
  route and affected consumers. Collective review is deferred.
- **Gate:** exact unaffected fields, zero refusal flips, approved source-specific
  pose/Addendum E contracts and all independent proof requirements. No generic
  epsilon or assumed Heat allowance. Both technical readiness guards remain false.
  Plan27 scientific replay and fresh full intervals remain held.

## Pressure stage speed

- **State:** P1-P3 have retained small-stage exactness, serial/worker and fallback
  evidence; full-scale/current combined-runtime proof remains separate. P4 is
  implemented and disabled: its retained small-stage comparison rose from
  57.12 to 123.025 s (+115.38%). That predates the later lifetime correction.
- **Arithmetic successor:** [Plan40A](workbench/plan40/pressure/FINDINGS.md)
  covers all ten groups. Its additive [core plus G4 source selection](workbench/plan40/pressure/implementation/README.md)
  removes midpoint derivatives and repeated contributions, powers, vectors and
  partition wedges. The measured core saves 27.35–61.94% on four complete
  synthetic calls; G4 adds a small marginal gain. These are component results,
  with real setup/accounting/fallback costs, not pressure-stage or IV savings.
- **Receiving route:** the [explicit runtime construction and entry](workbench/plan40/pressure/implementation/runtime/README.md)
  binds the selected sources to the existing profile loader and pressure-worker
  interfaces. No earlier profile or default is rewritten.
- **Left:** separately cleared actual-stage/applicability, spawned-worker and
  whole-interval performance/scientific proof on the selected successor.
  Existing frozen selections/defaults remain unchanged; P4/D5 remain off.
- **Gate:** exact pressure records, bounds, ordered rounding, refusal,
  cancellation and funded lifetimes. Dedicated-rerun IV and other holds remain.

## Exact heat kernels

- **H3 (heat certification kernel):** revision 3 accepted (cache names fixed so the identity guard sees the loaded
  implementation); its proof run has not run. Files: `pending/kernels/l3r3/` and `pending/kernels/h3/`.
- **D5 (exact twin and GMP wall measures):** repaired and privately integrated;
  source snapshot in [workbench/plan06](workbench/plan06/README.md). Rebuilt
  exactness/accounting checks passed. Measured kernel regressions justify
  keeping it disabled. Final selected Plan31/N9 binding and collective review
  remain open; the original refuted sources are retained.
- **L4 (interpreter binaries in identity):** approved, not started. It touches the shared runtime record in `reuse`,
  so the change needs review before it starts.
- **G-PY:** the genuine stacked D1/D2/G-PY r4 proof and its three cross-checks
  are qualified PASS. r4 source confirmation and Plan17 integration are complete
  with a source export; the proved bytes were already selected. Final assembly remains separate.

## Parallel start-up (per-world admission)

- **State:** ip9 build (`pending/kernels/initpar/`, transform `pending/kernels/transforms/initpar_r1.py`) passes its
  checks and smoke run; the proof run has not run. ip9 supersedes ip8.
- **Gate:** fails closed unless workers are actually adopted; the store must match the serial run byte for byte.

## Geometry

[Plan19](workbench/plan19/README.md) completes the five-candidate implementation
disposition: shell and alternate-axis changes are accepted and source-integrated;
the other three remain excluded on completed measurements. Its bounded private
native/worker/checkpoint checks passed. The [combined selection](workbench/plans19-20/README.md)
preserves later heat changes. Final runtime assembly, main-package landing and
scientific acceptance remain separate.

Plan17 component integration and source publication are complete. Genuine q23/q24 and all nine
required comparisons are qualified PASS. Operational r7 is source-integrated with
retained r4 dependencies; current selected geometry and later helper changes are
preserved with no native/runtime delta. See [Plan17](workbench/plan17/README.md).
Final programme acceptance and held full intervals remain separate.

- **Done:** Step 10 parity on real intervals 1 and 2. Six stages, no violations, structure identical to the reference
  except 245 charts no longer started. Surface CPU time: interval 1 893 → 454 s, interval 2 885 → 620 s (MEASURED,
  serial shards). D1+D2 transforms 70/70.
- **Plan16:** the sampled IV2 six-worker proof passed with actual session/peak six and exact records/streams.
  The selected-source successor wires authenticated parent measurements through the drivers; five helper changes,
  no native changes. Native-entry preflight is qualified; programme default/interval holds remain.
  See [source and measured limits](workbench/plan16/README.md).
- **Plan18:** endpoint lookahead with plain support-header retention now has an explicit public source selection.
  A detached two-worker endpoint-loop replay measured interval 2 at 451.32 → 274.23 s (1.65×) and
  interval 1 at 111.00 → 96.35 s, with identical ordered records. No whole interval was timed, and
  the earlier 402 → 217 s figure was a projection. Larger-interval retained capacity remains open.
  See [source and measured limits](workbench/plan18/README.md).

## Heat finish and reconstruction speed

- **Plan05 implementation/integration complete privately:** funded retained
  ownership, capture/writer/verifier/launcher, physical-order repair and the
  Plan12 consumer are published at [workbench/plan05](workbench/plan05/README.md).
  q32's full physical correspondence establishes exact input, five-array,
  four-cell-account and paired-face agreement. Metadata differences have bound
  owner dispositions. A later scoped decision accepted the repaired lf3/lh
  comparison; the historical verifier result remains unchanged.
- **Historical evidence:** q10 FAIL remains. q31 reproduced the exact-account
  defect; q32's changed metadata gives NOT REPRODUCED for historical linkage.
  Original failed attempts and reports are retained; none is rewritten as PASS.
- **Plan12/q22:** the successor execution on the same q22 ticket completed
  all 11 arms with PASS on 20 October. The old held route and failed evidence
  remain historical. See [Plan12](plans/plan-12-heat-q22-abba.md) for exact
  scope and decision identities. New combined-profile and full-interval
  validation remain separate, held work; no automatic rerun.
- **Separate finish work:** N6/S1 endpoint certificate reuse and closure-marker
  integration retain Plan14's obligations. Plan15's measured eight-worker candidate is source-integrated; final live adoption remains later.
  The q22 comparison keeps its authentic six-worker configuration.

## Storage

[Plan20](workbench/plan20/README.md) A/B is accepted and source-integrated:
S2 r9 capture-write timing passed and selected consumers were checked against
their base. The remaining work is the actual Release/Plan26 folded DLL binding,
including the module-lookup refusal controls, plus unproved prepared-entry execution.
Existing base failures and the dictionary skip remain explicit; this is not an
all-green consumer suite or a completed packaged route.

- **Merged:** sealed interval-1 heat reopen 46.1 → 15.7 s (MEASURED), in `composed-r2/helpers/segment_store.py`.
- **L3:** reviewed and source-integrated as an optional candidate, with bounded touched-page
  retention, reclaimable entry and record/mesh cleanup. **UNCERTAIN / NOT ENABLED**; the real
  interval-1 A/B comparison and final selection remain pending. Issue #48 stays open. See
  [Plan22](plans/plan-22-storage-l3.md) and [source/checks](workbench/plan22/README.md).
- **WP12:** assessment complete; **UNBUILT/OFF**. Source review establishes one eligible sealed reopen;
  the central estimated net saving is −3.1% against the 5% gate (not a measured failure). The former N = 2,
  +0.1% figure is a sensitivity case. Revisit only after guard-equivalent freshness work under Plan 30; see
  [Plan23](plans/plan-23-storage-mapped-reads-wp12.md).
- **Reopen preservation:** the selected combined source carries the retained B17/item14 files and the
  module-isolation repair in `test_wp10_integration`. The B17, sealed-read and page-layer suites pass on that
  source (14, 30 and 10 tests; one expected Windows skip). Final inclusion after the fold and assembly remains
  outstanding under #57; this is not final-runtime or new performance evidence.
- **Query store:** WP17 remains off. The assessment is done, but representative per-stage counts from the later
  fresh intervals are absent. Prepared-restart counts/selection and batched-route kill evidence remain pending
  under #61; the serial store's twelve-kill result does not cover the batched route.

- **Summaries (043) and buffer pools (032):** assessment complete; neither build gate is
  established and both remain not built. The retained profile does not bound all allocation
  costs or prove zero discard ([Plan 24](plans/plan-24-storage-segment-summaries.md)).

## Small optimisations

- **S2 (capture writers):** revision 9 final for exactness (37/37 mutants killed). Its before/after timing has not run.
  The capture library path must become package-relative, with the native library carried in the package and pinned.
- **S9:** held until its harness smoke and mutants pass.

## Final assembly and landing

The current public source choice is [Plans19–20](workbench/plans19-20/README.md),
an explicit successor of Plan15 with Plan17's geometry retained. Historical
`composed-r2` remains unchanged. This selection does not supply the final runtime,
Release/Plan26 fold or Plan37 main-package landing. The earlier assembly notes
below describe their historical preparation, not completed current delivery.

- **Assembly:** the assembly manifest is accepted as a draft (`pending/storage/assembly-manifest.md`). Order: freeze
  the manifest, assemble with pins, build the frozen final composition, then write the acceptance record.
- **Helper fold:** design accepted (`docs/release/FOLD.md`), with its parity checker. The fold transformer and its
  parity arms are not written.
- **Landing on remake:** the changed test expectations (`docs/release/EXPECTATIONS.md`, groups A-D) are accepted. At
  landing, re-run the expectation check and refuse if any bound is looser, record the new I03 state ID as a successor,
  and state where I04 feedback controls use the cell-mean approximation. Landing waits for the identity generation and
  the helper fold.
