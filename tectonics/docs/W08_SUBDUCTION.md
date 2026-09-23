# W08 Step 4: prescribed subduction and mantle wedge

WORKING NON-CANON. Implementation and bounded comparison record, not a change to
the frozen [W08 design](W08_REGIMES.md) or held R4.4 acceptance.
Step 4 remains IN_PROGRESS until its recorded numerical/source gates are met.

## Source decision before execution

The corrected [adapter fixture](../cases/w08_subduction_r2.json) identifies the later
xFieldstone natural thermal outflow operator explicitly: `k grad(T).n = 0`.
Advective heat export remains. The original2008 phrase "zero curvature" is not
silently interpreted as this Neumann condition, second-normal derivative zero
or Laplacian zero. Original contributor code was not accessible. Consequently,
**original2008 source-exact acceptance remains BLOCKED_SOURCE_ADAPTER**, even if
an engineering comparison happens to meet its unchanged numerical targets.

The 45-degree corner-flow adapter is resolved independently from the biharmonic
Stokes solution. In paper coordinates (x right, y down), shift the origin to
(50,50) km and let alpha=pi/4, theta=atan2(y-50,x-50), r=hypot(x-50,y-50).
With d=alpha^2-sin(alpha)^2, unit slab speed gives

    A = alpha*sin(alpha)/d
    C = -(sin(alpha)-alpha*cos(alpha))/d
    f = A*(sin(theta)-theta*cos(theta)) + C*theta*sin(theta)
    psi = r*f
    ux = fprime*cos(theta) + f*sin(theta)
    uy = fprime*sin(theta) - f*cos(theta).

These satisfy stationary-lid and full slab-velocity traces. The apex has no
unique point limit; analytic evaluation there refuses. Computed wedge elements
use a stationary apex node and a shrinking numerical first-edge approximation,
not an invented finite physical coupling ramp. Both far-field velocity components
are prescribed for case1b, as the original paper specifies. A zero-mean pressure
constraint accompanies that all-velocity case. Other computed cases prescribe
both components of zero total traction and therefore have no extra pressure gauge.

The original frozen Atlas design also had a diagnostic indexing error. The
paper's one-based T_ij is at (6*(i-1),6*(j-1))km, independently confirmed by its
Table4 coordinate examples. Slab RMS therefore samples0..210km; the78 wedge
points occupy54..120km. Adapterr2 corrects this measurement definition explicitly.
The [r1 fixture](../cases/w08_subduction.json), frozen parent design and failed
comparison remain preserved; PGC reference temperatures and2C/1C gates are unchanged.

## Numerical implementation

- Separate convex slab, lid and wedge triangulations share verified exact interface
  partitions. Positive-area P2 triangles and a continuous temperature field do not
  blend slab/lid/wedge velocities. Grading concentrates resolution near boundaries;
  omitted vertices, inconsistent interfaces and inverted triangles refuse.
- P2/P1 Taylor-Hood Stokes mechanics uses the full symmetric-strain weak operator.
  Case1b boundary normal flux is conservatively projected into its P2 trace.
  Direct saddle LU was rejected after excessive realised fill; the replacement
  uses separate velocity-block and weighted-BFBT pressure-Poisson factors, not a
  higher memory cap. Outer equation equilibration retains the physical equations.
  Original-unit momentum and continuity block backward errors, pressure mean and
  total relative residual must each meet 1e-10. Rowwise errors remain diagnostic;
  a zero-flow row cannot supply a meaningful relative denominator. Defect solves
  do not request precision below original scaled floating-point round-off.
  The pressure-mass preconditioner failed real high-contrast creep cases; BFBT
  instead applies the published two-Poisson-solve commutator matrix-free. Positive
  sqrt(viscosity)-weighted P2 mass uses elementwise diagonal scaling, explicitly
  an HRZ-style discretisation adaptation: ordinary P2 row sums have zero vertex
  weights. No empirical boundary damping or full saddle factor is hidden.
  Natural-boundary solves also correct their round-off-scale global flux mode
  through the same velocity block and a uniform pressure increment, then recheck
  both original equations. This is not a thermal boundary-flux redistribution.
