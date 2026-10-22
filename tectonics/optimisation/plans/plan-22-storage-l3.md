# Plan 22 - Storage L3: carry verified page pins between read batches

**Status:** WORKING NON-CANON. Owner design ACCEPTED; L3 implementation UNSTARTED and owner HOLDING. Room verdict AGREED WITH REWORK applies to this plan, not a built or integrated candidate.

**Retained owners:** Storage builds/proves the separate candidate; the Atlas coordinator owns release and timing-ticket decisions; Runner retains later integration. WP12's own implementation/proof belongs to Plan 23 and the existing owners.

**Room decision:** Gemini general692, after Claude general685 and Codex general689, with Claude general695 conditions. Correct the synthesis shorthand: `B` is `fixes/backlog`, and `compact-geometry-r1` contains the verified live base, not a completed L3 candidate. This assignment replaces only this workspace document.

**Completion condition:** implement and prove the accepted carried-page design on the verified live base; establish measured net benefit and retention cost under a coordinator-authorised comparison; record the disposition and any authorised Runner integration. A count-only probe, accepted design, smoke or future booking is not that completion.

## 1. Authority, source paths and hold

| Alias | Exact root |
| --- | --- |
| `W` | `C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace` |
| `A` | `C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas` |
| `T` | `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10` |
| `REVIEW` | `T/fidelity-integration-20261005/claude-review-steps1-7-20261015` |
| `B` | `REVIEW/fixes/backlog` |
| `R` | `T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1` |
| `CG` | `R/compact-geometry-r1` (Storage's local alias `C`) |

The owner record is **REVIEW/fixes/STATE.md**, SHA `064f6d87`, especially RESTART HERE lines 22-45 and the following NOW section. Its exact hold is:

> HOLDING until the weekly reset (22 Oct 21:00 BST) or the coordinator's word

Build only below 90% weekly usage. Neither the date in the record nor this room review establishes that release or usage check. The owner checks these prerequisites on an authorised resume; no usage probe, build or run is launched here.

The accepted design is **B/l3-build/DESIGN.md**, full SHA-256 **5751efb5a97bb45cdefd3b1106fdc101873b9caac3b4c781d9e4b091accffd51**, accepted as written by the coordinator on 16 October at 18:24. The directory currently contains **only DESIGN.md**. Origin/candidate code, new tests and L3 mutants remain unbuilt.

Current verified live bases:

| Source in CG | Current prefix | Role |
| --- | --- | --- |
| `record_views.py` | `a6bbb81d` | Merged item14 base; the only implementation file L3 is to change |
| `content_cache.py` | `de7d3e45` | Existing accounting/cache contract; read, not modified |
| `segment_store.py` | `a90ef8f3` | Existing verified-read/freshness boundary; not an L3 edit |
| `test_item14_page_layer.py` | `abd3bbd4` | Existing consumer proof source |

These are **base identities**. `R/composed-r2/helpers` separately holds older `record_views.py` (`e0a2a845`) and `segment_store.py` (`1f503604`), with no `test_item14_page_layer.py` there. Do not substitute that composition for the accepted CG origin or claim the Storage merge is already present in it. Any later integration needs the actual owner's source reconciliation and explicit repins.

The current `.atlas-dev` order, ownership and run protocol continue to apply. Preserve the Runner freeze, existing individual/full-interval holds, **N9 PAUSED BY USER**, immutable source stores and historical evidence. This plan supplies no implementation, run, queue-release, publication or cross-thread authority.

## 2. Opportunity evidence: measured counts, estimated removable cost

The accepted question is whether repeat cross-block re-pins and page verification can be avoided while retaining the same authenticated immutable data and freshness checks. It is not a generic raw-chunk cache or an inference from I/O wait.

Primary evidence: `B/l3-probe/RESULT.md` (`83417b47`), `l3-summary-l3b.json` (`1416a540`), `B/b17-dir/post-q04.json` (`42b1459f`) and q04's retained queue row.

| l3b probe observation | Result |
| --- | --- |
| Shared-cache lookups / verifier calls | 65,995 |
| Hits / misses | 57,673 / 8,322 |
| Native / small-path misses | 8,294 / 28 |
| Outer read_batch blocks / segments | 7,183 / 1 |
| Hits crossing blocks | 57,424 = 31,814 small + 25,610 native; about 99.6% of hits |
| Gap since last held page | One block: 46,111; 2-8 blocks: 11,182; more than eight: 131 |
| Lookups outside a block | Zero in this probe |
| Reopen equality | Equal result_id; five fields |

The untimed count-only probe simulated a 128-page LRU per segment in an instrumented copy of the real IV1 sealed heat reopen. It did not implement retention, caps, close handling or a process-wide L3 counter.

The **6.25%** is a profile-weighted opportunity estimate: 57,424 cross-block hits x about 28.776 microseconds of cProfile verifier cost = **1.652 s**, divided by **26.458 s** profile total own time, or 6.246% rounded. It passed the coordinator's **1% build-opportunity gate**. The counts are MEASURED; the profile costs are inflated; the estimated removable share is neither a percentage of hits nor a measured plain-time L3 saving.

The wider 5.242 s / 19.8% estimate includes lookup, scratch admission, key, pin and cursor work and is explicitly a cProfile-inflated upper estimate. It does not support the discarded 'over 20% I/O wait' claim. The 1% opportunity gate is not a new fixed percentage requirement for L3's final net gain.

The retained l3a/l3b counts agree apart from pid/mirror path. The summary's v2 corrected a derived-hit calculation which had included the 28 small-path misses. Its 13/13 summary selftest and six refused harness precondition mutants are scoped probe evidence, **not L3-M1..M7 implementation results**. Preserve the earlier refused summary/harness records rather than rewriting them.

q04 measured **B17/item14**, with plain means 46.127 s live, 17.419 s B17 and 15.670 s combined. All eight profile/plain arms had equal result IDs/five fields; the queue records a 0.32 GiB tree peak. These results supersede the earlier no-read prediction but are not L3 gains. L3's plain-time saving, retained-memory effects and integration remain unmeasured.

## 3. Accepted L3 mechanism and trust boundary

### Existing behaviour

In the current `record_views.py`, outer `read_batch` books the optional registry `ChargeSpec('record-batch-page-borrows', 128*2048+4096)` and pins up to 128 verified pages. `_pin_page` wraps the existing Owned holder; the native miss path already reserves page bytes plus binding/overhead, while a shared-cache hit obtains a child share. Normal block exit drops the pins, so the next block consults `ContentCache.get` and re-verifies a hit's full typed digest.

The cache page objects contain immutable bytes. A pin keeps the same verified object and its existing allocation alive. L3 changes **when that object is re-verified**, not its content, typed binding or scientific values.

### New behaviour, in a separate record_views candidate only

1. Add `_Segment._carried` for the registry between blocks. Keep `_batch_pages is None` outside a block; ordinary outside-block reads cannot consume a carried pin.
2. On a normal outer-block exit, `_carry()` trims LRU-first to the page-count and per-view booked cap, then moves the registry to `_carried`. Refuse and drop a carry that would exceed the process cap; count the refusal. Protect the module-level process total with a lock.
3. On entry to the next block, pop `_carried`, enter `segment.verified_read()` **before adoption**, then use the popped registry as `_batch_pages` instead of reserving a new one. Failed entry closes the popped pins and propagates the failure.
4. Keep `segment.check_unchanged()` on each served access. Preserve the verified-read entry/exit and file-batch closing checks, cancellation and closed-segment refusal. No result may escape before the required closing freshness check succeeds.
5. Remove pins/registry from reusable carried state on exceptional exits; release them on view close, an uncached value/raw fallback, failed entry, LRU trim or cap refusal as the ownership contract permits. Preserve the existing paid ownership of data retained by a failed frame/traceback: an exception must not create uncharged live bytes. Add `_Segment.release()` and call it from `CompactRecord.close` before `_columns` is dropped; an external `_Access` or column may still hold the segment.
6. Update the `read_batch` docstring: pins can persist, funded and capped, between blocks of the same view; they are served only within the next verified read and released on the specified boundaries.

A carried hit intentionally skips repeating the page digest. Requiring a new hash on every such hit would undo the accepted optimisation. Its trust boundary is the same immutable pinned object, verified-read freshness, per-access liveness/cancellation and same-segment lifetime. WP12's newly read sidecar bytes have a different check-at-use obligation in section 6.

Carried keys are `(name, start)` inside one `_Segment`, serving one segment. They are process-local objects, not a global cache indexed only by interval/stage/offset. Do not replace this ownership boundary with the rejected generic cache design.

The proof must cover an exception from the **closing verified_read/file-batch check**, as well as failed entry and a body exception. Current normal-exit handling occurs inside the enclosing verified-read context: a naive carry action could precede the outer context's refusal. The accepted drop-on-exception condition must cover that closing boundary in the existing freshness/exception tests and refuter scope. This is a requirement for the unbuilt candidate, not a reproduced candidate failure.

## 4. Accepted memory contract and reporting

| Limit | Accepted value and behaviour |
| --- | --- |
| Carried page count | At most 128 per view |
| Carried booked bytes per view | `_CARRY_VIEW_BYTES` = 10 MiB; trim LRU-first |
| Carried booked bytes per process | `_CARRY_TOTAL_BYTES` = 32 MiB across live views; locked accounting, refuse/drop/count an excess carry |
| New byte reservation | None: existing page allocation/holder accounting already funds the retained bytes |
| Existing page-cache quota | 64 MiB; raising it to 256 MiB was NOT TAKEN |

These are accepted **booked-byte** limits, not a new physical-RSS allowance. Existing scope and run guards remain unchanged. The 256 MiB scope cap and WP12's separate sidecar file cap grant no 256 MiB L3 cache.

`Owned.charged_bytes` already includes the allocation and that holder's carrier. A hit's child and parent share an allocation. Make the booked-byte definition explicit: retain the registry charge and distinct carrier overhead without adding the same underlying allocation twice. No extra byte reservation is permitted merely to account for the carry. Raw len-only accounting omits overhead; adding both full parent/child charged-byte values may double-count. Tests and reporting must distinguish these quantities.

The registry is booked at 266,240 B. With 65,536-byte chunks, 128 pages are at most 8 MiB raw; the accepted design estimates about 9.6 MiB booked per view including relevant page/binding/registry overhead. Treat that as the design's estimate, not a measured new candidate peak or an alternative to the enforced 10 MiB cap.

Pins make cache entries unevictable. `RetainedScope._reserve` relies on evicting unpinned entries, so retaining hot pages between blocks can leave less reclaimable memory for other scope consumers. Scope close also refuses live owners. Explicit release, correct process-counter transitions and the pressure/fallback tests are necessary; garbage collection is not the close contract.

Report with the future comparison:

- carried, adopted, refused, trimmed and dropped-by-reason counters;
- peak carried **real raw bytes and booked bytes**, per view and process, alongside pinned bytes in `stats()`;
- page_misses, physical RSS and queue process-tree peak with their actual scopes;
- refused/trimmed counts, cap behaviour and effects on other consumers.

**Page misses must not rise beyond noise.** Reduced re-verification counts alone do not establish a net win. The caps stay fixed as interval size grows; the design's expectation of increasing savings with more blocks is a projection to test, not a measured IV3 outcome.

## 5. Remaining owner proof and queue route

After the recorded hold/usage prerequisites are met, Storage follows RESTART HERE and the accepted design:

1. Verify the four CG source identities in section 1. If record_views or content_cache changed, reopen design sections 1-2 against the new code and update the owner design before building; do not silently repin.
2. Create `B/l3-build/origin/record_views.py` from the verified live file and a separate `candidate/record_views.py`. Implement only design section 3. Preserve the original files and old evidence; use argument/environment/module-relative paths as required by the owner.
3. Add `candidate/test_l3_carried_pages.py` and separate sources under `B/l3-build/mutants/`. Retain **L3-M1..M7**, each demonstrated to fail on its corresponding planted fault:

| Case | Required distinction |
| --- | --- |
| M1 caps | Lowered view cap causes trim/count; process-cap excess refuses and drops pins. No-trim mutant fails. |
| M2 close | An Access survives CompactRecord.close; live charges return to baseline and scope close succeeds. Missing release fails. |
| M3 freshness | Changed segment refuses before carried pages are adopted/served. Cover relevant closing-check refusal as well. |
| M4 key | Wrong carried-page key is caught by exact equality. |
| M5 fallback | Uncached value/raw fallback clears carried pins; leaving them retained fails the pressure check. |
| M6 outside-block invariant | `_batch_pages` is None outside blocks; an outside read must take its normal cache/verification route. |
| M7 exception | No reusable carried registry survives an exceptional exit, including the closing verified-read boundary; any traceback-retained data stays funded. |

4. Write **new** revisions of `B/scripts/item14_focused.ps1`, `combined_focused.ps1`, `l3_probe.ps1` and `q04_b17_profile_timing.ps1`; keep the old scripts. Every runtime-importing child uses the approved interpreter with `-B`, a cleaned environment containing `PYTHONHASHSEED=0` and no other PYTHON variables, no `-I`/`-E`, and a fail-closed child `sys.flags.hash_randomization == 0` check. Smoke each exact successor and demonstrate seed-mutant refusal. Read-only helpers that never import the runtime may use `-I`.
5. Use a fresh named mirror through runq small, one core, for the specified focused origin/candidate comparison. Require **zero new failures** against `B/known-failures-origin-r1b.json` (`69e9c45f`) via failure_set v2. It records six historical mirror path errors and one Step7B assertion, not a universal waiver or an all-pass result. Reconcile subsequent owner fixes on a future resume rather than reintroducing fixed failures. Preserve required `test_item14_page_layer`, `test_record_views` and `test_r1_views` coverage.
6. Re-run the count probe on the candidate: about zero cross-block re-verifies is expected; require equal result_id and five fields. This is distinct from measuring speed or proving all memory/lifetime behaviour.
7. Same-rule Ruff check-only on origin/candidate, zero introduced findings; Pyright on the changed file. Use the handoff's one refuter (recorded as sonnet), aimed at the unchanged verified data, freshness, caps and close accounting. Fix concrete findings and reproduce the affected failures; no automatic extra reviewer or broad audit is added.
8. With the stipulated proof, mutants, exact-route smoke and refutation complete, send **REQUEST** to the Atlas coordinator for the timing ticket. This plan creates no ticket and releases no hold. No dedicated L3 performance ticket is established by the current queue.

The old q04/probe runtime children used `-B` and exported seed 0, but did not assert it or clean other PYTHON variables. Preserve that limitation. Do not label the retained runs random-seeded without evidence, and do not treat their old harnesses as ready under the amended rule.

### Arm definition remains open before booking

Both accepted DESIGN section 5 and STATE step 9 say **plain A/B** and **ABC CBA**, without defining a third L3 arm. q04's historical live/B17/both arms are not automatically the new L3 comparison.

The owner/coordinator must bind the actual baseline, selected candidate, complete arm set/order and fresh outputs before booking. Do not invent arm C, silently choose a new order or present a fabricated executable run command. Preserve the source discrepancy until that decision is recorded.

The recorded request is for q04 inputs, exclusive timing, one core, against the verified live base. Any new booking needs frozen source/input identities, an exact reviewed route, a fresh output path and grounded time/memory estimates under the current protocol. Apply the by-need admission rules and existing in-run guards; no fixed new memory gate or timeout is inferred here. The coordinator owns release; the owner uses the native completion mechanism, not polling.

Report plain before/after values and **measured net benefit**, all section-4 counters/costs, input/source scope and load/gate context. Use the existing owner format: what changed, before, after, measured on, later-step impact and IV3 implications. The 1% probe gate is not a substitute for actual benefit. If no net gain is demonstrated, do not enable L3; retain the tested/disabled or unresolved disposition accurately. Runner receives the source-bound package only through the established handoff and integration authority.

## 6. WP12 relationship and sequencing

`B/wp12-design/DESIGN.md` (`99592b64`) records **D1 YES conditionally; B NOT TAKEN; L3 first, then WP12**. The latter's section-0 guard-equivalence argument is required before its build. Plan 23 owns that proof and its own acceptance gate.

The existing raw_sidecar component used whole-file authentication and per-call mmap. The proposed WP12 wiring instead uses a **positioned read into bytes, explicitly no mmap**, on native page misses. Exact bytes are required by the page verifier, so mapping would not avoid the copy. L3 avoids repeating verification of existing hits; WP12 replaces SQLite read/checksum/decode work on misses. They compose through the same page-cache route. The former generic 'bypass L3 for mapped pages' rule has no basis in this design.

Retain the WP12 seam requirements without duplicating its work:

- Quote the code establishing the same authenticated chunk ID and typed digest; every newly served sidecar byte must pass that check before use.
- Explicitly verify even when the shared cache is disabled: `ContentCache.offer_verified` returns False before calling its verifier in that mode.
- Address checks lost by removing whole-file validation: unused chunks, exact file length and trailing bytes. Keep equivalent checks or justify each difference in the accepted argument.
- Preserve wrong/swapped sidecar, truncated/extended file, unused-chunk-flip later used and cache-disabled faults; a present wrong sidecar raises ContractError rather than quietly falling back. Keep counted declines, scratch/handle/file caps and no-overwrite build behaviour.
- Keep the **at least 5% plain net-of-build/open gain** gate for WP12. It is not L3's gate. Report disk and real/booked memory separately.

The alternative to raise the page quota from 64 to 256 MiB was explicitly **not taken**. No new quota increase is authorised. Assess actual L3/WP12 overlap on the agreed sources and measurements; do not add their projected gains or start another cache/pool project.

## 7. Completion and unchanged boundaries

- [ ] Storage's hold/usage prerequisites are satisfied and the actual CG base is revalidated before a separate candidate is built.
- [ ] L3 implementation, exactness/lifetime/cap proof, L3-M1..M7, seed-safe successor harnesses, focused checks and the stipulated refuter are complete on the selected source identities.
- [ ] The owner/coordinator resolves the arm contract and issues/releases a grounded ticket through REQUEST; actual performance and all retention/counter evidence are recorded, with page misses checked and no unsupported net-gain claim.
- [ ] The L3 disposition is explicit; any enabled package is handed to Runner and integrated only after source reconciliation, freeze clearance and required owner checks.
- [ ] The existing final-build record reflects actual L3 disposition/integration and the L3-before-WP12 dependency; Plan 23 retains its separate conditional proof.

No checkbox is complete merely because this plan has been rewritten. Current next action remains with the parked Storage owner and Atlas coordinator under the recorded release conditions. This document neither starts that work nor sends messages to the original owner chats.

Preserve exact numerical identities/fields except established explicit successor identity rules, the 12 GiB tree-RSS guard, 1 GiB free floor, 16 GiB logical limit, 256 MiB scope caps, 1 MiB integer bound and 256 accepted-step ceiling. No environment replacement, scope-cap raise, silent repin, historical evidence rewrite or reopening of S10/other closed safety exclusions. N9 and fresh full intervals remain held under their own authority.

## 8. Evidence and identities

The frozen initial assessment (private evidence unavailable in this public snapshot) remains unchanged. The post-reveal review and replacement checkpoint (private evidence unavailable in this public snapshot) records the actual source reads, discovered design, static accounting/exception questions and room return. No new blind assessment or executed candidate failure is claimed.

All 27 review pins were freshly checked before replacement and were unchanged. The 25 primary-source identities below exclude the old plan and frozen initial. Static source inspection and historical results were reused within their scopes; no Atlas tests, fixtures, benchmarks or scientific runs were performed for this document.

| Source | SHA-256 |
| --- | --- |
| `A/.atlas-dev/plan-status-20261016.md` | `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e` |
| `A/.atlas-dev/optimisation-backlog-20261016.md` | `414470799087a745e79ded44fc53ff747f14ee5a3f773de039c0aa6b01658189` |
| `A/.atlas-dev/coordinator-handoff-20261016.md` | `e75652996f3f29e6c4b074f24bec561551c842c7b04a1ac49ccb8c411799ba15` |
| `A/.atlas-dev/run-queue-protocol-20261016.md` | `c0cf31fc54d4f302311037c2250c600c1ecd1429f5acf8940eac5dee9ac9a0b0` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/STATE.md` | `064f6d87469bad9071e7caf4891dd5363e92a6e7de6a53517d664757cb46f37a` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/l3-build/DESIGN.md` | `5751efb5a97bb45cdefd3b1106fdc101873b9caac3b4c781d9e4b091accffd51` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/l3-probe/RESULT.md` | `83417b47536ea489277ba4a2827be92240182db8b201572947b3ba904a3acf7a` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/l3-probe/l3-summary-l3b.json` | `1416a540b1d7bead1b9c1af451e8a14782b4bf77a59f37e51c9c6b13136112e2` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/b17-dir/post-q04.json` | `42b1459fdd66f6d72f469334c0304455786fe5f7d09067bebe46c58629bf2f17` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/wp12-design/DESIGN.md` | `99592b641eace6c425974e7345d4493b6810efc4ef63dc95cbcedbdceced9845` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/known-failures-origin-r1b.json` | `69e9c45f221d460ff1e65d92f436ccc39a9784a1c11b6c572269d364caf2ff1b` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/failure_set.py` | `86a3d0a6dfa83ae61512daf094888f538e12786293baa8682226115627242687` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/l3_summary.py` | `0f61848a9bd76f412efb7c927e57153b6685cda8c9e5fc6f15e820998d605792` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/item14_focused.ps1` | `aa16181e7f904ddec23e83adf7cf073495d999f4d8c19093dbf35a20daa0a771` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/combined_focused.ps1` | `68adf06a33bf8b1bc3e5496da3f49c6f18453e92b8172885896df0d160f32553` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/l3_probe.ps1` | `121497b4da38fcbf34015e037862ad59b94903ad819ff0e2aa27d63523faba09` |
| `T/fidelity-integration-20261005/claude-review-steps1-7-20261015/fixes/backlog/scripts/q04_b17_profile_timing.ps1` | `dfb8cd0063048eaef1140e5b772d141138a23ca32bf11cc919a92c3016cdb504` |
| `T/q/queue.json` | `0992c52d69b18268cf26f56282b36ce2922cac6928813afbe2fb4af12702cec6` |
| `R/compact-geometry-r1/record_views.py` | `a6bbb81dcc88c7f4b84272929922a8e4f702694163b18d18c26d3b76a86f89bd` |
| `R/compact-geometry-r1/content_cache.py` | `de7d3e454b41e78916a2c98cf76efe531e981be9a232915d6d152d6ad61e05bb` |
| `R/compact-geometry-r1/segment_store.py` | `a90ef8f3e519ee77ea4332380428ce2694c16134ec69603ccaf93ce95cea6cd9` |
| `R/compact-geometry-r1/test_item14_page_layer.py` | `abd3bbd466fcca61dd7632e0bb3178df5bd589bd133c71a1b8d9a5f35bcfbd60` |
| `R/composed-r2/helpers/record_views.py` | `e0a2a8453f494e50cacded7de06e275b1e36f526c220df611bbedb69248e0f9b` |
| `R/composed-r2/helpers/content_cache.py` | `de7d3e454b41e78916a2c98cf76efe531e981be9a232915d6d152d6ad61e05bb` |
| `R/composed-r2/helpers/segment_store.py` | `1f503604cbe76e39c80ae2260a2e485d70c2ee047326488aa8d2baa620cde53a` |
