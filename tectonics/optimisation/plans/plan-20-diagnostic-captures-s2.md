# Plan 20 - S2 r9 diagnostic captures: q15, Runner integration and R1 binding

**Item:** 20 / Small S2 / WP16 / backlog 16.  
**Status:** WORKING NON-CANON. S2 r9 is selected and accepted for its recorded exactness scope. q15 timing, Runner integration and the package-relative R1 library binding remain outstanding. Selected does not mean active in the composed runtime.  
**Owners:** Small retains the S2 package and q15 result handoff; Runner integrates the selected changes after freeze clearance; Release owns R1 package binding, with Storage's capture contract preserved.  
**Room authority:** Replacement directed by Gemini in general660, incorporating Claude's clarifications in general663 and Codex's source-grounded review in general657. This edits the workspace plan only.  
**Target completion:** Obtain the separately authorised q15 capture-write result, integrate selected r9 through the Runner's exact source/profile/manifest and consumer checks, and carry its pinned DLL through Release's proved R1 fold. Keep each result's scope and the final-composition dependencies explicit. This plan supplies no launch, freeze-clearance or implementation authority.

## 1. Actual scope and source selection

The compact pre-advance route writes three operands: **mesh, closed graph and bounds**. S2 changes their gzip level 1 containers to `atlas.diagnostic-capture.v1`, using Storage `capture_store.write_capture`, `representation='exact-bytes'`, `codec='zstd'`, `level=3`. It preserves the exact raw bytes and scientific results. This is not arbitrary dictionary/pickle serialisation or a replacement of the solver state format.

The selected revision is **T/so/s2/r9**. `INTEGRATION-r9.md` contains an earlier unresolved r9/r10 choice; the later Small handoff and consolidated status settle it in favour of r9. r10 remains a reference for module-relative semantics and tests. It is not an authorised silent substitution.

Only the three eligible kinds are covered: `mesh`, `closed-graph`, `bounds` (the operand name `closed_graph` maps to the hyphenated kind). Continuation traces, failure/dev-timing and direct-column captures retain their existing formats and disabled dispositions. Their established later combined-build reassessment remains with the relevant plan and owner; this document does not activate them.

### Baseline call sites versus selected r9 changes

Storage's original `R/diagnostic-captures/WIRING_NOTE_STEPS8-9.md`, Call sites A/B/C, provides the authentic design pointers:

| Pointer | Baseline/design meaning | Selected r9 boundary |
| --- | --- | --- |
| `compact_restart_patch.inspect_compact_preadvance` | Stream the compact mesh to gzip-1; check its raw hash against `view.geometry_id`. | CRP `7afe82bf...` still owns this function. It now calls local `capture_operand` for the mesh and `capture_operands` for graph/bounds. |
| `private_heat_original_coverage_r1.save_operands` | Actual gzip-1 writer for existing owned operand bytes; baseline source `90113110...`. The original note also names r1/r2 coverage callers. | This is a valid baseline pointer, not an additional r9 file edit. The selected compact-route change uses CRP-local capture functions. Follow the selected delta, not the older broader wiring sketch. |
| `ledger_fresh_interval.capture` | Read the pre-advance operands and check their receipt identities. | LG `06040fd2...` dispatches to the verified capture reader or bounded legacy-gzip reader, then applies the same raw identity checks. |

`capture_writer_r9.py` is not the selected implementation; `c92368bf` was a handoff revision, not its source pin. The real candidate files and integration anchors are below.

## 2. Exact-byte, reader and resource contracts

The codec-independent logical identity is **`raw_bytes` plus `raw_sha256`**. For the mesh, the raw hash must still equal `geometry_id`. Cross-run and cross-format comparisons use that logical identity. Each capture's `container_sha256` authenticates that file against its own receipt; it must not be compared across codecs or runs as though it were the logical identity.

The receipt generation changes once: captures use `*.capture`, `stored_bytes`, `container_sha256` and `format='atlas.diagnostic-capture.v1'` in place of gzip-specific fields. Receipt bytes and their derived IDs can therefore change even though the scientific bytes do not. Preserve the explicit generation note, old receipts and legacy-gzip readability; do not promise every receipt field is byte-identical.

Selected r9 writes through bounded byte chunks and the pinned backend, with fsync, exclusive publication and atomic rename. Missing or mismatched native support refuses; raw mode is not an ambient fallback. `require_capture_route` executes the capture imports through the selected loader and checks the backend for a compact store before the relevant advance. Module import alone is not route readiness. Other store types are left alone.

