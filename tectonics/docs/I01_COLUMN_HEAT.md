# I01: heat conduction and dissipation feedback in a layered column

**27 September 2026. WORKING NON-CANON. Bounded coupling and controls, task
atlas-i01-column-heat-20260927.** This makes temperature evolve inside the
reviewed [layered weakening column](I01_WEAKENING.md) and feed back into its
resistance and history. The reviewed helpers `check_i01_weakening.py` and
`check_i01_column.py` are imported read-only; their bytes are bound and compared
with the weakening receipt named by `WEAKENING_RECEIPT`. The
[weakening r2 receipt](../evidence/i01-weakening-r2.json) binds the layout before the
I02.2a package move; its designated successor `i01-weakening-r3` is evidence only
once captured, reviewed and listed as current in the
[evidence register](../../docs/CURRENT_EVIDENCE.md). The
[case](../cases/i01_column_heat_v1.json), [tool](../tools/check_i01_column_heat.py) and focused
tests as first delivered are bound by the [column-heat r1 evidence](../evidence/i01-column-heat-r1.json).
Review corrections (section 10) changed the tool, tests and this document. The
[reviewed r2 receipt](../evidence/i01-column-heat-r2.json) records the corrected
controls and volume-weighted means; r1 is historical, not rebound.
D4 context is in section 6 of the [I01 contract](I01_PHYSICAL_CONTRACT.md).

This is a fixed-geometry, small-strain column. It is not a finite-strain rift,
generated breakup, a global thermal model or a calibrated heat partition.

## What is happening, in plain language

Deforming rock does work, and that work becomes heat. The weakening column
calculated the work but held temperature fixed. Here the heat stays in the rock
that produced it and spreads by conduction through the layered column. The surface
and base keep their temperatures. Warmer rock creeps more easily, so the column
resists less.

Over 1.27 million years of slow stretching, the column warms by up to 6.7 K. That
alone lowers the transmitted force by 3.1%, more than the evolving plastic
weakening does (1.9%) in the same window.

## 1. Column, boundaries and initial state

**Mechanics.** The reviewed weakening case is used unchanged: layers and their
densities, rheologies, weakening law, gravity, inherited history, the supplied
axial rate of 1e-15/s and the total strain of 0.04. It is plane strain,
`eps_dot = diag(a, 0, -a)`, with mean pressure `P = sigma_v - sgn(a) s`. The
layers are:

| Depth (km) | Material |
| --- | --- |
| 0–20 | wet quartzite |
| 20–40 | wet anorthite |
| 40–50 | dry-olivine lid |
| 50–100 | dry-olivine mantle |

**Control.** Supplied axial rate. The transmitted force is an output. Driving
force and drag belong to Codex's separate motion-coupling work, and supplied-force
control is refused here.

**Geometry.** A fixed, 100 km laterally uniform column in material depth
coordinates. This is a declared small-strain approximation: accumulated axial
strain `|epsilon| <= 0.05` and at most 256 accepted steps. There is no thinning,
no advection of heat or history, no inflow at the base and no topography.

**Thermal properties and boundaries** (SI units; temperature in K). All values are
from the ASPECT continental-extension parameter file:

- conductivity 2.5 W/m/K;
- heat capacity 750 J/kg/K;
- density from the mechanical layers (2700 / 2900 / 3300 kg/m³);
- radiogenic heat production 1.0e-6, 0.25e-6, 0 and 0 W/m³ by layer. ASPECT
  documents these compositional heating values as W/m³;
- fixed temperatures of 273 K at the surface and 1613 K at 100 km.

Interfaces are perfect thermal contacts: temperature and heat flow are both
continuous.

**Initial state.** The discrete steady solution of `k T'' + A = 0` with these
sources and boundaries. The D4 contract's layered steady conduction is an initial
condition, not a boundary history.

- It approximates the cookbook's analytic piecewise-quadratic geotherm to within
  0.0079 K at 64 points per layer.
- The analytic reference reproduces the cookbook's own constants: 633 K and
  893 K at 20 and 40 km; 55, 35 and 30 mW/m² at the surface, 20 km and 40 km.
