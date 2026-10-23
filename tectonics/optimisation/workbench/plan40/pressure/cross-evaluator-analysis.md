# Cross-evaluator exact-work elimination — bounded author findings

Historical source/prototype analysis. Current implementation selection, measurements and resource qualification are in [FINDINGS.md](FINDINGS.md) and [the receiving implementation](implementation/README.md). Statements below about proposed work or unproved production contracts describe this earlier evidence, not the current selection. This public copy removes local coordination and paths; it does not authenticate a rerun.

Status: two new source-supported candidates; no production implementation, timing, stage launch, worker, survey edit or scientific acceptance. Primary recommendation is callback-local repeated profile/donor-integral reuse. Repeated donor-polygon wedge preparation is a separate preparation candidate. Whole native/reservoir refinement-tree reuse is rejected under the current exact-record contract.

## Source identity and scope

Repository-relative source identities were freshly checked before reuse. This work uses the selected Plan19–20 source map, not another similarly named source copy.

| Source | SHA-256 |
|---|---|
| C: `tectonics/optimisation/pending/pressure/c/full3/src/atlas_tectonics/integration_pressure_coupling.py` | `7c2c3b992d7e0267ed4da70dc5f6ba1bc557f3a2105369ca2b2abefa4e52d05e` |
| P: same directory, `integration_spatial_pressure.py` | `1f4f50ccb08eaeeab2a52c30dce033aa4b1fb07273a59ebd619d89f233c33712` |
| D: `tectonics/optimisation/pending/pressure/c/full/src/atlas_tectonics/integration_differential_pressure.py` | `e01a7af268de50560f631dce4ea3b69163e1a6bcc63c436bb18001bb579c4e4b` |
| PW: `tectonics/optimisation/workbench/plans10-12/source/src/atlas_tectonics/integration_pressure_walls.py` | `cdaed72fcabb9bf15d310f36c75944a2fd473ec9340829abdac09525e3e566ed` |
| I: `tectonics/optimisation/composed-r2/helpers/pressure_indexed_patch.py` | `315537284fd3aa4d461a0983bb087c78453de0811e432503ad59a585ba4f1c16` |

The original, pre-publication `wall-constraint-analysis.md` identity is `f805dfee462c648c98cdf74b349a3cd0a99c7b1ea32704dadd5fdbe39c5adcfa`. This investigation does not repeat its local vector CSE, immutable region preparation, indexed constraint decoding or midpoint-value investigation. It changes neither full-jet algebra nor sign primitives.

## Selected caller can generate duplicate donors

This is source reachability, not merely injected duplicates:

1. D `current_regions`, lines 306–307, creates native voxel regions with `plate_id=None`, density from the current EOS, empty cone and the full `(support_radius, radius)` radial range. Indexed dispatch likewise preserves native region semantics; it does not deduplicate donor contributions.
2. D lines 455–465 constructs one mantle row `profile=((rc,radius,mantle_density,surface_pressure),)` and calls `_wall_results(...,(profile,profile),...)`. PW `_selected`, lines 195–199, selects a native region with `side=None`.
3. For an exact pose, a voxel that crosses the radial wall has signed vertices on both sides. C `wall_polygon`, lines 186–219, then returns `contact=None`. P lines 403–405 assign both side weights exactly one half. This is an ordinary allowed crossing, not a boundary tolerance or approximate equality. A zero-density anomaly is filtered earlier; the example uses a nonzero anomaly.
4. P donor construction, lines 595–610, loops region, side, profile in that order and appends each nonzero row. Both sides use the same shape, clipped lower/upper radii and density. With D's identical profiles, their coefficients also match. There is **no donor deduplication** before C receives the tuple.
5. C partitioning, lines 654–670, preserves distinct donor indices in its event keys; lines 672–673 retain the sorted active rows in each piece. For each shared angular segment the two rows therefore retain exactly equal `(entry,exit,bottom,top)` supports. C `evaluate`, lines 675–700, computes their radial integrals twice.

