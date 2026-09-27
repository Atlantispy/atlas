# I01: evolving plastic weakening in a layered column

**27 September 2026. WORKING NON-CANON. Bounded adapter and controls, task
atlas-i01-weakening-20260927.** This connects the reviewed
[nonlinear column law](I01_COLUMN.md) to evolving plastic history. The column
kernel is imported read-only; its bytes are bound and compared with its own
[reviewed receipt](../evidence/i01-column-r1.json). The [case](../cases/i01_weakening_v1.json),
[tool](../tools/check_i01_weakening.py) and focused tests are bound by the
[reviewed weakening evidence](../evidence/i01-weakening-r2.json). D2/D4/D6 context is in the
[I01 contract](I01_PHYSICAL_CONTRACT.md).

This is not a native component, a rift or necking model, a rupture criterion or
a calibrated law. Section 8 says what it can and cannot give the breakup calculation.

## What is happening, in plain language

Rock that has already slipped is weaker than intact rock. The column kernel
answered one question: at a given temperature and pressure, how hard does a
layered column resist being stretched at a given rate? This adds memory. Every
material point records how much it has deformed plastically; that record lowers
its cohesion and friction; the column's resistance is recalculated from the
weakened state. Deforming at a fixed rate, the column's resistance falls. Pulled
with a fixed force, it stretches faster.

The pressure is also made consistent. In a stretched column the rock is squeezed
less than the weight of the rock above it would suggest, so frictional rock is
weaker in extension than in compression. The kernel cannot know this because its
pressure is supplied; here it follows from vertical force balance.

What it cannot do: a laterally uniform column stretches at the same rate
everywhere, so it cannot concentrate deformation into a rift. It gives the
resistance a wide, uniformly stretching region transmits and how history lowers
it. It does not say where or when a rift forms or breaks.

## 1. Representation, loads and boundaries

**Why not stack the thermal cell and the column?** The [thermal prototype](I01_THERMAL.md)
is a periodic, small-strain material cell with one material, a uniform reference
pressure and no depth. The column has depth, layering and overburden but no
lateral structure. Combining them would need a vertical conduction solver with
surface and basal temperature boundaries; the cell's periodic spectral operator
cannot supply it. Lateral localisation would still be missing. Temperature is
therefore **prescribed** here and thermal coupling stays a separate closure.

**Chosen representation.** A laterally uniform column in coaxial plane-strain
pure shear (`y` out of plane, `z` depth, positive down):

- kinematics `v = (a x, 0, -a z)`; the rate `a` is uniform, so every material
  point sees the same irrotational, coaxial strain rate;