- The mechanical template's linear temperatures from the weakening case are
  replaced by this thermal state.

## 2. Equations and energy ownership

```text
rho cp dT/dt = d/dz(k dT/dz) + A_rad + Q_mech                      W m^-3
Q_mech = f_c 2 s e_creep + f_p 2 s e_plastic                       (one partition of 2 s |a|)
T = T* + theta,   K T* = b + sigma_rad    (discrete steady reference; radiogenic balanced there)
C dtheta/dt = -K theta + sigma_mech,   sigma_mech,i = w_i Q_mech,i   W m^-2
stored (not heat) = (1 - f_c) creep work + (1 - f_p) plastic work
```

- **Heating counted once.** The same stress, creep rate and plastic rate that give
  the column's work also give its heat. The column work `a F = 2|a| sum(w s)` and
  the deposited heat `sum(w_i Q_i)` are one quantity. The case uses
  `f_c = f_p = 1`, like ASPECT's shear-heating term `2 eta eps':eps'`, which has
  no efficiency parameter. This is an explicit D4 choice, not a calibrated partition.
  The ASPECT cookbook itself does not enable shear heating.
- **Radiogenic heat.** Its only role is to keep the declared reference geotherm
  steady. Omitting it after starting from that geotherm would invent cooling.
- **Omitted by declaration:** adiabatic, latent and compressional heat; thermal
  expansion and buoyancy; advection; a supplied basal heat flux; temperature-
  dependent conductivity; melting. All are refused.
- **Energy identity checked every step.** The change in `sum(C_i theta_i)` must
  equal mechanical heat minus the departure's heat lost at the surface plus that
  gained at the base.
  - Boundary fluxes are the fixed-temperature conductances times the exact time
    integral of the adjacent departures (section 4).
  - The steady throughput (55 mW/m² out, 30 mW/m² in, 25 mW/m² radiogenic) is
    balanced in `T*` and reported separately.

## 3. Thermal support and mechanical quadrature

Each Gauss–Legendre point of the mechanical column owns one thermal control volume.

- **Cell widths.** Each cell's width is exactly that point's quadrature weight.
  Faces lie at cumulative weights within each layer, and layer interfaces sit
  exactly at their declared depths.
- **Support validated before assembly.** The preparation refuses the support
  unless:
  - layer IDs, depths and widths are nonempty one-dimensional arrays of one
    length, with integer IDs and real, finite depths and widths;
  - the IDs run 0, 1, 2, ... in order, with every declared layer present;
  - depths strictly increase and widths are positive;
  - each layer's widths sum to its declared thickness `h` within `8 (n + 3) u h`,
    for `n` points in the layer and unit round-off `u = 2^-53`.
- **Why that tolerance.** NumPy's `leggauss` rescales its weights by
  `2 / fl(sum w)`, so their exact sum is 2 within `(n + 1) u`. Scaling to the layer
  rounds each width once, and the compensated sum rounds once more: `(n + 3) u`.
  The factor 8 is margin. At 64 points this is 6e-14 of the layer, 1.2 nm in 20 km.
  It is a floating-point bound fixed in the tool, not a physical tolerance.
- **No repair at the interface.** Only a validated layer has its last cumulative
  face replaced by the declared interface, a round-off move. The first delivery
  made that move for any widths. In the review's reproduction, cells 1% too wide
  represented 101 km of rock, with 1% extra heat capacity, in a 100 km column; the
  run still completed with a zero energy residual. That support is now refused.
  Valid Gauss supports are assembled exactly as before.
- **Point inside its cell.** Preparation checks that every point lies strictly
  inside its cell; the preparation is refused otherwise.
- **Paired with the mechanics by value.** The evolution requires the thermal layer
  IDs, depths, widths and reference densities to equal the actual lithostatic
  mechanical preparation's bitwise. The thermal preparation retains the density
  used in its heat capacity; a caller-supplied mechanical fingerprint cannot
  substitute for that comparison. Section 1 selects the mechanical layers'
  density, and D4 uses the same reference material inventory for heat and
  mechanics. A separately approximated thermal density is not this contract.
  Supplied-pressure analytical columns have no mechanical density (their field
  is explicitly unknown); they retain their independently declared thermal
  density. Standalone conduction remains independent of a mechanical column.
