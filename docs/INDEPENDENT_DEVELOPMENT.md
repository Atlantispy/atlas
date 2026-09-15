# Independent Atlas development

Atlas is vibe-coded with OpenAI ChatGPT/Codex under the owner's direction.
**WORKING NON-CANON.** This is a runnable **public-component development package**,
not a substitute installation of the private scientific runtime.

The public package provides a fresh offline environment, an editable source
installation, explicit new execution identities, public test fixtures and focused
test commands. It uses the **actual unchanged** R12 executor/cache and selected
native numerical source. It does not fabricate the missing R11 scientific seal,
create a replacement historical checkpoint codec or claim that all of R31/R5 runs.

## Capability boundary

| Profile or command | Runnable public scope | Deliberately excluded |
| --- | --- | --- |
| `runtime` | Existing R12 executor, authenticated store and process-worker tests, including real spawned child processes. | Sealed R11 science integration, private inputs and a complete generator. |
| `numerics` | Existing R2 exact-allocation tests and R1 `FaceRequestsTests`. | The long analytical-decay class, native evolution/continuation, empirical or mountain acceptance. |
| `tooling` | Existing coding-safety and synthetic R5 byte-recovery tests, plus the development package tests. | Real checkpoints, native codec operation, live backup or Windows integration. |
| `smoke` | A four-node integer graph using the original R11 graph contract, R12 executor and real authenticated disk store. Independent expected values and exact cold/warm/reference agreement. | Diadem data, historical run import, terrain evolution and benchmark claims. |
| `doctor` | Read-only capability and environment-policy information. No Atlas/native imports. | An installation or proof that missing components are available. |

`all-public` means the three explicit profiles above, **not all repository tests**.
Do not use indiscriminate discovery over `engineering/work`: many retained tests
need private authorities, old seals, libraries or a separately authorised model run.

The wider R31 programme depends on a recursively sealed R11 scientific bundle;
its original `engineering/outputs/generator-upgrade-r11/connected-reference-04/VERIFICATION.json`
is excluded. Native R5 additionally requires the original bound
`engineering/outputs/native-terrain-r1/checkpoint_io.py`, Windows Zstandard library,
source/store/control dependencies and route-specific inputs. This development
package exposes neither an import command nor a fallback for those dependencies.
Those are separate integration/portability projects, not solved by adding pip packages.

## Fresh checkout: no network dependencies

Use an ordinary writable local filesystem and CPython **3.12 or 3.13**, with no
optimisation. The tested interpreter/platform is recorded in
[the obtained evidence](INDEPENDENT_DEVELOPMENT_EVIDENCE.md); a supported-minor
policy is not a claim that every OS/interpreter combination has been tested.

No package manager, administrator rights, compiler, GIS libraries or account
credentials are needed for these public profiles. `venv` and all dependencies are
from Python's standard library. The bootstrap does not contact a package index.
Run from the repository root; paths containing spaces are supported. Avoid
symlink/reparse source roots. `.gitattributes` preserves existing source-bound
bytes on Windows checkouts; **do not renormalise historical source trees**.

### Windows PowerShell

```powershell
py -3.13 -I -B tools/develop.py bootstrap
.\.atlas-dev\venv\Scripts\python.exe -I -B tools/develop.py smoke --binding .atlas-dev/bindings/initial.json
.\.atlas-dev\venv\Scripts\python.exe -I -B tools/develop.py test --binding .atlas-dev/bindings/initial.json --profile all-public --report .atlas-dev/tests-initial.json
```

### Linux or macOS

```sh
python3.13 -I -B tools/develop.py bootstrap
.atlas-dev/venv/bin/python -I -B tools/develop.py smoke --binding .atlas-dev/bindings/initial.json
.atlas-dev/venv/bin/python -I -B tools/develop.py test --binding .atlas-dev/bindings/initial.json --profile all-public --report .atlas-dev/tests-initial.json
```

Python 3.12 can be substituted deliberately. Activation and changes to PowerShell
execution policy are unnecessary: invoke the environment's interpreter directly.
Windows/macOS commands are provided for contributors but were not executed on
those operating systems in this delivery.

