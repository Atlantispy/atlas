# I01: a conditional error bound for omitted lateral conduction

WORKING NON-CANON. This selects a bounded thermal criterion for MC-06. It does
not certify a coupled neck, implement I05/I06 transport or permit separation.
The earlier thermal and breakup kernels and their receipts remain unchanged.

## What the criterion establishes

Ignoring conduction between neighbouring columns changes their temperatures.
The relevant quantity is the omitted heat flow divided by each cell's heat
capacity, accumulated over the declared interval. A small Fourier number alone
is not a temperature-error certificate: the temperature contrast also matters.

This tool bounds the difference between two exact solutions of the **same
declared semi-discrete heat model**, one with and one without its lateral
contacts. The contract is conditional on supplied whole-window temperature
difference bounds. Neither endpoint samples nor a converged numerical solution
establishes those bounds. A failure means omission is not certified, not that
the actual error necessarily exceeds the allowance.

## Model, units and valid assumptions

Cells have positive heat capacities `C_i` in J/K. An undirected contact has
positive conductivity `k` in W/(m K), area `A` in m^2 and centre distance `d` in m:
`G_ij = G_ji = k A/d` in W/K. Each pair is supplied once. The owner supplies a
valid orthogonal contact geometry with no missing lateral contacts; parsing a
declaration does not verify that physical geometry. For an interface between
different materials, the supplied equivalent conductivity must represent the
series thermal resistance, not an arbitrary arithmetic material average.

The accepted contract has fixed geometry, temperature-independent prescribed
properties, closed lateral boundaries and identical prescribed heat sources and
vertical boundary conditions in both models. The retained vertical thermal
operator must have nonnegative off-diagonal entries and nonpositive row sums.
Usual passive conduction with prescribed temperature, insulated or passive
Robin boundaries meets this condition after the common boundary forcing is
separated. That property is an explicit premise; this tool does not certify a
foreign vertical operator. No coefficient, geometry or heat-source response to
changed temperature, mechanical resistance or motion is admitted.

Unequally stretched columns can have different vertical supports. Pairing their
array indices does not define a valid lateral contact map. Moving geometry,
remapping, inflow, external lateral heat exchange, latent heat, changing material
properties and mechanical feedback require a different or extended contract.
Passing this criterion establishes no continuum spatial error, time-integrator
error, rheological error, force error or event-timing error.

## Derivation and exact admission

Write `L_z` for the retained vertical operator and `L_x` for lateral conduction,
with `(L_x T)_i = sum_j G_ij (T_j - T_i)/C_i`. Both models use the same prescribed
forcing `b(t)` and initial state:

```text
T'     = (L_z + L_x) T + b(t)       full thermal model
Tbar'  = L_z Tbar + b(t)            column-only thermal model
e'     = (L_z + L_x) e + L_x Tbar   e = T - Tbar
```

At a positive componentwise maximum of `e`, the operator contribution cannot
increase that maximum: off-diagonal entries are nonnegative and row sums are
nonpositive. Apply the same argument to `-e`. Equivalently, the full homogeneous
propagator contracts the maximum norm. Variation of constants then gives

```text
||e(t)||_infinity <= ||e(0)||_infinity + integral_0^t ||L_x Tbar(s)||_infinity ds.
```

For each contact the caller declares a whole-window bound
`|Tbar_j(s)-Tbar_i(s)| <= Delta_ij`. Triangle inequality yields

```text
r = max_i sum_j G_ij Delta_ij / C_i                 K/s
B = initial_error_bound + sum_windows duration * r  K
admit exactly when B <= temperature_allowance       K
```

The bounds concern the column-only trajectory throughout the window, including
its start; samples may contradict a declaration but cannot prove it. Each
declaration carries a nonempty basis. Its truth remains a caller obligation.
The analytical control provides that basis because its reduced cells remain
constant. Missing, unknown or sample-only envelopes refuse admission.

