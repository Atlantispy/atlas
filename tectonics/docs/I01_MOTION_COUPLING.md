# I01: driving force, drag and evolving column resistance

Status: **WORKING NON-CANON; bounded I01 feasibility connection**.
This new adapter imports the reviewed weakening and column helpers read-only.
It does not import Claude's concurrently developed column-heat adapter, change
native sources or create a global tectonics/transition acceptance claim.

## What now determines motion

Previously the layered weakening control received a stretching rate or the
force transmitted through the column. Here the external driving force is shared
between a disjoint drag element and resistance calculated from the actual layers:

```text
v = a w
F_drive = D v + F_column(a, kappa)
```

`a` is the signed axial rate in s^-1, `w` the physical width in m, and `v` the
signed relative edge velocity in m/s. Forces are N/m of strike. `D` is a positive
**generalised line drag in Pa s**, NOT the local basal eta/H coefficient in
Pa s/m. This is a stationary-frame, single-degree-of-freedom approximation with
external force constant over the accepted window. It solves for motion at every
history-integration stage. Weakening therefore changes velocity causally; no
post-processing of the generated rate is involved.

The new case's force, drag and 100 km width are authored controls, not calibrated
Earth defaults. Physical layers, thermal profile and inherited history retain
the provenance of [I01 weakening](I01_WEAKENING.md). No target speed is used to
choose the campaign force. A separate manufactured test constructs a force from
a known rate solely to verify the inverse calculation.

## Ownership and the energy check

The column includes its crust and mantle lid; its internal deformation is already
counted. The lumped drag represents a **different** external process whose
work-conjugate velocity is `v`. Do not also assign a surrogate interface resistance
to this same deforming column. Do not substitute `D_b*w` blindly for D: for a
centred, uniformly extending belt with basal coefficient D_b, its own velocity
field instead gives `integral D_b*(x/w)^2 dx = D_b*w/12`. That distributed-belt
interpretation is not used by this control. Moving mantle forcing would need a
separate work account and is not implied by the stationary dashpot.

Future callers own the external force and its provenance. D1's GPE/slab/mantle
terms must not double-count ridge push or resistance hidden in supplied factors.
This adapter is a regional reaction seam, not an assembled spherical momentum solve.

The retained helper returns column power `a*F_column` in W/m^2. Multiplying by
width gives the same units as force times velocity:

```text
F_drive*v = D*v^2 + w*(creep_power + plastic_power)   [W/m of strike]
```

We integrate all terms with the same accepted Heun stages, giving J/m. External
work must additionally equal `F_drive*displacement`. The creep/plastic split is
one partition of column work, never two added sources. Compression reverses force
and velocity together; dissipated power remains positive. Energy is accounted
but does not heat this fixed-temperature control; Claude owns that separate seam.

## Numerical choice and efficiency

Use `x=abs(v)/(abs(F_drive)/D)` on the analytic bracket [0,1]. The residual is
`x + abs(F_column(sign(F)*rate_scale*x))/abs(F) - 1`. Its derivative is
`1 + dF_column/da * rate_scale/abs(F) > 0` on the helper's admitted branch.
The zero endpoint is the continuous zero-stress limit; zero drive returns exact
rest. Safeguarded Newton uses the actual column tangent in log(x), limits a trial
to a factor-two rate change and falls back to bracket bisection outside the
interval. The log step avoids unnecessary near-zero-rate overshoots that lose
plastic-stress resolution despite a representable physical root. Force residual must be <=1e-10;
at most 96 iterations are allowed. A separate SciPy Brent solve checks roots.
Unsupported compressive pressure-dependent creep is refused by the helper rather
than extrapolated. A mathematical drag-only upper bound does not promise that
every intermediate evaluation lies in the material model's admissible branch.

The mixed stress exponents, including 3.5, are retained. This is not a conversion
to the integer-exponent family in [the decoupling certificate](I01_DECOUPLING.md).
Floating-point roots are not outward-rounded certificates or rupture criteria.

The evolving history uses second-order explicit Heun with a fresh balance at the
predictor and accepted endpoint. It retains current state and scalar accounts,
not every iterate. A refused small-strain trial does not book energy or history.
Temperature, material depths, width, forcing and drag are fixed, with total axial
strain <=0.05 and <=256 accepted steps. No advection, geometric necking, elastic
memory, dynamic inertia, finite-strain continuation or fault-width interpretation.

Unchanged immutable column coefficients are prepared once. Previous rate and
log-stress are initial guesses only; the current residual is always checked.
One matched cold/warm comparison reports raw times, evaluations, parity and
percentage. Both paths reuse preparation, so its measured saving is specifically
warm starts, not a claim about all possible caching or whole-world performance.
These tiny solves do not warrant process-pool or persistent-cache overhead.

## How we check it

- Exact linear-creep force/velocity relation for extension and compression,
  different drag values and no plastic activity.
- Known-rate inverse and independent Brent roots for both signed nonlinear laws.
- Exact zero-drive rest, input immutability, invalid inputs and deadline refusal.
- Work partition, external-work/displacement identity, plastic-history bound and
  atomic over-strain refusal.
- Coupled evolving-history controls at 16/32/64 time steps and 32/64/128 quadrature
  points per layer. Predeclared finest-pair velocity limits are 1e-4 in time and
  0.003 in depth; these are convergence controls, not Earth calibration.
- Fixed weakening-law coefficients give constant velocity; evolving inherited
  weakening changes velocity. Warm/cold solution parity limit is 1e-8.

Run from the repository root with the existing compatible scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_motion_coupling.py -v
python -B tectonics/tools/check_i01_motion_coupling.py --output tectonics/evidence/i01-motion-coupling-r1.json
```

The exclusive-created receipt binds this method, tool, tests, case, the actual
retained helper sources/case and reviewed r2 receipt before/after execution. It
checks helper bytes against r2. Runtime version observations are not binary seals.

## Papers and software actually consulted

- [Duretz et al. (2018), consistent tangent operators](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2018GC007877):
  introduction and section 4.3 support using a derivative consistent with the
  constitutive calculation for nonlinear equilibrium. Their full viscoelastic
  finite-element/finite-difference problem is not claimed reproduced here.
- [SciPy Brent documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html):
  sign-changing continuous bracket, bounded iteration, and relative/absolute
  tolerance semantics. Used as an independent scalar-root comparison; the
  dimensionless coordinate avoids applying a metre/second-sized absolute default.
- Actual retained Atlas `check_i01_weakening.respond` and `check_i01_column`
  implementations, their reviewed evidence and D1/D6 force/work ownership were
  inspected. The new scalar reduction and exact linear control are derived here,
  not attributed to those papers as a published breakup law.

A preliminary unrelated Solid Earth URL could not be fetched; no result relies
on it. No external reference software campaign or full-paper visual audit was run.
