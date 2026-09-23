# W07 Step 1 — regional mechanics model and benchmark specification

22 September 2026. **WORKING NON-CANON; Step 1 design complete.**
This is the implementation contract for W07, not a new solver acceptance record.
The [case register](../cases/w07_mechanics.json) fixes the first comparisons and
numerical gates. W06's completed scoped work and the held R4.4 campaign are unchanged.

## 1. Decision and implementation order

Develop Mode M as a **two-dimensional, plane-strain, incompressible creeping-flow
model**, initially steady, isothermal and Newtonian. Retain the existing structured
staggered-grid (MAC) full-stress operator as the first implementation candidate.
The immediate new capability is regional boundary forcing: nonzero prescribed
motion, no-slip and applied traction, not another closed-box convection campaign.

Compare MAC with an inf-sup-stable mixed **Q2/P1-discontinuous finite-element**
reference on the same small continuum cases before finalising the regional
backend. The method comparison below selects a starting route, not a measured
winner or a commitment to a new external framework. Code-level implementation and
the matched-error comparison belong to Step 2. No external dependency is installed
by this design; preserve existing third-party licences before any code transfer.

1. **This step:** equations, boundary/material conventions, source interfaces,
   independent cases and acceptance/performance policy.
2. **Basic regional mechanics:** boundary-aware constant-viscosity reference and
   candidate, pressure/nullspace handling, complete stresses/tractions and the
   small MAC/finite-element comparison.
3. **Heterogeneous and thermal mechanics:** explicit stress-site properties,
   independent sharp-interface tests, retained heat/material transport joined to
   compatible moving/open boundaries, then the named nonlinear material laws.
4. **Surface/strength response:** true free-surface geometry and integration;
   pressure-sensitive yielding. Localisation needs its own physical length and
   mesh-independence evidence; a narrow numerical shear band is not acceptance.
5. **Assembled workflow:** source-bound geological inputs, one owner per force/
   displacement/heat contribution, recovery, combined acceptance and measured reuse.

### Numerical alternatives checked

| Candidate | Useful property | Cost or limitation | Decision |
| --- | --- | --- | --- |
| Existing MAC full-stress operator; LaMEM/PETSc staggered references | Compact face fluxes and local divergence; much existing Atlas code can be reused | Current wall elimination, FFT inverse and GMG supports are specialised; moving geometry needs new metric/boundary work | First candidate for flat regional baseline |
| Q2/P1-discontinuous, as in pTatin3D | Stable velocity/pressure pairing, elementwise mass balance, natural traction and body-fitted geometry | More unknowns/quadrature; new assembly and transfer boundary; not an installed Atlas backend | Small independent comparator; retain as alternative if MAC geometry/accuracy cost loses |
| Unstabilised equal-order or Q1/P0 elements | Fewer apparent unknowns | Spurious pressure modes can invalidate the saving | Not selected |
| Full external LaMEM/ASPECT/pTatin framework integration | Extensive existing geodynamic capabilities | New runtime, licensing, packaging and source/restart boundary | Not required for this bounded step; no framework clone |

The literature motivates these choices; it does not establish which is fastest
in Atlas. Source access and the software methods actually inspected are listed
in Section 9. The tiny comparator must not become a second production solver.

## 2. Equations, units and pressure

Coordinates are x-right, z-up; velocity v=(u,w), in m/s. Use metres, seconds,
kelvin, pascals, Pa s, kg/m3 and body-force density N/m3. A named frame, vertical
datum, strike width and epoch are compulsory. W01 inward-positive depth needs an
explicit signed coordinate transform, including vector/tensor components.

```text
D = (grad(v) + grad(v).T)/2
div(v) = 0
sigma = -P I + 2 eta D
div(sigma) + rho_b g + f_external = 0
P = P_ref + pi;  grad(P_ref) = rho_ref g
-div(2 eta D) + grad(pi) = (rho_b-rho_ref) g + f_external
```