- **Fingerprint.** The thermal fingerprint hashes the properties, densities,
  boundaries, thicknesses and reference temperature, with the layer IDs, depths
  and widths. Validated depths already imply each point's layer; the IDs are
  hashed anyway. A separate preparation digest binds all resulting arrays and
  boundary values, including capacities, conductances and the steady reference.
  Coupled admission and propagator preparation check that digest, so replacing
  derived state while retaining its old labels is refused. A legitimate change
  to thermal properties must be rebuilt with `prepare_thermal` and receives its
  own input identity and propagator. These O(N) entry checks neither rebuild the
  numerical operator nor change its arithmetic. They protect normal preparation
  and copy paths, not deliberate forgery of internal identities or arbitrary
  replacement of the mechanical solver's own derived arrays.
- **Heat maps to work exactly.** The column integral of heat equals the column's
  mechanical work, and the temperature used by the mechanics is the temperature of
  that same material point. There is no interpolation between grids, no endpoint
  extrapolation and no aliasing.
- **Conduction.** Heat flow across the face between neighbouring points is
  `(T_{i+1} - T_i)/(d_i/k_i + d_{i+1}/k_{i+1})`: series resistance using each
  point's distance to the face. Inside a layer this is the ordinary difference
  quotient. At an interface it keeps both temperature and heat flow continuous,
  as D4 requires for variable conductivity.
  - Surface and base conductances use the distance from the outer point to the
    fixed-temperature boundary.
  - Interior fluxes cancel in pairs, so the scheme conserves energy exactly.

Points cluster towards layer ends; at 64 points per layer the smallest cell is
about 9 m. The steady geotherm and the two-layer transient both still converge at
second order (section 6).

## 4. Time integration and feedback

**Modal conduction.** Conduction is linear with constant coefficients, so the
symmetric operator `C^{-1/2} K C^{-1/2} = Q Lambda Q^T` is factorised once for
the support. Each mode is then advanced exactly with the φ-functions:

```text
z = -lambda h;   phi_1 = (e^z-1)/z,  phi_2 = (e^z-1-z)/z^2,  phi_3 = (e^z-1-z-z^2/2)/z^3
predictor  v_a = e^z v_n + h phi_1 g_n                         (g = Q^T C^{-1/2} sigma)
corrector  v_{n+1} = v_a + h phi_2 (g_a - g_n)                 (sigma linear over the step)
integral   int v dt = h phi_1 v_n + h^2 phi_2 g_n + h^2 phi_3 (g_a - g_n)
```

- **Exactness.** For a source varying linearly between the two stage values, this
  is the exact variation-of-constants solution (Kassam and Trefethen 2005,
  equation 2.1).
  - Stiff modes near 9 m cells are therefore stable at 20 kyr steps.
  - The φ-functions use series for `|z| < 1`, and `expm1` otherwise.
  - The φ3 integral was derived for this boundary account and is checked against
    the energy identity.
- **History and strain** use Heun steps with the same two stages. This is the
  reviewed weakening convention.

**Feedback at every stage.** Stage 1 uses `(T_n, kappa_n)`; stage 2 uses the
predicted `(T_a, kappa_a)`; the committed `(T_{n+1}, kappa_{n+1})` is re-solved
and reused as the next first stage.

- The prepared creep coefficients depend on temperature, so they are **rebuilt
  at every stage**:
  `log c = [log A - m log d] - (E + P V)/(R T)` and `V/(R T)`.
- This rebuild uses the kernel's own expression in the same operation order. It
  is bitwise equal to `check_i01_column.LocalLaw.prepare` at any temperature, and
  to the reviewed preparation at the template temperature.
- The rebuilt column carries a new fingerprint. The retained `evolve` still refuses
  changed-temperature replacements; this wrapper never bypasses it.