- Steady P2 heat transport is solved directly, with conservative weak advection,
  separate advective boundary flux and consistent SUPG including the quadratic
  diffusive Laplacian. Degree-six triangle quadrature and sixth-order edge Gauss
  quadrature are explicit. No temperature marching to100Myr is required.
- Heat transport uses a separate locally divergence-free P2 velocity, obtained
  from the curl of a continuous cubic streamfunction fitted in L2. Boundary
  normal traces are retained; tangential traces and the mechanical velocity are
  not silently replaced. Analytic-flow boundary potential is supplied explicitly.
  This fixes constant-temperature and Celsius/Kelvin reference consistency:
  weak P1 mechanical incompressibility alone was insufficient for P2 heat tests.
- Diffusion/dislocation creep uses the separately specified published laws and
  harmonic viscosity cap in logarithmic arithmetic; zero strain uses the finite
  cap limit. Nonlinear updates retain the same fixed point and have a finite
  convergence bound. Depth-three type-II Anderson acceleration acts on log
  viscosity with regularisation, half relaxation and a true next-map residual
  safeguard. A worsening proposal returns to its saved Picard update. The limits
  remain 200 maps, 1e-4 K temperature change and 1e-7 log-viscosity residual.
  Changed coefficients invalidate numerical factors.
- `PreparedSubduction` owns source/runtime verification, native single-thread
  execution, geometry/operator preparation and one latest immutable result.
  Mesh algebra is in km/slab-speed units; published fields are kelvin, m/s and Pa.
  Complete result geometry and velocity convert explicitly to Atlas x-right/z-up
  metres, z=-y and vz=-vy, with triangle orientation/midpoint ordering preserved.
- A shared128MiB accounted-work envelope admits geometry, assembly and sparse
  factors before execution. Realised sparse factor storage is checked against its
  allowance. This is not a process-RSS or allocator-enforced memory guarantee.
  Existing W07 mesh and256-history-interval limits are unchanged.
  Assembly scratch is released before factorisation; sparse matrices and retained
  output fields have separate leases. Scalar factors have an additional64MiB
  allowance ceiling and are still checked against their realised fill.
  Heat-gradient tables are prepared only for the thermal phase, then released
  before mechanics; their polynomial arithmetic is unchanged. Conservative
  transport retains its measured immutable backing arrays rather than reserving
  its larger construction envelope for the whole workflow.
  Block factors split construction scratch from bounded native/cached factor and
  permutation storage, checking both realised footprints. GMRES basis storage is
  admitted only after construction. A different case evicts the one-entry result
  cache before solving; externally retained outputs remain correctly charged.

## Finite material retirement

`SubductionInventory` retains individually named crust/mantle cohorts, exhaustive
component masses and signed enthalpy. `PreparedSubductionRetirement` computes
rho*H*(v_material-v_boundary).n times the explicitly supplied section width.
All supplied accretion/deep-storage/export fractions are applied simultaneously;
destination order cannot change results. Full three-component velocities are
retained under an explicit translation-invariant-along-strike section policy.
This does not assert unmodelled side-face exchanges vanish in a general3D region.

The first finite exhaustion is an exact named event. Requests beyond it refuse;
there is no implicit donor, sequential stock clamp, disappearing crust/mantle or
lost signed heat. Each evaluation branches from its initial finite inventory.
The eventual event-history owner must serialise spending and authenticate the
whole source-bound workflow; this primitive is not that cumulative ledger.

## Verification and timing

The comparison fixture retains2C diagnostic and1C finest-change targets. Initial
gradingr1 failed thermal convergence; gradingr2 uses h+0.25 times physical normal
distance, with explicit remote growth. It is not a fit to reference temperatures.
The corrected analytic-flow comparison at1.5km has errors(+0.3830,+0.3720,+0.6555)C
but wedge RMS changes1.1038C between the finest two levels, so it did NOT pass
the1C change gate. P2/SUPG also retains a reported7.25K hot-node overshoot in that
run; temperatures were not clipped to conceal it. This failed formulation is
preserved as historical evidence, not reused as acceptance of the replacement.