Plane strain has v_y=0, d/dy=0 and D_yy=0, not a plane-stress assumption.
Density used for buoyancy does not silently alter the conserved material masses.
The first reference density is constant; more general hydrostatic profiles require
their own consistent integration. With z-up and downward gravity, a reference
P_ref=P_surface+rho_ref*g_abs*(z_surface_ref-z) has the correct sign.
Keep the full symmetric-stress divergence for nonconstant viscosity; eta times
the vector Laplacian is valid only for constant eta and divergence-free velocity.

There are two distinct pressure questions:

- In all-velocity/impermeable-wall cases the algebraic pressure has a constant
  nullspace. Keep every continuity equation and impose the declared weighted
  mean/gauge with an augmented constraint or nullspace projection. Never obtain a
  result by dropping a conservation row. A numerical zero mean is not an absolute
  geological pressure datum.
- A specified normal traction fixes physical pressure through sigma*n. Do not
  also force a zero-mean pressure or subtract its mean after solving. For a
  pressure-dependent material in a velocity-only problem, supply an independently
  named physical datum (for example, mean pressure on a designated boundary),
  reconstruct P_ref+pi+the datum offset and use that pressure consistently in
  constitutive evaluation. Missing datum is an error, not a pressure clamp.

Use explicit scales L0, U0>0, eta0>0: strain rate U0/L0, stress eta0*U0/L0,
body force eta0*U0/L0^2 and time L0/U0. Physical zero motion does not imply a zero
normalisation scale. Retained diffusive scaling is also valid only when the
conversion U0=kappa/L0 is explicit. Binary64, finite conversions, no fast-math.

## 3. Boundary and force ownership

Each boundary segment supplies one velocity or conjugate traction condition per
component, with outward normal, units, time and source. Supported first cases are
full prescribed velocity; normal velocity plus tangential traction; and full
traction on a named segment. Velocity and traction cannot both constrain the same
component. Corners require compatible traces, not averaged contradictory values.

Lift prescribed velocity into the right-hand side of BOTH momentum and continuity.
For a fixed incompressible domain with every normal velocity prescribed, require
the integrated outward volume flux to be zero. Do not repair a mismatch by uniform
source subtraction, altered velocities or pressure pinning. If traction leaves
normal velocity free, solve it and check the completed boundary flux. Prescribed
inflow also needs source material and thermal data before time evolution is allowed.

Distinguish pressure nullspace from rigid translation/rotation modes. Fully
traction-driven cases need force/torque compatibility and explicitly constrained
or projected rigid modes. A missing mode constraint must fail before iteration;
no artificial drag is added. Uniform translation and rigid rotation have zero D.

Recover boundary reactions for Dirichlet segments. Check total force, torque and
mechanical power, including work on moving boundaries:

```text
integral(2 eta D:D dV) = integral(f_effective . v dV)
                        + integral(t_effective . v dS)
```

For the split-pressure equation t_effective=t_physical+P_ref*n; use matching body
forces and tractions on both sides of the identity. Full physical stress/work is
reported separately if reconstructed. Do not compare perturbation-body work with
full-pressure boundary work. Pressure-positive-compression and outward-traction
signs are tested independently of the assembled matrix.

W01/S6/W06 may provide boundary motion, not an extra displacement added after the
mechanical solve. Unsupported out-of-plane or omitted-section motion remains an
explicit incompatibility, not zero. W04 flexure/local compensation cannot be
added to a mechanical solution already owning the same buoyancy/load response.
Forces are source-tagged and applied once; there is no inferred slab pull.

## 4. Constitutive and free-surface choices

### C01: strength, pressure and localisation

The first baseline is eta=eta0>0, with no elastic memory or damage. Next, prescribed
positive heterogeneous viscosity and a source-explicit temperature law are added;
existing Tosi/BF reference laws retain their own identities and invariant factors.
They must not be relabelled pressure-sensitive geological rheology.

