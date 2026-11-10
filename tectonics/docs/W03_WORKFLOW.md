# W03 increment 4: bounded assembled columns

Implemented 22 September 2026. The last
selected W03 step joins the three component increments to actual W01/W02 source
inventories and verifies a **stationary, fixed-area, already-drained** workflow.
It is not acceptance of general coupled tectonics, moving stratigraphy or terrain.

## What is connected

`initialise_w03_columns` takes a genuine `RegionalWorkflowState` root and an
explicit authored sediment column. It requires planar sampling, zero represented
face velocity, and support spanning exactly that column's contiguous top sediment
stack. Every sampled unit must belong to that stack: identical amounts from a
different geological column are not proof of the same ordering/history.

The existing W01 compaction adapter creates ordered solid parcels. Their projected
grain and pore volumes must reproduce **each W02 cohort in each cell**, using
`area = grid.spacing_m * reference_width_m`. No material outside the selected
support is silently included, discarded or interpreted as sediment. One named
pore-water cohort is required; the finite external stock is explicitly the same
cohort/material. Multiple water origins need an allocation model and are refused.
The caller supplies maximum loading history, not an inferred deposition age.

Initial thermal reconciliation checks the named source cooling history, epoch,
datum, the same authored lithosphere/plate thickness, boundary values and true
means on every selected depth cell. Half-space inputs additionally match cooling
origin, diffusivity and boundary parameters. Unknown/incompatible fields refuse.
The caller's finite kelvin tolerance and measured maximum mean discrepancy are
retained with source, sample and workflow identities. This is agreement on the
declared cells, not proof that arbitrary within-cell profiles coincide pointwise.

## Evolution and accounts

`advance_w03_columns` accepts a later time and prescribed effective surface
traction. Area, grains, ordering and constitutive laws remain fixed. It:

1. Computes drained compaction/rebound with the retained maximum-stress history.
2. Advances the W02 material clock with an explicit zero-velocity closed-boundary
   transport receipt, then applies signed water removal/addition through existing
   named-reservoir `MaterialEvent` receipts.
3. Books `reservoir_new = reservoir_old + sum(pore_fluid_out)` once. Opposite
   exchanges can supply one another in this connected drained limit. Insufficient
   total stock refuses; it is not multiplied by column count or reset each step.
4. Checks per-cell phase closure, unchanged source grain inventory, total water,
   thermal numerical range and support ownership before publishing a successor.

Mixed inflow/outflow retains the clock, removal **and** addition receipts in one
bounded last-transition record, alongside signed per-column exchange, component
parent/result identities and stock before/after. `transition_record` returns a
detached copy. Functional branching from one immutable parent is deliberate;
continue from the returned state to consume its updated stock and history.

`thermal_diagnostics()` returns cell means, top/base outward heat since the fixed
reference, independently integrated net heat, and `(buoyancy sheet, downward
load, total downward displacement from reference)`. The net heat avoids subtracting
large opposing steady boundary accounts. Unresolved boundary-heat time differences
refuse. Thermal support is owned by `column-isostasy`; no second thermal load is
added to compaction, W02 mass or already-applied displacement. Compaction depths
are measured below the sediment top; they are not another isostatic displacement.

## Physical scope and exclusions

This is a reduced, explicitly partitioned model. The finite thermal plate retains
constant properties and reference geometry; the sediment response is saturated,
hydrostatic and already drained, with fixed reference grain/fluid densities.
Temperature-dependent compaction, pore-water heat transport, changing porosity's
effect on thermal properties, finite drainage time, erosion/deposition, lateral
remixing, deformed thermal meshes and dynamic/flexural support are **not solved**.
Sediment geometry change is bounded by the supplied relative-deflection envelope
times plate thickness; that numerical scope guard is not a physical error bound
or evidence that an arbitrary basin is calibrated.

The selected thermal material is an explicit effective constant-property model;
it is not silently inferred from sediment grain densities. Boussinesq buoyancy
density is never substituted into reference grain-mass conservation. Times beyond
the original frozen-forcing interval select the W03 stationary-column assumption,
not an extrapolated claim of supported regional plate motion.

The bridge refuses transported/mixed source states rather than inventing parcel
order, averaged peak stress or cooling ages. General history-preserving remapping
and fully coupled moving-geometry physics remain separate future capabilities.
No claim of empirically validated whole-world realism follows from this increment.

## Efficiency, caching and restart

Use `evolve_w03_columns(state, ((time_1, traction_1), ...))` for up to 1,024 ordered
steps. It automatically prepares the reference and SciPy execution identities
once and reuses them, retaining all existing live source/runtime checks. Every
intermediate load is evaluated: skipping one could lose irreversible compaction.
For custom stepping, a `W03ExecutionContext` can be supplied explicitly.

