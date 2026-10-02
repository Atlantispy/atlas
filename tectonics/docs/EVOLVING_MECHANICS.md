# Tectonics Step 3: compatible evolving mechanical inputs

23 September 2026. WORKING NON-CANON. Local implementation on `remake`.
This is the next tectonics increment after [underthrusting](UNDERTHRUST.md),
not W09 surface-process expansion. Existing modules stay in place.

## Changing elastic properties and physical loads

`evolving_flexure.py` connects actual W03 states to the existing W04 physical
load construction and conservative variable-rigidity Hermite solver. It does not
duplicate the inventory, pore-water placement, thermal load or external-pressure
calculations. The old fixed-property W04 API retains the same calculations after
extracting its shared input validation and load-change construction.

`W04RigidityState` binds each supplied E/Te/nu profile to an actual W03 state/time,
frame, datum and epoch. `W04AbsoluteReferenceLoad` supplies total reference
pressure on the actual reference cells, with source and exact reference
surface/policy/exterior binding. This datum is required: the old anomaly-only
inputs cannot identify an unloaded or stress-free plate when its stiffness changes.
It already includes the reference contributions; it is not another load to add.

`PreparedEvolvingW04Support` retains that fixed reference. At each supplied state,
W04 constructs the physical load change, then the new adapter evaluates

    q_current = q_reference_absolute + W04_physical_load_change
    delta_w = A(D_current)^-1 q_current - A(D_reference)^-1 q_reference_absolute.

Thus unchanged load can produce changed deflection when rigidity changes.
`A(D_current)^-1 delta_q` would miss that response. If the profile/operator is
unchanged, the existing compensated load-difference solve is retained, avoiding
subtraction of nearly identical large solutions. An exact unchanged reference
request avoids a redundant zero-load solve.

The conservative operator remains `(D w'')'' + K w = q`, not local D multiplied
by a uniform biharmonic stencil. Geometry, foundation K, boundary conditions and
accuracy policy remain fixed per preparation. Continuing-plate cases bind both
absolute exterior loads and exterior elastic properties; uncertain omitted loads
remain unsupported for variable rigidity. The complete absolute reference and
current solutions must pass the existing linear/small-slope/strain validity checks.
Changed-profile difference checks use a conservative sum of polynomial maxima
and mesh-change estimates, so large cancelling states cannot hide invalid physics.

Outputs retain the existing once-owned W04 load/sediment/water accounts plus both
absolute pressures and displacements. They are totals from the fixed reference,
not increments to add repeatedly. W03's local support diagnostic stays excluded.
The receiving module owns applying any output to its geometry or material state.

Only the reference operator and one replaceable current operator are retained;
old changing-profile factors are released before their replacement. Matching
profiles reuse factors. All work shares the existing 128 MiB accounting and native
thread controls. Returned outputs have caller-owned storage; no field history grows
inside the plan. Existing source-bound variable-flexure caching remains available.

## Coincident regional force, material and boundary inputs

`evolving_mechanics.py` adds an explicit exchange boundary to the existing W07
regional Stokes solver. `RegionalInputContext` binds dimensions, grid, world
origin, frame, vertical datum, epoch and exact physical instant. Immutable
`RegionalInputBlock` kinds cover:

- material viscosity at the separate normal-stress centres and shear vertices;
- complete physical body-force components on the staggered faces;
- all four boundary components, explicitly velocity or traction;
- optional downward surface pressure on the top-normal sampling support.

Every block names its producer state, source and sampling law. SI units and array
supports are checked before capture. `RegionalMechanicalRequest` rejects mixtures
of different instants, epochs, supports or frames. Physical effect IDs cannot be
duplicated across force, load and boundary inputs; total gravity has at most one
owner. These are declared producer contracts, not an inference that two differently
named physical effects are genuinely independent.

Surface pressure occupies a declared zero top-normal traction slot and is mapped
to negative vertical traction. A prescribed top-normal velocity or an already
occupied load slot refuses instead of silently overriding or adding loads.
W04 or other extra displacement cannot be attached to W07's owned response.

`regional_thermal_gravity` reuses the existing Boussinesq law and named
cell-mean-to-stress-site temperature reconstruction. It supplies replacement total
gravity; including both old and new gravity blocks refuses. The Stokes solver
alone subtracts its reference-pressure gradient. This does not change material
inventory mass, infer material viscosity or evolve heat. The law and temperature
bytes, source and producer state are bound into the resulting force input.