For the first new dry pressure-sensitive family select isochoric, non-associated
viscous yielding in the 2D invariant convention:

```text
eII = sqrt(D:D/2);  tauII = sqrt(tau:tau/2)
tau_y = C*cos(phi) + P_effective*sin(phi)
eta_eff = min(eta_creep, tau_y/(2*eII))    when eII > 0
eta_eff = eta_creep                      when eII = 0
tau = 2*eta_eff*D
```

C is Pa; phi is radians; P_effective=P-P_pore. First dry tests explicitly set
P_pore=0. C>0 and 0<=phi<pi/2 are required. Plastic flow is deviatoric/coaxial,
with zero dilatancy, no strain weakening and no hidden minimum strain rate.
The min form is a chosen perfect yield cap, not Tosi's factor-two harmonic law.
Use named creep parameters and their original laboratory invariant/unit convention
before adding Arrhenius/dislocation laws; synthetic tests are not crustal defaults.

The first compressive law refuses P_effective<0 and a largest principal effective
stress exceeding the explicit tensile-strength envelope (zero tensile strength in
the synthetic dry case). It does not manufacture positive pressure or model cracks.
Viscosity bounds are declared validity limits: reject an out-of-envelope result,
not clip it and claim the original stress law still holds. Zero shear is handled
by its finite limit. Nonlinear acceptance uses updated physical fields and law.

This fixes the initial strength choice, not a physical shear-zone width. Softening,
damage or a localisation claim requires a separately source-defined nonlocal/
gradient/other regularisation length and mesh/time refinement at fixed length.
No grid-sized weakening length is selected here. Tensile fracture, poromechanics
and elasticity require their own later constitutive extensions.

### C02: a true surface, not an impermeable lid

Select a body-fitted **arbitrary Lagrangian-Eulerian (ALE)** surface for the first
moving-boundary extension. The physical boundary is sigma*n=-P_external*n plus
any independently specified shear traction. Atmospheric pressure may be explicit
zero gauge; water loading needs a named water state/account, not a default ocean.
For a graph z=h(x,t), h_t+u*h_x=w before external erosion/deposition is coupled.
No W04 displacement is added again.

Require mesh normal velocity v_mesh.n=v.n on the material surface. The first mesh
choice is Laplacian smoothing, -laplacian(v_mesh)=0, with normal physical motion
on the surface and fixed geometry on the remaining box boundaries. Use v-v_mesh
for transport; the mesh velocity is not another physical material velocity.
Conservative geometric/volume closure, metric-aware adjoint operators, positive
cell Jacobians and source-bound remap are mandatory. Existing rectangular MAC
stencils cannot be used on a distorted grid unchanged. Step 4 must implement this
metric extension or adopt the compared finite-element route explicitly. Surface
overturning outside a height representation refuses instead of flattening it.

Begin with accuracy-resolved small timesteps. If a quasi-implicit stabilising
traction is enabled, bind its coefficient and timestep to the operator and prove
the same small-step limit. Stability is not a timestep-accuracy argument. ASPECT's
ALE/stabilisation documentation and Kaus et al. inform this choice. Sticky air is
not the initial substitute; it would require its own density/viscosity/thickness
convergence and finite mass accounting.

## 5. Reuse boundary and required new interfaces

Current source inspection identifies the following reusable machinery; it is not
a new test execution or a claim that the regional interfaces already exist.

