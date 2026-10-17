# Plan 06 — D5 exact arithmetic repair and shared mpq primitives

**Item:** 06  
**Status:** WORKING NON-CANON. Plan amendments agreed in general452–453; D5 remains PART-IMPLEMENTED, REFUTED and excluded from final assembly N12.  
**Owners:** Kernels owns the D5 implementation and shared primitives; Geometry owns the target wall-measure file, guarded hook and retained-native policy; Pressure consumes the shared interface for P4.  
**Completion condition:** Complete the retained handoff's repairs and expanded checks on rebuilt candidates, obtain the required delta-refuter and parity evidence, resolve D6 explicitly with the coordinator, and deliver the hook diff/modules through Geometry's integration boundary. A previous smoke pass or acceptance of this plan does not admit D5 to N12.

## 1. Purpose, evidence and authority

D5 accelerates existing exact `Fraction` wall-measure kernels using `gmpy2 mpq` intermediates. The relevant kernels are `_rotated_normal`, `_clip2` and `_line`; Pressure P4 is intended to share the exact primitives. This is an exact-arithmetic speed change: Python integers/Fractions remain the public and stored representation, with identical numerical results and the approved D-b source/runtime identity changes only. It introduces no new physical model or tolerance.

The retained handoff reports a parity smoke pass at `CK/d5-parity-s1`, followed by refuter r1 finding seven defects. The repairs had not started in that record. The current consolidated plan independently retains the REFUTED status and exclusion from assembly. Historical smoke evidence is neither proof of the repaired candidate nor full D5 parity.

Path abbreviations used here:

- `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`.
- `CK = T/ck`.
- `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`.

Primary evidence is `CK/HANDOFF.md` §3 and its standing rules; `CK/d5/DESIGN.md`; the saved twin modules, backend and refuter; and `A/.atlas-dev/plan-status-20261016.md`, especially “Heat, pressure, geometry and exact kernels” and the acceptance boundaries. The later handoff/refutation corrects the original design's post-reservation ceiling argument and unfinished attachment behaviour. The design's `active(reference)` is conceptual wording; the retained implementation uses `available()` and `_resident()`.

This plan authorises no new implementation, run, integration, swap or publication. It preserves Kernels' existing own-file code authority in the handoff, Geometry's ownership and the separate queue requirements. Codex's room assignment is to amend this document. N9 remains PAUSED BY USER; fresh full intervals and individual holds remain unchanged. D5 repair labels D1–D8 are local to this work and do not establish completion of Geometry's separate D1–D4 programme.

## 2. Exact route and resource contracts

### Backend selection

Keep provider-mediated selection. The retained twin calls `_library = X.library()` at module initialisation; the provider selects the backend at import and `library()` returns that selection. Do not describe this as lazy loading or add a direct unconditional `gmpy2` import to the twin.

- `python` never imports gmpy2.
- `auto` can select Python when the native library is unavailable or fails the provider's eligibility checks. Preserve the provider's separately propagated process errors.
- An explicit unavailable, untested, failing or unsealed `gmpy2` request fails; it does not silently fall back.
- A native calculation failure is never retried on another backend.

The guarded twin declines to the unchanged reference route when eligibility, exact argument types or reference-object identity do not match. Wrapped/replaced kernels must remain observable to instrumentation. New native results become new canonical Fractions of Python integers; input objects, container identity, aliasing, type and pickle semantics must match wherever the reference preserves them. Unsupported or non-canonical inputs must retain the reference behaviour rather than being silently normalised into a different observable result.

### Ceiling and leases

The shared native constant is `CEILING_BITS = _G.CEILING_BITS`; the retained `integration_exact_gmp.py` defines `1 << 27`, or **134,217,728 bits**. This constant is distinct from the project's **1 MiB integer bound (8,388,608 bits)**. Neither changes here. A two-million-bit example is below the shared native ceiling and cannot demonstrate over-ceiling refusal.

Use `V._bits` on reference-typed operands for the lease width. Converting an integer to mpq before measuring changes its accounting width, so a generic numerator-plus-denominator footprint rule is not a substitute. Preserve the reference reservation amount `65536 + 128*bits + 256*count + 256*pairs`, category `i03-physical-volume`, and ordering with `arena.work`.

D2 must decline to the reference route **before reserving** at the named over-ceiling sites: entry, both `clip2` paths, and `rotated_normal`. Retain the reference's own result or refusal; do not invent an exception class or change the shared scientific/resource limits. The old claim that project-sized budgets always make the post-reservation ceiling harmless is insufficient: r1 demonstrated the mismatch with an admitting budget.

