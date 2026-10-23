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
| `plans/` | Dated public projections (01-25) and `INDEX.md`; private execution plans retain authority. |

Source exports reuse existing identical public files where their import layout permits.
Plan02 retains a local `start_gate.py` copy because its preserved callers import it
beside them; its source map records that deliberate dependency copy.

Plans 01 and 03 now include reviewed workbench successors and their focused test sources. The frozen composed-r2 helpers, live runtime and historical execution pins are unchanged. See the two plan completion sections for retained evidence and remaining launch/integration limits.

Plan02's selected runner/caller generation and collar metadata repair are in
[`workbench/plan02/`](workbench/plan02/README.md), with an original/public digest
map and a synthetic public regression. The corresponding private repair is
installed; positive publication/reopen validation and end review remain
deferred. This snapshot does not apply an overlay to the main package.

Plan06's repaired exact wall twins, shared primitives, guarded hook and actual
assembly tools are in [workbench/plan06](workbench/plan06/README.md). Retained
technical checks passed, but the measured candidate was slower: D5 remains
disabled. Final selected Plan31/N9 binding and collective review remain open.

Plan04's installed comparator r24, dump r5, launcher and selected assembly
tooling are in [workbench/plan04](workbench/plan04/README.md), with original/public
hashes and test sources. Final Plan31 composition and authenticated field-proof
binding remain open; readiness guards stay false and collective review is deferred.

Plan05's observer ownership repair, complete correspondence verifier, native
launcher, physical-order repair and integrated q22 consumer are in
[workbench/plan05](workbench/plan05/README.md). The corrected private pair agrees
exactly. The scoped successor proof was subsequently accepted, and the
successor execution on the same q22 ticket completed all 11 arms with PASS.
[Plan12](plans/plan-12-heat-q22-abba.md) records the decision identities,
execution scope and retained historical failures. Historical q10 FAIL and
q32 NOT REPRODUCED remain preserved; the later selected source and scoped measurements are recorded below. This publication supplies source
and truthful scoped results, not a runnable private profile or main-package overlay.

The selected complete Plans10–12 private integration is exported in
[workbench/plans10-12](workbench/plans10-12/README.md), including its earlier
enabled source closure, original/public digest map and scoped retained results.
The new profile requires its own eligible ROOT; final interval testing remains held.

The successor [Plans13–14 source integration](workbench/plans13-14/README.md)
extends that selected closure with H3 certificate batches, Heat S1 finish reuse,
exact projection witnesses and fresh/prepared markers. It preserves earlier source
members and historical receipts, and includes the missing shared construction
dependencies. H3 remains candidate-only; final assembly and held runs remain later.

The [Plan16 geometry successor](workbench/plan16/README.md) extends the same
selected closure with authenticated parent measurements and conditional four/six
worker ceilings. Its sampled six-worker proof and native-entry preflight passed;
all native source is preserved. The public regression exercises the actual
helper functions on synthetic receipts without loading the private runtime.

The [Plan15 heat-worker successor](workbench/plan15/README.md) extends Plan16's
complete selection with the measured eight-worker candidate and independently
bound native observation. The [Plan17 source](workbench/plan17/README.md) adds
operational r7, retained r4 overrun sources and corrected method notes. Both
genuine geometry proofs and all nine comparisons are complete; the current selected
geometry sources are preserved with no native/runtime delta. Final programme
acceptance and held full intervals remain separate from this source publication.

The current [Plans19–20 source selection](workbench/plans19-20/README.md)
combines Plan19's two accepted geometry changes with Plan20's eight capture-helper
members, preserving the later heat and worker selection. It references existing
unchanged files instead of copying a second package. Plan19's declared private
validation is accepted; Plan20 A/B is accepted with the folded DLL binding still
pending. This is source integration on the review branch, not an executable
release, a main-package overlay or a new combined-runtime validation result.

The [Plan18 endpoint and retention source](workbench/plan18/README.md) adds
cross-support endpoint lookahead at one or two workers, plain support-header
retention, a measured 2,112 B ownership-carrier booking and a retained-handle
diagnostic to the compact route. Its exact endpoint-loop replay is a detached
measurement, not a whole-interval or integrated-runtime result. Larger-interval
retained capacity was still open in that predecessor selection; the combined
snapshot below supplies the subsequent partition-sized allowance.

The additive [Plan40A pressure examination and source successor](workbench/plan40/pressure/FINDINGS.md)
covers all ten arithmetic groups and selects the reviewed core plus G4.
Full-interval jets still supply curvature bounds; a separately funded midpoint
value calculation keeps the original rounding/constant semantics and full
fallback. Complete synthetic core calls save 27.35–61.94%, with a further small
marginal G4 gain. The [new explicit source map](workbench/plan40/pressure/implementation/SOURCE-MAP.json)
is connected through an [opt-in runtime constructor and entry](workbench/plan40/pressure/implementation/runtime/README.md)
to the existing fresh-profile loader and pressure worker. The constructor
preserves the frozen predecessor, external dependencies and live defaults.
Component measurements do not establish whole-IV performance or scientific acceptance.

The completed [combined source snapshot](workbench/combined-runtime-r1/README.md)
brings those selections together in 645 members, with 22 changed copies and 623
references to existing public files. It adds per-partition retained-carrier pools,
capture reservation/lifetime fixes and selected-source runner/bootstrap repairs.
Focused receiving, bootstrap, materialiser and prepared-entry fixture checks
support their stated seams. The prepared fixture does not execute a full prepared
workload. The qualified fold and installed-package delivery remain separate;
no application update, runtime admission, whole-interval performance or scientific
acceptance follows from source snapshot completion. Historical maps and component
measurements are retained unchanged.

## Not included

- Private inputs, checkpoints, sealed interval stores, run records, receipts, logs, captured data and working notes.
- Helpers and drivers expect those inputs and the pinned identities. Sanitised files no longer match the hashes pinned
  in `composition.json` or in run records.
- Sanitised public bytes do not authenticate historical runs.

## Package overlay

Not applied. `composed-r2`'s package and the current `tectonics/src/atlas_tectonics/` differ in both directions.
`remake` has lines that `composed-r2` lacks (`integration_ledger`, `integration_transfer`, `reuse`), and some
I04/I05 modules differ. Reconcile them file by file before any landing.

## Plan publication authority

The private execution plans and their bound owner evidence govern implementation,
run clearance and scientific acceptance. Public `plans/` files are dated,
sanitised projections for readers; they are not a second execution ledger.
Their differing bytes are expected after redaction, public explanation and
explicitly dated result updates. Git history retains earlier public versions.

Execution-contract or status corrections must first be reconciled against the
private owner record, then reflected in the affected public summary. Public-only
link, spelling and privacy repairs remain publication changes. A later export
must merge those repairs and preserve newer scoped results; blindly copying a
private plan over a public file is not a valid publication procedure. Compare
the exact source and destination versions before replacement. Source maps bind
exported implementation bytes; a public plan never substitutes for those maps
or private execution evidence. Publication does not release run holds.
