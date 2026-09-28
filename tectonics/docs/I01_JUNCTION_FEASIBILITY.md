# I01: bounded junction mechanics feasibility

WORKING NON-CANON. This control exercises the selected resolved-patch route
through the retained three-dimensional mechanics and plate-torque adapter.
It establishes same-time numerical feasibility only. It does not issue physical
interfaces, advance a world, choose a replacement graph or close physical
reorganisation acceptance.

## Producer and declared case

The [control](../tools/check_i01_junction_feasibility.py) calls the actual
`PreparedRegionalStokes3D` and `PreparedPlateBoundary3D` implementations. The
[fixed synthetic case](../cases/i01_junction_feasibility_v1.json) is a 2 m cube
with 2 by 2 by 2 Q2/Q1 elements. Two plates own its lower and upper velocity
faces. All lateral faces have zero traction. All three angular components of
both plates are solved. The planet-centred origin is explicitly (-1,-1,4) m;
this small embedding tests vector mechanics, not planetary curvature.

Scalar viscosity is `4-a*exp(-(x-1)^2/0.5^2)-b*exp(-(y-1)^2/0.5^2)` Pa s.
The symmetric pair uses (a,b)=(1.5,1.5); directionally unequal material uses
(2.5,0.5), and the rotated counterpart exchanges these coefficients. These
positive, intersecting spatial corridors are supplied material properties, not
generated damage or anisotropic constitutive coefficients. No thermal, fracture
or initiation calibration is inferred from them.

The plates receive opposite 1 N m torques, first in x, then y, then both.
An explicit 0.5 N m s exterior resistance per angular component removes common
rigid modes. This exterior term is separate from the resolved viscous rock.
The mechanical producer determines the resulting motion and its regional
reaction. The fixture does not prescribe a preferred graph or select a winner.

## What is compared

Eight real solves check forcing superposition, equal directional response in the
symmetric material, proper 90-degree mesh/material/forcing rotation, global
coordinate-frame rotation, plate-list permutation and changed material direction
under unchanged forcing. The unequal material must actually change solved motion;
a numerical comparison that ignores the material input cannot pass.

Independent nodal sums check net force, net regional torque and plate torque
returned as `sum(r cross F)`. Independent products check nodal work against
`omega dot torque`, opposite port work cancellation, exterior torque balance,
positive viscous dissipation and total external power against exterior drag plus
regional viscous and pressure work. Native residual gates are retained. The
control's fixed tolerances are 2e-8 relative and 2e-10 absolute; balance errors
are tested in the stated SI units. The minimum observable material-response
difference is 1e-5 rad/s for this synthetic fixture, not a geological threshold.

The existing outgoing-ridge helper is consumed directly: its kinematically
feasible candidate still reports `physical_birth_verified=false` and
`topology_change_authorised=false`. Mechanical snapshots retain their explicit
no-boundary-birth scope. This is an exercised negative result from retained
producers, not a new placeholder event issuer or a fabricated physical gate.

Geometry and viscosity stay fixed while the symmetric forcing cases reuse one
factor and a six-mode response. Different material creates a new plan. Plans
run sequentially with 64 MiB native admission and 4 MiB adapter buffers; at most
eight small immutable output snapshots are retained for comparisons. These are
accounted limits, not process RSS guarantees. The campaign checks a 60-second
wall-clock bound at completion; the native solver retains its own finite solve
bounds. There is no timing benchmark or claimed world-scale saving.

## I01 feasibility and later integration

This bounded control supplies the missing test that the selected I01 junction
method can consume multidirectional material resistance and return consistent
plate work. Existing local mechanics/evolution tests remain component evidence;
their unchanged numerical campaigns need not be rerun for this additional seam.

The [physical reorganisation specification](I01_JUNCTION_REORGANISATION.md)
remains the method contract. Full I07/I09 evolving regional/global assembly and
I03/I02 extraction/transactions are downstream integration responsibilities.
Requiring all of those completed implementations merely to accept I01's method
choice and bounded feasibility would make its stage boundary circular. This
control does not waive their physical acceptance obligations or declare MC-05
physical reorganisation complete.

Actual topology remains conditional on real admitted MC-01 separation/contact,
MC-02 initiation and MC-03 compatible finite magma when required by the case.
Objective stress/history evolution, accepted-parent transfer, moving surfaces,
material-derived interfaces, event timing, conservative joint transactions,
physical mesh/time/domain refinement and a whole-window mechanical handoff are
not tested here. The cube is a manufactured input, not an accepted geological
parent or a generated junction. Its symmetry checks establish no arbitrary
direction preference for this discrete mechanical case, not uniqueness of a
future nonlinear physical topology.

## Reproduce and source basis

From the repository root, using the existing compatible numerical environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_junction_feasibility.py -v
python -B tectonics/tools/check_i01_junction_feasibility.py --output NEW_REPORT.json
```

The optional report is exclusively created and binds this control, case, method,
tests, retained adapters and native source inventory, plus actual runtime identity.
Changed source or a failed check reports failure. A pass is explicitly
`PASS_BOUNDED_CONTROLS_ONLY`, with scientific acceptance and topology issuance
false. No existing receipt is rebound or overwritten.

The primary software references inspected for this control were
[Bleyer's consistent-reaction example](https://bleyerj.github.io/comet-fenicsx/tips/computing_reactions/computing_reactions.html),
which derives boundary force and moment from the original weak residual, and the
[FEniCSx Taylor-Hood Stokes demonstration](https://docs.fenicsproject.org/dolfinx/main/python/demos/demo_stokes.html),
which documents mixed velocity/pressure spaces and pressure nullspace treatment.
These support reuse of the retained reaction and mixed-element machinery.
Neither is a geological junction benchmark; neither software was installed or
run for this control. The actual Atlas method remains documented in
[regional mechanics](REGIONAL_MECHANICS_3D.md).
