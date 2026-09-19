# Atlas tectonics simulation plan

**Report 05 | ATLAS-TECTONICS-PLAN-1 | Revision 29 | 19 September 2026**

<a id="3cr3-stress-hardening"></a>

## Current R3 numerical hardening and review workflow

**19 September 2026, version `0.1.0.dev25`, revision 29.** A review found that
`stress_and_dissipation()` could return zero heat after squaring a tiny strain
rate even when the final heat rate was representable. For viscosity 1e100 and
strain diag(1e-170, -1e-170), the previous zero is replaced by approximately
4e-240 in the caller's consistent units. This is an extreme arithmetic test,
not an observed failure of a mantle-scale simulation.

The equations remain `tau = 2*eta*e`, `Q = tau:e = 2*eta*sum(e_ij^2)`.
Mantissa/exponent evaluation avoids premature overflow/underflow in `2*eta`,
`e^2` and the strain invariant. Each component of tau is evaluated independently;
Q is summed at a power-of-two-normalised scale before final range conversion.
Finite subnormal results are retained. A non-zero physical result that rounds to
zero, or a result outside finite binary64 range, is refused explicitly. Zero
strain is still a valid zero response. Symmetry and tracelessness use the existing
64-epsilon relative criterion in normalised coordinates; no physical tolerance,
source data, constitutive parameter or original test is changed.

New tests independently contract exact input floats using Decimal, including
ordinary scales, underflow/overflow counterexamples, subnormal outputs, 3D
invariants, broadcasting, detached arrays and memory refusal/release. Numerical
identities depend on the changed source, so historical records are not repinned.
**R4 remains unstarted.** The current R3 laws and registered physical scope below
are unchanged, and no new mantle model or PDE solver is added.

**Owner review convention:** a request to check whether the current stage is
accurate/optimised authorises fixing verified defects in that stage, not only
listing them. Diagnose, repair, test and report the change without another
approval loop for a scoped correction. It does not authorise a new stage,
scientific-model substitution, tolerance relaxation, publishing, dependency
installation or destruction of historical evidence. Include a copy-ready Git
changelog in each delivery response, and perform meaningful actual-code visual QA.

<a id="3cr3-physical-closure"></a>

## Current: R3 local physical closure

**Package `0.1.0.dev25`.** The selected local constitutive laws, material-point
memory update and an explicit fixed-length regularisation primitive are delivered
in [`physical_closure_r3.json`](../cases/physical_closure_r3.json). These are actual
array kernels and independent numerical tests, not a Stokes/convection solution.
**R4 is next and has not started.** R1's registered source-use approval and strict
source discrepancies remain unchanged. R2's accepted static-input/sampling scope
is retained; W01, W03 and W07 are not declared complete. Historical statuses below
must be read in their dated context.

### Selected models, not a universal mantle law

The order is the constant-viscosity analytical control, the Tosi et al. (2015)
local-law benchmark family, then the Becker & Fuchs (2023) strain-memory family
with a damage-free control. The full published methods and relevant parameter
tables were read before implementation. The exact locations, access limits and
primary-repository corroboration are recorded in the case file. No publication
PDF, ASPECT/CitcomS source, new PB2002 data or new dependency is bundled.

For the Tosi reference, `e = (grad(u) + grad(u).T)/2`,
`eII = sqrt(e:e/2)` and `q = sqrt(2)*eII`. The implemented local formulae are

```
L = exp(-log(contrast_T)*T + log(contrast_z)*z)
P = eta_star + sigma_Y/q
eta = 2/(1/L + 1/P)
```