The executable fixture extracts P's actual donor-construction statements through AST. Given a native crossing region with density 3301, reference density 3300, gravity 7/5, support 1–20 and the two exact half-weights, it emits two identical donor rows with coefficient 7/10. The crossing weights and prepared polygon are bounded fixture inputs; the test does not claim to have constructed or run a complete issued native state. The source chain above establishes why those inputs are reachable. Actual run prevalence remains unmeasured.

Different coefficients on identical support are possible in the general P interface and are covered by signed controls, but are not claimed as the ordinary selected-D two-side pattern. Equal coefficients already justify the optimisation: both original contributions must still be scaled and accumulated separately.

## Candidate A: reuse a complete scalar donor integral within one callback

The candidate keeps a bounded dictionary, at most eight entries, local to each invocation of C's nested `evaluate`. Its key is `(entry,exit,bottom,top)`. On a miss it runs the original `_radial_interval_jets`, existence branch, `_donor_radial_pressure` and nonselected enclosure multiplication in exactly the original order. It retains either the exact scalar jet plus `(selected,ordered)` flags or the original impossible-support result. It then executes the original coefficient scaling, `_jet_add` and `fixed &= ...` for **every original row in original order**, including hits.

This eliminates repeated radial-edge reciprocal/multiplication, branch comparisons, endpoint powers and donor primitive construction. It preserves all original rounding sites in each executed contribution; a stored result is the identical result those deterministic operations would produce again. No coefficients are combined, no rows are reordered and no cancellation is inferred. Opposite coefficient rows remain separate. Full derivative jets are retained, so this also applies to the first interval evaluation; it does not depend on midpoint-value support.

The omitted key context is fixed by the cache lifetime: the same `s`, receiver `low/high`, `left/right`, callback `bits` and `_JET_PRECISION` value apply to all rows of this single invocation. A cache must never survive into another interval, midpoint, precision or receiver callback. The first matching row always computes normally. Misses beyond eight entries compute normally without storage; no eager precomputation changes first-failure order. The prototype does not cache exceptions.

An edges-only key is unsafe: a deliberate fixture holds the edges fixed but changes radial support 2–12 to 5–6; the original donor integrals differ. The test confirms this fault. Identity by value interval alone, by region index, or by coefficient is likewise insufficient.

Sixty bounded synthetic callback controls passed exact equality of **all three jets' value, first derivative and second derivative pairs, plus the fixed flag**. They cover interval and midpoint calls, 96/160-bit precision, the selected two-side pattern, positive/negative coefficients, separated duplicates, empty supports and capacity overflow. Across these mixed controls: interval products 22,550→19,670; outward rounds 19,656→16,866. These aggregate controls are deliberately mixed and are not a workload estimate.

A subsequent two-callback selected-pattern control, not another full-suite run, retained these counts:

| Primitive | Interval original | Interval reused | Midpoint original | Midpoint reused |
|---|---:|---:|---:|---:|
| `_mul` | 511 | 382 | 299 | 245 |
| `_scale` | 234 | 176 | 164 | 130 |
| `_add` | 291 | 214 | 165 | 133 |
| `_dyadic_outward` | 438 | 324 | 276 | 219 |
| `_divide` | 12 | 10 | 12 | 10 |
| `_sqrt` | 2 | 2 | 2 | 2 |

Both callbacks use full jets at precision 96. The interval fixture is `fixed=False`, while its independently evaluated midpoint is `fixed=True`; the current integrator would not request that midpoint for this coarse interval. They are separate operation controls, not a claimed pair of consecutive actual integrator calls. Each has one miss and one hit, with one retained entry. No measured runtime or whole-pressure/IV percentage follows from these counts.

### A2: retain repeated profile integrals too

