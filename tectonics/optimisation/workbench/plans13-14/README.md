# Plans 13–14: compiled heat certificates, finish reuse and observations

Implementation and selected private integration are complete.
This additive snapshot extends [Plans 10–12](../plans10-12/README.md) on the
optimisation branch. It preserves 618 selected source members, changes 11 and adds
five: 239 native and 395 helper files in total, with no removed predecessor.
H3 remains a candidate; this source integration does not enable it by default.

## How the changes fit together

H3 batches directed MPFR interval dot products in compiled code for the heat
certificate: Gram matrices, inverse defects, residuals and physical bounds.
It preserves rounding direction, zero signs and ternary results. Unsupported
contexts or exceptional compiled results use the retained Python expressions.
The selected build uses `fastmath=false`; this is no change to the heat equation,
precision, acceptance tolerance or exact conservation accounts.

The H2 → L1 → H3 construction retains the physical scratch-order repair and
original public cell/face order. Heat S1 reuses the closed-guard endpoint
certificates through closed-owned r5 and finish r11. Its accepted 266 zero-mismatch
cases and 30-test suite retain their separate scope; small S1 query observations
are another change. The current forward,
checkpoint, joined, restored, RAM and native cold-reader consumers bind this
same generation. Historical readers and receipts remain intact.

Projection numerics retain one actual peak-width witness, with deterministic
ties. This avoids constructing a fictitious witness from component maxima.
The arithmetic and resource policy are unchanged; N5 selects the new numeric
helper while historical N4 retains its old implementation.

Fresh and ordinary prepared drivers share six ordered ticks, an eleven-stage
heat prefix and 16 registered stages (15 without the optional R3 hook). Closure
probes resolve the unique loaded code object before admission. The exact
projection marker observes `NUMERICS.calculate` on N5 and `R.calculate` on N4;
decoding still uses `R.verified_private`. These observations do not change the
numerical kernel, and nested stage durations must not be added together.

## Loaded marker and closure contract

Resolve the seam before admission through the actual loaded m.J.I.F.FINISH.Q._guard;
do not hard-code another imported guard. _closure selects the unique direct
types.CodeType entry of fn.__code__.co_consts with the requested co_name, raising
on zero or multiple matches. Exact code identity matters. Do not execute the
guard/closures for discovery or prescribe an unrecorded exception class.

Retain observer r1's ordered (probe,tick_name) interface. Ordinary probes are real
functions; nested probes are SimpleNamespace(__code__=resolved_code). No global
setprofile/settrace replacement is introduced.

| Ordered tick | Probe through loaded m |
| --- | --- |
| component_volume_queries | m.G.component_volume_bounds |
| heat_faces | m.J.I.F.FUNCTIONS._face |
| heat_faces_collected | m.J.I.F.FUNCTIONS.PARALLEL.completed |
| metric_identity_calls | m.J.I.INDEXED.metric_identity |
| closed_guard_certificates | _closure(m.J.I.F.FINISH.Q._guard,'certificate') |
| closed_guard_admissible_tests | _closure(m.J.I.F.FINISH.Q._guard,'admissible') |

| Ordered heat stage | Function through loaded m |
| --- | --- |
| actual-differential-geometry | m.G.enclose_differential_ale |
| actual-composed-heat-forward | m.J.forward |
| heat-low-predictor | m.J.I.F.LOW.solve |
| heat-certified-polygon-reconstruction | m.J.I.F.FUNCTIONS.reconstruct |
| heat-conservative-finish | m.J.I.F.FINISH.finish |
| heat-finish-correction | m.J.I.F.FINISH.C.correct |
| heat-finish-closed-guard | m.J.I.F.FINISH.Q.closed_guard |
| heat-finish-issue | m.J.I.F.FINISH.I.issue |
| heat-native-projection | m.J.I.N.project |
| heat-projection-decode | m.J.I.N.R.verified_private |
| heat-projection-exact | m.J.I.N.NUMERICS.calculate on N5; m.J.I.N.R.calculate on historical N4 |

Keep the commit stages afterwards: heat-result-packaging, heat-checkpoint-save,
optional heat-checkpoint-r3-checks, heat-exterior-finish, endpoint-store-publish.
There are 16 registered pairs only when Workflow._r3_after_heat_checkpoint is
callable, otherwise 15; keep the no-R3 condition/test and unchanged 11-stage prefix.

Registration includes nested calls, not a new solver order or proof all stages
executed. Preserve observed_stages and actual route. Closed-guard certificate/
admissible fixture counts are:

| Guard | Full theta=1 | Bisection | Remaining at zero |
| --- | --- | --- | --- |
| r4 | 4/1 | 70/67 | 70/67 |
| r5 | 2/1 | 67/67 | 66/67 |

