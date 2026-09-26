# New-world step 2: variable candidate plate layouts

Status: **WORKING NON-CANON; candidate geometry, not geological acceptance.**
The [step 1 configuration](NEW_WORLD_CONTRACT.md) feeds a real spherical
plate-layout producer. Crust, temperature, motion and a complete initial-world
descriptor belong to subsequent increments.

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
(64 KiB maximum). It validates before generating once, preserves explicit
candidate refusals and atomically saves only successful geometry. Interactive
requests must select at most 1024 support cells, 256 MiB work memory and 120 seconds;
larger requests are refused, not silently downsampled. These are connection limits,
not modifications to the scientific producer or S1 domains. `read` requires no
stdin and restores the existing `.atlas` project. Neither reading nor downloading
the file generates geometry or simulation history.

Both commands return `schema: atlas.world-session-response.v1`, `status: ok`,
`data: WORLD_VIEW`, exit 0. Failures return the same schema with `status: error`
and `error: {code, message}`, exit 2; messages omit private filesystem paths.
Success output is bounded to 2 MiB. The view has exactly:

```text
schema: atlas.world-view.v1
project_id, title, status: WORKING NON-CANON, atlas_id, geometry_id
request: original S1 request
resolved_settings: original sampled/fixed values
configuration_compatible: S1 binding comparison only
capabilities: save_world=true, load_world=true, candidate_geometry=true,
              evolve_world=false, native_restart=false
geometry:
  coordinate_system: unit-sphere
  vertices: [[x,y,z], ...]                  # original native unit directions
  plate_ids: [id, ...]
  patches: [{plate_index, rings:[[vertex_index, ...], ...]}, ...]
  boundary_edges: [[vertex_index, vertex_index], ...]
```

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
admission and native continuation. UI remains configuration-only: this candidate
must not feed the unrelated fixed W12 column demonstration.

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

[Windows evidence](../evidence/new-world-s2-r1.json), Python 3.12.14,
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
