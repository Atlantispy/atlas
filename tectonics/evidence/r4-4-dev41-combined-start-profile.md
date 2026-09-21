# Dev41 combined warm-start profile: locally benchmarked

**21 September 2026. WORKING NON-CANON; R4.4/R4 remain IN_PROGRESS.**

## Decision

Recommend the existing `previous-stage1` option together with GMG, Anderson,
adaptive-inner and guarded preconditioner reuse for the tested NEW Tosi case-2
128x128 workloads. This is a measured combination of already implemented
algorithms, not a new solver or blanket change of defaults. Old run bindings
cannot be changed to adopt this profile.

```text
--nonlinear-solver anderson --nonlinear-start previous-stage1
--adaptive-inner --preconditioner-max-uses 4 --velocity-preconditioner gmg
--ilu-fill-factor 17 --linear-rtol 1e-12 --momentum-tolerance 1e-9
--viscosity-rtol 1e-8 --max-picard 400
```

GMG support restrictions remain. Do not generalise this recommendation to every
rheology, geometry or resolution. The 16x16 correctness case saved only 9.095 ms
in one pair, which is not sufficient evidence for small-workload promotion.

## Measured incremental improvement

Exact source base: `49c6603fad2ed9a92f6f2a302037dd425f154c3c` (dev41).
Both sides use GMG + Anderson + adaptive-inner + four-use guarded reuse.
Only `zero-rate` versus `previous-stage1` differs. Each sample is **two accepted
coupled steps**, fixed dt=1e-7, starting with no seed. State capture, plan
preparation, both advances, seed capture and close are timed. Actual-path JIT
warm-ups, fixture creation, verification/export, checkpoint I/O and standalone
endpoint diagnostics are excluded. These are not full runner/campaign timings.

| Input, 128x128 | Zero-rate median | Warm-start median | Seconds saved | Time saved |
| --- | ---: | ---: | ---: | ---: |
| Analytic initial field | 2.505858400 | 1.963621100 | 0.542237300 | 21.638785% |
| Developed-field-derived NEW input | 35.089515200 | 20.052830500 | 15.036684700 | 42.852358% |

Three matched pairs each; order cold/warm, warm/cold, cold/warm. Every measured
pair favoured warm starts. These medians are not confidence intervals.
Do not add these percentages to earlier GMG or adaptive-inner savings.

| Input | Pair | Zero-rate seconds | Warm-start seconds |
| --- | ---: | ---: | ---: |
| Initial | 1 | 2.5058584000216797 | 1.963621100061573 |
| Initial | 2 | 2.33044599997811 | 2.0302457999205217 |
| Initial | 3 | 2.5143320000497624 | 1.9362696999451146 |
| Developed-derived | 1 | 39.63278929993976 | 21.466978399897926 |
| Developed-derived | 2 | 33.75528719997965 | 19.262625099974684 |
| Developed-derived | 3 | 35.08951520000119 | 20.05283049994614 |

The developed input starts from returned `from_900.npz` temperature on a 16x16
support, transformed by dev41 `probe_convection_r4_4.temperature_on_grid` to
128x128, with zero composition and a NEW time-zero state. It is **not an evolved
128-grid trajectory, historical restart, mature convection result or Diadem terrain
acceptance**. Original raw-file SHA256:
`7284398ed3b3603683a89e31e639d135a7d9d9a372047ccd7b509450bc1d1062`.
Prepared two-field NPZ SHA256:
`45cc6acf7d59370984b994f0ad2b8bf5c676c9be4ca105f583dc578b3cb3c26d`.
The developed fixture and full local records are not included in the public source.

## Quality and work checks

All sampled steps passed the original strict solver and transport gates.
Independent comparisons passed existing explicit-guess regression tolerances for
velocity/transport, the existing 1e-9 K coupled-field comparison bound, and exact
composition equality. Across these cases the maximum temperature difference was
4.440892098500626e-16 K. Developed-case maximum velocity difference was
3.135910142670895e-10 m/s. No solver tolerance, time step or iteration ceiling was
relaxed. Same-mode repeats retained identical accepted state IDs.

Developed two-step stage counts, identical across repeats:

- Nonlinear iterations: cold [144,149,143,132] = 568; warm [144,63,50,91] = 348.
- Linear iterations: cold [2082,2111,2075,1872] = 8140; warm [2082,718,608,1145] = 4553.
- Maximum returned momentum residual across both modes: 7.87226617227077e-10
  against the unchanged 1e-9 gate.
- Maximum divergence: 8.029132914089132e-13; heat-relative residual:
  3.4888853336570515e-19; composition residual: zero.

A separate 16x16 check saved/restored the first accepted state, recreated the plan
and matched uninterrupted state IDs and arrays exactly for both modes. Every
sample checked the seed chain, typed state decoding and zero remaining budget
reservations. Existing dev41 fresh-process CLI/restart evidence already covers
this combined profile on 8x8; it was not rerun merely to repeat unchanged evidence.

Warm starts add 395,264 raw seed-array bytes (386 KiB) to each retained 128x128
endpoint before compression, plus metadata; no recursive seed history is retained.
Both variants used the same 1 GiB WorkBudget. This is not a process-RSS limit.

## Environment and reproduction

Windows 11 AMD64, CPython 3.12.14, NumPy 2.4.6, SciPy 1.17.1, Numba 0.65.1,
llvmlite 0.47.0, threadpoolctl 3.7.0. One native numerical thread, no concurrent
numerical benchmark. All source bytes and membership matched the exact detached
base before and after execution.

The returned harness is `tools/benchmark_combined_start_r4_4.py`; its focused tests
are `tests/test_combined_start_benchmark_r4_4.py`. The Windows test-fixture setup
was corrected to write canonical LF bytes rather than platform-translated text.
The local result used its reviewed `source_audit`, `fixture`, `trial`,
`validate_seed_chain`, `compare_arrays` and `summary` functions in a bounded
driver: one 16-grid restart check, then three pairs for each 128-grid input.
It did not run the harness's longer all-in-one sequence of repeated CLI and
128-grid restart checks. Local driver SHA256:
`55222982e24504aa9534f739c9e8345adbe0c948810e470d0e6ba6d9ca65c8c3`.
Measured harness SHA256:
`77115cb340e5d8f1f616b99fc987ef6c36325a1fcf05700c1b8784edf4212a03`.

The standalone harness can reproduce comparisons in a **detached exact-base
checkout** with compatible installed dependencies, using `-I -B`,
`--output NEW_DIRECTORY --exclusive-host-confirmed --repeats 3`.
It also runs additional correctness checks; use `--help` for fixture provenance
requirements. Its exact-base guard intentionally refuses newer numerical source.
No baseline checkpoint or source binding should be repinned to make it pass.

The chat's original packet had tooling-only tests and no solver timing because
its execution environment could not fetch dev41. The local measurements above
supersede that numerical-execution limitation, not the retained original packet.
No full R4.4 campaign, default change, commit, push or canon adoption is implied.
