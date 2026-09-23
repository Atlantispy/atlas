# W07 Step 5 — geological assembly and recoverable execution

23 September 2026. WORKING NON-CANON. Implementation record; combined acceptance
and timing are in progress. The [Step 1 design](W07_REGIONAL_MECHANICS.md) and
[case register](../cases/w07_mechanics.json) are unchanged.

## Implemented connection

`bind_regional_geology` consumes the actual typed W01/W02 initial workflow, not
arrays with a geological-looking label. It preserves geological case, initial
sampling, original thermal profile, material cohorts, forcing, frame, epoch,
datum and source identities. Raw construction of the geological binding refuses.
Inward-positive source depth becomes upward-positive mechanical z explicitly.

Pure ordered horizontal layers supply point viscosity at cell centres and exact
vertical-series compliance over shear dual intervals. This is a stated series
law, not a universal harmonic mixture prescription. Exact layer intersections
preserve cohort volumes and reference masses separately from thermal buoyancy
density. Both original thermal point values and cell means remain available.

`RegionalPhysicsOwnership` and `W07BoundaryMotion` name the owner of gravity,
thermal inputs, imposed motion and surface response. Full physical gravity is
supplied once; only the mechanical solver performs reference-pressure splitting.
Thermal buoyancy replaces the earlier gravitational field, rather than being
added to it. W04 displacement, water loads, extra heating and extra displacement
cannot be attached as duplicate contributions. Replacement boundary scenarios
require zero original S6 motion and their own matching source; uniform retained
S6 translation is a separate route. Out-of-plane motion is not silently dropped.

`PreparedW07Workflow` assembles three compatible routes:

- **Steady mechanics:** original layered geometry and inventories, source-bound
  gravity and explicit closed, translated or simple-shear boundary conditions.
  The homogeneous dry C01 law can additionally use the declared physical pressure.
- **Thermal evolution:** one homogeneous cohort on fixed, closed rectangular
  support; original heat capacity, conductivity and radiogenic production;
  source-labelled boundary data; SSPRK2 heat with first-order frozen-velocity
  coupling and a fresh mechanical endpoint. Viscosity is the explicitly selected
  constant geological law, valid only over its declared temperature interval.
  Optional linear Boussinesq buoyancy does not alter reference material mass.
- **Moving surface:** one homogeneous, isothermal, zero-heat-production material,
  actual Q2 geometry, mapped mechanics and conservative material inventory.
  A separately sourced zero-volume disturbance defines a new synthetic initial
  scenario, never a reconstruction of observed source topography.

Evolved W02 geometry without a compatible ordered-layer/thermal producer, evolved
W03 columns, W06 motion without a vector bridge, mixtures, lateral geology and
spherical sections refuse explicitly. Moving heterogeneous heat/material needs
the corresponding deformed-mesh transfer. These remain named integration
boundaries, not implicitly completed capabilities.

## Recovery, storage and resource ownership

Schedules and cumulative partitions are immutable and source-bound. Requested
outputs are stored atomically in the existing `ArrayStore`. A compact catalogue
deduplicates identical arrays **before** payload copies, by exact dtype, shape
and bytes; no lossy compression or discarded physical fields are introduced.
Existing store compression policies, including zstd, remain selectable.

Recovery verifies the contiguous parent/source/schedule prefix, then decodes only
its newest physical state. It checks geometry, inventory, force, viscosity,
boundary and constitutive bindings, numerical gates and heat accounts without
rerunning completed mechanical solves. Closed heat accounts check source energy,
prescribed fluxes, stored energy and parent continuity. Corrupted or incompatible
records fail; the driver does not silently restart from scratch. Only the latest
output is retained in memory. Solver histories/Krylov vectors are not archived.

One driving thread and one native thread, shared 128 MiB accounted admission,
256 cumulative accepted steps, cancellation and publication checks remain in
force. These are resource-accounting limits, not measured OS RSS. A source
inventory overflow of 136 bytes was resolved by shortening redundant new-module
documentation, not increasing the existing 2 MiB source limit. That inventory is
now near capacity; further module growth must address its bounded representation
explicitly. No numerical tolerance, grid or physical duration was changed to pass.

## Verification and measurements

Pending final combined report. Tests use declared synthetic material controls
passed through the real W01/W02 producer, not Diadem terrain or calibration data.
The codec's independent eight checks passed; all nine geological-binding methods
have passing evidence. Workflow and timing results will be added after completion.

Existing Step 4 evidence was checked against its actual source list: **96 of 98
recorded files are byte-identical**, including the frozen design/case, mechanical,
thermal and surface implementations and reference helpers. Only `__init__.py`
and `reuse.py` changed to register the three new modules/public exports. The old
report is retained as component evidence, not relabelled with today's execution
identity. The new assembled workflow has its own evidence.

Retained failures: one geology cancellation fixture used a callable rather than
the required Event; the affected test passed after correction. The first workflow
run stopped at source-inventory admission before physics. The next exposed a
tuple/list provenance representation mismatch; canonical JSON normalisation
fixed that comparison without weakening source equality. Passing surface coverage
was not repeated for this motion-only correction.

## Software and literature checked

These were documentation/method inspections, not executions of external software:

- [ASPECT 3.0 checkpoint/restart](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html):
  complete physical state and compatible configuration informed exact source,
  schedule and parent binding. Atlas does not copy its old-checkpoint deletion.
- [ASPECT material averaging](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/cookbooks/cookbooks/sinker-with-averaging/doc/sinker-with-averaging.html):
  warnings about blanket averaging informed the explicit pure-layer series law
  and refusal of unsupported mixtures rather than implicit smoothing.
- [ASPECT pressure splitting](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-static-dyn.html):
  full physical gravity and solver-owned reference subtraction informed ownership.

No new paper-derived constitutive law was introduced. The existing solver,
transport, dry-strength and free-surface methods retain the research basis and
component validation recorded in Steps 2–4.

## Delivery

Local changes in Atlas `remake`; no commit, push, installation, R4.4 campaign or
whole-world generation. Completion handoff is pending combined acceptance.
