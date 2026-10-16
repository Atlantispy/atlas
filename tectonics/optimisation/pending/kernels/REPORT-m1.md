# Compiled exact kernels: milestone 1 (draft, 16 Oct 2026)

Brief: atlas/.atlas-dev/compiled-kernels-20261016-brief.md (backlog item 3, WP24, heat option H3).
Work folder T/ck (STATE.md, OPTIONS.md). Nothing installed or downloaded; no git writes; nothing in .r44-env.

## 1. Inventory (read-only)
See OPTIONS.md. Key facts: no C compiler anywhere; numba 0.65.1/llvmlite 0.47.0 already pinned
runtime dependencies; gmpy2 2.3.2 bundles MPFR 4.2.2/GMP 6.3.0 DLLs, headers and import libs;
no decimal C API in Python 3.12.

## 2. Ranked hot functions (existing profiles; profiler-inflated)
See OPTIONS.md table. Heat W4: certification interval dot 28% of worker time (after H1 accounting
43%, which the heat chat owns). Geometry IV2 interfaces (WP23 base): Q2 Decimal-80 jets about 45%
(q2_directed module self 24%, Decimal multiply/add 12%, any/min/max 12%); 31% of interval products
take the four-corner zero-endpoint path. Composed base (q14-smoke-r1, 4 interfaces, workers6-r6, no
G-PY, 107.6 s self, MEASURED): q2_directed family 57.5% (G-PY's target); next after G-PY are the
moving_face_moments.mul dispatch (7.9% self), Fraction + gcd (~10.7%), WP23 helpers (4.7%),
_admit_budgets (1.1%). Component shares, not interval gains; q14's 49-interface profile confirms.

## 3. H3: compiled heat interval dots
What: solve_enclosure's Gram, inverse defect, residual and eta dots and physical_bounds' dots run as
compiled batches (numba njit calling gmpy2's own MPFR DLL via ctypes); any decline runs r1's
unchanged expression. Transform layered on the heat chat's H2 outputs; one new pinned helper.
Hashes (r2): kernel d94fb79b, resources 1c557e98, helper 62c100cf (from H2 3be44650 / 8b451aa8).

Identity evidence:
| Check | Result | Label |
|---|---|---|
| Random batches (v1 36,249 dots; v2 3,000 batches) | 0 mismatches | MEASURED |
| Synthetic solves r1/H2/H3, 80 solves + physical, 4 precisions | 0 mismatches (5 Unresolved paths same) | MEASURED |
| Refuter fuzz 1,500 + Gram 400 (signed zeros, NaN/Inf, band edges, mixed precisions) | 0 mismatches | MEASURED |
| Import self-test vs seeded mutants | 8/8 non-equivalent rejected (3 RU-tie mutants provably equivalent) | MEASURED |
| W4 same-call proof h2 vs h3 arm in one ticket (arrays, result id, metadata) | q06 paused; compare arguments proven 21/21 (q06p2/proof.json) | — |
| Per-call replay of all real W4 certification calls (capture in q06) | pending | — |

q06 cost: each arm is the whole W4 control (q03 MEASURED 1,171 s / 1,304 s per arm, tree 1.03 GiB), so the
reviewed 6 arms + capture ~ 140 min PROJECTED (first booking ~20 min was wrong); 4-arm ABBA option ~ 100 min.

Speed:
| what | before | after | measured on |
|---|---|---|---|
| certification functions, synthetic 80 solves | r1 0.237 s / H2 0.235 s | H3 0.095 s (2.5x vs r1) | own fixture, one process, warm |
| W4 reconstruction worker CPU | H2 arm (q06) | H3 arm (q06) | genuine W4 call, ABBA |

Refuter (one agent) findings and fixes: precision 1 (gmpy2 makes p=1 values at 64 bits) -> declined;
a one-shot CancelledError swallowed by physical_bounds' fallback -> propagates; load/compile
failures other than ImportError escaped -> any failure selects the Python route; traps unchecked ->
contexts must equal Arithmetic's settings exactly; nogil liveness -> input tuples held; long batches
uncancellable -> blocks of 2**20 products with check() between.

Env cost: no new software. Per process: numba import + compile + self-test about 0.9-1.3 s CPU and
50-75 MiB (refuter-measured), paid once per worker; charged by the process meter to the caller's
ledger. Guards: the kernel hashes the helper and executes those bytes (RuntimeError on mismatch);
parallel_r1's worker file table covers the helper (private_heat_* in the candidate folder);
build_info records numba/llvmlite, gmpy2/MPFR, MPFR DLL sha256, compiled-assembly sha256.

## 4. Geometry options
G-PY (pure Python, D-b): per-coefficient interval classes in the moving-face Decimal jet product,
inlined mul/add, explicit first-of-equals for the zero-endpoint corners. Transform
transforms/gpy_q2_jets.py r3 (moving_face c5f2a123 -> 3e82a2be; workers6-r6 has the same input).
| what | before | after | measured on |
|---|---|---|---|
| jet mul / div (component) | 1.00 | 1.34x / 1.28x faster, 0 mismatches (600 mul, 300 div) | gpy-r3-check/test-300, MEASURED |
| one replay process peak (q11 TOTAL) | booked 2.0 GiB for 6 | 133 MiB (IV1 shard) / 149 MiB (IV2 deep) -> ~0.9 GiB for 6 | gpy-peak/*.log, MEASURED |
| 49 deep IV2 interfaces, CPU | 1,087 CPU-s (_Jets.mul 499 cum) | <= ~11% less | PROJECTED from q14 wp23r-prof-r1 |
Refuter (1 agent): 1 DEFECT, exception text only (non-tuple jets hit len() first; unreachable today) and
a zero-identity RISK (empty coefficients were equal new tuples, so pickle bytes differed). Both fixed in
r2; numbers were identical throughout (fuzz 67,868 pairs, 6/6 mutants caught). r2 re-check: repro 0
differ, fuzz 11,360 pairs 0 bad, identity + pickle 3,000 cases 0 bad (r1: 2,650 bad, so the check bites).
Delta refuter (2nd agent): 1 DEFECT, contract only (a J.zero replaced on the instance by a tuple subclass
or (sNaN, sNaN) was compared before its type was checked; nothing assigns J.zero outside __init__), fixed
in r3 (the zero must pass the coefficient test first). r3 re-check (gpy-r3-check): the refuter's
reproducer 0 differing (r2: 3), identity fuzz 6,000 0, fuzz 11,360 0, identity 3,000 0 (r1 2,650).
Parity D-b (IV1 all, IV2 sample, IV2 deep) is ticket q11 (paused 14:37). Harness r5 fails closed
(scripts/gpy_parity_check.py: shard exit codes, done rows, runtimes, package digests, empty/all-capped
stages; CAPS: no capped row at IV1/deep, IV2-sample caps re-run at 120 s on the deep lists or in stage
2b, and r3 checks that the deep stage replayed every deferred row; deep lists hashed). Replays run under
scripts/run1.py, not `timeout ... &`, which hid every shard from runq's tree peak (smokes s2/s3 recorded
0.03/0.02 GiB: UNDER-MEASURED). Proven 41/41 (q11p4/proof.json). Smoke s5 (r5, G-PY r3): all stages
PASS, 169 s, tree 0.19 GiB MEASURED.
Booking ~25 min / 1.0 GiB PROJECTED.

## 4b. Item 19: exact parallel initial metrics (per-world start-up)
What: route (1)'s 969 initial relative-error queries (serial, 1,002.5 CPU-s in adm1) computed ahead by
one-shot workers of the existing component session, adopted at their serial positions after the
cache-hit query checks; any refusal leaves the rest serial. Opt-in context pass; no pass = original path
(byte-inert: untransformed composed-r2 gives the same result signature). Transform transforms/initpar_r1.py
(3799958b) on five files + new module integration_initial_parallel.py (r2.2 5ffc7fb2: close() closes
the session first and is retryable, refuter D1 fixed; delta refuter 0 DEFECT); tree ck/ip8/src.
Proof ticket q19 held (pause): D1 reproducer on ip8 done (fixed; initpar/ip8_r1_close_retry.json); t8 and
smoke-s3 wait for RESUME.
| what | before | after | measured on |
|---|---|---|---|
| 40-query slice results + store bytes | serial | identical (pickle, JSON, store sha 0144a8fc); 40/40 adopted | initpar/t4, MEASURED |
| unmet answers (leaf ceiling 1000) | serial raises 2 | refused, pass closed with a worker running, same errors | initpar/t4, MEASURED |
| initial_metrics wall, 2 workers | 1,015 s | ~560-620 s | PROJECTED (simulate.py on adm1 order); proof ticket requested |
| initial_metrics wall, 6 workers | 1,015 s | ~220 s | PROJECTED; needs the 6-worker decision |
| memory during start-up | parent 354 MiB | + <= W x 384 MiB (child peak 182 MiB measured on slice) | MEASURED slice / envelope bound |
D-b: execution identity covers the new files, so item 7 pins and measurement-cache entries regenerate.

## 4c. Item 18 (packed coordinate keys): scoping, no CPU
W4 heat: Fraction hash/compare < 0.2%. Pressure stage: Fraction compares 14% (38.5 s cum) but from interval
_mul (pressure P3 covers it); _hull hashing 0.1 s; CartesianCell._vertices 13.8 s cum is recomputation
(memo candidate), not keys. Geometry (q14-smoke-r1, 4 interfaces, 107.6 s, MEASURED): all key-like self
time 1.3%, of which dict-key hashing/equality ~0.3% (Fraction __hash__ 0.07%, __eq__ 0.21%); the rest are
interval min/max compares (0.7%) and wall-measure _decode (0.17%). Packed keys would save < 0.5% while
changing order/digests (D-b): recommend closing item 18 unless q14's 49-interface profile differs.

## 5. Decisions (batched, with recommendation)
1. Adopt H3 into the heat chain after q06 passes: recommend yes if arrays/result id/metadata are D-b
   identical and the measured worker CPU gain holds.
2. Compiler install for a C/Cython route: recommend no; numba covers the heat case without new software.
3. G-PY: adopt after q11 parity is D-b clean (recommend yes; component 1.3x, no new software).
4. Item 19 worker bound 2 -> 6: recommend yes if the proof ticket is identical and the 2-worker gain is
   measured; 6 x 384 MiB = 2.25 GiB extra only during start-up.
5. Item 18 packed keys: CLOSED by the coordinator (D-l cell-order risk); was: recommend close (key hashing <= 0.3% geometry, < 0.2% heat; D-b churn for < 0.5%);
   the CartesianCell._vertices memo (pressure, 13.8 s cum) is a better small-optimisation lead.

Later-step impact: item 19 is per world start-up (run A, root reader, interval-1 reader), not per interval;
H3/G-PY act on every interval's heat/geometry work. Next-interval capacity: no guard changes; item 19 adds
memory only during start-up and closes before interval work.

## 4d. D5: GMP-resident twins of the wall-measure kernels (prototype, d5/)
Design d5/DESIGN.md r1 (Geometry reviews; Pressure agreed the shared primitives). Twins d5/twin.py r1, replayed on
34,230 real calls captured from 3 deep IV2 interfaces (d5/cap1; capture result-neutral, measure_sha = s5).
| what | before | after | measured on |
|---|---|---|---|
| identity: pickle 2-5 of (inputs, result), type shape, ledger + work traces | reference | 0 differing of 34,230, 0 fallbacks | d5/bench1, MEASURED |
| _rotated_normal / _clip2 / _line CPU per call | 72.7 / 81.3 / 33.8 us | 25.0 / 58.3 / 28.5 us (2.91x / 1.39x / 1.18x) | d5/bench1 ABBA x3, component, MEASURED |
| IV2 deep geometry stage | 1,087 profiled CPU-s | ~3.9% less | PROJECTED from q14 shares |
Pending: fuzz + mutants, backend test, T1 with/without pose rounding (b), refuter, D-b parity ticket after RESUME.

### 4d-2. D5 build: hooked runtime trees (d5-f2, d5-jets)
Shared primitives d5/src/integration_exact_twin.py (also for Pressure's P4: native/fraction/bits/lease/Retained/
dyadic_outward); twins d5/src/integration_wall_measures_gmp.py; transforms/d5_wall_hooks.py adds guarded hooks to
integration_wall_measures.py (d6b7d472 -> b5e01815; declined calls run the unchanged body); d5/build_tree.py.
Twins decline off the gmpy2 route, when any of 9 reference objects is wrapped (instrumentation sees every call), or
outside the exact types they reproduce. Added only: NATIVE_RETAINED surcharge (policy A, mean 14.9 KB per call).
| what | before | after | measured on |
|---|---|---|---|
| same-call identity on the installed runtime (d5/check.py) | reference module beside it | 0 differing: 48,170 real calls + 9,000 fuzz, both trees | d5/chkf, d5/chkj, MEASURED |
| fail-closed proof | - | 16/16 planted mutants caught; ceiling 2**27 boundary; dyadic 0/20,000 vs Pressure | d5/chkf, MEASURED |
| backends | - | python route and gmpy2-blocked: twins never used, imports as base | d5/chkf, MEASURED |
| D-b parity smoke (pinned checker) | jets-r1 / final-f2 | iv1 21/21, iv2 sample 36+1 capped->extra 1/1, deep 1/1 identical | d5-parity-s1, MEASURED |
| IV2 deep geometry stage CPU | 1,087 profiled CPU-s | ~3.9% less (prototype per-call ratios; build not timed) | PROJECTED |
Refuter r1: pending. Not done (light window): timing of the build and policy-A cost, T1 with/without (b), the full
6-process parity ticket. Later steps: every interval's wall measures; the primitives serve Pressure's P4.
Next-interval capacity: no guard changes; the surcharge can only refuse earlier, never later.
