# I04: a declared starting family and plate driving on the evolving sphere

**WORKING NON-CANON. I04 reviewed, repaired and accepted for its declared reduced-model scope, 4 October 2026.**
- The coordinator's rulings on the decisions proposal (3 October 2026) are written in below. They approved the
  proposal with conditions and replaced the boundary-kind rule, first by F6 and then, after F6 proved degenerate
  on the development seeds, by F6′.
- **Part B (I04b), reviewed and repaired 4 October 2026: accepted within the documented scope and limits.** It adds
  I04.3, the material-dependent boundary response (D2 reduced belts on the sphere, R4-4), and I04.4, the first
  property/motion feedback (R4-7), under the coordinator's rulings on the I04b decisions proposal (approved with
  conditions; rulings 4, 7 and 12 replaced) and its mid-build ruling on a declared one-sided belt.
- [Current state](../../docs/CURRENT_STATE.md) owns delivery status. This page explains the method and what its
  checks establish.

This document covers
[I04 in the integration plan](INTEGRATION_PLAN.md#i04--causal-starting-world-and-motionboundary-producer):
- the port record shared with I05 (P0, [I04_I05_PORTS.md](I04_I05_PORTS.md));
- a declared family of starting states on I03's network, independent of sampling resolution (I04.1);
- the D1 torque balance on that network, driven by gravitational potential energy (GPE) from the same columns and
  datum as support, with slab pull declared or explicitly omitted (I04.2).

**The route is `d1_reduced_known_forcing_v1`:** a reduced force balance under authored, labelled forcing.
- It is not the contract's `coupled_generated_candidate_v1`, which "must remain unavailable as a completed generator
  while D2/D6 … lack their required physical closure".
- A D1-driven interval enters I03 as an ordinary `prescribed_history_v1` motion. Its I04 balance record is the only
  D1 provenance.
- Prescribed rotations remain a separate reference mode (UR-01).
- A balanced torque does not validate a force law or show realistic Earth motion.

## 1. What this adds, in generation order

1. **Declare the starting family**
   ([`integration_family.py`](../src/atlas_tectonics/integration_family.py)). From a seed and a scenario (radius,
   initial plate count, initial continental fraction, range), it builds:
   - continental and oceanic provinces as continuous spherical polygons;
   - columns, and geotherms applied once;
   - inherited weaknesses, initial slabs and unknown ocean-history masks;
   - a plate layout that consumes that structure;
   - one I03 network, its material at a chosen sampling level, and an initial I03 state.
2. **Hand columns to the driving balance** ([`integration_ports.py`](../src/atlas_tectonics/integration_ports.py)).
   P1 columns are evaluated at the plate-boundary trace points. Those are the only columns the rigid-plate GPE torque
   needs.
3. **Solve the plate torque balance** ([`integration_driving.py`](../src/atlas_tectonics/integration_driving.py)).
   - One `3P` system combines each plate's basal resistance, its GPE torque, a declared slab pull or omission, a
     rigid mantle rotation, labelled authored torques, and an optional linear interface resistance.
   - Reported separately:
     - every term;
     - the residual;
     - the power account;
     - the net rotation;
     - the motion carried by the plate-boundary GPE partition.
4. **Return motion.** The result is a P5 value, issued only from the solved balance and bound to its parent state,
   interval, network, frame, forcing and datum. The finite stage rotations for an I03 `Motion` are taken from that P5
   value, so their duration is its interval. I03 advances the network only within its supported kinematic
   classes.
5. **Resist motion at declared belts (Part B, I04.3;
   [`integration_strength.py`](../src/atlas_tectonics/integration_strength.py)).** A boundary declared to carry a
   reduced belt resists relative plate motion through the I01 weakening column (D2), evaluated on a line of belt cells
   normal to each trace edge from the P2 strength state. The belt adds its torques and their exact tangent to the D1
   balance, and returns raw-history increments (P6) and energies (P7) for I05 (R4-4).
6. **Couple motion and properties at the endpoint (Part B, I04.4;
   [`integration_feedback.py`](../src/atlas_tectonics/integration_feedback.py)).** One interval is solved implicitly
   at its endpoint: each iterate advances I03 and I05 with the current rotations and increments, re-evaluates P1/P2
   and D1 with the belts at the candidate endpoint, and repeats until both stop changing. The converged interval is an
   ordinary I02 commit whose `MovingAdvance` carries the D1/D2 provenance record, replayed on reopen (R4-7). P9
   returns the belt's boundary reaction for I07/I09.

   The starting family (step 1) is not yet the coupled route's input: I04b's controls run on the twin-hemisphere and
   lune fixtures, which I03 supports under D1 output.

## 2. Research decisions

### R4-1. D1 on changing spherical geometry

The equations are the selected law `atlas.plate-torque-resistance.v1` (I01 contract §3), unchanged:

```text
M_i omega_i + interface reactions = b_i
M_i = int_A D (|r|^2 I - r r^T) dA                         [N m s]
b_i = int_A r x (t_drive + D v_m) dA + oint r x f_drive dl  [N m]
```

**Exact second moments, with no quadrature.** Take a region of the unit sphere bounded by great-circle arcs
`a -> b`, with the region on the left and every arc **strictly shorter than pi**. Then:

```text
int n n^T dA = (2 A I - sum_edges (c s^T + s c^T))/6,  s = a + b,  c = ((b - a) x a)/(1 + a.b)
```

- **Derivation.** On the unit sphere, `Laplacian_s(n_i n_j) = 2 delta_ij - 6 n_i n_j`. Integrate this over the
  region and apply the divergence theorem. On a great-circle arc the outward conormal `nu` is constant, and
  `int_arc n ds = (a + b) tan(theta/2)`.
- **The exact rewrite** `tan(theta/2) nu = ((b - a) x a)/(1 + a.b)` (ruling A1.1). Writing `b x a` as
  `(b - a) x a` avoids cancellation on short and thin edges. Evaluated directly, the relative error grows like
  eps/A: 2.7e-8 on a face 1e-5 rad wide.
- **Area.** `A` is I03's own measured area of the face (`_measure`). `trace(S) = A` holds identically, and a face that
  only rides with its plate keeps its moment bit for bit. Faces are measured in plate-local coordinates and rotated
  into the sphere's axes as `F S F^T`.
- **Orientation guard per ring** (ruling A1.3): `(1/2) sum_e theta_e p_e . c_anchor`, with
  `p_e = (a x b)/|a x b|`.
  - It must be positive for the outer ring and negative for each hole. I03 stores holes clockwise, and the formula
    then applies unchanged.
  - A reversed ring refuses. Neither `trace(S) = A`, nor the octant diagonal, nor an eigenvalue range detects a
    reversed ring. The octant off-diagonals (+1/3) do.
- **Plate resistance.** A face with basal drag `D_f` contributes `D_f R^4 (A_f I - S_f)`. A plate's `M_i` is the sum
  over its faces.

**Rounding bound** (ruling A1.4, derived for this kernel). The analytic shapes keep the 1e-11 relative gate: the
octant, lunes of arcs shorter than pi, a hemisphere of at least 3 arcs or 4 octants, and the sphere, each compared as
a full matrix. Per-face comparisons instead use an absolute elementwise bound, derived as follows. Take `u = eps/2`
and follow one edge to first order:
- `d = b - a` is correctly rounded: `u|d|`.
- The cross product adds `6u|d|`.
- `q = 1 + a.b` carries `3u + uq`.
- Then `|x| = |d| cos(theta/2)` and `q = 2 cos^2(theta/2)`.
- The quotient, `s = a + b` and the outer product each add first-order terms.
- Symmetrising doubles them.
- Edge accumulation adds `(n_e - 1)u` per unit edge term.

So the edge sum `E` satisfies

```text
|dE| <= eps [ sum_e (7/cos(theta_e/2) + 1.5/cos^2(theta_e/2) + 4) |b - a| + (n_e + 1) sum_e |b - a| ]
|dS| <= C7(face)/3 + (|dE| + eps sum_e |b - a|)/6
```

- `C7` is I03's measure bound. If it is undefined, the comparison fails closed.
- Comparisons between perturbed inputs add `3.4 n_e delta`, the Lipschitz term of the same derivation, for vertex
  displacements `delta`. That covers rotated inputs, and I03's C10 band of `68 eps` between plate copies and shared
  positions.
- A rotation of `S` adds `6 eps |S|`.
- The edge part is verified exactly, against rational arithmetic on the same binary64 inputs, on 200 random faces
  from 1e-7 to 0.5 rad, including slivers.

**Interfaces** (ruling A2).
- The optional linear interface (a verification option) is `B = k R^3 (theta I - N_arc)`, assembled as
  `[[B, -B], [-B, B]]`, as in the I01 control.
- The arc moment `N_arc = int_arc n n^T ds` is
  `a a^T (theta/2 + sin 2theta/4) + t t^T (theta/2 - sin 2theta/4) + (a t^T + t a^T) sin^2(theta)/2`, with
  `t = unit((a x b) x a)`.

**Frame and nullspace.**
- Every plate needs `D > 0`, which makes `M` symmetric positive definite and anchors the declared mantle frame.
- The solve reproduces the retained gates:
  - symmetry within `1e-13`;
  - `lambda_min > 0`;
  - condition number at most `1e12`;
  - relative residual at most `1e-11`.
- An ill-conditioned or relative-only resistance refuses. Nothing removes a nullspace, and net rotation is never
  subtracted.

**Mantle forcing.** Part A admits only a declared rigid mantle rotation `omega_m`, whose term is `M_i omega_m`
exactly. A general mantle velocity field refuses as unsupported.

**Reported with every balance:**
- each force term per plate;
- the solve residual;
- the omitted terms, **per item**, each in its own list: every trench whose slab pull is the declared omission
  (`omitted_slabs`; with no slab term at all when every trench is omitted), every boundary without an interface
  coefficient or regional reaction (`omitted_interfaces`), and every plate without an authored torque
  (`unauthored_plates`). A missing force stays visible, never a silent zero;
- the label "explicit, single evaluation at the start of the interval; no temporal-accuracy or convergence claim";
- **power**, by the exact identity (ruling A5.3, form ii), evaluated per face and per interface edge, independently
  of the block matrix:
  `omega . tau_known = sum_f D_f int |v - v_m|^2 dA + sum_e k int |dv|^2 ds + sum_f D_f int (v - v_m) . v_m dA`.
  The last term is the power delivered into the mantle. `tau_known` is every applied torque except the mantle
  traction.
  - **Closure criterion (approved in rounds 1 and 2).** The reported closure is
    `|lhs - rhs| / max(|omega . tau_known|, basal + interface + |to mantle| + |omega . M omega_m|)`, held to the
    existing `1e-11`.
  - **Round 2** added the mantle-traction power `|omega . M omega_m|`, which the round-1 scale omitted. Exact balances
    with a mantle rotation and a small authored torque had reported closure up to 1e-2.
  - **Why this scale:** the rounding of a summed identity grows with the magnitudes of its terms, not with their net
    sum. An exact balance whose driving power is small next to the dissipation and mantle terms would otherwise
    appear to fail. Independent quadrature agrees to 3.1e-16.
  - **History:** this normalisation was introduced after a failing run. An independent verifier showed the earlier
    `|driving|` scale reporting up to 2e-8 for an exact balance. It is declared here as the criterion.
- **net rotation:** `omega_net = (sum_i J_i)^-1 sum_i J_i omega_i`, with `J_i = int_{P_i} (|r|^2 I - r r^T) dA`.
  This is the least-squares rotation of all plate motion; it is a diagnostic. It uses the sum, not `8 pi R^4/3`, so
  it is exact for any plate set (ruling A5.1).
- **the drag challenge:** `D -> 2D` halves `omega - omega_m` only when the interface coefficients double too, or when
  there are none (ruling A5.4).

**Ownership, frame and reuse.**
- A boundary receives a reduced interface resistance or a declared regional replacement, never both. Declaring both
  refuses (`double ownership`).
- The forcing is declared in the network's own axes.
  - A forcing that carries axis-dependent vectors (authored torques, a mantle rotation, regional reactions) must name
    the network's frame, or it refuses (round 2).
  - An axis-free forcing (drag, `L0/L`, slabs, `k`) may omit the frame. Any forcing that names another frame refuses.
- The mantle frame is those axes, kept only as a kinematic label, so P1 and P5 for one network carry the same frame.
- The assembled resistance is reused only under its full identity (the network, per-plate drag and interface
  coefficients). A mismatched one is refused (contract §9).

### R4-2. GPE on the sphere

The retained stencil ([I01_GPE.md](I01_GPE.md)) assumes "a smooth, resolved column field". This page uses an
equivalent boundary-integral form, which handles discontinuities explicitly.

**Identity.** For any field `U` on the sphere, `int_P r x grad_s U dA = oint_dP U (r x nu) ds`. Each `e_k x r` is a
divergence-free (Killing) field, so `(e_k x r).grad U = div(U e_k x r)`. The GPE torque on a rigid plate therefore
depends only on `U` along its boundary. Jumps inside the plate are included exactly, as distributions.

**Discretisation** (ruling A3.1).
- On a great-circle edge, `int (r x nu) ds = R^2 (b - a)` for an edge counter-clockwise about the plate, because
  `n x nu = dn/ds`. No `tan` or conormal is evaluated.
- With `U_e` the column anomaly at the edge midpoint, the traction `-(L0/L) grad_s U` gives
  `-(L0/L) R^2 U_e (b - a)` on the edge's left plate. It gives the opposite on the right plate, for which the edge
  runs clockwise.
- A uniform field gives zero torque on every plate up to rounding, because the sum telescopes.
- `U` is the anomaly from the reproduced I01 column kernel (`g[q - m^2/(2 rm)]`) at one shared datum, the D5 datum.
  There is no separate ridge push.

**Plate-boundary trace** (ruling A3.2).
- The trace is `U_L + w (U_R - U_L)` with `w = 1/2`: the **symmetric partition, a declared convention**.
- **Justification:** it is the limit of a regularisation that is even about the plate boundary itself. A
  regularisation centred off the boundary gives any `w` in (0, 1), so no stronger claim is made.
- A single-valued trace makes the two sides' contributions cancel exactly. The lithosphere's internal GPE torques
  then sum to zero, where one-sided traces would leave the jump unowned.

**Published sensitivity** (rulings A3.3 and A3.4). Each boundary reports
`J_b = dtau_L/dw = -(L0/L) R^2 sum_e (U_R - U_L)(b - a)`, with `nu_L` the left plate's outward conormal; `tau_R`
changes by `-J_b`. Without D2 belts, the exact half-unit partition response is
`delta_omega_b = M^-1 (J_b on L, -J_b on R)/2`, from one back-solve.
With belts, the diagnostic instead uses the converged tangent `M + J_belt`, already
calculated by Newton. Its `partition_motion_evaluation` labels a local linearisation
with material held fixed, scaled to a half-unit partition perturbation, not a solution
at that finite new partition. The peak speed is `max |delta_omega| R` in either case.
If any belt is at rest, a finite tangent is unsupported and the diagnostic is explicitly
unavailable; this does not invalidate the production balance or its zero-motion solution.
The regression uses genuine nonlinear belts and central partition perturbations with
the existing tangent-check tolerance. Neither the production equations nor their
converged velocity changed in this repair.

In the reviewers' check, `|J_b|` reached twice a plate's whole GPE torque, so torque alone understates it. Rigid-plate
torques at weak or broken boundaries receive `V` through the same trace, which answers `I01_WATER_GPE.md` §11 and
`I01_ELASTIC_CORE.md` §11 for Part A. The boundary's reduced or regional mechanics owns only the deviatoric reaction.

**Order and the exact control** (ruling A4).
- With `N` equal edges on the equator and the I01 field `h^2 = h0^2 + A n_x`, the per-edge sums give
  `torque_y = -(L0/L) c pi R^2 sin(pi/N)/(pi/N)`. The constant part sums to zero.
- The relative error `1 - sin(pi/N)/(pi/N)` is the I01 stencil's own error formula with `delta = pi/(8 order)`.
- `N = 32, 64, 128` therefore reproduces the `i01-gpe-r1` errors, and the existing `<1e-3` and `(3.8, 4.2)` gates
  apply unchanged.
- The control keeps the I01 control's `alpha = 0` and uniform 1000 K, recorded in the case file.

**Water.**
- Dry columns come first.
- Water-loaded traces are admitted only in the zero-rigidity (Airy) regime, as the dry kernel with water appended as a
  top layer (`rho_w`, `alpha = 0`, `T_ref`). This is exactly `I01_WATER_GPE`'s structural limit.
- Water depths come only from a declared source: in Part A, a labelled test input. Rock lighter than water is refused.
- **Finite rigidity refuses:**
  - without a declared elastic core, by MC-07;
  - with one, because no spherical flexure producer exists yet (I08).

### R4-3. Slab pull and mantle forcing in the first controls

These are owner-level choices, decided by the coordinator for Part A.
- **Known-forcing controls** declare the slab-pull omission explicitly, as the reduced omission.
  - It is recorded per trench in the balance's `omitted_slabs`. When every trench is omitted there is no slab term,
    and `slab_pull` is not in the forcing's whole-term `omitted` list.
  - One convention applies to every omission. The forcing's `omitted` list names only terms omitted as a whole (a
    network with no trench declares `slab_pull` there). Each per-item omission is recorded in the balance in its own
    list: trenches in `omitted_slabs`, boundaries in `omitted_interfaces`, and plates without an authored torque in
    `unauthored_plates`.
