# W12: supported tectonics assembly and release boundary

24 September 2026. WORKING NON-CANON. This is the implementation record for
the existing plan's W12, not a new scientific model or a competing roadmap.

## What is usable

The source checkout now has a runnable, recoverable **W01 -> W02 -> W03 -> W04**
column example and typed, lossless consumer exports for the other supported
tectonics workflow families. It uses the existing Atlas graph, cache and native
checkpoint machinery. It does not substitute a historical terrain generator for
the current tectonics implementation.

The two kinds of delivery are deliberately distinct:

- `PreparedColumnAssembly` owns the supported column continuation, elastic
  response, complete native checkpoints and final graph publication.
- `publish_workflow_output` exports an existing native result with its original
  identity, scientific metadata, arrays, units and known/unknown masks. It does
  not evolve that result or turn a consumer export into a native restart.

### Supported route matrix

| Native owner / output | W12 delivery | Physical scope stays with |
| --- | --- | --- |
| W01/W02 regional workflow | Typed sampled geometry, material and provenance fields | [W01 acceptance](W01_COMBINED_ACCEPTANCE.md) and native regional workflow |
| W03 columns | Typed material, compaction and finite-water state; column assembly continuation | Existing W03 column laws and their supplied thermal history |
| W04 support | Identified support, loads and water-surface known mask; full column assembly | [W04 methods](TECTONICS_PLAN.md) and its stationary support envelope |
| W05 extension | Typed requested-output state, exchanges and support | Existing extension workflow and prescribed motion |
| W06 constant spreading / changing spreading / inherited margin | Typed dated thermal, material, heat and support results | Existing W06 native producer and history |
| W07 steady / thermal / surface | Every published state and mechanical field | [W07 workflow](W07_WORKFLOW.md); supported route-specific solver/coupling |
| W08 joined regimes | Geometry, material inventory, regional view and native receipt | Existing W08 joined workflow and its declared regimes |
| Underthrust / evolving elastic support / evolving regional mechanics | Typed direct results and dated-history outputs | [Underthrust](UNDERTHRUST.md), [evolving mechanics](EVOLVING_MECHANICS.md), [histories](TECTONIC_HISTORIES.md) |

This matrix is an export/integration matrix, **not permission to join arbitrary
rows physically**. In particular, the new example does not supply the missing
heterogeneous W06-to-W07 bridge, infer footprint-to-parcel conversions, finish
W09 surface-process feedback, or reopen held R4.4/generated-plate evolution.
Independent physical and field-evidence limits in W10 remain unchanged.

## Run the public example

Use the repository root and a compatible environment containing the declared
[package dependencies](../pyproject.toml). Python 3.12 or 3.13 is required;
the measured environment is recorded with the evidence. No private files,
download, test fixture import or saved Diadem state is needed.

```text
python -B tectonics/tools/run_tectonics.py --directory w12-demo
python -B tectonics/tools/run_tectonics.py --directory w12-demo --resume
```

The first directory must not exist; its parent must exist. For an intentional
interruption after the first continuation:

```text
python -B tectonics/tools/run_tectonics.py --directory w12-resume --stop-after 1
python -B tectonics/tools/run_tectonics.py --directory w12-resume --resume
```

`--cells` accepts 5..64, defaults to 8, and cannot change on resume. These bounds
are the example's admitted workload, not a resolution/realism setting for a
planet. The driver writes `case.json`, `native.sqlite`, graph-cache files when
requested, and separately numbered `run-*.json` reports without replacing an
earlier report. The source-checkout entry point uses the retained `engineering/`
tree; a wheel containing only `atlas_tectonics` does not include that graph CLI.

The default example has three dated outputs on a stationary 4 m by 2 m strip.
Only the upper 100 m sediment stack is represented in its material columns;
the supplied 100 km thermal plate is a separate, explicitly identified support.
These intentionally synthetic dimensions test connections, not a plausible
regional geological reconstruction. W03 effective compaction traction and the
additional W04 pressure are different inputs, not an omitted duplicate load.

