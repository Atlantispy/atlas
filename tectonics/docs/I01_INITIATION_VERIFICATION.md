# Initiation: independent verification instead of guessing a published case

WORKING NON-CANON. This is an I01 **bounded numerical verification route**, not
physical acceptance of generated subduction. It supplements the selected
[resolved initiation method](I01_INITIATION_DECISION.md). The Li-Gurnis archive
and its unresolved inputs remain intact as an optional external comparison.

## Why this route

Michael authorised an alternative when the exact benchmark cannot be recovered.
The published experiment is useful but not the only way to check equations.
ASPECT explicitly distinguishes solving the equations correctly (verification)
from establishing that those equations represent the real phenomenon (validation).
Its benchmark suite uses analytical solutions and community comparisons for
different parts of a coupled calculation. Atlas now follows that hierarchy.
This does not waive the eventual resolved initiation/force-release experiment.

## What runs now

The [case](../cases/i01_initiation_verification_v1.json) declares synthetic SI
coefficients and numerical limits **before the candidate is evaluated**. None
is claimed as a calibrated Earth or fictional-world default. The
[tool](../tools/check_i01_initiation_verification.py) solves a spatial mechanical
boundary-value problem, not a fitted resistance law or a drawn force curve.

For velocity u parallel to an inclined layer, with cross-layer position s:

```text
-(eta(s) u'(s))' = b,    b = Delta-rho g sin(dip)
u(0) = 0,              eta(H) u'(H) = prescribed top traction t
```

The tangential direction is periodic and the layer geometry is fixed. Gravity's
normal component is balanced by hydrostatic support; its tangential density
contrast drives the solved flow. Constant temperature/viscosity and no material
inflow are explicit analytical limits, not a full plate model.

Piecewise-linear finite elements give a symmetric tridiagonal stiffness system.
Consistent body loads and boundary reactions use the same weak form. All work is
per unit wall area (W/m2), not the initiation comparator's per-strike force N/m.

For constant viscosity, independently integrating the differential equation gives
`u(s) = b*s*(2H-s)/(2*eta) + t*s/eta`. For a linear viscosity profile
`eta(s)=eta0*(1+s/H)` and t=0, the exact solution is
`u(s) = b*H/eta0 * (2H*log(1+s/H)-s)`.

The second expression is evaluated independently of the discrete solve. It tests
nonuniform material response on 8, 16 and 32 cells, with second-order refinement.
Constant-viscosity nodal values are exact to arithmetic accuracy, but integrated
power still has spatial error: its separate analytical value is `b^2 H^3/(3 eta)`.
We report and refine that error rather than treating matching nodes as sufficient.

## Why the release and energy checks matter

Removing top driving traction allows a moving wall with zero applied tangential
traction. Setting its velocity to zero instead adds a reaction that constrains
the motion. Both cases use identical material and body force; the test measures
the distinct answers and returned reactions. This catches the exact boundary
condition confusion in the source comparison.

For each solved state, integrated body work plus boundary work must equal
independently integrated viscous dissipation. Reverse gravity must reverse the
velocity, zero gravity/traction must give rest, and imposed traction work must
not be described as gravitational release. A separate call to the **retained**
elastic-memory producer shows nonzero dissipation during unloaded relaxation
while external work is zero: that energy comes from stored stress, not gravity.
No second elastic constitutive law is introduced.

These checks establish force, boundary and energy conventions in explicit
continuum/material limits. They do not establish a slab's initiation distance,
spontaneous fault geometry, noncoaxial memory, weak-path formation or long-term
subduction. They cannot enable an event or change a world's state.

## Acceptance hierarchy and remaining integration

1. **I01 method selection:** equations, inputs, support, generated/prescribed
   distinctions and this bounded verification. Missing archival inputs no longer
   make an exact Gurnis reproduction a prerequisite for method selection.
2. **I07 generated-initiation acceptance:** implement the shared objective
   stress/plastic-history kernel and a fully declared resolved experiment. Keep
   the existing fixed-physical-length spatial, time, rotated-mesh and exterior
   checks; compare reaction curves, work, localisation and the finite-window
   force-release result. Lock its material-specific inputs before execution.
   A missing compatible producer is a refusal, not permission to insert R.
3. **External validation:** use source-coherent published cases or independent
   observations with explicit applicability and uncertainty. The Gurnis curves
   remain reported/not admitted until their source issues are resolved. Agreement
   in the current analytical controls is not a replacement observational dataset.

The original source-reproduction checker continues refusing its incomplete case.
Its 15 missing groups are not filled with synthetic values or marked complete.
This parallel route deliberately has a different case and result schema.

## Cost and commands

Preparation stores only a three-diagonal operator and O(N) fields. Matching
operator arrays are reused across loads; numerical solving is O(N). No parallel
workers or large field histories are warranted for these millisecond controls.
No unmeasured speedup is claimed. Existing output files cannot be overwritten.

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_initiation_verification.py
python -B tectonics/tools/check_i01_initiation_verification.py --output NEW.json
```

## Papers and software checked

- [ASPECT benchmark documentation](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/index.html):
  analytical/community verification and the distinction from physical validation.
- [Spiegelman et al. (2016) / Fraters et al. (2019) ASPECT benchmark](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/benchmarks/newton_solver_benchmark_set/spiegelman_et_al_2016/README.html):
  nonlinear pressure-dependent solver verification as a separate task from
  acceptance of a tectonic history. No ASPECT execution or cross-code agreement
  is claimed here.
- [Chertova et al. (2012)](https://doi.org/10.5194/se-3-313-2012):
  regional boundaries materially affect subduction dynamics, supporting retained
  exterior-sensitivity and genuine traction-release requirements.
- [Li and Gurnis (2023)](https://doi.org/10.1093/gji/ggac332):
  retained archive findings and unresolved conventions are documented separately;
  the present analytical case is not labelled as their experiment.

The channel equations, exact solutions and weak-form balances above are direct
derivations. No text, implementation or parameter file was copied from ASPECT.