Gradingr3 corrects a separate convergence defect: r2 left finite off-interface
cell sizes as h approached zero. With s=sqrt(h/6), r3 uses
`min(45*s, h+s*(.25*distance_to_slab+.1*remote_slab_distance),
h+s*(.25*distance_to_lid+.1*remote_horizontal_distance))` km. Thus both local and
remote spacing vanish; the law was fixed before its physics comparison, not fitted
to reference temperatures. At h=6/3/1.5km it has1850/4572/11547 triangles.
Final vertex/triangle limits remain12000/20000; temporary point-cloud candidates
have a separately bounded48000-entry allowance within the existing mesh scratch.

The first pressure-mass block run refused nonlinearcase2a at6km, with continuity
residual0.07568. Equilibration and exact velocity-block factors alone still failed
(8.83e-8). Weighted BFBT subsequently passed all18 mechanical solves reached
(maximum122 iterations, residual<=9.81e-11), then the old heat transfer refused a
non-positive temperature. These failures motivated the conservative transfer;
they are not successful nonlinear acceptance evidence. The early all-case run
was cancelled during another failed formulation and is not a completed campaign.

The completed r4 campaign subsequently computed 11 of 15 requested rows. The
finest analytic case1a gives (388.221466824, 503.735465333, 854.300731890) C:
maximum reference error 0.045466 C and maximum change from h=3 km 0.741635 C.
Both unchanged numerical comparison gates pass for that case. All four finest
computed-flow cases initially refused combined memory admission; this is not a
passing five-case comparison. The source-adapter gate remains independent.

Dislocation creep case2b previously reached its 200-map bound with log-viscosity
residual 6.178232e-7. Safeguarded Anderson converged at h=6 km in 105 maps with
residual 9.225309e-8 and temperature change 9.199434e-7 K. This repairs a failed
solve; it is not a matched successful-baseline speedup percentage.

The r4 repeated-request measurement uses three identical complete h=12 km case1c
requests, including preparation, source verification, materialisation and close.
Three rotated repeats gave fresh median 0.8484258 s versus prepared/reused
0.3802599 s: 0.4681659 s or 55.1805% saved, with identical result identities.
This is repeated-work reuse, not a claim that first-time generation is 55% faster.

The later phase-lifetime correction admits both computed constant-viscosity
cases on the 1.5 km mesh under the same 128 MiB envelope: case1b takes 1.220350 s
and case1c 1.229061 s, with maximum reference errors 0.059982 and 0.066103 C.
Their largest changes from the existing 3 km rows are 0.446116 and 0.429240 C;
both numerical gates pass. The reused coarse rows have the same physical mesh,
operators and convergence tolerances; later changes affect storage lifetimes.

The batch also held an unnecessary previous full result while starting another
case. The plan now evicts its unusable latest cache before a different case, and
the comparison driver releases each field after extracting its row. Caller-owned
results remain charged and immutable. A targeted lifetime regression checks both
behaviours. At 1.5 km, case2a then completes 46 nonlinear maps in 55.694123 s,
with maximum error 2.548410 C: **the 2 C accuracy gate still fails**. Its largest
change from the 3 km row is 0.991244 C, which does pass the separate 1 C gate.
Case2b also completes at 1.5 km in 157.057037 s. Its maximum reference error
0.863266 C passes 2 C, but the maximum change from the existing 3 km row is
8.022097 C: **the 1 C refinement gate fails**. All five finest cases now compute;
this does not make Step4 accepted. Next work is the two nonlinear accuracy/
refinement failures and the independent unresolved original thermal operator.

The r9 matched repeated-request measurement gives fresh median 0.8916486 s and
prepared/reused 0.3701639 s: 0.5214847 s / 58.4855% saved. This includes the
phase-based solver accounting and lazy thermal geometry. Subsequent cache
eviction affects different-case requests, not this identical-request workload.

