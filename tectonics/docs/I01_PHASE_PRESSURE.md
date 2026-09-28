# I01 reversible pressure changes with composition and energy

WORKING NON-CANON, 27 September 2026. Bounded ideal-mixture connection, not a
calibrated mantle law or native ascent/emplacement. This method is frozen before
the source-bound campaign; measured results belong in the current-evidence record.

## Why this connection exists

The [phase-energy model](I01_PHASE_ENERGY.md) tells us which ingredients are solid
or liquid at a given pressure and heat content. Moving that material to another
pressure changes its melting conditions and involves mechanical work. Keeping
its enthalpy fixed while changing pressure is generally **not** an adiabat.

For a closed, reversible, quasistatic move with no heat supplied, conserve the
component masses and total entropy S. At each requested pressure solve the same
material's equilibrium again. Melting can consume sensible heat; compression can
freeze melt and release it. This is not a rule that clips freezing or invents
extra material. The method does not yet choose an ascent rate or an extraction
fraction.

## Thermodynamic contract and work signs

The retained law gives H, S and V from one ideal-mixture free-energy model.
For fixed total component inventories:

    dH = T dS + V dP
    U = H - P V
    dU = T dS - P dV

Thus on this reversible path, enthalpy changes by the integral of V dP, while
external compression work **into** the material is the integral of -P dV. They
are different quantities. `Movement` exposes `enthalpy_pressure_change_j` and
`compression_work_j` separately. The receiver's existing `boundary_work_j` is
work **out** of that receiver; connecting the two uses opposite signs.

No heat exchange, kinetic/gravitational energy, extraction, replenishment or
irreversible dissipation occurs inside a pressure move. These require separately
accounted processes. Component ordering, material identity, energy datum and
parameter support are retained, not translated to Katz/W08 parameters.

## Efficient equilibrium at entropy and pressure

`flash_s` in [the implementation](../tools/check_i01_phase_pressure.py) inverts
S(T,P,masses) at the target P. There is no timestep sequence to store or replay.
At smooth equilibrium, S_T = H_T/T >= M cp/Tmax. Bracketed Newton uses that
derivative; non-progressing or out-of-bracket proposals use bisection. At most
64 outer iterations are permitted; the retained partition has its own 96-step
bound and 64-component limit. Cancellation and deadlines apply throughout.

The error rule is |computed S - target S| + numerical entropy uncertainty <=
(M cp/Tmax) times 1e-7 K. This lower slope bounds temperature error on smooth
branches. The comparison solver uses the same rule and bracket, but bisection
only; it does not use looser physical or numerical criteria.

Pure or exactly congruent materials have an entropy interval at one coexistence
temperature. Solve their liquid fraction directly within that interval, or
invert logarithmic single-phase entropy outside it. Do not merge almost equal
melting temperatures. Congruence at one pressure need not persist at another.

### Numerical uncertainty

For phase fraction f, partition K_i and bulk component mass m_i, define
d_i=f+(1-f)K_i, l_i=m_i f/d_i, A=sum(m_i/d_i), B=sum(m_i K_i/d_i).
Differentiating the actual phase-mixing entropy at fixed T/P gives:

    dS/df = sum_i [m_i K_i/d_i^2 * (D_i/T + R ln(A/B))]
    D_i = L_i + (v_liquid_i - v_solid_i) (P - P0)

For occupied components, 1/Kmax <= A/B <= 1/Kmin. Bound the derivative over
f +/- 4e-12 using the smallest positive d_i there and max |ln K_i|. This avoids
singular logarithms at a disappearing phase. The 4e-12 retains the partition's
1e-12 fraction tolerance plus its phase-normalisation discrepancy and rounding
margin. It is not a bound for arbitrary independent mass perturbations.

Add a 64-epsilon allowance based on absolute entropy terms. Analytically solved
coexistence needs no partition-root allowance. Unresolved conditioning refuses
the result. These are conservative floating-point safeguards, not a directed-
rounding interval certificate. Source and endpoint uncertainty are both disclosed
in the pressure-move receipt. Work uncertainty additionally includes enthalpy
and PV cancellation, and Tmax times entropy mismatch/uncertainty. Refuse when
that exceeds 4 M cp times 1e-7 K, including unusably large energy-reference
offsets; do not report unresolved work as an exact zero.

