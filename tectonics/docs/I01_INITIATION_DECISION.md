# I01: resolve subduction initiation, rather than prescribe its resistance

WORKING NON-CANON. **Selected method and test specification, not an implemented
initiation model or passing benchmark.** [The companion case](../cases/i01_initiation_decision_v1.json)
is not runnable configuration. MC-02 remains open until its benchmark inputs
and comparison allowances below are complete; I07 owns implementation.

## 1. Decision and scope

Use a regional, time-dependent elasto-visco-plastic calculation for initiation.
Do not fit a constant resisting force R to make a desired slab start moving.
The calculation must carry actual incoming rock, temperature, stress and plastic
history as the plate bends and develops a weak path. Its reaction forces and
energy accounts are outputs. An inherited weak interface, its polarity and
initial geometry are declared inputs, not spontaneously generated faults.

This selects the resolved alternative already allowed by
[transitions sections 6 and 10-11](I01_TRANSITIONS.md). The existing scalar
`forced_initiation` control and its receipt stay unchanged: their authored R and
geometry test bounded transfers/accounts, not this resolved mechanism. The new
route does not add that R on top of resolved bending/plastic/viscous resistance.
It neither chooses MC-01's physical separation law nor grants a global plate edit.

## 2. State and constitutive choices

- **Retain elastic memory.** Select the incompressible logarithmic-objective
  branch with fixed, positive material shear modulus G and the D2 creep/plastic
  rates in series. Bending and unloading make stored stress material to
  initiation, independently of the earlier rifting decision. General rotation,
  noncoaxial coupling, transport and energy consistency must be implemented by
  I07. The [coaxial elastic control](I01_ELASTIC_MEMORY.md) is not bending evidence.
  Changing G requires an admitted stored-energy law, not a temperature lookup
  that silently creates or deletes energy.
- **Keep plastic history distinct from total stretch.** Use accumulated equivalent
  engineering plastic shear: `Dkappa/Dt = 2*sqrt(Dp:Dp/2)`, with zero healing for
  this first branch. Here Dp is the symmetric plastic strain-rate tensor. This
  reduces to absolute engineering plastic shear rate in simple shear. It is not
  the signed logarithmic strain or total strain-rate integral. Preserve raw kappa;
  applying the strength filter must not overwrite or repeatedly diffuse it.
- **Use the D2 plane-strain convention**, `Y=C*cos(phi)+P_eff*sin(phi)` and
  `P_eff=max(P_lith+P_dynamic-P_pore,0)`. Pressure is referenced to the actual
  surface/load datum, not an arbitrary incompressible pressure gauge. Select
  zero dilatancy and a positive, declared viscoplastic regularisation viscosity;
  its value is a material/scenario input, not a solver knob allowed to vary with
  timestep. The tensor return must reduce to D2's engineering-shear convention.
- **Prescribe pore pressure explicitly for now.** Select
  `P_pore=lambda_p*P_lith`, evaluated from the current column and common datum;
  lambda_p is a declared material-carried value in [0,1]. Zero means a dry
  control. This is an imposed pressure-ratio scenario, not drainage, fluid
  conservation, dehydration or a pore-pressure evolution model. Full dynamic
  pressure still contributes to P_eff. Intrinsic friction and lambda_p cannot
  both be replaced by an already effective friction coefficient. Scenarios
  needing overpressure beyond this support are refused, not clipped into it.
- **Hold a physical weakening length fixed.** Use D2's Helmholtz-filtered
  kappa_bar with physical ell>0 and explicit filter boundary conditions (no-flux
  at closed boundaries, source history at material inflow). Select linear
  softening of cohesion and friction angle with
  `s=min(kappa_bar/kappa_f,1)`, `C=C0+(Cr-C0)*s` and
  `phi=phi0+(phir-phi0)*s`, with kappa_f>0. The coefficients, ell, initial weak
  zone and regularisation viscosity must be supplied with support/provenance.
  C0>=Cr>=0 and 0<=phir<=phi0<pi/2; angle inputs carry units. These are explicit
  scenario laws, not calibrated planetary defaults.

