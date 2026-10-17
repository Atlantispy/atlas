# Plan 08: Pressure P4 exact jet arithmetic

**Item:** 08 / P4  
**Status:** WORKING NON-CANON; P4 NOT BUILT; blocked on accepted D5 shared primitives landing and a coordinator assignment.  
**Route owner:** Exact Kernels and Parallel Admission. The P4 implementation assignee remains pending; the coordinator will assign Kernels or Pressure after the prerequisite lands.  
**Plan decision:** Agreed replacement of the numerical draft, general487-488, 17 October 2026. This accepts the specification, not an implementation, proof, integration or run.  
**Target completion condition:** Replace the existing exact Fraction pressure-jet arithmetic with the shared native mpq route while reproducing its interval operations, outward enclosure rounding and observable contracts; satisfy D5 dependencies and the P4 proof sequence below before owner/coordinator acceptance.

## 1. Current evidence and authority

Paths in this document: `T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`; `PS = T/ps`; `CK = T/ck`; `A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`; `R = T/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1`.

| Primary source | Reviewed identity | Relevant contract |
| --- | --- | --- |
| `PS/HANDOFF.md`, section 3 | SHA256 prefix `02147e2c9e52` | P4 is design hand-over only; route owner, base, prerequisite, assignment and proof sequence. No next command until assigned. |
| `PS/c/full3/src/atlas_tectonics/integration_pressure_coupling.py` | SHA256 `7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e` | Exact P3 reference: `_jet_mul`, related shortcuts, interval rounding and precision context. |
| `PS/c/full3/PS_COMPOSITION.json` | SHA256 prefix `f46407debea1` | Selected `test_only` and `record_identity` fields: test-only composition, byte-identical numbers with execution identity changes (D-b). |
| `CK/HANDOFF.md`, section 3 | SHA256 prefix `1c0fe29c5da6` | D5 REFUTED, seven defects, required repairs and proof; D6 diagnostic question remains open. |
| `CK/d5/DESIGN.md`, sections 3, 6 and 9 | SHA256 prefix `b91565297dc6` | Shared primitives, Policy A and native dyadic rounding. Later handoff repairs supersede refuted design/interface claims. |
| `CK/d5/src/integration_exact_twin.py` | SHA256 prefix `205453c148f3` | Saved shared candidate and native rounding helper; this remains refuted code, not the repaired interface. |
| `CK/d5-f2/atlas_tectonics/exact_arithmetic.py` | SHA256 prefix `84fc2127a86c` | Provider selection at module import; `library()` returns that selected library. |
| `R/width_gate.py` | SHA256 prefix `4c31a92f6880` | Record-width projections and units; no coefficient-compression authority. |
| `A/.atlas-dev/plan-status-20261016.md` | SHA256 prefix `be270e6898e0` | P4 unbuilt, D5 excluded from assembly, current order and unchanged acceptance boundaries. |

The P3 base is `c/full3`, not an integrated P4 runtime. The Pressure handoff records P4 as unknown in N12 s4. Acceptance of [Plan 06](plan-06-d5-exact-arithmetic.md) did not repair or land D5. Its saved candidate remains refuted and off N12; the existing owners retain their work and any pre-existing authority for their own repairs.

This document grants no implementation, queue, integration or publication authority. N9 remains PAUSED BY USER (general319); fresh interval and individual run holds remain in force. Reopen the current owner/status records when a later implementation assignment is made.

## 2. Preserve the actual reference operation

P4 is an exact-arithmetic speed substitution. The baseline already uses exact rational interval endpoints via `Fraction`; it is not a repair for floating-point catastrophic cancellation. There is no measured P4 speed or memory result yet.

`_jet_mul(a, b)` acts on three interval-valued derivative components. On its general path it computes, with the reference interval operations and grouping:

- component 0: `a[0] * b[0]`;
- component 1: `a[1] * b[0] + a[0] * b[1]`;
- component 2: `(a[2] * b[0] + 2 * (a[1] * b[1])) + a[0] * b[2]`.

