# I03: one shared spherical network, moved, bridged and changed by supplied events

**WORKING NON-CANON. Method updated 3 October 2026.** I03.1–I03.4 include
the reviewed shared network, material transport, regional bridges and supplied
events. The repair/extension pass adds strict forcing/support binding, corrected
junction planes and transfer allowances, exact difficult-sweep intersections,
declared-vertex traversal, supplied curved junction paths and transient material
accounting. [Current state](../../docs/CURRENT_STATE.md) records the verification
and integration outcome, rather than this method page implying a separate gate.

The projection criteria (R3-5), equivalence bound (E1–E3, E2 corrected) and
conditional event re-expression allowance (D7″) were approved on 3 October.
The sweep comparison bound is derived separately below; the trench audit retains
the original `1e-12 * swept_area` rule.

This document describes
[I03 in the integration plan](INTEGRATION_PLAN.md#i03--evolving-sphere-conservative-history-and-spatial-bridges):
- a closed spherical network carried beside the I02 accepted state (I03.1);
- its motion under supplied finite rotations, with conservative transfer of its material (I03.2);
- the bridges that hand part of it to a regional model and take the result back (I03.3);
- supplied plate splits, merges and ridge jumps, committed with the interval they end (I03.4).

[Current state](../../docs/CURRENT_STATE.md) owns delivery status; this document explains the method and what its
checks establish.

Everything here runs in `prescribed_history_v1`: rotations, ridge and trench rules,
sources, destinations and mesh changes are supplied. Nothing chooses a motion, a
boundary or an event. Producing motion is I04, the content of material histories is
I05, and physical event generation is I06/I07/I09.

## 1. What this adds, in execution order

1. **Declare the network** ([`integration_sphere.py`](../src/atlas_tectonics/integration_sphere.py)).
   A closed partition of the sphere at one accepted time: sampling faces, each owned
   by one plate; one record per boundary between two plates; the junctions where
   records end; one total finite rotation per plate; each boundary's origin and the
   lineage of retired identities. Its geometry is a W01 closed atlas
   ([`spherical_atlas.py`](../src/atlas_tectonics/spherical_atlas.py)), validated by
   the atlas's own checks.
2. **Declare its material.** Pieces, one per (face, cohort), with separate accounts
   for occupied area, reference mass and volume per declared phase, and signed
   enthalpy in a declared basis. Exact accounts record the declared totals.
3. **Attach it to an I02 history** ([`integration_ledger.py`](../src/atlas_tectonics/integration_ledger.py)).
   `Ledger.create(..., sphere=state)` stores the network in the root commit beside the
   column state and binds its identity into the ledger identity.
4. **Move it over one accepted interval** ([`integration_transfer.py`](../src/atlas_tectonics/integration_transfer.py)).
   `advance(state, Motion(...), end_time_s=...)` moves faces with their plates, moves
   each boundary by its declared rule, creates new faces at opening ridges, consumes
   at trenches, measures the overlap rows and transfers the accounts exactly.
5. **Commit, restore and continue through I02.** A `Motion` given to
   `Ledger.commit` or `Clock.advance` among the interval's transfers is applied to
   the parent commit's network and stored with the column steps in one transaction.
   Reopening recomputes the moved geometry and re-applies the stored rows.
6. **Hand a region to a regional model and take it back**
   ([`integration_bridges.py`](../src/atlas_tectonics/integration_bridges.py)).
   `extract(state, Footprint(...), motion, duration_s)` reads a declared set of whole
   faces in an exact local frame. `returned(state, [(extract, result)])` puts the
   regional result back on the same faces, conserving every account exactly
   (section 8).
7. **Commit supplied topology events**
   ([`integration_events.py`](../src/atlas_tectonics/integration_events.py)). A
   `Motion` may carry the splits, merges and ridge jumps that end its interval. They
   are applied to its endpoint and committed with its steps through I02, or not at
   all (section 9).

Section 2 records the research decisions and sections 3–6 give the method. Section 7
is the transport port that I05 builds on, section 8 the regional bridges and their
port for I07, I08 and I09, and section 9 the joint event commits. Sections 10–12 give
the checks, measured costs and limits.

## 2. Research decisions

The integration brief asked for seven decisions, each resolved only as far as coding
needs. "Newly consulted" means read for this work; "inherited" means an existing
Atlas contract or method was applied without re-reading its sources.

### R3-1. Conservative transfer: exact intersection, first order

**Decision.** Transfers use the common refinement of the parent and endpoint faces,
restricted to the faces that actually changed. For a parent face `i` (moved rigidly
with its plate to the endpoint time) and an endpoint face `j`, the row area is

```text
A_ij = area_on_sphere( S_i ∩ T_j )          [m2]
```

and an extensive amount `Q_i` held by `S_i` moves by

```text
Q_ij = Q_i * A_ij / sum_j A_ij ,   sum_j Q_ij = Q_i exactly.
```

A face must be covered by its rows: `|sum_j A_ij - A_i| <= 1e-12 A_i`, and every
endpoint face must be filled likewise. This is the constant-preservation condition
of the supermesh formulation (Kritsikis et al., Eq. 3, `A_i = sum A_k`), checked
rather than enforced. The transfer is first order: an amount is taken as uniform
over its face. No gradient is reconstructed, because the carried quantities are
extensive accounts of history-bearing pieces, not smooth fields (R3-3).

**Measures.** Areas are measured on the sphere, never in a projection. The two
polygons are projected into one gnomonic chart, where every minor great-circle arc
is a straight segment, so their intersection is an intersection of planar polygons
(shapely/GEOS, already a W01 dependency). Each resulting ring is mapped back to unit
directions and its area is the sum of signed spherical triangles from an anchor,
`2 atan2(a·(b×c), 1 + a·b + b·c + c·a)` per triangle, added with exactly rounded
summation (the W01 measure, `spherical_geometry._ring_area`). Accounts therefore use
the same support measure as the atlas that validates coverage. The anchor is the
ring's own mean direction, so every triangle is about as small as the ring and a
small overlap is measured at its own scale. An anchor at the chart's centre would
add and subtract triangles far larger than a small overlap far from that centre. A
face's own area is measured the same way, in its plate's reference frame (section 4),
from the mean direction of its outer ring. Before I03a-2 the anchor of a face was its
ring's first vertex. A ring's first vertex changes when a strip's corners are renamed
to frozen copies, so a face that only rode could change its measured area with
unchanged coordinates. The mean is an exactly rounded sum and does not depend on where
the ring starts.

**Whole faces.** Where a changed face lies wholly within a replacement face of a mesh
change, or a replacement lies wholly within a changed face, the row is the inner
face's own measured area and nothing is clipped. Containment is decided exactly. Every
predicate is the sign of an integer expression in the binary64 inputs: orientation,
position along an arc, and Sunday's winding number in the central projection, where
every minor arc is a straight segment. So it is never subject to rounding. A bounding
cap widened by the 64 ε band decides only whether the exact test is tried, never what
is accepted. A renamed face, a thin strip merged into a compact neighbour, and the
split back therefore close within the rounding of the compact face's own measure
(about 3e-16 of it in the controls), whatever the strip's width, and the accounts stay
exact. A merge of two thin faces still carries the evaluation error of the merged face's
own measure (section 12).

**Weights.** The denominator is the sum of the face's own rows, not its separately
measured area, so that a donor is debited exactly once. The two differ by at most
the audited closure (relative 1e-12); beyond it the step is refused. Nothing is
normalised after the transfer. In ESMF's terms this is the conservative weight
`w_ij = f_ij A_si / A_dj` applied to amounts rather than to mean values, with full
coverage required; partial coverage, which ESMF handles by destination or fraction
normalisation, is refused here because a closed network has none.

**Search.** Only changed faces are intersected (the boundary cells of a subducting
plate, or the faces replaced by a mesh change), within one plate, after a
bounding-cap rejection test. The tree search of Kritsikis et al. (their section 3.2)
is not implemented; see section 12.

**Validity.** Two faces that overlap must fit one conditioned chart (cosine of the
angle to the chart centre at least 1e-3). Two faces that fit none need no chart when
a great circle through an edge of one has that face on one side and every vertex of
the other beyond it by more than the 64 ε band: they cannot overlap, and no row is
made. Any other pair without a chart is refused.

**Resolution.** A face's area is defined by its binary64 vertices only to about
`δ P`, where `P` is its perimeter in radians and `δ` is the rounding of one unit
direction, about 1.1e-16 rad. Its rows are therefore certain to close on its area to
relative 1e-12 only while

```text
A / P >= 1.1e-16 / 1e-12 = 1.1e-4 rad      (about 700 m on a sphere of radius 6371 km)
```

with `A` in steradians. A thinner face often still closes. When it does not, or
when rows that each close deliver pieces that miss an endpoint face by more than
the tolerance, the step is refused as an unresolved overlap. Nothing is accepted
beyond the tolerance.

**Thin faces (C7 and D7, approved 3 October 2026 with conditions).** A closure made only of whole-face rows
compares measured faces with measured faces. It may close within the largest rounding of those measurements, where
that exceeds the relative tolerance:
`|Σ μ(pieces) - μ(F)| ≤ max(1e-12 μ(F), E)`, with `E = e(F) + Σ e(inner face)` and
`e = 9 ε Σ_j |v_j - c| |v_j+1 - c| + max(14 ε, 4.4 ε + 5 α) Σ_j |T_j|` over every ring of the face. Here `c` is the
anchor of the measure (M4), `α` is the largest departure of a vertex's or the anchor's norm from one, and `T_j` are
the fan's triangles: each triangle's relative error scales with its own area, so a hole adds to the rounding although
it subtracts from the area. (The first version used the face's net area there; the C7 verifier found a square
annulus 44° across, with rows 16 ε longer and shorter than unit, measured 1.19 times that bound from its true area.)
`e` is derived term by term from the fan's operations: the cross product's error by the permanent bound, `atan2`'s
derivative at most `2/D` with `D ≥ 1 + √2` when every vertex is within 45° of `c`, and `atan2` correct to one unit in
the last place. **That last item is a platform assumption.** It is tested against an exact arctangent on 20,000
samples over the fan's range. The bound is tested against a 90-digit evaluation of the same binary64 numbers for
strips 55 m, 5.5 m and 0.55 m wide and 3,200 km long, and for compact faces; and against the true area of the
exactly normalised directions for annuli and rings with holes whose rows lie up to 16 ε off unit length, the most the
stored-direction contract keeps. A measured error above its bound would fail the test; the bound is never adjusted. `E` is recomputed from the faces' rings in the same way when a step is
measured and when it is restored; no bound is stored with a row.

**The occupancy allowance (D7′).** A face whose pieces were set by whole-face rows keeps a stored allowance `A`, and
the every-interval check compares its pieces with its area within `max(1e-12 μ, A)`. The first version (D7) added each
step's bounds to the allowances before it. The coordinator withdrew that on 3 October 2026, after round-1 verifiers
showed that it grew with every rename although the discrepancy stayed zero: about 10% of a face at 0.27 µm strips, 20.6
times `1e-12 μ` after a long ride and a full remesh, and 2 × `1e-12 μ` per rename above the range. Rows that left out a
sliver at every step were then accepted for 16 steps. D7′ is derived in the bounds proposal's addendum. For pieces moved
by whole-face rows, exactly, `d(X) = c′_X + Σ_r w_r (c_s + d(s))`. Here `d` is pieces minus measured area, `c′` and
`c` are the receiver's and donors' measured closures, and `w` the donors' shares. The part one step introduces is
bounded by that step's own measures, `E_step = E_X + Σ_s w_s E_s`. The part inherited from earlier steps telescopes
back to the measures the pieces were born with, so the current measures do not bound it, and it is not carried. So:

- a rename (one row from a donor with only that row, equal to both measured areas bit for bit) leaves `d` unchanged,
  and the face keeps its donor's allowance;
- any other face that receives mesh rows gets `min(E_step, ceiling)`, never added to an earlier allowance. The ceiling
  is unlimited below 1.1e-4 rad of area over perimeter, `2 × 1e-12 μ` up to 2.2e-4 rad, and zero above;
- a face that only rides keeps its allowance, and a face given pieces by clipped rows gets none.

This fails closed. An honest thin face that went through several whole-face steps carries an inherited `d` that its
allowance does not cover, and can be refused. Rows that leave out a sliver at every step are now refused at the
eighth step, with 0.69 of one step's bound unbooked. Before, all 16 steps were accepted with 5.9 times the rounding
bound unbooked. The coordinator approved D7′ as written on 3 October 2026, after the cumulative D7 was withdrawn.

**An exception to D7′'s zero ceiling: D7″.** A face that a topology event re-expresses in another plate's frame, or
whose vertices change home, gets an allowance above the C7 range too (section 9). It is not a closure of rows. It is a
distinct rounding source: the same face is measured again from re-placed coordinates while its pieces stay put. D7′'s
ceiling bounds what rows can introduce, and says nothing about that. Rides, mesh steps and closures keep D7′ unchanged.

**How weak the per-face check is for thin strips.** This is a condition of the D7′ approval (3 October 2026). The
table gives `E_step/μ` for an end-to-end merge of two born strips, each with two vertices a side, into one strip of
the given width and length. It is computed with `_measure_bound` on the strips of `test_i03_thin_faces.strip`.
`E_step/μ` is the most that the occupancy check then lets that face's pieces differ from its area, relative to the
area. The existing check is 1e-12.

| Strip width | Length 3,200 km | Length 320 km |
| --- | --- | --- |
| 55 m | 2.3e-10 | 2.3e-11 |
| 5.5 m | 2.3e-9 | 2.3e-10 |
| 0.55 m | 2.3e-8 | 2.3e-9 |
| 1 cm | 1.3e-6 | 1.3e-7 |
| 1 mm | 1.3e-5 | 1.3e-6 |
| 0.27 µm | 4.7e-2 | 4.7e-3 |

The ratio grows as length over width, because `e` grows with the square of the length, not with the width. At these
widths the per-face occupancy check is weak: it cannot see an unbooked sliver smaller than the tabulated fraction of
the face. The global accounts stay exact in rational arithmetic, and the sphere's total closes within the atlas's
own 2e-11 sr. No width floor is imposed: it would be a new policy value without a derivation. The coordinator has
flagged a possible declared floor for the owner and Codex.

**The flagged range, stated plainly.** The proposal estimated that `E` stays below `1e-12 μ` while a face's area
over perimeter exceeds about 2.2e-4 rad. The C7 verifier measured otherwise: `E` grows with the number of vertices
and the square of their reach, so for strips with area over perimeter between 1.1e-4 and 2.2e-4 rad it was 5 to 94
times `1e-12 μ`, and it exceeded `1e-12 μ` up to about 7.6e-3 rad (strips 48 km wide with 60 vertices a side). `E`
is therefore used only in the range the approval states, judged by the closure's own face: in full where its area
over perimeter is below 1.1e-4 rad (R3-1's limit, where the existing criterion cannot be met), up to twice
`1e-12 μ` below 2.2e-4 rad (about 700 m to 1.4 km for a square), and not at all above that, where the existing
criterion alone applies. In the flagged range C7 can admit up to twice `1e-12 μ`: only what the rounding of that
measurement could produce, but looser than the existing tolerance. The coordinator approved C7 with this range
flagged, for Codex to confirm; the measured `E` is reported for that decision. Below 1.1e-4 rad, `E` does not shrink
with a strip's width, because it grows with the square of the strip's length. A thin–thin merge of strips 0.27 µm
wide closes under a bound of about 5% of the face, and the allowance it leaves is about 10% (round-1 verifier). A
width floor, or a refusal when `E` exceeds a declared fraction of the face, is a separate decision for the owner and
Codex. C7's slip term for a transform's far-side closures (`δn × L_slip`) is approved but not built: those closures
keep the relative criterion. M3 is now used selectively for trench-consumption overlaps that fail the original
swept-area-relative audit: exact integer predicates and homogeneous intersections avoid projection round trips,
and high-precision spherical triangle measures are rounded only at the result. Ordinary receiver and mesh overlaps
retain their existing fast path. If GEOS supplies only lines or points although its
union implies overlap greater than `1e-12` times the larger projected face area,
the original spherical operands go to the existing bounded exact intersector.
This replaces the former named refusal for that detected degeneracy; unresolved
exact operands still refuse. An empty overlap at or below the unchanged detection
threshold remains zero. Motion and mesh calls pass the caller's existing budget
through this fallback. A thin face cut by other ordinary paths can still be refused
(section 12).

**Independent checks.** The lune formula `A = 2 R^2 Δλ` for born and consumed areas;
the closed-sphere total `4πR^2`; the same history about a tilted axis; exact
rational closure of every account; merging and splitting faces; and a square 1.3 m
across inside a cell thousands of kilometres across, whose overlap with the cell
must equal its own area `4 atan(a² / sqrt(1 + 2a²))` within the existing W01
tolerance for small spherical areas (relative 1e-7).

**Sources.** Newly consulted: Kritsikis et al. (2017), sections 2–3 (supermesh,
Eqs. 2–3, exact arc intersections, search, cell areas); ESMF 8.3.0 reference,
sections 12.3–12.5 (conservative weights, great-circle cells, normalisation and
partly covered cells). Inherited: the W02 principle that overlap fractions multiply
extensive stocks (`remapping.py`, `planar_exchange.py`).

### R3-2. Poles and seams: no latitude or longitude in the calculation

**Decision.** Vertices are unit vectors, rotations are unit quaternions applied in
Cartesian coordinates, and edges are minor great-circle arcs. Every face has its own
gnomonic chart, centred on the exactly rounded mean of its vertices and used for
topology only. Each intersection uses one joint chart centred on the mean of the two
outer rings. Charts are derived from the current vertex positions whenever they are
needed, so they follow the geometry as it moves and are never part of the state.
A face that fits no open hemisphere and an antipodal edge are refused (W01).

**Validity.** Faces smaller than a hemisphere, conditioned as above. The frame's own
poles and antimeridian are not special.

**Independent check.** Every moving control is repeated about an axis tilted by
0.7 rad, so that no vertex lies on a frame pole and sectors cross the antimeridian;
areas and accounts agree with the untilted history to relative 1e-12.

**Sources.** Inherited: W01 `SphericalChart` and atlas validation
([foundations](FOUNDATIONS.md)).

### R3-3. Integrals move; histories are carried intact

**Decision.** Extensive quantities move by the overlap integrals of R3-1: occupied
area (m2), reference mass per phase (kg), phase volume per phase (m3), signed
enthalpy in its declared basis (J) and finite stocks. History is never averaged. A
cohort record holds a material identity, an origin, a formation interval
`[start, end]` in epoch seconds (or unknown at both ends) and an opaque history
reference owned by I05. Material is held as pieces, one per (face, cohort). When a
face is divided among rows, each of its pieces is divided in the same proportions
and keeps its cohort. Ages are derived per cohort when asked for; no mean age is
stored. Plate identity is not part of any material record.

**Validity.** First order: the arrangement of cohorts inside one face is not
represented, so a face divided among several receivers gives each the same mixture.

**Independent check.** The D3 staged lune: crust born in the first interval reports
a mean age of exactly 4.0 Myr from its formation interval, where present distance
to the ridge over the present rate would give 4.2 Myr. A rigid rotation and a mesh
change leave every cohort record unchanged.

**Sources.** Inherited: `atlas.spherical-cohort-transactions.v1`
([physical contract](I01_PHYSICAL_CONTRACT.md), section 5) and CM-05 of the
[closure matrix](I01_CLOSURE_MATRIX.md).

### R3-4. Moving boundaries and junctions

**Decision (I03a-2, approved by the coordinator on 3 October 2026 under the owner's delegation; Codex confirms at
review).** `atlas.boundary-migration.v1` ([transitions](I01_TRANSITIONS.md), section 5) is applied over one finite
interval. Each boundary record has one carrier rotation, and a junction goes where the advanced boundaries meet. The
bounds proposal of 3 October 2026 gives every derivation.

| Boundary | Rule | Carrier of its trace over the interval |
| --- | --- | --- |
| Locked | both plates share one stage rotation | that rotation |
| Ridge, accretion fraction `f` | `n·J = n·((1-f) v_L + f v_R)` | `C = R_L exp(f log(R_L⁻¹ R_R))` (M1) |
| Trench | moves with the overriding plate | the overriding plate's rotation |
| Transform | `n·(v_R - v_L) = 0` | the plate it declares as `carrier_side` (D6); without one, only locked |

**Ridges (M1).** Relative to its left plate the ridge turns through the fraction `f` of the right plate's relative
rotation. That is the contract's rule integrated exactly under a constant relative angular velocity of the two
plates. It is exactly covariant: a common rotation `Q` gives `Q C`. I03a used the rotation vector
`(1-f) r_L + f r_R`, which is not covariant. The two differ by `f(1-f)/12 (r_L - r_R) × (r_L × r_R)` at third order,
and not at all in exact arithmetic when both plates turn about one axis. In binary64 they differ in the last bits
(at most about 1e-17 rad over I03a's controls), so every I03a control gives I03a's results within the existing
tolerances (D4). **M1 changes an I03a rule.**
The half-rates are `b_L = f n·(v_R - v_L)` and `b_R = (1-f) n·(v_R - v_L)`. The symmetric value `f = 1/2` is the
contract's; another is admitted only as a declared input. M1 takes the shorter relative rotation, so it describes the
plates' relative motion only while their relative stage angle is below π; beyond that it and I03a's rule differ by π
even for coaxial motion. Nothing refuses such a stage, which is far beyond plate rates. A plate's total rotation composes as
`R_total = R_stage R_prior`.

**Transforms (D6, C6).** The trace is rigid in its carrier's frame and its vertices are kept there. Plates whose
relative pole is not the pole of the trace's great circle cannot slip exactly along a minor arc. At declaration a
transform that declares its carrier keeps its trace's great circle, with the pole formed stably as
`normalise((a+b) × (b-a))` from the trace's first vertex and the vertex farthest from it within 120°. The trace is one
circle when every vertex lies within the band of it. C6 is judged on the far plate's **total** frame relative to the
carrier's, `F_carrier⁻¹ F_far` after the interval. Every trace vertex, carried by that rotation, must lie within the
existing 64 ε band of the stored circle; on a trace that is not one circle, it must lie within the band of where it
was, so such a trace admits no slip in total. A frame change cancels in the relative rotation, and an exact slip
leaves only rounding (at most about 8 ε per placement). This is the round-1 correction (F3). The first version judged
each interval alone, so a far plate turning 60 ε per interval normal to the trace passed every interval and built up
36 band widths, about 41 m² opened and 41 m² closed with no account. A bent trace likewise accepted an exact slip of
2e-13 rad per interval for 36 intervals. (Before that, a segment's own circle was used, and a segment 2.2 km long
carried 7.5° beyond it put an exact slip 84 ε off in tilted axes, Part 3 verifier.) Otherwise the interval is refused
with the port code `transform not slip-parallel`: normal motion would open a gap or an overlap with no account. The
far plate's corners on the trace go with the trace,
and its cells beside it are sheared and remapped among themselves through overlap rows with no party. Nothing is
born or consumed, and material never crosses the trace. The step reports these cells as slid, and a face of a
line's carrier that only gains a sliding junction as reshaped; neither is consumed. A transform with no
`carrier_side` keeps I03a's rule and wording: sliding is not supported, and it is admitted only when its two plates
share one rotation.

**Junctions.** A junction where every record carries the vertex to one point is I03a's case, with I03a's test:
spread within 64 ε and spread over the largest relative displacement within 1e-11 (D4: I03a's behaviour is the
special case, within the existing tolerances). Under three different poles that case relies on M1: in the
hemispheres control, I03a's rotation-vector ridge carried the junction 3.3e-8 rad off the trenches' point, and I03a
refuses the first interval. Otherwise:

1. *Lines (M6, C3).* At declaration each record end at a junction gets the pole of its end segment's great circle,
   formed stably and kept in the carrier's frame. For two records with the same carrier, choose the
   best-conditioned pair from the junction and its two neighbouring vertices (largest stable cross-product
   magnitude). If the remaining point lies within the existing band of that circle, they form one through-going
   line and share one pole. Antipodal neighbours therefore do not cause a zero-vector normalisation: either
   incident segment still defines the plane. This
   is decided once. A line is rigid in its carrier's frame, so it is never tested again, and a pole is never formed
   later from a short pair of vertices, whose direction error grows as `ε/ℓ`.
2. *Residual (C1).* At the start of the interval the contract's residual `r = ||A J - b|| / max |v_i - v_j|` must be
   within 1e-11. Its rows are the stored poles and `b` is each record's carrier velocity there relative to one plate
   at the junction (the first by ID). That is the same residual in exact arithmetic, and it keeps the round-off at
   the scale of the relative velocities: with absolute velocities, a common rotation of every plate raised `b` and
   not the scale, and the Part 2 verifier found a slow T-junction refused at `9e-11` in the case's own rotated
   frame. The scale uses the plates' relative velocities, which is I03a's precedent and looser than the contract's
   literal "constraint velocities". For one line and one other record, or two lines of one record, `r` is zero by
   structure, to round-off.
3. *Three or more distinct lines* without a supported supplied path are refused by the rigid-line route. Three independently carried,
   unextended rigid lines that meet at one instant generally stop being concurrent at order `θ²` after an
   interval of rotation `θ`. This is not proof of physical instability: a junction satisfying the velocity
   closure can require newly generated boundary-end segments rather than rigid endpoints. Such finite-step
   construction is an I03 geometry responsibility. Physical reorganisation is required only when the physical
   closure fails or the topology changes, not merely because this representation cannot advance it.
4. *Two lines.* The junction goes to the intersection of the two advanced lines nearest the junction as the first
   line carries it (not nearest its start, which picked the antipode once a frame rotation moved it more than 90°
   in one interval, Part 2 verifier). Records on one great circle through the junction with different carriers
   would be one line carried by two plates, and such a junction is refused when it would advance (C3). C3 says to
   refuse that at declaration, but I03a admits such declarations and moves their junctions while every record
   carries them to one point, so the refusal waits for the advance. The lines must cross at
   `sin ψ ≥ 1/16` (C4: each stored pole carries at most 2 ε after one rotation, and the junction must stay within the
   band), or the junction is refused as underdetermined. A boundary between real
   junctions cannot collapse without reorganisation (C5). Ordinary degree-two
   sampling vertices on the through line can now be passed (D1-b): the carrier
   retains them, they move to the record behind, and the opposite face ahead loses
   them. Exact landing and traversal of multiple sampling vertices are covered.
   The constructed classes are transform-through-line motion, a carried ridge on
   that line, and a ridge on a trench line. Updated chains determine both the new
   ridge strips and the consumption owner of passed trench segments; passing a
   sampling vertex cannot leave either account attached to the obsolete chain.
   D1-b is not constructed where a plate also builds a D5 transient triangle at
   the junction (item 5): that triangle is built on the original trench end
   segment, and its born strip takes no retained sample. Passing the vertex that
   ends the triangle's trench segment, or a vertex at or between the triangle's
   intersection X and the new junction, is refused naming this case. A declared
   vertex between the new junction and X that the junction does not pass is named
   in the X-outside refusal (X lies beyond it), because D5 needs X on the trench
   segment next to the junction. A pass outside the triangle, beside a
   zero-opening side, stays admitted (v4 `d5_traversal`).
   A material seam requires its own moving intersection, not this degree-two rule.
5. *Construction.* The plate that carries the through line keeps its old corner where it was, as a new vertex of
   the record behind, and the junction is inserted into its face ahead. Its faces otherwise ride. A plate beside an
   opening ridge that is fixed relative to the carrier shares that old corner. A subducting plate's corner is pulled
   to the junction. The sharing plate's view of that corner is its own previous corner, unchanged, so its faces that
   only ride keep their bits in any frame. Seen through the carrier's frame they did not, and the same history was
   refused under D3 or with a moving carrier (round 1, F4). A plate on the ridge side that slides along the line
   would need its old corner to slide along the
   line as a vertex of it (option D1-c), which needs an explicitly supported seam
   construction. A ridge-side plate subducting beneath the line uses D5's
   construction below. The old blanket refusals applied also where every
   record carries the junction to one point: there too the plate's pulled corner would leave its opening unbooked
   (Part 3 verifier: 1.9 m² accepted with no birth at a motion of 1e-11°). Two junctions sliding on a line record of
   one segment each find the other's old corner by its new name. A junction whose records lie on two lines of one
   record each (a corner) is advanced only where they carry it to one point.

**Validity.** One stage rotation per plate per interval; a ridge must open on both sides and a trench must consume.
D5 now constructs the intersection `X` of the carried ridge-side material edge
with the advanced trench. `X` must lie inside the appropriate minor-arc segment,
not behind its former corner. The surviving face ends at `X`, the born strip
fills the supported remaining region, and the transient triangle is both supplied
and consumed once (section 5). The overriding face receives the same trench
subdivision. A geometrically inadmissible triangle or an unowned overriding-side
region refuses; neither a missing supply nor a sliver is concealed by an area
tolerance. The original failing-first examples remain negative controls where
they violate these premises, not convenient positive fixtures.

On a later interval, `X` is not a frozen point on the overriding plate. Where one
straight trench carries exactly two subducting material faces meeting one carrier
face, the shared material edge rides with its plate and is intersected again with
the advanced trench. Both sides receive that one updated subdivision. The crossing
must remain on its admitted minor arc, have the existing C4 conditioning and keep
its order relative to neighbours. This preserves both cohorts through a second
moving interval and through save/reopen/continue; it does not merge material or
permit a junction collision. The shortcut for a single carrier face applies only
to a consuming trench without crossed declared vertices. Sliding transforms and
D1-b traversal retain their shared-old-corner construction.

**Independent checks.**

- *Lunes and frames.* In the D3 control the strips lie at the predicted longitudes to 2e-12 rad. With `f` of 0.25,
  0 and 1, each side receives its share. M1's covariance defect is about 1e-16, and it equals I03a's rotation for
  coaxial motion in exact arithmetic (last bits in binary64).
- *Junctions.* Under three different poles the T-junctions persist where every record carries them to one point.
  Junctions of a northern hemisphere turning on the equator advance exactly by its rotation and are refused at the
  predicted lifetime. A frame change by the D3 definition (`R_k → G_k R_k G_{k−1}⁻¹`) changes neither acceptance
  nor positions beyond 2e-12 rad, including relative motion of 1e-4° per interval and frame rotations of 100° and
  150°. One interval and 2, 4, 8 or 16 sub-intervals agree within 8 ε (C8, C9). Two ridge-ended classes migrate
  and are controlled:
  - a ridge carried by its moving plate ending on a carried line, with the other ridge side locked to the line's
    carrier: lifetime to the next junction; strips 1 m to 111 m wide in fixed axes, D3 and with a moving carrier;
    tilted; halves;
  - a ridge on a trench line in the hemispheres world under three poles: lifetime to the next vertex, plain and
    tilted; D3; halves.

  A motion about another axis at the poles of the three-plate world is refused by the residual.
- *Transforms.* Exact slip remaps cells only into their neighbours, also along segments 2.2 km long in tilted and
  D3-rotated axes. A pole 1e-6 rad off, and a bent trace, are refused with the port code. So are a normal turn of
  60 ε per interval once it adds up to the band (the second interval), and a slip of 0.4 band per interval on a bent
  trace (the third).

**Sources.** Inherited: `atlas.boundary-migration.v1` and its closure residual; McKenzie and Morgan (1969) as cited
there (not accessed). M1 and the construction are derived here; they are not taken from plate-reconstruction
software. The bounds proposal and the coordinator's approval record give the derivations and the approval's
conditions.

### R3-4b. Explicit within-interval junction histories

The larger repair adds an opt-in supplied-history representation, not an automatic
ridge-direction law. Plate rotations and the instantaneous normal-velocity
constraints alone do not uniquely determine the future directions of general
oblique ridge ends. Selecting perpendicular spreading, smoothing a seam, or
minimising a residual would add an assumption not present in the input.

`JunctionPath(junction_id, reference_plate_id, relative_rotation,
max_deviation_rad, max_segments)` declares the missing trajectory. Both the
accuracy and segment ceiling are explicit; neither is a hidden universal setting.
All paths in one `Motion(junction_paths=...)` share one reference plate. This route
records `common_reference_exponential_v1`; without paths, the legacy M1 rule above
is unchanged. The new route's interpolation is a declared kinematic convention,
not a force balance or a claim that finite endpoint rotations determine a unique
history.

Let `F0` be the reference plate's stored frame, `R0` its interval rotation,
`Rp` another plate's interval rotation, and `s` range from zero to one. Define
`Omega_p = log(F0^-1 R0^-1 Rp F0)` and the path's `Omega_J` from its supplied rotation
in those same stored local axes. Use the common reference motion with relative
paths `exp(s Omega_p)`. A ridge's carrier has
`Omega_C = (1-f) Omega_L + f Omega_R`, so its instantaneous velocity obeys the
declared ridge rule in this shared history. Its finite rotation can differ from
legacy pairwise M1 for noncommuting rotations; that difference is recorded, not
silently substituted into existing motions.

In the carrier's coordinates a new end trace follows
`q_i(s) = exp(-s C_i) exp(s J) x0`, writing `C_i=Omega_C` and `J=Omega_J`.
The endpoint carrier frame places the complete trace. The exact analytic tangent,
not the final sampled chord, supplies the end normal retained for the next interval.

**C1: compatibility with the inherited tangent.** Set `d_i=J-C_i`,
`t_i=d_i × x0`, and let `n_i` be the stored initial unit boundary normal in the
common reference axes. The supplied path must satisfy

`r = sqrt(sum_i (n_i · t_i)²) / max_(p,q) |(Omega_p-Omega_q) × x0| <= ALGEBRA_RELATIVE`.

`ALGEBRA_RELATIVE=1e-11` is the existing named C1 constant, shared by the path
and transfer modules without a circular import. A zero denominator refuses.
This tests the supplied trajectory against the inherited geometry, not a
least-residual choice of a trajectory. Later, the analytic normal is perpendicular
to `d_i × exp(sJ)x0` by construction, so normal-velocity closure holds throughout
the supplied interval, not merely at its endpoints.

**C4: conditioning throughout the interval.** Write `v_i=|d_i × x0|`.
Since `|x'(s)| <= |J|`, the tangent norm is at least
`ell_i=v_i-|d_i||J|`; require `ell_i>0`. The unnormalised normal is
`a_i(s)=d_i-(d_i·x(s))x(s)`, with derivative bounded by `2|d_i||J|`.
Normalising projects that derivative onto the normal's tangent plane and divides
by `|a_i|`, giving a unit-normal drift bound over `s in [0,1]` of
`L_i=2|d_i||J|/ell_i`. Therefore

`|n_i(s) × n_j(s)| >= |n_i(0) × n_j(0)|-L_i-L_j`.

At least one pair must have this lower bound `>=1/16`, the existing C4 sine
criterion. Common frame rotation preserves this norm. This sufficient certificate
can refuse a physically admissible history when its bound is too conservative;
such a refusal is not proof of physical instability.

**Representation floors and caps.** Initial generated tangent norm must exceed
the existing `64 ε` band, and its dot product with the outgoing old segment must
be negative: this family extends rather than retracts. The norm measures angular
motion over the normalised interval, not a new dimensional minimum plate speed.
`max_deviation_rad` is finite and strictly between `64 ε` and `π/2`. The floor
separates representation accuracy from coordinate roundoff; the cap restricts this
supported representation and is not a universal physical stability theorem.
The retained family also refuses `|J-C_i|>=π`, rather than representing winding
or an ambiguous whole-history span. None of these replaces orientation, closed
coverage, conservative support or the existing chart limits.

**Chord certificate and execution ceiling.** For `q_i`, the angular vector is
`w(s)=exp(-sC_i)(J-C_i)`, so `|w|=|J-C_i|` and `|w'|=|C_i × J|`.
From `q''=w' × q+w × (w × q)`,
`|q''| <= M=|J-C_i|²+|C_i × J|`. A parameter interval of width `h` has Euclidean
chord error at most `delta=M h²/8`; normalising the chord bounds angular error by
`2 asin(delta)` when `delta<1`. The normalised chord traverses the same minor arc.
This is a representation-error bound, separate from C1 and coordinate roundoff.
Commuting equatorial rotations need no error-driven subdivision.

Sampling uses deterministic bisection: segment counts are `1,2,4,...`.
Consequently `max_segments=3` permits at most two segments, not three or four.
If the next required power of two exceeds the supplied ceiling, it refuses.
The declared maximum samples are charged to the caller's memory budget throughout
geometry, transfer and restoration, not only while the trace is constructed.

Even an exact great-circle arc must obey existing geometry admission. Each
segment's angular length is bounded by `|J-C_i|/count`; subdivision continues
until this is below `π-angular_resolution_rad` and its midpoint-chart endpoint
cosine is at least `CHART_MIN_COSINE=1e-3`. Emitted edges are checked against the
atlas's existing angular resolution at zero and π. Thus the exact-curve shortcut
cannot emit an unresolved near-antipodal chord. These local checks do not guarantee
that a whole face fits one chart; full network validation still decides that.

**Approval status.** The gates the review listed (C1 on the analytic tangent, the
C4 certificate with its drift bound, the 64 ε minimum tangent, the accuracy band and
π/2 cap, `|J − C| < π` and the reference convention) were approved under the owner's
3 October instruction to fix everything, given after the review raised their missing
approval trail. Two sampler rules were added after that instruction: the
chart-cosine subdivision and the emitted-edge atlas-resolution check. The owner
approved them explicitly later on 3 October, in the coordinator session, on the
coordinator's recommendation. This is owner approval, not a claim of earlier
Claude/coordinator approval or retrospective predeclaration of the first path
controls. The review found the chord and C4 derivations sound;
that mathematical finding and approval are separate. Section 12 lists the uses.

The represented extension is outward-growing all-ridge junction ends. Other
trajectory families must be represented explicitly before they are admitted;
unsupported inputs refuse. Physical path selection and reorganisation remain
with their later producers, not an undocumented geometry correction.
The present regional velocity port carries one constant angular rate per plate.
It therefore refuses velocity-bearing extraction and committed returns for **every
motion with nonempty `junction_paths`**, including a special case whose spatial
rate happens to be constant. An endpoint-equivalent rotation rate is not silently
passed off as its actual history. Material-only readout remains available. A regional
consumer must gain an explicit time-varying forcing port before coupling this path
family to its dynamics.

### R3-5. Regional projection bounds

**Decision.** Proposed and approved by the coordinator on 3 October 2026, as written;
Codex confirms at review.

Every account a bridge moves is measured on the sphere: each face's stored pieces and
its measured spherical area. A projection therefore never enters an account; it
affects only the geometry handed to the regional model. Inside I03.1–I03.2, gnomonic
charts are used for topology and polygon intersection only.

The regional frame is `coordinates.LocalCartesianFrame` at the footprint's centre:
east, north and up, turned by a declared azimuth. It is an exact rigid map of 3-D
positions. A regional model that keeps all three coordinates therefore has no
projection error beyond the rounding of one rotation. What a lower-dimensional model
omits is reported:

- **`'3d'`** omits nothing.
- **`'map'`** omits the vertical. At angular distance `ρ` from the centre the surface
  lies `h = R(1 − cos ρ)` below the plane, and radial lengths and areas are
  foreshortened by `cos ρ`. The relative length and area error is therefore
  `δ = 1 − cos ρ`. The extract reports `ρ_max`, `δ_max`, `h_max` and `h_max` over the
  depth extent, and gives each face its spherical and its projected area side by side.
- **`'section'`** omits the across-section horizontal direction. It follows
  `regional_forcing`'s rule, "never discard motion outside a chosen section". It is
  admitted only when the across-section component of every velocity handed over is
  within that module's round-off, 64 ε of the speed there. It needs the interval's
  motion.

**Criteria.**
- **P1.** Every footprint vertex satisfies `p·c ≥ CHART_MIN_COSINE`: R3-2's existing
  conditioned-chart limit, newly applied.
- **P2.** A `'map'` consumer declares `max_relative_distortion`, with no default, and
  a `δ_max` above it is refused. What a regional solver can absorb depends on that
  solver (I07, I08, I09), so an Atlas constant would be fitted.
- **P3.** The depth support is declared and the drop over depth is reported; nothing
  is refused on it.
- **P4.** Every velocity is a full 3-vector.

**Rejected:**
- a gnomonic regional frame, which distorts by `sec² ρ`;
- a fixed Atlas distortion bound;
- `1e-12` as a projection bound, which would admit only regions about 9 m across.

The bounds proposal of 3 October 2026 gives the derivation, and the coordinator's
approval record its reasoning. The tests of P1, P2 and the section rule were declared
before approval and run only after it. One of them was run once by a verifier before
approval; that run is not used as evidence.

### R3-6. What was taken from pyGPlates

The pyGPlates reference was read for meaning only, not used as software.

- **Finite rotations.** `(pole, angle)` and `(-pole, -angle)` are one rotation, and
  composition does not commute. Atlas compares unit quaternions up to sign and fixes
  its own order (R3-4), which a control checks.
- **Shared sub-segments.** A boundary section shared by two plates is one object
  with an orientation relative to each. Atlas stores one `Boundary` record with a
  left and a right plate and no per-plate copy.
- **Subduction polarity.** Overriding and subducting plates are named with a left or
  right polarity relative to the line's direction. Atlas declares
  `subducting_side` the same way.

Not taken: resolved topologies obtained by intersecting independently moving
boundary lines at each time. The transitions contract excludes closing gaps that
way, so an Atlas network must stay closed by its own records.

### R3-7. Reuse or native

**Decision.** A bounded native implementation on existing dependencies: the W01
atlas and chart, `kinematics.Rotation`, shapely/GEOS for planar polygon
intersection, and the I02 ledger and store. No library is added or installed. The
need is small (first-order transfer between conforming minor-arc faces), the atlas's
own measures must be the ones used for accounts, and identities and persistence must
go through I02. No external code is adopted, so no licence or dependency decision
arises; adopting pyGPlates or ESMF would be an owner decision, and their licences
were not assessed here.

## 3. The network state (I03.1)

### Records

| Record | Holds | Notes |
| --- | --- | --- |
| `Face` | face ID, owning plate, outer ring and holes of vertex IDs, optional block ID | a numerical cell, counter-clockwise seen from outside; not a material |
| `Plate` | plate ID, total finite rotation since the reference time, parent plate IDs | parents record lineage only |
| `Boundary` | ID, kind (ridge, trench or transform), left and right plates, oriented vertex chain, origin, `closed`, and the rule its kind needs | a ridge declares its accretion fraction in [0, 1]; a trench its subducting side; nothing is assumed |
| `Origin` | prescribed initial condition (naming its source) or a named creation event | |
| `Junction` | vertex, incident record ends and plates in counter-clockwise order | derived, never declared |
| `Lineage` | parent and root network identities, applied event identities, retired face, boundary and plate identities | a retired identity stays reserved |
| `Cohort` | cohort ID, material ID, origin ID, formation interval, history reference | never a face or plate ID |
| `Piece` | face, cohort, occupied area, mass and volume per phase, enthalpy | one per (face, cohort) |

Physical interfaces are separate from the sampling mesh. A boundary record follows
only edges between two plates and is stored once. An edge between two faces of one
plate is a seam of the mesh and belongs to no record.

A declaration is put into one canonical form before it is used. A ring starts at its
smallest vertex ID and keeps its direction; holes and parent plates are sorted; a
closed boundary chain starts at its smallest vertex ID; a block ID equal to the
plate ID is no block; and minus zero is stored as zero. Two spellings of one network
therefore issue one identity. A malformed record is refused with the package's own
error, never with a Python error from deeper in the calculation.

### What `build_network` checks

The W01 atlas checks that every edge is used once in each direction, that the faces
around every vertex make one full turn, the Euler characteristic, and the summed
area against `4π` within 2e-11 sr. `build_network` adds: every face names a declared
plate and every plate owns a face; exactly one boundary record per edge between two
plates, with sides matching the faces beside it; no record along a seam; no chain
through a vertex where another record ends or a third plate touches; acyclic plate
lineage; and no reuse of a retired identity. A gap, overlap, T-junction, unpaired
seam, pinch or second vertex at an existing position is refused. Nothing is snapped,
welded or repaired.

### Accounts

`SphereMaterial.stock` has one row per piece and one column per account: `area_m2`,
then `mass_kg:<phase>` and `volume_m3:<phase>` for each declared phase, then
`enthalpy_j` when a basis is declared. Three exact rational accounts are kept per
column, as the I02 exchange keeps them: the declared totals, what each named party
has supplied since the declaration, and the rounding of the stored binary64 values
with its allowance. The identity

```text
sum(stored pieces) = declared + sum(supplied) + rounding ,   |rounding| <= allowance
```

holds exactly for every column, or nothing is issued. An exact account must also
read back from its stored text as the same number (the I02 bound: magnitude below
2^960 and at most 1024 characters); a state whose accounts could not be restored is
never issued.

**One owner per point.** Two checks tie the pieces to the geometry, both with
existing tolerances:

- *Per face.* The pieces of every face occupy its measured area within
  `max(1e-12 μ, A)`, where `A` is the face's stored allowance (D7′, R3-1). `A` is zero
  except for a thin face after a whole-face mesh step, where it can exceed `1e-12 μ` by
  orders of magnitude: about 1e-8 of the face for strips a few metres wide. This is
  checked after every interval for every face, including faces that only rode with
  their plate, and again whenever a state is declared or restored.
- *Whole sphere.* The pieces of every state together occupy the network's area
  within the atlas's own closure, 2e-11 sr times `R²`.

**History of the per-face check.** I03a first checked every face after every
interval. Its own long histories then failed it. Vertices were stored in the sphere's
axes and rotated every interval, so a face that only rode was rounded once more each
time, and a thin strip's measured area wandered from its pieces by more than 1e-12. At
0.05° per interval the three-plate history was refused at interval 11 (15 about a
tilted axis), and at 0.1° at interval 87 (45 tilted). I03a then narrowed the check to
the faces a step created or changed. Codex's review showed that the narrowing was not
a remedy. A state holding a 55 m strip, turned rigidly 20 times, ended with the strip's
measured area `3.65e-11` from its pieces, relative. Verification and restoration
accepted that state, and a later mesh change, even a rename of that face, was refused
as an unresolved overlap. I03a-2 removed the cause. Vertices are kept in reference
frames (section 4), so a face that rides keeps its coordinates and its measured area
bit for bit. The per-face check was then restored for every face after every interval,
with the tolerance unchanged except for faces carrying a D7′ allowance (R3-1).
[`test_i03_frames.py`](../tests/test_i03_frames.py) runs Codex's path and fails on the
code before the change. I03a's four long histories (0.05° and 0.1° per interval, plain
and tilted, 254 intervals each) were re-run in scratch. Under the narrowed check all
four were accepted, but faces ended up to `4.0e-12` from their pieces. With every face
checked, all four are now accepted for all 254 intervals, the worst face within
`3.7e-15` of its pieces.

A stock link (section 5) needs declared phases and an enthalpy basis, because the
finite stocks it joins carry both.

### Identity, catalogue and unknowns

A network, a material and a state each have a SHA-256 identity over their canonical
record and the exact bytes of their arrays. The state record (schema
`atlas.i03-sphere-state.v2`) binds the network and material identities, the clock
(epoch, time, step), the frame, the unit system, the I02 catalogue identity and the
parent and root state identities. Issued objects are immutable and compare by
identity: `arrays()` hands out fresh read-only views, and a stock link is a
read-only mapping. `verified(state)` recomputes every identity from its record and
arrays and compares every part a caller can read (faces, plates, boundaries,
junctions, cohorts, accounts, clock and frame) with what those records describe, so
an edited attribute is refused as well as an edited record. As in I02, code that
rewrites a whole state and all its identities consistently is not defended, and the
name of the function that issued a state is provenance, not identity.

**Schemas.** The state and network retain `atlas.i03-sphere-state.v2` and
`atlas.i03-sphere-network.v2`. Steps and overlap maps use
`atlas.i03-sphere-step.v3` and `atlas.i03-overlap-map.v3`: these add explicit
transient birth-to-consumption rows, rather than inventing an endpoint face for
material that exists only within the interval. The stored arrays are `sphere.vertex_ids`,
`sphere.vertex_home`, `sphere.vertex_reference`, `sphere.view_vertex`,
`sphere.view_plate` and `sphere.view_reference`, with the faces and boundary records as
before. The network record gains each plate's and each ridge record's frame rotation, and
the pole of every record end at a junction (M6, `end_poles`). The material record is
version 2 (`atlas.i03-sphere-material.v2`): it adds each face's occupancy allowance
(`sphere.face_occupancy_allowance`, D7). A transform record may declare `carrier_side`.
`sphere.vertex_direction` is the same catalogued quantity, derived from them. Where a
vertex is kept is derived from its records and faces, never chosen: a layout that keeps
a vertex anywhere but with its carrier is refused, so one network has one stored form.
A declared state must hold a declaration: every frame at the sphere's axes and every
copy equal to its vertex's own direction, bit for bit. I03a's
version 1 states, steps and maps are refused by schema. The repair also refuses
version 2 steps/maps rather than silently interpreting them as transient-aware v3.
These experimental histories are not migrated or rebound.

`rotate_frame` expresses the same network in rotated axes (each plate rotation `R`
becomes `Q R Q^-1`); it is a change of coordinates, not a motion. It preserves each
face's measured area to that face's resolution (R3-1), not to 1e-12 for every shape.

Thirteen quantities are registered once in the I02 catalogue
(`integration_state.CATALOGUE`), owner "I03 spherical network", status `supported`:

| Name | Units | Support |
| --- | --- | --- |
| `sphere.vertex_direction` | 1 | network vertex |
| `sphere.face_plate` | 1 | network face |
| `sphere.face_area_m2` | m2 | network face |
| `sphere.boundaries` | 1 | shared boundary |
| `sphere.junctions` | 1 | junction |
| `sphere.plate_rotation` | 1 | plate |
| `sphere.lineage` | 1 | network |
| `sphere.cohorts` | s | cohort |
| `sphere.piece_area_m2` | m2 | cohort x face |
| `sphere.reference_mass_kg` | kg | cohort x face x phase |
| `sphere.phase_volume_m3` | m3 | cohort x face x phase |
| `sphere.enthalpy_j` | J | cohort x face |
| `sphere.exterior_accounts` | m2; kg; m3; J | named exterior |

A column envelope alone reports all thirteen as not carried: the network stands
beside the envelope in a commit, not inside it. Unknown is not zero. Reference mass
and phase volume are unknown when no phase is declared, enthalpy when no basis is
declared, and a cohort's formation when its interval is not given. The content
behind a history reference is unknown to I03.

## 4. Moving the network over one interval (I03.2)

A `Motion` declares the interval of whole global steps it covers, one stage rotation
for every plate (a plate that does not move is given the identity explicitly), a
`Supply` for every ridge side that opens, a `Sink` for every trench that consumes,
and optionally a replacement `Mesh`. `advance` then:

1. **Classifies each boundary** as locked, ridge, trench or sliding transform by
   R3-4. A transform slides only with a declared carrier and only when its far plate
   slides exactly along its trace (C6); otherwise the interval is refused.
2. **Moves every vertex.** A vertex on no boundary rides with the one plate around
   it. A boundary vertex is moved by its record's rotation. A junction goes where its
   records carry it if they agree (I03a), or else to the intersection of its two advanced
   lines, under the checks of R3-4; the line's carrier then keeps its old corner in the
   record behind. Rotations are applied element by element, so one
   vertex moved alone and the same vertex moved with its plate land on the same
   bits; a library matrix product does not guarantee that.

   **Where the result is kept.** Each vertex is kept as a unit direction in a
   reference frame:
   - a vertex inside a plate, in that plate's frame;
   - a trench's vertices, in its overriding plate's frame;
   - a transform's vertices, in the frame of the plate it declares as its carrier
     (`carrier_side`), or of its left plate when it declares none;
   - a ridge's vertices, in the ridge record's own frame. Where records meet, a
     trench's carrier is preferred, then a transform's, then a ridge.

   A frame is a rotation composed once per interval with its carrier's rotation: the
   plate's stage rotation, or the ridge's rotation of R3-4. It is applied once to the
   stored direction to place the vertex in the sphere's axes, so no vertex is rounded
   again interval after interval, however many intervals pass. A plate whose faces use
   a vertex kept elsewhere keeps its own copy of it in its own frame. Every face is
   measured from its own plate's coordinates. The decisions of this list (attachment,
   copies, junction closure) are still taken in the sphere's axes over this interval.
   A plate's image of a vertex is its own corner: its own copy, placed by its frame
   and moved with it. The vertex's home decides first; every other plate's copy is
   then measured against the vertex's own placement, exactly as it is checked on issue
   and restore (C10, form a, approved 3 October 2026), and is placed again at the
   vertex only when it would lie more than the 64 ε band from it. So motion slower
   than the band cannot accumulate unseen between a copy and its vertex: once the
   motion since the corner was placed exceeds the band, the ridge opens or the trench
   consumes there as at any other speed, and `|F_p·copy − F_home·reference|` stays
   within the band plus 4 ε of rounding. Where records meet, the kind of a record, not its status in
   one interval, decides where its vertices are kept: a ridge keeps them in its own
   frame even in an interval in which its two plates turn together.
3. **Opens ridges.** Each plate beside an opening ridge keeps its own copy of the
   old ridge vertices. The strip between that old edge and the moved ridge becomes
   new faces of that plate, one per ridge segment and side. A strip that would have
   the wrong orientation means a negative half-rate and is refused.
4. **Consumes at trenches.** The subducting plate's boundary faces are deformed to
   end at the moved trench. The quadrilateral between the plate's rigidly carried
   old edge and the trench is the swept region; a swept region of the wrong
   orientation means the trench opens and is refused.
5. **Validates the result** as a closed network by section 3's checks. A boundary
   cell consumed past its far edge inverts and is refused there.
6. **Applies a mesh change**, if declared: the same plates, records, time and
   lineage on other faces. A mesh cannot move, subdivide or remove a boundary chain.
   A `Mesh` lists every face of the new mesh and any vertices it adds; an added
   vertex that no face uses is refused, and the mesh identity does not depend on how
   an added direction was scaled before it was captured.

Whether a strip or a swept region has the right orientation is decided by the sign
of `a · ((b - a) × (c - a))` at each corner. This equals `a · (b × c)` but is formed
from differences of the ring's own corners, so it stays reliable for a ring a few
metres across. The junction pass of the endpoint network draws on the caller's work
budget and geometry limits and polls the caller's cancellation, like the rest of the
step.

Faces that only rode with their plate are the same records afterwards. Their
pieces, their coordinates in their plate's frame and their measured area keep their
exact bytes.

## 5. Overlap rows and exact transfers

**Rows.** A row is `(donor face, receiver face, party, area)`. Birth rows have no
donor and name the party `ridge|<boundary>|<side>`; their area is the new face's
measured area. Each deformed boundary face of a subducting plate, carried rigidly
with its plate, is intersected with the deformed faces of its plate and with the
swept regions; consumption rows have no receiver and name `trench|<boundary>`. A
mesh change adds rows between the replaced faces and their replacements. No row is
discarded, however small.

**Audit.** Before any amount moves, the rows are checked against the geometry they
claim to describe, whether just measured or read from a store: births match the born
faces and their measured areas exactly; every other row joins changed faces of one
plate or a trench that consumes that plate; a row joins two faces only if their
bounding caps reach each other; each donor's rows close on its area and each
receiver is filled (relative 1e-12 of that face's area); and each trench consumes
what it swept, `|consumed - swept| <= 1e-12 swept`. Boundary-cell area does not set
the trench's allowance.

**Thin sweeps and precision (repair of I03a's Ruling 13).** The earlier implementation
multiplied the tolerance by the larger boundary-cell area after a thin-sweep failure.
That unapproved criterion is removed, not retrospectively approved. When ordinary
projected overlaps miss `1e-12 swept`, only that trench's consumption overlaps are
recomputed using exact integer side predicates and homogeneous spherical clipping.
Concave rings are decomposed into triangles; hole contributions use inclusion-exclusion.
The triangle determinant and dot products are exact integers. Square roots and the
denominator use 80-digit decimal arithmetic before one final floating-point `atan2`,
retaining the existing one-ulp platform assumption. Swept rings use the same measure.
The fallback first applies the ordinary path's conservative bounding-cap reach
test, then reuses each donor's deterministic triangulation across candidate swept
rings. This avoids repeated exact work on unreachable pairs without discarding an
overlap or changing its measure. Its cost remains geometry-dependent; timing
evidence is recorded separately rather than inferred from this construction.
Thus clipping arithmetic is improved instead of accepting a larger discrepancy.
This measures the stored directions accurately; it does not remove the coordinate
uncertainty of a tiny polygon when the same intended geometry is expressed in another
rounded coordinate frame. The separate slow-sweep comparison accounts for that.

**Reported uncertainty, not an admission allowance.** For each trench and interval,
`Step.summary()['consumption_accuracy']` reports its exact measured sweep and
`sweep_c7_m2 = R² sum C7(ring)` over its actual complete swept rings. An undefined
C7 produces `None`, not zero. Here C7 is the **range-limited** bound, not raw
evaluation bound `E`: with ring area `A` in steradians, perimeter `P` in radians
and `rho=1e-12`, use `E` when `A/P < 1.1e-4`, `min(E,2 rho A)` when
`1.1e-4 <= A/P < 2.2e-4`, and zero at `A/P >= 2.2e-4`. The strict cut-offs are
the same as whole-face C7. For account column `c`, `account_roundoff[c]` is this
area bound multiplied by the largest actual donor density:
`sum(abs(piece_amount[c])) / sum(outgoing_row_area)`; transient ridge supply density
is included in that maximum. Absolute piece amounts keep opposite signed heat
from cancelling the uncertainty estimate. These are per-interval diagnostics.

The fresh predeclared slow-consumption comparison adds the larger of the two
representations' accumulated sweep bounds to `1e-12 × abs(reference consumed total)`.
It uses the corresponding density-scaled bound for amounts. This comparison of
rounded representations does **not** alter the row audit above, which still uses
`1e-12 × swept area`, or relax any conservation identity. The original controls
without a sweep term remain historical expected failures, rather than having their
criteria changed after seeing their results.
Its S1(b) turn is `2e-4°` per interval, not the historical S1 turn of `1e-4°`.
The control explicitly checks that its actual swept rings lie in C7's thin range;
the range rule is not inferred from the remaining endpoint faces.

The audit is a set of necessary conditions. It does not measure an intersection
again, so it cannot tell the measured rows from other rows that satisfy the same
conditions; section 12 states what that leaves open.

**Shares.** A donor piece's value `Q` is divided among its face's rows. Every row
but the largest receives the correctly rounded binary64 value of `Q A_k / sum A`;
the largest receives the exact remainder. The parts sum to `Q` exactly and each is a
binary fraction, so the exact accounts stay bounded.

**Births.** One new cohort per ridge side and interval, `<boundary>|<side>|<a>-<b>`,
with the supply's material, origin and history reference and the accepted interval
as its formation interval. Its amounts are the supply's declared reference mass,
thickness and enthalpy per unit area times the exact born area, booked to the named
source; the area itself is booked to the ridge record's own account.

**Consumption.** The consumed area is booked to the trench record's account. The
consumed mass, volume and enthalpy are divided among the sink's declared
destinations by exact binary fractions that sum to one.

**Born and consumed within one interval (D5).** Where admitted ridge/trench
geometry supplies a transient triangle, its area pairs a ridge-side source party
with a trench sink party. It has no donor or endpoint face index. The geometry is
reconstructed when auditing or restoring; a caller cannot add a free-standing
source-to-sink row. All surviving and transient pieces on one ridge side share
one supply allocation and one cohort for the interval. The transient share is
then passed through the ordinary sink fractions, including signed heat, and its
exact amounts remain in `births[].transient_consumption`. No mass is counted twice
and no empty endpoint face is manufactured. Both finite-stock legs belong to the
same atomic commit. This accounts for an admitted geometric event; it does not
invent a new trench or decide the ownership of an otherwise uncovered region.
At accretion fraction exactly zero or one, a side carried exactly by its plate
has no opening to supply: it may still consume inherited material at the trench,
but creates neither a zero-area transient birth nor a duplicate intersection vertex.

**Finite stocks.** A supply or destination marked as a stock is a W08 stock node of
the I02 exchange. The state's `stock_link` names two declared exchange exteriors
that stand for the network. A birth from a stock becomes one I02 `Transfer` from the
node to the receiving exterior, and a return becomes one from the returning exterior
to the node, both committed in the same transaction. Exhaustion is the exchange's
own refusal and refuses the whole interval. Phase volume has no W08 account and is
booked in the network's accounts only. No other producer may use the linked
exteriors.

**Rounding.** Each changed stored value is rounded to binary64 once; the difference
enters the exact rounding account within its allowance of half a unit in the last
place. A share too small to change a stored value is therefore booked, not refused.

## 6. Commit, restore and continue through I02

- **Root.** `Ledger.create(store, root, sphere=state)` accepts only a declared
  initial network dated at the root's epoch, time and step, in the same unit system.
  A stock link must name declared exchange exteriors of the right roles, with the
  same components and enthalpy basis as the stocks. The network's arrays and record
  go into the root snapshot and its identity into the ledger identity. A ledger
  without a network is byte for byte what it was, and `describe()` reports a network
  only when one is attached.
- **Commit.** When a network is attached, every commit must carry exactly one
  `Motion` for exactly its interval; an absent motion is unknown, never assumed
  stationary. The step is computed from the parent commit's network, its stock
  transfers join the commit's exchange, and the endpoint arrays, the overlap rows and
  the step record are written with the column steps in the one store transaction. A
  refused motion or an exhausted stock commits nothing of the interval. A cancelled
  commit stops inside the network step and prepares nothing.
- **Restore.** A stored step is not trusted. The parent's state is rebuilt through
  its constructors, the recorded motion is applied again, which reproduces the moved
  geometry, the stored rows are audited against that geometry and applied to the
  parent's material again, and the stored record, every stored array, every identity
  and the commit's stock transfers must equal the recomputed ones. Saved donor/receiver
  polygon overlaps are not recomputed; junction constructions and transient supports
  are reconstructed. A stored array must have exactly the issued type, shape and
  bytes: values that would only cast to the issued ones are refused. A root snapshot
  may hold no array of a step. A stored mesh must reproduce the mesh identity its
  record names. A commit in which another producer moved stock through the linked
  exteriors is refused, as `commit` refuses to write it.
  Reconstructing a stored mesh replaces only the Motion's mesh field; all other
  fields, including junction paths, their interpolation convention, events and
  regional returns, remain bound. Paths with a mesh, including an event after that
  mesh, must replay the complete proposal rather than an older positional subset.
- **Continue.** A history saved after some intervals and continued by a new process
  reaches exactly the state identity of the uninterrupted history.
- **Clock.** A `Motion` is accepted among a clock request's transfers and is grouped
  by its declared interval like a transfer. When the clock adopts a record that
  another attempt wrote, it compares the motion identity as well as the transfers.

**Resource ownership.** Both advancement and restoration charge their step workspace
to the caller's work budget. Material construction uses that same budget for both
the motion transfer and an optional mesh transfer, rather than selecting the process
default independently. Restoring saved overlap rows avoids measuring intersections
again, but still reconstructs geometry and transfers material, so it keeps the step
workspace reservation. A budget refusal publishes no partial state and releases the
temporary reservations. These checks change resource admission, not geometry,
transfer weights, scientific tolerances or the stored state format.

The step record (schema `atlas.i03-sphere-step.v3`) holds the interval, the motion
and its identity, each boundary's status and rotation, each junction's spread,
relative motion and closure residual, the largest attachment distance, the map
identity with the three geometry identities and row counts, the births and returns,
the stock transfer labels, the exact closure and the successor state's descriptor.
A step with a mesh change also stores the declared directions of the vertices the mesh
adds (`sphere.remap_vertex_direction`), so that its mesh, and the identity its motion
records, can be rebuilt on restore; that array is part of the map's identity. A
refusal on restore keeps its own cause: a work-budget refusal stays a memory-limit
error, and an invalid stored network reports why it is invalid, not only that it is
incomplete. `verified` also measures every face against its pieces.

Both direct step restoration and ledger inspection name unsupported old spherical
schema versions explicitly, including the current supported version. There is no
implicit migration. The combined mesh/path/event and save/reopen/continue controls
are in [test_i03_combined_replay.py](../tests/test_i03_combined_replay.py); fresh
regional-return admission is covered by
[test_i03_bridge_admission.py](../tests/test_i03_bridge_admission.py).

## 7. Transport port (I03 ↔ I05)

I03 owns geometry, overlap maps, ownership changes and the transfer of extensive
accounts. I05 owns what a history reference stands for and how heat, properties,
bonds and stress or stretch evolve. This is the one place the interface is recorded.

**What I03 provides for each accepted interval** (`Step`, `OverlapMap`):

| Item | Value |
| --- | --- |
| Map identity | `map_id`: SHA-256 over the parent, moved and endpoint geometry identities, the motion identity, the party names and the exact bytes of the row arrays |
| Geometry identities | `parent_geometry_id`, `moved_geometry_id` (after motion), `endpoint_geometry_id` (after any mesh change); atlas geometry identities. In an interval with topology events (section 9) or regional returns (section 8), the map's endpoint is the network before them. Events change only which plate owns each face, keeping face identities and order, so the row indices stay valid; but the successor's geometry identity differs from `endpoint_geometry_id` |
| Interval | `start_s`, `end_s` (epoch seconds), `start_step`, `end_step` (global steps) |
| Motion rows | `(donor, receiver, party, area_m2)`; donor indexes the parent's `face_ids`, receiver the moved network's; `-1` with a party name marks a birth or a consumption |
| Transient rows | `(birth_party, sink_party, area_m2)`; indices into the map's party names, with geometry-reconstructed support and no artificial face index |
| Mesh rows | `(donor, receiver, area_m2)` from the moved network's faces to the endpoint's; empty without a mesh change |
| Identity rule | a face that is no row's donor maps to itself with all its content |
| Measure and basis | `area_m2` is the area on the sphere of radius `R` of the intersection of the two minor-arc polygons; a share is a row's area over the sum of its donor's rows |
| Cohort changes | new cohort identities with their formation intervals, material, origin and history reference (step record, `births`) |

**Account basis per quantity.** Occupied area in m2; reference mass in kg per
declared phase; phase volume in m3 per declared phase; signed enthalpy in J in the
state's declared `enthalpy_basis`. A supply must declare exactly the state's phases
and give enthalpy exactly when the state carries it.

**What I05 must do to conform.** Key its content by cohort identity (or by the
cohort's history reference) for anything intensive, which then follows each piece
unchanged. Divide anything extensive it holds per piece by the same shares, debiting
each donor once. Supply the history reference of a new cohort through the `Supply`.
Never infer a row from geometry of its own: use the map of the accepted interval.

**Refusal codes** (`TransferRefused.code`; the reason text names the code too):

| Code | Meaning |
| --- | --- |
| `unresolved overlap` | rows do not close on a face, two overlapping faces share no conditioned chart, a moved face is not a simple polygon in its chart, an intersection failed, a row joins two faces that cannot overlap, a face disappears without a row, a piece without area would keep material, or the pieces delivered to an endpoint face do not occupy its measured area |
| `incompatible support` | a supply declares other phases than the network carries, or gives enthalpy when the network has no basis (or the reverse) |
| `stale geometry identity` | a prepared map is offered for another parent, moved or endpoint geometry or another motion |

Any other refusal carries no code. An accepted I05 port record does not exist yet;
when it does, differences are to be proposed as amendments to this section.

## 8. Regional bridges (I03.3)

A bridge hands part of the shared network to a regional process domain and takes the
result back, without becoming a second owner of anything
([`integration_bridges.py`](../src/atlas_tectonics/integration_bridges.py)). The
domain is a regional model of I07 (three-dimensional mechanics), I08 or I09 (map or
section models).

**Sphere to region.** `extract(state, footprint, motion=None, duration_s=None)` reads
a declared set of whole faces and issues a read-only `RegionalExtract`; the state is
not changed. Each face's pieces travel exactly as stored, with the face's measured
spherical area beside its area in the local frame. Columns travel whole: the depth
support is the regional model's declared extent, and no law divides a column by
depth. Given the interval's `Motion` (declared from the state's step) and its
duration, the extract carries:
- each footprint plate's mean angular velocity;
- the rigid velocity at every footprint vertex and at each face's reference point.

These are full 3-vectors in the sphere's axes and in the local frame. The mean angular
velocity is the stage rotation's principal rotation vector (angle at most π) over the
duration. A turn of more than π in one interval cannot be told from the shorter turn
the other way, so such an interval must be divided. Forces and work have no producer
in I03, so they travel as unknown, never as zero.
This velocity port excludes every Motion with nonempty `junction_paths`, even
when a particular path's spatial rate is constant. Such a history needs an explicit
compatible forcing port; omitting the motion still permits material-only readout
where the representation itself permits it (a section requires motion).

**Region to sphere.** `returned(state, [(extract, result), ...])` replaces each
footprint's pieces with the region's, on the same faces. Every other piece keeps its
bytes and the network is unchanged.
- **Accounts.** Each account must be returned exactly over each footprint, against
  totals read again from the state. So must each cohort's amounts: a regional process
  changes no cohort, because turning one cohort into another would need a named, booked
  transformation, which is not built (round 1, B1). An exchange with an exterior goes
  through a named exterior, not a return.
- **Binding.** The extract's identity, projection and parent are checked against the
  state.
- **Result.** A result that leaves every piece as it was returns the parent state
  itself. Otherwise the successor is a computed state whose parent is the given one.

**Committing a return (round 1, B2).** `returned()` works in memory. To enter an I02
history, the pair is carried, `carried(extract, result)`, in the `Motion` of the
interval it belongs to (`Motion(..., regional_returns=(...))`). It is applied at the
interval's end, after the motion and any mesh change, and before the events.
- **Bound to its actual forcing.** A committed return requires an extract made with
  an explicit motion and duration. The extract's identity is recomputed from the
  interval's parent; its forcing identity and duration must match the interval
  actually being committed. The forcing identity excludes regional returns to avoid
  a circular identity, but retains rotations, supplies, sinks, mesh and events.
  For `'3d'`, `'map'` and `'section'` alike, the commit performs a fresh `extract`
  against that actual parent, forcing and duration and compares its extract identity.
  It reapplies every extraction rule, including finite velocities, projection and
  any omitted-motion constraint; checking only projection metadata is insufficient.
- **Faces carried whole.** Both the material and the plate-relative support of every
  footprint face must remain unchanged. Equal stock or equal area is not proof of
  equal support. A face moved rigidly with its plate remains eligible; a cell cut,
  consumed or relocated by a mesh change refuses, even if its stock values match.
- **Same checks as in memory.** It then replaces those faces' pieces under the checks
  above. The I02 ledger commits it with the interval, or not at all.
- **Restoring.** The Motion's record stores the return, so restoring the step applies it
  again. A Motion without returns keeps its record and identity.

**Port for I07, I08 and I09.** This is the contract a regional model builds on.

| Item | Value |
| --- | --- |
| Footprint | `region_id`; `face_ids` (whole faces of the network); `centre_lon_rad`, `centre_lat_rad` and `azimuth_rad` (rad; the local x axis turned from east towards north); `depth_top_m < depth_bottom_m` (m, positive down); `representation` `'3d'`, `'map'` or `'section'`; `max_relative_distortion` (dimensionless; `'map'` only, declared) |
| Interval | a `Motion` declared from the state's step, with `duration_s` (s, positive and finite); optional for read-only extraction, required for a carried return |
| Identity | `extract_id`: SHA-256 over the parent state identity, the footprint record, the projection record, the forcing identity (Motion without regional returns) and the duration; also `parent_state_id`, `network_id`, `material_id` |
| Accounts | `columns`, the material's: `area_m2` (m²), `mass_kg:<phase>` (kg), `volume_m3:<phase>` (m³), `enthalpy_j` (J, in the state's declared basis); `pieces` per face as `(cohort ID, row)`; `totals`, exact per column |
| Geometry | `area_m2` (m², measured on the sphere: the support of every account); `projected_area_m2` (m², the plan area in the local x–y plane: the outer ring's straight-chord polygon less its holes'; None for a section); `rings_local_m` (each face's rings, outer then holes, as positions x, y, z in m in the local frame, z the height above the tangent plane) with `ring_vertex_ids`; `face_point` (unit vectors: the normalised mean of each face's vertex directions, not its area centroid); `frame`; `projection` (`rho_max_rad`, `relative_distortion`, `surface_drop_m`, `drop_over_depth`, `max_area_distortion`, `omitted`) |
| Quadrature and coverage | one point per face, `face_point`, weighted by its measured spherical area `area_m2`; the footprint covers exactly its declared faces, and its extent is `rho_max_rad` from the centre |
| Velocities | `angular_velocity_rad_s` per plate (rad/s); `vertex_velocity_m_s` per (vertex, plate), holes' vertices included, and `face_point_velocity_m_s` per face (m/s), in the sphere's axes; the `*_local_*` fields in the local frame (x, y, up); `omitted_velocity_share`, the largest share of a handed-over speed along the direction the representation omits (up for a map, across for a section, 0 for 3d); all None without a motion |
| Unknown | `forces_n`, `work_j` |
| Return | `RegionalResult(extract_id, representation, pieces)` naming every footprint face as `(cohort ID, row of the extract's columns)`. Cohorts must exist in the parent material and values must be finite floats. Area must be positive wherever any amount is held, and mass and volume must not be negative. Every cohort's exact amounts over the footprint must be those it held |
| Commit | `carried(extract, result)` gives a `RegionalReturn` (with its record and `from_record`), carried in `Motion.regional_returns`. It is applied at the interval's end to faces the interval carried whole, bound to the interval's parent, and the step record lists it under `regional_returns` |

**Refusal codes** (`BridgeRefused.code`; a `BridgeRefused` is a `TransferRefused`):

| Code | Meaning |
| --- | --- |
| `projection invalid` | a footprint vertex beyond the conditioned-chart limit of the centre; a map distortion above the declared tolerance, or none declared |
| `omitted dimension` | a section that would drop motion across it, or a section without a motion; a result of another representation than its extract |
| `unresolved overlap` | two footprints share a face (two regions would own one material); one region returned twice; returned pieces that do not occupy their faces |
| `incompatible support` | a footprint naming faces the network does not have; something other than a Footprint given as one; a result answering another extract; a result for other faces, with unknown cohorts, rows of another shape, negative mass or volume, material without area, an account not returned exactly, or any cohort's amounts changed; velocity-bearing extraction or a committed return with nonempty `junction_paths` |
| `stale geometry identity` | an extract not read from this state as recorded (another state, or an altered extract); a motion declared for another step; missing explicit forcing/duration for a carried return; a changed duration or forcing declaration, including rotations, supply, sink, mesh or event; an extract identity not reproduced by fresh extraction on the actual parent; footprint material, ownership or exact plate-relative support changed over the interval |

A Footprint with an unknown representation is refused with `omitted dimension`. Any
other malformed argument is refused with no code.

**What a bridge does not do.** It reconstructs no field, divides no column by depth,
produces no force or work, and is not a regional model. The regional model owns what
happens inside the footprint. The bridge checks only that it returns the same
accounts on the same support.

## 9. Joint geometry commits (I03.4)

**Route.** Supplied topology events travel inside the `Motion` of the interval they
end (`Motion(..., events=(...))`). They are applied to its endpoint, after the motion
and any mesh change
([`integration_events.py`](../src/atlas_tectonics/integration_events.py)). The I02
ledger recognises a `Motion` as the network's proposal, so the events are committed
with that interval's column steps and transfers in one transaction, or not at all.
Restoring the commit applies them again. A motion without events keeps the identity
and record it had before I03.4. The ledger itself is not edited.

**Time.** Each event declares its time (`time_s`, epoch seconds). It takes effect only at
the end of the interval that ends at that time, so nothing is applied in the middle of
an interval. The I02 clock's schedule places the interval ends, and a supplied event is
located exactly there: `atlas.event-transaction.v1`'s bracketing has nothing left to
find. An event whose time falls inside an interval, or in another interval, is refused.
That interval must be divided at the event, at a whole step of the clock's schedule.
The design and these two conditions were accepted by the coordinator on 3 October 2026.

The records follow `atlas.topology-transactions.v1` in `prescribed_history_v1`. Any
other basis is refused, because generating an event needs an admitted law. This is
also the entry point for later material-derived interface proposals (I07.5,
MC-05): they will arrive as event records of their own basis, once their law is
admitted.

**Events.**
- **Split** (`Split(event_id, plate_id, parts, boundary, time_s)`). A plate is divided into
  two fresh plates by whole faces, named by face identity at the interval's end.
  - The new boundary record's origin is the event. It follows existing edges and must
    end on existing boundaries or junctions.
  - A record that bordered the plate is re-sided whole when one new plate lies along
    it. Otherwise it is cut where the side changes, into fresh records named
    `<old>|<event>|<k>`, and the old identity retires.
  - A split through faces needs a mesh change in the same interval first.
- **Merge** (`Merge(event_id, plates, new_plate_id, time_s)`). Two plates join into a fresh
  plate. They must have moved together over the interval (one stage rotation) and
  share at least one record. The records between them (the suture) retire.
- **Ridge jump** (`RidgeJump(event_id, split, merge)`, its split and merge at one time),
  as prescribed history only, in one joint proposal:
  - the plate the ridge jumps into is split along the new ridge;
  - the slice left behind is merged with the plate across the old ridge, which
    retires.

  I01's table treats a ridge jump as a split plus a retirement; here the slice's
  identity retires into the merged plate. The slice moved with the split plate over
  the interval and is captured at its end, so the merge's common-motion requirement
  does not apply to it. Its accounts transfer exactly, and it moves with its old plate up
  to the jump and with its new plate after; the coordinator accepted this on that
  condition, and a control checks it.
- **Retirement on its own** is refused, with its cause. A plate retires when its area
  reaches zero through bracketed consumption, which this version cannot reach,
  because an exhausted boundary cell is refused.

**What an event changes: ownership only.** Every face keeps its place on the sphere
and its pieces. So every ownership intersection is exact, no material moves and every
account is unchanged. A face whose coordinates are carried into another frame keeps its
position within the angular tolerance, but its stored coordinates are rounded again,
and so its measured area can change by rounding (below). The bookkeeping that follows:
- **Frames.** New plates inherit their parent's frame and rotation. A merged plate
  continues one plate, its frame and its total rotation, by a rule that does not depend
  on spelling:
  - for a ridge jump, the plate across the old ridge;
  - otherwise, the larger plate by measured area, the first in identity order on a tie.

  The other plate's coordinates, and a retired ridge's vertices, are carried into that
  frame at the instant. New ridge records start with a frame of their own.
- **Poles.** Record-end poles are kept where a record end persists, and formed afresh
  where it is new, in the carrier's frame.
- **Identities.** Plates and records need fresh identities, and retired ones stay
  reserved.
- **Lineage.** It records the interval's event identities once, in canonical order (a
  ridge jump's own, then its split's and its merge's), and the retired plate and record
  identities.

**A face measured again (D7″, approved 3 October 2026 with conditions).** A face is
measured in its plate's frame, so a face an event carries into another frame, or whose
vertices change home, is measured again from coordinates rounded anew. Its pieces do
not change. For a thin face, such as a strip a few metres wide born during slow
spreading, the change can exceed the 1e-12 relative tolerance, although no material
moves. So:

1. **The change is exact.** Δ = μ′ − μ is computed exactly: the two measures lie within
   a factor 2 (Sterbenz).
2. **It is admitted only within a derived bound.** The bound is
   `C7(R) + C7(R′) + 4 ε P`, times `R²`.
   - C7 bounds each measure's rounding.
   - Re-placing every vertex by one composed rotation moves it by at most 4 ε, C10's
     approved rounding of placement and pull-back. That changes the exact area by at
     most `P` times that, `P` being the perimeter.
   - Above the C7 range (area over perimeter above 2.2e-4 rad) the C7 terms are zero, as
     D7′'s cap says, and `4 ε P` alone remains.
   - Beyond the bound the event is refused: that is a displacement, not rounding.
   - Within the range, where C7 is undefined (a vertex beyond 45° of its anchor), D7″
     admits nothing, and the existing check alone decides.
3. **The face's allowance takes the exact change.** It becomes what the per-face check
   allowed it before, `max(1e-12 μ, A)`, plus `|Δ|`, never plus the bound. The pieces were
   within that of `μ`, and `μ′` is exactly `|Δ|` from `μ`, so the identity closes exactly.
   - The coordinator's condition reads "the face's current allowance plus |Δ|". It is
     read here as the allowance the check applies, because with `A` alone the identity
     would not close where `A` is below `1e-12 μ`.
   - Only faces an event measures again are touched. Rides, mesh steps and closures
     keep D7′.

**This is an exception to D7′'s zero ceiling above the C7 range**, because re-expression
is a distinct rounding source: no rows, the same face, new coordinates.

**Measured** (scratch report from the tests' own histories):
- the measured changes are 0.4–7% of their bounds (median under 2%);
- a strip 3.9–5.3 km wide, above the range, changed by up to 2.9e-4 m², against `4 ε P R²` = 3.8e-2 m²;
- over two merges that each measured the same faces again, a thin strip's allowance grew from 0 to 6.7e-4 m², or
  1.4e-10 of its area. A compact face's allowance became `1e-12 μ` plus a few mm².

Without D7″, every merge or ridge jump after slow spreading would need a preparatory
mesh change.

**Simultaneous events** ([I01 transitions](I01_TRANSITIONS.md), section 2):
- **Disjoint events are applied in canonical order and checked in both.** Events of one
  interval whose footprints are disjoint are applied in canonical event-identity order,
  and the result is checked against the reverse order. A footprint is the set of plates
  an event touches: those it divides or joins, and those it creates.
- **Two cuts of one record are refused.** Disjoint footprints do not imply commuting
  events. Two splits of different plates can both cut the record between them, and the
  pieces would be named after whichever ran first. Such pairs are refused before anything
  is applied, naming the record (round 1, V1). The second cut belongs to a later interval.
  The two-order check remains as a safety net.
- **A shared plate means one joint proposal.** Two events touching the same plate are
  refused; they must be submitted together.
- **Finite stocks are aggregated.** The interval's transfer step adds up every finite
  stock it draws, so a joint demand beyond a stock refuses the whole interval, events
  included. There is no first-come allocation and no clipping.
- **Later events cascade.** Each interval's proposal is evaluated on the committed
  state of the one before.
- **Limits.** An event interval is an accepted interval and counts against the
  256-step ceiling. Replaying an event already in the lineage is refused.

**A mesh change and events in one interval.** The stored step keeps the faces after
the events. On restore, the mesh that preceded them is rebuilt from those faces: a mesh
never changes a face's plate, so each face takes its donors' plate in the moved network,
read from the stored mesh rows, or keeps its plate there. Nothing extra is stored. The
I03.4 verifier found that this route committed but could not be restored (its finding
C1); it is fixed and tested through a reopened ledger.

**Refused**, each with its cause:
- a standalone retirement;
- an event whose declared time is not its interval's end;
- junction reorganisation, generated separation, subduction initiation and rift
  migration (no admitted law);
- a merge of plates that do not move together or share no record;
- a split whose new record ends inside the plate, misses some of its faces, or
  crosses a closed record;
- a reused or retired identity;
- two events sharing a plate;
- a ridge jump with no ridge between the slice and the plate across;
- a face measured again in another frame beyond its D7″ bound: a displacement, not
  rounding (see above).

## 10. Controls and what the checks establish

The detailed delivery controls below describe the original I03a/I03b checks.
The 3 October repair adds forcing/duration and exact-support regressions, event-to-rename
continuation, exact-axis junction geometry, strict-sweep exact-overlap controls and the
fresh sweep-uncertainty comparison. New junction-path and transient-accounting checks
exercise the larger extension separately. Current combined results and acceptance
are recorded in [CURRENT_STATE.md](../../docs/CURRENT_STATE.md), not inferred from
this historical control inventory. Mutable per-module test totals are omitted.

The original I03a control values and tolerances are declared in
[`cases/i03_controls_v1.json`](../cases/i03_controls_v1.json), and the fixtures and
tests read them from it. I03a-2's controls are declared in
[`cases/i03_controls_v2.json`](../cases/i03_controls_v2.json), with a provenance note;
v1 is unchanged. The tolerances are existing ones: relative 1e-12, angular
2e-12 rad, area closure 2e-11 sr, the 64 ε attachment band and the small-area
tolerance 1e-7 from the W01 atlas and geometry cases, and the junction residual
1e-11 from the I01 transitions case. I03a introduced no new value. I03a-2 introduces
these, approved by the coordinator on 3 October 2026 (Codex confirms):
- C4's `sin ψ ≥ 1/16`;
- C7's coefficients (`9 ε`, `14 ε`, `4.4 ε + 5 α`) and its range (1.1e-4 and
  2.2e-4 rad of area over perimeter);
- C10's `4 ε`.

The 120° limit on the pair of vertices that forms a trace's circle, its 64 ε
point-to-circle test and the named degenerate-overlay refusal were explicitly
approved in the coordinator's 3 October round-1 addendum. The refusal was later
superseded by the owner's approval of exact recovery (3 October, evening; section 12).
The v2 case lists these,
and its provenance note
records which expectations were declared before their checks first ran and which
were changed afterwards. In v1 that was the polar rows (below), corrected without
changing a tolerance.

I03b's controls are declared in [`cases/i03_controls_v3.json`](../cases/i03_controls_v3.json), with a provenance
note; v1 and v2 are unchanged. I03b introduces no new tolerance. Its criteria were approved by the coordinator on
3 October 2026 before the tests that use them ran:
- R3-5's P1 and P2;
- E1–E3, with E2 corrected.

[`cases/i03_controls_v4.json`](../cases/i03_controls_v4.json) records the repair
controls and their actual provenance. The existing junction-path and transient
fixtures were recorded retrospectively, not represented as predeclared. The new
vertex-traversal, path-contract and sweep-repair fixtures were recorded before
their repair checks ran. The later `d5_traversal` refusal controls (review item N1)
were recorded after their cases were first probed, and say so. V2's bytes and its original refusal expectations remain
historical: `declared_vertex_ahead`'s refusal is superseded by current construction
and v4 controls, not silently reinterpreted as a positive test. The old
`ridge_on_a_trench` fixture still refuses because its computed D5 intersection X
lies outside the old ridge end or advanced trench end. Its former explanation
that transient handling is unimplemented is superseded; the admissible V-wedge
control in v4 exercises the implemented construction.

Two control changes were made openly, each with a note in the case file:
- **`bridge_projection`'s first map tolerance** was found to be below its own footprint's distortion, and was
  corrected. The coordinator accepted the correction as a control-design fix.
- **`equivalence_meshes`** declares the class E2's correction asks for before it ran. Its first run's premise check
  was then narrowed to the faces each step consumes, with no tolerance or expectation changed.

The worlds are small declared
sector meshes on a sphere of radius 6371 km: six or eight pole-to-pole sectors of
four latitude bands and two polar triangles each.

| Control | What it establishes |
| --- | --- |
| Coverage, refusals, identity, material accounts, persistence ([`test_i03_network.py`](../tests/test_i03_network.py)) | closed coverage and Euler characteristic; one record per boundary with its sides; junction cycles; refusal of gaps, overlaps, duplicate owners, T-junctions, duplicate vertices, pinches and reversals; plate identity separate from material identity; frame rotation preserves measures, sides and junction cycles; separate area, mass, volume and enthalpy accounts; unknown is not zero; exact restoration and refusal of edited records and arrays; declared work budget, limits and cancellation |
| Hardening (same module) | equivalent spellings of one network issue one identity; malformed declarations are refused with the package's error; handed-out arrays and the stock link cannot be edited; a forged attribute is refused by `verified`; stored arrays that only cast to the issued ones are refused; an account beyond the exact range is refused before anything is issued; the pieces must cover the sphere; the junction pass draws on the caller's budget |
| Ledger attachment ([`test_i03_ledger.py`](../tests/test_i03_ledger.py)) | the root commit stores column and network in one snapshot; the network is bound into the ledger identity; reopening in the same and in a new process restores it through its constructors; an edited store, root arrays of another type or not its own, another epoch or time, and an undeclared stock link are refused |
| Stationary and rigid rotation ([`test_i03_transfer.py`](../tests/test_i03_transfer.py)) | no row, no transfer, the same material bytes, no age reset; a vertex moved alone and with its plate lands on the same bits; total rotations compose in the stated order |
| D3 staged lune, plain and tilted | born area per ridge side `2R²·6.75°` and consumed area `2R²·13.5°` to relative 1e-12; formation intervals equal the accepted intervals; trajectory mean age 4.0 Myr against 4.2 Myr from present distance; source, sink and heat accounts close exactly; untouched faces keep their bytes |
| One plate between fixed neighbours | exact area, mass, volume and enthalpy balances; fixed neighbours and the locked boundary do not move; declared destination fractions are honoured exactly |
| Declared accretion fraction and oblique boundaries | with fractions 0.25, 0 and 1 the left side receives that share of the opening and the right side the rest, and a supply for a side that opens nothing is refused; zigzag boundaries oblique to the motion give the same lunes and exact balances, plain and tilted |
| Slow boundaries | rotations of 1e-4°, 1e-7° and 1e-10° balance within 1e-12 of the measured cells; inside the attachment band nothing moves and a declared supply or sink is refused; strips born a few metres wide ride on through later intervals |
| Small and coarse faces | polar triangles about 1 km and 11 m tall, below the resolution limit of R3-1: each step is either accepted with the right lunes and exact balances or refused as unresolved, never accepted wrongly, and at least one is accepted; a small overlap far from its chart centre is measured to the W01 small-area tolerance; the orientation of a tiny ring is decided at its own scale; cells too wide to share a chart that cannot overlap produce no row |
| Refusals | a missing rotation, closing ridge, opening trench, sliding transform, junction that would move relative to its plates, exhausted boundary cell, undeclared or mismatched supply and destination, and accounts that could not be stored exactly |
| Mesh change | merging, splitting and refining conserve every account exactly and keep cohort records; a mesh cannot move an interface or change a face's plate; malformed meshes and unused added vertices are refused |
| Prepared map and port codes | a map is reused only for identical geometry and motion; a forged row no longer closes; forged rows between faces that cannot overlap are refused although they close; rows that each pass the audit but together deliver pieces that miss an endpoint face are refused as an unresolved overlap; the three port refusals carry their codes |
| Clock, finite stock and continuation ([`test_i03_clock.py`](../tests/test_i03_clock.py)) | column steps, network step and stock transfers commit together or not at all; a cancelled commit prepares nothing and a clock is cancelled between intervals; idempotent replay, conflict on a changed replay, adoption of an interrupted write; a slow interval does not strand the history; births debit a finite stock once and exhaustion refuses the interval; another producer's transfer through the linked exteriors is refused at commit and on restore; edited pieces, vertices, rows, motion record, mesh identity and parent identity are refused at the head and inside the chain; save, reopen and continue in a new process reaches the uninterrupted state identity |
| Reference frames and the restored per-face check ([`test_i03_frames.py`](../tests/test_i03_frames.py); controls in [`cases/i03_controls_v2.json`](../cases/i03_controls_v2.json)) | Codex's path: a state holding a 55 m strip turned rigidly 20 times keeps every face within 1e-12 of its pieces after every interval, and the strip's measured area bit for bit; the strip is then renamed, merged into its neighbouring cell and split back, each with every exact account closing. A ridge vertex keeps its declared direction in its record's frame and is placed once from it. A forged rider whose pieces miss its area by 2e-12 is refused at the next interval, and a restored computed state with such a face is refused. The first four fail on the code before I03a-2. A strip whose corners are renamed to frozen copies, so that its ring starts at another vertex, keeps its measured area bit for bit. The others harden the new parts: the exact containment test gives the declared answer for a face inside, on the boundary, identical, across a notch (corners and edge middles inside) and disjoint; a ridge frame stored with the opposite quaternion sign is refused although it places every vertex on the same bits; a layout lacking a needed copy, or keeping a vertex anywhere but with its carrier, is refused; a declared state whose copy of one vertex is displaced is refused; a plate turning by less than the attachment band each interval, with no supply or sink, is refused within 12 intervals once its corners have moved beyond the band, and no copy lies more than the band plus 4 ε from its vertex before then; a ridge moving 1e-14 rad per interval relative to one side (the Part 1 conservation verifier's case) books that side's births once its motion exceeds the band, with every copy within the band plus 4 ε after every interval; a copy displaced 80 ε from its vertex is refused on issue and on restore, and one displaced 48 ε is accepted (C10); the last three fail on the code the verifier checked; restoration keeps the cause of a refusal (a memory limit stays a memory limit); and `verified` measures every face against its pieces |
| Thin-face bound ([`test_i03_thin_faces.py`](../tests/test_i03_thin_faces.py)) | the measured area of strips 55 m, 5.5 m and 0.55 m wide and of compact faces is within its derived bound of a 90-digit exact evaluation of the same binary64 numbers; `math.atan2` is within one unit in the last place over the fan's range (the platform assumption); two strips 3 m wide merge end to end, ride and split back with exact accounts, the merged face within its stored allowance; the same merge with one row enlarged by four times the bound is refused (the row loses its whole-face status, so this does not test the bound's size); annuli and rings with holes whose rows lie up to 16 ε off unit length are within the bound of their true area; a strip renamed after rides at 0.5°, 0.05° and 0.005° per interval gets a closure bound within 1e-12 of its area above 2.2e-4 rad of area over perimeter and within twice that in the flagged range. D7′: renames leave the allowance unchanged; above the range a renamed face, and a compact face merged from a thin strip, keep a zero allowance, and a rider forged 1.5e-12 off is refused; rows that leave out a sliver at every step are refused (at the eighth). A merge whose rows leave out a sliver of 4 E is refused by its closure, not by the later per-face check, so the size of the bound matters |
| Junction advance ([`test_i03_junctions.py`](../tests/test_i03_junctions.py)) | T-junctions persist for 20 intervals under three different poles where every record carries them to one point, plain and tilted; a northern hemisphere turning on the equator moves both junctions exactly by its rotation, keeps the old corners in the record behind, and is refused when a segment would shorten to zero at the predicted interval; the same history seen from rotated axes (the D3 definition) is accepted alike with positions equal within 2e-12 rad; one interval and two halves agree within 8 ε, and so do one interval and 4, 8 and 16 sub-intervals (C8); a motion about another axis at the poles of the three-plate world is refused by the residual above 1e-11; a ridge-side plate that slides along the line is refused naming option D1-c; lines that cross with sin ψ below 1/16 are refused (C4); a record end pole stored with the opposite sign is refused by `verified`; relative motion of 1e-4° per interval and frame rotations of 100° and 150° are accepted alike in both frames (C1 relative velocities, the junction's sign); two junctions slide on a line record of one segment; a far plate opening a ridge where every record carries the junction to one point is refused naming D1-c, at 1e-11° as at 2°; the historical v2 `ridge_on_a_trench` still refuses because X is outside its admitted ridge/trench end segments, not because transient handling is unimplemented; admissible D5 geometry is controlled in v4; a line of two carriers does not advance (C3); the line carrier's face ahead is reported as reshaped, not slid; a ridge carried by its moving plate ending on a carried line, with the other side locked to the line's carrier, slides until the next junction, and is accepted alike in fixed axes, D3 and with a moving carrier for strips 1–111 m wide, tilted and in halves; a ridge on the hemispheres' trench line slides until the vertex 30° along, plain and tilted, in D3 and in halves; the historical v2 `declared_vertex_ahead` refusal is superseded by v4 traversal controls; unsupported material-seam crossings still refuse; save, reopen in a new process and continue reaches the uninterrupted identity |
| Sliding transforms ([`test_i03_transforms.py`](../tests/test_i03_transforms.py)) | an exactly slip-parallel transform slides for three intervals: cells remap only into themselves or their neighbour along the slip, nothing crosses the trace or is born or consumed, plate areas hold within 1e-12 and riders keep their bytes; an exact slip along segments 2.2 km long is accepted in plain, tilted and D3-rotated axes; a pole 1e-6 rad off and a bent trace are refused with the port code `transform not slip-parallel`; without a declared carrier the I03a refusal and its wording stand; C6 is judged in total: a normal turn of 60 ε per interval is refused at the second interval, and a slip of 0.4 band per interval on a bent trace at the third; the historical degenerate-overlay refusal is superseded by exact recovery of significant lines/points-only intersections, with the unchanged trigger and fail-closed input/budget limits |
| Continuation and v1 records ([`test_i03_continuation.py`](../tests/test_i03_continuation.py)) | a ledger with migrating junctions, saved after two steps and continued by the clock in a new process, reaches the uninterrupted identity and restores on reopening; I03a's v1 state, network, material and step records are refused, not misread |
| Regional bridges ([`test_i03_bridges.py`](../tests/test_i03_bridges.py); controls in v3) | **Round 1.** A return relabelling material into another cohort is refused, and the redistribution keeps every cohort's exact amounts (B1). A return carried in its interval's Motion commits, restores from its record, and through the clock and a reopened ledger continues. A return for a face the interval cut, one read from another state, and a relabelled one are refused (B2). A holed face hands over its plan area without the hole; corner positions are handed over in the local frame; a map reports its plan-area departure and the motion it omits; the bridge holds on an evolved state, near a pole and in tilted axes; the finite-velocity refusal holds whatever the warning policy. **First round.** Extract then return unchanged gives the parent state itself; without a motion, velocities, forces and work are unknown. A redistribution between faces of two plates conserves every account exactly and leaves every outside piece's bytes. In four orientations the velocities are the same bytes in the sphere's axes, carried back by the frame within 2e-12 of their speed, equal to the rigid ω × r at each face's reference point and with no radial component. Refused with their codes: two regions sharing a face, a result for a state that has moved on, a result of another representation, one that does not conserve, and a footprint naming an unknown face. The I03.3 verifier's findings are fixed and tested: an extract is issued-only and read-only, and an altered one is refused as stale; non-finite velocities and a motion for another step are refused; negative mass and material without area are incompatible support; malformed inputs are refused; one region returned twice is refused. The three projection tests run after R3-5's approval: a map whose declared tolerance is below its distortion (two values) is refused and one above it admitted with its reported distortion `1 − cos ρ_max`; a footprint beyond the conditioned-chart limit is refused; a section along the motion is admitted, with no plan-view area, and one across it refused |
| Rotated coordinates and different meshes ([`test_i03_equivalence.py`](../tests/test_i03_equivalence.py), two of them expected failures; E1 and E2) | **E1, rotated coordinates:** the closed-sphere history through a ridge jump, plain and tilted, agrees face by face, plate by plate, cohort by cohort and account by account. The largest relative differences, re-measured on the final code, are 3.25e-14 (faces), 9.07e-15 (cohorts), 8.96e-15 (supplied accounts) and 2.2e-16 (plates), against 1e-12. Every face lies above the C7 range, an asserted precondition. (5.2e-14, quoted in the first handoff, came from code before the merged-plate continuation rule.) **E2, different meshes:** two intervals on sector6, on its nested refinement and on a non-nested mesh with the same plate boundaries agree in global totals, plate totals, named exterior transfers, per-trench consumed area and amounts, and born lunes against `2R²Δλ`. In the predeclared single-cohort-consumption class they also agree in cohort totals; its premise is checked from each step's own trench rows. Every face lies above the C7 range, an asserted precondition. The largest difference is 9.68e-15. **Outside the single-cohort class**, where consumed cells mix cohorts of different areal density, only consumed area is mesh-independent: consumed amounts, and so plate and global amounts, then depend on how the mesh mixes cohorts (the coordinator's probe: slab mass 33% apart). **Slow histories (S1):** the same comparisons at 1e-4° per interval, with thin faces (E1 in two rotated frames, E2 on both meshes), use the coordinator's aggregate bound, predeclared: `1e-12 × total + Σ C7` over the thin faces in the set, the larger side's C7, scaled for amounts by each face's piece share. Faces, plates, cohorts, births, the source and the lunes stay within it, using at most 17% of it. **The consumption accounts do not**: the trench area and the slab amounts differ by up to 2.35e-11 relative, 23.5 times their bound. Each interval's sweep is a thin sliver of about 11 m, measured in the step and not a face of either state, so the predeclared set gave it no term.
- **Ruling (the coordinator, 3 October 2026):** they stay declared failures, recorded as expected failures. Slow-history consumption accounts agree to between 1.07e-11 and 2.35e-11 relative, measured.
- **Repair, separately predeclared:** `consumption_sweep_c7_repair` in v3 applies the bound to the actual swept rings as well. The fresh rotated, refined and non-nested controls pass, using at most 1.192% of the declared bound. A perturbation beyond the bound refuses. Section 5 gives the measured quantity and amount-density propagation; the original two failures remain visible.
- **Rate and range:** that S1(b) control uses `2e-4°`, twice historical S1's `1e-4°`. Its sweeps must be in C7's thin range; the v4 sweep-repair controls separately exercise thin, transitional and out-of-range rings. Reported earlier results do not establish the status of the current repair checks.
- **Amounts:** the scaling of each thin face's term by its piece share is confirmed by the same ruling. |
| Joint geometry commits ([`test_i03_events.py`](../tests/test_i03_events.py)) | **Round 1.** Two splits of disjoint plates that cut one record are refused before anything is applied, naming it (V1). Where the plates' measured areas tie, the merged plate continues the larger exact account whatever the names. In the ridge-jump control the grown plate turns after the jump, and every vertex of the slice follows it, not A-east. **Splits and merges.** A meridian split, and a split across the plate that cuts the ridge and the trench it meets, divide whole faces: geometry, pieces and every exact account are unchanged, lineage and sides are as declared, and restoration is exact. A merge unites whole faces and retires the suture; after motion, every vertex stays within 2e-12 rad of where it was. **Ridge jump.** At the end of an interval in which the ridge spread, it captures its slice, retires the old ridge, and lets the new ridge spread in the next interval. **Order.** Two disjoint events give one state in either supplied order and either application order. **Refused with their causes:** a shared plate, a standalone retirement, a record ending inside the plate, plates moving apart, reused or retired identities, plates without a common record, an incomplete split, another basis. An event interval up to step 256 commits, and one past it is refused when declared. **Through I02:** a joint proposal whose component fails commits nothing, and the parent then accepts a valid interval. An identical replay is idempotent, a changed one conflicts, and a repeated application is refused. A later event is evaluated on the committed state: the cascade refuses the split of a plate already merged. A joint demand beyond a finite stock refuses the interval and its event, while one side from each stock commits. A closed-sphere history of three intervals with a ridge jump covers the sphere once in every state, and its source, birth, sink and heat accounts stay separate, each matching its lune, with the exact identity. Save, reopen and continue through the jump in a new process reaches the uninterrupted identity. **Time and capture:** an event whose time is not its interval's end is refused; the ridge jump's slice keeps its pieces' bytes and its place as moved with A, then stays put with its new, still plate. **The I03.4 verifier's findings, fixed with tests that failed first:** a mesh change with a split or a merge in one interval restores, and through a reopened ledger continues; a new record is accepted whatever its name; an event on a plate another event creates is one joint proposal; malformed events are refused; a merged plate continues the larger plate, or for a jump the plate across, even when that one is smaller, with a non-identity frame carried exactly; **D7″:** the jump after the reviewed slow control is accepted, every face measured again within its bound and its allowance the exact change added to what the check allowed before; with the bound forged one ulp below a face's change, the jump is refused, and at the change exactly accepted; a strip 3.9–5.3 km wide above the C7 range, measured again after a merge, is held to `4 ε P R²` with no C7 term; over two merges that each measure the same faces again, an allowance grows only at the merges, by each exact change, and rides and a split carry it unchanged |
| Execution identity ([`test_i03_identity.py`](../tests/test_i03_identity.py)) | the five I03 modules (`integration_sphere`, `integration_transfer`, `integration_bridges`, `integration_events`, `integration_junction_paths`) are in the package's source membership within its existing 512-file ceiling, and their source bytes and loaded code are part of the execution identity |