- The stress solve is the reviewed `stresses`. The column sums reproduce `respond`
  bitwise.

**Accepted steps are atomic.** Nothing is booked when a step is refused because:

- the strain bound would be exceeded;
- any point would change by more than 5 K in one step (an accuracy guard for the
  explicit coupling);
- the temperature would become nonpositive;
- raw history would fall, or plastic history would exceed `2|epsilon|`.

**Efficiency.** Prepared once while unchanged:

- the geometry, conductances and steady reference;
- one propagator (eigendecomposition and exponential factors) per step size;
- the temperature-independent parts of the creep coefficients.

Retained: the current state, one stage and scalar accounts, plus per-point
yield-stage counts. No iterate history is kept.

**Resources.** The command-line run leases single-thread BLAS and has a 120 s
cooperative budget.

## 5. Predeclared controls

Tolerances were frozen in the case before the evidence run.

| Control | Checks and limits |
| --- | --- |
| adapter | Thermal geometry equals the reviewed quadrature bitwise. Rebuilt coefficients equal the reviewed preparation at its temperature, and equal the kernel at a perturbed field, bitwise. The mechanics wrapper equals reviewed `respond` bitwise. Heat equals work within `1e-10`. Prepared arrays are immutable. |
| conduction | Steady layered geotherm at 16/32/64/128 points per layer: order in `[1.8, 2.2]`, finest error `<= 0.01 K`. Surface, interface and base heat flows within `1e-9`. Cookbook constants reproduced. Insulated uniform source within `1e-12`. Zero source bitwise. Two-layer eigenmode (different `k` and `rho cp`) at 16/32/64: order in `[1.8, 2.2]`, finest error `<= 0.01 K`, energy within `1e-10`. |
| homogeneous | Insulated uniform coupled layer versus a scalar DOP853 oracle for `(T, kappa)`, with the kernel re-prepared at every evaluation. Order in `[1.8, 2.2]` for temperature and history; finest error `<= 1e-5`; uniform; no boundary heat; energy and work-to-heat checks. |
| limits | With no heating, temperature stays at the steady reference bitwise and the evolution equals reviewed `evolve` bitwise. With heating but no feedback, the mechanics are still bitwise identical, the column heats, and energy and work-to-heat close. |
| coupled | Feedback on and off. Steps 32/64/128: force `<= 1e-4`, temperature `<= 0.01 K`. The smooth feedback-off reference must show order `[1.8, 2.2]` with no yield switching. Points per layer 32/64/128: force `<= 0.003`, thermal energy `<= 0.01`, thermal feedback `<= 3%`. Feedback positive and at least 10 times the resolved change. Energy and partition `<= 1e-10`. All runs complete. |
| refusal | 27 unsupported inputs refused: the 24 of r1, plus the review's 1% volume mismatch, a same-size support for other thicknesses and a replaced support copy. The temperature-step and small-strain refusals book nothing. |
| reuse | Propagator prepared once versus rebuilt every step: bitwise-identical state and accounts, with raw times. |

## 6. Results (deterministic; r1 control values)

These values were recorded by r1 from the first-delivery bytes. For valid supports
the review corrections leave the arithmetic unchanged: they correct the reported
layer means and add refusals. The corrected campaign is recorded by r2, not here.

