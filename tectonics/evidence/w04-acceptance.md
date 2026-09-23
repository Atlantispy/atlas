# W04 combined acceptance — bounded result

22 September 2026. WORKING NON-CANON, local unreleased `remake` work.

**PASS_SUPPORTED_STATIONARY_PLANAR_1D_W04**. The selected W04 load-to-support
workflow is accepted within its documented stationary 1D scope. No production
solver correction was needed. This does not establish calibrated terrain, other
stages, whole-world cost or general moving/2D/spherical support.

## Changes and independent review

- Added `tests/test_w04_acceptance.py`: four combined controls spanning uniform
  and variable stiffness under periodic, continuing and mixed free/clamped support.
  The same authentic W03 sequence cools, compacts and partly rebounds. Independent
  inventory/thermal accounting, explicit water redistribution, additional pressure,
  reference-shift additivity, exact restored continuation and cache recovery pass.
- Added an explicit variable-D bridge strain test: after a cache hit, the actual
  cropped profile Te and curvature mesh-change margin must still trigger the
  selected validity limit. It deliberately differs from `policy.elastic.Te`.
  Independent review identified this evidence gap; no defective solver was found.
- Extended the existing `verify.py` with `--w04`, exact reviewed test selection
  and scoped status. Failures, errors, skips, empty selections or source drift
  cannot pass, nor can the route fall back to full-suite discovery. Three new
  profile tests and three retained W01 profile tests passed in **0.001 s**.
- Updated the current README, plan and contracts. No source-module change,
  installation, checkpoint repin, commit/push, full terrain or R4.4 run occurred.

The first assembled four-test run took 41.327 s and reported three subcase errors
from the same final uniform mixed-edge snapshot. A bounded diagnostic established
strain **0.012010364704435138** against the unchanged **0.01** limit; slope was
0.015213242362989914 against 0.1. This was a correct safety refusal, not a hidden
implementation failure. The synthetic cooling intervals were changed from
1e6/2e6 s to 1e5/2e5 s, keeping the compaction/rebound stress choices, spatial
loads, physical validity limits and assertion tolerances unchanged. The control
remains an already-drained accounting example, not calibrated consolidation time.
Thermal diagnostics share the existing context and reference temperatures to
avoid repeated setup; that is a fixture improvement, not a new generator speed claim.

## Final execution

Command: `python -I -B tectonics/verify.py --w04`, existing Python environment,
one OPENBLAS/OMP/MKL/Numba thread, Windows AMD64.

**62 tests passed in 51.7190680000931 s; 0 failures, 0 errors, 0 skips.**
Source inventory was identical before and after execution. The selected gate
counts are 19 load, 10 periodic, 11 finite, 8 variable-D, 4 assembled, 1 load-reuse,
6 source/validity and 3 status controls. The [contract](../docs/W04_COMBINED_ACCEPTANCE.md)
maps their coverage and physical limits; the [JSON record](w04-acceptance.json)
contains exact test IDs, failures/skips fields, source inventories and runtime data.

Python 3.12.14, NumPy 2.4.6; existing SciPy 1.17.1 separately confirmed. No Linux
execution is claimed. Native/runtime/source checks were retained; unchanged
historical component results are not promoted to cross-platform evidence.

Source-only checks also passed:

- `python -B tools/check_coding_safety.py`: 13 maps / 41 paths, static only.
- `python -B -m unittest discover -s tests -p test_coding_safety.py -q`:
  30 PASS and one Windows symlink skip, **0.109 s** (separate from the 62-test run).
- `git diff --check`: PASS; existing informational LF/CRLF warning only.

The compiled production modules were not changed by this step. The earlier
[variable-factor reuse benchmark](w04-variable-timing.json) still binds the
unchanged implementation: 12 changing loads, median **0.039662400028 s ->
0.020635399967 s**, **0.019027000060 s / 47.97238706% saved**, identical results.
This was **not rerun** or relabelled as an end-to-end gain. Acceptance runtime is
not simulation runtime; no additional optimisation percentage is asserted here.

## Research and scope

Before selecting comparisons, reviewed [Wickert (2016), gFlex](https://gmd.copernicus.org/articles/9/997/2016/)
full-text passages on load/infill, superposition, discontinuities, benchmarking
and coupling, plus [gFlex numerical-accuracy documentation](https://gflex.readthedocs.io/en/latest/accuracy.html).
These informed comparing like equations, load representations and boundaries,
and keeping infill feedback separate from prescribed finite water placement.
Documentation/paper review only: no external gFlex execution or field calibration.

The existing analytical/convergence controls verify the selected equations; they
do not prove every geological application. D remains fixed in time, K constant,
variable exterior uncertainty unsupported, and mesh changes are estimates rather
than rigorous continuum bounds. The production result remains a one-way support
projection. Next is the separately scoped W05 regional-extension mechanism.

## Binding identities

- `evidence/w04-acceptance.json`:
  `a6be21a624721be5a40b3bee547f3f9d558b3be1aba99bf0b14d0225a3e151b2`
- `verify.py`:
  `37e764bfcfe8724919df12980b34e2849c4db4d6208be458e0316f68e42148ea`
- `tests/test_w04_acceptance.py`:
  `a18dabf076a8dbd465d1c7ff493d47edae5b782840f152e60dec98d31f064d37`
- `tests/test_w04_acceptance_profile.py`:
  `b08b22a1af8d6f1fee839235300fb82d4c48ab86a8ba0b9344315b8ec465c7f5`

All production source hashes are in the machine record; no old state was repinned.
Passing this bounded acceptance does not establish publication or canon adoption.
