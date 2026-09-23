# W06 Step 4 — changing plate-motion histories

22 September 2026. WORKING NON-CANON. This extends the frozen
[W06 design](W06_SPREADING.md), [birth geometry](W06_BIRTH.md) and
[cooling/support adapter](W06_COOLING.md). The Step 1 design bytes and numerical
gates are unchanged. Checks and measured performance are recorded in
[the Step 4 evidence](../evidence/w06-history.md).

## Events and material history

`RidgeHistoryEvent` supplies its offset from the named forward-running onset,
ridge position, left/right/ridge velocities, side plate IDs, activity, event ID
and source ID. Events start at offset zero, are strictly ordered and have unique
IDs. Between events, trajectories are affine. At an event, the new interval owns
the boundary while the preceding interval contributes its completed births only
once. An output request does not create a new physical cohort.

Ridge position must equal the position reached by the preceding motion. Arbitrary
ridge jumps and changed ridge identity refuse rather than create overlapping crust.
Asymmetric relative rates and continuous ridge migration are supported. The active
fixed-window route retains outward side velocities and positive relative spreading
on both sides, preventing exported material from silently re-entering. A stopped
welded boundary has all three velocities zero. It creates no material, but existing
crust continues to age and cool; subsequent supported restart adds new birth strips.

An explicit `PlateReassignment(side, from_plate_id, to_plate_id, source_id)` is
required for every changed side owner. Inherited birth event, source, original plate
and cooling onset remain unchanged. Current ownership is separate from origin.
No geometry or mass is added by reassignment; material already exported retains
its owner at first exit, not a later reassigned owner.

For a parcel born at time `tau` in a stage with ridge/side velocities `vr_i,u_i`:

```text
x(t;tau) = r(tau) + sum_k u_side,k * duration([tau,t] intersect stage_k)
dx/dtau = vr_i - u_i
formation_age = cooling_age = t - tau
```

The birth-time Jacobian depends on the birth stage, not the current rate. Each
semantic active interval therefore creates two affine strips with their complete
birth-time distributions. Intersect those strips with cells; do not infer old ages
from current ridge distance, average separate birth intervals before cooling, or
create tracer-age floors. Centres on the ridge are actual age samples, including
after spreading stops, not missing cells.

## First exits, heat and water

Each export record splits at both its birth stage and its exit-motion stage.
Solving the affine parcel path against the fixed boundary gives paired birth,
exit-time and exit-age endpoints. Endpoints are ordered by increasing birth time:
**exit age need not increase in that order**. A thermal mean uses the full range,
including the equal-age limit, weighted by exported width.

Exports retain original birth identities, the actual owner/event/source at first
exit and the named external destination. Heat, water and reference mass cross once.
After exit, further cooling or reassignment outside the region does not change
that regional export. The existing W06.3 thermal kernel, support owner, validity
limits, finite reservoirs and account tolerances are reused unchanged.

The frozen switch control changes rates after 10 Myr to ridge +5, left -15 and
right +35 mm/year. At 20 Myr the ridge is at +50 km, outer born edges are -350 and
+550 km, created width is 900 km and right export from the +/-500 km source window
is 50 km. Exported births span 0-2.5 Myr; their first-exit ages range from
18.571428571 to 17.5 Myr. The separate stop control creates only 400 km: at 20 Myr
the crust has ages 10-20 Myr, despite no motion since 10 Myr.

## Interfaces and efficiency

`PreparedSpreadingHistory(grid, events, phases, time_s=..., epoch_id=...,
width_m=..., source_id=..., context=..., budget=...)` has `.initial`,
`.advance(state, time_s=...)`, `.phase_thickness(...)` and explicit closure.
`HistorySpreadingState` retains exact strips, compact intersections, centre ages,
coverage, segmented exports and phase accounts. An intersection row is
`cell_index, strip_index, width_m, youngest_age_s, oldest_age_s`; its integer indices
are exactly represented in float64. Empty centres are marked invalid.

`PreparedHistoryCooling(history, parameters, budget=...)` projects that state into
the same cell/centre field and heat/water array layout documented for W06.3.
`HistoryThermalState.exports` contains `HistoryThermalExport(history,
destination_id, enthalpy_j, water_m3)` records. `history` is the exact first-exit
record, not an endpoint-only summary. The inherited continental margin adapter is
unchanged; plate reassignment is not permission to reset or recreate a continent.

Preparation validates and binds the event catalogue. Outputs integrate supplied
piecewise motion directly, without internal time stepping. Cell projection stores
only actual strip-cell intersections, then groups weighted thermal values by cell.
There is no dense events-by-cells tensor or copy of all earlier fields. Compatible
phase-age evaluations retain exact-key deduplication; no approximate age bins.
Source-validated prepared reuse and identical-endpoint reuse remain active.
Monotone outward motion proves that a side's younger material cannot have exited
if its oldest parcel is still inside the window. Such cases skip the quadratic
birth/exit-stage scan and its worst-case metadata reservation. Individual
non-crossing strips are skipped too. This admits the checked 256-event no-export
case within 128 MiB without weakening source or numerical checks.

Measured on the frozen switch: matched 256-cell output takes 0.101052 s instead
of 0.646369 s for independent scalar integration (84.37% less time). Reusing one
preparation across four 4000-cell outputs takes 0.658347 s instead of 1.273474 s
with fresh preparation each time (48.30% less, setup included). These are separate
three-repetition median comparisons, with no approximate physical shortcuts;
the [evidence](../evidence/w06-history.md#measured-performance) retains raw timings,
numerical errors, source bindings and admission accounting.

The accepted-request ceiling remains 256; semantic events also have a finite 256
cap. Memory admission includes temporary escaped metadata used in identities, not
just numerical arrays. Complex histories may exhaust the supplied budget and are
refused without partial debits. Outputs are immutable candidate branches; durable
publication/recovery is Step 5. No disk cache, new dependency, worker pool or
unrequested large simulation is introduced here.

## Papers and existing software actually checked

- [Karlsen et al., TracTec, selected full-text methods 2.1-2.2](https://arxiv.org/html/1910.03351):
  separate tracked age and changing current plate identity; prepare motion data
  outside the output loop. Its Euler stepping, ridge offsets, age floor and tracer
  deletion are not this conservative affine implementation.
- [Official pyGPlates conjugate-isochron example, Details and Advanced](https://www.gplates.org/docs/pygplates/sample-code/pygplates_create_conjugate_isochrons_from_ridge):
  explicit birth time, ridge geometry and conjugate side IDs. Missing IDs are
  rejected rather than replaced with example defaults; its geological time sign
  is not silently copied into this forward-running epoch.
- [Official pyGPlates topological-reconstruction primer](https://www.gplates.org/docs/pygplates/pygplates_primer.html#what-is-topological-reconstruction):
  per-interval ownership and motion. The design inference here is to retain origin
  separately, refuse missing coverage and preserve first-exit accounts instead of
  deactivating/discarding material or silently holding an uncovered point stationary.

The linked documentation/example code and selected paper sections were read;
TracTec and pyGPlates were not installed or executed. Piecewise characteristics and
their finite-volume accounts are derived directly from the frozen W06 equations.