| Quantity | Value |
| --- | --- |
| Steady geotherm error, 16/32/64/128 points per layer | 0.120 / 0.0311 / 0.00790 / 0.00199 K (orders 1.95, 1.98, 1.99) |
| Heat flows, finest | 55.000 / 35.000 / 30.000 / 30.000 mW/m² at the surface, 20, 40 and 50 km; 30.000 at the base (errors ~1e-12) |
| Two-layer eigenmode error, 16/32/64 | 0.0786 / 0.0204 / 0.00520 K on 100 K (orders 1.94, 1.98); energy 2.0e-13 |
| Insulated uniform source | 6.5e-15 relative |
| Homogeneous oracle | rise 2.385 K; orders 2.00 (temperature and history); finest errors 7.0e-8 and 6.0e-8 |
| Start force (steady geotherm, inherited history) | 1.5516e13 N/m |
| Weakening only, strain 0.04 | 1.5217e13 N/m (-1.93%) |
| Weakening + heat feedback | 1.4751e13 N/m (-4.93%; -3.06% relative to no feedback) |
| Peak warming | 6.68 K at 43.9 km (mantle lid); every point warms |
| Layer warming, maximum | upper crust 4.4 K; lower crust 5.9 K; lid 6.7 K; mantle below 50 km 5.0 K |
| Heat budget | 6.05e11 J/m² deposited; 97.21% retained; 2.76% conducted out at the surface and 0.03% at the base |
| Surface heat flow | 55.00 to 55.76 mW/m² |
| Yielding points | 118 without feedback, 113 with it. The deepest yielding point of each brittle zone turns to pure creep (16.1, 31.2 and 45.6–46.1 km), so every brittle–ductile transition rises slightly |
| Energy identity | 6.7e-14 cumulative, 1.5e-13 worst step; creep/plastic partition 1.4e-12 |
| Time refinement, 64 to 128 steps | force 3.9e-9, temperature 2.0e-6 K |
| Depth refinement, 64 to 128 points per layer | force 1.7e-4; thermal energy 3.1e-5; feedback 3.06% vs 3.08% |

**Layer means are volume-weighted.** A layer's mean warming is
`sum(w theta) / sum(w)` over its Gauss control volumes. In r1, the second value of
each `warming_by_layer_k` pair is an unweighted mean over points that cluster
towards the layer ends. That is not the layer's average warming, so those values
are withdrawn here. The corrected summary names `maximum` and
`volume_weighted_mean`; its means are left for r2.

**The time order is irregular, and this is understood.** Without feedback no point
changes yield state, and force, temperature and history converge at exactly
second order (2.00 for both force and temperature in the smooth reference). With
feedback, the five transition points listed above cross from yielding to creeping
partway through the run. Each crossing is a kink in the stage values.

- The observed orders therefore become irregular: 0.65 for force at 32/64/128.
  A development check from 16 to 256 steps gave orders between 0.65 and 2.6.
- The changes remain below 4e-9 in force and 2e-6 K in temperature, about ten
  million times smaller than the feedback being measured.
- It is reported, not hidden: second order is claimed only for smooth
  trajectories.

These are properties of an authored fixture, not Earth-wide values.

## 7. What this establishes, and what remains

**Established:**

- Layered conduction with mechanical heating counted once, conserving energy to
  round-off.
- Temperature feeding back into the reviewed creep, plasticity and history law at
  every stage, with no reused temperature-dependent coefficients.
- Second-order conduction on the mechanical support.
- Exact reduction to the reviewed fixed-temperature evolution when heating or
  feedback is switched off.

Over this window, thermal softening from dissipation is a first-order part of the
transmitted resistance, as the weakening diagnostic suggested.

**Still open:**

- finite strain: thinning, advection of heat and history, asthenospheric inflow,
  and topography with isostasy;
- a rock-specific heat partition;
- temperature-dependent conductivity and capacity;
- adiabatic, latent and melt terms;
- lateral conduction and localisation;
- calibrated thermal and rheological parameters;
- coupling to the driving-force solution;
- any rupture or breakup law.

**Validity.** The supplied rate and the 0.05 strain window bound what this column
represents. Heat conducted out at 1.27 Myr is already 2.8%, so longer windows need
the open thermal pieces above, not only more steps. The per-layer warming is
reported so a thermal owner can judge where the fixed-geometry assumption fails first.

## 8. Sources

**Read for this task:**

