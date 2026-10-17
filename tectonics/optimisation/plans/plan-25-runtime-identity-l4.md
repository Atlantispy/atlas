# Plan 25 — L4 runtime arithmetic identity

**Item ID:** 25  
**Retained owner:** Kernels, with coordinator control of the shared runtime-record seam.  
**Status:** WORKING NON-CANON. Approved, not started; the shared-file plan/decision and implementation remain outstanding.  
**Target completion condition:** Add the approved label-keyed arithmetic pins to the actual runtime record, prove refusal for changed pinned bytes and unchanged numbers, then carry the reviewed successor through C12/X1. Preserve historical receipts. This planning update does not authorise a shared-source edit.

## Authority and exact scope

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`. Primary contracts are `T/ck/HANDOFF.md` §4, `T/rm/LANGUAGES.md` L4 and `T/so/assembly-manifest.md` C12/X1 and amendments. Full document identities are retained in [primary-source-pins.json](reviews/codex/primary-source-pins.json). This plan implements the [accepted Plan 25 corrections](reviews/claude/consolidated-23-39-for-codex.md).

The seam is the function `reuse._runtime_record` in **`reuse.py`**, with `_loaded_binary` and `exact_arithmetic.runtime()` participating in the existing execution record. It is not a module called `_runtime_record.py`. The source to transform is the selected composition/package input named by C12, not an invented `T/ck/reuse` tree.

The gap is specific:

| Labelled input | Required source of identity |
| --- | --- |
| `_decimal.pyd` | Actual loaded extension path, full expected binary digest and its libmpdec version. |
| `python312.dll` | Actual loaded Python DLL, using the loaded handle/path route (`sys.dllhandle` in the current Windows runtime), with a full expected digest. |
| Arithmetic stdlib sources | Loaded `fractions.py`, and `decimal.py` / `_pydecimal.py` **as used**, with full expected source-byte pins. |

Retain existing runtime and exact-arithmetic identities, including already bound native dependencies. Do not replace them with this small table or add a separate GMP/MPFR scheme. L4 changes digests only (D-b), not numbers or arithmetic policy. FTZ/DAZ and IEEE rounding-word enforcement are outside this approved repair; a future kernel-specific need requires its own source-grounded decision.

## First gate: the existing shared-file decision

Before editing, Kernels sends the coordinator the proposed labels, exact files, trusted SHA sources, where the record is checked, refusal wording and recommendation. The coordinator's decision is the existing first gate in `ck/HANDOFF.md` §4. The current plan supplies scope, not invented runtime SHA values or a claim that this gate has passed.

Use the actual selected environment and loaded binary paths. A virtual environment's `sys.executable` sibling is not a reliable DLL location. A missing/unresolvable required file refuses; it must not become an accepted `SYSTEM_STATIC`, `BUILTIN` or empty identity. Recording the bytes found at launch is insufficient unless checked against the trusted expected reviewed pins.

## Implementation and composition contract

After the shared-file decision, Kernels implements the change as a source-bound transform under its existing `CK/transforms` route, with input/output pins and the small proof. Do not invent a transform filename or a verification API before the owner supplies it.

- Extend the existing label-keyed record and its load/boundary checks. Bind observed bytes and loaded locations to the expected runtime generation; retain transform/source bindings and fail-closed missing/mismatched dependencies.
- **C12:** produce one `reuse.py` revision/cache generation in the order source_handles r2 → L4 → package reconciliation. Resolve the actual shared input through the manifest; do not fork competing runtime-record implementations.
- **X1:** combine H3 + G-PY + N9 + L4 when timing allows. Preserve the approved fallback: L4 rides the first H3/G-PY generation. The runtime SHA set belongs to Kernels.
- **R1:** the mandatory final N12 fold consumes that selected revision, goes last and preserves package-relative loaded-source identity. The fallback does not make R1 optional or permit fresh runs before fold, landing and proofs.
- L4 is required before K1 under `LANGUAGES.md` L4. New identities are prospective successors; old run receipts and pins remain unchanged.

## Prospective validation and completion

Reuse existing unchanged runtime tests within their actual scope. The focused new proof must establish:

1. The authentic selected runtime passes with all required labels and full expected pins; the actual loaded extension/DLL paths are recorded and bound, including the virtual-environment/base-runtime distinction.
2. Changed `.pyd`, DLL and stdlib source each refuse at load. Use disposable fixtures or controlled expected-pin substitutions; do not alter the installed interpreter. A required missing file also refuses.
3. The proof is bound to the exact transform/output/runtime bytes, and exercises the real shared-record check rather than a standalone hash helper.
4. D-b holds: numerical fields and existing checks are unchanged; only the approved identity fields and their dependent identities change.

Run only the authorised small-lane proof under the existing queue and runtime seed/source rules. Record its actual source pins, observations, refusal evidence and disposition in Kernels' existing owner record and the composition manifest. No test command or success is fabricated here.

Completion requires the shared-file decision, source-bound transform, changed-input refusals, small proof and correct C12/X1 hand-off. It does not establish final-composition, scientific or canon acceptance. L4 remains not started until its owner record supplies those results.
