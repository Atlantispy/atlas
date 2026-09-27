# I01: evolving thermal and material history

**27 September 2026. WORKING NON-CANON. Bounded prototype, task
atlas-i01-thermal-20260927.** This advances the reviewed
[pressure/temperature snapshot](I01_STRENGTH.md) and its
[2D localisation probe](I01_FAULT2D.md) in time. Their tools are imported read-only
and bound by bytes; nothing in them is changed. D2/D4 context is in the
[I01 contract](I01_PHYSICAL_CONTRACT.md). The [case](../cases/i01_thermal_v1.json),
[tool](../tools/check_i01_thermal.py) and focused tests are bound by the
[reviewed thermal evidence](../evidence/i01-thermal-r2.json).

This is not a native component, a finite-strain model, a lithosphere column or a
calibrated planetary law. Section 6 lists the scientific closures that remain open.

## What is happening, in plain language

Deforming rock does work. In viscous creep and frictional slip that work becomes
heat, and conduction then spreads the heat out. Warmer rock creeps more easily, and
rock that has already slipped is weaker. The snapshot solver answered one question:
given this temperature and this damage, what is the stress? This prototype adds
time. Temperature and damage change as the rock deforms, and each new mechanical
state uses them. Heat and damage stay attached to the rock that carries them.

## 1. Support and kinematics: a small-strain cell in material coordinates

The D2 solver represents a periodic square in which velocity is
`v = G x + v~(x)`. Here `G` is an imposed mean velocity gradient and
`v~ = (psi_y, -psi_x)` is a periodic fluctuation whose vorticity is exactly the
solver's `chi = -Laplacian(psi)`.

**The affine part `G x` is not periodic.** Advecting a periodic field with it on
the fixed square would make the periodic images disagree by `G L`. That false
transport is refused. Instead, every field lives at a **material point**: in
reference coordinates `X`, the material derivative is simply `d/dt` at fixed `X`,
so no advective term has to be approximated. This is the geometrically linear,
small-strain setting in which the mechanical solver is already formulated (a fixed
square with fixed wavenumbers). Moulinec and Suquet (1998) integrate internal
variables pixel by pixel in the same periodic small-strain cell.

Validity is monitored, not assumed:

```text
H(X,t) = integral grad(v) dt,   grad(v) = [[e_xx, e_xy - chi/2], [e_xy + chi/2, -e_xx]]
refuse any step that makes max over X of |H|_2 exceed 0.05 (declared bound, <= 0.1)
```

`H` includes local rotation and the cell's own mean deformation. Neglected
geometric terms are of order `|H|`. The mean spin is zero; a rotating reference
cell is not represented.

Among affine mean motions, only **uniform translation** is periodic. Its Eulerian
view is a spectral shift: exact for band-limited fields and for whole-cell shifts
of any field. The material fields themselves never change under translation.

**Refused states:**

- Eulerian advection with a non-zero affine gradient.
- A non-zero mean spin.
- A step beyond the strain bound, or a strain bound above 0.1.
- Nonlocal history the grid cannot resolve (negative filtered values).
- More than 256 steps.

**Not claimed:** large strain, finite rotation, deforming-lattice remapping, or
Eulerian transport.

## 2. Equations, units and ownership

Units are SI with temperature in kelvin. Mechanics keeps the D2 scaling: stress
unit 30 MPa, engineering-rate unit 1e-14 /s, `g=(2 e_xx, 2 e_xy)`, `q=|g|`,
`s=|t|`.

```text
rho cp dT/dt = k Laplacian(T) + f_v Phi_v + f_p Phi_p               W m^-3
Phi = t.g = s q,   q = q_v + q_p,   Phi_v = s q_v = s^2/eta_v,   Phi_p = s q_p
d kappa/dt = q_p = max(s - Y, 0)/eta_p        raw engineering plastic shear
kappa_bar - ell^2 Laplacian(kappa_bar) = kappa   weakening input only, never stored
C = C0 [1 - (1 - r) min(kappa_bar/kappa_c, 1)]
Y = C cos(phi) + max(P_ref + p - P_pore, 0) sin(phi)
eta_v(T) = eta_ref exp[Q/R (1/T - 1/T_ref)]
stored-energy rate = (1 - f_v) Phi_v + (1 - f_p) Phi_p
W = <t>.G  (imposed mean deformation)  =  <t.g>  (checked in every solve)
```

- **Work.** Work through the imposed mean deformation, `W`, is the cell's only
  energy input.
- **Heat.** `q_v` and `q_p` split one rate, so `Phi_v + Phi_p = t.g` exactly (the
  control checks this). Plastic work is never added a second time on top of a
  viscous total. ASPECT's shear heating adds `2 eta eps':eps'` with the material
  model's viscosity; when that viscosity already includes yielding, this is the
  same total, counted once.
- **Stored energy.** The complement `(1 - f) Phi` goes to a named stored account
  with no feedback. The case selects `f_v = f_p = 1`: all dissipation becomes
  heat. A rock-specific partition of plastic work is not admitted.
