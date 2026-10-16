# Languages and toolchain for the certified generator's hot functions (plan only, 16 Oct 2026)

Reviewed 15:42 by "Exact kernels and parallel admission" (one pass, read-only). Its corrections are applied:
- figure provenance;
- K2 geometry reduced to 4–10% because of overlap with D5;
- the interface total is now 20–33%;
- K1 conditions: live context, first-of-equals, refusals;
- K2/K3 conditions: cross-CRT memory, 32-bit bit counts, shared work charges, the backend selector;
- L4 widened.

Thread "Release checks and language plan" (T/rm). Owner question (Michael): "I want to use the best languages for
accuracy and speed." This is a plan. Nothing was installed, compiled or run. Every figure is either:
- MEASURED: from an existing record, with its source named; or
- PROJECTED: with its method stated.

Estimates that no record backs are marked UNMEASURED.

Exactness bar throughout: **D-b**. Every number and field must be byte-identical; only digests and pins change.
Inputs:
- T/ck STATE.md, OPTIONS.md and REPORT-m1.md (the kernels thread, which is not re-derived here);
- the q14 profile `G/evidence/wp23r-prof-r1`: 1,087 CPU-s across 49 deep IV2 interfaces under cProfile;
- T/ps/STATE.md, T/hs/STATE.md and T/so/s7/S7-REPORT.md;
- `S/reuse.py` (`_runtime_record`, `_loaded_binary`) and `S/exact_arithmetic.py` (`runtime()`).

## 0. Answer in brief

1. **What makes the hot code slow is Python dispatch, not big-number arithmetic.** The profiled per-call costs show it:
   - a Decimal-80 multiply costs 0.39 µs (`Context.multiply`: 135.5 s over 349M calls);
   - the Q2 interval multiply's own Python logic costs 1.26 µs (197 s over 156M calls);
   - `Fraction.__new__` costs about 0.75 µs.

   The limb arithmetic inside libmpdec or GMP is a small part of each of these. So the gain comes from a compiled
   kernel that keeps values native across a whole jet product or leaf computation. It does not come from a faster
   big-number library. H3 already shows this on its own synthetic fixture (80 solves, one process, warm): 2.5× on
   the whole function, and 5.4–12× on the inner dot in noisy-machine microbenchmarks. Its W4 gain waits for q06.
2. **Best route for accuracy and speed: Cython, compiled ahead of time with MSVC.** It links the exact arithmetic
   libraries the Python reference already uses:
   - **libmpdec 2.5.1**, the copy inside `_decimal.pyd`, for the Decimal-80 jets;
   - **GMP 6.3.0 and MPFR 4.2.2**, gmpy2's own DLLs, reached through gmpy2's shipped C API, `gmpy2.pxd` and import
     libraries, for rationals, mpz and MPFR.

   The arithmetic is then identical by construction. The rules around it are not, and each kernel must replicate
   and prove them (§2, §4):
   - live context fields and flags;
   - the first-of-equals corner choice;
   - refusal on subclasses;
   - work-unit charges.
3. **Rejected for now:**
   - MPFR, Arb or malachite in place of Decimal-80. They change certified endpoints, which is D-c: a method change
     with a re-baseline.
   - Rust: it brings a second GMP copy and a heavy Windows toolchain.
   - C++ with FLINT: the Windows FLINT build is the obstacle.
   - python-flint: a new runtime dependency, and conversion at the boundary eats most of the gain on 13-term jets.
   - mypyc: it still needs the compiler and gains only on Python-level logic.

   numba stays where it already is (H3, the multigrid solver). It cannot reach libmpdec, and it costs
   JIT time, about 100 MiB per process and machine-specific code.
4. **PROJECTED gains after the Python-level fixes in flight:**
   - geometry interface CPU: about 20–33% less (1.25–1.5×), mostly from the Decimal-80 jets;
   - pressure stage: 13–24% less, if `_jet_mul` stays at 40% or more of the stage after P4. Re-rank after Step 19:
     the approved pose-width rounding (b) makes the operands small dyadic rationals;
   - admission: 8–12% of CPU from compiled `exact_gmp._clip`;
   - heat: no further speed beyond H3. An ahead-of-time (AOT) port only saves about 1.4 CPU-s and about 100 MiB per
     worker process.

   All of these need the plan Step 19 reprofile before any go/no-go.
