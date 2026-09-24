# New-world Step 3: coherent initial lithosphere

WORKING NON-CANON. A declared initial-condition scenario, not reconstructed
geological history, dry-land coverage or a mature terrain map.

## What is made and why

`tools/new_world_structure.py` makes one native `PrecursorState` from the S1
seed/settings. Three seeded, irregular spherical provinces contain the minority
crust type; the other type supplies a whole-sphere background. Their true spherical
areas add up to the requested continental-crust fraction. A seeded rotation avoids
privileging a geographic pole or map seam. The number/shape/distribution is an
explicit, uncalibrated scenario prior, not an Earth coastline distribution.

Each province has one shared layer stack, crust formation date and thermal model.
Continental columns vary between 30–45 km crust and 110–150 km total lithosphere;
oceanic crust varies between 6.2–8.0 km above a 125 km thermal-plate base. Basalt,
gabbro, granite and peridotite reference records come from the retained material
library. Reference mass is not hot-state mass or an equation of state. Porosity is
explicitly zero added pore volume in this dry bulk-reference scenario.

Oceanic columns use the existing W03 finite-plate solution with seeded cooling
ages of 10–120 Ma. Their crust formation and cooling dates coincide under the
declared no-reheating assumption; mantle formation remains unknown. Continental
crust formation ages (400–3000 Ma) are independent of the prescribed steady
layered conductive geotherm. No continental cooling onset is fabricated.

The temperature calculation uses explicit constant model conductivities and
volumetric heat production, not a silent extrapolation of room-temperature rock
measurements. Temperature and heat flux are continuous across continental layer
interfaces. Compact linear profile tables have a mathematical interpolation
error bound of at most 0.05 K; the native sampler integrates those tables with
spherical radial-volume weights. The interpolation bound is not total physical
error. Adjacent initial provinces need not already be laterally equilibrated.

Inherited continental traces have widths/depths but unknown strength. They do
not create active fault slip, accumulated damage, stress, collision histories or
subduction slabs. Motion and boundary reconciliation belong to Step 4.

This named Earth-like scenario requires radius at least 3000 km, so the largest
150 km column has depth/radius <= 0.05. That admits a planar thermal-column
approximation; it is not a bound on its physical error. Other radii need another
explicit scenario, not automatic rescaling of Earth crust.

## Native reuse, efficiency and persistence

The underlying features do not depend on plate count, support resolution or
sample order. Native `GeologicalCase`, `PrecursorState`, `PreparedPrecursor` and
`ArrayStore` retain material inventories, proper mixed-cell integration, reference
provenance, bounded workers, compression and immutable restore. No new cache or
parallel worker pool is added. Fixed small feature/profile preparation stays
serial; prepared native sampling remains the scalable consumer route.

Area fitting evaluates 32-direction rings, constructs each native polygon once,
and never searches for another seed. Named SHA-derived streams separate geometric,
crustal and thermal variation. Native source/runtime identity and both adapter
source identities are retained. Existing saved results are not rebound.

Project v2 adds only `structure_id` to the existing project manifest and stores
the native precursor and compact receipt in its existing Zstd array store.
Legacy v1 layout-only projects remain readable without invented geological data.
Opening a project restores its actual values and never runs either generator.

## UI handoff contract

`new_world_session.py` will emit `atlas.world-view.v2` inside the unchanged
`atlas.world-session-response.v1` envelope. Existing fields are retained, with
`capabilities.initial_structure` and `structure` added. `structure` is null for
a legacy layout-only project; otherwise it is `atlas.initial-structure-view.v1`:

- `structure_id`, `state_id`, frame/epoch/time/depth reference;
- actual `continental_fraction`, scenario status, assumptions and references;
- `columns`: crust type, crust/lithosphere thickness, material layers,
  formation/cooling ages, thermal-model assumptions and interpolation bound;
- `provinces`: column references and domain/geometry selectors;
- `precedence`: highest-priority province first, background last;
- `features`: named Polygon/LineString geometry in original unit directions;
  polygon rings include their closing point, connected by minor great-circle arcs;