Parcels/columns remain batched, equal compaction laws grouped, and immutable solid
payloads shared. Thermal diagnostics for the common profile are evaluated once,
not repeated per sediment column. The last state/receipt replaces the previous
one; the source root is shared and no growing array history is retained. Existing
automatic cache policy bypasses uneconomic millisecond disk work. No new JIT,
worker pool, library or lossy compression was introduced.

`save_w03_columns` uses the existing deduplicated `ArrayStore`, saving the actual
W01/W02 source workflow, compaction history, W02 material, reservoir and combined
binding. `load_w03_columns` checks dependency identities and current execution,
restores the source workflow without re-running geological intersections, and
rechecks initial thermal reconciliation against that source. It does not trust
only a saved error scalar or silently repin a source change. Parent IDs retain
lineage; earlier W03 outputs need not be retained to decode the current snapshot.
Restore verifies the current state/accounts, not an unretained complete trajectory.

## Papers and software checked

- [ASPECT 3.0 Boussinesq documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html),
  equations and incompressibility discussion reviewed for this integration:
  keep reference mass separate from diagnostic buoyancy density. Documentation
  inspection only; ASPECT was not installed or executed.
- [pyBacktrack `well.py`](https://raw.githubusercontent.com/EarthByte/pyBacktrack/master/pybacktrack/well.py),
  stratigraphic-unit/decompacted-thickness interface and grain-volume equation
  inspected. It supports an ordered grain-conserving reconstruction comparison,
  not a history-preserving transport bridge or finite-reservoir solver. No copied
  upstream code, installation or runtime comparison.
- [Fowler & Yang (2002)](https://people.maths.ox.ac.uk/fowler/papers/2002.1.pdf),
  full-text loading/unloading discussion reviewed for the preceding compaction
  increment and retained here: peak-load memory and drained versus transient
  behaviour. This integration introduces no replacement constitutive law or
  newly calibrated sediment coefficients.

See [bounded acceptance and measured sequence timings](#obtained-evidence-22-september-2026).

## Obtained evidence, 22 September 2026

The selected stationary fixed-area W01/W02/W03 assembly passed 63 focused Windows
tests in 31.735 s (nine new plus affected compaction/support/identity/cache). The
selection was test_w03_workflow, test_w03_compaction_columns,
test_w03_thermal_support and execution IdentityTests/CacheExecutionTests.
Python 3.12.14/NumPy 2.4.6 used one native thread; no full-suite/Linux claim.

The synthetic join used four 2 m² columns: 40 m sediment at porosity 0.4 above
60 m at 0.25 gives per-column solid equivalents 24/45 m and pore equivalent 31 m.
Pore water 248 m³ plus reservoir 100 m³ closes at 348 m³ through load/unload/reload.
Time labels differ by 1e12 s, but complete drainage is prescribed, not proven
dynamically. Source grains/reference masses are unchanged by buoyancy.

Actual source/sample/cohort and ordered-parcel checks refuse transported/mixed
geology or multiple fluid origins rather than infer stratigraphy/maximum-load
history. Thermal boundary/means/history/diffusivity/epoch/datum and authored
lithosphere versus model plate depth are reconciled. Both signs of mixed W02
exchange remain in the last-step account. Restore rechecks the actual thermal
source, peak history and stock; restored/uninterrupted/forced-cache successors
are bit-identical. Net heat is integrated directly; unresolved increments refuse.
Independent mass/heat/support accounts, insufficient stock, invalid clocks,
budgets/cancellation and nonaccumulating reference queries were checked.
Import/backend and typed-JSON restoration defects were repaired before the final
run without relaxing tolerances.

[Raw sequence timings](../evidence/w03-workflow-timing.json) compare six sequential
load/unload steps, 256 columns × 128 parcels (196,608 updates), three alternating
repetitions after equivalence warm-up. Separate setup 3.261035100 s versus shared
sequence setup 2.181135000 s saves 1.079900100 s (33.115255%), with identical final
state. Both include context setup/close; shared initialisation is outside both.
No intermediate hysteretic load, live source check or precision is skipped; no
cache/worker gain and no addition of earlier component percentages. Entry:
python -B tectonics/tools/benchmark_w03_workflow.py.

The [complete original report](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/evidence/w03-workflow.md) retains source identities,
exact commands/static results and ASPECT/pyBacktrack/Fowler–Yang review extent.
General lateral history remap, multiple-fluid allocation, evolved properties/
deformed thermal mesh, advected pore heat and transient pressure remain outside
this reduced synthetic acceptance.
