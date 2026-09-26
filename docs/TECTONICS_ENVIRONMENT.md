# Tectonics environment

26 September 2026. WORKING NON-CANON. Roadmap Phase A5.

This page records the tested Windows tectonics environment as reproducible setup
inputs. Package-version pins are **not** proof of identical native binaries or of
checkpoint-continuation compatibility.

## What was inspected

The existing Windows scientific virtual environment was inspected read-only on
26 September 2026, with system site-packages excluded. Only installed package
metadata was read, through `importlib.metadata`. No package was imported,
installed, upgraded, rebuilt or downloaded. The dependencies declared in
[tectonics/pyproject.toml](../tectonics/pyproject.toml) were followed through each
package's `Requires-Dist`, including extras requested by a parent.

| Fact | Observed |
| --- | --- |
| Interpreter | CPython 3.12.14, MSC v.1944 64-bit (AMD64), build of 25 August 2026 |
| Platform | Windows 11 (10.0.26200), AMD64 (`win32`, `win-amd64`) |
| Installed | 40 distributions: the 39 pinned below and the pip installer, which is not pinned |
| Origin | pip installed every pinned package from a wheel; compiled ones use cp312 or abi3 `win_amd64` wheels |

## Pinned routes

The machine-readable record is
[windows-amd64-cp312.json](../tectonics/requirements/windows-amd64-cp312.json), with
one pip input per route beside it. The acceptance and visual inputs each include core.

| Route | Declared in pyproject | pip input | Pins | Tested at these versions |
| --- | --- | --- | ---: | --- |
| core | `[project] dependencies` | `windows-amd64-cp312-core.txt` | 28 | numpy 2.4.6, scipy 1.17.1, numba 0.65.1 with llvmlite 0.47.0, threadpoolctl 3.7.0, blosc2 4.13.1, shapely 2.1.2 |
| acceptance | extra `acceptance` | `windows-amd64-cp312-acceptance.txt` | +1 | psutil 7.2.2 |
| visual | extra `visual` | `windows-amd64-cp312-visual.txt` | +10 | none |

**Tested** means a Windows CPython 3.12.14 receipt in `tectonics/evidence` records
exactly that version. The record names those receipts, and a test checks that each
named receipt contains the pinned string. The receipts come from runs of earlier
source revisions. They do not show that the current code passes in this environment
today. The 26 September repair checks describe "the existing scientific environment"
but record no package versions.

**Installed only** means the package was present and its exact version is pinned,
but no Atlas receipt records or tests it. A clean installation of all three routes
from PyPI has since been verified on Windows (below); that shows the pins install
and import, not how Atlas behaves with them:

- **Core:** the other 21 transitive packages, mostly pulled in by blosc2 (numexpr,
  ndindex, msgpack, and the pydantic, httpx/h2 and rich stacks).
- **Visual:** matplotlib 3.11.2 and its nine requirements. No Windows receipt
  records a visual run at this version. The only recorded matplotlib, 3.10.8, came
  from a Linux CPython 3.13.5 environment, so treat the visual pins as untested.
  One convection test also imports pillow, which this route supplies through
  matplotlib.

**Not covered:**

- `tectonics/tools/import_tosi_case5b.py` imports pdfplumber and pypdf, which are
  neither declared nor installed in the inspected environment. That reference-data
  import route has no pins.
- The pip installer itself is not pinned.

## Recreate an environment

With a 64-bit Windows CPython 3.12.14 as `python`, from the repository root:

```text
python -I -m venv NEW_ENV
NEW_ENV\Scripts\python.exe -I -m pip --isolated --require-virtualenv install --no-cache-dir --index-url https://pypi.org/simple -r tectonics\requirements\windows-amd64-cp312-core.txt
NEW_ENV\Scripts\python.exe -I -m pip --isolated check
NEW_ENV\Scripts\python.exe -I -B tools\check_tectonics_environment.py
```

For the optional routes, install from the acceptance or visual file (each includes
core), and check with `--route acceptance`, `--route visual` or `--all`. The pip
files refuse source builds (`--only-binary=:all:`), because every observed package
came from a wheel. The verified invocation used `--isolated` and an explicit PyPI
index; the actual wheel origins are recorded below.

### Clean installation verified, 26 September 2026

A new virtual environment was created from the recorded CPython 3.12.14, with system
site-packages excluded and only its bundled pip 25.0.1. All three routes were then
installed in turn with the commands above, the cache disabled and the verified run's
additional `--disable-pip-version-check`, `--progress-bar off`, `--report` and `--log`
options. The scientific environment was only read. Full commands, wheel names and
SHA-256 digests are in the
[installation evidence](../tectonics/evidence/environment-install.json).