Current repair coverage is located in
[`test_i03_vertex_traversal.py`](../tests/test_i03_vertex_traversal.py)
(the transform/carried-ridge/trench traversal seam, and the named refusal of
D1-b at a D5 junction),
[`test_i03_junction_paths.py`](../tests/test_i03_junction_paths.py)
(generated curves, actual moving continuation, frames and replay),
[`test_i03_path_contract.py`](../tests/test_i03_path_contract.py)
(documented path gates, dyadic ceilings and existing edge limits), and
[`test_i03_transient.py`](../tests/test_i03_transient.py)
(same-interval birth/consumption, signed accounts and persistence).
These are coverage pointers, not a claim that final combined checks have passed.

These checks compare the code with exact geometry and with its own accounting
identities. They do not establish physically generated motion or events, geological
realism, regional accuracy, a planetary runtime, or behaviour on a platform other
than the one they were run on.

**Stage finish.** The integration plan's finish line for I03, item by item:
- **Exact rigid rotation and the stationary state:** `test_i03_transfer` (I03a).
- **One supplied ridge/source control:** the D3 lune, and one plate between fixed neighbours (I03a).
- **Shared-junction movement:** `test_i03_junctions` (I03a-2).
- **Source/sink accounts and a closed-sphere control:**
  - the D3 lune on its closed two-plate sphere (I03a);
  - the closed three-plate history through a ridge jump (I03b).
