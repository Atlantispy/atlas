# New-world Step 4: initial plate motion

Status: backend implementation, WORKING NON-CANON, 24 September 2026.
This extends the actual Step 2 atlas and Step 3 lithosphere; it is not the fixed
W12 demonstration. UI rendering belongs to the separate Generator UI owner.

## How this is made, and how we check it

1. **Choose reproducible rotations.** Each plate receives a seeded Euler vector:
   an axis and angular speed. A point moves as `velocity = omega cross position`.
   This keeps each plate rigid and motion tangent to the sphere. The fit eliminates
   a shared reference rotation before fixing the largest plate for display. Both
   re-solving with a different anchor and subsequently changing display frame
   preserve relative motion. This is a plate-fixed frame, not a physical
   no-net-rotation frame. Fixed seed and inputs reproduce the result.

2. **Let the crust affect those choices.** Real continental polygon intersections
   along each boundary enter a small quadratic optimisation. It favours lower
   relative motion through a shared continental province, while remaining close
   to the proposed rotations. This is a declared dimensionless *affinity prior*,
   with coefficient 4, not a strength inferred from formation age or laboratory
   reference density. Continents are not asserted to be intact rigid bodies.
   A regression changes continental coverage and verifies changed directions,
   not merely a changed identifier or a uniform slowdown.

3. **Make junction velocities compatible.** The chosen initial boundary law moves
   a boundary normally at the average normal speed of its two plates. Where at
   least three plates meet, one tangent junction velocity must satisfy every
   incident boundary equation. A nullspace projection enforces those equations
   jointly, instead of assigning independent edge labels. Ambiguous constraint
   rank, exhausted motion freedom or excessive residual refuses the candidate.
   Tests independently recover the normal speeds from the rotations. This is
   instantaneous first-order compatibility, not proof of finite-time stability.

4. **Evaluate whole boundaries.** Exact great-circle intersections divide edges
   at geological features. Analytic normal-velocity zeros split any edge that
   changes between opening and shortening. Shear is retained continuously; no
   rule turns arbitrary convergence into a slab or assigns polarity. Touching
   or coincident crust boundaries retain ambiguity instead of choosing a side.
   Native geometric uncertainty refuses rather than snapping coordinates.

5. **Keep the chronology coherent.** This named scenario initiates the deformation
   at the saved initial epoch. Elapsed event time and newly formed crust volume
   are zero. Existing formation/cooling ages are retained exactly; extension is
   not called a mature ridge on previously old ocean crust. Unknown-strength
   inherited zones remain inactive. Later history/constitutive evolution needs
   its own admitted inputs; the native geological acceptance gate is unchanged.

6. **Store the actual outcome.** All rotations, boundary spans, contacts, junction
   velocities, original age references and assumptions are saved. Opening a
   project restores these records without drawing another seed or rerunning the
   optimiser. Source, configuration, atlas and precursor identities are checked;
   changed bindings are never silently replaced.

## Numerical method and efficiency

For a minor arc `r(s) = a cos(s) + u sin(s)`, with left normal `l = a cross u`,
the right-minus-left relative rotation `dw` gives:

```text
opening(s) = R [(dw dot u) cos(s) - (dw dot a) sin(s)]
shear(s)   = R (dw dot l)
```

The objective uses area-weighted squared departure from the proposed rotations
**modulo an arbitrary common rotation**, plus the length-normalised integral of
squared relative speed on unambiguous
continental spans. Junction equations eliminate their own two tangent unknowns;
the remaining plate system has at most three unknowns per configured plate.
The anchor is removed exactly. A single coordinated native-thread lease avoids
thread-start and oversubscription costs for this small dense solve.