`bootstrap` creates `.atlas-dev/venv` exclusively, without pip, installed third-party
distributions or system-site-package access. A plain, path-only
`atlas_public_source.pth` exposes the checkout's `development` and `engineering`
source directories to the new interpreter and test subprocesses. It contains no
executable `.pth` statements. Source files are not copied into or rewritten by the
installation. The source paths are verified on subsequent commands.

The last bootstrap step captures `.atlas-dev/bindings/initial.json`. Existing
environments and records are refused, not overwritten or adopted. A failed setup
retains its partial directory for inspection. Recreate a moved environment in a
new checkout; a virtual environment is not a portable backup.

## Make a change, then identify it explicitly

Read `AGENTS.md` and the relevant route in `CODING_SAFETY.md`. Change only the
requested boundary. Use the smallest applicable profile. After reviewing the
source difference, capture a **new** development binding:

```sh
.atlas-dev/venv/bin/python -I -B tools/develop.py capture --output .atlas-dev/bindings/change-001.json
.atlas-dev/venv/bin/python -I -B tools/develop.py check --binding .atlas-dev/bindings/change-001.json
.atlas-dev/venv/bin/python -I -B tools/develop.py test --binding .atlas-dev/bindings/change-001.json --profile runtime --report .atlas-dev/tests-change-001.json
```

Use the Windows interpreter path on Windows. Choose a new record name each time.
No command updates an old binding to make changed bytes pass. An intentional
source change makes the previous binding refuse execution; keep that previous
record as evidence. Source inventory is conservative and includes source/test/
policy files under both retained source trees and the development/tooling trees.
It is hashing for change detection, not another broad content audit.

Each binding has the explicit schema `atlas.public-development.binding.v1` and
scope `PUBLIC_SYNTHETIC_DEVELOPMENT_ONLY`. It records source-file bytes/hashes,
checkout location, Python version, interpreter/base-interpreter hashes and runtime
metadata. Cached fixture results also bind the fixture and synthetic producer.
The launcher source-captures the development package and verifies executed bytes,
not only current disk contents. A new interpreter, source change or checkout
location requires a new identity.
This does **not** grant scientific acceptance, compatibility with another runtime,
or authority to alter original seals, hash checks, tolerances or the 256-step limit.

These are local change-detection records, not cryptographic signatures against a
hostile user who can rewrite both sources and records. They are not a full lock of
all operating-system libraries or the entire standard library. Do not infer
cross-platform bitwise identity merely because tests pass. The original source/
runtime validators remain untouched and mandatory on their own routes.

## Interpreting the results

`test` launches each selected profile in a fresh subprocess and checks the binding
before and after it. A profile failure stops the aggregate; failed imports are
errors, not successful skips. The machine-readable report gives actual counts,
errors, failures and skips. A skipped test makes the profile `INCOMPLETE`, not a
fully passed result. The command exits nonzero for incomplete evidence. Permission-
dependent symlink tests may be incomplete on Windows; simulated reparse tests are
not a substitute for real Windows execution.

`smoke` compares the independent integer expectations with both the retained graph
oracle and cached execution. Repeated fixture invocations may already be warm;
the report distinguishes the first observed computation from the second warm pass.
It reports no performance forecast. The retained `SYNTHETIC TEST` product status is
preserved inside the explicitly labelled public-development envelope.

The commands do not expose arbitrary recipes, historical resume, world simulation,
cleanup, automatic sync, background tasks or scientific acceptance. Test workers
and all generated data are synthetic. Developer tests execute repository code;
this is **not** a security sandbox for untrusted pull requests.

## Keep local records private

`.atlas-dev/` is ignored by Git. It contains absolute local source/interpreter paths,
source manifests, cache authentication material and test receipts. Never commit
this directory or copy its records to public issues without reviewing/redacting
private information. Keep ordinary source changes separate from local runtime
state. This setup does not touch the original Windows workspace.

For R5 byte recovery use `R5_OPERATIONS.md`; a passing recovery fixture still is not
a successful historical native restart. For broader runtime portability, preserve
the source/identity boundary and publish a separately reviewed successor with its
own real evidence, rather than inventing missing historical files.

## Standard-library implementation references

- Python 3.13 `venv`: https://docs.python.org/3.13/library/venv.html
- Python 3.13 `unittest`: https://docs.python.org/3.13/library/unittest.html
- Python 3.13 `importlib`: https://docs.python.org/3.13/library/importlib.html

No project-wide licence or third-party notice was changed by this development setup.