5. **Decisions for Michael are in §6.**
   - L1: a compiler. Recommended yes, MSVC Build Tools 2022, but only after Step 19 confirms the residual.
   - L2: a language for each function group.
   - L3: scope and order. Rational pilot, then Decimal jets, then optional `_clip` and an H3 AOT port.
   - L4: an identity gap to close now, whatever L1 decides. Three things aren't pinned in the execution identity
     today:
     - `_decimal.pyd` (libmpdec);
     - `python312.dll` (a gap already documented in `_interpreter_binary`);
     - probably stdlib `fractions.py`.
   - L5: what is not adopted, and why.
6. **Outside the kernels (§7): no other part of Atlas is recommended for a rewrite in another language.** The
   rest of the time is already in compiled libraries, or it goes once the Python-level fixes land.

## 1. Candidates

Criteria are the coordinator's. "Our op mix" means millions of small exact operations at 80 decimal digits, or
small rationals, each wrapped in Python calls.

| Candidate | Exactness and determinism | Speed on our op mix | Windows toolchain | Desktop packaging | Identity pinning | AI-coder maintainability | Python reference kept | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Cython → C, linking libmpdec 2.5.1 + gmpy2's GMP/MPFR** | Same libraries and contexts as the reference, so D-b, given the conditions in §2 (live context and flags, first-of-equals, refusals, shared work charges). No host floating point in kernels. Rounding comes from libmpdec's context (Decimal-80) and MPFR's directed modes. | Removes the dispatch around each op. Leaf-level jets: 4–8× inner, 2–3× group (PROJECTED, §2). | MSVC Build Tools + Cython/setuptools in a separate build environment | One `.pyd` per module, cp312-win_amd64. No new runtime DLLs: it uses gmpy2.libs plus the vcruntime140 that CPython already ships. | Fixed binary. Hash the `.pyd` in `_runtime_record` binaries, plus a build record. | **High.** Python-like source, `cimport gmpy2`, typed loops. Most errors are caught at compile time. | Yes: a route selector with an import self-test (the H3 pattern) | **Recommend** |
| C via the CPython API + the same libraries | Same as Cython | Same as Cython, or slightly better | MSVC only | Same as Cython | Same as Cython | Medium. Hand-written reference counting and error paths are the classic bug source. | Yes | Use only for small glue (the libmpdec shim) inside the Cython modules |
| C++ (nanobind or pybind11) + GMP/MPFR/FLINT | Same as Cython, if the same libraries are used | Same as Cython | MSVC plus a FLINT 3 build on Windows against mingw-built GMP import libraries: hard | Adds the C++ runtime and FLINT DLLs | Same as Cython, plus FLINT | Medium. Templates and a CMake build. | Yes | No. Its only extra is FLINT, which we don't need (§1 python-flint). |
| Rust (PyO3 + rug, or malachite) | rug builds its **own** GMP/MPFR (gmp-mpfr-sys). The results are mathematically the same, but a second copy needs separate pinning. malachite-float is young and has no decimal type. | Same as C | rustup + MSVC link.exe, and MSYS2/MinGW for gmp-mpfr-sys (GNU target) next to an MSVC CPython. Heavy and awkward. | One `.pyd` with a static GMP | Fixed binary, plus a second GMP to pin | Medium-high for the code, low for the build | Yes | No. It is the heaviest toolchain and adds a second arithmetic stack for no gain. |
| Cython "pure Python mode" or **mypyc** | Same objects (Decimal, Fraction, mpq) and same calls, so D-b. mypyc can change exception types on bad input. | Only the Python-level logic speeds up: perhaps 1.5–2× on q2 mul's own 197 s. Each Decimal or mpq op still costs a Python-level call. | Needs the same compiler | `.pyd` plus a mypyc shared runtime module | Fixed binaries | **Highest:** the source *is* the Python reference | Yes, trivially | Fallback tier only, for logic-heavy code if ever needed. Not for the jets. |
| **numba** (current: H3, regional_multigrid3d) | Exact when it calls MPFR or GMP through ctypes. fastmath=False. Relies on gmpy2's undocumented object layouts, pinned by a self-test. **Cannot call libmpdec:** `_decimal` exports no symbols. | H3 MEASURED: 2.5× on certification functions (synthetic fixture, warm; W4 waits for q06), 5.4× (v1) and about 10–12× (v2) on the Gram inner dot (noisy-machine microbenchmarks) | None new (already pinned) | Needs numba + llvmlite in the package and a JIT in every process | The assembly is host-CPU-specific, so the identity differs per machine. cpu_name and features are recorded. | Medium. ctypes, raw struct offsets, runtime JIT errors. | Yes (H3) | **Keep** for H3 and the solver. Don't extend it to Decimal or rational jets. |
| **python-flint** (FLINT 3 / Arb) | Exact `fmpq_poly` jets are D-b for rationals. **Arb balls are not D-b with Decimal-80 directed intervals:** the endpoints differ, which is D-c, a method change. | Native polynomial multiply, but building an `fmpq_poly` from Python objects and back costs about the same as the 13-term jet itself (UNMEASURED estimate). Perhaps 1.5–2× at our jet size. | A pip wheel, no compiler. A new download is Michael's call. | Wheel with its own GMP/MPFR/FLINT DLLs (renamed), a second arithmetic stack in the process | Pin the wheel's DLLs as well | High (Python API) | Yes | No for now. Arb is recorded as a possible later *method version* (L5). |

