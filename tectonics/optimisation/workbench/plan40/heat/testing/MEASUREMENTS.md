# Heat candidate component measurements

**MEASURED, 23 October 2026. WORKING NON-CANON.** All 20 source-bound candidate arms passed their declared checks. These are short, synthetic component comparisons, not whole-heat or IV timings. The later source implementations have distinct identities; this table measures the frozen experimental arms and does not establish their deployed performance.

Times below are the median of the complete recorded arm samples in milliseconds; each row retains its actual batch size. Saved time is baseline minus candidate, so negative means slower. Different rows are not comparable workloads and their percentages must not be added. Small differences and overlapping short samples are not robust production savings.

| Candidate | Workload | Baseline ms | Candidate ms | Saved ms | Saving |
|---|---|---:|---:|---:|---:|
| C1 | 5 functional calls | 2.474550 | 2.922350 | -0.447800 | -18.096% |
| C2 | 12 functional calls | 10.408800 | 16.721100 | -6.312300 | -60.644% |
| C3 | rank 20, ordinary, 1 calls | 6.222450 | 5.823300 | +0.399150 | +6.415% |
| C3 | rank 4, ordinary, 4 calls | 1.340650 | 1.246550 | +0.094100 | +7.019% |
| C4 | rank 20, ordinary, 1 calls | 6.137250 | 5.993550 | +0.143700 | +2.341% |
| C4 | rank 4, ordinary, 4 calls | 1.201300 | 1.271350 | -0.070050 | -5.831% |
| C5 | rank 20, ordinary, 1 calls | 6.200400 | 5.179750 | +1.020650 | +16.461% |
| C5 | rank 4, ordinary, 4 calls | 1.252750 | 1.449400 | -0.196650 | -15.697% |
| C6 | 3 solve/finish calls | 0.763700 | 0.776300 | -0.012600 | -1.650% |
| C7 | 3 solve/finish calls | 0.125600 | 0.130400 | -0.004800 | -3.822% |
| C8 | 3 solve/finish calls | 7.072900 | 6.702000 | +0.370900 | +5.244% |
| C9 | 3 solve/finish calls | 0.313100 | 0.319100 | -0.006000 | -1.916% |
| C10 | 3 solve/finish calls | 4.851200 | 4.773600 | +0.077600 | +1.600% |
| C11 | rank 20, append, 1 calls | 23.458200 | 57.040400 | -33.582200 | -143.158% |
| C11 | rank 20, mismatch, 1 calls | 23.187950 | 57.791600 | -34.603650 | -149.231% |
| C11 | rank 20, no-funding, 1 calls | 23.045400 | 23.175450 | -0.130050 | -0.564% |
| C11 | rank 4, append, 4 calls | 2.282250 | 3.658000 | -1.375750 | -60.280% |
| C11 | rank 4, mismatch, 4 calls | 2.358500 | 3.621950 | -1.263450 | -53.570% |
| C11 | rank 4, no-funding, 4 calls | 2.376150 | 2.393650 | -0.017500 | -0.736% |
| C12 | 5 functional calls | 4.340300 | 4.689800 | -0.349500 | -8.052% |
| C13 | 2 functional calls | 4.535250 | 4.470700 | +0.064550 | +1.423% |
| C14 | 4 functional calls | 2.195900 | 2.323550 | -0.127650 | -5.813% |
| C15 | rank 20, ordinary, 1 calls | 6.126750 | 7.279550 | -1.152800 | -18.816% |
| C15 | rank 4, ordinary, 4 calls | 1.324300 | 1.319500 | +0.004800 | +0.362% |
| C16 | rank 20, ordinary, 1 calls | 6.876000 | 6.613700 | +0.262300 | +3.815% |
| C16 | rank 4, ordinary, 4 calls | 2.024650 | 1.970200 | +0.054450 | +2.689% |
| C17 | rank 20, ordinary, 1 calls | 6.112250 | 11.790900 | -5.678650 | -92.906% |
| C17 | rank 4, ordinary, 4 calls | 1.221100 | 2.362600 | -1.141500 | -93.481% |
| C18 | 3 solve/finish calls | 0.298500 | 0.287000 | +0.011500 | +3.853% |
| C19 | 3 solve/finish calls | 9.160700 | 9.205000 | -0.044300 | -0.484% |
| C20 | 3 solve/finish calls | 1.552300 | 1.744900 | -0.192600 | -12.407% |

## Measurement boundary