- **Save → reopen → continue with transfers:**
  - `test_i03_clock` and `test_i03_continuation`;
  - the continuation through a ridge jump (I03b).
- **Rotated coordinates and different meshes represent the same case within the declared bound:** `test_i03_equivalence`
  (I03b, E1 and E2 as approved).
  - **The class it holds for.** It is established for motion that is not small against the cells: every face above
    the C7 range, and on meshes, consumption that cannot mix cohorts. There every observed difference is at most
    3.25e-14, against 1e-12.
  - **Slow histories.** The original consumption checks remain historical expected failures
    (1.07e-11 to 2.35e-11 relative). Fresh controls including the actual sweeps' own
    predeclared uncertainty pass, as described above. Exact accounting and the strict
    per-trench row audit are unchanged.
  - I03a's tilted and D3-rotated histories exist besides.

## 11. Measured cost

**Bounded exact-fallback proposal comparison, 3 October 2026.** One sequential
before/after sample per size covered two moving intervals of the same three-plate
workload, using the same loaded geometry, inputs and default budget. This measured
the cap-reach/triangulation-reuse proposal against the prior geometry implementation;
it is not a workflow-timing receipt, a full-I03 measurement or a planetary scaling result.
The later junction-traversal changes do not exercise a different path in this
three-plate workload. Other CPU activity was possible.

