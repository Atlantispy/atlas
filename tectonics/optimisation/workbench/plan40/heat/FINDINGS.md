# Plan40B: source-bound heat arithmetic examination

WORKING NON-CANON. Examination accepted in final review on 23 October 2026; no proposed
optimisation below is implemented, enabled or timed. This is the heat workstream
of Plan40, not a new plan or work package. Pressure 40A and the later native
kernel design retain their separate acceptance requirements.

The most promising additional work is exact polynomial reuse inside the existing
admission sequence, followed by reuse of immutable reconstruction preparation.
The smaller opportunities remove demonstrably redundant construction or repeated
conversion within an owned calculation. There is no measured whole-interval gain
for these proposals. Heat's importance to interval time is a reason to prioritise
its repeated work, not to add overlapping historical speedups.

The [additional examination](ADDITIONAL-FINDINGS.md) records C12–C20 from the
requested further search, including flux/polygon work, shared observation
enclosures, retired inverse columns and repeated conversions. It also records
the repaired control-entry boundary. These additions and the repair are accepted
in the affected review; the original C1–C11 numerical conclusions remain unchanged.

The accepted examination covers all 20 candidate dispositions, 44 named source
bindings and six control/result pairs. Acceptance does not implement or qualify
the proposed optimisations.

## Source generation and evidence boundary

The examination starts from commit `0a2855125b79abcb4e05cf090adf46dcc8b1c80b`
and the [637-member selected source map](../../plans19-20/SOURCE-MAP.json), SHA-256
`ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc`.
Its public selection identity is
`dce2275046a2f8f9deb809bdb8a02e90bee65f777bb70919048e2c5ef583befb`.
[SOURCE-BINDINGS.json](SOURCE-BINDINGS.json) records the examined numerical and
consumer files, exact public bytes and original private digests. A selected
member is not necessarily an executed branch. Public sanitisation is not a
runtime binding and does not authenticate a historical private run.

The selected chain retains H1a/H1c exact-growth `35e77650…`, L1 low-ledger
`462bf6a2…`, H2 inside the H3-overlaid certificate (private `4099a297…`, public
`09ae26a2…`), compiled dot `e0be3a30…` and current certificate inventory
`40943b9c…`. The standalone H3 inventory `3c8f9725…` and H2-only kernel
`3be44650…` are earlier generations. The selected forward `de344f47…`,
closed-owned r5 `6da4964c…`, finish r11 (private `e5a2409f…`, public `46c4b132…`)
and cold reader `791899ac…` are retained. They must not be replaced by older
lf3 repair-only consumers. Current selected heat workers are eight in the
candidate fresh driver; the global helper default remains six. This examination
does not retune workers or activate H3.

Retained evidence is reused from [Plans10–12](../../plans10-12/README.md),
[Plans13–14](../../plans13-14/README.md) and [Plan15](../../plan15/README.md).
The original q10 failure, q32 historical NOT_REPRODUCED, q06 loaded-identity
failure and q52 admission failure remain historical failures. The later successful
proofs do not rewrite them. The strict saved Heat comparison covers five arrays,
four cell accounts, the face account, three scalars and private records;
174 captured Heat-source correspondences and nine separate marker controls
establish different boundaries. Neither driver was captured in that numerical
pair. Current public combined-runtime qualification remains unestablished.

The earlier native-kernel diagnosis is D5/P4-only. Its inclusive validation,
conversion and accounting shares are not a heat profile. q22's prof-lh worker
aggregate is also not wall time or a profile of the current selected H3 stack.
No absent sampled branch is treated as globally unreachable.

## Complete coverage and disposition

Names below are selected member basenames resolved by SOURCE-BINDINGS. Candidate
labels C1–C11 are local table references, not new plan or backlog identifiers.
“Useful” means a defined implementation scope supported by source analysis and
bounded controls; it does not mean measured benefit or implementation acceptance.