- **One control includes attached-slab pull** from a declared initial slab (a labelled test input):
  - The line force is `f = C g S n` (N/m), with `S = int (rho_slab - rho_m) dA_section > 0` (kg/m) for a dense slab.
  - With each trench edge ordered counter-clockwise about the **subducting** plate (ruling A5.2), the torque per edge
    is exactly `C g S R^2 (b - a)`, and the plate moves toward the trench.
- **Refusals:**
  - A trench with neither a slab nor a declared omission refuses (`missing force`).
  - A slab on a boundary that is not a trench refuses.
- There is no universal slab length.

### R4-4. D2 on the sphere

**Part B (I04.3), route `atlas.nonlocal-weakening-candidate.v1` with the reduced belt `atlas.i04-reduced-belt.v1`**
([`integration_strength.py`](../src/atlas_tectonics/integration_strength.py)). D2 is the I01 weakening method
([I01_WEAKENING.md](I01_WEAKENING.md)): plane-strain Drucker–Prager plasticity with a plastic viscosity, the layered
creep laws, and strain weakening from a nonlocal history `kappa_bar`. Here it is evaluated on the I03 sphere for each
boundary that a `Declaration` names, and it returns forces to D1 and history increments to I05. The coordinator's
rulings B1–B5 (4 October 2026) and the mid-build ruling on `Belt.side` are written in below.

**Inputs.** The I05 moving state's P2 at the evaluated state (temperature, the lithostatic vertical stress at each
sublayer's top and bottom, pore pressure, material and creep-law IDs, raw `kappa`); a `Declaration` per belted
boundary: the physical width `w` and the D2 length `ell`, each with provenance, the healing law (only
`atlas.i04-healing-none.v1`), and the side (`both`, or `left`/`right`); per layer a `BeltMaterial` (cohesion, friction,
plastic viscosity, grain size, weakening interval and factors, yield convention, source) and a `CreepLaw`; the Gauss
order per layer.

1. **The belt line.** At each trace edge the belt is the normal great-circle segment through the edge's midpoint:
   `y` in `[-w/2, w/2]`, or `y` in `[0, w]` wholly within one plate's margin when a side is declared. It is walked face
   by face with exact great-circle intersections; each crossed face's piece is a belt cell of length `dy`. `w` is a
   declared physical shear-zone width, never derived. Refusals: a line that re-crosses any trace (`unresolved belt`,
   `trace`); a half-width reaching a quarter of the sphere.
2. **The column of each cell** is the I01 lithostatic column built from P2. Layer densities are `(sigma_bottom -
   sigma_top)/(g t)`, checked against P2's stresses to `4 n eps sigma`. Materials, creep laws and weakening factors
   come from the declaration. Only the I01 plane-strain-matched Drucker–Prager convention (`C cos phi + P sin phi` on
   the invariant, `atlas.i01-plane-strain-drucker-prager.v1`) is admitted; any other `yield_convention` refuses
   `unsupported`. A crossed face's pieces must carry bitwise-identical P2 content (never grouped within a tolerance).
   P2 must lie on the evaluated state's piece support and come from the moving state whose bonds are read; at an
   endpoint its header must name the interval's parent and interval (otherwise `stale identity`).
   A belt cohort whose bond is BROKEN refuses `unsupported` (broken-surface sliding has zero cohesion; treating it as
   intact would be implicit rewelding, IN-04); UNRESOLVED bonds are reported. D2 never changes a bond latch.
3. **Oblique closure.** In a cell with normal rate `a` and shear rate `g` the invariant is `e = sqrt(a^2 + g^2)` and
   the obliquity `c = a/e`. The yield pressure is `P = sigma_v - c s`, so `_integration_weakening`'s pure-shear
   closure is reused with its sign replaced by `c`. This is exact at `c` in `{-1, 0, 1}` (checked bit for bit against
   the package solve at `c = +-1`, and against the supplied-pressure column at `c = 0`). For `0 < |c| < 1` it is the
   declared Lode-angle-free approximation, labelled.