Limits: 128 MiB of accounted component work, a 32 MiB native store and three
requested outputs. This is **not an operating-system RSS ceiling**. The public
driver records accounted peaks and checks that owned reservations are released.
Windows is exercised here; portable syntax is not a new Linux execution claim.

## Use outputs in another module

### Read-only UI connection

`tools/read_tectonics.py` exposes one already saved public column result to a
local presentation adapter. It is outside the scientific package, so adding the
reader does not change native execution identities or invalidate the saved case.
It does not start a simulation or provide a job service.

```text
python -B tectonics/tools/read_tectonics.py --directory w12-demo --report run-00001.json
```

Use an existing compatible public run and its recorded Python environment. The
optional report selector is a basename `run-NNNNN.json`, not a filesystem path.
The success response has schema `atlas.tectonics-ui-result.v1`, `status: "ok"`,
capabilities `{inspect: true, generate: false, cancel: false, resume: false}` and
`result`. The result contains IDs, context/time, native spatial/row support,
`fields[name] = {spec, values}`, provenance and a case-specific explanation.
Specifications retain the native units, named mixed-unit matrix columns and
known masks unchanged. Cohort and compaction-row descriptor arrays are separately
ordered to match their respective matrices; they are not interchangeable layers.

The browser must use the native strip/table/profile support, not project these
results onto the illustrative globe. `support.values` is **cell x named column**;
its last column requires `support.reservoir_surface_known`. Preserve each field's
sign and reference. UI project saving is separate from native result/restart data.

For a configured invocation, stdout contains one compact JSON object. Exit 0
means a verified result; exit 2 means `status: "error"` and `{code, message}`.
Messages contain no traceback or machine-local paths. Supported refusal codes:
`INVALID_PATH`, `INPUT_LIMIT`, `INVALID_REPORT`, `RUN_BUSY`, `INVALID_STORE`,
`UNSUPPORTED_RESULT`, `INVALID_RESULT`, `INCOMPLETE_RESULT`, `CONTEXT_MISMATCH`,
`SOURCE_MISMATCH`, `OUTPUT_LIMIT`, `READER_ERROR`, `DEPENDENCY_UNAVAILABLE`,
`MISSING_INPUT`, `READ_FAILED`, `RESOURCE_LIMIT`, `VERIFICATION_FAILED`.
Invalid CLI syntax is an ordinary parser/configuration failure, not a browser
request parameter. The local HTTP adapter must also handle unavailable processes,
timeouts and non-JSON output without exposing raw stderr.

The reader bounds reports/responses to 2 MiB, cases to 64 KiB, native databases to
32 MiB and accounted work to 128 MiB. It refuses links/reparse paths and active
SQLite sidecars. The original database opens `mode=ro`; SQLite's backup API makes
a bounded consistent **temporary** snapshot for existing `ArrayStore`, whose
constructor normally performs schema writes. The temporary copy is removed after
reading. This avoids changing either the original store or its source-bound
storage implementation; it adds no persistent duplicate/cache. A future native
read-only-store API is not implemented by this tool.

The thin HTTP/UI owner must use trusted launch configuration for Python, checkout,
run directory and report, not accept arbitrary browser paths or shell commands.
Keep the service loopback-only, same-origin and read-only with bounded process
time/output; do not infer generation/pause/resume from this inspection endpoint.

Backend evidence: **6 focused tests pass in 2.702 s**, including the retained
result's complete field/spec/hash parity, mask/row alignment, tampered/missing
dependency refusals, and unchanged original-file hashes. The measured retained
read took **2.274 s**, including imports in that invocation; this is a read timing,
not a simulation speedup. An initial reader smoke exposed an incorrect epoch
attribute access; it was corrected to the native material epoch before the passing
suite. Source-only safety: 13 maps/41 paths and 30 passes/one existing skip.
No simulation or broad regression replay was required. UI/browser acceptance is
owned by the separate Generator UI task, not established by these backend tests.