| Selected path and previous coverage | Further mechanism / disposition | Applicability, proof, resource and consumer obligations |
|---|---|---|
| Exact-growth `Arithmetic.reserve/rational`, low-ledger `RationalGrowth.op/slot` | H1a/H1c/L1 **already covered** cache/inline overhead. C1 concerns repeated numerical products above these guards. | Keep reviewed-resource/base-method guards, original operand reads, prospective limb bounds, cancellation, source pins and fallback. Broad admission/sampling changes remain Plan34. |
| Functional support basis `Basis.point`; cubic basis of 20 terms | **C1 useful:** reuse exact monomials after the same original admission positions. A bare reordered polynomial DAG is rejected. | Per-point immutable rational operands only; preserve all reference guard/poll positions and conservative refusals, output order and exact canonical values. Retain logical admission counts and separately disclose actual/reused native work. Fund reference metadata before use; do not create a global value cache. |
| `functionals_kernel_r5._prepare/_face/_vector`, parallel parent preparation | **C2 useful:** per-forward preparation and same-face exact support/basis reuse across actual refinement calls. Different faces are not automatically the same matrix. | Bind payload, geometry, boundary keys, conductivity, support order and exact source generation. Keep child admission/identity and every per-face certificate. Release with the forward owner; charge retained/replacement overlap. MPFR Gram/inverse/rho cannot cross precision changes. |
| Certificate `Arithmetic.dot`, compiled `_product/_pair_dots` | H2 frame fusion and H3 eligible sign classes / restricted Gram symmetry **already covered**. **C3 useful:** a degenerate signed-zero product can avoid its eight corner multiplies while retaining the first-corner zero sign and both ordered additions. | Exact finite MPFR endpoint tuples and reviewed contexts only. Do not delete a whole zero term. Nonfinite/unsupported operands use the original route; preserve ternary, precision, flags, block cancellation and input custody. No production zero-density or timing claim. |
| Gram construction and approximate inverse in `solve_enclosure` | **Reject** unconditional Gram symmetry, exact-dot-then-one-rounding, reassociation/FMA, identity/diagonal inverse shortcuts and changing pivot order. Existing approximate inverse remains an untrusted proposal. | Zero-ended intervals can break signed-zero symmetry. Each Gram corner and accumulation rounding point affects the enclosure; the subsequent defect proof does not authorise changing certified records. No tolerance, precision ladder or method change. |
| Same face, complete-shell support expansion in `_face` | **C11 useful, conditional:** retain completed rounded Gram accumulators at a nominated precision and continue their original fold through appended observations. | Basis is created once; the matrix grows by append. Require identical ordered prefix, keys, basis/frame/scale, column selection, precision/context, source and live owner. Retain all endpoint signs/ternary values. Recompute inverse, proposal, defect, residual and radius. A failed attempt currently drops its Gram: introduce an explicitly charged completed-Gram owner, never retain its traceback. On mismatch or unavailable cache, use the complete reference; no cross-precision reuse. |
| RHS proposal and residual singleton tuples in `solve_enclosure` | **C4 useful:** lazy per-index midpoint reuse and one owned xhat interval list. | Cache first midpoint at its original evaluation position, not before earlier operations. Same precision/RHS/inverse-call lifetime; no subclass/instance-method bypass. Exact output/flags and unchanged check traces tested. Keep old conservative interval allowance; new midpoint references must be funded. |
| Inverse defect `R*A`, residual `b-A*xhat`, `R*residual`, physical bounds | **C5 useful:** reuse prepared RHS endpoint-address/class arrays within one defect loop; retain row consumption and fallback. **Reject** treating defect as symmetric or skipping norm/residual work. | For rank n, current defect loop prepares the same n-by-n RHS in n batches. Bind immutable endpoints, strong references and exact contexts to an owned solve-local handle. Preserve row ordering, every subtraction/abs/upper sum, rho<1, eta and radius; charge live buffers and release on cancellation/fallback. Larger full-result batching is not selected because it adds n² live outputs and moves refusal timing. |
| Physical conversion, singleton refinement, Decimal80 enclosure gate, exact export in certificate r1/r3 | Exact forced values, precision retries and fast rational-to-Decimal conversion **already covered**. Keep full range validation and exact endpoint export. | A singleton screen is necessary, not a feasibility proof. Same-precision output equality and signed-zero gate remain. No conversion cache across attempts or mutated caller matrices. Export requires additional admission while MPFR arrays remain live; release failed attempt frames before the next precision. |
| Exact rank, modular lower bound, canonical independent columns and original-column certificate | **Already covered** reduced rank, primitive integer rows and common-factor work. **Reject** modular-rank-only acceptance or skipping original-column certificates. | The unlucky-prime control demonstrates canonical-order fallback; identical feasibility alone is insufficient. Preserve first independent columns, incompatible witness and all exact original checks. |
| Exact functional / exact-face fallback Gram and moment verification | **Reject as a free exact-record change** triangular Gram elision or zero-coefficient Bareiss row skipping. | Exact values are symmetric, but the counted arena and refusals are observable. Bareiss still scales a row by pivot/previous when its elimination coefficient is zero. Full original physical moment checks and admitted fallback remain. |
| LOW r5 constant shortcut, singleton assembly and sparse r1 SuperLU | Exact loaded-bound constant case, physical order and target checks **already covered**. | Constant means exact equality, never a tolerance. Sparse r1 genuinely uses its binary64 matrix: C6 below does not apply. Preserve exact global ledger and per-cell/public bounds. |
| HIGH `decimal_sparse_core_r2._solve` unused approximate matrix | **C6 useful:** replace unused binary64 CSR→CSC construction/sort with its exact appended-entry count. | Preserve every float conversion/truth test in sorted unique-column order, support refusal and `approximate_system_nnz`. Actual RCM uses a different Decimal-support matrix; actual factorisation uses MPFR. Retain old conservative reservations/diagnostics initially. Test the actual changed consumer before adoption. |
| HIGH MPFR factor/solve and correction residuals | Factor reuse **already covered**. **C7 low priority:** factor-owned ordered triangular-entry views. **Reject** warm-start/residual elision and Decimal→MPFR residual substitution. | Initial solve plus conditional corrections use one immutable private factor; direct mutable factor dictionaries are ineligible for cached views. Preserve insertion/pivot order, every rounded operation and all residual/correction history. Extra tuple/index storage needs admission; measured benefit is unknown. |
| Assembly r1 `_scale`, r2/r5 owners, refinement intersections | **C8 useful:** exact rational +1/-1 scaling in validated cell-owner contributions. Unchanged-row sharing **already covered**. **Reject** subtract-old/add-new interval aggregate update. | Preserve exact endpoint types/order, distinct owners, per-owner checks, additions and Contribution records. `[-hi,-lo]` is exact rational negation, not rounded MPFR algebra. Interval subtraction is not an inverse; retain ordered full sums and disjoint/reversed-certificate refusal. |
| Forward/issuer source load and boundary debit | **C9 useful:** construct old+source once, retaining a distinct boundary-debited array. | Removes n exact additions for n cells; reuse is local to one immutable input state. Original load must survive boundary mutation. Extend custody/charge explicitly and keep receiver recomputation and source checks. |
| Closed-owned r5 / finish r11 endpoint and interior scalar search | S1 endpoint certificate reuse **already covered**. **C10 lower priority:** retain only the latest feasible interior certificate and its exact state for the final reuse check. | Saves one final duplicate only on an interior outcome, not the 64-step search. Preserve nonmonotone predicate sequence/history, final theta/state equality and stale-state refusal. Fund retained state/proof plus replacement overlap; no unbounded certificate cache. |
| Projection, checkpoint, joined/CAS, restored/RAM and native cold consumers | Current witness and consumer binding **already covered**; no generic trusted-caller shortcut. | Forward output alone is not the entire boundary. Preserve public array equality, conservation, private certificate records, immutable ownership, source/runtime checks, close/borrow/recovery rules and physical keys. Rebind only a new selected generation after implementation review. Plan21 retains separate S9 identity work. |

