# W06 Step 2: conservative oceanic birth and spreading

Status: **WORKING NON-CANON — prescribed planar, constant-velocity implementation**.
This implements the material/motion part of the [frozen Step-1 design](W06_SPREADING.md).
See [measured verification](../evidence/w06-birth.md); this is not combined W06
acceptance or empirical validation of generated terrain.

## Model and ownership

An initially empty ocean receives two continuous strips at a supplied ridge.
The ridge position is `r(t) = r0 + vr*t`; a parcel born at offset `tau` follows
`x(t;tau) = r0 + vr*tau + u*(t-tau)`. Each side has its own constant plate
velocity and plate ID. Positive half rates `vr-uL` and `uR-vr` are required.
The supported fixed-source-window family has `uL <= 0 <= uR`; the active ridge
must remain strictly inside that window. Inward trajectories, ridge exits and
time-varying schedules are refused, not silently discarded.

Each phase supplies a fixed reference thickness, reference density and finite
external stock in kg, with distinct phase/feed IDs. Newly created reference mass
is `(uR-uL)*elapsed*strike_width*thickness*density`. The frozen case contains
disjoint 0–7 km crust and 7–100 km mantle layers, not two overlapping full plates.
This prescribed accretion model does not predict mantle melting or breakup.

`PreparedRidgeSpreading.advance` computes a complete candidate from the original
event. It refuses the whole request if any phase feed is exhausted. An unchanged
endpoint returns the identical immutable state and does not debit stock again.
Candidate branches do not authorise spending a shared real reservoir twice:
committing shared feeds belongs to the later workflow transaction owner.

## Exact histories, projection and accounts

Two `BirthStrip` records retain full unclipped affine formation-time histories,
plate/ridge/event IDs and offsets from the explicit onset epoch. For this selected
hot-birth family only, cooling onset equals formation; inherited continental
histories are not represented by these strips and must not be reset to them.

The vectorised cell intersection returns `(side, cell, 3)` values:

- occupied width in metres;
- youngest material age in seconds;
- oldest material age in seconds.

Positive width is validity. Empty cells have zero placeholders, **not valid
zero-age material**. Ages are uniformly distributed within each occupied side-cell
intersection because the birth path is affine. Both sides are retained when a
cell straddles the ridge. `phase_thickness` is only a conservative cell mean;
downstream cooling must use the full age distribution, not cool its mean age.

The per-phase `accounts_kg` columns are created, remaining feed, represented,
left export, right export and material-balance residual. Exports are direct
boundary-crossing integrals, not leftover cell mass. Each phase and the summed
material ledger use the existing W02 roundoff policy. Finite feed debit is
checked separately. The stored residual follows W02's
`represented - created + left_export + right_export` sign convention.

Geometry is evaluated in onset-local coordinates to avoid subtracting rounded
large absolute positions. Unresolvable widths/clock increments and numerical
overflow refuse; no stock clipping, age clipping or tolerance relaxation is used.
The immutable state ID binds its payload and parent; prepared identity binds
the grid, motion, phases, epoch, strike width, source and execution identity.
The new module participates in shared source/live-callable protection.

## Efficiency and limits

Closed-form paths avoid internal advection time steps, scalar per-cell searches
and output-dependent birth bins. Each requested output is O(cells + phases);
the physical history remains two strips rather than growing with output count.
Immutable buffers are reused without an extra conversion copy. A prepared plan
can share an existing source-verifying `ExecutionContext`. Repeated endpoint
reuse is in memory, not a persistent cache claim.

Current caps are 65,536 cells, 16 distinct phases and 256 requested intervals.
WorkBudget leases, cancellation, foreign/closed-state checks and source checks
are retained. As with W02, callers must account for retained output states;
the prepared lease owns its initial state, not arbitrarily many caller snapshots.
The benchmark explicitly reserves caller output allowances. These are accounted
working bytes, not measured process RSS.

Cooling, inherited passive margins, enthalpy/water/support accounts, changing or
stopped ridge histories and durable recovery are the planned later steps. No
stationary W03/W04 assembled adapter is applied to these moving newborn strips.
No disk cache or parallel dispatch is added to this inexpensive vector kernel.

## Reproduction

With the existing NumPy/SciPy-compatible environment, run from the Atlas root:

```powershell
$env:PYTHONPATH='tectonics/src;tectonics/tests'
python -B -m unittest test_w06_spreading -v
python -B -m unittest test_execution_reuse.IdentityTests -v
python -B tectonics/tools/benchmark_w06_spreading.py --output w06-birth-timing.json
```

The fixture binds the unchanged Step-1 design by SHA-256. Changing that design
requires explicit review, not an automatic pin update. The scalar reference has
no production imports: it integrates the birth-time preimage of each cell and
uses two-point Gaussian integration for first/second formation-time moments.
The benchmark compares identical width/age fields at four outputs on 4,000 cells
using three alternating repetitions; setup-inclusive protected outputs and
same-state request validation are reported separately.

## Research/software checked for this implementation

- [Karlsen et al., TracTec author preprint](https://arxiv.org/html/1910.03351):
  selected birth/advection methods and limitations informed explicit continuous
  formation histories and the distinction between prescribed motion and predicted
  dynamics. The reference/production integrals here are independently derived 1D
  paths, not a claim to implement the full tracer model.
- [Official pyGPlates conjugate-isochron example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_create_conjugate_isochrons_from_ridge):
  documentation/example code checked for conjugate birth geometry and separate
  plate identities. No pyGPlates runtime was installed or executed.
- Existing Atlas W02 material ledgers and W05 preparation/resource/source guards
  were inspected and reused where their contracts apply. No new dependency or
  external code copy was required.
