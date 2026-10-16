# Development speed tools

Atlas is vibe-coded with OpenAI ChatGPT/Codex and Anthropic Claude Code under the owner's direction.
**WORKING NON-CANON.** These tools make development checks faster. None of them is a gate, a scientific acceptance
or a replacement for `tectonics/verify.py`; they never relax a test, a tolerance or a refusal.

| Tool | Purpose |
| --- | --- |
| `tectonics/verify.py --quick` | The full or a focused selection without the measured slow tests (`SLOW_TESTS`). |
| `tools/run_tests_parallel.py` | Run unittest suites in parallel worker processes, with per-test outcomes and durations. |
| `tools/test_impact.py` | Record what each test unit executes and opens; select the tests a change can affect. |
| `tools/verify_candidate.py` | Verify a patch set in a scratch clone: trees, bytes, static checks and one test tier. |

All four use the standard library only. Run them with the tested tectonics interpreter, passed explicitly
(`--python`); no interpreter or private path is written into tracked files. Keep their outputs (run folders, maps,
summaries) outside tracked files, for example under the ignored `.atlas-dev/`.

## When the full gate is still required

Run the unchanged full gate, `python -I -B tectonics/verify.py` (or the profile a stage names), before a result is
reported as passing, before an evidence receipt is captured and before a change is accepted. A quick, focused,
parallel or impact-selected run is evidence about the tests it ran, and only those. In particular:

- `--quick` omits real tests; its JSON reports `PASS_QUICK_SELECTION_ONLY`, never the gate's status.
- A parallel run reports the same per-test outcomes as a serial run of the same selection (checked once, below), but
  it is not `verify.py`: it does not write verify's source-inventory record.
- An impact selection rests on stated assumptions (below). Use it to choose what to run while iterating, then run the
  full gate once on the final candidate.

## Test tiers: `SLOW_TESTS` and `--quick`

`tectonics/verify.py` keeps every test in full discovery. `SLOW_TESTS` names measured slow tests by exact test ID, or
by class ID where the class fixture dominates. `--quick` omits them, either alone (the full discovery, native checks
included) or with one focused profile:

```text
python -I -B tectonics/verify.py --quick
python -I -B tectonics/verify.py --quick --i02
```

`--quick` refuses to combine with `--core`, `--native`, `--acceptance`, `--w01`, `--w04`, `--w05`, `--w06` and
`--w10`; acceptance selections are exact and stay whole. A registry entry whose module the selection covers must name
a discovered test or class exactly, or the run refuses as stale; an entry for a module outside the selection is not
judged. An empty quick partition refuses. The full run, `_checks_passed` (no skips) and the local-bytecode refusal are
unchanged. `--i02-quick` keeps its own meaning (the four timing-harness tests only).
The verifier requires strict execution before running a suite, including before the W10 delegation; a live
packaged release mode cannot produce verification evidence.
When combined with `--quick`, both I02 partitions validate registry entries against the original complete I02
discovery, then omit slow tests only from the requested partition.

The registry was measured at `30a79e6`: wall time per test, or per class fixture, of at least
`SLOW_TEST_THRESHOLD_SECONDS` (30 s) in a full parallel run (14 workers on 16 logical CPUs, so under load). Add or
remove entries only from a new measurement, recording the run; never to make a run pass.
The additional `test_i04_controls.ResolvedCaseB` entry uses the ED-7 measurement of 2760.8 s on 5 October 2026
for its single-test class. It stays in default/full discovery without an environment-controlled skip. Other I04
controls need recorded per-test or per-class timings before they can enter this registry; a whole-module duration
does not establish those individual durations.

## `run_tests_parallel.py`

```text
python -B tools/run_tests_parallel.py --root . --python <tested python> --pattern "test_i0[12]_*.py"
python -B tools/run_tests_parallel.py --root . --python <tested python> --serial --pattern "test_i0[12]_*.py"
python -B tools/run_tests_parallel.py --compare RUN_A/summary.json RUN_B/summary.json
```

- **Default selection.** Without `--pattern`, a run uses the tree's full `verify.py` discovery. That is its
  `FULL_PATTERNS`, `test_*.py` and `check_native_transport.py`; the same two are used for a tree whose `verify.py`
  does not name them. A default run is therefore never narrower than the full gate's discovery.
- **Units.** A unit is a test class, or a whole module when it defines `setUpModule`, `tearDownModule` or
  `load_tests`, so fixtures keep their meaning. A unit never splits across processes. Units start longest first when
  `--durations` names an earlier `results.jsonl`.