The same selected caller also duplicates profiles. P line 594 flattens `(profile,profile)` into two identical radial-profile rows, each weighted 1/2. C lines 680–690 repeats `_radial_interval_jets` and the entire `_positive_interval_primitive` for each row before applying that weight. The final prototype adds a separate callback-local eight-entry profile cache keyed by `(bottom,top,rho,ptop)`. Its value is the completed original scalar jet and selected/ordered flags, or the impossible-support sentinel. It preserves the original weight scaling, ordered addition and fixed-flag update on every row. Receiver edges, chart, gravity, precision and interval are fixed within this callback. No cumulative-pressure assumption or bounds-only equality is used.

There are at most **eight donor plus eight profile entries, sixteen total**. Both caches are lazy and callback-local. The first profile row follows the original computations; its second exact match reuses that preweighted result. The donor-only 60-case result above remains predecessor evidence; it is not relabelled as a combined-cache suite. The changed combined implementation received only the focused two-callback selected-pattern control, one same-bounds/different-rho-and-ptop control, and the scalar coalescing refutation.

| Primitive | Interval original | Combined reuse | Midpoint original | Combined reuse |
|---|---:|---:|---:|---:|
| `_mul` | 511 | 297 | 299 | 191 |
| `_scale` | 234 | 137 | 164 | 102 |
| `_add` | 291 | 167 | 165 | 104 |
| `_dyadic_outward` | 438 | 252 | 276 | 171 |
| `_divide` | 12 | 8 | 12 | 8 |
| `_sqrt` | 2 | 2 | 2 | 2 |

These are the same independently sampled full-jet interval/midpoint contexts and retain the same `fixed=False`/`fixed=True` caveat. Complete jets and flags match exactly. In the unequal-profile control, changing both rho and ptop while retaining bottom/top produces two profile misses and still matches; the cache may not use bounds alone. The combined result's cache counters include that third control, while its two per-case operation tables exclude it.

Coalescing even equal weights is explicitly refuted using original source arithmetic: at precision 3, jet value `(1/8,1/8)`, derivative `(1,1)`, second derivative `(0,0)`, two separate half-scaled contributions followed by addition produce value `(0,1/4)`. A single scale by their sum, one, returns `(1/8,1/8)`. The probe checks both values. Reusing the preweighted jet preserves these two scale operations and the original addition; merging coefficients does not.

## Candidate B and rejected cross-call sharing

| Examined path | Disposition and reason |
|---|---|
| PW native/reservoir active-region preparation | Already shared by P2 `_held`; no new saving claimed. It includes wall-local plane filtering, polygon construction and contact weights. |
| C donor polygon `_angular_wedges` | New exact preparation reuse is viable. P appends the same immutable polygon for multiple sides/profile bands, and PW repeats donors for native/reservoir receivers. `_angular_wedges(poly)` depends only on the exact ordered polygon; it performs a scan over all edges for each angular knot interval. Reuse its complete tuple, retaining all original donor indices/events and order. |
| Whole angular partitions/refinement heaps across receivers | Rejected. Receiver wedge limits clip donor events, receiver radial bounds affect every integral, and width/max-leaves determine precision and heap stopping. Different receivers or strip-route widths are not interchangeable. Extra shared subdivision also changes retained bounds, leaf count, serial order and potential refusals. |
| Cross-call donor scalar jets | Rejected without a much larger exact key and budget design; receiver bounds, angular interval, precision and source expression identity all matter. Invocation-local reuse avoids this state entirely. |
| Whole constraint/face proof verdicts across walls | Rejected. `_face_on_wall` depends on the current wall cross product and its pose history; a plane proved coincident with one wall can be oblique to another. I already retains decoded exact constraints; P2 already suppresses repeated face preparation for one native/reservoir wall set. No new proof-verdict cache is justified here. |

A two-receiver synthetic partition control uses four donor rows sharing one shape. Reusing complete wedge tuples reduces `_angular_wedges` evaluations from ten to two while preserving exact ordered `pieces` and every `coefficients(data)` tuple. The fixture bounds its shape cache to four entries. This proves data equivalence in that fixture, not production memory admission. Within-call duplicate-shape reuse is the narrower first implementation. Extending it across native/reservoir calls must solve retained ownership below; it must not borrow data after a closed partition lease.

