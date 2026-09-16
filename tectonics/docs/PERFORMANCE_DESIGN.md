# Performance design: mod findings and implementation language

**16 September 2026. Design guidance only; no new optimisation implemented or benchmarked.**
Vibe-coded with OpenAI ChatGPT/Codex under Michael's direction. WORKING NON-CANON.
Code basis: `11317165b7e2aeab7201a1fe3e3f646cb640d51e` on `remake`.

This note consolidates the later Minecraft-mod screening and language assessment.
The full 84-entry screening, revised Plan 05 (revision 4), Report 03 language
supplement and Report 06 catalogue (revision 2) are separate review artefacts;
this directory is not claimed to contain those complete reports.

## 1. Retain a readable controller; accelerate substantial kernels

Keep Python for case definitions, orchestration, validation and scientific review.
Use suitable native-backed numerical routines for bulk operations. Consider a
narrow compiled kernel when measured cost warrants it; C++ is a candidate, not a
whole-project rewrite decision. An existing array routine or eligible Numba kernel
may be a smaller adequate change. Do not add several native languages/frameworks
without a demonstrated need and a maintainable build/test path.

NumPy already performs many numerical operations in compiled code. Many operations
release the interpreter lock, but that does not make every operation internally
parallel or shared writes safe. Sources: [NumPy arrays](https://numpy.org/doc/stable/user/whatisnumpy.html)
and [thread safety](https://numpy.org/doc/stable/reference/thread_safety.html).

| Observed foundation | Candidate investigation | Must preserve |
| --- | --- | --- |
| `thermal.py` calls `math.erf` through Python iteration | An eligible bulk error-function routine | Broadcasting, zero age, surface/depth limits, finite-range checks and a defined error policy |
| `transport.py` performs several array passes | Fused native loop or private scratch reuse | The same conservative update, outgoing Courant-sum refusal, positivity and budget diagnostics |
| `flexure.py` calls native FFTs with reusable coefficients | Setup, batching and workspace/copy cost before a backend change | The discrete centred-difference operator, not an unannounced continuous spectral replacement |
| `_validation.py` detaches inputs and freezes output bytes | Ownership-proven copy reduction only | No writable alias can change accepted state; failed/cancelled candidates cannot publish partial state |

These are source observations, **not established bottlenecks**. A native wrapper
rewrite alone does not improve an FFT algorithm. The [SciPy array erf](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.erf.html)
is one documented candidate, not a new dependency installed by this note.

## 2. Native boundary and acceptance rules

Pass arrays or substantial batches, not one foreign-language call per cell.
Specify dtype, shape, strides/contiguity, alignment, byte order, allowed conversions,
copy budgets, input lifetime, output ownership and scratch ownership. Refuse
unsupported inputs or convert explicitly; do not silently downcast or hide a large
copy. A read-only view does not freeze other aliases to the same buffer.

Hold buffer owners alive during native work. Release the interpreter lock only
around work that does not access Python objects. Budget outer workers and all
inner native threads together. Define deterministic errors, cancellation boundaries,
late-result rejection and explicit fallback. Never silently change numerical
backend following failure.

Record compiler/build flags, target architecture, ABI/dependency and relevant
binary identity. No fast-math, reassociation or reduced precision is enabled by
this design. The [Numba guidance](https://numba.readthedocs.io/en/stable/user/performance-tips.html)
and [pybind11 buffer documentation](https://pybind11.readthedocs.io/en/stable/advanced/pycpp/numpy.html)
are method references, not guarantees of exactness, zero-copy behaviour or portability.

Compare unchanged equations, inputs, boundaries and precision under the declared
error/equality policy. Include import/build/JIT setup, dispatch, transfers, copies,
temporary/native memory and verification. Preserve an independent reference and
test extremes, conservation, event decisions and failed attempts. No language-only
speed ratio or automatic C++/Rust/GPU migration is established.

## 3. Additional mod lessons: evaluate the method, not the name

| Reference | Candidate lesson | Boundary |
| --- | --- | --- |
| [Accelerated Recoiling](https://modrinth.com/mod/accelerated-recoiling), [C2ME OpenCL](https://www.curseforge.com/minecraft/mc-mods/c2me-ocl) | Selective native or device computation | Algorithms/behaviour also differ; selected GPU stages are not a whole-world solver |
| [EfficientHashing](https://www.curseforge.com/minecraft/mc-mods/efficient-hashing) | Better lookup-key distribution | Hash-table hashes never replace cryptographic source identities; compare full keys on collisions |
| [Jasione](https://modrinth.com/mod/jasione), [Redirected](https://modrinth.com/mod/redirected) | Share data only after proving safe lifetime and immutability | Current detachment checks are deliberate, not overhead to remove blindly |
| [Achievements Optimizer](https://modrinth.com/mod/achievements-optimizer), [Sepals](https://www.curseforge.com/minecraft/mc-mods/sepals) | Cheap pure predicates, indices and selective updates | Preserve all relevant dependencies and side effects; individual modules need review |
| [Command Optimiser](https://modrinth.com/mod/commandoptimiser), [Fast Recipe Search](https://modrinth.com/mod/fast-recipe-search) | Parse/index preparation separate from evaluation | Bind parser, symbols, schema and input membership, not just unchanged text |
| [Async Logger](https://modrinth.com/mod/asynclogger), [Async Pack Scan](https://modrinth.com/mod/async-pack-scan) | Bounded asynchronous diagnostics/discovery | Backpressure, shutdown flush, generation identity and required evidence must survive |
| [Create: Threaded Trains](https://modrinth.com/mod/create-threaded-trains), [RailOptimization](https://modrinth.com/mod/railoptimization) | Private work followed by controlled join; avoid redundant notifications | Adjacent physical regions and sequential timesteps are not independent tasks |
| [Faster Random](https://www.curseforge.com/minecraft/mc-mods/faster-random), [NumFlux](https://modrinth.com/mod/numflux) | Study random/arithmetic cost only when relevant | Changed algorithm, draw mapping or precision needs a new reviewed numerical identity |

These are developer-description leads, not code audits or accepted Atlas methods.
Graphics, audio and networking projects remain references for future subsystems.
Skipping updates by camera distance, deleting records, raising bounds, disabling
checks or upscaling an image does not preserve the scientific calculation.
A library or a broad optimisation bundle is not an implementation specification.

## 4. Loading and storage remain separate concerns

[DashLoader](https://github.com/alphaqu/DashLoader) is a reference for restoring
prepared artefacts. ModernFix's [dynamic resources](https://github.com/embeddedt/ModernFix/wiki/Dynamic-Resources-FAQ)
and [dynamic entity renderers](https://github.com/embeddedt/ModernFix/wiki/1.21.1-Summary-of-Patches)
are references for deferring model construction. Cache reuse avoids repeated work;
lazy loading avoids unrequested preparation. Full dependency paths can defeat
laziness, and cache retention can cost more than recomputation.

Keep compact stored geology, active numerical buffers and viewer data separate.
Lossless palettes/chunks do not make all continuous fields uniform. Storage
residency is not permission to omit remote stresses, loads or drainage influences.
See [VOXEL_STORAGE.md](VOXEL_STORAGE.md) for the representation boundary.

## 5. Immediate use

Continue the scientific foundations and the first justified mechanism. Instrument
what actually runs; do not implement the whole mod catalogue first. A narrow
verified optimisation may enable a realism experiment without conferring physical
acceptance. Production remains after the relevant realism and scale gates.

This documentation update changes no solver, parameter, numerical limit, source
binding, checkpoint or recorded test evidence. No mod installation, benchmark,
scientific test, simulation, automatic workflow or Windows integration was run.