| Source | Used for |
| --- | --- |
| [ASPECT continental-extension parameter file](https://github.com/geodynamics/aspect/blob/main/cookbooks/continental_extension/continental_extension.prm) | Initial-temperature function with constants `ts1-3 = 273/633/893 K`, `qs1-3 = 0.055/0.035/0.030 W/m²`, `A1-3 = 1e-6/0.25e-6/0 W/m³`, `k1-3 = 2.5`; box boundary temperatures 273/1613 K; heating model is compositional heating only; conductivity 2.5; heat capacity 750 |
| [ASPECT heating-model documentation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Heating_20model.html) | Compositional heating values are per unit volume (W/m³). Shear heating adds `2 eta eps':eps'` with no work-fraction parameter |
| [NumPy `leggauss` source](https://github.com/numpy/numpy/blob/main/numpy/polynomial/legendre.py) | Review correction: the weights are rescaled by `2. / w.sum()`, the basis of the width-sum tolerance in section 3 |

ASPECT was not installed or run. No external code was copied.

**Reused from earlier I01 reading:**

- Kassam and Trefethen (2005), equation 2.1 (variation of constants), as in the
  [thermal prototype](I01_THERMAL.md).
- ASPECT shear-heating and particle documentation.
- Brune et al. (2014) Methods: SLIM3D includes shear heating.
- The D4 enthalpy contract.

**Not read:**

- Chapman (1986) on continental geotherms: the cookbook's own function was used
  instead.
- Cox and Matthews (2002): the ETD2 corrector and φ3 integral were derived from
  the variation-of-constants formula and are checked numerically.
- Finite-volume textbooks on interface conductances: the series-resistance flux
  was derived directly.

## 9. Commands and bindings

From the repository root, using the existing scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_column_heat.py -v
python -B tectonics/tools/check_i01_column_heat.py --output NEW_PATH.json
```

The receipt binds, before and after execution:

- this document, the tool, case and tests;
- the imported `check_i01_weakening.py` and `check_i01_column.py`;
- the weakening case, document and tests;
- the column case and the column receipt listed in the tool;
- the weakening receipt named by `WEAKENING_RECEIPT`, whose recorded hashes the
  imported helper bytes and their package owners must match. The designated
  successors for the package-owned code are `i01-column-r2` and `i01-weakening-r3`.

Timings exclude imports. The reuse comparison is one matched observation, not a
generator speedup. No existing helper, native source, shared status or receipt was
changed. The r1 receipt binds the first-delivery bytes; the corrected bytes need a
new output path (r2), never a rewrite of r1.

## 10. Review corrections

Review found the conservative flux assembly, the ETD2/φ3 heat accounting, the
temperature-dependent preparation and the once-only creep/plastic work partition
consistent; none of them changed. It found three defects around them:

1. **Layer means.** The summary averaged clustered Gauss points without their
   volumes. It now reports each layer's maximum and volume-weighted mean
   (section 6).
2. **Unchecked support.** The thermal geometry was not validated, a wrong last
   face was silently replaced by the interface, and the evolution matched only a
   fingerprint label and point count. The support is now validated before assembly
   and paired with the mechanics by value (section 3). A point outside its cell is
   now a `ValueError`, like the other input refusals.
3. **Unchecked material density and derived preparation.** A public
   `prepare_thermal` call could supply density 1% above the actual mechanical
   density while copying its real fingerprint. The one-step reproduction
   completed with changed warming and a closed energy account, because the
   account used the inconsistent capacity too. Admission now compares the actual
   reference densities. The preparation digest also detects changed derived
   thermal arrays, including a copied capacity, conductance or steady reference.

Regression tests cover the weighted mean on a non-uniform profile, the reproduced
1% volume mismatch, same-size foreign supports, replaced dataclass copies,
malformed, missing, non-finite and nonpositive supports, the public-constructor
1% density mismatch, changed derived thermal arrays, and an unchanged valid
layered run. They also retain the supplied-pressure homogeneous oracle and check
that a freshly prepared different heat capacity remains admissible while its
old propagator is refused.

No physics, case input, physical tolerance, step or strain ceiling, campaign
parameter or reviewed constitutive helper changed. The
[r1 receipt](../evidence/i01-column-heat-r1.json) and
[r2 receipt](../evidence/i01-column-heat-r2.json) remain unchanged evidence for
their original snapshots. The preparation correction changes this tool's source
identity and therefore its downstream bindings. Fresh results belong in a new
receipt and the current evidence register; no old binding is rewritten.
