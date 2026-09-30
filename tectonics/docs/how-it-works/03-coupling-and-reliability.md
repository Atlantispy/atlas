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
remain visible. Several prepared workflows retain only their latest complete
result, limiting growth. Changed physics computes a new answer even when
unchanged geometry remains reusable.

[Execution-reuse tests](../../tests/test_execution_reuse.py) cover invalidation,
same-request coordination and failure paths. Hashes support identity and
corruption detection; they are not signatures against an attacker who controls
both code and stored records. Loaded binary identity also assumes those binaries
remain unchanged during the process.

### Save losslessly, share unchanged chunks and publish atomically

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
[Storage-profile tests](../../tests/test_storage_profiles.py) exercise malformed
encodings, changed dependencies, staging, rollback and restoration. The
[recorded comparisons](../../evidence/storage-comparisons.json) include a slower
first-write path alongside faster repeated reads: compression and staging do
not guarantee every operation improves. Journals, spools and backups need space
in addition to the database allowance; referenced histories are dependencies.

### Bound parallel work and measure the complete workload

[KernelExecutor](../../src/atlas_tectonics/execution.py) parallelises eligible
independent batches, preserving returned order. Small requests stay serial;
automatic execution normally uses at most two workers, four in-flight tasks and
one inner native thread. Process execution is explicit. Precursor point sampling
can share prepared indices across threads, while its automatic cell route stays
serial following measured overhead. Dependent physical timesteps are not
independent jobs.

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
