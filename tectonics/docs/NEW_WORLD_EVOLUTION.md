# New-world Step 5: generated regional tectonic evolution

The r1 timings and outputs below bind earlier motion/adapters. The later
[r2 combined workflow receipt](#current-rerun-26-september-2026) also remains
historical after subsequent source repairs. [Current evidence](../../docs/CURRENT_EVIDENCE.md)
owns receipt classification; [current state](../../docs/CURRENT_STATE.md) owns
delivery and holds. Historical numerical results were not repinned.

This producer connects a saved S2/S3/S4 world to actual
conserved-crust deformation and calculated surface change. It does not send new
seeds to the fixed W12 demonstration or claim global geological evolution.

## The causal order

Seeded starting structure and compatible motions -> native conservative sampling
-> full-vector finite deformation -> changed crustal thickness -> vertical
response -> identified fields available to later geology/terrain consumers.

The saved starting world is an initial condition, not a pre-made final landscape.
The resulting surface-change values are calculated, not randomly decorated onto
the map. The current connection is one admitted regional scenario; it is not a
whole-planet formation run.

## What is actually calculated

`new_world_native.py` constructs a real native `InitialConditionState`: the
generated spherical atlas supplies topology; the saved precursor supplies actual
materials, layered columns, thermal profiles, origins and unknowns. Native W01/S5
sampling integrates spherical footprint/depth intersections. The complete
sample descriptor, arrays and source definitions survive in the job's initial
record; the original global world remains in its byte-identical `.atlas` file.

A circumscribed-cap test admits an entire footprint within one geological column
and exactly the selected plate pair. It checks all competing interplate edges,
both edge endpoints and every crust-province boundary, not just the centre.
Unsupported footprints refuse without quietly shrinking the requested area.
Auto selection prefers a continental convergent interval and records its actual
native edge ID; an explicit edge selection remains fixed.

The local frame points across the boundary (x) and along it (y). Actual saved Euler
vectors give both plates' velocities at the centre. For a declared width W:

```
G = [[relative_normal_velocity / W, 0],
     [relative_strike_velocity / W, 0]]
v(x) = G * (x - anchor) + mean_plate_velocity
```

Native W08 `PreparedAffineMotion` evaluates the finite affine map using its matrix
exponential. `PreparedPlanarMaterials` conserves each complete material parcel's
reference volume and mass. Its thickness is volume divided by the current actual
planar area. Convergence reduces area and thickens crust; extension does the
opposite. Shear remains in the map but does not itself change area or create
relief. Common translation is retained, not silently dropped.

This is an explicit distributed-deformation scenario, not a prediction of stress,
fault localisation, subduction polarity or mantle forces. The chosen width and
finite forcing interval are stored assumptions. The gnomonic chart's scale
distortion and the variation of original Euler velocities are bounded over the
whole footprint and elapsed horizon. A conservative affine trajectory bound
includes shear and common translation. These are approximation bounds, not proof
that the surrounding global plate network remains compatible through time.

**Column envelope (R1, 30 September 2026).** The chart bound alone admitted more
strain for smaller footprints. The review (s17) found a 1 km footprint whose
34 km crust thickened to 182 km in the default 100 kyr (357 km, 0.056 R, at
140 kyr), with +18 to +40 km of surface change, far below the column's own
121.75 km lithosphere base. `assemble_input` now refuses, before `prepare`
succeeds, any scenario whose thickest evolved crust exceeds the smaller of two
bounds the repository already declares: the sampled column's source lithosphere
thickness (crust is part of the lithosphere), and the 0.05 depth/radius ratio
that admitted the planar column approximation in
[NEW_WORLD_STRUCTURE.md](NEW_WORLD_STRUCTURE.md). For this constant-gradient map
the area ratio is exactly `det exp(G t) = exp(trace(G) t)`, monotonic in time,
so the thickest crust over the horizon is the initial equivalent thickness
divided by `min(1, J(T))`; no time sampling is needed. Admission uses the larger
of requested and represented endpoint duration and leaves a relative margin of
`2 * transform.MAP_ERROR` for the native map's accepted area error. The bound, both sources,
the minimum area ratio and the admitted maximum thickness are recorded as
`column_envelope` in the native input and in every evaluated output, and
`evaluate` refuses to publish any thickness above the recorded bound. Thinning has
no declared bound and is not limited by this envelope; choosing one would be a
new scientific threshold, not part of this repair.

Spherical shell volume is **not** silently treated as planar depth times area.
The planar initial thickness is its volume-equivalent representation. Native
bulk-reference phase/matrix volumes stay distinct from intrinsically known grain
volumes; unknown solid-volume masks are retained. Densities are the saved
constant reference-density scenario, not an inferred hot-state equation of state.

## One owner for uplift

`new_world_evolution.py` supplies a specifically named **dry local Airy** response:
instantaneous local compensation, zero elastic rigidity, negligible air mass,
and the source's explicit mantle reference density. If layer k changes thickness
by dH[k], then

```
surface_change = sum((1 - density[k] / mantle_density) * dH[k])
base_change = surface_change - sum(dH[k])
```

Both are positive upwards. The weight change at a common compensation depth is
zero: `sum(density*dH) + mantle_density*base_change = 0`. Gravity cancels from this
equilibrium. No extra Airy term is added to a flexural solution, and no 1D strip
flexure is misrepresented as finite 2D support.

This selected response is a simplified tectonic surface-change product, not a
claim of elastic support, stress-dependent deformation, absolute elevation or
sea level. It remains separate from more detailed native W04 support routes.
Unknown enthalpy stays `null`; original initial temperatures retain their known
masks and provenance. This increment does not label those temperatures evolved.

## Persistence, resources and consumers

The distinct `new_world_job.py` producer freezes the exact input archive,
configuration, source/runtime identity, actual prepared material inventory and
finite requested output schedule. It never modifies the original archive.
One synchronous worker owns the job under the existing process lock. Cancellation
and wall limits are cooperative; committed outputs remain usable.

Each completed output is immutable and content-identified. Resume validates the
original input and source dependencies even on a complete cache hit. It restores
the saved initial material map and computes only missing output times; it does
not rerandomise, resample geology or replay earlier output times. Direct finite
maps make this mathematically possible. This is a closed-form producer restore,
not an unsupported claim of generic W08 joined-workflow restart.

The frame and inverse gnomonic mapping locate each material footprint on the
original sphere for display. The physical area/thickness owner remains the
admitted planar model; displayed spherical polygon area must not replace it.
Source thermal data, calculated displacement, assumed support and unknown
absolute heights remain separate. Unchanged world-view.v3 still describes the
starting world; regional results have their own schema and producer.

Current finite limits: at most 64 across-boundary parcels, 256 requested times,
2 MiB per initial/output record, 64 MiB total outputs, and the saved world's
accounted work-memory budget. No parallel pool is added for these tiny coupled
outputs. Prepared native operators, stored sampling and direct evaluation avoid
repeated work without changing the selected equations or precision.

**Submission limits (R4 repair, introduced 30 September 2026).** The reviewed,
integrated repair status is recorded in [current state](../../docs/CURRENT_STATE.md);
the dated failures and checks below retain their original scope. Every
control file (`status.json`, `prefix.json`, a cancellation request) is written
in its canonical compact form plus one newline and is read with a 65,536-byte
limit, so a record's canonical bytes may use at most 65,535. The 256-time limit
is unchanged, but `submit` now also refuses with `OUTPUT_LIMIT`, before anything
is created, a schedule whose complete `prefix.json` could not fit. It builds the
prefix that the job would write with every entry at its largest: the index and
file name for its position, 64-hex digests and `size_bytes` of 2 MiB. No
otherwise-valid schedule of at most 256 binary64 floats is refused by this
prefix-size check: 256 times at 1/7 Myr spacing need at most
63,211 bytes on disk, and 256 floats with the longest (23-character)
representations need 64,609. Integer times of about 27 digits or more
throughout the schedule are refused; real schedules are also bounded by the
prepared horizon, so this check is a defensive bound rather than a new
scientific limit. Integer times beyond the finite floating-point range refuse
with `INVALID_REQUEST` before conversion or publication, rather than leaking
`OverflowError`; extreme wall-time integers are refused by the same request gate.
The earlier writer spaced its JSON, so a job near 256 outputs
could publish a 65,779-byte prefix that its own reader, resume, `read_output`
and the bundle copy then refused. Such jobs are not migrated; like every job
started before this change, they refuse with `SOURCE_MISMATCH`.

On Windows, `submit` also refuses with `INVALID_PATH`, before creating anything,
a jobs root for which any path the job can create reaches 260 UTF-16 units, as
`tectonics_job.py` already counts for W12. The longest is the attempt-1000
cancellation temporary, `<root>/<job ID>/.cancel-1000.json-<32 hex>`, at 84
characters beyond the root; roots of up to 175 characters are therefore
admitted. The publication temporary `.new-world-<32 hex>.tmp`, `output-0255.json`
and every staged path are shorter. Before this, a 195-character root failed after
the job directory existed, leaving an unusable job ID, and a 176-178-character
root admitted the job but made cancellation fail with `MISSING_INPUT`. The CLI
reports the fixed `INVALID_PATH` message; the Python exception says that the
jobs root is too long.

A new job is staged like a W12 job. `input.atlas`, `request.json` and an initial
`status.json` (state `preparing`, phase `submitted`) are written into a dot-named
`.<job ID>-<16 hex>` folder in the jobs root. The copied input is read back and
compared with the original bytes, and the folder is renamed to the job ID under
`active.lock`. Only then does the worker take `worker.lock`, retried for about
two seconds because a poll may hold it at that moment. The claim retains the
`submitted` phase through frozen-input verification and project loading. A failure
before the rename, including `INPUT_CHANGED`, removes only the files this call
created and its empty folder, so the job ID stays usable. A hard crash can leave
that staging folder. It is never counted, read or deleted automatically (see
[W12_ASSEMBLY.md](W12_ASSEMBLY.md#managed-local-run-cancel-and-resume)).

Phase `submitted` marks a job that sampled nothing. While the submitter holds
the root's `active.lock`, status reports such a job as `preparing`, not
`interrupted`. Once both worker and root locks are free, status reports
`interrupted` without rewriting the saved marker. A cancel is recorded
without probing the lock, and the worker sees it at its first check, before
preparation. The job still carries phase `submitted` when any of these happens:

- that cancel is honoured;
- the wall limit is reached first;
- a failure or interruption occurs during input verification or project loading;
- the first claim is refused with `RUN_BUSY`.

The last case is recorded as `interrupted`. In each case, resume starts the
job's first preparation from its frozen input as attempt 2.

This is not a resample. Nothing was sampled before, so no saved initial map or
output can disagree with the new one. Immediately before calling `prepare`, the
worker durably removes `submitted`; this is the conservative no-resampling
boundary. A hard kill after that write, even before entering the producer, cannot
prove that preparation did not start, so it requires a complete saved initial map
and prefix. A cancel honoured during preparation, before the
initial map and prefix are saved, still ends the job ID with `INITIAL_INCOMPLETE`.
A repeated identical `submit` still returns the existing job's status.
A process killed after publication or claim but before that durable boundary
retains `submitted`; after its locks are released, status exposes the interruption
and resume starts its first preparation. A transient project-loader failure has
the same retry behaviour. Source and frozen-input checks still apply on resume.

Focused lifecycle tests cover:

- a full 256-output long-float schedule followed by resume and `read_output`;
- a refused worst-case schedule;
- a staging failure;
- a poll at publication;
- status and cancel before the claim, with and without a poll holding the lock;
- a claim held past its retry, then resumed;
- a child process exiting after claim during loading, followed by first preparation;
- loader failure and retry, and no resampling after the durable preparation boundary;
- extreme integer schedule and wall-time refusals;
- the exact path-budget boundary;
- a refused 195-character root;
- cancellation under roots of 175 to 178 characters.

The original R4 checks ran in the scratch candidate on Windows/CPython 3.12.14.
Later focused repair results are reported separately; no POSIX execution is implied.

## How it is checked

Independent controls check column weight balance, exact finite area/thickness
relations, the column envelope (the reviewer's seed-42 cases are refused, the
default case is admitted with a recorded bound matched by the published
thickness to 1e-12), normal-plus-shear motion, pure-shear/translation zero-relief cases,
constant cohort inventory, unknown preservation and direct-restoration identity.
Native sampling checks cover complete footprint admission and retained source
arrays. Lifecycle checks cover changed sources/inputs, malformed or partial
records, request conflicts, cancellation, committed-prefix recovery and safe
paths. A real retained generated world supplies the assembled example; analytic
fixtures are labelled as such and do not replace it.

## Measured implementation checkpoint, 24 September 2026

The original r1 example used a generated six-plate world and a 40 × 20 km,
four-parcel regional scenario. Its exact material conservation, direct
restoration and finite-deformation checks apply to that declared case, not to
empirical mountain-belt validation. Its timings and results are historical:
[r1 evidence](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-s5-r1.json).
They do not establish present-source performance or Linux acceptance.

## Combined lifecycle qualification

The fixed [Step-7 runner](../tools/check_new_world_acceptance.py) declares three
cases before execution: seed42 and seed43 each use six plates/192 support patches;
seed42-finer uses twelve/512. All use Earth radius/gravity and continental fraction
0.3. Each saves an actual initial world, reopens in another process, samples a
40 × 20 km footprint into four parcels, saves time zero, and continues in another
process to 50,000/100,000 years. All three passed first attempt without replacement
or reduced scope. Exact reopened views, unchanged committed prefixes, zero initial
resampling on resume, direct-evaluation field parity and completed reuse with no
new outputs check lifecycle composition. Independent finite-deformation area,
compensating thickness and crust/mantle weight checks pass; mass/reference-volume
arrays remain exact and unknown heat/absolute elevation remain unknown. These
test the prescribed regional model, not empirical forcing or plate morphology.

<a id="current-rerun-26-september-2026"></a>

### Historical rerun: 26 September 2026

This incoming anchor names the tested r2 snapshot, **not the present sources**.
The [r2 receipt](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-s7-r2.json) predates the same-day
[A3 repair](../../docs/CURRENT_EVIDENCE.md#a3-follow-on-bounded-source-inventory-capacity)
and is historical. The [predeclared matrix](../evidence/new-world-s7-r2-matrix.json)
has its separate register classification. All nine fresh-process r2 phases passed
in 46.767698 s with matching source/runtime bindings. Corrected motion gave mean
100,000-year regional surface changes of 181.254509 / 119.939201 / 1.644192 m for
seed42/seed43/seed42-finer, replacing r1's 2.768 / 120.330 / 26.849 m. This physical
difference follows the frame-neutral motion correction, not line endings/platform.
It does not renew S2–S5/UI qualification or establish geological realism.

One Windows/CPython 3.12.14, one-thread observation per r2 case measured create/
save/view versus same-view reopening at 3.162314/1.061075, 3.136050/1.057452 and
4.316352/1.522087 s (66.45%, 66.28%, 64.74% restoration savings). Completed reuse
took 0.786622 / 0.773937 / 0.767947 s. These compare generation with restoration,
not old/new solver performance; no repeated benchmark or second-platform run.

### Historical record: 24 September 2026

The original r1 qualification exercised the declared three-case regional
lifecycle and retained its source-bound S2–S5 and UI checks. Different seeds
and layouts produced different regional outcomes; this was not a global
mountain-height distribution, solver comparison or geological acceptance.
The [original qualification](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/docs/NEW_WORLD_ACCEPTANCE.md)
retains the historical results. The later r2 evidence above is also historical.

Supported initial-world limits remain 1,024 patches, 256 MiB accounted work and
120 s; regional jobs remain 256 outputs, 2 MiB per record, 64 MiB outputs and
300 s per attempt, subject to native footprint/horizon admission. The matrix's
100,000-year regional horizon is no global-duration promise. The existing
`tectonics/tools/check_new_world_acceptance.py` runner and its guards retain the
declared matrix; this documentation grants no run authority. [Portable bundles](#portable-world-projects)
carry combined initial/results storage; global plate-network evolution is separate.

## CLI and UI handoff

`tectonics/tools/new_world_job.py` supports `submit`, `resume`, `status`, `cancel`
and read-only `result`. Use the declared scientific environment, an existing
safe jobs root, and a new lowercase 32-hex-character job ID. Submit additionally
requires `--file ORIGINAL.atlas` and this JSON on stdin:

```json
{"options":{},"schedule_s":[0,1577880000000,3155760000000],"max_wall_seconds":300}
```

All actions take `--root JOBS_ROOT --job-id JOB_ID`. `result --index 1` selects the
second committed time; omission selects the latest. `submit`/`resume` optionally
take `--max-new-outputs 1` to finish a bounded committed prefix with state
`partial`, not falsely report completion or cancellation. The requested schedule
is immutable; execution resumes the same definition, not modified settings.
It contains 1–256 finite nonnegative elapsed times, starts at zero and strictly
increases; its last time must fit the prepared horizon.

The response schema is `atlas.new-world-evolution-job.v1`. Job states distinguish
`preparing`, `running`, `partial`, `completed`, `cancelled`, `failed`, `interrupted`.
`requested_elapsed_s` describes the requested schedule; `completed_outputs`
describes the committed prefix. A result response contains the separately typed
`atlas.generated-regional-output.v1` scientific object. Errors are safe bounded
codes, including source/input mismatch and native-input/evolution refusal.

The UI owner owns the **regional** evolve action, managed process,
progress/cancel/resume, saved-time selection and rendering actual calculated
fields. Keep the initial world visible on failure. Do not relabel an initial
world-view.v3 as an evolved planet, connect this action to the fixed W12 fixture,
or infer absolute elevation from displacement. An initial-only `.atlas` contains
the original starting world; this distinct evolution job persists in the managed
local jobs directory and must be labelled separately, not advertised as included
in that initial-only archive. The implemented
[combined portable bundle](#portable-world-projects) separately carries the initial
world and selected committed regional jobs without changing their producer or
restart identities.

### UI integration closed, 24 September 2026

The UI owner delivered regional submit/cancel/resume, committed-time inspection,
complete parcel fields, original-sphere location, progressive method explanation
and local recovery. Its 132 focused checks and actual Windows/browser checks
passed, including all three saved times and narrow-screen layout. One separately
managed UI run completed 3/3 outputs in 3.7880601 s of native worker time; all three
scientific output identities match the retained backend evidence. Receiver review
checked actual source/project/time/mapping boundaries and unchanged backend
bindings, reusing those checks rather than repeating a scientific campaign.
The four pages are Fields, Location on planet, How this is made, Run & recovery.
Initial-world preservation and separate local job storage remain unchanged.

## Research and software checked

- [pyGPlates StrainRate](https://www.gplates.org/docs/pygplates/generated/pygplates.StrainRate.html):
  full velocity-gradient representation, area dilation and the distinct role of
  shear. Used as a mathematical cross-check, not a dependency or a global solver.
- [gFlex theory and numerics](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html):
  elastic versus local restoring support, density contrast and the difference
  between infinite-strike 1D loads and finite 2D footprints. The local response
  here is the zero-rigidity/no-in-plane-stress limit, not gFlex's general solver.
- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.html):
  primary model reference and abstract checked alongside the official equations;
  no new full-paper reproduction or calibrated tectonic history is claimed.
- Existing Atlas W01/S5 sampling and W08 affine/material implementations were
  inspected and reused without changing the native source package.

<a id="portable-world-projects"></a>

## Portable world projects

**backend implemented.** Installed UI coverage is recorded
separately in the [desktop delivery record](../../desktop/README.md#obtained-windows-qualification).

`tools/new_world_bundle.py` saves an initial world and selected regional results
in one `.atlas` file. Loading restores the original world, saved times and the
prepared inputs needed to continue a compatible partial run. Neither saving nor
loading generates a world, samples geology or runs the physics. Resume is a separate,
explicit action using the existing native job manager.

### What the file contains

The versioned outer ZIP contains `bundle.json`, the exact original `world.atlas`,
and, for each selected job, its original `request.json`, `initial.json`,
`prefix.json`, `status.json` and the prefix's committed `output-NNNN.json` files.
The original world is stored **once**, even when several jobs use it. Every job
must name those exact original bytes, not a regenerated equivalent planet.

The manifest schema is `atlas.world-bundle.v1`. It records world/project identity,
job IDs, exact member names, sizes, SHA-256 digests and a digest of the canonical
manifest. These establish integrity and consistency, not a digital signature or
independent scientific approval. Scientific definitions, original job IDs,
request/source/runtime bindings, attempts, errors and timing records are not
rewritten. Only committed output prefixes are saved. Lock files, cancellation
requests, temporary files, orphan outputs and machine-specific UI records are
not portable state and are excluded.

The outer ZIP uses stored members: the native initial-world array store already
uses lossless Zstandard. This avoids recompressing that data and requires no new
codec. Transfer/import is streamed in 64 KiB chunks. Active restored controls are
ordinary JSON. Import recreates each native job's isolated frozen input file;
deduplication applies to the portable archive, not a change to the native job
storage contract.

<a id="bundle-integrity-and-recovery"></a>

### Integrity and recovery rules

- Initial-world v1/v2/v3 files remain loadable without modification. A legacy
  file returns `kind: initial-only`, `bundle_id: null` and no jobs.
- Regional jobs must have a complete initial/prefix pair, even when the prefix
  has zero outputs. Cancellation during incomplete preparation is not magically
  restartable and returns `INITIAL_INCOMPLETE`. A job stopped before its
  preparation began (status phase `submitted`, R4 repair) is started by the job
  tool's resume; until then it has no checkpoint to save and the bundle refuses it
  with `INITIAL_INCOMPLETE` too.
- Busy jobs return `RUN_BUSY`. A stale active state or unreconciled status counts
  returns `UNSTABLE_JOB` or an integrity refusal: settle/recover the original job
  first. Stable completed, partial, cancelled, failed or interrupted checkpoints
  retain their real state; a failure is not relabelled successful because files
  exist. The original attempt ceiling is preserved.
- The native request, every prefix record, original input identity, initial
  identity, scientific output digest, context/time and world pairing are checked.
  Regional export requires the current code/runtime. Import and inspection also
  admit integrity-verified jobs from a different code/runtime, retaining every
  original binding and reporting `continuation_compatible: false` with
  `continuation_refusal: SOURCE_MISMATCH`. Their saved results remain available
  through the bundle `result` interface. Native resume still refuses mismatched
  bindings; no automatic installation, compatibility migration or silent repin is
  performed. Only supported saved schemas are admitted.
- The integrated I02 workflow changes the package
  execution identity and `tectonics_job.py` and `read_tectonics.py`, which every
  New World job binds. Jobs started before it then refuse resume, output export and
  bundle saving with `SOURCE_MISMATCH`; bundles already saved stay inspectable as
  described above. Saved worlds with initial structure and motion still load, but new
  evolution jobs from them, motion generated from a saved structure and re-saving with
  structure and motion refuse with `SOURCE_MISMATCH`
  ([I02 workflow](I02_WORKFLOW.md#8-evidence-effects)).
- Strict member allowlists, record/total limits, duplicate/linked/encrypted/
  compressed-member refusal, bounded central-directory parsing and manual member
  copying prevent archive-path extraction and unbounded decompression. No
  `extractall` is used. Native codecs still enforce their own limits.
- The central-directory bound is checked from the ZIP end record before
  `zipfile.ZipFile` reads or parses the directory. The outer bundle admits at most
  `2 + 32 × (4 + 256)` members in at most 4 MiB. Every project container admits
  exactly two members in at most 4096 directory bytes, on disk 0: a directly opened
  `.atlas` project, a legacy initial-only file and a bundle's inner `world.atlas`
  alike, because all three are read by `new_world_project.load_project`. A saved
  project's two directory records occupy 117 bytes. Before this check a 64 MiB
  project listing 1,429,325 members cost about 555 MiB of memory and 3 s before
  its refusal; it is now refused in milliseconds without that allocation. The end
  record is read by CPython's private `zipfile._EndRecData`, which reads at most the
  final 64 KiB; that private name is a dependency on the pinned Python 3.12, and the
  Python `zipfile` documentation states no directory or member-count bound of its own.
- A project container that `zipfile` itself cannot read, because a record needs an
  unsupported extract version, sets flag bit 5 (patched data) or 6 (strong
  encryption), or has a member name that is not valid UTF-8 under the UTF-8 flag,
  refuses as `INVALID_PROJECT` "Damaged project container." instead of a raw Python
  error. The outer bundle reader maps those parser/member-read failures, plus
  damaged ZIP and premature end-of-file errors, to `INVALID_BUNDLE`. This applies
  to Python inspection/loading and the command response before destination
  publication. Filesystem and environment failures retain their distinct handling;
  nothing is generated or rebound to repair a damaged container.
- Reopening applies the save-time title rule after the manifest integrity check.
  The title must be a string that is nonblank after Python's `str.strip()`, at
  most 160 code points long, with no C0 control character (below U+0020). The rule
  does not refuse DEL (U+007F), C1 control characters (U+0080 to U+009F) or
  invisible characters such as U+200B, at save or at load. Project digests are
  self-digests, not signatures, so a crafted title with recomputed digests that
  breaks this rule refuses with `INVALID_PROJECT` on load and inspection.
  The session's `INVALID_TITLE` message names the C0 range explicitly; it does not
  imply a wider Unicode-control ban than the existing save/load rule.
- Saving publishes a complete, fsynced file exclusively. Loading validates all
  data in an owned staging directory, then publishes into an exclusively new
  managed directory. `ready.json` is published last. Callers adopt the new world
  only after the successful response; failure retains the previously open world.
  Rollback removes only unchanged files created by that call and its empty owned
  directories, never an existing project or arbitrary recursive tree.
- The trusted system temporary-directory root is resolved before staging, so a
  system alias such as `/var` does not invalidate a save or load. User-supplied
  source and destination paths still reject symlinks/reparse points. Unavailable
  safe staging or missing native dependencies return `ENVIRONMENT_ERROR`, not a
  claim that the saved world is damaged.

Native world restoration remains mandatory and unchanged: its codecs and geometry
identity checks must succeed before a world is returned. A different job execution
binding does not by itself prevent world restoration. This is not a promise that
every older schema, native library or platform can decode every world. A native
reader refusal remains a refusal; the adapter neither repins a world nor claims
metadata-only inspection as a successfully loaded world.

The project/session staging adapters have changed; source-bound jobs created with
their prior bytes may therefore be inspectable but noncontinuable under these
updated adapters. Existing job and native execution guards remain unchanged.

### Stable backend and UI interface

Use the declared scientific Python and trusted server-owned paths:

```text
python -B tectonics/tools/new_world_bundle.py save --file NEW.atlas --world ORIGINAL.atlas --root JOBS_ROOT
python -B tectonics/tools/new_world_bundle.py inspect --file SAVED.atlas
python -B tectonics/tools/new_world_bundle.py result --file SAVED.atlas --job ORIGINAL_JOB_ID --index 0
python -B tectonics/tools/new_world_bundle.py load --file SAVED.atlas --directory NEW_DIRECTORY
```

`save` reads exactly `{"job_ids":["lowercase-32-hex-job-id"]}` from standard input.
An empty list saves the initial world alone; `--root` may then be omitted.
At most 32 distinct IDs, 256 times per job, 64 MiB output data per job and 256 MiB
total payload are admitted. Individual native bounds remain unchanged. The
manifest is at most 2 MiB and the complete archive at most 260 MiB.

All commands return a path-free envelope:

```json
{"schema":"atlas.world-bundle-response.v1","status":"ok","data":{"kind":"combined","bundle_id":"64-hex","project_id":"64-hex","title":"World title","status":"WORKING NON-CANON","jobs":[],"generated_on_open":false,"world_file":"world.atlas","jobs_directory":"jobs"}}
```

The nested status is a [legacy compatibility field](../../docs/CODING_SAFETY.md#legacy-document-and-format-bindings).

`save` additionally reports `archive_bytes`, `stored_world_copies: 1` and
`avoided_frozen_world_copies`. Each job summary contains `job_id`, `producer_id`,
`state`, `attempt`, `completed_outputs`, `total_outputs`, `requested_elapsed_s`,
`output_ids`, `continuation_compatible`, `continuation_refusal`, `attempts_remaining`
and its safe `error` or null. Compatibility is not permission to reset an exhausted attempt count.
Failures return `status: error`, safe `error.code/message` and exit 2, never
private filesystem paths or raw exceptions.

After successful load, `NEW_DIRECTORY/world.atlas` works with the existing
`new_world_session.py read`. `NEW_DIRECTORY/jobs/<ORIGINAL_JOB_ID>/` works with
the existing `new_world_job.py status/result/resume/cancel` interface when its
source/runtime guards permit the operation. For historical saved results, use
bundle `result`: it verifies the archive and committed scientific identities,
returns `job`, `index`, `result` and `generated_on_open: false`, and never creates
an execution owner. Omit `--index` or use `-1` for the last committed result.
UI owns registration/routing to that imported jobs root and collision handling; it must
not rename IDs, merge into an existing conflicting job, or call submit instead
of resume. It should select committed saved times without initiating physics.
The `.atlas` upload must not be treated as the old smaller initial-only format
before its type and bounds are checked by this adapter.

Python API: `save_bundle(path, world_path, *, jobs_root=None, job_ids=())`,
`inspect_bundle(path)`, `load_bundle(path, new_directory)`. Each returns the
envelope's `data` value; `read_bundle_output(path, job_id, index=-1)` returns a
verified saved result with its job compatibility summary. `response(argv, stdin)`
also supplies the exit code. Historical inspection is read-only access to saved
data, not scientific revalidation or execution compatibility.

### Historical bundle evidence

The retained [r1 delivery evidence](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-bundle-r1.json)
and [r2 native check](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-bundle-r2.json)
are historical after later source repairs. They recorded save, inspect, load and
saved-output access, including foreign-identity refusal on resume, for their
bounded Windows examples. They are not present-source timing, Linux compatibility
or scientific acceptance. Current receipt classification belongs to the
[evidence register](../../docs/CURRENT_EVIDENCE.md).
