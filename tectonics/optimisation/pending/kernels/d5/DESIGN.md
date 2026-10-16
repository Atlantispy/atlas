# D5: Fraction -> gmpy2 mpq in the wall-measure kernels (design r1, 16 Oct 2026 15:35)

Owner of the target file: Geometry ("Geometry speed and parallel workers"); it reviews this design.
Shared with Pressure ("Pressure speed and pose width"), whose P4 (mpq jets in `_jet_mul`) should use the
same primitives, so there is one implementation. Author: "Exact kernels and parallel admission" (T/ck).
Bar: numbers identical, D-b only (source/runtime digests change, nothing else). Twin code lives in new files;
the existing files gain only a guarded hook. No geometry or pressure file is written by me.

## 1. Where the time is (q14 deep profile, 49 IV2 interfaces, 1,087 profiled CPU-s, MEASURED, profiler-inflated)
| function (final-f2 line) | cum s | caller | note |
|---|---|---|---|
| W._clip2 (wall_measures:119) | 43.5 | differential_geometry._moving_interface_leaf (265,672 outer calls; recursion inside the lease) | V._work builds Fraction copies of every coordinate that _clip2 never uses |
| W._rotated_normal (:58) | 42.0 | W._pose_vector <- _ray_box (27.2), _constraint_pose (15.6) | Taylor loop, one V._work lease per step |
| W._line -> O._dot (:191) | 16.9 | the same leaf | 3 dot products, each `sum(..., Fraction(0))` |
Together about 102 s (9.4% of the profiled stage). Fraction entry time from these modules: wall_measures 55.0 s,
volume_overlap 30.1 s (_dot/_cross), integration_volume 7.1 s (V._work's copy tuple). math.gcd: 58M calls,
~1 us each, so the numbers are modest and per-operation Python overhead dominates. mpq removes that overhead
(~0.1-0.2 us per operation against ~2-3 us); boundary conversions are the cost.

## 2. Precedents and their differences (read-only)
- integration_exact_gmp (reviewed GMP-resident twins of clip/volume/projection): gate `_resident()` (gmpy2
  backend selected AND every reference kernel object still the loaded one, so instrumentation sees every call);
  `_native` (Fraction/int only, else VolumeError); `_exact` (Fraction(int(n), int(d)), re-runs gcd);
  `_work` (V's amount and category, then a 2**27-bit CEILING check after the reserve); `_settle` +
  NATIVE_RETAINED surcharge for natives that outlive a step (gmpy2 recycles blocks up to 64 limbs).
- WP23 (differential_geometry 1046-1190): imports gmpy2 directly, so it runs on mpq even under
  ATLAS_EXACT_ARITHMETIC=python (bypasses the backend contract "python never imports gmpy2"); V-identical lease
  without the ceiling; natives retained across Taylor steps with no surcharge. Not copied here; flagged to Geometry.

## 3. Shared primitives (one new module, used by D5 and P4)
New file `integration_exact_twin.py` (name for Geometry to choose), importing exact_gmp's constants so there is
one source of truth:
1. `active(reference)`: X.library() is not None (so `python` and an unavailable gmpy2 keep the reference route)
   AND each object in `reference` is the loaded one (the _resident rule: wrapped/replaced kernels, V._work,
   O._dot/O._cross, Q keep the reference route). Decided once per operation, never retried on the other route.
2. `native(v)`: exact_gmp._native (int/Fraction only). A type guard before entry sends anything else (floats,
   bools, subclasses, non-tuples, wrong lengths) to the unchanged reference function, so its errors are its own.
3. `fraction(q)`: `Fraction._from_coprime_ints(int(numer), int(denom))` (mpq is canonical with a positive
   denominator, as Fraction is, so no gcd); fallback `Fraction(int(n), int(d))` if the private API is missing.
   Always a NEW Fraction (pickle memo structure is preserved: the reference never shares result objects).
4. `lease(values, budget, *, pairs=0)`: the exact V._work amount (65536+128*bits+256*len+256*pairs) in
   'i03-physical-volume', with `bits` from V._bits of the REFERENCE-typed objects (an int n counts n.bl, its mpq
   n/1 would count n.bl+1), no Fraction copy tuple, then exact_gmp's CEILING check. The ceiling cannot refuse
   anything the reference admits under our limits: 2**27 bits reserve > 16 GiB, above the 12 GiB RSS guard and
   the 16 GiB logical ceiling, so the reserve refuses first (stated in the proof, tested at the boundary).
5. Retained natives: policy below (section 6), one rule for both chats.

## 4. T1: `_rotated_normal` twin (whole Taylor loop native)
Guard: the reference's own `exact_scale` condition (middle is Q; normal and omega are 3-tuples of int/Q) and
`active(...)`. Pre-loop values (derivative, norms, x, target) are computed natively; the early return keeps
`normal` itself and a new Q(0). Each step: `arena.work(64)` then the lease, in that order, as the reference.
Lease bits: omega and middle from the original objects (computed once); term and major from the originals at
step 0 (norm_n = max(map(abs, normal)) on the originals, first of equals) and from the natives afterwards (the reference's term/major are Fractions from step 1, whose bits equal
the mpq bits). total, term, major, ratio and tail stay native; out: `tuple(fraction(t) for t in total)` (or the
original `normal` objects if the loop never runs) and `fraction(3*tail + half*sum|derivative|)`. A refusal or
work-unit stop happens at the same step with the same exception; nothing partial is returned.

## 5. T2: `_clip2` twin (per call) and W._line
Guard: line a 3-tuple of exact Q (so the reference's signs and `f` are Fractions, never int/int floats); poly a
tuple of 2-tuples of int/Q; `active(...)`. With an arena: the lease from the reference objects (no copy tuple),
then the body natively. Signs, min/max, `sp*sq < 0`, `f = sp/(sp-sq)` and the new points are native; kept
vertices are the ORIGINAL point objects; new points are new tuples of new Fractions; dedupe `p != out[j-1]`
is decided on the natives in the same order; `poly` itself is returned when every sign >= 0, `()` when all
<= 0 or fewer than 3 points remain. Identity relations, types and pickle bytes therefore match. W._line twin:
the three dots and the offset natively, three new Fractions out (O._dot's `Fraction(0)` start makes every
coefficient a Fraction, which the twin reproduces). Natives never outlive the call (no surcharge needed).
T3 (later, Geometry's call site, after D1-D4): keep the whole `_moving_interface_leaf` clip chain native
(convert `original` and each line once, one lease per clip from tracked reference bits, native _integral);
larger gain, but it changes Geometry's call structure, so it waits for their D1-D4.

## 6. Retained-natives policy (decision for Geometry; one rule for D5 and P4)
| option | what | cost | note |
|---|---|---|---|
| A (recommend) | exact_gmp's rule: natives kept across steps are _settle'd, the surcharge over the reference allowance reserved in NATIVE_RETAINED (only adds) | ~1 us per retained value per step; T1 holds ~8 | consistent with EXACT_ARITHMETIC_BACKEND.md; can refuse earlier, never later |
| B | one fixed per-operation NATIVE_RETAINED bound (count x 1,056 B) without _settle | cheapest | unsound if a small value sits on a block wider than the bound (add's unreduced product) |
| C | WP23 style: no surcharge | none | under-books retained native blocks |
T2 and W._line keep nothing native after return, so the policy only touches T1 and P4's jets.

## 7. Proof plan (before any queue ticket; review-before-queue applies)
1. Capture real calls (small lane, 1 core, my own process wraps W._clip2/_rotated_normal/_line locally; no
   global hooks): one IV2 deep interface on final-f2 -> CK/d5/capture.
2. Replay every captured call through reference and twin: result pickle bytes (protocols 2-5), types (deep),
   identity relations (`is poly`, kept vertex objects, shared objects), exceptions (type + text).
3. Ledger trace: a recording budget/arena logs reserve(amount, category) enter/exit and arena.work(n) in order;
   i03 sequences identical; NATIVE_RETAINED appears only in the twin and only adds.
4. Fuzz: int/Fraction mixes, zeros, huge (10^4-bit) values, empty/1-2 point/duplicate/collinear polys, exact-zero
   signs, zero line coefficients. Mutants that must be caught: no dedupe; new tuple instead of `poly`; int instead
   of Fraction for integer values; step-0 bits from mpq; missing/misordered arena.work; shared result object.
5. Backend: ATLAS_EXACT_ARITHMETIC=python and gmpy2 absent take the reference route (subprocess test).
6. One refuter on the exact code; then a q11-style D-b parity ticket (IV1 all, IV2 sample, IV2 deep; harness r5
   with a D5 runtime pair, ~25 min / 1.0 GiB PROJECTED) after RESUME.

## 8. Expected gain and interactions
| what | before | after | measured on |
|---|---|---|---|
| T1+T2+_line share of the IV2 deep geometry stage | ~102 of 1,087 profiled CPU-s (9.4%) | ~3x faster on those calls -> ~6% less (component, not interval) | PROJECTED from q14; prototype on captured calls next |
- (c) bounding the pose width (Michael's call; Pressure's (b) dyadic pose): smaller numbers make Fraction
  cheaper and shrink this gain; measure on both if (c) lands.
- Geometry's D1-D4 change these call sites and counts; T1/T2 are leaf twins independent of them; T3 waits.
- Later-step impact: every interval's wall/interface geometry runs these kernels; cache keys already differ
  by backend (exact_arithmetic contract), so D-b only.
- Next-interval capacity: no guard or cap changes; the twin can only refuse earlier (surcharge), never admit more.

## 9. Agreements so far
- 15:4x Pressure: the primitive set fits P4 (not scheduled; P1 first after RESUME). Add a native twin of
  pressure_coupling._dyadic_outward (the same floor/ceil and bit count) to the shared module, so the rounding has
  one source. Policy A suits their jets. Their pose-width (b) (T/ps/width/DESIGN.md) rounds in W._pose_vector
  after each _rotated_normal step with delta > 0: text disjoint from T1, stacks in either order; round_to takes
  T1's new Fractions. With (b), T1 operands are dyadics of <= 32+2L+12 bits: measure T1 both ways.