Portable guards run through `test_read_tectonics.py`. Set `ATLAS_UI_TEST_RUN` to
an existing compatible public run (and optionally `ATLAS_UI_TEST_REPORT`) to enable
its two retained-result checks; absent inputs are explicit skips, never fabricated
or generated automatically. The other four guards use temporary synthetic files.
Reused software: native `read_product`, W03 dependency restoration, `ArrayStore`,
Python `sqlite3` backup and JSON. No new physical equation or paper-derived claim.

### Managed local run, cancel and resume

`tools/tectonics_job.py` adds a trusted local-process interface around the same
public W12 case. It remains outside the source-bound scientific package. The
existing reader, original driver and native methods keep their identities.
The local UI/server owns its child process and HTTP boundary; this tool does not
detach workers, install a service or introduce another numerical scheduler.

Create a dedicated empty jobs directory with your normal local file tools. The
root is launch configuration, never a browser-supplied filesystem path. Generate
one lowercase UUID hex ID per submitted run and retain it across retries:

```text
python -B tectonics/tools/tectonics_job.py run --root jobs --job-id 0123456789abcdef0123456789abcdef --cells 8
python -B tectonics/tools/tectonics_job.py status --root jobs --job-id 0123456789abcdef0123456789abcdef
python -B tectonics/tools/tectonics_job.py cancel --root jobs --job-id 0123456789abcdef0123456789abcdef
python -B tectonics/tools/tectonics_job.py resume --root jobs --job-id 0123456789abcdef0123456789abcdef
python -B tectonics/tools/tectonics_job.py result --root jobs --job-id 0123456789abcdef0123456789abcdef
```

Run and resume remain attached until the worker exits; the local server must
track/reap them rather than impose its short read-request timeout. Other commands
are short. Stdout is one JSON object: `atlas.tectonics-job.v1`, `status: "ok"`,
and `job`; errors use `status: "error"`, `error: {code, message}`, and exit 2.
Exit 0 authenticates the control response, not scientific completion: inspect
`job.state`. The result command instead returns the existing verified reader
envelope. No result is available while the worker owns its native store.

Job states are preparing/running/finalising, cancelling, completed, cancelled,
failed and interrupted. A cancellation request is not an acknowledged stop.
The callback uses existing native checks; case construction and final graph
verification have uninterruptible sections. A verified final completion wins a
late cancellation. `completed_outputs / total_outputs` counts the three declared
dated commits; it is not a percentage of remaining execution time. Restored-output
statistics count native visits, not unique outputs.

The worker saves reader-compatible immutable reports after verified native
commits and a separate final graph report. Cancellation/failure keeps those
records. Resume authenticates the original request, adapter sources, runtime,
case and native dependencies, then computes missing work only. Older reports
remain untouched. A repeated run ID cannot launch a second calculation; different
inputs under that ID refuse. Browser draft Save is still not checkpoint saving.

OS file locks enforce one active job per root and one owner per job on Windows
and POSIX. Locks release on process death; no PID reuse heuristic is used. A
previously active status without a live lock is reported as interrupted. Reopening
the UI does not launch it automatically. Shutdown first requests cancellation
and reaps the owned child; if an owner must terminate an unresponsive process,
it must not call it cleanly cancelled or delete checkpoints. Subsequent resume
performs normal native verification. Missing or invalid control files refuse.

The case keeps 5..64 columns, three dates, 128 MiB accounted work and a 32 MiB
native store. Each invocation requests cooperative cancellation at 300 seconds;
that is not an OS hard wall-time or RSS guarantee. Control storage allows at most
32 job IDs per configured root and 1,000 attempts per job. No automatic deletion
or source migration is provided. Local inputs reject linked/reparse paths; this
cooperative desktop service is not a sandbox against hostile filesystem mutation.

HTTP owners must use loopback binding, strict same-origin JSON POST mutations,
bounded bodies and fixed commands/IDs, not shell strings or arbitrary source
paths. Preserve Windows processor architecture metadata in restricted child
environments; dropping it changes Python's native runtime identity. Never invent
an architecture value to make verification pass.