| Latitude bands | Before, s | After, s | Exact pair calls, before → after |
| --- | --- | --- | --- |
| 48 | 2.3598282 | 1.7407953 | 4,802 → 662 |
| 96 | 4.0196066 | 4.0530363 | 0 → 0 |
| 192 | 17.0186592 | 11.5097252 | 37,249 → 3,445 |

Rows were bit-identical and state identities equal in each matched comparison.
The exact-pair workspace peak stayed 209,920 bytes where fallback ran; neither
96-band run needed it. The 96-band sample demonstrates no speed gain. These are
single matched observations, not a general speed-up estimate. The local proposal
record binds before-transfer source `6c0ce265ddd9e189…`, proposed source
`315e9eb4b1d55661…` and proposal `143ca753e642e60a…`; it does not certify the
subsequently integrated candidate or replace its required combined checks.

The delivery measurements below predate the repair/extension pass. They are retained
as measurements of that candidate, not refreshed speed claims for new geometry.
A one-shot repair comparison timed `advance` only, with state construction outside
the timed region: on the tilted 36-face case an ordinary 0.5-degree step took
69.619 ms before and 68.241 ms after; a 0.0001-degree step needing exact overlap
took 68.727 ms before and 74.305 ms after. The difficult step added 5.578 ms (8.1%).
One sample each cannot establish a meaningful ordinary-step speed-up. Exact accounts
held in both. This is precision-repair cost, not whole-planet performance.

