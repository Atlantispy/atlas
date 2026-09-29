# I01: force-driven motion with thermal and weakening feedback

**27 September 2026. WORKING NON-CANON. One bounded I01 connection; not I02,
world generation or I01 completion.** This joins the reviewed
[layered column-heat connection](I01_COLUMN_HEAT.md) to the reviewed
[resistance-to-motion connection](I01_MOTION_COUPLING.md). The
[case](../cases/i01_thermomechanical_motion_v1.json), [tool](../tools/check_i01_thermomechanical_motion.py)
and [focused tests](../tests/test_i01_thermomechanical_motion.py) are new. The
retained helpers `check_i01_column_heat.py`, `check_i01_motion_coupling.py`,
`check_i01_weakening.py` and `check_i01_column.py` are imported read-only and
never monkey-patched. Execution results are maintained separately from this
source-bound method specification; see section 7.

## 1. What changes, in plain language

Before this join, the column-heat control stretched the column at a supplied
rate, and the motion control solved the rate from a driving force at a fixed
temperature. Here the driving force is constant and everything else responds:

- the plate edge moves as fast as the force can push against external drag plus
  the layered rock column's resistance;
- the rock's creep and plastic work becomes heat in the rock that did it; the
  external drag's work does not;
- heat is conducted through the column, warmer rock creeps more easily, and
  accumulated plastic strain weakens it, so the same force drives faster motion.

## 2. Equations, units and once-only ownership

At every stage (initial, predictor, accepted endpoint), with temperature `T`,
raw engineering plastic history `kappa` and signed edge velocity `v`:

```text
a = v / w                                             axial rate [1/s]; w belt width [m]
F_drive = D v + F_column(a; T, kappa)                 [N/m of strike]; D generalised drag [Pa s]
F_column = sign(a) 2 sum_i w_i s_i                    s_i solved local stress [Pa], w_i Gauss width [m]
P_column = a F_column = creep + plastic               [W/m^2]
sigma_i = w_i 2 s_i (f_c e_creep,i + f_p e_plastic,i) [W/m^2 per control volume; width already inside]
F_drive v = D v^2 + w (creep + plastic)               [W/m of strike]
C dtheta/dt = -K theta + sigma                        [W/m^2]; T = T* + theta, K T* = b + sigma_rad
dkappa/dt = 2 e_plastic                               [1/s]
```

- **Heat source.** `sigma` is `heat.mechanics` evaluated at the same prepared
  column, history and rate that `motion.solve` just balanced. Its log-stress
  root is only the starting guess; `same_stress` records that the re-evaluated
  stresses are bitwise the solved ones, and the controls require it at every
  committed stage. The depth weights are applied once, inside `sigma`; the
  column heat is `sum_i sigma_i`, never `sum_i w_i sigma_i`.
- **Width appears once.** Column work per unit area is multiplied by `w` exactly
  once to enter the motion account in W/m.
- **Drag is a different process.** `D v^2` is booked only as drag work; it never
  enters `sigma`. The case uses `f_c = f_p = 1` from the column-heat case.
- **Checked accounts** (integrated with the same Heun stages; J/m or J/m^2):

| Identity | Reported residual |
| --- | --- |
| drive = drag + w (creep + plastic) | `motion_work_relative` |
| drive = F_drive x displacement | `drive_displacement_relative` |
| w x (column creep + plastic) = motion column terms | `width_relative` |
| creep + plastic = column work | `partition_relative` |
| column work = heat + stored | `column_energy_relative` |
| heat = f_c creep + f_p plastic | `work_to_heat_relative` |
| w (heat + stored) = drive - drag (drag excluded) | `drag_excluded_relative` |
| thermal change = heat - surface loss + basal gain | `energy_relative` (and per step) |

- **Reference throughput kept separate.** The balanced steady reference (55 mW/m^2
  out at the surface, 30 in at the base, 25 radiogenic) is reported under
  `reference` in W/m^2 and J/m^2; it is never added to the departure accounts.
- **Rest.** At zero drive, `motion.solve` returns exact rest and the stage skips
  `heat.mechanics` (which divides by a nonzero rate). There is no motion,
  mechanical heat or history growth. An existing departure still conducts.

## 3. Numerical method

Each accepted step of length `h`:

1. Deadline check; the propagator (or a supplied replacement) must match the
   thermal support and `h`.
2. Predictor temperature: retained ETD2 predictor with the current source.
3. Predictor stage at `(T*+theta_a, kappa + h kdot_n)`: rebuild
   `ArrheniusUpdate.of(base).at(T)`, solve the force balance, take heat.
4. Corrector: retained ETD2 with the source linear between the stages; Heun
   updates of history, strain and displacement.
5. Refusals: strain `> 0.05` or the case bound, a temperature jump above the
   guard (at most 5 K), nonpositive temperature or falling history, or history
   above `2|strain|`.