| Existing source | Reuse | New work / restriction |
| --- | --- | --- |
| [stokes.py](../src/atlas_tectonics/stokes.py), [stokes_execution.py](../src/atlas_tectonics/stokes_execution.py) | MAC layout, scaling, gauge, independent sparse reference and checks | Closed free-slip walls only; separable FFT inverse is not valid for arbitrary new boundaries |
| [variable_stokes.py](../src/atlas_tectonics/variable_stokes.py), [variable_stokes_execution.py](../src/atlas_tectonics/variable_stokes_execution.py) | Full symmetric-stress operator, explicit centre/vertex eta, updated-law checks, GMRES | Boundary lifts/reactions and pressure-sensitive material interface are missing; current thermal coupling is closed-box |
| [_mechanics_native.py](../src/atlas_tectonics/_mechanics_native.py) | Fused binary64 stencil and symbolic sparse refill | Kernels encode old boundary layout; extend rather than bypass checks |
| [_velocity_multigrid.py](../src/atlas_tectonics/_velocity_multigrid.py) | Existing assessed GMG option | Square power-of-two isotropic support; not a general rectangular/ALE preconditioner |
| [preconditioner_reuse.py](../src/atlas_tectonics/preconditioner_reuse.py) | Bounded optional lagged helper with exact current-operator checks | Never reuse stale physics; existing optional Tosi policy is not automatically enabled for new rheology/boundaries |
| [reuse.py](../src/atlas_tectonics/reuse.py), [resources.py](../src/atlas_tectonics/resources.py), [storage.py](../src/atlas_tectonics/storage.py) | Live identity, admission, cancellation, atomic lossless snapshots | New prepared identities bind boundary support, pressure datum, material sampling and mesh metrics |

The regional input contract must identify geometry/support; x/z transform; epoch;
source W01/W02/W03/W06 state IDs; conserved phase inventories versus buoyancy
density; centre AND shear-site viscosity; all force/traction/motion sources;
physical pressure datum; material/thermal inflow; and the sole vertical-response
owner. A source-bound array with the wrong spatial or temporal meaning is invalid.

For first heterogeneous references evaluate the exact coefficient at each stress
site or use the explicit layered-series construction below. Phase mixtures need
a named mixing/sampling law and independent interface tests; no universal hidden
arithmetic/harmonic average. Existing sharp-jump tests check discrete work and
unchanged inputs, not an independent continuum interface solution.

Outputs must include velocity, dynamic AND reconstructed physical pressure when
defined, full strain/stress components and their locations, boundary tractions/
reactions, flux/work residuals, material-sampling provenance and source identities.
Actual transfer/evolution remains with the compatible W02/thermal producer, not
point interpolation of conserved quantities. Reject a missing compatible bridge.

## 6. Independent benchmark definitions

The JSON register fixes numbers and stage ownership. All first cases are synthetic,
with unit scales unless stated; they are not Diadem geography or Earth calibration.
Every continuum load is independently derived, never made from A*v_exact. Sampling
must compare like quantities: face points/averages, cell pressure/means and boundary
quadrature are explicitly reported. Pressure errors remove a mean ONLY for an
actual gauge-free problem, and compare to a physical datum otherwise.

**B00 — hydrostatics and datum.** Reuse f_z=-7, W=2, H=3, p=-7(z-1.5), v=0
for the mean-zero case. Also specify the same problem with physical top normal
traction: the pressure offset must follow that traction rather than be removed.
Test a nonzero background P_ref and no spurious reference-density force.

**B01 — retained smooth full-stress controls.** Retain existing constant-viscosity
trigonometric MMS and the exponential eta(x,z) MMS, including their exact signs,
unequal-spacing cases and already frozen numerical limits. These discriminate
stress divergence from eta*Laplacian. Reuse existing evidence when bindings match;
rerun only the affected boundary/operator path during Step 2/3.

**B02 — no-slip polynomial vortex.** On [0,1]^2, eta=1, define
A(s)=s^2(1-s)^2, psi=A(x)A(z), u=A(x)A'(z), w=-A'(x)A(z),
p=x^3+z^3-1/2. Then div(v)=0, both boundary velocities vanish, mean(p)=0:

```text
A' = 2s-6s^2+4s^3; A'' = 2-12s+12s^2; A''' = -12+24s
f_x = 3x^2 - A''(x)A'(z) - A(x)A'''(z)
f_z = 3z^2 + A'''(x)A(z) + A'(x)A''(z)
```