- `thermal_profiles`: shared depth/temperature tables in metres/kelvin;
- `weak_zones`: trace references, depth interval, width, null strength and reason.

The UI owner should expose crust type/thickness/age, thermal inspection and inherited
structure from these actual values while keeping plates independent. Continental
crust is not necessarily emergent land. Do not derive final terrain or silently
use patch centres as cell averages. Inspection uses province precedence, not plate
IDs. Preserve v1 load/save, exact downloaded archives and old-world-on-error.
The backend adapter identity changes, so the UI server must capture the new source
in a fresh process. Do not weaken its drift guard.

## Sources checked

- [Fraters et al. (2019), Geodynamic World Builder](https://se.copernicus.org/articles/10/1785/2019/):
  reusable geometric features carrying composition and temperature independently
  of the numerical grid. No upstream code is copied.
- [White, McKenzie & O'Nions (1992)](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/92JB01749):
  normal oceanic crust reference near 7.1 km. Our seeded range is a scenario prior,
  not a fit to that paper's distribution.
- [ASPECT initial-temperature documentation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Initial_20temperature_20model.html):
  layered conductive continental geotherm, explicit surface/LAB boundary values
  and consistent thermal parameters.
- [Solid Earth 14, 1155 (2023)](https://se.copernicus.org/articles/14/1155/2023/):
  35 km crust / 120 km lithosphere as a published model configuration, not a universal
  Earth value. Atlas varies declared model thicknesses rather than calling them observations.
- Retained [W03 finite-plate derivation and sources](W03_THERMAL_COLUMNS.md),
  including Parsons & Sclater (1977), Stein & Stein (1992) and the existing ASPECT
  comparison: the already implemented thermal solver is reused.

## Verification scope

Focused checks cover seed replay/variation, independence from support/plate count,
exact spherical coverage and conservative mixed-cell volumes, thermal interpolation
and interface balance, source refusal, native project recovery and bounded session
wiring. Measured results are recorded on completion; this document does not itself
claim that an unrun test passed. No whole-world evolution campaign is required.

### Obtained Windows evidence, 24 September 2026

[Bound measurements](../evidence/new-world-s3-r1.json): six thermal, six structure,
twelve project and twelve session checks pass. The mixed-cell test verifies each
cohort volume as well as total volume and temperature-volume integral against
disjoint child queries, within the unchanged 2e-11 tolerance. Seed replay and
plate-count/resolution independence are exact; pure ocean, pure continent,
half-and-half and continent-majority scenarios are exercised. Poles/seam, profile
balance and interpolation, retained unknowns, source/memory refusal, exact native
recovery without generation, legacy archives and shared deadlines are covered.

Commands from the repository root use the existing scientific Python environment:
`python -B -m unittest discover -s tectonics/tests -p test_new_world_STRUCTURE.py -v`,
substituting `structure`, `thermal`, `project` and `session` for `STRUCTURE`.
The new thermal source/budget guards and strengthened per-cohort assertion were
rerun individually after those assertions changed, not via another full suite.
Required static source-map check passes; coding-safety tests pass 30 checks with
one explicit Windows symlink-privilege skip in 0.109 s. No Linux run is claimed.

On the six-plate/192-support fixed case, structure preparation takes 1.055 s on
the first lazy scientific import and 0.184–0.192 s already loaded. The two loaded
creation/save versus recovery pairs average **1.163 s versus 0.324 s**: **0.838 s /
72.11% less elapsed time** by restoring saved work. Including the first import in
the three-pair average gives 1.461 versus 0.313 s (78.60% less). These are small-case
recovery comparisons, not a physics-solver speedup or a whole-planet forecast.
The archive is 313,649 bytes and its view 65,824 bytes. Four shared profiles use
315 knots altogether; the largest analytical interpolation bound is 0.039772 K.

Backend completion and UI integration are separate: the UI owner received the
actual v2 fixture and final backend hashes, with a direct completion return due.