Do not infer unobserved IV1 paths, sum overlapping phase timings or claim zero
instrumentation cost. Marker-only changes affect counters/seconds, preserving
sealed-output parity; S1 separately permits certificate-sharing/skipped-work/source
metadata differences while guard/energy/face/certificate values remain exact.
H5a need not be generated for the selected lf3/S1/H3 route. HeatS2 remains
conditional on worthwhile bisection; S4 consumes commit markers.

## Source and earlier-plan integration

[SOURCE-MAP.json](SOURCE-MAP.json) maps the complete selected closure to exact
public bytes, reusing existing files where identical. It includes a bounded set
of constructor and control sources, including the shared profile builder and H3
transform previously absent from the exported maps. The witness control's r3
resource fixture is labelled under `controls/`; it is not selected production
source. Original/public digests and sanitising transformations are explicit.

The selected closure retains the earlier storage/admission/pressure/geometry
selections and Plans 10–12 reuse, reader scheduling and lf3 heat. The later Plan04
r24 comparator has separate source on this branch; its final producer/Heat
binding remains Plan31 work. This snapshot preserves its selected r21 ancestor
and does not silently repin that frozen composition or claim every pending
earlier-plan change has been folded.

Private paths use `LOCAL_USER`, coordination references are redacted and text
uses LF with one final newline. Numerical literals, tolerances and historical
pins are retained. These transformations change execution identities. Builders
and controls still require excluded private metadata, fixtures and runtime:
this is inspectable source, not a runnable public native installation.

## Review, retained checks and measurements

[RETAINED-RESULTS.json](RETAINED-RESULTS.json) is a new summary of private evidence,
not an execution receipt. Review of the actual compiled helper/fallback, resource
witness, consumer bindings, marker code and strict comparator found no material
code defect. Existing adequate runtime proof is reused without rerunning heat.

- q25 completed all four arms, exact comparison and explicit compiled-route checks.
- The strict saved-output proof passes all five arrays, four cell accounts, face
  account, three scalars and private records, with no unresolved differences.
- All 174 captured Heat source files match the final generation. Neither driver
  was captured; nine focused marker controls establish that binding separately.
- Earlier fresh/prepared marker checks passed 37/17 tests and caught five mutants.
  Six source-bound witness cases cover both cell orders and compact reopen/refusal.
- Native conversion-work amounts compare exactly, but their uncaptured ABI-dependent
  object-size preimage was not replayed. No tolerance or field exemption was added.

| Measurement | Reference | Candidate | Interpretation |
|---|---:|---:|---|
| H3 component wall time | 89.57 s | 84.95 s | 5.16% less; one unmirrored timing sample per side, including compilation/imports |
| Same component sampled tree RAM | 1,030 MiB | 1,376 MiB | 33.59% more; acceptable speed trade-off within existing memory limits |
| Combined heat CONTROL observation | 78.7677 s | 73.3181 s | 6.92% less; one base-then-joint pair, not a robust final-stack claim |
| Same combined stage sampled tree RAM | 1,144,270,848 B | 1,505,419,264 B | 31.56% more; samples, not a hard upper bound |
| H3 component logical source bytes | 9,816,635 B | 9,841,837 B | 25,202 B more; source layout, not interval storage |

The original q52 metadata-admission failure is preserved; a separate corrected
offline proof compared its saved numerical arms successfully. These observations
cannot be added to the earlier heat/ROOT improvements. Final interval time,
runtime disk, combined peak RAM and Release/Debug gains remain unmeasured.

The q25 component schedule was H2 proof, H3 proof, H3 time, H2 time on genuine W4,
with six workers per heat call, no fallback/leaks, frozen sources and environment
checks, proof D-b PASS and an explicit compiled-H3 route record. The historical
q06 loaded-identity failure remains separate. The old 28-run/seven-fail marker
baseline is not relabelled as current passing proof. The174-source numerical
capture excluded both drivers; nine final marker controls cover that seam.
Native conversion-work values compare exactly, while their uncaptured
ABI-dependent object-size preimage remains unproved. No new full-driver runtime
run or additive whole-programme speed claim follows.

## Remaining programme boundaries

H3 is candidate-only; H5a, D5 and P4 stay disabled. A new profile needs its own
eligible ROOT. Final assembly/fold, first IV1 marker observations, conditional
S2/S4 work, full-workflow recovery, final timing and enablement remain later
scoped work. The [N9 owner](../plan04/BOUNDED-WIDTH.md) records its accepted
bounded outcome, cancelled separate post-assembly verification and remaining
unproved fields. N9 replay remains subject to its existing hold. The full-interval
hold, numerical contracts, memory guards and accepted-step ceiling remain. This integration establishes neither scientific
acceptance nor release authority.