Software reused: `PreparedColumnAssembly`, native cancellation and `ArrayStore`,
the existing R11/R24/R12 graph/cache, Python JSON/subprocess boundaries, and OS
file locking (`msvcrt`/`fcntl`). No new physical method or paper-derived claim.

Backend verification: **13 lifecycle tests pass in 0.299 s; 12 worker tests pass
in 0.049 s**. The lifecycle tests include an actual killed child process releasing
its Windows lock, not only a mocked PID. POSIX locking is implemented but not
executed in this Windows check. Symlink/reparse metadata guards are synthetic.
Source-only safety: 13 maps/41 paths and 30 passes/one existing skip in 0.140 s.

One actual Windows CLI sequence runs eight columns, requests cancellation after
the first verified output, inspects that saved prefix, resumes, and verifies the
final result against the retained direct-run product. It stopped after **8.501916 s**
and resumed in **31.883260 s**, computing **only two missing outputs**. Four restored
visits include repeated native prefix validation; they are not four different
outputs. All field specifications/hashes and the final product identity match;
the original prefix report is byte-unchanged. Repeating the same run ID and
resuming an already completed job perform no new work. The complete diagnostic
sequence took 48.808049 s including reads/no-ops; these are operational timings,
not a controlled speedup comparison.

The first native attempt exposed the existing Windows 259-UTF-16-unit graph-cache
path limit. Shortening the new cache leaf to `g` and preflighting the full hashed
destination before computation fixes that connection without enabling long-path
mode, weakening the native guard or shortening content identities. The failed
attempt was retained; the corrected test used a new job, not repinned metadata.
Browser run/cancel/resume acceptance belongs to the UI owner and is separate from
this backend evidence.

### Calculated cross-section and saved-time access

`tools/view_tectonics.py` adds a separate read-only presentation adapter. The
original reader, managed job/worker and scientific sources are not edited or
repinned. Existing closed results therefore remain valid inputs.

```text
python -B tectonics/tools/view_tectonics.py catalogue --directory w12-demo --report run-00001.json
python -B tectonics/tools/view_tectonics.py section --directory w12-demo --report run-00001.json --output-index 1 --field porosity --cell-start 0 --cell-stop 4
python -B tectonics/tools/view_tectonics.py catalogue --root jobs --job-id 0123456789abcdef0123456789abcdef
```

Use one configured directory/report or a managed job root/ID. The managed route
holds the existing worker lock throughout reading and refuses an active worker.
The root and report are trusted local launch configuration, not browser paths.
The same CLI source options apply to both actions. An optional expected plan ID
refuses a changed source when switching an already displayed selection.

Responses use `atlas.tectonics-view.v1`, `status: "ok"`, `catalogue`, `provenance`
and, for a section, `view`. Errors are fixed path-free `error: {code, message}`
with exit 2. The catalogue contains the actual plan/context/epoch, three declared
times and committed/missing availability. It walks native completion keys, not
thousands of repeated run reports. It checks metadata identities, native markers
and parent links without decompressing every historical field. **A catalogue
entry is not a full array/dependency validation.** Selecting a time performs that
existing full native verification before any calculated geometry is returned.
Missing future outputs stay unavailable; internal checkpoint gaps refuse.

The section uses the **ordered compaction parcels**, not alphabetically sorted
material-cohort totals. For each parcel and cell, its saved grain volume times
`(1 + void_ratio)`, divided by native cell area, gives bulk thickness. Cumulative
thickness yields parcel top/bottom depths **below the current sediment surface**,
positive down. That is a surface-relative sediment section, not an inferred
absolute terrain elevation, subsurface geological map or the separate 100 km
thermal plate. Porosity is `void_ratio / (1 + void_ratio)`; this is conversion of
saved state, not another compaction simulation. W04 signed displacement/surface
changes are separate curves with their original validity masks and units.

Supported colour fields are void ratio, porosity, parcel bulk thickness in metres
and grain volume in cubic metres per native cell. The adapter returns exact native
edges, IDs, parcel order and top/bottom geometry. Cell intervals use zero-based
start-inclusive/stop-exclusive indices. It performs no smoothing, interpolation,
resampling or level-of-detail calculation for this bounded 5..64-cell case.

