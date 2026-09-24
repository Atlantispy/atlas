# Coding Atlas without losing the active route

Reviewed against public commit `15a8e8f217a84ebedc47489dfe9a213efe2baa67`.
This is a source-navigation and change-review map, not an installed runtime,
complete call graph, scientific sign-off or replacement for execution bindings.
The current status remains [WORKING NON-CANON](CURRENT_STATE.md).

## 1. Choose the route before reading the stack

Paths below are relative to `engineering/work/` unless stated otherwise.

| Requested change | Start here | Retained wiring that matters |
| --- | --- | --- |
| Current W12 tectonics assembly | Repository paths `tectonics/src/atlas_tectonics/assembly.py`, `workflow_ports.py`, `tectonics/tools/w12_graph.py` | Explicit current producer and read-only consumer use the captured R11 contract, R24 executor and R12 cache. They do not load R31's scientific registry or retarget its historical tectonics operation. Run the focused `test_w12_*.py` seams for changes here. |
| Read-only saved tectonics result connection | Repository path `tectonics/tools/read_tectonics.py` | Uses existing native verification/restoration on a temporary SQLite snapshot, never starts or repins a simulation. Keep presentation adapters outside the source-bound package; `tectonics/tests/test_read_tectonics.py` has small guards and explicitly opted-in retained-result checks. |
| Managed W12 UI runs and recovery | Repository paths `tectonics/tools/tectonics_job.py`, `w12_job_worker.py` | Trusted local CLI paths; one process-locked worker per jobs root, immutable inputs/source/runtime, cooperative cancellation and original native restore. Focused `test_tectonics_job.py` and `test_w12_job_worker.py` use isolated fake seams; a small authorised process test verifies native parity. No detached worker, new numerical scheduler or silent rebind. |
| Calculated W12 section and saved-time inspection | Repository paths `tectonics/tools/view_tectonics.py`, `w12_section_geometry.py` | Read-only native checkpoint catalogue; selected-output restoration and parcel geometry. Preserve source bindings, top-to-bottom compaction order, separate cohort totals, relative depth and signed/masked support curves. Focused `test_view_tectonics.py` and `test_w12_section_geometry.py`; never run a simulation to fill missing saved times. |
| New-world seed/settings contract | Repository paths `tectonics/tools/new_world_contract.py`, `new_world.py` | Configuration-only, outside pinned native sources: strict Fixed/Auto inputs, named seed streams, scientific/execution identities and no-overwrite plan persistence. Focused `test_new_world_contract.py` and `test_new_world_cli.py`. Independent random draws never imply independent physical components; dependent crust/plate calculations still require invalidation. No world or simulation is produced here. |
| New-world candidate plate layouts | Repository paths `tectonics/tools/new_world_layout.py`, `assess_plate_layout_morphology.py` | Strict step-1 plan consumption; variable exposed-reference size prior; native shared sphere and connected sparse cuts. Focused `test_new_world_layout.py` and `test_new_world_layout_morphology.py`. Preserve one-attempt refusals, source/runtime identities and reference split; descriptive morphology is not geological acceptance. Native package remains unchanged. |
| Seeded starting crust and lithosphere | Repository paths `tectonics/tools/new_world_structure.py`, `new_world_thermal.py` | Plate/grid-independent native geological precursor; joint columns, ages and bounded analytical thermal tables. Focused `test_new_world_structure.py` and `test_new_world_thermal.py`, plus the affected project/session seams. Preserve material-reference versus thermal-law distinctions, explicit unknown inheritance, spherical mixed-cell accounts, source bindings and v1/v2 archive compatibility. Native package remains unchanged. |
| Saved new-world candidate projects | Repository path `tectonics/tools/new_world_project.py` | Single portable file containing the original plan/report and lossless native atlas. No-overwrite save and read-only source-file reopening through a temporary native store; no regeneration, source repin or simulation restart. Focused `test_new_world_project.py`. Separate from the UI request/presentation project format. |
| Generated regional continuation | Repository paths `tectonics/tools/new_world_native.py`, `new_world_evolution.py`, `new_world_job.py` | Actual S2/S3/S4 initial state and native S5 inventories feed full-vector W08 material deformation plus explicitly dry local Airy support. Focused `test_new_world_native.py`, `test_new_world_evolution.py`, `test_new_world_job.py`. Keep source/input checks on cache hits, immutable committed outputs, unknown heat and full normal/shear motion. No global topology evolution, W12 fixture substitution, native source edit or historical repin. |
| Combined new-world acceptance | Repository path `tectonics/tools/check_new_world_acceptance.py` | Fixed three-case real workflow, fresh-process continuation and independent finite-area/column-weight checks; source-only tool outside native package. `test_new_world_acceptance.py` checks fail-closed reporting without a campaign. Do not retry rejected seeds, rewrite historical receipts or rerun the matrix just for documentation changes. |
| Portable initial world and regional results | Repository path `tectonics/tools/new_world_bundle.py` | New wrapper preserves original source-bound adapters, archive bytes and committed prefixes. `test_new_world_bundle.py` has bounded synthetic archive/lifecycle guards; actual complete/partial portability evidence is separate. Never call submit on import, extract arbitrary member paths, overwrite destinations, copy process locks or repin old jobs. Only the UI owner registers imported job roots. |
| New/Save/Load World native UI adapter | Repository path `tectonics/tools/new_world_session.py` | Explicit bounded candidate generation and lossless reopening; path-free machine responses and actual indexed spherical geometry. UI server owns managed file paths and serves original project bytes. Focused `test_new_world_session.py`; preserve current world on refusals and leave UI rendering/server ownership with the UI task. |
| Wider connected generator recipes | `generator_upgrade_r31/registry.py`, `__main__.py` | The CLI clones R27's CLI with the R31 registry. The registry clones R30 execution, retains R28 planning/preflight and R26 registration machinery, then overrides six topography operations. Follow the imported modules, not a guessed linear R1-to-R31 chain. |
| R31 topography integration | `generator_upgrade_r31/topography.py` | Uses `topography_r1/{terrain,kernels,transport,provenance}.py`, `geology_r1/consumer.py`, R26 physical validation, R22 moving roots/evaporation and R12 storage. |
| Regional job interface | `generator_upgrade_r31/region.py` | Deliberately re-exports R30 `recipes` and `iter_region`. This interface does not acquire a new topography namespace merely because its folder is R31. |
| Execution, caching and worker lifecycle | `generator_runtime_r12/{__init__,executor,store,parallel}.py` | R31 also retains the R24 executor through predecessor orchestration. Inspect `generator_upgrade_r24/executor.py` when changing connected scheduling; do not assume R12's executor is the only active executor. |
| Native shared history and session controls | `native_terrain_r5/{history,session,integrity,provenance}.py` | Retains R4 session/integrity and proposal policy, R3 ownership/codec/compression machinery, and R2 numerical evolution. R5 is not the whole generator and not a new solver-speed claim. |
| Native step CLI and interval proposal | `native_terrain_r5/runner.py`, `native_terrain_r4/scheduling.py` | The R5 CLI adapts R4 `step`; its private proposal wrapper changes latest-row retrieval, not the accepted numerical policy. |
| Native arithmetic or evolution | `native_terrain_r2/{numerics,evolve}.py` | Read R1 dependencies and the R3–R5 adapters before touching retained numerical code. Treat numerical policy and provenance changes as explicit successors, not incidental cleanups. |
| Retained shared generator | Repository path `shared_generator/engine/` | A separate retained tree. Do not assume a change to native R5 also updates these builders or their launch controls. |

