# Independent development: obtained evidence

Date: 15 September 2026. Requested change: enable independent Atlas development.
Vibe-coded with OpenAI ChatGPT under the owner's direction. WORKING NON-CANON.

Baseline: public `main` commit
`10a49165fdd7d4fa5bc349719d3219df321dc15c`.
The local baseline exactly matched Git tree
`891dd286a3835e01f1ff957dbed8abdc9e1d44ac` before this change.

## Delivered and preserved

A standard-library-only public development package, offline editable installation,
explicit fresh public source/runtime bindings, a small independent integer fixture,
focused test profiles and a documented contributor workflow. No download, pip,
third-party package installation or historical scientific seal is required for
these public profiles. A read-only capability command identifies excluded routes.

No existing file under `engineering/work/` or `shared_generator/` changed. Their
Git trees remain `de32de5bbbff9a31640321f459d8c90fbb034246` (engineering) and
`4b5dfce5f416bff0f0456b8d438e9742866dabec` (shared_generator). New .gitattributes
protects their bytes against checkout line-ending conversion; no renormalisation
was performed. New code lives outside source-bound packages.

The public fixture calls the retained R12 executor/cache through its explicit
snapshot-module interface and uses the original standalone R11 graph contract.
It does not substitute the recursively sealed scientific bundle. The source-capture
and runtime checks in the retained code are unchanged. New development bindings
have their own schema, scope and identities; no historical record is adopted.

## Checks actually run

Environment: Linux, CPython 3.13.5. A fresh checkout was materialised from the
prepared Git index without any .atlas-dev directory. The final bootstrap created
a new environment without pip or system-site-package access and installed only
plain local source paths. No manual environment repair was required in this run.

```text
python -I -B tools/develop.py bootstrap
NEW_PUBLIC_BINDING; public environment ready

.atlas-dev/venv/bin/python -I -B tools/develop.py smoke --binding .atlas-dev/bindings/initial.json
PASS: a=2, b=3, c=3, d=11
First computation: a,b,c,d. Warm computation: none. Warm reuse: a,b,c,d.
Exact agreement with independent expected values and retained graph oracle.

.atlas-dev/venv/bin/python -I -B tools/develop.py test --binding .atlas-dev/bindings/initial.json --profile all-public
runtime: 127 tests, PASS
numerics: 25 tests, PASS
tooling: 125 tests, PASS
Total: 277 tests, zero failures, zero errors, zero skips.

Coding-safety check (also run by the tooling profile):
PASS: 13 selected source maps; 41 required paths.

git diff --cached --check
No whitespace errors.
```

The tooling profile contains 31 existing coding-safety tests, 49 existing synthetic
recovery tests and 45 new development tests. This is not a repository-wide or
full-generator test count. Runtime tests include real spawned test workers.
The numerical profile excludes the long analytical-decay trajectory tests and
all native session continuation.

Additional unmocked CLI checks on the disposable checkout established:
- A binding captured in another checkout is refused (exit 2).
- Appending a byte to the public fixture makes its original binding refuse
  execution (exit 2). Restoring the exact bytes restores verification (exit 0).
- A separate subsequent process reuses all fixture results from the real cache.
- Re-running bootstrap refuses the existing environment instead of clearing it.

New unit tests cover fresh bindings, source/file-membership drift, runtime drift,
actual-executed-source checks, historical-schema refusal, strict fixture bounds,
exclusive file publication, interrupted setup, path-only source installation,
symlink/reparse refusal and malformed inputs. Some unit tests mock runtime metadata
in deliberately tiny temporary trees; the clean bootstrap, smoke, profile runs and
CLI refusal checks above use the real package and interpreter without those mocks.

## Not established

No Windows or macOS execution, CPython 3.12 execution, full R31 integration,
native R5 codec/history continuation, complete scientific runtime installation,
original Windows integration or historical-checkpoint restart was tested. The
supported-minor policy and documented OS commands are not test evidence for those
environments. Source inventory/runtime metadata do not lock every OS or standard-
library binary and are not signatures against a hostile owner of both code and
records. The setup is not a security sandbox for untrusted repository code.

No physics, acceptance tolerance, numerical policy, 256-step boundary or original
binding changed. No world/trajectory simulation, benchmark, live backup, cleanup,
automatic sync, CI workflow or background task was performed. Bounded unit tests
and a four-node integer graph are not mountain/scientific acceptance evidence.
Private plans, absolute local paths, authentication keys, test environments,
installed libraries and generated binding records are not published.

## Tested file identities

These SHA256 values identify this public development change, not historical
execution bindings. The evidence file does not include its own recursive hash.

| File | SHA256 |
| --- | --- |
| `tools/develop.py` | `500ab37f6ca7ea09951219dd93b62ae866c18609dd8f443a21b8b1633ab6c328` |
| `development/atlas_dev/__init__.py` | `79127dafcb2d8a0ccefddedd7e10156a2377f4fa563a3def1ced0b5399726725` |
| `development/atlas_dev/core.py` | `f072cbf773a5efad4264cf0e15659ea10d080a5df1ce0107d0dd53883c4d8e67` |
| `development/atlas_dev/cli.py` | `da29bba5787d5deb04a8aa6bc935d0c9c9c70330ac7aeabd74d27df0df9753b5` |
| `development/atlas_dev/fixture.py` | `a8430b539a01286794ad330b7a2bb1b31339582d5281029e52edd36bd72e21e2` |
| `development/ENVIRONMENT.json` | `1af5778434ddef09b724e8586dcd4330a02aca9770075177dfada269660ae28d` |
| `development/PROFILES.json` | `3fc3809c4c9784dfe8ebf7055462b164492e9d8f066a054c37337641b1e67a1e` |
| `development/fixtures/runtime_graph.json` | `f24968e1d3689fc4e0beb94ce13004adfd8fccb3fec689f8c5aff9d8fa39d9e3` |
| `tests/test_development.py` | `9641aa0e0835a3c8c92f2d47948cd4d8a3074bf28b586b1d62969d2c45db9de1` |
