# New-world Step 5: generated regional tectonic evolution

WORKING NON-CANON. This producer connects a saved S2/S3/S4 world to actual
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

## How it is checked

Independent controls check column weight balance, exact finite area/thickness
relations, normal-plus-shear motion, pure-shear/translation zero-relief cases,
constant cohort inventory, unknown preservation and direct-restoration identity.
Native sampling checks cover complete footprint admission and retained source
arrays. Lifecycle checks cover changed sources/inputs, malformed or partial
records, request conflicts, cancellation, committed-prefix recovery and safe
paths. A real retained generated world supplies the assembled example; analytic
fixtures are labelled as such and do not replace it.

## Measured implementation checkpoint, 24 September 2026

The retained generated six-plate world supplied native edge 101 and province-0
crust, not the W12 example. A 40 x 20 km reference footprint, four material
parcels and outputs at 0/50,000/100,000 years produced 12.2593% area reduction,
5,273.37-5,273.41 m thickening and 688.253-688.258 m local isostatic surface rise.
These are consequences of the stated scenario, not observations or validation
of those assumed velocities/support against a real mountain belt. Reference
volume and mass arrays are exactly unchanged. Maximum chart area-scale deviation
over the admitted trajectories is 0.0034131%; the frozen-rigid-velocity path
bound is 31.12 m, not an uncertainty estimate for the whole tectonic model.

Twenty-seven focused methods pass (6 sampling, 8 evolution, 13 lifecycle).
A fresh-process one-output prefix followed by resume computes only the missing
two outputs and exactly matches every scientific field from the uninterrupted
run. Direct native CLI selection of the middle saved time also passes without
generation. Thirty source-safety tests pass; one existing Windows symlink-
privilege check is skipped. No full suite or Linux claim is added.

Current-job fresh generation/storage: **4.937890 s**. Verified completed reuse:
**0.788870 s**, saving **4.149019 s / 84.0241%** (one end-to-end pair). Repeated
preparation versus one prepared owner for three identical outputs, three
alternating pairs: **1.836554 -> 0.695375 s**, saving **1.141179 s / 62.1370%**.
The latter evidence was reused after the selected-time CLI addition only because
the entire model source/runtime binding and every output identity matched.
Fresh-process partial continuation takes 2.501657 s, including startup; its
source sampling time is zero. Complete retained job storage is 402,993 bytes,
including the 327,172-byte original archive. Native evolution's accounted peak
is 2,428,894 bytes, not a process-RSS measurement. See the full
[evidence and source identities](../evidence/new-world-s5-r1.json).

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

The response schema is `atlas.new-world-evolution-job.v1`. Job states distinguish
`preparing`, `running`, `partial`, `completed`, `cancelled`, `failed`, `interrupted`.
`requested_elapsed_s` describes the requested schedule; `completed_outputs`
describes the committed prefix. A result response contains the separately typed
`atlas.generated-regional-output.v1` scientific object. Errors are safe bounded
codes, including source/input mismatch and native-input/evolution refusal.

The existing UI owner owns the new **regional** evolve action, managed process,
progress/cancel/resume, saved-time selection and rendering actual calculated
fields. Keep the initial world visible on failure. Do not relabel an initial
world-view.v3 as an evolved planet, connect this action to the fixed W12 fixture,
or infer absolute elevation from displacement. Save World still exports the
original initial `.atlas`; this distinct evolution job persists in the managed
local jobs directory and must be labelled separately, not falsely advertised as
included in that portable archive. A future combined portable format is separate.

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
