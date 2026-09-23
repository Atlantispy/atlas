# W06 Step 5 — recoverable execution and combined acceptance

22 September 2026. WORKING NON-CANON. **PASS_SUPPORTED_W06_WORKFLOW.**

## Result

`PreparedW06Workflow` now executes an explicit requested-output schedule for
constant spreading/cooling, changing motion/ownership histories and inherited-margin
cooling/support. It preserves original typed fields, finite material/heat/water
accounts and geological/thermal provenance. Each route is a separate physical
scenario, not a newly coupled ocean-continent domain.

The existing ArrayStore atomically publishes one complete checkpoint per output.
Source/runtime, preparation, policy, entire schedule, output index and parent
lineage are bound to the key. Reopening restores the last accepted output without
rerunning completed thermal integration. Corruption and missing predecessor
manifests fail visibly. No automatic repinning or silent cache repair was added.

Ocean snapshots omit geometry and provenance reconstructible from the source-bound
recipe; margin snapshots retain both temperature means and small temperature
changes to avoid cancellation on restore. Chunk deduplication and lossless
Blosc2-backed Zstd are reused, not reimplemented. Only the newest output is retained
by the runner, and all transient/retained allowances respect its selected shared
budget. Integration review caught and corrected propagation of a stricter child
budget into ocean snapshot packing before the combined profile ran.

The [API and recovery contract](../docs/W06_WORKFLOW.md) documents ownership and
limits. Equations, physical parameters, numerical tolerances and the frozen design
were not changed.

## Matched timing

[Machine-readable measurements](w06-workflow-timing.json): Windows, Python
3.12.14, one numerical thread, three rotating-order samples per mode. Ocean
cases contain 4,000 cells; inherited margin has two actual source layers. Each
sequence has four requested outputs.

Every timed mode starts a fresh source context, physical preparation and workflow;
execution and closure are included. Durable modes additionally include store
opening/closing and the inventory query. Exact typed-state/byte comparisons,
benchmark source hashing and process launch are outside the timer. Warm is a
reopened SQLite connection, not an operating-system cold-cache test.

| Route | No-store calculation, s | First calculation + save, s | Verified warm reopen, s | Warm saving vs no-store | Partial continuation, s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Constant ocean | 1.220668 | 1.683468 | 0.520681 | 0.699987 / 57.34% | 0.919054 |
| Changing-history ocean | 0.981009 | 1.341096 | 0.396041 | 0.584968 / 59.63% | 0.705706 |
| Inherited margin | 0.989721 | 1.099665 | 0.411937 | 0.577783 / 58.38% | 0.602819 |

- Constant ocean: first publication adds 0.462800 s / 37.91%. Warm versus full compute-and-publish saves 1.162787 s / 69.07%. Partial continuation takes 0.764414 s less / 45.41% less than a full cold run.
- Changing-history ocean: first publication adds 0.360087 s / 36.71%. Warm versus full compute-and-publish saves 0.945055 s / 70.47%. Partial continuation takes 0.635390 s less / 47.38% less than a full cold run.
- Inherited margin: first publication adds 0.109944 s / 11.11%. Warm versus full compute-and-publish saves 0.687727 s / 62.54%. Partial continuation takes 0.496845 s less / 45.18% less than a full cold run.

Partial timings start with outputs 0–2 already accepted, restore output 2 and
calculate/save output 3. Prefix computation and backup seeding are excluded. That
is a shorter remaining workload, not a faster algorithm or a claim that interruption
reduces total work. First-time storage overhead is real; use the no-store mode when
durability/reuse is unnecessary. These are measured workflow savings, not new
physical-kernel or whole-generator speedups, and are not additive with Step 3/4
measurements.

All 36 timed results exactly matched their route's no-store complete typed-state,
array-byte, account and provenance signature. All 97 benchmark source bindings
matched before/after. The frozen requested times and full raw samples are retained
in the JSON; no benchmark rerun was used to select better numbers.

| Route | Snapshots | Encoded payload, bytes | Database, bytes | Peak accounted allowance, bytes |
| --- | ---: | ---: | ---: | ---: |
| Constant ocean | 4 | 485,901 | 548,864 | 48,195,696 |
| Changing-history ocean | 4 | 503,118 | 565,248 | 48,236,200 |
| Inherited margin | 4 | 168 | 32,768 | 34,345,687 |

