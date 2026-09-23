# W01 Stage 8: obtained combined acceptance evidence

22 September 2026. Local unreleased working-tree result; WORKING NON-CANON.

**Technical result: PASS_SUPPORTED_WORKFLOW. Whole-W01 result: INCOMPLETE.**
S3C Earth-like partition acceptance remains REOPENED. R4.4 remains held/incomplete;
this assessment neither ran that campaign nor accepted its missing evidence.

## Executed check

```text
python -I -B tectonics/verify.py --w01
```

**71 tests passed in 54.571858800 seconds**, with zero failures, errors or skips.
The bounded profile was run once after the focused new-test development run.
Source inventory before/after matched exactly. No unexpected stderr diagnostics;
`git diff --check` passed (only Git's configured LF-to-CRLF notice).

| Selected gate | Tests |
| --- | ---: |
| Original representation and thermal limits | 20 |
| Initial inventories and unknown-value meaning | 4 |
| Supported workflow, geometry, history and recovery | 29 |
| New assembled Stage-8 witnesses | 6 |
| Shared execution invalidation | 9 |
| Acceptance-status distinction | 3 |

Runtime: Windows x86-64, CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1,
Shapely 2.1.2 and Numba 0.65.1. OPENBLAS/OMP/MKL/NUMBA thread environment values
were each 1. Recorded elapsed time is the unittest execution interval, not a
whole-world timing forecast or a full interpreter-start-to-exit measurement.
Full verifier JSON contains exact selected IDs and all observed source hashes;
its retained raw output SHA-256 is
`be938bda43b7d35739fc8b3ba4f85947d5a38ace089fe9f16374c33a98ae73d1`.
This is an evidence-file identity, not a scientific signature.

The separate first development execution of the six new assembled tests passed
in 15.022 seconds. It is not added to the final 71-test count. No unrelated full
Atlas regression, parameter sweep, long convection run or world generation ran.

## Independent assembled witnesses

- A northern hemispheric wedge crosses longitude 180 degrees and undergoes
  nonzero axial transport. With R=10 m, depths 0–2 m, reference width 10 m,
  initial volume is 244*pi/3 m3 and equivalent inventory is q=122/75 m.
  For two cells, speed 0.1 m/s, duration 0.25 s and inlet 2q, the independent
  upwind expectation is `[q*(1+0.01/pi), q]`; physical volume increases by
  q/4 m3. Stored/restored source, thermal provenance and material receipts match.
- Nonuniform MUSCL reference/native fields and cohort accounts agree using the
  retained material-case tolerances. Backend-specific execution identities are
  not incorrectly required to match.
- Changing inlet composition/reservoir, interval or spherical reference width
  produces distinct correct cache results, while equivalent physical inventories
  remain consistent under metric re-expression.
- Cancellation after one completed cached substep leaves the prior accepted
  workflow recoverable from its saved store. Resuming reaches the original
  endpoint; all temporary reservations release. A pure cached computation is
  deliberately not mistaken for a published accepted workflow state.
- During S5 sampling, prior preparation outputs have a live admitted lease;
  ownership transfers to the prepared plan and closes cleanly.

## Corrections and preserved boundaries

Two implementation corrections were required: admit forcing/cell/sample outputs
across preparation phases, and enforce the existing 4,096-cell wrapper limit on
restore as well as creation. No numerical kernel, accuracy tolerance, material
law, default scheme, dependency, runtime installation or step ceiling changed.
The added profile and three status checks prevent a technical pass being reported
as whole-W01 scientific completion. Existing W02/W03 and Stage-7 edits were kept.

These source changes create new execution identities. The original Stage-7
timing remains historical evidence for its measured bytes; it was not re-run or
advertised as a new Stage-8 speedup. Stage 8 reports verification time only.
The case's byte-budget checks are allocation-admission evidence, not sampled RSS
or a production-scale memory guarantee.

Stage 8's supported technical assessment is complete. Whole-W01 acceptance
remains open because independent complete outline/motion validation and the
remaining physical-formation evidence are not supplied by these tests. Initial
thermal data is not evolved heat; unrestricted spherical dynamics, W03 evolution
and geological/whole-world realism are not newly accepted. See the complete
[scope and gate explanation](../docs/W01_COMBINED_ACCEPTANCE.md).
