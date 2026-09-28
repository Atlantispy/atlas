# I01: physical reorganisation of plate-boundary junctions

WORKING NON-CANON. **Resolved-patch method selected; physical implementation and
acceptance outstanding.** The [case record](../cases/i01_junction_reorganisation_v1.json)
fixes the proposed route and controls, not a runnable simulation. MC-05 is not
closed by this document. The previously completed contact and outgoing-ridge
helpers remain valid numerical prerequisites, not the whole junction model.

## 1. The physical rule

**Evolve the rock around an unresolved junction; extract a new plate network
only after supported physical interfaces and a valid mechanical handoff exist.**
The network follows the material solution. It does not pick a convenient new
edge and modify the rock to fit it.

Select a finite, multidirectional **regional deforming patch** under the existing
global/regional coupling. The patch includes the approaching boundaries, their
inherited structures and enough surrounding material to check exterior influence.
It can retain distributed deformation or an extended junction region; it is not
required to produce exactly three lines meeting at a point on the next timestep.

Do not introduce a separate universal junction-fracture law. MC-01 supplies any
admitted separation/slip-discontinuity mechanism, MC-02 supplies initiation and
MC-03 supplies compatible finite magma where that mechanism requires it. I07
solves local mechanics; I03 represents the resulting geometry; I09 couples it to
the plates; I02 commits the event and accounts. This choice connects those
responsibilities without declaring their unfinished producers implemented.

The general patch retains two horizontal directions and vertical structure:
**a three-dimensional region**, not independent vertical slices meeting at a
point. A depth-integrated approximation would need its own derived constitutive
and coupling error demonstration before substitution. This is local refinement,
not a requirement to simulate the whole mantle at regional resolution.

## 2. When to leave the rigid-junction description

There are two distinct triggers:

1. Bracketed contact or geometric degeneracy of actual evolving boundaries. The
   [existing exact contact helper](I01_JUNCTION_EVENTS.md) only covers declared
   affine planar paths. Its double-root example remains a required control.
   Curved edges, uncertainty and simultaneous contacts need I03's actual
   geometry, not snapping near endpoints or reusing a straight-edge assumption.
2. Loss of a compatible rigid-junction velocity under the admitted boundary
   constraints. An excessive algebraic residual indicates failure of that
   representation; it is not a physical fracture threshold or a measured growth
   rate. Re-evaluate the assumed geometry and forcing before promoting a patch.

Stop the old proposed rigid evolution before it crosses its validity limit.
Transfer the accepted pre-event material, composition, temperature/enthalpy,
stress, plastic history and contact/interface state conservatively into the patch.
Do not reset those histories, erase the disappearing edge's material, or recreate
young crust because two labels changed. The initialisation is a change of
representation of the same state, not a second source of material or energy.

## 3. Governing mechanics and dimensional conventions

The selected first resolved branch is quasi-static and incompressible/Boussinesq:

```text
div(v) = 0
-grad(p) + div(tau) + rho_b*g = 0
D = sym(grad(v))
D = tau^(log)/(2*G) + D_creep + D_plastic
```

Here rho_b is the density used consistently in buoyancy; changing thermodynamic
density does not silently change the chosen volume-transport approximation.
Composition, physical inventories, heat and latent/pressure work follow the shared
D3/D4 producers and their stated approximation. G is a fixed positive material
modulus unless a compatible changing-modulus stored-energy law is admitted.
Use the retained logarithmic-objective elastic direction and raw plastic history,
not a memoryless viscosity replacing bending and unloading.

The existing D2 yield expression is explicitly two-dimensional. For the proposed
3D branch, select the ASPECT 3.0.0 source's middle-circumscribing Drucker-Prager
convention, with `tau_II=sqrt(tau:tau/2)`:

```text
P_eff = max(P_lith + P_dynamic - P_pore, 0)
Y_3D = 6*(C*cos(phi) + P_eff*sin(phi)) / (sqrt(3)*(3 + sin(phi)))
lambda_p = max(tau_II-Y_3D,0)/eta_p
D_plastic = lambda_p*tau/(2*tau_II)     when tau_II > 0
D_plastic = 0                         when tau_II = 0
Dkappa/Dt = lambda_p                   zero-healing first branch
```

eta_p is the positive, declared engineering-shear regularisation viscosity,
not ASPECT's unconverted tensor-invariant damper parameter. Then
`2*sqrt(D_plastic:D_plastic/2)=lambda_p` and plastic dissipation is
`tau:D_plastic=lambda_p*tau_II>=0`. The flow is isochoric, non-associative: the
pressure dependence of Y does not add unowned plastic volume dilation.
Use physical-length Helmholtz weakening and explicit cohesion/friction residuals
as in the [initiation specification](I01_INITIATION_DECISION.md), with material
provenance and full pressure reference. No arbitrary new pore-fluid evolution.