- **Conduction.** Conduction in the periodic cell has zero net boundary flux, so
  thermal energy changes only through the owned heat source.
- **Omitted by declaration:**
  - radiogenic, adiabatic and latent heat, thermal expansion, buoyancy and
    thermal pressurisation;
  - evolution of pore pressure, which stays the supplied constant;
  - elasticity;
  - healing (a non-zero rate is refused).

  One material has constant `rho`, `cp` and `k`.
- **Pressure.** Effective confinement is the uniform reference plus the zero-mean
  dynamic pressure, minus pore pressure, clamped at zero as in D2. Temperature
  enters only through creep viscosity.

## 3. Time integration and accepted steps

```text
S = heat/(rho cp);  z = -kappa_T k^2 dt;  E = e^z
predictor   T_a = E T_n + dt phi1(z) S_n              (per Fourier mode)
            kappa_a = kappa_n + dt q_p,n
stage       D2 solve at (T_a, kappa_a) -> S_a, q_p,a, grad(v)_a
corrector   T_n+1 = T_a + dt phi2(z) (S_a - S_n)
            kappa_n+1 = kappa_n + dt (q_p,n + q_p,a)/2;   H_n+1 = H_n + dt (L_n + L_a)/2
phi1 = (e^z - 1)/z,   phi2 = (e^z - 1 - z)/z^2
```

- **Temperature scheme.** This follows from the exact variation-of-constants
  formula (Kassam and Trefethen 2005, equation 2.1), with the source varying
  linearly over the step. Conduction is exact at any step size, and the scheme is
  second order.
- **Energy quadrature.** For the zero mode (`z = 0`) the update is the trapezoid
  of `S`, so mean temperature and the energy accounts use the same quadrature.
  `phi2` is evaluated with a series for `|z| < 1e-2`, avoiding cancellation.
- **History.** Raw history and `H` use Heun steps with the same stage values.
- **Mechanics.** Each stage calls the unchanged `check_i01_strength.solve`, with
  its tolerances: equilibrium 1e-10, pressure 1e-9, momentum 1e-7 and work 1e-8.
  It is warm-started from the last accepted solution.
- **Atomic acceptance.** Fields and accounts commit together. A refused step
  leaves the previous state and accounts unchanged. The refusals are:
  - temperature change above 5 K in one step (an accuracy guard on the explicit
    coupling);
  - the strain bound;
  - any decrease of raw history.
- **Step ceiling.** At most 256 steps are accepted; that ceiling is unchanged.

## 4. Predeclared controls

| Control | Kind | Checks and limits |
| --- | --- | --- |
| translation | transport only | Material fields unchanged; band-limited shift, round trip and whole-cell shift within `1e-12`; affine Eulerian advection refused |
| manufactured | thermal only | Forced two-mode solution, including a stiff mode (`kappa k^2 dt > 1`); observed order in `[1.8, 2.2]`; finest error `<= 1e-3`; exact pure diffusion within `1e-12` |
| homogeneous | coupled, uniform | Independent scalar DOP853 oracle for temperature rise and history, with order in `[1.8, 2.2]` and finest error `<= 1e-6`. Also checked: exact uniformity, `Phi_v + Phi_p = t.g` within `1e-12`, energy balance `<= 1e-8` (quadrature identity `<= 1e-10`), `f_p = 0.5` ownership, and subyield keeping raw history exactly |
| coupled | genuinely coupled 2D | 17/33/65 cells and 16/32 steps. Stress, mean and RMS changes, and spectrally resampled fields, each change `<= 3%`. Energy `<= 1e-8`, history quadrature `<= 1e-12`, strain bound respected. Heating and weakening feedback each at least 10 times the resolved discretisation change. Warm and cold starts agree within `1e-6` |
| refusal | refusal | Small-strain and temperature-step refusals without booking; healing, spin, heat fraction, strain bound and unknown-law case fields refused; 257 steps refused |

The coupled fixture combines several parts, all at fixed physical coordinates on
every grid:

- a large-scale 80 K temperature mode;
- a 30 K warm spot 10 km wide;
- two 7.5 km history seeds, as in the 2D probe.

These are initial geological assumptions, not nucleation. The quadrature-identity
bound `1e-10` reflects round-off in differences of ~1000 K means, set before the
recorded run. The reviewed D2 tests (`test_i01_strength.py`, `test_i01_fault2d.py`)
are rerun unchanged.

## 5. What these checks do and do not establish

They support one bounded claim. In a small-strain periodic cell, temperature and
raw plastic history evolve at material points under an exact conduction operator
and a second-order coupled quadrature. Heating comes once from the constitutive
dissipation, with mechanical work, heat and stored-energy accounts closing.
Temperature (through creep) and filtered history (through cohesion) feed back into
a converged D2 pressure/temperature solve.