The measurements below precede the resource-ownership correction described in
section 6. They are retained as the original candidate's measurements, not a fresh
timing or corrected-budget admission claim. In particular, the old caller-budget
figures omitted material reservations, and restoration omitted the step reservation.

Measured once, after the checks passed, on the development machine: Windows 11,
CPython 3.12.14, one process, timed without memory tracing. No receipt was captured;
these are working measurements, not evidence. Each size ran in two fresh processes,
and "cold" is the first repetition in a process and "warm" the second. The worlds are
the controls' three-plate sector world at four resolutions, with one ridge and one
trench running from pole to pole. They show how the cost scales. They are not a
planet.

| Faces | Build the network, s (cold / warm) | One interval, s (cold / warm) | Validating the endpoint network | Measuring rows | Audit and transfer | Restore one state, s |
| --- | --- | --- | --- | --- | --- | --- |
| 36 | 0.040 / 0.039 | 0.062 / 0.061 | 83% | 10% | 3% | 0.052 |
| 120 | 0.128 / 0.127 | 0.166 / 0.167 | 89% | 7% | 2% | 0.150 |
| 432 | 0.463 / 0.478 | 0.537 / 0.564 | 93% | 4% | 1% | 0.534 |
| 1,632 | 1.771 / 1.864 | 2.004 / 2.004 | 95% | 2% | 1% | 1.926 |

