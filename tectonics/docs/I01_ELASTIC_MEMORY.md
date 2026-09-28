# I01: retain elastic stress memory; exact coaxial control

WORKING NON-CANON. This settles the **keep rather than omit** branch of MC-01's
rift elastic-memory choice and supplies a bounded constitutive control. MC-01's
separation mechanism remains open. This is not a resolved neck or a production
stress-transport solver. Existing viscoplastic controls and receipts are unchanged.

## What this changes

Rock can temporarily store deformation energy, then unload or release it as
heat. Forgetting its earlier stress deletes that part of its history. A short
computer timestep does not establish that the rock forgets stress quickly: the
material relaxation time and the history of loading matter.

The generated resolved-rift route must therefore carry elastic stress memory.
There is no automatic switch to a memoryless model. Omission would need a
separate whole-approach error demonstration, including unloading and the
separation/handoff diagnostics. No such omission is selected here.

For finite, noncoaxial deformation, the selected formulation direction is an
incompressible Hencky/logarithmic objective elastic branch, with the existing
creep and plastic rates in series. In notation, for constant shear modulus G:

`D = stress^(log)/(2 G) + D_creep + D_plastic`.

The logarithmic rate uses the rotation that makes the objective derivative of
the Hencky strain equal the stretching tensor. It is not interchangeable with
using the material spin in a general Jaumann update. I07 must implement and
check the general logarithmic spin, nonlinear return/coupling and transport;
this helper explicitly rejects general shear. Supplied material shear moduli
and their support must be recorded. Changing G needs its own stored-energy law.
This choice does not resolve the subduction-initiation resistance MC-02.

## Exactly what the code supports

The immutable material state constructs its full kinematic history as

`F = R(theta) diag(exp(epsilon), exp(-epsilon), 1)`.

Stress, stretching and the stretch tensor share those axes. A step prescribes
constant signed principal stretching rate `e` and a superposed rigid rotation;
it advances epsilon by `e dt` and theta by that rotation. Merely supplying two
instantaneously aligned tensors would not establish this history. There is no
independent off-axis strain input. Signed rate opposing the stress is valid.

For this history the logarithmic-spin correction vanishes. Constant positive
G and Newtonian viscosity eta give a scalar Maxwell law in the rotating axes:

```text
stress = R diag(s,-s,0) R^T       [Pa]
ds/dt  = 2 G e - (G/eta) s
stored energy = s^2/(2 G)        [J/m3]
mechanical power = 2 s e         [W/m3]
viscous dissipation = s^2/eta     [W/m3]
```

This is the elastic/Newtonian subcase, not a replacement for the nonlinear
composite creep or plastic law. `eta=None` explicitly selects the purely elastic
control, never a numerical viscosity cutoff. Finite viscosity always keeps its
actual relaxation time. Total log stretch is bounded to +/-1, elastic strain
`|s|/(2G)` to 0.01, and rotations to at most one turn per call. These are declared
control/admission bounds, not calibrated rock-failure thresholds. Nonfinite,
unrepresentable-clock, modulus-mismatched and unsupported histories are refused
without modifying the input state. No threshold produces a breakup event.

## Exact update and stable energy accounts

Let `z=G dt/eta`, `a=exp(-z)`, `phi=-expm1(-z)/z`, `c=2 G dt e`.
Then `s1=a s0+phi c`. The elastic limit is evaluated separately at z=0.

The code integrates work and heat independently. Heat is a positive
mean/variance integral, not a residual set to make the energy account close.
For z<=0.5:

```text
psi = (1-phi)/z
chi = (1/2-psi)/z
v = [phi(2z)-phi(z)^2]/z^2
mean stress m = s0+c/2 - z (psi s0+chi c)
h = c-z s0
heat Q = (dt/eta) [m^2+v h^2]
work W = 2 dt e m
delta_s = phi h
s1+s0 = 2 s0+c-z m
delta_E = delta_s (s1+s0)/(2G)
```

