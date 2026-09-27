# I01: nonlinear belt-to-boundary motion admission

27 September 2026. WORKING NON-CANON. A bounded extension of the
[reviewed D6 specification](I01_TRANSITIONS.md#3-continental-separation-atlasrift-decoupling-handoffv1).
Earlier source-bound files and evidence are unchanged. This is one numerical
prerequisite for a handoff, not a physical rupture law or an implemented world.

## What this fixes

A flat force-versus-speed curve can still exert a large force. Therefore looking
only at its slope can incorrectly decide that a belt no longer matters. Instead,
ask whether removing the belt would alter the actual calculated motion by more
than the declared allowance. Check the whole proposed interval, not just today:
a belt that strengthens tomorrow can invalidate a harmless-looking switch now.

## Supported law and derivation

For fixed positive driving force F and far-field drag D, use the authored scalar
resistance family below. The direction is fixed and the response quasi-static:

```text
F = D v + Y + a v^(1/n),  v > 0
v = 0 if F <= Y                 static yield complementarity
v0 = F/D                       proposed belt-free speed
F, Y [N/m]; D [Pa s]; a [(N/m)/(m/s)^(1/n)]
```

Y,a are nonnegative integrated coefficients, not automatically depth-integrated
outputs of the existing D2 solver. Integer stress exponents n=1..8 are supported;
this deliberately excludes arbitrary/noninteger exponents rather than rounding
them into a different law. Resistance is strictly increasing because D>0, even
though its slope may diverge at zero. There is a unique positive equilibrium
when F>Y; otherwise the static state is retained.

Let x=v/v0, y=Y/F and K=a^n v0/F^n. For any positive target x, the true speed is
at least x*v0 exactly when both conditions hold:

```text
r = 1 - x - y >= 0
K x <= r^n
```

This follows by isolating the nonnegative nth root before raising to n; the first
condition is essential (an even power must not admit a negative remaining force).
Evaluate at x=1-epsilon. It checks the actual nonlinear equilibrium error relative
to v0 without repeatedly solving the equilibrium. For n=1,Y=0 it reduces to
Pi/(1+Pi)<=epsilon, recovering D6's valid linear result. For a yield plateau it
retains the offset which the derivative-only criterion missed.

Python Fraction performs this comparison exactly for the finite numeric inputs
as represented, including binary floats. There is no rounded fractional power,
tolerance padding, or claim that a converged floating root brackets the true one.
Input precision and exponent limits bound the exact arithmetic. Diagnostic
bisection uses the same one-sided exact comparisons and returns a rational
enclosing interval. Its float display is not used for admission.

## Finite-window contract, quantities and refusals

A caller must supply Ymax and amax valid throughout duration T, for the fully
coupled trajectory, with the same F,D,n and direction. The bounds must include
the current state. The weakest guaranteed speed is the equilibrium under those
maxima; the actual speed lies between it and v0. Consequently a passed tolerance
epsilon bounds speed change by epsilon*v0, displacement by T*epsilon*v0, and
driving-force work by F*T*epsilon*v0. Initial positions must match.

The gate uses the stricter of the supplied relative velocity allowance and
displacement_limit/(T*v0). Displayed upper bounds are rounded outward. A missing
envelope refuses even if the current snapshot passes. A yield pulse between two
zero-strength endpoint samples demonstrates why endpoints cannot establish it.
The envelope is an explicit model premise, not a certificate manufactured from
those samples. Changing force/drag/exponent, inertia, reversing directions,
elastic memory or velocity-weakening laws require a different derivation.

At equilibrium Fv=Dv^2+Yv+a*v^(1+1/n). The work bound concerns this supplied
driving force only: it is not a full heat, stored-energy or material-transfer
balance. `generated_separation_authorised` remains false even on numerical
admission. Physical weakening/rupture, compatible geometry, retained cohorts and
thermal history still need their own accepted producers and transfer checks.
This work neither depends on nor edits Claude's thermal/history prototype.

## Checks and efficiency

The predeclared case covers linear drag, a yield plateau, combined yield/rate
resistance, the quadratic oracle for n=2, sticking and a free belt. Additional
tests cover exact threshold neighbours, dimensional scaling, root enclosures,
missing/insufficient windows, transient strengthening, displacement constraints,
invalid inputs, and outward rounding. The nonlinear oracle tolerates 1e-12;
all actual admission comparisons are exact, including threshold equality.

The executable compares 100 checks on the same prepared nonlinear law using
44-step exact bisection versus the direct inequality, recording both times and
decision parity. It retains only active scalars, needs neither parallel workers
nor a new cache store, and reuses prepared powers. This is one tiny comparison,
not a world-runtime estimate or a claim to beat every possible solver.

Run `python -B tectonics/tools/check_i01_decoupling.py --output NEW.json`.
The output is exclusive, preserves failures, binds tool/case/method/tests before
and after, and records runtime versions and elapsed time. See the
[source-bound result](../evidence/i01-decoupling-r1.json).

## Papers and existing software checked

- [Duretz et al. (2021)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2021GC009675),
  section 4.2.2 and adjacent discussion: power-law overstress and the distinction
  between regularisation and full frictional/elastic mechanics. No coefficients
  or complete constitutive formulation are claimed reproduced here.
- [ASPECT continental-extension documentation](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html),
  material/history and creep-convention discussion: laboratory coefficients and
  stress conventions require explicit conversion, not copying into a scalar law.
- [SciPy bisection documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.bisect.html),
  bracketing and mixed absolute/relative stopping conditions. A floating solver's
  convergence flag alone is not used as an exact error certificate.

These sections were inspected, not their entire libraries or all supplementary
papers. No external software was installed or run. The inequality and finite-
window comparison are derived here for this stated reduced law, not attributed
to those sources as a published geological rupture criterion.
