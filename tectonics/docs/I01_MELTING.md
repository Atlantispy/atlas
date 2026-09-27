# I01 dry decompression melt production

Status: **WORKING NON-CANON; bounded parcel controls, not whole-I01 acceptance.**

## What this does

When hot mantle rises, pressure falls. Its solidus falls faster than its
temperature, so some rock melts. Melting also consumes heat and therefore limits
how much more melt forms. This calculation follows those two effects together,
instead of estimating an independent melt fraction at each depth or supplying
the delivery prototype with an invented amount of melt.

The caller supplies a dry parcel's mass, starting pressure/temperature, ending
pressure and initial clinopyroxene abundance. The result contains the final
temperature, remaining solid, retained liquid and **net newly produced melt**.
There is no supplied clock, so this is a mass increment, not a mass flux. All
melt stays with the parcel; the composition is the parameterisation's fixed bulk
composition. Changing composition through extraction is a different calculation.

## Scientific method and evidence

The implemented dry fractions follow equations 2–9 and Table 2 of
[Katz, Spiegelman & Langmuir (2003)](https://doi.org/10.1029/2002GC000433).
Below the solidus there is no liquid. Above it, a power law estimates the mass
fraction melted. Once clinopyroxene is exhausted, a second branch supplies the
different productivity. Both sides have the same fraction at the transition,
but their derivatives need not match. Pressures in those empirical polynomials
are in GPa and temperatures in degrees Celsius; the implementation's public
temperature is kelvin and its energy coefficients are SI.

The thermal path is derived from the paper's equation 23, using the chain rule:

`dT/dP = [A(F) - ΔS (∂F/∂P)T] / [cp/T + ΔS (∂F/∂T)P]`,

where `A(F)=(1-F) αsolid/ρsolid + F αliquid/ρliquid`. The code multiplies `A` by
10^9 when integrating pressure in GPa. Positive `ΔS=300 J/kg/K` means fusion
consumes heat. It does not copy the sign convention of another program's API.
This also avoids relying on the apparently duplicated liquid-expansion term in
the displayed equation 20. Equation 23 supplies the unambiguous phase-weighted
form. Defaults are cp=1000 J/kg/K, expansion coefficients 40/68×10^-6 /K and
densities 3300/2900 kg/m³ for solid/liquid. Initial modal cpx=0.15 is declared.

Existing software checked, not executed or vendored:

- [ASPECT's Katz reaction implementation](https://github.com/geodynamics/aspect/blob/main/source/material_model/reaction_model/katz2003_mantle_melting.cc): branch construction, cpx exhaustion and analytic derivative structure.
- [pyMelt's Katz implementation](https://pymelt.readthedocs.io/en/latest/_modules/pyMelt/lithologies/katz.html): an independent software comparison of the equilibrium branches. Derivatives here were independently differentiated from the equations and tested, not blindly copied.
- [SciPy RK45](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.RK45.html) and [DOP853](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.DOP853.html): adaptive integration with different orders for production and the tighter numerical control.

## What the accounting proves

The thermal equation is `cp dT = T A(F)dP - T ΔS dF`. The two right-hand terms
are integrated alongside temperature. Their sum must reproduce `cp ΔT`.
The first term is **thermal adiabatic cooling**, not a complete pressure–volume
work budget. A second check integrates `cp dT/T + ΔS dF - A(F)dP` along the path.
With phase-dependent `A`, this approximate differential need not define a
globally integrable absolute entropy state function. Neither check is described
as conserved full enthalpy or an exact entropy law. They check bookkeeping;
independent exact and tighter numerical controls check solution accuracy.

Solid plus retained melt equals the original parcel mass. A restarted segment
uses its supplied current temperature/pressure and recalculates the equilibrium
fraction; its heat/path accounts and net production refer to that segment only.
Segment accounts must be added for a whole-path total. No hidden cache restores
an earlier state.

## Bounds and efficient execution

This prototype admits dry, decompressing paths within 0–3.5 GPa, modal cpx
0.01–0.2 and at most 40% melt. These are declared engineering scope limits,
not claims that experiments validate every combination of inputs. Supplied
coefficients must be positive/finite. There is no water, fractional extraction,
depletion chemistry, Darcy flow, compaction or transport to the surface here.

Analytic derivatives avoid repeatedly evaluating neighbouring phase states.
Adaptive RK45 resolves solidus onset and the cpx derivative change. It has at
most 256 accepted steps and 4096 right-hand-side evaluations, including rejected
trials. Exhausting either budget, leaving support, cancellation or failed local
error/accounting checks refuses a result. Accuracy is never rescued by clipping
fractions or lifting the budget. Only the current four-state vector is retained;
no full iteration or stage histories accumulate. An immutable model can be
reused safely between independent parcels. Millisecond-scale single-parcel
controls do not justify worker/process or disk-cache overhead.

## How it is checked

Focused tests cover the known branch formulas and units, continuity at cpx
exhaustion, independent central differences for both analytic derivatives,
the exact unmelted exponential adiabat, and an independent endpoint root when
the two phases have equal expansion/density. That special root is **not** used
for unequal phase coefficients. They also cover melt cooling, mass/heat/path
accounts, restart, immutable reuse, invalid input, cancellation and both budgets.

The authored two-path campaign crosses melt onset and cpx exhaustion. A tighter
DOP853 control must agree within **0.002 K and 2×10^-6 mass fraction**. The same
exact dry and constant-expansion controls are recorded. The case file fixes the
criteria before the run. No comparison to an observed mantle column or full
ASPECT/pyMelt simulation is claimed.

A five-repetition local benchmark compares analytic derivatives against central
numerical differentiation of the **same** equilibrium law, with the same RK45
settings. It reports all timings, median seconds, absolute/percentage savings
and temperature parity. This is not a comparison with an old generator stage
and does not establish any whole-generator speedup. The diagnostic numerical
derivatives are not a selectable public physical model.

## Integration boundary

The existing delivery prototype has an isobaric, common-melting-temperature
phase/enthalpy law. Katz batch fractions cannot be fed into that law as though
their reference states, fusion energy and phase compositions were interchangeable.
A compatible extraction/transport handoff remains a distinct I01 decision.
This control produces a defensible parcel melt amount; it does not yet deliver
that melt, grow crust, diagnose breakup or alter a generated world.

Run `python -B tectonics/tools/check_i01_melting.py --output <new-receipt.json>`
from the repository root. The exclusive-create receipt binds this document,
the tool, focused test and case bytes. It records the observed runtime rather
than pretending to be a sealed native execution identity. Existing evidence is
never overwritten or rebound by this tool.