Eighteen-term series evaluate psi, chi and v without subtracting nearby numbers;
their coefficients are respectively `(-1)^k/(k+2)!`, `(-1)^k/(k+3)!` and
`(-1)^k (2^(k+2) k+2)/(k+4)!`, k=0..17. Their limits are 1/2, 1/6 and 1/12.
The remainder on this bounded interval is below double precision. Centring the
elastic path before the correction preserves small work during load reversal.

For larger z, use steady stress `u=2 eta e`, mean `m=phi s0+(1-phi)u`, and
`Q=(dt/eta)[m^2+(phi(2z)-phi^2)(s0-u)^2]`. The implementation checks
`W-delta_E-Q` against the declared round-off scale; it never clips negative heat.
Algebraic stable differences preserve energy changes smaller than subtracting two
rounded endpoint energies can resolve. Physical heat is not total mechanical work:
some work is stored, and unloading can give negative work with positive heat.

## Checks and timing

The focused tests compare with independent 80-digit direct exponential integrals
over z from 1e-12 to 1000, including both sides of the series boundary. Heat is
checked separately with a relative bound; nearly cancelling work is checked
against gross input stress work, not an ill-conditioned near-zero net. The
2e-12 tolerance is a numerical control, not geological accuracy.

Other checks cover stress relaxation, released stored heat, the small-step heat
asymptote, steady stress, a purely elastic limit, negative work, exact matrix
rotation, frame covariance, subdivision parity, immutable preparation and invalid
or unsupported inputs. The memory-on/zero-start comparison measures the stress
lost by resetting history; it does not calibrate a rift or permit omission.

Preparation is O(1): immutable coefficients for one G/eta/dt. Each update keeps
one state and constant-sized accounts, with no solver iterations or accumulated
history arrays. Rebuild if any preparation input changes. No disk cache, dense
matrix or worker processes are useful for this tiny kernel. Five alternating
matched repeats time 2,000 identical updates with preparation reused versus
rebuilt, including the same state validation and accounts in both arms. Report
raw seconds and percentage for this kernel only. No previous generator release
or whole-world speedup is implied. The campaign has a ten-second budget.

## Papers and software actually checked

- [ASPECT viscoelastic source](https://github.com/geodynamics/aspect/blob/main/source/material_model/viscoelastic.cc),
  evaluated outputs and declared constitutive equations: stress components are
  carried explicitly, rotation and dissipation are separate, and elastic and
  viscous rates add. ASPECT's general Jaumann discretisation is not copied here.
- [Schrank et al. (2017), sections 1-3](https://doi.org/10.1093/gji/ggx297):
  comparison of small-strain, Jaumann and logarithmic finite-strain Maxwell
  formulations; large noncoaxial-deformation pitfalls motivate the explicit
  restriction and finite-strain direction. This paper does not validate Atlas.

The stable scalar integrals are derived here from the stated ODE. External
software was not run. The Kaus and Podladchikov (2006) article and an ASPECT
stress-build-up benchmark page were inaccessible in this pass and are not cited
as read. No new dependency was installed.

## Ownership and result boundary

I02 must persist accepted stress/stretch state. I05 transports that state with
the same material, never interpolating it as unrelated scalar magnitudes. I07
owns general noncoaxial objective transport, nonlinear creep/plastic coupling,
and stress-memory effects on the neck; I09 owns the coupled time integration.
Energy sent to heating must be viscous/plastic dissipation, not reversible
stored-energy change. The present control neither implements those steps nor
changes the retained basal ledger that expressly excludes elastic storage.

Code: [helper](../tools/check_i01_elastic_memory.py),
[tests](../tests/test_i01_elastic_memory.py), [case](../cases/i01_elastic_memory_v1.json).
The exclusive-output CLI binds these files and this method before/after execution:
`python -B tectonics/tools/check_i01_elastic_memory.py --output NEW_PATH.json`.
Results belong in the current evidence register, not this source-bound document.
