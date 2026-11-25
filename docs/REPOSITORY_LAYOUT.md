# Repository layout and retirement rules

Where code lives, how it moves and how old code leaves the tree. Status is **WORKING NON-CANON**: this is
the target, reached in steps; most of it does not exist yet. Read it with [AGENTS.md](../AGENTS.md) and the
[coding-safety map](CODING_SAFETY.md), which keep authority over the active route.

## Target layout

```
atlas/
  README.md, AGENTS.md, CLAUDE.md, LICENSE*   unchanged
  docs/                programme-wide: roadmap, state, module scopes, contracts
  shared/              atlas_shared, with pinned gmpy2 and an optional psutil acceptance extra
    pyproject.toml
    src/atlas_shared/
      machine/         resource monitor and start gate
      formulas/        sphere, cooling, interval and summation formulas used by more than one module
      execution/       kernel executor, rolling schedule, worker owner and start-up
      storage/         codecs, compact stores, retained caches, captures, atomic write, file digests
      reuse/           pure-kernel cache engine, timing memory
      exact/           exact arithmetic backend, filtered predicates
    tests/             one focused test file per subpackage
    docs/              one page per subpackage: what it is, who calls it
  tectonics/           src, tests, tools, docs, cases, evidence, reference_data
  <module>/            each later module, named after its science (hydrology/, not c04/)
  tools/               repository-wide tools; tools/runs/ later holds the run launcher and queue
  tests/               tests of the repository-wide tools
  development/, desktop/                  unchanged
  engineering/work/, shared_generator/    frozen: no new files; they shrink only by retirement
```

## Rules

- **Modules are named after their science.** The category number goes in the module's README.
- **Modules never import each other's internals.** They exchange data through [`docs/contracts`](contracts/).
  Code that two modules need goes in `atlas_shared`.
- **`atlas_shared` never imports a module.** Its identity is pinned on its own, and each module's execution
  identity includes the `atlas_shared` digest, so a change to shared code reruns only the steps that use it.
  How that digest enters the identity is designed and reviewed before any file moves into `shared/`.
- **`atlas_shared` adds no dependency** beyond the libraries already pinned in the science environment.
- **No revision suffixes (`_r2`, `_v3`) in new names.** Git keeps the revisions. A replacement removes the
  copy it replaces in the same landing.

## Module skeleton

Every new module starts with this; tectonics moves to it in a later rename-only landing.

```
<module>/
  README.md, pyproject.toml, LICENSE, THIRD_PARTY_NOTICES.md
  src/atlas_<module>/
    <stage>/           one subpackage per science stage, in generation order
    integration/       the module's own route: driver, evolution, state, clock, ledger
    codecs/            checkpoints and restores of the module's own objects
    _private/          build and heat machinery, grouped like the public part
  tests/               mirrors src: tests/<stage>/test_*.py; shared fixtures in tests/fixtures/
  tools/
    run/               launchers and drivers
    check/             inventories, identity and coverage checks
    report/            summaries and reader outputs
  cases/               inputs, one folder per case family
  reference_data/      third-party data, one folder per source
  docs/
    how-it-works/      the reader guide
    methods/           specialist method documents
  evidence/            sealed and append-only; new records in dated folders (evidence/YYYY-MM/)
```

Group by science stage, never by work-package number or revision. Tests mirror `src`, so a stage's focused
tests sit in one folder.

## Moving files

An unissued development copy resolves `atlas_shared` from `shared/src`.
Set `PYTHONPATH` to the absolute snapshot and shared source directories, with the snapshot
first. Use `;` between the paths on Windows and `:` on POSIX. The parallel test runner supplies
the snapshot path through `--src` and inherits the shared path. The isolated tests supply both
paths directly or use adjacent package copies. Snapshot CI stages the declared source with
the shared package beside it.

The issued snapshot stages `atlas_tectonics` and `atlas_shared` next to each other in its
selected native root. The application declaration lists all Python sources in both packages.
The driver lists the shared files in its pinned workspace source map and retains its
tectonics-only native source digest.

| Working snapshot path in sealed references | Shared source path |
| --- | --- |
| `atlas_tectonics/machine_resources_monitor.py` | `shared/src/atlas_shared/machine/resources_monitor.py` |
| `atlas_tectonics/resources_gate.py` | `shared/src/atlas_shared/machine/resources_gate.py` |
| `atlas_tectonics/exact_arithmetic.py` | `shared/src/atlas_shared/exact/exact_arithmetic.py` |

- **A move changes no value.** Byte-identical bodies use move records. The exact backend
  separates shared selection from tectonics activation and is issued as a removal and additions.
- **No re-export shims.** Every caller is repointed in the same landing.
- **One landing per batch, one repin per landing.** Only the steps whose identity moved are rerun, and the
  rerun must give identical results.
- **Before a move,** `git grep` every dotted module name and path, including tests, tools, pins, identity
  lists, inventories and manifests.
- **Sealed records are never edited or moved.** A record names paths that were correct at the commit it
  records; a path table maps each moved file to its new path and the commit that moved it.

## Retiring old code

For each candidate:

1. **Find every reference:** `git grep` the module or folder name across imports, tests, docs, pins,
   identity lists, inventories, manifests, evidence records and run tools.
2. **Check the current route.** The active route must not run it, and no pin or identity list still in use
   may name it. A sealed record that cites a file by working-tree path blocks its deletion until that wave is
   ruled on; a move is covered by the path table.
3. **Keep its checks.** A file that holds a check is retired only if the same check runs in its replacement.
   Removing a check outright is a separate, explicit decision.
4. **Retire it in one landing:** repoint every caller, then delete the file. Git history is the archive; the
   repository has no `archive/` folder.
5. **Run the checks:** `python -B tools/check_coding_safety.py`,
   `python -B -m unittest discover -s tests -p test_coding_safety.py -v`, `tests/test_public_paths.py`,
   and the focused tests of every repointed caller. If an identity moved, rerun only the affected steps.
6. **Record it:** one line per retirement in a retirement register (path, commit, replacement, reason).

Each retirement wave is one landing, reviewed and swept for redundant work before it is pushed.

**Never retire:**
- native terrain R5, while it is the bounded storage and session route;
- generator runtime R12, while it is the infrastructure for R31;
- anything a pinned checkpoint or a shared history store depends on: those stores are dependencies, not caches.

## Checks

After each step: the two coding-safety checks pass, `tests/test_public_paths.py` passes (it scans `shared/`
once that folder exists), and each moved file's focused tests pass. Once `shared/` exists, a grep confirms that
`atlas_shared` holds no `import atlas_<module>`, and each module's identity record names the `atlas_shared`
digest.