- **Time is linear in faces.** Building and checking a network takes about 1.1 ms
  per face, and one interval about 1.2 ms per endpoint face. Cold and warm differ by
  less than a tenth: nothing is cached between calls.
- **Validation is the cost.** Between 83% and 95% of an interval is rebuilding the
  endpoint network and checking it as a closed atlas, for every face including
  those that only rode with their plate. Measuring the overlap rows is 2–10% (about
  1.5 ms per subducting boundary cell), and auditing and applying them 1–3%. A
  prepared map therefore saves little: the same intervals from a prepared map took
  0.055, 0.154, 0.535 and 1.948 s.
- **Restoring costs the same as building.** Opening a ledger rebuilds the root
  network (0.04 s at 36 faces, 1.9 s at 1,632). `verify_chain` rebuilds every
  commit: 0.32, 0.78, 2.5 and 8.5 s for a root and four intervals.
- **Through the ledger and clock** an interval took 0.08–0.11 s starting from 36
  faces and 2.1–2.3 s starting from 1,632. The store write is 6–16 ms of that. The
  same clock step of the column alone takes about 0.01 s, so the network step is
  between 5 and 220 times the column's at these sizes.
- **Memory.** The work budget's reservation peaks at about 27 KiB per face while a
  network is built and 35 KiB per endpoint face during an interval (60 MiB at 1,700
  faces). Traced Python allocations peaked at 25 MiB there, and the process working
  set grew by 32 MiB. The default 256 MiB budget is enough to build a network of
  7,488 faces (197 MiB reserved) but not to move it (259 MiB): that interval was
  refused with a memory-limit error, and needs a larger declared budget.
