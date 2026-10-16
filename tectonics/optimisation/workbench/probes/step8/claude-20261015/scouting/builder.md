I ran all the requested measurements. `summary.md` was not written because the harness blocks report `.md` files from subagents, so the summary is below. All numbers are in `result.json`.

**Provenance**
- The input file sha256 `5847e28a…` matches the census graph entry, and the census file's own sha256 `02f0a05a…` was verified.
- `record_tables.py` `229c6b7d…` and `mesh_tables.py` `3f3e06e3…` were unchanged before and after the run. Python 3.12.14.
- The run took 657 s with a peak working set of 1.78 GB.
- Every builder run reproduced the canonical bytes exactly (digest and length), including the whole graph against the census sha256.

**Slices differ from the brief:** `physical_measure_receipts` is an object with 48,391 keys, each a 64-hex string, not an array. The 58 non-receipt fields alone are 17.22 MB, so "non-receipt fields + N rows" slices cannot be 1–15 MB. I used:
- **A:** 31 scalar fields plus the first N receipts, at 1/2/4/8/15 MB.
- **B:** the non-receipt fields only.
- **L:** B plus 550 or 2,195 receipts.
- **D:** the whole graph, with `MAX_BUILD_BYTES` raised in-process only as a probe device, then restored.

No A, B or L slice was refused under 256 MiB.

**Cause of the original refusal:** `record_tables.py:304-306` interns all 48,391 receipt keys before reading any row value. That books 48,391 × 3,072 = 148,657,152 B, 55% of the cap. The refusal came 1,807,740 B into the rows; the canonical prefix before receipts is 14,472,375 B.

**Whole graph (D, measured): booked vs real new bytes**

| Category | Booked | Real | Ratio | Per item (booked vs real) |
|---|---:|---:|---:|---|
| tokens | 169.58 MB | 9.38 MB | 18.1× | 3,057 vs 169 B per token |
| nodes | 169.81 MB | 45.39 MB | 3.7× | 1,445 vs 386 B per node |
| integers | 31.21 MB | 8.16 MB | 3.8× | |
| shapes | 3.59 MB | 0.45 MB | 8.0× | |
| pairs | 3.55 MB | 1.49 MB | 2.4× | |
| ids | 3.03 MB | 1.28 MB | 2.4× | |
| transient scratch peak | 6.25 MB | about 11 KB | | |
| **after add** | **386.86 MB** | **70.48 MB** | **5.49×** | |

- The token-index keys are all input strings: 5.80 MB pinned, 0 bytes newly allocated. The ID keys pin a further 1.24 MB.
- `finish()` books another 62.29 MB, for 449.04 MB in total. It produces 15.39 MB of arrays; its real peak is 29.43 MB above its start.
- Real pack high-water is about 99.9 MB, 4.5× below booking and about 37% of the 256 MiB cap. Allocator rounding is not measured.

**Scaling**
- A slices (measured fit, r² ≥ 0.995): 7,872 B per row booked vs 1,542 B per row real.
- D minus B (measured): 5,818 vs 852 B per row.
- The booked-to-real ratio is 4.31–4.97 for A slices, 3.60 for B and 3.67–3.84 for L.

**Whole-graph projection**
- Extrapolated from B plus the A slope × 48,391 rows: 486 MB booked, 104 MB real.
- Measured D: 387 MB booked, 70.5 MB real. The linear extrapolation overstates by 25% (booking) and 47% (real), because later rows deduplicate better.

**Decode charge**
- `_decode_charge` books 2,081,838,392 B against `json.loads`'s real 387,407,234 B (tracemalloc), a ratio of **5.37×**.
- Against RSS delta (418,496,512 B) the ratio is 4.97×. Against the tracemalloc peak during decoding (494,030,833 B) it is 4.21×.
- The charge splits as 4·len 20%, strings 28%, containers 22%, separators 30%.
- Per slice the ratio is 5.30–5.40×.

**Caveats**
- tracemalloc excludes allocator rounding; the decode's RSS-to-tracemalloc ratio of 1.08 is the only indicator.
- Untraced builder RSS deltas are unreliable because the heap reused memory freed earlier.
- 0.78 MB of cyclic garbage remained after the whole-graph build with gc disabled.
- During the run another chat changed `C/live_composite.py`, `C/spatial_record_recipes.py` and their tests. This probe did not touch them.

Files are in `C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10/fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1/probes/step8/claude-20261015/builder-probe/`:
- `probe_builder_memory.py`
- `result.json`
- `analyze_result.py`
- `decode_charge_terms.py`
- `probe.log`