Compiler flags (any AOT route):
- `/O2 /fp:strict`; no `/fp:fast`; no FMA contraction.
- No `/arch:AVX2` or higher, so one binary runs on every x64 machine with the same hash. numba's per-CPU assembly
  doesn't have that property.
- `/Brepro` with no embedded PDB path, so a rebuild from the same inputs gives the same bytes.

The kernels do no host floating-point arithmetic. All arithmetic stays inside libmpdec's, GMP's or MPFR's integer
limb code.

## 2. Which functions: residual hot list after the Python-level fixes in flight

### Method
1. Start from the q14 profile: 1,087 CPU-s, cProfile, 49 deep IV2 interfaces.
2. Subtract the fixes in flight. Interfaces: Geometry D1 −148 s, D2 −34 s, D3 up to −30 s, D4 up to −14 s.
3. Apply G-PY r3's measured component gains (mul 1.34×, div 1.28×) to the jet work D1 leaves. That is
   499 − 148 = 351 s of `_Jets.mul` cumulative time, which becomes about 262–274 s. Carrying a component gain over
   to cumulative time is PROJECTED.

The interface residual comes out at about **780–820 profiler-s**.

For pressure, take P2+P3 as MEASURED: 108.3 → 70.8 s serial (T/ps). P4 is unmeasured.

Gains are projected per group:
- **Inner gain:** profiled Python per-op cost divided by an estimated native per-op cost (UNMEASURED; it needs a
  microbenchmark once a compiler exists).
- **Group gain:** Amdahl, with the share left outside the compiled loop taken from H3. H3 measured 2.5× whole against
  5.4–12× inner, which means 26–35% of the function stayed in Python. The same remainder is applied here. H3
  converted no values per call (it reaches MPFR through ctypes), while K1 and K2 must convert at the leaf edges. So
  carrying its remainder over is UNMEASURED.
- **Saving:** share × (1 − 1/group gain).

cProfile inflates Python call overhead more than native code, so shares and inner gains are upper-leaning. The low
ends of the ranges allow for this.

