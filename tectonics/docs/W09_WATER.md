# W09 Step 2: drainage and finite lake water

23 September 2026. **WORKING NON-CANON. Step 2 COMPLETE** for the bounded
instantaneous-routing/ideal-sill model selected in the
[frozen design](W09_SURFACE_PROCESSES.md). The original design and
[case register](../cases/w09_surface_processes_r1.json) remain unchanged.

## Implemented

- `w09_drainage.prepare_drainage`: detached immutable geometry, deterministic
  steepest-downhill receivers, acyclic flat routing, complete basin/saddle
  adjacency and Priority-Flood escape levels. Physical terrain is never filled.
  Higher alternative saddle connections are retained, not discarded by taking
  only each basin's first spill. Closed components have no invented outlet.
- `w09_water.PreparedWater`: finite volume filling, internal spills, merging,
  drawdown/splitting, drying, precipitation, effective runoff, evaporation and
  infiltration. Simultaneous losses are accounted before surplus export.
  Competing dry-bed losses share only the actually available input water.
- Event integration stops at physical bed/sill/dry boundaries; a single request
  can cross those events without exposing half-applied accepted state. Current
  lake occupancy is rebuilt after drawdown; historical filled flags are not reused.
- `accumulate_runoff` exposes dry-network discharge in m3/s, stopping at pits and
  declared outlets. It does not masquerade as transient lake discharge.
- `relocate` conserves the water on unchanged indexed cells/areas while changing
  bed/connectivity. Frame/datum and physical support must agree. Water newly able
  to escape is booked as export, not deleted. Arbitrary moving-grid overlap still
  requires the Step 4 consumer adapter.
- Source-bound complete states, one latest-result cache, and explicit atomic
  ArrayStore checkpoint/restore. A restored continuation pays only remaining
  transfers. Cancellation/refusal leaves the caller's accepted state unchanged.

The water state keeps surface m3, subsurface m3, atmospheric export m3, boundary
export m3, total supplied m3 and the initial total separately. Their integrated
account must close under the frozen binary64 tolerance. No sediment, soil flow,
support displacement or pore water is silently created by this component.

## Numerical details and interface

Use metres, m2, seconds and m3. Positive-area cells hold water; explicitly
zero-area connectors can represent a saddle without adding fictitious storage.
Outlets also have zero area. Every pit's lowest plateau needs positive area.
Link lengths must be positive; duplicate/self links, non-finite values and
unconverted/bool indices refuse. Flat ties use shortest-hop routing then stable
node IDs. Outlet spill ties use lowest sill then stable basin order.

Prepared geometry stores the full spill graph. The water solver forms currently
connected lake groups from it and resolves the active ideal-sill constraints.
This is a bounded graph implementation, not copied FSM code or a claim of linear
complexity for every coupled lake event. Effective dry-land runoff is supplied;
when `rain_m_s` is omitted, the same supplied depth flux explicitly applies to
wet footprints. Separate lake rainfall can be supplied. These are model forcing
inputs, not an inferred climate.

At a cell's represented shoreline the wet/dry footprints change discontinuously.
A receding patch ceases evaporation/infiltration. If the two one-sided rates
straddle zero, a bounded wet-duration fraction balances the contact without
nudging terrain or manufacturing water. All simultaneous contacts are resolved.
This is an explicit sub-cell contact convention, not resolved shore hydraulics.

`PreparedWater(..., frame_id=..., datum_id=..., source_id=..., budget=..., store=...)`
owns the reusable geometry and execution identity. `initialise`, `add_water` and
`advance` return immutable `WaterState` values; `advance` accepts a constant
forcing interval and its `forcing_id`. Changing forcing invalidates affected
results, not geometry. New physical geometry requires a new prepared model.
`checkpoint(state)` returns an ArrayStore key; `restore(key)` verifies plan,
source/runtime, array, account and state identities before returning it.

The model owns an 8 MiB conservative allowance for context, graph/event scratch,
one output and up to 256 cached group hypsometries. Sorted cumulative area/volume
tables replace repeated height searches with binary searches. Temporary geometry
work joins the same parent budget. Cached state is bounded and released on close.
Caller-owned retained results are not an unlimited managed archive.