`PreparedEvolvingRegionalMechanics.evaluate(request)` produces a quasi-static
mechanical snapshot. Changing force/boundary values reuse the existing operator;
changed viscosity refills the coefficients and factors while retaining geometry.
Identical coefficients retain factors even when provenance changes. A latest
identical request still verifies live source identity. Only one current operator
and latest response are retained. Geometry, boundary types and pressure convention
changes need a new plan, not a silently reused incompatible operator.

**An interrupted viscosity change no longer breaks the plan (R7 repair, 1 October
2026 candidate).** A coefficient change can be cancelled, or fail, at three kinds
of moment: before the numeric refill starts, during it (including after the solver
core has taken the new coefficients but before the operator records them), and at
the operator's closing cancellation/source check, after the change was accepted.
The same exception type can come from all three, so the exception does not say
which material the operator holds. Before the repair the interface assumed it
still held the previous one and kept the operator whatever had happened:

- after a cancellation or failure during the refill it held an operator that
  [refuses every operation](W07_HETEROGENEOUS_THERMAL.md), so every later request
  was refused, and a tectonic history on this route could not resume;
- after a cancellation at the closing check it held the new material under the
  previous material's label, so the next request carrying the previous material
  skipped the refill and was solved, and published without error, using the new
  viscosity.

The interface now treats its material label as unknown from the moment it asks
for a change until that change returns. If the change raises and left the
operator invalid (its `usable` property is False), the interface closes it,
releases its storage and prepares a new operator from the next request's
material. If the change raises but the operator is still usable, the operator's
own record names the material it holds, old or new; the next request reads the
label back from that record and asks for a change only if its own material
differs. The operator's own rule is unchanged: nothing is rolled back and an
interrupted operator is never used again.

A replacement operator must carry the execution identity of the plan's first
operator. If the source changed in between, the request is refused and a new plan
is needed; a replacement is never adopted under different source bytes.

What this costs and changes:

- The replacement is a cold preparation, not a refill, and the operator's retained
  allowance is released in between. It publishes the same bytes and identifiers
  as an uninterrupted change; the focused tests compare them.
- `statistics()['preparations']` can exceed one. `statistics()['mechanics']` is
  `None` while no operator is held, which can now also happen after the first
  preparation: from a failure that released the operator until a request has
  prepared a new one. A failure that leaves the operator usable keeps its
  statistics, and a new operator's counters start at zero.
- While the source differs from the first preparation, each refused request still
  pays for one preparation before it is refused.
- After a change that raised but left the operator usable, the next request reads
  the operator's descriptor once. It makes no extra coefficient comparison,
  reservation or source check. A budget that is too small to admit a coefficient
  change therefore still serves the unchanged material after a refused change,
  as it did before the repair; a focused test holds this at the smallest budget
  that admits the fixture's preparation and solve.

These inputs can describe successive supplied states. There is no interpolation,
transport, integrated displacement or invented geological history between them.
Joined histories and persistent continuation belong to the next tectonics step.
Nonlinear constitutive evolution remains with the existing explicitly supported
material/thermal/mechanical producers, not an implicit law in this interface.

## Focused verification

- Nine new evolving-flexure methods pass (16.888 s); two affected methods also
  pass after final close/zero-result changes (6.928 s).
- Three retained W04 checks pass after the shared validation/load extraction
  (7.689 s), including the connected variable-property total-reference route.
- Seventeen new regional-input methods pass (5.154 s): independent affine shear,
  hydrostatic pressure, changed force and thermal-gravity controls; source/time/
  support and double-counting refusals; coefficient reuse; immutable results;
  cancellation and shared reservation release.
- Nine shared execution-identity checks pass (2.275 s). Static safety passes
  13 source maps / 41 paths and 31 tests (0.110 s; one environmental skip).