## Proposed implementation order and stopping conditions

1. **C1 exact polynomial reuse:** the strongest broadly repeated arithmetic
   opportunity found. Implement under the existing point owner and retain the
   original guard sequence. Compare all 20 values, full certificates, admitted
   refusals/cancellation and honest work counters; measure complete functional
   calls, including memo bookkeeping. A numerical DAG alone is insufficient.
2. **C2 immutable preparation reuse:** only the exact same prepared inputs within
   one forward lifetime. Same-face refinement offers actual repeated preparation;
   cross-face Gram/factor sharing is not established. Measure preparation plus
   retained-memory cost on a representative refined call. Keep precision-specific
   rounding work fresh. **C11** adds a distinct same-precision append-only Gram
   opportunity within a face. Start with at most one nominated precision cache,
   not one cache entry for every caller-supplied rung. For n=20 it retains 800
   MPFR endpoints plus metadata; actual memory is precision-dependent. Preserve
   full reference admission and check order, charge replacement overlap, and
   replay the full reference on exceptional compiled fallback. The benefit is
   conditional on complete-shell growth at the retained precision, not every face.
3. **C3–C6 certificate and HIGH construction:** implement as separately selectable
   changes so eliminated arithmetic, Python preparation and allocation are not
   conflated. C4 has an in-memory source variant; C3 has exact signed-zero and
   exceptional-operand controls; C6 has a complete source dataflow argument and
   tiny actual CSR/CSC comparisons. C5 needs a prepared native handle with its
   own custody and failure tests before any compiled acceptance.
