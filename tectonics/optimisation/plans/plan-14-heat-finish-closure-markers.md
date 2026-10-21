# Plan 14: Heat finish reuse, markers and closure ticks

**Status:** WORKING NON-CANON. Requested implementation, focused verification and
private integration are complete. The optimisation branch carries the selected
source; commit/push and production enablement remain separate.

## 1. Current scope

Heat S1 closed-guard reuse (closed-owned r5/finish r11) is integrated with Plan13
H3 and the preceding Plans10–12 generation. Its accepted 266 zero-mismatch cases
and 30-test suite were reused. Small S1 query observations are a different change.
Runner M now implements the loaded-code markers below in the fresh driver and
shares them with the ordinary prepared path. These are implemented sources, not
the former unbuilt seam or historical red baseline.

## 2. Final source and verification

The [combined source map](../workbench/plans13-14/SOURCE-MAP.json) identifies the
selected 239-native/395-helper generation and the bounded construction/control
sources. The final private fresh driver has SHA-256
`c6df7b959ec9309d7b7ab12f2e763c5e111138fbb2cf2d736b4c616d24132895`.
Current checkpoint/restoration/native-cold consumers bind the integrated heat.
Older readers, receipts, failures and the former 28-run/7-fail marker baseline
remain preserved; they are not relabelled as passing current evidence.

The original marker successor passed 37 fresh-driver and 17 prepared-driver
checks and caught five required mutants. Nine focused final controls cover N5/N4
projection binding, stale source, missing marker, invalid numerical helper and
the shared stage/tick definitions. The actual-source projection-witness cases
pass in both cell orders and on compact reopen/refusal.

The strict saved genuine W4 comparison passes arrays, exact cell/face/scalar
accounts, private records and resource invariants with no unresolved differences.
All 174 captured Heat sources match the final generation; drivers were excluded
from that capture, so marker controls provide a separate proof boundary. It is
not a new full-driver runtime run. The uncaptured ABI-dependent conversion-work
preimage remains an explicitly limited, exactly compared observation.

[Retained results](../workbench/plans13-14/RETAINED-RESULTS.json) identify the
original evidence. Review found no material marker/comparator defect and reused
adequate checks without repeating scientific execution.

## 3. Closure and tick contract

Resolve the seam before admission through the loaded `m.J.I.F.FINISH.Q._guard`. Do not hard-code a separately imported candidate r5 module. Historical r4 and selected r5 both contain the two direct nested code objects.

`_closure(fn, name)` inspects direct entries of `fn.__code__.co_consts`, selects `types.CodeType` entries with the requested `co_name`, and returns the **unique matching code object**. It **raises on 0 or 2+ matches**. The owner records do not fix exception classes, so this plan does not prescribe them. Exact code identity is required, not just a matching function name. Do not execute the guard or closures to discover their code.

Retain observer r1 and its existing list of `(probe, tick_name)` pairs. For either nested closure, the probe is `types.SimpleNamespace(__code__=code)`, using the resolved code object. Ordinary probes remain their actual function objects. The observer reads `fn.__code__`; no dictionary interface or observer replacement is required. M must not add global `setprofile`/`settrace` instrumentation.

The list contains **six ticks in this order**, consisting of three retained R9 ticks followed by three new Heat ticks:

| Tick | Probe through the loaded module `m` |
| --- | --- |
| `component_volume_queries` | `m.G.component_volume_bounds` |
| `heat_faces` | `m.J.I.F.FUNCTIONS._face` |
| `heat_faces_collected` | `m.J.I.F.FUNCTIONS.PARALLEL.completed` |
| `metric_identity_calls` | `m.J.I.INDEXED.metric_identity` |
| `closed_guard_certificates` | SimpleNamespace carrying `_closure(m.J.I.F.FINISH.Q._guard, 'certificate')` as `__code__` |
| `closed_guard_admissible_tests` | SimpleNamespace carrying `_closure(m.J.I.F.FINISH.Q._guard, 'admissible')` as `__code__` |

## 4. Stage registration and interpretation

Register these **eleven heat stage pairs**, in this order:

| Stage name | Function through `m` |
| --- | --- |
| `actual-differential-geometry` | `m.G.enclose_differential_ale` |
| `actual-composed-heat-forward` | `m.J.forward` |
| `heat-low-predictor` | `m.J.I.F.LOW.solve` |
| `heat-certified-polygon-reconstruction` | `m.J.I.F.FUNCTIONS.reconstruct` |
| `heat-conservative-finish` | `m.J.I.F.FINISH.finish` |
| `heat-finish-correction` | `m.J.I.F.FINISH.C.correct` |
| `heat-finish-closed-guard` | `m.J.I.F.FINISH.Q.closed_guard` |
| `heat-finish-issue` | `m.J.I.F.FINISH.I.issue` |
| `heat-native-projection` | `m.J.I.N.project` |
| `heat-projection-decode` | `m.J.I.N.R.verified_private` |
| `heat-projection-exact` | `m.J.I.N.NUMERICS.calculate` on N5; `m.J.I.N.R.calculate` on historical N4 |

Keep the existing commit stages after them: `heat-result-packaging`, `heat-checkpoint-save`, optional `heat-checkpoint-r3-checks`, `heat-exterior-finish`, and `endpoint-store-publish`.

There are **16 registered pairs when the R3 checkpoint hook is present, 15 without it**. Preserve the existing condition that `Workflow._r3_after_heat_checkpoint` is callable and the corresponding no-R3 test; do not manufacture that hook. The eleven-pair heat prefix remains unchanged in either case. `heat-projection-exact` observes the actual loaded N5 numerical helper; decoding still uses `R.verified_private`.

This registry includes nested calls; it is not a new sequential solver algorithm or proof that every registered stage executed. `closed_guard` is called only on the closed path. Record the actual stages and ticks, retaining `record['observed_stages']`. The owner interprets certificate/admissible counts as follows:

| Loaded guard | Full theta=1 | Bisection | Bisection remaining at zero |
| --- | --- | --- | --- |
| r4 | 4 / 1 | 70 / 67 | 70 / 67 |
| r5 | 2 / 1 | 67 / 67 | 66 / 67 |

Read these with the actual route and revision. Do not infer IV1's unrecorded path from fixture counts, sum overlapping phase timings, or claim zero instrumentation overhead. Heat's estimated savings remain projections until the relevant authorised measurement.

## 5. Numerical boundary and downstream work

Marker changes affect run-record counters and phase seconds only. Marker-only
sealed-output parity is retained; they do not change the observer interface,
heat algorithm or numerical acceptance limits. Heat S1 has its separate accepted
changed-field contract: exact guard/energy/face/certificate values remain equal,
while certificate sharing, skipped work and source identities can change metadata.
Do not claim every metadata byte is identical. H5a remains disabled; no H5a
generation is required for the selected lf3/S1/H3 integration.

The first separately authorised fresh IV1 must still supply real marker/tick
observations. Heat S2 is conditional on worthwhile bisection; S4 uses the commit
markers. Final programme fold, eligible ROOT, N9 replay, full-workflow recovery,
final performance and enablement retain their later scope and holds.

No requested Plan14 implementation or private integration obligation remains.
The source export is not a runnable public native profile or main-package overlay.
Preserve all numerical/resource limits, historical receipts and full-interval
holds. This record does not grant a new run, retry, repin or scientific acceptance.