- **Stored bytes.** Each interval stores the whole endpoint state: 210–260 bytes
  per face in arrays, plus about 11 kB of commit record, of which the step record
  is 7.8 kB here. The ledger file grew by 36, 60, 130 and 380 kB per interval at
  these sizes, against 6 kB per interval for the column alone.
- **A mesh change searches pairwise.** Replacing 8, 32, 128 and 512 faces of one
  plate (each split in two) took 0.011, 0.063, 0.42 and 3.8 s to measure, about
  2 ms per replaced face plus 11 µs per pair of replaced and new faces, and the
  network is validated twice besides.

**Forecast.** A network gains two faces per ridge segment and interval. With `F0`
faces, `s` ridge segments and `N` intervals it has `F0 + 2 s N` faces, so the time,
memory and stored bytes of one interval grow linearly with `N` and their totals
quadratically, until a mesh change merges the strips. From the figures above:

| Case | Faces at the end | Network steps in total | Stored in total |
| --- | --- | --- | --- |
| 1,632 faces, 34 ridge segments, 256 intervals, strips never merged | 19,040 | about 53 min | about 610 MB |
| the same with the face count held at 1,632 | 1,632 | about 8 min | about 100 MB |
| 100,000 faces, one interval | 100,000 | about 2 min | about 23 MB |

The last row would also need a declared budget of about 3.4 GiB. Replacing 10,000
faces of one plate in one mesh change would take about 18 minutes in its pairwise
search. Cohorts grow by one per opening ridge side and interval, and pieces by one
per born face, plus the pieces made where trench cells exchange cohorts with their
neighbours. These are extrapolations from four small sizes on one machine; no larger
case was run.

**I03a-2 (3 October 2026), on the same workload.** Each kernel was measured once, on a
quiet CPU, against I03a with the resource fix, one fresh process per tree and size.
Every kernel is 3–13% slower:

| Faces | One interval, warm |
| --- | --- |
| 36 | 0.060 → 0.067 s |
| 120 | 0.166 → 0.182 s |
| 432 | 0.536 → 0.580 s |
| 1,632 | 1.884 → 2.107 s |

Building, restoring and the mesh merge are 3–13% slower likewise. The causes are:
- the copy checks on issue and restore (C10);
- the per-face check after every interval;
- the per-triangle C7 bound for whole-face closures;
- placing every vertex from its frame.

A round-1 verifier, on a noisy CPU, measured the interval and restore at the upper end
of that range or slightly above it. The new kernels, a migrating T-junction, a
persisting three-pole junction and a sliding transform, cost 0.09–0.12 s per interval at
72–84 faces, in line with the three-plate interval at similar sizes. They were measured
before round 1's fixes and were not measured again.

**I03b (3 October 2026): bridges and events, on the same worlds.**
- **Setup.** One fresh process per size. The first repetition is cold and the second
  warm. Timed without memory tracing, on a quiet CPU, after the checks passed. These are
  working measurements, not evidence.
- **Footprint.** The latitude bands of one sector of plate A.
- **Return with an exchange.** One face of A exchanges halves with the face of the same
  band in B's first sector.
- **Event cost.** An event's cost is the difference from a still interval.

| Faces (footprint) | Extract, s | Extract with motion, s | Return unchanged, s | Return with exchange, s | Still interval, s | With one split, s | With one merge, s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 36 (4) | 0.0036 / 0.0029 | 0.0034 / 0.0033 | 0.0033 / 0.0033 | 0.0032 / 0.0032 | 0.046 / 0.045 | 0.127 / 0.126 | 0.129 / 0.124 |
| 120 (8) | 0.0085 / 0.0084 | 0.0093 / 0.0091 | 0.0092 / 0.0091 | 0.0093 / 0.0090 | 0.145 / 0.143 | 0.415 / 0.408 | 0.411 / 0.415 |
| 432 (16) | 0.029 / 0.029 | 0.030 / 0.030 | 0.031 / 0.031 | 0.031 / 0.031 | 0.509 / 0.514 | 1.492 / 1.492 | 1.481 / 1.480 |
| 1,632 (32) | 0.107 / 0.106 | 0.108 / 0.108 | 0.114 / 0.116 | 0.114 / 0.122 | 1.942 / 1.934 | 5.621 / 5.565 | 5.623 / 5.603 |

Measured on the final code. In these worlds no face is measured again (every frame is still the identity), so D7″
adds nothing here. Its cost is one bound per face an event measures again: twelve faces in the slow-control jump.

- **A bridge costs about one check of the state.**
  - Extracting and returning take about 66 µs per face of the whole network: almost
    all of it is `verified()` on the state.
  - The footprint's own work is small.
  - Cold and warm agree, because nothing is cached.
- **An event interval costs about 2.9 still intervals.**
  - Each event rebuilds and validates the network twice: once to find its junctions,
    once with its record-end poles. It then re-issues the material.
  - With more than one event, the two-order check applies the whole set again in
    reverse, so N events cost about 4N network builds.
  - The I03.4 verifier measured three splits at 648 faces at 11.3 s, against 0.78 s for
    a still interval.
  - A clock retry of a failed commit doubles that again.
- **Stored bytes.** A split of a 144-face plate at 432 faces adds 4.85 kB to the step
  record, about 34 bytes per face of the split plate, because its parts are named twice:
  in the motion record and in the step's event list. The stored arrays grow by 2 kB for
  the new plates and record.

## 12. Limits and what remains

- **Bridges carry whole columns and rigid velocities (I03.3).**
  - No law divides a column by depth, and a region receives each face's pieces as uniform: nothing is
    reconstructed inside a face.
  - The regional model's forces and work are not produced.
  - Velocities are rigid-plate motion from the supplied stage rotations, as a mean over the interval; a turn of more
    than π per interval must be divided.
  - A committed return performs fresh extraction on the actual parent, forcing and
    duration for all three representations, then checks exact support and material.
    In-memory `returned()` changes no interval. The constant-rate velocity port
    refuses every Motion with nonempty `junction_paths`, including constant-rate
    special cases; omitting motion permits material-only extraction only where the
    representation allows it.
  - The projection criteria are approved for this bridge. What a regional solver can absorb is still its own
    declaration (P2).
- **Events are supplied, whole-face and at interval ends (I03.4).**
  - A face measured again in another frame is admitted only within D7″'s bound (section 9). Its allowance grows by
    each event's exact change, so repeated re-expression loosens its per-face check a little each time: measured,
    from 0 to 6.7e-4 m² over two merges of a thin strip. A later mesh redraw or closure replaces the allowance, as
    D7′ says.
  - Where C7 is undefined, a thin face that changes beyond 1e-12 is still refused.
  - Record-end poles are not regrouped when a merge gives two collinear records one carrier: such a junction is
    seen as three lines and refused, where a fresh declaration might advance it. The verifier found no motion where
    this changes the outcome; it is conservative.
  - An event interval costs about 2.9 still intervals per event, and more than one event about 4N network builds
    (section 11).
  - A split follows existing edges and names its parts by face identity at the interval's end. A proposer reads the
    born faces' identities from a dry run of the interval; they are deterministic.
  - A split through faces needs a mesh change first, and an event between whole steps needs its interval divided.
  - Junction reorganisation, generated events and a standalone retirement are refused.
  - A merged plate continues one plate's frame and total rotation:
    - for a ridge jump, the plate across the old ridge;
    - otherwise the larger plate by its exact rational piece-area account, and on an exact tie the first in identity
      order. That is a convention: on an exact tie it depends on the names, and on a near tie the exact accounts
      themselves carry the rounding of the measures they were set from, so rotated axes may decide differently.
  - Two splits that cut the same record in one interval are refused; the second belongs to a later interval.
  - A regional return commits only where the interval carried its faces whole, and only for faces whose cohorts it
    conserves exactly.
  - A ridge jump's slice is captured at the instant, with no common-motion check.
  - Each event rebuilds and validates the network twice: once to find its junctions, and once with the new record-end
    poles (section 11).
- **Junction motion has explicit kinematic scope.** Admitted:
  - a junction every record carries to one point (any poles);
  - a junction where one through-going line, carried by one plate, meets one other record, sliding along the line
    while every other plate there is fixed to the line's carrier or subducts beneath it. That includes two
    ridge-ended classes:
    - a ridge carried by its moving plate, with its other side locked to the line's carrier;
    - a ridge on a trench line whose plates carry the junction to one point under three poles.

    These classes and the transform-through-line class have constructed D1-b
    traversal (R3-4): strict passes, exact landing and multiple degree-two sampling
    vertices use updated strip/sweep chains. D5 supplies and consumes the admitted
    transient regions at ridge/trench ends. D1-b is not constructed inside such a
    D5 triangle; passes that would subdivide it are refused (see Refused), while a
    pass outside it is admitted.
  - outward-growing all-ridge junctions with the explicit analytic path, common
    reference convention and curve-accuracy/segment limits of R3-4b.
    Bisection uses power-of-two segment counts within the declared ceiling;
    exact arcs still obey chart conditioning and the atlas's zero/antipodal edge
    limits. Unsupported whole-face geometry continues to refuse.

  Refused:
  - a general oblique junction whose future path is unspecified: instantaneous
    closure is not a unique future direction law;
  - corners of two single-record lines that would move;
  - a line of two carriers that would advance (C3, refused at the advance rather than at declaration);
  - a ridge-side plate sliding along the line outside the supported D5 material-edge
    intersection construction (general D1-c seam reorganisation is not inferred);
  - D5 intersections outside their admitted material segment or regions without a
    declared physical owner. Where a declared vertex that was not passed lies
    between the new junction and X, the refusal names it;
  - D1-b at a junction where a plate builds a D5 triangle: a pass of the vertex
    that ends the triangle's trench segment, or of a vertex at or between X and the
    new junction (R3-4), including a pass by the record's other junction. The refusal
    names this unconstructed case rather than a geometric or seam cause;
  - a D5 overriding-side subdivision that leaves an unpaired edge, including
    larger spreading outside the constructed case, refuses with that named cause;
    general seam reorganisation is not inferred;
  - contact with another real junction, exhausted cells or unsupported material-seam
    crossings. Those require a remesh or an admitted reorganisation, not deletion of
    material or a longer tolerance.
  - A slowly sliding ridge–trench–trench junction can be accepted in one interval and refused in two halves (round-1
    verifier: at relative rotations of about 1e-6°). The trench sweep beside the old corner left on the subducting
    frontage is then thinner than rounding, and becomes a bow-tie in its chart. This is a composition limit; it
    refuses, never accepts wrongly.

  The earlier claim that a hemisphere-shaped plate between two trench frontages covering the equator cannot hold a
  migrating junction was wrong (round-1 verifier): with a relative rotation normal to the plane through both junctions
  and the world axis, it can, and the hemispheres-slide control holds one. A future
  I04 producer must supply a supported trajectory or another explicit direction
  history where finite rotations alone do not close a junction. I03 now constructs
  the supported generated ends; it does not choose their physical evolution.
