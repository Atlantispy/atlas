# W03 increment 3: drained compaction and partial rebound

22 September 2026. WORKING NON-CANON, local `remake` implementation. A forward,
history-dependent, saturated **already-drained equilibrium** column model, not
Athy backstripping relabelled as physical unloading. This completes the selected
compaction increment; the subsequent [bounded W01/W02/W03 assembly](W03_WORKFLOW.md)
now covers stationary fixed-area integration, not general coupled transport.

## Constitutive choice and physical limits

Each ordered solid parcel has void ratio `e = pore volume / grain volume`, current
compressive effective stress `s` in Pa, maximum past stress `p`, and an explicit
material/mixture law. For a new stress `s_new`:

```text
p_new = max(p, s_new)
e_new = e - (Cc-Cr)*ln((p_new+s0)/(p+s0))
          - Cr*ln((s_new+s0)/(s+s0))
```

`Cc` and `Cr` are dimensionless **natural-log slopes** with `0 <= Cr <= Cc`.
A conventional base-10 compression index is divided by `ln(10)`. `Cr=0` selects
no rebound; `Cr=Cc` is the explicitly selected reversible limit, not a default.
Unloading preserves `p`; reloading below the previous maximum does not impose
the virgin compression slope again. Separate slopes preserve irreversible
compaction instead of restoring all depositional pore space after unloading.

`s0 > 0` is a caller-supplied low-stress regularisation/reference scale. It keeps
the law finite near a free surface. This shifted-log law is an explicit Atlas
approximation, **not Fowler & Yang's complete nonlinear equation of state** or
an automatically fitted sediment law. The caller supplies provenance, maximum
effective stress and minimum/maximum porosity. Out-of-range results refuse, not
clip. Neither unknown porosity nor unknown maximum past loading becomes zero.

Assumptions: connected saturated pores, hydrostatic pore pressure, constant grain
and fluid densities, no grain crushing/dissolution/cementation, no lateral grain
exchange during the update and a prescribed common area for a column. External
effective traction is supplied, not inferred from an unlabelled total load.
No drainage timescale, permeability, trapped excess pore pressure, unsaturated
response or horizontal stress evolution is solved. Transition time labels order;
it does not establish that drainage actually completed within that interval.

## Solid-coordinate pressure, geometry and fluid accounts

For parcel `i` with invariant grain volume `V_i` in m3, density `rho_i`, column
area `A` in m2, fluid density `rho_f`, gravity `g` and top effective traction `T`:

```text
s_i = T + (g/A) * [sum(j<i) (rho_j-rho_f)*V_j + (rho_i-rho_f)*V_i/2]
h_i = V_i*(1+e_i)/A
V_pore_i = V_i*e_i
m_grain_i = rho_i*V_i
fluid_out_i = V_i*(e_old_i-e_new_i)
```

Hydrostatic fluid stress cancels the pore-volume part of total overburden, so
pressure can be evaluated directly from solid inventory; no coupled thickness
iteration is necessary. Changes of `A` affect both self-weight pressure and
thickness. Invariant thickness is **not** substituted for invariant solid volume.

One stress/void ratio is represented per finite material parcel, at its solid-
volume midpoint. It is not an exact continuous solution within a thick layer.
The independent continuum test demonstrates second-order parcel refinement.
Use sufficiently resolved parcels for the requested geometric accuracy; they
need not coincide with a terrain pixel or change with the horizontal grid.

Every component retains its W02 cohort, solid-volume fraction, true grain density
and source. A homogeneous grain mixture uses volume-weighted density; its
compaction law must be supplied explicitly, **not averaged from component laws**.
Bulk-reference rock density is not interpreted as intrinsic grain density.

`advance_compaction` returns per-column signed fluid volume/mass exchanges and
per-parcel pore-volume change. Positive means fluid goes to the named reservoir.
`available_reservoir_fluid_m3` is one finite **pooled scalar stock**, not a value
multiplied by the number of columns. Simultaneous outflow can supply other columns
under the selected connected/drained assumption. Insufficient net stock refuses.
The caller owns the reservoir: it must book each returned exchange once and pass
the updated stock to later transitions. This function does not mutate that ledger.

No external vertical-support term is added. Reported depths start at the sediment
top, not an absolute elevation. Changing pore geometry, external isostatic/flexural
support and deposition/erosion are separate effects requiring later assembly.

## APIs, source connection and recovery

