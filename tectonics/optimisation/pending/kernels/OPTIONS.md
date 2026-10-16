# WP24 compiled exact kernels: options (draft, 16 Oct; MEASURED / PROJECTED labels)

Exactness bar: identical numbers; D-b only (digests/pins change, every number and field byte-identical).

## Inventory (read-only, 16 Oct)
- .r44-env: CPython 3.12.14 (MSC v.1944 x64), Python.h present.
- gmpy2 2.3.2 / GMP 6.3.0 / MPFR 4.2.2 / MPC 1.4.1, limb 64; headers and import libs bundled
  in gmpy2/ and gmpy2.libs/ (mingw-built DLLs). `_C_API` capsule present.
- numba 0.65.1 + llvmlite 0.47.0: installed AND already pinned runtime dependencies
  (regional_multigrid3d: njit nogil, fastmath=False, cache=False; build info records versions and
  an assembly sha256).
- Absent: Cython, cffi, mypyc, setuptools, wheel, meson, ninja, pybind11, python-flint; no C
  compiler anywhere (no cl/clang/gcc/mingw, no Visual Studio, no Windows Kits).
- No decimal C API in 3.12 (libmpdec is static inside _decimal).

## Ranked hot functions (existing profiles; cProfile self/cum, profiler-inflated)
| Where | Profile | Hot share |
|---|---|---|
| Heat W4 workers (6 workers, 525.7 s) | G/evidence/heat-w4-p4w | accounting 43% (H1, heat chat); certification interval dot 28% cum (512,684 of 549,600 dots in solve_enclosure: Gram + inverse defect; 626 solves) |
| Geometry IV2 interfaces, WP23 base (28.6 s) | profile-interfaces-iv2-wp23-r1 | Q2 Decimal-80 interval jets 41% cum; Fraction 11% + gcd 5.5%; WP23 mpq helpers ~10% |
| RC1 IV2 endpoints (60 s) | profile-iv2-rc1 | Fraction 26% + gcd 8%; exact_gmp 21% (_clip, _noncollinear) |
| Admission (1,053 s) | admission-profile-r1 | Fraction 16%; exact_gmp 13% (_clip 166 s cum); reuse identity 11% |
| Composed candidate final-f2, hard IV2 | q07 cancelled (merged into q14); deep16 never ran | see q14-smoke-r1 below |
| Geometry 4 interfaces, workers6-r6 base, no G-PY (107.6 s self) | G/evidence/q14-smoke-r1/merged.prof | q2_directed family 57.5% self (q2 mul 21.0%, decimal multiply 14.8%, add 6.9% + 6.1%, is_zero 3.9%) = G-PY's target |

## Next kernels after G-PY (coordinator item 2, 16 Oct 14:35; MEASURED on q14-smoke-r1, cProfile-inflated)
Component self-time shares of 4 interfaces, not whole-interval gains; q14's 49-interface profile confirms.
| Rank | Candidate | Self share | Notes |
|---|---|---|---|
| 1 | moving_face_moments.mul (:69) dispatch over q2 mul | 7.9% self, 56.2% cum | callers moving_interface_moments:1039 (4.6 s), value (1.4 s), circular _dot; entry _clip 48.2% cum, value 27.9%, _normal 15.9%, _rotated 14.8%. Checked 14:55: :69 IS _Jets.mul, the function G-PY restructures (its Decimal route is what G-PY inlines), so most of this share is G-PY's own; the residual needs a profile with G-PY on (after q11) |
| 2 | Fraction + math.gcd (G2: gmpy2 mpq) | ~10.7% (gcd 3.6%, Fraction new/_mul/_add/forward) | spread: q2 point, volume, volume_overlap _cross, wall_measures, _rotated. Also RC1 endpoints 26%+8%, admission 16%. D-b only if every value and serialisation is identical |
| 3 | WP23 differential_geometry helpers | 4.7% self (_wp23_bernstein 1.5%, _wp23_product 1.2%) | _wp23_rotation_compute 8.1% cum; mpq already |
| 4 | resources._admit_budgets | 1.1% self, 2.2% cum | accounting, not a kernel; as heat H1 |
| — | builtins len/max/min | 5.6% | spread across callers; no single kernel |

## Options
| ID | What | Exactness | Env cost | Status |
|---|---|---|---|---|
| H3 | Heat certification interval dots in compiled batches: numba njit calling MPFR (gmpy2's own DLL) through ctypes; sign-class corner selection + Gram symmetry; Python fallback on any decline | D-b (numbers identical) | none new: numba/llvmlite already pinned; +~0.9-1.3 s CPU and 50-75 MiB per process (import + compile + self-test) | built, refuted, fixed (r2); W4 proof q06 pending |
| G-PY | Geometry Q2 jets: per-coefficient interval classes, inlined mul/add, explicit first-of-equals (transforms/gpy_q2_jets.py, c5f2a123 -> 3e82a2be, r3) | D-b | none | built; jet mul/div 1.34x/1.28x, 0 mismatches; refuter 1 DEFECT + RISK fixed in r2, delta refuter 1 contract DEFECT fixed in r3; harness r5 (deferral checked), smoke s4 PASS; parity q11 paused |
| G2 | Fraction -> gmpy2 mpq in remaining hot spots (endpoints, admission) | D-b if every value/serialisation identical | none | idea |
| G3 | Compiled exact_gmp._clip (numba + GMP mpz via ctypes) | D-b only if work-unit charges replicate | none new | idea, high effort |
| G1 | Compiled Decimal-80 directed replica (ideal exponents, libmpdec semantics) | high risk | none new, large | not recommended |
| C1 | Cython / C extension over gmpy2 C API or MPFR/GMP | — | needs a compiler install (MSVC Build Tools or mingw-w64) + Cython/setuptools: Michael's decision | not needed now |