6. **Re-solve the endpoint** at the committed `(T, kappa)`; only then are state
   and accounts booked. The endpoint is the next step's first stage.

- **Atomic refusals.** `REFUSED_SMALL_STRAIN`, `REFUSED_TEMPERATURE_STEP` and a
  mid-run `REFUSED_DEADLINE` return the accepted prefix. Nothing of the refused
  trial is booked. A budget already expired before the first balance raises, as
  in the retained helpers. A deterministic `CountdownDeadline` (a float
  subclass consulted by the retained `perf_counter() > deadline`) makes the
  mid-run refusal reproducible in tests.
- **Feedback off.** Every stage uses the preparation at the initial temperature;
  heat is still produced and conducted. With no heating, temperature stays
  exactly at the reference.
- **Stages and warm starts.** The initial stage is cold. The predictor is warmed
  by the current stage and the endpoint by the predictor, exactly as in
  `motion.evolve`. Guesses never replace a solve.

## 4. Reuse design

- **Prepared once while their inputs are unchanged:**
  - the reviewed mechanical preparation and thermal support, paired by value;
  - the temperature-independent Arrhenius terms (`ArrheniusUpdate.of`);
  - one conduction propagator per support and step, shared by feedback on/off
    runs at the same step.
- **Rebuilt at every stage:** the temperature-dependent creep terms (new
  fingerprint per temperature), the motion root, the stresses and the source.
- **Retained:** only the current state, one predictor, scalar accounts and
  per-point yield counts.
- **Freshness.** Stale inputs (`inputs` key), a support prepared for another
  column, a temperature-prepared column passed as the base, a replaced support
  copy and a mismatched propagator are all refused.

## 5. Case and domain of validity

- **Physics** from the reviewed column-heat case and, through it, the weakening
  case. The geotherm starts at `heat.steady_k`, not the weakening template.
- **Forcing** from the motion case, unchanged: `F = 2e13 N/m`, `D = 5e22 Pa s`,
  `w = 1e5 m`. This is not tuned to a speed.
- **Duration 1e13 s.** Since `|F_column| >= 0` acts against motion,
  `|a| <= |F|/(D w) = 4e-15/s` for any column state. So `|strain| <= 0.04 < 0.05`
  is guaranteed before running. The motion case's 3e13 s lacks that guarantee,
  and a longer duration is refused by the case validator.
- **Homogeneous oracle input.** This is the column-heat case's insulated uniform
  wet-quartzite layer, unchanged: 10 km, 600 K, supplied 150 MPa mean pressure,
  history 2.0. Unlike the column-heat oracle, it is driven by the same force,
  drag and width for 1e13 s rather than a supplied rate. That difference is
  deliberate and declared.
- **Declared limits.** Fixed geometry and width, constant layer thermal
  properties, unchanged constitutive law, at most 256 accepted steps, strain at
  most 0.05 and temperature change at most 5 K per step.

## 6. Predeclared controls and gates (frozen in the case)

Retained tolerances may be tightened but not relaxed. The validator refuses any
relaxation against the imported column-heat and motion cases, and the tool fixes
the four new gates.

| Control | Checks |
| --- | --- |
| limits | No heating (`f=0`): temperature exactly the reference; motion, history and drive/drag/creep/plastic work bitwise equal to retained `motion.evolve` at `ArrheniusUpdate.at(heat.steady_k)`. Feedback off with heating: same bitwise motion; heats; energy, work-to-heat, drag exclusion. |
| homogeneous | Insulated uniform force-driven layer at order 8, steps 16/32/64, against DOP853 on `(T, kappa, strain)` with an independent kernel `LocalLaw` + Brent force balance per call. Temperature and history orders in [1.8, 2.2]; finest temperature, history, strain and velocity within 1e-5; initial and final-state roots within 1e-8; uniform within 1e-13; accelerates; no boundary heat; accounts. |
| feedback | On/off at identical force, drag and history. Time steps 16/32/64 (order 64) and orders 32/64/128 (64 steps). Finest time changes: velocity 1e-4, temperature 0.01 K, history 1e-4 (relative to gain), drive work and heat 1e-4. Finest depth changes: velocity 0.003, thermal energy and heat 0.01, mean history gain 0.01, drive work 0.003. Velocity feedback positive and at least 10x the larger finest time/depth velocity change; feedback depth change 3%. Stage balance 1e-10, stage power 2e-10, no restress mismatch, every account and nonnegative dissipation. |
| states | Rest with a 2 K half-sine departure: no motion, work, heat or history change; the departure conducts with closed energy. Rest without departure: bitwise zero. Extension and compression complete with closed accounts, correct signs and nonnegative dissipation. |
| refusal | 18 case mutations (advection, finite strain, rate control, drag heating the column, melting, tuned force, over-long duration, relaxed tolerances, and others); direct guards (steps, strain allowance, guard, untyped drive, zero drag, heat fractions, departure shape and nonpositive temperature, negative history, flags, other column, temperature-prepared base, stale inputs, foreign and replaced supports, propagator/provider step); retained compressive pressure-branch refusal. Atomic strain, temperature and mid-run deadline refusals equal independent prefix runs bitwise. |
| reuse | One matched run: warm guesses plus one propagator versus cold roots plus a propagator rebuilt every step. Parity within 1e-8 and the same gates; raw seconds and percentage reported. |

