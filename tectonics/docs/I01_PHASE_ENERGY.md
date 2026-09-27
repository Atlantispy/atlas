# I01 composition-aware phase energy

WORKING NON-CANON. A bounded thermodynamically consistent ideal-mixture control,
not a calibrated mantle model or an automatic replacement for Katz/W08.

## What happens, in generation order

1. Declare the material ingredients, their phase properties, pressure, shared
   energy reference and supported temperature range.
2. Calculate how those ingredients divide between solid and liquid at a given
   temperature. The same physical law calculates their heat content.
3. When energy is supplied instead of temperature, solve for temperature and
   phase amounts together. At a pure melting point, extra energy melts more
   material while temperature stays fixed.
4. Remove a prescribed share of existing liquid, including its actual composition
   and energy. Recalculate the residue from what remains, not the original rock.
5. A receiver using this same law can cool and crystallise the separated material;
   the removed heat is an explicit credit to its surroundings.

This closes the phase/composition/energy accounting prerequisite. It does not
choose how much melt escapes, move it through rock or emit a W08 payload under
W08's different common-melting-temperature law. The previous
[partition](I01_PHASE_PARTITION.md), [Katz parcel](I01_MELTING.md) and
[W08 delivery](I01_DELIVERY.md) implementations and receipts remain unchanged.

## One law, rather than independently chosen melt and heat formulas

For component i, L is fusion enthalpy at reference pressure P0, Tm its melting
temperature there, and vs/vl are constant phase-specific volumes. All components
share positive heat capacity cp and mixing constant R: this explicitly assumes
equal effective molar masses. Heat of mixing is zero. Each component may have
a shared solid/liquid energy offset e. At absolute temperature T:

```text
hs_i = cp (T-T0) + e_i + vs_i (P-P0)
hl_i = hs_i + D_i,                  D_i = L_i + (vl_i-vs_i)(P-P0)
ss_i = cp ln(T/T0)
sl_i = ss_i + L_i/Tm_i
g_phase_i = h_phase_i - T s_phase_i
K_i = csolid_i / cliquid_i
    = exp((D_i/T - L_i/Tm_i)/R)
```

Each phase's mixture entropy also includes `-R sum(c_i ln(c_i))`. Chemical
potential equality then gives the displayed K. The retained partition solver
supplies finite component masses in each phase. Summing those masses times the
corresponding h, s and volume gives bulk H, S and V. Ideal mixing affects S and
chemical equilibrium, but does not add a separate heat term.

This is an explicitly derived ideal-solution law, not the empirical melting-point
curves or independent curvature coefficients of a mantle calibration. Positive
fusion enthalpy is checked throughout the declared pressure interval. The fixture
properties establish independent analytical answers, not observed mantle values.

The pressure terms are physical. At equilibrium and fixed bulk composition,
`dH = T dS + V dP` and `U = H-PV`. An adiabat would require `dH=V dP`, not constant
H. This slice does not integrate pressure paths. Constant component volumes also
mean zero single-phase thermal expansion; it must not replace the thermal
expansion in the existing Katz control. Changing P0 alone changes the material law.
Changing the common energy datum or component offsets consistently does not change
the phase split, but the offsets must travel with extracted material.

## Invert energy accurately and efficiently

At fixed pressure, write `d_i=f+(1-f)K_i` for liquid mass fraction f and bulk
component fraction b. The existing mass-partition residual is
`r=sum(b_i(1-K_i)/d_i)`. Its exact derivatives give

```text
K_i,T = -K_i D_i/(R T^2)
r_f = -sum(b_i (1-K_i)^2/d_i^2)
r_T = -sum(b_i K_i,T/d_i^2)
f_T = -r_T/r_f
liquid_mass_i,T = mass_i [K_i f_T-f(1-f)K_i,T]/d_i^2
H_T = M cp + sum(D_i liquid_mass_i,T) >= M cp > 0.
```