### Retained natives and refusal behaviour

Geometry selected **Policy A** for T1 and P4: use the shared `exact_gmp._settle` rule and charge the retained-native surcharge under `NATIVE_RETAINED`. This charge only adds to the reference accounting. Preserve reference work/reservation order and ordinary exceptions, while stating the approved exception accurately: **the native-retained surcharge can cause earlier refusal, never later admission**. An unqualified same-step promise for every refusal would contradict Policy A.

D1 creates `Retained` lazily after the first `arena.work`. Order-zero calls reserve nothing and must avoid the unwanted `arena.resource` reads and revoker calls exposed by r1. This is an accounting/observable-behaviour requirement, not a claim that no native object is allocated. Order-zero is the actual mathematical branch, not a replacement condition based on `count == pairs == 0`.

The general Atlas contracts remain intact, including 12 GiB tree RSS, the 1 GiB free floor, 16 GiB logical budget, 256 MiB scope caps and the 256 accepted-step ceiling. Numerical parity remains exact; the separate bounded N9 exception does not grant D5 rounding permission. Runtime escalation rules and bookings remain those of the queue, not new limits inferred from this plan.

## 3. Required repairs

Apply the handoff's complete repair set to new, owner-controlled candidate revisions:

1. **D1 — lazy retention:** defer `Retained` until after the first `arena.work`, preserving the reference order and order-zero behaviour above.
2. **D2 — early decline:** check reference-derived widths and decline before reservations at entry, both `clip2` paths and `rotated_normal`; leave reference behaviour intact.
3. **D3/D7 — documentation:** reconcile the primitive, ceiling, retention, backend, return and refusal contracts with the actual implementation and adopted Policy A.
4. **D4 — module attachment:** add the handoff's fail-closed `_closed` handling for a second `attach()`. The retained code currently overwrites `_module` and `_loaded` and has no such guard. This is a module-attachment repair, not an arena state-machine API. Preserve the original instrumentation boundary and make the second-copy and namespace-mutant checks exercise it; no invented `DoubleAttachError` is required.
5. **Identity coverage:** extend the existing reference-object identity tuple with `W.V`, `W.O`, `V.Fraction` and `O.Fraction`. Preserve its existing entries and their identity comparisons; do not replace it with a new digest/version tuple.
6. **D8 — shared lease interface:** rename the context manager to `_work(bits, count, budget, *, pairs=0)` and keep `lease = _work`. Notify Pressure in the implementation handoff. Retain diagnostics-equality coverage.
7. **Check gaps:** expand `check.py` for near-full budgets, the real `_Arena`, second module copy, D8 diagnostics equality, order-zero no-reservation behaviour and `mutant_namespace` handling of `_closed`. Also cover the retained instrumentation and non-canonical-Fraction findings and the return/type/alias/pickle contract.

**D6 remains an open coordinator question:** does adding `NATIVE_RETAINED` to budget-statistics categories change persisted failure diagnostics? r1's category probe supplies evidence, not a waiver. Record the coordinator's explicit disposition and any resulting work; do not assume that selecting Policy A automatically accepts diagnostic differences.

## 4. Owner workflow and integration boundaries

The retained candidate files and tools are:

| Role | Existing path |
| --- | --- |
| Design | `CK/d5/DESIGN.md` |
| Shared primitives | `CK/d5/src/integration_exact_twin.py` |
| Wall twins | `CK/d5/src/integration_wall_measures_gmp.py` |
| Guarded hook transform | `CK/transforms/d5_wall_hooks.py` |
| Tree builder and outputs | `CK/d5/build_tree.py`; `CK/d5-f2`, `CK/d5-jets` |
| Checks | `CK/d5/check.py` |
| Retained refuter and raw evidence | `CK/d5/refute1/r1.py`; `CK/d5/refute1/r1.out` |
| Independent refuter brief | `CK/REFUTER-TEMPLATE.md` |

Kernels' next sequence, within existing authority and applicable holds:

1. Make the repairs and expand the checks in its own candidate files; update the source identities without overwriting historical evidence or silently repinning consumers.
2. Rebuild both `d5-f2` and `d5-jets` candidates from the repaired sources and retain their exact identities.
3. Run the expanded `check.py` and retained `refute1/r1.py` under the existing own-file/small-lane rules. Bind results to the actual rebuilt sources and use new output locations.
4. Obtain the stipulated one independent delta refuter using `CK/REFUTER-TEMPLATE.md` against those exact candidates. The delta-refuter artefact is required future work, not an already implemented script with an invented filename.
5. Send the batched coordinator note with repair/check/refuter outcomes, rebuilt identities and the D6 question. Deliver the hook diff and modules to Geometry; include the shared-interface handoff to Pressure.
6. Complete the required rebuilt-tree parity smoke and separately ticketed full D5 parity before claiming the relevant validation/integration stage complete. The full proof follows the design's IV1-all, IV2-sample and capped-to-deep scope; a smoke pass cannot replace it. Geometry registers the guarded early-return hook as a SHA-pinned transform on its target file.

