# C13 polygon implementation — additive, not enabled

**NOT ADOPTED:** the later [actual native-owner/source-check comparison](../MEASUREMENTS.md) is 6.001% slower. The implementation and negative result are retained as an explicitly unselected experiment. The earlier 1.42% prototype reduction below is not an implementation saving.

The measured functional caches do not justify implementation: C1's full-arm median was 18.10% slower, C2 60.64% slower, C12 8.05% slower and C14 5.81% slower. C13's stateless norm/edge/symmetry subset is the only positive result:4.53525 ms baseline versus4.47070 ms candidate, a 1.42% median reduction across six samples per arm. All three counterbalanced block means favour C13, but the last by only about 0.10%; ranges overlap. This is a modest bounded-component result, not a statistically established or whole-IV saving. Raw arm samples and dispositions are in `MEASURED-DISPOSITION.json`, derived only from accepted run `364b539f-74df-4ee4-83ce-f4f1cb2370f8`, measurement SHA256 `9b825953f92e734dd5a42dd517e36ec72ad01ee1b52a1700b4eb2d9f8e97f294`.

Implemented three additive modules:

| File | Change / SHA256 |
|---|---|
| `private_heat_polygon_numerics_40b_r1.py` | Original exact Fraction geometry checks and output with the normal square retained, each edge difference reused within its convexity check, and lower-triangle output referring to immutable upper-triangle values. Three distinct result rows remain. No triangle-sum cache. `5991aca3ed26e65e2290be6c1ee4052f15b74a1e770b9606849263e25b12f00c` |
| `private_heat_polygon_moment_40b_r1.py` | Calls actual predecessor `M.admit`, retains identical full prospective plan, executes the successor, shrinks at the original boundary, then uses actual retained-value r4 transfer. Same native owner types and failure custody. Pins predecessor M bytes and numerical successor bytes/callables. `de56233d0272555e7998f1dc5418a65c017abcb7a51e3a48aaea62738ca4bfd0` |
| `private_heat_functionals_kernel_40b_r1.py` | Exact selected r5 source with only its MOMENT import changed to the new owner. The real reconstruction moment provider therefore reaches the successor. `0c9606475fb7e6576d94680c0d7b2757e8088c0d94bc20564e842ea45c3a1c59` |

## Why the original native admission still applies

The original M1 `_plan` deliberately charges **all generated exact scalars cumulatively**, independently of lifetime. The retained normal square is its initial normal-dot result; each cached edge is the first original edge subtraction. Their extended lives are already within this cumulative charge. All remaining numerical expressions are original expressions in the same order, except the duplicate lower triangle, which now shares canonical immutable Fraction values. Multiplication/shape bounds are symmetric in the two indices, so each copied value is covered by both original output slot bounds. The returned graph retains the original three independent row lists and nine scalar references.

There is no lookup table, cross-call state, optional cache lease or new retained container. The output lists replace the old nested-comprehension lists one for one; an edge tuple replaces an already generated edge tuple. A fixed handful of local references stays inside the original fixed container/frame allowance (`80*N+128` container units), without changing its count. The original full plan, scalar-operation audit and maximum-expression allowance are unchanged. Retained-value r4 deliberately counts aliases repeatedly, so shared off-diagonal values cannot evade its admission. The prototype's fixture-only 65 KiB extra lease is **not** transplanted. There is no new general admission mechanism and no smaller reservation.

Numerical source verification occurs after the predecessor's metadata admission and before the original full-plan reservation. It bounds each source read to 64 KiB and reads one helper at a time within the existing fixed source buffers. A changed file or replaced numerical callable refuses. The original START/runtime gate remains in `M.admit`; no production fence was bypassed or edited. Extra successor source checks mean its precise elapsed saving cannot be inherited from the measured prototype; the subsequent actual-source comparison included these checks and was 6.001% slower, so it is not adopted.

## Focused checks and boundaries

`check_functional.py` SHA256 `bd05f15b48b5bdc757985fc223520e0f0a823239577c339f50676ed16972b091`; `RESULTS-r1.json` SHA256 `09bd1d47220b444a9768188f75eb9a7b7da7365b654deb93c9802b2c7ebb7427`.

PASS: four exact shapes (triangle, rectangle, reverse orientation, tiny tilted face far from origin); canonical values, plan content/full charge, polls and peak reservation agree. Thirteen controls cover six invalid geometries, three cancellation positions, one-byte-short full-plan refusal, changed source, replaced callable, and retained-transfer failure. Real native leases stay charged while an escaping error lives and drop after traceback release; successful owners reject a borrow after close. Actual selected backend, M1/M4 owner factories, counted-retention r4 and WorkBudget execute. Imported functional binding and its prescribed-power `_face` consumer pass. Focused Ruff F821/F841/B905 is clean. Those focused correctness controls added no timing, worker or science run; the later separately admitted actual-source comparison is recorded above.

The test uses the frozen source loader and an **explicit component dependency injection** for geometry START's private source fence; it authenticates selected component files instead of claiming the public private-runtime graph is coherent. Bounds/parallel dependencies are import-only shells to verify the complete functional module's binding, not exercised workers or a certified non-power face. The production successor itself contains ordinary imports and retains the real predecessor fence. These checks do not qualify the full private runtime, complete non-power reconstruction, forward issuer or checkpoint consumers.

Run the bounded check with the selected Atlas interpreter (no benchmark mode):

```text
PYTHON -B check_functional.py --repo ABSOLUTE_CHECKOUT --testing FROZEN_FUNCTIONAL_TESTING_DIRECTORY --output NEW_RESULT.json
```

## Exact receiving change still needed

Forward r13 currently imports `private_heat_functionals_kernel_r5 as FUNCTIONS` at60 and invokes it for initial reconstruction at291 and refinement at325. A receiving successor must bind `private_heat_functionals_kernel_40b_r1` there, preserve both call sites and update actual transitive code/source/default identities in native issuer r13 before routing calls to it. Joined/checkpoint/restoration pins must follow that new generation; do not relabel existing saved evidence. The functional successor's MOMENT binding is implemented, but no live forward/issuer import was changed here.

Keep current selected dispatch and parallel worker pins untouched until their receiving qualification is complete. C2's same-face preparation, C13 triangle-sum storage and C14 worker-generation caches remain outside this implementation. Selected/frozen source files, measured artefacts and orchestration were not modified. H5a and all individual/scientific/full-interval holds remain unchanged.