The ledger requires composed helpers and runtime source on `sys.path`; missing reader dependencies produce a clean refusal. Before allocating the capture output buffer, selected `captured_bytes` checks receipt types and ceilings, stored size, full container hash and the authenticated footer's raw size. It consumes the bounded reader fully, closes yielded owners, checks completion and raw identity, then parses. Preserve these ordering and lifetime checks.

Retain the documented limitations:

- **CAPTURE_MAX_BYTES is 16 GiB on this route**, for the explicit logical/stored ceilings. This replaces `capture_store`'s 4 GiB defaults for these writers/readers; it does not raise the project's RSS or workspace guards.
- WP16 export/replay/CLI readers still have **4 GiB defaults**. A 4-16 GiB capture can be ledger-readable and refused by those tools. This remains an explicit Storage compatibility issue, not a silent promise of universal readability.
- Accepted legacy reads can need approximately **2x raw_bytes** transiently; the owner note's 182 MiB raw mesh example is about 385 MiB. Retain the accepted many-member per-block cost and stricter malformed-gzip header checks. New capture reads also allocate the validated raw output buffer; a streaming writer does not imply constant whole-reader memory.
- The selected capture route uses 64 KiB chunks. Logical booking figures are not process RSS, and there is no new 150 MiB cap or demonstrated RSS saving.
- The accepted compact-mesh/legacy-store case refuses at capture after advance. Optional extra module-list checks for stop-before-advance smokes remain an owner choice under the integration note; this plan does not silently make them mandatory.

## 3. Runner integration after freeze clearance

The latest Small handoff and Runner wind-down record retain the freeze: **S2 r9 is not applied to the composed runtime; no edits under the held composed-r2/helpers/drivers until the coordinator clears them.** A calendar change alone does not clear it. Runner owns the following work when authorised.

### Selected candidates and driver placements

| Owner file or addition | Selected transition or identity |
| --- | --- |
| `R/compact_restart_patch.py` | `9d076c80...` to `7afe82bf...` |
| `R/ledger_fresh_interval.py` | `cd89718b...` to `06040fd2...` |
| `R/test_step8_coverage.py` | `fcd8cf6a...` to owner-layout `59adb189...` |
| `fresh_interval_driver.advance_first_interval` | Import and call `require_capture_route(store)` immediately after the docstring, before `_seed_pinned()`. |
| `fresh_interval_driver.advance_successor_interval` | The same check before `_seed_pinned()`. |
| `prepared_interval_driver.advance_prepared_interval` | Import and call `require_capture_route(workflow._store)` after the lineage-gate if/else, before derivations. |
| New `capture_store.py` | `4664b205...` |
| New `test_wp16_preadvance.py` | `25e9d8c6...` |
| New `test_s2_route_wiring.py` | `d5f68374...` |

The driver text is `T/so/s2/r9/driver-lines.diff`, `1e2652b8...`, authored against FD `d7bba076...` and prepared driver `6fb4ab6d...`. Those are review anchors, not permission to patch a moved source blindly. Reconcile N12 C19/C20 and the shared driver changes against the owner's selected bytes.

The Runner must:

1. Add `capture_store.py` to composed helpers and the runtime manifest's `files`, and to fixture copy lists and test roots. `storage_zstd_backend.py` is already listed in the integration note's baseline. Preserve selected-runtime source and loaded-code checks.
2. Explicitly repin CRP, LG, owner-layout T8C and both patched drivers. Regenerate the profile: CRP and the prepared driver are in RFI `FRESH_MODULES`, and the advance driver has its own pin.
3. Record the authentic generation: **S2/WP16 capture-digest generation; pre-advance operands as zstd-3 exact-bytes captures with run-start route check; CRP 9d076c80 -> 7afe82bf, LG cd89718b -> 06040fd2, T8C fcd8cf6a -> 59adb189; drivers + require_capture_route at both fresh entries and after the prepared lineage gate; + capture_store 4664b205, test_wp16_preadvance 25e9d8c6, test_s2_route_wiring d5f68374.** Use the actual full output identities for the integrated generation.
4. Supply the ledger's helpers/runtime source path and complete the required owner-layout coverage, affected driver/reader and composition checks. The owner-layout T8C differs from the test-run copy in environment-root layout; run the required owner-layout check after applying. Reuse adequate unchanged evidence; revisit moved seams and affected consumers, not an invented arbitrary-state suite.

Saving the plan, selecting r9 or repinning a manifest is not integration acceptance. Final-composition heat/control and shared-generation obligations remain with their existing owners.

## 4. Retained evidence and its limits

### Exactness and mutation evidence

The source-linked r9 evidence is retained; no tests were rerun for this plan replacement:

| Evidence | Recorded outcome and boundary |
| --- | --- |
| r9 selected tests | Base 8 OK; r9 37 OK. |
| DriverTests controls | FAIL 3 on unpatched owner drivers; OK 3 on patched copies; FAIL 1 on the old r7 successor placement, as expected. These controls do not show the live owner drivers are already wired. |
| r9 mutation evidence | `r9-check/make_mutants_r9.py` with `r9-check/run_all_r9.sh`; log has 37 KILLED rows, each `loaded-from-mutant=4`, and no SURVIVED rows. |
| Earlier writer evidence | The separately retained 9/9 writer result; do not attribute r9's 37 cases to `mutants_s2.py`. |
| Owner driver comparison | Prepared base/r9 17 OK each; fresh base/r9 each ran 28 with the same seven deliberate upstream wiring failures. Preserve these, without calling every suite green or treating them as introduced S2 failures. |
| Review scope | Rounds through r7-to-r8 are closed or booked; the r8-to-r9 wording/test delta was not re-refuted. Preserve that recorded scope and acceptance, without inventing a fresh compulsory review. |

The false test file, 10,000-dictionary suite and live-DLL tamper instruction are removed. Existing guard/mutation evidence is not permission to alter the real binary.

### Measurements, projections and smokes

| Label and source | What is established |
| --- | --- |
| **MEASURED component evidence**, Storage README, 15 October | One matched fresh-process pair per saved input; both formats included flush/fsync/atomic publication. Eligible capture totals were **79,554,528 versus 91,964,804 bytes: 13.5% less**. This sum is not combined-workflow timing. Component read times increased; no process-RAM reduction was demonstrated. Original captures remain. |
| **Earlier Storage-reported measured saving**, wiring note / Small brief / INTEGRATION-r9 | Approximately **1.0-1.26 s** for the eligible capture-write work per interval fixture, accounting for the changed durability work. Preserve its source attribution and component/wiring scope. This is not a q15 result or a measured whole-solver interval gain. |
| **SMOKE**, r9 harness | L 2.28 s / N 1.19 s, disk 91.96 -> 79.55 MB and peak 0.80 GiB. The owner explicitly says these are not timing evidence. |
| **PENDING**, q15 | Selected-r9 comparison of the three writes and receipt rows on the saved IV1 inputs, as specified below. |
| **PROJECTED / not established**, integrated interval benefit | Applying earlier savings to the final integrated interval remains a projection until the appropriate integrated measurement. **q15 alone cannot establish whole-interval performance**, because it excludes the solver and other interval work. |

The replacement does not relabel historical measurements as projections, promote smokes to timings, add overlapping savings or impose a 35% gain hurdle. Small exact gains count; later enablement needs the applicable measured benefit and owner acceptance. There is no supported pickle/uncompressed, 25-second or >10 GiB baseline here.

## 5. q15: pending owner measurement, not execution authority

### Current state

The checked queue row is **queued**, with **2.0 GiB booking, 3-minute estimate, 1 core, quiet=true, timing=true, exclusive=true**, output `T/so/s2/m1`. Booking is not an in-run guard or acceptance ceiling; the estimate is not a timeout.

Current queue top-level `pause` and `hold` are **null**. Separately, Small's handoff and `s2/q15-run.log` record that the waiter exited at **18:46 on the hold**, exit 1; the measurement workload did not run. **Explicit re-release is still required.** Null global fields are not task-specific release authority and do not clear the Runner freeze. `m1` was absent at this replacement; keep it absent before an authorised launch.

The owner's recorded invocation is the cleaned, seed-zero environment:

`env -u PYTHONDONTWRITEBYTECODE PYTHONHASHSEED=0 runq run q15 -- <py> -B -s -P <T>/so/s2/measure_s2_r2.py <T>/so/s2/m1 3`

Here `<py>` is `T/.r44-env/Scripts/python.exe`, `runq` is the existing `T/q/runq.py` route, and paths are resolved to the owner's actual absolute Windows paths. This is a historical/future owner contract, not an instruction to execute it now. No -I/-E on a runtime-importing process; the selected harness refuses unless `sys.flags.hash_randomization == 0`.

The harness is **measure_s2_r2.py, 23728693...** and selects r9. `measure_s2_r3.py`, `009e07a0...`, selects r10 and must not silently replace it.

### What the selected harness measures and checks