**Repair note (R7, 1 October 2026 candidate).** The counts and times above are
the 23 September record and are not rewritten. The interrupted-viscosity-change
repair adds eight regional-input methods in their own class of
[the same module](../tests/test_evolving_mechanics.py): cancellation at every
cancellation check of a coefficient change, with the previous and the new
material then solved exactly and with the identifiers an uninterrupted plan
publishes; a cancellation, a factorisation failure and an interruption that is
not an ordinary exception (as a keyboard interrupt is) inside the refill, each
followed by a released operator and a replacement; a cancellation just after an
accepted change; a cancellation before the refill and a budget-refused change,
which both keep the operator and still serve the unchanged material; byte parity
between a replacement operator and an uninterrupted change; and two checks that
a replacement is refused under another execution identity. One added
[tectonic-history method](../tests/test_tectonic_history.py) resumes a stored
regional history after a cancellation inside a coefficient refill, with outputs
equal to an uninterrupted run. Cancellations and failures are injected through
cancel tokens and through attributes of the one operator object; the changed
source is emulated as the existing source-drift method does it. These were run
in the repair's scratch candidate on Windows/CPython 3.12.14 only; no timing is
recorded here and nothing is claimed for other platforms.

The unchanged-load/changed-rigidity control explicitly distinguishes the correct
two-equilibrium calculation from the incorrect current-operator load-delta route.
Actual W03 advancement also checks unchanged inventory/thermal/water accounting.
No existing benchmark threshold, source cap or R4.4 hold is relaxed. Historical
reports are not rebound; the two new modules participate in current loaded-code
identity. The production inventory was then 122 files under the 128-file cap; the
later [A3 capacity repair](REVIEW_REPAIRS_2026-09-26.md#a3-follow-on-bounded-source-inventory-capacity)
raised that cap to 512 files.

The bounded runner is `tectonics/tools/check_evolving_inputs.py --report NEW.json`.
It measures three changed regional requests and three changed elastic/load
scenarios, cold versus prepared, including setup, source checks, complete output
hashing and close. Upstream fixture construction and imports are excluded. It
binds all production files, the driver and imported fixture sources; report
overwrite and source changes during measurement refuse.

### Measured preparation reuse

[Current-source Windows evidence](../evidence/evolving-inputs-r1.json) passes
complete output/identity hash parity for both routes. Medians of three alternating
cold/prepared pairs (three changed outputs each):

| Route | Cold | Prepared | Seconds saved | Time saved |
| --- | ---: | ---: | ---: | ---: |
| Regional mechanics, 12 x 12 | 0.8189610 s | 0.5888821 s | 0.2300789 s | 28.0940% |
| Evolving elastic support, 32 cells | 2.7921546 s | 1.4756385 s | 1.3165161 s | 47.1505% |

Regional requests change viscosity and boundary motion at three labelled times.
Elastic requests change supplied rigidity/load scenarios at one real W03 instant;
actual W03 time advancement is covered separately by the focused test. Regional
controls independently check affine velocity and shear stress. There are no
identical latest-result hits. Peak accounted bytes were 25,803,044 (regional) and
5,101,952 (elastic), including declared caller fixture allowances; all reservations
were released. These are not process RSS measurements. The complete evidence run
took 18.721 s. This measures preparation reuse, not whole-generator speed or an
external-software performance comparison.

## Research and existing software consulted

- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/)
  and its [official governing-equation documentation](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html#governing-equations):
  conservative variable-rigidity flexure and explicit load/boundary meaning.
  The paper page/excerpts and documented equations were checked, not a fresh
  complete PDF reading.
- [Landlab's gFlex wrapper source](https://landlab.csdms.io/_modules/landlab/components/gflex/flexure.html),
  `flex_lithosphere`: a current equilibrium is compared with the prior deflection
  before applying a surface change. Atlas uses a fixed-reference total instead of
  silently accumulating output increments. The two-operator formula above is a
  direct mathematical consequence of the linear equilibrium equation.
- [TU Delft Euler–Bernoulli weak/discrete form](https://teachbooks.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html):
  retain the existing C1 Hermite curvature form rather than invent a new stencil.
- ASPECT 3.0 [basic equations](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/basic-equations/index.html),
  [material model interface](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/extending/plugin-types/material-models.html)
  and [static/dynamic pressure](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/methods/pressure-static-dyn.html):
  separate instantaneous mechanics from temperature/composition evolution, respect
  coefficient sampling/dependencies and perform reference-pressure splitting once.

These were documentation/source inspections, not external software executions or
claims of empirical calibration. Existing numerical laws and their component
evidence are retained; this increment verifies their new input/integration boundary.
