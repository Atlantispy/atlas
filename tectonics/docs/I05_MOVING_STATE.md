# I05a: complete material records, heat on the moving sphere, current properties

**I05a candidate; coordinator verification pending; not accepted.** WORKING NON-CANON.

I05 owns what an I03 cohort's history reference stands for, and how heat, properties, bonds and stress or stretch
evolve on the moving spherical network. I05a covers three substeps:

- **I05.1** transports complete material records;
- **I05.2** moves heterogeneous heat;
- **I05.3** returns current properties and basal exchanges.

I05.4 (phase and supply) and I05.5 (production joins) are not part of this stage. The decisions were proposed with
citations and ruled by the coordinator (4 October 2026); this document records them as built.

**Code.**

| Module | Contents |
| --- | --- |
| `integration_material.py` | records, transport, the I02 attachment hooks |
| `integration_thermal.py` | heat, lateral contacts, the MC-06 reproduction |
| `integration_properties.py` | P1, P2 and the carried P3 |
| `integration_basal.py` | the MC-04 open-base reproduction and its I02 transfers |
| `integration_splits.py` | the I03 history split |

**Tests.** `test_i05_transport.py`, `test_i05_heat.py`, `test_i05_properties.py`, `test_i05_basal.py`,
`test_i05_ledger.py` and `test_i03_history_split.py`.

## 1. What this adds, in execution order

1. **A moving state beside each network state.**
   - A `MovingState` (`atlas.i05-moving-state.v1`) is bound to one I03 `SphereState` by its identity and piece order.
   - It holds one cohort record per I03 cohort.
   - Per piece, it holds the signed heat of each sublayer.
2. **One transaction per interval.** `advance_moving(parent, sphere, step, advance)` follows an accepted I03 step:
   - it transports over the step's own rows;
   - it then conducts heat, if declared;
   - it then commits raw-history increments, uniform within each cohort.
3. **Properties at the state's own time.** P1 columns and the P2 strength state come from one moving state, so they
   share one endpoint. P3 is carried.
4. **Basal exchange.** The open-base strip and its accounts are reproduced from the I01 tool. Its I02 `Transfer`s are
   whole-stock amounts, scaled by the declared attached-window length.
5. **Persistence.** The I02 ledger attaches the moving state beside its network (`Ledger.create(..., moving=)`).
   - Every commit carries the moving step with the column and network steps.
   - A stored moving step is restored by running its transaction again.
6. **The history split, carried in the I03 `Motion`.** It keeps one raw history per cohort when histories diverge.

## 2. Research decisions

### R-1. Moving-grid and material energy fluxes

**Form** (D4, `I01_PHYSICAL_CONTRACT.md` §6). Per cohort, with mesh velocity `w` distinct from material velocity `v`:

```text
d/dt ∫ e dV = −∮ e (v − w)·n dS + ∮ k ∇T·n dS + ∫ Q dV + named exchanges,
e = ρ_ref H(T),   H(T) = ∫_{T_ref}^{T} cp dT'   (J/kg)
```

**Discrete form on I03:**
- **Advection is the interval integral of the first term**, through the I03 step's overlap rows.
  - A face that rides with its plate has `w = v`, so it has zero flux and keeps its exact bytes (I03's identity
    rule).
  - Births, consumption and mesh rows carry each sublayer's heat with I03's own share rule (`_split`): every row but
    the largest gets the correctly rounded share, and the largest gets the exact remainder. Material and heat
    therefore share intersections by construction.
  - Same-cohort parts that arrive in one face add, as I03's accounts add: the finite-volume cell content.
- **Vertical conduction** is exact modal ETD2 per endpoint piece (`_integration_heat.prepare_thermal`,
  `prepare_propagator`, `conduct`).
  - There is one control volume per sublayer, with its node at the midpoint and width equal to the current thickness.
  - The interface conductance is the series form `1/((f−z_i)/k_i + (z_{i+1}−f)/k_{i+1})`.
  - The top is held at the declared surface temperature; the base is at its declared temperature, or insulated.
  - There is no vertical stability limit.
- **Splitting.** Transport first (the I03 step defines the endpoint geometry), then conduction on the endpoint pieces.
  This is first-order Lie splitting. Any coupled time-refinement criterion (I05.5, I04.4) must be predeclared on that
  first-order basis; the second-order [3.8, 4.2] window does not apply to time.
- **Reference.** `T_ref` is a required declared input (IN-05 `enthalpy_reference`), carried in the state's
  identity. No value is chosen in code.
- **Caloric law** (ruling). Heterogeneous constant `cp` per material, so `H(T) = cp (T − T_ref)`.
  - The code goes through `Sublayer.caloric` and its inverse `Sublayer.temperature`, so an admitted `cp(T)` law with
    provenance would slot in. None is admitted.
  - The declared heat of a linear sublayer profile is `ρ h (H(T_top) + H(T_bottom))/2`. This is exact for the
    linear caloric law, where the mean of `H` is `H` of the mean temperature.
- **Interfaces: disjoint-cohort.** Different cohorts in one face keep separate heat and are never mixed. Perfect
  contact would need a named mixing law.
- **Ownership.** I05 owns the heat of an attached moving state. The I03 material must therefore carry no enthalpy
  basis of its own (`incompatible support` otherwise): one owner per quantity.

**Independent checks:**
- rigid rotation keeps every heat byte, about the world axis and about an axis tilted by 0.7 rad;
- shifting `T_ref` changes no temperature;
- conduction closes energy per piece to `1e-11` (the existing I01 `algebra_relative`);
- the exact heat accounts close after every step.

**Sources:**
- **Inherited:** `I01_PHYSICAL_CONTRACT.md` §6 (D4) and `I01_CLOSURE_MATRIX.md` CM-05.
- **Newly consulted** (3 October 2026, through a read-only extraction): the FiPy official documentation, "Finite
  Volume Method" (stable, version 4.0.3).
  - It was used only to compare the two-point face flux and its orthogonality restriction.
  - FiPy's transient term has no moving-volume term; the motion rows supply it here.
  - No dependency is adopted.

### R-2. Admitted lateral contacts

A lateral contact between two pieces is admitted only when **all** of these hold (ruling: strict):
1. **Shared boundary.** The two faces share one or more I03 edges of positive length. Every shared edge counts.
   When there are several, they must lie on one great circle (their poles agree within the attachment band, with
   the same orientation). Otherwise one two-point flux cannot be orthogonal to the boundary, and the step refuses
   `nonorthogonal contact`.
2. **Single cohort.** Each face holds exactly one cohort piece. Otherwise the step refuses `unresolved contact`, the
   D-P2 rule applied to heat.
