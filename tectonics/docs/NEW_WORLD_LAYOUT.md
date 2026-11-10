# New-world initial layout and plate motion

Status: **candidate geometry, not geological acceptance.**
The [step 1 configuration](NEW_WORLD_CONTRACT.md) feeds a real spherical
plate-layout producer. [Crust and temperature](NEW_WORLD_STRUCTURE.md) and
[initial motion](#initial-plate-motion) are supplied by their later adapters,
not by this layout producer.

## Save and reopen a project

`tools/new_world_project.py` saves the actual candidate, not just a seed:

```python
from new_world_project import save_project, load_project

save_project('My world.atlas', plan, candidate, title='My world')
restored = load_project('My world.atlas')
atlas = restored.atlas
plan = restored.manifest['plan']
```

With `tectonics/tools` on the Python import path, use these functions where the
producer already has a plan and successful candidate. To inspect a saved file:

```text
python -B tectonics/tools/new_world_project.py inspect --file "My world.atlas"
```

The portable single-file `atlas.new-world-project.v1` container keeps the original
plan, report, native geometry, source/runtime bindings and integrity digests. The
native SQLite ArrayStore provides lossless Zstandard array storage. The outer ZIP
is stored without another compression pass. Reopening verifies and restores the
saved geometry, without running the layout generator or modifying the project.
It works after moving/renaming the file. Save publishes atomically and refuses an
existing destination; save subsequent versions under new names.

Only two fixed archive members are permitted, with a 64 KiB manifest and 64 MiB
database limit. No archive-supplied path is extracted. Source/runtime mismatch in
the S1 contract marks `configuration_compatible=False`: the original layout can
still be inspected with a compatible native reader, but its plan is not rebound.
This is a saved step-2 layout, not an evolved-world checkpoint. The UI's separate
**New World / Save World / Load World** controls now connect to these native
candidate files. `atlas-ui-project-3` JSON remains a presentation/request draft
format with separately labelled controls; it is not a native world archive.

### UI generation and file connection

`tools/new_world_session.py` is the native adapter for **New World**, **Save World**
and **Load World**. It leaves the S1 configuration and native scientific packages
unchanged. The local UI server owns file paths and opaque world tokens; browsers
must never choose server-side paths.

```text
python -B tectonics/tools/new_world_session.py generate --file MANAGED_NEW_PATH
python -B tectonics/tools/new_world_session.py read --file MANAGED_PATH
```

`generate` accepts exactly `{"title":"My world","request":S1_REQUEST}` on stdin
(64 KiB maximum). The current composed command prepares structure, then layout
and motion, preserves explicit candidate refusals and atomically saves only a
successful project. Interactive
requests must select at most 1024 support cells, 256 MiB work memory and 120 seconds;
larger requests are refused, not silently downsampled. These are connection limits,
not modifications to the scientific producer or S1 domains. `read` requires no
stdin and restores the existing `.atlas` project. Neither reading nor downloading
the file generates geometry or simulation history.

Both commands return `schema: atlas.world-session-response.v1`, `status: ok`,
`data: WORLD_VIEW`, exit 0. Failures return the same schema with `status: error`
and `error: {code, message}`, exit 2; messages omit private filesystem paths.
Success output is bounded to 2 MiB. `world_view` now emits
`atlas.world-view.v3`: project/request identities, resolved settings, configuration
compatibility, capabilities and indexed geometry, plus nullable structure and
motion. The [current view contract](#ui-contract-world-view-v3)
owns the field definitions, including `boundary_edge_indices` and the initial
structure/motion capability flags. The original v1 table is not a second current
schema. `evolve_world` and `native_restart` remain false for this initial-world view.

Rings preserve native ordering: outer first, then holes. Close the last index to
the first, using minor great-circle arcs, not straight longitude/latitude lines
across a seam. `boundary_edges` contains real interplate boundaries only; support
tile seams are not faults. Display code must handle globe clipping/map seams and
must not show a demonstration terrain image as this new world's calculated terrain.
The frame is right-handed: +X at longitude 0/latitude 0, +Y at east longitude 90/
latitude 0, +Z north. Equivalently x=cos(lat)cos(lon), y=cos(lat)sin(lon),
z=sin(lat). Outer rings are counter-clockwise and holes clockwise in the outward
native gnomonic chart. Current S2 patches are convex Voronoi support tiles or
convex triangular subdivisions inside a conditioned open hemisphere; a whole
plate is a union of patches, not necessarily convex. Current S2 patches have no
holes, but the exported schema preserves the native hole representation.
Save World downloads the exact managed `.atlas` bytes. Load World uploads bounded
binary bytes, verifies them with `read`, then adopts the view only on success.
Existing worlds survive failed/cancelled/stale requests. UI implementation and
browser verification belong to the Generator UI task.

The local UI connection is integrated: New World draws a fresh seed by default,
with explicit replay override; Save World downloads the actual generated archive,
not subsequent draft changes; Load World validates before replacement. Browser
New/Save/Load, corrupt-file refusal, page-reload recovery and actual globe/map
display have focused owner evidence. No simulation is replayed to open a world.

## How it is made, and what the checks mean

Think of the planet as a fine shared mosaic. Each tile has a measured spherical
area and shares its edges exactly with its neighbours. Tiles support boundary
construction; they are not individual tectonic plates or display pixels.

The original layout route always reused the largest requested number of PB2002
plate areas, normalised to cover the sphere. This route varies those weights
before sorting and normalising them. The default multiplies each reference
weight by `exp(delta)`, with delta sampled uniformly in `[-0.35, 0.35)`.
That width is an **explicit engineering assumption**, not a measured confidence
interval or a universal distribution inferred from one Earth model. Zero width
recovers the exact original targets. No small plate is silently removed.

The existing recursive geodesic-cut algorithm groups connected tiles until
there is one connected group per requested plate. Sparse shortest paths measure
distance through each group. A bounded cut search approximates the requested
areas while checking that both groups stay connected. The atlas builder checks
coverage and consistent edge ownership. It does not smooth boundaries for
appearance or infer fault types from shapes.

Independently named random streams control sizes and support/cuts. This prevents
call-order drift; it does not decouple the physics. Later crust, thermal,
weakness and motion construction must reconcile or reject this preliminary
layout. Matching areas cannot prove realistic tectonic formation.

Numerical checks ask whether the geometry is valid: no missing surface, double
ownership, disconnected plates or artificial longitude seam; a globe rotation
should preserve areas, lengths and adjacency. We also rerun the same seeded cuts
on rotated support and independently compare outline and tiled areas.
Morphology assessment separately
measures size, compactness, boundary turning, elongation and neighbours at
declared observation scales. Reference comparisons respect the existing split
and audited use restrictions (51 eligible ordinary outlines, 43 neighbour-count
records, with further scale-resolution exclusions retained separately);
they cannot turn calibration into independent validation, invent a realism
score or label an arbitrary generated plate as a named Earth reconstruction.

## Causal-generation diagnosis and replacement design

Reviewed 26 September 2026. **Diagnosis/design, not an implemented successor.**
The owner requires correction of the generating processes, not adjustment of
finished outlines towards an Earth-like appearance. The fairing prototype stays
unintegrated. B1 measurements remain descriptive controls.

### What actually causes the three reported defects

| Observation | Generating cause traced in the current code | Consequence for the repair |
| --- | --- | --- |
| Grid-shaped, rapidly turning plate boundaries | `generate_layout_candidate` in [new_world_layout.py](../tools/new_world_layout.py) assigns owners to existing support patches using `_graph`/`_assign` in [plate_layout.py](../src/atlas_tectonics/plate_layout.py). Graph costs use geometric distance, not stress, strength or geological inheritance. Physical boundaries inherit support edges. | Increasing support resolution or fairing those edges does not add a physical boundary-formation mechanism. Separate physical interfaces from numerical sampling, and supply a declared mechanism for their creation and evolution. |
| Similar, rounded continental arrangements | `_footprints` in [new_world_structure.py](../tools/new_world_structure.py) explicitly constructs three nearly equal minority-crust provinces, spaced 120 degrees apart, with small radial perturbations. | This is the starting recipe, not a failed collision or rifting calculation. Broader starting conditions help diversity, but evolving breakup and assembly must actually act on their material. |
| A nearly uniform ocean-age field | `generate_structure` supplies one cooling age per geological column. An ocean-majority world has one oceanic background column; [new_world_thermal.py](../tools/new_world_thermal.py) evaluates its cooling profile correctly for that supplied age. | Repair the age/history producer, not the cooling law. Track crust birth, transport and consumption, keeping inherited ages distinct. |

The entry point [new_world_session.response](../tools/new_world_session.py)
constructs structure, then layout, then motion and saves them. **It does not run
tectonic evolution before publishing the initial world.** Structure is available
before layout but is not an input to the layout function. The subsequent motion
fit changes Euler vectors, not the boundary geometry or continental template.

`_reconcile` in [new_world_motion.py](../tools/new_world_motion.py) fits seeded
Euler proposals under junction constraints and a continental-affinity preference,
then scales relative speed to a seeded target. This is a kinematic initialisation,
not a force balance predicting plate motions. Jagged boundary normals can change
the classified opening/shortening of that same velocity field. Their contribution
to flip statistics is not evidence that every observed flip is physically false.

One bounded dependency experiment confirmed the missing link: seed 41, six plates,
192 support cells, continental fraction changed from 0.30 to 0.40, all other
settings unchanged. Both candidates were accepted geometrically. Vertex positions,
shared-edge indices, interplate edges and patch ownership were exactly equal;
maximum coordinate change was **0.0**. Scientific identities correctly differed.
The two-candidate experiment took **3.080537 s**, excluding interpreter/import
startup. This is a diagnostic measurement, not a speedup or realism acceptance.
It used `test_new_world_layout.plan()` and changed only the fixed continental
fraction in a copied request before resolving it and calling the real producer.

### What existing tectonics can and cannot supply

- Native spherical geometry, geological sampling, material inventories,
  rotation/velocity calculations, thermal laws and save/restart machinery are
  reusable building blocks. Their existing validity limits remain in force.
- The saved-world [regional continuation](../tools/new_world_evolution.py) uses a
  prescribed affine deformation gradient and velocity over an admitted interval.
  It changes local parcel area/thickness and calculates local isostatic change;
  it does not feed those changes back into the global plate network. Running it
  longer is not the missing global generator.
- [W06 spreading](../src/atlas_tectonics/spreading.py) tracks birth and age under
  supplied regional ridge/plate histories. Reuse its accounting and thermal
  concepts, not an assumption that it already generates global ridges or breakup.
- The [force-driven experiment](how-it-works/05-experimental-dynamics.md) has
  constitutive and Stokes components, but is rectangular, has incomplete mature
  acceptance and lacks evolving damage in its coupled heat/composition state.
  It is not a ready-made spherical plate-formation solver. Do not activate R4.4
  or transplant its equations to a globe as an incidental connection fix.

### Replacement order and first implementation boundary

This is Atlas's proposed architecture, informed by the references below; no paper
establishes the complete proposed hybrid as validated. B2, B3 and B4 share a
missing evolution layer and must not be treated as three independent visual fixes.

1. **Introduce a versioned evolving-world state.** Keep shared physical boundary
   curves/junctions, material ownership, birth times, geological columns and
   declared forcing separate from the mesh used to sample them. Every boundary
   needs an origin: prescribed initial condition or a named creation event.
   Preserve existing initial-world saves without silently converting them.
2. **Implement a bounded history producer before a random global scenario.**
   Its first control is prescribed constant rotations with an explicitly supplied
   ridge and any required sink/boundary flux. Move inherited crust, create material
   from actual opening relative to the moving ridge, retain each side's birth
   history, and account for consumption/exports. Advancing independently rotated
   polygons and patching their gaps afterwards is not an admissible algorithm.
   The control tests the transport/accounting connection; it does not resolve
   the physical origin of an arbitrary plate network.
3. **Supply the causal boundary producer.** Couple declared forcing to material
   strength, temperature and inherited weakness; evolve deformation/localisation
   and use supported failure/event criteria to create or change boundaries.
   Specify equations, dimensions, regularisation length, validity regime and an
   independent control before coding a reduced law. Random Euler proposals,
   a shortest-path weakness score or a favourable PB2002 bend score must not be
   relabelled as a force-driven mechanism. A kinematic-only consumer mode is a
   different, explicitly labelled scientific choice, not completion of this item.
4. **Evolve one coherent state.** Boundary changes, motion, continental material,
   ocean birth/age and temperature must refer to the same accepted time and
   geometry. Pass changed material/thermal state back to any active mechanical
   law. Distinguish continental thinning from new oceanic accretion; do not create
   oceanic crust merely because two continental polygons leave a gap. Unsupported
   collision, subduction polarity, junction change or disappearance must refuse
   explicitly, not be resolved by cosmetic clipping or a maximum-age fill.
5. **Connect the accepted producer to New World.** Retain deterministic seed
   streams for genuine initial uncertainty; generate successors from the declared
   history. Derive thermal/support outputs from that history and its inventories.
   Recompute contacts, motions and downstream identities against the final shared
   geometry, then save/display those same data. Initial-condition mode remains
   available but must not masquerade as an evolved world.

The five points above describe the diagnosed generator gap, not the whole
integration scope. The [complete integration plan](INTEGRATION_PLAN.md) now governs
implementation: **I01 closes the scientific model/contract choices before I02's
state and transaction layer**. It also covers W05–W08 joins, global/regional and
external feedback, support ownership, W12 delivery, UI and end-to-end acceptance.
Do not substitute this earlier short outline for that full plan. A history
interface alone does not fix the three realism defects; consumer runtime has not
yet been demonstrated.

For that slice, compare exact finite rotations, zero-motion preservation, born
material ages, area/volume/mass accounts and save/load/restart equivalence. For
subsequent causal generation, vary strength/forcing in controlled cases, rotate
and refine sampling independently of physical length scales, then use the existing
B1 protocol on development and withheld seeds. Do not optimise for minimum bends
or require every small parameter change to alter a thresholded physical outcome.

Start with short deterministic controls and report actual time/peak memory/output
growth before scaling. Reuse exact rotations and shared age/cohort records where
valid; store requested checkpoints rather than duplicate full histories. Keep
dependent time advances ordered, parallelise independent cases only when useful,
and preserve current resource limits. These are design choices, not measured
speedup claims or authority for a whole-planet simulation.

### Research/software checked for this diagnosis

- [pyGPlates: reconstructed crustal thickness and tectonic subsidence](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence):
  inspected the documented API/example. It follows material through supplied
  rotations and topologies; it does not discover an initial plate network from
  forces. Useful model/state separation, not a drop-in generative solution.
- [Karlsen et al., tracer-based seafloor ages](https://arxiv.org/html/1910.03351v1)
  (2019 preprint; published 2020, DOI 10.1016/j.cageo.2020.104508): inspected methods
  2.1–2.4 and stated limitations. Birth, transport and removal derive ages from
  an existing boundary/motion history. Do not blindly copy its fixed birth offset,
  nearest-grid assignment or deletion heuristics into conservative Atlas accounts.
- [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html):
  inspected formulation, prescribed forcing, thermal/material setup and strain
  weakening. It illustrates mechanically generated localisation, but explicitly
  says this shallow example cannot represent realistic complete breakup without
  additional asthenospheric/basal treatment. It is not a planetary generator.
- [Cortial et al. (2019), Procedural Tectonic Planets](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.13614):
  publisher abstract/search-accessible author summary only; the author PDF failed
  to open. Relevant to fast event-driven authoring, explicitly procedural rather
  than a replacement for physically based simulation. No implementation details
  or Atlas runtime forecasts are inferred from the abstract.

These sources were read, not installed or benchmarked in this pass. No numerical
producer, source/runtime identity, historical receipt or acceptance threshold was
changed by this diagnosis.

## Backend interface

`tools/new_world_layout.py` stays outside `atlas_tectonics`. Existing native
source identities, W12 results and step 1 contract bytes are unchanged. It reuses
the native support builder, `_graph`, `_assign`, atlas validation and
`ExecutionContext` guards underlying `generate_plate_layout`; it neither copies
nor monkeypatches the cut algorithm. The original API/recipe is retained.

```python
from new_world_contract import new_request, resolve_request
from new_world_layout import generate_layout_candidate

request = new_request("00000000000000000000000000000000")
request["settings"]["plate_count"] = {"mode": "fixed", "value": 12}
candidate = generate_layout_candidate(resolve_request(request))
if candidate.atlas is None:
    print(candidate.report["rejection"])
else:
    atlas = candidate.atlas  # actual native SphericalAtlas
```

Use scientific Python with `tectonics/tools` and `tectonics/src` on its import
path. Configuration-only preparation still needs only stdlib.

`LayoutPolicy(size_log_spread=.35, max_area_l1_error=.04,
max_relative_area_error=.25)` is explicit and identity-bound. Width is 0..1.
Existing accuracy bounds may be tightened, not widened through this adapter.
They control area approximation, not physical acceptance.

One call requests **one candidate**. It never chooses a more favourable seed,
silently increases resolution, loosens tolerance or retries a failed layout.
The support builder's own bounded geometric-degeneracy attempts retain their
existing provenance. Expected geometry/resource/cancel refusals return
`atlas=None`, `REJECTED`, seed/policy/targets, reason, elapsed time and accounting.
Invalid plans/source changes raise instead of producing a misleading candidate.

Success is `CANDIDATE_NOT_GEOLOGICALLY_ACCEPTED`. The native atlas binds the
scientific plan identity, frame/epoch, exact targets, streams, policy, adapter
hash, native execution/runtime and realised geometry. `candidate_request_id`
alone is **not a cache key**. The attempt's plan ID retains resource limits.
Full scientific identity conservatively invalidates changed upstream settings
even when this preliminary geometry does not yet use them physically. An ID
change alone is never diversity evidence.

Native `save_spherical_atlas` / `load_spherical_atlas` preserve actual arrays and
bindings in the existing lossless store. Step 5 owns complete world jobs, cache
admission and native continuation. The layout function supplies candidate geometry;
the composed UI route adds the separate structure and motion adapters. This
candidate must not feed the unrelated fixed W12 column demonstration.

## Efficiency and resource scope

Size sampling is O(plate count), without global RNG state. Cuts retain sparse
adjacency and three single-source shortest paths per split, not an all-pairs
matrix. There is no duplicate persistent cache or new worker pool for a short
candidate. Existing shared work accounting refuses resource pressure rather
than lowering accuracy. Wall limits use cooperative cancellation, not hard OS
interrupts. Accounted peak bytes are not measured process RSS.

Different support resolution changes the stochastic boundary representation;
it does not resample an identical continuum surface. The assessment reports
sensitivity, not a fabricated mesh-convergence certificate.

## Papers and software checked

- Bird (2003), [PB2002](https://doi.org/10.1029/2001GC000252): existing pinned
  Table 1 transcription and verified boundary dataset, reused as exposed data.
- Morra et al. (2013), [Organisation of the tectonic plates in the last 200 Myr](https://www.earthbyte.org/Resources/Pdf/Morra_etal_Plates200Ma_EPSL_2013.pdf),
  abstract and sections 1–2.2 checked: changing hierarchy and reconstruction
  uncertainty argue against one universal present-day spectrum. The paper does
  **not** calibrate our perturbation width; its fitted distributions are not
  implemented or claimed as this generator's law.
- [SciPy sparse Dijkstra](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html):
  single-source solves, symmetric positive weights and runtime-dependent ties
  support the existing algorithm/identity choices.
- Existing Atlas spherical atlas, reference protocol, common-scale ring metrics
  and lossless store. No new dependency installation or global simulation.

## Measured verification

[Windows evidence](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-s2-r1.json), Python 3.12.14,
predeclared world seeds 0/1/2 with 12 plates and 512 support cells, then seed 0
at 1024 support cells and an explicit 52-plate/1024-cell stress case:

| Case | Generation | Accounted generation peak | Result |
| --- | ---: | ---: | --- |
| 12 plates, 512 support, seed 0 | 1.795978 s | 65,248,730 B | Candidate; numerical checks pass |
| 12 plates, 512 support, seed 1 | 1.566751 s | 65,248,850 B | Candidate; numerical checks pass |
| 12 plates, 512 support, seed 2 | 1.580710 s | 65,248,694 B | Candidate; numerical checks pass |
| 12 plates, 1024 support, seed 0 | 2.950430 s | 107,450,321 B | Candidate; numerical checks pass |
| 52 plates, 1024 support, seed 0 | 1.667067 s | 107,450,321 B | Finite connected-cut search refused |

The complete campaign, including source-verified reference preparation and
morphology checks, took **18.892965 s**. Reference preparation was 1.301531 s.
The separate assessment budget peaked at 118,362,368 accounted bytes; every
budget returned to zero. This is not total process RSS. No matched previous
implementation exists for the new capability, so no speedup percentage is
claimed. The initial output-path permission refusal occurred before generation;
the authorised run then claimed a new evidence file without overwriting work.

All 48 generated plate outlines passed independent area comparisons; maximum
formula disagreement was 1.78e-15 sr against the unchanged 2e-11 sr bound.
All four atlases pass edge/junction/owner/pole/seam/connectivity checks and
rotation, including identical cut assignments after rotating their support.
Three same-resolution seeds have pairwise sorted-area L1 differences of
0.139336, 0.157092 and 0.149773. These differences survive rotation and relabelling:
the worlds are not the same map with different IDs.

Morphology remains descriptive, not accepted. For example, seed 0 at 250 km
observation spacing has median compactness 0.4814, against 0.6140 development /
0.4921 withheld, and median reflex turning 18.4848 radians, against 2.4314 /
0.8511. Those populations have different sizes and plate areas; neither raw
turning totals nor these discrepancies are a calibrated realism test. They
show why size matching alone cannot close shape acceptance. Finer generating
support also changes adjacency and shapes, not just area error. No tuning was
performed against the withheld comparisons; steps 3–4 must supply physical
structure and motion, followed by appropriate conditional/independent challenges.

Focused evidence: 14 layout-contract/native-store checks, 14 morphology/series
checks and 3 final report guards, using targeted reruns after fixture/policy
corrections rather than repeating the campaign. The final report aggregator
also requires every requested case and outline/rotated-cut checks; it was
checked against the retained campaign without regenerating any candidate.
Its later guard-only source identity differs from the historical runner hash in
the unchanged evidence file. Candidate/assessment source bytes remain matched.

<a id="initial-plate-motion"></a>

## Initial plate motion

Status: backend implementation, 24 September 2026.

Evidence status, 26 September: the r1 receipt below predates the committed
frame-neutral motion correction and is historical, not a current-source pass.
The corrected motion now has a fresh [three-case workflow check](NEW_WORLD_EVOLUTION.md#combined-lifecycle-qualification);
this does not replace independent motion/morphology acceptance.

This extends the actual Step 2 atlas and Step 3 lithosphere; it is not the fixed
W12 demonstration. UI rendering belongs to the separate Generator UI owner.

### How this is made, and how we check it

1. **Choose reproducible rotations.** Each plate receives a seeded Euler vector:
   an axis and angular speed. A point moves as `velocity = omega cross position`.
   This keeps each plate rigid and motion tangent to the sphere. The fit eliminates
   a shared reference rotation before fixing the largest plate for display. Both
   re-solving with a different anchor and subsequently changing display frame
   preserve relative motion. This is a plate-fixed frame, not a physical
   no-net-rotation frame. Fixed seed and inputs reproduce the result.

2. **Let the crust affect those choices.** Real continental polygon intersections
   along each boundary enter a small quadratic optimisation. It favours lower
   relative motion through a shared continental province, while remaining close
   to the proposed rotations. This is a declared dimensionless *affinity prior*,
   with coefficient 4, not a strength inferred from formation age or laboratory
   reference density. Continents are not asserted to be intact rigid bodies.
   A regression changes continental coverage and verifies changed directions,
   not merely a changed identifier or a uniform slowdown.

3. **Make junction velocities compatible.** The chosen initial boundary law moves
   a boundary normally at the average normal speed of its two plates. Where at
   least three plates meet, one tangent junction velocity must satisfy every
   incident boundary equation. A nullspace projection enforces those equations
   jointly, instead of assigning independent edge labels. Ambiguous constraint
   rank, exhausted motion freedom or excessive residual refuses the candidate.
   Tests independently recover the normal speeds from the rotations. This is
   instantaneous first-order compatibility, not proof of finite-time stability.

4. **Evaluate whole boundaries.** Exact great-circle intersections divide edges
   at geological features. Analytic normal-velocity zeros split any edge that
   changes between opening and shortening. Shear is retained continuously; no
   rule turns arbitrary convergence into a slab or assigns polarity. Touching
   or coincident crust boundaries retain ambiguity instead of choosing a side.
   Native geometric uncertainty refuses rather than snapping coordinates.

5. **Keep the chronology coherent.** This named scenario initiates the deformation
   at the saved initial epoch. Elapsed event time and newly formed crust volume
   are zero. Existing formation/cooling ages are retained exactly; extension is
   not called a mature ridge on previously old ocean crust. Unknown-strength
   inherited zones remain inactive. Later history/constitutive evolution needs
   its own admitted inputs; the native geological acceptance gate is unchanged.

6. **Store the actual outcome.** All rotations, boundary spans, contacts, junction
   velocities, original age references and assumptions are saved. Opening a
   project restores these records without drawing another seed or rerunning the
   optimiser. Source, configuration, atlas and precursor identities are checked;
   changed bindings are never silently replaced.

### Numerical method and efficiency

For a minor arc `r(s) = a cos(s) + u sin(s)`, with left normal `l = a cross u`,
the right-minus-left relative rotation `dw` gives:

```text
opening(s) = R [(dw dot u) cos(s) - (dw dot a) sin(s)]
shear(s)   = R (dw dot l)
```

The objective uses area-weighted squared departure from the proposed rotations
**modulo an arbitrary common rotation**, plus the length-normalised integral of
squared relative speed on unambiguous
continental spans. Junction equations eliminate their own two tangent unknowns;
the remaining plate system has at most three unknowns per configured plate.
The anchor is removed exactly. A single coordinated native-thread lease avoids
thread-start and oversubscription costs for this small dense solve.

For positive plate-area weights `w`, sum `W`, and Euler residuals `e`, minimising
`sum(w_i * |e_i - c|^2)` over the shared vector `c` gives
`c = sum(w_i * e_i)/W`. The resulting precision is
`K = (diag(w) - w w^T/W) tensor I3`. It annihilates common rotations, but is
positive definite once an anchor removes that three-dimensional freedom.
The same junction nullspace solve therefore stays small and deterministic.
An independent explicit augmented least-squares test checks this elimination;
native tests re-solve with every plate as anchor. Residual centring is a fitting
operation, not the surface integral needed to calculate physical net rotation.

This corrects the original anchored fitting objective, which inadvertently made
the reference choice affect relative motions. Diagnostics identify the successor
as `area-weighted-common-rotation-eliminated.v1`; `relative_prior_adjustment`
now uses the area-weighted centred Euler residual, with its metric explicitly
named. Historical records retain their old values and exact source bindings.

Boundary-length-weighted RMS relative speed is normalised to a seeded 1–8 cm/year
scenario target. This interval is an explicit uncalibrated prior, not a measured
distribution or a prediction for the planet. The achieved RMS is independently
recomputed and saved alongside the target and prior adjustment.

Speed integrals use a positive midpoint-basis decomposition. The tiny-interval
weight `(d - sin(d))/2` uses its small-angle series, so short crust intersections
do not lose their physical sign through subtraction. Scalar integrals sum
nonnegative squared projections. Round-off-sized normal components are labelled
`normal-motion-unresolved`, not classified by an arbitrary geological speed
threshold. Their actual components and numerical allowance remain visible.

No dense global field, time history, new cache daemon, worker pool or second
compression format is introduced. Native geometry and the existing Zstd-backed
ArrayStore are reused. Work reservations cover adapter matrices/records and
native temporary work; they are accounted workspace, not measured process RSS.
Saved records have an 8 MiB cap and the interactive response retains its 2 MiB
cap. One deadline covers structure, layout and motion; native cancellation maps
to the same safe timeout response without publishing a partial project.

### Backend and persistence contract

`tools/new_world_motion.py` provides:

```text
generate_motion(plan, candidate, structure, *, cancel=None) -> WorldMotion
check_motion(plan, atlas, structure, motion, *, current=False)
save_motion(motion, store) -> motion_id
load_motion(store, motion_id) -> WorldMotion
motion_view(motion) -> JSON object
```

`WorldMotion` owns immutable canonical bytes; `descriptor()` returns a detached
object. Full source hashes, native execution identity and every upstream ID are
part of its content identity. Saving checks current compatibility; historical
read-only restoration preserves recorded bindings and does not repin them.

Project v3 extends v2 with `motion_id` and requires its matching structure.
New v3 saves place the **complete** layout report in a content-addressed native
uint8 receipt (1 MiB limit); `manifest.report` is a small typed reference. This
fixes the 1024-patch report overflowing the unchanged 64 KiB manifest limit.
Existing v1/v2 and early v3 inline reports remain readable. The native store's
separate metadata cap is explicitly 2 MiB instead of its 1 MiB default, to admit
the 1024-patch atlas descriptor; this is not the project manifest cap. Its native
workspace allowance correspondingly grows by 4 MiB. Both archive members, the
64 MiB store envelope, no-overwrite policy and lossless native compression remain
unchanged. No JSON report information is dropped.

### UI contract: world-view v3

The response envelope stays `atlas.world-session-response.v1`. The view changes to
`atlas.world-view.v3` and adds `motion` (object or null) and
`capabilities.initial_motion`. Legacy worlds get null; no field is manufactured.
`evolve_world` and `native_restart` remain false for this initial-world route.

The geometry adds `boundary_edge_indices`, parallel to `boundary_edges`. These
are original **native** edge IDs, not offsets into the filtered boundary array.
Join each motion `edge_index` through this mapping. The vertex pair's order is
canonical; interpolate along its minor great-circle arc at `start_fraction` and
`end_fraction`. Never infer fractions from longitude or redraw continental data
using plate ownership. Contacts with zero length are separate point records.

`motion.schema` is `atlas.initial-motion-view.v1`. Its contents are:

- `angular_velocities_rad_s`: plate-ID to forward-time three-vector; frame anchor
  explicitly identified. For display arrows at a unit direction `r`, use
  `omega cross (radius_m * r)`, not the Euler vector itself as a surface arrow.
- `segments`: native edge ID and fractions, left/right plate IDs, possible column
  IDs/crust types, regime, signed midpoint opening, full-interval opening range,
  signed shear, numerical opening allowance, unit midpoint and actual relative
  velocity. Speeds are m/s. Positive opening separates right from left; shear
  follows the canonical edge tangent. All `polarity` fields are null.
- `crust_contacts`: zero-length contacts and all possible column IDs.
- `junctions`: native vertex indices/unit positions, Cartesian velocities in m/s,
  incident native edge IDs and residuals. Do not animate this as validated history.
- `event`, `inherited_zones`, `diagnostics`, `assumptions`, references and identities:
  expose these without inventing active faults, cooling ages or acceptance badges.

Regimes are `incipient-extension`, `incipient-shortening`, `stationary`, or
`normal-motion-unresolved`. Shear can coexist with opening/shortening. A finite
pure transform is not inferred from a small visual threshold. To display cm/year,
multiply m/s by `100 * 31557600`. Scientific detail remains progressively exposed.

UI scope: add actual-motion overlay/arrows and selection/legend details, strict
v3 admission, and preserve New/Save/Load, old-world recovery, source protection
and bounded public asset rules. Use the retained actual fixture supplied in the
handoff; no additional generation campaign or broader UI redesign is required.

### Sources checked

- [pyGPlates velocities](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities)
  and [plate-ID example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_calculate_velocities_by_plate_id):
  Euler velocity and explicit anchor convention; no external software dependency.
- [pyGPlates NetRotationModel](https://www.gplates.org/docs/pygplates/generated/pygplates.NetRotationModel):
  why subtracting an area-weighted Euler average would not be a true NNR frame.
- [McKenzie & Morgan (1969), Evolution of Triple Junctions](https://www.nature.com/articles/224125a0):
  abstract checked for the distinction between instantaneous geometry and
  finite-time stability; this is not claimed as a reproduction of its full model.
- [Bird (2003), An updated digital model of plate boundaries](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2001gc000252):
  geological boundary interpretation requires observations beyond a velocity sign.

The particular continental-affinity recipe is an Atlas scenario prior, not a
published Earth calibration.

For the frame-neutral correction, also checked
[Boyd and Vandenberghe, Convex Optimization, sections 10.1.1–10.1.2](https://web.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf):
equality-constrained quadratic minimisation and nullspace elimination. These
support the numerical method, not empirical calibration of the motion prior.

### Frame-neutral correction and diagnostic scope

The correction changes new generated motions; it never rewrites an existing
world or job. Historical initial worlds remain readable. Running or transferring
source-incompatible regional results continues to refuse under the existing
source guards; it requires its original compatible implementation, not a silent
rebind. The initial-motion record/view shapes remain compatible.

Assessment uses actual boundary arc lengths, not the number of subdivisions.
Normal and sideways relative velocities are evaluated at the same boundary
location; two distant plate arrows are not a local collision measurement.
Convergence can be oblique, and a pair-mean display frame makes two local arrows
opposite by construction, including pure sliding. Neither arrow opposition nor
roughly equal counts of opening/shortening establish geological realism.

Continental affinity and the symmetric initial junction law remain declared
scenario assumptions, unchanged by this correction. Their directional/obliquity
distributions still need reference-data calibration; no appearance-based seed
selection, forced head-on motion or geological acceptance badge is introduced.

#### Correction evidence, 24 September 2026

The [bounded frame-correction evidence](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-motion-frame-r2.json)
compared three retained geometry/geology inputs. Changing the old fit's anchor
changed the boundary-weighted relative field; the corrected fit agreed across all
tested anchors to 2.86e-15. This is reference-frame sensitivity, not physical
ground truth or a geological acceptance. Observed component timings did not
establish a material speedup.

`python -B tectonics/tools/assess_new_world_motion.py PROJECT.atlas` reads an
existing initial world; `assess_motion` can also assess a separately calculated
candidate. Fractions derive from Euler zero crossings; the mean obliquity is a
length-weighted midpoint approximation, not a subdivision-invariant statistic.
The measured normal and shear distributions are descriptive, not a calibration.
The r2 receipt is historical in the [evidence register](../../docs/CURRENT_EVIDENCE.md)
because some project/session and integration dependencies changed. Focused
fit/frame, assessment and affected integration controls passed at their recorded
scope; no rerun, Linux coverage or full physical validation is implied.

### Matched boundary diagnostics (roadmap B1)

`tools/assess_boundary_kinematics.py` measures a saved world, a neutral boundary
input or the admitted PB2002 source with the **same** geometry and velocity
calculations. It does not generate or evolve a world, change its motion fit or
decide whether the world is realistic. The neutral input retains unit-vector
boundary points, left/right plate ownership, sphere radius and Euler rotations;
it also makes prototype measurements reproducible without a private project file.

#### How the comparison works

Imagine laying equally spaced measuring marks along each boundary, then joining
successive marks with short great-circle chords. The bend at each mark measures
how sharply the boundary changes direction. Evaluating the two plates' velocities
at the same chord midpoint gives their relative opening and sideways motion.
Comparing two distant display arrows would not give this local measurement.

The declared scales are **100, 250 and 500 km**, retaining the existing registered
PB2002 scale series. The roadmap's 400 km suggestion is not silently substituted
for 500 km. Changing a scale or classification changes the measurement protocol
identity. Intervals are equal along the original path, not necessarily along the
shortcut chords. Short lines that cannot support the requested sampling are
reported as unresolved with their excluded length, not filled with invented data.

Physical boundaries are counted once. Pieces join only where exactly two ends
of the same plate pair meet; junction endpoints are excluded from bend counts.
Closed loops include their closing turn and closing sign transition. The current
boundary protocol uses one source-anchored loop phase; it does not assess phase
sensitivity. It measures unsigned bend magnitude, **not** plate-outline reflex
turning. Keep the separate two-phase outline/reflex measurements from
`assess_plate_layout_morphology.py`; the two definitions are not interchangeable.

Reports give mean, median, quantiles and fixed-bin distributions, both raw
normal-sign changes and opening/shortening-dominated transitions per 1,000 km,
and shear-dominated length. Signed normal/along-boundary components remain
available, including small values hidden by classification. Obliquity is the
absolute angle from the boundary normal: 0 degrees is head-on and 90 is sideways.
The predeclared shear threshold is 70 degrees, not a claim that every such stretch
is a geological transform. Sign-noise suppression is an explicit floating-point
guard, not a geological uncertainty estimate or a proved error bound.

Class fractions weight the source-path length represented by each chord;
bend/obliquity distributions give each vertex/chord equal weight. Both conventions
are declared. Native-resolution values remain separate: the generated support
grid and PB2002 digitisation have very different vertex spacing. The report flags
sampling finer than the median native edge, where extra samples mostly subdivide
an existing straight segment rather than reveal finer geology.

PB2002 is used only through its existing source-use policy. Development and
withheld boundary selections remain separate; this checkpoint uses development
only. The source's known incidence, overlap and coverage qualifications are not
silently repaired. Distribution differences are descriptive, with no statistical
independence assumption, p-value or universal realism score.

#### First matched checkpoint: retained seed 42

[The recorded comparison](../evidence/boundary-kinematics-r1.json) measures the
existing 13-plate, 1,024-support-cell development world and the paused prototype
against PB2002 development. Both use the **original saved rotations**. Only
prototype vertex positions were transferred by matching native vertex IDs; no
motion fit, native candidate validation or generation was performed.

| At 500 km sampling | Original | Paused prototype | PB2002 development |
| --- | ---: | ---: | ---: |
| Mean bend (degrees) | 37.2422 | 20.1582 | 25.5295 |
| Median bend (degrees) | 34.8917 | 16.8335 | 20.2369 |
| Normal-sign changes per 1,000 km | 0.3230 | 0.1283 | 0.1665 |
| Opening/shortening-dominated changes per 1,000 km | 0.1230 | 0.0795 | 0.0570 |
| Shear-dominated length | 16.82% | 13.12% | 21.19% |

The prototype reduces mean bend by 45.87% and raw sign-change density by 60.26%
against this same world's original geometry. These are **geometric diagnostics,
not speedups or percentages of improved realism**. It is smoother than this Earth
reference, and its shear share moves further away: minimising bending alone would
not be a sound acceptance criterion. Motions must be refitted on the actual
successor geometry in B2 before assessing a generated result.

All 33 generated/prototype chains resolve at these scales. PB2002 development has
113 chains; at 500 km, 1,273.88 km (0.5552%) is unresolved and excluded explicitly.
At 100 km the original median bend is almost zero because most inserted marks
fall inside its much longer straight support edges. That does not establish
smooth real boundaries. The JSON retains all three scales and complete signed
component samples, not just the favourable 500 km comparison.

One Windows CPython 3.12.14 / NumPy 2.4.6 wall-time observation: restore/export
2.2127 s, matched assessment including PB2002 source checks 1.6951 s, combined
3.9078 s before the final report write. This is not a before/after timing trial.
Two portable inputs total 67,112 bytes; the compact report is 1,024,947 bytes.
Original world and prototype hashes were unchanged after measurement.

Replay from the repository root with the scientific environment, choosing a
**new** output path (the tool refuses overwrite):

```text
python -B tectonics/tools/assess_boundary_kinematics.py --input tectonics/evidence/boundary-input-original-r1.json --input tectonics/evidence/boundary-input-prototype-r1.json --reference development --run-id B1-retained-input-replay --report NEW-REPORT.json
```

The input hashes, tool hash, protocol and reference identities are recorded.
The [evidence register](../../docs/CURRENT_EVIDENCE.md) checks tool/input bindings;
runtime versions are metadata, not a native-binary or transitive-source seal.
The supplied 25 September Claude baseline used a different world identity and is
not treated as the numerical baseline for this same-seed comparison. No withheld
seed/reference campaign or seed selection took place. Broader seed and loop-phase
coverage belongs to successor acceptance; existing geometry/conservation and
outline/reflex gates remain in force.

#### Checks and sources

The focused tests cover analytic straight/right-angle/closed boundaries,
orientation reversal, junctions, tiny genuine sign changes, pure sliding,
stationarity, unresolved scales and safe input refusal. Euler components are
checked against all 5,819 PB2002 source steps and saved native motion segments.
Checking source arithmetic is not a withheld aggregate comparison. The initial
30-test suite passed in 7.881 seconds; seven new/affected checks for the
component-retention addition passed in 4.804 seconds (overlapping tests, not 37
unique tests). No full simulation or existing acceptance campaign is
rerun for this measurement tool.

At the original B1 capture, `tools/check_current_evidence.py` passed (two current,
nine historical, one superseded); its checked-in-register test passed in 0.083 s.
Those counts describe that snapshot; the maintained register owns current status.
Required `tools/check_coding_safety.py` passes (13 maps/41 paths); its suite has
30 passes and one existing Windows privilege skip in 0.123 s. The public-path
scan passes and its 14 tests pass in 0.756 s. These are source/publication checks,
not additional physical validation. No native solver, generator, dependency pin
or existing result was changed by that diagnostic implementation.

Sources actually consulted for this implementation:

- Bird (2003), *An updated digital model of plate boundaries*,
  [DOI](https://doi.org/10.1029/2001GC000252), through the pinned
  [PB2002 original format and interpretation notes](../reference_data/pb2002/original/README.md).
  Those notes specify great-circle segments, left/right ownership and the
  20-degree-from-strike classification. The publisher fetch was blocked; this is
  not a claim of a new full-paper reading. Dataset attribution: Peter Bird;
  distributed by Hugo Ahlenius/Nordpil/fraxen, ODC Attribution 1.0, with exact
  provenance in the [source manifest](../reference_data/pb2002/SOURCE_MANIFEST.json).
- Official [pyGPlates velocity documentation](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities)
  and [PlateBoundaryStatistic](https://www.gplates.org/docs/pygplates/generated/pygplates.PlateBoundaryStatistic.html):
  local relative velocity, boundary normals, parallel components and explicit
  units. Atlas reports opening-positive, whereas the reference API's normal
  convergence component uses the opposite sign. No GPlates dependency was added.

### Historical measured checkpoint

The [original bounded Windows evidence](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/new-world-s4-r1.json)
records initial-motion generation, save/restore and focused project/session
controls for its stated 192- and 1,024-patch cases. Its restoration comparisons
are reuse of identical outputs, not an evolution-solver speedup. The receipt
predates the frame-neutral correction and is historical, not present-source proof.