## Resource, error and lifetime contract

The proposed cache is **not yet production-ready**. Existing tests replace `_work` and partition reservations with no-op fixtures and validate no ledger, cancellation or worker lifetime behaviour.

For A/A2, retain the original per-callback `_work` admission unchanged. Each of two caches has at most eight entries (sixteen total), each retaining a four-field key, a three-pair scalar jet and flags (or an empty sentinel); they retain no derivative DAG or parent callback. Rational payload widths remain governed by the actual admitted callback coefficients/precision, but a byte bound must be derived from that envelope rather than treating sixteen entries as sixteen small numbers. Include both dictionaries' tuple/header costs and aliased versus independently owned rational payloads. Keys and source radial expressions must be immutable. Both caches must disappear when the callback returns or raises, before the next interval/midpoint work admission.

If the existing operation reservation cannot demonstrably cover this additional peak, use an optional scratch admission that can decline caching before allocation, then run the original uncached callback. The absence of cache space must not introduce a new numerical refusal. A cache does not need an unknown-constancy fallback: it stores a completed original full-jet result. On a computation exception, propagate it with original source context and release scratch; never catch generic arithmetic/resource/cancellation exceptions and pretend they were cache misses. First-row numerical failure still occurs at its original location. No cancellation checkpoint exists inside these arithmetic-only helpers; preserve all surrounding original admissions/checkpoints and any explicit future callback checkpoints.

For B, a cache kept after `_integrate_radial_pressure` returns outlives its partition reservation. It therefore needs a named wall-set owner with a valid retained-memory charge and bounded shape/result payload. Such a new live charge can reduce headroom for the next original reservation and change refusal behaviour. Do not claim optional-cache equivalence merely because its own reservation succeeded: either prove coverage under an already-live adequate reservation, or relinquish optional retained data before it can cause an otherwise successful original admission to fail. Without that proof, limit reuse to one admitted partition call and clear it before leaving. Hit/miss must remain lazy; first computation still produces original errors.

Later implementation checks must verify actual scratch admission/refusal, zero retained cache after exceptions, unchanged original admissions and cancellation, complete output/leaf/record equality and source/refusal notes. The probes establish numerical feasibility and a concrete reachable duplicate, not these production contracts. Production selection still needs representative duplicate prevalence and, if desired, separately admitted timing; neither was performed here.

## Reproducible evidence

`cross_evaluator_probe.py` depends on the already reviewed sibling helper `midpoint_value_probe.py`, pinned to SHA-256 `d08ad403068a7f5e8690c4e3959a038f584e50a67f836537ad356ef2e2f25f0a`. It extracts the original full-jet callback and preserves its final scaling/addition statements. It does not install the midpoint-value candidate. Coupling, vector, spatial and differential source identities are checked before the relevant controls. `-O` is refused because assertions enforce acceptance.

Commands, using the installed review Python with bytecode disabled:

```text
python -B cross_evaluator_probe.py --repo REPO --support-probe midpoint_value_probe.py --output cross_evaluator_result.json
python -B cross_evaluator_probe.py --repo REPO --support-probe midpoint_value_probe.py --selected-only --output cross_evaluator_combined_result.json
```

`cross_evaluator_result.json` is the retained 60-case donor-only result. `cross_evaluator_selected_result.json` retains its isolated donor-only operation counts. `cross_evaluator_combined_result.json` records the final combined-profile/donor focused checks. The final script's default broad mode has not been rerun after adding profile reuse; the command documents reproducibility, not an already completed combined broad run. No previous 172-case midpoint suite was rerun. Native Ruff check-only `F821,F841,B905` is clean on the final cross-evaluator script. All evidence remains explicitly synthetic. No production source changed in this prototype investigation.
