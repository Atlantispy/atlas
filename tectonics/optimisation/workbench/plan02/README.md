# Plan02 source snapshot

WORKING NON-CANON. This additive snapshot preserves the selected Plan02
runner/caller generation and the subsequent collar metadata repair. It is
source for review, not a runnable installation or a complete native package.
The frozen `composed-r2` snapshot and the main tectonics package are unchanged.

## Changes

The prepared producer, independent reader and monitored launcher use the
by-need Route2 admission contract in [ROUTE2_ADMISSION.md](ROUTE2_ADMISSION.md).
The compatible fresh-route callers, companion gates, identity probe and tests
are retained together. Replacing the prepared runner alone would leave older
callers using its removed `START_BYTES` constant.

The native transfer loader now admits both metadata shapes emitted by the
collar producer: the five base fields of an initial state, and those fields
plus `heat_id` and `transport_id` on an evolved state. Both extra identifiers
must occur together and each must be a lowercase SHA-256 value. They stay in
the original metadata, migrated snapshot and snapshot identity. Missing,
unknown, partial or malformed fields still refuse. This repairs admission of
existing producer output; it does not change simulation calculations.

## Source identity and scope

[SOURCE-MAP.json](SOURCE-MAP.json) maps the 25 selected source/document files
to their original and public SHA-256 values. Text uses LF. Any publication
change is explicit there; public copies never silently authenticate private
execution receipts. The root optimisation manifest also lists these files.

Private source manifests, runtime profiles, checkpoints, receipts, logs and
coordination records are excluded. Host-bound original test sources are
included for inspection; their presence does not make the whole suite runnable
in a public clone. A new native installation needs its own complete source
closure and profile binding.

## Verification and remaining work

The private selected generation was installed with 43 distinct live checks
and 100 C18 source/lineage checks recorded. The later one-helper repair passed
six metadata controls, six document-fault controls and source/profile checks.
These are retained private results, not new public execution evidence.

The public regression `tectonics/tests/test_plan02_metadata.py` uses synthetic
metadata and the published helper. It checks both valid shapes, malformed
and partial extensions, metadata preservation, identity sensitivity and the
source map. It imports no Atlas native runtime, opens no store and performs
no simulation. It requires NumPy, as does the helper.

Positive prepared-state publication and independent reopening remain unrun
after the repair, deferred by the owner; final review is also outstanding.
Plan31 assembly integration is a separate later stage and does not block
Plan02's own completion. All scientific and individual run holds remain.