The Helmholtz length, measured shear-zone width and accumulated slip are different
quantities. At fixed physical transects report the plastic-dissipation participation
width from the [shared diagnostic specification](I01_SEPARATION_DECISION.md),
integrated plastic shear and dissipated work. Zero activity gives undefined width.
For a uniform band only, slip equals width times accumulated engineering shear;
do not apply that identity to a heterogeneous evolving zone without integration.

The fully weakened constitutive branch (`kappa_bar>=kappa_f`) supplies a declared
surface-to-base connectivity diagnostic. Mixed or unresolved support is
UNRESOLVED. Also retain actual material connectivity, integrated strength and cut
traction separately. A spanning weakened band is neither a crack nor permission
to delete material, make a plate split or declare self-sustaining subduction.

## 3. Loading, release and energy ownership

First drive the inherited interface using declared boundary motion. Record the
signed reaction force per unit strike length against cumulative convergence,
not just elapsed time. Subtract/reference external pressure consistently and
record its work separately; a stress-difference column integral is not the
general boundary reaction. Free-surface motion, water loading and basal fluxes
use D5 and [MC-04's boundary/accounts](I01_BASAL_CLOSURE.md).

For the **separate Atlas release test**, fork the exact accepted parent state,
preserving its geometry, thermal state, inventory and elastic/plastic memory.
Replace the imposed *driving* velocity by zero driving traction while retaining
the declared reference pressure and other physical tractions. Do not set velocity
to zero: that clamps the plate. Fix only the same permitted rigid-frame gauge.
Audit every other port, including mantle/basal driving and incoming material;
remaining positive imposed driving work invalidates a claim of gravity-only
continuation. Physical hydrostatic support is not deleted to make a zero-traction
test. The trial branch does not advance or debit the live world's inventory.

Predeclare a finite observation window, material slab support and downward-flux
surface, then check continued sinking and incoming material transfer throughout
that window. Require gravitational energy release and nonnegative dissipation,
with explicit elastic-energy change and all boundary/advective work. A short
rebound driven only by stored elastic energy is not gravity-supported continuation.
The result is continuation **over that window**, never proof of indefinite motion.
Window length, resolution and error bounds cannot be picked after the outcome.

Report one of `FORCED_INCIPIENT`, `UNFORCED_CONTINUATION_OVER_WINDOW`,
`STALLED_OR_REVERSED`, or `UNRESOLVED`. Refinement disagreement, unsupported
material laws, missing ports or an unclosed energy account gives UNRESOLVED.
Reaction force crossing zero while velocity remains prescribed is a useful
diagnostic, but it does not pass the release test. I02 alone commits any admitted
D6 transition, once, using I03/I05 geometry and cohort ownership.

## 4. Predeclared comparison, without claiming missing data

Two comparison tracks must remain separate:

1. **Published-source reproduction.** Gurnis, Hall and Lavier (2004) use a
   compressible explicit Lagrangian FLAC-style method with velocity forcing and
   mesh-linked localisation. Atlas's incompressible, physical-length branch is
   not numerically identical. Their Table 3 case 23 reports a 10/40 Myr pair:
   **left/overriding 10 Myr, right/subducting 40 Myr**, as identified by Figure 13
   and section 4.4. It is not an incoming/overriding ordering. The case uses a
   1000 by 300 km domain, 2 cm/yr on one side, 1 km mesh, weakening strain 0.5,
   no crust, critical convergence 109 km and work 1.17e17 J/m. Those last two
   numbers are comparison targets for a fully reconciled reproduction, not
   generator triggers. Figure 8 compares rates (cases 1/5) and meshes (3/4).
   Their weakening equation acts on angle; do not silently interpolate tan(phi)
   or reuse its strain variable without conversion. These controls are
   velocity-driven, not force-release experiments.
2. **Atlas regularised mechanism verification.** At identical physical ell,
   coefficients, inherited geometry and material history, compare h, h/2, h/4,
   then timestep refinement and a rotated-mesh control. Measure full force-versus-
   convergence curves, peak force and its location, zero-reaction bracket if one
   exists, work, plastic width, weak-path connectivity and release classification.
   Failure to initiate is a valid result, not a reason to weaken the inputs.
   Vary physical ell only in a separately labelled sensitivity experiment.

Run cheap material and load controls first: simple shear for the plastic-history
factor, rigid rotation and unload/reload for stress memory, an analytic elastic
surface-load solution, pressure-datum/pore-pressure checks and energy/inventory
closure. The analytic load comparison must avoid relative division by zero stress
and distinguish the ideal load-edge singularity from interior error. Only then
run the bounded initiation comparisons; no planet or multi-day campaign is needed
to select the method. No initiation simulation is reported by this specification.

Before either numerical track can claim acceptance, fill the companion record's
missing inputs: complete inherited/interface and boundary profiles; thermal and
creep constants with conventions; residual strengths and their source; physical
ell and plastic regularisation; numerical/curve-comparison allowances; and the
release window/flux definition. Lock these before inspecting Atlas outcomes.
Digitised published curves require recorded extraction uncertainty. The paper's
Figure 9 case labels conflict with Table 3, so those cases are not frozen here.
The observed 100-130 km source-case range is not a universal initiation distance.
MC-02 remains open specifically for this benchmark completion, not because the
resolved-versus-authored-R decision is still undecided.

### Recovered source parameters and remaining conflicts

The companion record now preserves the reviewed Table 2 material constants and
Table 3 case-23 values separately from executable inputs. These include cohesion
44 MPa, intrinsic friction coefficient 0.6, shear/bulk moduli 30/50 GPa,
creep exponent 3.05, reference strain rate 1e-15/s, reference viscosity 5e19 Pa s,
viscosity limits 1e18 to 3e27 Pa s, reference density 3200 kg/m3 and thermal
expansion 3e-5/K. Creep reference temperature and case-23 mantle temperature are
distinct inputs even though both are 1400 degrees C in these tables.
Derived conversions are labelled separately; the friction angle is atan(0.6),
not exactly 30 degrees. Finite source bulk modulus is not an incompressible
Atlas parameter. Known scalars alone do not complete a material/thermal profile.

Equation 6 gives
`eta=eta0*(strain_rate_II/strain_rate0)^(1/n-1)*exp[H/(n*R)*(1/T-1/T0)]`.
Its temperatures are absolute, H and R need consistent units, and H's numerical
value and the exact strain-rate invariant remain unresolved. This is a
strain-rate dependence, not accumulated strain.

Important missing definitions remain explicit:

- Paragraph 35 specifies a 1500 degrees C base, while case 23's mantle temperature
  is 1400 degrees C. Figure 5 labels the base Tm but illustrates **case 15**;
  it does not establish a case-23 exception. The basal temperature stays unset.
- Residual strengths, initial weak-plane amplitude/width/depth, initial stresses,
  exact side velocities, diffusivity, gravity and pore-pressure conventions are
  not recovered completely. Right-side driving is an inference, not a recovered
  case-specific function. Homogeneous-case terminal friction and ancestor-model
  constants are not automatically inherited by case 23.
- The paper's accumulated-plastic-strain scalar still lacks a verified tensor
  definition. Atlas uses equivalent **engineering plastic shear**, not J2
  equivalent plastic strain. For isochoric plastic flow, if the source scalar
  were `integral sqrt(Dp:Dp/2) dt`, Atlas kappa would be twice it; if it were
  accumulated absolute engineering shear, they would agree in simple shear.
  J2 equivalent plastic strain would instead be kappa/sqrt(3). These conditional
  identities do not establish which conversion applies to the paper's 0.5.

The complete research extraction record contains 28 graphical force intervals
across Figures 8b and 13a, including the 20 originally supplied in prose. All
are preserved as **reported, not admitted** data. The returned JSON identifies
the source PDF, physical-axis units, curve names, horizontal reading half-widths
and outward-rounded force bands. It does **not** retain panel/tick coordinates,
PDF-to-axis transforms, exact vector selectors, stroke-width/intersection details,
an executable extractor, parser version or unrounded extrema. Thus delivery is
complete, but reproducibility of the extraction is not established. A new bounded
extraction must retain those details without fitting its results to these bands.
Stroke width gives reading uncertainty, not physical uncertainty or an Atlas tolerance.
Case 23's left and right forces stay separate. Sparse readings cannot reproduce
critical work without the source's force definition and integration interval;
the published 109 km must not be forced to coincide with an exact zero crossing.
`benchmark_protocol.reference_curve` and `comparison_policy` therefore remain
null. No solver profile, scientific gate or numerical allowance was invented.

### Implemented input coverage and curve comparison

[`check_i01_initiation_inputs.py`](../tools/check_i01_initiation_inputs.py) now
provides a standard-library-only preparation/comparison tool. It does not import
the native solver, alter its identity or launch a run. The existing companion
record's `benchmark_protocol` stores the outstanding definitions, reference curve
and comparison allowances; it supplies no guessed constants. The known Table 3
numbers remain in `published_comparisons`, not duplicated as admitted inputs.

Each definition records its basis (`SOURCE_EXPLICIT`, `SOURCE_DERIVED`,
`ATLAS_CHOICE`, `INFERRED` or `MISSING`), exact source/locator and review state.
Definitions must describe the material-specific values, units, profiles and
conventions together; they are inert text, never evaluated expressions. Inferred
or unreviewed entries cannot complete coverage. A claimed published reproduction
cannot substitute Atlas choices for missing published inputs. Atlas's separate
regularisation, release and refinement definitions are mandatory only for its own
track. `COMPLETE_FOR_REVIEW` means these documentary groups are populated, **not**
that a solver adapter has checked all equations, dimensions or boundary support.
That physical/configuration admission remains I07 work.

The implemented numerical comparison is more specific:

- Reference and candidate curves explicitly use cumulative convergence in metres
  and signed resistance in N/m (positive resists convergence), not force in N or
  elapsed time. Convergence must increase strictly. No automatic sorting, duplicate
  averaging, extrapolation or sign conversion hides an incompatible input.
- A reviewed policy declares the physical comparison interval, maximum sampling
  gap, force allowance in N/m and signed-work allowance in J/m. There are **no
  default scientific tolerances**. Reference uncertainty is a nonnegative N/m
  envelope at every reference knot with a documented extraction basis; include
  horizontal extraction error conservatively in that envelope before admission.
  The tool does not silently treat missing uncertainty as zero.
- Both curves are piecewise linear. Evaluation uses the union of their knots and
  the fixed interval endpoints, so a candidate excursion between reference samples
  is not missed. Maximum absolute error beyond the linearly interpolated reference
  envelope must fit the separate force allowance. Integrating each segment gives
  signed work; its difference must fit the work allowance plus the integral of
  reference uncertainty. Signed-work cancellation cannot hide a failed force gate.
  Unsampled structure still requires the declared sampling-gap policy/refinement.
- This signed integral is not automatically the paper's critical work: its
  integration limits and force definition must first be reconciled. Peak location,
  zero-reaction bracket, localisation, refinement and force-release/energy tests
  remain separate observations; curve agreement does not prove them.

Prepare a **new** plan before producing a candidate. It snapshots the reviewed
specification and binds the comparison tool/method bytes. The candidate must name
that plan's digest and its own run identity. Changed inputs, allowances, sources
or plan linkage are refused; output creation never overwrites a prior file.
This prevents accidental mismatches, not deliberate rewriting of both records or
proof of chronology. The future runner must retain the pre-run plan identity.

From the repository root, using the existing Python environment:

```text
python -B tectonics/tools/check_i01_initiation_inputs.py inspect
python -B tectonics/tools/check_i01_initiation_inputs.py prepare --spec reviewed.json --output plan.json
python -B tectonics/tools/check_i01_initiation_inputs.py compare --plan plan.json --candidate candidate.json --output comparison.json
python -B -m unittest discover -s tectonics/tests -p test_i01_initiation_inputs.py
```

The current `inspect` result is intentionally `INCOMPLETE` (exit 2); `prepare`
refuses without creating a partial plan. Candidate JSON contains `plan_sha256`,
`run_identity`, and `curve` with `convergence_m`, `force_N_per_m` and
`sign_convention: "positive_resists_convergence"`. Reference curves add
`uncertainty_N_per_m`, `source`, `locator` and `uncertainty_basis`. Policies contain
`interval_m`, `max_gap_m`, `force_allowance_N_per_m`, `work_allowance_J_per_m`,
`basis`, and `reviewed: true`. Unknown fields in these records are refused.
Successful comparison is labelled `PASS_DECLARED_CURVE_ONLY`, scientific
acceptance stays false and release classification stays `NOT_ASSESSED`.

The focused synthetic tests use independent triangular-curve areas and perturbed
curves, check interior peaks, cancellation, uncertainty, sparse/invalid data,
changed plans/sources and refusal/no-overwrite behaviour. They establish comparator
behaviour, not Gurnis reproduction. Tables are limited to 8,192 points and records
to 2 MiB; one union sort and monotone interpolation scans avoid repeated searching
or retaining simulation fields. No speedup is claimed without a matched baseline.

## 5. Efficient implementation and next owner

I07 should reuse the material kernel, current sparse geometry and immutable
accepted-parent checkpoints. A release branch can share read-only parent arrays;
mutable stress/history/geometry and inventory accounts must be branch-owned.
Reuse symbolic sparse structure only while mesh/connectivity/operator support
match; rebuild numerical factors when their actual coefficients change. Never
reuse a stale weakening factor after a moving-grid or length change.

Run independent parameter cases in parallel only within the existing resource
budget; do not parallelise causally dependent timesteps. Store bounded diagnostic
histories and selected restart checkpoints, not a full duplicate of every field
at every iteration. Identity includes laws, material parameters, pressure datum,
loads, initial history, mesh, solver and both forced/release boundary conditions.
These are implementation requirements, not measured speedups.

Next bounded assignment: reconcile the missing benchmark inputs and tolerances,
then implement I07's shared general stress/history kernel before the initiation
campaign. Do not modify Claude's independent separation-law work or create
another standalone implementation of the same material law.

## 6. Sources actually checked

- [Gurnis, Hall and Lavier (2004), Evolving force balance during incipient
  subduction](https://authors.library.caltech.edu/records/p4ehh-qw433), DOI
  10.1029/2003GC000681: original PDF equations 1-6, Tables 2-3, Figures 5, 8 and 13 and
  localisation/forcing discussion, including table/figure caveats. Read-only
  source extraction and selected-page visual inspection were delegated.
  The source-input review also inspected the original Table 2/3 page images;
  a bounded source check verified plate roles, the thermal conflict, unresolved
  residual strengths and equation 6. The case record binds the inspected PDF.
  The research worker additionally inspected Lavier, Buck and Poliakov (2000),
  sections 3.1-3.2, as a cited ancestor method; its defaults were not imported.
- [ASPECT 3.0.0 material parameters](https://aspect-documentation.readthedocs.io/en/v3.0.0/parameters/Material_20model.html):
  full versus adiabatic plasticity pressure and explicit elastic-time handling.
  They support preserving pressure and time conventions, not an Atlas pass.
- [ASPECT elastic line-load benchmark](https://aspect-documentation.readthedocs.io/en/latest/user/benchmarks/benchmarks/elastic_line_load/doc/elastic_line_load.html):
  analytic stress comparison and zero-stress/load-edge error caveats. Latest
  documentation, not a pinned or executed software comparison.
- [ASPECT rheology documentation](https://aspect-documentation.readthedocs.io/en/latest/doxygen/namespaceaspect_1_1MaterialModel_1_1Rheology.html):
  plastic-history versus finite-strain distinctions inspected by the research
  worker. No external software was installed or run.

Atlas's selected laws, pressure scenario and release protocol above are modelling
decisions, not claims that those sources supplied a universally calibrated rule.
For the input/comparison implementation, the Caltech article summary and ASPECT
3.0.0 full-versus-adiabatic pressure and elastic-time entries were checked again.
They reinforce separate convergence, pressure and time conventions; neither
supplies the missing Atlas calibration or an automatic numerical allowance.
Other source-bound methods and historical receipts remain unchanged.
