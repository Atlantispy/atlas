# I01: resolve subduction initiation, rather than prescribe its resistance

WORKING NON-CANON. **Selected method and test specification, not an implemented
initiation model or passing subduction benchmark.** [The companion case](../cases/i01_initiation_decision_v1.json)
is not runnable configuration. I01 selects the resolved method and the independent
[analytical verification route](I01_INITIATION_VERIFICATION.md). I07 owns its full
implementation and physical acceptance; missing published-case inputs no longer
block the I01 method decision.

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

**Preferred primary candidate: Li and Gurnis (2023), not yet an admitted case.**
The [archive](https://data.caltech.edu/records/haw6e-eck15) provides actual code
and numerical histories, but its incomplete inputs prevent exact reproduction.
It remains an optional external comparison, not a prerequisite to I01 selection.
Gurnis, Hall and Lavier (2004) remains supporting evidence; its
retained record below is not relabelled as the newer experiment. The
[companion record](../cases/i01_initiation_decision_v1.json) pins the three
inspected files and the findings under `replacement_source_review`.

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
Those requirements remain mandatory for full numerical/physical acceptance in
I07; they are not prerequisites for testing an independently specified equation.
The [separate verification specification](I01_INITIATION_VERIFICATION.md) locks
synthetic inputs and analytical error limits for gravity-driven viscous flow,
force release versus clamping, and gravitational versus stored-elastic work.
Its passing controls establish these prerequisites, not slab initiation. This is
the selected I01 alternative to waiting indefinitely for an incomplete archive;
no published constants, missing profiles or comparison allowances are guessed.

### Replacement archive assessment

[Li and Gurnis (2023)](https://doi.org/10.1093/gji/ggac332) compares an analytical
force balance with nonlinear thermomechanical calculations, including imposed
velocity/force and viscoplastic/viscoelastoplastic branches. These allow useful
force/convergence and elasticity comparisons. The analytical solution is a
comparison, not a new authored resistance to insert into Atlas's solver.

The inspected README identifies Underworld 2.7.1b. No external code was executed
or installed. Its paragraphs, table and equation text were extracted; document
layout could not be rendered because the bundled renderer lacked LibreOffice.
This does not prevent reading the parameter labels, but no visual README QA is
claimed. The source and numeric archive were inspected directly, not inferred
from the existence of a download link.

`T1_rec` and `F1_rec` each have shape 16 by 40, with 332 paired finite samples;
remaining slots are paired trailing NaNs. One entire row is missing. Converted
with the source's 365-day year, `u` spans 2 through 17 cm/year; the empty row is
10 cm/year. Missing samples are not zeros, and shared speed is not proof of a
shared rheology. The source requires `inputfile.txt`, which is absent from the
archive listing. Its 15-column interface is recorded, but no complete input row
or raw-row-to-rheology mapping has been recovered.

The README labels time as Myr, speed as m/s and force as N/m. Therefore its
shorthand `time*speed` needs a Myr-to-seconds conversion to yield metres. The
code's input velocities instead use m/year. The stored force diagnostic is a
plate-interior integral of `tau_xx-tau_zz`, not automatically Atlas's signed
boundary reaction. Early raw forces are negative; every nonempty row begins
with a zero force at zero time. The source's tensile-positive stress difference
can be negated to report compression-positive **column** force, but its relation
to boundary work still needs establishing. The code projects initially zero
stored stress before its first stress update, explaining its initial zero; this
does not prove the unprovided aggregation history of the NPZ.

Three further distinctions matter:

- The code uses 1400 C for thermal scaling but 1500 C in activation scaling.
  Substitution into its uncapped creep exponent gives an effective activation
  energy of **504 kJ/mol**, not the literal 540 kJ/mol numerator. At 1000 C and
  fixed strain rate the viscosity ratio to its 1400 C reference is 44.5686,
  versus 58.4543 using 540 kJ/mol. This is an algebraic reconstruction of the
  source, not permission to repair it or change Atlas's creep law silently.
- Its weakening history accumulates total strain rate when yielding; Atlas uses
  resolved plastic strain rate. A factor-of-two conversion cannot generally make
  those different histories equivalent.
- Its `stopstep` branch sets right-boundary horizontal velocity to zero. Atlas's
  release branch removes driving traction and allows motion. Keep these tests
  separate, along with their energy accounts.

### One case reconstructed as far as the sources support

The [bounded reconstruction tool](../tools/reconstruct_i01_initiation_case.py)
now reads only the three hash-pinned archive files, without executing the
downloaded Python. Its [retained output](../cases/i01_li_gurnis_reconstruction_v1.json)
keeps all 24 finite pairs from zero-based row 2, whose nominal speed is 4 cm/year.
The converted distance extends to **199.584348 km**. Trailing NaN pairs are
reported as omitted padding; holes, unpaired padding, empty rows and changed
files are refused. Initial zeros and original signed values are retained.
Compression-positive column force and nominal convergence have distinct names
from the admitted comparator's boundary-resistance inputs. No work integral,
release classification or initiation threshold is inferred from this record.

The source velocity varies with depth through a tanh function: speed times time
is therefore labelled nominal convergence, not the integral of a measured
material path. Its active undeformed mesh represents a 900 by 6 by 450 km box
with 256 by 2 by 128 elements and periodic strike direction. These are facts
about the archived script, not proof of the mesh behind a published curve.

The intended target is the published 4 cm/year VEP comparison. Paper section 3
and Table 1 provide 20/40 Myr overriding/subducting plates, 25/8 km continental/
basaltic crust, 20 km weak zone, 45-degree dip, 150/3 MPa maximum/residual strength
and 30 GPa shear modulus. The machine-readable reconstruction labels these as
paper descriptions, **not an authenticated input row**. Figure 4 separates VP,
analytical and VEP panels, but supplies no archive-row key. Matching speed alone
cannot identify the constitutive branch.

The deeper inspection found a second absent required file, `morbphase.txt`.
Source lines 294-305 and 362-376 load it and use it in basaltic crust density;
the pressure/temperature axes alone cannot reconstruct its values. The paper
cites Hacker, Abers and Peacock (2003), DOI 10.1029/2001JB001127, but a citation
does not identify the exact table. Substituting the separate Atlas melt provider
would change the experiment. The archive's Figure 7 labels also conflict with
the final paper's spatial curvature/strain-rate Figure 7, so its panel mapping
is not accepted on the README's authority alone.

The paper/code comparison also exposes constitutive and timestep differences.
Paper Table 1 calls 0.6 a friction **coefficient**; section 3 uses `mu*p+C`.
The active script instead treats 0.6 as an angle in radians and uses
`C*cos(phi)+p*sin(phi)`: before capping, its initial pressure coefficient is
0.564642 and its cohesion contribution is 36.3148 MPa rather than the supplied
44 MPa. Weakening these quantities is not the same law. The linked supplement's
S2 (PDF pages 2-3) associates Figure 4c with an elastic timestep near the numerical
timestep, whereas Figure S5's caption (page 7) associates Figure 4c with its
1 Myr panel rather than the 1.5 kyr panel. The archived script's effective
elastic interval is approximately 1.057 Myr. These are unresolved source
conventions, not reasons to select whichever case matches an Atlas outcome.

**Completion requires missing source information:** the selected case's input
row, basalt density table and raw-row/rheology provenance, plus resolution of the
remaining published/code conventions. Do not repeat figure digitisation or run
the solver to guess them. If these cannot be recovered, a fully declared Atlas
verification case is a different comparison track, not an exact reproduction.
Raw histories avoid reading error but not numerical error; lock allowances only
after the case is coherent. All 15 active input/curve/policy groups stay unfilled.

```text
python -B tectonics/tools/reconstruct_i01_initiation_case.py ARCHIVE_FOLDER --output NEW.json
python -B -m unittest discover -s tectonics/tests -p test_i01_initiation_reconstruction.py
```

The eight focused checks cover units/signs, preservation, missing or unordered
data, source identity, exclusive output and an independent algebraic form of the
activation exponent. These establish reconstruction behaviour, not subduction
accuracy. Only 21 kB of numeric source data are loaded; no mesh, external solver
or repeated simulation is allocated.

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

The new [executable extraction](../tools/extract_i01_initiation_curves.py) and
[complete output](../cases/i01_initiation_digitisation_v1.json) retain 28 graphical
force intervals across Figures 8b and 13a. They include the source PDF hash,
panel/tick coordinates, PDF-to-axis transforms, exact vector selectors and path
digests, stroke/intersection rules, unrounded extrema and parser versions.
The research owner executed the script with CPython 3.13.5, PyMuPDF 1.26.7 and
MuPDF 1.26.12: five synthetic geometry/rounding tests passed and all 28 rounded
bands matched the earlier readings. Historical raw extrema were not retained,
so raw-to-raw parity is unknown. The current record retains the new horizontal
half-widths; the largest correction is 0.0000037312 km, not a change to the bands.
Local review checked the complete script/output, source hash, units, Figure 8b
case colours and Figure 13a left/right plate identities visually. The exact PDF
parser is not installed locally; no rerun or substitute-parser parity is claimed.

Run `python -I -B tectonics/tools/extract_i01_initiation_curves.py INPUT.pdf NEW.json`
in the recorded parser environment. It refuses a changed PDF, changed parser,
ambiguous vector selection, unsupported clipping/strokes or existing output.
It clips every original line segment against a half-stroke-width horizontal
slab, includes all intersections without joining gaps, expands vertically by
half the stroke width, and rounds outwards. The old bands are used only for
the final comparison, not to choose an answer. This is a declared rectangular
reading convention, not an exact reconstruction of stroke ink.

The data remain **reported, not admitted** to a simulation comparison. Axis
systematic uncertainty has not been quantified: tick-fit residuals are diagnostics,
not automatically valid uncertainty bounds.
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

Next implementation owner: I07. Implement the shared general stress/history
kernel and lock a supported Atlas forced/released case before the full initiation
campaign. Exact Li-Gurnis reproduction can be revisited only when its missing
source information is available. The analytical verification route does not
remove mesh/time, boundary-sensitivity, physical-input or force-release gates.
Do not create a second implementation of the common material law.

## 6. Sources actually checked

- [Li and Gurnis (2023), A simple force balance model of subduction
  initiation](https://doi.org/10.1093/gji/ggac332) and its
  [CaltechDATA archive](https://doi.org/10.22002/D1.8958): published model/diagnostic
  descriptions, archived Underworld script, README and numeric array contents.
  The file identities and source-line locators are in `replacement_source_review`.
  These support selecting the next benchmark candidate, not a reproduced case.
  The source-reconstruction research additionally inspected section 3/Table 1,
  Figure 4/7 captions and the article-linked `ggac332_supplemental_file.pdf`,
  especially S2 and Figure S5. Hacker, Abers and Peacock (2003) is a recovered
  density-law citation, not a newly reproduced table or independently tested law.
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