The R31 topography operation set is exactly `terrain_from_seed`, `terrain_advance`,
`terrain_view`, `moving_roots`, `geological_terrain_step`, `surface_water_route`.
The existing R31 tests check those six registrations change and 26 others retain
identity. That is a test expectation, not a claim that tests ran in this handover.

## 2. The non-obvious injected implementations

| Adapter seam | What is actually substituted | Review requirement |
| --- | --- | --- |
| R31 `registry.run` → R28 `preflight.clone(prior.run, ...)` | R30's globals receive R31 provenance, registrations, ownership and worker callbacks. | Check serial/worker paths, producer identity, cleanup and warm reuse together. |
| R31 `topography._terrain_step` | Clones geology `consumer.terrain_step` with `terrain=kernels`. | Do not change only the visible consumer while assuming its original terrain global is active. |
| R31 `Adapter._moving_module` → R24 `inner._module` | Copies R22 module-owned functions into a private module; injects topography transport and a provenance wrapper. | Preserve private recursion, copied globals, verification and override ownership. Do not patch the original imported module. |
| R31 private authenticated `terrain_view` validation | Clones `terrain.view` with `verify=accepted` inside a freshly authenticated callback. | This narrower verifier is not a public replacement for full native verification. Preserve its identity/input boundary. |
| R5 `session` → R3 `_adapt` | R2 numerical validation/sealing/advance and R4 session methods receive R5 provenance, schema, history, validators and copy behaviour. | Read the function's original globals and every override; a source file alone does not show the effective implementation. |
| R5 `provenance.chunks` | Retains R3 streaming logic with the R5 `History` class. | Preserve logical encoding and the distinct location-independent history commitment. |
| R5 `integrity` | Retains R4 verification/commitment with R5 history and source checks. | Preserve explicit full-verification forwarding and distinguish scientific hash from storage commitment. |
| R5 `runner` | Retains R4 step/proposal code with R5 session/provenance and shared-history latest-row access. | Preserve proposal defaults, acceptance policy and no-unrequested-run boundaries. |

### Three helpers that must not be treated as interchangeable