- **Workers.** Each worker is a separate process of the tested interpreter with:
  - single-threaded BLAS/OpenMP (`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, ... = 1);
  - `PYTHONPATH` beginning with the selected `tectonics/src`, followed by the inherited entries (resolved before the
    worker changes directory);
  - its own short temporary folder beside the inherited one, because several tests budget Windows path lengths from
    it;
  - `PYTHONPYCACHEPREFIX` pointing at a cache outside `src` and `tests`. By default this is a new short folder,
    removed afterwards. A deep cache path plus a deep source path can exceed the Windows path limit, and then Python
    silently recompiles every module in every worker.

  The run refuses a cache inside `src` or `tests`, and fails if any local `.pyc` exists there at the end.
- **Serial group.** `--serial-unit ID` and `SERIAL_UNITS` in the tool run units after the parallel phase, one at a
  time, each in its own new process. One unit is registered: `test_regional_multigrid3d.MultigridPlanTests`. Its test
  `test_default_budget_admits_a_nine_cube_...` failed in 2 of 7 shared-worker full runs and passed in every other
  run, including alone on the same trees. Its outcome depends on which units ran earlier in the same process. The
  conventional serial order passes; the cause is not yet identified.
- **Reference.** `--serial` runs the whole selection in one process in discovery order: the conventional run that
  parallel outcomes are compared with.
- **Records.** Results stream to `RUN/results.jsonl` as units finish; `RUN/summary.json` is written atomically with
  per-test outcome, seconds and detail, per-unit wall time, counts, the omitted slow tests and the bytecode check.
  Subtests are recorded separately and their parent test is recorded as failed, errored or skipped accordingly. A
  worker that dies or exceeds `--unit-timeout` is reported for every test of its unit and replaced.
  Traced runs also retain source and runtime provenance before discovery and after execution. An impact map requires
  equal snapshots of the clean commit, tracked blobs, actual file hashes and worker runtime/import environment.
- **Exit code.** 0 only when nothing failed, errored or unexpectedly succeeded, every selected test has a result and
  no local bytecode exists. Skips are reported, not hidden; unlike `verify.py`, they do not fail the run.

`--quick` reads the tree's `SLOW_TESTS` (or `--slow-file`, a JSON object of ID to seconds) and refuses a stale entry
as `verify.py` does.

## `test_impact.py`

```text
python -B tools/test_impact.py record --root <clean checkout> --python <tested python> --map .atlas-dev/impact.json
python -B tools/test_impact.py select --map .atlas-dev/impact.json --root . --python <tested python> BASE HEAD
python -B tools/test_impact.py select --map .atlas-dev/impact.json --root . --python <tested python> --files PATH...
```

**Scope.** The map covers the tectonics suite (`tectonics/tests`, `test_*.py` and `check_native_transport.py`). A
changed test file elsewhere is reported as `outside_scope`, and a changed file that no recorded unit touched as
`untouched`: some other suite (for example the repository-root `tests/`) must cover those. `verify_candidate --tier
impact` runs the root suite in that case.

`record` runs every unit in its own fresh process from before the unit is loaded. It uses `sys.monitoring`, which
reports every code object that starts. Functions, methods, lambdas and generator expressions count as execution;
module and class bodies count as import. An audit hook records:

- byte reads by code;
- the sources of `shutil` copies, `sqlite3` connections and `ctypes` loads;
- directory listings;
- process starts.

The import system's own work is not counted: compiling a module it imports, and searching `sys.path`. Numba dispatchers
that compiled are found afterwards by a scan of live objects. The run must be a clean commit. The map records:

- that commit and every tracked file's blob;
- the AST-detected numba files and code-inspecting functions;
- a fingerprint: the interpreter, installed distributions, and the `ATLAS_*`, `NUMBA_*` and `PYTHON*` environment.

`record --from-run RUN` rebuilds the map from a complete earlier traced run of the same clean commit. It preserves
that run's original provenance and refuses missing provenance, source drift, runtime/import-path changes or a narrowed
selection. A second source/runtime check covers map construction itself. Old traced runs without these snapshots
must be recorded again; they cannot be relabelled with the present commit or environment. The v4 map schema makes
this boundary explicit. Outputs must be ignored or outside the repository so they do not dirty the source snapshot.
Inherited `PYTHONPATH` entries are part of the observed worker import paths, including their order. A change selects
all tests. The runner-controlled source/test paths are represented relative to the root so equivalent clean clones
can reuse a map. This records the configured import environment, not arbitrary external file bytes; changing an
external dependency in place still requires a fresh map.

`select` is conservative: a false positive is allowed, a false negative is not. The full rules are in the tool's
docstring. In short:

- **Everything.** Added, deleted, renamed or type-changed files, `.gitattributes`, unknown files, unopened data files,
  a map that differs from BASE in membership, and a different fingerprint all select every test. A file whose content
  differs between the map and BASE is treated as structurally changed.
- **Body-only changes.** A change confined to function bodies selects:
  - the units that ran code of the file, read it or listed its folder;
  - code-inspecting units that imported it.
  It counts as body-only only if it keeps docstrings, keeps generator and coroutine status, and still compiles under
  the tested interpreter with warnings as errors.
- **Other changes.** Any other change also selects the units that imported the file, with their whole modules.
- **Numba files.** These select every unit that compiled a kernel.
- **Always selected.** Units that started a process, skipped or failed a test, or have no trace.
- **Test files.** A changed test file of the suite selects its whole module.

`--files` names working-tree changes against the root's HEAD and applies the same rules.

**Assumptions.**

- Tests are deterministic for a given tree and fingerprint. Re-record after a base commit moves.
- A unit's outcome does not depend on units run before it in the same process. The map is recorded one unit per
  process, and `verify_candidate` runs a selection the same way (`--fresh`).
- A test observes a repository file only in one of these ways:
  - by running its code, importing it, reading its bytes or listing its folder;
  - for units that ran code-inspecting functions such as the identity guard, by inspecting the code objects or line
    numbers of modules it imported.
- A file's existence is covered by the added/deleted rule.

These assumptions were attacked by an independent adversarial review. The handoff lists its findings and what each
change did about them.

**Why package changes select many tests.** Two mechanisms make this a real dependency, not a tracing artefact:

- `ExecutionContext` re-reads every package source file on every verify, so every unit that creates one depends on
  every package source byte.
- Several modules hash their own source when imported.

## `verify_candidate.py`

```text
python -B tools/verify_candidate.py --repo <checkout to clone> --base 30a79e6 \
    --chain first.patch second.patch --combined combined.patch --expect-tree 99878a45 \
    --python <tested python> --tier quick --summary .atlas-dev/verify-summary.json
```

It clones `--repo` without hard links into a new short temporary folder (never inside the repository), applies the
chain and the combined patch in two working trees, and records each step in the summary JSON:

1. equal tree hashes (and `--expect-tree`);
2. no CR byte in a patch or a changed file; patch paths relative and outside `.atlas-dev/`; the combined patch names
   exactly the chain's changed paths; optional `--forbid-paths` and `--expect-paths` lists;
3. `check_coding_safety`, `check_public_paths`, `check_current_evidence`, their tests and the default
   `check_before_commit`, in the combined tree;
4. one tier through `run_tests_parallel.py`: `quick`, `full`, `impact` or `none`.
   - `--slow-file` supplies a registry when the candidate tree has none.
   - `impact` needs `--impact-map`. It commits the candidate inside the scratch clone, selects BASE..HEAD, and runs
     the selection one unit per process. It also runs the root `tests/` suite when a change lies outside what the
     recorded suite covers.

The exit code is 0 only when every requested step passes. During execution the summary has `completed: false` and
`passed: false`; an interrupted run cannot leave a green receipt. Missing required tier arguments refuse before a
scratch run is created. A completed pass is evidence for those commands only; even the full parallel tier is not the
`verify.py` gate and is not scientific acceptance.

## Measured at `30a79e6`

These are single runs on one Windows machine (16 logical CPUs, 14 workers, the pinned tested interpreter). They
describe that run, not a performance guarantee.

| Run | Tests | Serial | Parallel | Per-test outcomes |
| --- | --- | --- | --- | --- |
| I01/I02 (`test_i0[12]_*.py`) | 759 | 268.3 s | 103.3 s | identical (759 passed) |
| I03 (`test_i03_*.py`) | 325 | 190.2 s | 34.4 s | identical (323 passed, 2 expected failures) |
| full suite (`test_*.py`, `check_native_transport.py`) | 5356 | not run | 476.1 s | 17 host skips, 2 expected failures, no failures |

The full suite was also run one unit per fresh process, while recording the impact map. Its per-test outcomes equal
the shared-worker run's. Seven later shared-worker full runs, on mutated trees, exposed the one order-dependent unit
now in the serial group.

The I01/I02 and I03 timings predate the short default bytecode cache. Their parallel workers recompiled every package
module, so the parallel times are, if anything, pessimistic.

`SLOW_TESTS` at a 30 s threshold has 22 entries (37 tests, about 19% of the measured unit-seconds). A 60 s threshold
would have had 5 entries (about 6%).

Impact selection sizes from the map recorded at `30a79e6` (602 units, 5356 tests):

| Edit | Units | Tests |
| --- | --- | --- |
| `integration_transfer.py`, a function body | 293 | 2782 |
| `integration_transfer.py`, a module constant | 401 | 3881 |
| `spherical_atlas.py`, a function body | 344 | 3305 |
| `spherical_atlas.py`, a module constant | 506 | 4805 |
| `plate_cooling.py`, a function body | 236 | 2637 |
| `plate_cooling.py`, a module constant | 506 | 4805 |
| `test_i03_events.py`, a test body | 75 | 930 |
| `tectonics/tools/i02_column_workflow.py`, a function body | 77 | 930 |

71 units (907 tests) are always selected because they start processes or skip tests. Package edits select many tests
for the two reasons given under `test_impact.py` above.

Mutation check: seven injected faults, each followed by one full-suite run. The faults were three package function
bodies, a package constant, a numba kernel, a test helper and a data file. Every test whose outcome changed under
fresh-per-unit execution was selected. The one exception seen in shared-worker runs was the order-dependent unit now in
the serial group. This is evidence for the rules above, not a proof.
