# I01 D2: pressure and temperature in the mechanical response

WORKING NON-CANON. A bounded extension of the [2D localisation probe](I01_FAULT2D.md),
not its replacement and not a native production component. The earlier receipts,
case, tool and physical contract remain unchanged. This document and the new
case/tool/tests are bound by the new receipt.

## What is happening

Warm rock generally creeps more easily; confinement resists frictional failure,
while pore-fluid pressure reduces that confinement. Deformation itself also
changes pressure. We therefore cannot calculate a pressure-sensitive strength,
solve once, then attach a different pressure map without recalculating strength.

This tool solves that feedback at a supplied temperature and material-history
snapshot. It returns strain rate, deviatoric stress, dynamic pressure, strength
and plastic strain rate from the same converged state. It does not repaint or
smooth a generated boundary to resemble a fault.

## Equations, units and support

Use the earlier incompressible, small-strain, periodic square. Engineering rate
`g=(2 e_xx,2 e_xy)`, `q=|g|`, deviatoric stress `t=(tau_xx,tau_xy)`, and total
stress `sigma=-p I+tau` retain the earlier factors and signs. The out-of-plane
deviatoric component is zero in this isotropic, incompressible, non-elastic case.

```text
eta_v(T) = eta_ref exp[Q/R (1/T - 1/T_ref)]
P_eff = max(P_ref + p_dynamic - P_pore, 0)
Y = C cos(phi) + P_eff sin(phi)
q = s/eta_v(T) + max(s-Y,0)/eta_p
t = s g/q                    (t=0 at q=0)
```

Temperature is kelvin and activation energy J/mol. This is the `n=1`, fixed-grain,
zero-activation-volume creep branch, not an unconverted dislocation-creep law.
It has no numerical viscosity floor/cap. Unrepresentable values are refused.
Friction uses the declared 2D convention; plastic flow has zero dilation and is
therefore non-associated when friction is nonzero. The negative effective-pressure
clamp is the declared compressive-friction branch, not a tensile-fracture model.

The mechanical implementation scales stress by 30 MPa and engineering rate by
1e-14 /s, so one viscosity unit is 3e21 Pa s. The case explicitly supplies all
coefficients, including a spatially uniform confining reference and pore pressure.
These are **authored numerical fixtures, not calibrated planetary defaults**.
A zero-mean dynamic field does not determine absolute confinement. The periodic
test has no depth-dependent gravity/free surface; do not interpret its uniform
reference as a calculated lithostatic column.

The 2D fixture supplies smooth temperature and raw accumulated plastic history at
fixed physical coordinates. The retained Helmholtz operator with 5 km length
filters only history's influence on cohesion, which saturates at its residual
fraction. Raw history is not filtered back into storage or advanced here.
Temperature affects creep; no unsupported direct thermal cohesion law is invented.
Heating/cooling, healing, material transport, dislocation creep, elastic memory,
calibration and rupture remain separate work.

## Pressure and nonlinear solution

Retain `g=G+A chi`, `chi=-Laplacian(psi)`, with the prepared Fourier projector
`A=(-2 kx ky, kx^2-ky^2)/k^2`. For every nonzero mode:

```text
B = (kx^2-ky^2, 2 kx ky)/k^2
p_hat = B . t_hat
A . t_hat = 0
```

The zero dynamic-pressure mode is fixed to zero; `P_ref` supplies the absolute
reference. The pressure sign follows directly by taking the divergence of
`div(tau)-grad(p)=0`. `A` and `B` are orthogonal unit vectors mode by mode.
Independent direct Cartesian derivatives check both components of momentum.

At frozen pressure/strength the existing constitutive potential is convex.
Newton with a matrix-free conjugate-gradient tangent solve and backtracking is
valid for this **inner** problem. The coupled non-associated law is not declared
convex: use bounded under-relaxed pressure iteration outside it. Positive finite
viscosities, input shapes, pressure gauge, residual policy and resource limits
are checked; nonconvergence is a refusal, not a fallback to pressure-free strength.