The monotonicity supports a bracketed Newton solve with an analytical slope and
bisection fallback when Newton leaves the bracket or residual reduction stalls.
An improving step near a bracket edge is retained, avoiding unnecessary bisection.
The minimum slope converts an energy residual into a
temperature-error bound. The stopping account includes propagated partition
tolerance and floating-point summation allowances; these are numerical safeguards,
not a formal interval-arithmetic proof. Unsupported or unresolved states refuse
instead of clipping fractions or accepting a small residual alone.

Pure material, or occupied components sharing exactly the same melting temperature
at the requested pressure, has a latent-energy interval at one temperature. That
interval is solved directly using H; temperature alone cannot choose its melt
fraction. Nearly coincident melting points are not silently merged.

Models and returned states are immutable. Only the current bracket/state is held;
there is no growing iteration history, disk cache or worker overhead. The bounds
are 64 components and 64 outer iterations, with the retained partition's own
96-iteration bound. Cancellation and deadlines propagate to both solves. Extraction
reconstructs supplied state accounts before trusting them. A matched benchmark
compares Newton with bisection using the same model, input and error allowance.

## What the checks establish

An independent binary example chooses K=(1/2,2) at 1500 K, cp=1000 J/kg/K,
T0=1000 K and L=(300,600) kJ/kg. With component masses (4000,6000) kg, the lever
rule gives 2000 kg liquid and H=5.8 GJ. Removing half the liquid transfers
1000 kg and 0.9 GJ, leaving 9000 kg and 4.9 GJ. Solving the remaining composition
and energy recovers 1500 K and 1000 kg liquid. Cooling the removed material to
1000 K fully solidifies it and releases 0.9 GJ; source, solid and surroundings
recover the original energy.

Focused checks also cover signed energy references, component-wise datum shifts,
pure/congruent latent plateaux, complete and repeated extraction, empty states,
permutation/scaling, chemical potentials, immutable/forged states and refusals.
Independent finite differences check H_T, `dH=T dS` at fixed P and
`H_P=V-T V_T`. Equal solid/liquid volumes independently require pressure-invariant
phase fractions while enthalpy changes by V times the pressure increment.

Run from the repository root:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_phase_energy.py -v
python -B tectonics/tools/check_i01_phase_energy.py --output NEW_PATH.json
```

The exclusive-create campaign binds this document, the new tool/test/case and
the unchanged partition helper before and after execution. It records analytical
account residuals and three interleaved 40-call timing batches. Tests of the
thermodynamic identities are in the focused suite; the campaign records the
binary extraction/cooling case and timing, not a mantle simulation. Runtime
versions are observations, not sealed native restart identities. Results do not
establish production-world speed or geological calibration.

## Research and software checked

- [Keller & Katz (2016), section 2.1.1 and Appendix A.2.2](https://eprints.gla.ac.uk/195948/1/195948.pdf):
  phase/component constraints and the distinction between phase enthalpy, reaction
  and energy transport. Their empirical calibration is not adopted here.
- [R_DMC equilibrium implementation](https://github.com/richard-katz/R_DMC/blob/master/src/R_DMC_Equilibrium.m):
  partition residual, temperature-dependent coefficients and melting-point
  construction inspected. Its temperature-dependent latent coefficient is not
  copied into an unrelated absolute-energy formula. No code was vendored or run.
- [ASPECT melt-transport methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html):
  phase inventory, reaction and transport remain distinct; this control introduces
  no Darcy or compaction shortcut. ASPECT was not installed or executed.

The free-energy law and enthalpy derivative above were independently derived and
cross-checked before implementation. Source/reference checks are not new claims
of independent software benchmark agreement.

## Next connection

Carry this law's identity, pressure and component/energy references into a compatible
receiver and material-history adapter. A receiver may not reinterpret these joules
through the old common-Tm inversion. Geological material parameters, non-ideal
equilibrium where required, physical extraction/focusing, moving pressure/thermal
history and global coupling remain distinct work. I01 remains open.
