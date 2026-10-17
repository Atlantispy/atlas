# Plan 05: q10 H5a evidence and correctness resolution

**Item:** 05  
**Status:** WORKING NON-CANON; **q10 FAIL with unresolved correspondence and causality**.  
**Retained owner:** Heat. Codex performed bounded read-only diagnosis; that contribution does not transfer ownership.  
**Dependency:** **q22 remains HELD** until the required correctness proof is accepted through the existing owner/coordinator process.  
**Document disposition:** Revised under general441, incorporating Claude general437 and Codex general439. This accepts the plan amendments, not H5a correctness.  
**Completion condition:** Obtain a source-grounded disposition of the q10 failure through the existing correctness process. A bounded evidence inquiry may instead finish with a precise missing-evidence blocker; that leaves correctness unresolved and q22 held.

This plan grants no new executable verification, regeneration, rerun, implementation, integration, publication or queue-change authority. Separately authorised work retains its existing scope, owners and queue requirements. Preserve the original q10 records, all individual holds and the fresh-interval hold. No proposed artefact or method below is represented as built or run.

## 1. Established outcome

The coordinator records q10 on 16 October 2026, 21:46:25-21:54:26: elapsed 481 s, exit 1 and measured process-tree peak 1.03 GiB against 1.1 GiB booked. These are historical observations, not a new runtime estimate or admission rule. All five arms completed cleanly without fallback/leaks. Observer, H1a/H2, H1c and L1 exact comparisons passed; the H5a `lf3` to `lh` comparison failed. Clean arm execution and within-arm legacy/compact agreement do not establish cross-arm equivalence.

The retained `compare-l1-h5a.txt` reports:

| Captured array | Positional comparison |
| --- | --- |
| `enthalpy_j` | DIFFERS |
| `input_capacity_j_k` | DIFFERS |
| `input_enthalpy_j` | DIFFERS |
| `input_source_w` | Bit-identical |
| `temperature_k` | DIFFERS |

All five are binary64 arrays of shape `(236,)`. The comparator requires equal names, dtypes, shapes and bytes; it performs no row mapping. Separately, its metadata walk reports **501 digest leaves and 3,021 NUMERIC/OTHER metadata leaves** differing. The latter include four exact cell-account families, `exact_paired_face_energy_j` and resource-accounting fields. They are not 3,021 proven topological errors, nor a count of changed array elements. The comparator's digest category is not independent proof that an identity translation is legitimate.

Both inspected arms retain 236 unique cell IDs, with zero intersection. This establishes no common literal key in those lists. It does not prove that corresponding physical locations differ, that a harmless permutation exists or that H5a is accepted.

## 2. Source mechanism and its limits

The retained source diagnosis identifies this dependency:

`native-package source pin -> execution identity -> native/collar plan and funding identity -> thermal cell names -> sorted mesh-row order`.

The package inventory includes a binding file changed by the H5a layout. Funding participates directly in collar thermal cell IDs and indirectly through support identity in exterior thermal cell IDs. The mesh sorts by those names before the heat advances call H5a's shared preparation. This supplies a mechanism by which changed provenance can rename/reorder cells without requiring a coordinate change.

It does not reconstruct every historical execution/funding preimage, establish the actual q10 bijection or prove equal corresponding inputs. Current source identities are not a substitute for the missing historical arm-bound records. A source formula cannot invert a historical hash.

The open explanations remain unavailable correspondence evidence, mismatched physical inputs, a representation change and numerical regression. They are not settled by zero ID overlap, identical per-arm summary flags, matching value multisets or failure to find a map. No solver-kernel redesign is inferred at this stage.

## 3. Precise evidence boundary

The inspected arm-3 and arm-4 directories contain `arrays.json`, `legacy_metadata.json` and five `.npy` files. Their retained records contain no explicit cell logical/physical mapping, coordinates, polygons, incidence table or cross-arm identity map sufficient to establish correspondence. Whole-geometry digests and the saved face-ID list do not recover missing cell geometry or face-to-cell incidence.

The named control harness held packed mesh support blobs in a local in-memory dictionary. Its observer captured heat metadata and numerical arrays, not that instantiated mesh/crosswalk. The saved source diagnosis identifies the exact fixture, loader and observer chain and its limits.

This absence claim is confined to the inspected outputs and named harness. It does not establish that no other authoritative artefact exists elsewhere. Reuse the existing diagnosis; repeating the same inventory or numerical comparison without changed input cannot supply the missing proof.

The conditional next evidence step is for the Heat owner to identify an exact existing candidate artefact path and identity, with its authentic linkage to both saved arms. It must retain row index, thermal cell ID, suitable logical/physical key and sufficient exact geometry/support, bound to the saved input/output/account rows. Inspect that specific artefact within the authorised scope. If none is available, record the precise blocker and the evidence required to resolve it; do not regenerate a layout, rerun arms, invent a crosswalk or broaden the search automatically.

## 4. Conditional correspondence and comparison contract

A future crosswalk is an evidence route, not a predetermined PASS. It must satisfy all of the following before it can support the correctness decision:

1. **Authentic binding.** Verify that the records belong to the actual q10 arms and bind the original saved rows. Similar geometry generated later or matching source code alone cannot establish that historical binding.
2. **Exact keys and complete coverage.** Use independently established physical/logical keys with uniqueness and coverage across the complete relevant cell sets. Derive the expected set from the authentic records. The observed 236 cells are a retained-run fact, not a universal hard-coded mesh size. Exterior logical-key components remain candidates until checked. Collar `logical_cell_id` is funding-dependent; physical cell IDs and their Cartesian context need their own proof.
3. **Equal physical context.** Establish the relevant geometry, topology, support, boundary conditions and input context. Centroid proximity is neither necessary nor sufficient proof: different cells can share a centroid and nearest matches can be ambiguous. No approximate nearest-centroid, guessed-ID or value-based matching is admitted.
4. **Coherent row semantics.** Apply one independently proved cell mapping consistently to corresponding input/output/cell-account rows. Do not find a different permutation for each field to make it agree. Respect each array/account's actual axes; face accounts require authentic face/incidence/orientation correspondence rather than a cell permutation.
5. **Inputs before attribution.** Establish corresponding input parity, including enthalpy, capacity and source, before attributing output differences to H5a under equal conditions. Checking temperature alone cannot resolve the retained failure.
6. **Complete exact comparison.** Preserve the existing exact/bitwise contract and required coverage: all five arrays, the four exact cell-account families, face accounts and other metadata. Source/path/digest and resource differences need their own contract-grounded disposition. A cell reorder must not erase them. Any proposed exception requires the existing acceptance process; this plan introduces none. N9's numerical criteria do not apply to this heat proof.

The four cell-account families are `exact_cell_storage_residual_j`, `exact_corrected_enthalpy_j`, `exact_retained_solver_residual_j` and `exact_stock_projection_residual_j`. Retain `exact_paired_face_energy_j` separately. Use the model's actual quantities, units and source-defined conservation checks; a temperature-volume sum is not a replacement thermal-energy proof.

If a verifier is later authorised and built, its focused checks must distinguish a valid mapped control from an actual misplaced field and from incomplete/ambiguous binding. A generic refusal caused by missing evidence cannot stand in for detecting the intended defect. This conditional requirement supplies no new verifier filename, executable command or run assignment.

## 5. Disposition and holds

| Evidence outcome | Permitted conclusion and next action |
| --- | --- |
| No authentic mapping available in scope | Report the precise evidence gap. q10 remains FAIL with unresolved correspondence; q22 remains held. |
| Complete mapping, but unequal corresponding inputs or physical context | Identify the actual mismatch and its source. Do not attribute output differences to the solver under equal conditions. Heat owns the corrective proposal. |
| Valid correspondence and complete exact proof | Submit the evidence and every metadata/identity disposition to the existing correctness acceptance process. Mapping or script success alone is not acceptance. |
| Valid correspondence exposes a representation or numerical defect | Locate and describe that defect with evidence; propose the bounded owner repair. Neither kernel redesign nor a rerun follows automatically. |

Preserve the historical q10 FAIL and original artefacts even if later evidence resolves the issue. Record the later proof/disposition as a successor outcome. Only accepted correctness proof can satisfy the q22 dependency; the existing coordinator still controls queue action. Plan approval never changes a ticket or releases a hold.

## 6. Completion conditions, not current claims

- [ ] An authentic arm-bound mapping/evidence source is identified, or the bounded inquiry records the exact missing-evidence blocker.
- [ ] Any supplied correspondence is proved unique, complete and physically appropriate for cell and face/account layouts, with saved-row provenance.
- [ ] All inputs, outputs, exact accounts and remaining metadata receive their required exact comparison or separately authorised disposition.
- [ ] Heat records the evidence-backed correctness outcome through the existing owner/coordinator process; missing evidence is not recast as PASS or a proved numerical defect.
- [ ] q22's prerequisite is satisfied only by accepted correctness proof, with any subsequent queue action separately controlled. Otherwise the hold remains explicit.

The first condition can close a bounded inquiry with a blocker while the remaining correctness conditions stay incomplete.

## 7. Sources and current authority

`T = C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10`  
`W = C:/Users/LOCAL_USER/Documents/Codex/agentchattr/workspace`  
`A = C:/Users/LOCAL_USER/OneDrive/Documents/GitHub/atlas`

| Source | SHA-256 | Scope |
| --- | --- | --- |
| `A/.atlas-dev/plan-status-20261016.md` | `be270e6898e0b1d5aa0c7d29065baf1d4df16ece34490f17d7c68a9d77d4339e` | Current q10 status, Heat ownership and q22 dependency |
| `A/.atlas-dev/coordinator-handoff-20261016.md`, Room checkpoint, 16 Oct 21:59 | `e75652996f3f29e6c4b074f24bec561551c842c7b04a1ac49ccb8c411799ba15` | Actual q10 run outcome and preserved holds |
| `T/hs/scripts/compare_ab_r2.py` | `f67dbb662b66fc0c8559a5df7f92c3f8789210fbe4cf3892a57f7bdb26f5e7da` | Existing positional byte/metadata comparison; source read, not re-executed |
| `T/hs/evidence/h1c-r4a/compare-l1-h5a.txt` | `cb2d98fd4059c88d146ad17032f5d0c480663e830ca2059fd34deb008c252a7e` | Retained four-array and metadata differences, D-b FAIL |
| [Pairing evidence](../work/q10/pairing-evidence.md) | `4fa908160e0f5aacd6e39c18e4696daad298fe0e008be082d89c2603b603e225` | Existing bounded output inventory, recorded ID-set result and missing correspondence |
| [Identity boundary](../work/q10/identity-boundary.md) | `f1cdcba41d01d765a116c7f6c6245cca91232b7192643d9983ac7c56a041279e` | Source dependency chain, exact source pointers and uncaptured mapping boundary |
| `T/hs/HANDOFF-20261016.md` | `0c0d7459c6263dcbefd3853586feb1a213dbe5e5f5952145b41cdf282cf21899` | Retained owner/design context; its older not-run wording is superseded by the actual q10 result |

The frozen independent reviews remain unchanged. The post-reveal amendments and completion return are retained in [Codex's Plan 05 discussion record](../discussions/atlas-plans-39-review-20261017/codex-plan-05-turn-02.md).