All reservations released to zero within the 128 MiB shared admission, including
a 16 MiB caller allowance. This is not a process-RSS cap. Storage uses Zstd level 1,
byte shuffle and palettes where suitable, with no dictionary or decoded cache.
The optional standalone `zstandard` package is not installed; the actual codec is
provided by the existing Blosc2 dependency.

## Verification performed

- Selected `--w06` profile: **20 PASS, zero failures/errors/skips, 44.148151 s**,
  with unchanged source inventory. Eight grouped workflow tests, nine shared
  live-source identity tests and three profile/status-contract tests. Full
  [acceptance record](w06-workflow-acceptance.json).
- Workflow coverage: every requested state on all three routes, exact restart and
  fresh-child-process continuation, unknown inherited cooling history/nonzero
  source epoch, independent endpoint thermal/first-exit references, zero completed
  thermal calls on warm load, unchanged future-event provenance, finite stocks,
  pre-commit rollback and mid-evolution cancellation, corruption and consistently
  rehashed foreign state, missing history, changed source/schedule/policy,
  bounded decoding, 256-request limit, resource and borrowed-object lifetimes.
- Five focused ocean codec checks have passing evidence. Initial five passed in
  3.565 s; after correcting child-budget propagation, only the affected budget/
  cancellation/history-corruption method was rerun, passing in 0.383 s. Final codec
  SHA256 `8e35ee6c7c8c26fb0278797b60b796c9c52e32455ad23aa941bb6ff491d2ecb8`.
- Existing numerical evidence was reused after 94 recorded Step 3/4 source/case/
  test bindings matched live bytes, excluding the intentionally changed public
  exports and execution-identity registry. No repeated three-grid, quadrature or
  partition sweep. Current shared identity checks cover the registration changes.
- Required static source checker: 13 maps / 41 paths PASS. Safety suite: 30 PASS,
  one Windows symlink-capability skip, 31 reported in 0.107 s. That skip is outside
  the strict 20-test W06 acceptance profile.
- Scoped diff/new-file whitespace, JSON and local document-link checks complete
  the delivery checks; no unrelated runtime suite or large simulation.

Commands (repository root, installed scientific environment; numeric thread
environment fixed to one):

```text
python -I -B tectonics/verify.py --w06
python -B tectonics/tools/benchmark_w06_workflow.py --output OUTPUT.json
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
```

The original selected-profile stdout/stderr and process metadata are retained in
the Engineering task's `w06-check/`; the original benchmark is
`W06_STEP5_BENCHMARK.json`. Repository copies above are the portable evidence.

This completes the scoped W06 implementation sequence. The independently bound
age/depth/heat-flow observational challenge remains separate; R4.4 remains held.
Windows execution is measured here, not a new Linux or physical power-cut test.
Existing SQLite/filesystem guarantees are not extended to arbitrary sync/network
behaviour. Next implementation: W07's selected regional mechanical backend.

## Existing software and research checked

- [ASPECT 3.0.0 checkpoint/restart documentation](https://aspect-documentation.readthedocs.io/en/v3.0.0/user/run-aspect/checkpoint-restart.html):
  full-state continuation and changed-parameter compatibility warnings informed
  exact source/recipe binding. Documentation read; ASPECT not executed.
- [SQLite atomic commit](https://www.sqlite.org/atomiccommit.html): selected
  introduction and recovery/testing discussion informed atomic publication and
  the in-transaction interruption check. Existing ArrayStore was reused.
- [Official pyGPlates inherited thickness/subsidence example](https://www.gplates.org/docs/pygplates/sample-code/pygplates_reconstruct_crustal_thickness_and_tectonic_subsidence):
  selected Details informed explicit initial-history and retained-inventory
  handling. Example conventions checked, not used as a numerical oracle.

Existing Atlas W05 workflow, ArrayStore, shared execution identity and W06 source
were inspected for integration. Earlier TracTec/thermal papers remain the physical
basis; no new physics paper or geodynamic-package execution is claimed for this
storage/recovery step.
