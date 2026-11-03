# Plan16: geometry worker cap and rolling interfaces

The sampled six-worker proof passed. This additive source
revision integrates the scheduling seam with [Plans13–14](../plans13-14/README.md),
preserving 629 selected members and all 239 native files. Five helpers change;
the existing worker/rolling/endpoint-clamp transforms are already present.

For ordinary interval N>=2, the runner reads the adopted parent's producer
receipt at its authenticated SHA-256 and checks profile, interval, runner and
seal bindings. Actual parent RSS and logical peaks feed the existing selector:
four by default, six only when CPU, RAM and logical booking all fit. Missing
measurements refuse. The native scheduler retains its own per-session cuts.
The choice and parent receipt are recorded and passed through both drivers.
Pressure auto/two, interval-one serial, explicit serial comparisons, migrated
calls and approved recovery remain bounded. Conflicting serial/automatic
requests refuse. The closed successor profile explicitly binds the selector;
it needs its own eligible ROOT. Historical profiles and checkpoints stay intact.

[SOURCE-MAP.json](SOURCE-MAP.json) maps the whole selected closure. These five
new files have the same bytes as their private sources; other entries retain
their existing publication transformations. The private runtime, inputs and
receipts remain excluded, so this is source for inspection, not a public native
installation.

## Scheduling and proof contract

The three-transform item is workers6 + workers6rolling + workers6clamp:
- workers6 permits policy 1..6, retaining single-contact min(workers,2), existing
  CPU/memory/booking/predicate cuts, workers+1 lanes, at most workers running and
  twice workers batches outstanding. It is not a 32-chunk guarantee.
- rolling interfaces own the pass only for workers>2, batch_seconds not None and
  minimum_job_seconds None; otherwise single-contact remains. Do not lose a
  per-contact floor by migrating to a route that does not apply it.
- automatic endpoints clamp to 2 after machine gates; ComponentParallelSession
  remains1..2. The superseded workers_six_endpoints transform is not selected.

Exact record/stream digests must match each same-runtime serial, with nonmissing
consistent package/profile binding, no errors and serial cross-check against the
retained r2 view. Preserve the IV1 encoding correction's actual package identity.
All required current/retained/superseded arms remain visible: IV2 serial/w2/w4/w6
and IV1 serial/w4/w6. A genuine failed/unknown attempt cannot disappear behind a
successor.

IV2 w2 requires the interface-route gate and single-contact selection. IV2 w4/w6
require that gate refusing single-contact and interface-batch peak live workers>2;
IV1 w4/w6 use the recognised interface/wall controllers. A peak above 2 alone does
not prove six; the accepted q53 evidence separately meets actual-session/peak-six.
The proof uses IV2 shard 0/20, not full IV2 or a whole planet.

VOID-ENVIRONMENT is narrow: concurrency peak must be the only failed check for a
request above 2. Sessions/gates must exist, and the first trim to<=2 must be CPU or
memory with a reading proving three could not fit:
- CPU: free_cores<4<=physical_cores; rounded ambiguity refuses.
- RAM: available<3*per_worker+reserve<=physical_RAM, with the actual 768-MiB
  (805306368-byte) worker booking and 2-GiB (2147483648-byte) reserve.
These are gate-classification terms, not per-worker buffers or replacement RSS caps.
A positive trimmed count must run normally; zero must be refused by that gate alone.
Gate-less companions need the recognised below-threshold reason without error.
Budget/predicate trims, missing sessions, binding/funding/worker errors and the
deliberate endpoint cap are not VOID excuses.

| Outcome | Meaning |
| --- | --- |
| Summary 0 PASSED | Required exact/route/session/current and retained checks pass |
| Summary 1 FAILED | Genuine failed/missing check or unacceptable old attempt |
| Summary 3 VOID-ENVIRONMENT | Mechanical environment predicate only; not proof completion |
| Wrapper 2 refused start | Existing output, invalid generation or unresolved start/attempt condition |
| Historical launch15 | q21 invalid-launch failure, not a summary verdict |

q13 was VOID despite identical records; q21 had an earlier held waiter that never
started science and a later invalid launch (exit 15; date/seq/cp unavailable). These
are different events, not fabricated ticket suffixes. Preserve old partials and
orphan rulings, original exits and finality; a fresh log name cannot clear them.
The later reviewed/cleared q53 proof and completed handoff supersede the old
pending rearm instructions. There is no automatic retry, new algorithm, blanket
Plan31/35 prerequisite or newly retained coordinator-return task.

Queue prediction, runtime selection and tree protection remain distinct. The
historical wrapper did not call SG.decide/admit; do not claim an exact-byte gate
was already wired there. Runtime imports require seed 0, fail-closed checking and
the named plain -B or -s -P route, no -I; pure queue/JSON/summary helpers may isolate.
Record actual load/cores/workers; bounded quiet waits do not guarantee quiet.
The original 144/144 summariser controls remain scoped evidence, not a new run.

[RETAINED-RESULTS.json](RETAINED-RESULTS.json) summarises private evidence; it is
not an execution receipt. The original exact merged proof passes, with six
actual interface workers and a sampled live peak of six. All 14,355 records
and 26,816 streams match serial. q13's VOID and q21's invalid-launch evidence
are preserved. The repaired launch uses the existing owned-job supervisor to
enforce sampled 12 GiB tree RSS / 1 GiB free memory and owned-process cleanup.

| Sampled observation | Reference | Six-worker candidate |
| --- | ---: | ---: |
| IV2 shard 0/20 elapsed | 946.57 s serial | 421.73 s; 55.45% less |
| Earlier policy-w4 / three actual workers | 569.09 s | 25.89% less |
| Separate parent + descendant peaks | 253 + 0 MiB | 284 + 1,033 MiB |
| Guarded invocation sampled tree peak | no matched serial tree measurement | 1.34 GiB |
| Profile-store logical bytes | 15,314 B | 16,898 B; 10.34% more |
| Selected logical source bytes | 15,471,006 B | 15,476,587 B; 0.0361% more |

Historical load metadata is incomplete. These are same-scope retained component
observations, not a new controlled A/B, a simultaneous component-peak sum or a
whole-interval estimate. Higher RAM for the measured speed remains within the
unchanged limits; overlapping gains are not added. New evidence artefacts occupy
82,235,898 logical bytes, including required merged copies of retained results;
that is evidence storage, not an interval-store saving.

Four launch-guard controls, three assessment-classification controls and seven
actual candidate-function controls pass. The seven controls are supplied in
[`tests/test_integration_policy.py`](tests/test_integration_policy.py). From the
repository root, run `python -B -m unittest discover -s
tectonics/optimisation/workbench/plan16/tests -v`. They exercise the actual helper
functions with synthetic receipts and do not load the private native runtime. Scoped independent source review found
no material delta defect. The separately cleared native bootstrap/launcher
preflight passed in 2.75 s at 73,191,424 B sampled RAM, exit 0 and no live owned
process. Two preceding prerequisite refusals are preserved. No full interval, ROOT creation, worker
pool or final combined performance is claimed. Programme default enablement,
final assembly acceptance and scientific holds remain separate.