The general result passes through `_jet_outward`. These expressions describe the existing operation; they are not an arbitrary-degree scalar Taylor/Cauchy-product interface. Preserve the reference interval endpoint/sign rules, operation order and representation.

Before the general path, `_jet_mul` checks each operand for constancy and uses `_jet_scale`. Preserve its zero result, identity return and constant shortcuts, including caller-observable object sharing. `_RadialJet` carries an exact radial expression local to a calculation: equal interval endpoints do not prove expression identity, and this metadata must not be invented or propagated through arbitrary arithmetic.

Do not introduce a new jet class, centroid field, scalar coefficient array or a separate arithmetic engine. The future owner must establish the native entry and conversion boundaries against this pinned reference and the repaired shared primitives.

## 3. Preserve existing outward enclosure rounding

The existing `_jet_outward` bounds derivative arithmetic, never physical coefficients or stocks. It uses `denominator = 1 << _JET_PRECISION.get()` and rounds each interval pair using `_dyadic_outward(pair, denominator)`. This rounding is already part of the reference enclosure; P4 must reproduce it identically.

For positive denominator `d`, the lower endpoint is rounded down to `floor(lo*d)/d` and the upper endpoint up to `ceil(hi*d)/d`, including negative endpoints. Preserve the source's exact numerator/denominator arithmetic and conversion semantics. A single away-from-zero scalar rounding is not an interval enclosure substitute.

`_JET_PRECISION` is context-local (default 128); the angular integration request derives and sets its precision. Preserve that request calculation, concurrent-request isolation and the `finally` cleanup/reset on success or refusal. Do not replace request-derived precision with the default. The unchanged enclosure-width and leaf-budget acceptance still apply.

The shared native helper is `dyadic_outward(lo, hi, denominator)`. It returns native endpoints internally; the P4 boundary must preserve the reference pair, canonical Fraction outputs where required, precision, bit-count semantics and output alias/pickle behaviour. Retain existing rounding locations and shortcuts. There is no new coefficient compression, approximation tolerance or energy-conservation claim in P4.

## 4. Shared provider, accounting and lifetime

Use the repaired shared module and the established provider. In the retained source, `exact_arithmetic._select()` runs at import; the twin calls `X.library()` at initialisation. This is not a new lazy-loading requirement. Do not add a direct unconditional `gmpy2` import to the twin or P4 path. Python mode never imports gmpy2; auto mode can select Python when the native backend is unavailable; an explicit unavailable, untested or unsealed native request fails. Preserve the provider's handling of process-resource errors and native-file identities. A native calculation failure is not retried on another backend.

Preserve the shared type, shape and loaded-object guards. Unsupported or instrumented cases follow the unchanged reference route with its errors; eligible native results return through the required reference types. No native object escapes into returned or persisted state. Preserve required fresh Fraction construction and reference shortcut identities rather than introducing new shared results.

The required repaired interface is `_work(bits, count, budget, *, pairs=0)` with `lease = _work`. This is required work: the saved candidate still exposes the old lease signature. Use reference-derived widths and reservation counts, not widths inferred after converting integers to mpq. Preserve the reference reservation amount/category and observable ordering. Apply the repaired width-decline checks before reservation/native work at the relevant entry points; never allocate a result and then decide whether its size was admissible. The shared native ceiling and the compact-record integer bound are distinct contracts, not interchangeable thresholds.

Retained natives use Policy A: shared `_settle` plus the surcharge over the reference allowance in `NATIVE_RETAINED`. This only adds accounting and may refuse earlier, never admit later than the reference. Preserve reference reservations, ordinary exception behaviour, appropriate lazy retention acquisition and release on success/refusal. P4 must not waive the D5 repair requirements or the still-open D6 question about persisted failure diagnostics and budget-statistics categories. Resolve and communicate that question through the existing D5 owner/coordinator handoff.