- `generator_upgrade_r28/preflight.clone`: copies globals, code, positional
  defaults and closure; separately copies keyword-only defaults.
- `generator_upgrade_r24/inner._function` and `_module`: rebind module-owned
  functions together to preserve private recursion. `_function` retains
  keyword-only defaults, annotations, qualified name and documentation; some
  metadata objects are shared, not deep-copied.
- `native_terrain_r3/session._adapt`: copies globals, code, positional defaults
  and closure, but **does not copy keyword-only defaults**. R5 explicitly forwards
  `full` in `integrity.verify_history` and restores proposal defaults in `runner`.
  Do not remove these compensations or replace this retained helper as a casual fix.

The static inventory records selected direct imports, adapter call targets,
keyword overrides and the small helper/default contracts. It is a review tripwire,
not a proof of semantics or a complete transitive dependency scanner.

## 3. Choose focused tests by the changed boundary

These are **paths to inspect**, not commands authorising execution. Existing
source-capture loaders, native libraries and input bindings can prevent them from
running in the public source-only environment. Do not weaken those checks.

| Changed boundary | Existing focused evidence to inspect/run when authorised and compatible |
| --- | --- |
| R31 registrations, worker bindings or connected terrain | `test_r31_registry.py`; relevant predecessor `test_r30_registry.py`, `test_r28_registry.py` |
| Clone/preflight or copied-module behaviour | `test_r28_preflight.py`, `test_r24_inner.py`; affected route's integration test |
| Connected executor | `test_r24_executor.py`; R12 `test_executor.py`, `test_parallel.py` only where affected |
| Cache identity/authentication | `generator_runtime_r12/test_store.py`; affected registry/executor tests |
| R5 shared frame ownership | `native_terrain_r5/test_history.py` and `test_session.py` |
| R5 integrity/proposal adapter | R5 session/history tests plus R4 `test_integrity.py`, `test_scheduling.py`, `test_session.py` |
| Retained archive/codec behaviour | R3 `test_session.py`, `test_compression.py`; relevant R4/R5 continuation tests |
| Numerical representation or migration | R2 `test_numerics.py`, `test_evolve.py`, `test_migration.py`; affected successor continuation tests |

For a future adapter simplification, require focused evidence for keyword-only
arguments, closure/default handling, private recursion, non-mutation of parents,
source drift refusal and relevant restart/cache paths. Static AST agreement alone
cannot establish any of these runtime behaviours.

## 4. Migration and source-identity boundaries

- R31 topography source changes require explicit new recipe identities for the
  changed operations. Other producers are not automatically re-versioned.
  Older terrain envelopes require the relevant explicit native import; a copied
  JSON file with a changed hash is not a migration.
- Native R3 `import_legacy`, R4 `import_r3` and R5 `import_r4` are explicit
  predecessor transitions. Read each implementation and prerequisites. Their
  existence does not authorise migrating a user's saved controls.
- R4 changes history commitment/proposal meaning. Do not infer full historical
  body or long-run trajectory equality from bounded active-state/receipt parity.
- R5 `fork` creates a control sharing immutable objects; `export` creates a separate
  self-contained store/control directory. Neither supplies missing runtime/source
  dependencies. Do not treat a branch as an independent backup or delete its store.
- The source-only export lacks `engineering/outputs/native-terrain-r1/checkpoint_io.py`
  and the original pinned Windows codec/runtime. No automatic installation,
  placeholder codec, tolerance relaxation or silent rebind is acceptable.
- Sanitised public sources cannot be labelled byte-identical to historical private
  execution bindings. A portability implementation needs its own reviewed identity
  and focused evidence. Code approval does not grant scientific or canon acceptance.

## 5. Source-only check and change procedure

From the repository root, Python 3.10 or later, standard library only:

```text
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
```

These commands parse selected source with `ast`; they never import Atlas, load
libraries/checkpoints or start simulation. The checker also verifies named test
and dependency files exist. It neither modifies files nor regenerates its map.
It exits non-zero for missing files, changed direct imports, changed recognised
adapter calls or changed small helper/default contracts.

It does **not** prove source authenticity, validate the full import graph, detect
all behavioural edits or determine whether an arbitrary new helper is an adapter.
A coordinated change to code and inventory can pass. Runtime hash checks remain
independent and mandatory. No CI workflow or branch protection is installed by
this change; run the commands explicitly.

When an intended change trips the check: inspect the changed implementation,
update this explanation and the affected tests, then review the corresponding
entry in `tools/coding_safety_manifest.json`. Record the new review basis when
changing that inventory. Do not regenerate every entry or erase a failure simply
to get green output. Start a separate compatibility/versioned change before
simplifying source-bound adapters; this guide does not refactor them.

A completion report should contain the changed files, source/runtime-binding
impact, exact checks actually run and their outcome, and untested dependencies.
Keep the report bounded to the request. No repeated broad audit or coordination
acknowledgement loop is needed.