T3 changes to Geometry's call structure wait for its D3/D4 work; they are not included in this repair. P4 remains a dependent consumer, as described in [Plan 08](plan-08-pressure-p4.md); final assembly remains governed by [Plan 31](plan-31-final-assembly-n12.md) and its authoritative owner records. Those dependencies do not authorise edits to their owners' files.

Any process importing the runtime must use the handoff's seed-zero, cleaned-PYTHON-environment and fail-closed hash-randomisation rules; do not use `-I` for native runtime imports. Use the established small lane or required ticket for actual execution. The retained r1 entry point takes scripts/runtime/base arguments, so no unbound, argument-free invocation is prescribed here. Current commands, inputs and output locations must be bound by the owner before execution. No native import, rebuild, test or queue action accompanies this documentation change.

## 5. Required evidence and interpretation

Preserve `CK/d5/refute1/r1.out` unchanged (SHA256 `728c87037197f00e02bf9c738c3ccc780f7d10ce7c4fea87582557432c90dd1f`). It records several `DIFFERENT` results and instrumentation/category mismatches, yet ends with process **exit 0**. The retained r1 script prints findings without an aggregate failing exit. A successful process exit is therefore not proof that its defects are fixed.

Assess every retained probe substantively. Expanded checks must assert the intended repaired behaviour so each claimed repair is demonstrated; the delta refuter must identify the exact candidate and findings. Preserve raw original output and separate successor results. D6's diagnostic-category question must remain visible even if arithmetic results match.

Coverage includes:

- Order-zero arena without a resource, resource-property reads, revoker calls and real/near-full budget behaviour; reference work before resource validation on the applicable non-zero path.
- Over-ceiling decline, both `clip2` paths and the rotated-normal entry/step boundary, using reference widths and unchanged accounting contracts.
- Instrumentation changed through `arena.work`, module-object substitutions, a second wall-module copy and namespace mutants, including `_closed`.
- Non-canonical Fraction inputs, retained input objects, new canonical result Fractions, container/alias/type relations and pickle protocols 2–5.
- Exact lease/category/order traces, D8 diagnostics equality and the separate permitted Policy A surcharge, with D6's outcome explicitly recorded.
- Provider routes, reference fallback/decline and explicit-native failure behaviour; no retry after native calculation failure.

Reuse adequate unchanged captured-call and mutation evidence within its actual scope, but prove changed behaviour on the rebuilt candidates. Do not report projected speed gains, old smoke results or source constants as new measurements. Any later gain must retain its baseline/candidate scope and distinguish component performance from whole-interval performance.

## 6. Completion gates

- [ ] The handoff's repair set and documentation changes are complete in owner-controlled candidates with exact source identities; historical candidates/evidence remain intact.
- [ ] Expanded checks and the substantive r1-probe assessment pass for the rebuilt candidates, including all stated GAP, instrumentation, non-canonical-input and return-semantics cases.
- [ ] The required delta refuter reports NOT REFUTED for those candidates, and the rebuilt-tree parity smoke passes; neither is inferred from exit 0 alone.
- [ ] The coordinator explicitly disposes of D6, and Kernels delivers the batched outcome, hook diff/modules and shared-interface information to the appropriate owners.
- [ ] Required full D5 parity and Geometry/assembly integration decisions are completed under their existing authority and tickets before D5 is admitted to N12. Plan acceptance alone changes none of these statuses.

## 7. Review provenance

The [frozen Codex initial assessment](reviews/codex/plan-06.md) remains unchanged. The [post-reveal source corrections and evidence pins](../discussions/atlas-plans-39-review-20261017/codex-plan-06-turn-02.md) record the later corrections, including withdrawal of the earlier lazy-library wording. The plan edit implements general452 and Claude's explicit acceptance/additions in general453.

Primary identities checked for this edit include `CK/HANDOFF.md` (`1c0fe29c…`), `CK/d5/DESIGN.md` (`b9156529…`), the twin modules (`205453c1…`, `616fc5c0…`), the retained backend (`84fc2127…`) and the consolidated plan (`be270e68…`); the linked discussion record holds the full pins. These are evidence identities, not implementation or integration receipts.