This is a **proposed 3D constitutive convention**, not permission to reinterpret
already calibrated 2D coefficients or an implemented general return mapping.
For phi=0, Y_3D=2*C/sqrt(3), whereas D2 gives Y_2D=C. A parameter adapter must
record which material strength was fitted; it cannot claim 2D and 3D parity using
the same bare number. ASPECT's v3.0.0 source uses a coefficient 6 on pressure;
one Visco Plastic description on the parameter page prints 2. The inspected
source, not that conflicting sentence, is the comparison used here.

This continuum branch can localise deformation, but localisation is not itself
an admitted new discontinuity. The shared failure/contact law must supply that
additional physical change where required. In particular, a closed slipping
fault does not need an empty gap, and a weak coloured corridor does not establish
a fault. MC-01 owns that distinction; the junction code must not invent another.

## 4. Exchange with surrounding plates

All exterior plate motion uses the same frame and accepted interval. Apply each
boundary condition by component: prescribed velocity and prescribed traction
must not both constrain the same component. The solved traction is returned to
the global motion calculation; prescribed velocities cannot stay immune to the
patch's changed resistance. I09 iterates the coupled response within its declared
allowances rather than fitting local velocities once and ignoring feedback.

Keep the free surface and common water/load datum from D5, and the mechanical,
thermal and incoming-material base contract from MC-04. Side and basal fluxes
must use actual transported composition/enthalpy. Include both horizontal
components, surface motion, stored elastic energy, plastic/viscous dissipation
and external work. Replacing a belt by the patch must remove the replaced force
contribution from D1: no duplicate ridge push, interface drag or bending term.

At a port, record the work-conjugate pair `(traction, velocity)` on the same
surface and frame. Regional/global port works cancel after opposite-normal
orientation; internal port work is not counted again as an external source.
Changing a patch boundary requires a conservative remap and an explicit
inventory/energy exchange, not fresh initial conditions.

## 5. How a new network is selected

There is no independent score ranking hand-drawn candidate graphs. The resolved
state can yield a connected interface network, continued distributed deformation,
or insufficiently resolved alternatives. Apply this ordered rule:

1. Carry the physical interface/contact objects or accounted material-state
   changes issued by admitted process laws. Their geometry, mechanism, support,
   parent state and uncertainty are required, not a caller's `verified=true`.
2. Reconstruct shared surfaces, intersections, exterior connections and cyclic
   ownership from those objects and the transported material. Include paths
   around the patch; a section or raster majority is not sufficient coverage.
3. Classify each proposed boundary from its mechanism and signed full relative
   motion. Opening alone is not basalt creation: ridge accretion needs real
   source material; a supported melt-poor route may expose mantle without
   inventing basalt. A trench needs polarity and actual incoming consumption;
   tangential slip does not create area. If the model does not support a mixed
   oblique boundary, retain the deforming patch instead of forcing a label.
4. Use the existing kinematic checks on that resulting geometry. The all-ridge
   helper is applicable only to its stated symmetric planar branch. Its one
   feasible candidate cannot disprove a different physical solution.
5. Compare the resolved patch and proposed reduced network over the declared
   handoff window, using the shared maximum-vector-velocity error criterion and
   compatible work/history accounts. A one-instant low residual or an arbitrarily
   thin band cannot authorise the replacement.
6. If all applicable obligations pass, propose the entire interacting event to
   I02. Otherwise continue the supported patch, refine an unresolved state, or
   stop at the stated resource/domain limit. Do not continue an invalid old
   graph merely because the new one is not ready.

No finite-width extraction threshold is selected as a physical birth law. Real
interfaces come from an admitted mechanism; reduction of a finite-width belt
requires the whole-window handoff. Perfect symmetry with competing alternatives
must not be broken by face ordering, node number, round-off or a random graph
tie-break. A physically declared initial perturbation belongs to the input and
must retain its seed/support; unresolved symmetric cases remain unresolved.

## 6. Event time and exact transfer responsibilities

Contact time and physical boundary-birth time are separate. Evolve between them;
do not assign both the first contact timestamp. Bracket each genuine physical
change with the producer's event criteria and numerical error. If candidate
intervals overlap, do not select the earlier rounded endpoint: solve interacting
events jointly or refine their ordering. Tangencies must be covered, not just
sign changes. The existing affine contact control supplies one special case.

The joint proposal includes one parent identity, one validity interval, the
affected geometry and mechanisms, reservations, transfers and all residuals.
For each transported component k, preserve

`M_after[k] = M_before[k] + M_external_in[k] - M_external_out[k]`.

Internal donor/receiver entries occur once with opposite signs. Preserve
composition, cohort birth times, temperature/enthalpy and stress/plastic/contact
history under the admitted remap; a topological relabelling has no independent
mass, heat or age source. Ledger identity can be exact while continuous remap and
energy residuals still need declared numerical error bounds. Do not call a
floating-point physical transfer exact merely because its transaction ID is unique.

I03 checks one owner per surface point, no gaps/overlap, compatible edge endpoints
and full spherical coverage. A new local interface tip can exist inside a
deforming patch without yet becoming a global plate boundary. I02 publishes the
complete valid change atomically; on failure nothing is partly committed. I09
then recomputes dependent motion/triggers. Source-bound old receipts are not
rewritten to cover this future integration.

## 7. Predeclared controls and acceptance

