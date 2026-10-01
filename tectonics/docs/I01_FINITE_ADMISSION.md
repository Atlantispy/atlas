# I01: motion admission on the evolving finite-strain column

**27 September 2026; restoration of I02 ledger commits added 29 September 2026. WORKING
NON-CANON. One bounded I01 connection, which also admits states the I02 ledger restores
(section 5) but is not itself I02; not rupture or topology, a whole-world run or an
automatic solver switch.** The
[case](../cases/i01_finite_admission_v1.json), [tool](../tools/check_i01_finite_admission.py)
and [focused tests](../tests/test_i01_finite_admission.py) are new. The accepted
[finite-strain strip](I01_FINITE_STRAIN.md), [column admission](I01_COLUMN_ADMISSION.md)
and [exact decoupling gate](I01_DECOUPLING.md) are imported read-only; no retained
source, case, receipt or tolerance changes. Measured results stay outside this
source-bound document (section 10).

## 1. What this answers, in plain language

Before a deforming belt could ever be replaced by a simpler boundary, one must know
that losing its resistance would not change the motion by more than an allowance,
not only now but for the whole period ahead. The earlier column admission answered
that for a column whose width, thickness, pressure and temperature were frozen, and
only while total strain stayed below 5%. The accepted finite-strain strip does
change: it widens, thins, loses overburden, heats and weakens as it moves.

This connection rests on four facts that hold for every future state of that strip,
however its temperatures evolve inside the accepted window:

1. The pull is constant and positive, so the strip only widens, and never faster
   than drag alone would allow.
2. Plastic history only grows (no healing), so rock can only weaken.
3. A thinner strip carries less rock, and each parcel carries less overburden.
4. Creep can only take strain rate away from the plastic branch; it never adds stress.

From these the tool computes, once, the largest resistance the strip could offer at
any later moment, then asks the retained exact gate whether even that worst case
keeps the motion within the allowance for the declared future window. A pass is a
guarantee for that window of the retained model. A failure means only **not
certified by this bound**: the actual error may still be small. Nothing is switched,
separated or ruptured, and `generated_separation_authorised` is always false.