4. **Series reduction.** Under thin-sheet equilibrium the cells are in series: series equilibrium plus an isotropic
   flow rule force one shared obliquity `c` and one shared deviatoric resultant `S`, whatever the rheology (the
   coordinator's checkers confirmed this with a two-cell general solve, `c1 = c2 = 0.8` to `1e-16`). With the velocity
   jump `dv` across the edge, `U = sqrt(dv_n^2 + (dv_t/2)^2)` and `c = dv_n/U`, the scalar equation `sum_k dy_k
   e_k(S; c) = U` fixes `S` (Newton in `ln S`, stopping at `|d ln S| <= 2e-11`, the kernel's rate tolerance; brackets in
   factor-2 steps). The traction on the left plate is `f = (S/U) A dv` with `A = 2 nu nu^T + t t^T/2`, and the power
   is `f . dv = 2 S U`. `U = 0` is the continuous zero limit: `f = 0`, `S = 0`, no increment, and no kernel call
   (`c = 0/0` is never formed).
5. **Nonlocal history.** `kappa_bar - ell^2 kappa_bar'' = kappa` on the belt line, cell-centred finite volumes with
   zero flux at the belt's ends, at each Gauss depth. It is well balanced (a uniform history stays exactly uniform on
   unequal cells) and second order (the closures check's 40/80/160-cell ratio window). Raw `kappa` is never written.
   A Gauss depth below the base of any crossed cell refuses `unresolved belt` (`depth`): `kappa_j(z)` is then
   undefined and is not extrapolated. Sublayer membership uses half-open depth intervals, so the rule passes only for
   pieces of one cohort or of identical declarations; belts between differently layered cohorts (ridge births, trench
   belts) refuse by name.
6. **The exact tangent.** `dS/dU` and `dS/dc` at fixed `U` come from the same kernel terms: per point, `d(total)/dc =
   s V/(R T) (scaled creep) + s sin(phi) inv` where the point yields with positive effective pressure, and in series
   `dS/dc|U = -(sum dy de_k/dc|S)/(sum dy de_k/dS)`. The traction tangent `df/d(dv)` is non-symmetric wherever
   `dS/dc` is not zero (ruling C1(1)).
7. **Coverage and labels.** The line quadrature deposits each cell into its piece with weight `dy L_e / A`. Per face,
   `beta = sum dy L_e / A_face`. The tolerance for `beta = 1` is derived from the face geometry before any test:
   `(1/cos h - 1) + sum over the face's edges of L R (the edge's great-circle excess beyond its endpoints' distance
   from the trace)/A + 1e-12`, with `h = w/2R` (both sides) or `w/R` (one side). (The bulge term was re-derived on 4
   October 2026 after a 1.15% bulge of a south row was found while checking a case, before any criterion test ran; the
   first form counted only the excess beyond `w/2`.) `beta > 1 + tol` refuses `unresolved belt`, as does a face of the
   belt's plate within `h` of the trace that no line crosses. For a one-sided belt,
   that missed-face check also requires the face centre to lie on the declared
   geometric side of the directed trace (using the existing attachment band).
   Plate identity alone is insufficient where a plate wraps around a ridge/transform
   corner. The point-to-arc endpoint caps and beta tolerance are unchanged.
   `beta < 1 - tol` labels the whole coupled result COARSE
   (a diluted line-quadrature deposit, persisted and inherited). The deposit is a line quadrature, not a consistent
   finite-volume discretisation; orientation independence is claimed only for aligned belts with `beta` within its
   tolerance and is withdrawn on non-aligned production meshes (no exact piece–strip overlap deposit is implemented).
   Every result carries "thin-sheet validity not established (I01_WEAKENING §8); reduced-model numerical claim only";
   `0 < |c| < 1` adds the Lode label (classified with a 64 eps band, labels only); a side other than `both` adds
   "declared one-sided shear-zone placement (I03 cannot carry history in sheared non-carrier rows)".
8. **Products for I05.** Per piece and sublayer, the raw-history increment is the sublayer mean of `2 dt e_p` at the
   Gauss points (the depth discretisation of raw history; the sublayer count is reported), deposited by `dy L_e/A` and
   checked against `0 <= dkappa <= sum (dy L_e/A) 2 dt e_k (1 + 2e-11 + 4 eps)`. Creep and plastic energies (J/m³) come
   from the same integration. Deeper sublayers that only creep do not weaken.
9. **Reports.** Per boundary: dissipation as `f . dv L` and as column work, peak resultant, plastic share, the `c`
   and `beta` ranges, resolution, `w/H`, the raw-history width over `H` (the closures metric `2 sqrt(second moment)`
   applied to raw `kappa`, so mostly the inherited profile: a uniform belt gives the mesh's uniform-profile second
   moment, `w/2` with one row per side, whatever `kappa0` or the response), the localisation width of the interval's
   increment (the same metric on the depth-mean plastic rate, as the closures tool applies it to history grown from
   zero; reported, not gated), the within-belt GPE omission ratio `max_k |int sigma_v,k dz - mean| / S` (the series
   equates deviatoric resultants only), the `U` residual, unresolved bonds, and the side. Per edge, the symmetric
   tangent margins (reported, not gated).
10. **Events.** None is admitted. A fully yielded opening belt reports the CM-07 separation refusal and a closing one
    the CM-11 initiation refusal; a transform (`|c|` within the same 64 eps band as the Lode label) suggests no event.
    Nothing edits the network (rulings P4, I04.4 events below).
11. **Rate support.** The column kernel's rate support sets a floor on the belt's relative speed: the layered belt
    refuses below about 0.06 mm/yr and the single-layer belt below about 6.3 mm/yr (measured by the coordinator's
    review). These are nonzero-rate support limits. Exact zero forcing retains the
    zero-motion limit; its finite local tangent diagnostic is unavailable, not
    represented as a zero derivative.

**What the reduced belt means at ridges.** I03 accommodates opening by accreting birth columns, while the belt resists
it as pure-shear stretching of fixed columns. That is what the reduced representation means, not necking.

**Predeclared refusals (fixed before running, `i04_controls_v1.json` part_b).** Normal belts in multi-interval
feedback (the cumulative strain guard or `unresolved column`); convergent belts with the I01 weakening-case dry olivine
(the monotonicity check inside the inherited bracket search at `c = -1`, which fires at rates the search visits,
not at the root; never relaxed); three plates with belts (the uncarried B|C
transform once D1 drags B and C unequally); a locked belt whose rates leave the kernel's support. Found by the
feasibility probes and added before any control ran: the symmetric belt on the twin transform at interval 2
(`unresolved column`), and ridge belts at the first coupled interval (`unresolved belt`, beta aliasing on a birth
strip; section 5, Part B results).

### R4-5. Material inputs versus scenario assumptions

| Coefficient | Class | Part A value and status |
| --- | --- | --- |
| Crust reference density | material input (library) | basalt 2650, gabbro 2950, granite 2650 kg/m³ (`material_library`) |
| Lithospheric-mantle reference density | **derived** (ruling P6.1) | `rho_ref = rho_m/(1 - alpha (T_base - T_ref)) = 3431.8 kg/m³`, with the datum's `rho_m = 3300 kg/m³` at `T_ref = 293.15 K` and `T_base = 1573.15 K`. This avoids a density jump at the base of the lithosphere: library peridotite at 3190 would flip the sign of thermal-root buoyancy and make slabs buoyant. A compositional jump is allowed only as an explicit, provenanced assumption |
| Thermal expansivity | material input with **no admissible library value** (the library has only 20–100 °C secants, none for peridotite) | `3.0e-5 /K`, labelled "scenario assumption; the library has no admissible instantaneous expansivity". Inherited citation: `i01_transitions_v1.json` attributes 3e-5 to Clennett et al. (2023) Table S1. It is a standard value, not newly read. The 0.1 anomaly cap still refuses beyond support |
| Conductivity, heat production (continental geotherm) | material inputs; heat production missing | the existing New World scenario values `k = (2.5, 2.5, 3.3)`, `H = (1e-6, .25e-6, .02e-6)` |
| Ocean thermal model | material and scenario | the existing `ocean_profile` (kappa 1e-6, k 3.3, 273.15 K to 1573.15 K) |
| Seed, radius, plate count, continental fraction, epoch | scenario (IN-01) | exact starting controls |
| Inherited ages, assumed thermal ages, weaknesses, initial slabs, `omega_m` | scenario (IN-02) | sampled by the family, or authored in controls, each with an origin |
| `D = eta_a/H_a`, `L0/L`, interface `k_ij` | scenario (IN-03) | the I01 control values: `D` 6.25e14 and 6e14 Pa s/m, `L0/L` 1, `k` 1e21 Pa s. Authored, not Earth calibration |
| Slab transmission `C` and section anomaly `S` | scenario (IN-02/IN-03) | **new authored values** for the slab control: `C = 1` (no reduction, the upper limit; its challenge moves it to 0.5) and `S = 2e12 kg/m` |
| Datum, water | scenario (IN-07) and the D5 owner | the I01 GPE case datum; water depths only as labelled test inputs |

**Declared v1 limitation: one datum for families** (round-2 decision).
- v1 starting families exist only on the 3300 kg/m³ / 293.15 K datum. Their slabs, columns and I03 material are all
  built on it.
- `family_columns` requires both `mantle_density_kg_m3 == 3300` and `reference_temperature_k == 293.15` exactly. Any
  other datum is refused (`stale identity`, `datum_id`), never rebuilt.
- So a twin datum with a different `T_ref`, whose derived mantle-lid density happens to agree, cannot silently
  reinterpret the crust densities.
- The D1 kernel itself takes any valid datum; only the family columns are limited. Adding a datum to the family
  request is a later follow-up.

**Source (newly consulted, 3 October 2026).** The relevant methods of
[Clennett et al. (2023)](https://www.nature.com/articles/s41598-023-37117-w) were consulted through the publisher page:
the slab pull, GPE, mantle drag and residual torque equations (Eqs. 1, 4–8). Supplementary Table S1 and the authors'
code were not obtained.
- **Not adopted:** their fitted Earth coefficients (C ≈ 0.2–0.25, D ≈ 6.4e14 Pa s/m, a 700 km slab length), and their
  present-day residual as a pass threshold. That residual follows from fitting to observed motion.
- **Contrast:** the paper reports no discretisation convergence check. Here, exact controls (section 4) bound the
  residual's numerical part, so an omitted force can be told apart from numerical imbalance.

### R4-6. The declared starting family

See section 3.

### R4-7. First feedback coupling

Part A is an explicit start-of-interval evaluation (port record D-P3).

**Part B (I04.4), route `d1d2_endpoint_fixed_point_v1`**
([`integration_feedback.py`](../src/atlas_tectonics/integration_feedback.py), with the belt solve inside
[`integration_driving.py`](../src/atlas_tectonics/integration_driving.py)); coordinator rulings C1–C3 and P1–P7.

**Inputs.** The accepted parent state `S0` and its moving state; the D1 `Forcing` (which names the belted boundaries,
exclusively owned against interface `k` and regional reactions); the D2 `Declaration`; the shared datum; an I03
template holding only supplies and sinks (a mesh replacement is not replayable from a commit in v1 and refuses by
name); I05 births and conduction; and the parent interval, either the CoupledInterval this process produced for it or
the Verified record of the parent commit (never a caller's record). **Outputs.** The interval's `Motion` and
`MovingAdvance` (with the `driving` record) for an ordinary I02 commit, the endpoint balance, the coupled P5, P6, P7,
P9 and a coupling report.

1. **Predictor.** D1 with the belts at `S0` by the inner solve, warm-started from the parent interval's committed
   omega (the first interval starts from the belt-free balance). Its omega is the first iterate `omega^0`; its balance
   identity is recorded (`start_balance_id`) and replayed.
2. **Iterate `k`.** I03 advances from `S0` with `omega^k`, the rotations taken only from the coupled P5 through the
   bound helper; I05 commits `dkappa^k` through its two-pass split flow (sub-cohorts named by a pure function of
   cohort, increment and interval). That gives the candidate endpoint `E^k`.
3. **Endpoint balance.** P1 (when GPE is on) and P2 are evaluated at `E^k`; D1 with the belts is solved there,
   warm-started from `omega^k`. The same integration gives `omega^(k+1)`, `dkappa^(k+1)` and the energies.
4. **Inner solve.** `M omega = b + tau_belt(omega)` by Newton on omega with the exact tangent: each step solves
   `(M + J) d = -R` by a general solve whose SVD condition must stay at or below `1e12`. Stop at the relative residual
   `||M omega - b - tau||_2 / max(||M omega||, ||b||, ||tau||) <= 1e-10`, with the relative omega increment at most
   `1e-10` or `cond(M + J) 1e-10 <= 1e-9`, else `unresolved inner solve`. Backtracking halves a step at most 64 times,
   inside a 96-iteration cap (the halving cap refuses `nonconverged balance` with detail `halvings`); a trial outside
   the kernel's support is halved, except a tangent that is not representable near `U = 0`, which refuses by name
   (detail `tangent`); a singular or ill-conditioned `M + J` refuses. At the accepted solution the symmetric
   part of `M + J` must be positive semidefinite, else `non-monotone belt response`. Zero forcing returns `omega = 0`
   exactly, with the belt evaluated there at `U = 0` (no kernel call).
5. **Power.** The belt's dissipation and column work are booked on their own lines; the closure bound is derived
   from the solve hierarchy: inner residual `1e-10` + the belt's `U` residual + the kernel's work partition `4e-11`
   (ruling C2(3)). Regional-reaction work has its own line, outside the driving power.
6. **Outer convergence.** Relative changes of omega and of `dkappa` (on pass-1 keys) at or below `1e-8`, cap 40 (the
   regional-strength Picard precedent). It refuses `nonconverged coupling` when the change grows in two consecutive
   iterates after the second. (At return every earlier change exceeded `1e-8`, so the last contraction is below 1 by
   construction; there is no separate `rho >= 1` refusal.) The committed iterate's error is estimated as
   `Delta/(1 - rho)`.
   A changed endpoint support between iterates refuses `unresolved endpoint support` (increments are never
   remapped). Nothing is committed on refusal.
7. **Cumulative small strain.** Per boundary, `E_b = sum over intervals of max_k |a_k| dt` (`a_k = c e_k`) is carried
   in the driving record and inherited only from the parent interval's own record; an interval taking it above the
   unchanged I01 guard `0.05` refuses `unsupported` before commit (ruling B4). A transform (`c = 0`) adds zero to
   rounding. **P7 closure:** the energies booked per piece and sublayer (`E_l t_l A`) must equal the belt's column work
   over the interval within the derived bound (the belt's `U` residual + the kernel's partition `4e-11`), else
   `nonconverged coupling` (`p7 closure`).
8. **Heat.** v1 converts no dissipation to heat. Per interval and per piece the pointwise adiabatic bound `dT <=
   max_l E_l/(rho_l cp_l t_l A)` of the omitted energy is recorded (`heat_omission.per_piece_k`), with its maximum and
   the cumulative sum of maxima, beside I05's declared lateral-omission allowance when lateral heat is omitted. The
   temperatures of any state after a D1/D2 interval are labelled by `omission_labels` (HEAT_OMITTED, the cumulative
   bound and the lateral allowance) (ruling P4). The label is carried by the history, not inside I05's arrays.
9. **Provenance.** The `driving` record holds the applied P5, the start and endpoint balances, the forcing and
   declaration records, the coupling report, the labels, the cumulative strain and heat bound, the P6/P7/P9
   identities, and the digest of the parent interval's record (`parent_driving_sha256`).
   - **On a ledger** (round 1, rulings P1 and P2(e)): `step(ledger, inputs)` reads the head commit's own record,
     replays it (or accepts the Verified value `commit` returned for that head) and inherits from it; `commit(ledger,
     coupled)` binds the interval to the ledger's next interval field by field and requires the record to inherit
     from the head's record, before writing. I05 checks the record's parent, endpoint, motion and interval again
     inside every commit, so the plain ledger path cannot commit a record solved for another interval.
   - In v1 a coupled history must be unbroken: a non-coupled interval after a coupled one, and any committed I03
     topology event, refuse by name (`chain`, `events`): E_b and the labels are not carried across them.
   - Before a `CoupledInterval` can be committed or used as a parent, it must be the exact object issued by the
     converged solver, with its retained content digest unchanged. The digest covers its transfer records, endpoint
     descriptors, complete ports, balance and report. A public constructor, copy or `dataclasses.replace` does not
     inherit issuance; editing a nested diagnostic also invalidates it. Refusal precedes the ledger clock or the
     next solve. Weak registry keys retain only the digest, not released states. This check does not repeat physics;
     cold verification still replays the saved interval as below. It protects the public API, not arbitrary private
     Python-state mutation.
   - Only Verified values issued in this process by `verify_driving` or `commit` are trusted (a module-private
     registry); a hand-built value refuses by name. A cache hit is accepted only for an issued verification of the
     very record and endpoint stored at that commit, because the cache key is positional and another ledger of the
     same identity shares it (otherwise `stale identity`, `cache`), and only when the chain behind it is this
     ledger's: the parent commit is validated the same way and the record's parent digest must be the digest of the
     parent commit's stored record (round 3). A valid cache costs comparisons, no solves. A replay refusal names the
     binding and inheritance fields first (`parent_driving_sha256`, `interval`, `parent_state_id`,
     `endpoint_state_id`, `motion_id`), then the first other differing field.
   - `find_driving` labels a found record "recorded, not replayed". `verify_driving` replays it by verifying the
     parent commit's record first and then solving the whole interval again from the parent commit's restored states
     (forcing and declaration from the record, supplies and sinks from the committed motion, births and conduction
     from the committed advance). The replayed record must equal the stored one in every field, and the replayed
     advance, motion and endpoint states the committed ones. Each record is verified once per call and cached by its
     commit key (`cache`): verifying commit k solves its k intervals once each, and verifying a whole chain of n
     intervals with one shared cache solves n intervals (as long as solving them did: 13–23 s each on the
     fixtures). Verifying every commit
     separately without a shared cache would cost n(n+1)/2 solves (port record section 4).

**Time accuracy.** The scheme is first order. Its order is gated only on an oracle control (below); coupled cases
report orders without gating them and gate step-halving changes (ruling C3).

**Events.** None is admitted. Template rotations, events, regional returns, junction paths and history splits refuse
by name, and so do ridge jump, subduction polarity reversal, slab breakoff and continental collision (CM-12, I07).

### R4-8. Package ownership of the tool-resident I01 helpers

No tool is moved or edited in Part A; ten current receipts bind those tools.
- **Reproduced in the package**, each with the same equations and arithmetic order:
  - `Datum` and `columns` (from `check_i01_gpe.py`);
  - `solve_torque` (from `check_i01_closures.py`), which now also returns its residual;
  - `stream_seed`, the New World structure draw, `continental_profile` and `ocean_profile`.
- **Compared with the tools directly by tests:** outputs must be bitwise equal, with the same refusals. One type
  deviation is recorded: a floating-point overflow in `columns` refuses as `DrivingRefused`.
- **Closed-form moments** are checked against the tool's `drag_matrix` on its own exact point rules.
- **A later move** of the tool helpers into the package, with the tools re-exporting them and the ten receipts
  reclassified, is a proposal for Codex.

## 3. The starting family (I04.1)

`atlas.i04-starting-family.v1` is a labelled initial-condition prior with origins. It is not mechanics, and not an
appearance objective. A seed and the scenario determine it. The sampling level changes only how plate interiors and
boundary edges are sampled.

**Supported plate counts are 4 to 52 in v1** (ruling C2.1).
- N of 3 or fewer, and site sets on one great circle (antipodal Voronoi vertices, edges of pi), refuse by name.
- New World admits 2 to 52, so N = 2 and 3 are a recorded v1 gap.

**Streams.** The New World seed streams are reproduced (`stream_seed`).
- Geology reads `continental_structure`, `crustal_structure` and `thermal_structure`. It never reads the plate count
  or the sampling level.
- Plate sites read `plate_layout`.
- Every predicate that can change declared geometry is evaluated on the continuous polygons, never on the mesh or on
  pieces (ruling B1.2):
  - ocean-site rejection;
  - anchors;
  - sutures;
  - kinds;
  - slab columns;
  - trace columns.

**Provinces.**
- **Shape and placement.** The minority crust type forms provinces on the majority background.
  - f = 0.5 belongs to the oceanic-background branch, as in `_footprints`.
  - Each province is a star-shaped polygon of 64 vertices in a gnomonic chart at its centre, with lobes (harmonics
    2–5) and an aspect stretch.
- **Size.** Bisection fixes each province to its exact target area, within `2e-11`, inside an 80° cap. If the
  cap-limited area falls below the target, the province refuses by name: "outside the fixed shape envelope".
- **Area shares.**
  - The fragment-share parameter takes its share of the minority area for fragments, and the majors take the rest.
  - Within each group, `A_k = A_floor + (A_group - n A_floor) w_k/sum w`, with seeded weights.
  - Below the floor, fragments are dropped first, then majors. If a single province remains and the minority area is
    below `A_floor`, the world refuses (RD-05 option A).
- **Placement.**
  - Provinces are placed largest first, uniformly on the sphere.
  - A placement is rejected if it overlaps an earlier province. The test uses I03's exact spherical intersection on
    fan triangles.
  - At most 64 attempts are made, then the world refuses. There is never a seed retry.

| Parameter | `default` (physically safe) | `wide` (opt-in, recorded) |
| --- | --- | --- |
| major provinces | 3–7 | 1–12 |
| fragments | 0–6 | 0–16 |
| fragment share of the minority area | 0.02–0.10 | 0–0.30 |
| size weights | `exp(ln4 (2u-1))` | `exp(ln8 (2u-1))` |
| aspect | 1–3 | 1–6 |
| lobe amplitude | 0–0.30 | 0–0.45 |
| column-scale floor `k` | 1 | 0.5 |

**RD-05 floor** (ruling C1, a coordinator decision under the owner's delegation).
- **Definition.** `A_floor = pi (k H_max)^2`, where `H_max` is the declared scenario maximum column depth, 150 km. It
  is not the realised deepest column.
- **k = 0.5 is aspect ratio 1:** the province's equivalent diameter equals the deepest column depth.
- **What a 1-D column loses.** For a cylinder of radius `kH` in a slab of thickness `H`:
  - lateral relaxation time divided by vertical is `(pi k/2.405)^2`: 0.43 at k = 0.5 and 1.71 at k = 1;
  - in steady state the centre keeps `1/I0(pi k)` of the lateral contrast: 0.58 and 0.18.
- **Labels.** Every k < 1 province is labelled as one where the 1-D geotherm is not representative even at its centre.
- **Scope.** The floor bounds the equivalent radius only. Elongated or lobed provinces are narrower locally: the minor
  semi-axis is 0.41 kH at e = 6, and lobes reach a minimum radius factor of 0.0625.
- **No other effect.** The wide range never widens the requested fraction, which the family takes exactly. It is never
  used unless requested. Its name and parameters enter the family's identity and labels.

**Columns.** Continental columns reuse the existing New World scenario ranges (`NEW_WORLD_STRUCTURE`):
- crust 30–45 km;
- lithosphere 110–150 km;
- upper-crust share 0.45–0.60;
- inherited formation age 400–3000 Ma;
- the steady geotherm `k_i T'' + H_i = 0`, applied once.

**Densities.**
- Crust densities come from the library.
- The lithospheric-mantle density is derived from the shared datum (R4-5): `rho_ref = rho_m/(1 - alpha (T_base -
  T_ref))`.
- **A declared v1 limitation** (round-2 decision; R4-5). v1 families exist only on the 3300 kg/m³ / 293.15 K datum.
  - `family_columns` takes the shared Datum and requires both `mantle_density_kg_m3` and `reference_temperature_k` to
    match exactly. Otherwise it refuses (`stale identity`, `datum_id`).
  - A twin datum with another reference temperature, whose derived density happens to agree, is refused too.
  - It also checks each delivered mantle-lid density against the datum's derived one.
  - It refuses rather than rebuilds, because the slabs and the I03 material were built on the family's datum. A
    compositional jump at the base of the lithosphere is never silent.
  - Adding a datum to the family request is a later follow-up.

**Column bounds** (round 1). The table's 0.04 K bound belongs to the table only. Each delivered column records a
derived column-level bound, `max_l M_l h_l^2/8` plus the node error, with `M_l` the geotherm's curvature bound in
sublayer `l`.
- The largest measured departure of a linear mantle-lid sublayer from the exact finite-plate geotherm, on the
  development worlds, is 15.7 K. That is within its bound.

**Ocean history.**
- Formation age is **unknown** and masked. There is no single background age and no nearest-ridge age.
- The thermal state is a separate declared assumption: one assumed thermal age per plate's ocean, 10–120 Ma
  (`ocean_profile`).
- The family reports how much material rests on assumed histories (CM-02).

**Weaknesses, slabs and land.**
- **Weaknesses.** Up to two inherited sutures cross each major continental province, each with an origin and unknown
  strength (IN-04, Part B).
  - Each suture is a great-circle chord between two outline vertices `i` and `j`.
  - Its span `j − i` lies in `[K/4, 3K/4]` with `K = 64`, a declared scenario prior approved in round 1: neither
    side of the chord keeps less than a quarter of the outline, so no sliver part forms.
- **Initial slabs.** One initial slab per trench, with a seeded length (default 100–600 km; wide 0–1200 km).
  - `S = length × int rho_ref alpha (T_base - T(z)) dz` over the subducting column's lithospheric mantle. That equals
    the contract's `int (rho_slab - rho_m) dA` only under the derived-density rule.
  - The integral is evaluated as a trapezoid on the 10 mantle-lid sublayer boundaries. Its derived offset bound,
    `sum_l rho alpha (M_l h_l^3/12 + e_node h_l)`, is recorded with each slab. The largest measured offset from the
    continuous profile, on the development worlds, is 2.3%.
  - Crustal buoyancy is a declared omission.
- **Land.** Dry land is unknown. Crust type is never relabelled as land, because no D5 producer exists.

**Boundary-inheritance rule** (ruling F6′; a labelled prior; kinematic only; not mechanics).
1. **Sites in proportion to crust area.** `n_a = floor(N s + 1/2)` sites belong to the minority crust type, where
   `s` is its area share: f, or 1 − f under the swap.
   - It is evaluated exactly on the rational value of the binary64 f, rounding half up, so ties are exact on that
     binary value. The swap symmetry holds for every f whose complement 1 − f is exact in binary64. A tie test and a
     swap-symmetry test cover it (round 1).
   - When both types exist, `n_a` is clamped to [1, N − 1].
   - The other `N − n_a` sites are free, drawn in the background crust.
   - **Why:** sites drawn at a common density give Voronoi cells of equal expected area. Allocating sites by area
     share therefore keeps the expected plate size independent of crust type. The rule uses only N and f, the exact
     controls, and needs no new number.
2. **Anchors fill the minority slots first.** Provinces of the minority crust type, majors and fragments alike,
   largest first, anchor one site at their area centroid. That is continents when f <= 0.5 and oceanic provinces under
   the swap. The rule encodes the prior "strong continental lithosphere nucleates plates".
   - A sutured anchor gives two sites, but only while two of the `n_a` slots remain, and with no offset number (round
     1 ruling).
     - The suture's great circle divides the province into two sides. A side may be more than one piece, where the
       circle cuts the outline more than twice; "the larger side" is the union of the pieces on that side.
     - The first site is the area centroid of the larger side. The second is its mirror across the circle,
       `g − 2 (g.p) p`.
     - The boundary between the mirrored pair therefore lies on the suture.
     - **Both sites take the province's crust type**, wherever the mirror lands (round-2 ruling, option 1). This is
       the F6′ rule that an anchored site takes its province's type; the crust under the site does not decide it. A
       test covers mirrors that land in ocean.
   - Slots the anchors cannot fill get **minority-drawn** sites, uniform inside minority crust, which are not anchors.
3. **Free sites** are uniform on the sphere and rejected inside minority crust. Every site, including anchors, both
   mirrored suture sites and minority-drawn sites, must be at least `2 k H_max/R` from every other.
   - Each site has at most 64 attempts, and then the world refuses.
   - A suture whose mirrored pair would be too close is skipped as a site generator and recorded.
4. **The swap (f > 0.5).** The roles swap: oceanic provinces anchor, and free sites are drawn in continental
   crust.
5. **Plates** are the spherical Voronoi cells of the sites.
   - Every boundary is a great-circle arc with a declared origin.
   - The plate count is exact by construction.
   - Bit-equal Voronoi vertices refuse by name. v1 does not merge them into a junction of degree 4 or more. There is
     no minimum-edge-length policy, which would be a new underived number. Short-edge frequencies are reported
     instead.
6. **Kinds.** Each plate takes its site's crust type: anchored sites (both sites of a mirrored pair included) and
   minority-drawn sites take the minority type, free sites the background type.
   - continental against oceanic: trench, with the oceanic-site plate subducting;
   - the same type on both sides: ridge (f = 1/2). Between two continent-bearing plates this is an Atlantic-type
     ocean basin;
   - **except** the bisector edge of a mirrored suture pair: transform with no carrier, an inherited weakness.

**Rules this replaced.**
- **The proposal's midpoint rule** was rejected because the crust is the same on both sides of almost every edge:
  0 trenches in 2,533 edges.
- **F6, which classified sides by anchor type,** let anchors fill every slot. Three of eight wide development worlds
  then had only transforms, and three of eight default worlds had no ridge.

**Consequences, recorded** (rulings F6 and F6′):
1. A carrier-less transform locks its two plates in I03. Under F6′ it occurs only at suture bisectors.
2. A ridge needs a Supply for each opening side.
3. **No family world is advanced with D1 output in Part A.** Generic Voronoi vertices are junctions of three lines,
   which I03 refuses without a supplied `JunctionPath`. This is not worked around.
4. Slab pull exists only at these labelled continental|oceanic trenches.
5. A "ridge" between plates with assumed uniform ages has no young axis. Its GPE comes from per-plate contrasts in
   `U`, not from ridge push.

**Sampling.**
- **Edge points.** Edges up to 120° use `t = k/2^L` and one reversal-symmetric expression,
  `(sin((1-t) theta) a + sin(t theta) b)/sin theta`, with the stored Voronoi vertices as endpoints. Shared points are
  therefore bitwise equal across levels.
- **Longer edges** are generated by rotating the start vertex about the edge pole `unit(s_i - s_j)`, with an
  exactly verified off-plane bound. An edge whose point bound would exceed I03's 64 eps attachment band refuses by
  name.
- **Interior.** Each plate is fanned from its site in `2^L` rings.
- **Material pieces** come from exact intersections with the province fan triangles, with the background as the
  remainder.
  - A face wholly inside a province is assigned whole.
  - Each face therefore closes exactly, with no negative remainder.

## 4. Controls and what the checks establish

The controls and their criteria were fixed in `tectonics/cases/i04_controls_v1.json` and approved, with the
conditions above, before running. Results are in section 5.

| Control | Criterion | Establishes |
| --- | --- | --- |
| Closed-form moments: octant, split lunes, hemisphere and sphere, as full matrices; tool `drag_matrix` parity on its exact rules | `1e-11` relative (existing) | the basal and interface operators are exact |
| Per-face covariance, additivity, holes, moved networks | the derived absolute bound (R4-1), whose edge part is verified exactly | exactness at rounding level on I03 faces, including thin ones |
| Orientation guard | reversed rings and counter-clockwise holes refuse | the moment cannot silently flip sign |
| D1 closures control on I03 faces: analytic `omega`, power, frame rotation, `2D -> omega/2` (with `k` doubled), zero drive, repeat | `1e-11`; exact zero; bitwise | signs, nullspace and frame, torque and power, as in the retained control |
| Mantle rotation: plates co-move with the mantle; `2D` halves `omega - omega_m` | `1e-11` | the `D v_m` term and its power account |
| GPE two-hemisphere exact solution, `N = 32, 64, 128` | finest error `< 1e-3`; ratios in `(3.8, 4.2)`; equal to `1 - sinc(pi/N)` and to the `i01-gpe-r1` errors within `1e-12`; cancellation and work `< 1e-11` | GPE from columns on I03 geometry at the existing gates |
| Uniform `U`; a jump field | zero torque; global cancellation `< 1e-11`; `J_b` and `delta_omega_b` reported | the single-valued trace and its published sensitivity |
| Linear challenges: `L0/L -> 2 L0/L`, `C: 1 -> 0.5`, `D -> 2D` | the change equals `M^-1 delta tau` within `1e-11` | LS-I04 force-parameter challenges move the solution in the derived direction |
| Slab pull | exact torque; at every trench edge midpoint the subducting plate moves into the overriding plate, for both subducting sides; other plates exactly at rest | attached-slab pull toward the trench, and the declared omission |
| Refusals | named codes | no missing force read as zero; no double ownership; frame refusal; stale and unknown columns; water regimes |
| I03 hand-off | a driven sector plate advances; a general-axis drive at the polar triple junctions is refused by I03 | D1 output enters I03 only within its supported classes; no junction law is invented |
| Family: declared geometry at two levels | bitwise, on a record that excludes the level | the continuous geometry is independent of sampling |
| Family: per-plate and continental areas at two levels | the range-limited C7 at both levels, plus `1e-12 mu_f` per face, plus the per-edge boundary term | areas are independent of resolution up to rounding |
| Family: exact controls | plate count exact; fraction within `2e-11` plus the occupancy term, against `4 pi R^2` | starting controls, with no correction step |
| Seed-41 repeat | the layout differs when only the continental fraction changes | structure is an actual input to the layout |

**Case H (description only, development seeds)** reports morphology at 100, 250 and 500 km, and the boundary
kinematics from D1 motion. It also reports:
- the shares of trenches, ridges and transforms;
- refusal rates;
- short-edge frequencies;
- torque shares per term (GPE, slab, drag), so that initial diversity is not mistaken for driving physics.

**These checks do not establish** realistic Earth motions, generated events, morphology acceptance (case H), I09
coupled convergence, planetary runtime or Linux behaviour.

### Part B controls (I04.3 and I04.4)

Fixed in `i04_controls_v1.json` `part_b` before any dependent control ran (with the sizing probes recorded there),
and amended before the dependent runs for the mid-build `Belt.side` ruling, the re-derived beta tolerance, the time
spans and the feasibility findings. Fixtures: the twin hemispheres (an equatorial transform carried by the south
plate, with belt rows at `+-w/2R`, refined rows, and a one-sided variant with rows at `-w/2R` and `-w/R`) and the I03
lune world (ridge `m00`, trench `m04`) with its zigzag variant. That original delivery
left the staircase criterion unmet; the genuine repair control below now covers it.

| Control | Criterion | Establishes |
| --- | --- | --- |
| Oblique column solve at `c = +-1`; at `c = 0` | bit for bit against the package solve and `respond`; equal to the supplied-pressure column | the closure reuses the I01 kernel exactly at the end members |
| Inverse, `dS/dc`, traction tangent | `2e-11`; central differences to `1e-4` | the series solve and the exact Newton tangent (non-symmetric) |
| Line operator | package parity; the 40/80/160 ratio window `(3.8, 4.2)`; uniform stays uniform | the nonlocal step is the existing second-order operator, well balanced |
| Geometry and refusals | `sum dy = w`; re-crossing, depth, yield convention, BROKEN bond, `U = 0` (no kernel call), COARSE, a missed face, `beta > 1 + tol`, P2 binding; inner-solve refusals on synthetic terms; events on a fully yielding belt | the belt line and its named refusals |
| Depth order 8 against 16 | `<= 0.003` on the belt force | the I01 layered Gauss gate on the belt |
| Single balance | inner residual `<= 1e-10`; increment or condition rule; PSD symmetric part; derived power closure; increments within the D-P1 bound | the inner solve and its accounts |
| Coupled interval | coupled P5 header and residual `<= 1e-8`; P6 = applied increments; P7 heat rule and closure on the column work; per-piece heat bound; P9 power and torques `1e-11` | the coupled ports |
| P9 swap | `omega_swap = omega* - M^-1 r(omega*)`, `1e-11` | the reaction port enters D1 as exactly the belt torques |
| Zero forcing; caps; strain guard | exact zero; named refusals; byte-level non-commit | the zero branch and refusals |
| Tilted pole (oblique `0 < |c| < 1`) | Newton converges; tangent non-symmetric; monotone | the non-symmetric control (C1(3)) |
| fv-cell-mean | one coupled balance with GPE on `s00-merged` records its trace indices | the P7(2) obligation |
| Provenance on an I02 ledger (round 1) | inheritance from the parent commit (`step`/`commit`); found = "recorded, not replayed"; the whole interval replayed; forged labels, strain, heat or P5, a dropped inheritance and a malformed record refuse by name; an interval solved for another span cannot be committed | D1 provenance after reopen |
| Case A frame | tilted world: rotated omega, same increments within `cond(M+J) 1e-10 + 2e-11` | frame invariance |
| Case B direction | cohesion x2 slower; +100 K faster; kappa0 2.5 faster; torque x2 faster with a larger plastic share | the response moves the predeclared way |
| Case B rows 2/4/8 | change 4 to 8 `<= 0.03` (peak force, speed, kappa gain, width_2sigma (the raw-history width)) | reduced-model refinement: **failed on the peak increment; convergence not established** (see Part B results); not a physical width |
| Case B length | `ell` 2500 against 5000 m, cells under 2500 m: width differs by more than 50 m | the declared length acts |
| w and side disclosures | reported, not gated | dependence on authored assumptions |
| Time oracle | orders in `[0.8, 1.2]` against DOP853 (uniform one-row single-layer belt, one-sided) | first-order time accuracy of the scheme on that belt, against a high-order integration of the same reduced equations (the package's balance as right-hand side); not of the layered, localising belt |
| Coupled time | step-halving `<= 0.03`; feedback `>= 10 x` its halving change; iteration/time `<= 1e-3` | resolved coupled feedback on the layered column |
| Reopen parity | a fresh process continues to the same head and records | provenance supports continue/reopen |
| Lune ridge, zigzag, trench | start balance (COARSE); coupled refusals by name | the predeclared refusals, not worked around |

### Ridge/transform staircase repair control (4 October 2026)

Michael authorised the necessary I03 material-seam extension, rather than accepting
the earlier oblique ridge as a staircase. The inputs and checks are recorded before
execution in `cases/i04_staircase_v1.json`. This is a manufactured integration
control, not a generated-world realism result.

Two equatorial ridge-transform-ridge offsets are related by a half-turn about the
Euler axis. Each is a true 20-degree transform between offset ridges. The same A/B
plate identifiers deliberately describe rigid multipart plates. Their geometry,
columns and two transform belts share that half-turn symmetry, so a constant axial
authored torque can produce coaxial motion through the full six-component D1/D2
balance. No solved velocity is projected onto an axis, and no forcing is fitted to
an endpoint result. This isolates the supported slip-parallel geometry without
claiming a mechanism for a general off-equator transform.

The control requires two nonzero `coupled_interval` calls, retained offset corners,
positive ridge births, positive belt work, exact material-account closure and the
unchanged inner/outer convergence checks. Spreading is ordinary 50/50 accretion.
Only the two transform belts supply D2 resistance. Ridge and trench resistance,
GPE, mantle traction and slab pull are explicitly omitted in the forcing record;
this must not be reported as acceptance of ridge or trench D2 coupling. The
standalone I03 checks separately cover endpoint fractions, tilted axes, three
intervals and restoration.

**Measured repair checks.** Both two-step coupled histories passed, plain and
tilted: three plain/coverage checks took 13.982 s and the tilted check 11.982 s.
Each tilted step converged in four outer iterations, with maximum residual
`3.01e-12` against the unchanged `1e-8` bound. Maximum cumulative transform
slip was `1.87e-16 rad`, and offset error was at most `1.67e-16 rad`.
The tilted steps produced approximately `8.2521e9` and `8.2531e9 m²` of
crust and `9.4555e11` and `9.4507e11 W` of positive belt dissipation.
The positive raw-history increments were about `0.0032545` and `0.0032548`.
These are fixture results, not calibrated planet predictions or speed comparisons.

The joined check exposed and now covers a missed-face bug in a one-sided belt:
a plate can wrap around a transform endpoint, so its newborn crust on the opposite
geometric side must not count as missing belt coverage. The signed-side repair
retains the existing band, footprint distance, endpoint caps and beta bound.
An intentionally omitted face on the selected side still refuses.

## 5. Results

Executed in the scratch candidate on Windows/CPython 3.12.14, on 3 October 2026, after approval. These are
candidate results, not acceptance.

**D1 and GPE** (`test_i04_driving.py`, 35 tests OK, with the round-2 fixes):
- **GPE two-hemisphere control.** Relative rotation errors of the north plate at `N = 32, 64, 128` (the test asserts
  the maximum over both plates, which agrees to about 1e-15):
  - 1.6056069643815e-3, 4.0154685032067e-4 and 1.0039578385910e-4;
  - each equals `1 - sinc(pi/N)` to about 1e-15 (the declared tolerance is 1e-12);
  - refinement ratios 3.99855 and 3.99964;
  - `|omega_y|` of 2.5592e-17, 2.5623e-17 and 2.5631e-17 rad/s, the `i01-gpe-r1` values;
  - global GPE cancellation and power closure at or below 3.5e-16.
- **D1 closures control on I03 faces.** `omega` equals the `i01-controls-r1` values to 2.5e-16 (relative norm), with
  work 406413337.597 W:
  - basal dissipation 258064739.98 W;
  - interface dissipation 148348597.62 W;
  - closure 0.0.
- **Rounding bound.** The derived edge-sum bound held on all 200 random faces. The worst observed error was 0.041 of
  the bound.
- **Authored slab control** (`C = 1`, `S = 2e12 kg/m`). The subducting plate moves toward the trench at 111 mm/yr;
  the other plates stay exactly at rest. These are authored values, not an Earth comparison.
- **Mantle rotation with a small authored torque** (round 2). With `mantle_omega` from the case file and authored
  torques down to 1e14 N m, the closure stays within `1e-11` once the mantle-traction power is in the scale.
- **I03 hand-off.**
  - A plate driven about the world axis advances through `T.advance`.
  - A general-axis drive at the polar three-plate junctions is refused by I03, as expected.

**Port record** (`test_i04_ports.py`, 13 tests OK). Header identities, the reserved P4, column ownership, unknowns,
the water-source rule, P5 refusals, and (round 2) the field each refusal names and NumPy seconds.

**Reproductions** (`test_i04_equivalence.py`, 6 tests OK; plus the family parity tests). `Datum`, `columns`,
`solve_torque`, `stream_seed`, the structure draw, `continental_profile` and `ocean_profile` are bitwise equal to the
tools, with the same refusals.

**Starting family** (`test_i04_family.py`, 37 tests OK, with F6′ and the round-1 and round-2 fixes):
- **C-7.** The declared geometry is bitwise equal at levels 1 and 2 on every development and declared review world
  that built.
- **C-8.** The largest per-plate area difference was 1.1e-4 of its bound on the development worlds, and 1.5e-4 on the
  declared review worlds. The review worlds include 10 N = 4 worlds with a rotation-built edge over 160° (the
  longest 177.7°), and N = 30 and N = 52 worlds.
- **C-9.** `|f_realised - f|` was at most 1.1e-16 against a bound of 2.1e-11, including 28 worlds under the f > 0.5
  swap. The plate count was exact.
- **Seed-41 repeat.** Changing only the continental fraction from 0.30 to 0.40 moves plate sites by up to 309 km, so
  structure is an actual input to the layout.
- **Paths exercised:**
  - minority-drawn sites (N = 52, and N = 30 under the swap);
  - suture-derived site pairs (20 of the 73 development-world sutures became mirrored pairs);
  - the exact `n_a` ties;
  - mirrored suture sites that land in ocean, which keep the province type (round 2);
  - datum refusal, on each field alone and on a twin datum (round 2);
  - named budget refusal.

**Mutation proof.** Each of 36 deliberate defects makes its named test fail (scratch `mutate_d.py`). There are 25 in
the driving kernel and ports, and 11 for the round-2 checks in the driving kernel, ports and family datum and site
rules.
- Four tests were strengthened in the first pass, until every defect was caught.
- In round 1 the slab test was rewritten to check velocity into the overriding plate at every trench midpoint, on
  both subducting sides. The old assertion could not fail, and it missed a reversed slab torque (mutation D20).
- In round 2 the datum test gained a T_ref one ulp above 293.15 with the density exactly 3300. It derives the same
  mantle-lid density, so only the exact T_ref comparison refuses it. The first version of the test missed a
  density-only gate (mutation D32).

**Case H: initial diversity on development seeds 1–8** (N = 12, f = 0.35, level 1, F6′; description only, no
acceptance).

| Range | Built | Trench/ridge/transform per world (of 30 edges) | Plate area fractions | Torque shares GPE / slab / drag |
| --- | --- | --- | --- | --- |
| default | 8 of 8 | 16/14/0, 14/14/2, 17/11/2, 14/14/2, 15/14/1, 16/13/1, 11/17/2, 15/13/2 | 0.023–0.206 | 0.04–0.09 / 0.44–0.48 / 0.47–0.48 |
| wide | 6 of 8 (seeds 5 and 8 refused: outside the 80° shape envelope) | 17/13/0, 15/13/2, 17/12/1, 13/15/2, 18/11/1, 14/14/2 | 0.018–0.208 | 0.02–0.05 / 0.46–0.49 / 0.48–0.49 |

**Metrics.**
- **Torque share** of a term is `sum_p |tau_term,p|` divided by the same sum over GPE, slab pull and the basal-drag
  reaction `M_p omega_p`. Drag balances the driving terms, so its share is close to one half.
- **RMS plate speed** is `R sqrt(mean_p |omega_p|^2)`, taken over plates.
- **Area-weighted RMS surface speed** is `sqrt(sum_p omega_p . J_p omega_p / (4 pi R^2))`.

**Sites and short edges.**
- Every world that built has `n_a = 4`: 4 anchored sites, no minority-drawn site, and 8 free sites.
- No default world has zero trenches or zero ridges.
- The shortest boundary edges are 16 km (default seed 4) and 26 km (default seed 8). Three default worlds (seeds 4,
  5 and 8) have edges shorter than the column scale `k H_max`. These are reported, not refused (ruling C2.3).

**D1 runs.** They used:
- GPE from the family columns;
- basal drag of 6.25e14 Pa s/m;
- the family's declared slabs, with a labelled `C = 1`.

**Outcomes:**
- **Power.** Every solve closed power to 2.1e-16 or better.
- **Speeds.** RMS plate speeds are 117–443 mm/yr; area-weighted RMS surface speeds are 92–341 mm/yr. With these
  authored coefficients, slab pull gives 83–96% of the driving torque. The speeds describe the authored inputs, not
  Earth.
- **Partition.** The trace partition can move a plate by up to 51 mm/yr.
- **Net rotation.** Slab pull, an external force, gives net rotations of 0.09–0.67 deg/Myr. GPE alone gives none,
  because its torques cancel.
- **B1 boundary kinematics** at 250 km, from the D1 motion:
  - opening 36–53% of boundary length;
  - shortening 36–58%;
  - shear-dominated 4–21%.

  These describe how the D1 motion relates to the labelled kinds. They are not a check of them.

**Independent verification.** Four verifiers worked on a read-only copy, each trying to break the code by running
it, and a skeptic reproduced or refuted each finding. They confirmed nine findings, all now fixed:
- **Already superseded:** the copy still followed F6, so its kind and anchor findings were already met by F6′.
- **Regression tests added for the rest:**
  - **P1 binding:** P1 columns are bound to the datum, the network frame and the start of the interval.
  - **P5 binding:** P5 is bound to its balance.
  - **Read-only record:** the issued balance's mappings cannot be changed.
  - **Power closure:** it is measured at the scale of the identity's terms.
  - **Named refusals:** the Airy regime without a declared water density refuses by name.
  - **Port refusals:** refusals on consuming a port carry `PortRefused` codes, with the I01 code in `detail`.
  - **Anchor order:** anchors are the largest provinces first, fragments included.

  Each test failed before its fix and passes after it. Five other findings were refuted, because the rules do not
  require the behaviour they expected.

**Coordinator verification, round 1** (3 October 2026). It confirmed the physics independently, and required fixes to
tests, declarations and binding:
- a slab-direction test that could not fail;
- the derived suture sites and the declared suture span;
- the datum-bound mantle density;
- P5 bound to its balance;
- the forcing frame;
- per-item omissions;
- named refusals and consistent codes;
- the `test:` water source;
- added tests (C-9 under the swap; C-7 and C-8 on long-edge and N = 4, 52 worlds);
- documentation corrections.

All are applied above. The round-1 addendum in the handoff lists each fix.

**Coordinator verification, round 2** (3 October 2026). It required:
- a forcing frame that is mandatory for axis-dependent vectors;
- the mantle-traction power in the closure scale;
- the province crust type for both mirrored suture sites, and the "larger side" declaration;
- named refusals for a wrong `columns_port` type and for non-numeric or overflowing coefficients;
- the exact two-field v1 datum gate;
- wording and number corrections.

All are applied above. Each new or extended test was run and seen to fail before its fix, with two exceptions:
- The mirror-type test already passed, because F6′ gives anchors the province type. It stays as a guard (mutation
  D33).
- The datum test's one-ulp `T_ref` case was added after the fix. It fails against the round-1 gate (mutation D36).

Case H was re-run on the round-2 code and is unchanged apart from timings.

**Measured cost.** One cold run and warm repeats in a fresh process, on Windows/CPython 3.12.14. No other Python or
Atlas desktop process ran, but Codex desktop processes were present.

| Workload | Cold | Warm | Peak traced memory |
| --- | --- | --- | --- |
| Starting family, N = 12, level 1 (240 faces) | 0.66 s | 0.66 s | 2.0 MB |
| Starting family, N = 12, level 2 (960 faces) | 1.80 s | 1.84 s | 6.0 MB |
| D1 operator assembly, family level 1 / level 2 | 26 ms / 126 ms | 26 ms / 126 ms | — |
| GPE traces (120 / 240 trace points) | 0.4 ms / 0.7 ms | 0.3 ms / 0.6 ms | — |
| Balance with the prepared operator reused | 1.4 ms / 2.1 ms | 1.3 ms / 1.9 ms | — |
| Dense `3P` solve (36 unknowns) | 0.07 ms | 0.07 ms | — |

- **Operator reuse.** Reusing the prepared operator removes 95% of a level-1 balance's time: 27.3 ms down to 1.4 ms.
  The operator is reused only while its network and resistance identity are unchanged.
- **Where the time goes.** Most of the family's time is I03's network construction.
- **After round 1.** Re-measured on the round-1 code: 0.67 s and 1.83 s cold, with peaks of 2.1 MB and 6.0 MB. That
  is unchanged within 2%.
- **Interactive limits.** New World's interactive limits (1024 cells, 256 MiB, 120 s) are quoted for information
  only; they are not a promise for evolved worlds.

### Part B results (I04b)

Executed in the scratch candidate on Windows/CPython 3.12.14, on 4 October 2026, after the rulings, and again on the
round-1 sources after the coordinator's verification (the numbers below are the round-1 run's; every physics number
is bit-identical between the two). These are candidate results, not acceptance. **Two predeclared controls failed**,
and the failures stand recorded: Case B plastic share ("expectation withdrawn as an authored error") and Case B
refinement of the peak increment ("pre-asymptotic, h/ell = 1.25; 16-row information only"). Their assertions are
unchanged and are kept as expected failures, as I03 keeps its historical ones.

**Unit and coupled tests.** `test_i04_strength.py` 25 tests OK; `test_i04_feedback.py` 25 tests OK. Measured within
them:
- the oblique solve equals the package solve bit for bit at `c = +-1` and the supplied-pressure column at `c = 0`;
  `dS/dc` and the traction tangent match central differences to `1e-4`; depth order 8 against 16 changes the belt
  force by less than 0.003;
- a single balance on the twin transform (torque `1e28` N m, `kappa0 = 1.5`): Newton in 4–5 steps, closure
  `1.9e-12` against its derived bound `1.5e-10`;
- one coupled interval: 8 outer iterations, coupling residual `1.33e-9`; the P9 power equals the belt dissipation to
  `2.2e-16`, its torques the belt term to `1.5e-32`, and `-sum omega.tau` the dissipation to `2.2e-16`; the P9 swap
  gives `omega* - M^-1 r(omega*)` to `1.4e-16`;
- the tilted pole (10 degrees): `c` in `[-0.185, 0.185]`, Newton in 5 steps, a non-symmetric tangent (relative
  asymmetry `2.4e-2`), positive definite symmetric part;
- zero forcing: omega, increments, dissipation and P9 exactly zero in one outer iterate;
- on an I02 ledger (round 1): a chain inherits through `step` and `commit` (the second record carries the first's
  digest, its labels and its cumulative heat and strain), and `verify_driving` replays both intervals exactly with one
  cache; forged labels, cumulative strain, heat bound and P5 omega (one part in `10^6`), each committed through the
  plain path, refuse `stale identity` naming that field; an interval solved without its parent refuses at `commit`
  (`parent`) and on reopen; a record with only its binding fields refuses `missing value`; a record without them,
  and an interval solved for half a step, are refused inside the commit by I05, the head unchanged; a coupled
  interval with GPE replays; a forced cap of 1 refuses with the ledger head, chain and store file unchanged;
- the inner-solve refusals (non-monotone, the 64-halving cap, unresolved inner solve) and the outer ones (stopped
  contracting, a changed endpoint support) fire by name; a missed face refuses `missed` and a doubled line `beta`; on
  a fully yielding single-layer belt the transform suggests no event and an opening belt reports CM-07; the P7
  energies close on the column work within the derived bound; E_b on the 10-degree oblique belt equals `max_k |c
  e_k| dt` and accumulates from 0.049 to the guard.

**Finish controls** (`test_i04_controls.py`, round 1: 12 tests, 23.3 min; 10 pass, and the 2 failed predeclared
controls are kept as expected failures):

| Control | Result |
| --- | --- |
| Case A frame (tilted twin) | omega `3.8e-16`, increments `2.0e-14` relative, bound `8.9e-10` (`cond = 8.7`): **pass** |
| Case B direction | relative speed 96.0 mm/yr; cohesion x2 87.1 (slower), +100 K 254.4 (faster), kappa0 2.5 184.2 (faster), torque x2 438.0 (faster): **pass**. Torque x2 plastic share 0.676 against 0.702: **FAILED predeclared control; expectation withdrawn as an authored error** (coordinator ruling b1). At fixed history the creep layers' work grows as `U^(1+1/n)` while the plastic layers' stress rises less (a factor of 1.38 against 1.45 for the creep layers at 4.5 times the speed; about -0.011), and the localised weakening during the faster interval lowers the plastic work further (about -0.014); the split depends on the path taken (43/57 or 22/78). I01 §7 does not imply the expectation |
| Case B rows 2/4/8 | 4 to 8 rows: peak force 0.11%, speed 0.29%, raw-history width 0.58% (pass; that width is the inherited profile plus one increment, so it mostly measures the authored input); peak increment 0.286 to 0.310, 7.8% against 3%: **FAILED predeclared control; pre-asymptotic, h/ell = 1.25** (ruling b2). Causes: the inherited kappa0 is sampled at row centres (its peak moves 2.8% from 4 to 8 rows), and the cells are coarser than `ell` (h/ell = 5, 2.5, 1.25), whereas I01's 0.03 was set for h/ell <= 0.25. **16-row information only** (the coordinator's review run, not predeclared): 0.316000, 1.82% from 8 to 16, difference ratios 3.55 and 4.20, Richardson 0.3178. The increment's localisation width (reported, not gated): 40.2, 37.7 and 38.2 km |
| Case B length | the increment profile's width 40.92 km (`ell` 2500 m) and 42.35 km (5000 m): 1427 m wider, more than 50 m: **pass** |
| w disclosure | w: 96.0 mm/yr, peak force 1.557e13 N/m, max dkappa 0.094; 2w: 117.2 mm/yr, 1.467e13 N/m, 0.057 (reported) |
| Side disclosure | both: 96.0015 mm/yr, 1.5568e13 N/m, max dkappa 0.0938, omega_z north 1.397980e-15 and south 9.204875e-16 rad/s; carrier side: 96.0118, 1.5567e13, 0.0978, omega_z 1.398005e-15 and 9.204618e-16 (differences +0.010 mm/yr, -4.3e8 N/m, +0.0040, omega_z +2.57e-20 and -2.57e-20 rad/s; off-axis components at rounding) (reported) |
| Time oracle (uniform one-row belt, single layer, T = 0.2 Myr) | DOP853 gain 0.70712, rotation 0.011359 rad (182 evaluations, all yielding); errors at N = 4, 8, 16: gain 4.02e-3, 2.00e-3, 1.00e-3; rotation 6.46e-5, 3.21e-5, 1.60e-5; orders 1.008, 1.004 (both): **pass** |
| Coupled time (layered, one-sided, T = 0.4 Myr) | step-halving 8 to 16: gain 1.1%, rotation 0.95%, final speed 0.26%; orders reported 1.10 (gain) and 1.07 (rotation); feedback effect 89 x its halving change; iteration/time `4.0e-6` (round 1: the committed iterate's `Delta/(1 - rho)`, over N = 8 and 16; it was `1.4e-7` with `Delta rho/(1 - rho)` at N = 16 only): **pass**. Feedback stiffness, recorded after the run: `|lambda| dt = 0.067` at N = 4 |
| Reopen parity | through `step` and `commit`: the fresh process replays the saved head's record, continues, and reaches the uninterrupted head (sha256, state, sphere, moving and driving digests equal); every record of the uninterrupted chain replays with one cache: **pass** |
| Lune and zigzag ridges | start balance COARSE (`beta` at most 0.043), `c = 1` (lune) and `[0.992, 1]` (zigzag); coupled: `unresolved belt` (`beta` 1.0115 on a birth strip): **pass** (predeclared refusal) |
| Lune trench | `unsupported` at the start balance ("not monotone", the monotonicity check inside the bracket search): **pass** (predeclared refusal) |

- **Pieces per face** stayed 1 in every interval of every control. Distinct increments and new sub-cohorts per
  interval are recorded (for example 19 and 18, then 24 and 5, 23 and 1, 25 and 0 over the N = 4 coupled run):
  fragmentation from exact grouping, falling as sub-cohorts stop splitting.
- **D1 axis tilt** `|omega_xy|/|omega|` stayed below `7.1e-17` in every interval (the transform band is 64 eps).
- **The first oracle attempt errored.** Its two-row fixture let the weaker row localise the shear; at t = 4.3e12 s
  the stronger row left yield and the kernel refused. That broke ruling C3(1)'s precondition, so it measured nothing.
  It was replaced by the uniform one-row belt the ruling names, with T, N and the window unchanged, and the amendment
  is recorded in part_b before the corrected run. The first run's two failures recurred in the final run with
  identical values; the final run used the finished sources.
- **Outer support stability:** `unresolved endpoint support` never fired.

**Measured cost** (fresh process; first call, then the median of warm repeats; Windows/CPython 3.12.14; Codex desktop
processes were present, no other Python):

| Kernel | Cold | Warm | Peak traced memory |
| --- | --- | --- | --- |
| Oblique column solve (layered, order 8) | 0.5 ms | 0.4 ms | — |
| Resultant with `dS/de`, `dS/dc` | 0.4 ms | 0.4 ms | — |
| Inverse resultant | 2.6 ms | 2.6 ms | — |
| Belt line solve (2 cells) | 39 ms | 38 ms | — |
| Belt term build (12 edges) | 73 ms | 72 ms | — |
| Belt term evaluation (12 edges) | 0.42 s | 0.42 s | — |
| Belt balance at the start (P2, belts, Newton) | 2.15 s | 2.13 s | 1.0 MB |
| Coupled interval, twin, both sides | 13.3 s | 13.2 s | 2.6 MB |
| Coupled interval, twin, one-sided | 15.8 s | 15.8 s | — |
| Ledger route, one-sided, one 0.198 Myr ledger step (round 1): `step` | 23.3 s | — | — |
| `commit` | 0.29 s | — | — |
| `verify_driving` (one exact replay of that interval) | 23.4 s | 23.0 s | — |

Most of a coupled interval is its outer iterates (8–11), each an I03/I05 advance and an endpoint belt balance. A
replay costs what solving the interval cost; the ledger fixture's longer step needs more outer iterates.

### Reviewed repairs and resolved refinement, 4 October 2026

The result-provenance repair passed 19 focused checks; the nonlinear partition
sensitivity repair passed 14. Existing valid broader evidence was reused. The
staircase and signed-side coverage results are recorded above, including real
motion, new crust, deformation history, offset preservation and restart.

The separately predeclared resolved successor uses 42/84 rows per side at the same
physical width, `ell=5000 m`, forcing and 0.1 Myr interval. The first grid comes
from `ceil(40/cos(15 degrees))=42`, allowing for the great-circle row-edge bulge
before running. Measured maximum cell sizes at both start and endpoint were
1232.471642/616.235822 m: `h/ell=0.246494328/0.123247164`.

| Quantity | Relative change, 42 to 84 rows |
| --- | ---: |
| Peak raw-history increment | 0.0556096% |
| Peak force resultant | 0.00213208% |
| Relative plate speed | 0.00548303% |
| Raw-history width | 0.0108494% |

All four pass the unchanged 3% limit. The peak increment was
`0.3175702755808601 -> 0.31774697333945223`. Both solves needed 16 outer
iterations. Actual times were 934.645081 and 1826.100926 s, 2760.770 s for the
focused test overall. The original coarse failed assertion remains unchanged.

The [observational refinement report](../evidence/i04-resolved-refinement-r1.json)
records the results and reuse boundary. No complete launch source manifest was
captured. Its test/case/fixture were fixed before execution; later changes were
an issuance guard, a ridge/transform corner path absent from this twin, and a
one-sided coverage filter absent from its both-sided belts. Those changed paths
were tested separately. This is assessed reuse of unchanged numerical work,
not a claim that the long test executed the final package's exact bytes.

## 6. Limits and what remains

- **The family is a prior, not a mechanism.** Its province shapes, anchors and kinds are labelled scenario
  assumptions. Physical boundary evolution belongs to Part B and later stages.
- **I03 junction classes.** I03 advances junctions only in its supported kinematic classes, or with a supplied
  `JunctionPath`. No family world is advanced with D1 output in Part A, and no junction-direction law is invented. The
  regional velocity bridge refuses every motion with junction paths.
- **Explicit interval.** `omega` is solved at the start of the interval and held over it, with no temporal-accuracy
  or convergence claim. Part B and I09 own convergence.
- **Trace partition.** The symmetric partition at plate boundaries is declared, and `J_b` and `delta_omega_b`
  publish its sensitivity. An admitted interface law would replace it.
- **Mixed faces after an advance.** A P1 producer that reads an I03 state (I05) must refuse `unresolved column` for a
  trace point whose adjacent face holds several cohort pieces it cannot place. This is a rule for that producer; Part A
  has no such producer and does not code it. The lasting fix is conforming faces (I04.1) or I03 sub-face geometry, and
  it is a probable blocker for runs of more than one interval.
- **Finite-rigidity water loading** is refused until an elastic core and a spherical flexure producer exist.
- **Plate count.** N = 2 and 3 are not supported by the v1 family. At sampling level 0, I03 refuses some small-N
  worlds on chart conditioning; levels 1 and above build them.
- **Column representation.** Family P1 columns have 30 sublayers, each linear in temperature (the port's `I01_GPE`
  representation, at most 32 layers). This is a bounded, declared discretisation, approved in round 1.
  - For young ocean on the development worlds, the columns depart from the exact geotherm by up to 15.7 K (measured),
    within each column's recorded bound.
  - On the development worlds, the slab section anomaly differs from the continuous profile's by up to 2.3%
    (measured), within its recorded quadrature bound.
  - These maxima are for the development worlds only. At the admitted 10 Ma minimum, round-1 verification measured
    17.4 K and 2.65%, still within the recorded bounds.
- **One datum for v1 families** (a declared limitation, round-2 decision; R4-5). v1 families exist only on the
  3300 kg/m³ / 293.15 K datum, and `family_columns` refuses any other datum, matching both fields exactly. Adding a
  datum to the family request is a later follow-up.
- **Budget.** A request beyond the resource budget (for example N = 30 or 52 at level 3 under 256 MiB) refuses by
  name (`BUDGET_EXCEEDED`). It never escapes as an unnamed error.
- **Containment prefilter.** The `1e-12` margin of the float prefilter in province containment is declared as a
  conservative filter that decides nothing: the exact integer signs decide.
- **Short edges.** Voronoi edges as short as 16 km occur and are reported, not refused (no minimum-edge-length rule).
- **Slab column.** The slab of an F6′ trench uses the oceanic-site plate's ocean column, even where the trench crosses
  continental crust. That is consistent with the rulings, and it is a labelled prior.

**Part B limits (I04b).**
- **Reduced model only.** Every belt result is labelled thin-sheet validity not established: the control's
  `w/H = 1` is outside I01_WEAKENING §8. Peak force, speed and the raw-history width meet 3% between 4 and 8 rows; the
  peak increment does not (7.8%): the original coarse control remains failed
  (`h/ell = 1.25` at 8 rows). The separately predeclared 42/84-row successor above
  satisfies actual `h/ell <= 0.25` and passes all four unchanged 3% comparisons.
  That closes this reduced-model numerical check, not physical thin-sheet validity,
  general mesh-orientation independence or a physical belt-width calibration.
- **Coupled feedback only on the transform, one-sided.** The symmetric belt refuses `unresolved column` at
  interval 2 (non-carrier rows shear every interval; tied to the open splits-1 owner decision); a declared one-sided
  belt on the carrier is required (labelled). Ridge belts refuse at their first coupled interval (beta aliasing on birth
  strips: the midpoint-line deposit, with no exact piece–strip overlap); trench belts refuse already at the start
  balance (the inherited bracket check). On the two-plate lune only the ridge belts' start balance runs. Splits-1
  fragmentation (one sub-cohort per piece from ulp-level differences) is reported and never grouped within a
  tolerance.
- **Orientation independence** is claimed only for aligned belts with beta within tolerance.
- **No heat from dissipation** (v1): the omitted energy's pointwise bound is reported per interval and accumulated.
- **No events**: fully yielded belts only report the CM-07/CM-11 refusal text.
- **The staircase finish rule now has a genuine coupled control.** The owner-authorised
  I03 extension admits the two-record great-circle ridge/transform corner.
  The predeclared C2 manufactured fixture above passes two D1/D2 intervals in plain
  and tilted frames without straightening its offsets. The old oblique ridge is
  not used as a substitute. This admits transform belts on the stated geometry,
  not arbitrary small-circle traces, ridge/trench belts or a generated-world history.
- **The starting family is not yet the coupled route's input**, and New World is not connected (I10).
- **Lode-angle-free oblique belts.** Exactness is claimed only at `c` in `{-1, 0, 1}`.
- **Within-belt GPE** redistribution is omitted and reported as a ratio; the net left/right GPE is D1's.
- **Rate support floor.** The layered belt refuses below about 0.06 mm/yr of relative motion and the single-layer
  belt below about 6.3 mm/yr (the column kernel's rate support).
- **Provenance (v1).** A coupled history must be unbroken (no non-coupled interval after a coupled one, no committed
  I03 topology event); a declared mesh replacement is not replayable and refuses. Replay is exact and re-solves:
  each record is verified once and cached by commit key, so a chain of n intervals costs n coupled solves (13–23 s
  each on the fixtures) with one shared cache, and n(n+1)/2 if each commit is verified with a fresh cache. Nothing
  is persisted, so the first `step` after a reopen replays the whole coupled history from a cold cache: one solve per
  coupled interval (about 1.6 to 2.3 h at the 256-step ceiling). The heat-omission label is carried by the history
  (`omission_labels`), not inside I05's arrays.

## 7. Evidence effects

- Adding three package modules changes the whole-package execution identity.
- At I04a: `i02-workflow-timing-r10` binds the existing package files. Its execution identity is not checked by
  `check_current_evidence.py`, so adding new modules did **not** make that check fail; its staleness was proposed as
  an explicit register reclassification. `i01-finite-admission-r8` was unaffected at I04a.
- **Original integrated delivery (with I05a and I04b):** `check_current_evidence.py` failed both `i01-finite-admission-r8` and
  `i02-workflow-timing-r10`, through I05a's edits to `integration_clock.py`, `integration_ledger.py` and
  `integration_transfer.py` (I04b changes none of them).
- New World `current=True` regeneration of older saves reports `SOURCE_MISMATCH`. Plain loading is unaffected.
- Original receipt bytes have not been rewritten.
- **Part B (I04b)** adds `integration_strength.py` and `integration_feedback.py` and edits `integration_driving.py`,
  `integration_ports.py`, `integration_properties.py` and `integration_material.py`. This changes the whole-package
  execution identity again. The reviewed integration captured successors
  `i01-finite-admission-r9` and `i02-workflow-timing-r11` on 4 October. All five
  finite-admission controls and all seven workflow equality/parity checks passed;
  timings were captured after the other checks had finished. The register
  supersedes r8/r10 without altering their bytes. This renews their declared
  source bindings, not scientific acceptance or spherical D1/D2 performance.

## 8. Sources

**Inherited:**
- the I01 physical contract, closure matrix, GPE, water GPE, elastic core, weakening and transitions method pages;
- the I03 method page;
- the New World structure, thermal and layout pages;
- `i01_transitions_v1.json`'s attribution of alpha = 3e-5.

**Part B (4 October 2026):** all inherited. The I01 contract, closure matrix and weakening method; the closures
check's width metric and nonlocal operator; the package's weakening kernel; the regional-strength Picard criterion;
I03, I04a and I05a. DOP853 is used as I01 uses it (SciPy). No source was newly consulted for Part B.

**Newly consulted (3 October 2026):**
- **Clennett et al. (2023), methods** (R4-5).
- **The ASPECT continental-extension cookbook** (documentation build 3.2.0-pre), for one convention only: inherited
  weakness is kept separate from newly accumulated strain and declared with zone geometry and seed. Nothing else from
  it is used. It is a prescribed-extension Cartesian example, not a starting-state producer, and it is not installed.
