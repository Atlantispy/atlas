# W01 Stage 7: described geology to regional material evolution

22 September 2026. Local, unreleased implementation; WORKING NON-CANON.
This connects the supported S5/S6/W02 route, not whole-W01 scientific acceptance.
The subsequent [Stage-8 assessment](W01_COMBINED_ACCEPTANCE.md) checks this
assembled route. Reopened S3C acceptance, unrestricted spherical dynamics and
R4.4 remain separate. No long simulation was run to implement this bridge.

## Public workflow

`PreparedRegionalWorkflow(initial, definition, section, reduction, grid, support)`
takes an `InitialConditionState`, the existing S6 motion records, a uniform
`RegionalGrid1D` and an explicit `RegionalColumnSupport`. It builds the cell
footprints, obtains S5 intersection inventories, constructs W02 material cohorts,
and prepares source-bound face velocities. Callers do not assemble numerical
inventory arrays. Sources, material definitions, formation times, cooling history,
unknown masks and the original geological description remain accessible through
`state.initial_samples.state`.

```python
with PreparedRegionalWorkflow(initial, motion, section, reduction, grid, support,
                              budget=budget) as plan:
    start = plan.initialise()
    end = plan.advance(start, left=left_boundary, right=right_boundary)
    save_regional_workflow(end, store, budget=budget)

restored = load_regional_workflow(store, end.workflow_id, budget=budget)
with PreparedRegionalWorkflow.from_state(restored, budget=budget) as plan:
    # Only if some of the ORIGINAL frozen forcing interval remains:
    continued = plan.advance(restored, left=left_boundary, right=right_boundary)
```

An omitted duration advances to the original S6 endpoint. A supplied positive
duration can cover a prefix. The unchanged W02 adviser determines substeps;
the default remains MUSCL/Numba, with no numerical fallback or interval extension.
Boundary reservoirs/composition must be explicit, including all required inflow.
Each accepted step retains its parent, cohort exchanges and numerical receipt.
`initialise()` always returns the original root, not the latest advanced state.

Run the complete authored example, from the repository root:

```text
python -I -B tectonics/tools/run_w01_workflow.py
python -I -B tectonics/tools/run_w01_workflow.py --benchmark --output s7-timing.json
```

The example uses two explicitly synthetic rocks, three geological strips and
32 solver cells. It verifies a 24 m3 initial inventory and evolves 0.025 seconds.
It installs/downloads nothing; `--output` refuses to overwrite existing evidence.

## Meaning of the conserved quantity

For cohort k and numerical cell i:

`q[k,i] = sum(actual S5 phase intersection volumes[k,i]) / (ds * reference_width)`.

Hence `sum(q * ds * reference_width)` is the retained volume. Stable grouping
with compensated summation preserves small mixed-fragment contributions. There
is no re-normalisation of authored fractions or implicit density/porosity law.
W02 calls q "partial thickness"; in the spherical route it is an equivalent
inventory per reference area, **not raw radial thickness**. W02 exchange receipts
are per unit reference width (m2); multiply by the declared width for m3.

Planar support is a straight strip centred on the declared section, of explicit
reference width and initial depth band. Its complete footprint must lie inside
the regional topology. Every intersecting owner must have compatible full
relative-motion coefficients, not merely the same projected speed at a centre.
S6's continuous-section discontinuity checks are still mandatory.

Spherical support is a complete north- or south-hemisphere longitude wedge about
the section's declared pole, bounded by great-circle meridians and the equator.
Axial relative Euler rotation preserves that transverse support. Surface area is
`R * ds`; shell volume is `ds/R * (r_outer^3-r_inner^3)/3`. S5 uses stable shell
arithmetic, not surface area times depth. For R=10 m, depths 0–2 m, width=10 m,
q=122/75 m, not 2 m. The two hemispheres are separate supported queries, not a
general finite-latitude strip or a two-dimensional spherical mechanics model.
Changed/unsupported owner motion anywhere inside a wedge is refused.

Explicit pore phases require `PoreFluidCohort(unit_id, cohort, source)` mappings.
Different units can share an explicitly identical fluid history or retain
different origins. No fluid age/origin is invented from a material name. Bulk
reference materials keep their declared intrinsic-pore uncertainty; this bridge
does not claim to resolve unknown true solid volume, heat or in-situ mass.

## Initial temperature is not evolved temperature

Initial profiles, source conditions, volume-weighted temperatures and validity/
known masks survive every step and restore. Their label remains **initial epoch,
not evolved heat or temperature**. No temperature advection, thermal density,
compaction, relative fluid motion or new W03 physics is implemented here. Carried
formation/cooling provenance must not be interpreted as a current thermal field.

## Reuse, restoration and bounds

One preparation is reused across consecutive steps or independent scenario
branches. Initial samples/forcing are shared immutable objects; history is a
linked sequence, not repeatedly copied into each new state. Persistent transport
reuse uses the existing `ArrayStore` and `CachePolicy`; no extra scheduler/cache
service, compression format or worker pool is added. Dependent time steps remain
sequential. Parallel workers would add overhead to the bounded example.

Snapshots save dependencies before their workflow nodes. Restoration checks
source/runtime, whole-footprint geometry and S5 plan binding, initial inventory,
every parent/time/velocity/policy binding and cohort balance receipt. It does not
re-sample geology or re-evolve the material. Existing integrity checks are not
proof against a hostile Python runtime or a substitute for scientific validation.
The new modules join the live-callable execution identity inventory. Changed
source requires a new run; historical runs are never automatically rebound.

The wrapper accepts at most 4,096 cells, 4,096 cohorts and 256 cumulative steps,
subject also to existing geometry/sampling, byte-budget and numerical limits.
These are finite engineering bounds, not a tested capacity claim. Plans admit
retained descriptions, topology, samples, velocities and execution state;
advances admit their candidate history. Returned snapshots transfer ownership to
the caller. `WorkBudget` is an allocation-admission estimate, not an RSS ceiling.
Cancellation is checked through preparation, aggregation and each substep.
Unrepresentable clocks/metrics, exhausted budgets, changed bindings, unsupported
interfaces, incomplete inflow and off-section movement are refusals, not silently
repaired outputs. A failed advance publishes no partial workflow result.

## Method references

The official [Geodynamic World Builder painting model](https://gwb.readthedocs.io/en/latest/user_manual/concepts/painting_in_the_world.html)
and [2D section documentation](https://gwb.readthedocs.io/en/latest/user_manual/basic_starter_tutorial/18_2D_models.html)
(manual 1.2.0-pre, accessed 22 September 2026) support separating source geometry,
feature precedence and numerical queries. Their point-query model is not proof
of conservative cell integration.
[ASPECT particle properties](https://aspect-documentation.readthedocs.io/en/latest/parameters/Particles.html)
(3.2.0-pre) distinguish initial composition/position/generation time from evolving
properties. [Kritsikis et al. (2017), sections 2, 3.4 and 4.3](https://gmd.copernicus.org/articles/10/425/2017/)
support intersection-based conservative spherical remapping and reuse of fixed
geometry. The shell-volume reduction above is derived for this restricted
workflow; that paper does not validate its physics. No external code/dependency
was copied or added.

Focused verification and measured timings are recorded in
[Stage-7 evidence](../evidence/w01-stage7-workflow.md).