**B03 — imposed extension and frame invariance.** On [0,2]x[0,1], eta=1,
u=x-1, w=-(z-1/2), p=0, f=0. All boundaries take the exact velocity;
outward flux is zero, D=diag(1,-1), stress=diag(2,-2), dissipation=8 per unit
strike width. Boundary-reaction work equals 8. Add constant translation (0.3,-0.2)
without changing D/stress. A deliberately unbalanced boundary flux must refuse.

**B04 — traction-driven Couette.** On [0,1]^2, eta=1, bottom v=0, side traces
u=z,w=0, top t=(1,-2). Exact u=z,w=0,P=2; shear stress 1; dissipation/work=1.
The top is a traction boundary, not yet an evolved free surface. It tests both
nonzero shear load and physically fixed pressure; zero-mean postprocessing fails.

**B05 — nullspaces.** With compatible pure traction and f=0, rigid motion is
undetermined unless the declared translational/rotational constraints remove it.
Test a rigid rotation with prescribed boundary velocity (D=0), pressure checkerboard
refusal, incompatible net force/torque and conflicting component boundary types.

**B06 — material interfaces (Step 3).** Couette with u(0)=0,u(1)=1, w=0,
eta=1 below z=a and 1000 above: tau=1/[a+(1-a)/1000],
u=tau*z below a and tau*[a+(z-a)/1000] above. Use a=0.5 and a=0.37; preserve
velocity and shear-traction continuity and use exact integral stress-site support.
Prescribe exact velocity traces on the sides and a separate physical pressure
datum P=10 on the top; the datum is not an additional normal-traction condition.
Also use the independently implemented published SolCx solution: free-slip unit
box, gravity (0,-1), density sin(pi*x)cos(pi*z), eta=1 left of x=0.5 and 10^6
right. Its documented sign correction must be preserved. Aligned and unaligned
meshes are separate tests; do not impose smooth pressure convergence at the jump.

**B07 — heat/material transport (Step 3).** Constant translation, a declared
sinusoidal temperature perturbation and matching open-boundary traces give
T=T0+A*exp(-kappa*k^2*t)*cos[k*(x-U*t)]. Use kappa=0.01,U=1,k=2*pi,T0=1,A=0.1.
Check thermal flux/storage, maximum principle and conservation independently.
Material translation uses exact region intersections, with real inflow/outflow
inventories. Repeat on prescribed ALE motion; stationary physical material must
not be advected at the mesh velocity. This requires a new compatible transport
adapter, not unmodified closed-box R4.2 evolution.

**B08 — strength/datum (Step 4).** First use material-point and homogeneous shear
cases for the explicit C01 law: C=2,phi=pi/6,P=10,P_pore=0,eta_creep=100.
Check low-rate creep, yield cap and zero-rate limit; changing algebraic pressure
gauge with the same physical datum leaves strength unchanged. Changing physical
P changes strength. Tensile/out-of-envelope inputs refuse. This is not a shear-band
width test. Any later localisation case must freeze its physical length first.

**B09 — surface relaxation (Step 4).** Homogeneous Newtonian layer, no-slip bottom,
free-slip sides and traction-free top; W=2,H=1,eta=rho*g=1, k=pi, initial
h=a*cos(k*x), a=1e-4 and 5e-5. The infinitesimal-amplitude reference is

```text
h(t)=a*exp(-gamma*t)*cos(k*x)
gamma = (rho*g)/(2*eta*k) * [sinh(2*k*H)-2*k*H]
                            / [cosh(2*k*H)+1+2*(k*H)^2]
```