Recorded evidence: [r4 three-level campaign](../evidence/w08-subduction-r4.json),
[r9 finest case1c](../evidence/w08-subduction-r9-1c.json),
[r9 timing and retained-result refusal](../evidence/w08-subduction-r9-fine.json),
and [r10 corrected batch/fine creep comparison](../evidence/w08-subduction-r10-fine.json).
Each records exact source identities. The remaining numerical failures are not
waived or reclassified by 54 distinct passing focused module checks (12 main,
9 mesh,13 linear,11 retirement,9 transport). The shared identity and coding-safety
checks also passed; no full-suite, whole-world or held R4.4 run was launched.

## Research-led correction in progress

The original paper's PGC contributor description (printed p.190) reports a 1 m
horizontal tip removal and elements ranging from 4e-8 to 70 m within the first
kilometre. Its nonlinear cases have thin boundary layers. This is stronger
resolution evidence than the nominal whole-domain spacing. The existing first
P2 slab edge has speed samples (0,1,1), giving 3s-2s^2 and a 12.5% between-node
overshoot. The stationary apex is source-supported; this numerical trace is not
a linear physical coupling ramp. The separate original UM ramp variant and the
2023 FEniCS-SZ ramp/adiabat are not silently adopted into the frozen no-ramp case.

Grading r4 retains r3 away from the corner and adds geometric upper bounds on
spacing. With r in km from (50,50), s=sqrt(h/6), and d a lower-bound distance
outside the wedge, the additional targets are
`h/4+s*(.05*r+.5*max(r-25,0)+.25*d)` and
`h/6000+s*(.35*r+.25*d)`. The 25 km transition is half the lid thickness.
The first resolves the near-corner layer; the second confines the singular
first-edge approximation to 1/0.5/0.25 m targets at base scales 6/3/1.5 km.
The coefficients were chosen using geometry and bounded mesh admission before
the new thermal comparisons, not fitted to their temperatures. This gives
2654/6084/14511 triangles, of which 1014/2448/5996 are in the wedge.
No PGC notch or finite physical coupling ramp is introduced. Geometry checks
pass, but no numerical acceptance is implied by those counts.

The first r4 attempts exposed conditioning on tiny elements and an excessive
retained-geometry allowance. `interface-r3` remains the working default;
`corner-r4` is an explicit experimental mesh, not silently substituted for it.
`corner-r5` is a second declared candidate: the final apex target is h/60
(100/50/25 m at base h=6/3/1.5 km) with the same surrounding corner grading.
It avoids the sub-metre extreme; no boundary trace, coupling ramp, viscosity law,
128 MiB cap, iteration ceiling or acceptance tolerance has been changed.
The mesh policy and realised target are included in the plan/result identity.

Transport conditioning now subtracts the local streamfunction gauge before
differentiation, retains compensated boundary-integral prefixes until after a
single global gauge shift, and closes that integral on the longest boundary
edge. These are constant-gauge/round-off changes, not flux redistribution.
Eleven focused transport checks pass, including independently differentiated
cubic traces on a 512 km/0.244 m graded boundary.

Locator retention now accounts for the warmed, closed non-incremental SciPy
Qhull object's complete Python/array backing, rather than a coarse envelope.
The r4 fine main+wedge reservation falls from15,645,104 to6,187,778 bytes;
this is a more accurate accounting allowance, not a measured RAM saving.
Flow gradients are also released during factorisation and regenerated only for
the strain calculation. These phase changes retain the original cap and
round-off arithmetic; caller-held results remain charged.

The r4 true saddle solve still fails unchanged continuity checks at the
1200-inner-iteration ceiling. It must not be accepted because geometry checks
pass. Moderate r5 computes both creep cases at base h=6/3 km; its h=3 maximum
reference errors are1.336940 C (2a) and1.147598 C (2b). Fine convergence and the
refined affine pressure patch are still required before candidate acceptance.

The affine patch has since passed after fixing premature normwise convergence:
the solver now conditionally uses its already permitted defect corrections when
the true equilibrated residual remains above an operation-magnitude round-off
scale. The existing physical1e-10 gates,1200-inner-iteration ceiling and two
correction opportunities are unchanged. On r5 the manufactured pressure error
falls from2.967546e-7 to3.820023e-12; the unchanged1e-8 assertion passes.

