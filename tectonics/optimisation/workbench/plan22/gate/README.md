# Plan22 composed gate

**WORKING NON-CANON. Source integration and bounded control checks only. The full
gate has not been constructed or run for this successor.** This directory supplies
the complete gate, its three child sources and a portable standard-library control
test. It is not a detached patch or a passing composed-runtime result.

The gate composes the pinned p1820c-r4 base with S3, L3 and S1 Stage A ports into
new folders. It compares base and candidate identity suites in both composition
and owner layouts, requires the focused suites to pass, and requires the planted
reader mutant to fail. Sources are copied and authenticated before execution;
the supplied inputs are read only.

## What the repair changes

Every positive child and the S3 negative fixture must exit exactly 0. The planted
reader-mutant child must exit exactly 1. A passing JSON object cannot excuse a
timeout or another process exit. Every suite must execute tests; identity
comparisons preserve the baseline's run count, skipped count and failing test
names. S1 changes may repair existing failures but may not drop tests or add
skips. Required L3, S1A, S3 and G0-G2 cases must all run without skips.

The public entrypoint takes explicit paths. It accepts no digest or expected-count
override. Missing/extra configuration keys, relative paths, nonexistent inputs,
directories supplied in place of a PORT.json file and a different selected
interpreter all refuse. Input digests and full tree memberships remain pinned in
the implementation. Changing a source needs a reviewed successor with its own
identity, not a new path label or a relaxed check.

## Run the portable controls

From the repository root, with Python 3.10 or later and only the standard library:

```text
python -B tectonics/optimisation/workbench/plan22/gate/test_gate_results.py
```

The controls exercise the real `evaluate`, `outcome`, path configuration and
early CLI refusal code with disposable inputs. They do not construct the five
composition arms, import the scientific stack, open an interval store, run IV or
measure timing. To retain a new result, add `--report NEW_FILE.json`.
[CONTROL-RESULT.json](CONTROL-RESULT.json) identifies the exact checked public
gate and test bytes. Its successful control result is not a full-gate PASS.

## Supply the exact inputs for full verification

The original base, three port packages, constructor, owner runtime, endpoint test,
heat-repair test tree, suite runner and compatible Windows science environment
are **not supplied by this public directory**. Public source selections elsewhere
in the repository have different identities and are not substitutes. The
historical Windows file-replacement controls also do not establish support for
another operating system.

Copy [PATHS.example.json](PATHS.example.json) outside the source tree and replace
each example location with an absolute path. There are exactly ten keys; each
port entry names its actual `PORT.json`, with its referenced packaged rows and
diffs in their original relative layout. L3 references its package's parent as
recorded in that port. Paths change location only: all required SHA-256 values,
tree counts, dependency exceptions, expected suite counts and the extracted
constructor-function digest remain fixed in [gate_s3l3.py](gate_s3l3.py).

Use the configured interpreter to invoke the gate. Child processes use that same
resolved executable. This selection check is not an installed-package or runtime
dependency audit; the compatible pinned science environment remains required.
With exact inputs available and the separate execution authority satisfied:

```text
PATH_TO_CONFIGURED_PYTHON -B gate_s3l3.py verify NEW_SHORT_ROOT --paths PATHS.json
PATH_TO_CONFIGURED_PYTHON -B gate_s3l3.py run ANOTHER_NEW_SHORT_ROOT --paths PATHS.json
```

Both commands refuse an existing output directory and output inside an input tree
or this gate directory. Keep it short enough for the inherited Windows test
layouts. `verify` authenticates inputs, exercises the six fail-closed composition
controls and builds every arm; it is not a cheap source-only lint command. `run`
does the same work and then launches the full suite matrix, three children at a
time. Do not use either command merely to run the portable controls above.

## Read the result literally

`verify` writes **`VERIFIED_NOT_RUN`**, meaning composition verification completed
but the runtime suites did not run. Only `run` can write **`PASS`**, and only when
all evaluated checks succeed. Runtime check failure writes `FAIL` and exits 1;
input/configuration refusal exits 2. Each successful verification or completed
run writes its new root's `GATE-RESULT.json`, with source pins and its actual
command. This result contains supplied machine paths and should be reviewed
before any publication. No result is written for early refusal.

Neither status selects L3 by default, qualifies a combined IV run, measures a
speed gain, releases an execution hold or establishes scientific acceptance.
The S1A integration, D-22r timing and final enabling selection retain their own
requirements. Historical gate results are not rebound to these changed bytes.
[SOURCE-MAP.json](SOURCE-MAP.json) records predecessor/public identities and the
limited adaptations; the three child sources retain their exact original bytes.
