# Plan 20 - S2 r9 exact diagnostic captures

**23 October 2026 — WORKING NON-CANON. A/B accepted and public source integrated;
C, the Release/Plan26 folded DLL binding, remains pending.**

The retained 12-arm capture comparison passed: 48.9264% lower median write time and
13.4949% fewer stored bytes for the three eligible operands. This excludes input
decoding, preparation and initial library loading; no RAM or whole-interval gain
is claimed. Selected private composition/runtime changes were applied and checked.
Consumer failure IDs/counts match the selected base; fresh-entry probes pass 9/9,
and native-library tests give 16 passes/one dictionary skip. These do not establish
all-green consumers or execution of the prepared-entry insertion.

See [method, measurements and remaining binding](../workbench/plan20/README.md),
[source overlay](../workbench/plan20/SOURCE-MAP.json) and the
[combined selection](../workbench/plans19-20/README.md). Final selected-generation
fold controls and prepared-entry execution remain outstanding; the implementation
issue stays open. The library binary and private execution records are not shipped.

This is a dated public projection of the accepted outcome, not an execution
ledger. The linked method/source records state the numerical, resource, refusal
and integration boundaries. Git history retains earlier projections. Private
execution records remain authoritative; publication does not release run holds.

## 2. Exact-byte, reader and resource contracts

The codec-independent logical identity is **`raw_bytes` plus `raw_sha256`**. For the mesh, the raw hash must still equal `geometry_id`. Cross-run and cross-format comparisons use that logical identity. Each capture's `container_sha256` authenticates that file against its own receipt; it must not be compared across codecs or runs as though it were the logical identity.

The receipt generation changes once: captures use `*.capture`, `stored_bytes`, `container_sha256` and `format='atlas.diagnostic-capture.v1'` in place of gzip-specific fields. Receipt bytes and their derived IDs can therefore change even though the scientific bytes do not. Preserve the explicit generation note, old receipts and legacy-gzip readability; do not promise every receipt field is byte-identical.

Selected r9 writes through bounded byte chunks and the pinned backend, with fsync, exclusive publication and atomic rename. Missing or mismatched native support refuses; raw mode is not an ambient fallback. `require_capture_route` executes the capture imports through the selected loader and checks the backend for a compact store before the relevant advance. Module import alone is not route readiness. Other store types are left alone.

The ledger requires composed helpers and runtime source on `sys.path`; missing reader dependencies produce a clean refusal. Before allocating the capture output buffer, selected `captured_bytes` checks receipt types and ceilings, stored size, full container hash and the authenticated footer's raw size. It consumes the bounded reader fully, closes yielded owners, checks completion and raw identity, then parses. Preserve these ordering and lifetime checks.

Retain the documented limitations:

- **CAPTURE_MAX_BYTES is 16 GiB on this route**, for the explicit logical/stored ceilings. This replaces `capture_store`'s 4 GiB defaults for these writers/readers; it does not raise the project's RSS or workspace guards.
- WP16 export/replay/CLI readers still have **4 GiB defaults**. A 4-16 GiB capture can be ledger-readable and refused by those tools. This remains an explicit Storage compatibility issue, not a silent promise of universal readability.
- Accepted legacy reads can need approximately **2x raw_bytes** transiently; the retained 182 MiB raw mesh example is about 385 MiB. Retain the accepted many-member per-block cost and stricter malformed-gzip header checks. New capture reads also allocate the validated raw output buffer; a streaming writer does not imply constant whole-reader memory.
- The selected capture route uses 64 KiB chunks. Logical booking figures are not process RSS, and there is no new 150 MiB cap or demonstrated RSS saving.
- The accepted compact-mesh/legacy-store case refuses at capture after advance. Optional extra module-list checks for stop-before-advance smokes remain an owner choice under the integration note; this plan does not silently make them mandatory.