The finest candidate then exposed sparse-factor fill, not a physical failure.
Heat now uses RCM followed by SuperLU MMD_AT_PLUS_A, symmetric mode and a0.01
diagonal-pivot threshold (off-diagonal pivoting remains available). This is full
LU with original-equation residual checks, not incomplete factorisation.
Heat gradients are released before LU, since only assembled operators are needed
afterwards. Freed headroom permits a72MiB internal construction envelope instead
of64MiB while retaining the unchanged shared128MiB cap and realised-fill checks.
CSC backing and permutation storage are included in the new accounting.

A three-repeat alternating comparison on the same26,692-unknown fine case1a
thermal matrix gives0.9100626s →0.0457220s median ordering/conversion/factor time:
0.8643406s /94.97595% saved. Factor nonzeros fall1,890,881 →1,771,368.
Manufactured forward error is1.12e-14 and backward residual8.52e-16.
This is a factor-only speedup, not a whole-generator or completed-baseline-run
claim. Both measured variants are assessed using the same complete storage rule.

The r16 nonlinear fine solves now complete. Their full shared accounting peaks
at exactly134,217,728 bytes: the velocity-factor construction reservation is
limited to the actual available ancestral-budget headroom, then its realised
fill and retained storage are still checked. This avoids treating an internal
72MiB maximum reservation as irreducible live storage when Anderson history is
also resident. No native hard-RSS limit or extra uncharged allocation is claimed.

Current corner-r5/nodal-P2 comparisons use r14 h=6/3 km, r15 finest constant
cases and r16 finest creep cases. These reports deliberately preserve their
different source identities: intervening changes concern factor ordering,
storage lifetime and admission, not the physical equations, quadrature, mesh,
boundary traces, sample points or nonlinear convergence thresholds.

| Case | Fine maximum error (C), limit2 | 3-to-1.5 km change (C), limit1 | Fine elapsed (s) |
|---|---:|---:|---:|
|1a|0.047639|0.151066|0.326436|
|1b|0.047088|0.148727|5.128511|
|1c|0.074320|0.107190|1.335523|
|2a|0.309064|**1.029971 FAIL**|43.110065|
|2b|0.855078|0.511755|89.712439|

All five now pass the reference-error test; four pass the fixed refinement test.
The2a miss is not rounded into a pass. Compared with historical r10 timings,
creep runs are12.584s/22.59% and67.345s/42.88% shorter, respectively; those are
observed scenario improvements with changed meshes/algorithms, not a matched
isolated optimisation experiment. The matched factor measurement above is the
controlled speedup evidence. Step4 remains IN_PROGRESS.

The optional `coupling_trace='mesh-linear-first-edge-v1'` now removes the
first-edge12.5% mechanical velocity overshoot. It changes only that actual
edge's P2 midpoint to the mean of its endpoint values; `nodal-p2-v1` remains
the default. Geometry, trace choice and realised edge length are identity-bound;
analytic1a is unchanged. Monotonicity is a mechanical boundary property, not a
claim about the subsequently projected interior/tangential transport field.
It is a mesh-tied numerical variant, not UM's physical ramp or PGC's notch.

Its separate three-level2a comparison r17 completes in70.554689s. Fine reference
error0.309063C passes, but finest change1.029971C still fails. Temperature changes
versus the original trace are at most about3e-6C over these diagnostics: this
rules out that overshoot as a material cause of the remaining diagnostic miss.
The variant is retained explicitly, not promoted or called a convergence fix.

Final checkpoint: implementation/owner regressions pass in their recorded
scopes; all five r5 reference-error comparisons pass;2a refinement and the
independent original2008 source operator remain unresolved. Next work should
localise the thermal discretisation error and justify any further local
resolution from it, rather than tuning geometry or tolerances to the reference
row. Default mesh/trace remain interface-r3/nodal-p2-v1 pending acceptance.