A declared face-gradient bound `g` in K/m can supply `Delta <= g d`. This is a
bound on the represented inter-cell difference. It does not turn a continuum
gradient estimate into a bound on continuum flux divergence. The contact length,
time, conductivity, area, heat capacity and contrast all remain explicit.

All gate operations use `Fraction` on the supplied finite numbers as represented;
there is no solver tolerance or floating exponential in admission. Displayed
upper bounds round outward. Equality passes. For consecutive windows the errors
add; a continuation must carry the previous error bound through
`initial_error_bound_k` rather than reset it. Different prescribed sources are
permitted across cells but must be identical between the full/reduced models.

## API and limits

`Network(capacities_j_k, contacts, assumptions=...)` prepares immutable sparse
contacts. `admission(network, windows, temperature_allowance_k=...,
initial_error_bound_k=0)` returns the conditional decision, the exact rational
bound, its outward-rounded display and per-window increments.

The declared assumptions must match the supported contract exactly. Negative,
non-finite or zero capacities/conductances/areas/distances, invalid endpoints,
duplicate contacts, mismatched envelopes and excessive resource/input bounds
are refused. Temperature-difference/error allowances may be zero. Fixed bounds
are 256 cells, 1,024 contacts, 64 windows and 4,096-bit input rationals. Preparation
and each window cost O(cells + contacts), with no dense matrix or solver and no
background work, new cache or installed dependency. Exact arithmetic cost also
depends on the represented numeric precision.

Every result keeps `coupled_neck_certified`, `physical_separation_authorised` and
`continuum_error_certified` false. A later I05/I06 owner must supply valid contacts,
whole-window bounds, numerical-error treatment and a coupled feedback argument
before applying an omission decision to an evolving neck.

## Frozen controls and verification

The case uses two insulated cells of unequal capacity, one lateral contact and
no heat source. The reduced temperatures are constant, proving the declared
contrast bound without temporal sampling. For initial difference `Delta0`,

```text
Delta(t) = Delta0 exp[-G(1/C1 + 1/C2)t]
T1(t)-T1(0) = -Delta0 C2/(C1+C2) * (1-exp[-G(1/C1+1/C2)t])
T2(t)-T2(0) =  Delta0 C1/(C1+C2) * (1-exp[-G(1/C1+1/C2)t])
```

The analytical solution is an independent diagnostic; the derived inequality
certifies admission. The control checks its error against the exact bound, heat
conservation, permissive/strict allowances, uniform temperatures, no contacts,
cumulative budgets and sample-only/unknown refusals. Focused tests also cover
exact threshold neighbours, time/contrast/conductivity/distance scaling, restart
carry, invalid inputs and immutable preparation. A three-cell SciPy matrix
exponential is a tiny independent test oracle; runtime admission uses no matrix.
Endpoint samples of a prescribed interior contrast pulse illustrate
why a finite-window declaration cannot be replaced by those samples.

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_lateral_heat.py -v
python -B tectonics/tools/check_i01_lateral_heat.py --output NEW_PATH.json
```

The command writes only a new exclusive receipt and binds these four new files
before and after execution. Failures are retained. No benchmark or broad
simulation is required. Execution results belong in the new receipt and current
owner record, not edits to this source-bound method after the run.

## Sources checked

- [NIST FiPy, Finite Volume Method and discretisation](https://pages.nist.gov/fipy/en/stable/numerical/discret.html):
  transient capacity, conservative face flux, `G = k A/d`, and the orthogonality
  restriction of the two-point approximation. No FiPy code was copied or run.
- [Droniou (2014), Finite volume schemes for diffusion equations](https://arxiv.org/html/1407.1567v1),
  sections 1.3 and 2: monotonicity, nonnegative inverse/M-matrix conditions and
  orthogonal two-point flux geometry. These support the discrete maximum-principle
  assumptions; the transient residual inequality above is derived here and is
  not attributed to that paper as an Atlas or tectonic error theorem.

The scope is the MC-06 criterion requested by the breakup closure section 8.
An accepted thermal bound alone cannot bound coupled rheology or separation.
