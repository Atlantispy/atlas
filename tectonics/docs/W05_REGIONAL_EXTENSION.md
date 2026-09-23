# W05 step 1: prescribed regional extension

22 September 2026. **WORKING NON-CANON — mechanism specification complete;
implementation and acceptance NOT YET COMPLETE.** This is the first of the five
W05 steps, not a new terrain generator or a passed realism experiment.

## Selected mechanism and scientific boundary

Select a dry, isothermal, constant-density crustal section with a prescribed
listric detachment, conservative hanging-wall transport, and one quasi-static
elastic support response. Coordinates are Cartesian x (fault-normal, positive
down-dip) and z (positive upwards), with constant transverse accounting width W.
The solution is invariant along strike, not a finite-width 2D plate. Time is s;
horizontal velocity is m/s; positive-down support displacement w is m.

The fault geometry and horizontal displacement are inputs, not consequences of
solved stress. A competent effective supporting layer continues beneath the
detachment; the fault is **not** silently treated as a broken elastic plate.
Effective elastic thickness Te is independent of crustal thickness and is fixed
in time. This is a reduced kinematic-plus-support model, not the full flexural
cantilever, yielding, fault-initiation or lithospheric stretching/thermal model.

There is no erosion, sedimentation, water, pore pressure, heat evolution,
magmatism, dynamic mantle traction, in-plane stress or self-selected fault
motion in the initial case. Dry does not mean above sea level: negative z is
allowed without automatically filling the basin. Adding those processes later
requires their own mass/heat/geometry treatment; no default Earth/Diadem values
or unconnected W03 cooling arrays are inferred.

## Geometry, state and conservative transport

Initial surface z0=0, crust base b0=-Hc0, detachment depth 0<d<Hc0,
surface dip 0<theta<pi/2 and zero-surface trace xf are explicit. Define
xi=x-xf, lambda=d/tan(theta), and the footwall upper surface in the unflexed
coordinate system:

```
f(xi) = 0                              xi <= 0
      = d * expm1(-xi/lambda)           xi > 0
F(xi) = f(xi) - b0                     stationary footwall thickness
H0(xi) = -f(xi)                        initial moving hanging-wall thickness
```

The branch at xi=0 is a continuous, piecewise-smooth exposed-footwall join, not
a globally C1 fault through air. No huge exponential is evaluated on the negative branch.
Sample **cell means** by integrating across the trace; centre samples do not
establish inventories. F+H0=Hc0 exactly in the continuum.

Transport only the hanging wall, keeping the stationary footwall separate:

```
partial_t H + partial_x(u H) = 0
H = sum_k H_k; M_k = rho_c * W * sum_i(H_ki * dx_i)
d/dt integral_[L(t),R(t)] H dx = (u-vL)H|L - (u-vR)H|R
```

H_k denotes partial cohort thickness, not a second independently evolved total.
All initially supported cohorts share rho_c. Material, plate, frame and epoch
identities remain distinct. Formation ages are not reset by motion. External
fluxes are signed and retained by cohort; the calculation is regional, not a
closed whole-planet inventory. No negative thickness or missing inventory is
repaired by clipping.

The first physical case has u=U>=0 constant, a=U*t and fixed Eulerian cells.
Its exact continuum solution is H(xi,t)=H0(xi-a). Uniform translation conserves
the thickness of a moving parcel; local crustal thinning arises because the
hanging wall moves away from the fixed footwall. It is **not** uniform pure
shear of the entire crust. Applying U to F+H would move the footwall incorrectly.

For a parcel initially at (X,Z), before flexure:

```
x = X + a
z_kin = Z + f(x-xf) - f(X-xf)
```

This vertical-shear map has unit area Jacobian, is tangent to the prescribed
basal surface for particles on it, and keeps relative height above the fault.
It defines a kinematic reconstruction, not a stress solution or an assertion
that real beds remain undeformed. The numerical material state is cell-integrated;
subcell depth order is not invented from mixed cohort totals.
Horizontal displacement a is **heave**, not distance travelled along the fault.
Side-by-side plate-ownership reassignment is not a substitute for sliding these
vertically superposed bodies.

