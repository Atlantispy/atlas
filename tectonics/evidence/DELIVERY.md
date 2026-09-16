# First remake delivery — obtained evidence

Date: 16 September 2026. Base commit: `7d0e707a576fe08b9bcb816466a0a8fb5f115808`.
Target: **remake**, not main. Vibe-coded with OpenAI ChatGPT/Codex under the
owner's direction. This delivery starts Plan 05 revision 3, not its full scope.

## Actually run

On Linux x86_64, CPython 3.13.5, NumPy 2.3.5 already present:

```text
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python -I -B tectonics/verify.py
53 tests passed; no failures, errors or skips.

python -B tools/check_coding_safety.py
PASS: 13 selected source maps; 41 required paths.

python -B -m unittest discover -s tests -p test_coding_safety.py -v
31 existing tooling tests passed; no failures, errors or skips.
```

`foundation-tests.json` is the actual fresh record, including relative source hashes
before/after and the test environment. It is not a signature or performance result.
A second execution from a fresh relocated copy, with bytecode files excluded,
produced the identical structured record and no bytecode files. New source also
passes a CPython 3.12 grammar parse; this is not a Python 3.12 runtime test.

Mathematical tests exercise the actual kernels. They include independent dense
real-space flexure comparison and first/second-order convergence on small grids.
No observational geological comparison, calibrated material profile, whole-world
simulation, performance benchmark or old checkpoint continuation was attempted.

## Implemented versus proposed

Implemented: rotations and boundary diagnostics; periodic conservative thickness
transport; analytical half-space cooling; uniform periodic difference flexure;
explicit immutable physical parameter records; narrow validation and test reporting.

Proposed only: the Minecraft/OpenVDB-inspired chunk/palette/sparse storage ideas
in `../docs/VOXEL_STORAGE.md`. No Minecraft/OpenVDB dependency, copied game code,
full 3D storage layer, distributed solver or rendering system is supplied.

No existing repository file is changed, and no source-bound historical package is
imported by the new module. The module README records current development status
and keeps realism before production. A package-local `.gitattributes` supplies LF
policy only for the new text files. No workflow,
background run, main-branch merge, Windows synchronisation or licence grant is added.

## Still unverified

Windows/macOS execution; Python 3.12 execution; other NumPy versions; editable
installation; large-memory behaviour; physical realism; all non-periodic/further
mechanical regimes. Scientific limitations are in `../docs/FOUNDATIONS.md`.

Review the mathematical formulas and independent expectations before extending the
first mechanism. The existing 53 tests are not evidence of full W01–W04 completion.