**Why the new gates have these values.** Time history and time work use 1e-4,
the retained velocity time gate, because both are integrals of the same Heun
stages. Depth mean history uses 0.01, the retained thermal-energy depth gate:
history grows only at yielding points, so it is a column integral with kinks at
the brittle–ductile transitions. Depth drive work uses 0.003, the retained
velocity depth gate, since drive work is `F` times displacement.

**Smooth convergence versus yield switches.** Second order is claimed and gated
only for the feedback-off series, and only if it has no yield-state switching.
If switching occurs, orders are reported, the absolute gates still apply, and
the receipt says `claimed: false`. Velocity orders are reported but not gated:
at these step sizes, root-solver residuals can approach the velocity's time
changes. The homogeneous oracle always yields, so it supplies an unconditional
order gate for the coupled integrator.

## 7. Results

The coding handoff was prepared without execution. The coordinator runs the
focused tests and bounded campaign before accepting this connection. Consult
the [current evidence register](../../docs/CURRENT_EVIDENCE.md) for the reviewed
receipt and measured results; an unregistered file is not acceptance. Keeping
results there avoids changing this source-bound specification after a run.

## 8. Sources

**Consulted for this join:**

| Source | Influence |
| --- | --- |
| [ASPECT heating-model parameters](https://aspect-documentation.readthedocs.io/en/latest/parameters/Heating_20model.html), fetched 27 September 2026 | Shear heating adds `2 eta eps':eps'`. It has no work-fraction parameter and is separate from adiabatic and latent terms. Compositional heating is W/m^3. This supports depositing all column dissipation once and keeping external drag out. |
| [SciPy `solve_ivp`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html), fetched 27 September 2026 | Local error kept below `atol + rtol abs(y)`, with per-component `atol`. DOP853 is recommended for high precision. Used for the three-component oracle. |
| Retained Atlas `check_i01_column_heat`, `check_i01_motion_coupling`, `check_i01_weakening` and `check_i01_column`, with the column-heat r2 and motion r1 receipts | Interfaces, units, stage and warm-start order, retained tolerances and the drag-only bound |

**Reused, not re-read:**

- Kassam and Trefethen (2005), equation 2.1, for exponential time differencing,
  through the reviewed [thermal](I01_THERMAL.md) and column-heat derivations.
- The ETD2 corrector and phi3 boundary integral, as derived and checked in
  column heat.
- Duretz et al. (2018) and the SciPy Brent documentation, as cited for the
  motion connection's consistent tangent and root comparison.
- The ASPECT continental-extension parameter file behind the column-heat thermal
  inputs.

**Not consulted:** no further paper or software was needed. No new physical law
or numerical closure was introduced; the join composes reviewed pieces. ASPECT
was not installed or run. No external code was copied.

## 9. Limitations

- Fixed geometry and width, with no advection, thinning, asthenospheric inflow
  or topography. The small-strain window is guaranteed only through the
  drag-only bound.
- The drive is a single constant degree of freedom in a stationary frame. The
  drag is lumped, not the local basal coefficient. The heat fractions are
  authored (1, 1).
- Constant thermal properties; no latent, adiabatic or melt terms.
- No lateral conduction or localisation, rupture or separation criterion.
- The support-pairing limitation recorded in column-heat review section 10
  still applies.

These are properties of authored fixtures, not Earth-wide values.

## 10. Commands and bindings

From the repository root, with the existing compatible scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_thermomechanical_motion.py -v
python -B tectonics/tools/check_i01_thermomechanical_motion.py --output NEW_PATH.json
```

The exclusive-create receipt binds, before and after execution:

- the four new files and the package module that now owns the stage;
- the imported tools and loaded cases;
- the column-heat and motion-coupling receipts that the tool pins. The designated
  successors for the package-owned code are `i01-column-heat-r4` and
  `i01-motion-coupling-r2`; each is evidence only once captured, reviewed and
  listed as current in the [evidence register](../../docs/CURRENT_EVIDENCE.md).

The receipts must equal their accepted SHA-256 values. Every retained tool and
case must equal the bytes those receipts recorded, and each imported module
must resolve to its bound path. Timings exclude imports; the budget is 120 s
after them. The reuse comparison is one matched observation, not a generator
forecast.
