# I01: nonlinear rock resistance through a supplied column

27 September 2026. WORKING NON-CANON. Independent of the evolving thermal task.

## What this does, in plain language

Cold and hot rock should not resist deformation in the same way. Nor should
quartz-rich crust and olivine mantle use one arbitrary constant viscosity. This
component calculates resistance from each layer's supplied temperature, pressure,
grain size and flow laws, then integrates that resistance through its thickness.
Several creep mechanisms can act together; frictional yielding adds another way
to deform. The same calculated stress determines the dissipated work.

It supplies a nonlinear constitutive calculation and a column diagnostic that
later breakup work needs. It does not itself create a fault, find a rift or solve
force balance. The existing D2 solver and Claude's thermal/history files remain
unchanged; the new law is not silently substituted into either.

## Constitutive contract

Stress and strain-rate invariants are `s=sqrt(tau:tau/2)` in Pa and
`e=sqrt(eps:eps/2)` in s^-1. Each mechanism has explicit, already invariant/SI
coefficients, with grain size in m, absolute temperature in K, energy in J/mol,
activation volume in m^3/mol and absolute mean pressure in Pa:

`e_i = A_i d^(-m_i) s^(n_i) exp[-(E_i+P_mean V_i)/(R T)]`.

All mechanisms share stress and their strain rates add. Taking the minimum of
their separate stresses or adding viscosities is not this constitutive model.
For the declared 2D friction convention, retained from I01_STRENGTH:

`Y=C cos(phi)+max(P_mean-P_pore,0) sin(phi)`;
`e = sum(e_i) + max(s-Y,0)/(2 eta_p)`.

The plastic viscosity is explicit positive physical regularisation, not a
numerical floor/cap. Stress can exceed Y. Setting the plastic branch to `None`
explicitly disables it. Cohesion/weakening and pore pressure are supplied; they
are not generated or evolved here. Creep uses total mean pressure, never the
effective friction pressure. Negative effective pressure is the stated
compressive-friction clamp, not a tensile-fracture or fluid-pressure model.

At zero rate the stress is zero and the linear tangent is left undefined. At
positive rate the returned consistent tangent is `ds/de=1/(de/ds)`. Values outside
the declared floating-point support are refused, not clipped to a viscosity.
Numerically negligible individual rates may underflow to zero; the summed rate
must still meet the frozen relative residual tolerance. All active laws have
stress exponents 1..8, so the summed stress-rate relation is monotone.

## Laboratory conventions: a necessary conversion

For an incompressible uniaxial laboratory experiment with axial strain rate a
and differential stress D: `e=sqrt(3)*abs(a)/2`, `s=abs(D)/sqrt(3)`.
Thus an axial/differential-stress coefficient becomes
`A_II=3^((n+1)/2) A_lab/2`, after unit conversion. An MPa-based stress coefficient
also gets `10^(-6n)`; micrometre grain units get `10^(-6m)` for a `d^(-m)` law.
No second conversion is applied merely because the calculation is 2D.
Coefficients already in ASPECT's invariant convention must NOT be converted again.

The tests independently reconstruct the lab law and Newtonian limit, rather than
testing only two copies of the same converted formula. Conventions with von Mises
equivalent quantities or other published definitions require their own mapping.

## Column and work interpretation

Input is a finite ordered set of layers with positive thickness. Within each,
temperature, absolute mean pressure and pore pressure are explicitly piecewise
linear in depth; other coefficients are constant. Pressure is **not** silently
computed as overburden or claimed to satisfy vertical momentum. In extension,
mean pressure and lithostatic vertical normal stress generally differ because
the deviatoric vertical stress is nonzero. The mechanics owner must supply the
compatible pressure field before treating this as a resolved mechanical reaction.

For the declared coaxial, incompressible, uniform-rate plane-strain diagnostic,
`eps=diag(a,0,-a)` and `tau=diag(sign(a)*s,0,-sign(a)*s)`:

