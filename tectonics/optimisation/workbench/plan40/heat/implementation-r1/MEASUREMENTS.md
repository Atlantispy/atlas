# Actual source implementation measurements

**MEASURED, 23 October 2026; WORKING NON-CANON.** These results measure the complete additive imported source/receiver versions, including their own source checks and native ownership. They supersede prototype percentages for these implemented entries. They are short synthetic component samples, not full-IV timings, production occurrence rates or scientific acceptance. Positive saved time means faster.

| Candidate | Complete component | Baseline ms/call | Successor ms/call | Saved ms/call | Saving |
|---|---|---:|---:|---:|---:|
| C3 | solve_physical, rank 4 | 0.306687 | 0.320937 | -0.014250 | -4.646% |
| C3 | r3_attempt_export, rank 4 | 0.493525 | 0.491525 | +0.002000 | +0.405% |
| C3 | solve_physical, rank 20 | 6.009200 | 5.720750 | +0.288450 | +4.800% |
| C3 | r3_attempt_export, rank 20 | 6.765100 | 6.539150 | +0.225950 | +3.340% |
| C8 | complete owning assembly receiver | 4.492133 | 4.431967 | +0.060167 | +1.339% |
| C13 | native polygon/source/retained owner | 2.541587 | 2.694100 | -0.152512 | -6.001% |

Each row normalises every raw sample by its recorded complete-call count, then takes the median. C3 uses four counterbalanced pairs; C8 uses three alternating samples per arm with three calls/sample; C13 uses three ABBA/BAAB/ABBA blocks, six samples/arm and four calls/sample. Every raw sample, including outliers, remains in the linked records. Different rows must not be added or treated as a combined runtime.

## Disposition

- **C3: retained source candidate with mixed performance.** Rank-20 full solve and complete r3 attempt/export improve in this fixture; rank-4 solve regresses and its full attempt is effectively flat. No general rank threshold or production activation is inferred from two synthetic sizes. The full source/native successor is reviewable; later selection needs the actual receiving workload and explicit source generation.
- **C8: retain the small additive source/owning receiver implementation for review.** All three paired batches favour it, but the absolute saving is about 0.060 ms/call in this fixture. Both arms use the same new public portability binding and original conservative admission; the only arithmetic difference is exact owner-unit scaling. No whole-IV saving follows.
- **C13: do not adopt.** The real successor is about 6.001% slower when source verification/native plan/retained transfer/close are included. Its code, checks and failed performance outcome remain as an explicitly unselected experiment. The earlier 1.423% prototype reduction is not an implementation saving.

The C3/C8 actual imported consumer controls and all declared exact outputs, accounted-memory observations, refusals, cancellation and failure-custody checks remain supporting implementation evidence. C13 retains its explicit symmetric START component injection; it does not qualify a full private runtime, non-power face, worker or checkpoint. None of these candidates is selected by the frozen current runtime.

## Exact evidence

- [C3 all raw samples](certificate/ACTUAL-MEASUREMENTS-r1.json), SHA-256 `f64dca6897ce94ddb04f1e7d78951ccd5fb4d52ec4ec3a2b910bbed29c987f98`; adapter `9d1be5f19a2d4b18917ec4b320de677df9c8d3523186c879a5fde9a8102ecf5e`.
- [C8 all raw samples](solve-finish/ACTUAL-MEASUREMENTS-r1.json), SHA-256 `5f8bfa72e15f647c4abf3b950071629807db7433c535a82b2b80bd71561d59e9`; adapter `00804cf8465e9f66ecfb8dbe6f6116176543ea2f6584286c1d33b4c16f938960`.
- [C13 all raw samples](functional/ACTUAL-MEASUREMENTS-r1.json), SHA-256 `5fb5429a2caa65023b6e19956600675847a80392bb5a3ab341550963886ebd3c`; adapter `637e04c01d57faa50eacd6f725c86f56233a56a1f9ff8e3fa5332e903019efc5`.

The raw copies are byte-identical. Scoped Git attributes preserve their exact JSON bytes, including Windows newlines. Source generation is bound in [SOURCE-GENERATION.json](SOURCE-GENERATION.json); the original selected map remains unchanged. Native module import/build/self-tests are reported separately from warmed C3 component calls.

The guarded payload occupied about 4 s and the outer tracked attempt about 7 s. Eighteen 250 ms guard samples recorded aggregate supervisor/descendant peak RSS239,751,168B, minimum physical free12,767,072,256B and0.0083557 s sampling time. No trigger occurred; inner and outer trees reached zero members. These physical observations are separate from logical per-arm accounting and do not bound between-sample spikes.

Implementation review/integration/final acceptance/publication remain separate from this completed supporting measurement. No testing-review approval, worker dispatch, production default, full interval or scientific acceptance is implied.