3. **Declared nodes.** Each face has a declared node direction (a caller input; I03 stores none). The node must be
   a finite nonzero vector (else `missing record` when the `Conduction` is built). It must name a face of the
   network and lie inside that face: an even-odd test in the face's gnomonic projection, where its great-circle
   edges are straight, inside the outer ring and outside any hole. Otherwise the step refuses `incompatible support`;
   an antipodal or foreign node is never admitted.
4. **Orthogonality.** With `n` the pole of the shared boundary:
   - `|n·(s_i × s_j)|` must lie inside I03's existing 64 ε attachment band. The product is not normalised, so as an
     angle the tolerance is `64 ε / sin φ` for nodes `φ` apart: about 9e-14 rad at 1000 km and 9e-12 rad at 10 km.
     That is physically negligible, but it is not a 64 ε angle;
   - `(n·s_i)(n·s_j) < 0`;
   - the node line must cross inside one of the shared edges.
5. **Same depths.** The sublayer depths are identical within I03's existing relative tolerance (`1e-12`). Otherwise
   the stacked two-point flux is not horizontal, and the step refuses `nonorthogonal contact`.

**Conductance per sublayer:**
- `G = A/(d_i/k_i + d_j/k_j)` (series resistance, never an average of `k`);
- `d = R asin|n·s|`;
- `A = R θ t`, with `θ` the summed arc of every shared edge and the thinner side's sublayer thickness `t`.

The adversarial verification of 4 October 2026 found that the first build kept one edge per face pair. Two faces
sharing two edges conducted over half their boundary, and a crossing on the other edge was refused with the wrong
message. Its probe is now a test: bands 1 and 2 merged in every sector, so neighbouring merged faces share two
meridian edges. The conductance uses the whole boundary, and crossings on either edge are admitted.

**Geometry convention.** This is the prism convention of I03's `V = h A`, with the wedge factor `1 − z/R` omitted and
declared.
- **Where the error is.** `R` cancels in `G = R θ t/(R asin_i/k_i + R asin_j/k_j)`, so using `R − z` for both the area
  and the distances gives the same `G`. The omission therefore lies in the capacity and thickness: about `2z/R` in
  volume at depth `z`.
- **Size.** The order of magnitude is `z/R`:
  - 7 km / 6371 km ≈ 0.11% for the control crust;
  - 150 km / 6371 km ≈ 2.4% at a lithosphere base.
- **Per run.** Each conduction report gives the run's own `max_thickness_over_radius`.

**Limit.** On generic I03 meshes most contacts refuse. This is a declared v1 limit; declared nodes or conforming faces
are the lasting route.

### R-3, option (b). The lateral rule

The lateral mode is declared by the caller (`Conduction`), never switched automatically.
- **`solve`.** Each declared substep is Lie splitting of two operators:
  1. an explicit (forward-Euler) lateral exchange over every admitted contact: `T_i ← T_i + Δt Σ_j G_ij (T_j − T_i)/C_i`;
  2. then the exact modal vertical conduction of every piece, with no source.
  - Every pair of faces that share an edge must be admitted, or the step refuses.
  - **Stability:** `Δt (ΣG + G_bdy)/C ≤ 0.9`, accepted to `(1 + 8 ε)`. This is W07's limit (`regional_transport`)
    applied to the operator that is integrated explicitly. That operator is the lateral exchange, whose lateral
    boundaries are closed, so its `G_bdy = 0`. The boundary conductances belong to the vertical operator, which is
    integrated exactly. The caller declares the number of substeps; there is no automatic substepping.
  - **Maximum principle.** Under the limit the exchange is a convex combination of a cell's own and its neighbours'
    temperatures. The exact vertical solve keeps the maximum principle too, so their composition keeps it. Without
    radiogenic heat, every temperature after every substep must lie within the range of the starting temperatures
    and the fixed surface and base temperatures. As in W07, the check uses 128 ε of the extreme magnitude, and the
    step refuses `unsupported` (detail `maximum principle`) otherwise.
- **`omit`.** Admitted only with an MC-06 certificate, using the package reproduction of the tool's exact `admission`
  (§9):
  - the certificate is captured at construction as canonical JSON text: plain data with finite numbers only, so a
    later edit of the caller's object cannot reach it;
  - it declares only its **windows** (whole-window envelopes, one difference bound per contact in the order of
    `omission_cells`) and its **temperature allowance**; declared cells or conductances refuse;
  - it holds **exactly one window** per interval (coordinator ruling of 4 October 2026, heat-R1-01). The state
    samples only the interval's start and end, so the envelope of a middle window could never be refuted; a
    certificate of two or more windows refuses `unsupported` (detail `certificate`);
  - it is re-run on **the state's own network** and must pass;
  - its window must cover exactly the interval;
  - the window must keep every contact: no rows, no mesh change, no events, every plate turning alike;
  - its envelopes must not be **refuted by the state's own temperatures**;
  - its initial error bound is the **carried bound**, which must be known.

  Each of these is set out below.

**The state's own network** (ruling (c), 4 October 2026: conductances are derived, never free).
- **Cells.** One cell per piece sublayer, in I03 piece order, top down, with the state's own capacity `ρ cp t A`.
- **Contacts and conductances.** These are the R-2 contacts that `solve` would use, with their `G` derived from the
  declared IN-05 `k` and the declared nodes. An omission therefore needs the same nodes and admitted contacts as a
  solve. A mixed face or a missing node refuses, as it does there.
- **Topology check.** The admitted contacts must be exactly `omission_cells`' topology: every pair of sublayers that
  overlap in depth (beyond I03's relative tolerance) in two pieces of faces sharing an edge, or in two pieces of one
  face. None may be missing and none invented.
- **Size.** MC-06's own policy bound of 256 cells and 1024 contacts applies unchanged. A larger state cannot omit
  lateral conduction.

**Refuted envelopes** (review heat-1). The state's temperatures at the window's start, and the column-only temperatures
the omission computes at its end, are samples of the trajectory the envelope must bound.
- An envelope bound below `|T_i − T_j|` of either sample refuses `unsupported` (detail `certificate`), compared
  exactly.
- A sample cannot prove an envelope, but it can refute one. This adds no number.
- **Fixture envelopes.** The fixtures declare the range of the start and fixed boundary temperatures. Without
  radiogenic heat, the column-only maximum principle makes that a valid whole-window bound.

**The carried bound.**
- The moving state carries the bound in its record as `lateral_omission_error_k`. A declared state starts at zero.
- Each passing omission carries its bound on. The stored value is the least binary64 number not below the exact
  bound, so it stays an upper bound and its record stays bounded.
- A solved interval keeps the bound unchanged. The coupled propagator does not expand the max norm.
- An interval **without conduction** (advection only) leaves the column-only trajectory, so the bound becomes
  `UNKNOWN` (review heat-2).
  - A later omission refuses to chain from it.
  - A solved interval keeps it `UNKNOWN`.
  - Only a new declaration starts a chain again.
- A certificate that declares another initial bound refuses. The bound is never reset (`I01_LATERAL_HEAT.md`).

The adversarial verification of 4 October 2026 found three defects in the first build, each now covered by a test:
- **No tie to the state.** The certificate was not tied to the state: a one-cell, contact-free certificate with a
  zero allowance was admitted. On a 20 km sphere, omitting lateral heat then changed temperatures by 2.141 K against
  `solve`.
- **Bound reset.** The bound restarted at zero every interval.
- **Draining twice.** The first scheme fed the lateral flux to the vertical ETD2 solve as a source frozen over the
  substep. At a ratio of 0.89 that drained a hot column twice, through the frozen flux and its own vertical cooling,
  to 267.2 K: below every starting and boundary temperature of 273.15–373.15 K. The splitting above replaces it.

Option (a), an extended MC-06 bound for moving geometry, is not built.

**Checks:**
- the conductance equals the series form and differs from an averaged `k`;
- **every sublayer's conductance** of a layered control (unequal sublayer thicknesses, a different `k` in every
  sublayer and on the two sides) is pinned independently to the R-2 series form, computed in the test from the
  declared nodes and `k`, to `1e-12` relative (heat-R1-02);
