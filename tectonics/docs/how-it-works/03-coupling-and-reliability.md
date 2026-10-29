# Surface processes, validation and reliable execution

This chapter covers W09–W12 and the shared services that let supported tectonic
calculations exchange, retain and inspect results. It belongs to
[How tectonics is made](../HOW_TECTONICS_IS_MADE.md). Atlas remains **WORKING
NON-CANON**: implemented equations, numerical verification, geological credibility
and practical integration are different achievements.

All numerical measurements below describe their recorded source/runtime snapshots.
The W01–W12 numerical receipts are outside the initial
[current-evidence register](../../../docs/CURRENT_EVIDENCE.md); their existence or
recorded pass does not establish current-checkout acceptance. The
[current state](../../../docs/CURRENT_STATE.md) takes precedence over older
implementation documents' “next step” or “current” labels.

## W09: water and finite surface material

### Find drainage without filling the real landscape

Water needs connected routes, physical storage and explicit supply. Given bed
heights, cell areas, connections, distances and outlets,
[drainage preparation](../../src/atlas_tectonics/w09_drainage.py) selects each
cell's steepest downhill receiver. Flat ground receives a deterministic, acyclic
route. Depressions retain their pits, connecting saddles and possible escape
levels. A routing calculation must not turn a real basin into solid ground or
create the water needed to fill it.