**This cell cannot demonstrate thermal localisation.** Shear heating raises
temperature by `tau gamma/(rho cp)`, and creep viscosity halves after about
`ln2 R T^2/Q`. So thermal softening needs an engineering strain of roughly
`rho cp R T^2 ln2/(Q tau)`. For these inputs (`tau` about 72 MPa, 1000 K,
120 kJ/mol) that is about 2.6, far beyond the 0.05 bound. The coupled case
therefore shows small, resolved feedback, not runaway. Weakening through history
is the stronger feedback over this strain.

## 6. Remaining scientific closures

1. **Finite strain.** Needed: a deforming-lattice or remapped periodic cell, or a
   finite-strain reference formulation, with its mechanical solver. Material
   transport beyond the 0.05 bound is refused until then.
2. **Elasticity.** Elastic stress memory with objective transport (D2 input 1).
3. **Pore fluid.** Pore-pressure evolution and fluid transport. Pore pressure is
   supplied constant.
4. **Healing.** A law with temperature dependence and provenance. Zero is the only
   admitted rate.
5. **Heat partition.** A rock-specific split of plastic work between heat and
   stored energy. All dissipation is heat here.
6. **Omitted heat terms.** Radiogenic, adiabatic or compressional and latent heat;
   thermal expansion and buoyancy; gravity and a free surface (D5).
7. **Open thermal boundaries.** Exchange with surroundings or the mantle. The
   periodic cell is closed.
8. **Materials.** Multiple materials with interface flux (D4 section 6 and I05),
   dislocation or grain-size creep, and calibrated parameters with provenance.
9. **Embedding.** Placing this cell inside I03/I05 transport and the global model.
   The cell is a local material-point experiment.

## 7. Efficiency

- **Prepared once.** Spectral operators are prepared once per grid, and the
  exponential factors once per grid and step.
- **Warm starts.** Each solve starts from the last accepted solution; the evidence
  records one warm-versus-cold comparison of the same run.
- **Retained state.** Only current fields, one stage and scalar accounts are kept;
  no iterate history is stored.
- **No dense matrices.** Every field operation is `O(N log N)` FFT work.
- **Threads.** The command-line run leases single-thread BLAS and restores it
  afterwards.
- **Time budget.** The campaign has a cooperative 150 s budget.

Raw times are control observations, not a generator forecast.

## 8. Sources

**Read for this task:**

| Source | Scope | Used for |
| --- | --- | --- |
| [Moulinec and Suquet 1998](https://arxiv.org/pdf/2012.08962), author version | Full paper | Periodic cell `u = E x + u*` with `u*` periodic; internal variables integrated per pixel at small strain; exactness conditions for the discrete Fourier transform; extrapolated initial guesses |
| [Kassam and Trefethen 2005](https://people.maths.ox.ac.uk/trefethen/publication/PDF/2005_111.pdf) | Full paper | Integrating-factor and exponential time differencing; exact variation-of-constants form; small-`z` cancellation |
| ASPECT [heating models](https://aspect-documentation.readthedocs.io/en/latest/parameters/Heating_20model.html) | Documentation | Shear heating `2 eta eps':eps'`; summed heating models |
| ASPECT [particle properties](https://aspect-documentation.readthedocs.io/en/latest/parameters/Particles.html) | Documentation | Lagrangian strain history (`integrated strain`, invariants) and objective elastic-stress update |
| ASPECT [operator-splitting benchmark](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/benchmarks/operator_splitting/doc/operator_splitting.html) | Documentation | First-order advection–reaction split |

ASPECT was not installed or run.

**Reused from earlier I01 reading:**

- Brune et al. (2014), Methods: `cp = 1200`; particle-in-cell transport of
  accumulated plastic strain; shear heating in SLIM3D.
- Clennett et al. (2023), Table S1: `rho = 3300`, `kappa = 1e-6`.
- Gurnis, Hall and Lavier (2004): Lagrangian elasto-visco-plastic weakening.

**Not read:**

- Kiss et al. (2019), on thermal localisation: not openly available here. The
  estimate in section 5 is derived.
- Cox and Matthews (2002): the scheme is derived from Kassam and Trefethen
  equation 2.1.
- Finite-strain spectral solvers such as DAMASK: not accessed.

**Existing Atlas code:** `check_i01_strength.py` and `check_i01_fault2d.py`,
imported unchanged; their receipt hashes are compared in the evidence.

## 9. Integration review

Review verified the mechanical power partition, Fourier heat step, engineering-
strain/vorticity conventions and linear-reference displacement-gradient bound.
It found an input guard gap, not a change to the accepted fixture's numerical
method: direct `evolve` calls skipped case validation, coordinate/affine-use
declarations were not enforced, and extra nested mechanics laws were ignored.
The public evolution entry now validates before solving; unsupported declarations
and additional mechanics laws are refused. Two added regression tests cover these
cases (13 focused tests total). The separate translation control remains a
transport-only check, not evidence of finite-strain coupled advection.

The [original r1 receipt](../evidence/i01-thermal-r1.json) is retained byte-identical
as historical evidence; r2 binds the corrected tool, tests and explanation.
No constitutive law, case input or numerical acceptance tolerance changed.
The unchanged strength/fault helper checks are reused, not rerun for handoff.
