# Finite-region three-dimensional mechanics

Status: WORKING NON-CANON. This is an implemented same-time mechanical solver
and finite-mode force connection, not a generated rift or evolved planet.

## Responsibility and inputs

`atlas_tectonics.regional_execution3d.PreparedRegionalStokes3D` solves an
axis-aligned finite Cartesian box. x and y are horizontal; z increases upward
from the bottom. All three velocity components are solved. The caller supplies
positive viscosity at volume quadrature points, body force, optional retained
symmetric deviatoric extra stress, and velocity or outward traction for every
component on all six faces. One shared nodal velocity trace avoids contradictory
edge/corner copies. Material, frame, datum, parent state, epoch and forcing
identities accompany the arrays. Public inputs and outputs use SI units.

The geometry, viscosity and boundary-condition pattern are fixed in a prepared
plan. Changing them requires a new plan; changing a force can reuse its matrix
and factor. The constitutive producer owns effective viscosity and retained
stress. This solver does not guess geological defaults or reset those histories.

## Equations and discretisation

With D = (grad(u) + grad(u)^T)/2 and supplied extra stress S:

```text
sigma = 2 eta D + S - p I
-div(sigma) = f,             div(u) = 0
outward traction = sigma n
```

The weak momentum equation is
`integral(2 eta D(u):D(v) - p div(v)) = integral(f.v) + integral(t.v) - integral(S:D(v))`.
This includes cross-component derivatives; three independent scalar Laplacians
would be wrong for spatially varying viscosity. Trilinear pressure (Q1) and
triquadratic velocity (Q2) use a regular hexahedral Taylor-Hood mesh, with three
Gauss points per direction. Incompressibility is imposed in the pressure test
space, not claimed to vanish pointwise at every quadrature point. A pressure
jump is not exactly representable by continuous Q1 and needs refinement evidence.

The matrix has velocity block A and divergence block B = -integral(q div(u)).
Prescribed velocities are eliminated without modifying the original equations
used to recover reactions. A volume-weighted pressure-mean constraint is added
only when a constant pressure is genuinely undetermined; that test compares the
pressure leak with the divergence entries themselves, so a small open (traction)
box is never mistaken for a closed one. Incompatible net boundary flux is
refused, not projected away: the net flux must be below `2e-11` of the
integrated absolute normal boundary flux, `integral(|u.n|)` over the six faces,
plus the binary64 rounding bound of the computed sum. A numerical zero mean is not a
physical pressure datum; `physical_pressure_pa` is available only with an
explicit mean pressure or normal-traction conditions that determine it.
Unconstrained rigid translations/rotations are refused rather than hidden pins
being added.

## Solving and safe reuse

