# W04 step 1: physical loads against a finite reference column

22 September 2026. WORKING NON-CANON, local unreleased `remake` implementation.
This completes **load construction**, not W04 support/coupling acceptance or
empirical terrain realism. It does not change `PeriodicFlexure` or apply movement.

## Inputs and physical meaning

`LoadSupport` identifies the fixed horizontal footprints, frame, vertical datum,
finite column height, areas and geometry source. `LoadPhase` identifies each
disjoint rock, sediment-grain, pore-water, water or other inventory phase and its
explicit constant reference density/source. `ColumnLoadState` captures volumes,
replacement density and source/epoch identities in immutable byte-backed arrays.
Reference/current snapshots must share the exact support and phase catalogue.
Use a union catalogue with explicit zero volumes for absent phases, not an
intersection which silently discards material. Different density materials are
separate phases; no undocumented density change is inferred from thickness.

`geometry_source` and thermal coverage sources are caller attestations, not proof
that two polygons or depth intervals coincide. The next W04 step must bind these
to actual W01/W02/W03 geometry, inventory, history and exclusive support ownership.
`epoch_id` names the instant of each snapshot; reference/current may differ. No
time conversion or chronological interpolation is performed by this kernel.

Let A be area, V* the finite supported volume, V the sum of disjoint occupied
volumes, M their inventory mass, f the explicit replacement density and g positive
gravity. For each state, supported mass is `B = M + f (V* - V)`. The applied load is:

`q_material = g (B_current - B_reference) / A`, positive downwards, in Pa.

The implementation evaluates the equivalent contrast form:

`Delta B = sum[(rho_phase - f_current) Delta V_phase] + (V* - V_reference) Delta f`.

This avoids subtracting two large absolute loads. The second term is essential
when replacement density changes. A full support has no replacement material.
Negative volumes, overfilled supports, implicit remapping and unknown catalogues
are refused; volumes are never clipped to make them fit. One uniform replacement
density is prescribed per column. Represent distinct water/air regions explicitly
as phases; this is not a sea-level solver or an infinite background reservoir.

Compaction keeps grain mass unchanged. If pore water leaves and identical water
occupies the vacated volume, its two accounts cancel: compaction alone creates no
extra excess load. If negligible-density air replaces that water, the support
unloads. Fluid arriving elsewhere loads its destination only when that destination
is represented. This kernel neither locates an external reservoir nor proves its
supply: source-bound finite-reservoir placement belongs to the next coupling step.

## Thermal term and double-counting boundary

Optional thermal phases require `BoussinesqMaterial`, its **uncorrected reference
density**, zero extra composition anomaly, explicit fixed coverage, and valid
true volume-mean temperatures for both states. Because this EOS is linear,
volume means give the exact integral for the selected constant-property law:

`q_thermal = g sum[-rho0 alpha (T_current - T_reference) V_phase / A]`.

Cooling increases downward load; heating reduces it. Thermal phase volumes must
remain exactly fixed. Moving/changing thermal coverage is refused until a
conservative thermal mapping exists. All material temperature and small-anomaly
validity bounds remain active. The thermal account is a **diagnostic buoyancy
sheet**, not added/removed physical mass, pore fluid or W02 inventory.

The output of `column_load_change(reference,current,g)` has shape `(columns,4)`:

| Column | Quantity |
| --- | --- |
| 0 | Occupied inventory mass change / area, kg/m2 |
| 1 | Replacement mass change / area, kg/m2 |
| 2 | Thermal diagnostic buoyancy-sheet change, kg/m2 |
| 3 | Total prescribed downward pressure, Pa |

This is the **total change from the given reference**, not a displacement or a
load increment to repeatedly add to an already-loaded state. No precomputed W03
subsidence is accepted as another load input. Integrating this with W03 must still
enforce one owner: it must not apply both local thermal isostasy and flexure to the
same thermal anomaly. Future deflection-created infill belongs to the restoring
term/feedback equation, not both that equation and this fixed-reference load.
There is no dynamic mantle traction, non-Boussinesq EOS or pressure-dependent
mineral phase equilibrium in this step.

## Efficiency and reuse

Inputs are captured/hashed once per immutable state, not once per column or
evaluation. The kernel vectorises across bounded column batches and uses
compensated accumulation across phases, retaining small loads between opposing
large ones. Scratch memory scales with batch size, not an extra full phase cube.
Positive-zero underflow and nonfinite intermediates fail closed; some extreme
representable end results are deliberately refused if their chosen intermediate
scales cannot be represented. This is not arbitrary-precision arithmetic.

`reuse.cached_column_load_change` uses the existing auto-admission, lossless
storage, execution/source identity, claims and cancellation machinery. Cheap work
bypasses persistence. Both snapshot identities, geometry, gravity, input bytes,
catalogue and current execution identity distinguish cached results. Changing
batch size changes workspace, not the numerical method or result identity.
No process pool is imposed on this millisecond-scale workload.

The constructors and kernel reserve transient workspace before allocation.
Caller-retained immutable snapshots need the caller's existing retained-state
allowance. Accounted workspace is not measured operating-system RSS. There are
explicit column/phase limits and cancellation checkpoints. Nothing uses a
platform-specific process/fork path; actual tests/timing here were on Windows.

## Research and existing software checked

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/gmd-9-997-2016.pdf):
  full-text section 2.1, equations 1-2 and infill discussion checked. Informed the
  distinction between imposed pressure and buoyancy/restoring infill. The finite
  material/replacement mass bookkeeping above is our explicit derived contract,
  not a claim that gFlex performs these Atlas source checks.
- [ASPECT 3.0 Boussinesq documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/approximate-equations/ba.html):
  approximation, incompressibility and near-linear-model sections checked.
  Informed the separation of thermal buoyancy from conserved reference mass.

These were paper/documentation reviews, not external software installation,
execution, code audits or cross-solver validation. No empirical data calibration
is claimed. See [focused evidence and measured timing](../evidence/w04-loads.md).

## Next, not silently completed

The subsequent [W04 step-2 implementation](W04_WORKFLOW.md) now supplies actual
stationary W01-W03 adapters and exclusive thermal/support ownership for the
periodic uniform case. Non-periodic/domain-size treatment, variable rigidity and
general assembled support verification remain subsequent steps. No full terrain
or held R4.4 campaign was run.