- lateral heat leaves one column exactly as it enters the other;
- the split scheme approaches the exact solution of the same coupled semi-discrete system as substeps increase. On a
  20 km sphere, the maximum temperature errors at 1, 2, 4, 8 and 16 substeps decrease monotonically. No order
  criterion is set here;
- at a ratio of 0.89, a hot column beside steady cold ones stays within 273.15–373.15 K;
- **the 0.9 edge:** a ratio of `0.9(1 + 4ε)` is admitted and one of `0.9(1 + 1e-9)` refused. The test also computes
  `dt · max ΣG/C` itself, from the independent R-2 conductances, `ρ cp t A` and `G_bdy = 0`, and checks the reported
  ratio against it to `1e-12` (heat-R1-03);
- **one substep reproduced independently:**
  - the forward-Euler exchange with the R-2 `G`, then each column's own operator integrated by scipy's matrix
    exponential, agrees to `1e-11` relative;
  - the reverse order differs by far more;
  - this pins the Lie order and the size of the interface flux;
- **the strict refusals:** different sublayer depths, a kinked shared boundary (an L-shaped face around a corner), a
  node line crossing outside the shared edge, and a node outside the orthogonality band all refuse. A node inside the
  band is admitted;
- **the maximum-principle check fires by name:** a vertical solve that undershoots is injected in the test;
- **omission certificates:**
  - one that declares cells or conductances refuses, as does a mis-sized envelope, a missing node or a reset initial
    bound;
  - a three-window certificate, whose middle window declares 0 K envelopes that nothing samples, refuses by name;
  - the omission network's conductances are exactly the solve's;
  - an envelope refuted at the start or at the end refuses;
- **`omission_cells`** equals hand-enumerated contact sets, for offset sublayer depths and for a two-piece face;
- **the carried bound:**
  - two omission windows that pass alone refuse together;
  - the carried bound survives a solved interval and a restore;
  - an interval without conduction makes it `UNKNOWN`.

### R-6. Belt state and per-column clocks: deferred to I05b/I07

- **Ruling (d) of 4 October 2026.** R-6 is deferred to I05b/I07, and the belt record is not built in I05a.
- **P4** stays reserved and refuses `unsupported`; a test pins the code.
- **I04.3** must not depend on P4.
- No producer of a necking chain exists before I07, and nothing in I05.1–I05.3 consumes one.
- The shape the digests support is recorded for that ruling:
  - ordered columns of fixed material width `dX_i`, stretch `λ_i`, per-column `T` and `κ`, and a per-column clock;
  - an exact split near the minimum-strength column;
  - merges refused.

  I05 would carry it, and I07 resolves it.
- P4 stays reserved and refuses.

### R-7. Stress and stretch memory

- **Default.** Every current route carries `NOT_REPRESENTED`: I02 persists no elastic branch (`elastic_stress_pa` is
  `unknown`). A zero stress is never written, because that is the refused `omit_elasticity`.
- **`ElasticMemory`** holds:
  - the I01 elastic-memory `State` fields, with the I01 bounds `|ε| ≤ 1` and elastic strain `≤ 0.01`, handed to I07
    beyond them;
  - the frame, plane, modulus source and support.
- It is carried by cohort identity only. It is never interpolated, averaged or rebased.

### R-8. Drained compaction on moving columns

- **The drained law is not applied on moving I03 columns.** The W03 law assumes a prism of one area with no lateral
  grain exchange, and its workflow refuses spherical normalisation.
- **Memory survives by identity.** A cohort's `CompactionMemory` (void ratio and peak effective stress per parcel)
  moves with the cohort and is never reset.
- Family worlds have no sediment, so they carry `NOT_REPRESENTED`.

## 3. The records

**`CohortRecord`**, one per I03 cohort. These are carried by identity: one raw history per cohort (ruling I05-2).
- **`sublayers`**, top down. Each `Sublayer` holds:
  - material and I03 phase;
  - declared thickness;
  - `ρ_ref` and `α`;
  - `k`, `cp`, `H`;
  - the declared top and bottom temperatures (the original profile, never reset);
  - optionally `creep_law_id` and `pore_pressure_pa`.

  The sublayers of one phase are contiguous.
- **Provenance:** `profile_id` and `thermal_source`.
- **Boundary conditions:** the surface temperature, and the base temperature or insulated.
- **`cooling_start_s`:** None is unknown, never zero. The formation interval is the I03 cohort's own.
- **`kappa`:** the raw plastic history at each sublayer's material point. Non-decreasing and never filtered.
- **`bond`:** a `BondRecord`, the package reproduction of the I01 bond latch.
  - `ever_broken` changes only by OR.
  - Support only degrades.
  - Nothing rewelds.
- **`compaction`** and **`elastic`:** `NOT_REPRESENTED`, or the carried memory.

**Current thickness of a sublayer.** Its declared thickness times the piece's phase volume over area, divided by the
declared phase thickness. This is uniform strain within a phase (declared), and exact for transport, because volume
and area share the same shares.

**`MovingState`** holds:
- the bound I03 identities: state, network, material, time, step and frame;
- `enthalpy_reference_k`;
- the cohort records;
- the arrays `moving.cohorts` (packed records), `moving.heat_offsets` and `moving.heat_j` (per piece, in the I03
  piece order);
- exact rational heat accounts. `sum(stored) = initial + Σ supplied + rounding`, with `|rounding| ≤ allowance`, half
  an ulp per changed value, as I03 keeps its own;