## 5. Width rules remain separate

The compact-record integer ceiling is **1 MiB = 8,388,608 bits**. The actual width gate projects from current width `W` and previous width `P`: the next width `W + (W - P)` must be at most 50% of that bound and the following width `W + 2*(W - P)` at most 100%, under the gate's existing record/field rules.

The recorded 24.5% value is a historical observation, not a fixed 25% acceptance gate. The removed draft's 262,144 bits equals 32 KiB and establishes no P4 threshold. `width_gate.py` records and checks widths; it does not round or change values. Preserve its existing contract and the separate N9 authority boundary. No coefficient-triggered rounding is authorised by either percentage.

Exact field/number parity remains the default, with only explicitly approved identity translations and the bounded N9 design exception in their own scope. Keep the existing scientific bounds and 12 GiB tree-RSS, 1 GiB free floor, 16 GiB logical, 256 MiB scope, 1 MiB integer and 256 accepted-step limits. Do not silently repin, change environments or overwrite historical evidence.

## 6. Future implementation and proof sequence

1. Complete the existing D5 repair, owner review/proof and shared-primitive landing requirements. Plan approval alone satisfies none of them. Keep D6 explicit and retain the batched coordinator/Geometry/Pressure handoffs specified by D5.
2. After that prerequisite, the coordinator assigns P4 to Kernels or Pressure. The assignee selects and records the actual candidate files, guarded integration boundary, source identities and proof commands. No decided P4 implementation/test filename, runtime hook or next command is supplied here.
3. Implement the source-bound native operation and conversion/lifetime boundary in the assigned revision. Preserve the P3 reference and old evidence. Do not edit another owner's files or an in-flight composition.
4. Run the stipulated focused checks and mutants, one independent refuter and a small A/B using the authorised route. Cover constant/zero/identity shortcuts; interval signs and exact endpoints; existing outward rounding and request-context cleanup; backend selection and loaded identities; output types, alias/pickle behaviour; near-limit budgets, refusal/error ordering and retained-native release. Compare all required records and arrays byte-identically. If execution IDs move, use the approved D-b/null-control method; an unexplained difference remains a failure.
5. Submit the timed-proof REQUEST through the coordinator after the prerequisites. Report actual commands, pinned inputs/candidate, outputs, resources and baseline/candidate measurements within the proven scope. A small A/B is not full-scale acceptance, and no unmeasured saving or ticket is implied. Follow the current queue rules; preserve existing holds and historical receipts.

There is no substitute gate based on only non-degenerate comparisons, imagined float cancellation or a fixed count of arbitrary convolutions. Implementation, proof, integration and publication remain separate states. Assembly/retest dispositions are made from the accepted owner evidence; this document does not mark the N12 row complete or schedule those stages.

## 7. Completion conditions

- [ ] D5 repairs, proof, D6 disposition and shared-primitive landing are evidenced through the existing owner/coordinator process.
- [ ] The coordinator has assigned P4 and the owner has recorded the actual candidate and integration boundary against the pinned P3 reference.
- [ ] The candidate preserves the interval operation, existing enclosure rounding, provider, accounting, lifetime and observable reference contracts, including the approved Policy A earlier-refusal exception only.
- [ ] Byte-identical records/arrays, any required D-b null control, focused checks/mutants, one refuter and the small A/B meet the stipulated bar.
- [ ] The coordinator-requested timed proof and owner acceptance are recorded with scoped measurements; any subsequent integration/assembly disposition is explicit and does not release unrelated holds.

Related work: [Plan 07: P1-P3 proof](plan-07-pressure-p1-p3-assessment.md), [Plan 04: paused N9 tools](plan-04-n9-width-tools.md), and [Codex's post-reveal source corrections](../discussions/atlas-plans-39-review-20261017/codex-plan-08-turn-02.md). The frozen independent reviews remain unchanged.