The Frobenius norm in `P` and factor **two** in the harmonic mean follow the
source; neither is silently replaced by a conventional yield cap. Table-1 cases
1 and 3 use `L` directly. Cases 2, 4 and 5a use the harmonic law, with the named
source values. At zero strain rate and positive sigma_Y its viscosity tends to
`2*L`; zero-stress variants have their separate analytical limit. Case 5b's
periodic-regime survey and all Nusselt/velocity convection comparisons are **not**
run or accepted here. Sources: [Tosi et al., equations 6–10 and Table 1](https://doi.org/10.1002/2015GC005807).

For the selected BF2023 **model-19 local-law subset**, define

```
eta_T = eta0*exp(E/(T+1) - E/2)
f = 1 - Gamma*min(d,dcrit)/dcrit
sigma_y = (a+b*z)*f
eta = min(eta_T, sigma_y/(2*eII))
h(T) = B*exp(-Ed/(T+1) + Ed/2)
D_t d = eII - h*d
```

The registered values are E=40, eta0=1, a=1e6, b=1.51e7, dcrit=10, Gamma=0.9,
Ed=46.1 and B=2.44e9. Gamma=0 supplies the damage-free control. This reproduces
local equations 6–8 and their table values, **not** the paper's full spherical
experiment. Asthenospheric/melt multipliers, continental rafts, empirical 0.1
time rescaling and unspecified absolute viscosity-clipping bounds are absent,
not hidden defaults. This family is not relabelled microphysical grain damage.
Source: [Becker & Fuchs, section 2.3, equations 6–8 and Table 1](https://doi.org/10.1029/2023GC011179).

Damage is an unbounded strain-like history within an explicit computational
limit. Only its **strength effect** saturates; stored damage above dcrit is not
clipped away. Initial damage must be supplied explicitly, including a deliberate
zero. For constant strain rate and temperature over one supplied interval,
`d_new = d*exp(-h*dt) + eII/h*(1-exp(-h*dt))` is evaluated with stable small-h
limits. This is not a spatial advection method or exact integration for varying
thermal/mechanical fields. Existing W02 histories are not silently converted.

### Units, force ownership and R4 boundary choices

Local rheology inputs use T,z in [0,1], with finite parameter/rate/history
limits and binary64 arithmetic. SI conversion requires a named `DiffusiveScales`:
`t0=L^2/kappa`, `u0=kappa/L`, `stress0=eta_ref/t0` and `rate0=1/t0`.
The **diffusive length and depth normalisation are separate required quantities**
(radius versus layer thickness must not be conflated). The 20°C material library
is unchanged and is never extrapolated into these phenomenological laws.
Optional viscosity bounds are explicit numerical choices; every clipped point
is reported, and no floor is treated as measured strength or localisation length.

The local thermochemical reference is the selected constant-property Boussinesq
approximation, with `rho'=-rho0*alpha*(T-Tref)+delta_rho*C`, `f=rho'*g`,
`q=-k*grad(T)` and reference heat capacity `rho0*cp`. Each SI material profile
names its source and validity interval. C is a supplied volume fraction in
[0,1], not a renamed plate or provenance ID. The R4 Tosi control has C=0, no
compositional strength multiplier and H=0. A future continental-strength model
requires its own explicit profile; the BF continental-raft extension is not
silently selected. The viscous stress/dissipation helper takes a traceless
symmetric strain tensor; it refuses compressible input rather than inventing a
bulk law or hiding divergence by automatic trace removal.

The pressure variable for the initial R4 box is dynamic pressure with an
Atlas-selected zero-domain-mean gauge. It is **not** fed into the depth-only
BF yield law, a high-pressure EOS or a tensile/friction law. Free-slip, impermeable
walls, fixed top/bottom temperatures and insulated sides are selected for the
Tosi unit box. These are recorded boundary choices, not an implemented boundary
assembler. Body-force density owns thermal/compositional buoyancy once; no extra
slab-pull traction, prescribed plate motion, latent heat or adiabatic work is
added. Viscous dissipation can be computed separately and included only through
the explicit heat-source argument when that approximation is selected.

**Source-convention issue retained:** the printed Tosi momentum equation's
right-hand-side sign with its stated upward unit vector does not directly match
Atlas's `-grad(p)+div(tau)+rho'*g=0` body-force convention. The density/gravity
implementation in the tagged ASPECT benchmark was checked and supports warm
upward buoyancy. This is not an author-confirmed erratum. The case records the
three exact ASPECT file identities. R4 must verify assembly signs, tensor factors,
pressure normalisation and the full numerical benchmark before claiming its
convection solution reproduces the paper. R3 local-law tests do not settle a
future PDE comparison by omission.

### Fixed length and what remains unaccepted

An **explicit Atlas-selected extension**, separate from both published local
controls, solves `d_bar - ell^2*d_bar_xx = d` on a 1D cell-centred uniform support
with zero normal gradient at its ends. The positive physical ell does not change
with mesh size. The banded SPD operator is tested against independent dense and
analytic modal solutions, including second-order refinement at fixed ell,
constant preservation, integral preservation and non-negativity. Its linear
factorisation is reused; no dense inverse, numerical viscosity floor or repeated
mutation of raw history is used as a substitute for a physical length.

**This operator verification is not a mesh-independent coupled localisation
result.** The primitive is optional and never silently alters the BF reference
input. Raw history and a strength-driving filtered field must remain distinct.
A 2D/3D coupled shear-band model, its boundary behaviour and a physically justified
length require R4/R5 verification before localisation is claimed. The first R4
control is constant viscosity, followed by the unchanged Tosi local laws; it does
not depend on pretending this later gate is already passed.

### Evidence and stage completion

The existing verification runner discovers the new law, execution/storage and
case/visual tests. Obtained results are retained in `evidence/3cr3-tests.json`;
finite matched-work comparisons and length-refinement evidence are in
`evidence/3cr3-measurements.json`. `tools/visual_r3.py` generates actual temperature,
yield, healing, length-response and buoyancy curves with source/result identities.
Visual review is a separate recorded step; plots are not physics acceptance.

The existing [execution reference](OPTIMISATION_REFERENCE.md#3cr3-execution)
specifies native batching, measured serial/thread selection, resource admission,
source-sensitive reuse and exact lossless persistence. **Every implementation
delivery now includes a copy-ready changelog in the accompanying response**,
as well as precise before/after hashes and grouped diffs. Historical case/test/
reference/evidence bytes remain unchanged. AGPL-3.0-only is the selected code
licence; the PB2002 licence and notices remain separate.

## Retained cleanup decisions — revision 27

Package `0.1.0.dev23` fixes interpreter-link portability and clarifies the working
documentation, evidence delivery and visual QA. R1 remains complete only for its
registered uses. R2's static-state/sampling and engineering envelope is unchanged;
R3 has not started. The historical revision 26/25 delivery descriptions below
retain their original scope and evidence. W01 as a whole remains incomplete.

**The Diadem is an explanatory test case, not a generation target.** Atlas should
investigate whether and through what plausible initial conditions, geological
processes and history the authored geography could arise. Different conditions
may produce different worlds; a failure to explain the Diadem is a valid result.
Do not tune global defaults against the target outline, hide a special collapse
or other event in a general law, or treat a fitted history as independent evidence.
Report alternative explanations, unresolved mechanisms and any necessary
non-Earth-like assumptions explicitly. This does not introduce an inverse solver,
start W05, change the R3–R9 ordering or bypass scientific acceptance.

**The current infrastructure/physics ratio is intentional.** Do not optimise line
counts or impose a physics-versus-contract quota. Implement the authorised physical
stage with the correctness, provenance and resource machinery it actually needs.
Optimisation is a tested implementation baseline, not postponed cleanup.

**Post-stage visual QA is required where meaningful.** Generate from the actual
case and current code; record source identities, units and display transformations.
Check geometry, slivers, field discontinuities, unknowns, material/age joins,
antimeridian continuity and both poles. Distinguish renderer bugs from model bugs,
authored inputs from predictions, and observational approval from numerical or
physical acceptance. Never use plausible-looking illustrations as code evidence.
A stage with no meaningful visual observable records that limitation explicitly.
See the [execution and delivery rules](OPTIMISATION_REFERENCE.md#cleanup-execution).

**Licence update (revision 28):** the owner selected AGPL-3.0-only after the
cleanup. It now applies to Atlas-owned code. The pinned reference-data attribution
and licence remain unchanged and separate.

## Historical revision 26 delivery

**Revision 26 — R2 bounded scheduling and spherical candidate indexing.**
The current package is `0.1.0.dev22`. This increment completes the authorised
R2 engineering follow-up without adding geological or thermal/mechanical laws.
The initial-state and sampling scope of revision 25 remains unchanged. **R3 is
next and has not started.** The original R2 case, all earlier tests/evidence and
all original PB2002 bytes, strict discrepancies and scoped-use restrictions are
preserved. The current execution contract takes precedence over historical
statements below that no worker-pool adapter was present.

<a id="3cr2-scaling"></a>

## R2 execution/indexing follow-up: scientific invariants

The new spherical broad phase computes one conservative hemispherical cap for
each unique footprint, indexes enclosing Cartesian boxes on the unit sphere,
and retains exact spherical intersections for uncertain candidates. Caps contain
minor-arc edges and polygon interiors, not only vertices. No longitude seam or
polar shortcut is introduced. Footprints sharing a chart no longer receive the
same ineffective chart-centred enclosure. Repeated footprints reuse one cap and
sweep their disjoint depth intervals. Contacts remain zero-volume; even tiny
positive-area intersections still cause rejection when depths overlap.

This is **not** an arbitrary cross-chart polygon repair or global-mesh certificate.
Where candidate intersection cannot be certified in the existing compatible
conditioned charts, the same explicit refusal remains. Dense mutually overlapping
caps can still require quadratic work; sparse indexing is not a universal
linear-time promise, and the original explicit work/memory envelope still applies.

`PreparedPrecursor` now adapts independent static queries to the existing
`KernelExecutor`. Complete-request frame, ID, geometry and overlap checks precede
cell batching. A global ledger preserves hit/row/work ceilings across batches;
workers cannot multiply them or hide cross-batch material double counting.
Results retain original query order, with translated sparse row/phase offsets.
Serial and threaded routes produce the same numerical arrays and current sample
identity. Changes in actual source/numerical method still correctly invalidate
prepared identities; historical stored arrays can be restored without regeneration.

Automatic execution selects bounded threading for indexed point requests of at
least 262,144 points. Smaller and unindexed point requests remain bulk serial.
Cell threading is implemented and verified, but **the automatic cell default
remains serial because the bounded matched-work comparisons were slower with
threads**. An explicit execution policy can select threaded cell work or a
workload-specific cell threshold; no fictional speed advantage is claimed.
Full state/geometry, capture, in-flight work, retained batch results and final
assembly are admitted. Cancellation drains active jobs before releasing admission.
Binary64, exact unsnapped geometry, fixed per-cell summation and all scientific
error tolerances are unchanged. No new scheduling or persistence subsystem exists.

The focused registration is [`precursor_r2_scaling.json`](../cases/precursor_r2_scaling.json).
Fresh evidence belongs to `evidence/3cr2-scaling-tests.json` and
`evidence/3cr2-scaling-measurements.json`, not to overwritten historical reports.
Timing is descriptive, not a scientific pass criterion. Linux execution does not
establish Windows, whole-planet resources, production readiness or physical realism.
The existing limitations on arbitrary dipping 3D structures, spherical Cartesian-
prior cell means and full W01-to-W02 evolution remain. W01 as a whole is incomplete.

## Historical revision 25 delivery and unchanged R2 scientific contract

**Revision 25 — 3C-R2 initial geological precursor and bounded sampler, 18 September 2026.**
R2 is delivered for the registered **static-input and initial-sampling envelope**
in [`precursor_r2.json`](../cases/precursor_r2.json). **R3 is next and has not
started.** R1's scoped source-use approval, strict discrepancy failure, source
pins, exclusions and holdouts are unchanged. W01 as a whole remains incomplete;
no W03 evolution, rheology or causal plate-generation acceptance is claimed.
Earlier dated status paragraphs below describe their own revisions, not the
current next action. The current package is `0.1.0.dev21` on `remake`.

<a id="3cr2-initial-state"></a>

## 3C-R2 delivered scope and scientific contract

**Plate-independent substrate.** `GeologicalDomain` is a bounded planar area,
conditioned spherical patch, or an entire named reference sphere. It has no
physical plate or region owners. Existing `GeologicalCase` validates its original
materials, formation cohorts, ordered columns, thermal profiles, provinces,
faults and weak zones against this support. Old `BoundaryNetwork`/`SphericalAtlas`
cases and their serialised definitions remain supported. A pre-partition case
refuses selectors that require final plate/region IDs; its computational sampling
cells cannot determine the later physical plate partition.

`PrecursorState` adds one explicit origin assignment per source (observed,
authored, sampled named prior or model-evolved import), separate known/unknown
cooling histories, density/volume bases, optional initial scalar fields and
explicit mantle/slab inputs. An observed label requires a cited record but is not
independent verification; model-evolved input requires its parent-state identity
but does not run that model. Formation times are never replaced by cooling dates.
All times are SI seconds in the case's named epoch; a frame, epoch or depth-datum
mismatch requires explicit conversion, not a renamed array.

**Inherited and deeper structure.** Existing faults/sutures and weak zones remain
independent of plate labels. Exact finite-trace corridor membership is available
at points; overlapping weakness follows the existing explicit precedence without
invented multiplication, averaging or a damage law. Optional slab/mantle records
use named footprints and constant surface-relative depth bands with explicit
body precedence. They can replace column material or extend support below the
lithosphere base. These are supplied initial structures, not dynamically formed,
dipping/curved 3D slabs or inferred slab-pull forces.

**Material knowledge and property conditions.** Exact bindings to the existing
offline Earth-material library retain its full source/condition dependency and
automatically obtain volume bases. Partial records remain partial; source-bound
values cannot be silently rebound or extrapolated. Grain volume, reference
aggregate/matrix volume, explicit pore volume, bulk volume and mass are distinct.
Additional porosity on an already-bulk reference rock is refused. A bulk-reference
row does not assert its unknown intrinsic solid/pore split. Optional
`reference_mass_temperature_k` computes only source-reference-density inventory,
not in-situ mass of hot/pressurised lithosphere or a common pressure assumption.
No new hot/high-pressure or constitutive law is selected by R2.

**Sampling added to W01 stage 5.** `PreparedPrecursor` supplies immutable point
samples and conservative initial inventories for polygon-prism or minor-arc
shell-sector cells. Province overlap is resolved by subtracting higher-priority
footprints before integrating lower-priority material; body bands similarly
replace rather than double-count it. All province candidates are retained at
points. Layer/body intervals are top-inclusive and bottom-exclusive; cell faces
have zero extensive volume. A winning centre point is never substituted for a
mixed-cell average. Unsupported depths, missing required porosity/temperature or
unresolved property requests fail explicitly. Optional unresolved scalar fields
and reference masses carry known masks; convenience accessors refuse unknown
values rather than treating numeric placeholders as physical zeroes.

For planar area A and positive downward depths a,b, V=A(b-a). For a spherical
footprint whose reference-surface area is A on radius R,

    V = A/(3 R²) * [(R-a)³ - (R-b)³]
      = A*(b-a)/3 * [((R-a)/R)² + ((R-a)/R)*((R-b)/R) + ((R-b)/R)²].

The factored form avoids subtraction of nearly equal radius cubes. For explicit
porosity phi, matrix volume is V(1-phi), explicit pore volume is V phi, and each
constituent receives its declared fraction of matrix volume. Existing fractional
round-off allowances are not renormalised: bulk-coverage and phase-volume
residuals are reported separately. Cohort/material indices refer to shared
immutable records, preserving origins and formation dates without rich objects
copied into every cell. Crust and lithosphere thickness remain the existing
separate column quantities.

**Initial thermal/other fields.** Constant and piecewise-linear profiles integrate
analytically with the appropriate radial metric. The existing E04 half-space
initial reference uses bounded quadrature for cell means, with an explicit error
estimate and refusal rather than midpoint fallback. Mean temperature is
volume-weighted temperature, not heat/enthalpy; this adds no thermal evolution.
Temperature offsets must also have a non-negative envelope on requested cell
support; a positive mean cannot conceal potentially sub-zero temperatures.
Stress, damage and prescribed forcing can be explicitly supplied/unresolved
scalar components with units and interpretation, not an inferred mechanical state.

A named prior is the bounded Cartesian cosine field

    f(r) = mean + amplitude/N * sum_i cos(k_i dot (r-origin) + phase_i).

SHA256(name, unsigned-64-bit seed, mode index) supplies fixed per-mode streams.
Amplitude means maximum deviation, not standard deviation; wavelengths are named
feature scales, not an asserted fitted correlation length. Domain/frame/origin
and seed belong to the identity. Planar coordinates are (x,y,depth) metres;
spherical coordinates are geocentric Cartesian metres, without a longitude seam.
Changing support resolution/order does not redraw the field. Planar polygon-prism
prior means are analytic Fourier integrals including holes. Statistical inputs
remain assumptions, not simulated geological events.

**Explicit remaining limits.** General dipping/curved 3D structure and arbitrary
volumetric interpolation remain unimplemented. Spherical point priors and radial
base-profile means work, but spherical cell means of Cartesian spectral priors
are refused. Positive-volume overlap between query cells is refused by default;
when charts cannot certify disjointness, no snapping or blanket sliver tolerance
is substituted. Compatible patches are required, or the caller must explicitly
request non-additive overlapping queries. A set of individually queried spherical
volumes is not thereby certified as a global disjoint mesh. R2 does not close all
W01 stage-5 interpolation, stages 6–7 forcing/evolution integration, the combined
stage-8 gate, or any R3–R9 physics/acceptance work.

**Evidence and acceptance.** Existing T04/T05/T06/T14/T15 and relevant PT families
are credited only for their static age/thermal/volume/restart and execution
obligations, not their whole dynamic scopes. New focused tests include analytical
mixed inventories, shell metrics, formation/cooling distinction, prior
batch/refinement invariance, retained inherited structure, property conditions,
immutable ownership, resource refusal/cancellation, changed-input/source
invalidation, corruption and cold self-contained restoration. The finite
execution card checks 672 points against exhaustive membership and 1/4/16-cell
inventories without source tuning. See [`3cr2-tests.json`](../evidence/3cr2-tests.json)
and [`3cr2-sampling-evidence.json`](../evidence/3cr2-sampling-evidence.json) for
actual runs, commands, source hashes and platform. Passing these checks is
implementation/numerical evidence, not physical plate-formation validation.

Execution/storage details and measured costs are maintained only in the
[optimisation reference](OPTIMISATION_REFERENCE.md#3cr2-initial-execution).
Michael retains local application/commit/push ownership; this delivery does not
modify his PC or publish to GitHub.

---

### Retained revision-24 status and R1 decisions


**Revision 24 — 3C-R1 bounded reference-use sign-off, 18 September 2026.**
Source acquisition, full offline processing and the reference-quality/use review
are complete **for the scopes below**. R2 has not started. No new thermal,
mechanical, sampling or plate-generation implementation is included.

The original strict source-consistency gate remains
`REFERENCE_DISCREPANCIES_REQUIRE_REVIEW` (exit 1). The separate source-use result
is `ACCEPTED_FOR_SCOPED_REFERENCE_USE`: it approves only enumerated observations
from the exact source/protocol and exact audited findings. It does not alter the
strict report, accept a whole-planet mesh or validate any generated world.

- **ON area:** original publication Table 1 confirms 0.00802 sr, so Atlas's
  transcription is correct. Retain table and outline-derived values separately;
  no equivalence, averaging, source replacement or retrospective tolerance change.
  The origin of their difference is not established.
- **MS coincident geometry:** Bird paragraphs 44 and 65 support deliberate
  subsurface representation; paragraph 65 uses the archived BH-side label.
  Retain both source traces and their kinematics. MS ordinary simple-ring
  morphology is unavailable at every scale/phase, even where a diagnostic looks
  plausible. No fictitious two-owner surface edge is created.
- **Polygon-only connectors:** the three exact spans absent from boundary data
  remain unresolved source-representation differences. Neither source is snapped
  and no new motion step is invented. All five incidence-affected edges are
  refused for local two-owner surface use. Nine touching owners are conservatively
  excluded from surface-neighbour-count comparisons.
- **Peru:** no documented closure exception justifies inventing an edge. Retain
  the original open trace and exclude only closed-polygon uses; a derived complete
  global deformation mask is unavailable. The other 12 outlines remain usable.

**Executable acceptance:** the versioned, pinned
[`plate_reference_use_policy.json`](../cases/plate_reference_use_policy.json)
records decisions, source locators, exact finding identities and restrictions.
[`plate_reference_use.py`](../src/atlas_tectonics/plate_reference_use.py)
checks that nothing unreviewed has changed; it prepares shared immutable indexes,
enforces uses, and reports every omission plus remaining coverage. A scoped result
requires all original numerical checks apart from the specifically recorded
non-equivalence finding to remain satisfied; the original strict gate still fails.

The retained inventory is 52 separately labelled areas/native formula checks,
51 ordinary-morphology eligible plates before scale limits, 12 closed orogens,
229 original boundary segments and 5,819 original motion records. Surface-neighbour
counts retain 43 plates. These are different qualified populations, not a 51-plate
world or a complete deformation mask. Ten morphology holdouts remain reserved;
all 52 areas remain exposed calibration. Known source exclusions are never chosen
from candidate errors and must not be hidden in model comparisons.

**R1's finite reference-use review is closed; unrestricted PB2002 source consistency
is not accepted.** Historical/external-model challenges remain explicitly unavailable
for R9. W01 stages 5–8, R2–R9 and W03 do not advance through this review. The next
separately authorised task remains R2. Michael retains local commit/push ownership.
See the [assessment](../evidence/3cr1-reference-use-assessment.json),
[scale coverage](../evidence/3cr1-reference-use-coverage.json),
[regression](../evidence/3cr1-reference-use-tests.json), and the
[maintained optimisation contract](OPTIMISATION_REFERENCE.md#3cr1-reference-tools).

*Revision 23 repair is historical:* baseline/import repair and source-preserving
processing are recorded in `evidence/3cr1-tooling-repair.json`; its strict findings
and original test record remain unchanged. Revision 24 supplies the source-use
decision that was still outstanding at that point.

**Retained historical report header: Report 05 | ATLAS-TECTONICS-PLAN-1 | Revision 24 | 18 September 2026**
**Status: development plan with a delivered foundation; remaining capabilities are proposed, not physically accepted.**

Atlas is vibe-coded, with OpenAI ChatGPT/Codex doing the coding under Michael’s direction. The owner has selected Earth-like mobile-plate tectonics for the intended 1.0 release. Atlas remains world-agnostic; the Diadem is the principal development case, not the definition of the underlying physics.

**Revision 21 — plate-formation implementation plan.** A nine-stage, accuracy-first
sequence now connects observed reference tests, pre-boundary geological state,
selected physical closures, verified regional thermomechanics, process experiments,
spherical dynamics, boundary extraction/history and independent acceptance.
This is a proposed sequence, not a new completed implementation. The named subset
of W03/W07 must be brought forward explicitly to make causal formation claims;
statistical layouts remain priors/controls. No out-of-scope coding is started.
The implemented layout revision and subsequent 15-study literature update are both
preserved in the maintained reference. The
[implementation sequence](#plate-formation-implementation-plan) and
[execution contract](OPTIMISATION_REFERENCE.md#plate-formation-execution-plan)
take precedence over older next-step statements. Current default/source/tests and
historic evidence are unchanged. Michael retains manual commit/push ownership.

**Revision 20 — stage 3C scientific acceptance reopened.** A gap-free spherical
Voronoi partition is not an accepted Earth-like plate-layout model. A separate
PB2002 area-conditioned, connected-layout candidate and independent outline/
Euler-motion checks now exist, with recorded limitations. Size fit is calibration;
full boundary morphology and geological history remain unaccepted. Do not claim
W01's Earth-like generation requirement is satisfied or silently promote this
candidate to a validated default. The original Voronoi API remains an explicitly
limited fixture, not discarded source. The geometry, material library and regional
physics remain useful and unchanged. See the [single optimisation reference](OPTIMISATION_REFERENCE.md#plate-layout-science-correction).
**Current blocker before scientific stage-3C sign-off:** scale-matched multi-plate
outline and kinematic/geological evidence, not merely additional boundary wiggles.
W01 stages 5–8 and W03 remain unimplemented in this correction. The dated summaries
below describe the earlier delivery claims and must be read with this correction.


**Revision 19 — W01 stage 4B, sourced reference materials.** The existing case
schema now has a versioned offline library covering 67 principal rock/mineral/fluid
profiles and seven declared sediment/regolith recipes. Original units, source
locations, ranges, reference coordinates and interval-mean expansion semantics are
preserved. Prepared native property tables, per-capability preflight, exact
stage-4 layer bindings, mixture/assay rules and self-contained library storage are
implemented. This is reference knowledge, not a general high-temperature/pressure
law or a W03 solver. Some profiles are deliberately partial; 44 have density,
specific heat and conductivity together at nominal 293.15 K. The original
instantaneous expansion/heat-source gaps are not hidden by zeroes or secant values.
See [the existing optimisation reference](OPTIMISATION_REFERENCE.md#w01-stage4b-delivery).
**Next is W01 stage 5; W03 remains paused.** No new scientific evolution,
publication or Windows acceptance is claimed.

**Revision 18 — W01 stage 4, geological descriptions.** Typed, immutable initial
material/cohort/layer/thermal/fault/weak-zone records now attach to the validated
regional or planetary geometry. Explicit precedence, complete catalogue references,
unknown-value reporting and self-contained definition restoration are implemented.
The supported stack is surface-relative and piecewise constant by province; the
records specify initial geology, not sampled cell fields or validated constitutive
laws. **Stages 5–8 remain outstanding; W03 implementation remains paused.** See
[the single optimisation reference](OPTIMISATION_REFERENCE.md#w01-stage4-delivery).
Older revision summaries below describe the status at their respective deliveries.

**Revision 17 — W01 stage 3C, generated initial partitions.** The initial world
partition can now be constructed from an explicit sphere, plate count and seed,
with shared topology and working patches generated together. Its unweighted
nearest-site prior and bounded, recorded candidate conditioning are assumptions,
not an observed plate distribution. Authored site inputs and the existing authored
atlas route remain separate and are never randomly replaced. Alternate working
patch layouts preserve intrinsic ownership and boundary geometry. This closes the
explicit 3C subdivision, not stages 4–8 or W01 as a whole. W03 remains paused.
See the [single optimisation reference](OPTIMISATION_REFERENCE.md#w01-stage3c-delivery).

**Revision 16 — W01 stage 3B, closed spherical geometry.** The static world can now
be a closed, conforming atlas of local charts with shared canonical vertices and
edges, globally reconciled ownership/junctions, and plate identities spanning any
number of patches. Stage-3 networks can be joined using explicit shared-vertex
bindings; mismatches are rejected, not automatically welded. This is not an
unrestricted polygon-soup repair algorithm, spherical W02 dynamics or a generated
planet. **W01 stages 4–8 remain outstanding; W03 implementation remains paused.**
See the [stage-3B contract and evidence](OPTIMISATION_REFERENCE.md#w01-stage3b-delivery).
The following revision summaries describe their historical delivery scopes.

**Revision 15 — W01 stage-3 shared boundaries.** A verified static network now
connects the supported planar/spherical-patch regions through single shared edges,
left/right owners, direction-reversal checks, adjacency, cyclic junction sectors
and point-contact distinctions. Same-plate seams stay separate from interplate
boundaries. Batch frame/motion diagnostics and existing snapshot/resource systems
are connected; no velocity, force, subduction polarity or geological sampler is
invented. Spherical networks remain within an explicit common conditioned domain
chart; unresolved reprojection joins and whole-sphere stitching are not silently
accepted. **W01 stages 4–8 remain outstanding; W03 has not started.** See the
[stage-3 entry](OPTIMISATION_REFERENCE.md#w01-stage3-delivery) for evidence and scope.

**Revision 14 — targeted stage-2 correctness corrections.** The independent
recheck identified short-arc cancellation, inconsistent zero-edge validation on
import, nonfinite metre-distance publication and empty-query cancellation. The
corrected delivery adds regression tests for those cases without changing the
original geometric tolerance or broadening hemisphere support. Fresh obtained
evidence is recorded separately from the original stage-2 result. No W03 work,
new physical mechanism or repository publication is part of this change. See the
[existing correction entry](OPTIMISATION_REFERENCE.md#w01-stage2-corrections).
At revision 14, W01 stages 3–8 remained; revision 15 above supplies supported stage 3.

**Revision 13 — W01 stage-2 supported geometry delivered.** The implementation
adds native planar regions/traces, minor-arc spherical patches with conditioned
hemisphere charts, metrics/set operations, shared immutable spatial indexing,
explicit static coverage diagnostics and verified definition persistence. No invalid
shape is repaired or ambiguity resolved by deleting coverage. **W01 remains partial:
stages 3–8 are outstanding.** Stage 3 must construct shared boundaries, orientation,
side ownership and appropriate patch/junction reconciliation. Arbitrary full-sphere
Boolean topology, geological sampling, plate-history forcing and spherical W02
transport are not inferred from this primitive layer. See the existing
[optimisation reference](OPTIMISATION_REFERENCE.md#w01-stage2-delivery).

**Revision 12 — W01 coordinate/time stage delivered.** Stage 1 supplies explicit
spherical/geocentric, planet-centred and regional Cartesian conventions; static and
instantaneous moving-frame transformations; legacy handedness/unit conversion; and
named forward/before time axes with explicit inter-epoch offsets. Cases and tests
are added beside the existing source, with shared resource and identity checks.
**At revision 12, stages 2–8 remained. W03 starts after the required W01
initialisation and supported W01-to-W02 link are complete.** This supersedes the
older W04-first sequencing suggestion. No whole-work-package completion, physical
acceptance, Windows pass or remote publication is implied. The optimisation
reference remains the sole performance reference.

**Revision 11 — regional W02 implementation complete.** The local delivery adds
conservative nonuniform remapping, ALE moving volumes with u-w fluxes, explicit
1D plate/block ownership, split/merge/reassignment/activity events, material marker
maps and self-contained cold restoration. Together with regional/cohort transport
and prescribed transfers, all named W02 responsibilities now have an executable
**1D regional, constant-density, prescribed-kinematics** implementation and tests.
This is not arbitrary-dimensional/planetary topology or physical/geological acceptance.
Future spherical polygons/junctions and force/productivity laws remain W01/W06–W08
extensions; they are not silently claimed by a 1D pass. The earlier W04-first sequencing suggestion is
superseded by revision 12 above. The [existing optimisation reference](OPTIMISATION_REFERENCE.md#w02-completion-delivery)
records measured methods, memory and remaining validity boundaries. Accuracy-first
compiled defaults, W00–W12 dependencies and prior acceptance tolerances are retained.

**Revision 10 — material cohorts and formation history.** The second W02 increment
adds nonnegative partial-thickness transport by cohort, explicit known/unknown
formation times, immutable lineage receipts, and prescribed birth/addition/removal
transactions with per-cohort regional accounts. Higher-accuracy MUSCL/SSP-RK2 is
the default even when upwind is faster. Runtime, memory pressure and cache policy
must not silently lower accuracy; optimise execution of the selected equations.
The existing snapshot store, cache controls and executor are reused. This is
fixed-grid, common-velocity, constant-density volume accounting, not a variable-
density or multi-velocity model. Remapping, moving topology and plate-membership
events remain future W02 work. Physical production/recycling rates, mechanical
closure and W05 terrain acceptance are not supplied by bookkeeping events.
See [cohort implementation and checks](OPTIMISATION_REFERENCE.md#w02-materials-delivery).

**Revision 9 — W02 regional transport delivered.** Open/closed fixed-grid transport,
explicit external accounts, timestep advice, compiled upwind/MUSCL profiles, existing
executor/cache integration and independent refinement checks are now implemented.
This is one W02 increment, not all material/event history or a W05 geological pass.
No prior numerical kernel, fixture or tolerance was altered. Current tests and
selection limits are recorded in the existing optimisation reference's
[W02 section](OPTIMISATION_REFERENCE.md#w02-regional-delivery).

**Revision 8 — combined resource acceptance.** Item 12 now adds shared parent/component
byte admission, retained-state lifetimes, pooled CPU/worker allowances and a combined
resource/platform acceptance route. The local Linux run passes the regression suite
and bounded compute/cache/compression/incremental-recovery combinations. **Windows
acceptance is still pending an actual local run.** Item 1 remains skipped; items
2–11 and the scientific K/M modes, equations, parameters, W00–W12 and T01–T16 remain
intact. See the [existing optimisation reference](OPTIMISATION_REFERENCE.md#combined-acceptance)
for evidence and limits. These are engineering foundations, not geological acceptance
or completion of the coupled tectonic model. Two maintained documents remain the
policy: this plan and the optimisation reference, with case/tests beside code.
No new general roadmap or publication is part of this delivery.

**Navigation:** [Scope](#recommended-architecture-and-10-scope) · [State and interfaces](#scientific-state-and-interface-contracts) · [Equations](#equation-plan-and-gaps-to-close) · [Work packages](#work-packages-and-dependency-gates) · [Coupling](#coupling-timestep-and-state-acceptance-policy) · [Execution and optimisation](#numerical-and-computational-design) · [Validation](#verification-physical-validation-and-decision-rules) · [Milestones](#milestones-decision-ownership-and-risk-control)

<a id="plate-formation-implementation-plan"></a>

## Plate formation correction: implementation sequence (18 September 2026)

**Status: proposed implementation plan; no new solver, scientific pass or default
change is delivered here.** This section governs the reopened stage-3C scientific
work and supersedes conflicting older next-step sentences. It preserves the
existing geometry, material library, regional W02 work, the PB2002-conditioned
candidate and its obtained evidence. Neither Voronoi nor the area-conditioned
candidate is promoted from a prior/control to accepted dynamics.

### Objective and scope boundary

Build an initialisation and evolution path in which material/thermal structure,
inherited weakness, forcing, deformation and plate geometry are consistent. The
normal accuracy policy is unchanged: choose the scientifically appropriate model
and numerical error requirements first, then its fastest verified implementation.
No exact universal plate count, Earth-outline copying, random-wiggle score, or fit
to the Diadem's desired mountains is an acceptance criterion.

Separate origin from execution: a **reference/statistical initial state**, a
**prescribed-kinematic history**, and a **dynamically produced state** make different
scientific claims. They are not fast/slow backends of the same equation. Preserve
the existing K/M model modes. Record origin independently; an M-mode calculation
may start from an explicitly statistical prior. Selecting a mature starting epoch
does not require simulating a planet from a magma ocean.

**Sequencing consequence:** causal boundary formation requires thermal and
mechanical capabilities that belong to W03 and W07. The proposal is to bring
forward only their named benchmarkable subset below, credit it to those work
packages, and reuse it later. This does not mark W03, W07 or planetary W02 complete.
No W03/W07 coding or large simulation is authorised by this planning-only update.
W01's remaining sampler and integration responsibilities are not silently erased.

### Scientific responsibilities and numerical baseline

Use an explicitly scaled, incompressible, inertia-free thermochemical reference:

\[
\nabla\cdot\mathbf u=0,\qquad
-\nabla p+\nabla\cdot(2\eta\dot{\boldsymbol\epsilon})+\rho'\mathbf g=0,
\]
\[
\rho_0c_p(\partial_tT+\mathbf u\cdot\nabla T)=\nabla\cdot(k\nabla T)+Q,
\qquad
\partial_t C+\mathbf u\cdot\nabla C=0.
\]

Here \(\mathbf u\) is velocity, \(p\) the selected pressure variable,
\(\dot{\boldsymbol\epsilon}\) symmetric strain rate, \(\eta\) viscosity,
\(\rho'\) buoyancy density contrast, \(T\) temperature, and \(C\) composition.
\(Q\) is the heating included in the selected approximation, in W/m³. Declare
Boussinesq/reference-density assumptions, pressure reference, boundary tractions,
thermal boundaries and nondimensionalisation. Do not present this reference as a
compressible, phase-changing, elastic or full free-surface model.

Start with constant-viscosity verification, then reproduce one published
viscoplastic specification before adding memory. The revision-28 local implementation now selects the BF2023 model-19 subset
described [above](#3cr3-physical-closure). The original design direction was
strain-weakening with temperature-dependent healing in the Fuchs/Becker family
(PF-C03/C04), with a damage-free control. In general form,
\(D_t d=S_d-\mathcal H_d\); this is an interface, **not an already selected
constitutive law**. Its exact published source/saturation/healing and strength
coupling, units, numerical regularisation and supported parameter ranges must be
transcribed and independently checked in 3C-R3. Do not relabel it the distinct
microphysical grain-damage theory in PF-C02.

### Nine implementation stages

| Stage | Implementation and deliverable | Acceptance before its dependent claim |
| --- | --- | --- |
| **3C-R1 — Reference data and success criteria (scoped reference uses delivered)** | Extend the existing reference/diagnostic modules to full accessible plate outlines, boundary-step motion and deformation-region data. Preserve raw-source identities, licence, coordinate/time conventions and known uncertainty. Reserve independent regions, reconstructions or model versions for tests not used to choose parameters. Compare at declared physical scales and per-plate resolution. | Check source transcription, sphere-area and perimeter calculations, signs and units against independent values. Register each metric, scientific question, tolerance derivation and holdout split before tuning. PB2002 area-fit values are calibration, not held-out validation; another derivative of the same map is not independent evidence. |
| **3C-R2 — Initial state before final plate labels (bounded static delivery in revision 25)** | Extend W01's existing geological records with an explicit pre-partition description: continental/oceanic structure, ordered layers, thermal initial state, known formation versus cooling history, inherited weak zones and supported mantle/slab structure. Implement the bounded portion of stage-5 sampling needed to populate test meshes. Distinguish observed, authored, sampled-prior and model-evolved values. | No circular dependency requiring final plates before specifying their geological substrate. Missing thermal/stress/damage state is not filled by unlabeled noise. Seeded fields have documented amplitudes/scales and stable streams; mesh refinement does not redraw the prior. Authored states remain unchanged. |
| **3C-R3 — Freeze the physical closure (local laws and 1D length primitive delivered)** | Select one reference rheology, then one memory model; document viscosity, yield, healing, composition, heating and surface/boundary choices. Obtain complete methods/supplements before reproducing a paper. Give each law a versioned parameter profile and finite validity envelope. Separate body forces from prescribed tractions to avoid double-counting slab pull or other forcing. | Hand-calculated constitutive values, reference-unit conversions, temperature/pressure/strain-rate limits, zero-damage and healing-only solutions. The 20°C material catalogue is not a mantle-creep model. Localisation needs demonstrated mesh-independent regularisation; a numerical viscosity floor is disclosed, not treated as measured material strength. |
| **3C-R4 — Verified thermal/mechanical core** | Build the selected W07 structured staggered finite-volume pilot with W03 heat evolution and conservative composition transport. Begin in a 2D box: constant viscosity, then variable viscosity/yielding and the applicable Tosi benchmark cases (PF-C14). Reuse existing numerical interfaces/budgets; a small native sparse direct solution is an independent reference, with preconditioned native iterative solves for larger verified workloads. | Manufactured velocity/pressure, boundary/pressure null-space handling, mass/divergence and heat accounts, space/time/nonlinear convergence and published benchmark diagnostics. Two-dimensional success establishes a solver component, not planet-wide shapes, trench curvature or transform segmentation. |
| **3C-R5 — Process experiments, not decorative contours** | Test weak-zone reactivation against healed/undamaged controls; inherited-structure rifting; segmented spreading and transform development; one-sided subduction with an appropriate surface/interface treatment; curved-trench fragmentation and small-block formation. Use 3D regional geometry when the claimed feature varies along strike. Run paired cases that change one causal ingredient rather than fitting every output. | Each process reproduces its selected independent benchmark/analogue constraints and remains stable under refinement and rotated mesh orientation. Do not require damage to have one universal effect, place a plume beneath every ridge, infer polarity from convergence, or count a 2D cross-section as an along-trench fragmentation test. A failed family remains unsupported. |
| **3C-R6 — Spherical dynamics and plate identification** | Extend the verified formulation to a coupled 3D spherical shell, using globally consistent metric terms and pressure/interface treatment. Existing surface patches are output geometry, not a ready volume mesh. Recover coherent surface regions from independently calculated velocity/strain/damage fields, and fit Euler rotations to candidate interiors. Keep distributed deformation explicitly represented. | Spherical benchmark and rotation/seam tests, conservation, parameter and resolution sensitivity, declared spin-up and sample-selection rules, rigidity residuals and stable segmentation thresholds. A warm-up ends by registered diagnostics, not because one image looks Earth-like. Never prescribe Euler poles then claim recovering them proves independent rigidity. |
| **3C-R7 — Shared geometry and causal event history** | Convert supported field-derived boundaries into the existing shared-edge atlas; maintain one edge, two sides and consistent junctions. Fit boundary/junction velocities subject to the selected kinematic rules. Track persistent material, weakness, plates and events separately; record splits, merges, reactivation, accretion/export and candidate rejection. Use conservative multidimensional transfers where needed; reuse W02 contracts, not its 1D equations under a spherical name. | Underlying surface coverage remains complete without forcing every cell into a perfectly rigid plate; deformation zones do not vanish as polygon gaps. Boundary extraction has a spatial error budget and does not move material. Junction compatibility is stricter than the telescoping sum of relative velocities. Preserve origin/energy/history through events and cold restoration. |
| **3C-R8 — Initialisation and W01 integration** | Supply a named starting-epoch workflow: load an authored/reconstructed state, use a declared statistical candidate, or evolve an accepted dynamic precursor and select its state by the recorded rule. Any faster reduced generator must be calibrated on process results and checked independently before adoption. Map the resulting geology, supported motion and fields through W01 sampling into appropriate regional W02 scenarios. | No manual stitching, unknown-as-zero state or regenerated world on restore. Identical provenance yields the agreed reproducibility. Exact plate-count requests are only supported where the selected origin model warrants them; dynamic mode does not forcibly merge bodies to hit a UI number. An initialisation pass is not complete global material/thermal evolution. |
| **3C-R9 — Independent acceptance and selected default** | Run predeclared ensembles, holdout-data challenges, mesh/time/parameter sensitivity, controls and ablations, then combined execution/cache/storage/restoration/platform checks. Record accepted regimes and unresolved failures in the two maintained documents and obtained case records. | Keep calibration, numerical verification, physical validation and fictional compatibility separate. No universal percentage realism score; no pass from a lone attractive map or small global-average error hiding lost microplates. Promote the appropriate accuracy-first optimised recipe only for supported regimes. Report platform/resource limits and retain explicit verification/control paths. |

The R1 delivery is limited to the reviewed present-day PB2002 uses described in
revision 24. It does not satisfy the independent-model or historical challenges
reserved for R9. Those unavailable observations cannot be filled from modern Euler
poles or another reformat of PB2002.

### Required observations and failure tests

Use multi-scale area distribution, compactness, elongation/concavity, turning and
segmentation by boundary type, topology and adjacency, small-plate position relative
to margins, intraplate deformation, relative motion, weak-zone persistence,
reorganisation and heat/material accounts. Plates and broad deformation zones are
not interchangeable labels (PF-C15). Total perimeter must ignore computational
seams. Sampling density must not improve a morphology score by adding vertices.
A plate population is temporally variable; do not fit exactly one modern spectrum
(PF-C10). Held-out observables must not have already selected the same parameters.

Numerical thresholds come from the declared equations, source precision and
refinement study, not convenient post-hoc tolerance changes. Use at least three
resolutions for appropriate convergence cases, vary time step independently, and
keep geometric tolerances distinct from physical uncertainty. Model ensembles and
steady/transient sampling windows are registered before scoring, including failed
seeds and error bars. Data versions with shared ancestry are sensitivity challenges,
not additional independent samples.

### Stop points and package accounting

* **After R1–R3:** scientific specification and test inputs ready; no claim of
  simulated boundary formation. These are the immediate next coding increments.
* **After R4–R5:** verified solver and individually supported process behaviours;
  no whole-planet acceptance from regional results.
* **After R6–R9:** a bounded planetary formation/initialisation route can be accepted
  only for the regimes, material laws, resolution and data challenges it passed.

R2/R8 close relevant portions of W01 stages 5–7; their unimplemented responsibilities
remain visible. R3–R6 credit the actual W03/W07 subset and relevant W06/W08 process
work rather than duplicate those modules. W03 sediment compaction, full W04 loading,
other W08 regimes, W09 surface processes and production integration remain separate.
W11's relevant work is performed within every stage; there is no later blanket
optimisation pass. The existing one-dimensional W02 completion boundary is retained.
The proposed sequence is larger than a polygon patch because causal formation is
larger than geometry; progress reports must not disguise that fact.

### Execution and delivery

The [formation execution contract](OPTIMISATION_REFERENCE.md#plate-formation-execution-plan)
assigns optimisations and checks to each stage. No new general cache, scheduler,
compression format or report is required. Comments beside code must cover equations,
units, assumptions, ownership, invalidation and failure cases. Case contracts/tests
stay next to implementation. Deliver one copy-ready update relative to the known
remake baseline, preserving unrelated files; Michael commits and pushes manually.

This document update changes no numerical source or tests, installs nothing,
executes no geological case and makes no claim to access the PC or update origin.


## Executive decision

Develop a **physically tested, multiscale tectonics system**, not a mountain-placement algorithm and not a collection of seventeen integrated software packages. Use a shared description of the world, plate history and material accounts, with two explicitly different ways to calculate deformation: prescribed kinematic experiments and regional mechanical calculations. Couple only the surface and thermal processes required to interpret each experiment. Design for efficient execution from the outset. Verify any enabling acceleration against an appropriate numerical reference while the physical investigation proceeds; later optimise and scale accepted behaviour at matched error. Build production interfaces only after the relevant scientific and resource gates.

The first delivered foundation contains restricted versions of the **small mathematical reference suite**: rotations and boundary signs, periodic conservative thickness transport, analytical cooling and uniform periodic load response. Continue from those kernels rather than rebuilding them; they do not complete W01–W04. The first coupled mechanism should be prescribed regional extension plus a separately checked vertical response. This is a recommendation for an informative test, not a claim that extension explains the Diadem. Shortening, shear and subduction must receive their own subsequent tests.

**What this plan selects:** architecture direction, scientific responsibilities, candidate equation families, work order, required evidence, optimisation priorities and release gates. **What it does not select:** calibrated Earth/Diadem parameters, a complete mechanical closure for every regime, a production machine, runtime budgets, an external solver dependency, or permission to execute any case. Parameters and unresolved constitutive choices have named decision gates rather than hidden defaults.

The full 1.0 tectonics scope below is deliberately broader than the first prototype. If a required regime remains unsupported, the deliverable must be a labelled research preview or an explicitly narrower capability release—not an unqualified claim of complete Earth-like tectonics.

## 1. Basis, constraints and intended result

### 1.1 How this plan uses the pre-studies

Reports 01–03 supply the modelling, optimisation and implementation assessments. Report 04 supplies the stable identifiers **P01–P15**, **E01–E28**, **F01–F17** and **O01–O17**. They are retained here; they are not new Atlas module names or a replacement for its eighteen categories. In particular, Report 04 identifies gaps in yielding, free-surface treatment, mass creation/consumption, magmatic transfer and water/sediment closure. This plan treats those gaps as work, not as capabilities already supplied by the equations. [[R01](#research-basis); [R02](OPTIMISATION_REFERENCE.md#scientific-methods); [R03](#research-basis); [R04](#research-basis)]

The repository baseline described in those studies is `7d0e707a576fe08b9bcb816466a0a8fb5f115808`. This is **not a fresh audit of GitHub or the Windows workspace**. The studies identify an active tectonic snapshot adapter, existing geometry/route reuse, a native 256-cell domain and a fixed-quantum material ledger. Preserve them as historical implementations with their own meanings; new experiments must not silently alter their bindings or relax their limits. [[R03](#research-basis); [A01][url-001]; [A02][url-002]; [A04][url-003]; [A06][url-004]; [A07][url-005]]

The original consolidation changed documentation only. Later numbered implementation increments above record their own source changes and obtained checks; they do not repin historical evidence or imply Windows integration. Any companion repository-documentation publication is recorded separately; checking documents is not running the model. Execution references PS01–PS08 and language references LS01–LS05 are retained with the optimisation reference; no scientific-software re-audit was performed.

**Implementation status supplement:** the historical pre-study baseline above is preserved. The subsequent remake foundation at `11317165b7e2aeab7201a1fe3e3f646cb640d51e` provides the restricted kernels listed in the optimisation reference’s current-baseline section. This does not complete W01–W04 or validate real terrain. The current update changes documents, not that implementation.

### 1.2 Owner requirements retained

| Requirement | Consequence for this plan |
| --- | --- |
| Accuracy is the default | Keep the most accurate supported selected scheme as normal; optimise it rather than selecting lower order/precision for speed. Refuse an inadequate resource budget instead of silently downgrading physics or accuracy. |
| Earth-like tectonics for 1.0 | Assume a mobile lithosphere with terrestrial-style physical relationships; do not require a model of the origin of plate tectonics. |
| Physical parameters are not buried in solver code | Use explicit, versioned Earth-like profiles in 1.0; reserve user-facing customisation for later without making it a release obligation. |
| Atlas must not require the Diadem | World identity, radius/geometry, material parameters, constraints and initial conditions are inputs. History A is a compatibility example, not a universal template or independent validation case. |
| Eventual whole planets | Establish spherical rotation and area conventions early. Full planetary physical execution is a later scale gate, not a claim made by passing regional cases. |
| Resolution as fine as feasible, including 1 m | Keep evidence, process, exchange and output spacing separate. No fixed 100 m/10 m product ceiling; no promise of metre-scale whole-planet physics. |
| Realism before production wiring | Independent equations and bounded mechanism tests precede the end-to-end production chain. Interfaces needed to test a mechanism are allowed in its future scope; production integration remains later. |
| Learn methods, do not integrate packages now | Reuse scientific ideas and documented algorithms as references. Any future source, data, library or database adoption needs a separate dependency/provenance and permission review. |

### 1.3 What a successful tectonics result contains

The tectonics product should provide evolving plate/block geometry; deformation and displacement; crustal/lithospheric state; surface and subsurface material histories; specified thermal and magmatic consequences; and the uncertainties, applicability limits and accounts behind them. A terrain view must identify what elevation came from tectonics, loading, thermal support, erosion, deposition or generated visual detail.

A successful numerical run is not necessarily geologically plausible. A geologically plausible unconstrained case is not automatically compatible with the Diadem. Code correctness, numerical accuracy, physical adequacy, world-design compatibility and canon approval remain distinct judgements.

<a id="current-implementation"></a>

### 1.4 Current implementation and document maintenance

**Current local engineering status:** the item-12 package builds on local items
2–11 (remote base `0590774b…`). Shared resource and combination tests are Linux-
accepted within their measured envelope; Windows is unverified. The next scientific
work now continues from delivered open-boundary transport towards the remaining
material-history/creation work and physically defined loading.
Continue using the optimised defaults, and carry resource/ownership tests into each
physical increment. No statement here means a new remote commit or a passed W05.


Verified documentation baseline: `remake` at `612d53eba495202101a8e638578f47fb37752649`; delivered numerical foundation: `11317165b7e2aeab7201a1fe3e3f646cb640d51e`. The [module README][url-006] and [delivery record][url-007] are the source of this status, not a new run.

| Work package | Delivered portion | Still outstanding |
| --- | --- | --- |
| W00 | Synthetic foundation case and verification rules. | The next physical case’s complete inputs, observations and acceptance decisions. |
| W01 | Geometric/declarative stages 1–4B (including 3B/3C): optimised coordinates/time, corrected geometry, shared/global boundaries, seeded partitions, and typed geological descriptions with explicit evidence, layers, thermal initial conditions and precedence, plus the sourced material library and condition-aware mixtures. | Stage-3C Earth-like scientific acceptance is reopened; a reference-conditioned candidate exists but its full morphology/history is not accepted. Stages 5–8: initial-condition sampler, motion-to-regional adapter, W01→W02 workflow and combined acceptance. Static geometry/descriptions do not supply evolving spherical material physics. W01 remains partial. |
| W02 | Regional implementation complete: cohorts/history, prescribed transfers, conservative nonuniform remap, ALE u-w motion, complete interval ownership, split/merge/reassignment/activity, marker maps, direct snapshot restoration and existing executor/cache integration. | Physical/geological acceptance is not implied. General 2D/spherical junctions and predictive source/force laws require W01/W06–W08 extensions. |
| W03 | Analytical half-space temperature reference. | Evolving thermal solver, finite plate and compaction. |
| W04 | Uniform periodic 1D discrete flexure. | Physical load construction and further geometries/boundaries. |
| W05–W10 | Planning and method studies only. | Coupled mechanisms and independent physical validation. |
| W11 | Local items 2–12 and W02-specific native, allocation, accuracy-cost and combined-path checks; bounded Linux evidence. Item 1 explicitly skipped. | Windows acceptance, future mechanisms and their physical scale-transfer/world-scale evidence. |
| W12 | Planning only. | Production integration and release acceptance after scientific and scale gates. |

**Two maintained documents:** update this plan for scope, equations, dependencies and acceptance; update `OPTIMISATION_REFERENCE.md` for execution, storage, language and method detail. Word files are reading editions of the same Markdown content, not extra authorities. Keep change history inside these documents/Git history; do not create another supplement, general review guide, source-register file or performance-plan copy for routine findings. Case specifications and obtained test evidence stay next to code and are not competing roadmaps.

Previous versions and scientific pre-studies remain historical evidence. They are not deleted from prior chat attachments or restated as newly verified. Retired optimisation pages are superseded by the reference; no numerical source or historical evidence bytes are rewritten by consolidation.

<a id="recommended-architecture-and-10-scope"></a>

## 2. Recommended architecture and 1.0 scope

### 2.1 Three scientific layers, not seventeen software integrations

**World/history layer.** Holds geometry, finite rotations, shared boundaries, events, material identity and initial geological/thermal descriptions. It can replay an authored history or propose a constrained generated history. Generated proposals must pass structural and physical admissibility checks; random rotations and arbitrary polygon repairs are not a validated tectonic model. GPlates, GPlately and World Builder are the method references. [[S01][url-008]; [S03][url-009]; [S04][url-010]; [S06][url-011]]

**Regional process layer.** Applies an explicitly chosen deformation model to a named domain with external boundary information. Begin with reduced kinematics where that answers the question. Use a selected mechanical formulation when stress, strength, localisation or slab/overriding-plate response is part of the claim. LaMEM, ASPECT, Underworld and pTatin3D are alternative references—not four solvers to run in sequence. [[R01](#research-basis); [S08][url-012]; [S10][url-013]; [S13][url-014]; [S16][url-015]]

**Surface/history layer.** Converts rock movement, physical loading and the necessary water/sediment processes into surface elevation and stratigraphy. Track material budgets and geological histories independently of rendering resolution. gFlex, pyBacktrack, FastScape, selected Landlab components, Badlands and goSPL supply the main method references. [[R04](#research-basis)]

### 2.2 Two deformation modes, with no silent substitution

| Mode | Recommended role | Mandatory statement |
| --- | --- | --- |
| **K: prescribed kinematics** | Initial reference cases and supported reduced geological scenarios: motion or fault displacement is specified, while transport, thickness and defined vertical consequences are calculated. | Motion is prescribed or generated by a stated scenario rule; it is not predicted from mantle forces. |
| **M: regional mechanics** | Questions needing stress/strength-dependent deformation, subduction-wedge flow, shortening, distributed strain or localisation. | Geometry, rheology, initial state and mechanical/thermal boundaries close the equations; their adequacy needs separate evidence. |

Mode M may take boundary velocities from Mode K. In that configuration K supplies boundary forcing, not a second displacement to add to M’s solution. Likewise, flexure may supply a missing load response only when that response is not already represented by the mechanical calculation. Every contribution has one physical owner.

**Candidate numerical baseline for M:** a two-dimensional, inertia-free viscous/Stokes calculation on a structured staggered grid, with explicit material fields and conservative transfers; compare it with a compatible mixed finite-element alternative at the design gate. Start at constant viscosity before adding thermal coupling and pressure-sensitive yielding. This is a proposed small reference formulation, not a decision to recreate LaMEM, approve all its laws or restrict eventual three-dimensional modelling. [[S08][url-012]; [S10][url-013]; [S16][url-015]]

### 2.3 Release scope: required, conditional and deferred

| Scope | Planned 1.0 treatment |
| --- | --- |
| Kinematics and topology | Required: regional translations/rotations, spherical rigid rotations, shared boundaries, reference frames, time-dependent stages and explicit supported boundary events. |
| Material creation and recycling | Required: ridge birth, age, tracked subduction/export, accretion and plate/crust identity separation, with explicit source/sink accounts. |
| Extension and spreading | Required: continental thinning, normal-fault kinematic consequences, breakup when selected, ocean-crust creation and cooling; no invented height bands. |
| Convergence | Required: supported subduction and continental-shortening/collision cases, clear regime transitions, material budgets and defensible vertical response. |
| Shear | Required: transform/oblique motion and supported local transpression/transtension; pure shear must not invent crustal mass or blanket uplift. |
| Thermal and support response | Required where causally relevant: cooling/heating, density/strength effects, isostatic/flexural support and sediment compaction/loading without double counting. |
| Magmatism | Required reduced accounts where oceanic crust, arcs or volcanic construction are claimed; source, rate, emplacement geometry and heat treatment must be justified. |
| Surface evolution | Required for claims about final landforms: adequate runoff/routing, erosion, deposition and loading for the selected regime. Full climate need not be solved simultaneously. |
| Special events | Conditional: back-arc opening, fault reactivation, post-collision extension, terrane accretion, hotspot tracks and caldera collapse. A scenario invoking one needs its tested closure. |
| Specialist diagnostics | Optional: elastic dislocation diagnostics, phase-equilibrium property tables and thermochronometric observations. They must answer a needed question, not expand scope automatically. |
| Beyond the baseline | Deferred: self-organising global mantle convection, spontaneous initiation of every fault/subduction zone, individual earthquake rupture/waves, full reactive two-phase magma transport, non-Earth-like tectonic regimes and universal metre-scale mechanics. |

Complete planetary execution is a separate capability claim even if spherical mathematics is present. Whether it is included in the eventual 1.0 release should depend on its evidence and resource gate, not on a new restriction of the owner’s long-term product intent.

<a id="scientific-state-and-interface-contracts"></a>

## 3. Scientific state and interface contracts

### 3.1 State to represent explicitly

| State group | Minimum content | Main consumers |
| --- | --- | --- |
| World and run profile | Geometry/radius, gravity, units, reference frame, time convention, scenario, boundary extent, selected laws and validity envelope. | Every process. |
| Plates and blocks | Stable identity, polygons/shared sections, material membership, finite-rotation stages, rigid versus deforming status. | Kinematics, birth/recycling, regional boundaries. |
| Boundaries and faults | Side identity, orientation, boundary velocity, type/activity intervals, polarity, dip/slip geometry as needed, junctions and event lineage. | Regional deformation, subduction, hazard-facing outputs. |
| Crust and lithosphere | Distinct thicknesses, composition/material classes, density/strength inputs, temperature or justified reduced thermal state. | Mechanics, loading, material accounts. |
| Conserved material | Material/origin IDs, represented mass and support volume/area, phase/class, sources/sinks, split/merge transactions. | All creation, transport, erosion and deposition. |
| Geological history | Formation time, deformation, burial/exhumation and temperature history at the resolution required by a selected diagnostic. | Geological products and validation. |
| Solver fields | Velocity, pressure/stress, strain rate and accumulated strain, thermal fields and solver boundary/reference data. | Mechanics and state update. |
| Surface and load state | Rock surface, sediment thickness, water/ice load where relevant, compaction state, reference column and prior support response. | Vertical response, hydrology and terrain. |
| Numerical state | Mesh/partition, timestep, transfer operators, tolerances, physical versus numerical regularisation, cache identities, accepted-step receipt. | Execution and reproducibility. |

A passive tracer is not automatically a parcel with conserved mass. A birth age is not a cooling age. A computational node is not a permanent geological entity. Intensive-property interpolation is not conservation of an extensive quantity. These distinctions are explicit in the pre-study’s material and diagnostic links. [[R04](#research-basis), P02/P05/P11/P14]

### 3.2 Minimum interface contract

Each exchange carries the quantity, units, sign/frame, spatial support, physical start/end time, intensive/extensive classification, material/source identities, uncertainty or applicability status, and whether the result is supplied, generated, numerically derived or independently validated. An interface also names the receiving approximation: converting a three-dimensional stress field into a reduced load is not a neutral file conversion.

A future step result should conceptually contain a candidate state, material and energy transfers, explicit surface contributions, events, unresolved conditions and error diagnostics. The accepted state remains unchanged until validation succeeds. This is a data contract for future coding—not a requirement to add a new general scheduler or plugin framework.

### 3.3 Canon and generated detail

Keep authored constraints in a separate world profile with hard/soft status and uncertainty. Do not optimise the physical parameters against a desired mountain outline and then use that same outline as independent validation. A compatibility study can be reported honestly as an inverse/constrained scenario. It must be accompanied by tests that were not constructed around the Diadem.

Procedural fine detail remains permissible. Label it as procedural, physically resolved or interpolated, retain its seed and scale, and prevent decorative detail from silently altering scientific drainage, loads or conserved resources. If fine detail is promoted into physical geometry, it becomes a changed model state that needs affected calculations and accounts to be revisited.

<a id="parameter-separation"></a>

### 3.4 Parameter separation without a customisation feature

**Scope.** Keep scenario-dependent physical values outside new solver logic so supported values can be exposed through future customisation without rewriting equations. For 1.0, use the selected Earth-like profiles. No sliders, public override interface, arbitrary-composition engine or mandatory 2.0 feature is added to this plan.

**Minimal design.** Pass a small typed parameter record, or the relevant subset, explicitly into each kernel. Keep physical/model choices, numerical controls and execution settings separate. Record parameter names, units, source/assumption, applicable law and tested range when established. A parameter may describe a scalar, spatial field or material law; do not flatten a variable viscosity or composition model into one universal constant. Do not build a general configuration framework.

**Defaults and identity.** Keep defaults together in named, versioned Earth-like material/case profiles, using only values selected through the existing scientific gates. Validate units, finite values, required fields and combinations supported by the chosen laws; missing required knowledge must not trigger invented defaults. Resolve and freeze the complete profile before computation and record its content identity with the run. No new numerical defaults are chosen here.

**Propagation and reuse.** Changing an input must recompute its affected derived properties and invalidate dependent scientific results. Changing only runtime parameter values need not recompile an unchanged expression, but must not reuse stale results. Record derived-value provenance. A future composition or mantle-flow control can expose only behaviour represented by a supported law: parameter separation does not itself supply new chemistry, mantle physics or scientific validation.

**What stays fixed.** Mathematical constants and coefficients fixed by an equation need not become world settings. Unit conventions remain explicit. Numerical tolerances, overflow bounds, safety limits and source/checkpoint verification are not ordinary planetary customisation controls. Existing source-bound implementations, values and histories stay unchanged unless separately authorised; do not silently repin or widen them.

**Acceptance in existing work.** W00 selects the profile; W01 and later kernels consume it. During future implementation, check unchanged Earth-like results when values are merely moved out of code; explicit versus default-profile agreement; invalid-input refusal; correct propagation and cache invalidation; and persistence of the exact resolved profile through restart. These extend existing case/identity checks, not a new simulation or test programme. Broader user customisation remains future work.

<a id="equation-plan-and-gaps-to-close"></a>

## 4. Equation plan and gaps to close

### 4.1 Retained equation-to-method map

The existing equation IDs remain authoritative navigation labels. Inclusion below is not unconditional selection of every equation or software mode. [[R04](#research-basis)]

| Process / equations | Planned use | Method study and place in the work |
| --- | --- | --- |
| P01 / E01–E02 | Rigid and relative/boundary-frame motion. | F01/O01; W01–W02. |
| P02 / E03 | Birth, ageing and retirement of oceanic material. | F02/O02; W02 and W06. |
| P03 / E04 | Explicit thermal/feature initial conditions; half-space cooling as a restricted reference. | F03/O03; W01 and W03. |
| P04 / E05–E09 | Mass, creeping-flow mechanics, heat, creep and coupled solver structure. | F04–F07/O04–O07; W07–W08. Yield/free-surface closure is additional work. |
| P05 / E10–E11 | Material trajectories and intensive projection. | F04/F06/F07; W02/W07. Extensive transfer must separately satisfy E23. |
| P06 / E12–E13 | Uniform elastic flexure and analytical/spectral reference. | F08/O08; W04. Variable rigidity and other boundaries are later extensions. |
| P07 / E14–E15 | Solid-preserving compaction and restricted age–depth response. | F09/O09; W03/W09. Thermal depth is an alternative to resolving the same support, not an extra term. |
| P08 / E16–E17 | Prescribed listric geometry and constant/divergence-free advection check. | F11/O11; W05. Not the general deforming crust thickness law. |
| P09 / E18 | Acyclic accumulation without unresolved storage. | F11/O11; W09. Real lakes need an additional storage/discharge law. |
| P10 / E19–E21 | Restricted stream-power and diffusion reference models. | F10/O10; W09. Not a drop-in replacement for Atlas’s material-aware erosion. |
| P11 / E22–E23 | Sediment and finite-volume/remapping accounts. | F12–F13/O12–O13; W02/W09/W11. Transport closure remains required. |
| P12 / E24–E25 | Conditional elastic-slip diagnostic. | F14–F15/O14–O15; W08/W10 only if needed. Not million-year plastic deformation. |
| P13 / E26 | Conditional equilibrium/property calculation. | F16/O16; W08/W10 after pressure–temperature–composition validity. |
| P14 / E27 | Conditional thermal-history observable. | F17/O17; W10 after trustworthy material histories. |
| P15 / E28 | Single-owner conversion of rock motion and surface processes into elevation. | W04–W10; connecting identity, not a complete physical solver. |

### 4.2 Core equations the plan builds around

**Motion and its limits — E01–E02.**

$$\mathbf v(\mathbf r)=\boldsymbol\omega\times\mathbf r,\qquad \mathbf r_{n+1}=\mathsf R_{n+1,n}\mathbf r_n$$

$$\Delta\mathbf v=\mathbf v_R-\mathbf v_L,\qquad v_n=\Delta\mathbf v\cdot\hat{\mathbf n},\qquad \mathbf v_{a,b}=\mathbf v_a-\mathbf v_b$$

Position is m, angular velocity rad/s and velocity m/s. Finite rotations are ordered. Plate-relative motion cancels a common frame velocity; trench-relative influx still needs the moving boundary. Whole-planet parameters and geological-time conversions must be explicit. [[S01][url-008]; [S03][url-009]]

**Added planning relationship N01 — deforming crustal thickness.** Derived by vertically integrating mass conservation for a selected column representation:

$$\partial_t(\rho_c H_c)+\nabla_h\cdot(\rho_c H_c\mathbf v_h)=s_{add}-s_{remove}$$

For constant density and no sources, $DH_c/Dt=-H_c\nabla_h\cdot\mathbf v_h$. Here $H_c$ is m, $\rho_c$ kg/m³, and the sources are kg/(m²·s); the horizontal velocity is the consistently thickness/mass-weighted column transport velocity. Layered or vertically sheared columns need their integrated flux, not an arbitrary surface velocity. Uniform extension at areal strain rate $\theta$ gives $H_c(t)=H_{c0}e^{-\theta t}$; shortening reverses the sign. Variable density, underplating, erosion and three-dimensional transport require their explicit terms. This is not E17’s purely advective thickness equation except under its compatible constant/divergence-free assumptions. [[R04](#research-basis), E05/E17/E23; derived here]

**Added planning relationship N02 — moving-boundary material flux.**

$$\dot M_{out}=\int_{\Gamma}\rho H(\mathbf v-\mathbf v_b)\cdot\hat{\mathbf n}_{out}\,ds$$

For a vertically integrated material layer, the result is kg/s. It provides the accounting for surface-domain retirement, ridge creation and regional export, but it does not prescribe productivity, accretion efficiency or slab forces. Sources and sinks need physical event identities. Crust and lithospheric mantle have separate thicknesses and ledgers. [[R04](#research-basis), E02/E05/E23; derived here]

**Mechanical baseline — E05–E08.**

$$\nabla\cdot\mathbf v=0,\qquad -\nabla p+\nabla\cdot(2\eta\mathsf D)+\rho_b\mathbf g=\mathbf0,\qquad \mathsf D=\tfrac12(\nabla\mathbf v+\nabla\mathbf v^T)$$

$$\rho_0 c_p(\partial_tT+\mathbf v\cdot\nabla T)=\nabla\cdot(k_T\nabla T)+H_T$$

This is an explicitly restricted incompressible/Boussinesq comparison, not every geodynamic formulation. Stress/pressure is Pa, viscosity Pa·s, heat production $H_T$ W/m³, conductivity W/(m·K), and temperature K. A density used for buoyancy must not silently change the conserved mass density. Constant-viscosity tests precede temperature/strain-dependent creep. Compressibility, latent/shear/adiabatic heating, elasticity and yield need named additions when relevant. [[S10][url-013]; [S11][url-016]]

**Yielding is a closure gate, not an omitted term.** The proposed first nonlinear mechanical family is viscous creep with a dimensionally explicit pressure-sensitive yield cap. Freeze the invariant, dimensional convention, cohesion/friction law, effective-pressure/pore-pressure treatment, tensile limit, flow rule, strain history and regularisation before implementing localisation. A common effective-viscosity construction compares creep viscosity with $\tau_y/(2\dot\epsilon_{II})$, but this expression alone is not a complete plasticity model. In ASPECT’s documented conventions, the two- and three-dimensional yield formulae differ. No universal coefficients or an unreviewed pressure clamp are selected here. [[S11][url-016]]

**Load response — E12–E13.**

$$D_f\nabla_h^4w+\Delta\rho g w=q_L,\qquad D_f=\frac{Y T_e^3}{12(1-\nu^2)}$$

$$w(x)=\frac{q_0\cos(kx)}{D_fk^4+\Delta\rho g}\quad\text{for a uniform periodic sinusoidal load}$$

Deflection $w$ is downward-positive m; load $q_L$ Pa; $D_f$ N·m; $T_e$ effective elastic thickness, not crustal thickness. The comparison assumes a flat, thin, small-deflection elastic plate with uniform rigidity and no imposed in-plane stress. Spectral/analytical and finite-difference answers must use the same boundary problem. [[S18][url-017]; [S20][url-018]]

**Added planning relationship N03 — local buoyancy check.** For dry, uniform crust/mantle densities with $\rho_m>\rho_c$ and a specified common compensation reference, a local Airy comparison gives $\Delta h=(1-\rho_c/\rho_m)\Delta H_c$. It tests a restricted support response; do not add it independently to a flexural or mechanical solution already incorporating that buoyancy. Spatial rigidity, density layering and water replacement require the appropriate different load operator. [Derived hydrostatic column balance; compare [S18][url-017]]

**Surface accounting — E28.**

$$\partial_t h+\mathbf v_h\cdot\nabla_hh=v_z+\mathcal D-\mathcal E$$

All right-hand rates are vertical thickness rates in m/s; $h$ is upward-positive. A normal erosion speed requires geometric conversion. Downward deflection contributes through its material derivative only if not already included in $v_z$. This identity does not by itself supply a free-surface traction condition, erosion law or sediment-distribution law. [[R04](#research-basis), P15]

### 4.3 Closures that must be selected explicitly

| Decision | Proposed route | What must be fixed before its work package can claim the process |
| --- | --- | --- |
| C01: mechanical strength/localisation | Newtonian reference, then a documented creep plus pressure-sensitive yield family. | Invariants, constitutive parameters and evidence, pressure/tension treatment, flow rule, weakening and mesh-independent regularisation. |
| C02: surface mechanics | Choose one free-surface method for M; retain a reduced flexural path for K. | Stress boundaries, surface motion, buoyancy reference, mesh strategy and stabilisation. Sticky-air or a height field is not automatically equivalent to a true free surface. |
| C03: oceanic production/recycling | Birth and sink fluxes from moving boundaries, explicit productivity and accretion parameters. | Crustal thickness/density and thermal state of new material, extraction/recycling reservoir and transfer destination. |
| C04: subduction/collision transition | Prescribed, source-visible transition rules first. | Polarity, dip/history, entry of continental material, flux partition, slab/overriding response and unsupported-event refusal. |
| C05: water and sediment | Start with explicit runoff and a restricted transport regime, then add lake/storage and deposition where needed. | Erosion law, entrainment/capacity or settling closure, porosity, finite supply, outlet law and physical closed-basin handling. |
| C06: magmatism | Reduced source-to-emplacement account, conditional on a selected scenario. | Source/rate, intrusive/extrusive/reservoir fractions, volume-to-mass conversion, footprint/geometry, thermal and load effects, independent calibration. Equilibrium melt fraction is not eruption flux. |
| C07: thermal/vertical ownership | Select resolved temperature-density support or a documented reduced cooling/subsidence relationship. | Reference state, valid age range, material/compaction model and all loads already included. Never apply both alternatives to the same effect. |

These are bounded scientific decisions attached to later packages, not permission to fill missing science with defaults. The plan remains usable because each capability has a deliverable and stopping condition; it does not pretend the pre-studies already provide a complete closure set.

<a id="work-packages-and-dependency-gates"></a>

## 5. Work packages and dependency gates

Each W-package ends with a reviewed evidence record. Any failed gate blocks its dependent capability, but not unrelated analytical work. Parameters used to obtain a fit must be separated from withheld validation data. The foundation status below is already delivered; remaining work is subject to its scoped development and execution requirements. This document edit authorises no simulation or benchmark.

### W00 — Freeze the scientific case and evidence rules

**Question:** what claim is the next experiment actually testing? Produce a short case contract identifying Mode K or M, domain and regime, equations, initial/boundary data, units, physical duration, numerical representation, output quantities and explicit exclusions. Register analytical expectations and failure cases before implementation.

Create three distinct evidence sets: exact/manufactured verification, analogue/observational validation, and Diadem compatibility. Where a published benchmark is used, record the exact setup, source version, input permissions, measured observables and uncertainty. A graph or table in a paper must be acquired and interpreted explicitly; merely citing its title is not an executable fixture.

**Output/gate:** one reviewable case specification with a physical question and quantitative acceptance procedure. Add the compact execution card from [the optimisation reference’s execution card](OPTIMISATION_REFERENCE.md#execution-card): candidate task independence, state ownership, cost/memory estimates, cache identities, equality policy and applicable PF/PT checks. Select finite resources for the specific proposed experiment; unresolved values are not unlimited. No production integration or universal configuration framework.

### W01 — Coordinates, rotations and initial geological fields

**Stage 4B reference-library status:** sourced principal-material records,
condition-aware property resolution and exact layer bindings are now supplied.
Stage 5 must preserve the distinction between grain/bulk properties, explicit
pore fluids, scalar reference values and still-needed constitutive laws.

**Current stage-4 status:** descriptions and their structural/identity validation
are implemented for regional and global initial configurations. No stage-5 field
sampler or W03 thermal/compaction calculation is delivered. W02 cohort identity is
referenced, not converted into an initial evolving state without stage-5 sampling.



**Prior stage-3C scope (retained for context):** automatic initial spherical
partition construction/validation is implemented. Stage 4 above now supplies the
initial geological description. Stage 5 (sampling), stage 6 (motion adapter),
stage 7 (W01–W02 integration) and stage 8 (combined acceptance) remain outstanding.


**Stages 1–3 delivered within the declared regional/hemisphere-patch scope:** see `cases/w01_coordinates.json`, `cases/w01_geometry.json` and
[coordinate/time implementation](OPTIMISATION_REFERENCE.md#w01-stage1-delivery).
This is stage-level completion only. The agreed remaining sequence is:

| W01 stage | State and completion responsibility |
| --- | --- |
| 1 — Coordinate/frame/time conventions | Implemented; explicit spherical, local and legacy axes, unit/epoch conversions and independent numerical checks. |
| 2 — Plate and feature geometry | Implemented for planar polygons/traces and conditioned minor-arc spherical patches, with metrics/overlays, spatial indexes, gap/overlap diagnostics and checked persistence. No arbitrary whole-sphere Boolean engine is claimed. |
| 3 — Shared boundaries and sidedness | Implemented: complete static domain coverage, single shared segments, verified sides/orientation, same-plate seams, cyclic junction sectors, point contacts, metric frames and prescribed velocity diagnostics. Spherical networks require a coherent common domain chart; arbitrary full-sphere stitching remains unsupported. |
| 3B — Shared whole-sphere geometry | Delivered with canonical shared vertices, matching seams and global ownership; not dynamics. |
| 3C — Generated initial partition | Geometry fixture complete. Earth-like scientific acceptance REOPENED: calibrated connected candidate plus independent limited challenges delivered; full outline/motion validation outstanding. |
| 4 — Initial geological description | Delivered: typed crust/material/cohort/ordered-layer/thermal/fault/weak-zone descriptions, explicit provenance and precedence, regional/planetary attachment, and self-contained verified storage. Point/cell sampling remains stage 5. |
| 5 — Initial-condition sampler | Outstanding: grid-independent features, appropriate point/average/inventory sampling and missing-data rules. |
| 6 — Motion to regional forcing | Outstanding: explicit supported reduction from prescribed plate motion, without dropping cross-transect transport silently. |
| 7 — W01-to-W02 workflow | Outstanding: initialise and evolve a known case without ad hoc intermediate arrays; preserve W03 input descriptions. |
| 8 — Combined W01 acceptance | Outstanding: original geometric/scientific gates plus resource/cache/restoration checks; then assess whole-package completion. |


**Dependencies:** W00. **References:** P01/P03, E01/E02/E04, F01/F03.

Establish regional east/north/up and spherical Cartesian conventions with explicit conversion at legacy x-east/y-south interfaces. Implement future reference tests for finite rotations, composition order, inverse motion and reference-frame changes. State geometric and area errors separately from the physical model’s uncertainty.

Define a compact world/case description for crust types, layers, faults, weak zones and thermal profiles. Seeded generation may create initial plates/weakness patterns under declared priors, but cannot embed the desired final mountain surface. Sampling at a new grid must not move the underlying feature or silently supply unsupported material.

Use the parameter separation in Section 3.4: kernels receive a frozen, identified Earth-like profile rather than scattered physical literals. This is ordinary input design inside W01 and subsequent kernels, not a new framework or a user customisation feature.

**Deliverables:** conventions, pure initial-condition sampler, small known geometries and rotation/profile fixtures. **Gate:** rigid distances and zero strain, side/trace reversal, seam/pole tests for spherical primitives, unit/time round trips and correct thermal boundary limits. These tests validate representation, not the selected plate history.

### W02 — Conservative material history and boundary events

**Regional completion (17 September 2026):** the remaining representation, motion
and event operations are delivered on ColumnGrid1D. The verification case
`cases/w02_completion.json` binds equations, coverage, immutability, conservation,
formation history, cold restoration and optimised defaults. All 488 tests pass on
the recorded Linux runtime, including 78 new cases. This closes implementation of
the regional contracts, not every geometry or scientific validation gate.
The prior fixed-grid subsection below records the earlier delivery state.


**Delivered fixed-grid portion (17 September 2026):** regional open/closed transport
now has cohort partial thicknesses, formation-time metadata, explicit exterior
composition, and parent-bound prescribed transfer receipts. The sum of cohort
quantities is the total; no independent total-density constraint is claimed.
Self-contained snapshots preserve histories and zero-volume catalogue entries.
See `cases/material_transport.json` and the existing scientific case notes.
That earlier remaining remap/motion/ownership work is supplied by the regional
completion above. General planetary geometry and predictive forcing are not supplied.


**Delivered increment:** `RegionalGrid1D`, `TransportBoundary`, `advect_regional`
and timestep advice now supply fixed-grid, constant-density one-field transport.
Compiled MC-limited MUSCL/SSP-RK2 is the new regional default; first-order upwind and
independent references are explicit. The two schemes have distinct identities and
CFL/accuracy envelopes. Source-reservoir labels are provenance, not a transported
mixture or full history. Remaining W02 responsibilities below are still outstanding.

**Dependencies:** W01. **References:** P02/P05/P11, E03/E10/E11/E23, N01/N02; F02/F04/F06/F07/F13.

Track material identity separately from plate identity and mesh identity. Move material, record birth/removal, and transfer extensive quantities conservatively. Treat particle-to-mesh intensive projection separately. Establish thickness change from area deformation under constant-density analytic cases before variable properties or mixed layers.

Use shared boundaries with explicit side ownership and junctions. Supported ridge opening, subduction retirement, split/merge and active/inactive transitions become events with before/after geometry and mass/area accounts. Do not cure overlaps by deleting material, allocate the same volume to two plates, or reset history when a plate changes identity. Closed-world area coverage must remain valid; regional external exchanges must remain visible.

**Deliverables:** material/event schema, boundary-account reference, moving-point and column tests. **Gate:** known extension/shortening, sharp tagged-material advection, birth-age history, reversible motion where physically reversible, explicit sinks, and unchanged totals under a remap-only step. Event discovery itself remains a declared rule, not a force prediction.

### W03 — Thermal evolution, lithosphere age and compaction

**Dependencies:** W01–W02. **References:** P03/P07, E04/E07/E14/E15; F03/F09.

Begin with one-dimensional conduction and half-space cooling as a limiting check. Compare a finite plate with prescribed deep and surface temperatures where the half-space approximation is no longer appropriate. Handle zero thermal age explicitly: a ridge initial condition is not obtained by numerically dividing by zero or introducing an undocumented minimum age.

Derive or select the thermal-density/support relationship consistently. A reduced age–depth relation is an alternative calculation with its own calibration range. Compaction must conserve solid material while changing bulk volume and load; fixed-area decompaction identities cannot be reused blindly in laterally deforming columns.

**Deliverables:** thermal/age/compaction specification and references; named density and support ownership. **Gate:** thermal boundary limits, conserved solid thickness, heat accounting for the selected equation, time/grid refinement and independent bathymetry/heat-flow or column comparisons once suitable data are selected. No duplication of thermal subsidence and density-driven buoyancy.

### W04 — Vertical support from a physically defined load

**Dependencies:** W01, with W02/W03 when material or thermal loads are used. **References:** P06/P15, E12/E13/E28, N03; F08/F09.

First solve uniform, small-deflection flexure for a periodic sinusoid and a local-isostatic limiting case. Derive the load in Pa from a stated reference column, density contrast and replacement medium; thickness alone is not a load. Then test domain enlargement, nonperiodic boundaries and only subsequently variable rigidity with the correct operator.

Record whether a result is total deflection from the reference state or an increment. Repeatedly adding the total deflection at every step is an error. Effective elastic thickness is a constitutive parameter, not automatically crustal thickness or actual full lithospheric thickness.

**Deliverables:** load-construction and support contracts, analytical solution fixtures and candidate numerical method. **Gate:** sinusoid amplitude/sign, superposition where linear, convergence with domain/grid and independent load response. A model passing this gate explains response to a load, not where the mountain or magma load originated.

### W05 — First coupled mechanism: regional extension

**Dependencies:** W02 and W04; W03 when thermal/compaction effects are in scope. **References:** P08/P15, E16/E17/E28 and N01; F11/F08.

Recommended initial case: a prescribed detachment geometry and displacement with no Diadem shape targets. Begin with constant horizontal velocity and a translated thickness profile. Where the velocity field has nonzero divergence, use the appropriate conservative thickness law and sources, not the constant-translation check.

Connect the physical column/load change to a single vertical-response treatment. Measure hanging-wall displacement, basin subsidence, footwall/shoulder response, crustal thinning and boundary export. Treat the listric geometry as prescribed: this experiment does not prove spontaneous fault initiation or stress-controlled localisation.

**Deliverables:** mechanism specification, independent reference implementation, component-versus-coupled comparison, and an analogue/observational challenge plan. **Gate:** accounts close; changing grid, timestep and domain does not control the qualitative result; uplift/subsidence signs and amplitudes match justified expectations. Do not interpret success as acceptance of collision or of History A.

### W06 — Spreading, passive margins and changing plate histories

**Dependencies:** W02–W05. **References:** P01–P03/P07, E01–E04/E15 and N02; F01/F02/F03/F09.

Extend the kinematic regime to selected breakup and ocean-birth events. Compute creation at moving ridges, track material age and cool it. Test asymmetric spreading, ridge migration and explicit plate-boundary transitions; distance to today’s ridge is not a general formation-age estimator.

Keep continental thinning and new oceanic material distinct. A passive margin inherits its rift and thermal history after the active ridge moves away. Generated motion proposals must obey geometric/flux constraints, carry their priors and be rejected or revised when inconsistent. They do not become physically force-balanced because they produce complete polygons.

**Deliverables/gate:** coherent birth/age/cooling history with finite material sources, independently verified motion and boundary coverage. Expansion to spherical surfaces requires spherical area/normal tests, not a planar result relabelled global. Thermal depth and mantle/lithosphere accounts must remain consistent.

### W07 — A selected regional mechanical backend

**Dependencies:** W00–W03; W04 supplies checks of loading, not automatically an added response. **References:** P04/P05/P15, E05–E11/E28; F04–F07.

Study one explicit mixed velocity–pressure formulation. Start with constant-viscosity analytical/manufactured velocity fields, pressure-reference handling, rigid-body modes and boundary traction. Compare candidate discretisations against those cases before adopting a framework architecture. Add variable viscosity and heat transport only after that baseline passes.

C01 and C02 must close before strain localisation or surface mechanics is claimed: pressure convention, creep/yield law, physical strength/weakening parameters, tensile behaviour, free surface, stabilisation and mesh/particle transfer. Use reference pressure plus the solved perturbation consistently when a creep or thermodynamic law needs absolute pressure.

**Deliverables:** one selected formulation, boundary/constitutive specification, verified reference solver and public benchmark definition. **Gate:** force/divergence/thermal residuals, independently calculated fields, sharp material contrasts, convergence and mesh-independent quantities of interest. A low nonlinear residual cannot excuse a numerically defined shear-zone width. If a reduced K-mode answers the question sufficiently, M is not mandatory for that particular case.

### W08 — Shortening, transform/oblique motion, subduction and magmatism

**Dependencies:** W02/W04/W06, and W07 where mechanical response is claimed. These are separate cases, not one universal tuned recipe.

**Shortening/collision:** first verify uniform shortening and thickness/mass conservation; then supported underthrusting, distributed strain, loading/foreland response and material accretion. Test finite strain and boundary effects. A thickened crust plus a buoyancy response does not automatically reproduce a fold-and-thrust belt; fault localisation and structural geometry require the relevant mechanical or reduced closure.

**Transform/oblique:** begin with pure shear and translated markers, then prescribed bends/stepovers and oblique motion. Test local compression/extension, offset histories, volume balance and frame invariance. Optional E24/E25 elastic responses serve a diagnostic, not an accumulated million-year plastic model.

**Subduction:** use a prescribed slab/plate kinematic benchmark with a mechanically computed wedge as the first thermal-mechanical reference. A published community benchmark explicitly uses this mixed approach; it tests boundary and rheological treatment, not spontaneous global plate formation. Follow with a buoyant-slab/free-surface benchmark only if the claimed response needs it. The methods literature warns that viscosity averaging and artificial surface layers can materially change results. [[N-S01][url-019]; [N-S02][url-020]]

Close C03/C04 before geological histories: slab polarity/geometry/time, oceanic material sinks, accretion versus erosion, trench migration, overriding shortening/extension, and collision/subduction-cessation rules. Back-arc opening and rollback remain conditional until separately tested. A valid boundary projection does not choose which plate subducts.

**Magmatism:** close C06 before producing volcanic mass. The mantle/crust/reservoir budget must reconcile extraction, intrusive addition, eruption, storage and external export. Melt fraction from E26, if later used, is not a rate or pathway. Reduced emplacement needs a calibrated rate and geometry with validity limits; no arbitrary cone is to be labelled mechanically predicted. Caldera collapse and hotspots are optional scenario packages with their own volume, thermal and load accounts.

**Deliverables/gate:** separate regime evidence records with clear prescribed/predicted distinctions, geological observables and cross-regime transition tests. An unsupported case stays unsupported rather than receiving generic mountain uplift. Full 1.0 claims require all core regime gates, not just the successful extension case.

### W09 — Necessary surface response and source-to-sink accounting

**Dependencies:** an accepted tectonic mechanism from W05/W06/W08; W03/W04 for feedback. **References:** P09–P11/P15, E18–E23/E28; F10–F13.

Use explicit water forcing initially; solving global climate is not a prerequisite for a bounded terrain experiment. Keep physical topography separate from any surface altered solely for routing. Genuine closed basins need storage, overflow/evaporation/infiltration treatment where relevant; E18’s accumulation is not transient water dynamics.

Use the linear, fixed-receiver stream-power update and sinusoidal hillslope diffusion only as narrowly defined reference calculations. Before actual basin morphology is claimed, close C05: material-aware incision, finite sediment source, entrainment or capacity/settling law, deposition, porosity and outlets. E22 balances material but does not choose its flux. Preserve origin and history through transport and compaction.

**Deliverables/gate:** tagged sediment pulse through a closed/open catchment; dry/no-forcing limits; receiver changes; lake conservation; geometry/coupling refinement; and independent profiles/stratigraphy where available. Load-feedback tests must not apply the same sediment, thermal or isostatic effect twice. This mechanism coupling is not the full eighteen-category production chain.

### W10 — Independent realism challenge and uncertainty

**Dependencies:** the relevant mechanism gates, with W09 for final-landform claims. Separate verification from validation and from visual preference. Reserve material/parameter regions or independent data that were not used for calibration.

Use a ladder: exact/manufactured cases; published multi-code benchmarks; analogue deformation experiments; then geodetic/geological observations appropriate to the selected mechanism. The identified analogue shortening/extension benchmark is a candidate source, but this plan has not acquired its full numerical setup or licensed data. [[N-S03][url-021]] Cross-code agreement with shared equations/data is numerical corroboration, not complete independent physical proof.

Quantities of interest include surface and basement displacement, crustal thickness, strain/slip distribution, heat flow, basin volume, mass export, drainage structure and stratigraphy. Thermochronology is optional only after material thermal histories exist. Compare uncertainty and sensitivity to forcing, boundaries, strength, effective elastic thickness and erosion parameters—not only one best-looking run.

**Deliverables/gate:** accepted within a stated validity envelope, rejected, or unresolved. Never equate ensemble spread with calibrated uncertainty by default. Retain failed explanations. Only after independent credibility is established does a Diadem constraint-compatibility test assess its authored landforms.

### W11 — Matched-error optimisation, multiresolution and scale

**Dependencies and timing:** W00 defines the question and finite envelope. W11 is a cross-cutting workstream, not a blanket wait for every physical model to pass. Its design reviews begin in W01–W04. An enabling performance study may occur alongside W05–W10 after the relevant numerical reference/invariants exist, especially when needed to make an authorised realism experiment practical. Broad scale and production claims still require the relevant W10 physical acceptance. All performance execution remains separately authorised.

Start with measured repeated setup, geometry decoding, projection rebuilds, per-object overhead and material-history size. Prioritise bounded reuse, contiguous arrays, batched work and appropriate ordered algorithms. Choose implicit updates or approximations only through a new numerical/model identity. Compare total cold/warm cost, memory, storage and physical error; a faster kernel alone is insufficient.

Then test adaptive support, conservative remapping, nonuniform layers, spherical meshes and cross-partition fluxes. Coarse/fine regions need explicit exchange rules and boundary closure; a halo alone cannot isolate a globally connected river or stress field. Changing partitions must not move geology, reset history or change accepted results outside the declared tolerance.

**Deliverables/gate:** evaluated PF decisions, per-calculation execution cards, applicable PT01–PT14 results and, after relevant physical acceptance, a feasible measured workload envelope with independently checked scale transfer. No universal grid or machine is selected now. One-metre outputs remain eligible; output density and process resolution remain separate. GPUs, MPI and large symbolic frameworks are conditional choices, not mandatory next tasks.

### W12 — Production integration and release acceptance

**Dependencies:** relevant W10 physical gates and W11 resource/scale gates. Only now select production adapters into Atlas’s wider graph and retained spatial outputs. Reuse existing execution, source identity and recovery systems where suitable; do not build another chain of copied module globals merely to attach the new work.

A separately identified producer must publish the equation/closure version, inputs, numerical policy, declared scope, output identities, material/load accounts and restart dependencies. Historical R5 controls are not rebadged as checkpoints of changed physics. Public fixtures and a reproducible compatible runtime must accompany any independent-execution claim.

**Release gate:** supported regime matrix, scientific evidence, finite resource envelope, coherent checkpoint/recovery drill, clean-versus-incremental comparison and truthful documentation. Code approval, physical acceptance and fictional canon remain separate. Main-branch publication requires its own coding/publication scope; this documentation consolidation changes no numerical implementation.

<a id="coupling-timestep-and-state-acceptance-policy"></a>

## 6. Coupling, timestep and state-acceptance policy

### 6.1 A future physical step

The following is conceptual execution order, not runnable code or a production instruction:

1. Verify the accepted starting state, selected laws, sources, frame/time and boundary inputs. Choose a candidate interval limited by physical events, numerical accuracy and transport constraints.
2. Locate the next plate/boundary event. Split an interval at a topology or forcing discontinuity rather than averaging through an unrepresented event.
3. Evaluate kinematics and regional boundary forcing. In M-mode, solve the coupled mechanics/thermal problem with its declared boundary conditions and pressure reference.
4. Construct a candidate material update: horizontal/vertical movement, thickness, birth/subduction/accretion and associated heat/material exchanges. Preserve source identity and finite accounts.
5. Evaluate the selected vertical response and physical surface motion. Include only effects not already owned by the mechanics or previous support state.
6. Subcycle the necessary water/sediment/compaction processes. Exchange integrated transfers at common physical times, not by assuming their numerical timesteps are equal.
7. Where loads, geometry or temperature feed back strongly, iterate the selected coupling or reduce the macro interval. Compare one interval with a refined or reversed-order reference to expose splitting error. Do not assume a chosen splitting order is harmless.
8. Re-establish affected geometry/connectivity and verify accounts, field bounds, residuals, accuracy estimates and event consistency. On failure, reject the candidate; preserve the accepted state and the failure evidence.
9. Commit one coherent accepted state and receipt. Cache only quantities valid for that state, and save restart information at a policy-defined cadence distinct from scientific output sampling.

### 6.2 Timesteps are selected by meaning, not calendar convenience

Use physical forward time internally with explicit conversion from geological age and declared year length. Transport may require a Courant constraint; an implicit thermal/incision solver may be stable at a larger interval while still inaccurate. Localisation, slab motion, free surfaces and topology events can impose different limits. Choose the smallest applicable constraint and perform temporal-refinement checks for the coupled quantities of interest. [[R04](#research-basis); [S27][url-022]; [S28][url-023]]

Do not fix one timestep for tectonics, rainfall, sediment, thermochronology and rendering. Nor does an existing 256-interval limit imply a physical duration. Any future successor that changes a computational bound needs its own scoped numerical/resource evidence; this plan does not change the retained native boundary.

### 6.3 Ownership of vertical and thermal effects

| Effect | Ownership rule |
| --- | --- |
| Fault/continuum movement | One selected K or M source for each represented displacement contribution. |
| Isostatic/flexural response | One reference state and response operator; do not add local Airy support to the same response already in flexure or M. |
| Thermal subsidence | Resolved thermal-density support or a reduced age-depth model for that effect, never both. |
| Sediment | Deposition changes thickness; compaction changes bulk volume; loading changes support. They are related but distinct updates. |
| Magma | New mass, emplacement volume and heat are linked accounts, not independent terrain decorations. |
| Erosion | Surface removal and unloading are distinct, with shared material/account identities. |
| Visual refinement | Remains separate from scientific state unless explicitly promoted and re-evaluated. |

<a id="numerical-and-computational-design"></a>

## 7. Numerical and computational design

### 7.1 One place for detailed optimisation decisions

The [consolidated optimisation reference](OPTIMISATION_REFERENCE.md) is the sole maintained home for execution, cache, memory/storage, native-language and optimisation-study detail. This plan states the scientific obligations and where those decisions enter the work. Do not copy the reference back into a new supplement.

| Responsibility retained in the plan | Detailed specification in the reference |
| --- | --- |
| Per-process independence and shared-state ownership | [Process placement](OPTIMISATION_REFERENCE.md#process-placement) and [execution contract](OPTIMISATION_REFERENCE.md#execution-contract) |
| Complete identities, bounded reuse and invalidation | [Cache contract](OPTIMISATION_REFERENCE.md#cache-contract) |
| Host/device working sets, chunks, palettes, streaming and coherent recovery | [Storage contract](OPTIMISATION_REFERENCE.md#storage-contract) and [volumetric representation](OPTIMISATION_REFERENCE.md#volumetric-storage) |
| Python orchestration and selective native numerical work | [Language and native boundary](OPTIMISATION_REFERENCE.md#native-boundary) |
| All PF01–PF26 candidate families and PT01–PT14 checks | [Candidate register](OPTIMISATION_REFERENCE.md#candidate-register) and [measurement and tests](OPTIMISATION_REFERENCE.md#performance-tests) |
| O01–O17 scientific-software methods and retained engineering patterns | [Scientific methods](OPTIMISATION_REFERENCE.md#scientific-methods) and [engineering methods](OPTIMISATION_REFERENCE.md#engineering-methods) |
| Retained engineering screening lessons and non-goals | [Adoption and boundaries](OPTIMISATION_REFERENCE.md#method-adoption) |
| One compact execution record per selected case | [Inline execution-card specification](OPTIMISATION_REFERENCE.md#execution-card) |

### 7.2 Principles that remain binding

**Keep three representations distinct.** A small analytical/high-accuracy reference verifies the equation. Process state uses arrays, sparse operators and justified precision. Material/provenance accounts retain stable extensive quantities and histories. Preserve the historical fixed-quantum routes; any new conservative representation needs explicit conversion, residual, overflow and reproducibility rules. A floating solver is not permission to silently round away mass.

**Design efficiently from the outset.** Use pure/batched interfaces, explicit ownership, finite working sets and valid cache identities from the first kernel. A serial reference is not a single-threaded production decision. Verified enabling acceleration may support a realism experiment before that experiment establishes physical adequacy. Production still waits for the relevant physical and resource gates.

**Do not alter the scientific question to obtain a performance result.** Keep E execution, N numerical, M model-reduction and S scale/representation changes distinct. Changing precision, a random stream, a drainage rule, a timestep or a mechanical law requires the corresponding numerical/scientific review. Camera-based culling applies to display, not to hidden material's physical influence.

**Reuse what exists.** The remake already has arrays, batching and immutable flexural-operator reuse. Measure a current cost before adding another cache, scheduler, native language or voxel framework. Keep historical source/checkpoint safeguards unchanged.

### 7.3 Resolution, duration and resources

Let $A$ be a sampled surface area and $\Delta x$ a nominal square-cell spacing. Approximately $N=A/(\Delta x)^2$ samples are required; a uniform volume scales with $(\Delta x)^{-3}$. These are count estimates, not runtime predictions. A world need not store every layer at every output resolution or every point at every historical time.

Select process resolution from error and represented physics; select output detail from purpose and budget. Use compact features, layer columns and history sampling where justified. For a future planetary route, pick a true spherical area/edge representation and test metric distortion, seams, poles and conservation. A full climate/tectonic solve at 1 m is not implied by a metre-sampled terrain export.

Before each authorised benchmark/run, fill total parent-plus-worker peak RAM, scratch/persistent/staging/recovery storage, wall-time ceiling, cancellation policy, available cores, dependency versions and recovery requirements. The plan deliberately invents no owner hardware specification or deadline. Unfilled fields block a production claim, not the scientific planning work.

Before selecting a mesh, record characteristic length $L_0$, velocity $U_0$, density, viscosity $\eta_0$, thermal diffusivity $\kappa$ and the phenomenon’s physical timescale. A viscous stress scale is $\eta_0 U_0/L_0$ and an advective time is $L_0/U_0$ when $U_0$ is nonzero. A thermal Peclet number $Pe=U_0L_0/\kappa$ identifies the relative importance of the selected advection and diffusion terms; it is a diagnostic, not a universal switch that permits dropping a term. [E06/E07; dimensional analysis]

For a chosen Maxwell material, $\tau_M=\eta/\mu$ is a useful relaxation timescale, where shear modulus $\mu$ is Pa and viscosity Pa·s. Compare the physical timescale with that material model before applying repeated elastic displacements over geological time. Real heterogeneous/yielding lithosphere cannot be reduced to one global Maxwell time. The selected constitutive model must explain why an elastic, viscous, viscoelastic or plastic approximation is appropriate. [[S39][url-024]; [R01](#research-basis)/[R04](#research-basis)]

This scale analysis provides an early feasibility/validity filter without a simulation. It also guards against importing a centimetre-scale laboratory setup or short earthquake-cycle equation into a kilometre-scale geological problem without matching the relevant nondimensional behaviour.

### 7.4 Development placement and current next step

| Work | Required performance planning |
| --- | --- |
| W00 | Define the finite case, equality/error policy, inputs, cost/memory estimate and relevant PF/PT checks. The execution card belongs with its case, not in another general-purpose document. |
| W01–W04 | Keep explicit parameters, array/batch interfaces, accepted/candidate ownership and valid setup reuse. No compulsory worker pool for a tiny fixture. |
| W05–W09 | Specify physical coupling barriers, shared-face ownership, bounded scratch and necessary enabling acceleration. Verify the numerics independently of physical acceptance. |
| W10 | Parallelise independent cases/diagnostics where valid. Keep stable random identities and validation separate from performance tuning. |
| W11 | Measure enabling work when needed; then compare accepted behaviour at matched error and broaden the workload envelope. No speculative whole-world speed multiplier. |
| W12 | Carry only supported backends, compatible fixtures and tested cache/recovery behaviour into production. |

The next substantive work is W04 physical load/buoyancy construction from the delivered regional material state, with W03 thermal/compaction where needed. Reuse W02 transport, cohorts, remapping and events rather than rebuilding them. Apply the existing optimised execution and resource tests during that physical increment.

<a id="verification-physical-validation-and-decision-rules"></a>

## 8. Verification, physical validation and decision rules

### 8.1 Four independent gates

| Gate | Evidence | What passing does not mean |
| --- | --- | --- |
| **V1: implementation verification** | Units/signs, manufactured/analytic solutions, conservation, field bounds and declared invalid-input refusal. | The constitutive law is true for a geological setting. |
| **V2: numerical adequacy** | Mesh/time/coupling/domain refinement, appropriate residuals, remapping/rounding error and resolved physical features. | A visually plausible field matches independent observations. |
| **V3: physical adequacy** | Withheld analogue/geophysical/geological observables and sensitivity/uncertainty within a defined regime. | Every world, scale, history or boundary condition is covered. |
| **V4: world compatibility and release** | Required authored constraints, provenance, resources, output/restart consistency and named supported capabilities. | Canon approval or an untested generic-planet guarantee. |

A common modelling assumption across two codes weakens their independence as physical evidence. Use exact checks, alternate discretisations and observations/experiments for different purposes. Software-family agreement and agreement between AI reviewers are not acceptance metrics.

### 8.2 Required verification matrix

T01–T16 remain scientific/numerical verification families. The new PT01–PT14 matrix in [the optimisation reference’s performance tests](OPTIMISATION_REFERENCE.md#performance-tests) supplies execution, cache, resource and recovery checks; passing it does not replace these physical tests.

| ID | Case | Expected quantity or invariant |
| --- | --- | --- |
| T01 | Finite rotation and its inverse | Rigid distances/area and zero strain; noncommuting composition handled correctly. |
| T02 | Common motion and trace reversal | Relative behaviour invariant; side/normal conventions preserved. |
| T03 | Constant translation / uniform extension | Translated field; $H=H_0e^{-\theta t}$ under the stated source-free approximation. |
| T04 | Birth, migration, subduction | Correct age and mass/area transfer; no double ownership or unexplained disappearance. |
| T05 | Heat diffusion / half-space / finite plate | Analytic limits, heat accounting and time/depth refinement in their valid regimes. |
| T06 | Compaction and reversal | Fixed solid mass/volume under declared density and area; correct zero-compaction limit. |
| T07 | Periodic flexure | E13 amplitude, sign and superposition; independent sparse/spectral comparison if implemented. |
| T08 | Mechanics manufactured solution | Velocity/pressure error, divergence and force residual; null-space and boundary treatment. |
| T09 | Variable strength / free surface | Viscosity/yield and surface-convergence behaviour; no mesh-only localisation claim. |
| T10 | Pure shear / oblique cases | Expected strain/mass/thickness behaviour and finite offsets. |
| T11 | Subduction benchmark | Specified thermal/mechanical observables under exactly matching boundary/rheology assumptions. |
| T12 | Incision / diffusion | Fixed-network solution and transient refinement; sinusoidal diffusion decay; no unsupported stability-to-accuracy inference. |
| T13 | Sediment and real closed lake | Tagged solid and water budgets, storage/outflow and changed routing without destructive numerical filling. |
| T14 | Coupling / remap / partition | Zero-forcing and isolated-effect checks, no double counting, geometric and extensive conservation. |
| T15 | Restart and source change | Same accepted state under the declared equality policy; refusal of stale binding or incompatible checkpoint. |
| T16 | Withheld geological case | Predetermined quantities and independent uncertainty envelope, not only fitted final topography. |

### 8.3 Threshold policy

Set acceptance thresholds before optimising or fitting the candidate. For an analytic case use absolute and relative error with physically stated normalisation; do not divide by a near-zero reference. Evaluate convergence over at least three refinement levels where practical and compare the observed order with the scheme’s expected regime. Discontinuities and non-smooth events require appropriate norms and event/location errors rather than an unjustified smooth-solution order.

For a conserved quantity, the residual is final storage minus initial storage minus integrated sources plus sinks/external export. Require exact reconciliation for a declared integer account; for floating transfers require a specified error bound and stable accounting procedure. Solver residual thresholds must be tighter than the error they are allowed to contribute, but a residual alone is not physical accuracy.

Do not invent one universal percentage for every geological observable. Tolerances must reflect numerical truncation and independent measurement/model uncertainty, recorded separately. A failed run cannot redefine its own limits after seeing the result. A changed scientific model gets a new identity and comparison, not a backdated pass.

## 9. All seventeen software families: decisions, not dependencies

| Family | Planned lesson | Disposition |
| --- | --- | --- |
| F01 GPlates / pyGPlates | Spherical rotations, shared boundaries, cached time states. | Early mathematical foundation; not a mantle-force predictor. |
| F02 GPlately | Moving ocean-material birth/age/removal; separate gridding. | Early history reference; reject hidden initial-age guesses. |
| F03 Geodynamic World Builder | Compact feature-based initial geometry and thermal/composition sampling. | Early case-definition reference. |
| F04 LaMEM | Staggered mechanics and moving material; solver/data separation. | Candidate regional mechanics reference, not a framework clone. |
| F05 ASPECT | Governing formulations, creep/yield conventions, adaptive/multigrid methods. | Closure and verification reference; advanced solvers conditional. |
| F06 Underworld | Material history versus mesh fields; batching and equation visibility. | Use narrow lessons first; UW2 and UW3 are not assumed identical. |
| F07 pTatin3D | Mixed pressure–velocity solve and matrix-free/preconditioning lessons. | Specialist comparison; incomplete earlier source access remains a caveat. |
| F08 gFlex | Load-to-deflection equations and analytical/finite-difference verification. | Early physical-support reference; FFT is a derived candidate, not a certified stable feature claim. |
| F09 pyBacktrack | Thermal subsidence and solid-preserving decompaction. | Early where needed; inverse/reconstruction workflow is not generative physics. |
| F10 FastScape family | Restricted implicit incision, ordered graph sweep and ADI diffusion. | Surface-response reference after law selection; Python/Fortran/C++ scopes remain distinct. |
| F11 Landlab | Prescribed extension and TVD; routing/depression-policy separation. | First mechanism candidate, not blanket validation of all Landlab components. |
| F12 Badlands | Source-to-sink material, stratigraphy and controlled remeshing. | Later surface/material coupling. |
| F13 goSPL | Spherical finite volumes and explicit distributed face flux. | Scale study after a valid serial operator; no metre-scale claim. |
| F14 PyLith | Prescribed-slip mechanics, nondimensionalisation and interface constraints. | Optional diagnostic; not spontaneous rupture inferred from older papers. |
| F15 cutde | Triangular elastic response; dense/blocked/matrix-free trade-offs. | Optional diagnostic; low-rank compression is approximate. |
| F16 MAGEMin | Pressure–temperature–composition equilibrium and bounded properties. | Optional after material-state validity; not an eruption model. |
| F17 GDTchron | Independent thermal-history observables and batch histories. | Optional validation stage, not a tectonic driver. |

All entries inherit the source and version caveats of Reports 01–04. No new feature claim is based on the under-review pyBacktrack/goSPL extensions. No code or database copying is selected; a future implementation must review the exact source/data rights and required notices separately from the scientific method. [[R01](#research-basis); [R02](OPTIMISATION_REFERENCE.md#scientific-methods); [R03](#research-basis); [R04](#research-basis)]

## 10. Responsibilities across Atlas’s eighteen categories

This is an interface plan, not a task to build the whole generator now. Tectonics owns the selected deformation/material history. It should not absorb every downstream scientific responsibility.

| Category | Tectonic contribution / boundary |
| --- | --- |
| Plate tectonics | Plate/block motion, boundary history, supported regional deformation and material birth/recycling. |
| Geology | Material structure, deformation, thermal/magmatic histories and exposure; geology supplies density/strength/stratigraphy laws. |
| Topography and topology | Rock displacement plus explicit surface/support contributions; drainage topology remains a distinct physical/numerical responsibility from plate topology. |
| Hydrology | Geometry and structural changes, defined loads and boundary fluxes; no universal water dynamics implied by accumulation. |
| Political borders | Later constraints/opportunities only; physical deformation does not generate legitimate political ownership. |
| Settlements | Later terrain/ground opportunity and hazard context; not automatically realised sites. |
| Populations | Indirect downstream support/constraints; no tectonically determined population count. |
| Biomes | Indirect elevation/material and history forcing through climate/soil/ecology. |
| Climate | Continental positions, elevation and land–ocean geometry where used; full atmospheric circulation is separately scoped. |
| Precipitation | Explicit forcing for the test; later climate interaction, with intervals and units preserved. |
| Plant and animal ranges | Indirect habitat/barrier/history information, not biological coefficients inferred from geology. |
| Soils and ground conditions | Parent material, thermal/structural setting and disturbance; soil water/root/failure laws remain explicit. |
| Erosion and sediment transport | Tectonic forcing and exposed materials in; removal, transfer, deposition and unloading out. |
| Seas and coastal processes | Basin/coast/seafloor movement and selected boundary histories; water/sediment/sea-level conventions remain separate. |
| Resources and land suitability | Geological/magmatic/structural evidence; occurrence and economic/extractable quantities are separate claims. |
| Land use and agriculture | Later terrain, material and water constraints, not tectonic crop or food predictions. |
| Infrastructure and connectivity | Later topographic barriers, ground stability and hazard context; no road construction in this plan. |
| Natural hazards | Active structure, strain/slip, slab/volcanic setting as inputs; event probabilities, recurrence and exposure are separate validated models. |

<a id="milestones-decision-ownership-and-risk-control"></a>

## 11. Milestones, decision ownership and risk control

### 11.1 Milestones and permitted conclusions

| Milestone | Work packages | Permitted conclusion |
| --- | --- | --- |
| M0: case contract | W00 | A specific scientific question and acceptance procedure are defined. |
| M1: representation/accounts | W01–W02 | Geometry, motion and material bookkeeping pass their stated mathematical checks. |
| M2: vertical/thermal references | W03–W04 | Selected thermal, compaction and load responses are independently verified. |
| M3: first mechanism | W05 plus a W10 challenge | A stated extensional regime is physically supported within a measured envelope. |
| M4: tectonic breadth | W06–W08 plus relevant W10 challenges | Named spreading, shear, shortening and subduction regimes are supported; failures remain visible. |
| M5: terrain response | W09–W10 | The tectonic/surface combination has credible landform and material-history evidence beyond imposed outlines. |
| M6: useful scale | W11 | Behaviour survives specified optimisation/resolution/resource conditions. |
| M7: production/readiness | W12 | Reproducible supported outputs and recovery can be delivered at the stated scope. |

Thermal/support references and kinematics can be developed in parallel after W00. Regional mechanics is a separate branch and is not a prerequisite for the first kinematic extension check. W11 execution design and verified enabling acceleration accompany the relevant packages; its production-scale acceptance remains after physical evidence. Regime tests share infrastructure but do not inherit one another’s scientific pass. W12 cannot be pulled forward by an attractive screenshot or an implementation milestone.

**Decision ownership:** Michael chooses scope, world intent and resource priorities. Future coding agents implement the agreed case; they do not change its scientific criteria to get a pass. Independent reviewers challenge equations, assumptions, evidence and reproducibility. A suitably qualified domain review is desirable at physical acceptance gates; agreement among AI systems alone is not independent experimental evidence.

### 11.2 Highest-priority risks

| Risk | Mitigation and stop condition |
| --- | --- |
| Desired landforms become the answer key | Withhold validation cases; label Diadem fitting as compatibility, not proof. |
| Reference models become an unscalable permanent backend | Retain transparent cases; estimate representation costs early; select production representation only with accepted physics and matched-error evidence. |
| More adapter/version layers hide behaviour | Narrow pure interfaces and explicit dependencies; no source-bound in-place monkey-patching as the default new architecture. |
| Load or thermal response counted twice | One contribution owner/reference and isolated-effect tests at every coupling. |
| Rigid plates are treated as undeformable continents | Explicit deforming zones, block/plate distinction and supported strain partition. |
| Numerical regularisation creates the geology | Record it as part of the method; test mesh/parameter sensitivity and physical localisation length. |
| New material/retirement corrupts history | Separate birth/deposition/cooling ages, extensive ledgers, boundary transactions and remap tests. |
| Planetary scope drives premature complexity | Spherical primitives early, useful regional physics first, global physical scale only after gates. |
| Fine output is presented as fine evidence | Preserve four resolution descriptors and procedural-detail labels. |
| Missing closures are disguised by labels | C01–C07 block their claimed processes until specified, tested and reviewed. |
| Parallel work changes the physical result | Stable work/stream identities, explicit dependencies, current boundary data and PT01/PT02/PT07; no silent event or material divergence. |
| Caches or queued work exceed resources | Byte budgets, back-pressure, ownership and PT03–PT06; no unbounded pools or metadata-only source authentication. |
| A fast result cannot be recovered | Immutable accepted state, coherent publication and PT09–PT11; shared history is not disposable cache data. |

### 11.3 Items that remain open, with a concrete resolution point

Before W00 can be signed off: select the first case’s observables, physical domain and duration, benchmark/data access and finite experimental budget; fill the relevant execution-card decisions. Estimate early memory/work and identify safe parallel units without building a runtime framework. This plan recommends extension as the first coupled case but does not authorise executing it.

Before W07: choose the mechanical discretisation and C01/C02 specifications, including solver/thread ownership and true-residual checks. Before W08: close productivity/recycling, transitions and any claimed magmatism. Before W09: choose water/storage and sediment closures. For each enabling W11 study: identify the verified numerical baseline, actual workload, hardware, error criteria and finite limits; broader W11 scale claims also require relevant W10 acceptance. Before W12: agree public runtime/fixtures, release scope, recovery and source/data licensing decisions.

These decisions are not an excuse to keep writing general plans. Each is resolved in the smallest relevant package, with the case’s equations and expected evidence in hand. Do not attempt to decide every future planetary process before implementing the first independently testable mechanism.

## 12. Next development scope and review guide

**Next separately authorised task:** 3C-R4 — verify the thermal/mechanical core.
R3's local-law and 1D regularisation-primitive scope is delivered under revision 28;
coupled localisation and full benchmark reproduction remain explicit R4/R5 gates.
R2's registered initial-state/sampling envelope is delivered under revision 25;
its remaining general W01 responsibilities are explicit above. R1's reviewed
uses stay complete under revision 24, while strict consistency and external-model/
historical validation remain distinct unpassed claims. **R4 is not started.** Follow the
[explicit sequence](#plate-formation-implementation-plan). Causal formation later
requires the named W03/W07 subset; do not smuggle it into an unrelated W01 update.
Retain the current statistical candidates as controls, the existing geometry and
material knowledge, and regional W02. Complete remaining W01 stage-5–8 work through
the planned connections; no spherical geometry-to-1D physics equivalence is implied.

For Claude or another reviewer, review this plan in the following order: (1) whether the two deformation modes are honestly distinguished; (2) whether N01/N02 and E28 close the material/surface links without double counting; (3) whether C01–C07 identify real missing physics rather than hiding it; (4) whether the proposed cases can falsify errors independently of Diadem geometry; (5) whether the core 1.0 scope and later planetary aims are realistic and distinct; (6) whether optimisation is matched to a verified equation and fixed error budget; (7) whether the P01–P15 execution map respects nonlocal/sequential dependencies; (8) whether cache identities, resource admission, random streams and PT01–PT14 tests can catch real failures. Challenge any PF candidate whose added complexity exceeds its demonstrated benefit.

A review finding should identify the section/equation, the suspected physical or numerical failure, supporting evidence and the smallest correction or verification. Competing preferences are not defects by themselves. Proposed plan changes remain reviewable, not automatic code changes.

**Bottom line:** establish coherent motion and material accounts, verify thermal/support responses, demonstrate one causal mechanism, then earn each additional tectonic regime and its surface consequences. Efficient design and verified enabling acceleration support that investigation from the beginning. Broad physical scale claims and production integration still follow independent realism evidence. This is the plan—not a claim that any future gate has passed.

## References and evidence scope

The pre-study register remains historical evidence, not a separate maintained planning file. Scientific methods remain grounded in the four pre-studies and the original three benchmark leads. Revision 2 adds PS01–PS08: targeted official documentation about execution, parallel randomness, solver reuse, storage and measurement, checked on 16 September 2026. Dynamic documentation is not a pinned or installed runtime; select exact versions before implementation. Proposed Atlas rules are design judgements, not blanket claims about those packages. No source is evidence that Atlas ran or passed a test.

**[R01](#research-basis) — Modelling capabilities and scientific methods.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R02](OPTIMISATION_REFERENCE.md#scientific-methods) — Specific optimisation methods.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R03](#research-basis) — Implementation feasibility.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[R04](#research-basis) — Equation–process–method cross-reference.** Supplied Atlas pre-study, 15 September 2026. Planning evidence; not an installed or independently accepted physical model.

**[S01][url-008] — GPlates: pyGPlates Primer.** Official documentation. Rotation hierarchy, topology, deformation; documentation labelled pyGPlates 1.0.0.

**[S03][url-009] — pyGPlates: calculate_velocities.** Official API documentation. Rotation-based velocities and radius/time conventions.

**[S04][url-010] — GPlately: SeafloorGrid.** Official methods/API documentation. Documentation labelled 2.0.0; initial-age heuristic and surviving-seed artefacts explicitly described.

**[S06][url-011] — Fraters et al. (2019): The Geodynamic World Builder.** Peer-reviewed methods paper. Initial conditions, not time evolution; Cartesian and spherical geometry.

**[S08][url-012] — LaMEM official repository.** Official repository. Marker-in-cell, staggered finite differences, PETSc and rheology; no runtime reproduced.

**[S10][url-013] — ASPECT: Basic equations.** Official scientific documentation. Stable documentation labelled 3.0.0; equation families and approximations.

**[S11][url-016] — ASPECT: Material model.** Official scientific documentation. Creep, yielding and explicit warning about rheological parameter conventions.

**[S13][url-014] — Underworld: Introduction.** Official documentation. Underworld3 is a rewrite; Underworld2 remains a distinct code family.

**[S16][url-015] — May, Brown and Le Pourhiet (2015): Matrix-free multigrid for heterogeneous Stokes flow.** Institutional record of peer-reviewed methods paper. Q2–P1-discontinuous/material-point method and hybrid multigrid; full paper/code not audited.

**[S18][url-017] — Wickert (2016): Open-source modular solutions for flexural isostasy, gFlex v1.0.** Peer-reviewed methods paper. Analytical and finite-difference methods; boundaries and variable rigidity.

**[S20][url-018] — Hindle and Besson (2023): Corrected flexure finite differences with abrupt coefficient changes.** Peer-reviewed methods paper. Independent warning about discretising variable rigidity and interfaces.

**[S27][url-022] — Fastscapelib C++: Eroders.** Official API/scientific documentation. First-order implicit SPL and nonlinear Newton treatment; not all Fortran features inferred.

**[S28][url-023] — Braun (2023): Implicit algorithm for threshold stream-power incision.** Peer-reviewed methods paper. Accuracy and nonlinear convergence caveats; thresholds change the problem.

**[S39][url-024] — PyLith: Governing elasticity equations.** Official scientific documentation. Static/quasistatic/dynamic formulations and rheologies.

**[A01][url-001] — Atlas: coding and dependency map.** Pinned Atlas source documentation. Read through GitHub connector; active route and source-identity boundaries.

**[A02][url-002] — Atlas: active tectonic adapter.** Pinned Atlas source code. Read through GitHub connector; R3 snapshot, pinned inputs and no category acceptance.

**[A04][url-003] — Atlas: native common domain.** Pinned Atlas source code. Source-defined 256-cell envelope; not a product target.

**[A06][url-004] — Atlas: native numerical policy.** Pinned Atlas source code. Fixed-quantum accounting; must not be silently replaced by floating-point implementation.

**[A07][url-005] — Atlas: topography kernels.** Pinned Atlas source code. Target for relevant routing/geometry method study, not a claim of modification.

**[N-S01][url-019] — van Keken et al. (2008): A community benchmark for subduction zone modeling.** Primary author institutional record and abstract. Kinematically prescribed slab plus dynamically computed wedge. Full benchmark configuration/data not acquired or executed.

**[N-S02][url-020] — Schmeling et al. (2008): A benchmark comparison of spontaneous subduction models—Towards a free surface.** Peer-reviewed primary methods paper; publisher abstract/preview. Numerical/laboratory comparison; viscosity averaging and free-surface sensitivity. No figures/tables or performance results reproduced.

**[N-S03][url-021] — Schreurs et al. (2006): Analogue benchmarks of shortening and extension experiments.** Primary institutional bibliographic record. Candidate benchmark identified only. Full experimental configuration and data must be obtained before use.

<a id="research-basis"></a>

### Historical research basis

R01 (modelling), R03 (implementation feasibility) and R04 (the 28-equation/15-process cross-reference) are the dated pre-studies already supplied in this conversation. They remain source material, not additional maintained plans, and are not reproduced in this two-document edition. R02’s optimisation methods and the retained engineering methods now have their maintained home in the [optimisation reference](OPTIMISATION_REFERENCE.md). The primary scientific sources above continue to support the plan. A reference to R04 preserves an equation identifier; it does not assert that every R04 equation is fully specified or implemented here.


[url-001]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/docs/CODING_SAFETY.md
[url-002]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/generator_upgrade_r29/tectonics.py
[url-003]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/native_terrain_r1/domain.py
[url-004]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/native_terrain_r2/numerics.py
[url-005]: https://github.com/Atlantispy/atlas/blob/7d0e707a576fe08b9bcb816466a0a8fb5f115808/engineering/work/topography_r1/kernels.py
[url-006]: https://github.com/Atlantispy/atlas/blob/11317165b7e2aeab7201a1fe3e3f646cb640d51e/tectonics/README.md
[url-007]: https://github.com/Atlantispy/atlas/blob/11317165b7e2aeab7201a1fe3e3f646cb640d51e/tectonics/evidence/DELIVERY.md
[url-008]: https://www.gplates.org/docs/pygplates/pygplates_primer
[url-009]: https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities
[url-010]: https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.SeafloorGrid.html
[url-011]: https://se.copernicus.org/articles/10/1785/2019/
[url-012]: https://github.com/UniMainzGeo/LaMEM
[url-013]: https://aspect-documentation.readthedocs.io/en/stable/user/methods/basic-equations/index.html
[url-014]: https://www.underworldcode.org/intro-to-underworld/
[url-015]: https://www.research-collection.ethz.ch/handle/20.500.11850/690333
[url-016]: https://aspect-documentation.readthedocs.io/en/stable/parameters/Material_20model.html
[url-017]: https://gmd.copernicus.org/articles/9/997/2016/
[url-018]: https://se.copernicus.org/articles/14/197/2023/
[url-019]: https://ora.ox.ac.uk/objects/uuid%3A9f5ad33b-3fba-4658-9764-19436dfcc4e3
[url-020]: https://www.sciencedirect.com/science/article/pii/S0031920108001568
[url-021]: https://gfzpublic.gfz.de/pubman/item/item_234212_1
[url-022]: https://fastscapelib.readthedocs.io/en/latest/api_cpp/eroder.html
[url-023]: https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023JF007140
[url-024]: https://pylith.readthedocs.io/en/stable/user/governingeqns/elasticity/index.html
