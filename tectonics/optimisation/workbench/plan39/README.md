# Release policy: reviewed source integration, qualification pending

Plan39 is partly implemented. Release is **not the default** and issue #67 remains
open. This source selection connects the policy changes to the existing store,
publication, parent/worker and checkpoint consumers. It is not a qualified release
package, an installed application update or permission to run an interval.

`SOURCE-MAP.json` describes all 692 selected members: 287 native/package assets
and 405 helpers. It supplies 52 changed or missing public copies and references
640 existing files. This includes all 18 A7 pin-propagation members omitted from
the initial handoff patch, the retained fixture-loading support and its assets.
The private predecessor and sealed candidate are preserved. Original and public
digests are separate: public comments, identifiers and line endings do not
authenticate historical private measurements.

Construct a separate source layout from the repository root:

```text
python -B tectonics/optimisation/workbench/plan39/build_selection.py --repo . --output NEW_DIRECTORY
```

The builder authenticates every selected file, refuses occupied or linked output
paths and imports no Atlas module. The resulting source and helpers belong
together. Its manifest grants no runtime, default, interval or scientific authority.

## Behaviour and integration

- Compact sealing, promotion and adoption call the publication boundary before
  committing. Release verifies captured backends; strict checks entered contexts.
  A failed context close cannot pass as a successful identity check. An unfinished
  concurrent close/check refuses publication; a successfully closed context may
  be skipped. The catalog remains unchanged on refusal.
- Release retains package source handles for the process lifetime. Store-open
  verification covers its read session; commit, backup and publication remain
  full boundaries. Byte authentication remains required.
- Worker entry, capture and parent acceptance admit the guarded Release mode.
  Parent acceptance verifies the boundary before using identity. The bare-name
  fresh-module route refuses packaged execution. Evidence commands remain strict.
- The two finish-arithmetic assertions are explicit `AssertionError` raises.
  Optimised Python is refused. Sizing helpers use a composition-bound shipped
  strict-peak table, cap at `min(12 GiB, physical - 3 GiB)` and require available
  memory of `peak + ceil(peak / 5) + 1 GiB`. Missing estimates refuse.
- The static closure checker detects the reviewed alias/rebinding cases, rejects
  missing packages and blocks unresolved imports. It is a bounded policy check,
  not a hostile-code sandbox or complete Python data-flow proof. Excluded-name
  files must actually be omitted by the future build hook.

## Evidence and remaining work

The repaired private successor passed 24 focused checks: eight disposable payload
checks, five sizing checks and eleven closure-checker controls. Eight inert
close-race controls distinguish the repaired implementation from the rejected
candidate. Entry admission alone does not prove a launched worker workload.
The original strict helper evidence remains scoped to its original source.
The constructed public selection also passed those 24 focused checks and the
eight race controls. Its 692-member materialisation and six source-builder
controls passed. These public-copy checks do not qualify a real desktop build.
The final cleanup changes eight fixture-description strings and removes two
trailing blank lines; executable code, fixture numbers and JSON structure remain
unchanged.

The current closure fails on five fixture imports and ten computed import sites.
The latter need an explicit source-bound disposition; they are not evidence of
malicious code and have no blanket waiver. E2 dependency promotion, interval
runner entry and sizing wiring, folded helper pins, the desktop manifest hook,
authentic measured peaks and real packaged strict/Release parity remain open.
No timing improvement, fresh interval or scientific acceptance is claimed.

Public source sanitisation removes coordination comments and neutralises a
proof-only refusal message. The review-approver identifiers in the new public
driver copy are generic roles; private approval records are not migrated or
accepted by rewriting their identities. Strict numerical checks and resource
limits remain; original private source and receipt hashes are preserved.

Focused tests under `checks/` require `ATLAS_COMPOSITION` to name the constructed
layout and the compatible scientific interpreter. The disposable packaged-layout
fixture is Windows-specific and uses `ATLAS_VENV` for that interpreter. Ordinary
checkout operation remains strict; real delivery qualification is still pending.
