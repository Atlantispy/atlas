# Atlas: coding instructions

Atlas is vibe-coded: OpenAI ChatGPT/Codex writes the code under the owner's
requirements, decisions and review. Status is **WORKING NON-CANON**. Passing tests,
code review and scientific acceptance are separate outcomes.

## Start with the smallest relevant context

1. Read `README.md`, `docs/CURRENT_STATE.md`, then the relevant section of
   `docs/CODING_SAFETY.md`. Do not repeat a broad audit as a setup step.
2. Identify the requested route, its retained implementation and injected
   dependencies before editing. R31 is the wider integration; runtime R12 provides
   infrastructure; native terrain R5 is only the bounded storage/session route.
3. Inspect only the affected code, retained imports and named tests. Batch
   independent reads. Reuse verified evidence unless the source changed.

## Change boundaries

- Make one scoped change using the owner's requested delivery route. Direct-to-main
  updates require focused checks and a non-forced update against the latest state;
  otherwise use a review branch. Preserve unrelated work. Do not synchronise or
  alter the original Windows workspace without instruction.
- Keep source-only guides/tools outside `engineering/work/` and
  `shared_generator/`. Adding a Python file inside a source-bound package can
  change its identity even without editing an existing function.
- Do not delete predecessors because a higher revision exists. Follow the active
  route map, not numerical folder ordering.
- Never bypass hash/source checks, silently repin checkpoints, relax acceptance
  tolerances or raise the 256 accepted-step ceiling to obtain a pass.
- Sanitised public bytes do not authenticate historical runs. The original codec,
  pinned libraries, private inputs and checkpoints are not supplied here.
- For R5 backup/recovery, read `docs/R5_OPERATIONS.md`; tools stay outside the
  source-bound packages. Never treat a staged byte recovery as a native restart.
- Shared history stores are dependencies, not disposable caches. No cleanup,
  checkpoint migration, simulation or benchmark is implied by a coding request.
- Do not publish personal information, credentials, private paths or coordination
  records. Preserve the approved public worldbuilding material and AI disclosure.

## Public development route

For independent component development, read `docs/INDEPENDENT_DEVELOPMENT.md`.
`tools/develop.py` provides offline bootstrap, explicit NEW public bindings,
focused `runtime`/`numerics`/`tooling` profiles and an integer-graph smoke fixture.
`all-public` does not mean all Atlas tests. Original R11 seals and native R5
checkpoint/runtime dependencies remain unavailable; never invent them. After a
reviewed source change, capture a new record rather than updating an old binding.
Do not commit `.atlas-dev/` (local paths, environment and cache state).

## Check and report

For source-only guidance/tool changes, run from the repository root:

```text
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
```

These are standard-library static checks, not generator tests. For generator
changes, use the focused tests listed in `docs/CODING_SAFETY.md` only after
confirming compatible dependencies and the requested execution scope. Never install
or rebind missing components just to make a test import.

An inventory mismatch requires review of the code, route map and test implications;
it is not permission to regenerate expectations blindly. Report what changed,
exact commands actually run, their results and anything not tested. Do not claim
runtime compatibility, physical acceptance or Windows integration from source checks.