For positive plate-area weights `w`, sum `W`, and Euler residuals `e`, minimising
`sum(w_i * |e_i - c|^2)` over the shared vector `c` gives
`c = sum(w_i * e_i)/W`. The resulting precision is
`K = (diag(w) - w w^T/W) tensor I3`. It annihilates common rotations, but is
positive definite once an anchor removes that three-dimensional freedom.
The same junction nullspace solve therefore stays small and deterministic.
An independent explicit augmented least-squares test checks this elimination;
native tests re-solve with every plate as anchor. Residual centring is a fitting
operation, not the surface integral needed to calculate physical net rotation.

This corrects the original anchored fitting objective, which inadvertently made
the reference choice affect relative motions. Diagnostics identify the successor
as `area-weighted-common-rotation-eliminated.v1`; `relative_prior_adjustment`
now uses the area-weighted centred Euler residual, with its metric explicitly
named. Historical records retain their old values and exact source bindings.

Boundary-length-weighted RMS relative speed is normalised to a seeded 1–8 cm/year
scenario target. This interval is an explicit uncalibrated prior, not a measured
distribution or a prediction for the planet. The achieved RMS is independently
recomputed and saved alongside the target and prior adjustment.

Speed integrals use a positive midpoint-basis decomposition. The tiny-interval
weight `(d - sin(d))/2` uses its small-angle series, so short crust intersections
do not lose their physical sign through subtraction. Scalar integrals sum
nonnegative squared projections. Round-off-sized normal components are labelled
`normal-motion-unresolved`, not classified by an arbitrary geological speed
threshold. Their actual components and numerical allowance remain visible.

No dense global field, time history, new cache daemon, worker pool or second
compression format is introduced. Native geometry and the existing Zstd-backed
ArrayStore are reused. Work reservations cover adapter matrices/records and
native temporary work; they are accounted workspace, not measured process RSS.
Saved records have an 8 MiB cap and the interactive response retains its 2 MiB
cap. One deadline covers structure, layout and motion; native cancellation maps
to the same safe timeout response without publishing a partial project.

## Backend and persistence contract

`tools/new_world_motion.py` provides:

```text
generate_motion(plan, candidate, structure, *, cancel=None) -> WorldMotion
check_motion(plan, atlas, structure, motion, *, current=False)
save_motion(motion, store) -> motion_id
load_motion(store, motion_id) -> WorldMotion
motion_view(motion) -> JSON object
```

`WorldMotion` owns immutable canonical bytes; `descriptor()` returns a detached
object. Full source hashes, native execution identity and every upstream ID are
part of its content identity. Saving checks current compatibility; historical
read-only restoration preserves recorded bindings and does not repin them.

Project v3 extends v2 with `motion_id` and requires its matching structure.
New v3 saves place the **complete** layout report in a content-addressed native
uint8 receipt (1 MiB limit); `manifest.report` is a small typed reference. This
fixes the 1024-patch report overflowing the unchanged 64 KiB manifest limit.
Existing v1/v2 and early v3 inline reports remain readable. The native store's
separate metadata cap is explicitly 2 MiB instead of its 1 MiB default, to admit
the 1024-patch atlas descriptor; this is not the project manifest cap. Its native
workspace allowance correspondingly grows by 4 MiB. Both archive members, the
64 MiB store envelope, no-overwrite policy and lossless native compression remain
unchanged. No JSON report information is dropped.

## UI contract: world-view v3

The response envelope stays `atlas.world-session-response.v1`. The view changes to
`atlas.world-view.v3` and adds `motion` (object or null) and
`capabilities.initial_motion`. Legacy worlds get null; no field is manufactured.
`evolve_world` and `native_restart` remain false for this initial-world route.

The geometry adds `boundary_edge_indices`, parallel to `boundary_edges`. These
are original **native** edge IDs, not offsets into the filtered boundary array.
Join each motion `edge_index` through this mapping. The vertex pair's order is
canonical; interpolate along its minor great-circle arc at `start_fraction` and
`end_fraction`. Never infer fractions from longitude or redraw continental data
using plate ownership. Contacts with zero length are separate point records.