Evidence: [r14 coarse/middle and fill refusals](../evidence/w08-subduction-r14-refined.json),
[r15 fine constant cases](../evidence/w08-subduction-r15-fine.json),
[r16 fine creep](../evidence/w08-subduction-r16-creep.json),
[matched thermal-factor timing](../evidence/w08-subduction-thermal-ordering.json),
[r17 separate monotone-trace comparison](../evidence/w08-subduction-r17-monotone.json).

Wilson & van Keken (2023), section2.3.3, explicitly defines homogeneous natural
outflow as Neumann, and its steady weak equation117 has no diffusive boundary
load. This independently supports the implemented zero-normal-diffusive-flux
operator. It does not explicitly clarify the 2008 wording, so the historical
source-exact gate remains visible rather than claiming an author correction.

## Papers and software checked

- [van Keken et al.2008](https://sites.ualberta.ca/~ccurrie1/papers/vanKekenEtAl_PEPI_2008.pdf):
  frozen prior paper/table review plus newly retrieved indexed mechanical-boundary
  sections; current direct PDF fetch timed out. Supplies the original cases and
  reference rows, but not a resolved differential thermal-outflow operator.
- [van Zelst, Thieulot and Craig2023](https://se.copernicus.org/articles/14/683/2023/index.html)
  and [xFieldstone source](https://github.com/irisvanzelst/xFieldstone/blob/master/main_solver_Stokes_T_grid.py):
  methods, setup and selected thermal assembly/velocity source checked. Informed
  the separately labelled natural-outflow reproduction adapter and direct steady
  solve. No external code was installed or executed.
- [ASPECT subduction cookbook](https://raw.githubusercontent.com/geodynamics/aspect/main/cookbooks/vankeken_subduction/doc/vankeken_subduction.md):
  interface-aligned geometry guidance checked; its own warning against claiming
  benchmark reproduction is preserved.
- [FEniCS-SZ benchmark description](https://cianwilson.github.io/fenics-sz/notebooks/03_sz_problems/3.4a_sz_benchmark_intro.html):
  revised geometry/assumptions checked. Its newer benchmark is not substituted
  for the frozen2008 fixture or its reference diagnostics.
- SciPy official Delaunay documentation and Burkardt Strang triangle-quadrature
  datasets informed the geometry and positive degree-five/six integration rules.
- [Rudi, Stadler and Ghattas2017](https://arxiv.org/html/1607.03936v2):
  equations7-8, weighted mass and boundary-condition discussion checked for BFBT.
  The triangular P2 positive-diagonal adaptation is identified above, rather than
  claiming their different finite-element discretisation was reproduced.
- [Schoeberl H(div) finite elements](https://jschoeberl.github.io/talk-HDivconforming/theory/spacehdiv.html):
  normal-continuity/BDM-space construction checked for the conservative transfer.
  [Chang, Azevedo and Batty2019](https://doi.org/10.1145/3309486.3339890) provides
  curl-reconstruction context; the scalar P3 finite-element fit here is derived
  separately and is not their grid interpolation algorithm.
- [SCS Anderson acceleration documentation](https://www.cvxgrp.org/scs/algorithm/acceleration.html):
  type-II multisecant updates, regularisation, relaxation and safeguarding checked.
  Only the algorithm was adapted; SCS is not a dependency or an executed solver.
- [Wilson and van Keken2023](https://link.springer.com/article/10.1186/s40645-023-00588-6):
  sections2.3.3-2.3.4, equations107-117 checked for natural outflow and coupled
  weak forms; its additional physical ramp/adiabat are not imported.
- [ASPECT mesh-refinement documentation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Mesh_20refinement.html):
  temperature/velocity error indicators and logarithmic-viscosity refinement
  checked as guidance for concentrating resolution. Atlas r4 is explicit
  geometry-based grading, not a claim to implement ASPECT's adaptive estimator.
- [SuperLU FAQ](https://portal.nersc.gov/project/sparse/superlu/faq.html):
  symmetric-mode/diagonal-pivot guidance checked for sparse fill and solve time;
  adoption is supported by measured fill and original-equation accuracy checks,
  not an assumption that the advection-diffusion matrix is symmetric.
- [SciPy GMRES documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.gmres.html):
  true-residual semantics and legacy callback inner-iteration counting checked.