The window is measured on the strip's own clock from its undeformed reference. Only a
state that the tool itself produced by running the accepted evolution (or that
evolution's starting state) can be admitted, and only with an envelope prepared from
the same run. An edited, rebuilt or imported state is refused, so no one can relabel
the clock, the reference or the rock's history to claim a used part of the horizon
again (section 5).

## 2. The model that is bounded

The retained strip of [I01_FINITE_STRAIN.md](I01_FINITE_STRAIN.md), sections 2 and 4,
with Gauss points `j` of its represented quadrature:

```text
lam >= 1                   stretch from the reference preparation (lam = 1 at elapsed time 0)
q_j = q0_j/lam             current Gauss width; q0_j at the reference [m]
P_j = P0_j/lam             lithostatic vertical stress or supplied mean pressure [Pa]
w = w0 lam,  e = v/w       current width [m]; axial rate = strain-rate invariant [1/s]
F > 0, D > 0               constant driving force [N/m]; disjoint generalised drag [Pa s]
kappa_j                    raw engineering plastic history (memory, never geometry)
C_j = C0_j lamC(kappa_j),  phi_j = phi0_j lamphi(kappa_j)
lamX(kappa) = 1 - (1 - fX) clip((kappa - k_start)/(k_end - k_start), 0, 1),   0 < fX <= 1
```

At every point the retained summed-rate law and closures are

```text
e = sum_m creep_m(s; T, P) + max(s - Y, 0)/(2 eta_j),    creep_m >= 0,  eta_j > 0
Y = C cos(phi) + max(P - p_c, 0) sin(phi),    p_c = s (lithostatic, extension) or 0 (supplied)
R = 2 sum_j q_j s_j,    F = D v + R,    dlam/dt = v/w0,    dkappa_j/dt = 2 e_p,j >= 0
```

The kernel admits `C0 >= 0`, `0 <= phi0 < pi/2`, at least one creep mechanism with
positive prefactor per point and, here, a plastic branch at every point. Pore pressure
is zero: the finite-strain model refuses supplied pore pressure.

## 3. Derivation

An envelope is prepared from one committed state with stretch `L`, raw history
`kappa_f` and elapsed time `t_f`; a window `[t_s, t_s + T]` is admitted from a later
committed state `S` of the same evolution (section 5) with `lam_s >= L`,
`kappa_s >= kappa_f` and `t_s >= t_f`.

**Lemma 1 (direction, speed, reach).** Every point has creep with a positive prefactor,
so `s -> 0` as `e -> 0` and `R(0+) = 0`; `R` has the sign of `v`. If `v <= 0` then
`D v + R <= 0 < F`, so every balanced state has `v > 0`, hence `R >= 0` and
`D v = F - R <= F`. Therefore `lam` never decreases and

```text
lam_s <= lam(t) <= lam_s + (F/D)(t - t_s)/w0.
```

**Lemma 2 (history floor).** `dkappa/dt = 2 e_p >= 0`, so `kappa(t) >= kappa_s >= kappa_f`
at every point. Since `0 < fX <= 1` the factors never increase with history:
`C_j <= Cmax_j = C0_j lamC(kappa_f,j)` and `phi_j <= phimax_j = phi0_j lamphi(kappa_f,j)`.

**Lemma 3 (pointwise stress).** If `s <= Y` then `s <= Y + 2 eta e`. Otherwise
`(s - Y)/(2 eta) = e - sum(creep) <= e`. With `C >= 0`, `p_c >= 0` in extension,
`cos(phi) <= 1` and `0 <= sin(phi) <= min(1, phi)`:

```text
s <= Y + 2 eta e,     Y <= Cmax + P min(1, phimax).
```

**Lemma 4 (envelope).** For `lam >= L` and `v > 0`, using `q = q0/lam <= q0/L`,
`P = P0/lam <= P0/L` and `e = v/(w0 lam) <= v/(w0 L)`:

```text
R(v, state) <= 2 sum((q0/L)(Cmax + (P0/L) min(1, phimax))) + 4 sum(q0 eta) v/(w0 L^2)
            <= Ybar + Abar v
Ybar = 2 g sum((q0/L)(Cmax + (P0/L) min(1, phimax))),   Abar = 4 g sum(q0 eta)/(w0 L^2)
```

with `g = 1 + 2^-50` (section 4). Temperature appears only in the creep terms, which
the bound discards, so the envelope holds for **every** temperature field, including
whatever the coupled conduction and mechanical heating produce. No effective power
exponent is fitted: exponent 1 belongs to the upper bound, not to the rock.

**Theorem (future-window certificate).** Suppose also that the admitted temperatures
of `S` lie in `[T_lo, T_hi]`, `t_s + T <= H` (the cumulative horizon) and
`lam_s + (F/D) T/w0 <= U` (the stretch ceiling). Then for every continuation of the
retained model over `[t_s, t_s + T]` that stays inside its temperature window and
constitutive support:

```text
(a) lam_s <= lam(t) <= U                         the stretch window cannot be left
(b) v(t) >= v_low = max(0, (F - Ybar)/(D + Abar))
(c) if the retained gate admits eps' = min(eps, X/(T v0)), v0 = F/D, then for all t
        0 <= v0 - v(t) <= eps' v0
        0 <= v0 T - [x(t_s + T) - x(t_s)] <= eps' v0 T <= X
        0 <= F v0 T - W_drive <= F eps' v0 T
```

*Proof.* (a) is Lemma 1 with the admitted reach. By Lemmas 1-2 every state of the
continuation has `lam >= L` and `kappa >= kappa_f`, so Lemma 4 applies:
`F - D v = R <= Ybar + Abar v` gives (b). The retained exponent-1 gate evaluates
`(Abar/D) x <= 1 - x - Ybar/F` at `x = 1 - eps'` in exact rationals, which is
`v_low >= (1 - eps') v0`; integrating (b) over the window and multiplying by `F`
gives (c). Drive work is `F` times edge displacement at constant force. ∎

The theorem is conditional on the continuation remaining inside the temperature
window and constitutive support; the retained evolution refuses otherwise, and a
refusal ends what the certificate describes. It does not predict or match the
coupled thermal trajectory.

**Corollary (the discrete trajectory).** Every stage of the retained scheme, the Euler
predictor `(lam_n + dt v_n/w0, kappa_n + dt kdot_n)` with a window-checked
temperature and the re-solved endpoint, is a balanced state meeting the premises of
Lemma 4. Each stage speed therefore obeys (b) up to the kernel's root tolerances and
floating evaluation. Stretch, displacement and drive work are positive-weight
quadratures (`w_n + w_a = 1`) of stage speeds, so they obey (a) and (c) to the same
accuracy. This conditional argument covers every balanced stage.

**What the numerical checks observe is narrower.** The controls compare only each
window's two committed endpoint stages (speed and column force), its aggregate
displacement, drive work and stretch gain, and its endpoint history and temperatures.
Per-stage bounds imply the aggregate ones, but aggregates passing does not show that
every intermediate stage passed. No trajectory is stored to inspect the intermediate
predictor or committed stages. The comparisons are diagnostics of the discrete model,
never the proof.

## 4. Exact arithmetic and the floating geometry/pressure contract

- **Envelope and gate.** Every coefficient and decision is a `Fraction` of the
  represented binary64 inputs: reference weights, pressures, cohesion, friction,
  regularisation, law parameters, `F`, `D`, `w0`, the history floor, `L`, `t`, `T` and
  the window. `Fraction(float)` is the float's exact value. Division by `L` happens in
  exact arithmetic, never through a rounded derived array.
- **Rounded derived arrays.** The floating realisation forms `fl(q0/lam)`,
  `fl(P0/lam)`, `fl(w0 lam)`, `fl(|F|/D)` and the axial rate from them. IEEE 754 requires
  each such operation to be exactly rounded, so in the normal range each carries a
  relative error of at most `u = 2^-53`. The rounded weight, pressure and rate exceed
  their exact affine values by at most `(1+u)^3/(1-u)^2 < 1 + 6u`. `Ybar` and `Abar` both
  carry `g = 1 + 8u`, so the envelope also dominates the plastic-limit resistance
  evaluated with the arrays the model actually uses. They are never treated as exact.
- **Numerical allowance, not proof.** The retained kernel's stress roots (`2e-11`),
  motion root (`1e-10`), library `exp/log/sin/cos`, products and `fsum` are not bounded
  by this proof. Comparisons with the numerical trajectory use one declared
  allowance, `1e-9`, the retained column-admission `inequality_relative`. It is
  reported apart from the exact bounds and never enters a gate.
- **The frozen window edge.** `float(5e22) = 5e22 - 2^22` and `float(1.4) < 1.4`. The
  exact drag-only reach of the represented forcing from the reference over the whole
  `1e14 s` horizon is about `1.4 + 3e-17`, above the represented ceiling
  `1.4 - 9e-17`. The finite-strain case admitted that window through its `1e-12` float
  tolerance; this admission does not borrow it, so that single full-horizon window
  from the reference is refused. Windows from later states keep physical slack
  because the resisted strip is slower than the drag-only bound.
- **Quadrature model only.** The certificate covers the represented Gauss-point
  column. A converged quadrature is not reinterpreted as an enclosure of the
  continuous depth integral; another order needs another envelope.

## 5. Issued states, absolute reference, cumulative limits and repeated admission

```text
evolution  = Evolution(base, thermal, law, drive, key, kappa0, step_s=dt, window=...,
                       temperature_step_k=..., fractions=..., policy=...)   # validated; runs nothing
origin     = reference_state(evolution)             # issued: lam = 1, t = 0, kappa0, theta0
raw, state = evolved(evolution, n)                  # runs the retained evolve n steps; issues the endpoint
envelope   = prepare(base, thermal, law, drive, key, state, window=..., horizon_s=...)
result     = admit(envelope, base, thermal, law, drive, later_state,
                   duration_s=T, relative_tolerance=eps, displacement_limit_m=X)
```

**Provenance contract.**

- **One evolution.** An `Evolution` names one authorised retained evolution. It holds
  the reference preparation and paired support by identity. It copies the law,
  drive, inputs key, initial history, initial temperature departure and the retained
  settings: time step, window, temperature-step guard, heat fractions and policy.
  Every construction, `dataclasses.replace()` included, is validated through the
  retained pairing (`fs.paired`: fresh key, paired support, zero pore pressure,
  eigensystem), the window, the policy and the initial temperatures.
  The eigensystem is built internally once, with immutable bytes-backed arrays;
  constructors and `replace()` cannot inject externally mutable modal data. Every
  issued run reuses those owned modes. The copied window/policy control refusals,
  not trajectory coefficients; the inputs key is checked again before each run.
- **Two state issuers.** `reference_state(evolution)` issues lam = 1 at zero time with
  the evolution's own initial history and temperature. `evolved(evolution, n)` calls
  the retained `fs.evolve` itself, from that reference, for `n` steps at the
  evolution's own step and settings. It issues a state only for a `COMPLETE` run of
  exactly `n` steps at that step, copying the committed endpoint read-only, and
  returns the raw output beside it for diagnostics.
- **One envelope issuer.** `prepare()` accepts only a state issued by an evolution of
  exactly the preparation, support, law and drive it receives, and records that
  evolution in the envelope. `admit()` accepts only an issued envelope and a state
  issued by the same `Evolution` object, then applies the checks below.
- **The issue mark.** The mark is the record's `evolution` field. It is no constructor
  argument, and `dataclasses.replace()` rebuilds through the constructor without
  copying it (Python refuses to set an `init=False` field that way). Frozen records
  reject assignment, and arrays are copies backed by immutable bytes. A state built
  field by field, even from genuine values, an edited copy, a raw or imported
  dictionary, and an edited or built envelope therefore carry no mark and are
  refused. A shallow `copy.copy` is the same issued record; a deep copy creates a
  different evolution object and is refused.
- **Trust boundary for raw outputs.** A raw evolution output is never evolution
  evidence, whether `evolved()` returned it, the retained evolve was called directly
  or it was imported from a file. Raw outputs feed only the numerical diagnostics, and
  no function converts a dictionary into an issued state.
- **Not provided.** No defence against deliberate bypass of Python's object model:
  `object.__setattr__` on a frozen record, private names, monkeypatching this module,
  `gc`, `ctypes` or edited pickles. No persistence, restart, cross-process identity,
  registry or log: issued records live only in the process that made them.
- **Engine-owned restoration (I02.5).** `restored(evolution, ledger, commit)` issues a state
  for an accepted commit of the package ledger
  ([I02 workflow](I02_WORKFLOW.md#5-saving-reopening-and-continuing)). The ledger re-reads the
  commit on its accepted chain and rebuilds its state with the package restorer, which
  re-derives every identity from stored values and checks the admitted ranges and the
  retained step relations; the tool then requires that state to be exactly this evolution's
  history (fingerprints, law, drive, fractions, step, window, guard, policy, initial
  departure and history, production solver). A common state, a fingerprint, a raw output, a
  `Commit` object edited after it was issued or a commit of another ledger is refused. The
  ledger store is trusted local input: these checks establish consistency, not who wrote a
  record, so a consistent record appended to the store by other means is restored and
  admitted like a computed one. The source and runtime identities are those its caller
  declared when opening the ledger (`Ledger.open` compares them with the recorded ones);
  `restored()` does not check which code produced the history, so admitting a restored state
  does not depend on it. The issued record itself stays process-local.
- **Where restoration is tested.** The frozen controls of section 8 run this tool's own
  retained evolution in memory and do not exercise `restored()`. The bound
  `tests/test_i01_finite_admission.py` (`RestorationTests`) does: it commits four accepted
  steps of the bound I02 fixture column, reopens the ledger, and checks the restored clock
  and stretch against in-memory evolution. `prepare()` and `admit()` must use that clock;
  a common state, fingerprint, another evolution's history or an edited copy is refused.
  The tool also binds `tests/i02_workflow_fixtures.py` and `integration_clock.py`, used by
  that test. `tests/test_i02_persistence.py` retains wider source-binding and trusted-store
  boundary checks. The receipt binds this regression; its five controls remain distinct.
- **What restoration executes, and what is bound.** `restored()` executes the package
  modules `integration_ledger`, `integration_state`, `storage`, `_validation`, `materials`,
  `resources` and `timebase`, and `w08_inventory` with `constitutive` when stocks are
  attached; the `Ledger.open` or `Ledger.create` it relies on also executes `mesh`. These
  ten, plus `integration_clock` used by the bound restoration regression, are the tool's
  eleven `RESTORATION` sources: all are bound and all are import-checked (an
  evidence run refuses before any control if an imported module is not its bound file).
  The retained package owners it executes as well (`integration_evolution` and the
  `_integration_*` modules) were already bound and import-checked with the retained tools.

**Why the reachability guard alone was not enough.** Before this contract a state
carried its clock as a plain field, and the only clock check was
`lam_s <= 1 + (F/D) t_s/w0`. Resisted motion is slower than drag-only motion, so this
inequality has slack. A clock moved anywhere between the earliest drag-only time and
the true time passed it, and so did an envelope freshly prepared from such a state,
regaining part of a used horizon. The inequality remains as a consistency check only.
Provenance, not another inequality, now carries the clock.

**Proposition (carried limits).** Every certificate from `admit()` refers to a window
`[t_s, t_s + T]` where `t_s` is the actual elapsed time, since the absolute reference,
of the one evolution E that issued both the admitted state and the envelope's
preparing state. `lam_s`, `kappa_s` and the temperatures are E's committed values at
`t_s`, and the envelope's floors are E's values at a time `t_f <= t_s`.

*Proof.* The envelope carries a mark, so `prepare()` made it. `prepare()` recorded the
evolution E of an issued preparing state `S_f` and copied `L`, `t_f` and `kappa_f`
from it. Frozen fields cannot be reassigned, and a replaced or built envelope carries
no mark. The admitted state `S` carries a mark with `S.evolution is E`. Marks are set
only by `reference_state(E)`, whose values are E's `(1, 0, kappa0, theta0)`, and by
`evolved(E, n)`, whose values are copied from a `COMPLETE` retained run of E's own
inputs for `n` steps of E's fixed step. So `t_s` is the clock that run accumulated,
`n` times the step, and the same holds for `S_f`. Both states are therefore committed
states of the one evolution E, measured from one reference, and `t_s + T <= H`
bounds E's total elapsed time. No normal operation yields a marked state or envelope
with other values, so no used horizon can be regained. The admission checks below
then place `S` inside the floors. ∎

The mark proves where a state came from. It does not add accuracy: a certificate
remains the conditional statement of section 3 about E's continuation from `S`.

**Admission checks.**

- **Carried, never reset.** The envelope keeps the reference preparation and its
  paired support by identity, the law and drive by value (`drive.width_m` is `w0`),
  the evolution by identity, the finite-strain window, the cumulative horizon
  (`1e14 s`, frozen ceiling) and its floors `L`, `t_f`, `kappa_f`. The caller cannot
  supply a separate used budget to reset.
- **Every admitted state is checked** against its evolution and reference
  fingerprint; the retained geometry expressions `w0 lam` and `h0/lam` (bitwise);
  history at or above the floor; temperatures inside the admitted window;
  `L <= lam <= U`; `t_f <= t <= H`; and the exact reachability
  `lam <= 1 + (F/D) t/w0` as a consistency check. The window must satisfy
  `t + T <= H` and `lam + (F/D) T/w0 <= U` exactly.
- **Refused before any certificate:**
  - identity: a changed law, force, drag, reference width, preparation or support (a
    replaced copy included); a stretched preparation or stale inputs posing as the
    reference; another material;
  - provenance: an unissued state or envelope as above; a raw output; a genuine state
    of another evolution or material;
  - evolution: a run that does not complete (refused or out of time), a stale key or
    initial temperatures outside the evolution window;
  - scope: history below the floor; temperature, stretch, time or reach outside scope;
  - premises: compression or zero drive; missing plastic regularisation; transported
    pore pressure;
  - inputs: malformed numbers, cancellation or an expired deadline.

  A refusal raises, issues nothing and changes no evolution output, issued state or
  envelope.
- **Repeated admission.** A later issued state of the same evolution inside the floors
  may reuse the same envelope: its stretch, history and clock have only grown. A fresh
  envelope prepared there is at least as tight. Neither regains the used horizon. The
  same evolution run again issues a new state at the same cumulative clock, which the
  carried envelope admits.
- **Reuse.** Preparation is linear in quadrature points with exact rationals; each
  admission then needs linear float guards and a constant-size exact gate. No disk
  cache, growing log or parallel worker exists for this small calculation.
- **The old guard is unchanged.** The fixed-column 0.05 small-strain guard of the
  retained admission still refuses these windows. This is a separate finite-strain
  contract, not a relaxed old guard.

## 6. What a failure means, and what is never claimed

`NOT_CERTIFIED_BY_BOUND` means the plastic-limit envelope is too weak to guarantee
the allowance; it is not evidence of a large actual error. The accepted layered strip
is expected to be uncertified at every allowance below one. Its yield bound alone
exceeds the drive because every point is credited with full frictional strength,
while hot deep rock in fact creeps at far lower stress. A creep-aware bound would
need a proven temperature floor over the whole future window (section 9); none is
assumed here. Tolerances, laws, loads and the accepted case are not tuned to obtain
a pass. Never claimed: physical separation or rupture (D2/D6), an automatic solver
or boundary switch, the coupled thermal trajectory, the continuous depth integral,
lateral localisation or necking, compression, elasticity or inertia.

## 7. Validity

| Premise | Admitted | Enforced by |
| --- | --- | --- |
| Drive | constant `F > 0`, fixed `D` and `w0` | preparation; identity at admission |
| Stretch | `L <= lam <= 1.4` over the whole window | floor, window and exact drag-only reach |
| Time | cumulative `t + T <= 1e14 s` from the reference | exact horizon and reachability |
| Temperature | any field inside `[273, 1613] K` | window check; the bound is temperature-free |
| History | raw history at or above the floor, no healing | floor check; retained monotone evolution |
| Column | plastic branch at every point, `C0 >= 0`, `phi0 >= 0`, zero pore pressure | preparation |
| Model | represented Gauss-point strip, affine pure shear, closed | inherited finite-strain limits |
| Provenance | states issued by this tool's own run of one retained evolution, or restored by the engine from a commit of that evolution in a trusted local I02 ledger store; envelopes prepared from those states | issue mark outside constructors and `replace()`; evolution identity at admission; raw outputs refused; restoration only through `restored()`, which checks a trusted store's consistency, not who wrote it |

## 8. Controls (frozen before execution)

The layered strip uses the accepted reference order 64; the homogeneous fixture uses
order 8; both use the accepted 128-step level (`dt = 7.8125e11 s`). Each fixture is
one `Evolution`; its issued states after 32, 96 and 128 steps come from `evolved()`
runs of that step, whose prefixes are bitwise the longer run's.

| Control | Checks |
| --- | --- |
| analytic | A formula check at authored floors, with no state or clock. Order-2 rate-linear layer: `Ybar = 0` and `Abar` equal the closed form exactly at `lam = 1.25`; the retained stage there matches `v = F/(D + K/lam^2)` within `1e-8`, validating the scaling the bound assumes. From the layer's own issued reference state, `prepare()` reproduces the formula and the exact threshold is certified while its `1e-30` neighbour is not. Weakened accepted homogeneous layer: exact closed form with the represented overburden and the independent ASPECT factor transcription; the stage obeys the formula at and above the floor; more history and stretch tighten it. Layered strip at its issued reference: yield bound above the drive, uncertified at `1 - 2^-20`. The retained 0.05 guard still refuses. |
| trajectory | From the issued reference and the step-32 state, for both allowances: at each window's two committed endpoint stages and in aggregate, every force, speed, displacement, drive-work, reach, history and temperature comparison lies within the exact bounds plus `1e-9`; claimed certificate bounds hold; the layered strip is visibly uncertified; the weak belt is certified at 0.1 but not at 0.01; stretch, temperature and history all change in every window; the certified window ends beyond `ln lam = 0.05`. Intermediate stages are not observed. |
| refusal | Fourteen case mutations and every section-5 refusal, each with its expected reason. Provenance candidates: a state built from genuine values, a partial clock rollback, an envelope renewed from it, edited clocks, references, stretches, histories and temperatures, raw outputs, genuine states of another evolution or material, and edited or built envelopes. Scope refusals use genuine issued states against tighter admitted windows or earlier floors, and each candidate's premise is checked. The undamaged candidate is certified; evolution outputs are unchanged; issued states stay read-only and keep their evolution. |
| repeat | The step-32 envelope admitted again at step 96 to the horizon, and an envelope renewed there; one evolution carried; the later state inside the floors; the window cumulative; the renewed envelope at least as tight. Refused: beyond the horizon; a partial clock rollback inside the old slack; an envelope renewed from it; rebuilt, reset-clock, pre-preparation, re-referenced and relabelled-history states; another evolution's reference state lying inside every floor of the whole-horizon envelope; an earlier state below the floors. |
| reuse | Three interleaved batches of the same public admissions with a reused versus a rebuilt envelope from the same issued state; identical answers; raw seconds and saved percentage; both outcomes exercised. |

The cooperative budget is 60 s after imports (hard ceiling 120 s).

## 9. Next integration dependency

- A **restartable finite-strain evolution** that continues from an issued state,
  carrying the cumulative clock, accounts and evolution identity. The retained
  `evolve` always starts at the reference, so `evolved()` re-runs from the reference
  for every issued state, and a generator cannot yet alternate admission and
  evolution without re-running.
- The **I02 common state and transactions** must carry the evolution identity,
  cumulative clock and stretch with the material as a checkpoint that survives
  persistence and restart. The I02 ledger and `restored()` above provide one from a
  trusted local store, checked for consistency rather than authorship; this tool's
  issued records themselves remain process-local and are not serialisable evidence.
  It refuses re-referencing through its own
  objects, but it cannot recognise a column re-prepared from scratch at thinner
  layer thicknesses as the same material.
- A **creep-aware envelope** for thick hot lithosphere needs a proven lower
  temperature bound over the window: a thermal comparison result not supplied.
- **D2/D6** separation and rupture remain open; admission never authorises them.

## 10. Results

Measured results and review status are kept in the
[current evidence register](../../docs/CURRENT_EVIDENCE.md) and current-state record,
not this source-bound method specification. A receipt is captured only after the
focused tests and bounded campaign; neither this document nor completed execution
alone establishes acceptance.

## 11. Sources

**Read for this connection:**

| Source | What it justifies |
| --- | --- |
| Python [`fractions`](https://docs.python.org/3/library/fractions.html) documentation, fetched 27 September 2026 | A `Fraction` built from a float has exactly the float's value (`Fraction(1.1) = 2476979795053773/2**51`); exact rationals of represented inputs. |
| Python tutorial, [Floating-Point Arithmetic](https://docs.python.org/3/tutorial/floatingpoint.html), fetched 27 September 2026 | Python floats map to IEEE 754 binary64 on almost all platforms, 53-bit significand; errors "on the order of no more than 1 part in 2**53 per operation". It does not itself state exact rounding. |
| Goldberg (1991), *What Every Computer Scientist Should Know About Floating-Point Arithmetic*, as Appendix D of the [Sun/Oracle Numerical Computation Guide](https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html), fetched 27 September 2026 | IEEE 754 requires `+ - * /` to be exactly rounded (computed exactly, rounded to nearest even), relative error at most machine epsilon `(beta/2) beta^-p`, which is `2^-53` for binary64: the `g` factor. |
| Python 3.12 [`dataclasses`](https://docs.python.org/3.12/library/dataclasses.html) documentation, fetched 27 September 2026 | `replace()` builds the new object through `__init__`; `init=False` fields "are not copied from the source object", and naming one in `replace()` raises `ValueError`; frozen classes only emulate immutability ("It is not possible to create truly immutable Python objects"). This is the issue mark's basis and its stated limit. |
| Retained Atlas derivations: [I01_FINITE_STRAIN.md](I01_FINITE_STRAIN.md), [I01_COLUMN_ADMISSION.md](I01_COLUMN_ADMISSION.md), [I01_DECOUPLING.md](I01_DECOUPLING.md), [I01_PHYSICAL_CONTRACT.md](I01_PHYSICAL_CONTRACT.md) D2 and D6, [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) I01, and the imported tools' code | Geometry and pressure scaling, constitutive law and closures, the retained exact gate and its outward display, physical scope. |

**Reused, not re-read:** the ASPECT finite-strain and continental-extension cookbooks
and particle parameters through the finite-strain document; Duretz et al. (2021) and
the ASPECT continental-extension input through the column admission; SciPy
documentation through the decoupling and column-admission documents.

**Not consulted:** the IEEE 754 standard text itself (not openly available); its
exact-rounding requirement is cited through Goldberg. No external software was run
or installed. The inequalities are derived here from Atlas's retained law; they are
not attributed to these sources as a published rupture or admission criterion.

## 12. Commands and bindings

From `tectonics`, with the existing compatible scientific environment:

```text
python -B -m unittest discover -s tests -p test_i01_finite_admission.py -v
python -B tools/check_i01_finite_admission.py --output NEW_PATH.json
```

The exclusive-create receipt binds, before and after execution, the four new files,
the retained tools, cases and package modules listed in the tool, and the
finite-strain and column-admission receipts that the tool pins, at their accepted
SHA-256 values. The designated successors for the package-owned code are
`i01-finite-strain-r4` and `i01-column-admission-r2`; each is evidence only once
captured, reviewed and listed as current in the
[evidence register](../../docs/CURRENT_EVIDENCE.md). Before any control the tool
verifies that every source the pinned receipts recorded
still has its bytes and that each imported module resolves to its bound path.
Timings exclude imports. The reuse comparison is one small matched observation.