- the carried MC-06 omission bound `lateral_omission_error_k` (§2, R-3), or `UNKNOWN`;
- `declared_step`, the network step of the declaration it descends from (in the identity; §7's inventory guard counts
  the steps since).

The parties are:
- `ridge|<boundary>|<side>` for born heat;
- the trench destinations for consumed heat;
- `i05|conduction` for the exact stored change of a conduction step.

The physical breakdown of a conduction step (surface, base, radiogenic, lateral) is reported and checked to `1e-11`.

**`BirthColumn`** is the I05 content behind a ridge supply's history reference.
- It must reproduce the supply's thickness, within I03's tolerance, and its mass, within `inventory_bound(0)`, per
  phase: no wider than P1's guard (RB-2; it was `4(n+2) ε`). Each born piece is then checked by P1's own guard at its
  birth step (§7), so a born record that P1 would refuse is refused at birth.
- A born cohort starts with zero raw history and its declared bond support.
- A birth without a column refuses `missing record`. A column declared for no birth of the step refuses
  `incompatible support`: an unused declaration is refused, never ignored.

**`MovingAdvance`** owns its content from construction.
- The increments are `((face, cohort), values)` pairs, with one finite value per sublayer. Minus zero is stored as
  zero.
  - A malformed pair or a non-finite value refuses `missing record`.
  - A negative increment refuses `unsupported` (`h = 0`).
- A stored advance whose content is malformed refuses `missing record`, never a raw Python error.
- When an interval is advanced, a wrong number of values per sublayer refuses `missing record` before any
  `history divergence` check.

**Refusal codes** (`TransportRefused.code`, with `detail`):

| Code | Meaning |
| --- | --- |
| `stale identity` | another I03 state, step or interval |
| `missing record` | an absent or non-finite input, record, birth column or increment |
| `incompatible support` | phases, layering, basis or a birth column that does not match |
| `history divergence` | an update would give pieces of one cohort different histories |
| `unresolved overlap` | rows that do not account for every piece |
| `unsupported` | a regional return (no rows), a negative increment, elastic memory beyond its bounds |

## 4. One raw history per cohort, and the history split

**The rule.**
- Every mutable history is keyed by `cohort_id`. `history_id` stays an immutable provenance pointer.
- Raw-history increments (P6) are committed once per interval and must be equal within a cohort. Otherwise the update
  refuses `history divergence`, with the cohort as detail. Nothing is ever averaged or kept for all.

**The history split** (an I03 amendment, `integration_splits.py`; `I03_SPHERICAL_NETWORK.md` §7 "History split").
- A `HistorySplit(cohort_id, groups)` is carried in the interval's `Motion`, so it is bound into the motion identity,
  stored with the step and applied again on restore.
- Each group is a history reference and face IDs. It relabels the named endpoint pieces of the cohort into one
  sub-cohort, after the motion rows, any mesh change, regional returns and events.
- Each piece keeps its exact stock row, so every account and occupancy allowance is unchanged.
- The sub-cohort keeps material, origin and formation interval. Its ID, `split:` + sha256(cohort, end step,
  history)[:32], is bounded and never nests its parent's name.
- The lineage (parent, child) goes into the step's arrays (`sphere.split_parent`, `sphere.split_child`).
- **Refusals:**
  - an unknown cohort, or a face holding none of its pieces;
  - an empty group, or a piece named twice;
  - an ID already in use;
  - a cohort split twice in one interval;
  - a cohort carried by a regional return of the same interval;
  - a no-op: one group holding every piece;
  - groups that together name every piece, which would leave the parent cohort without one (one history stays in
    the parent, so cohorts never outnumber pieces through a split);
  - a history reference equal to the parent's.
- A motion without splits records nothing new and keeps its identity, so stored histories restore unchanged.

**The P6 flow is two-pass.**
1. Advance without splits (nothing is published) and take one increment per endpoint piece.
2. `split_for_increments` groups each cohort's pieces by equal increment values, with minus zero taken as zero, as
   `MovingAdvance` stores them. Since increments are finite, equal values are bit-equal. The largest group stays;
   each other group becomes a sub-cohort.
3. Advance again with the splits, and commit each sub-cohort's single increment.

**Growth, measured.** A level-1 family world (seed 1, N = 12, f = 0.35; 353 pieces) turned rigidly 0.5° per interval,
with declared synthetic increments:

| Increments | Cohorts per interval (start 20) |
| --- | --- |
| Banded by latitude, the same every interval | 54 after the first interval, then constant |
| Bands shifted 15° on alternate intervals | 54, 87, then constant |
| One distinct value per piece (the worst case) | 353 after the first interval |

The cohort count is bounded by the piece count, as ruled. The exact identity held throughout.

**Growth with mixing, measured** (coordinator condition). The same family turns rigidly 0.5° per interval. In each
interval a mesh change also merges 24 disjoint pairs of adjacent same-plate faces, so sub-cohorts from neighbouring
faces meet in one receiver. Increments take five values per interval, by a deterministic hash of face and interval.

| Interval | Cohorts | Pieces | Faces | Pieces per face, max / mean |
| --- | --- | --- | --- | --- |
| start | 20 | 353 | 240 | 3 / 1.47 |
| 1 | 92 | 323 | 216 | 3 / 1.50 |
| 2 | 236 | 320 | 192 | 5 / 1.67 |
| 3 | 300 | 319 | 168 | 5 / 1.90 |
| 4 | 315 | 319 | 144 | 6 / 2.22 |
| 5 | 318 | 319 | 120 | 8 / 2.66 |
| 6 | 319 | 319 | 96 | 12 / 3.32 |

- On this **rigid** control, the cohort count rises by 72, 144, 64, 15, 3 and 1, and saturates at the piece count:
  nearly one cohort per piece (315 of 319) after four intervals, and one per piece after six.
- Pieces per face grow here because the merges coarsen the mesh (fewer faces, the same pieces).
- This control turns the whole world rigidly. With no motion relative to another plate, it has no ridge, no trench and
  no partial cross-face row, so it cannot show how growth behaves under relative motion. The coordinator's review
  showed that (splits-1).