Length L, speed V and reference viscosity eta0 define internal units. Stress
scales as eta0 V/L, body force as eta0 V/L^2, integrated force as eta0 V L,
and power as eta0 V^2 L. These are full 3D forces/powers, not per-unit-strike values.
The reference path is GMRES with an incomplete velocity-block factor and a
viscosity-weighted pressure-mass diagonal. A separately selected sparse direct
method supplies small independent comparisons; a failed iterative solve never
silently switches to it. A third method solves the same equations without
assembling the velocity block
([matrix-free multigrid](#matrix-free-multigrid-candidate-i072-solver-scaling));
it faces exactly the gates below. The default, `method='auto'`, chooses multigrid
wherever it has been shown to converge and GMRES elsewhere, for each prepared
operator before anything is reserved
([automatic choice](#automatic-choice-between-gmres-and-multigrid-methodauto));
explicit requests are honoured unchanged. The fixed tolerances are linear relative residual
2e-9, mechanical-work residual 5e-9 and coupled-force residual 5e-8. GMRES asks
for relative tolerance 1e-11 of the right-hand side (absolute tolerance 0, so
SciPy's stopping target is purely relative) and at most 1,200 iterations.

Every gate is relative to its own operands, with no absolute floor, so the
caller's choice of L, V and eta0 cannot make a gate pass by shrinking the
numbers. (Scales still set conditioning: a badly chosen scale can make a solve
refuse, and the forward error of an accepted solve is its backward error times
the conditioning of the scaled system.) The right-hand side is normalised to unit
size before GMRES or the direct solve, so SciPy's internal 2-norms cannot
underflow or overflow. A forced problem whose right-hand side is zero or below
about 1e-281 after scaling is refused, as is nonzero forcing that underflows to
zero in assembly; an exactly unforced problem has the exact zero solution.

In a closed box the zero-mean pressure gauge is enforced exactly after every
solve (the gauge weights sum to one and `B_f^T 1 = 0`, so velocity is
unaffected); no gate would otherwise see a constant in pressure units. When the
velocity is below 1% of the magnitude the load implies (a load-dominated state,
such as full rho*g balanced by pressure), the solution is refined up to twice:
a relative stop on the whole right-hand side otherwise leaves the small driving
velocity inaccurate. If any gate still fails, up to two further working-precision
refinement steps are taken before refusing; fixed-precision refinement is a
standard way to recover componentwise backward stability for an accurate but
badly scaled solve (Skeel's 1980 analysis, cited from background knowledge and
not re-read for this change). A first GMRES solve that does not converge is
refused. A refinement correction that reaches the iteration limit is kept only if
it lowers the worst gate ratio: discarding such corrections refused well-scaled
problems (a buoyant inclusion at contrast 1e4) whose corrected solution passed
every gate. Refinement never changes a gate, and the published solution always
faces all of them. Three linear gates must then all pass:

- the combined relative residual `||K x - rhs||_inf/||rhs||_inf <= 2e-9`;
- the momentum block, row by row: `|r_i| <= 2e-9 (|A||u|)_i + 256 eps (|B^T||p| + |load|)_i`
  on the free rows. Pressure and load enter only at their round-off level
  because in a load-dominated state they cancel; at full weight they admitted
  velocity errors of 1e-5 when rho0 = 3300 drove a density anomaly of 0.01;
- the continuity block, row by row: `|B u + w lambda|_i` against
  `(|B|(|u| + 64 eps/2e-9 U*))_i + w_i |lambda|`, where `U*` is the momentum
  scale divided by the largest free-row sum of `|A|`, the velocity magnitude the
  momentum block implies. Only its round-off share enters: in a hydrostatic state u itself is
  round-off, while a larger share let an inflated pressure-balanced scale hide
  continuity error.

Rows are judged componentwise (Oettli-Prager form), each against its own
magnitudes, because normalising by the largest row let a weak layer's rows go
unchecked: a velocity error confined there was accepted at 2e-5 (viscosity
contrast 1e4) and 1e-4 (contrast 1e6). Rows below 1e-8 of the largest
magnitude are judged at that floor. Blockwise checks matter because one dominant
block can otherwise hide the other inside the combined norm.

A declared physical mean pressure is added to the pressure after solving, and
every gate and the work identity use the zero-mean solution: in a closed box the
datum cannot change velocity, whereas inside the right-hand side a 3 GPa datum
dominated every relative target and let GMRES move the velocity by 2.5e-7, and
inside the gate magnitudes it loosened them. Reactions are then recomputed with
the datum included.

The work identity is a consistency check between the published quadrature
fields and the assembled operators. In exact arithmetic its error equals the
momentum residual weighted by velocity, which the momentum gate already bounds,
so that exact term is subtracted. What remains must be `<= 5e-9` of the larger
side of the power balance (viscous, extra-stress and pressure power against
body, traction and constraint power), never of `max(1, ...)`. For rigid or
exactly balanced states, whose powers are all round-off, the only floor is 64
binary64 units on the magnitudes actually multiplied (`|A||u|`, `|B^T||p|`,
loads and reactions, and a shape-derivative bound for quadrature powers). A
forced solve whose powers underflow to zero or overflow is refused. The identity
detects a mis-scaled or mis-assembled symmetric strain rate (an injected scale
error of 2e-9 or a symmetric-part error of about 1e-7), but it cannot see an
error in the antisymmetric (spin) part of the gradient, in the velocity
interpolated to quadrature points, or in the scaling of the published pressure,
because those enter neither side of the balance it compares. Those outputs rely
on the exact-field and manufactured-solution tests instead.

Before 30 September 2026 (review finding s11-1) GMRES used an absolute tolerance
of 1e-13 and both gates were floored at 1. A problem posed in SI with unit scales
therefore returned velocities 2.6e-4 away from the direct answer, or exactly zero,
while reporting residuals near 1e-14. Intermediate candidates of this repair were
shown by adversarial verification to accept rigid fields with 225-8210% error at
badly chosen scales (combined residual only, with a work floor that absorbed the
residual), to let a datum or a hydrostatic load loosen the gates, to miss
weak-layer errors and to refuse well-scaled problems by discarding an unconverged
correction; the rules above close those cases. Scratch probes on the candidate
(Windows, CPython 3.12.14; not acceptance) found accepted velocity errors of at
most 3.5e-9 over a 430-case sweep of layered, inclusion and random viscosity
contrasts 1e3-1e6 with badly chosen reference viscosities, and 5.0e-9 over 192
lithosphere/asthenosphere solves with full rho*g, extra stress and four boundary
sets. Random-sign errors injected into momentum or continuity rows were accepted
only up to about 1e-10.

The gates bound backward error, not forward error. An adversarial residual that
fills each gate in the worst direction, with refinement disabled, was accepted
with velocity errors of 1.2e-8 in a uniform box and about 2e-9 times the
viscosity contrast in a layered one (1.85e-6 at contrast 1e4). A load-dominated
state has a floor of about eps times the ratio of the load-implied velocity to
the actual velocity, a property of solving the full pressure in binary64 that a
refined direct solve shares: it reaches 1e-8 only when rho0/delta-rho exceeds
about 1e7. Deliberately mis-scaled choices (for example L = 1e-3 m with
eta0 = 1e30) are refused, and GMRES alone refuses some strong-contrast cases
(layered contrast 1e6 at 4x4x4 did not converge) that the direct method solves.

Assembly reuses a sparse structure instead of retaining dense contributions
for every element. Memory is admitted before mesh/factor construction and actual
factor storage is checked afterwards. Admission is an accounting bound, not an
operating-system RSS guarantee. Cell counts 2-24 per direction are interface
limits, not a promise every such grid fits the selected memory budget.
In practice the assembly reservation alone is 8 MiB plus 420,000 bytes per cell
plus 3,000 bytes per velocity unknown (three per Q2 node) and per pressure node,
before the separate factor allowance. For cubes that is about 176 MiB at 7x7x7
and about 257 MiB at 8x8x8. The default GMRES route then reserves an
incomplete-factor allowance of 160 bytes per nonzero of the free velocity block
plus 1,024 bytes per free velocity unknown, so it grows as fewer velocity
components are prescribed. At 6x6x6 the factor allowance is about 85 MiB with all
faces velocity-prescribed, 131 MiB with free-slip faces and 151 MiB with only the
base velocity-prescribed (combined about 200, 246 and 265 MiB); at 7x7x7 even the
all-velocity case needs about 325 MiB. The default 256 MiB budget therefore
refuses every 7x7x7 cube and admits 6x6x6 only for velocity-dominated boundaries
(measured 29 September 2026; an earlier 28 September estimate of 7x7x7 counted
assembly only). The 24x24x24 interface limit would need about 6.9 GB (6.4 GiB)
for assembly alone. Larger grids need an explicitly larger budget and machine;
nothing is subdivided or coarsened automatically. The connected evolution
fixture is 3x3x3. These figures describe the assembled `gmres`/`direct` routes;
the multigrid candidate's admission is described in its own section.
Cancellation, loaded-source identity, single-owner use and closure are checked.
Only the latest immutable result and one finite-mode response are retained;
there is no growing history cache. Caller-retained snapshots remain caller storage.

## Matrix-free multigrid candidate (I07.2 solver scaling)

Status: optimisation candidate reviewed with benchmark/documentation corrections,
now applied in the working tree with the automatic choice below; not yet
accepted. It is used when requested with `method='multigrid'` or chosen by
`method='auto'`. The assembled `gmres` route stays the reference and the
small-case choice; `direct` stays the bounded oracle. Nothing below changes an equation, coefficient, gate,
tolerance, iteration ceiling, output field or pressure-gauge rule.

### Why the assembled route stops scaling

A Q2 velocity row couples a node with every node of the up to eight bricks that
contain it: 81 to 375 nonzeros, about 183 on average in these grids. At 24x24x24
the assembled block alone has 64.7 million entries; the plan then keeps copies
for the free block and the saddle-point matrix, forms `|A|` for the gates on every
solve, and adds an incomplete factor with up to eight times the block's fill.
Memory therefore grows with the stencil width times the unknowns, and the
incomplete factor's strength does not survive refinement. The candidate removes
the assembled velocity block altogether and replaces the incomplete factor with
velocity multigrid. The fine matrix-free action has fixed-stencil work proportional
to the velocity unknowns. The complete preconditioner also factors the continuous
Q1 pressure mass at the finest pressure resolution and applies that sparse LU on
every iteration; its fill, storage and factorisation cost can grow faster than the
pressure unknown count. Scaling evidence for the complete preconditioner is limited
to the bounded grids measured below.

### What the candidate does

- **Operator.** Every brick of the regular mesh has the same shape, so one table of
  reference-element gradients serves the whole box. `A u + B^T p` is evaluated by
  gathering each element's 27 nodes with strided slices, forming
  `2 eta D(u) - p I` at the 27 Gauss points with the supplied point viscosities,
  and scattering back: two dense matrix products per application, with no
  per-element or global matrix stored. The divergence matrix B has no viscosity in
  it and remains the same assembled matrix the reference uses.
- **Gate products.** The scale-invariant gates of the previous section use `|A|`
  with *assembled* entries. Summing element magnitudes instead would be looser:
  the full-stress form has entries whose element contributions cancel in
  assembly. In a 2x2x2 constant-viscosity box, 4,304 assembled entries are
  exactly zero, all of them couplings between different components of nodes
  that share a coordinate plane. The candidate therefore regenerates the assembled
  couplings one node offset at a time (the element contributions to one offset
  are summed, then the magnitude is taken) and never keeps the matrix. `A u`,
  `|A| |u|`, the row sums of `|A|` and the work-identity bound all use these
  assembled entries, so every gate compares exactly the quantities it compared
  before.
- **Preconditioner.** An upper block-triangular preconditioner, one velocity
  approximation per iteration (pressure first, then velocity, as in ASPECT and
  pTatin3D). The Schur complement is approximated by the full 1/eta-weighted Q1
  pressure mass, with eta at the same Gauss points, and solved exactly by a
  sparse factorisation; the reference uses only its diagonal. For the velocity
  block, one V-cycle:
  1. on the Q2 level, matrix-free Chebyshev smoothing of the Jacobi-scaled
     operator: degree 4, interval from 1/15 of an upper eigenvalue bound to that
     bound, where the bound is 1.2 times a 10-step Lanczos estimate frozen at
     preparation;
  2. Q1 on the same bricks. Because Q1 functions are exactly representable in Q2
     inside every brick, the Galerkin product `P^T A P` is exactly Q1 assembly
     with the fine Gauss points and viscosities. It is assembled with the same
     offset-by-offset method;
  3. nested Q1 levels. Along each axis, every other node is kept plus the last
     node, so odd cell counts nest too. The axes with the smallest spacing are
     coarsened first, which is semi-coarsening for flat boxes. Each level is a
     Galerkin product with trilinear interpolation, so high-contrast material
     remains represented on coarse levels;
  4. a sparse factorisation once a level has at most 3,000 unknowns.

  Constrained components are held at zero on every level: a coarse function that
  vanishes on a constrained face interpolates to zero there. All choices are fixed
  at preparation, so the preconditioner is one fixed linear operator.
- **Krylov method.** Flexible GMRES (right preconditioned, so the minimised
  residual is the true one) with restarts of 60 vectors that keep 20 harmonic Ritz
  directions (deflated restarting). Restarting without deflation stalled on sharp
  high-contrast inclusions at Atlas's tolerance. Every cycle ends by recomputing
  the true residual `||b - K x||_2`:
  - when it exceeds twice the recurrence's own estimate (rounding accumulated in
    the deflated basis), the next cycle restarts plainly from the true residual;
  - when the recurrence claims convergence the true residual does not show, the
    next cycle restarts plainly with a tighter inner target.

  The solve aims for `1e-13 ||b||_2`, with the same 1,200-iteration ceiling.
  SciPy's reference GMRES is left-preconditioned and in practice overshoots its
  own 1e-11 target by one to two orders of magnitude. Stopping at 1e-11 or 1e-12
  gave larger forward errors and more refinement solves. Some valid,
  ill-conditioned systems cannot reach 1e-13 in binary64. If two successive
  claims do not halve the true residual, the solve therefore stops at that floor.
  At that stop, and at the ceiling, it counts as converged only if the true
  residual meets the reference's own `1e-11 ||b||_2`, never a looser target.
  Refinement and all the gates are the shared code of the reference route.
- **Changed viscosity.** `with_viscosity(viscosity, material_source=...)`
  prepares a new plan that shares only viscosity-independent structure: mesh
  tables, B, masks, sparsity patterns and transfer operators. Operators, factors,
  caches and identity are new. It is checked against the cells, scaled lengths,
  boundary pattern and method. With `release=True` the old plan is closed first,
  so its storage and reservations are returned before the new plan is admitted.
  The connected evolution now rebuilds through this path for every method. Its
  default `gmres` results are bitwise unchanged, because the reused mesh is
  identical.
- **Admission.** The candidate reserves structure (mesh, B, patterns, transfers,
  level matrices), work (Krylov basis, element and stencil transients, the result
  envelope) and, once the coarse and pressure-mass sizes are known, a factor
  allowance. It refuses if the realised structure or factors exceed what was
  admitted. As before, these are accounting bounds, not an operating-system RSS
  guarantee.

### Evidence from the literature and software

- May, Brown and Le Pourhiet (2015), with the pTatin3D source, is the closest
  precedent: matrix-free Q2 on the fine level, Galerkin coarse operators where
  viscosity varies strongly, Chebyshev-Jacobi smoothing, upper-triangular
  field-split and flexible outer Krylov. Their block-diagonal Q2-P1disc pressure
  mass does not transfer, because Atlas's pressure is continuous Q1. The candidate
  therefore factors the (sparse, well-conditioned) Q1 mass. Tensor-product sum
  factorisation for deformed elements is not needed on identical bricks, where one
  dense product per application is simpler and fast in NumPy. Rediscretised
  coarse levels with averaged viscosity are not used; at 24 cells or fewer per
  axis, Galerkin products on every level are affordable and more robust.
- Clevenger and Heister (2019/2021), with ASPECT's matrix-free Stokes solver and
  deal.II steps 37 and 56, gave the smoother settings adopted here (degree 4,
  smoothing range 15, 10 eigenvalue iterations, safety factor 1.2) and the same
  block order and inverse-viscosity pressure mass. They report that iteration
  growth at high viscosity contrast comes from the Schur approximation rather than
  the velocity multigrid. The scratch tests here agree for bricks of moderate
  aspect ratio; on flat bricks with a viscosity contrast, the pointwise Q2 smoother
  is the weak block instead (see limitations). Adaptive meshes,
  global coarsening and ASPECT's "expensive" inner Krylov solves are not needed
  or used, so the preconditioner stays linear.
- PETSc's PCMG, KSPChebyshev, PCFIELDSPLIT, KSPFGMRES and the ex42/DMStag ex4
  Stokes tutorials confirm the Galerkin and Chebyshev conventions and that a
  flexible method is required when an inner solve varies. The SciPy sources
  confirm that `gmres` is left-preconditioned and that `gcrotmk` is flexible.
  GCROT(30,30) was measured and needed more iterations than the deflated FGMRES
  here.
- MFEM's partial assembly, p-multigrid (ex26) and low-order-refined
  preconditioning (Pazner 2020; Franco et al. 2020) support the Q2 to Q1 step
  that keeps the fine quadrature points. A low-order refined operator was
  considered; p-coarsening was chosen because it is an exact Galerkin product with
  eight times fewer unknowns.
- Rudi, Stadler and Ghattas's (2017) weighted BFBT was evaluated in scratch with
  exact inner solves. On Atlas's closed-box gauge and Dirichlet faces it did not
  beat the full weighted mass, without their boundary treatment. It is not
  adopted; see limitations. Grinevich and Olshanskii (2009) give the spectral
  equivalence of the inverse-viscosity mass. Wathen and Rees (2009) bound the
  diagonally scaled mass, which is why the diagonal alone (condition up to about
  27 for trilinear bricks) was replaced by the full matrix.
- Saad's FGMRES (book section 9.4) was read. Deflated restarting follows Morgan's
  GMRES-DR (2002) and the flexible variant of Giraud, Gratton, Pinel and Vasseur
  (2010); both are cited from background knowledge and were not re-read for this
  change.

### What the checks establish

- The matrix-free operator, divergence, diagonal, assembled-entry gate products
  and the Q1 Galerkin level agree with the assembled matrices to about 1e-15 on
  anisotropic bricks with random viscosity spanning about e^8 and mixed
  boundaries. Interpolation maps constrained faces to zero, and restriction is
  its transpose. The V-cycle is linear to round-off.
- The reference 3D suite is rerun with `method='multigrid'` as the default
  method, at the same tolerances. The exact affine, polynomial, hydrostatic,
  mixed-traction, layered, extra-stress, rigid-motion, small-magnitude,
  net-flux, traction-box, underflow, cache, coupling, face-mask, refusal and
  manufactured-convergence checks then build multigrid plans, and all pass. Checks
  that name a method keep it: the SI-rescaling and mis-scaled-scale checks, the
  same-SI-problem, load-dominated, declared-datum and unconverged-refinement
  comparisons (gmres and direct), and the weak-layer and badly-scaled-contrast
  checks, which inject into the direct factor. Separate multigrid checks cover
  high contrast.
- Further checks compare against the direct oracle to 1e-8:
  - a buoyant 1e4-contrast inclusion, closed and open-top;
  - a flat, semi-coarsened box;
  - a floor-limited, base-only box with cellwise 1e4 contrast (condition about 1e13).

  They also cover changed-viscosity reuse, which is bitwise equal to a fresh
  plan, invalidates the cached result and returns its reservations; mismatched
  reuse; cancellation; refused admission, which returns every reservation; and
  the floor-aware stopping rule. The new module's source and loaded code are
  bound. The plate torque adapter recovers the analytical twist, and the
  evolution consumer selects the candidate and reuses geometry.
- A scratch before/after comparison, not a committed test, ran identical inputs
  through the unmodified and modified trees. The `gmres` and `direct` routes
  published bitwise identical arrays in all 10 cases, which include force
  coupling, extra stress, refinement and load-dominated states, and so did the
  default evolution route. Their descriptors are identical except the package
  execution identity and the `plan_id`/`result_id` derived from it. The evolution
  descriptor adds `mechanics_method`, and its statistics add
  `mechanical_geometry_reuses`.
- An independent adversarial review (scratch) reproduced the gate quantities
  against assembled matrices on odd, anisotropic grids with 1e6 per-point
  contrast. Injected errors were accepted or refused identically by `direct` and
  `multigrid`. It found the defects fixed before delivery: floor-limited cases
  spun to the ceiling, the recurrence drifted after deflation, and a refused
  admission leaked a reservation.

These are implementation and conditioning checks. They are not a geological
calibration, a whole-world speed forecast or an accepted evidence receipt.

### Scratch measurements (30 September 2026; not a receipt)

**Setup.**
- Machine and software: one Windows 11 AMD64 machine (8 cores), CPython 3.12.14,
  NumPy 2.4.6, SciPy 1.17.1.
- Threads: OpenBLAS was imported with 16 threads. Every solver operation ran on
  one thread under the package's native lease.
- Harness: [`tools/benchmark_regional3d_solvers.py`](../tools/benchmark_regional3d_solvers.py),
  one fresh process per case. It ran the unmodified tree's `gmres` and this
  change's `multigrid` on identical inputs, each passing the same fixed gates.
- Cases: `lithosphere` is an open top over free-slip sides, a 1e23/1e20/1e21
  lid, mantle and fault, and a dense blob, on a 2:1 flat brick. `smooth` is the
  manufactured polynomial case with `eta = 1 + x`. `inclusion` is a closed box
  with a buoyant 1e4-contrast weak inclusion.
- Times are seconds. "First" means cold preparation plus the first solve;
  "warm" is the mean of three solves with changed forcing.

| Case, cells per axis | gmres first | multigrid first | gmres warm | multigrid warm | gmres peak working set | multigrid peak working set |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| lithosphere 8 | 2.78 | 1.10 | 1.01 | 0.43 | 410 MB | 175 MB |
| lithosphere 12 | 16.25 | 3.06 | 6.18 | 2.33 | 1,339 MB | 254 MB |
| inclusion 8 | 4.73 | 2.91 | 3.40 | 2.27 | 350 MB | 167 MB |
| inclusion 12 | 68.29 | 10.71 | 60.49 | 9.98 | 1,100 MB | 242 MB |
| smooth 8 | 1.69 | 1.21 | 0.41 | 0.53 | 346 MB | 163 MB |
| smooth 12 | 8.02 | 2.43 | 1.92 | 1.72 | 1,077 MB | 232 MB |
| lithosphere 24 | not admitted | 14.02 | not admitted | 11.68 | not run | 1,162 MB |

**Changed viscosity.** At 12 cells, preparing a changed-viscosity plan fell from
5.8-9.5 s to 0.25-0.34 s. The candidate's reuse path took 0.25-0.26 s; the
assembled route's own reuse saves only about 2%.

**Regressions.** The candidate is slower for small or easy problems:
- warm solves of `smooth` take 48% longer at 4 cells, 14% at 6 and 29% at 8;
- `lithosphere` at 6 cells takes 11% longer;
- first solves at 4 cells take up to 9% longer.

**Forward error against `direct`**, at 3-8 cells, for the three cases plus
layered contrasts of 1e4 and 1e6. The candidate was as or more accurate in 6 of
12 checks. It was less accurate in 5, by factors of 1.1-19 (largest: 1.6e-11
against 8.4e-13 where `gmres` refined), and it solved the 1e6 layered case that
`gmres` refused.

The reviewed comparator preserves pressure offsets whenever traction or a
supplied physical mean fixes the datum; only an undetermined gauge is compared
up to a constant. Four focused regressions cover both datum sources, free-gauge
shifts and a zero reference. The 12 small direct-oracle comparisons were
refreshed after this correction, retaining the outcome counts above. Earlier
forward-error v1 records removed every mean and do not check determined offsets;
the v2 records identify the comparison mode. This correction does not change
solver equations or the retained performance measurements.

**Memory.**
- Admission: the default 256 MiB budget admits the candidate up to about 11
  cells per cube, against 6 for the assembled route.
- Accounting against measurement: the candidate's accounted reservation was at
  least its measured solver-attributable peak private memory at every size
  checked. That peak is the peak after a warm-up plan: 144 MB against 125 MB at
  8 cells, and 1,626 MB against 1,162 MB at 24 cells.
- The assembled route's accounting was below its measured peak at 12 cells:
  2,017 MB against 2,209 MB.

The 24-cell case needs about 16.4 GiB of assembled reservation, so the
reference was not run there.

### Limitations

- **The candidate can refuse inputs the default route accepts.** Examples:
  - 4x4x4 or 2x3x7 boxes with per-point, log-uniform viscosity spanning 1e6;
  - isotropic boxes with many 1e6-contrast inclusions;
  - flat bricks (element aspect of about 20 or more) with a 1e3 viscosity
    contrast.

  In the first two cases the true residual stalls near 1e-9, above the
  reference's 1e-11. The inverse-viscosity mass Schur approximation is too weak
  there, and a boundary-aware weighted BFBT is the next candidate. On flat
  bricks the pointwise Q2 Chebyshev-Jacobi smoother with Q2-to-Q1 coarsening
  loses its effect; a line smoother along the thin axis would be needed.
  Semi-coarsening acts only on nested Q1 levels above 3,000 unknowns. Such
  refusals are visible (`3D FGMRES-DR did not converge`), never wrong output.
  The default `gmres` route remains the choice for these materials.
- With a sharp 1e4 inclusion, iterations still grow with resolution: about 680
  at 12 cells and 690 at 16.
- Some small problems are faster with the assembled reference. The
  [automatic choice](#automatic-choice-between-gmres-and-multigrid-methodauto)
  keeps `gmres` for boxes with fewer than 4 cells along an axis and accepts the
  workload-dependent losses at 4^3. Its measurements below distinguish the
  29-workload sample from the larger losses in separate noisy-viscosity probes.
- Element loads, field evaluation and boundary tractions still run per brick in
  Python (the reference code). They cost under a second per solve at 24 cells.
- Scratch measurements only, on one Windows machine with single-threaded BLAS.
  Linux and other BLAS builds are unmeasured, and no evidence receipt has been
  captured for this candidate.

## Automatic choice between gmres and multigrid (`method='auto'`)

Status: implemented and focused-tested on 30 September 2026. Not yet reviewed
or accepted. `auto` is the default for new plans and new 3D evolution runs.
Explicit `gmres`, `direct` and `multigrid` requests are honoured exactly as
before. The choice never changes an equation, coefficient, gate, tolerance,
iteration ceiling, output field or pressure-gauge rule.

### What it does

Before anything is reserved, an `auto` plan reads a few workload features and
predicts both methods' complete memory reservations. It then applies selection
policy `atlas.regional3d-solver-selection.v2` and prepares the chosen method in
the ordinary way. Nothing is solved or timed to decide. A decision took 0.3-1.4
ms in the measured runs, against preparations of 0.2-10 s.

**The rule (multigrid first).**
1. *Admission.* Each method's complete reservation is predicted with the
   formulas that method itself reserves with. Focused tests check that the
   prediction equals the actual peak reservation for both methods.
   - If neither method fits the budget's available bytes, the plan is refused
     with `MemoryLimitError` before anything is reserved. No limit is raised.
   - If only one fits, it is chosen.
2. *Multigrid inside its shown range.* Multigrid is chosen when the workload lies
   where it has been shown to meet every gate:
   - viscosity contrast (max/min over all Gauss points) at most 1e5 with brick
     aspect ratio (largest over smallest spacing) at most 2, or contrast at most
     1e3 with aspect at most 4;
   - at least 4 cells along every axis.
3. *Otherwise the assembled route.* `gmres` is used outside that range. If only
   multigrid fits the budget there, multigrid is used and the record says it is
   outside its shown range. Its failure mode is a visible refusal
   (`3D FGMRES-DR did not converge`), never a wrong answer.

The plan definition records `requested_method: "auto"`, the resolved `method`
and a `solver_selection` record, so all three enter `plan_id` and every
published result. The record holds the policy, the features, the admission
predictions, the reason and any out-of-range reasons. `plan.method`,
`plan.requested_method` and `plan.solver_selection()` expose the same.

`with_viscosity` on an `auto` plan decides exactly as a fresh plan with the same
selection allowance would, and
the rebuilt plan has the same `plan_id`. It shares preparation only when the
method is unchanged, and releases the old structure otherwise. There is no retry
or fallback: a refused or unconverged solve is reported exactly as for an
explicit method.

The decision depends only on the inputs, the budget and the policy, not on the
machine or timings. A 3D evolution plan records `mechanics_method`, and for
`auto` the policy version and admitted-method mask established after fixed
preparation and allowance for the advance workspace. Evolution pins that
admission context across rebuilds: later shared-budget pressure may refuse an
actual reservation, but does not silently reroute. A reopened plan with a
different method, policy or admission mask refuses the state. Different byte
limits admitting the same methods are compatible; raw free-byte counts are not
part of the identity. To continue a run, pass its recorded `mechanics_method`
and use a budget supporting the same admission choices. States from before
this change are refused because the package's execution identity changed.

### Why multigrid first

An earlier, cost-predicting version of this rule was calibrated on three
workloads and then tested on held-out ones. It never chose multigrid where
multigrid was slower, but it kept gmres where multigrid was faster in 17 of 29
measured workloads, by up to about ten times. The measurements support a simpler
rule.
- On all 29 workloads multigrid met every gate. The workloads covered 4^3 to
  16x16x8 cells, contrasts from 1 to 1e4, closed and open boxes, and layered,
  inclusion, plume, slab, rift and multi-body structures.
- Multigrid was faster or within 3% in 27 of them.
- Always choosing it took 177.8 s in total. The faster method for each workload
  took 177.5 s together, and gmres 752.8 s.

These totals cover this 29-workload sample. The range-edge probes below are
separate and are not included in that aggregate.

Measured with this rule on the same 29 workloads:
- one Windows 11 AMD64 machine, CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1, one
  BLAS thread;
- one fresh process per run;
- totals are preparation, the first solve and three warm solves;
- gmres and multigrid were run explicitly, and auto is its own run.

These are scratch measurements, not an evidence receipt.

| Workload | Cells | auto chose | gmres (s) | multigrid (s) | auto (s) | auto vs gmres | auto vs multigrid | Slower choice |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| smooth | 4x4x4 | multigrid | 1.03 | 1.22 | 1.24 | -0.21 (-21%) | -0.02 (-2%) | yes |
| smooth | 6x6x6 | multigrid | 1.53 | 1.46 | 1.46 | +0.07 (+5%) | -0.00 (-0%) | no |
| smooth | 8x8x8 | multigrid | 2.89 | 2.74 | 2.75 | +0.14 (+5%) | -0.00 (-0%) | no |
| smooth | 10x10x10 | multigrid | 6.45 | 4.56 | 4.62 | +1.83 (+28%) | -0.05 (-1%) | no |
| smooth | 12x12x12 | multigrid | 13.41 | 7.30 | 7.37 | +6.05 (+45%) | -0.07 (-1%) | no |
| lithosphere | 4x4x4 | multigrid | 1.34 | 1.33 | 1.31 | +0.04 (+3%) | +0.03 (+2%) | no |
| lithosphere | 6x6x6 | multigrid | 2.25 | 2.16 | 2.14 | +0.11 (+5%) | +0.02 (+1%) | no |
| lithosphere | 8x8x8 | multigrid | 5.66 | 2.38 | 2.36 | +3.30 (+58%) | +0.02 (+1%) | no |
| lithosphere | 10x10x10 | multigrid | 13.72 | 3.41 | 3.42 | +10.31 (+75%) | -0.01 (-0%) | no |
| lithosphere | 12x12x12 | multigrid | 33.42 | 9.89 | 9.91 | +23.51 (+70%) | -0.02 (-0%) | no |
| inclusion | 4x4x4 | multigrid | 4.00 | 2.69 | 2.71 | +1.29 (+32%) | -0.02 (-1%) | no |
| inclusion | 6x6x6 | multigrid | 6.26 | 4.33 | 4.29 | +1.97 (+31%) | +0.04 (+1%) | no |
| inclusion | 8x8x8 | multigrid | 15.69 | 9.71 | 9.48 | +6.21 (+40%) | +0.23 (+2%) | no |
| inclusion | 10x10x10 | multigrid | 32.18 | 11.46 | 11.04 | +21.14 (+66%) | +0.42 (+4%) | no |
| inclusion | 12x12x12 | multigrid | 233.38 | 40.45 | 39.69 | +193.69 (+83%) | +0.76 (+2%) | no |
| shear (held out) | 4x4x4 | multigrid | 1.12 | 1.15 | 1.14 | -0.03 (-2%) | +0.01 (+1%) | yes |
| shear (held out) | 8x8x8 | multigrid | 4.59 | 1.68 | 1.67 | +2.92 (+64%) | +0.01 (+1%) | no |
| shear (held out) | 12x12x12 | multigrid | 22.17 | 3.51 | 3.51 | +18.66 (+84%) | -0.00 (-0%) | no |
| plume (held out) | 5x5x5 | multigrid | 1.70 | 1.24 | 1.25 | +0.45 (+26%) | -0.01 (-1%) | no |
| plume (held out) | 8x8x8 | multigrid | 7.26 | 1.79 | 1.78 | +5.47 (+75%) | +0.00 (+0%) | no |
| plume (held out) | 12x12x12 | multigrid | 36.54 | 3.91 | 3.90 | +32.64 (+89%) | +0.01 (+0%) | no |
| layered1e4 (held out) | 12x12x12 | multigrid | 17.93 | 4.44 | 4.42 | +13.51 (+75%) | +0.01 (+0%) | no |
| ramp (held out) | 8x8x8 | multigrid | 7.39 | 3.25 | 3.24 | +4.15 (+56%) | +0.00 (+0%) | no |
| ramp (held out) | 12x12x12 | multigrid | 89.14 | 12.43 | 12.19 | +76.96 (+86%) | +0.24 (+2%) | no |
| slab (held out) | 8x8x4 | multigrid | 3.00 | 2.00 | 1.97 | +1.03 (+34%) | +0.03 (+1%) | no |
| slab (held out) | 12x12x6 | multigrid | 17.71 | 6.85 | 6.86 | +10.85 (+61%) | -0.01 (-0%) | no |
| slab (held out) | 16x16x8 | multigrid | 133.20 | 11.88 | 12.22 | +120.97 (+91%) | -0.34 (-3%) | no |
| blobs (held out) | 8x8x8 | multigrid | 6.31 | 4.43 | 4.50 | +1.81 (+29%) | -0.07 (-2%) | no |
| blobs (held out) | 12x12x12 | multigrid | 31.50 | 14.09 | 14.34 | +17.16 (+54%) | -0.24 (-2%) | no |


| Method | Total (s) |
| --- | ---: |
| auto | 176.8 |
| multigrid | 177.8 |
| faster method for each workload | 177.5 |
| gmres | 752.8 |

auto chose the slower method (by more than 2%) twice, both at 4^3: smooth by
0.21 s and shear by 3%. Its first decision in each process took 0.3-1.4 ms.

Accuracy: both methods pass the same backward-error gates, so neither is less
accurate by Atlas's acceptance standard. Their forward errors against the direct
oracle differ in both directions:
- in 12 small checks, multigrid was as accurate or better in 6;
- it was less accurate in 5, by factors of 1.1-19, the worst being 1.6e-11
  against 8.4e-13;
- it solved one 1e6-contrast layered case that gmres refused.

Where multigrid is slower:
- in the 29-workload, four-solve sample, smooth 4^3 took 1.22 s against
  1.03 s for gmres; the separate auto run took 1.24 s, a 0.21 s loss;
- the separate noisy-viscosity probes show larger losses for preparation plus
  two solves: `random@c5` at 4^3 took 2.37 s against 0.97 s (1.40 s, about
  144% longer), and `random@c4` took 1.62 s against 0.91 s (0.71 s, about
  78% longer). Auto selects multigrid for both;
- repeated solves of easy closed-box problems can erase the preparation
  savings. The warm-solve regressions are reported in the scratch measurements
  above; the four-solve aggregate does not establish the total cost for an
  arbitrary number of solves on the same operator.

The rule accepts these workload-dependent losses in exchange for large gains elsewhere and a
decision that needs no timing calibration.

### How the range was set

The limits come from a probe of their edges, in the same way:
- preparation, the first solve and one warm solve;
- both methods run explicitly;
- "refused" means the solve did not converge and published nothing.

`base@cX` rescales a workload's viscosity to contrast 10^X. `base@aX` makes its
bricks X times flatter. `random@cX` is a closed box with point-by-point random
viscosity.

| Case | Cells | Contrast | Aspect | gmres | multigrid | auto chooses |
| --- | --- | ---: | ---: | --- | --- | --- |
| random@c3 | 4 | 1e3.0 | 1 | 0.88 (112 it) | 1.24 (131 it) | multigrid |
| random@c3 | 8 | 1e3.0 | 1 | 4.88 (348 it) | 2.27 (145 it) | multigrid |
| random@c4 | 4 | 1e4.0 | 1 | 0.91 (152 it) | 1.62 (251 it) | multigrid |
| random@c4 | 8 | 1e4.0 | 1 | 6.30 (483 it) | 3.40 (270 it) | multigrid |
| random@c5 | 4 | 1e5.0 | 1 | 0.97 (214 it) | 2.37 (475 it) | multigrid |
| inclusion@c5 | 8 | 1e5.0 | 1 | refused: did not converge | refused: did not converge | multigrid |
| inclusion@c6 | 8 | 1e6.0 | 1 | refused: did not converge | refused: did not converge | gmres |
| blobs@c4 | 8 | 1e4.0 | 1 | 10.67 (1105 it) | 5.80 (529 it) | multigrid |
| blobs@c5 | 8 | 1e5.0 | 1 | refused: did not converge | refused: did not converge | multigrid |
| layered1e4@c5 | 8 | 1e5.0 | 1 | refused: did not converge | 2.46 (169 it) | multigrid |
| lithosphere@c5 | 8 | 1e5.0 | 2 | 27.77 (1786 it) | 2.96 (216 it) | multigrid |
| lithosphere@a4 | 8 | 1e3.0 | 4 | 3.20 (123 it) | 1.77 (89 it) | multigrid |
| lithosphere@a4 | 12 | 1e3.0 | 4 | 20.44 (169 it) | 6.92 (159 it) | multigrid |
| lithosphere@a8 | 8 | 1e3.0 | 8 | 2.76 (117 it) | 2.98 (217 it) | gmres |
| lithosphere@a20 | 8 | 1e3.0 | 20 | 2.68 (148 it) | 9.54 (904 it) | gmres |
| plume@a4 | 8 | 1e2.1 | 4 | 3.58 (152 it) | 1.32 (39 it) | multigrid |
| plume@a4 | 12 | 1e2.2 | 4 | 20.37 (172 it) | 2.84 (43 it) | multigrid |
| plume@a8 | 8 | 1e2.1 | 8 | 3.12 (156 it) | 1.66 (75 it) | gmres |
| shear@a4 | 8 | 1e0.0 | 4 | 2.26 (60 it) | 1.20 (27 it) | multigrid |
| shear@a8 | 8 | 1e0.0 | 8 | 2.05 (58 it) | 1.38 (46 it) | gmres |

- **At contrast 1e5,** multigrid never failed where gmres succeeded.
  - It alone solved the layered case, and it was 9 times faster on the flat
    lithosphere case.
  - Both failed the sharp inclusion and the multi-blob case.
  - gmres was faster only on the tiny random box.
- **At 1e6,** earlier checks found each method failing cases the other solves:
  - multigrid fails random point-by-point and many-inclusion fields;
  - gmres fails a layered one.

  gmres, the reference, stays the choice there.
- **Flatter bricks:**
  - with 4:1 bricks and contrast up to 1e3, multigrid was 1.8-7 times faster;
  - at 8:1 it was slower on the lithosphere case, with its iterations rising;
  - at 20:1 it was 3.6 times slower.

  Contrasts above 1e3 in bricks flatter than 2:1 were not probed, so gmres is
  used there.

### What the checks establish

`tests/test_regional_solver_selection3d.py` checks:
- **Admission.** On several grids and boundary sets, the predicted admission
  bytes equal both methods' actual peak reservations.
- **Routing.** Plans route inside and outside the range; memory decides when
  only one method fits; the plan is refused when neither fits, with nothing
  reserved.
- **Explicit methods** are honoured and unrecorded.
- **No fallback.** A failed multigrid preparation is not retried with gmres.
- **Bitwise equality.** An auto plan publishes arrays bitwise identical to the
  method it resolved to.
- **Changed viscosity.** A changed-viscosity plan has the same `plan_id` as a
  fresh plan, and switches method when the range is left. It reuses geometry
  only within a method, and its results are bitwise equal to a fresh plan's.
- **Cancellation** returns every reservation.
- **Evolution.** Recording, counting, and refusal of mismatched saved states.

The existing mechanics, element, evolution, plate-coupling and multigrid suites
pass with `auto` as the default. A scratch comparison with the reviewed
multigrid candidate found every array from explicit `gmres`, `direct` and
`multigrid` bitwise identical.

### Limitations

- **Evidence base.** The range and the timings come from one Windows machine.
  The limits are where multigrid has been shown to converge, not where it stops
  converging. Inputs outside them may well work, but gmres is used there.
- **Knife-edge at the limit.** A viscosity field that drifts across the
  contrast limit during an evolution switches method at that step. That is safe
  and recorded.
- **Performance losses depend on the workload.** The separate noisy-viscosity
  probes include a 1.40 s (144%) loss at 4^3, and repeated solves can outweigh
  cheaper preparation. The 29-workload aggregate is not a bound on these losses.
- `direct` is never chosen automatically.

## Force-driven connection

`solve_force_coupled` accepts one to twelve declared boundary displacement modes.
A mode in metres multiplied by its unknown rate in 1/s gives velocity. Its
conjugate force has units joules (a rotation mode gives torque); force times
rate gives watts. Solving each independent mode gives a regional resistance
matrix. The same regional matrix and factor serve the whole calculation.

The connection solves regional reaction plus explicitly separate exterior
resistance against supplied driving forces. More resistant material therefore
changes the resulting motion; regional speed is not just prescribed and then
reported as force-driven. The exterior contribution must not duplicate physics
inside the box. Reciprocal work, independent resisting modes and the final
force residual are checked. Regional reactions are forces applied to the region;
the equal-and-opposite force acts on the surrounding plates.

The adapter below now maps actual Euler plate modes into one declared region
and returns its torques. Assembling many regions and accepting one shared
world state still belong to I04/I07/I09. Transport, nonlinear constitutive iteration,
surface motion, thermal history and physical boundary birth remain separate
connections, not implicitly supplied by a linear mechanical solve.

### Planet-centred plate motion and returned torques

[`PreparedPlateBoundary3D`](../tools/regional_plate_coupling.py) connects existing
native `PrescribedPlateMotion` records to this solver. The caller supplies a
stationary, right-handed orthonormal local frame Q, a planet-centred origin r0
and one owner for each plate-controlled velocity node. With column-vector notation:

```text
r = r0 + Q x
u_local = Q^T (omega_global cross r)
torque_on_region = sum_owned_nodes r cross (Q reaction_local)
torque_on_plate = -torque_on_region
power_into_region = omega_global dot torque_on_region
```

All three components are retained, including the contribution from the actual
planet-centred origin. Plate ownership requires three prescribed velocity
components; partially constrained or interior nodes cannot masquerade as full
plate control. Unowned fixed supports have separate, explicit velocities. Their
reactions are not attributed to plates. Corner nodes have one owner, not one per
face. Tractions remain separate native inputs, not a second copy of plate drag.

Prescribed solves check plate order, global frame, epoch, time and native motion
provenance. Force-driven solves use all three Cartesian angular components for
each of one to four plates (the native twelve-mode limit), full supplied external
torques and an explicit exterior resistance matrix. No axis is silently locked
or discarded. The returned immutable exchange binds the mechanical snapshot,
mapping/source identity, angular rates, both torque signs and each plate's power.
The native conditioning, incompatible-flux and conservation refusals still apply;
a geometrically small or insufficiently resisted rotation can be inadmissible.

In a closed box without a declared mean pressure, the pressure is known only up
to a constant c, and c shifts the torque projected on each plate mode by
`-c` times that mode's net boundary flux. Totals and flux-free generalized forces
stay gauge-free and the native snapshot still publishes
`velocity_constraint_reaction_n` with `physical_pressure_defined=False`. The
adapter therefore refuses per-plate torques in that case unless every owned
plate mode is net-flux neutral (`1^T B m = 0`, tested with the closed-box flux
tolerance and recorded as `mode_net_flux_neutral`). Before 30 September 2026
(review s11-2) such torques were published as if the mean pressure were zero; in
the test box a 1000 Pa constant moves them by 39,000 and 18,000 N m. Declaring a
physical mean pressure, or traction faces, makes them physical.

The torque is the transpose of the same discrete velocity map acting on the
native nodal reactions. It therefore preserves virtual work without interpolating
stress onto another boundary or multiplying integrated nodal forces by area again.
Prepared displacement modes and the native factor/response are reused; no large
mechanical result is duplicated by the exchange wrapper. An explicit adapter
buffer allowance is separate from the native solver budget and is not an RSS cap.

This is an explicit flat-box embedding of instantaneous Euler velocities, **not
a curved spherical mesh, moving reference frame, automatic plate ownership,
regional time step or planetary assembly**. Domain curvature and evolution must
be handled by their owners before this becomes a world-scale calculation.

Focused tests independently check the cross-product mapping, multiple owners,
rotated axes and planet-scale offsets. An exactly representable twisting column
has nonzero strain: on a 2 by 3 by 4 m box with viscosity 2 Pa s and angular speed
0.5 rad/s, its plate torque is 1.625 N m and mechanical power 0.8125 W.
Both prescribing that rotation and solving for it from torque recover the same
analytical answer. Invalid ownership/frames/time, overflow, cancellation and source
drift are refused. Repeated torque solves retain one factor and reuse the response.
These are synthetic implementation controls, not geological calibration.

## What checks establish

The element tests independently check interpolation, derivatives, symmetry,
full-stress assembly, quadrature, interface loads, traction work and cancellation.
The prepared-solver tests use exact affine, genuinely 3D heterogeneous, hydrostatic,
mixed-traction and layered-shear solutions; retained extra stress; dimensional
rescaling; direct/iterative agreement; and a non-polynomial refinement case.
Scale controls solve one heterogeneous problem at load amplitudes 1 to 1e-14 and
one SI problem under length scales 1e-3 to 1e5 m: GMRES must match the direct
oracle to 1e-9 or be refused. A 5% net inflow into a closed box must be refused
with unit and physical scales alike, and a small traction box must not acquire a
pressure gauge. A scratch sweep of 64 scale combinations on two boundary types
found 28 accepted wrong answers before the change and none after; badly
conditioned choices (dimensionless viscosity 1e-9 with an open top) are refused.
Further controls cover rigid translation, rotation and boundary shear at badly
chosen scales (accurate to 1e-8 or refused), a 3 and 10 GPa pressure datum
(velocity unchanged to 1e-9, pressure shifted by the datum) and underflowing
forcing or power (refused, not published as zero). A rho0 = 3300 load driving a
0.01 density anomaly must give the anomaly's velocity to 1e-8 with either method
(baseline GMRES was 8.6e-6 away); a momentum-row error confined to a weak layer
(contrast 1e4) must be refused when refinement cannot repair it and repaired when
it can; a reference viscosity at the weak end of a 1e5-1e6 contrast must, with
the direct method at 4x4x4, be refined to an accurate solution rather than
refused; and a buoyant weak inclusion (contrast 1e4) whose GMRES correction
reaches the iteration limit must be accepted and match the direct solution to 1e-8.
Force-driven controls change viscosity and driving force against an analytical
response. Refusal and reuse tests cover net flux, source changes, resources,
mutable inputs and pressure assumptions. These check implementation and bounded
resolution, not calibration against a geological event.

The separate Local Generator Engineering chat supplied independently derived
smooth-polynomial and layered pressure-jump cases. They are prospective continuum
checks, not published benchmark data or an executed cross-code comparison.
In particular, the pressure-jump case must not be required to fit continuous Q1
exactly. This delivery retains an exactly representable layered-shear control.

`tools/check_regional3d.py` records exact-field controls and cold/prepared/cache
timings with source bindings; refinement is checked in the focused tests.
Its matched outputs and admitted workload matter:
a small-grid reuse percentage is not a whole-planet runtime forecast. Old W07
and W10 receipts are not rebound or promoted by these new checks.

## Research and software checked

- [FEniCSx Stokes demonstration](https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_stokes.html):
  Taylor-Hood spaces, pressure nullspace and block solution. Its pressure-sign
  convention is explicitly different; Atlas retains sigma = viscous - p I.
- [ASPECT numerical methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/numerical-methods.html):
  stable mixed elements, block preconditioning and resolving different length
  scales. Atlas has not acquired ASPECT's adaptive/distributed implementation.
- [PETSc DMStag example 4](https://petsc.org/release/src/dm/impls/stag/tutorials/ex4.c.html):
  an actual 3D variable-viscosity Stokes implementation, dimensional scaling and
  pressure-nullspace handling; not the finite-element backend used here.
- [Bleyer's consistent reactions](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html):
  recover forces from the original weak residual. The example concerns elasticity;
  its virtual-work principle informs the reaction calculation, not a rock law.
- [SciPy sparse LU](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html):
  factor reuse and sparse storage for the explicitly bounded direct comparison.
- [pyGPlates velocity calculation](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities):
  rotation-derived global velocities and explicit local-coordinate conversion
  informed the adapter. Atlas consumes instantaneous SI Euler rates, not a finite
  stage rotation or pyGPlates' geological-time unit convention. Bleyer's reaction
  example above also informed the work-preserving torque return.

### Consulted for the multigrid candidate (30 September 2026)

Read in full or in the named parts:

- [May, Brown and Le Pourhiet (2015)](https://jedbrown.org/files/MayBrownLePourhiet-ScalableMatrixFreeMultigridPreconditionerFEHeterogeneousStokes-2015.pdf)
  (author-hosted copy of the CMAME article, whole text) and their
  [SC14 pTatin3D paper](https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf);
  the [pTatin3D source](https://bitbucket.org/ptatin/ptatin3d) at 74d0760 (tensor
  operator, matrix-free diagonal, multigrid level types, scaled pressure mass,
  default solver options and the user manual's solver chapter).
- [Clevenger and Heister, arXiv 1907.06696 v4](https://arxiv.org/abs/1907.06696)
  (whole text), [ASPECT's matrix-free Stokes solver](https://github.com/geodynamics/aspect)
  at 94d1a22 (`stokes_matrix_free*.cc`, `block_stokes_preconditioner.h`, parameters),
  and deal.II [step-37](https://dealii.org/current/doxygen/deal.II/step_37.html),
  [step-56](https://dealii.org/current/doxygen/deal.II/step_56.html) and
  `PreconditionChebyshev`.
- PETSc sources and manual pages for PCMG, KSPChebyshev, PCFIELDSPLIT, KSPFGMRES,
  KSPGCR and PCJACOBI, and the [ex42](https://petsc.org/release/src/ksp/ksp/tutorials/ex42.c.html)
  and DMStag ex4 Stokes tutorials; SciPy's `gmres` and `gcrotmk` sources and pages.
- MFEM: [Anderson et al. (2021)](https://arxiv.org/abs/1911.09220),
  [Pazner (2020)](https://arxiv.org/abs/1908.07071),
  [Franco et al. (2020)](https://arxiv.org/abs/1910.03032),
  [Pazner, Kolev and Camier (2023)](https://arxiv.org/abs/2210.12253), and the
  `ex26`, Chebyshev smoother, transfer, elasticity partial-assembly and `lor_elast`
  sources.
- [Rudi, Stadler and Ghattas (2017)](https://arxiv.org/abs/1607.03936) (whole
  text); Grinevich and Olshanskii (2009) (author copy, whole text);
  [Wathen and Rees (2009)](https://www.cs.ox.ac.uk/files/1540/NA-08-14.pdf);
  Wathen's 2015 Acta Numerica preprint (mass scaling, block and flexible
  sections); Burstedde et al. (2009, 2013), solver sections; Saad, *Iterative
  Methods for Sparse Linear Systems*, 2nd ed., section 9.4; the Ifpack2 guide's
  Chebyshev section.

Not read here: the Wiley version of Clevenger and Heister (HTTP 403; the arXiv
text was used), May and Moresi (2008) (abstract only), Adams et al. (2003) and
Wathen (1987) (paywalled; known through citing papers), and Saad (1993) and
Elman, Silvester and Wathen (known through the sources above). Morgan (2002) and
Giraud, Gratton, Pinel and Vasseur (2010) are cited from background knowledge.

The implementation is original Atlas code. These sources explain method choices;
they are not claims that their software was installed or benchmarked locally.

### Consulted for the automatic choice (30 September 2026)

- ASPECT's `source/simulator/parameters.cc` at 94d1a22 (the local copy read for
  the candidate): its default Stokes solver type picks geometric multigrid when
  the model supports it and algebraic multigrid otherwise, and it first tries a
  bounded number of cheap GMRES iterations before switching to the expensive
  preconditioner. Atlas's rule has the same shape as that default (multigrid
  where it is known to work), but not the runtime escalation: it decides before
  preparing anything and never retries a failed solve with the other method.

No other paper or program was consulted for the choice. The rule, its
measurements and its held-out and probe workloads are Atlas's own.
