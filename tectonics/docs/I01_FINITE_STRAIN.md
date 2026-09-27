# I01: material-following finite-strain column

**27 September 2026. WORKING NON-CANON. One bounded I01 closure; not I02, world
generation, full I05 transport, lateral localisation or rupture.** This removes
the fixed-geometry limit of the reviewed
[force-driven thermal/motion connection](I01_THERMOMECHANICAL_MOTION.md) by
changing the representation, not by relabelling its small-strain guard. The
[case](../cases/i01_finite_strain_v1.json), [tool](../tools/check_i01_finite_strain.py)
and [focused tests](../tests/test_i01_finite_strain.py) are new. The retained
`check_i01_thermomechanical_motion.py`, `check_i01_column_heat.py`,
`check_i01_motion_coupling.py`, `check_i01_weakening.py` and `check_i01_column.py`
are imported read-only and never monkey-patched; the retained fixed-geometry
`evolve` wrappers are never called for a finite deformation. Measured results
are kept outside this source-bound specification (section 10).

## 1. What changes, in plain language

The earlier connection pulled on a column whose shape could not change. Here the
100 km strip really stretches: it widens, thins and carries its rocks with it.

- Every rock parcel keeps its own temperature and plastic history as it moves.
- A thinner column has less rock to resist the pull and lighter overburden on
  each parcel, so friction and pressure-sensitive creep weaken.
- Heat crosses a thinner column faster, and the whole strip keeps exactly the
  same rock and heat capacity.
- Motion is still solved from the constant driving force against external drag
  plus the column's resistance at every stage; drag never heats the rock.

## 2. Kinematics and finite strain

A closed, laterally uniform, incompressible plane-strain strip of unit strike
deforms by affine pure shear about its surface. With reference width `w0`,
thickness `h0` and material depth `z0`:

```text
lam > 0                              stretch; the state variable
w = w0 lam;  z = z0/lam;  h = h0/lam  current width, depth and thickness [m]
lam_dot = a lam;  a = v/w             axial (logarithmic) rate [1/s]
v = w a = w0 lam_dot                  signed edge speed [m/s]
eps = ln(lam)                         finite strain: log stretch
w h = w0 h0                           volume per unit strike, conserved
```