Bounds remain 256 nodes, 2048 connectors, 128 MiB shared accounted work and 256
cumulative accepted subintervals. No ceiling was increased. Source membership is
now 117 Python files, below the unchanged 128-file cap; both W09 modules join the
existing loaded-code/source identity. Old checkpoint identities are not repinned.

## Verification and measured efficiency

Six new drainage tests and sixteen water tests have passing Windows evidence.
They cover frozen W1-W4, nested drawdown, disjoint forcing footprints, event
partitioning, newly dry shores, multiple simultaneous shoreline contacts,
finite loss allocation, conservative bed changes, read-only snapshots, invalid
inputs, cancellation, shared-budget cleanup, interval limits, result reuse and
exact checkpoint continuation. The latest complete water suite took 8.337 s;
the subsequently added accumulation assertion and nine existing identity tests
took 3.737 s together. No broad physical campaign was repeated.

A targeted numerical check found that resolving only the first of two independent
shore contacts could conserve total water while drying the second incorrectly.
The active-set loop was corrected and that exact two-basin case is now a test.
The first evidence write exposed a NumPy-bool JSON serialisation error; the checker
was corrected, the incomplete local file preserved, and a new complete report
produced. These were fixed failures, not accepted exceptions.

[Source-bound evidence](../evidence/w09-water.json) records all four frozen water
controls (41 numerical/account observations), every timing sample, output hashes,
runtime and budgets. The complete control/timing run took **16.3237191 s**.
Three rotated cold/prepared pairs per workload include preparation, source checks,
fresh initial states, changed forcing, complete evolution, output materialisation
and close. There were no full-output cache hits in these comparisons.

| Workload | Cold median | Prepared median | Saved |
| --- | ---: | ---: | ---: |
| One fresh 256-node drainage request | 0.3407067 s | 0.3407240 s | No meaningful change; 0.0000173 s slower |
| Three changed drainage requests | 1.0249139 s | 0.6155989 s | 0.4093150 s / **39.9365%** |
| Three changed lake requests, 64 two-child systems | 1.0894821 s | 0.7501048 s | 0.3393773 s / **31.1503%** |

All complete output arrays and state identities were bit-identical between
routes. The lake fixture includes split/dry events, not only open drainage.
Peak shared accounted work was **9,158,656 bytes**; this is not process RSS.
Python 3.12.14, NumPy 2.4.6, Windows 11; both measured native pools had one thread.
These are reuse savings on stated workloads, not a whole-world time prediction.

Reproduce with the existing scientific environment:

    python -B tectonics/tools/check_w09_water.py --repo . --report <new-report.json>

The report target must not exist. The tool fixes the reference hash, checks source
stability and preserves failure status; it does not update thresholds or fixtures.
Static coding-safety checks pass (13 maps/41 paths;31 tests, one environmental
skip). Linux execution was not repeated in this increment; no OS-specific water
solver path or new runtime installation was introduced.

## Papers and software used

- [Barnes et al. (2014), Priority-Flood](https://richard.science/sci/2014_depressions.pdf):
  depression/escape preparation and deterministic priority ordering.
- [Barnes, Callaghan and Wickert (2021), Fill-Spill-Merge](https://esurf.copernicus.org/articles/9/105/2021/):
  hierarchical filling and area-weighted lake levels; its equilibrium snapshot is
  distinct from the explicit Atlas loss/event integration implemented here.
- [Landlab LakeMapperBarnes](https://landlab.readthedocs.io/en/latest/generated/api/landlab.components.lake_fill.lake_fill_barnes.html)
  and [FlowAccumulator](https://landlab.readthedocs.io/en/latest/tutorials/flow_direction_and_accumulation/the_FlowAccumulator.html):
  separation of routing geometry, lake capacity and accumulated supplied runoff.
  No third-party simulator was installed or claimed as an executed comparator.

**Next:** W09 Step 3, material-aware bedrock/alluvium erosion and finite-supply
hillslope transport. Joined sediment/thermal/load feedback remains Step 4.