`adiabatic_move` first reconstructs the source's accounts through the existing
zero-extraction validation, then returns immutable new values only after checks.
The same-pressure path reuses the validated state with exactly zero work. Empty
inventory remains empty. Negative reference-relative entropy is allowed.
When sampling several pressures on one path, always use the **original source**
for every move. Repeatedly resetting conserved entropy to approximate endpoints
would otherwise accumulate drift. A heat/extraction/mixing event establishes a
new physical source for the next reversible segment.

## How we know it is right

The [fixed case](../cases/i01_phase_pressure_v1.json) declares bounds and comparison
tolerances before execution. [Focused tests](../tests/test_i01_phase_pressure.py)
cover independent pure melting/freezing, full phase crossings, congruent mixtures,
binary inversion/reversal, vanishing phases, signed references, scaling, component
permutation, unchanged inputs and explicit refusal/cancellation cases.
The partition provider now calculates each component's smaller phase inventory
directly, instead of losing the residual solid by subtraction of near-equal
numbers. Tests recover both entropy and enthalpy at 1e-6 K inside the binary
solidus and liquidus with the same 1e-7 K temperature criterion. The former false
chemical-equilibrium refusal, including intermediate inversion states, is fixed
without loosening any tolerance. Ill-conditioned roots and inventory underflow
remain refusals; see the [partition method](I01_PHASE_PARTITION.md) for the
arithmetic and independently specified endpoint controls.

For a pure material let lambda=L/Tm0, a=(vl-vs)/lambda and Tm(P)=Tm0+a(P-P0).
On a mixed segment starting at P1,T1,f1:

    f2 = f1 - (cp/lambda) ln(T2/T1)
    integral V dP = V1(P2-P1) - M cp [T2 ln(T2/T1)-T2+T1]
    -integral P dV = M cp [(T2-T1)-(Tm0-a P0) ln(T2/T1)]

These are independent integrals, not checks that merely redefine work as an
energy difference. A 10,000 kg analytical parcel starts half molten at 1 GPa and
1720 K. At zero pressure its expected T is 1600 K, molten fraction
0.7892826463185045, enthalpy change -3,192,869,414.725983 J and work into material
-42,869,414.725982 J. The large difference detects confusing the two accounts.

For the binary fixture, composite Simpson integration of V(P) at 16, 32 and 64
panels independently checks endpoint enthalpy change; errors must decrease and
the final error must be <=2 J. This diagnostic is not used in production inversion.
Equal phase volumes give unchanged temperature/phase fractions and zero external
work. Single-phase paths also retain T because this particular material law has
zero thermal expansion and compressibility; do not represent this as a realistic
single-phase mantle adiabat. A fixed-H counterexample must change S.

The new pressure-to-[receiver](I01_MAGMA_RECEIVER.md) test checks total internal
energy against the sum of both work accounts. A pressure-moved parcel containing
solid is refused by the liquid-only receiver; explicit extraction retains the
residue instead of silently dropping it. This is an in-memory connection, not
an issued native transport transaction or an extraction-rate law.

The bounded campaign times three interleaved batches of 40 matched inversions
using Newton versus bisection. It records raw times, iterations and temperature
parity. No cached answers, pressure history, parallel overhead or changed accuracy
are introduced. The 30-second deadline excludes interpreter/import startup.

## Papers and software checked

- [Keller and Katz (2016), section 2.2.1, equations 17-19 and 2.2.2](https://eprints.gla.ac.uk/195948/1/195948.pdf):
  rechecked the distinction between latent heat, adiabatic pressure work and
  dissipation. Their flow/thermal-expansion model is not copied into this
  constant-volume law. The entropy inversion above follows the retained free
  energy, rather than claiming that paper directly implements this solver.
- [Cantera 3.2 thermodynamic properties and multiphase equilibrium](https://cantera.org/stable/python/thermo.html):
  inspected entropy/pressure state pairs and the SP equilibrium interface. This
  supports using conserved entropy at prescribed pressure, not mantle calibration
  or an external numerical result for Atlas.
- [pyMelt 2.0 mantle source](https://pymelt.readthedocs.io/en/latest/_modules/pyMelt/mantle_class.html):
  inspected `adiabaticGradient`, `dFdP`, `dTdP` and `adiabaticMelt`, including its
  coupled Runge-Kutta stepping and optional freezing suppression. Atlas retains
  reversible freezing here and uses endpoint inversion for its different explicit
  mixture law. Neither package was installed or benchmarked in this task.

Calibrated, mutually compatible material properties, pressure/velocity selection,
extraction/focusing, native thermal/geometry coupling and persisted transfers
remain integration work. This connection removes one specific thermodynamic gap
without claiming those other pieces or changing the retained material laws.