Functional samples use three alternating ABBA/BAAB blocks, six samples per arm. Certificate samples use four counterbalanced pairs, with rank 4 and rank 20 at 320 bits; C11 retains append, mismatch and no-funding cases separately. Solve/finish samples use three alternating samples per arm, each with three component calls. Setup, optional ownership/cache construction, original guards, fallback and retirement remain within the disclosed changed-component boundary. Source verification and result comparison are outside the arm clocks. Source extraction, adapter and instrumentation limitations remain in each raw record and the [coverage table](README.md).

The actual successful payload occupied about six seconds; the outer tracked run occupied about eight seconds. Its sampled supervisor-plus-descendant RSS peaked at 248,606,720 bytes and free physical memory stayed at or above 7,758,573,568 bytes. All 24 guard samples completed, spending 0.0110081 seconds in sampling; no guard trigger occurred and both owned trees reached zero members. Sampling does not bound between-sample spikes. These physical observations are separate from per-arm logical reservations and are not assigned to individual candidates.

Native import/build/self-tests are separately reported in the certificate record, rather than included in a repeated warmed component sample. The process used one CPU affinity and native thread caps of one; this is not a worker benchmark.

## Source and raw evidence

The raw synthetic records below are byte-identical copies of the successful outputs, including every sample, workload/source identity, accounting observation and declared limitation. They contain no local absolute paths. The private orchestration receipt and queue records are not public substitutes for these source-bound records.

- [functional raw measurements](functional/MEASUREMENTS-r1.json), SHA-256 `9b825953f92e734dd5a42dd517e36ec72ad01ee1b52a1700b4eb2d9f8e97f294`; executable SHA `50b834caa8c5bf01156909ec96f49afdeace2df9e8f3fff30ff5cef879c20147`.
- [certificate raw measurements](certificate/MEASUREMENTS-r1.json), SHA-256 `e2266ec5bea52e373e2f5058357c57b6fd4456f96a2fbdf1cba29be1d3fd1d5d`; executable SHA `ba7dda0d0565f2fee86d38b07e098e921253987b93da22003e85546a1449e392`.
- [solve-finish raw measurements](solve-finish/MEASUREMENTS-r1.json), SHA-256 `6066340af5920727697fbbd7a0c1e1306af4c4e698dbe029866803cae991e918`; executable SHA `b25cc0bf30933927bbbeb5eed4621b75241fb1ddd7b89dd288deb577a3700c1a`.

Selected source-map SHA-256: `ce77c8f2922e0d8780e241ba9204e775388fa093935968eaee7c577606baaccc`. The measured request is `b793d9a074bdf1f6df1360d46e0289d5b7d7e6a157670ae16c8c22427960d0ba`; its exact checked numerical entries are included alongside these results. Public source correspondence does not authenticate historical private runtime/checkpoint bindings.

## Implementation selection

C3 signed-zero products and C8 exact owner-unit scaling are selected for bounded additive source implementation: they avoid speculative retained caches and preserve existing inventories. C3 improves both recorded ranks (6.415% at rank 20, 7.019% at rank 4). C8 improves its median by 5.244%, with overlapping samples and only two of three pair wins, so the claim remains modest component evidence.

C1, C2, C6, C7, C9, C11, C12, C14, C15, C17, C19 and C20 are not adopted from this batch because their measured main-case medians regress. C15 is near-flat at rank 4 but slower at rank 20. C11 also regresses on mismatch and no-funding cases; its Python continuation does not qualify native continuation.

C4 and C5 improve rank 20 but regress rank 4. C5 also retains additional accounted memory, so its 16.461% rank-20 saving is not a general win. C10 and C18 show small positive fixture medians while retaining unqualified production ownership/cancellation/issuer seams. C13 and C16 show modest positive medians; their disposition depends on whether the real successor can preserve ownership and imports without disproportionate new machinery. No extra timed run, default enablement or blanket implementation of positive percentages is implied.

Implementation review covers the completed actual source batch and its supporting checks. Measurement preparation, execution and interpretation need no separate reviewer approval. Existing IV, worker, source and scientific holds remain.

The later [actual-source comparison](../implementation-r1/MEASUREMENTS.md) now
qualifies the changed entry points separately: C3 is mixed by size, C8's owning
receiver saves about 1.339%, and C13 is 6.001% slower and not adopted. C16 retains
the reference because its small mixed gain does not justify a new attempt owner.
The prototype table above remains unchanged evidence, not the implementation
performance claim.