[Priority-Flood](https://richard.science/sci/2014_depressions.pdf) supplies the
depression-preparation approach; the
[Fill–Spill–Merge paper](https://esurf.copernicus.org/articles/9/105/2021/)
explains the useful hierarchy of nested basins. Atlas implements its own bounded
graph and event balance. These references are methodological support, not
third-party simulators executed underneath Atlas.

Outputs include receivers and basin/saddle geometry. Supplied effective runoff
then accumulates downstream as discharge, stopping at pits and declared outlets.
This instantaneous network calculation does not model channel storage or a flood
wave. [Drainage tests](../../tests/test_w09_drainage.py) check flats, closed pits,
alternative saddles, invalid geometry and changed beds; the
[water receipt](../../evidence/w09-water.json) records the frozen water controls.
Those establish routing and accounting on the selected supports, not a calibrated
catchment or a rainfall model.

### Fill, spill, merge and drain real lakes

[PreparedWater](../../src/atlas_tectonics/w09_water.py) takes that geometry,
initial water, duration and supplied runoff, precipitation, evaporation and
infiltration. A lake stores cubic metres. Its level is the height at which the
sum of each submerged cell's area times water depth equals that volume. More
water raises the level until a sill permits overflow; neighbouring full basins
can merge, then split again when drawdown exposes their saddle.

The calculation stops at shoreline, spill and dry-out events before continuing
the requested interval. Rain on wet ground and runoff from dry ground use
separate footprints. Evaporation goes to an atmospheric account; infiltration
goes to a named subsurface account. A dry lake can lose only water actually
available, shared between simultaneous demands. The ideal sill releases excess
water immediately: it is a reduced outlet law, not calibrated weir hydraulics.

Outputs retain surface and subsurface water, supplied volume and atmospheric and
boundary exports. Bed changes can relocate water conservatively on unchanged
indexed cells and areas; arbitrary moving-grid overlap is still unsupported.
[Water tests](../../tests/test_w09_water.py) include two simultaneous shoreline
contacts, nested splitting, finite losses and exact checkpoint continuation.
The recorded four controls contain 41 numerical/account observations. Matching
totals alone was insufficient: the simultaneous-contact regression also checks
where the remaining water sits. The [implementation record](../W09_WATER.md)
states the 256-node, 2,048-connector and 256-cumulative-subinterval limits.

### Incise finite rock beneath protective sediment

[PreparedErosion](../../src/atlas_tectonics/w09_erosion.py) consumes a fixed
single-receiver network, physical slopes, supplied discharge, an inundation mask,
finite rock layers and mobile alluvium. Its
[SPACE-family basis](https://gmd.copernicus.org/articles/10/4577/2017/) separates
bedrock erosion from sediment entrainment: thick cover shields rock, while
erodible sediment becomes more available as cover increases. Atlas selects
explicit thresholds and discharge/slope exponents, rather than importing
another program's defaults.

Cells are solved downstream first so an upstream cell uses its receiver's new
height. A bounded implicit solve finds rock lowering and cover removal together;
it therefore accounts for their effect on slope during the interval. The bare-rock
case has a direct solution, related to the ordered implicit approach documented
by [FastScape](https://fastscape.org/fastscapelib-fortran/). Rock interfaces trigger
an event search, after which the next layer supplies its own properties. Exhausting
the last supplied layer returns the valid endpoint and refuses further removal.
Dry or inundated cells do not incise through this operator.

The outputs are changed finite stocks and tagged releases carrying density,
origin, formation time and signed enthalpy relative to its declared reference.
A release has not yet travelled to the sea. The
[river tests](../../tests/test_w09_erosion.py) check changing cover, updated
receiver heights, material interfaces, tiny releases and restart without paying
the same transfer twice. [Recorded controls](../../evidence/w09-erosion.json)
compare the discrete implicit answer and temporal refinement against independent
formulae. [Landlab's SPACE component](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.space.space_large_scale_eroder.html)
is a method/interface reference, not an Atlas dependency or executed comparator.

### Move available soil down a hillslope

[PreparedHillslope](../../src/atlas_tectonics/w09_hillslope.py) takes explicit
cell areas, distances, widths, mobile soil stocks, porosity, density and transport
parameters. It uses the
[Roering–Kirchner–Dietrich nonlinear law](https://seismo.berkeley.edu/~kirchner/reprints/1999_29_Roering_nonlinear.pdf):
transport rises rapidly as a soil-covered slope approaches its supplied critical
gradient. Sparse implicit iteration evolves the slopes; the same shared-face
transfers move tagged grains and enthalpy between cells.

This implementation supports a one-dimensional strip or periodic chain. Bare
rock remains immobile, including cliffs. Soil slopes at or beyond the critical
gradient refuse because their failure mechanism is missing. Donor exhaustion
returns a depletion time and valid state; the remaining duration is unadvanced.
No soil is created to keep the equation running. A completed advance, and a
prescribed river release that crosses layers, ends exactly at its requested time
under the shared interval rule.

[Hillslope tests](../../tests/test_w09_hillslope.py) compare exact face flux,
finite depletion and a low-slope sinusoidal profile. The recorded spatial errors
fall from 0.0012812 to 0.00009824 over 8/16/32 cells; separate time refinement avoids
confusing the two errors. These support the discretisation, not landslide prediction
or general two-dimensional terrain smoothing. Persistent hillslope recovery and
full planar gradients remain outside this route.

### The unfinished source-to-sink connection

The [W09 design](../W09_SURFACE_PROCESSES.md) specifies subsequent sediment routing,
settling, deposition, stratigraphic insertion, drained compaction and shared
water/heat/load accounts. Those joined Steps 4–5 remain unfinished. Existing
erosion releases and mobile-soil transfers do not close a coupled river-to-basin
sediment budget.

A future compatible bridge must conserve grains and water as deposition changes
bed geometry, draw pore water from finite supply, preserve formation history and
apply each support effect once. W04 returns total displacement from a fixed
reference; repeated feedback must apply its change, not repeatedly add the total.
The [ownership decision](../TECTONICS_PLAN.md#current-module-boundaries-and-continuation-23-september-2026)
assigns hydrological expansion to hydrology, sediment processes to erosion and
sediment transport, stratigraphic/material development to geology, and terrain
representation to topography/topology. Tectonics owns its response to supplied
loads and forcing. This dependency boundary prevents an implementation location
from implying a finished coupled landscape model.

## W10: what the evidence establishes

### Mathematical correctness and numerical resolution

Mathematical tests ask whether implementation matches its equations: rotations
preserve lengths, material transfers conserve stock, and manufactured solutions
recover known velocity, temperature or displacement fields. Numerical tests ask
whether grid and timestep approximations are sufficiently resolved. Refining
space, time and coupled update intervals answers different questions; a small
linear-solver residual alone answers none of them completely. This follows
[NASA's code/calculation verification distinction](https://www.grc.nasa.gov/WWW/wind/valid/tutorial/verassess.html).

The [W10 coverage record](../W10_VALIDATION.md) maps those checks across W01–W09.
Its [free-surface receipt](../../evidence/w10-free-surface-r1.json) records 12
checks over ten small-amplitude trajectories and independent spatial/time
refinement. The [active-coupling receipt](../../evidence/w07-active-coupling-r3.json)
instead uses a 16×16 grid with 8/16/32 mechanical intervals and a separately
resolved heat step. Decreasing temperature, velocity and viscosity differences
support that time-splitting calculation; they do not establish a continuum or
field solution.

The retained comprehensive baseline ran 3,565 tests and recorded failures, errors
and skips. It is not a passing full-suite result. A
[137-check targeted successor](../../evidence/remap-v2-integration-r1.json)
addresses joint-material remapping and missing integration controls.
[Validation-gap tests](../../tests/test_validation_gaps.py) include independent
changed-rigidity flexure and interruption after a committed snapshot but before
its adoption. Focused successors resolve their named failures, not every possible
claim attached to the baseline.

### Challenge a physical model with independent observations

The mature-ocean screen holds Atlas's cooling parameters fixed and compares
predicted surface heat flow with 50 published age bins between 40 and 165 Ma.
The observations come from the
[Richards et al. study and deposited dataset](https://www.repository.cam.ac.uk/items/76c2dd6c-0ea4-4886-9c48-f52f81561fa9).
They were not used to fit this synthetic case, although its methods paper had
already informed development: this was not a blind external assessment.

The recorded scaled RMS is 0.714587 against Atlas's declared threshold of 1;
the mean discrepancy is −8.782888 mW/m² and only 24/50 predictions lie inside
the observed interquartile ranges. Every prediction falls below its bin median.
The result supports limited consistency with observed dispersion while retaining
systematic underprediction. The threshold is a screening choice, not statistical
significance, and dispersion is not a confidence interval.

[Ocean-screen tests](../../tests/test_w10_ocean.py) independently check the
surface derivative and statistic. Fixed parameter variations are sensitivity
cases, not calibrated uncertainty. Natural deformation, forcing, rheology,
effective rigidity, newborn-ocean cooling and independent age–depth behaviour
still lack the required field evidence. Published subduction comparisons provide
numerical corroboration of supplied cases, not validation of a natural subduction
zone. R4.4 remains held and incomplete.

### Integration and scale are further questions

Integration evidence asks whether compatible components exchange real fields,
retain units and recover consistently. W12 supplies bounded examples below.
Scale evidence asks whether changing resolution or workload preserves the
quantities of interest within resources. The
[W11 scale receipt](../../evidence/w11-scale-r2.json) compares 8×8, 16×16 and
24×24 steady affine-shear cases against an independent solution, with all 90
computed outputs checked. That supports this synthetic problem's transfer across
three grids; it cannot establish heterogeneous geological histories, adaptive
mesh exchange or planet-scale feasibility. Visual review helps expose missing
regions and misleading axes, but supplies neither numerical error estimates nor
geological acceptance.

### Compare optimised outputs under their actual source contracts

An optimisation comparison needs independently corresponding physical records
and the sources that produced and read them. Equal-looking numbers alone cannot
establish that the two records describe the same quantity, units, norm, time or
mesh. The N9 tools accept authenticated source inventories and reader-bound
records, catalogue wall-measure and exterior-mesh producer calls, and return
source-binding receipts plus field verdicts. A source slot marked BOUND supplies
one part of the proof; it is not numerical or scientific acceptance.

The catalogue follows the reviewed direct calls, module relays and consequence
routes through the package. A reviewed caller must exist in both arms. Missing
or unresolved context gives REVIEW; malformed inventories fail integrity. The
scan has explicit limits for computed names, container or argument relays and
dynamic mutation. Helpers outside the package must therefore remain identical.

Field comparison is exact unless a source-specific proof applies. For the
reviewed exterior-mesh pose transform, exact rational checks establish an
outward operator-error radius, growth strictly below 2^-11 of the original
radius, and a quaternion L2 displacement bounded by that growth. The internal
quaternion error and the stored four-times operator error remain distinct.
Changing the supporting dependencies withdraws this proof even when the
producer itself is unchanged. It does not provide an error allowance for
downstream geometry, current forces or Heat; those quantities need their own
propagated-bound designs. Diagnostic ULP or relative differences are not
automatic acceptance tolerances.

Compact saved roots are read through the producer's own segment decoders.

- Each decoder module is pinned by SHA-256 to the arm's source manifest and also
  checked on disk, so a changed decoder refuses.
- A helper decoder that differs between the arms gives REVIEW. A differing
  `atlas_tectonics` decoder is only recorded, because the width arm transforms
  those modules.
- Synthetic controls, written by the selected producers, corrupt a chunk, drop
  or substitute a joined record, or change one logical field. Each fault is
  refused by its own guard.
- A fault shared by a segment writer and its reader is invisible to this byte
  check.

A few downstream records also have source-specific design rules. A rule decides
only where its record is dumped and only when it can check every precondition it
states. Its equality checks are type-strict: 5 and 5.0, or 0.0 and -0.0, are not
the same. The current rules cover:
- a band or exact identity on the differential interval;
- contradiction checks on the dual-closure graph and on the certification
  force, which can only fail;
- a zero-source heat audit;
- the consistency of the joined heat plan's targets;
- an exact differential-mesh header formula;
- each stored heat value, which must equal its retained part plus the exact
  rounding of the new value to the stored float.

The heat rows compare arms only on the selected heat route, with the same method
and identical consumer sources. Every cross-arm rule also needs the reviewed
differential-geometry source in both arms; without it the rule is REVIEW, while
each arm's own consistency checks still apply.

An exterior-mesh volume bound passes only when its computed enclosure radius is
strictly smaller than the smallest cell volume. At production pose errors that
bound can be vacuous. Because the mesh header stores no rotation, the radius also
needs each arm's quaternion to lie in the norm band its pose routine guarantees.

Rows whose records the replay route never writes are dropped, but not silently:
such a record, if present, makes the comparison REVIEW. Adaptive enclosure
magnitudes, multi-step pose routes, most Heat quantities, ledger-only rows,
module-level identities and per-site outcomes stay REVIEW.

Refusals are judged at two levels. A field-level refusal flip is REVIEW, as the
design asks. The stage rule is stricter, by a recorded departure from the design:
an attributed resource stop of the unchanged workload in the width arm, after an
adopted reference, still FAILs, and so does any width-gate flip.

For each physical field the comparator also reports the largest change between
the arms, the certified radius it is judged against and that radius's source,
their ratio, and the change in units in the last place. A field without a
certified radius is reported as having none; no substitute tolerance is used.
These tables are diagnostics and change no verdict.

The rules come from a retained design review. Static and synthetic qualification
evidence is recorded with the source successor. No external method or benchmark
is claimed.

Diagnostic per-arm scales include all finite compared numeric values, including unchanged ones.
An array absolute change beyond binary64 range is labelled `overflow`, with its exact rational
maximum and worst location retained; the report never substitutes a finite display cap for that
measured change. Relative changes are normalised without the overflowing subtraction.
Common-cell float64 ULPs remain available in a birth/death comparison, but its cell-ID join is
diagnostic and supplies no correspondence proof or numerical allowance. Missing radius remains
explicit.

The observer verifies its pinned inputs before discarding the standard
multiprocessing alias of the exact main object. A separate object at the same
path, a wrong pin or another entry-object alias still refuses; the main-file
exemption remains singular.

The arithmetic checker reports evaluated and refused cases and fails if any
required case is refused. Synthetic controls exercise missing callers, changed
dependencies and refusal reporting; they do not qualify a replay generation.
Each complete successor lives beside its predecessor, so existing compositions
keep their byte-bound tools. No scientific replay is implied by source
publication. The [specialist method and limits](../../optimisation/workbench/plan04/README.md)
identify the consulted implementation, pinned producer bodies, exact claims and
remaining root-route and field-proof requirements; no external method or
benchmark is newly claimed here.

The width implementation can be integrated as a guarded source successor using
its bounded actual-native test and retained component evidence. Wall rays keep
outward radii; coaxial quaternion rounding preserves the exact axis certificate;
mesh header rounding follows the exact budget decision. Existing authenticated
reader tables and the unchanged continuation gate remain required at runtime.
The [bounded result and limits](../../optimisation/workbench/plan04/BOUNDED-WIDTH.md)
show local integer-width reductions, increased sampled RSS and unchanged fixed
heat inputs. They do not establish a heat solution, full coupled C4 or a whole-run
speedup. No new IV is part of this guarded integration route.

## W11: spend work on changed science

### Prepare geometry, evaluate lazily and use suitable kernels

Preparation retains immutable geometry, spatial indices, drainage order,
thermal structures and mechanical setup across compatible requests. Compact
geological descriptions are sampled where requested, rather than expanded into
a universal object per voxel. Conservative spatial indices remove impossible
candidates before exact intersections; dense overlaps can still be expensive.
Pools and applicable backend setup are created when needed. These mechanisms
reduce repeated preparation, not the requested physical calculation.

Contiguous arrays support bulk operations and bounded batches. Safe immutable
buffers may be borrowed; mutable inputs are detached, and published slices are
compacted so a small result does not retain a large parent. SciPy supplies bulk
special functions and sparse solves; Numba compiles selected transport and
mechanical kernels. [Numba's arithmetic guidance](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
explains why fast-math can change numerical behaviour: Atlas's exact transport
path disables reassociation and uses an independently tested accurate accumulator.
Missing required backends refuse rather than silently change the method.

See [precursor execution](../../src/atlas_tectonics/precursor_execution.py),
[copy/ownership tests](../../tests/test_copy_reuse.py) and
[kernel tests](../../tests/test_kernel_batches.py). Their parity and mutation
guards check implementation equivalence, not geological quality.

### Reuse matrix work without solving stale equations

Prepared solvers retain FFT coefficients, banded or sparse factors and fixed
matrix structure where their defining geometry and coefficients permit it.
Changing a load can reuse an unchanged operator; changing stiffness or viscosity
requires the appropriate current operator. SciPy's
[SuperLU interface](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.splu.html)
provides factor-and-solve machinery; Atlas owns its invalidation rules.

The experimental mechanics route additionally contains compiled matrix-free
actions, sparse velocity templates, geometric multigrid, guarded preconditioner
reuse, warm starting guesses and Anderson acceleration. These are implemented
execution options within the held R4.4 route. A lagged approximate preconditioner
is distinguished from the current physical equations; final residuals and
constitutive checks still use the current state. Optional adaptive intermediate
accuracy ends with strict final certification. Seeds and policies are identified
in continuation records.

[Regional execution](../../src/atlas_tectonics/regional_execution.py),
[preconditioner tests](../../tests/test_preconditioner_reuse_r4_4.py),
[multigrid tests](../../tests/test_velocity_multigrid_r4_4.py) and
[adaptive-inner tests](../../tests/test_adaptive_inner_r4_4.py) define these
different boundaries. Fewer iterations or factor builds are not themselves a
measured end-to-end improvement.

### Cache an identified request, not a plausible-looking file

[Reuse services](../../src/atlas_tectonics/reuse.py) bind inputs, parameters,
backend, source membership/bytes, loaded instructions and selected runtime
identities. The loaded instructions cover every module in the package's source
membership, including the numba kernels whenever they import, together with each
module's upper-case data tables and numerical constants. Until 30 September
2026 a fixed list omitted 25 modules (3D, integration, assembly, workflow ports,
plate reference and, outside numba, the kernels), so a long-lived process running
stale code of those modules received the identity of the fresh source. The set
is derived from file membership, not from whatever happens to be imported, so the
identity does not depend on import history. Prepared immutable inputs can retain their data digest. Source
verification still streams every current source file; cheaper file-status work
does not replace those reads with timestamps. The current inventory admits
512 files while retaining a 2 MiB digest-record bound.

The source checkout keeps these strict checks on each operation. A packaged
desktop payload can use a separate release policy: capture each backend once,
then check fully again before saves, on reopen and on cache reads. The calculation
is identical; only the frequency of checking whether code changed is different.
A packaging marker and matching interpreter/command paths select this policy,
not a user environment setting. The scientific identity stays the same between
modes; saves record the producer mode separately. Source changes still invalidate
reuse, and evidence tools cannot turn a release run into a strict pass.

Within strict checks, deeply immutable constants can reuse their normalised
representation while mutable constants, defaults and function bindings are
re-examined. This avoids repeated formatting, not source verification. Focused
controls deliberately mutate sources and functions and require refusal.

The [explicit final source constructor](../../optimisation/workbench/plan31/final/r3/README.md)
can select a manifest-bound fixture route. It authenticates the selected manifest
with its SHA-256 at context entry, then retains those exact immutable bytes. Each
subsequent fixture-identity lookup opens the manifest afresh and compares all its
bytes against that authenticated reference. Changed, truncated or appended data
refuses, even when the file size or modification time has been restored. Declared
fixture bindings, source checks and finder/root ownership keep their existing
checks, including verification when the context closes.

The retained reference is limited to 8 MiB per active fixture context. A lookup
reads at most the retained length plus one byte, in blocks of at most 1 MiB, so
late file growth cannot make that comparison unbounded. Focused disposable
controls exercise mutation, growth, binding changes and cleanup; an unavailable
OS symlink-creation control is recorded as skipped. These checks establish the
method's refusal and lifecycle behaviour. A changed implementation still needs
new source/profile identities and actual receiving and folded qualification;
earlier recordings do not prove the changed source. No speed gain is established.

Data-format constants are part of that check too. Changing a NumPy data type can
change how saved bytes are interpreted without changing a function: the same
bytes could become different numbers. The identity records byte order, field
names/order/offsets, alignment, subarray shape and inspectable metadata, rather
than relying on NumPy type equality. Focused tests change the actual checkpoint
type and require both rejection by an existing context and a different fresh
identity. They also cover metadata changes inside mutable containers. Cyclic or
unsupported opaque metadata is refused rather than identified only by its class.
The implementation follows NumPy's [dtype reference](https://numpy.org/doc/stable/reference/generated/numpy.dtype.html)
and [structured-array layout documentation](https://numpy.org/doc/stable/user/basics.rec.html);
this is an integrity repair, not a change to the physical equations.

Result caching is distinct from prepared setup. Automatic cache admission weighs
result size and observed calculation/write/restore cost; explicit always/off
policies remain available. Bounded same-request coordination lets concurrent
callers share one computation. Cancellation, corruption and a failed creator
remain visible, and a cancellation stays with the caller who asked for it: a
caller still waiting takes the computation over instead of inheriting someone
else's cancellation. Separate processes coordinate through 16 lock stripes per
store; the holder records which request it is computing, so an unrelated request
that happens to share its stripe proceeds instead of waiting behind it or timing
out (before the R4 repair it could fail after 30 s). The trade-off is a possible
duplicate: while an unrelated request holds the stripe, identical requests in
several processes each compute, and publication stays idempotent. Several prepared workflows
retain only their latest complete result, limiting growth. Changed physics
computes a new answer even when unchanged geometry remains reusable.

[Execution-reuse tests](../../tests/test_execution_reuse.py) cover invalidation,
same-request coordination and failure paths. Hashes support identity and
corruption detection; they are not signatures against an attacker who controls
both code and stored records. Loaded binary identity also assumes those binaries
remain unchanged during the process.
Each one is therefore hashed once per process and its digest is reused. Until the
R7 repair of 1 October 2026 the digests were kept in a 16-entry cache, smaller
than the SciPy and Numba binary sets, so every new context of those backends read
its files from disk again (about 126 MB for Numba on the pinned Windows
environment).
The interpreter is a weaker entry than the extension modules. On Windows the
hashed file is only the small `python.exe` launcher; the interpreter itself lives
in `python312.dll`, which is not hashed, so there the interpreter is identified by
its recorded version and build string and not by its bytes.

### Check retained state before reopening

The [release-accounting source component](../../optimisation/workbench/plan26/README.md)
connects one retained-state validator to both prepared and fresh producer/reader
paths. Each snapshot must declare a retained limit equal to the fixed 256 MiB
pool plus its own carrier allowance. Capacity and index peaks follow exact integer
grids and lease bounds; an active compact scope also funds its 5,120-byte control
charge. Both snapshots are checked independently. Their scope, shape and lifetime
peaks must agree, peaks cannot fall, and the after-close snapshot retains no bytes
or pools. A record that balances only in aggregate is insufficient.

These constraints retain a conservative 50,688-byte slack per extra simultaneously
funded pool. The one-pool capacity ceiling and total retained limit are different
quantities; the checks do not establish exact multi-pool accounting or increase
the allowed resource budget.

The restart source port also preserves a narrow exception for the registered
compiled heat helper. Its exact helper and kernel source pins and loaded-source
bindings must agree. This remains a cooperative check of participating modules;
it does not authenticate every preplanted self-declared module or arbitrary
runtime rewriting. The public port preserves the existing query-stage behaviour
and all unrelated source members.

The [source constructor](../../optimisation/workbench/plan26/build_candidate.py)
authenticates its complete parent, applies exact declared diffs and creates a new
source tree. It refuses output overlap with its inputs before writing, linked
members and undeclared files, including nested manifests. Focused controls cover
these boundaries and the four validator callers. The
[fold and parity source](../../optimisation/docs/release/fold/r6/README.md)
separately retains native, source and AST guards with explicit publication hashes.
The [pre-fold receiving guards](../../optimisation/workbench/plan26/receiving/README.md)
also distinguish the fresh profile from its prepared companion and bind both to
the selected source manifest. Selected-generation checks bind the independently
reviewed constructor, its complete construction plan and the delivered files.
They account for every changed, added and omitted member while preserving the
full parent history. An isolated runtime facade remains in the complete file
inventory; the native-package source digest covers the package itself.
Their authentic producer contract and runtime bindings are supplied separately;
the exported code does not qualify existing private packets or a public runtime.
A source manifest from either component is not a prepared runtime receipt.
Actual selected profiles, loaded bytes, compiled execution, folded/unfolded
parity and interval admission require their own source-bound qualification.

The [closed-payload receiver](../../optimisation/workbench/plan39/README.md#canonical-closure-and-payload-receiver)
uses the canonical source-bound closure checker, its authenticated base and fixed
policy. It checks complete delivered code coverage, finite native/helper import
domains, explicit fixture aliases and pinned Python-environment proofs before a
package can pass. The desktop builder connects this receiver for explicit release
builds; ordinary builds remain strict. It authenticates the complete source and
Python inventories before output creation, then verifies delivered bytes before
writing the release marker and build seal. Its qualified source-frame set remains
empty until authentic folded records are supplied, so packaged qualification is
still pending. The checker parses source without importing the scientific payload.

The [selected-generation receiver](../../optimisation/workbench/plan26/receiving/README.md)
checks the constructor and complete source membership before invoking its
prepared-base guard. It also authenticates the original paired-profile
configuration and exact namespace authority. The explicit public receiving caller
connects that source boundary to its selected transformer and parity tools. It
binds the public constructor context, source graph, construction-return roles and
paired API intake, retaining exact status checks and recursive purpose/rehearsal
refusal. Unbound public tool or authority projections refuse before dispatch.
Local execution and public counterpart identities are recorded separately;
actual public observations, fold gates and runtime qualification retain their own
evidence. The [selected public fold source](../../optimisation/docs/release/fold/r10/README.md)
provides the separately bound transformer and checker counterparts. Prepared policy
data and predecessor recordings do not supply missing
actual fold bindings.

After a completed fold, the [runtime metadata constructor](../../optimisation/workbench/plan31/final/folded-runtime-r1/README.md)
binds the actual source, manifest, report and fixed tool identities before deriving
new paired profiles. The report must explicitly declare an empty rehearsal list;
a missing declaration, null, boolean false or a nonempty list is refused. The
actual fold caller requires all seven gates to pass. Constructed metadata and
strict identity capture still require the subsequent receiving qualification.

The [complete original-record consumer](../../optimisation/workbench/plan26/receiving/final-records-r2/README.md)
checks the original producer and reader sources, collected records and completed
process evidence before comparing a source arm with its folded counterpart.
The parent creates each leg's authority only after that independent evidence
has passed. A collection envelope or a fixture-created authority cannot supply
missing process finality. Source identities are rederived from their full
original preimages. Differences are permitted only in named source-defined
identity slots with the corresponding typed proof; physical values and unknown
containers remain exact.

The comparison consumes complete private heat results, original checkpoint
arrays, force and geometry records, retained accounting and historical storage
records. It checks native manifests, page and chunk bindings and the complete
logical records decoded from their original carriers. Indexed binary64 values
are read in source order without float re-encoding. Prepared migration preserves
historical funding and its full native, collar and spatial records. Logical
resource reservations, limits and release obligations remain distinct from the
explicitly identified measurements; an equal total does not excuse a missing
accounting field.

The selected ordinary fresh route compares two completed intervals; prepared
receiving follows the actual migrated-root successor. This is separate from the
six first-freeze source/fold arms, which stop before numerical advance. A complete
synthetic pair can test record handling and physical-change refusal without
proving that the native generator produced its geometry or that an actual reader
and process qualified. Those runtime and scientific claims require their own
source-bound results. Source/fold qualification can precede installation; the
installed consumers still require their separately qualified delivery.

Installing that same folded source has a separate
[profile relocation route](../../tools/materialise_profile.py). It authenticates
the completed constructor result, selected profile and exact fold before moving
their references to the qualified installation. The original policy, manifest
and evidence remain pinned external dependencies. A separate installation policy
names the new manifest and rebases all evidence references together. Source
inventories, constraints and measured execution identities remain unchanged;
the existing prepared runner and independent reader still require the selected
manifest to match that policy. The profile pins the policy after the manifest
is written, avoiding a circular hash dependency. This does not change preparation
bytes, native source identity or historical acceptance. A different fold
requires its own construction and evidence. Actual source and installed consumer
checks remain necessary after the real artefacts arrive.

Wheel and strict-desktop packaging read fixture membership from the same
authenticated application declaration. Executable aliases must cover every
declared fixture exactly once, while case JSON and documentation remain data.
The build checks the complete source before copying and checks the copies again;
an older fixed fixture list cannot silently substitute another generation.
These checks preserve the selected bytes. They do not establish runtime or
scientific qualification.

### Save losslessly, share unchanged chunks and publish atomically

Repeated saves retain the exact stored-byte total only while SQLite's data,
connection-change and schema versions match the last accepted publication.
New rows add their exact sizes. A different writer, schema change, rollback or
unrecognised schema forces the original full scan. The store and SQLite page
limits still apply; direct file tampering outside SQLite is outside this existing
local-store trust model. No approximate size estimate replaces the safety gate.

[ArrayStore](../../src/atlas_tectonics/storage.py) keeps typed arrays in SQLite
as independently identified chunks. Exact uniform values, packed categorical
indices, run-length records and Blosc2/Zstd compression reduce repetition without
quantising floating values. Signed zero and unknown-value masks keep their
meaning. Fast, balanced and compact profiles trade chunk granularity against
metadata and partial-read cost; opening a store does not migrate it.

Unchanged chunks can be referenced directly; replacing one complete chunk does
not rewrite the whole history. Manifests point to their payloads directly, avoiding
long decode chains. Encoding and round-trip checking precede the write transaction.
A bounded spool uses memory then temporary disk; publication rechecks dependencies
and commits one complete manifest. [SQLite isolation](https://www.sqlite.org/isolation.html)
and [Blosc's compression API](https://blosc.org/python-blosc2/reference/autofiles/low_level/blosc2.compress2.html)
are actual software foundations here.

Reads verify metadata and payloads. Bounded decoded/verification caches are
invalidated by relevant database changes; chunk reads and streaming avoid loading
an entire snapshot. Consistent backup creates an independent database copy.

A store opens only a database whose schema is exactly its own three tables. A
view, trigger, generated column or extra index would run SQL the store never
wrote, and a shared file can contain one: before the R4 repair a 26 KB crafted
project made loading hang. SQLite's [security guidance](https://sqlite.org/security.html)
treats a database file from elsewhere as untrusted input; the store already set
its recommended `trusted_schema=OFF`, yet a trigger running a recursive query
still hung the open in Atlas's test. The store therefore compares the recorded
schema text ([`sqlite_schema`](https://www.sqlite.org/schematab.html)) with its own
before any statement touches the tables. SQLite parses that schema at the very first
statement, so the parse itself is bounded too: statement length and the opening's
[virtual-machine work](https://www.sqlite.org/c3ref/progress_handler.html) are
capped (an 8 MB view previously cost about 700 MiB before any check could run). A snapshot is also published only when a
full read under the same limits could load it back, and SQLite failures reach
callers as the store's own error, with lock contention reported separately from a
damaged file. Dated histories go one step further: a checkpoint is written only
after its complete restoration has been admitted under the same memory budget, so
a stopped history can always resume
([dated histories](../TECTONIC_HISTORIES.md#recovery-and-optimisation)).
Reusing the latest output in memory also checks the store's change token. If
another writer has changed the database, the saved output is verified again;
matching output names alone cannot hide damaged data or justify continuing it.
[Storage-profile tests](../../tests/test_storage_profiles.py) exercise malformed
encodings, changed dependencies, staging, rollback and restoration. The
[recorded comparisons](../../evidence/storage-comparisons.json) include a slower
first-write path alongside faster repeated reads: compression and staging do
not guarantee every operation improves. Journals, spools and backups need space
in addition to the database allowance; referenced histories are dependencies.

### Carry verified pages between read batches

The optional [L3 candidate](../../optimisation/workbench/plan22/README.md) addresses
repeated reads of the same immutable pages. A view can retain at most 128 verified
pages between its batches, trimming to 10 MiB of booked memory per view and
refusing a carry above 32 MiB across the process. The page cache remains 64 MiB.
The registry and page holders keep their existing charges; raw and booked bytes
are reported separately.

The next batch must enter its verified read before adopting carry. Optional carry
remains reclaimable while that entry acquires its required reservation, so it
cannot hide memory needed for admission. Every served access still checks the
segment. In an outermost store-set read, carry follows the closing freshness
check. A view batch nested inside another verified read can carry before that
enclosing check; if it refuses, the next verified-read entry must refuse before
adopting those pages. Outside-batch reads use the ordinary verification path. Idle carry yields after
unpinned pages cannot meet pressure; record and mesh close release it. Failed
frames keep their own data funded. Evicted pages also leave the bounded touched
set, preventing a long scan from retaining an unbounded list of closed wrappers.

The receiving port preserves the mesh's streaming encoder used by diagnostic
captures and its repeated-close behaviour. Synthetic exactness, lifetime,
pressure and refusal controls exercise these boundaries. The corrected-reader
[controlled comparison and additive source selection](../../optimisation/workbench/plan22/README-r4.md)
now meet the recorded selection rule: 15.4381 s to 12.2384 s mean sealed-ledger
reopen (3.1997 s / 20.73%) on the private comparison stack. The public/final stack
was not timed. Component integration is finally accepted. Individual L3
verification after assembly, including final L1 checks, was cancelled by the
owner; this is not a PASS and does not enable runtime/default use or release
other run/scientific holds.

### Keep physical correspondence separate from row names

The separate optimisation review route found that provenance-dependent cell
names could change row order while describing the same physical cells. Equal
floating-point output arrays did not guarantee equal exact residual accounts:
the private solver's finite-arithmetic work still depended on that order.
The bounded repair gives arithmetic scratch a common physical-key order, then
maps results back to public rows. It changes no equations or tolerances.

The observer retains funded owners through callbacks, finalisation and escaped
tracebacks. Its verifier first proves one complete cell correspondence and a
separate face/incidence/orientation correspondence, compares physical inputs,
then checks all arrays, exact cell accounts and paired-face energy. Remaining
provenance/resource differences require explicit dispositions.

[Plan05's method and implementation](../../optimisation/workbench/plan05/README.md)
record the actual source, checks and limitations. The corrected private pair is
exact; this is neither general physical validation nor a main-package overlay.
Collective correctness acceptance and the held performance run remain separate.
This explanation derives from the retained code and exact replay; no new
external scientific literature was consulted for the repair.

### Bound parallel work and measure the complete workload

[KernelExecutor](../../src/atlas_tectonics/execution.py) parallelises eligible
independent batches, preserving returned order. Small requests stay serial;
automatic execution normally uses at most two workers, four in-flight tasks and
one inner native thread. Process execution is explicit. Precursor point sampling
can share one plan's prepared indices and starting state among worker threads,
while its automatic cell route stays serial following measured overhead. Each
threaded precursor request builds its own bounded executor on the calling thread
and closes it before returning. A prepared plan therefore keeps no worker pool or
native-thread limit between requests, is not tied to the thread that first used
it, and can be closed from any thread once no call is active. Threaded requests on
one plan take turns: each uses several workers, but two never overlap. The
process-wide native-thread limit is set only while such a request runs, and a
request made while another live thread holds that limit is refused and leaves the plan
usable. The [execution contract](../OPTIMISATION_REFERENCE.md#3cr2-scaling-execution)
records this 1 October 2026 repair and its cost: the pool is rebuilt for each
threaded request. The prepared local-law evaluator
([PreparedRheology](../../src/atlas_tectonics/constitutive_execution.py)) follows
the same rule when a caller selects threads; its normal route is serial. It differs
in one respect: an evaluation that overlaps another on the same plan is refused
instead of waiting its turn
([R3 execution notes](../OPTIMISATION_REFERENCE.md#3cr3-execution)).
The native-thread limit has one owning thread at a time, recorded as the thread
itself and not as its identifier, which the system reuses. Should that thread end
with an executor still open, any thread may close that executor, and the next
thread to take the limit reclaims it and the pool's CPU slots once every job the
ended thread had submitted is done; before the
same repair every other thread stayed refused for the rest of the process
([executor contract](../OPTIMISATION_REFERENCE.md#execution-reuse-delivery)).
Dependent physical timesteps are not independent jobs.

[WorkBudget](../../src/atlas_tectonics/resources.py) admits estimated simultaneous
allocations before work and shares reservations between related owners.
Queue bounds, worker allowances, native-thread controls, cancellation and owner
closure prevent accidental unbounded execution. Accounted memory is not process
RSS: interpreters, libraries and caller-retained results require additional room.
[Combined-resource tests](../../tests/test_combined_resources.py) and the
[recorded drill](../../evidence/comprehensive-resource-r1.json) distinguish the two.

The [module-wide W11 measurements](../OPTIMISATION_REFERENCE.md#w11-module-wide-linked-workflow-pass--24-september-2026)
compare complete matched requests: W01→W02 construction fell from 1.237829 to
0.928682 seconds; a three-output W05 sequence from 1.307060 to 0.970070 seconds.
W07 verifier reuse and checkpoint-copy removal have separate comparisons. The
protocol includes preparation, checks, output construction and closure, following
[PETSc's application-level profiling guidance](https://petsc.org/release/manual/profiling/);
PETSc itself is not required by these measurements. Different percentages cannot
be added or multiplied. GPU/MPI execution, general adaptive/distributed operators,
out-of-core solving and the six recorded advanced optimisation candidates remain
unestablished or deferred.

## W12: assemble, save and inspect supported results

### A real column workflow through Atlas's graph

[PreparedColumnAssembly](../../src/atlas_tectonics/assembly.py) connects a
W01/W02-backed material state to W03 cooling/compaction and W04 elastic support.
Its inputs include the schedule, fixed reference, finite reservoir, allocation
and pressure policies, physical context and resource limits. Each interval uses
the current reservoir; support is the total response from the initial reference.
Initial surfaces inconsistent with the declared policies refuse.

[The W12 graph adapter](../../tools/w12_graph.py) registers this producer and a
read-only field consumer through the retained R11 contract, R24 executor and R12
cache. The consumer inspects actual arrays; it adds no downstream physics. W12
does not silently retarget R31's historical tectonics operation.

Exported fields keep their known/unknown meaning. When a regional snapshot has
no pressure datum, its normal stresses and the normal components of its boundary
tractions carry the same arbitrary pressure constant, so all of them are marked
`declared-gauge`; tangential tractions are unaffected. (Before 30 September 2026
the normal tractions were exported as ordinary known values.)

The native checkpoint is saved first, consumer arrays next, completion marker
last. Resume validates the committed prefix and computes missing outputs only;
gaps or missing dependencies refuse, including on graph-cache hits.
[Assembly](../../tests/test_w12_assembly.py) and
[graph tests](../../tests/test_w12_graph.py) compare complete direct, assembled,
clean and resumed results. The [assembly receipt](../../evidence/w12-assembly-r1.json)
records that historical integration evidence. The
[subsequent repair record](../REVIEW_REPAIRS_2026-09-26.md) separately covers
signed-zero export, initial-surface policy and ownership corrections.

### Export compatible fields without inventing a physical bridge

[Workflow ports](../../src/atlas_tectonics/workflow_ports.py) describe 17 supported
output forms: regional material, columns, support, extension, three ocean/margin
forms, three W07 forms, joined W08, and three direct plus three dated-history
forms. Exports preserve arrays, units, support, owners, masks and provenance.
They require explicit world, snapshot, calendar, spatial frame, vertical reference
and scenario identities. Matching names do not transform coordinates or reconcile
incompatible physics. Ocean outputs additionally require their exact open native
owner for authentication.

Where a table lists its columns by name, it does so in one way on every route:
an ordered list with one name-and-unit row per column. Until the R7 repair
of 1 October 2026 the two ocean forms listed bare column names and kept the units
in a separate list, so a reader written for the support tables failed on them.
Their values did not change, but the published format did, so those two routes
are now named `w06-constant.v2` and `w06-history.v2`; a reader that selects by
route name must ask for the new names. The
[port tests](../../tests/test_w12_ports.py) describe all 17 output forms and
check the row form wherever such a list appears.

[Publishing tests](../../tests/test_w12_publishing.py) check full fields, native
bindings, frame refusal and value bits. A consumer export supports inspection and
exchange; native restart also requires original inputs, policies, schedule,
producer and checkpoint dependencies. The
[supported-route matrix](../W12_ASSEMBLY.md#supported-route-matrix) does not supply
the missing heterogeneous W06→W07 connection or W09 feedback.

### Manage jobs and view only saved physical states

[Managed jobs](../../tools/tectonics_job.py) wrap the same bounded column case
with immutable requests, process locks, cooperative cancellation and verified
resume. Repeating an ID cannot start duplicate work; altered inputs refuse.
A new job appears all at once: its request and first status are written into a
dot-named staging folder and renamed to the job ID, so a status or cancel call made
during submission finds no job or a complete one, never half of one (before the R4
repair a poll at that moment could make the ID permanently unusable). A poll holds
the job's lock only briefly, so the worker waits for it instead of refusing; until
the worker has the job, status shows it as submitted and a cancel made then is
kept. If the worker cannot take it, the job is recorded as interrupted and never
started, and resume starts it. A failed submission removes only the files it
created. Control files are compact JSON, refused before writing if they would
exceed the 64 KiB their own reader accepts
([managed-run rules](../W12_ASSEMBLY.md#managed-local-run-cancel-and-resume)).
A cancellation request is distinct from an acknowledged stop, and late
cancellation can arrive after verified completion. Committed outputs survive
interruption. [Worker tests](../../tests/test_w12_job_worker.py) exercise these
boundaries; the [operational record](../W12_ASSEMBLY.md#managed-local-run-cancel-and-resume)
also preserves an actual Windows cancel/resume comparison. Its 5–64 columns,
three dates and finite budgets describe this example, not production capacity.

[Saved-result reading](../../tools/read_tectonics.py) and
[section viewing](../../tools/view_tectonics.py) use a temporary consistent store
snapshot without evolving the model. The catalogue reports saved/missing times;
selecting a time invokes full native verification. Ordered parcel grain volume
and void ratio reconstruct thickness and depth below the current sediment surface.
Signed support curves and their masks remain separate. This is neither absolute
topography nor interpolated history. [Section tests](../../tests/test_w12_section_geometry.py)
check native ordering, reconstructed volume, units, slicing and unknowns. The
software basis is native checkpoint restoration and
[Python's SQLite backup interface](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup),
not a new physical model. Browser presentation and whole-world generation retain
their own acceptance boundaries.