| Rank | Group (reference functions) | Residual (PROJECTED) | Language | Inner / group gain (PROJECTED) | Saving |
|---|---|---|---|---|---|
| **K1** | Q2 Decimal-80 interval jets: `moving_face_moments._Jets.mul`, `integration_q2_directed` mul, add and point, plus their is_zero/min/max. Entry callers: `contains`, `value`, `_normal`, `_rotated`, `moving_interface_moments`. | About 230–270 s of about 800 (30–34% of interface CPU) | Cython + libmpdec 2.5.1, kept native across a **leaf** | Inner 4–8×. Per interval product: profiled ≈2.5–3.5 µs of Python (1.26 self + 2–4 Decimal ops at 0.39 + compares) against native ≈0.3–0.8 µs (2–4 products of 80 digits, 5 words of 19 digits; UNMEASURED). Group 2–3×. | **15–23%** of interface CPU |
| **K2** | Exact rational kernels:<br>• pressure `_jet_mul` jet convolution (after P4's move to mpq);<br>• geometry wall_measures and volume_overlap fallback (after D5's move to mpq);<br>• WP23 `_wp23_bernstein`, `_wp23_product` and `_wp23_rotation` (already mpq; 80–110 s cumulative after D3). | Geometry: about 10–14% WP23, plus about 3–4% of mpq left after D5. D5 targets `_rotated_normal`/`_clip2`/`_line`: about 102 s, 9.4%, of which about 6% is projected to go (T/ck/d5/DESIGN.md). Pressure: unknown until reprofiled (Fraction was 46% of small5 before P2–P4). The approved pose-width rounding (b) makes the operands small dyadic rationals. | Cython over gmpy2's C API (`mpq_t` and `mpz_t` loops), with the same GMP DLLs | Inner 3–6× over Python-level mpq (a per-op Python call against a native `mpq_mul` on small operands). Group 1.5–2.5×. | Geometry **4–10%** of interface CPU (mostly WP23). Pressure **13–24%** of the stage, if `_jet_mul` is still ≥40% after P4. |
| **K3** | `exact_gmp._clip` (admission initial metrics; RC1 endpoints, where exact_gmp is 21%) | 166 s cumulative of 1,053 s (adm1, MEASURED, 16%). Item 19 runs it in parallel. | Cython over `mpz_t`, **replicating the work-unit charges exactly** (G3's condition) | Group 2–4× | **8–12%** of admission CPU. Wall time falls by roughly that divided by the item-19 worker count. |
| **K4** | Heat certification dots: solve_enclosure Gram, defect, residual and eta; physical_bounds | Already compiled (H3, numba). W4 gain pending q06. | Optional AOT port of H3 into the same Cython/MPFR module | Speed about 1× (same MPFR calls, UNMEASURED) | **Capacity, not speed:** −1.4 CPU-s and about −100 MiB per process (STATE MEASURED; refuter 50–75 MiB), so about 0.3–0.6 GiB across 6 workers |
| — | Accounting: heat H1 (43% of W4 worker time), `_admit_budgets` (28.9 s) | Python-level fixes (H1 in heat) | None | — | — |
| — | Identity and data hashing: heat issuer, 72% snapshot/mesh/origin hashing (S7) | hashlib is already C (OpenSSL). Hashing less is the release-checks policy. | None. A faster hash would change digests. | — | — |
| — | `CartesianCell._vertices` (pressure, 13.8 s cumulative) | Recomputation | Python memo | — | — |

Interface total, PROJECTED: K1 15–23% plus K2 4–10%. This overlaps, so it is not a straight sum: about **20–33%**,
or 1.25–1.5×. Per interval, the saving is Σ (stage share × stage saving). The stage shares need Step 19's
whole-interval profile, so no interval-level figure is claimed here.

**K1's one design risk is granularity.** There is no decimal C API in 3.12, so Decimal objects have to be converted
at the kernel boundary. Three ways to do it:

| Boundary | Cost | Gain | Status |
|---|---|---|---|
| (b) string or tuple conversion | About 1–2 µs per value (UNMEASURED). One `_Jets.mul` call moves 52 Decimals in and 26 out. | At best about 1.0–1.8× per call (`_Jets.mul` is about 200 µs/call, cProfile-inflated): not worth it | Rejected per call |
| (c) one kernel per leaf | Conversions only at leaf entry and exit, amortised over many jet products | The 4–8× above | **Recommended** |
| (a) read and write `PyDecObject`'s `mpd_t` directly | Fast | Fast | 3.12.14 has no `_decimal._API` capsule (the kernels thread checked), so this means the **private** PyDecObject layout. Only with the `_decimal.pyd` hash pinned and a self-test; otherwise decline to Python. A fallback if (c)'s leaves are too small. |

Phase 2's first task is to find the smallest leaf with few Decimal inputs and outputs.

Why this is not G1, which the kernels thread rejected as high risk: G1 *re-implemented* Decimal semantics such as
ideal exponents. K1 *links the same libmpdec* that `_decimal` uses. Each libmpdec operation is then identical by
construction: the General Decimal Arithmetic specification fixes coefficient, exponent and sign of zero, and the
version is pinned on top of that.

The specification around those operations is not handled by libmpdec. K1 must replicate it, or decline (from the
kernels thread's review):
1. **Live context.** q2_directed builds `Context(prec=80, rounding=FLOOR/CEILING)`, which takes Emin, Emax, traps and
   clamp from DefaultContext *at construction*. The kernel must either:
   - read the live context's fields and update its flags as the reference does; or
   - prove nothing reads those flags.

   Otherwise it declines.
2. **Corner choice.** Python `min`/`max` is first-of-equals over equal Decimals with different exponents or signed
   zeros. That ordering is part of the specification; G-PY needed an explicit first-of-equals for the same reason.
3. **Refusals.** Decline on Decimal subclasses and on instance-replaced attributes (G-PY r3 DEFECT A).

**K2 and K3 conditions** (the kernels thread's review):
- **Cross-CRT memory.** gmpy2's GMP is mingw-built. Use its C ABI only, and free GMP memory with GMP's own calls.
- **Bit ceiling.** The wheel counts bits in 32 bits, so keep exact_gmp's `CEILING_BITS = 2**27`.
- **Work charges.** Reproduce the `V._work` amounts, the `_settle`/`NATIVE_RETAINED` surcharge and the work units
  *through the shared D5/P4 primitives* (T/ck/d5/DESIGN.md section 3). Don't write a new accounting copy.
- **Backend selector.** Don't inherit WP23's direct `gmpy2` import, which bypasses `ATLAS_EXACT_ARITHMETIC`.

## 3. Toolchain

| Option | What | Size (PROJECTED; check in the installer) | Licence | Verdict |
|---|---|---|---|---|
| **MSVC Build Tools 2022** (v143 x64 + one Windows 11 SDK) | The compiler CPython 3.12.14 itself was built with (MSC v.1944 = VS 2022 17.14). The supported route for CPython extensions; setuptools finds it automatically. | About 2–4 GB, minimal C++ workload | Visual Studio licence terms. Free for an individual developer under the Community terms. **Accepting the licence is Michael's step.** No new runtime redistributable: extensions use the UCRT (part of Windows) and the vcruntime140 that CPython ships. | **Recommend** |
| MinGW-w64 (GCC, UCRT) | Works through meson. setuptools and CPython don't support it for extensions. | About 0.5–1 GB | GPL-3 with the GCC runtime exception | No |
| clang-cl (LLVM) | Still needs MSVC's libraries and the Windows SDK, so it adds to MSVC rather than replacing it | +2–3 GB | Apache-2.0 with the LLVM exception | No |

Build-only Python packages, never shipped and never put in `.r44-env`, pinned by hash in the build environment:
- Cython 3.x (Apache-2.0)
- setuptools and wheel (MIT)

Source:
- libmpdec from the **CPython 3.12.14 source tag**, the copy compiled into `_decimal.pyd` (BSD-2). Check
  `MPD_VERSION == "2.5.1"` at build and at import.

**Separate build environment.** Use a real folder outside AppData and outside `.r44-env`, for example
`C:/Users/LOCAL_USER/atlas-tools/kbuild/`:
- its own venv made from the same CPython 3.12.14;
- it reads `.r44-env`'s `include/` and `libs/python312.lib` without writing to them;
- it reads gmpy2's headers and import libraries (`gmpy2.libs/gmp.lib`, `mpfr.lib`).

Michael installs the Build Tools himself (winget, licence acceptance, PATH): installs and PATH edits are his
under the desktop app's AppData redirection.

Outputs:
- the `.pyd` files, copied into the candidate source tree (never into `.r44-env`);
- a **build record** (JSON) for each module, holding:
  - the sha256 of every source (`.pyx`, the C shim, libmpdec);
  - the generated C sha256;
  - the Cython, `cl` and link versions;
  - the flags;
  - the gmpy2 and import-library hashes;
  - the output sha256.

**How compiled modules join the execution identity (B1)**, following gmpy2's existing pattern
(`exact_arithmetic.runtime()['binaries']`):
1. Each loaded kernel `.pyd` is added to `_runtime_record()['binaries']` through `_loaded_binary(path)`, which
   hashes the loaded file. Windows locks a loaded `.pyd`, so `_loaded_binary`'s assumption that the file doesn't
   change for the life of the process holds, as it does for gmpy2's DLLs.
2. `versions` gains:
   - the kernel module version;
   - the **route** (`compiled` or `python`), a per-process constant chosen once by the import self-test;
   - `mpdecimal: 2.5.1`, Cython, `cl` and the build-record sha256.
3. B1's first capture per backend already hashes runtime binaries, so no new boundary is needed. The release
   checks' recommended boundaries are unchanged.
4. The D6 ship list gains the kernel `.pyd` files, their build records and the import self-test, all functional.
   Not shipped: the build environment, Cython, the compiler, and the fuzz and mutant harnesses.
5. **Gaps that exist today, independent of compilers** (L4):
   - **`_decimal.pyd`** (libmpdec 2.5.1, static; in the runtime's DLLs folder) is not in `_runtime_record`; the
     kernels thread confirmed this. Geometry's certified Decimal-80 arithmetic depends on it.
   - **`python312.dll`** is not hashed. `_interpreter_binary`'s docstring says so: on Windows the hashed
     `python.exe` is only a launcher, the module at `sys.dllhandle` is never hashed, and built-in `math` repeats the
     launcher's hash. So the interpreter's identity rests on the `sys.version` string.
   - **Stdlib `fractions.py`** (pure-Python Fraction) and `decimal.py`: `reuse.py` doesn't mention them (grep), so
     they are probably unpinned. Confirm when the patch is drafted.

   The fix: add the `_decimal` binary hash and `decimal.__libmpdec_version__`, the `sys.dllhandle` DLL, and the
   stdlib arithmetic sources.

## 4. Accuracy proof route (per kernel; the H3 and G-PY precedents)

1. **The Python reference stays the specification**, unchanged. A per-process route selector chooses the compiled
   route only after an **import self-test**:
   - a fixed battery compared bit-for-bit with the reference;
   - a check that the libmpdec version and the `_decimal` hash match;
   - for K1 option (a), a check of the object layout.

   Any failure, refusal or exception means the reference runs, and the route is recorded. The rules:
   - Contexts are read **live** and must equal the reference's settings exactly: prec, rounding, Emin, Emax, clamp
     and traps (Emin, Emax, traps and clamp come from DefaultContext when the context is built).
   - Flags are updated as the reference updates them, or a proof shows nothing reads them.
   - Any status that would trap means the kernel refuses, so the reference raises the same exception.
   - Subclasses and instance-replaced attributes are declined.
   - The first-of-equals corner choice is replicated exactly.
2. **Differential fuzzing, bitwise:**
   - Decimal by `as_tuple()`, which catches exponent and signed-zero differences, and by context flags where the
     code reads them;
   - rationals by (numerator, denominator, type).

   Adversarial classes:
   - zero-endpoint corners (31% of interval products);
   - signed zeros, Emin/Emax and carries at digit 80;
   - straddling sign classes;
   - cancellation, and huge or tiny rationals;
   - NaN/Inf where reachable.
3. **Planted mutants**, which the self-test and fuzzing must reject:
   - wrong rounding direction, and RU ties;
   - prec 79 or 81;
   - swapped corners;
   - a dropped or extra jet term, or wrong truncation;
   - an unreduced rational;
   - a wrong sign of zero;
   - an unreplicated work-unit charge (K2, K3);
   - a context with a non-default Emin or traps;
   - a last-of-equals corner choice;
   - a Decimal subclass that is accepted.

   H3 rejected 8/8; G-PY rejected 6/6.
4. **Capture and replay of real calls.** IV1 all, an IV2 sample and IV2 deep, reusing G-PY's fail-closed q11
   harness r5: 0 mismatches.
5. **D-b parity of the whole control** in one ticket, on the same calls, as in q06:
   - arrays, stores, results and metadata byte-identical;
   - only identity digests differ.
6. One refuter agent per kernel, plus a delta refuter after any fix.
7. **Rebuild determinism.** Two `/Brepro` builds must give the same `.pyd` sha256. If they don't, the shipped binary
   is still the pinned artefact, and any rebuild is a D-b re-pin.

## 5. Sequencing

The compiled work starts after the Python-level fixes land (Geometry D1–D5, Heat H1/H2/H5a, Pressure P2/P3/P4,
Fraction → mpq) and after the **final reprofile (plan Step 19)**. Compiling now would optimise code those fixes are
still changing.

| When | Work | Needs |
|---|---|---|
| **Now** (no installs, no runs) | N1: kernel interface specs for K1–K4: the reference function, inputs and outputs, contexts, refusal rules, and the leaf choice for K1 | Reading only |
| Now | N2: catalogues of fuzz generators and mutants, written in Python against the reference | Running waits for the small lane after RESUME |
| Now | N3: capture hooks for K1 and K2, a spec on top of the q11 harness r5 | Reading only |
| Now | N4: the build recipe (versions, flags, `/Brepro`, layout), the identity-field schema, and a draft L4 identity patch (`_decimal.pyd`, `python312.dll`, stdlib arithmetic sources), not applied | Reading only |
| After Step 19 | Re-rank K1–K4 on the new profile. **Go/no-go:** a group needs at least about 10% of an interval's CPU, and a projected saving of at least about 5% of the interval | Reprofile |
| After L1 = yes | Michael installs Build Tools. Phase 1: **K2 pilot** (pressure `_jet_mul` + WP23 helpers). Rationals are canonical and the work charges go through the shared D5/P4 primitives, so it proves the toolchain, the build record, identity and parity at the lowest risk. | Compiler |
| Then | Phase 2: **K1** Decimal-80 leaf kernel, which has the largest gain | Phase 1 passed |
| Optional | Phase 3: K3 `_clip`, after item 19 is measured; K4 H3 AOT, if per-process memory binds or a release build arrives | Phase 2 |

Each kernel is adopted only with:
- §4 steps 1–6 clean;
- a **measured** gain;
- a ticket for every heavy run.

## 6. Decisions for Michael (batched, each with a recommendation)

**Coordinator's answers (16 Oct, after 15:42):**
- L2, L3 and L5: accepted as recommended.
- L4: approved. It is bundled with the next identity change, through Small's assembly manifest.
- L1: goes to Michael as a *conditional* yes, applying only if Step 19 shows at least 15%.
- N1-N4: deferred until the reprofile.

**L1. Install a compiler?**
- **Recommendation:** yes, **MSVC Build Tools 2022** (v143 + Windows SDK, about 2–4 GB). It goes in a separate build
  environment and never in `.r44-env`. Install it only after Step 19 confirms that K1 and K2 together are still at
  least about 15% of interface CPU. The projection today is 20–33%.
- **Alternative: no compiler.** Stay with the Python-level fixes plus numba H3. This gives up the PROJECTED 1.25–1.5×
  on interface work and 13–24% on the pressure stage.
- **Later-step impact:**
  - each adopted `.pyd` enters the B1 execution identity, so pins and caches regenerate once per adoption (D-b);
  - the D6 ship list gains the `.pyd` files and build records;
  - every later interval gets the speed;
  - the packaged release ships prebuilt binaries and needs no compiler.
- **Next-interval capacity:** AOT kernels add about 1–5 MiB per process (UNMEASURED; a static libmpdec plus small
  modules). numba measured about +100 MiB. No guard changes.

**L2. Language per function group.**
- **Recommendation:**
  - K1 Decimal-80 jets: **Cython + libmpdec 2.5.1, leaf-level**.
  - K2 rationals and K3 `_clip`: **Cython over gmpy2's C API**.
  - K4 heat dots: **keep numba H3**; port it to AOT only for memory or packaging reasons.
  - Accounting and hashing: **no language change**.
- **Later-step impact:**
  - one build route serves every kernel;
  - Decimal-80 and MPFR semantics are unchanged, so no certified endpoint moves;
  - numba stays a runtime dependency for H3 and the solver.
- **Next-interval capacity:** unchanged until K4 is ported. Porting K4 frees about 0.3–0.6 GiB across 6 workers.

**L3. Scope and order.**
- **Recommendation:** K2 pilot → K1 → optional K3 and K4. Each is gated on D-b parity and a measured gain. N1–N4
  are prepared now, read-only.
- **Later-step impact:** each phase is one identity change. Bundle adoptions where possible so caches regenerate
  fewer times.
- **Next-interval capacity:** no guard or ceiling changes. Parity tickets book the same memory as their G-PY/q11
  equivalents.

**L4. Pin `_decimal.pyd` (with its libmpdec version), `python312.dll` and the stdlib arithmetic sources in the
execution identity.**
- **Recommendation:** yes, whatever L1 decides. Bundle it with the next planned identity change (for example
  G-PY or H3 adoption) so no extra cache regeneration is paid.
- **Later-step impact:** closes unpinned dependencies of certified arithmetic. It is a one-time D-b re-pin. It is needed in any case
  before K1, whose self-test checks this hash.
- **Next-interval capacity:** none (a single file hash at first capture).

**L5. Not adopted, recorded with the reason.**
- Arb or MPFR replacing Decimal-80: D-c, every endpoint changes. It could become a future *method version*, with a
  re-baseline, if Michael ever wants one.
- python-flint now: a new runtime dependency, a second arithmetic stack, and little gain at 13-term jets.
- Rust: a second GMP plus an MSYS2+MSVC toolchain.
- C++ with FLINT: the Windows build.
- mypyc: needs the compiler anyway, and gains only on logic.

Later-step impact: none.

## 7. Outside the kernels: why nothing else is rewritten (added 15:46 at Michael's request)

The language question was asked for the whole generator, not only K1–K4. This is the answer for everything else.
No change is proposed in this section, so it has no later-step impact and no capacity effect.

| Area | Language now | Rewrite in another language? | Why |
|---|---|---|---|
| Exact-arithmetic kernels (K1–K4) | Python + Decimal/Fraction/gmpy2; numba for H3 | **Yes**, §2–§6 | This is where the profiled time is |
| Floating-point solvers (`regional_multigrid3d`; scipy sparse, LAPACK, FFT) | numba (fastmath=False); compiled numpy and scipy | No | Already compiled. A port would have to reproduce operation order exactly to stay byte-identical, or it becomes D-c. |
| Resource accounting (heat H1, `gmp_resources`, `_admit_budgets`) | Python | No | Logic, not arithmetic. H1 fixes the algorithm, which is 43% of W4 worker time. mypyc only if it is still hot after Step 19. |
| Identity and guard checks (`verify_boundary`; callable inventory walk, 96% of it) | Python introspection | No | It inspects Python objects, so a compiled language can't do the walk faster. The release-checks policy (D1–D6) cuts how often it runs. |
| Data hashing (72% of the heat issuer) | hashlib (OpenSSL C) | No | Already native. The fix is to hash less; another algorithm would change every digest. |
| Storage (ArrayStore, compact restart store) | sqlite (C) + numpy | No | Already native. No profile shows it hot; Step 19 checks this. |
| Recomputation (`CartesianCell._vertices`; Geometry D2–D4) | Python | No | Memo or hoist. Removing the repeated work beats doing it faster. |
| Drivers, runners, queue, interval orchestration | Python | No | Not hot in any profile. Clarity and fail-closed behaviour matter more here. |
| Desktop app (`desktop/`) | Not assessed | — | Outside this thread's brief and folders |
| Other modelling categories (C02–C18) | As they are built | Same rule | Python reference first; compile only kernels measured as hot |

**The rule for compiling anything:** all four conditions must hold.
1. The measured share is at least about 10% of interval CPU *after* the Python-level fixes.
2. The arithmetic can be byte-identical, because it uses the same library and the same context (D-b).
3. The Python reference stays as the fallback.
4. The §4 proof route passes.

**A wholesale rewrite (the whole generator in Rust or C++) is not recommended:**
- **Cost:** it means re-proving everything: about 10,955 class-A check sites (RELEASE-CHECKS §0) and all the parity
  evidence.
- **Lost fallback:** there would be no Python reference to fall back on or compare with.
- **Little gain:** the time outside the kernels is either already in compiled libraries or removed by the fixes in
  flight.

**Caveat:** only the profiled stages were ranked here: geometry interfaces, heat W4, pressure small5 and admission.
No whole-interval profile exists yet. The Step 19 reprofile should re-rank *every* stage under the rule above,
including stages nobody has profiled, such as the interval driver, restart/compaction and store I/O.