- One process receives the same receipt-verified historical IV1 mesh/graph/bounds bytes. Input decode and block preparation are excluded from timing. The mesh block stream represents row-style yields; it is not a full `iter_legacy_json` production measurement.
- Timed work is the three writes plus receipt rows. L copies the baseline gzip-1 writes and digest work; N uses r9 capture functions with fsync and atomic publication. The pinned backend loads before timing.
- Three rounds yield **LNNL / NLLN / LNNL**, twelve arms total. Every arm's `raw_bytes` and `raw_sha256` must match the historical receipt. The **first N arm** is decoded through the candidate ledger with its container pin and compared to the exact bytes; the ledger parser is also exercised. These controls are outside timing.
- An identity mismatch aborts before a successful summary. The harness refuses an existing output directory and checks that logical reservations are released. Do not delete or silently reuse partial outputs to force a retry.
- `summary.json` records order, raw times, medians/minima, `median_gain_s`, disk sizes, `capture_peak_reserved_bytes`, seed fields and loaded CRP/LG paths plus full hashes. `capture_peak_reserved_bytes` is a **logical WorkBudget peak**, not tree RSS.

The handoff's phrase **control PASS** means a successfully completed run with its summary after the control checks. The actual `summary.control` is descriptive text, **not a PASS enum**. The owner must verify exit 0, the fresh matching summary, expected order/control coverage, `hash_randomization == 0`, and the full loaded CRP `7afe82bf...` / LG `06040fd2...` identities. Do not invent a `control == 'PASS'` check or rely on a stale summary alone.

After a separately authorised result, record median L/N, gain, disk and actual measured/booked memory through `runq note q15`, preserving the evidence path, and tell the coordinator the conclusion. Use queue/process evidence for physical peak RSS. Preserve the current by-need queue protocol and individual holds; neither the historical smoke nor this document declares q15 READY or released.

## 6. Native DLL and Release's R1 fold

Selected r9's CRP and LG use the existing absolute `CAPTURE_LIBRARY` at:

`R/compact-geometry-r1/native/wp10_zstd.dll`

The full pinned SHA-256, verified against the existing binary, is:

`a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28`

Both modules already require that full identity through `ZstdBackend`. An eight-hex prefix, ambient environment fallback or invented loader is not the contract. Keep r9's current selected binding until the authorised fold; do not describe its absolute path as a newly discovered reason to reject the selected revision.

Release's `T/rm/STATE.md`, N12 input record at lines 226-241, specifies R1:

1. Carry the same DLL bytes into the package at the key named by the rewritten path, and pin the unchanged full binary pair in `sha_map` so the existing pin check covers it.
2. Map the source's exact forward-slash spelling injectively, treating the implicitly concatenated source string as one constant. Do not create a second alias that defeats the key map.
3. Emit the folded reference as `<identity_name>.resolve('<B key>')`, matching the accepted gate's normalisation. Preserve runtime full-hash refusal and the genuine fold/identity/consumer proof obligations.

r10 supplies useful module-relative semantics and tests. Verbatim substitution of its `Path(__file__)` expression would need a new AST-gate rule and its mutant/refuter evidence; it is not the selected rewrite. Carrying a binary alone does not prove package binding. A smoke on the old composed-r2 CRP/LG cannot exercise r9's binding because those older modules do not contain it.

Package transformation, identity successors and acceptance belong to Release's R1 plan. This document does not implement the fold, create a new package layout or declare it complete.

## 7. Completion and unchanged boundaries

- [ ] The owner has explicit q15 re-release and has reconciled the selected harness/inputs/output and current queue prerequisites without changing individual holds or reusing an existing output silently.
- [ ] q15 has actually completed with valid controls, expected loaded full identities and scoped timing/disk/physical-memory evidence; the owner has recorded the result and returned it to the coordinator. The measured disposition does not claim whole-interval performance.
- [ ] After freeze clearance, Runner has integrated the selected candidate/driver chain with explicit manifest/profile/generation changes, ledger dependencies and the required owner-layout/affected-consumer checks; known upstream failures remain accurately classified.
- [ ] Release has carried and fully pinned the DLL, applied the source-grounded package-relative rewrite and completed the applicable R1 proof on the actual selected generation. r10 remains reference unless separately selected through that process.
- [ ] The existing owner record states the enabled/disabled disposition, actual integration/fold status, remaining final-composition dependencies and next action. Old receipts, legacy readers and pending tool-limit/retest obligations remain intact.

These are outstanding owner completion conditions, not claims that replacing this document completed the work. The workspace edit authorises no Atlas code change, test or scientific run, ticket launch, queue/manifest mutation, live swap or publication. Preserve N9 **PAUSED BY USER** (general319), fresh-full-interval and individual holds, existing owners and Claude's work. Keep exact numerical/source/loaded-code contracts and the current resource and width limits; do not restore obsolete start gates, silently repin or change environments.

## 8. Source identities and review records