`motion.schema` is `atlas.initial-motion-view.v1`. Its contents are:

- `angular_velocities_rad_s`: plate-ID to forward-time three-vector; frame anchor
  explicitly identified. For display arrows at a unit direction `r`, use
  `omega cross (radius_m * r)`, not the Euler vector itself as a surface arrow.
- `segments`: native edge ID and fractions, left/right plate IDs, possible column
  IDs/crust types, regime, signed midpoint opening, full-interval opening range,
  signed shear, numerical opening allowance, unit midpoint and actual relative
  velocity. Speeds are m/s. Positive opening separates right from left; shear
  follows the canonical edge tangent. All `polarity` fields are null.
- `crust_contacts`: zero-length contacts and all possible column IDs.
- `junctions`: native vertex indices/unit positions, Cartesian velocities in m/s,
  incident native edge IDs and residuals. Do not animate this as validated history.
- `event`, `inherited_zones`, `diagnostics`, `assumptions`, references and identities:
  expose these without inventing active faults, cooling ages or acceptance badges.

Regimes are `incipient-extension`, `incipient-shortening`, `stationary`, or
`normal-motion-unresolved`. Shear can coexist with opening/shortening. A finite
pure transform is not inferred from a small visual threshold. To display cm/year,
multiply m/s by `100 * 31557600`. Scientific detail remains progressively exposed.

UI scope: add actual-motion overlay/arrows and selection/legend details, strict
v3 admission, and preserve New/Save/Load, old-world recovery, source protection
and bounded public asset rules. Use the retained actual fixture supplied in the
handoff; no additional generation campaign or broader UI redesign is required.

## Sources checked