**Growth under relative motion** (the coordinator's review of 4 October 2026, splits-1; quoted, not re-run here).
- **Control:** the I03 three-plate world, with plate A turning 2° per interval between a ridge and a trench, and the
  two-pass flow with a distinct increment per piece.
- **Result:** pieces per face grow **quadratically**, with a maximum of `1 + k(k+1)/2`: 67 at `k = 11` and 277 at
  `k = 23`. Without splits the same control keeps one piece per face.
- **Mechanism.** I03 pieces carry no position within a face. A partial row carries every piece of its donor, so
  trench-side rows spread each distinct history into the next face, and the slivers never merge again.
- **Where it shows.** In that control only four faces mix, and mean pieces per face grows linearly, from 1.00 to 2.85
  by `k = 23`. Any partial cross-face row, from trench-side clipping or a non-union mesh change, has the same effect.
- **What bounds it** (ruling of 4 October 2026):
  - trench consumption;
  - the existing work and memory budgets, which refuse by name. No new limit number is set.
  - I04b controls measure and report pieces per face at every interval.
- **Consequence.** A mixed face is refused by lateral conduction. P1 admits it only as an `fv-cell-mean` column of
  bitwise-equal layer structure (§7). The lasting fix is the main open owner decision: Lagrangian material-point
  histories, I03 sub-face geometry or conforming faces.

**Regional returns and splits** (splits-2).
- A split changes the interval's forcing identity: `history_splits` is kept in the bridges' `_forcing_id`, with no new
  identity semantics.
- A regional return extracted for the split-free motion is therefore refused as stale. A split motion needs a
  re-extracted return.
- A cohort that the return carries is still never split in the same interval.
- A test runs a real return through `T.advance`. Another offers a return extracted for the split-free motion with a
  split motion, and it refuses as stale geometry (N4).

## 5. Transport (I05.1)

`advance_moving(parent, sphere, step, advance)`:
1. checks that the moving state belongs to `sphere`, and that the step continues it over the advance's interval;
2. divides each sublayer's heat over the motion rows and mesh rows, exactly as I03 divides its accounts;
3. books births and consumption;
4. relabels split pieces;
5. requires the result to cover the endpoint's pieces exactly;
6. rounds each changed value once;
7. conducts heat, if declared, then commits increments.

- **Moved network.** With a mesh change, the moved network's face list is rebuilt by I03's own functions and must
  reproduce the map's moved geometry identity.
- **Regional returns** carry no rows, so per-piece content cannot follow them. They refuse `unsupported`; this is an
  I07 requirement.

**Checks** (`test_i05_transport.py`):
- rigid and stationary cases change nothing;
- a heated plate between a ridge and a trench keeps its riding bytes, born pieces take their column's exact heat, and
  the accounts close exactly;
- bonded and broken cohorts merged into one face stay two pieces with their own records;
- `ever_broken` survives a remap and cannot be cleared;
- compaction memory and the original profile survive two intervals;
- raw history is untouched by transport, a uniform increment commits once, and divergent increments refuse;
- the two-pass split commits one increment per sub-cohort;
- **pass 2 is pass 1 apart from the relabel** (splits-5): every step array but the cohort records, the piece cohorts
  and the lineage is byte-identical, the births are equal, and each piece is pass 1's piece under its split name.
  (The first build also claimed equal stock transfers; that comparison was vacuous on this fixture, so the claim is
  dropped, N5);
- refusals;
- identical replay gives the same identity, and an edited or stale replay refuses;
- **restore is exact and exclusive.** The stored `moving.*` arrays must be exactly the rebuilt ones, byte for byte,
  with no other `moving.*` array, as I03's exclusive root restore requires. A trailing value, an edited offset or an
  extra array refuses `stale identity`; it is never sliced away;
- **declarations:**
  - a `MovingAdvance` keeps its record and identity after the caller edits its certificate object;
  - a certificate holding a `Fraction`, NaN or infinity refuses `missing record`, naming the certificate;
  - malformed increment pairs refuse `missing record`;
  - minus-zero increments are zero;
  - an unused birth column refuses.

## 6. Heat (I05.2)

**`integration_thermal.conducted`** implements R-1 to R-3 (§2).

**Occupied-material means:**
- `occupied_mean` and `face_mean` average over occupied pieces only, each at its own state, so the result is the
  age-distribution integral.
- A face with no such piece gives None, never 0 K.
- `face_mean` checks that the moving state is the one of the given I03 state (`stale identity` otherwise) and that
  the face exists (`missing record` otherwise). A face with no occupied piece still gives None.
- Values and areas must be finite real numbers, and areas nonnegative. Anything else refuses; nothing is dropped
  silently.
- **Which pieces count is the caller's.** "Occupied" (for example oceanic) is the caller's predicate over the cohort
  records: `CohortRecord` carries no oceanic class. A permissive predicate gives a mixed mean, and the result is only
  as oceanic as the predicate (review heat-9).
- `mean_age_cooling` refuses. The refusal is declarative, since no production path offers mean-age cooling. The real
  guard is that each piece is averaged at its own state; a test with unequal areas checks it (heat-8, heat-10).

**Checks** (`test_i05_heat.py`):
- **Translating enthalpy:** exact, about two axes; the field is independent of `T_ref`.
- **Stationary columns** stay unchanged to I03's relative tolerance, and the accounts close.
- **Series-resistance conductance** and exact lateral exchange.
- **Convergence** of the split scheme to the coupled solution.
- **Heterogeneous capacity:** heat exchanged between cohorts of different constant `cp`, with closure.
- **The two-age occupied-ocean mixture.**
  - W03's half-space branch (`Fo ≤ 1/576`) gives `Q = 2kΔT√(t/πκ)`.
  - Ages {0, t} with equal areas give `Q(t)/2` to `1e-12`.
  - That is `1/√2` of the value at the mean age.
  - On unequal areas `a1`, `a2` they give `a2 Q(t)/(a1 + a2)`. `face_mean` over a two-piece face of unequal areas
    equals an independent area-weighted sum.
- **The occupied-ocean face mean**, and its state, face and input checks.
- **Refusals:** non-orthogonal nodes, a missing node, a mixed face, omission on moving geometry, a failing or
  mis-sized certificate, deformed faces.
- **Repairs of 4 October 2026** (§2 R-2, R-3): the maximum principle at a ratio of 0.89; a shared boundary of two
  edges; a certificate on the state's own network; the carried bound; nodes outside their faces or for unknown faces.

## 7. Properties (I05.3)

**P1** (`moving_columns`). This is the I04/I05 port record's P1 on the trace support.
- **Header.** It names this state, its network, frame and datum, with `endpoint_s = interval[2] =` the state's own
  time and `interval[0] =` its step.
  - An endpoint or interval other than the state's own refuses `unsupported`, with I04's evaluation label.
  - Another parent state, network, frame, parameter or datum refuses `stale identity`, with that field as detail.
- **Provenance.** P1 and P2 are issued with `parameter_id` the `moving_id` they are computed from. A header naming
  another moving state refuses `stale identity` (detail `parameter_id`), so columns from two moving states cannot pass
  as one.
- **Family datum** (review basal-04). If any cohort comes from a starting family (its I03 origin is the family
  schema's), P1 and P2 apply I04a's v1 family gate: `ρ_m` and `T_ref` must be exactly 3300 kg/m³ and 293.15 K, or
  they refuse `stale identity` (detail `datum_id`). A test refuses each field alone: a datum differing only in `ρ_m`,
  and datums differing only in `T_ref` (273.15 K, and 293.15 K plus one ulp) (RB-3).
- **Face.** The face beside each trace point must hold one cohort piece, or several admitted by the `fv-cell-mean`
  amendment below. Otherwise it refuses `unresolved column` (D-P2).
- **Layers**, bottom to top: current thickness; the cohort's fixed `ρ_ref` and `α`; the sublayer's finite-volume mean
  temperature as both boundary temperatures. This is the piecewise-constant case of the `I01_GPE` representation.
- **Mixed faces: `fv-cell-mean`** (amendment of 4 October 2026, recorded in `I04_I05_PORTS.md`).
  - **When admitted.** A face holding several pieces is admitted only when every piece has bitwise-equal layer
    structure: the same material, phase, `ρ_ref`, `α` and `cp` per sublayer, and identical tuples of sublayer
    thicknesses and depths, not equal within a tolerance. The thickness tuple is compared as well as the depths
    (round 2), so no rounding of the cumulative sum can hide a thickness difference.
  - **The column.** Per sublayer, its temperature is the caloric inverse of the exact mean specific enthalpy
    `ΣH_i / Σ(ρ t A)_i`, formed in rationals from the stored heat and rounded once. This is the enthalpy-consistent
    first-order finite-volume cell average, and it conserves heat. Pieces of equal temperature therefore give exactly
    their own column, by the monotonicity of rounding.
  - **The record.** The representation flag and the sorted contributing cohort set are carried per point
    (`Columns.representation`) and bound into `port_id`. A P1 without mixed faces keeps its old record and identity.
    A representation of all None is normalised to None, so one value has one identity (P1-NOTE-3).
  - **I04b's obligation.** The flag says which points are cell means; recording which trace indices a downstream
    consumer used from them is I04b's obligation, not P1's.
  - **What it does not touch.** Histories and kappa stay per piece (P2, P6), so no history is averaged. This
    supersedes "columns are never averaged" (I05-10) for this case only.
  - **Refusals.** A different layer structure still refuses `unresolved column`.
  - **Controls** (predeclared, tested):
    - identical pieces give the single-piece column bit for bit;
    - a two-piece face gives the exact enthalpy mean. This pins the mean only to rounding: under bitwise-equal
      structure `ΣH/Σ(ρ t A)` equals the area-weighted temperature mean in real arithmetic, so on this fixture a
      float or area-weighted mean rounds to the same bits. The exact formation is the code's; the control does not
      separate it (review P1-NOTE-2);
    - a layer-structure mismatch refuses, including pieces whose depths are bitwise equal but whose thicknesses
      differ by one ulp in a sublayer;
    - each piece of a mixed face is still guarded (below).
- **Inventory guard.** `Σ ρ_ref t A` per phase must equal the piece's I03 mass within
  `(3.5 + (k + 1)) ε` relative, with `k` the steps since the moving state was declared (`step − declared_step`).
  `declared_step` is in the record and in the moving identity, so `k` is the same after a reopen. Beyond the bound,
  P1 and P2 refuse `incompatible support` (detail `reference mass`).
  - **This is a re-derivation** of the approved `4(n+2) ε` guard, which miscounted the roundings (review basal-05,
    coordinator ruling (B) of 4 October 2026). It is not a change made after results.
  - **The I05 side is 3.5 ε, independent of n.** Each row rounds `V/A`, `/H` (`H` itself an `fsum`, one rounding),
    `× h0`, `× ρ` and `× A`, and the final `fsum` rounds once: 7 roundings of at most ε/2.
  - **The I03 side is (k + 1) ε.** I03 rounds a piece's mass `M` and volume `V` each once per interval, at most ε/2
    each, so `M/V` gains at most ε per interval. Over `k` intervals and the declaration's own rounding, the worst case
    adds linearly.
  - **Measured.** A 20-interval run of plate A turning 0.25° between a ridge and a trench drifted at most 1.924 ε,
    against a bound of 24.5 ε; it is a test. The review's own probe measured 5.33 ε after 175 intervals.
  - **Still tight.** Even at `k = 1000` the bound is about 2.3e-13, far below any density inconsistency the guard
    exists to catch.
  - **Tests** pin the formula at `k = 0` and `k = 10`, a perturbation just beyond the step-`k` bound (refused), one
    within it (passing), and the identity binding of `declared_step`.
  - **The wiring of `k`** (P1-SHOULD-1). One state at step 20 is issued twice, as declared at step 20 (`k = 0`) and
    at step 0 (`k = 20`), with densities 12 ε high: between `inventory_bound(0)` and `inventory_bound(20)`. P1 and P2
    refuse the first and issue the second, so `k` is the steps since declaration, not the absolute step.
  - **Declaration and birth use the same guard** (RB-2, below). A test declares records over a range of density
    offsets: each admitted one passes P1 and P2 at once, and each refused one names `reference mass`. Births over a
    range of offsets are admitted only where P2 then issues at the endpoint, and each check fires on its own: a birth
    column 4 ε dense passes the supply check and is refused by P1's guard on the born piece, while 6 ε and 12 ε (both
    within the old `4(n+2) ε = 24 ε`) are refused by the supply check itself.
  - **Per piece on a mixed face** (P1-NOTE-2). On an `fv-cell-mean` face, a second piece whose density is 30 ε high
    (issued without the declaration's checks) still refuses the face's column.

**P2** (`strength_port`). The amendment of 4 October 2026 to the port record.
- **Support:** the piece support `atlas.i05-piece-support.v1`.
- **Per piece and sublayer, bottom to top:**
  - thickness and temperature;
  - the lithostatic vertical stress at the bottom and top of the sublayer. It is integrated from zero at the column's
    top with `ρ_ref(1 − α(T − T_ref,datum))` and the datum's gravity; it is not a mean pressure;
  - the declared pore pressure;
  - material and creep law;
  - raw `kappa` on the same material-point support P6 uses.
- **Healing:** only `atlas.i04-healing-none.v1` is admitted.
- **Inventory guard.** Each column must pass P1's guard, because P2 uses the same representation. The first build
  issued stresses from columns P1 refused; the verification found that, and it is now refused and tested.

**Declaration ties the record to the I03 mass** (review basal-02).
- `declare_moving` checks every declared piece with P1's own row arithmetic (`ρ_ref (h0 · ratio) A`, then `fsum`)
  and P1's bound at `k = 0`, `inventory_bound(0) = 4.5 ε`: per phase, `Σ ρ_ref t A` must equal the piece's I03 mass
  within it, else `incompatible support` (detail `reference mass`). A record whose density contradicts the I03
  material therefore refuses at declaration, not intervals later at P1.
- **Same guard, same bound** (RB-2 and P1-SHOULD-2, 4 October 2026). The first build checked declaration within
  `4(n+2) ε`, which is wider than P1's guard at `k = 0`, so a declared record could pass declaration and be refused by
  P1 at once. Declaration now uses P1's guard at `k = 0`, so every declared record passes P1 at its declared step. A
  born piece is checked by the same guard at its birth step (`k = step − declared_step`), and `_check_birth`'s mass
  tolerance is `inventory_bound(0)`. This narrows a tolerance; it relaxes nothing.
- The guard is still tested, through a state issued without the declaration's checks, as a restored or drifted state
  would be.
- **Deviation from the approved I05-3 schema, recorded for the coordinator.** That schema cross-checked I03 enthalpy
  against I05 heat "exactly, same basis". The code instead requires an I03 material with no enthalpy basis
  (`incompatible support` otherwise), so I05 is the single owner of heat. This mass check is the tie that remains
  between the I05 record and the I03 material.

**P3** (`carried_core`) is the declared core, carried unchanged.
- **Declaration checks.** It first passes the `I01_ELASTIC_CORE.md` §6 declaration checks in that section's order,
  as a package reproduction of the tool's `elastic_core`:
  - placement absent;
  - several cores, layers or array-valued fields;
  - wrong fields, non-finite, boolean or text numbers, `a ≥ b`, `E ≤ 0`, `ν` outside (−1, ½), empty texts, another
    depth reference, an unrepresentable `D` or `c`;
  - `a < 0`.
  A parity test compares the codes with the tool's over the verification's cases.
- **Rock check.** Its base must then lie within the rock of every P1 column, else `REFUSED_CORE_OUTSIDE_ROCK`.
- `Te`, `D` and `c` are never accepted, and nothing is derived.

**Direction controls** (predeclared, ruling I05-10). Heating a cohort by +ΔT:
- keeps reference mass bitwise;
- lowers the effective load;
- raises the surface;
- raises a single uniformly heated layer's anomaly when `r > r_m/2`;
- raises the P2 temperature by ΔT and lowers the vertical stress below it.

P1 from a moving state feeds I04's `trace_anomaly` unchanged.

## 8. Basal exchange (I05.3, MC-04)

**Package reproductions** of the I01 basal tool, with bitwise parity tests that import the tool from tests only (R-5):
- `strip_open_base`, `thermal_condition`, `volume_account`, `propose_interval` and `diagnose_endpoint`;
- the same codes, check order and floating-point expression order;
- the closed strip stays the default and untouched;
- volume, inventory and caloric accounts stay at the existing `1e-12`;
- exhaustion is exact and joint, never clipped.

**`strip_transfers(proposal, *, account, ledger, parent, end_step, …)`** converts a proposal's per-metre amounts to
whole-stock I02 `Transfer`s:
- **The account.** The proposal must be exactly the one `propose_interval(account)` gives for the declared account,
  as `diagnose_endpoint` recomputes it. An edited proposal refuses as foreign, whether the change is to the moved
  components, the energy, the mass or the checked remainder. What is checked is what moves. The first build checked
  `remaining_mass_kg` but moved `components_kg`, so an edited proposal could move twice the declared mass.
- **The I02 interval** (review basal-01). The proposal's `interval_s` must be exactly the I02 clock times of the
  parent commit's step and `end_step`, so its start and duration are bound to the interval it is committed over.
  Otherwise it refuses as foreign.
- **Once per strip** (RB-1, 4 October 2026). The labels are
  `basal/<strip identity>/<start>-<end>/in|out/<row name>`.
  - The strip identity is `strip_identity(account)`: the first 24 hex digits of the sha256 of the declared account's
    canonical JSON without `interval_s`. The row name is the proposal's own name for a source or a receiver
    row, not the exterior it is mapped to.
  - Nothing in a label is the caller's choice, so a second conversion of the same strip in one interval carries the
    same labels under another domain node or another exterior, and I02 refuses it as applied twice. The first build
    keyed the labels on the caller's node and exterior names, so a renamed second conversion was booked again.
- **The interval label** (RB-5). The binding is to the declared I02 interval label (`<start>-<end>`, the parent
  commit's step and `end_step`). The caller integrates the amounts over that interval: I01 accounts carry integrals,
  not rates, so nothing here checks a duration beyond the `interval_s` equality above.
- **What stays the caller's.** I02 records no declared initial stock for an exterior, so a finite exterior source
  drawn across intervals is bounded only by the caller's per-interval accounts. This is a recorded limitation, not
  built.
- **Scaling.** Amounts are multiplied by the declared IN-06 attached-window length `L_s`, which is required, with its
  provenance. This is dimensional analysis, not a new number. A missing argument is a `TypeError`, and a
  non-positive or non-real `L_s` refuses `REFUSED_INVALID_INPUT`.
- **Direction.** Inflow runs from a declared exterior source to the strip's stock node, and outflow from the node to a
  declared exterior sink. A mapping for a row the proposal does not hold refuses; it is never ignored.
- **Components** (ruling (a), 4 October 2026).
  - A row's components must be among the stocks'; nothing is relabelled.
  - A stock component that the row lacks is filled with an explicit 0.0 kg only when it is structurally absent: no
    material feeding that row declares it. That is the source's own material, or the materials of the cohorts whose
    outflow a receiver collects.
  - The zero is bound into the transfer record, and the producer names the zero-filled components.
  - A component that a feeding material declares is never filled.
  - The caloric basis must equal the stocks'.
- **No dead check.** The former overdrawn-source check is gone: the recomputed proposal already refuses exhaustion
  exactly.

**Surface.** Only the stationary surface (the strip's closed form) is represented. A moving surface needs its own
supplied, labelled swept volume (I08).

## 9. The lateral-heat certificate (MC-06 reproduction)

`LateralNetwork` and `lateral_admission` reproduce the exact `Fraction` admission of
`tools/check_i01_lateral_heat.py`:
- the same assumptions and policy;
- `REFUSED_UNCERTIFIED_ENVELOPE` for sample-only or unknown envelopes;
- the initial error bound carried across windows.

The parity tests compare results with the tool.

## 10. Persistence through I02 (ruling I05-1, option a)

**Attaching.** `Ledger.create(store, root, sphere=state, moving=moving)` attaches a declared moving state beside its
network:
- it is bound into the ledger identity;
- the root stores its record and arrays.

**Each commit** carries exactly one `MovingAdvance` for its interval: birth columns, conduction and increments, with
its own `advance_id`.
- A commit without one refuses as an exchange refusal, so nothing of the interval is committed.
- A `MovingAdvance` offered to a history with no moving state refuses with that reason, before any I03 step is
  computed.
- The advance's content, including its certificate, is captured at construction. A later edit of the caller's
  objects cannot store content under a stale `advance_id`. The first build kept the certificate by reference, so such
  a commit passed in its writer and never restored in a fresh process.
- The successor's moving step (`atlas.i05-moving-step.v1`) is stored with the column and network steps in one
  transaction.

**Restore is by replay.**
1. The parent's stored moving state is rebuilt through its constructors. Its stored arrays must be exactly the
   rebuilt ones, with no other `moving.*` array; this applies at the root too.
2. The commit's I03 step is rebuilt and verified.
3. The stored advance must reproduce its identity.
4. The transaction runs again; the stored record and every `moving.*` array must equal the recomputed ones.

**Unchanged histories.** A ledger without a moving state is byte for byte what it was. It imports no I03 or I05 module
for the moving checks (review ledger-6): no `MovingAdvance` can exist unless `integration_material` is loaded, so the
checks look it up in `sys.modules`.

**Named refusals** (reviews ledger-1 and ledger-8).
- A root that declares a moving state without its network refuses as foreign.
- A malformed stored moving record refuses as a `LedgerError`, never a raw Python error.
- An unknown moving step schema is refused by name, as an unknown spherical step schema is.

**Edits to I02 files** (minimal, listed with reasons in the handoff):
- `integration_ledger.py`:
  - the attachment's hooks;
  - the `MovingAdvance` checks on the shared paths (`_proposal`, `_declared_content`, the commit pre-check), which
    every ledger runs, guarded by the `sys.modules` lookup;
  - the moving content of `_network_content`, read only when a commit carries one;
- `integration_clock.py`: one expression, so an interrupted clock commit names a `MovingAdvance`;
- `integration_state.py` is unchanged. The I05 quantities are not added to the catalogue, because that would change
  `CATALOGUE_ID` and every stored state; that is a migration decision.

**Checks** (`test_i05_ledger.py`):
- the root and a plain ledger, and an advance offered to the plain ledger;
- a commit carries its moving step, and a missing advance commits nothing;
- identical replay is a no-op, and a changed one is a stale parent;
- an edited moving array refuses on replay;
- **store rewrites** (as `test_i03_ledger` rewrites a root), through a freshly opened ledger:
  - an edited head record or head array refuses through `verify_chain` and `moving`;
  - an unknown moving step schema refuses by name;
  - a successor without its moving record refuses through `chain`;
  - an edited or extra root array, or a malformed root record, refuses on `open`;
  - a foreign root without its network refuses;
- **save, reopen and continue**, with and without finite stocks. The moving control is saved after three intervals and
  continued for three more by a fresh process. Parity (ledger-5) is judged on:
  - the head record's sha256;
  - the column, network and moving identities;
  - the exchange identity;
  - the exact closure.
  Ledger keys are positional, so they are not evidence of parity. In the stocked variant (ledger-4), an ordinary I02
  `Transfer` is committed beside each `Motion` and `MovingAdvance`. The control:
  - conducts at intervals 0 to 3 on the undeformed mesh: omission at 0, 2 and 3, with the carried bound chaining
    across the save, and a solve at 1;
  - turns plate A at interval 4, with births, consumption and a split;
  - merges two faces at interval 5.
  Intervals 4 and 5 are advection only, so no omission follows them;
- **a ledger without a moving state imports no I03 or I05 module** on its first commit (a fresh process).
- **Not changed** (notes ledger-7 and ledger-9): `verify_chain` replays each commit's I03 step twice on a moving
  ledger, once for the network and once for the moving state, and `describe()` does not report the moving state.

## 11. Results

These were executed in the scratch candidate on Windows/CPython 3.12.14, 4 October 2026. They are candidate results,
not acceptance. The focused counts:

| Module | Tests |
| --- | --- |
| `test_i05_transport` | 17 |
| `test_i05_heat` | 24 |
| `test_i05_properties` | 23 |
| `test_i05_basal` | 13 |
| `test_i05_ledger` | 13 |
| `test_i03_history_split` | 10 |

All passed. Every test of the I01–I05 regression set also passed, the 2 historical I03 expected failures apart. The
evidence register is affected only as ruled: two receipts go historical, with successors to capture after
acceptance.

## 12. Limits and what remains

- **Lateral contacts on generic meshes refuse** (R-2). Declared nodes or conforming faces are the lasting route.
- **Omission is small-state only.** It is bounded by MC-06's own policy of 256 cells and 1024 contacts. It needs the
  same admitted contacts as a solve, since its conductances are derived. Its envelopes are declared and checked
  against the state's own samples (§2 R-3).
- **History growth under relative motion** is quadratic in pieces per face, bounded only by trench consumption and the
  existing budgets (§4). The lasting fix (material points, sub-face geometry or conforming faces) is the main open
  owner decision.
- **A finite exterior source across intervals** is bounded only by the caller's per-interval accounts (§8).
- **Regional returns** carry no rows, so per-piece I05 content cannot follow them. This is an I07 requirement.
- **No cp(T) law** is admitted. The caloric structure is ready for one.
- **Lie splitting is first order in time.** Coupled time refinement belongs to I05.5 and I04.4, with a criterion
  predeclared on that basis.
- **The prism convention** omits the wedge factor, about `z/R` in capacity and thickness (§2 R-2).
- **The drained law** is not applied on moving columns; its memory is carried.
- **The belt record (R-6)** is deferred to I05b/I07 (ruling (d)). P4 refuses `unsupported`, and I04.3 must not depend on
  it.
- **Stock-linked I03 materials** carry an enthalpy basis, so they cannot attach I05 heat in v1.
- **P2 consumers** are I04 Part B's. The pressure closure that consumes `σ_v` is theirs.
- **I05.4** (phase and supply) and **I05.5** (production joins, refinement, resumed parity on a production case) are
  not started.

## 13. Sources

- **Inherited** (read locally, not newly read):
  - `I01_PHYSICAL_CONTRACT.md` §§5, 6, 9;
  - `I01_CLOSURE_MATRIX.md` (CM-02, CM-05 to CM-08, MC-01, MC-04, MC-06, IN-02/04/05/06);
  - `I01_LATERAL_HEAT.md`, `I01_BASAL_CLOSURE.md`, `I01_SEPARATION_FEASIBILITY.md`, `I01_ELASTIC_MEMORY.md`,
    `I01_BREAKUP_CLOSURE.md` and `I01_WEAKENING.md`;
  - `W03_THERMAL_COLUMNS.md`, `W03_COMPACTION.md`, `W06_COOLING.md` and `W07_HETEROGENEOUS_THERMAL.md`;
  - `I03_SPHERICAL_NETWORK.md` and `I04_I05_PORTS.md`;
  - Droniou (2014) and Fazio–LeVeque, as cited by `I01_LATERAL_HEAT.md`.
- **Newly consulted:** the FiPy official documentation (§2 R-1).
