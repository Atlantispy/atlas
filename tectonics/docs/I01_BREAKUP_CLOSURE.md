# I01: physical breakup closure — from necking to material separation

**27 September 2026. WORKING NON-CANON. One bounded I01 decision with analytical
feasibility controls; not I05/I06 implementation, a resolved breakup certificate, a
rift solver, world generation or physical acceptance.** This refines D2 and D6 of the
[I01 physical contract](I01_PHYSICAL_CONTRACT.md) and the continental-separation row of
the [D6 transitions](I01_TRANSITIONS.md#3-continental-separation-atlasrift-decoupling-handoffv1).
The [case](../cases/i01_breakup_closure_v1.json), [tool](../tools/check_i01_breakup_closure.py)
and [focused tests](../tests/test_i01_breakup_closure.py) are new. The accepted
[finite-strain strip](I01_FINITE_STRAIN.md) and its retained imports are used
read-only; no retained source, case, receipt or tolerance changes. Measured results
stay outside this source-bound document (section 12).

## 1. The question and the answer, in plain language

When a continent is pulled apart, three different things can happen. Atlas must
record them separately:

1. **Mechanical decoupling.** The stretched belt becomes too weak to control how fast
   the plates move. The rock is still one connected piece.
2. **Material separation (breakup).** The continental material joining the two sides
   thins to nothing somewhere. The margins become separate bodies and the mantle
   beneath reaches the surface.
3. **Magmatic ocean birth.** New crust forms in the gap from melted mantle. That needs
   a melt supply; without one, the floor of the gap is exhumed mantle.

A uniformly stretched column can never break: its thickness `h0/lambda` stays
positive at every finite stretch. Thinning has to concentrate onto less and less
rock. That is **necking**: a slightly weaker place stretches faster under the same
pull, so it becomes thinner and weaker still. Whether necking actually cuts the rock
through after a *finite* amount of opening, or only keeps thinning it for ever, is
decided by the rock's flow law and by the shape of the weakness. It is not decided by
a thickness cutoff.

**Selected law: `atlas.necking-connectivity-breakup.v1`.** The belt is a chain of
material columns side by side. Every column carries the same transmitted pull, which
the existing D1 drive/drag balance sets. Each column thins by its own pure shear, with
its own temperature and history. Breakup would be the moment when the thinnest
column's thickness reaches zero **after a finite opening and time**.

**What this closure establishes, and what it does not:**

- **Established: analytical continuum feasibility.** Take one fixed flow law with a
  constant stress exponent `n` and a weakness whose minimum is a non-degenerate
  quadratic. For `2 < n <= 4`, the exact continuum solution pinches off at a finite
  opening and time. For the control belt, the neck slope also stays inside the
  long-wave bound all the way. The status is `ANALYTICAL_CONTINUUM_PINCH_FEASIBLE`.
- **Not established: a resolved breakup certificate.** Certifying a breakup event for
  a general column law needs spatial resolution at every detection level. It also
  needs a constitutive basis along the whole approach to pinch-off. Neither exists yet,
  so general event certification is `UNRESOLVED` and not implemented. No breakup event
  is issued.

**Refused here.** Brittle (frictional-plastic) necks are how the crust finally separates
in Brune et al. (2014): the lower crust cools and embrittles, and faults cut through to
the mantle. This chain cannot decide those necks, so it refuses them and passes them to
the resolved I07 regional mechanics. The retained Atlas lithosphere column is
plastic-dominated at the sampled states, so the chain refuses that regime too. Whether
that lithosphere eventually separates is unresolved. The refusal is not a proof that it
never does.

## 2. Why the present strip cannot express breakup

The deformation is incompressible plane strain, per unit strike. Take any *fixed* set
of material with reference area `A`. If it takes all the opening `u`, its current width
is `W0 + u`, so its mean thickness is `A/(W0 + u)`. That is positive for every finite
`u`. Therefore:

- **The accepted affine strip** (`h = h0/lambda`) never reaches zero at finite stretch.
- **A neck of fixed current width `w`** thins as `h = h0 exp(-u/w)`. That covers the
  D6 fixed-width belt, and a nonlocal length held constant in current coordinates. It
  has no finite event, as the [transitions separation control](I01_TRANSITIONS.md) shows.
- **Any chain with finitely many columns** cannot let its thinnest column vanish at
  finite opening, because that column is itself a fixed material set.

Zero thickness at finite opening needs the actively thinning material to shrink onto
ever smaller material sets. That means continuous re-localisation in *material*
coordinates.

Two consequences follow. First, **the state must change**: the belt needs lateral
material resolution. Second, **a breakup event can only be the limit** of resolved events.

## 3. Representation: a long-wave necking chain

Material coordinate `X` runs across the belt, `-L <= X <= L`. Each `X` carries one
column: the accepted finite-strain column with stretch `lambda(X,t)`, thickness
`h = h0/lambda`, and material-following temperature and raw plastic history.

**Long-wave assumption.** The neck is much wider than it is thick. Each column then
deforms by its own pure shear, as in the accepted strip, and the depth-integrated
stress is nearly uniaxial.

For incompressible plane strain with lithostatic `sigma_zz`, the depth-integrated
horizontal stress is `integral sigma_xx dz = F_i - U_i`. Here `U` is the integrated
lithostatic pressure (the [I01 GPE](I01_GPE.md) `U`, in J/m²) and `F_i = 2 h_i s_bar`
is the column's deviatoric force. There is no basal traction inside the belt, so the
horizontal balance `d/dX(F_i - U_i) = 0` gives:

```text
F_i(t) = F_t(t) + (U_i - U_ref)                one transmitted force F_t per belt   [N/m]
F_i    = F_col(a_i; lambda_i, T_i, kappa_i)     each column's own law (retained kernel)
dlambda_i/dt = lambda_i a_i ;  h_i = h0_i/lambda_i ;  x_i = x_left + sum_(j<i) lambda_j dX_j
v = sum_i dX_i lambda_i a_i                     belt opening rate (edge speed)       [m/s]
F_drive = D v + F_t                             existing D1 drive / disjoint drag balance
```

- **Relation to the accepted strip.** With one column, or identical columns, this is
  exactly the accepted affine strip.
- **The GPE term.** It is a coupling port (section 8). The feasibility controls
  deliberately disable gravity and GPE: `U_i - U_ref = 0` by construction. Equal
  density structure alone would not make the term vanish, because columns that thin by
  different amounts have different `U`.
- **Material width is never renormalised.** `dX_i` is fixed per material column, and
  each column conserves its own volume exactly.

### Routes compared

| Route | Physical assumptions | Calibration needs | Compute and storage | Decision |
| --- | --- | --- | --- | --- |
| Thickness, strain or low-resistance cutoff | None beyond a chosen number | The cutoff itself | Trivial | Rejected: no law, and the event depends on the cutoff (section 2) |
| D6 decoupling ratio / finite admission | Belt weak enough to ignore mechanically | Coupled-controller tolerance | Scalar | Kept as the separate mechanical record; it is not separation |
| **Long-wave necking chain (selected)** | Plane strain; neck wider than thick; each column in pure shear; one transmitted force | Retained column law (ASPECT-sourced creep parameters); inherited weakness profile as an initial assumption; D1 drive and drag | Per stage, one scalar force root over N independent column inversions. State is O(N × depth points); only event states and ladder values are stored | Selected route. Analytical continuum feasibility is shown here for a fixed power law; a resolved event certificate is future I05/I06 work |
| Resolved x–z visco-elasto-plastic rift (Brune et al. 2014; ASPECT) | Full 2D mechanics, free surface, particle history, softening, asthenosphere | Full rheology, softening, seeds, thermal structure | Brune: 500 × 150 km at 1 km elements, 10 kyr steps over tens of Myr. ASPECT cookbook: 1.25–2.5 km cells for 5 Myr. Particles or fields for history | Required for brittle and plastic-dominated necks, depth-dependent sequencing and rift migration; owned by I07 |
| Whole-crust embrittlement plus a fault geometry | Crust fully brittle, then separation along supplied faults | Fault dip and geometry law | Cheap | Refused as a generator: the separation step is prescribed kinematics. Embrittlement survives only as the refusal classifier |
| Magma-assisted (dyking) breakup | Melt-weakened plate | Melt supply and dyke-opening law | Unknown | Not available: Atlas has no calibrated supply law |

No cost in this table is measured. The resolved-rift figures are the published setups;
they are not an Atlas benchmark.

## 4. When does necking separate? The invariant and the criterion

**Power-law columns.** Take the single-mechanism case of the retained convention:
depth-uniform power-law creep, `F = 2 h s` and `a = A(X) s^n`. It gives
`a = A(X) (F/(2h))^n` and hence

```text
d(h^n)/dt = -n A(X) (F/2)^n      so, for every column,
h^n(X,t)  = h0^n(X) - A(X) Psi(t),    Psi = n integral (F/2)^n dt
```

Every column follows the **same clock `Psi`, whatever the force history**. That is the
long-wavelength result of Hutchinson and Neale (1977, eq. 3.7): the relation between
local and uniform strain does not depend on the load history. Here it is written in
thickness form.

A layered column with one exponent, `A_j` per layer and fixed material temperatures
is the same law with an effective `A`. Activation volume, mixed exponents and the
plastic branch break the invariant (section 6).

**The control profile.** Uniform `h0 = H` and `A(X) = A_max alpha(X)`, with
`alpha = 1 - (X/ell)^2` and `L < ell`: an inherited rheological weakness. Set
`theta = A_max Psi/H^n`, which runs over `[0, 1)`:

```text
lambda(X,theta) = (1 - theta alpha)^(-1/n);   h_min = H (1 - theta)^(1/n) -> 0 as theta -> 1
U(theta)  = integral (lambda - 1) dX                              opening [m]
U'(theta) = (1/n) integral alpha lambda^(n+1) dX
U*        = 2 [ ell^(2/n) L^(1-2/n) / (1 - 2/n) - L ]            finite iff n > 2
```

**The criterion and its hypotheses (an Atlas derivation).** Assume:

1. the single-mechanism law above, with **one constant exponent `n`** and a
   time-independent material field `A(X)`;
2. the long-wave chain, with one transmitted force and the GPE term disabled;
3. the column strength `f(X) = h0(X)^n/A(X)` has a unique minimum `f_min` at `X0`, with
   `1 - f_min/f(X) = c |X - X0|^q (1 + o(1))` near `X0` for some `c > 0`, and
   `1 - f_min/f` bounded away from zero elsewhere.

Then pinch-off happens first at `X0`, when `Psi` reaches `f_min`. Each column's stretch
`lambda = (1 - Psi/f)^(-1/n)` rises monotonically with `Psi`, so the opening at
pinch-off is `U* = integral [(1 - f_min/f)^(-1/n) - 1] dX`. That integral is finite if
and only if `n > q`.

- A **non-degenerate quadratic minimum** (`f''(X0) > 0`) has `q = 2`. The control
  profile is one: `1 - alpha = (X/ell)^2`.
- **Smoothness alone is not enough.** A smooth quartic minimum has `q = 4`. With
  `n = 3` it thins for ever, with no pinch-off at finite opening.
- A **flat-bottomed minimum** (`1 - f_min/f = 0` on an interval, including a uniform
  belt) never separates at finite opening.

The criterion holds only under all three hypotheses; it is not an empirical rule for
other laws. An exponent read from a column's tangent at one finite state is not a
constant `n`, so it does not satisfy hypothesis 1.

Audoly and Hutchinson (2019) give the same kind of critical stretch distribution,
`lambda^c(X) = (1 - (f(0)/f(X))^(1/m))^(-m)` (their eq. 2.12, m = 1/n). Its average is
finite for a quadratic minimum exactly when `m < 1/2`. That derivation is ours; the
threshold is not stated in the sections read (pp. 149–163).

**Time comes from D1.** Let `phi = F_t/F_drive` be the belt's share of the drive. With
`g0 = (1 - s0)/s0^n` for the declared initial share `s0`:

```text
phi + g(theta) phi^n = 1,   g = g0 U'(theta)/U'(0)        (monotone; phi decreases with theta)
v = v_inf (1 - phi),        v_inf = F_drive/D
t(theta) = integral U'(theta) dtheta / (v_inf (1 - phi))  = integral dU / v
```

`1 - phi` stays between `1 - s0` and 1, so `t*` is finite exactly when `U*` is. Near
pinch-off, with `delta = 1 - theta = (h_min/H)^n`:

```text
U* - U  ~  C delta^(1/2 - 1/n)  =  C (h_min/H)^(n/2 - 1)
n = 3: square-root convergence;  n = 2: +2 ell ln 2 per halving (no limit);  n = 1: grows as (H/h_min)^(1/2)
```

**Neck shape and long-wave validity.** In current coordinates the pinch-off profile is
`h ~ |x|^(2/(n-2))`: parabolic for `n = 3`, V-shaped for `n = 4`, a cusp for `n > 4`.
For the quadratic minimum, the neck slope near the tip behaves as

```text
|dh/dx|_tip ~ (H/ell) (h_min/H)^((4-n)/2)        as h_min -> 0
```

- **`2 <= n <= 4`.** The largest slope over the belt rises monotonically to a finite
  limit, `2 H (L/ell)^(4/n - 1)/(n ell)`, reached at the belt edges as `theta -> 1`.
  The feasibility check uses that analytical limit as well as the sampled rungs.
- **`n > 4`.** The tip slope grows without bound, so the long-wave assumption
  eventually fails. The slope scales with `H/ell`, so a slender enough belt passes any
  finite ladder of sampled slopes. Therefore `n > 4` is refused from the asymptotics,
  whatever the sampled slopes show.

Audoly and Hutchinson (2019) find the long-wave approximation "surprisingly accurate"
when rate dependence is significant and imperfections are wider than the specimen
thickness. They also find that gradient (Bridgman) effects matter for narrower
imperfections.

## 5. What the ladder establishes: analytical feasibility, not a resolved event

**The ladder.** The detection ladder is `h_k = H 2^-k` for `k = 1..K`. For the
continuum solution, each rung records the opening `U_k` and time `t_k` at which the
thinnest column first reaches `h_k`. Both come from the exact invariant, by quadrature.

```text
r_k = (U_(k+1) - U_k)/(U_k - U_(k-1))      increment ratios over the last W rungs
FINITE_LIMIT     all r <= r_max, spread <= r_spread; exponent e = -log2(r); tail = dU_K r/(1-r)
NO_FINITE_LIMIT  all r >= r_div
```

**The analytical feasibility status.** It is granted only on an explicit basis: the
fixed single-mechanism power law with constant `n`, the non-degenerate quadratic
weakness profile, and the belt's thickness and lengths. Malformed ladders
(non-finite, negative or mismatched arrays) are rejected as errors and receive no
status. The statuses are:

- `ANALYTICAL_CONTINUUM_PINCH_FEASIBLE`. All of these hold:
  - `2 < n <= 4`;
  - opening and time both have finite limits;
  - the opening exponent is `n/2 - 1` within tolerance;
  - the opening tail recovers the closed-form `U*`;
  - every sampled slope and the analytical slope limit are within the bound.
- `NOT_ESTABLISHED_NO_FINITE_LIMIT`: `n <= 2` and both ladders diverge. Thinning and
  weakening are real, but there is no separation at finite opening.
- `REFUSED_OUTSIDE_LONG_WAVE_VALIDITY`: `n > 4` (from the asymptotics, whatever the
  sampled slopes), or a sampled or limiting slope above the bound.
- `REFUSED_UNSUPPORTED_BASIS`: any other law, profile or provenance. That includes an
  exponent inferred at one finite state, a smooth but degenerate minimum, and geometry
  outside `0 < L < ell`.
- `UNRESOLVED`: the ladders disagree with the exact solution of the declared basis.

Every record also carries `resolved_event: UNRESOLVED`.

**Not a cutoff.** The threshold is a resolution parameter whose influence is removed by
the limit. A cutoff model has no limit and is reported as `NO_FINITE_LIMIT`.

**What is resolved laterally, and what is not:**

- **The first detection level only.** The time-stepped chain is verified against the
  exact discrete chain at `h = 0.1 H` (the `invariant` control). Lateral refinement of
  the exact discrete chain (256–2048 columns) converges to the continuum at that level,
  for `n = 3` only.
- **The deeper rungs are continuum integrals.** At rung `k`, the neck's material scale
  is `w_k = ell (delta_k/theta_k)^(1/2)`: the material half-width over which
  `1 - theta alpha` doubles. At rung 12 it is about 2.29 m for `n = 3` and 0.286 m for
  `n = 3.5`, against columns of about 293 m at N = 2048.
- **No per-rung event.** No rung below the first has a laterally converged discrete
  event.

**A resolved connectivity-loss certificate is not implemented.** General event
certification stays `UNRESOLVED`. Before any `atlas.connectivity-loss-event.v1` is
issued, a future certificate must supply five things:

1. **A constitutive basis along the approach.** Either the declared fixed power law,
   or evidence for the actual column law over the stresses the neck reaches, inside
   the support of its coefficients. An exponent read at one finite state is not enough.
2. **Spatial resolution at every rung used.** Laterally converged discrete events
   (N versus 2N at each rung), with exact material splitting near the neck so that the
   columns resolve the neck's material scale.
3. **Long-wave validity along the whole approach,** from the declared law's asymptotics
   and not only from sampled slopes.
4. **Declared coupling errors.** A thermal error criterion (a length, time and
   gradient) if temperatures evolve (section 8), and the GPE term from the I01 GPE
   column law instead of zero.
5. **The event record** of section 8, with the tail booked as a handoff error.

## 6. Brittle, plastic-dominated and fixed-width necks are refused

- **Rate-independent plasticity** makes the long-wave chain ill-posed. The weakest
  material set takes all the opening, so the event opening scales with the column
  width (`2 dX (H/h - 1)`) and vanishes under refinement. This is the thin-sheet form
  of mesh-dependent localisation.
- **Regularised plasticity in the retained kernel.** The retained kernel adds a
  regularised plastic rate to the creep rates at one stress:
  `a = sum_k A_k s^(n_k) + max(s - Y, 0)/(2 eta)`, with `eta = 1e21 Pa s` in the
  retained case.
  - Just above yield, the plastic branch is nearly rate-independent. Where it
    dominates, the overstress `2 eta a` is linear in rate, so `n_eff` falls towards 1.
  - That is an intermediate window, not the asymptote. Any creep mechanism with
    `A > 0` and `n > 1` grows faster than the plastic branch. At high enough stress,
    the plastic share falls to zero, as `s^(1-n)/(2 eta A)` for the dominant mechanism,
    and `n_eff` tends to that mechanism's `n`.
  - So the regularisation does not ultimately dominate, and it does not imply that a
    plastic-dominated neck never pinches.
  - The `validity` control shows both regimes on a scaled analytical law,
    `r = k sigma^n + max(sigma - 1, 0)`. The law is independent of the mantle fixture,
    and the control checks it against the retained point kernel.
  - The retained lithosphere is not extrapolated: its coefficients are not evaluated at
    the stresses where creep would take over.
- **An imposed viscosity floor is a different modification.** A floor (the ASPECT
  cookbook sets a minimum viscosity of 1e18 Pa s) replaces the response wherever it is
  active. It is not equivalent to the retained parallel branch. The Atlas kernel has no
  floor, and none is analysed here.
- **A fixed physical length in current coordinates** thins exponentially (section 2).
  That includes the D2 nonlocal `ell = 5 km` of the fault fixture.
- **What a brittle neck actually needs.** Its width scales with its *current thickness*,
  because conjugate faults or slip lines cross the layer. Only a resolved x–z neck can
  represent that, and it needs a physical shear-zone width much smaller than the
  thickness. This matches Brune et al. (2014, Fig. 2 and Results): "The crust becomes
  progressively brittle and faults penetrate into the mantle ... Soon after, these
  faults bring the crust to break-up until mantle is exhumed with very little magmatic
  activity."
- **Owner.** I07 owns that resolved neck. Atlas does not insert a universal fracture
  energy or put a brittle law on the ductile mantle to replace it.

**Classification rule for a column state** (frozen in the case):

- `PREMISE_CONSISTENT_WITH_REDUCED_PINCH` if, at the state and along a rising rate
  ladder, the plastic share of the column's dissipation is at most `p_max` and
  `1/4 <= m_eff < 1/2`, where `m_eff = a F'(a)/F`.
- Otherwise `REFUSED_REQUIRES_RESOLVED_NECK`.

Both outcomes are regime diagnostics at the sampled states:

- `REFUSED_REQUIRES_RESOLVED_NECK` means the reduced chain does not support that
  regime, so resolved mechanics is needed. The state's eventual breakup stays
  unresolved: it is neither predicted nor excluded.
- `PREMISE_CONSISTENT_WITH_REDUCED_PINCH` grants nothing. An `m_eff` read at a finite
  state is not the constant-power-law basis of section 5.

## 7. Decoupling, separation and ocean birth are three records

| Record | Trigger | What changes | What does not |
| --- | --- | --- | --- |
| Mechanical decoupling (D6 `atlas.rift-decoupling-handoff.v1`) | `phi = F_t/F_drive <= eps_v` | The solver may treat the belt as a weak coupling | Material stays connected; no new area, no boundary split |
| Material separation (`atlas.connectivity-loss-event.v1`) | A future resolved certificate (section 5); not issued by this closure | Split at the neck by current material position; fresh divergent boundary; margins keep cohorts, ages, heat and D2 memory | No ocean crust is created by the split |
| Magmatic ocean birth (D3 `atlas.decompression-supply.v1`) | Opening after separation plus an actual melt/enthalpy source | New cohorts from the supply | Exhumed mantle is never relabelled as basalt |

In this chain `phi` decreases monotonically, so decoupling is permanent once reached.
The control shows two things:

- For `n = 3`, decoupling comes before the analytical pinch-off, with a finite interval
  between them.
- For `n = 1` and `n = 2`, decoupling happens at finite time, but the exact continuum
  solution never separates at finite opening. The result is a hyperextended belt that
  is decoupled but still connected.

## 8. Coupling ports for I05/I06

- **Force (D1).** Solve `F_drive - D v(F_t) = F_t`. Here
  `v(F_t) = sum dX_i lambda_i a_i(F_t + dU_i)` is monotone in `F_t`, so this is a
  scalar root with N independent column inversions per evaluation. Use the retained
  `respond_force`, parallel across columns. The belt share `phi` is the decoupling
  diagnostic.
- **GPE (D1/D5).** Use `F_i = F_t + (U_i - U_ref)`, with `U_i` from the I01 GPE column
  law on the same columns. Higher-GPE columns carry more deviatoric tension:
  - thinner crust lowers `U` and resists necking;
  - thinning of dense mantle lithosphere can raise `U` and promote it.

  No separate ridge-push line force is added. The feasibility controls switch this
  term off deliberately; they do not show that it is zero.
- **Temperature (D4).** Each column runs the accepted material-coordinate thermal clock
  with its own `lambda_i(t)`.
  - **Lateral conduction is omitted, and the slope bound does not bound that
    omission.** Columns with flat tops and bases can still have sharp lateral
    temperature differences.
  - **A future coupling must declare a thermal error criterion,** in terms of a lateral
    length, a time and a temperature gradient. None is claimed here. The controls in
    this closure are isothermal and need no thermal solver.
  - **At the base,** either keep the accepted fixed material-base temperature or adopt
    an asthenosphere inflow account. ASPECT states that realistic breakup needs
    upwelling asthenosphere or a Winkler base. The vacated region below thinning
    columns belongs to a named exterior account.
- **History (D2).** Raw plastic history stays per column, never filtered across the
  neck in the chain. The D2 nonlocal length belongs to the resolved I07 neck.
- **Material.** Volume is conserved per column. Splitting a column into two with
  identical state is exact; merging needs identical state or a declared remap. At
  separation, ownership follows current material position.
- **Event (D6).** Only a future resolved certificate issues the
  `atlas.connectivity-loss-event.v1` record. It holds:
  - parent and interval; law and parameters;
  - ladder levels, openings and times;
  - increment ratios, the local exponent and lateral-refinement changes;
  - maximum slope, neck position (`X*`, `x*`) and split rule;
  - handoff error (tail opening and time); new boundary ID;
  - post-separation supply owner (D3); status or refusal.

## 9. Controls (frozen before execution)

The case fixes every input and gate; the tool refuses a case that differs.

**Authored control inputs:**

- `H = 100 km`, the thickness of the accepted strip.
- `L = 300 km` and `ell = 600 km`, so the weakest column is 25% weaker in `A` than the
  belt edge.
- `F_drive = 2e13 N/m` and `D = 5e22 Pa s`: the reviewed motion drive and drag,
  checked against the retained context.
- Initial belt share `s0 = 1/2`.
- Exponents 3 and 3.5 (inside the analytical window), 1 and 2 (subcritical) and 5 (above
  it). Wet anorthite, dry olivine and wet quartzite in the retained case use 3, 3.5
  and 4.
- A slender belt, `H = 1 km`, for the `n = 5` asymptotic refusal.
- The scaled parallel-plastic law: `n = 3`, `k = 1e-4`, and stress multiples 10, 100,
  1000 and 10000 of yield.

| Control | What it tests | Checks |
| --- | --- | --- |
| `invariant` | Implementation and event detection at the first detection level; not physics | A time-stepped chain (DOP853 on `ln lambda_i`, clock, edge and work accounts) with the D1 root at every stage, N = 256 and 1024, detection at `h = 0.1 H`. It must match the exact discrete-chain solution in opening and time. The invariant residual, kinematic closure (edge displacement against summed column elongation) and drive = drag + belt work are checked. A prescribed oscillating force gives the same opening at detection, but a different time. Uniform chains with N = 1 and 8 are identical to each other and to the affine strip's closed-form opening and time. |
| `pinch` | Analytical continuum feasibility of the declared power law; not a resolved event | For `n = 3` and `3.5` on a 12-rung ladder:<br>• Quadrature self-consistency, independent `2F1` values and the derivative identity.<br>• Closed-form `U*`, and `t*` by an endpoint-regularised quadrature.<br>• `FINITE_LIMIT` for opening and time, with exponent `n/2 - 1`; the tail estimates recover `U*` and `t*`; sampled and limiting slopes within bound; status `ANALYTICAL_CONTINUUM_PINCH_FEASIBLE`.<br>• Lateral refinement (256–2048 columns) of the exact discrete chain converges to the continuum at second order, at the first detection level only.<br>• Decoupling precedes the analytical pinch-off.<br>• Reported: the material neck scale at every rung, the finest column width, and `resolved_event: UNRESOLVED`. |
| `no_pinch` | Negative cases: thinning and weakening are real, breakup is not established | • `n = 1` and `n = 2`: closed forms agree with the quadrature; `NO_FINITE_LIMIT` within validity; decoupled but connected.<br>• A uniform (affine) belt.<br>• A flat-bottomed plateau weakness with `n = 3`.<br>• A fixed 5 km neck width, equal to the D2 fixture length and read from its case.<br>All five are `NO_FINITE_LIMIT`. |
| `validity` | Refusals outside the representation, and the plastic asymptote | • `n = 5`: the reduced law predicts a finite `U*`, but the neck slope exceeds the bound, so `REFUSED_OUTSIDE_LONG_WAVE_VALIDITY`.<br>• The same `n = 5` ladder on the slender belt: every sampled slope is inside the bound, and the status is still `REFUSED_OUTSIDE_LONG_WAVE_VALIDITY`.<br>• A rate-independent chain's event opening halves with each column halving, so `REFUSED_ILL_POSED_RATE_INDEPENDENT`.<br>• The scaled parallel-plastic law matches the retained point kernel. The frozen classification rule refuses it at 10 times yield and admits it at 10000 times yield. Its plastic share falls along the ladder, and its local exponent approaches `n`. |
| `retained` | Connection to the accepted column | The accepted finite-strain column (order 64) at its committed initial state must reproduce the r2 receipt's first-stage speed and column force. Force rises with rate and falls with stretch. Along a rate ladder at stretch 1, 1.2 and 1.4 it reports `m_eff`, the plastic share and the necking number `gamma = (-dlnF/dln lambda)/m_eff`. The frozen classification is reported, not gated; the eventual breakup is reported as `UNRESOLVED`. |

**Why the gates are discriminating.**

- **Chain against discrete oracle.** The chain integrates `N + 5` coupled ODEs and never
  uses the invariant; the oracle uses only the invariant. They agree only if the force
  root, clock and event location are right at that detection level.
- **Load-history test.** It separates geometry, which is a material property, from
  time, which the force balance owns.
- **Threshold ladder with the exact solution.** It separates a finite singularity from
  a cutoff. Feasibility also needs the tail to recover the closed-form `U*` of the
  declared basis, so converging arrays alone cannot pass.
- **Negatives.** They show that thinning, weakening and decoupling can all be present
  without separation.
- **Validity rows.** They show refusal where the reduced dynamics would otherwise
  over-claim. The slender row shows that the `n > 4` refusal does not depend on
  sampled slopes.
- **Parallel-plastic row.** It shows that the plastic-dominated refusal is a regime
  diagnostic, not a universal no-pinch rule.
- **Retained parity.** It proves the classification is evaluated at the accepted
  committed state, not at an invented one.

**Gate values:**

- Quadrature self-consistency, closed forms and independent `2F1`: `1e-10`. These are
  round-off-level agreements of different rules.
- Chain against oracle: `1e-8`, with ODE `rtol = 1e-12`.
- Exponent tolerance: `0.01`. The corrections are `O((h/H)^(5/6))` for the opening at
  `n = 3`.
- Tail estimates: `1e-4` for opening and `1e-3` for time. The D1 correction decays only
  as `(h/H)^(5/6)`.
- Refinement orders: `[1.8, 2.2]`, because the discrete error is `O(dX^2)` through the
  midpoint rule and the detection shift.
- Slope bound: `0.25`, an authored long-wave representation bound, not a geological
  constant.
- The parallel-plastic row reuses existing tolerances: `exponent_tolerance` for its
  local exponent and `parity_relative` for its kernel parity.

The cooperative budget is 60 s after imports. The deadline is checked inside the ODE
right-hand side and at every control boundary, so a slow solve stops at the budget
rather than after it.

## 10. Validity and limits of this closure

- **Long-wave, plane strain, depth-uniform stretching per column.** This gives no rift
  migration or asymmetry, and no crust-first versus mantle-first separation: every
  column loses crust and mantle together. Those need the resolved I07 neck.
- **The power-law control is isothermal and single-mechanism,** with no activation
  volume and no plastic branch. The retained layered column is only classified here,
  never run in the chain.
- **No resolved event.** Only the first detection level is laterally resolved, and
  general event certification is `UNRESOLVED` (section 5).
- **The weakness profile is an inherited geological assumption.** The chain has no
  intrinsic length, so it cannot select the dominant necking wavelength (a 2D effect)
  or nucleate a neck.
- **No GPE, flexure, isostasy, water or sediment load** in the control. The GPE port is
  specified in section 8.
- **Isothermal controls.** They need no thermal solver, and the slope bound says
  nothing about lateral conduction (section 8).
- **No melt, asthenosphere inflow or ocean crust.** Separation is not ocean birth.
- **Authored inputs only;** no Earth calibration. The analytical window `2 < n <= 4`
  for a constant `n` and the slope bound are representation limits.

## 11. Sources

**Read for this closure:**

| Source | Parts read | What it supports |
| --- | --- | --- |
| [Brune et al. 2014](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf), Nat. Commun. 5:4014 | All 9 pages: Results, Figs. 1–6 and captions, Discussion, Methods (modelling, numerical, thermal, melt, rheology, weakening, boundary conditions, alternatives) | Localisation by friction softening. Rift migration ends when the lower crust cools. Crustal break-up by faults that penetrate the embrittled crust into the mantle, then mantle exhumation. Kinematic 4 mm/yr side boundaries. Friction softening 0.5 to 0.05 over plastic strain 1. Dislocation creep n = 3–4 for crust (plus dry olivine for the mantle). Viscous softening factor 30. Break-up is read from the resolved 2D geometry, not from a scalar threshold. |
| [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) | Setup, rheology, strain fields, breakup statement, mesh | "will not produce a realistic representation of continental breakup due to the lack of an upwelling asthenosphere layer"; breakup studies need an asthenosphere or modified basal conditions |
| ASPECT `cookbooks/continental_extension/continental_extension.prm` (main branch) | Material model / Visco Plastic, boundary velocity, end time | Stress exponents 3.5/4/3. Cohesion 20 MPa and friction 30°, weakened by a factor 4 between plastic strain 0.5 and 1.5. Plastic damper 1e21 Pa s. Viscosity limits 1e18–1e26. Prescribed ±0.25 cm/yr sides |
| ASPECT `source/material_model/rheology/strain_dependent.cc` (main branch) | `compute_strain_weakening_factors`, `calculate_plastic_weakening`, `fill_reaction_outputs`, `calculate_strain_healing` | Clamped linear weakening. The plastic-strain increment is `edot_ii dt` at yielding points. Optional temperature-dependent healing. Softening is local memory, not a separation law |
| [Hutchinson and Neale 1977](https://groups.seas.harvard.edu/hutchinson/papers/340.pdf), Acta Metall. 25:839–846 (author scan) | All sections, eqs. 2.1–2.23, 3.1–3.13, 4.1–4.7, 5.1 | Long-wavelength approximation. Load-history independence (eq. 3.7). Local area reaching zero at finite uniform strain (eq. 5.1). Long-wave growth `n eps0` (eq. 2.11). Stated three-dimensional limits |
| [Audoly and Hutchinson 2019](https://groups.seas.harvard.edu/hutchinson/papers/2019-1-Rate-DependentNecking.pdf), J. Mech. Phys. Solids 123:149–171 (author copy) | pp. 149–163: sections 1–6 and the start of Appendix A | Long-wave equations 2.5–2.12, including the critical stretch distribution and its average. Plane-strain sheets are equivalent to bars (sec. 5.3). The long-wave approximation is accurate for significant rate dependence and wide imperfections; gradient/Bridgman effects matter for narrow ones |

**Retained Atlas material (read or inspected):**

- [I01 physical contract](I01_PHYSICAL_CONTRACT.md), D2 and D6.
- [D6 transitions](I01_TRANSITIONS.md) and their fixed-width separation and supply controls.
- [Finite strain](I01_FINITE_STRAIN.md), [finite admission](I01_FINITE_ADMISSION.md),
  [strength](I01_STRENGTH.md), [2D fault](I01_FAULT2D.md), [thermal](I01_THERMAL.md),
  and the [GPE](I01_GPE.md) `U` definition.
- Retained tools, inspected read-only: `check_i01_finite_strain.py` (`column_at`,
  `stage`, `evolve`, `layered`, `connection_control`, bindings), `check_i01_weakening.py`
  (`respond`, `respond_force`, the immutable `frozen` helper), `check_i01_column.py`
  (`LocalLaw.solve`, whose creep and regularised-plastic rates add at one stress) and
  `check_i01_transitions.py`.
- Cases (column, weakening, finite strain, fault2d) and the finite-strain r2 receipt's
  bindings and start-stage values.

**Not accessible or not read, and not claimed:**

- Schmalholz and Mancktelow (2016, Solid Earth 7:1417): only the landing-page
  abstract; the PDF exceeded the fetch limit.
- Huismans and Beaumont (2011, Nature 473:74): the publisher and PubMed pages were not
  accessible. Their crust-first and mantle-first breakup types are named here only as a
  limitation to test in I07.
- Not accessed: Schmalholz et al. (2008), England and McKenzie (1982), Houseman and
  England (1986), Fletcher and Hallet (1983), Zuber and Parmentier (1986),
  Pérez-Gussinyé and Reston (2001) and Duretz et al. (2020). The lateral force balance,
  the `n > q` criterion with its hypotheses, the slope asymptotics and the
  parallel-plastic asymptote are derived here and not attributed to them.

No external software was installed or run, and no model output was fitted.

## 12. Results

None are recorded here. The coordinator runs the focused tests and the bounded
campaign. Any reviewed receipt belongs in the [current evidence register](../../docs/CURRENT_EVIDENCE.md),
not in this source-bound document.

## 13. Remaining I05/I06/I07 work

**I05:**

- **The belt state.** Store ordered material columns (`dX_i`, `lambda_i`, per-column
  `T` and `kappa` on the shared preparation) and current edges. Material refinement
  near the minimum-strength column must be exact splitting only.
- **Solves.** The common-force root with retained column inversions. Per-column
  thermal clocks with a declared lateral-conduction error criterion, and the basal
  inflow decision. The GPE port.
- **Neck diagnostics per stage:** `m_eff`, plastic share, slope and necking number.

**I06:**

- **The resolved event certificate** (not implemented; `UNRESOLVED`). Meet the five
  obligations of section 5 before issuing `atlas.connectivity-loss-event.v1`.
- **On a certified event:** split by material position at the last resolved rung, and
  book the tail as a handoff error against the D6 tolerance. Post-separation area comes
  only from D3.
- **On `NO_FINITE_LIMIT`:** the belt stays connected. The D6 decoupling handoff may
  still switch to a weak coupling, but there is no ocean birth.

**I07 (refused cases):** the resolved x–z visco-elasto-plastic neck, with a free
surface, particle history, physical shear-zone width much smaller than the thickness,
and asthenosphere inflow. It must:

- decide brittle and plastic-dominated separation, including for the retained
  lithosphere, and depth-dependent sequencing;
- reproduce this chain's analytical continuum result for the declared power law in the
  long-wave limit.

## 14. Commands and bindings

From the repository root, with the existing compatible scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_breakup_closure.py -v
python -B tectonics/tools/check_i01_breakup_closure.py --output NEW_PATH.json
```

**What the receipt binds.** It is created exclusively. Before and after execution it
binds:

- the four new files;
- the retained imported tools and cases;
- the fault2d case (read for its length);
- the accepted `i01-finite-strain-r2` receipt at its accepted SHA-256.

**Before any control runs,** the tool verifies two things: every source recorded by
that receipt still has its bytes, and each imported module resolves to its bound path.

**Timings.** They exclude imports and are raw control observations. No performance
comparison is claimed, because no matched comparator exists for this new closure.