Use finite-depth gamma, not its infinite-depth limit. Pogosian et al., Section 3.1,
gives the decaying solution/relaxation time; its displayed evolution equation has
an inconsistent sign, so the reference must independently satisfy the traction
boundary-value problem and gamma>0. Verify the thin-layer limit
gamma~rho*g*k^2*H^3/(3*eta), the half-space limit and exact flat rest. Compare
amplitude at t=0,0.25/gamma,0.5/gamma,1/gamma; halve amplitude to distinguish
linearisation error from solver error. Refinement/timestep partition, surface
volume and boundary work are required. The more expensive Crameri rising-blob
campaign is not a prerequisite for the basic solver.

## 7. Fixed gates and practical resource policy

Keep existing returned-field, force-normalised gates: momentum 1e-9, divergence
1e-10, gauge 1e-12 and mechanical work 1e-9; linear target 1e-12. For new moving
or traction boundaries, define denominators from declared characteristic scales
and nonzero body/boundary terms, never a near-zero net load. Report dimensional
residuals too. Gauges apply only to gauge-free cases. Do not loosen old gates.

For new smooth MMS use 16/32/64 cells per side, volume/dual-volume weighted L2
errors and separately boundary maximum errors. Require velocity refinement ratios
at least 3.2 on the two successive refinements and finest relative L2 <=1%;
pressure relative L2 <=1% and ratios >=3.2. If the reference norm vanishes, use
declared U0/stress scale and absolute error, not a relative quotient. This is a
target for the new second-order scheme, not a claim that it has passed. Exact
affine cases require scale-normalised field error <=1e-9. B06 layered velocity and
integrated shear work <=1%, no prescribed smooth pressure order at interfaces;
SolCx finest L2 velocity <=2%, pressure <=5%, errors decreasing. The source's
pressure gauge and field sampling must match.

B07 finest relative temperature perturbation error <=1% with decreasing spatial/
temporal errors and scale-normalised storage/flux residual <=1e-9; B08 material-
point law error <=1e-10. B09 finest amplitude error <=1%, surface-volume residual
<=1e-9 and decreasing error under both mesh/time refinement. Use 16/32/64 accepted
steps for its one-relaxation-time comparison, no change to the global 256 ceiling.
Long-run continuum convergence is not needed to test steady boundary mechanics.

The small method comparison uses MAC 4/8/16 versus Q2/P1-disc 2/4/8 elements,
then compares interpolated physical outputs on independent quadrature, not raw
vectors or equal-grid-size timings. Record unknowns and pressure/flux accuracy;
both candidates must satisfy the same case, gauge and boundary work. Reference
direct solves must pass existing fill/memory admission (64*N^2+linear allowance),
not just an unknown-count threshold. Larger 32/64-cell MAC refinement uses a
suitable explicitly selected iterative solver; no silent direct fallback.

Initial executable-case admission is 128 MiB shared accounted memory, one numerical
thread and <=256 accepted intervals; it is not an OS-RSS cap or global resolution
limit. Cases are steady snapshots or short defined transients, not millions of
unnecessary steps. Report predicted cost before scaling; stop on a resource/
convergence failure without coarsening, changing physics or raising the budget.

## 8. Efficiency designed in, measured after implementation

- Reuse topology/sparsity, immutable geometry, boundary lifts and numerical factors
  only under compatible keys. Key geometry, coefficient support, actual eta,
  constrained-DOF pattern, pressure policy, ALE metrics and stabilisation dt.
  Pure load changes can reuse a matrix; changed physical operators cannot.
- Keep O(N) native actions where applicable. MINRES requires a symmetric operator
  and positive definite symmetric preconditioner; a triangular/nonsymmetric block
  requires GMRES. Variable inner preconditioning requires a compatible flexible
  method, not an unchanged fixed-preconditioner call.
- Assess Schur AND velocity blocks. Retain existing ILU/GMG support restrictions;
  do not transfer the constant free-slip FFT inverse to new boundaries. Warm
  starting or lagging a helper does not skip true residual/current-law evaluation.