- [pyGPlates velocities](https://www.gplates.org/docs/pygplates/generated/pygplates.calculate_velocities)
  and [plate-ID example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_calculate_velocities_by_plate_id):
  Euler velocity and explicit anchor convention; no external software dependency.
- [pyGPlates NetRotationModel](https://www.gplates.org/docs/pygplates/generated/pygplates.NetRotationModel):
  why subtracting an area-weighted Euler average would not be a true NNR frame.
- [McKenzie & Morgan (1969), Evolution of Triple Junctions](https://www.nature.com/articles/224125a0):
  abstract checked for the distinction between instantaneous geometry and
  finite-time stability; this is not claimed as a reproduction of its full model.
- [Bird (2003), An updated digital model of plate boundaries](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2001gc000252):
  geological boundary interpretation requires observations beyond a velocity sign.

The particular continental-affinity recipe is an Atlas scenario prior, not a
published Earth calibration.

For the frame-neutral correction, also checked
[Boyd and Vandenberghe, Convex Optimization, sections 10.1.1–10.1.2](https://web.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf):
equality-constrained quadratic minimisation and nullspace elimination. These
support the numerical method, not empirical calibration of the motion prior.

## Frame-neutral correction and diagnostic scope

The correction changes new generated motions; it never rewrites an existing
world or job. Historical initial worlds remain readable. Running or transferring
source-incompatible regional results continues to refuse under the existing
source guards; it requires its original compatible implementation, not a silent
rebind. The initial-motion record/view shapes remain compatible.

Assessment uses actual boundary arc lengths, not the number of subdivisions.
Normal and sideways relative velocities are evaluated at the same boundary
location; two distant plate arrows are not a local collision measurement.
Convergence can be oblique, and a pair-mean display frame makes two local arrows
opposite by construction, including pure sliding. Neither arrow opposition nor
roughly equal counts of opening/shortening establish geological realism.

Continental affinity and the symmetric initial junction law remain declared
scenario assumptions, unchanged by this correction. Their directional/obliquity
distributions still need reference-data calibration; no appearance-based seed
selection, forced head-on motion or geological acceptance badge is introduced.

### Correction evidence, 24 September 2026

[Bounded correction evidence](../evidence/new-world-motion-frame-r2.json) compares
three retained geometry/geology inputs without evolving a world. The old fit's
reference sensitivity was 72.2718%, 104.6057% and 42.6831% boundary-weighted RMS
relative-field difference when changing from largest to smallest anchor. These
are **reference sensitivity**, not errors against physical ground truth. The
corrected fit's largest relative difference over every anchor in all three
cases is `2.86e-15`, i.e. floating-point round-off.

| Retained case | Old fit mean | Corrected fit mean | Observed time change |
|---|---:|---:|---:|
| Seed 42, 6 plates / 192 patches | 12.0568 ms | 11.9166 ms | -0.1401 ms / -1.1623% |
| Seed 43, 6 plates / 192 patches | 10.9552 ms | 11.2524 ms | +0.2972 ms / +2.7126% |
| Seed 42, 12 plates / 512 patches | 26.4144 ms | 26.5830 ms | +0.1686 ms / +0.6382% |

Three alternating warm pairs per case measure `_reconcile` only, not whole-world
generation. These small differences show no material timing change or established
speedup. No extra solver, worker, cache or physics step is introduced.

`tools/assess_new_world_motion.py PROJECT.atlas` reopens one existing initial world
read-only. `assess_motion(atlas, motion, plan=original_plan, structure=original_state)`
also supports a separately calculated candidate. The helper derives fractions
from Euler zero crossings rather than trusting saved regime labels. Full, normal
and shear RMS use analytic arc integrals. Mean obliquity is explicitly a
length-weighted **midpoint approximation**; stationary and zero-speed exclusions
are reported, and that mean is not claimed subdivision-invariant.

The corrected cases contain 50.25–53.92% shortening by actual boundary length,
with the remainder extending. Normal RMS is 2.21–3.80 cm/year and shear RMS is
2.03–3.48 cm/year; approximate mean obliquity is 41.42–45.61 degrees. These
describe genuine oblique relative motion, not a calibrated realism threshold.
All retained original files remain byte-identical.

Verification: 11 existing motion methods plus 5 new fit/frame methods pass in
4.918 s; 9 analytical assessment methods pass in 0.067 s; 4 affected regional-input,
source/cancellation and project/session restoration methods pass in 8.216 s.
The same tested source bytes were integrated. A separate corrected fixture saves
and reopens with exactly preserved motion; historical inputs are not overwritten.
Static route checks pass; 30 safety methods pass with the existing explicit
Windows symlink-privilege skip. No long simulation or Linux coverage is claimed.

## Historical measured checkpoint

[Full bounded evidence](../evidence/new-world-s4-r1.json): Windows/Python 3.12.14,
seed41, 6,371 km radius, 0.3 continental fraction, unchanged saved outputs.

| Case | Create, save and view | Restore and view | Saved |
|---|---:|---:|---:|
| 192 patches / 6 plates, three-pair mean | 2.051165 s | 0.347091 s | 1.704074 s / 83.0784% |
| 1024 patches / 12 plates, one sample | 4.690197 s | 1.716475 s | 2.973722 s / 63.4029% |

First small sample includes lazy initialisation. Loaded small-case motion alone
took 0.487121 and 0.471030 s; larger-case motion took 0.729691 s. These percentages
measure reuse of identical output, not a faster evolution solver. Native .atlas
sizes were 327,172 and 1,359,367 bytes. Motion workspace allowances peaked at
13,227,264 and 30,122,496 bytes respectively; these are not process RSS figures.

Eleven motion and six exact-arc checks pass. The initial 15 project / 14 session
checks passed; eight changed-boundary checks subsequently covered report receipts,
1024-patch persistence, native deadline cancellation, legacy reads and edge-index
joins. These groups overlap and are not summed as unique tests. The source-only
check passes; unchanged static-suite evidence is reused, including its explicit
Windows symlink-privilege skip. No full physical evolution campaign was required.