Loading takes one temporary consistent read-only store snapshot per request.
Only one chosen output is restored, with all its fields/dependencies verified;
only the selected colour field and cell interval are sent to the UI. This is
bounded output selection, not a claim of chunk-only verification or a zero-copy
store. No persistent scientific cache or copied history is added. Immutable view
IDs include product identity, selection and adapter-source hashes; the catalogue
ID changes with its native completed-output inventory. Timing is excluded from
those identities.

The UI owner renders actual cell/parcel rectangles, labels depth direction and
aspect scaling, preserves unknown gaps, and selects saved dates without inventing
intermediate states. It keeps absolute/relative references and units visible;
these columns cannot be projected onto an illustrative globe as new world data.
The browser project stays separate from the scientific view. Native compaction
and W03 representation rules supply the method; no new physical law or paper is
introduced by this visualisation adapter.

Focused Windows evidence (24 September 2026): eight geometry checks pass in
0.003 s; eight catalogue/selection/locking/snapshot guards pass in 0.604 s. One
explicitly opted-in retained-result test passes in 3.820 s: the middle saved time,
porosity and cells `[1, 5)` match independently reconstructed native depths,
field hashes/specs, parcel order and signed curve values/masks exactly. Original
run-file hashes remain unchanged. No simulation was started. Static safety checks
pass (13 route maps/41 paths; 30 tests pass and one existing Windows symlink
privilege skip).

Observed reads of an existing eight-cell result took 1.168 s for its three-time
catalogue and 1.428/1.509 s for selected initial/final sections, respectively;
these are individual reads, not a controlled speedup benchmark. The selected
three columns have bulk thickness 100 m initially and 94.18095283360248 m at the
last saved time; first-parcel porosity changes from 0.4 to 0.3348780969367049.
Backend evidence does not substitute for the UI owner's browser-rendering check.

### Native consumer APIs

The APIs live in `atlas_tectonics.assembly` and
`atlas_tectonics.workflow_ports`. `describe_workflow_output(output)` is a
read-only typed description. `publish_workflow_output(...)` saves a consumer
product into an existing `ArrayStore`; `read_product(...)` authenticates its
current-source identity, metadata and every stored field before returning arrays.

Supply the six explicit Atlas context strings: `world_id`, `snapshot_id`,
`calendar_id`, `spatial_frame_id`, `vertical_reference`, `scenario_id`, plus an
honest physical `scope`. Native metadata remains authoritative for spatial
support, time, units, constitutive choices and source ownership. Supplying six
strings is not a coordinate transform or an arbitrary scientific compatibility
check. An explicit single native frame must match; multiple native frames refuse
until an explicit mapping is supplied by a supported owner. The product records
whether a native frame identity was available to check. The column assembly also
explicitly matches the actual source datum; generic exports do not infer a datum
or calendar mapping from a label.

W06 constant/history ocean outputs additionally require
`native_owner=the_open_PreparedW06Workflow`. Their native states contain opaque
plan IDs rather than a standalone runtime binding. Publishing authenticates the
already retained/stored output using `owner.load`, compares its complete fields
and metadata, and records the owner identity. It never calls `run` to manufacture
missing work. A missing, different or closed required owner refuses.

Every field has a dtype, shape, content hash, units and support/owner information.
Packed mixed-unit matrices have ordered column descriptions. Dry water surfaces,
partial ocean occupancy and unknown underthrust enthalpy keep their masks;
placeholder zero values are not promoted to known physical zeroes. Unknown output
classes and authored fields without supported unit contracts refuse.

The receiving hydrology, geology, terrain or other module must apply its own
response to these quantities. W12's sample downstream graph operation only reads
and hashes the actual arrays; it is **not a new downstream physics model**.

## What the graph and recovery actually do

`tools/w12_graph.py` uses the captured R11 graph contract, R24 executor and R12
authenticated graph cache with an explicitly registered current producer and
read-only field inspector. It authenticates the executed adapter/runtime bytes.
It does not load R31's scientific registry, redirect its old tectonics recipe,
clone a new set of scientific globals or relabel a historical R5 checkpoint.