- Use the existing ArrayStore and source/budget/cancellation machinery, including
  checkpoint parent/source bindings. Store accepted physical state, not duplicated
  solver histories or every Krylov vector. Snapshot output is separate from small
  diagnostics and is not mandatory for one-off work.
- Time assembly/preparation, coefficient evaluation, preconditioner setup, solve,
  diagnostics, storage and end-to-end separately. Compare equal outputs at equal
  error with three rotating-order samples; report raw seconds, medians, saved
  seconds/percentages and any first-run overhead. Include cold and reused paths,
  plus a repeated-RHS case. Never count failed or under-resolved work as faster.
- Parallelise independent cases/regions when workload and memory justify it;
  dependent evolution remains ordered. No new process pool for tiny checks or
  nested thread oversubscription. Desktop feasibility needs measured evidence.

These are selected implementation strategies, not measured W07 speedups. No Atlas
mechanical solve or simulation was run for this specification. Step 2 will measure
the actual paths.

Design QA used exact rational-polynomial differentiation to check B02's momentum,
divergence, no-slip boundaries and pressure mean; the affine/Couette work identities
also passed. An independently constructed biharmonic traction boundary-value
calculation matched B09's decay rate at eight depth/wavenumber pairs to maximum
relative difference 1.96e-14, with the thin/deep limits and positive decay checked.
These are reference-definition checks, not numerical acceptance of an Atlas solver.

## 9. Papers and existing software checked

Primary sources inspected for this step; external packages were not executed.

- [Kaus et al. (2016), LaMEM, Sections 2.1–2.2](https://juser.fz-juelich.de/record/507751/files/nic_2016_kaus.pdf):
  staggered full-stress mechanics, distinct material tracking and block solvers.
  Selected full-text sections; no adoption of its entire constitutive system or
  sticky-air treatment.
- [May, Brown & Le Pourhiet (2014), pTatin3D, Section II and solver discussion](https://jedbrown.org/files/MayBrownLePourhiet-pTatin3d-2014.pdf):
  Q2/P1-discontinuous comparator, traction/nullspace distinction and coupled
  preconditioning. Selected full text; published HPC speedups are not Atlas claims.
- [PETSc DMStag ex2 source](https://petsc.org/release/src/dm/impls/stag/tutorials/ex2.c.html):
  inspected description, manufactured fields, boundary/nullspace and solver setup.
  Its documented force sign and toy preconditioner must not be copied blindly.
- ASPECT 3.0.0 documentation: [pressure split](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-static-dyn.html),
  [pressure normalisation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-norm.html),
  [material-model conventions](https://aspect-documentation.readthedocs.io/en/v3.0.0/parameters/Material_20model.html),
  [ALE](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/arbitrary-le-implementation.html),
  [stabilisation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/freesurface/stabilization.html),
  [SolCx](https://aspect-documentation.readthedocs.io/en/stable/user/benchmarks/benchmarks/solcx/doc/solcx.html)
  and [Crameri cases](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/benchmarks/benchmarks/crameri_et_al/doc/crameri_et_al.html).
  Relevant documentation sections, not a fresh independent ASPECT run. Underworld's
  historical SolCx contribution is identified there, not independently executed.
- [Kaus, Muehlhaus & May (2010)](https://doi.org/10.1016/j.pepi.2010.04.007):
  abstract and ASPECT's documented application checked; full paper not accessed.
  Supports the stabilisation question, not a claimed implementation of its terms.
- [Pogosian et al. (2015), Section 3.1](https://www.intechopen.com/chapters/47551):
  finite-depth no-slip-bottom surface-relaxation time; sign issue and independent
  boundary-value verification requirement recorded in B09.

The frozen [tectonics plan](TECTONICS_PLAN.md) supplies W07/T08/T09/C01/C02 scope;
the [optimisation reference](OPTIMISATION_REFERENCE.md#O07) supplies the existing
matched-work/preconditioning policy. Current Atlas source, cases and named tests
were inspected without rerunning their suites or extending scientific acceptance.