The companion record lists exact negative outcomes and numerical conventions.
Required comparisons, in implementation order:

- 3D invariant/yield conventions, zero stress, simple shear, rigid rotation,
  unload/reload and nonnegative dissipation. Shared general material-kernel tests
  are reused once supported; no separate junction constitutive implementation.
- Same contact and plate velocities but different supported temperature,
  inherited weakness and supply. Results must actually consume these inputs;
  do not demand a topology change for every perturbation.
- Multidirectional competing zones, continued distributed deformation and a
  symmetric case with no artificial ordering-based winner. Freeze the full
  material/boundary initial state before testing.
- Material-derived boundaries versus a kinematically feasible but physically
  unissued candidate: only the former can reach a physical event proposal.
- Joint events competing for the same finite source, exact replay/rollback,
  source exhaustion, no heat/age reset and no duplicate global/regional work.
- h/h2/h4 at fixed physical lengths and material laws; independent time
  refinement; rotated mesh; expanded patch/deeper base; preserved exterior
  coverage. Report force/work, material amounts, event brackets, interface
  geometry and handoff error, not just a visually similar topology.

Numerical tolerances, regional domain/material coefficients and handoff window
must be locked in runnable cases before physical tests; they are not supplied
by the literature summaries. The exact conventions and refusal expectations in
this record are predeclared now; campaign values remain unset, never silently
defaulted. Existing kinematic/accounting receipts do not validate the new route.
MC-05's completion rule is unchanged: admitted reorganisation, timing, transfers
and bounded controls must actually pass before closure.

## 8. Cost control and next coding slice

Activate a region only around loss of the supported rigid representation; use
the same existing region when physical footprints overlap. Independent disjoint
regions can run in parallel within the shared memory budget. Interacting regions
must exchange forces/material and share a joint event; running them independently
because they have different junction IDs is incorrect.

Cache immutable geometry and symbolic sparse structure while their identities
match. Recompute numerical factors on relevant coefficient changes. Preserve
branch-owned active fields with shared immutable parent checkpoints; save bounded
diagnostics and selected restart states, not every nonlinear iterate. Include
all exterior forcing, material laws/history, source inventories, geometry,
regularisation and numerical configuration in reuse identity. Warm starts are
guesses checked against the new state, not reuse of an accepted old topology.
No time saving is claimed for this design-only work.

**Next implementation, not another contact helper:** build one shared I07
multidirectional regional solve from an actual accepted parent, preserve its
stress/history, and return work-conjugate forces through I09. Feed admitted
MC-01/02/03 mechanism outputs into the I03 joint extraction and I02 transaction.
Start with the material/invariance/negative controls above; then one completely
specified competing-direction case. No broad planetary or multi-day run is
needed for that increment. Any actual physical-event claim waits for its
missing producer and resolved comparison, not for a cosmetic graph repair.

## 9. Research/software basis

- [Kleinrock & Phipps Morgan (1988), pp. 2983-2987](https://www.researchgate.net/publication/252480635_Triple_junction_reorganization),
  author-uploaded paper: local stress and existing transform geometry matter to
  ridge propagation. The idealised wedge/singularity and minimum-dissipation
  limitations prevent treating it as a universal graph selector. Available OCR
  equations were not copied as numerical authority.
- [Gerya & Burov (2018)](https://www.sciencedirect.com/science/article/abs/pii/S0040195117304456):
  publisher material only; distinguishes transient rifting junctions from mature
  oceanic spreading and uses 3D magmatic thermomechanics. The full derivation
  remained inaccessible. The mature weighted-lengthening formula is not adopted
  as a birth law or claimed reproduced.
- [Koptev et al. (2018), Modelling Approach and Results; Methods](https://doi.org/10.1038/s41598-018-33117-3),
  full publisher text recovered through the authors' ResearchGate paper:
  3D thermomechanical evolution gives multiple rifting geometries; dissipation
  is a reported consequence, not a graph objective. Its plume-driven continental
  case is not validation of Atlas's oceanic reorganisation. It informs the
  dimensionality and competing-pathway test requirement.
- [ASPECT 3.0.0 Drucker-Prager source](https://github.com/geodynamics/aspect/blob/v3.0.0/source/material_model/rheology/drucker_prager.cc#L65),
  `compute_yield_stress` and damper convention; [material documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/parameters/Material_20model.html)
  exposes a conflicting pressure coefficient. The source comparison fixes the
  proposed 3D convention, not a claim that Atlas runs ASPECT or shares its complete
  time integration, material calibration or yield cap.
- [pyGPlates resolved deforming networks](https://www.gplates.org/docs/pygplates/generated/pygplates.ResolvedTopologicalNetwork.html):
  useful separation of deforming regions, rigid blocks, shared subsegments and
  fields. Its supplied reconstruction/triangulation is not a physical birth
  solver; rubber-banding and Earth-specific defaults are not adopted.

The junction-paper comparison was delegated read-only; source scopes and access
limits are retained above. Main review inspected the existing Atlas helpers,
coupling contracts and official software source/docs. No external software or
scientific campaign was run for this decision.