- horizontal-minus-vertical stress resultant `F=sign(a)*2 integral(s dz)` in N/m;
- work per horizontal area `W=a F=2 abs(a) integral(s dz)` in W/m^2;
- creep and plastic work partition this SAME total, not additional heat sources.

This is not absolute horizontal traction, an arbitrary fault reaction or an
orientation-independent rupture threshold. D4 decides what fraction of the
dissipated work becomes heat; this diagnostic does not add heat to stored state.
Actual material history and the evolving pressure/temperature fields remain with
their owners. No universal through-thickness cutoff or plate-breakup threshold is
introduced.

## Efficiency and acceptance

For each point, solve in log stress with a safeguarded Newton method. The minimum
of the single-mechanism stress roots is an upper bound. With M active branches,
dividing that stress by M is a lower bound: each branch's rate falls at least
linearly when stress is decreased (n>=1, Y>=0). This gives a tight bracket without
blind searches across orders of magnitude. The plastic derivative is evaluated
directly, avoiding a zero-times-infinity expression at yield. Bisection on the
same bracket remains an independent algorithmic comparison.

An immutable prepared column retains only quadrature weights and local
temperature/pressure-dependent coefficients. Reuse it for changed strain rates;
any profile/material change requires a new preparation. No history of iterates,
disk cache, parallel team or new dependency is needed. Bounds are 64 layers,
four mechanisms per point, 128 Gauss points per layer and 96 scalar iterations.

The case freezes a 2e-11 rate residual and a 0.3% 64-to-128-point column-force
change before execution. This is quadrature convergence for a supplied profile,
not mesh convergence of a coupled deformation calculation. Three illustrative
rock-law layers must weaken with +100 K and strengthen with tenfold rate.
Their coefficients follow the cited software example; profiles/rate are authored
fixtures, not Earth-wide calibration or reproduction of its numerical simulation.

Tests cover lab/SI conversions, an exact real-exponent composite solution, the
existing n=1 regularised law, analytical force/work, layer partition, pressure
versus pore pressure, tangent differentiation, yield/zero limits, cancellation,
immutable preparation and failure inputs. No unchanged mechanical suite is rerun.
The small benchmark compares identical prepared inputs and tolerances for ten
local solves; timing excludes imports and is not a whole-generator speed claim.

From the repository root:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_column.py -v
python -B tectonics/tools/check_i01_column.py --output NEW_PATH.json
```

Only a new receipt is written; the tool/case/test/this document are bound before
and after execution. Installed binaries and external publications are not sealed.

## Papers and software checked

- [Dannberg et al. (2017), The importance of grain size to mantle dynamics and seismological observations](https://doi.org/10.1002/2017GC006944),
  Supporting Information S1.1 and S1.3, especially S15-S19: invariant/laboratory
  conversion and common-stress composite creep. The independent read-only
  scientific check accessed the supplement; the main session's direct PDF fetch
  was blocked. The conversion was also derived independently from the tensors
  above and checked against the software conventions, not accepted solely from
  the inaccessible main-session fetch.
- [ASPECT continental-extension source](https://github.com/geodynamics/aspect/blob/main/cookbooks/continental_extension/continental_extension.prm),
  rheology block: already converted wet-quartzite, wet-anorthite and dry-olivine
  dislocation coefficients. It identifies Gleason & Tullis (1995), Rybacki et al.
  (2006), Hirth & Kohlstedt and Dannberg's conversion. Those original experiments
  were not all re-read here; inherited example values are not new validation of
  their entire physical applicability range.
- [ASPECT composite-creep implementation](https://github.com/geodynamics/aspect/blob/main/source/material_model/rheology/diffusion_dislocation.cc),
  `calculate_isostrain_viscosities`: shared-stress, summed-rate and logarithmic
  root approach. Atlas uses its own derived bracket and safeguarded iteration;
  no upstream source code was copied. The actual executable activation factor
  was inspected rather than relying on a comment with an extra n in its exponent.

The PDF skill prompted explicit checking of the convention equations; its
main-session access failure is retained above. No PDF artefact was authored.
