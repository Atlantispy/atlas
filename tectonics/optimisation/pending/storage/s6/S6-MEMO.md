# S6: H5 (heat fact reuse) decision memo, 16 Oct 2026

Read-only; code in R/composed-r2/helpers; scripts in T/so/s6.

## What H5 is
- **Pass loop:** `private_heat_forward_kernel_r13.py:_run`.
  - Pass 1 (l.285) covers all faces; each disjoint refinement group re-calls `FUNCTIONS.reconstruct(selected_faces, certification_precisions=offered)` (l.319). HIGH solve at l.367.
- **Facts:** in `private_heat_functionals_kernel_r5.py`:
  - `_prepare` decodes every cell and face on every call.
  - `_face` builds the prelude: moment, `B.support` over all observations, basis, about 40 observation rows of 20 exact rationals, gradient and target. It then calls `functional_bounds`.
- Pass 1 runs in workers. `functionals_parallel_r1.reconstruct_faces` starts and stops them on every call.

## Exact?
**YES**, keyed per call on the same payload object, boundary sets and k, and per face on the face id.
- The prelude and `_prepare` read none of the precision settings. All three calls pass the same objects.
- `functional_bounds` takes the precision ladder, so it is recomputed.
- Shell expansion follows exact incompatibility only, which is precision-independent.

Only census `seconds` and the ledger timeline differ.

## Trust boundary
- **H5a (reuse `_prepare`):** one process and one verified `advance` call. The prepared value is an owned local in `_run`.
  - Never a module-level cache (it would pin the 0.94 GB payload; the identity guard records upper-case module state).
- **H5b (reuse the per-face prelude):** pass-1 facts die with that call's workers. Reuse needs one of:
  - pipes carrying gigabytes, plus integrity checks on the data;
  - warm workers that keep each face on the same worker (item 9).

## Cost and payoff
**Where the r9 IV1 tail goes:**
- MEASURED: pass #2 took 16.1 s and pass #3 took 39.9 s.
- INFERRED from the IV1-size replay `replay-forward-full-r12.json`:
  - pass #3 holds assess (15.7 s), the HIGH solve (8.0 s) and intersect walks (about 2 s);
  - so the real reconstruct ceiling is about **28 s**, not 56 s.

**Inside those calls:**
- Replay calls: 25.1, 22.7 and 19.4 s for 27, 21 and 17 faces.
- Fit: about 10 s fixed per call plus 0.56 s per face. `_prepare` books 2.17 GB, then settles at 66.6 MB.
- W4 profiles (MEASURED): the prelude is 61% of `_face` and `functional_bounds` 39%.
  - Pass-1 workers: 554 s.
  - The parent's 7-face refinement: 5.33 s.
  - `_prepare`: 0.33 s per call.

**H5a:**
- Saves: 2 × T_prepare = **6-20 s per IV1 interval** (T_prepare is 3-10 s, unmeasured). About 4× that at 4× mesh, and less after H1.
- RAM: +66.6 MB held (about 270 MB at 4×). Two transient 2.17 GB bookings disappear. The heat peak (9.49 GB, LOW) is unchanged.
- Code: transforms of forward r13 and functionals r5. Nothing hex-pins functionals r5.
- Pins: forward r13 → `checkpoint_consumer_r10`, `joined_consumer_r6`, `restored_binding_r10`, `restored_binding_ram_context_r1`; also two r9 copies and `composition.json`.
- Risk: moderate (forward custody code).

**H5b:**
- Saves at most about 5-7 s.
- RAM: about 65 of about 5,000 faces are selected, only after assess, so all must be kept: **2.5-8 GB** at IV1, 10-30 GB at 4× (breaks the 12 GiB guard). Basis: 40.5 rows × 20 values per face, about 0.9 KB per coordinate, cubed.
- Code: H5a's files plus parallel_r1; risk high.

## Recommendation
- **H5b: DROP.** Exact, but gigabytes and a process crossing for about 5 s.
- **H5a: BUILD WITH CONDITIONS.**
  1. MEASURE `_prepare` + `_prepared_bytes` on a saved IV1 payload first (small ticket, about 1.2 GB).
  2. Ship it with the next forward successor (Steps 8-9, H4 or item 9) so the pin cascade is paid once.
  3. Keep the owner local, under its own category, and close it before FINISH. Lower-case names only.
  4. Reuse only if the payload `is` the same object and the boundary sets and k are equal; otherwise recompute.
  5. Proof: W4 same-call control (D-b), refinement rows and census equal apart from `seconds`, and one refuter.
