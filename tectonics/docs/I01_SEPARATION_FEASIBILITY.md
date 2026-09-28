# I01: selected bond history and resolved shear-band feasibility

WORKING NON-CANON. This is an I01 constitutive choice and a bounded numerical
feasibility route. It is not I07's resolved lithosphere neck, empirical material
calibration, a mechanical handoff certificate, or permission to split a plate.
Execution status belongs in [CURRENT_STATE](../../docs/CURRENT_STATE.md).

The [case](../cases/i01_separation_feasibility_v1.json) fixes every synthetic
input and numerical limit before execution. The [tool](../tools/check_i01_separation_feasibility.py)
and [tests](../tests/test_i01_separation_feasibility.py) implement the choices
below without modifying the retained [local law](I01_SEPARATION_LAW.md).

## 1. The selected meaning and history

Separation concerns **bonded connectivity**, with point-set connectivity reported
separately. A broken frictional surface can transmit compressive and shear
traction while no longer bonding its sides. A positive bonded film remains a
connection. Cohesion completion changes neither material amount nor stored
elastic stress. The choice supplies no failure of a creeping lower-lithosphere
bridge: that bridge must remain in the connectivity assessment.

Select an irreversible `ever_broken` flag attached to material cohort identity,
independently of D2's recoverable strength history. Update it by logical OR with
an evidenced completion of the declared cohesion-loss law. A lower filtered
history, healing term, remeshing or restored friction cannot clear the flag.
No rewelding law is selected; a request to weld broken cohorts is unsupported.
This is an explicit constitutive restriction, not a claim that geological faults
can never seal or strengthen.

Transport raw plastic history and this bond record with material. Reconstruct
filtered strength history on the current geometry. Preserve distinct bonded and
broken cohorts when they share a numerical cell; never average their flags or
let a majority classifier erase a bridge. If geometry cannot resolve their
connection, the diagnostic is UNRESOLVED. `preserve_bond_cohorts` preserves these
identities; it is not a conservative remapping implementation.

The support certificate covers the entire plastic-history approach and every
raw-history contributor to a filtered value. An endpoint in range does not
certify previous increments. UNKNOWN cannot upgrade to INSIDE; a violated range
remains VIOLATED. A known break survives a later unsupported interval as a
historical fact, but that interval cannot supply an admissible mechanics or event
certificate. Thus bond identity and current predictive support are distinct.
The no-flux Helmholtz filter has nonlocal influence: an uncertified contributor
cannot be ignored merely because its weight is small.

## 2. Required material inputs, without a new default

An executable material producer must declare:

- peak and residual cohesion/friction, softening history, plastic viscosity,
  creep law and their units, provenance and coefficient support;
- residual-state semantics: `broken_surface_sliding` requires exactly zero
  residual cohesion; `weakened_intact` never removes a bond;
- temperature/effective-pressure support for cohesion loss, and the accumulated
  support record, not just support for the creep coefficients;
- a physical shear-zone width with its basis, separately from physical D2 length
  `ell`; both stay fixed under numerical refinement;
- the softening convention, transported cohort/bond records, material anchors,
  geometry and the whole interval's supported loading.

The retained ASPECT fixture does not acquire those missing semantics from this
decision. Its factor-four residual cohesion must not become a cohesionless
surface. It remains usable for its original weakening controls, not calibrated
separation. This case's round SI values and narrow support box define a synthetic
experiment only. Production inputs remain required rather than silently filled.

## 3. What is spatially resolved

The control resolves transverse coordinate `x` across a shear band of physical
width `w_s`. The strip is homogeneous along slip and strike. Its two exterior
faces are the declared anchors. Quasi-static shear equilibrium makes traction
`tau` constant across `x`; a surrounding elastic spring carries the stored
traction. There is no normal opening, normal material transport, inertia,
free surface, thermal evolution or changing pressure. This restricted geometry
allows force balance to be solved exactly, while plastic flow is nonuniform.

```text
kappa_bar - ell^2 d²(kappa_bar)/dx² = kappa,   zero normal gradient at both faces
C0(x) = C0 [1 + a cos(2 pi x/w_s)]
Y0(x) = C0(x) cos(phi) + P_eff sin(phi),  Yr = P_eff sin(phi)
Y(x) = Y0(x) - [Y0(x)-Yr] min(kappa_bar/kappa_c, 1)
p(x) = max(tau-Y(x), 0)/eta_p
kappa_dot(x) = p(x)
tau_dot = k [V - integral(p(x) + tau/eta_v) dx]
```

The fixed smooth cohesion variation puts the weak part at the centre and drives
nonuniform flow; it is not fitted to a desired failure time. Creep is optional.
Linear yield softening here is linear cohesion softening at constant friction
and pressure. It is not a substitute for independently evolving friction,
pressure or a different D2 convention.

A conservative cell-centred finite-volume Helmholtz solve reconstructs the
filtered field at each Runge–Kutta stage. No filtered history is transported or
stored as material memory. The positive-definite Neumann Helmholtz matrix is
factored once per fixed band using SciPy's banded Cholesky routine; each stage
reuses that immutable factor. Input and output finiteness checks remain in place.
Both preparation and each solve are O(N),
with O(N) active state and no growing trajectory store. Explicit RK4 advances
traction, raw history and independently evaluated work rates. The bounded
experiment requires `dt` times its declared rate bound at most 0.1, at most 256
cells and 20,000 steps, and a 60-second cooperative campaign limit after imports.