- For this affine flow the deformation gradient is exactly `F = diag(lam, 1/lam)`
  (ASPECT's `dF/dt = G F`, `F(0) = I`); `ln lam` is its principal log strain.
- Raw engineering plastic history `kappa` remains constitutive memory at material
  points (`dkappa/dt = 2 e_plastic`). It is never used as geometry. Its bound is
  `kappa - kappa0 <= 2 int |a| dt`, integrated with the same stage weights.
- The strain-rate invariant of `diag(a, -a)` is `|a|`: the retained constitutive
  convention applies unchanged at the current rate `a = v/w`.
- No asthenospheric inflow, extraction, births, lateral mixing or reference-mass
  change from thermal buoyancy. Densities are Boussinesq reference values.
- **A priori window.** The column force opposes motion, so `|v| <= |F|/D` and
  `|lam - 1| <= |F| t/(D w0)` for any column state. With the reviewed
  `F = 2e13 N/m`, `D = 5e22 Pa s`, `w0 = 1e5 m` and `t = 1e14 s` this is exactly
  0.4: the frozen stretch window `[0.6, 1.4]` is guaranteed before running, for
  either sign of the drive. The window is not narrowed to an expected outcome.

## 3. Heat in material coordinates

**Moving-domain equation.** For `T(z, t)` in the pure-shear flow `u_z = -a z`,
`rho c (dT/dt - a z dT/dz) = d/dz(k dT/dz) + Q`. At fixed material depth `z0 = lam z`
the material derivative is `dT/dt|z0` and `d/dz = lam d/dz0`, so

```text
rho c dT/dt|z0 = lam^2 d/dz0 (k dT/dz0) + Q          [W/m^3]
```

**Finite volumes on the reference support.** The retained column-heat support
(one control volume per mechanical Gauss point, series interface resistance,
perfect layer contact) is kept in material coordinates. At stretch `lam` the
current widths are `W_i = W0_i/lam`; face distances shrink by `lam`; conductances
and both boundary conductances grow by `lam`. Multiplying per-current-area terms
by the current width `w = w0 lam`:

```text
whole-strip capacity   w C(lam) = w0 lam (rho c W0/lam) = w0 C0         constant
whole-strip operator   w K(lam) = w0 lam (lam K0)       = w0 lam^2 K0   boundaries included
whole-strip source     w sigma  = w0 m;   m_i = (w/w0) sigma_i          per reference area
C0 dT/dt = -lam^2 (K0 T - b0) + r0 + m                                  [W/m^2 of reference area]
```

`r0 = W0 A` is radiogenic heat (constant per material) and `m` the mechanical heat.
The operator identity is checked through the retained assembly itself: the
`scaling` diagnostic rebuilds the support at the current geometry with
`heat.prepare_thermal` and compares it with `lam^2` times the reference.

**Why no separate advective flux.** Every control volume is a fixed set of
material particles: its faces move with the material, so the face flux
`e (v - w_mesh) . n` of the D4 contract vanishes identically. The lateral edges
move at the material edge speed `v`, the surface point stays at `z = 0` with
`u_z = 0`, and the strip base moves with its own material (`dh/dt = -a h`).
The strip is closed, so pure Lagrangian transport needs no advective term; the
`-a z dT/dz` term is absorbed exactly by the material derivative.

**What general Eulerian/I05 transport still needs.** A mesh that does not follow
the material (or a non-affine velocity) requires conservative advective enthalpy,
composition and history fluxes, bounded or particle-based transport of raw
history without averaging, interface tracking where layers cross cells, inflow
boundaries with supplied temperature/composition/history (asthenosphere),
outflow sinks, lateral conduction and remeshing/remapping. None is supplied here.

**Fixed enthalpy reference.** Temperatures are departures `theta = T - T*_0` from
the initial discrete steady geotherm, which is never recomputed. Because
`K0 T*_0 - b0 = r0`, the departure equation along the clock (section 4) is

```text
C0 dtheta/dtau = -K0 theta + g;   g = r0/lam^2 - r0 + m/lam^2         (exactly m at lam = 1)
```

The steady geotherm of a stretched strip differs (its radiogenic curvature is
`r0/lam^2`). Resetting to it would create or destroy heat; the tool reports that
avoided "reset heat" for the layered support in the clock control.

**Whole-strip accounts (J/m of strike).** Stage powers are whole-strip W/m: the
retained stage multiplies each per-current-area column power by the current width
once, at that stage.

```text
drive work    = drag work + column work (creep + plastic)
column work   = heat + stored;  heat = f_c creep + f_p plastic;  f = (1, 1)
thermal change = mechanical heat + radiogenic - reference outflow
                 - departure surface loss + departure basal gain
radiogenic    = w0 R dt,  reference outflow = w0 R dtau,  R = sum r0
```

The reference outflow is `lam^2` times the reference's net boundary outflow,
which equals `R` by the discrete steady identity; the stretched reference
therefore loses more heat than it produces. Surface and basal flows are also
reported separately (`q* dtau` plus departure terms); that absolute split closes
to the retained reference-flow balance, gated at `flow_relative`.

## 4. Numerical method

**Thermal clock.** Since `C0` is constant and every operator is a multiple of
`K0`, the operators at different times commute and the homogeneous propagator is
exactly `exp(-A tau)` with `tau = int lam^2 dt`. One reference eigensystem
`C0^(-1/2) K0 C0^(-1/2) = Q Lambda Q^T` is therefore reused; each step recomputes
only the exponential and phi factors of `-Lambda dtau` (O(N)), never a dense
factorisation, and never reuses factors across different increments.

**Stage weights.** For stage stretches `lam_n` and `lam_a`:

```text
dtau = 2 dt/(lam_n^-2 + lam_a^-2);   w_n, w_a = lam^-2/(lam_n^-2 + lam_a^-2)
Q[f] = dt (w_n f_n + w_a f_a)  =  (dtau/2)(f_n/lam_n^2 + f_a/lam_a^2)
```

- `Q[1] = dt`: the tau-trapezoid of `dt/dtau = lam^-2` spans exactly one step, so
  radiogenic heat, time and every constant power integrate exactly.
- The ETD2 corrector with `g` linear in tau deposits exactly `Q` of every source.
  History, stretch (`lam += Q[v]/w0`), displacement, log-strain path and every
  work/heat account use the same `Q`, so all account identities close to round-off.
- **Second order.** `Q` is a positively weighted trapezoid: for smooth `f` it
  equals `int f dt + O(dt^3)` per step. `dtau` is the harmonic trapezoid of
  `lam^2`; for linear `lam` it differs from the exact clock by
  `-(5/6) (dlam/dt)^2 dt^3` per step. The Euler predictor `lam_a` enters only at
  `O(dt^3)`. The prescribed-history oracle and homogeneous oracle test this.
- At `lam = 1` the clock is `dt`, the weights are 1/2 and every factor is the
  retained propagator's bitwise.

**One accepted step.** (1) Deadline check. (2) Euler stretch
`lam_a = lam_n + dt v_n/w0`; refuse outside the window. (3) Clock and weights.
(4) ETD2 predictor temperature with the current source; refuse outside the
temperature window. (5) Predictor stage at `(lam_a, T_a, kappa_n + dt kdot_n)`:
current geometry, widths, overburden `P0/lam` and creep coefficients rebuilt, then
`F = D v + F_column(v/w)` balanced by the retained motion solver. (6) ETD2
corrector; weighted history, stretch and path. (7) Refusals: endpoint stretch or
temperature window, temperature jump above the guard (at most 5 K), non-finite or
nonpositive temperature, falling history, history above twice the path. (8) The
endpoint is re-solved at the committed state; only then are geometry, state and
accounts booked. The endpoint is the next step's first stage.

- **Atomic refusals.** `REFUSED_STRETCH_WINDOW`, `REFUSED_TEMPERATURE_WINDOW`,
  `REFUSED_TEMPERATURE_STEP`, `REFUSED_CONSTITUTIVE` (a retained kernel refusal
  during a trial) and `REFUSED_DEADLINE` return the accepted prefix, including
  when the final endpoint is refused. A refusal at the initial balance, or a budget
  expired before it, raises.
- **Warm starts** are guesses only; every stage is solved at its own pressure,
  temperature and geometry.
- **Memory.** Only the current state, one predictor, one endpoint and scalar
  accounts are kept; no per-step arrays.
- **Comparators.** `geometry_feedback=False` keeps the mechanics at the reference
  geometry while kinematics and conduction follow `lam` (feedback measurement
  only). `rebuild=` re-assembles the retained support at the step's effective
  geometry `sqrt(dtau/dt)` and eigendecomposes it every step (reuse timing only).
  `conduction=False` (insulated supports only) is the Lagrangian transport control.
  `conduct_history` runs prescribed smooth histories: exact controls only, never
  generated-motion acceptance.

## 5. Validity window (frozen)

| Quantity | Admitted | Basis |
| --- | --- | --- |
| Stretch | `0.6 <= lam <= 1.4`, predictor and endpoint | Exactly the drag-only reachable range at the authored forcing and 1e14 s |
| Temperature | `273 <= T <= 1613 K` at every material point, predictor and endpoint | The reviewed surface and strip-base temperatures |
| Step | temperature jump `<= 5 K`; `<= 256` accepted steps | Retained ceilings |
| Constitutive | the retained creep/plasticity refusals, including the unsupported compressive branch; zero supplied pore pressure | Kernel checks at every stage; pore pressure is not transported |

- Old controls keep their own 0.05 small-strain bound; nothing here widens it.
- **No-melt margin (documented hand check, not a gate).** The hottest point is
  the 1613 K strip base. Its lithostatic pressure is 3.0411 GPa at `lam = 1`, so
  2.1722 GPa at `lam = 1.4`. The retained dry-solidus transcription in
  `check_i01_melting.py` (Katz et al. 2003 coefficients) gives about 1623 K there;
  the base would reach it near `lam = 1.46`. Omitting latent heat is therefore
  consistent across the window for this dry case only. Wet or fertile rock, a
  hotter base or a wider window needs a melt join first.
- The strip base is held at 1613 K as it rises to `h0/lam`: a declared boundary
  conduction, not McKenzie's passive upwelling, which keeps the base at a fixed
  depth by inflow.

## 6. Case

- **Physics** from the reviewed thermomechanical case and, through it, the
  column-heat, weakening and motion cases, all unchanged: layered material,
  heat fractions (1, 1), `F`, `D` and `w0`. The geotherm starts at `heat.steady_k`.
- **Duration 1e14 s**, confirmed by the drag bound above; the validator refuses a
  longer duration, a mismatched declared bound, a window that does not contain the
  reachable range, or a window beyond the frozen ceilings.
- **Main example** solves motion from force and resistance. Prescribed histories
  (linear `lam(t)` to 1.375 and 0.625) are clearly labelled exact controls.

## 7. Controls and gates (frozen before execution)

Retained tolerances may be tightened, never relaxed; the validator enforces this
against the thermomechanical, column-heat and weakening policies.

| Control | Checks |
| --- | --- |
| kinematics | Layered strip, insulated, source-free, conduction explicitly off: the nonuniform geotherm carried bitwise through `ln lam > 0.05`; current layer faces `Z0/lam` bracket every labelled point; history of never-yielded points bitwise; volume, mass and whole-strip capacity to 16 u; no heat exchanged. Homogeneous insulated layer with conduction on and a 25 K uniform departure: uniform within 1e-13. |
| clock | Two-layer eigenmode under prescribed linear histories to 1.375 and 0.625, steps 64/128/256: error against the independent semi-discrete solution `expm(-tau S)` at the exact clock of order [1.8, 2.2], finest within `oracle_relative`; against the continuous mode within `eigen_finest_k`; per-step energy. Retained assembly at `lam` = 0.6/0.8/1.2/1.4 equals `lam^2` times the reference within `flow_relative`. Zero deformation: clock factors, conduction, preparation, stage and rest evolution bitwise equal to the retained ones. |
| homogeneous | Insulated uniform force-driven layer for 1e14 s, steps 64/128/256, against DOP853 on `(T, kappa, lam)` with an independent kernel `LocalLaw` + Brent balance at `P0/lam`, `h0/lam`, `w0 lam`: temperature and history orders in range, finest T/history/log-stretch/velocity within `oracle_relative`, roots within `root_parity_relative`, uniform, thins and accelerates, every account. |
| connection | Layered force-driven run, time 64/128/256 steps (order 64) and depth 32/64/128 (256 steps): retained velocity, temperature, history, work/heat, energy and drive-work gates plus the two stretch gates; geometry feedback on/off at each order, positive and at least 10x the finest refinement change, depth change within 3%; rate consistent with the current width (`sum Q[a]` versus `ln lam` within 1e-4); every account; nonnegative dissipation. |
| states | Rest with a 2 K departure (no motion, work, heat or history; conducts; closed) and without (bitwise still); extension thins and compression thickens with positive drive work and closed accounts; independent retained re-preparation at the current thickness and transported temperature matches geometry, overburden and coefficients (`kernel_parity_relative`) and the cold stage and heat source (`root_parity_relative`); caller inputs unmodified; prepared arrays read-only. |
| refusal | 23 case mutations; direct guards (steps, windows, guard, drive type, heat fractions, departure shape, initial window, history, flags, other column, temperature-prepared or stretched base, stale inputs, foreign/replaced support, foreign modes, conduction/modes/rebuild contradictions, unreproduced rebuild inputs, pore pressure, prescribed-history start and window, retained compressive branch). Atomic stretch refusals at a predictor and at the final endpoint, temperature-step, temperature-window and mid-run and final-endpoint deadline refusals equal independent prefix runs bitwise, with whole accepted time, conserved material and closed heat. |
| reuse | One matched run: warm guesses and one eigensystem versus cold roots and the support re-assembled and eigendecomposed every step. Parity within `parity_relative`, same gates; raw seconds and percentage. |

**Why the new gates have these values.** `time_stretch_relative = 1e-4` is the
retained time gate for integrals of the same stages (history and work), because
`ln lam` integrates the edge velocity with the same weights. `depth_stretch_relative
= 0.003` is the retained depth gate for drive work, since displacement
`w0 (lam - 1)` is the time integral of the velocity. The conservation bound 16 u
and the geometry parity (`kernel_parity_relative`, 1e-10) are round-off bounds, not
physical tolerances. The operator identity uses the retained `flow_relative`
(1e-9): the retained assembly computes face distances by cumulative sums, and
cancellation there bounds its round-off near 1e-10.

Orders are gated only in the oracles; the layered runs switch yield states, so
their time orders are reported, not gated, as in the retained connection.

## 8. Reuse design

- **Prepared once per support:** the eigensystem; the temperature- and
  pressure-independent creep terms per point and mechanism.
- **Rebuilt at every stage:** current geometry, widths, overburden, creep
  coefficients (new fingerprint), the motion root, stresses and heat source.
- **Rebuilt every step:** the clock increment and its exponential/phi factors.
- The comparator re-assembles and factorises the support every step; the saving
  is measured once, on one matched run, not forecast for a world.

## 8a. Freshness and identity

The public `evolve` refuses stale inputs, a thermal support paired with another
column, a replaced support copy, a temperature-prepared or stretched preparation
passed as the base, an eigensystem of another support, rebuild inputs that do not
reproduce the support, and a pre-expired deadline. The CLI binds all four new
files, the retained tools and cases, and the three accepted receipts before and
after; before any control it verifies that every source recorded by those
receipts still has its recorded bytes and that each imported module resolves to
its bound path.

## 9. Sources

**Read for this closure:**

| Source | What it justifies |
| --- | --- |
| Angevine, Heller and Paola (1990), *Quantitative Sedimentary Basin Modeling*, AAPG course notes, chapter 4 "Thermal subsidence" ([course copy](https://pages.uoregon.edu/rdorsey/BasinAnalysis/AngevineEtal1990/Chapt%204%20Thermal%20Subsidence.pdf), scanned pp. 20-35 read) | McKenzie's uniform stretching: crust and mantle lithosphere thinned by the same factor, base held at `T1` at fixed depth by passive upwelling (contrasted with this closed strip); eq. 4.30 `beta = exp(G t)`; eq. 4.32 Peclet number `G a^2/kappa` (here about 9, so neither instantaneous nor quasi-static stretching); section I lateral-conduction caveat. |
| [ASPECT finite strain cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/finite_strain/doc/finite_strain.html), fetched 27 September 2026 | `dF/dt = G F`, `F(0) = I`; integrating `G` alone would give a grain of zero length, whereas the true solution is exponential; natural strain from the stretch; compositional fields suffer numerical diffusion. Supports defining finite strain from the stretch, not accumulated additive strain. |
| [ASPECT particles parameters](https://aspect-documentation.readthedocs.io/en/latest/parameters/Particles.html), fetched 27 September 2026 | 'integrated strain' stores `F`; 'integrated strain invariant' accumulates `dt` times the rate invariant (a path measure); particles follow interpolated velocities with limited accuracy. Supports keeping plastic history as memory separate from geometry; here the affine velocity is exact at material points. |
| [ASPECT continental extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html), fetched 27 September 2026 | Open box with side outflow balanced by basal inflow and a free surface; particles carry composition and plastic strain; 273/1613 K boundaries; its stated breakup limitation without upwelling asthenosphere. Supports the retained temperatures and the explicit statement that this strip is closed. |
| Retained Atlas column-heat derivation ([I01_COLUMN_HEAT.md](I01_COLUMN_HEAT.md) section 4 and its tool) | ETD2/phi3 heat accounting, series interface conductance, support validation; reused along the clock. |

**Not accessible, not claimed as read:** McKenzie (1978, *EPSL* 40, 25-32) and
Jarvis and McKenzie (1980, *EPSL* 48, 42-52); the publisher pages returned HTTP
403 to the fetch tool. Their models are cited only as presented in the chapter
above.

**Reused, not re-read:** Kassam and Trefethen (2005) and Cox and Matthews (2002)
through the column-heat derivation; the Katz et al. (2003) dry-solidus
coefficients through the retained melting tool (section 5 margin only); SciPy
`solve_ivp` DOP853, `brentq` and `linalg.expm` as independent oracle machinery.
No ASPECT run, installation or copied code.

## 10. Results

The coding handoff was prepared without execution. The coordinator runs the
focused tests and the bounded campaign before accepting this closure; consult the
[current evidence register](../../docs/CURRENT_EVIDENCE.md) for any reviewed
receipt. Keeping results there avoids editing this source-bound document after a run.

## 11. Limitations

- Laterally uniform affine pure shear only: no necking, lateral localisation,
  lateral conduction, rupture or separation criterion.
- Closed strip: no asthenospheric inflow, extraction or melt; the base boundary is
  a declared fixed temperature at the rising material base.
- Lithostatic closure remains instantaneous; no elasticity, topography, isostasy,
  sediment or water load; Boussinesq reference densities.
- Constant per-material thermal properties; no latent or adiabatic heating.
- One constant drive degree of freedom with lumped drag; authored heat fractions.
- Properties of authored fixtures, not Earth-wide values or calibration.

## 12. Commands and bindings

From the repository root, with the existing compatible scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_finite_strain.py -v
python -B tectonics/tools/check_i01_finite_strain.py --output NEW_PATH.json
```

The exclusive-create receipt binds, before and after execution, the four new
files, the retained tools and cases listed in the tool, and the accepted receipts
`i01-thermomechanical-motion-r1`, `i01-column-heat-r2` and
`i01-motion-coupling-r1`, which must equal their accepted SHA-256 values. Timings
exclude imports; the cooperative budget is 120 s after them. The reuse
comparison is one matched observation, not a generator forecast.
