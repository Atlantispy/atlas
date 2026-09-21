# Remake review fixes — dev40

WORKING NON-CANON. Changes prepared against dev39
`7aacee7661a96ce35f78dfe61ec5228801ba44dc` with OpenAI Codex assistance.
Code checks, scientific acceptance and publication remain separate.

## Subsequent adaptive-inner return review

The dev39-based adaptive-inner return was independently reviewed and reconciled
with these dev40 changes, preserving diagnostic-only recovery. All seven modified
baseline source files matched the named Git base exactly. A restored-state
validation gap was fixed: Tosi-plastic records cannot claim inactive adaptive
solving and omit their strict certificate. Non-unit SI and adaptive recovery
regressions were added. The optimisation remains opt-in; no tolerances were relaxed.
See [review, focused checks and timing evidence](../tectonics/evidence/r4-4-dev40-adaptive-inner.md).
This addendum supersedes the earlier 37-file delivery count below; those earlier
verification results describe the preceding checkpoint, not this new source identity.

## Corrected behaviour

- Convection recovery appends a hash-linked diagnostic-only receipt when
  cancellation saved an accepted endpoint before its sample. Resume completes
  that obligation before advancing, including step zero and the final step.
  Existing receipts and physical steps are not rewritten or repeated. The audit
  folds the repair into its endpoint while retaining the complete receipt-chain
  identity; repeated resume adds nothing.
- Spherical-network stitching aligns source-region rings to the network domain's
  chart before spatial-index lookup, preserving exact shared-vertex checks.
- Species adapters authenticate declared source files before/after execution and
  when graph results are restored from cache or resume. The existing synthetic
  marker is restricted to explicitly synthetic evidence; actual file paths are
  checked even for synthetic registers. Missing or changed sources are refused,
  not repinned.
- Fixed-grid and ALE material transport reject materially rounded clock intervals
  rather than integrating one duration and labelling it as another.
- Reference remapping/ALE forms neighbour-centre distances from adjacent widths,
  avoiding origin-dependent rounding at large coordinate offsets.

The earlier dev40 thermal-wall, dependency-compatibility, periodic-assessment and
schedule/preflight corrections are included. Their prior bounded numerical
evidence remains separately labelled in
[the numerical assessment](../tectonics/evidence/r4-4-dev40-numerical-assessment.md).

## Admission observations

Direct authored polygons deliberately require strictly interior, disjoint holes.
Exact set operations and WKB import can legitimately contain GEOS-valid point
contacts; that distinction is documented and tested, not removed by snapping or
discarding valid overlay results.

A near-unit material volume-fraction total can still pass the initial sum check
and then be refused by the stricter conductivity-bound check. No fraction
renormalisation, invented missing constituent or relaxed physical bound was added.
Resolving that input-policy ambiguity is outside these five defect repairs.

## Compatibility and verification

Source changes invalidate old source-bound execution identities. This update does
not migrate historical runs, rewrite their receipts, or make old caches/checkpoints
valid under changed code. Use their original source/runtime for historical replay;
new execution needs its own explicit identity. The declared SciPy range is now
`>=1.15,<1.18`, matching the authenticated FFT backend.

Focused checks used Python 3.12.14, NumPy 2.4.6, SciPy 1.17.1 and Numba
0.65.1, with numerical thread limits set to one and bytecode disabled.

| Selection | Result | Elapsed |
| --- | --- | ---: |
| Material transport and remapping/ALE | 18 passed | 7.824 s |
| Spherical stitching and planar geometry | 47 passed | 0.542 s |
| Convection recovery, wall reconstruction, assessment, preflight and schedule | 80 passed | 33.343 s |
| Species source boundaries and retained semantics | 10 passed | 0.413 s |
| Repeat of seven new species checks in the delivery checkout | 7 passed, already counted above | 0.474 s |
| Coding-safety static tests in the delivery checkout | 30 passed, 1 skipped | 0.113 s |

That is 155 distinct focused component/workflow tests passed, plus 30 static tests.
The static skip is Windows refusing test-symlink creation, not a numerical skip.
The coding-safety checker also passed its 13 selected maps and 41 required paths;
`git diff --check` passed. Before the final documentation update, all 37 delivered
changed/new files matched the tested review copy byte-for-byte. The 80-test run
and repeated seven species tests ran in the actual delivery checkout.
These are test timings, not development-time or solver-speed measurements.

Convection selection used `unittest.main(module=None, argv=[...])` under
`python -I -B -c`, with the checkout's `tectonics/src` and `tectonics/tests`
prepended to `sys.path`. Exact selected names:

```text
test_convection_diagnostic_recovery_r4_4
test_convection_assessment_r4_4
test_convection_schedule_r4_4
test_convection_probe_r4_4
test_thermal_wall_reconstruction_r4_4
test_convection_r4_4.TemporalScreeningTests
test_convection_workflow_r4_4.AnalysisPolicyTests
test_convection_workflow_r4_4.SuiteAcceptanceTests
test_convection_workflow_r4_4.DriverRecoveryTests.test_fresh_process_resume_matches_uninterrupted
test_convection_workflow_r4_4.DriverRecoveryTests.test_cooperative_bound_saves_then_resumes
test_convection_workflow_r4_4.DriverRecoveryTests.test_changed_source_refused_without_rebinding
```

Geometry selected `test_w01_spherical_atlas.Stage3Stitching` and
`test_w01_geometry.PlanarGeometryTests`. Material selection covered the five new
clock/translation regressions, retained zero/overflow intervals, upwind balance,
smooth refinement, remap affine/constant/front conservation, irregular ALE,
geometric conservation and event-interval guards.

Species selected `test_species_source_bindings` and these retained
`test_r22_species.SpeciesTests` methods:
`test_source_day_recruitment_and_residence_separate`,
`test_source_selection_and_context_refusals`,
`test_owner_biology_binds_to_replaceable_application`.
The actual R12/R24 executors and disk Store were exercised; full R31 scientific
execution and real spawned scientific workers were not.

Final static commands, from the repository root with the same interpreter:

```text
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -q
git diff --check
```

No full regression suite, mature convection campaign or world generation was run.
R4.4/R4 remain IN_PROGRESS and full scientific acceptance remains false.