**Separate divergent-flow verification:** use material-following edges
x(t)=beta(t)X and H=H0/beta, with u=(beta_dot/beta)x. It tests dilution under
extension and relative boundary flux. The finite-increment W02 u=v_mesh test
uses beta_step=1+epsilon*dt, not exp(epsilon*dt) unless that exponential edge
history is explicitly supplied. This control is not added to the listric case.
General velocity divergence requires the conservative equation above, not the
passive-scalar equation partial_t H+u partial_x H=0.

## One load and one vertical response

This section is the Atlas-derived closure to connect the selected kinematics to
the existing W04 physical-load contract. On the fixed load grid, let

```
Hc(x,t) = F(x) + H(x,t)
delta_Hc = Hc(x,t) - Hc0
z_kin(x,t) = b0 + Hc(x,t)
q(x,t) = rho_c * g * delta_Hc            Pa, positive down
D = E * Te^3 / [12(1-nu^2)]             N m
K = rho_m * g                           Pa/m, rho_m > rho_c > 0
D * d^4w/dx^4 + K*w = q
z(x,t) = z_kin(x,t) - w(x,t)
b(x,t) = b0 - w(x,t); f_supported(x,t) = f(x) - w(x,t)
```

Construct q with W04's finite column loads: occupied rock volume A*Hc, reference
A*Hc0, air/void replacement density zero, A=W*dx and fixed support height Hc0.
The initial translating profile only unloads, so it fits that height. A future
thickening case must declare adequate support capacity before running, never
silently enlarge a sealed reference. Separate stationary and moving rock phase
IDs may share the same density; they may not overlap in volume.

The mantle displacement is already represented by K*w. Do not also put that
moving mantle into q, use a second crust-mantle contrast load, add local Airy
uplift, or repeatedly add a total w to the previous surface. q and w are always
**total changes from the same initial reference**. The compensating mantle is a
declared hydrostatic reservoir, not W02 crust generation. Its volume change is
-A*w in this reduced vertical-column account; the model does not predict mantle
flow or claim a finite globally closed mantle reservoir.

Independent hydrostatic check: when support is locally compensated,
w=(rho_c/rho_m)*delta_Hc and
delta_z=(1-rho_c/rho_m)*delta_Hc. Thus thinning produces unloading/rebound, but
the rebound only partly offsets the initial thickness loss. The net basin
subsides. With flexure, neighbouring unloaded footwall can rise even where
delta_Hc=0; neither response is to be imposed by a terrain-shape target.

The physical parcel projection is z=z_kin-w(x,t), whose vertical velocity
contains -(partial_t w+u*partial_x w), not just -partial_t w. Footwall u=0.
This is the leading-order small-slope column projection, not a new finite-strain
elastic mapping. Do not feed a flexed surface back into H=z-f using the old f:
that would turn support motion into fictitious material. The transported state
stays in the unflexed reference frame; final surface/base/fault are derived views.

## Regional boundaries and support representation

Use open regional material boundaries: specified zero hanging-wall inflow from
the left (L<xf) and accounted rightward export. Zero hanging wall at the left
does not delete the stationary footwall. Initial and exterior right-side
hanging-wall geometry are explicitly the same exponential family.

Use W04 **uniform-D continuous-plate** support, not a periodic wrap or a clamp
at the map crop. The uniform solver integrates cell-constant pressures exactly;
its point-centre/face outputs must not be labelled output cell means. The output
crop, computed load domain and physical exterior are separate. Missing exterior
loads cannot be made exact by calling them zero.

Canonical gridded surface output is a **cell mean**:
z_bar=b0+F_bar+H_bar-w_bar. Step 3 must obtain w_bar by integrating the analytic
W04 response over the cell (or controlled quadrature with <=0.01 m absolute
error), alongside its existing centre/face diagnostics. Reuse cell-integrated
weights when available; this is output integration, not another physical solve.
Never add centre-sampled f to unlabelled mean H and call it point topography,
or substitute centre w for mean w without an explicit verified error treatment.
The continuum parcel map remains an independent reference; visual interpolation
does not change the accepted inventory or turn cell means into measurements.

For source right edge R>xf+a, the exact omitted load has the bound

```
QR = rho_c*g*d * exp(-(R-xf-a)/lambda) * [-expm1(-a/lambda)]
QL = 0, for L < xf
alpha = (4*D/K)^(1/4)
abs(delta_w_tail) <= QR*exp(-(R-x)/alpha)/(sqrt(2)*K)
```