Bond loss is bracketed by consecutive accepted samples at constitutive
completion. No numerical thickness or damage threshold replaces `kappa_c`.
Within this *prescribed homogeneous strip* a broken transverse cell spans slip
and strike, so no bonded path joins the faces. Point-set connectivity remains
CONNECTED. These brackets are convergence diagnostics, not rigorous ODE error
enclosures or event certificates for a general material geometry.

## 4. Accounts and predeclared checks

Per unit band face area, independently integrate:

```text
Wdot = tau V
E = tau²/(2k)
Ddot_creep = integral(tau²/eta_v) dx
Ddot_breakdown = integral[(Y-Yr) p] dx
Ddot_friction = integral[Yr p] dx
Ddot_overstress = integral[eta_p p²] dx
W = change(E) + D_creep + D_breakdown + D_friction + D_overstress
```

The uniform-band limit is compared with the retained phase-exact solution,
including completion time, final stress/history and `G=(Y0-Yr) kappa_c w_s/2`.
For a nonuniform filtered band, the measured breakdown integral is reported;
the uniform formula is not imposed on a different field. No energy is supplied
as the residual of the balance. Heating would consume dissipation through D4's
conversion rule; stored elastic energy is not heat. This control does not solve
that thermal feedback.

The declared 32/64-cell grids supply 4/8 cells per fixed `ell`. Compare those
grids and the finer grid at `dt/2`. The existing 3% gates remain: event brackets
overlap, their time and imposed shear-displacement midpoints agree within 3%, and measured
breakdown energy agrees within 3%. The numerical energy-account allowance is
1e-6. An analytical Neumann cosine checks spatial filter accuracy and second-order
convergence; the uniform-band exact solution checks the mechanical solver.

Report physical sensitivities separately: double `ell`; halve/double `w_s`,
`kappa_c`, and `eta_p`; and vary `eta_p` in the unstable spring regime. A sensitivity
need not produce bond loss within the fixed horizon. Missing loss is reported as
such, never repaired by extending a run or changing the input. Creep-only and
weakened-intact controls retain bonds. The original positive-film counterexample
retains its bond at every ladder value and the false extrapolated limit.

The creep-only arm uses `dt/2 = 0.0025 s`: its elastic-creep rate adds
`k w_s/eta_v` to the explicit stability bound, so the original common `0.005 s`
step exceeded the predeclared `dt * rate <= 0.1` limit. This is a stability-driven
numerical correction to that arm only. Its viscosity, forcing, horizon and all
acceptance gates are unchanged; the failed first receipt is retained.

## 5. Sources actually consulted and limits

[Fei & Choo (2020)](https://arxiv.org/html/2003.04779v3), introduction, Fig. 1,
section 2.3's loading/unloading equations and irreversibility condition, support
the distinction between residual friction and bonding, and irreversible fracture
history under unloading. Their phase-field model is not implemented here and its
fracture energy is not borrowed as an Atlas constant. The cohort latch is Atlas's
explicit discrete constitutive choice, not their numerical algorithm.

[PyLith's current fault-interface documentation](https://pylith.readthedocs.io/en/stable/user/physics/faults/),
conventions and implementation sections, describes prescribed interfaces with
relative slip and zero-thickness cohesive cells. It supports retaining contact
while distinguishing material bonds. It neither chooses a new fault path nor
validates this band's breakup. The documentation warns that spontaneous rupture
is unavailable in v3.0+; no PyLith run is claimed.

The retained [law's source comparison](I01_SEPARATION_LAW.md#7-sources) supplies
the prior Lavier cohesion-softening and physical-width rationale; those papers
were not reread for this addition. The fixed-length Helmholtz/history convention
comes from Atlas's D2 contract. The tridiagonal spatial discretisation and the
uniform-limit derivation above are inspectable mathematical verification routes,
not digitised published lithosphere outcomes.

The [SciPy Cholesky documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cholesky_banded.html)
and [factor-reuse solve](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.cho_solve_banded.html)
were consulted for the fixed-operator optimisation. Regression checks compare it
with the previous general banded solve as well as the analytical controls above.
Receipt schema v2 names the imposed quantity `shear_displacement_bracket_m`;
the old `opening_bracket_m` label was misleading because no normal opening is
solved here. Its values and the convergence tolerance are unchanged.

## 6. I01 closure and later acceptance are different

This supplies the missing explicit bond-history/input choice and a resolved
constitutive feasibility experiment. If its declared tests pass, MC-01 may be
recorded as **selected with bounded resolved feasibility** within I01. There is
no claim that all lithosphere can fracture under that law, or that the retained
mixed column has acquired the required physical inputs.

I07 still needs the full free-surface neck, thermal and mixed-material evolution,
basal-depth sensitivity and physical ranges required by the original section 9.
I05 must implement conservative transport of the selected records and any
separately admitted reclassification. I03/I07 must cover along-strike/exterior
paths. I02 must supply the whole-window replacement tolerance, accounts and
single commit. The resolved comparison, sensitivities and 3% tolerances in
[I01_SEPARATION_LAW section 9](I01_SEPARATION_LAW.md#9-the-exact-next-resolved-comparison-predeclared-not-implemented)
remain applicable to that later acceptance; this smaller experiment does not
claim to have run it or weaken it. Genuine rewelding remains outside this law.

Run from the repository root in the existing scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_separation_feasibility.py -v
python -B tectonics/tools/check_i01_separation_feasibility.py --output NEW_PATH.json
```

The writer reserves a new output exclusively before calculating, refuses an
existing output before the campaign starts, and leaves any campaign exception as
an explicit failed record, with source bindings and elapsed time when known.
It binds its sources before and after execution and
marks physical acceptance and event authorisation false. Evidence registration,
current-status and reader-guide integration remain with the integrating owner.
