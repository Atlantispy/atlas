# Optimisation programme: review snapshot (16 Oct 2026)

Status: WORKING NON-CANON. This is a review snapshot, not the landed route. It is not runnable as-is.

The aim is exact, certified interval generation that runs fast enough for an interactive generator: under five
minutes of wall time per interval on one Windows machine. Every change either keeps physical results bit-identical
or changes only digests under field parity. No tolerance is relaxed, and no resource guard or step ceiling is raised.

## Layout

| Folder | Contents |
|---|---|
| `composed-r2/src/atlas_tectonics/` | Full package copy of the integrated checkpoint build. Compare it against `tectonics/src/atlas_tectonics/`. |
| `composed-r2/helpers/` | Composition helpers: runtime transforms, compact store and restart, heat ledger tables, transfer and admission code, plus their tests and probes. |
| `composed-r2/composition.json` | The composition, with the pinned helper hashes. |
| `drivers/` | Fresh and prepared interval drivers, launchers, reopen tools and their tests. |
| `pending/<area>/` | Built candidates not yet in `composed-r2`: heat, pressure, kernels, storage, geometry. |
| `workbench/` | Earlier composition stages and probe/measurement scripts. |
| `docs/` | `COMPACT_EVERYWHERE_PLAN.md` (the 21-step plan) and the release-check and language plans. |
| `MANIFEST.json` | Each file's origin in the private engineering tree. |
| `SANITISED.md` | Files where local user paths or contact details were replaced. |
| `CHANGELOG.md` | What changed, with MEASURED and PROJECTED results. |
| `IN-PROGRESS.md` | Part-implemented work: state, location, what is left and the acceptance gate. |
| `plans/` | Finalised completion plans (01-25) and `INDEX.md` with dependencies and status. |

`pending/` and `workbench/` hold only files whose bytes differ from `composed-r2` and the repository package, and
each unique file appears once.

Plans 01 and 03 now include reviewed workbench successors and their focused test sources. The frozen composed-r2 helpers, live runtime and historical execution pins are unchanged. See the two plan completion sections for retained evidence and remaining launch/integration limits.

## Not included

- Private inputs, checkpoints, sealed interval stores, run records, receipts, logs, captured data and working notes.
- Helpers and drivers expect those inputs and the pinned identities. Sanitised files no longer match the hashes pinned
  in `composition.json` or in run records.
- Sanitised public bytes do not authenticate historical runs.

## Package overlay

Not applied. `composed-r2`'s package and the current `tectonics/src/atlas_tectonics/` differ in both directions.
`remake` has lines that `composed-r2` lacks (`integration_ledger`, `integration_transfer`, `reuse`), and some
I04/I05 modules differ. Reconcile them file by file before any landing.