Declare zero far-field load as an approximation with this nonzero uncertainty;
include W04's slope/curvature uncertainty bounds in validity checks too. A
reference tail at t=0 is exactly zero. Exp underflow must not create a false
zero uncertainty claim: use a conservative representable upper bound or refuse.
Domain enlargement retains the same physical exterior profile and output crop.
Uniform-D uncertainty bounds do not automatically validate variable-D support.
Physical free/clamped ends and evolving rigidity are not needed for this case.

## Bounded synthetic execution case for steps 2-5

These are declared numerical challenge inputs, **not measured calibration or
Diadem canon**. Their order of magnitude alone is not evidence of realism.

| Input | Selected value |
| --- | --- |
| Hc0, d, theta, xf | 30,000 m; 10,000 m; pi/4 rad; 0 m |
| rho_c, rho_m, g | 2,800 kg/m3; 3,300 kg/m3; 9.81 m/s2 |
| E, Te, nu | 70 GPa; 5,000 m; 0.25 |
| U and duration | 0.001 m per declared 31,557,600 s year; 1,000,000 such years |
| Transverse bookkeeping width | 1 m; the physical solution remains strike-invariant |
| Output times | a = 0, 250, 500, 1,000 m horizontal displacement |
| Load/transport domain; output crop | [-160,240] km; [-40,80] km |
| Grid study | dx = 500, 250, 125 m; 800, 1,600, 3,200 source cells |
| Time study on dx=250 m | 32, 64, 128 equal transport steps; no ceiling change |
| Domain study at dx=250 m | enlarge source domain to [-240,320] km, same crop |
| Explicit support envelope | abs(w)<=1,000 m; abs(w')<=0.1; Te*abs(w'')/2<=0.01, including exterior uncertainty |

Computed directly from the specified equations (not from a generator run):
lambda=10,000 m; D=7.777777777777778e20 N m; K=32,373 Pa/m;
alpha=17,606.909974655 m. At a=1,000 m the maximum unflexed drop, at x=xf+a,
is 951.625819640 m and q there is -26,139,258.0139 Pa. The corresponding
**local-isostatic control**, not a prediction for finite D, is 144.185730249 m
net subsidence. The full-line integrated crust deficit is d*a=1e7 m2,
equivalently 1e7 m3 per metre of strike (2.8e10 kg/m); finite-domain export must
instead use its own exact bounds.
For the base source domain, QR=0.001090574 Pa and its displacement effect on
the stated output crop is bounded by 2.694e-12 m under the uniform-D assumptions.
The highest constant-U CFL in the grid/time combinations is 0.25.

## Independent references and acceptance gates

Step 2 implements an independent adaptive-quadrature reference in
`tests/w05_reference.py`, with no Atlas imports. It integrates the point profile
and boundary flux separately, including split fronts and tiny local intervals.
Use the exact characteristic solution with a separate integration path from the
production flux solver. For s>0 define J(s)=d*[s+lambda*expm1(-s/lambda)], else
J(s)=0. Then cell-average H is [J(r-xf-a)-J(l-xf-a)]/(r-l), and finite-domain
inventory change per width is
J(R-xf-a)-J(L-xf-a)-J(R-xf)+J(L-xf).
For U>=0 the cumulative right export is J(R-xf)-J(R-xf-a); left input has the
same expression at L. Stable small-argument evaluation and independent numerical
quadrature must challenge cancellation near the front rather than repeat the
production expression as its own test.

Use independent adaptive quadrature of the continuum Green function against the
piecewise analytic q as the coupled reference. Split at xf, xf+a and the
evaluation point. Do not compare a cell-constant production load to a smooth
continuum reference as if their discretisation errors were zero. First test the
same cell-constant load, then measure the smooth-load refinement error separately.
Landlab/gFlex can be additional matched-equation comparisons; neither is a
mandatory runtime dependency or a substitute for these independent controls.

The following gates must be frozen in the executable case before results, not
tuned to a desired basin. Failure means diagnose/refine within the envelope or
retain INCOMPLETE, not silently loosen the target.

| Gate | Required evidence |
| --- | --- |
| Accounting and identity | Existing W02 arithmetic/error contracts unchanged; all cohort and total boundary receipts close; no clipping, duplication, fake birth or footwall transport. |
| Kinematics | Zero motion, exact translation/cell means/finite exports and the separate divergent-flow dilution control; positivity and source history preserved. |
| Component isolation | Kinematics-only, support-only on the same q, and combined output satisfy z=z_kin-w; zero delta load and repeated output requests do not accumulate movement. |
| Numerical accuracy | Finest-grid crop H error <=10 m maximum and <=5e-3 relative L1 against exact cell means; smooth-load reference w error <=1 m maximum on crop centres/faces. Relative L1 uses the crop integral of abs(H_exact), with zero-reference cases tested absolutely. |
| Time/domain sensitivity | 64->128 step cell-mean surface difference <=1 m on the same crop; enlarged-domain difference <=0.01 m with conditional exterior bounds included. Grid errors must decrease toward the independent reference; do not demand a formal second-order rate at fronts. |
| Signs and amplitudes | Local-isostatic control above; for finite D, compare cell-mean basin minimum, footwall peak and locations against equivalently averaged independent convolution, not the local amplitude. Extrema location difference <=one finest cell; no imposed universal sign at every forebulge. |
| Physical approximation | Enforce the explicit dry displacement/slope/strain envelope above with uncertainties; apply plate-slope limits to w, not to the steep prescribed fault. The W03-bound wrapper's cooling-thickness displacement scale cannot be borrowed into dry W05. Passing does not prove long-term constant-Te rheology. |
| Engineering | Exact restart/reference reconstruction, cold/warm cache parity, cancellation/resources, unsupported input refusals, and a bounded end-to-end timing at matched accuracy. |

Reference quadrature uncertainty must be <=0.01 m in w before it can judge the
1 m target. Compare identical output times, domains, units, boundary physics and
quantity support. Inspect both scientific answers and accounting, not only a
plausible rendered image. No full Diadem, held R4.4 or multiday run is needed.

**Physical challenge beyond numerical acceptance:** select a published balanced
analogue cross-section with explicit fault shape, imposed displacement and
uncertainty. Compare normalised rollover shape and section-area/export closure
without fitting them all as inputs. Test support separately against a case with
independent load/density/Te constraints. Do not treat resemblance to the North Sea,
or the synthetic figures above, as field validation. No observational dataset or
uncertainty is silently supplied here; the empirical challenge remains pending.

## Integration and efficiency decisions before implementation

- Reuse W02 `MaterialState` on `ColumnGrid1D`, native conservative transport and
  existing immutable histories. Use `advect_ale` with zero mesh velocity for the
  fixed-grid baseline, and with declared moving faces for the divergent control.
  The older `advect_materials` requires `RegionalGrid1D`; it is not interchangeable
  with the selected `ColumnGrid1D` path.
  Boundary receipts are signed **into** the domain in m2 per transverse width;
  convert to kg with rho_c*W once. The selected left inflow is exactly zero at
  all times; a later nonzero time-dependent inflow cannot be passed through
  W02's interval-frozen boundary API without a declared sampling/error policy.
- Add a narrow W05 reference/geometry/load adapter in subsequent steps. W04
  `ColumnLoadState` and `column_load_change` can represent the load; the existing
  `PreparedW04Support` wrapper requires stationary W03 states and must not be
  impersonated or have its guard removed to accept this new route.
- Reuse prepared `FiniteRegionFlexure` and existing load/flexure reuse functions.
  Preserve full identity, reference, exterior uncertainty, source and runtime
  validation in the new adapter; a generic array kernel alone does not do this.
- Transport cost is linear in cells/cohorts per step; uniform support uses
  prepared linear FFT convolution. Solve support only at requested output times:
  it does not feed back into this case's prescribed u or unflexed inventory.
  This is exact within the selected one-way closure, not a coarse-time shortcut
  for future stress/erosion/thermal feedback. Baseline support evaluations are
  three nonzero outputs, not 128 timesteps.
- Keep reference, current material state, cumulative exchange and requested
  outputs; do not retain every trial array. Use existing admitted lossless
  snapshots/recovery, not another history store. Cache cheap derived expressions
  only when existing admission shows reuse pays; precompute fixed geometry.
- No process pool inside sequential transport or nonlocal support. Independent
  refinement cases may run concurrently only within the existing budget.
- Measure transport, support, preparation/restart and end-to-end elapsed time
  separately against matched-output controls. The change in support-call count
  is a design property, **not yet a measured wall-time saving**. Direct analytic
  translation is the reference first; an optional production fast path must
  preserve cohort/export/restart contracts and earn its own comparison.

## Papers and existing software actually checked

Reviewed on 22 September 2026; no external software was installed or run, and
no external code was copied. These sources inform the design, not its acceptance.

- [Landlab ListricKinematicExtender tutorial](https://landlab.csdms.io/tutorials/tectonics/listric_kinematic_extender.html):
  theory and flexure-coupling example reviewed. Informed the prescribed
  exponential detachment and separation of moving and stationary material.
  Its illustration is not an empirical calibration or a divergence test.
- [Landlab component source](https://landlab.csdms.io/_modules/landlab/components/tectonics/listric_kinematic_extender.html):
  geometry setup, advection wiring and surface update read. We retain our own
  conservative inventory and source controls; tutorial years become explicit
  seconds, and the initial/final support reference must remain unambiguous.
- [Wickert (2016), gFlex v1.0](https://gmd.copernicus.org/articles/9/997/2016/):
  full-text sections 2.1/2.3/2.4 and boundary discussion checked. Informed
  load/infill separation, continuous-plate versus broken-plate distinction,
  and the deliberately restricted fixed-rigidity approximation.
- [McKenzie (1978), Some remarks on the development of sedimentary basins](https://doi.org/10.1016/0012-821X(78)90071-7)
  ([full-text copy](https://www.zetaware.com/public/McKenzie_1978.pdf)):
  section 2/Figure 1 and assumptions checked. Distinguished pure stretching and
  later thermal subsidence from the selected dry fault-motion experiment;
  this specification does not claim to reproduce that thermal model.
- [Beaumont (1978), The evolution of sedimentary basins on a viscoelastic lithosphere](https://doi.org/10.1111/j.1365-246X.1978.tb04283.x):
  publisher summary only. Supports separating basin initiation from adjustment;
  no viscoelastic coefficients or solver have been adopted from this access.

Kusznir, Marsden and Egan (1991), DOI 10.1144/GSL.SP.1991.056.01.04, was located
but the publisher article could not be retrieved. It is not claimed as a
full-text review or the implemented method. Existing Atlas W02/W04 contracts
were checked directly alongside the independent interface review.

## Completion and next step

Step 1 delivered the selected mechanism, equations, boundary/ownership decisions,
synthetic challenge, independent-reference design and efficiency choices.
**Step 2 is now implemented and checked:** conservative prescribed motion,
cell-mean thinning, stationary footwall, cohort history and finite-domain exports.
See [the motion evidence](../evidence/w05-motion.md). **Step 3 is now implemented
and component-verified:** load/support coupling and true cell-mean geometry;
see [support evidence](../evidence/w05-support.md). **Step 4 recoverable optimised
workflow is now complete:** [workflow evidence](../evidence/w05-workflow.md).
**Step 5 combined acceptance now passes the selected dry prescribed 1D workflow:**
[acceptance design](W05_COMBINED_ACCEPTANCE.md) and [measured evidence](../evidence/w05-acceptance.md).
The five-step numerical sequence and separate empirical challenge plan are complete;
the actual empirical comparison awaits independently bound analogue/support data.
Existing W01/R4.4 holds are unchanged. No later workstream is automatically started.

Step-1 review confirmed the dry load/sign/accounting derivation and checked actual
W02/W04 API boundaries. Its geometry, unit, cell-mean, exterior and dry-validity
corrections are incorporated above. Only documentation changed. Source-only
checks passed: 13 selected maps/41 paths; 30 safety tests passed, one Windows
symlink test skipped (31 reported, 0.110 s); `git diff --check` passed. Synthetic
numbers above were evaluated directly with standard-library arithmetic. No W05
runtime, external-package, generator regression or performance run was performed.

### Step 2 implementation and algorithm selection — 22 September 2026

`PreparedListricExtension` binds a `ColumnGrid1D`, `ListricGeometry`, explicit
velocity/density/width, named cohort fractions, epoch/datum/source and verified
execution identity. `initial` and `advance(state, time_s=...)` return immutable
`ExtensionState` objects. `geometry_fields` returns columns H, F, Hc and unflexed
cell-mean surface change, all in metres. Exchanges are cumulative signed m2 INTO
the represented section, referenced to the initial material; mass is rho*W times
that account. Parent transitions retain the actual request history without
duplicating all past cell arrays. A repeated same-time request returns its input.

The default `transport='characteristic'` integrates the prescribed translated
exponential exactly in each cell, using stable local exponential/series formulas.
It retains the same independent boundary-flux and W02 arithmetic-balance checks.
The kernel is O(cells*cohorts) per requested output, with no CFL substeps or
repeated interpolation. This path is ONLY for the admitted constant-U,
exponential initial geometry and constant spatial cohort fractions. It neither
silently replaces arbitrary stratigraphy nor treats translation as divergent
stretching. The separate material-following ALE dilation control verifies H/beta.

The explicit `transport='muscl'` route retains native/reference W02 transport and
its existing per-step cache. It is a comparison route: at the frozen 125 m grid
and 128 intervals its moving-front error is 24.5848 m, failing the 10 m gate.
The exact characteristic alternative passes without changing that threshold.
It matches independent quadrature to 5.457e-12 m globally (3.638e-12 m in the
acceptance crop); errors are already roundoff-sized on all three frozen grids,
so there is no meaningful asymptotic convergence rate to fit. Final material
and exports are bit-identical after 64 or 128 requested outputs. Enlarging the
domain changes the common crop by exactly zero for this motion-only case.

For characteristic transport `steps=1` means one requested output, not one
approximate numerical step. Per-step cache arguments are refused explicitly;
there are no internal steps to cache. Fixed geometry/initial inventories and
execution context are prepared once. Durable W05 output reuse/recovery is supplied
by the step-4 workflow below, not a second per-internal-step cache.
Both public numerical backends use the same vectorised analytical integrals;
`reference`/`numba` choose inventory and total-field reductions. The native
backend reduced the measured three-output sequence from 0.295834 s to 0.270354 s,
but preparation was 0.210932 s versus 0.127891 s in the already-warm process.
Thus reference reductions are preferable for this short one-off case including
setup; native preparation pays back only with enough reuse (about four such
sequences in these measurements). Neither timing includes first-ever JIT startup.

Numerical/resource guards reject unresolved endpoint clocks, underflowed positive
cohorts/displacements, excessive cells/intervals, foreign states and changed
source/live code. Call budgets must descend from the prepared owner, and any
MUSCL store budget must also be an ancestor of the active compute budget. The
same allowances therefore cover nested computation, including cache bypass.
Closing the preparation releases its reservation. Returned retained states are
owned by the caller, as in W02; no memory-mapped or history archive is implied.

Additional implementation reference checked: [Clawpack's Riemann-book advection
chapter](https://www.clawpack.org/riemann_book/html/Advection.html), especially
conservation and constant-speed characteristics. The Landlab tutorial's theory
was reopened alongside it. Documentation was read; neither external package was
installed or run. Independent SciPy quadrature and existing Atlas W02 were run.

### Step 3 implementation — 22 September 2026

`PreparedExtensionSupport(motion, policy)` consumes the accepted characteristic
motion preparation without modifying it. `ExtensionSupportPolicy` requires
explicit `FlexureParameters`, displacement/slope/strain/exterior-error limits and
source identity. `solve(state)` computes q and w from the SAME initial reference;
repeated or out-of-order output requests cannot accumulate deformation.

Separate stationary footwall/moving hanging-wall finite-volume phases preserve
small unloading changes against a large crustal baseline. At preparation, fixed
F volume is capacity minus initial H volume, checked against the geometric F to
1e-12 relative arithmetic accuracy. Moving inventory is untouched. The initial
support height remains Hc0; no headroom or infill is silently introduced.

`ExtensionSupportResult.cell_means` columns are q, w, unflexed surface change,
surface, base, fault, Hc, H, F, and hydrostatic mantle volume change. Units are
Pa for q, m3 for mantle volume, m otherwise. `face_centre_response` separately
stores point w,w',w'',w''' at alternating faces and centres. The descriptor binds
source state, reference, operator, frame/datum/epoch and explicit error bounds.

The new `ContinuousCellMeanFlexure` complements, rather than replaces, W04's
point solver. It double-integrates the Green function over source and target
cells, factors primitive differences using expm1 and uses a small-cell series at
zero separation. Fixed weights are reused via linear zero-padded FFT, with no
cyclic load wrap. The current adapter requires a shared uniform load/motion grid
within 1e-12 spacing-relative arithmetic resolution; it never remaps implicitly.

Load tails use the declared exponential exterior, not an invented zero geology.
Zero far-field changes are approximate with nonzero whole-domain bounds on w,
slope and curvature. Face/centre maxima are supplemented by continuous derivative
norm bounds between samples before admitting the displacement/slope/strain
envelope. Source/load approximation errors remain separately compared against
independent smooth continuum quadrature. Fixed kernels are reused; the step-4
workflow supplies durable result reuse and restoration without changing this model.

### Step 4 recoverable workflow — 22 September 2026

`PreparedExtensionWorkflow(motion, policy, output_times_s, store=store)` binds the
exact preparation, initial reference, source/runtime and whole requested schedule.
It owns one prepared support operator, borrows the motion/store, and retains only
the current output in RAM. Output times are strictly increasing, may include the
initial time, and are capped at 256. Motion remains characteristic-only; support
is evaluated once per newly requested output. No finer hidden time loop is added.

`run()` completes the schedule; `run(through=i)` stops at an inclusive zero-based
output index. It returns an immutable checkpoint containing `state`, `support`,
`output_index` and deterministic `checkpoint_id`. `load(i)` restores an individual
completed output. Supply the same explicitly prepared motion, policy and schedule
to resume after closing/reopening the existing `ArrayStore`. Changed definitions
or source/runtime produce new identities, not migration or repinning.

Each output is one atomic ArrayStore publication: material, cumulative exchanges,
mean displacement, point diagnostics and bounded provenance. The existing Zstd,
chunk deduplication, checksums, SQLite FULL durability, budgets and cancellation
remain active. Shared fixed edges and nine cheap derived mean columns are not
stored again. Restore reconstructs those columns during its necessary reference/
geometry/load checks and verifies the original full result hash, bit for bit.
No flexure convolution or characteristic evolution is repeated on a warm hit.

Restart scans at most 256 manifests for a contiguous completed prefix, decoding
only the last required payload. Earlier payloads are verified when individually
loaded; this is not an archive-wide corruption scan. Missing intermediate outputs,
invalid fields/accounts and corrupt data fail visibly. Publication failure leaves
the prior completed state intact. A checkpoint contains enough state to resume
with its explicitly matching preparation; it is not a standalone configuration
file or a backup of the database. Preserve the store using existing backup tools.

The motion, workflow and store must use one compatible ancestor budget. Returned
outputs retained by callers need their own allowance. Without a store, the same
API performs a cheap one-off calculation but only the current output is retained;
it does not promise recovery of earlier outputs or process-restart durability.

On the frozen 3200-cell, three-output Windows case, setup-inclusive verified warm
reopening takes 0.365163 s versus 0.767235 s recalculation: 0.402072 s / 52.41% saved.
Cold durable execution costs 0.857438 s, 11.76% more than no-store calculation.
Recovery after just the first output is essentially break-even at this small
scale (0.757400 s, 1.28% lower; seed cost excluded). These are three-repeat local
medians, not world-scale forecasts. The compact layout reduces encoded payload
from 1,032,553 to 619,839 bytes (39.97%) without changing output bytes.

Implementation references checked: existing Atlas W02/W03 snapshot reconstruction,
W05 support and ArrayStore source; official [SQLite atomic commit and recovery
documentation](https://sqlite.org/atomiccommit.html), including sections 3.11 and 4.
This engineering increment changes no physical equations; no new geology paper,
external simulator execution or empirical realism claim is attached to it.

### Step 5 combined acceptance — 22 September 2026

The explicit `verify.py --w05` selection passes 37 checks in 31.807493 s, with
source identity unchanged and no skipped tests. Full crop centres/faces at every
output/grid, independently averaged basin/footwall extrema, inventories, physical
envelopes, partition/domain sensitivity and exact recovery are covered. Maximum
fine-grid support error including quadrature uncertainty is 1.0164 mm against the
smooth reference. Production equations and frozen thresholds were unchanged.
The final [JSON](../evidence/w05-acceptance.json) records every case and source hash.
Existing matched timing was reused after source checks, not measured again.
The [combined acceptance design](W05_COMBINED_ACCEPTANCE.md) records the exact
claim, analogue challenge plan and papers/software actually checked this step.