| Step | Result | Time |
| --- | --- | ---: |
| Core install | 28 wheels from `files.pythonhosted.org`, exact pins | 38.5 s |
| Acceptance install | psutil 7.2.2 | 1.0 s |
| Visual install | 10 wheels | 10.1 s |
| Metadata checker, all routes | PASS; no build or wheel-tag notes; pip is the only other distribution | 0.27 s |
| `pip check` | No broken requirements | 0.34 s |
| Environment-checker tests | 10 of 10 pass | 0.15 s |
| Import/render smoke check | SciPy, numba/llvmlite, blosc2, GEOS 3.13.1, psutil and a matplotlib Agg PNG all work | 3.7 s |

About 121 MB of wheels were downloaded; nothing came from a cache, a direct URL or a
source build. Pip's installed-file records report matching hashes for all 189 native
`.pyd` and `.dll` files in the two environments. This comparison read `RECORD`
metadata, not the installed files' bytes. Setting aside install-time bytecode and
pip's `REQUESTED` markers, the only differing recorded hashes are those of the
15 console-script launchers pip writes for each environment.

This shows that the pins install and load on this Windows machine from this PyPI
snapshot. It is not native execution-identity equality, checkpoint-continuation
compatibility, physics validation or geological acceptance.

## Check an environment

Run the checker with the interpreter you want to check:

```text
python -I -B tools/check_tectonics_environment.py [--route core|acceptance|visual] [--all]
```

It uses only the standard library and `importlib.metadata`. It imports no Atlas or
numerical package, installs nothing and writes nothing. It exits 1 when:

- the interpreter is outside the pinned scope (CPython 3.12.14, `win32`, AMD64, 64-bit);
- a pinned package is missing, has another version or has several installed versions;
- a pip file disagrees with the JSON record, or contains anything other than exact
  `name==version` pins, `-r` includes and `--only-binary=:all:`;
- the expanded requirements omit the wheel-only directive, repeat an included
  path or exceed the limits of 32 files, four nesting levels and 1 MB per file.

Some differences are reported as notes, not failures: a different Windows or CPython
build, a different wheel tag for the same version, and installed packages outside
the checked routes.

## What pins do not establish

Atlas's native execution identity (`atlas_tectonics.reuse.ExecutionContext`) hashes
the interpreter executable and selected numpy, SciPy, numba/llvmlite, shapely and
GEOS binaries. It also records the full `sys.version`, the machine and the platform,
and, for the numba backend, the CPU name and features. So identical version strings
can still produce a different identity, for example with another CPython build,
another wheel build or another CPU.

Pins specify a package set; they do not recreate binaries. A refused continuation
is never made acceptable by matching pins. Integrity and compatibility refusals
stay authoritative: never repin a checkpoint or edit a binding to get past one.

## Read-only viewing versus exact continuation

| Task | What it needs |
| --- | --- |
| Inspect a saved new-world bundle (`new_world_bundle.py inspect`/`result`) | A working environment for the route. Integrity-verified results from a different execution identity stay readable and are reported with `continuation_compatible: false` (`SOURCE_MISMATCH`). Native world decoding must still succeed. |
| View a W12 native result (`read_tectonics.py`) | The run's recorded environment: it authenticates the recorded source and runtime before showing anything. |
| Resume or continue native work (`run_tectonics.py --resume`, `new_world_job.py resume`, the W12 job worker) | The exact recorded sources and native execution identity. A version-matched new environment can still be refused. |

## Platforms

Only Windows AMD64 with CPython 3.12.14 was inspected and pinned. `pyproject.toml`
allows Python 3.12 and 3.13, but no 3.13 set is pinned.

Linux is unverified for the current code. On 26 September no Linux environment was
available to check: WSL is not installed on the inspected machine, no WSL
distribution is registered, and Docker and Podman are absent. None was created.
Earlier Linux x86_64 CPython 3.13.5 receipts record a different, partial version set:

- `combined-resource-acceptance.json`: numpy 2.3.5, scipy 1.17.0, numba 0.65.1,
  llvmlite 0.47.0, blosc2 4.3.3 and threadpoolctl 3.6.0.
- `review-cleanup.json`: shapely 2.1.2 and matplotlib 3.10.8.

Those receipts cover older sources and no transitive closure, so no Linux pin set
is offered. No cross-platform lock or wheel hashes are recorded.

## Updating the record

When the environment changes on purpose:

1. Inspect it read-only again.
2. Update this maintained record and its pip files together, including the
   observation date and provenance. Do not create routine dated copies; Git retains
   committed versions. Preserve any exact record still bound by a run or checkpoint.
3. Mark a package as tested only when a new receipt records that exact version.

Never edit pins to match an environment nobody has checked.