- **Transforms slide only when exactly slip-parallel.** A transform slides only when its far plate's relative pole is
  the pole of its trace's great circle, to the 64 ε band, and only when it declares its carrier. The history must
  keep that true in every interval: constant stage rotations about fixed axes turn the trace away from the relative
  pole. C6 is judged in total since declaration, so motion inside the band cannot add up, and a trace that is not
  one great circle admits no slip in total. C7's slip term for far-side closures is not built, so those closures keep
  the relative criterion. Far-side cells narrower than about 90 km may be refused as unresolved, because
  their rows close only to the slip's normal offset over their width. Under an exact slip the far cells are clipped
  rows, held to the relative tolerance, so whether thin far cells are accepted depends on the frame: in the Part 3
  verifier's probe the plain frame, where the equator's coordinates are exact, accepted cells 89 m wide that tilted
  axes refused, and tilted axes accepted 890 m cells for nine intervals. Shear builds up: on the control mesh a far
  cell's remap is refused as an unresolved overlap ("two faces share no conditioned hemisphere") after about 75° to
  80° of slip, although the moved network is still a valid tiling, because its old and new shapes no longer fit one
  conditioned chart. A mesh change before then avoids it.
- **Boundary cells bound the interval.** A trench cannot consume more in one
  interval than its subducting plate's boundary cells hold, and cells much thinner
  than the motion must be re-meshed first.
- **Thin and tiny faces can be refused when cut.** A face with area over perimeter
  below about 1.1e-4 rad (R3-1) that is cut at a trench, or by a mesh change that
  clips it, may not close to 1e-12 and is then refused as an unresolved overlap.
  The selective M3 trench fallback does not replace every receiver or mesh overlap.
  Such a refusal can still depend on the frame: the
  rounding of an added mesh vertex changes with the axes (Part 1 verification). Merges
  and splits of whole faces close under C7 down to strips 0.27 µm wide (round-1
  verifier), where one step's bound is about 5% of the face and the allowance it leaves
  about 10% (R3-1). D4's plain-against-tilted equality holds within C7's bound, not
  within 1e-12, for faces with area over perimeter below 1.1e-4 rad. One strip of
  I03a's 254-interval history differed by 1.18e-12 between plain and tilted axes,
  0.11 of its bound. Riding no longer widens the limit: since I03a-2 a face that rides
  keeps its coordinates and its measured area bit for bit (section 4). A rename, a
  merge into a compact neighbour and the split back close within the rounding of the
  compact measure, whatever the width (R3-1, whole faces).

  **Measured before and after I03a-2.** This is a scratch probe, not a control. In the
  three-plate history at 0.05°, 0.005°, 0.0005° and 0.00005° per interval, two strips
  born side by side on one side of the ridge in interval 1 ride for 10, 20, 40 and 80
  intervals and are then merged end to end. Each strip is about 2.65 km, 265 m, 27 m
  and 3 m wide; the whole opening per interval is twice that. Before I03a-2, a strip
  on the moving plate drifted from its pieces by up to `2.2e-12` at 2.65 km, and its
  merge was refused after 20 and 40 intervals (accepted after 10 and 80). At 265 m it
  drifted by up to `1.3e-11` and every merge was refused; at 27 m and 3 m every merge
  was refused, on both sides. After I03a-2 no strip drifted at all, and merges of
  2.65 km, 265 m and 27 m strips were accepted after every number of intervals, the
  merged face within `4.8e-13` of its pieces. Merges of 3 m strips (area over
  perimeter `2.1e-7` rad) are still refused there. The merged face's own measured
  area differs from the sum of its parts' measured areas by `1.2e-12`: the fan's
  evaluation error on a long, thin polygon, which C7 (approved after this part of the
  probe) now admits within its derived bound. Strips 26 km wide (0.5° per interval) stayed below `1.2e-13` before and
  were exact after. With C7, 3 m, 30 cm and 3 cm strips merge end to end after every
  number of rides; the merged face is within its stored allowance (`1.2e-12` to
  `5.8e-10` of its area, all rounding of its measure).
- **Very wide cells at a trench.** Two faces that do overlap but fit no common
  conditioned chart are refused. In a probe, subducting boundary cells up to 110°
  of longitude wide were moved and cells of 112° or more were refused, so a world
  of three equal sectors cannot be moved.
- **Numerical mixing at trenches.** Neighbouring boundary cells of a subducting
  plate exchange a small area each interval, because their side edges are redrawn as
  great-circle arcs to the moved trench. It is conservative and first order; cohort
  records stay intact, but the distribution of cohorts among neighbouring trench
  cells is not exact.
- **Rows at rounding level.** Two faces that only touch can measure a sliver at
  rounding level (a share near 1e-17), which becomes a row and can leave a face
  listing a cohort it holds only at that level. No cut-off is applied.
- **Relative motion inside the 64 ε band** moves no material in that interval.
  Since I03a-2 it accumulates: a plate's corner is its own copy, and a plate's copy of
  a vertex kept elsewhere is measured against that vertex's own placement (C10), so
  once the motion since it was placed exceeds the band the ridge opens or the trench
  consumes, and a supply or sink is then needed. This changes I03a's attachment rule
  under sub-band relative motion, which judged each interval alone; the coordinator
  accepted the change with C10. Between one and two band widths a trench can consume
  while the ridge on the same plate, whose sides each move half as far, still opens
  nothing; the accounts stay exact, and the plate's area changes by that sliver.
- **Applications of existing constants and approval status.** An existing constant
  does not automatically approve a new application. The listed repair applications
  were approved under the owner's 3 October 2026 instruction to fix everything, given
  after the review raised that distinction. Three were added after that instruction:
  the path sampler's chart-cosine subdivision, its emitted-edge resolution check, and
  the recovery of a degenerate overlay by the exact intersector. The owner approved
  those explicitly later on 3 October, on the coordinator's recommendation. This is not
  a claim of prior Claude/coordinator approval for the path extension.
  - the former trench balance's operand scale, `1e-12 × max(swept, cells)`, was
    removed during repair; section 5 uses the original `1e-12 × swept` with improved arithmetic;
  - the 64 ε band as the margin of the bounding-cap test before the exact
    containment test of whole-face rows (it decides nothing; R3-1);
  - the 64 ε band applied to a plate's own copy when deciding attachment (section 4);
  - the 120° limit on the pair forming a trace's circle, and the band test of whether a trace is one circle
    (`_trace_pole`), approved in the coordinator's 3 October round-1 addendum;
  - the unchanged relative tolerance against the larger projected face detects
    significant overlap omitted by a lines/points-only GEOS result. Such a pair
    now uses the bounded exact spherical intersector; unresolved operands refuse.
    A rounding-level empty overlay remains zero, and the same caller budget applies.
    This recovery supersedes the round-1 approved refusal, with the owner's explicit
    approval;
  - R3-4b's supplied analytic-tangent residual uses the named C1 `1e-11`, with a
    zero relative-speed scale refused; C4's `1/16` is certified over the whole
    interval by subtracting the derived normal-drift bounds, not checked only at
    sampled points;
  - the `64 ε` band is the minimum resolvable generated tangent norm and the
    exclusive lower bound on declared curve accuracy; `π/2` is the exclusive
    accuracy cap of this represented family, not a physical stability claim;
  - `common_reference_exponential_v1` is an explicit input convention, together
    with the retained `|J-C|<π` family bound and deterministic dyadic ceiling;
  - exact and curved emitted segments use the existing `1e-3` chart cosine and
    atlas angular resolution at zero and π. These are representation/admission
    uses, not changed physical tolerances. R3-4b gives their full derivations.

  C10's limit is evaluated in binary64, like the other band checks, so copies up to about 68.2 ε off in exact
  arithmetic were accepted by a round-1 verifier. The criteria approved for I03a-2 (C1, C3–C10) and the method changes M1–M6 are in
  the bounds proposal, its C10 addendum and the coordinator's approval of 3 October
  2026; Codex confirms them at review.
- **A plate's copy of a vertex kept elsewhere is tied to that vertex (C10, form a,
  approved 3 October 2026).** A copy is re-placed whenever it would lie more than the
  64 ε band from the vertex's own placement, and `|F_p·copy − F_home·reference|` is
  checked to be at most the band plus 4 ε on issue and on restore; the 4 ε is the
  rounding of two placements and one pull-back. This is an exact relation between
  stored values, not an authentication: a store rewritten consistently in other ways,
  with recomputed identities, stays inside the trusted-local-store boundary (section 3).
- **Stored and prepared rows are audited, not measured again.** The audit's
  conditions (section 5) are necessary, not sufficient. Rows changed consistently
  within them, for example by moving area around a cycle of neighbouring cells or
  by edits below 1e-12 of a face, together with the arrays and identities that
  depend on them, would be accepted. Detecting that needs the intersections
  measured again on restore, which this version avoids so that a restore does not
  depend on the platform's GEOS build.
- **Search is not sub-quadratic.** Changed faces are tested pairwise within a plate
  after a bounding-cap test. A mesh change that replaces every face of a large plate
  is quadratic in its face count.
- **Face count grows at ridges** by two faces per ridge segment and interval until a
  mesh change merges them.
- **Each commit stores the whole endpoint geometry and all pieces.** Unchanged
  arrays are shared by content address, but moved vertices are rewritten every
  interval. The step record also holds one entry per boundary and junction inside
  the commit's bounded JSON record (512 KiB in I02), which bounds a network at a
  few thousand junctions until those lists move into arrays.
- **The whole network is validated again every interval.** Section 11 measures it:
  rebuilding and checking the endpoint atlas is most of a step's time.
- **A clock request is not interrupted inside a network step.** The clock polls its
  cancellation between whole steps, as in I02.
- **One platform.** The checks were run on Windows with CPython 3.12.14 only. A
  restored step re-applies stored rows and does not depend on re-measuring an
  intersection, but a fresh computation on another platform or GEOS build may
  measure rows that differ in their last bits and so issue other identities.

## 13. Evidence effects

The two new modules and the edits to `integration_state.py`, `integration_ledger.py`
and `integration_clock.py` change the package's execution identity and the I02
catalogue identity. Receipts that bind those files describe the earlier source and
need successors captured from the accepted source; no existing receipt is edited.
I03a-2 changes `integration_sphere.py` and `integration_transfer.py` again, and adds a
test module and a case file. It edits none of the files that the I01 finite-admission
receipt binds (`integration_state.py`, `integration_ledger.py`, `integration_clock.py`,
`storage.py`, `materials.py`, `resources.py`, `_validation.py`, `timebase.py`); the
package's execution identity changes with it.
I03b adds:
- two modules, `integration_bridges.py` and `integration_events.py`;
- a test module for each, and a case file, `cases/i03_controls_v3.json`.

It edits:
- `integration_transfer.py`: the `events` field of `Motion`, its stored record, and the step that applies the events;
- `test_i03_identity.py`.

It again edits none of the eight files the I01 finite-admission receipt binds. The package's execution identity
changes with it.

The 3 October K1-K5 follow-up also changes `integration_ledger.py` to preserve an
explicit old-schema refusal cause. Its final bound source was recaptured as
[finite-admission r8](../evidence/i01-finite-admission-r8.json); all five bounded
controls passed, reusing unchanged finite-strain-r5 and column-admission-r3
prerequisites. [Workflow timing r9](../evidence/i02-workflow-timing-r9.json) renews
whole-package source bindings after the final transfer, path and bridge repairs;
its seven parity checks pass. Both predecessors remain unchanged and superseded.
The later N1 change to `integration_transfer.py` (the named D1-b/D5 refusal)
superseded timing r9 with [timing r10](../evidence/i02-workflow-timing-r10.json),
which also passes its seven checks; finite-admission r8 does not bind that file.
That column timing is not a measurement of spherical transfer speed. The exact
fallback comparison and its limitations are reported separately in section 11,
with controls in [test_i03_sweep_repair.py](../tests/test_i03_sweep_repair.py).

[Current evidence](../../docs/CURRENT_EVIDENCE.md) is the register of which records
are current.

## 14. Sources

The later K1–K5 documentation repair reuses the sources and reviewed derivations
listed below, together with the current implementation and v4 case declarations.
It consulted no new external literature and does not relabel retrospective controls
or old source reads as fresh evidence.

Consulted during the 3 October repair pass:

- Shewchuk's [author overview of adaptive robust predicates](https://www.cs.cmu.edu/~quake/robust.html),
  linked to his 1997 *Discrete & Computational Geometry* paper. It distinguishes exact
  determinant signs from inaccurate floating-point decisions and advocates paying for
  precision only where necessary. The overview was read, not the full paper; Atlas's
  targeted integer/decimal fallback is not his expansion-arithmetic implementation.
- [CGAL's exact-predicates/exact-constructions kernel reference](https://doc.cgal.org/latest/Kernel_23/classCGAL_1_1Exact__predicates__exact__constructions__kernel.html),
  for the distinction between deciding an intersection exactly and retaining its
  construction exactly. CGAL was neither installed nor benchmarked.
- Kritsikis et al.'s article abstract and the pyGPlates API overview were rechecked
  for conservative common-refinement and shared-topology scope. They do not supply
  an automatic physical law for the future direction of an oblique ridge.
- Lynch and Park's [Modern Robotics, exponential coordinates of rotation, section 3.2.3](https://modernrobotics.northwestern.edu/nu-gm-book-resource/3-2-3-exponential-coordinates-of-rotation-part-2-of-2/),
  official online transcript, was consulted for the supplied path's rotation
  exponential/logarithm convention. Its use here is kinematic; it is not a tectonic
  path-selection model. The chord-error and closure bounds above are derived for
  Atlas's explicit trace rather than attributed to that reference.

Newly consulted for this work:

- Kritsikis, E., Aechtner, M., Meurdesoif, Y. and Dubos, T. (2017). Conservative
  interpolation between general spherical meshes. *Geoscientific Model Development*
  10, 425–431. <https://gmd.copernicus.org/articles/10/425/2017/>. Sections 2–3
  read: the supermesh formulation and Eqs. 2–3, the pairwise intersection, the
  search for candidate cells and the cell-area calculation. Its second-order
  reconstruction, tree search and timings are not used here.
- Earth System Modeling Framework, *ESMF Reference Manual*, release 8.3.0, command
  line tools, sections 12.3–12.5.
  <https://earthsystemmodeling.org/docs/release/ESMF_8_3_0/ESMF_refdoc/node3.html>.
  Read for the meaning of conservative weights, great-circle cell edges and the
  normalisation of partly covered cells. ESMF was not installed or run.
- pyGPlates API reference, `FiniteRotation` and
  `ResolvedTopologicalSharedSubSegment`.
  <https://www.gplates.org/docs/pygplates/pygplates_reference>. Read for
  rotation equivalence and composition, shared sub-segments and subduction polarity.
  pyGPlates was not installed or run.

Inherited from existing Atlas contracts and methods, not re-read:

- [I01 physical contract](I01_PHYSICAL_CONTRACT.md), sections 1–3 and 5
  (`prescribed_history_v1`, product ownership, `atlas.spherical-cohort-transactions.v1`).
- [I01 transitions](I01_TRANSITIONS.md), sections 2 and 5
  (`atlas.event-transaction.v1`, `atlas.boundary-migration.v1` and its closure
  residual), and its case file `cases/i01_transitions_v1.json`.
- The D3 staged-lune control parameters in `cases/i01_closures_v1.json`.
- W01 [foundations](FOUNDATIONS.md): the closed spherical atlas, gnomonic charts and
  finite rotations; W02 conservative remapping.
- [I02 common state](I02_COMMON_STATE.md) and [I02 workflow](I02_WORKFLOW.md): the
  catalogue, the exact exchange accounts, the ledger, clock and store.

I03b consulted no new external source. It applies these, from existing Atlas code and contracts:
- `coordinates.LocalCartesianFrame`, the exact local frame;
- `regional_forcing`'s section rule and its 64 ε round-off;
- [I01 transitions](I01_TRANSITIONS.md), read again for this work:
  - section 2: simultaneous events, cascades and the ceiling;
  - its table of event types: split, merge, retirement, and a ridge jump as prescribed history.