4. **C7–C10 small or conditional reductions:** lower priority until the selected
   workload shows enough applicable work to justify their extra state. Their
   source-based dispositions are complete; the implementation/timing decision is
   separate. C10's maximum one-call saving is not a large search speedup.

No new implementation is assigned by this examination. A selected batch needs an
owner and owned successor files, changed inventories/consumer pins, exact focused
checks and required review. Start from the mapped selected generation; do not
overwrite frozen inputs. Keep the reference fallback and unchanged conservative
resource limits. Controlled timings require exact coordinator admission/GO;
optional retained preparation must fall back to the reference if its extra
custody cannot be funded, rather than add a new refusal or undercharge live data.
Before any queued worker proof, qualify actual dispatch/compatibility and strict
transitive imports without workers. If complete-call benefit does not justify
setup, checking, retention or conversion, retain the reference.

## Bounded evidence and arithmetic counts

[Certificate controls](examine_controls.py) / [results](CONTROL-RESULTS.json)
extract the exact selected numerical definitions with H3 dispatch disabled.
Nine rank 2/3/4, precision 53/80/320 comparisons preserve endpoint binary encoding,
precision, ternary, sign, proof scalars, context flags and check trace. Five
malformed/singular/cancellation cases preserve the failure and check trace.
216 zero-product cases cover both zero signs, both operand orders, three
precisions and extreme finite exponents; nonfinite operands retain refusal.
These are feasibility/refutation controls, not an imported production runtime,
native/JIT proof, resource qualification or performance measurement.
Four same-precision prefix-extension cases additionally compare all nine ordered
Gram dots (36 total) against a complete source-reference fold. They establish the
ordered accumulator identity only, not C11's new owner or native fallback.

[Solve controls](solve_controls.py) / [results](SOLVE-CONTROL-RESULTS.json) cover
MPFR output/flags and six cancellation positions, exact unit scaling, canonical
unlucky-prime fallback, Bareiss scaling and actual tiny sparse matrix count cases.
[Finish controls](finish_controls.py) / [results](FINISH-CONTROL-RESULTS.json)
cover scalar search/reuse, stale-state refusals, independent load/debit arrays
and the source-bound exact basis proposal. Their stated Fraction/GMP/resource
limits are retained; a logical control is not an admitted production proof.

| Workload / operation | Reference | Candidate | Absolute change | Change | Units / evidence status |
|---|---:|---:|---:|---:|---|
| Cubic basis point, native exact multiplies (C1) |105|16|-89|-84.762%|Source-derived operation count; original admission positions retained; not time |
| Degenerate finite-zero interval product (C3) |8|0|-8|-100%|Corner multiplies; both ordered additions remain; actual zero frequency unmeasured |
| Rank20 RHS midpoint construction (C4) |400|20|-380|-95%|Midpoints only, excluding 400 inverse midpoints; analytical count, not time |
| Rank20 fallback residual input tuples (C4) |420|20|-400|-95.238%|Tuple constructions, including attempted batch input; not RAM or time |
| Rank20 defect RHS endpoint preparation (C5) |8000|400|-7600|-95%|Interval visits only; proposed handle reuse, excludes left side and arithmetic |
| Interior final certificate search (C10) |67|66|-1|-1.493%|Certificate calls in logical fixture; endpoint-full 2→2, zero-only 66→66 |