- material depth coordinates at small strain. Accumulated axial strain is
  `epsilon = integral(a dt)`; neglected geometric terms are `O(epsilon)`. A step
  that would take `|epsilon|` above 0.05 (the thermal cell's bound) is refused;
- temperature and pore pressure are supplied and fixed at material points;
- raw plastic history `kappa` is stored at every Gauss point.

**Loads and boundaries.**

- The top surface is free and unloaded: `sigma_zz(0) = 0`. There is no water or
  sediment load.
- The column is laterally uniform, so `sigma_xz = 0`, and vertical momentum gives
  a lithostatic vertical stress exactly: `sigma_zz = -sigma_v`,
  `sigma_v(z) = integral_0^z rho g dz'`.
- The lateral boundaries impose either the axial rate `a` (rate control) or the
  transmitted force `F` (force control).
- The base is a material surface supported lithostatically. `F` includes only
  the column's own material.

## 2. Tensor, invariant, rate and work conversions

```text
eps_dot = diag(a, 0, -a)        e = sqrt(eps_dot:eps_dot/2) = |a|      q = 2|a|  (engineering)
tau     = diag(sgn(a) s, 0, -sgn(a) s)     s = sqrt(tau:tau/2)
          (isotropic, incompressible flow with eps_yy = 0 gives tau_yy = 0)
sigma   = -P I + tau,   sigma_zz = -sigma_v   =>   P = sigma_v - sgn(a) s
F   = integral (sigma_xx - sigma_zz) dz = sgn(a) 2 integral s dz          N/m
W   = integral tau:eps_dot dz = 2|a| integral s dz = a F                  W/m^2
2 s e = 2 s e_creep + 2 s e_p                 one total, partitioned once
kappa_dot = q_p = 2 e_p = max(s - Y, 0)/eta_p    raw engineering plastic shear
plastic dissipation per volume = s kappa_dot
```

- **Pressure closure.** In extension the mean pressure is the overburden minus
  `s`; in compression it is the overburden plus `s`. This is the D2 contract's
  `P_hydrostatic + P_dynamic`, with the dynamic part `-sgn(a) s` fixed exactly by
  this geometry. Near the surface in extension, `P` can be negative (tensile mean
  stress). The existing compressive-friction clamp `max(P - P_pore, 0)` then
  applies; no tensile-failure law is claimed. Creep uses the total `P` in its
  activation-volume term.
- **Power.** The lithostatic boundary tractions and gravity exchange no net power
  in a laterally uniform column. The tectonic force's power `a F` therefore equals
  the deviatoric dissipation. Creep and plastic work are two parts of that one
  total, not extra heat sources.
- **Kernel convention.** The kernel is symmetric in the sign of `a` because its
  mean pressure is supplied. Supplying the lithostatic vertical load as the mean
  pressure overstates extensional frictional strength and understates
  compressional strength (section 6).
- **History convention.** ASPECT accumulates `integral(e dt)` of the *total*
  deviatoric second-invariant rate at yielding points. Atlas `kappa` (the D2 and
  thermal convention) is `2 integral(e_p dt)`. Where the plastic branch carries
  all the deformation, rates exceed ASPECT's minimum-rate floor, initial history
  matches and healing is absent, `kappa = 2 epsilon_ASPECT`; the control therefore
  maps ASPECT's interval 0.5–1.5 to `kappa` 1–3. Where creep also acts, `kappa`
  counts only the plastic share, which is a stricter material history. This is
  not an exact history conversion for every ASPECT regime.

## 3. Weakening law and material history

```text
u   = clip((kappa - k_s)/(k_e - k_s), 0, 1)
C   = C0 [1 - (1 - f_C) u],    phi = phi0 [1 - (1 - f_phi) u]          (ASPECT form)
Y   = C cos(phi) + max(P - P_pore, 0) sin(phi)                         (2D convention)
e   = sum_i A_i d^-m_i s^n_i exp[-(E_i + P V_i)/(R T)] + max(s - Y, 0)/(2 eta_p)
```

- **History monotonicity is certified, not assumed.** At fixed stress,
  `dY/du = -C0 (1-f_C) cos(phi) + C phi0 (1-f_phi) sin(phi) - P_eff phi0 (1-f_phi) cos(phi)`.
  The worst case is `P_eff = 0` at `u = 0`. Yield is therefore non-increasing in
  history for every admissible pressure if and only if
  `phi0 (1-f_phi) tan(phi0) <= 1 - f_C` wherever `C0 > 0`. For the case this is
  0.227 <= 0.75.
  - Friction-only weakening with non-zero cohesion fails this test: `C cos(phi)`
    rises near the surface. Such a law is refused rather than silently used.
  - With the certificate, every point's stress magnitude is non-increasing in
    its history, so `|F|` is non-increasing. Signed compressive `F` approaches
    zero from below; it does not become more negative.
- **Raw history is material history.** It is stored per material point. It only
  accumulates, at `kappa_dot <= 2|a|`, and is never filtered or written back.
- **No nonlocal field in depth.** The weakening input is the local raw value. The
  imposed uniform rate prevents localisation in depth: each point is an ODE with
  a bounded rate. A depth filter would mix brittle and ductile materials across
  layer boundaries with an invented length. D2's physical length (5 km) belongs to
  laterally resolved mechanics (section 8). A non-zero depth length is refused.
- **Not admitted and refused:**
  - healing: ASPECT offers a temperature-dependent option, but no law with
    provenance is admitted;
  - elasticity;
  - pore-pressure evolution;
  - finite strain;
  - thermal feedback.

## 4. Numerical method and efficiency

- **Preparation through the kernel.**
  - `check_i01_column.Column` builds the Gauss–Legendre points and the creep
    coefficients at `sigma_v`, or at the supplied mean pressure.
  - The adapter recomputes each point's yield and checks it equals the kernel's
    value bitwise.
  - Per-point arrays have immutable byte storage. A SHA-256 fingerprint of all
    inputs identifies reuse; stale inputs and changed replacement preparations
    are refused, including during the re-preparation comparison.
- **Local solve.** A vectorised safeguarded Newton in log stress for each point,
  with the kernel's residual, 2e-11 tolerance and 96-iteration limit.
  - Brackets start from the kernel's argument. Because the pressure closure moves
    branch roots, each bracket end is also checked by evaluation; the upper end
    doubles until bracketed.
  - For compressive creep with an activation volume, the rate must stay monotone:
    `n - s V/(R T) > 0` at the upper bracket, or the input is refused.
- **Time stepping.** Heun (explicit trapezoid) for history and strain.
  - Accepted steps are atomic; a refused step books nothing.
  - The response at the committed state is reused as the next step's first
    stage, giving two solves per step, with warm starts.
  - At most 256 accepted steps.
  - The 0.05 strain bound is enforced on direct calls as well as the case file.
    This is one reference-window evolution, not a finite-strain restart API;
    carrying history to another call does not reset accumulated physical strain.
  - Direct calls also enforce the declared solver/step ceilings and validate
    nonnegative, bounded envelope allowances. Invalid inputs cannot relax them.
- **Force control.** `F(a)` is strictly increasing, so it is inverted by
  safeguarded Newton in log rate using `dF/da = 2 integral(ds/de) dz`, to a
  relative tolerance of 1e-10.
  At yield/clamp switches the returned value is a selected branch tangent,
  rather than a claim of a unique classical derivative at the kink.
- **Retained state.** Current history, one stage and scalar accounts, plus
  per-point dissipation and yield counts. No iterate history is kept.
- **Resources.** The command-line run leases single-thread BLAS, has a 120 s
  cooperative budget and uses no background process or cache.

## 5. Predeclared controls

Tolerances were frozen in the case before the evidence run.

| Control | Checks and limits |
| --- | --- |
| kernel | Bound column case (supplied pressure, no history): adapter force, plastic work and every point stress equal the kernel within `1e-10`. Closed forms with negligible creep (`s = (C cos phi + (sigma_v - P_pore) sin phi + 2 eta e)/(1 +- sin phi)`, or `C cos phi + 2 eta e` at the clamp), both signs, weakened and not, within `1e-10`. Kernel re-prepared at `P* = sigma_v - sgn(a) s` reproduces every adapter stress within `1e-9`. Extension below the supplied-load convention, which is below compression. |
| homogeneous | Uniform layer versus a scalar DOP853 oracle, with the kernel re-prepared at every evaluation. Order in `[1.8, 2.2]`, finest history and force error `<= 1e-5`, uniform within `1e-13`, always yielding inside the interval. |
| local | Rate control: upper-crust history bitwise unchanged when the other layers are 100 K warmer. With weakening off, force is constant. From zero history, the published interval is unreachable and results equal no weakening bitwise. |
| layered | Base and +100 K, weakening on and off. Time steps 32/64/128 (change `<= 1e-4`); Gauss orders 32/64/128 per layer (force `<= 0.003`, weakening feedback `<= 3%`). Feedback at least 10 times the resolved change. Warmer column weaker. Monotone force decrease. Work partition `<= 1e-10`. Never-yielding history bitwise. Force window envelope. End-state fixed point. |
| force | Constant transmitted force: inverse consistency and no-weakening rate within `1e-8`; acceleration with weakening; `W = F epsilon` within `1e-9`; rates inside the constant-force envelope. |
| refusal | 23 unsupported inputs refused, including the history-monotonicity refusal. The small-strain step refusal books nothing. |
| reuse | Prepared coefficients reused versus re-prepared every step: bitwise-identical history, force and accounts; a changed input changes the fingerprint. |

## 6. Results (deterministic; original r1 control values)

The reviewed r2 keeps the physical laws, case and numerical tolerances unchanged.
It adds immutable-preparation and direct-entry/refill/window guards, plus three
regression tests. The original r1 receipt is retained as historical evidence;
the current source-bound result is r2. No old receipt was rewritten.

| Quantity | Value |
| --- | --- |
| Reviewed column case, adapter vs kernel | 2.5655385e13 N/m both; point stresses identical |
| Closed forms / fixed point | max 7.1e-13 / 4.8e-12 (256 points, both signs); 6 tensile-mean-stress points in extension |
| Vertical load supplied as mean pressure (inherited state) | 1.923e13 N/m, sign-symmetric |
| Lithostatic closure, extension / compression | 1.570e13 / 2.566e13 N/m: ratios 0.816 and 1.334 |
| Homogeneous oracle | observed orders 1.997, 1.998; finest errors 3.4e-7 (history), 8.4e-9 (force) |
| Base column, unweakened | 1.905e13 N/m |
| Inherited history, `kappa0 = 2` | 1.570e13 N/m (-17.6%) |
| Evolving weakening to strain 0.04 at 1e-15/s | 1.539e13 N/m (-1.97%) |
| +100 K column | unweakened 7.646e12; inherited 6.755e12 (-11.7%); evolved 6.675e12 (-1.19%) |
| Time change, 64 to 128 steps (order) | 4.0e-10 (2.00) |
| Depth change, 64 to 128 points per layer | 4.8e-5 force; 5.0e-4 of the feedback |
| Yielding depths, base (evolved) | 0–16.5, 20–31.7 and 40–46.1 km; mantle below 50 km creeps |
| Yielding depths, +100 K (evolved) | 0–11.7 and 20–24.7 km; mantle lid creeps |
| Plastic share of work, base / +100 K | 56.3% / 34.5% |
| Force control at 1.570e13 N/m | rate ×1.230 by strain 0.0443; envelope 1.000–1.318e-15/s |
| Dissipation diagnostic | max 2.6e7 J/m^3, about 10.5 K if kept locally; conduction length 7.0 km over 1.27 Myr |

These are properties of an authored fixture, not Earth-wide values. The dominant
effect is the inherited history, set as an initial assumption. Evolving weakening
at small strain changes the transmitted force by only about 2%.

## 7. The supported force–rate–history interface

For a prepared column and a history array:

```text
respond(prep, law, kappa, a)          -> F, dF/da > 0, W = aF = creep + plastic, kappa_dot = 2 e_p >= 0
respond_force(prep, law, kappa, F)    -> a with F(a) = F (strictly increasing, unique)
evolve(... control="rate"|"force")    -> atomic Heun history/strain evolution with accounts
force_envelope(prep, law, kappa, [a_lo, a_hi], t)   -> |F| in [F(a_lo; kappa + 2|a_hi| t), F(a_hi; kappa)]
rate_envelope(prep, law, kappa, F, eps)             -> |a| in [a(F; kappa), a(F; kappa + 2 eps)]
```

**Guarantees:**

- `F` is strictly increasing in the rate.
- `|F|` is non-increasing in each point's history, for certified laws.
- History rises at most `2|a|` per unit time.
- The two envelopes are mathematical window bounds on the admitted monotone
  branch. Computed endpoints have solver/round-off error; this implementation
  does not provide outward-rounded interval certificates.

**Validity:** laterally uniform deformation, lithostatic vertical stress below a
free surface, small strain, prescribed temperature and pore pressure, no
elasticity or healing.

**Fit with the decoupling family.** The [decoupling admission](I01_DECOUPLING.md)
family `F = D v + Y + a v^(1/n)` is not this law. That family has one integer `n`;
this column has several exponents, including 3.5, pressure-dependent yield and
history. Using this column's resistance there needs one of two things:

- an admission rule for a monotone function over the window (the envelopes above
  supply its corner values);
- or a separately certified bounding member of the family.

The velocity mapping `v = a w` also needs a deforming width `w` that the column
does not know.

## 8. What this gives the breakup calculation, and what it cannot

**Demonstrated issues:**

1. **Pressure closure.** The kernel's supplied-mean-pressure convention is correct
   only when the owner supplies the compatible pressure. For this geometry that
   pressure is `sigma_v - sgn(a) s`. Using the overburden overstates extensional
   resistance by 22.5% at the case's state. This is not a kernel defect; the
   kernel documents the requirement.
2. **Published weakening is out of reach of a homogeneous column.** Plastic strain
   cannot exceed total strain. Reaching ASPECT's interval start from zero history
   needs homogeneous axial strain of at least 0.5 (stretching factor
   `e^0.5 = 1.65`), ten times the small-strain bound. The local control shows zero
   weakening up to the bound, bitwise identical to no weakening.
3. **No localisation.** A uniform-rate column cannot concentrate strain.
   - Placing columns side by side with a common force (a thin sheet) is valid only
     for deforming widths much larger than the ~100 km thickness.
   - A 5 km nonlocal length, or a fault-scale zone, violates the depth-uniform-rate
     assumption by more than an order of magnitude.
   - Necking and rift-scale localisation need a laterally resolved x–z momentum
     solution.
4. **Prescribed temperature.** Over the 1.27 Myr window, local dissipation could
   heat the most stressed points by about 10 K, and conduction reaches about 7 km.
   A 10 K rise increases creep rates about 2.1 times for wet quartzite near 600 K
   and about 1.9 times for dry olivine near 1000 K (`exp(E dT/(R T^2))`). Thermal
   feedback is not negligible for longer windows.

**What it can provide:** the depth-integrated resistance of a wide,
uniformly deforming region; its dependence on rate, temperature, layering,
pressure closure and history; mathematical window envelopes; and a local history
update that a laterally resolved solver could call per column or per point.

**Still needed for physical breakup:**

- **Lateral mechanics.** An x–z momentum solution with a physical localisation
  length (the D2 nonlocal length or another regularisation), refinement in both
  directions, and the deforming width.
- **Finite strain.** Thinning (stretching factor), transported temperature and
  history, and asthenospheric inflow at the base.
- **Thermal evolution.** Conduction, advection and a D4 partition of dissipated
  work.
- **Driving force.** The transmitted force from the D1 force balance. This column
  gives resistance only.
- **Buoyancy.** Gravitational-potential-energy differences, isostasy, and
  water/sediment loads (D5).
- **Other material laws.** Elastic and flexural stresses, healing, pore-fluid
  pressure, melt weakening and supply (D6 and melting), each with provenance.
- **Separation criterion.** An admitted through-lithosphere separation law and a
  connectivity change (D6), not a thickness, damage or force cutoff.
- **Calibration.** Calibrated weakening interval, factors, plastic regularisation
  and inherited history, with provenance.

## 9. Sources

**Read for this task:**

| Source | Used for |
| --- | --- |
| [ASPECT `strain_dependent.cc`](https://github.com/geodynamics/aspect/blob/main/source/material_model/rheology/strain_dependent.cc) | `calculate_plastic_weakening` interval formula (transcribed independently for the tests); strain increment `sqrt(-J2(dev(eps_dot))) dt`, credited to plastic strain only while yielding; temperature-dependent healing option (not admitted) |
| [ASPECT continental-extension parameter file](https://github.com/geodynamics/aspect/blob/main/cookbooks/continental_extension/continental_extension.prm) | Dislocation-creep coefficients, densities, cohesion, friction, gravity, the weakening interval and factors, the initial plastic strain `0.5 + rand` in the central 100 km of the upper 50 km, and the diagnostic heat capacity and conductivity |
| [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) | Purpose of the inherited strain (localising deformation); 893 K Moho isotherm; the stated inability to represent breakup (100 km depth, no asthenosphere) |
| [ASPECT material-model documentation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Material_20model.html), Visco Plastic | 2D Drucker–Prager `C cos(phi) + P sin(phi)`; plastic-strain-only tracking; viscosity rescaled to the yield surface |
| [Brune et al. 2014](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf), Methods | Friction coefficient 0.5 reduced linearly to 0.05 by accumulated plastic strain 1; viscous softening; random initial friction 0.4–0.5 to break symmetry. The coefficient form is recorded, not implemented; Brune's strain-invariant definition is not stated in the text read |

ASPECT was not installed or run. No external code was copied.

**Reused from earlier I01 work:** the column kernel's own references (Dannberg et
al. 2017 supplement conversions; ASPECT `diffusion_dislocation.cc`); Gurnis, Hall
and Lavier (2004) on structure-dependent initiation; Brune 2014 thermal and melt
Methods (section 10 of the I01 contract).

**Access failures:** these papers were not read, and no claim depends on them.

- Naliboff et al. (2017), Nature Communications: the publisher required a cookie
  sign-in; PubMed Central returned a reCAPTCHA, which was not bypassed.
- Huismans and Beaumont (2003), JGR: Wiley returned HTTP 403; the Dalhousie
  mirror had a certificate mismatch.
- Lavier, Buck and Poliakov (2000), JGR: the author PDF is an image scan with no
  extractable text; only the search-result abstract was seen.
- Buck (1991), JGR: ADS returned HTTP 405. Only a secondary EGU blog summary was
  seen, noting thin-sheet force changes select rift modes.

## 10. Commands and bindings

From the repository root, using the existing scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_weakening.py -v
python -B tectonics/tools/check_i01_weakening.py --output NEW_PATH.json
```

The receipt binds this document, the tool, case and tests, the imported
`check_i01_column.py`, the reviewed column case it reads, and the column receipt
whose recorded kernel hashes it compares, both before and after execution.
Timings exclude imports.

**Not done:**

- No native source, shared status document or existing receipt was changed.
- No existing test suite was rerun.
- The reuse comparison is one matched observation, not a generator speedup.