Accept the actual returned pressure/strength/stress together. Test the unrelaxed
pressure mismatch, projected equilibrium, full momentum and equality of local
dissipation with macroscopic work. A tiny damping factor cannot fake convergence.
There is no uniqueness or universal-convergence claim for the coupled law.

## How we know this implementation is solving those equations

The policy was declared before the campaign:

- Homogeneous yielded, subyield and zero-rate states have exact scalar answers.
- A Fourier stress mode parallel to `B` has an exact pressure with zero momentum
  residual; reversing its sign fails. An `A` mode has no pressure and nonzero force.
- An independent temperature/pressure oracle uses `T(x)`, `G=(1,0)`, uniform
  cohesion and the wholly yielded, positive-confinement branch. Put
  `alpha=eta_v/(eta_v+eta_p)`, `K=eta_v*eta_p/(eta_v+eta_p)+alpha*Y0`,
  `beta=alpha*sin(phi)`, and
  `S=mean(K/(1-beta))/mean(1/(1-beta))`. Then
  `p=(K-S)/(1-beta)`, `t=(p+S,0)` and `chi=0` exactly. Check its branch assumptions,
  not just its numerical match. Maximum pressure/stress error must be <=1e-7
  relative to `S`.
- The genuinely 2D snapshot uses 17/33/65 cells per side. Final changes in
  macroscopic stress-work, pressure RMS and plastic-rate RMS must each be <=3%.
  This is spatial convergence of snapshots, not time refinement of a thermal run.
- Full momentum must be <=1e-7 after scaling by physical length/stress;
  pressure mismatch <=1e-9, projected equilibrium <=1e-10, and work mismatch
  <=1e-8. RMS of Cartesian components is used for the momentum norm.
- A nearby temperature change is solved once from the preceding solution and
  once from zero. Stress, pressure and strain-rate RMS differences must be
  <=1e-7 relative. Both must independently meet the same physical residual gates.

Inputs/iteration failures, the pressure clamp and the no-friction reduction to
the original solver have focused regression tests. Passing these checks supports
this bounded constitutive/numerical connection, not global geological realism.

## Efficiency and recording

Reuse the prepared spectral operators, fixed-temperature viscosity field and
preceding pressure/strain solution. Keep only active fields, not every iterate.
No dense matrix assembly or new cache store is needed. A scoped one-thread BLAS
lease avoids nested teams for these small solves and restores the caller's policy.
The whole control campaign has a cooperative 120 s budget. The output retains
completed cases on a later failure and is created exclusively, without overwrite.

Run `python -B tectonics/tools/check_i01_strength.py --output NEW.json` using the
existing scientific environment. The receipt includes source/case/method/test
hashes, library versions, each solve's iterations and raw times after imports.
Warm-versus-cold timings are one local comparison, not a general performance
promise; a negative saving must remain visible. No world-scale run is involved.

## Papers and existing software consulted

- [Duretz et al. (2021)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2021GC009675):
  sections 2 and 4.2 distinguish friction, non-associated flow, rate regularisation,
  pressure effects and nonlinear difficulty. The paper's compressible/elastic
  implementation is not claimed reproduced here.
- [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html):
  explicit material/temperature-dependent rheology, strain history and conversion
  between laboratory stress conventions and numerical invariants. Its calibrated
  rock parameters and free-surface evolution are not borrowed as fixture defaults.
- ASPECT [static/dynamic pressure](https://aspect-documentation.readthedocs.io/en/latest/user/methods/pressure-static-dyn.html)
  and [normalisation](https://aspect-documentation.readthedocs.io/en/latest/user/methods/pressure-norm.html):
  separate the dynamic solution from the reference needed by material properties.
  Documentation was inspected; ASPECT itself was not installed or run.

The pressure projection and manufactured oracle above are derived for Atlas's
declared Fourier representation, not asserted to be a published benchmark.
