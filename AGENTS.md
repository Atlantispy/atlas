# Atlas: coding instructions

Atlas is vibe-coded: OpenAI ChatGPT/Codex and Anthropic Claude Code write code under the owner's
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

## Keep the scientific explanation current

As part of each completed method or integration change, update the affected
reader chapter under `tectonics/docs/how-it-works/` and its specialist method
document where needed. Explain what happens, inputs/outputs, the papers/software
actually consulted and what the checks establish. Update the guide index and
README links when coverage changes; keep delivery status in `docs/CURRENT_STATE.md`.
Arrange the reader guide in generation/dependency order, with explicit feedback
loops and optional routes, not implementation dates or W/I package numbering.
Do not duplicate a progress log or imply a cited source was newly read or benchmarked.
Finish source-bound method documentation before capturing new evidence; never
rewrite an old receipt for a documentation update. Documentation-only edits get
focused content/link and required static checks, not scientific reruns.

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

## Keep documentation, experiments and checks bounded

- Maintain one current home for each status, method and decision. Update existing
  owner documents in place, link to detail and use Git history for ordinary prior
  versions. Add a Markdown file only for a distinct required purpose or consumer
  that cannot fit an existing section; name that purpose in the existing brief.
  Routine progress does not need dated update files or parallel ledgers.
- Retain files for an actual selected import/constructor, useful regression or
  negative control, supported claim or recovery need. Age, revision number, an old
  reference, inventory membership or historical hash alone proves neither need nor
  disposability. When replacing material, migrate useful content and consumers,
  repair links/current inventories and remove authorised obsolete members together.
  Protected exclusions must name their dependency, owner and unresolved question.
- Keep disposable probes, invocation logs and trial copies outside tracked or
  source-bound packages unless a selected consumer requires them. At completion,
  remove owned disposable material after retaining the minimal useful result,
  failure cause or regression in its existing home. Do not preserve whole failed
  attempt trees, one report per retry, default second backups or extra archives.
- Share source and fixtures only when import, constructor, frozen-source and
  qualification contracts permit it. Identical bytes do not make contexts
  interchangeable. Preserve required originals until an authorised successor
  migrates their consumers; preserve current integrity/recovery identities. Do not
  create historical hash catalogues or require obsolete files merely because a
  test asserts their presence or old progress wording.
- Historical archives must have no current-run input, selection, dispatch,
  recovery or runtime role. Current-run storage has its own database, code,
  configuration and lifecycle. Archive cleanup must not access or alter current
  runs/stores; an extra copy needs a concrete recovery purpose.
- Reuse adequate checks while candidate, inputs, tools and configuration remain
  valid. Rerun for relevant changes, unresolved failure, missing coverage or
  mandatory freshness/independence. Combine demonstrated same-context duplication;
  retain distinct fixtures/trust boundaries and required numerical, integrity,
  identity, privacy, resource and recovery checks. Maintain one structured
  definition per distinct check in [the existing inventory](tools/verification-checks.json),
  with results at their existing owner; classification never disables a check.
  Follow the [focused check procedure](docs/CODING_SAFETY.md#5-source-only-check-and-change-procedure).
- Close the existing owner record and resolve obsolete pending-removal references
  in the same change. These rules create no recurring audit, cleanup service,
  monitor, approval chain or authority to touch another owner's work or lift holds.

## Public development route

For independent component development, read `docs/INDEPENDENT_DEVELOPMENT.md`.
`tools/develop.py` provides offline bootstrap, explicit NEW public bindings,
focused `runtime`/`numerics`/`tooling` profiles and an integer-graph smoke fixture.
`all-public` does not mean all Atlas tests. Original R11 seals and native R5
checkpoint/runtime dependencies remain unavailable; never invent them. After a
reviewed source change, capture a new record rather than updating an old binding.
Do not commit `.atlas-dev/` (local paths, environment and cache state).

## Local review tools

Where a machine provides local review tools (see the untracked `CLAUDE.local.md`), use
them on relevant work: check-only lint comparing base and candidate with the same
executable and rules, reporting only introduced findings; independent maths in an
environment separate from the science environment; symbol navigation where available.
Never auto-fix or reformat source, never install into the science environment, and treat
results as review aids, not evidence. Their absence is not a failure.

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