The prepared column identity includes the original W01/W02-backed state, source,
thermal/compaction history, W04 policy, output schedule, source/runtime identity,
and explicit fixed reservoir-allocation/extra-pressure policies. Every interval
uses the current finite reservoir. Elastic displacement is the **total response
from the initial reference**, never repeatedly added to an earlier deflection.

The native W03 checkpoint closure is saved first, the consumer arrays second,
and a completed-output marker last. Resume authenticates the completed prefix
and computes only missing outputs. A gap or a missing native dependency refuses;
graph-cache hits also validate the native product on both producer and consumer
restoration. A small graph receipt cannot replace missing physical data.

For recovery, keep the complete closed native store, case definition and
compatible source/runtime together. Keeping the graph cache avoids repeated
inspection but does not replace the native store. Generic typed exports alone
are not restarts: retain the original native producer, source inputs, policies,
schedule and required checkpoint/parent records. No automatic migration or
source-hash repinning is performed. Adding W12 changes the package source
identity; earlier source-bound W10/W11 receipts remain historical.

## Verification and resources

The acceptance record is [w12-assembly-r1.json](../evidence/w12-assembly-r1.json).
It separates native direct-versus-assembled calculations, clean-versus-resumed
results, cross-route export round trips, graph reuse and refusal/resource checks.
The tests compare complete fields and identities, not merely one plotted value.
The CLI campaign separately exercises actual process restarts and retained files.

Results: **29 distinct W12 test methods pass**, including all 17 typed output
forms; 30 source-only safety tests pass with one explicit existing skip. The
final publisher change receives its own 10-test suite, with the affected assembly
guards checked afterwards; no full regression replay is implied by these counts.

| Public CLI invocation | New outputs | Restored native outputs | Reported seconds |
| --- | ---: | ---: | ---: |
| Stop after the first continuation | 2 | 0 | 10.675692 |
| Resume that prefix to the final graph output | 1 | 2 | 20.081869 |
| Separate uninterrupted fresh run | 3 | 0 | 17.920495 |
| Reopen its completed graph cache | 0 | 0 | 6.072994 |

The final products and full field inspections match across fresh, interrupted and
warm runs. Warm reopening restores both graph stages, not native continuation
steps, while checking their native dependencies. Its single measured comparison
saves **11.847501 s / 66.11%**; this is saved-work reuse, not a solver speedup or
a repeated controlled benchmark. Timings include case construction, execution,
verification and store closure, but exclude interpreter/import startup and report
serialisation. The prefix/restart figures do not demonstrate a speed improvement.

Peak accounted work is 35,238,104 bytes fresh and 25,490,448 bytes warm; all owned
reservations are released. The native database is 180,224 bytes with 8,185 bytes
of unique encoded chunk payload. Its 32 MiB limit is not a total-directory quota:
SQLite journal/staging allowances, graph cache and reports are separate.

Only new integration boundaries are tested here. Existing physical-method
evidence is reused at its recorded scope; neither the 3,565-test comprehensive
campaign nor the held multi-hour simulation is replayed. The source-only coding
safety checks remain separate from physical acceptance.

### Software and research basis

Reused software: Atlas R11/R24/R12, native `ArrayStore`/Zstd, existing W01-W08
producer/checkpoint implementations and the three tectonic-history owners.
No new scientific equation, solver or physical closure is introduced, so this
step adds no new paper-derived physical claim. The existing method and paper
references remain in [How tectonics is made](HOW_TECTONICS_IS_MADE.md) and the
linked native implementation records.

The six advanced optimisation candidates remain in the existing
[potential-improvements list](OPTIMISATION_REFERENCE.md), deferred at the user's
request. They are neither implemented nor required by this release boundary.

Atlas-owned example/code licensing follows [AGPL-3.0-only](../../LICENSING.md).
The example uses authored synthetic inputs, not third-party world data. This
record does not publish a release, upload data, approve canon or turn bounded
technical integration into an unrestricted production/field acceptance claim.