For C11, retaining an old prefix of m observations removes those m interval
products per actually computed Gram dot on a subsequent append. H3 already
computes `400 - e*(e-1)/2` dots for a 20-column Gram when e rows are eligible
for its symmetry shortcut: the saved prefix terms range from 210m to 400m.
This is conditional arithmetic work, not a measured production frequency or
time reduction. It must not be added to H3's existing symmetry saving.

Three explicit refutations prevent invalid extensions: at 8-bit precision,
swapping `(-1,-0)` and `(-1,+0)` changes the dot's lower zero sign; dropping a
final zero term changes the final addition's ternary result; accumulating exact
products and rounding once changes the enclosure. Equal real algebra therefore
does not establish equal interval records.

## Retained performance, exclusions and limits

Change is candidate minus reference. These historical comparisons have different
or overlapping scopes; they must not be added or multiplied.

| Workload | Reference | Candidate | Absolute change | Change | Units / evidence status |
|---|---:|---:|---:|---:|---|
| q22 W4 lw→lf3 cumulative selected H1/H2/L1 + physical-order chain |109.625|80.742|-28.883|-26.347%|s, supervised mean, two observations/layout |
| q22 le3→lf3, L1 plus physical-order/startup/retention changes |88.024|80.742|-7.282|-8.272%|s; not isolated L1 attribution |
| q22 lf3→lh H5a |80.742|85.641|+4.899|+6.067%|s, regression; H5a not selected |
| Same H5a comparison, sampled tree mean |1089.473|1096.043|+6.570|+0.603%|MiB; no compensating measured RAM benefit |
| q25 H2→H3 component |89.570|84.950|-4.620|-5.158%|s; one unmirrored sample/side, imports/compilation included |
| Same H3 component sampled tree |1030|1376|+346|+33.592%|MiB; physical samples, not logical allowance/hard bound |
| Same H3 logical source layout |9816635|9841837|+25202|+0.257%|B; not runtime or interval storage |
| Saved combined Heat CONTROL observation |78.7677|73.3181|-5.4496|-6.919%|s; one base-then-joint pair, not robust final-stack timing |
| Same combined sampled tree |1144270848|1505419264|+361148416|+31.561%|B; sampled peak |
| q60 six→eight workers |74.4685|73.4765|-0.9920|-1.332%|s; two repeats/count; selected candidate, global default unchanged |
| Same worker comparison maximum RSS |1532248064|1945915392|+413667328|+26.997%|B, simultaneous supervisor+job |

q22's second samples were all slower by 2.001–9.312s. q60's six-worker span was
0.999s versus a 0.992s difference of means. These limits remain material. The q22
worker cProfile aggregate 284.8951766s, dot 50.414s, GMP multiplication 33.218s and
ledger-op 16.236s are scoped profiler quantities, not additive wall savings or
proof that checks can be removed. Isolated profiler overhead was not retained.

H5a remains disabled. Its retry requires the selected combined heat generation,
Plan34 attribution and an applicable complete workload/worker configuration,
including startup/construction/solve/certification, through the existing exact
queued harness. H3 remains candidate-only, not a performance-disabled method.
WP25 warm start remains unadopted because certified records differ; later HIGH
correction demand plus an identity-preserving variant or separate method
authority is required. WP15 compact payloads' heat regression, H5b memory safety
exclusion and S10 verify-every-call rule remain. No new proposal is relabelled
“implemented but disabled”.

The examination changes no mathematical method, tolerance, precision ladder,
conservation account, default memory limit, accepted-step ceiling, production
source selection or run hold. It supplies decisions to later Plan40/34 work.
No full-IV performance, new physical-memory bound, final runtime/restart proof,
scientific acceptance or completion of all Plan40 is claimed.

Prepared with OpenAI Codex assistance from the named local source and retained
evidence. No new external research or library installation was used.