Aliases:

- `W = C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace`
- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`
- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`
- `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`

The following are reviewed source identities, checked unchanged on 17 October 2026. They do not silently repin a runtime. Full read scopes, objections and the replacement checkpoint are in the Codex turn record (private evidence unavailable in this public snapshot). The initial review (private evidence unavailable in this public snapshot) remains frozen; this is a post-reveal replacement.

| Primary source | SHA-256 |
| --- | --- |
| `A/.atlas-dev/plan-status-20261016.md` | `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e` |
| `A/.atlas-dev/small-optimisations-20261016-brief.md` | `caa8364298cc1a795853871c69e11b25a2714830318d9ac26b477fd1b5377d0f` |
| `T/so/HANDOFF.md` | `b4cba23827ef7581e0c753962629831b500d876a5a0ecb458756f160123d7ec7` |
| `T/so/s2/INTEGRATION-r9.md` | `be7ffbd7e7226e3c435e6161de476c303840539d505334b00da12881cf127d85` |
| `R/diagnostic-captures/WIRING_NOTE_STEPS8-9.md` | `b09be0b66f031024a286ce736c3bc27330db6f4c1d2792e415549c5f2bb26e11` |
| `R/diagnostic-captures/README.md` | `4ab43fede47da224487da682f22d1a67c98712288a4bc7a0e3a188865b88715d` |
| `T/so/s2/measure_s2_r2.py` | `23728693e3fb821039c9493f05879a8a358bafbdd892e9a20a7e02be91b207dd` |
| `T/so/s2/measure_s2_r3.py` | `009e07a0160e788adb8410ed3cec49012cd66b4a45751da17dd29cf2719a6ca1` |
| `T/q/queue.json` | `0992c52d69b18268cf26f56282b36ce2922cac6928813afbe2fb4af12702cec6` |
| `T/so/s2/q15-run.log` | `b0227b8cc75388bb672cef8eb67a00318b81f05e9c0c70bd40d30edeba3adb33` |
| `T/so/s2/r9/compact_restart_patch.py` | `7afe82bfc22403097eaa4acb378f1799c8fd42e6aad502f911efcec0d04275e3` |
| `T/so/s2/r9/ledger_fresh_interval.py` | `06040fd28c42f06210a32467a02f1d037f87c2cb8164888be46c745bd18349ef` |
| `R/composed-r2/helpers/private_heat_original_coverage_r1.py` | `90113110a3c7a37c70ea16df6de6166d61ed728d2bc974f6e2e3dbd49409c688` |
| `T/so/s2/r9/driver-lines.diff` | `1e2652b8e21d45e61bbc638251c12c15800f8e7acf823b42cb2d1aafc9e8109e` |
| `T/so/s2/owner/test_step8_coverage.py` | `59adb1899df26f6002bc04457ec0d2e1cc26728a090ca38bb5ea305f4940da5a` |
| `T/so/s2/r9/test_wp16_preadvance.py` | `25e9d8c60df91109101b29eaca83c8205f33ce143384ff8b5a9d44a3cdf54037` |
| `T/so/s2/r9/test_s2_route_wiring.py` | `d5f6837486d655bf30a15e855aeb22c5ea8e46b57b576fa66c6b88390289b912` |
| `R/diagnostic-captures/capture_store.py` | `4664b20599fa9b05d584328aa02d34478ae307a6204216497c637d6fa0804647` |
| `R/compact-geometry-r1/native/wp10_zstd.dll` | `a40c24ad328da37a42c7f69e434c576254f11fde4097cd5de7416f8f78444f28` |
| `T/so/s2/r9-check/run_all_r9.sh` | `89df190290601d78d50e3522f275f913c865fb288285136f7a6f5dab8836fcf5` |
| `T/so/s2/r9-check/make_mutants_r9.py` | `cd58edef7c988065ed282f259d9b827b116635c45d6c5ef02c90c1cfd3588830` |
| `T/so/s2/r9-check/tests-r9.log` | `0b8a1edb3bd4fba3d34ccf7686622df5002b92ddce6725dbf1029b65337de18f` |
| `T/so/s2/r9-check/drivers-r9b.log` | `de80c6739054c44e5ab8102aa6ea62a665a361bf67379c72ed8a3c6d120dee51` |
| `T/rm/STATE.md` | `3e41d1bdcdb3365ff5ba26c783ea6dbf02f5f4a4fa7180e39b2d8ee4975e015a` |
| `R/probes/step8/claude-20261015/STATE-NOTE.md` | `3556ac777b8fd632a68c6204575ca767b0e46600944d4a6c8391ce557cd6d312` |