- `CompactionParameters` and `compaction_response(...)` supply the broadcast
  constitutive law. Final output axis is `(void_ratio, maximum_effective_stress_pa)`.
- `GrainComponent`, `CompactionParcel`, `DrainedCompactionConditions` and
  `CompactionState` retain ordered grain inventories, model/provenance, area,
  traction, epoch, depth datum, source/parent identities and maximum loading.
  Arrays use `(parcels, independent columns)`. An absent parcel must be removed
  explicitly; a zero grain volume cannot carry an undefined void ratio.
- `compaction_from_geological_column(...)` imports the explicitly selected W01
  **authored top sediment stack**, with caller-selected subdivisions/laws/history.
  True grain/fluid basis and known source-bound densities/porosity are required.
  `maximum_effective_stress_pa='normally-consolidated'` is an explicit caller
  assertion of no greater past loading, never an inferred default.
- `compaction_geometry(...)` returns checked thickness/depth, porosity, grain and
  fluid mass, bulk density and effective stress.
- `advance_compaction(...)` performs one functional equilibrium update with
  prescribed area/traction and explicit reservoir stock. Original state is unchanged.
- `save_compaction_state` / `load_compaction_state` use the existing deduplicated
  `ArrayStore`. Self-contained state snapshots preserve maximum loading and exact
  continuation; parent/source IDs retain lineage without decoder dependencies.
  External reservoir accounts and thermal state are not silently included.

The authored-column adapter does not spatially sample intrusions/faults or pretend
that W02 mixed-cell cohort amounts establish vertical stratigraphy. Remapping or
mixing maximum-load history needs a separate explicit integration contract.
This increment does not replace original geological descriptions or W02 inventories.

## Efficiency and numerical protections

Batch independent columns; group equal material laws without rehashing parameters
for every parcel. Stable `log1p` ratios avoid cancellation; range-aware scaling
handles large shifted stresses and small representable changes. Explicit numerical
limits refuse rather than manufacture zero. These precautions do not eliminate
ordinary rounding when a change is smaller than the precision of stored `e`.

Admission covers array shapes and metadata/component sizes **before capture**;
scratch is batched and cancellation leaves the original state untouched. Grain
bytes are shared across transitions, not copied into growing histories. Only
current void ratio, maximum stress and parent identity are needed to continue.
The existing verified cache includes all four constitutive input fields, full
parameters and source/runtime/loaded-callable identities. Cheap calls auto-bypass
disk. There is no new dependency, JIT or forced worker pool for millisecond batches.

## Papers and software actually checked

- **Fowler & Yang (2002), Loading and unloading of sedimentary basins: The effect
  of rheological hysteresis**: [author-hosted full text](https://people.maths.ox.ac.uk/fowler/papers/2002.1.pdf),
  constitutive discussion and loading-history branches. Informed distinct loading
  and rebound slopes, maximum-load memory and the drained/finite-rate distinction;
  it does not calibrate Atlas's offset, coefficients or discretisation.
- **Müller et al. (2018), PyBacktrack 1.0**: [primary paper, section 2.3](https://doi.org/10.1029/2017GC007313).
  Full-text decompaction method reviewed for conserved grain volume and the
  distinction between historical reconstruction and forward physical rebound.
- **pyBacktrack software**: inspected [`well.py`](https://raw.githubusercontent.com/EarthByte/pyBacktrack/master/pybacktrack/well.py)
  thickness/density integration and iterative decompaction, and
  [`lithology.py`](https://raw.githubusercontent.com/EarthByte/pyBacktrack/master/pybacktrack/lithology.py)
  mixture handling. No installation/execution or runtime comparison; no copied GPL
  code. Its depth-law parameter averaging is not imported as an Atlas mixture law.
- **Athy (1930)**: original full text was inaccessible; do not claim it was
  reviewed. Its exponential depth-law context was checked through the later
  primary paper and pyBacktrack source, not selected as our forward unloading law.
- **Existing Atlas**: W01 grain/bulk/fluid conventions, W02 cohort identity,
  resource admission and verified reuse/store machinery were inspected and reused.

See [focused checks and measured batching gain](../evidence/w03-compaction.md).
The subsequent [assembled W01/W02/W03 increment](W03_WORKFLOW.md) covers compatible
thermal fields, ordered stationary material/history and external fluid/load
accounting—not a long R4.4 or whole-world simulation.
