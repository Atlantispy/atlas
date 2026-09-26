# External-review repairs: first batch

26 September 2026. WORKING NON-CANON. Based on `remake` at `e7466e8`, with the
supplied review/patches against `6285d4a`. This is a scoped correctness repair,
not completion of all roadmap Phase A or acceptance of generated terrain realism.

## A3 follow-on: bounded source-inventory capacity

The live package contains **126 Python files**. Its former 128-file ceiling would
reject execution-context creation on the third additional module. The deliberate
successor ceiling is **512 files**: 386 spare slots instead of two. This bounds
the temporary path list while leaving room for development without relocating
source merely to evade identity tracking. A package split is not required now.

The **2 MiB canonical inventory limit and 64 KiB streaming buffer are unchanged**.
Every source file still contributes its full byte count and SHA-256, with no
truncation, timestamp-only reuse or relaxed mutation/link guards. The 513th file
refuses before source contents are read. No physics method, numerical tolerance,
accepted-step ceiling, cache policy or record schema changed.

Windows/CPython 3.12.14: **22 focused tests passed in 4.559 s** (5.326449 s including
imports/loading). These cover the exact capacity boundary, a real execution
context with 129 files and changed-source refusal, encoded-memory limits,
streaming/mutation/link guards, loaded code and constants, both execution
backends, and the existing legacy-checkpoint rejection gate. Reproduce:

The required source-only check also passed (13 maps / 41 paths), and its tests
recorded 30 passes plus one existing unrelated Windows symlink-privilege skip
in 0.111 s. The scoped diff has no whitespace errors. No Linux run or full suite
was performed for A3.

```text
python -I -B -c "import sys,unittest; sys.path[:0]=['tectonics/src','tectonics/tools','tectonics/tests']; r=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(['test_source_inventory','test_execution_reuse.IdentityTests'])); sys.exit(not r.wasSuccessful())"
```

This is a capacity repair, not a measured speedup. Raising the ceiling does not
allocate 512 records for a 126-file package. The native source identity changes
normally; original checkpoints and receipts are **not repinned**. The Step 7 r2
and bundle r2 results below remain evidence for the first repair batch, before
A3, not exact-current-source acceptance. No simulation rerun is needed to test
this file-count policy. Claude's parallel A2 checker must retain that distinction.
Existing W08/W09 references to an unchanged 128-file cap describe their dated
implementation history, superseded by this A3 policy.

## A4 follow-on: public path redaction

Redacted **13 personal Windows username components in three W07 reports**:
`w07-regional-mechanics-check.json`, `w07-regional-mechanics-controls.json` and
`w07-workflow.json`. Each report explicitly identifies itself as a redacted
historical public copy. The [before/after trail](../evidence/public-path-redaction-r1.json)
records the original and public file digests; original bytes are retained outside
the public checkout. Git history was not rewritten.

Only path components, publication metadata and the affected report-file digests
changed. The parent-report reference and three digest citations in two documents
now identify the redacted copies. The original parent digest remains recorded.
All scientific values, errors, timings, source/runtime identities and the earlier
line-ending correction trail are preserved. Exact preimages and parsed-object
comparisons were checked before writing; final bytes matched the prepared changes.
This is not fresh scientific evidence and does not change native execution identity.

The read-only `tools/check_public_paths.py` guard and its focused synthetic tests
check public tectonics evidence/docs for personal Windows and POSIX home paths,
including JSON-escaped separators. Only the explicit `LOCAL_USER` placeholder is
accepted. Diagnostics identify the file and line without printing private content.

Verification: **13 synthetic privacy checks passed in 0.027 s**, and the actual
public evidence/docs scan passed in **0.611 s**. The two digest/line-ending guards
passed in 0.378 s. Required static checks passed (13 maps / 41 paths; 30 tests
passed in 0.109 s, one existing unrelated Windows symlink-privilege skip).
The exposed username was also absent from non-ignored repository text. No
simulation, source-bound package edit, commit, push or Git-history rewrite ran.

```text
python -B -m unittest discover -s tests -p test_public_paths.py -k SyntheticPublicPathTests -v
python -B -m unittest discover -s tests -p test_public_paths.py -k CurrentEvidenceTests -v
python -B -m unittest tectonics.tests.test_digest_line_endings
```

## A2 integration: current-evidence checker

Reviewed and integrated Claude's read-only checker, bounded 11-record register,
19 focused tests and [guide](../../docs/CURRENT_EVIDENCE.md). Current-source SHA
checks remain distinct from native execution IDs and scientific validity.
Classified Step 7 r2 and bundle r2 as historical after A3 changed native source;
classified the whole motion-frame r2 receipt as historical because its embedded
integration observations use changed/unbound project/session dependencies.
The case matrix alone remains current. No old receipt was edited or repinned.

Corrected one parser edge case: strict JSON now rejects floating exponent
overflow as well as literal NaN/Infinity. The focused suite passed 18 methods
with one Windows file-symlink-privilege skip in 0.526 s; the real directory-junction
guard passed. The actual register checker passes: one current declaration, nine
historical records, one superseded, none invalid. W01-W12 evidence remains outside
the initial register, not implicitly accepted. No numerical campaign was run.

## First-batch repair details

- **W12 export:** retain native IEEE-754 negative-zero bits. The independent
  regression checks little/big-endian and strided float32/float64 arrays, plus
  an actual W05 output. Expected data no longer repeat the faulty zero rewrite.
- **W12 initial load:** reject inconsistent external pressure or reservoir
  allocation before preparing support. For machine-rounding differences only,
  apply one exact allocation rule to both the reference and initial output;
  preserve both supplied and effective input identities. This prevents an
  artificial first load/displacement step. Foreign-thread closure refuses before
  releasing owner resources. No physical tolerance or acceptance gate was relaxed.
- **Bundle portability:** integrity-verified saved worlds/results can be inspected
  under a foreign job execution binding. They are explicitly noncontinuable;
  native resume still refuses source/runtime drift. No metadata-only world fallback,
  automatic migration, dependency installation or hidden generation was introduced.
- **Temporary staging:** resolve the trusted system temp root before creating
  owned staging. User source/destination links remain refused. Missing safe staging
  or native dependencies produce an environment error instead of alleging damage.
- **Digest consistency:** applied the reviewed v2 hash corrections and LF policy
  for logs. All 31 changes across 14 holder files were checked against their exact
  base/postimages and CRLF/LF transformations before application. The
  [old/new correction trail](../evidence/line-ending-digest-correction-r1.json)
  is retained. Numerical measurements and original source/runtime bindings were
  not rewritten. Historical physical evidence remains historical.
- **Windows evidence writers:** explicit LF output for the layout/combined
  acceptance writers and W12 public runner/worker. The new digest guard catches
  CRLF-only references and incorrect local line endings. Only 22 named evidence
  files needed local normalisation; their original bytes were retained outside
  the public repository. No whole-checkout reset or rewrite was used.
- **Stale current claims:** fresh three-case Step 7 evidence now accompanies the
  already committed motion correction. S4/S5/S7 and bundle r1 claims are labelled
  historical instead of silently repinned. This is a bounded correction, not the
  general current-evidence registry/checker still planned in A2.

The patch's proposed whole-checkout commands and full-suite-on-every-push workflow
were not adopted. There was no commit, push or GitHub workflow installation.

## Verification actually run

Windows, CPython 3.12.14 in the existing scientific environment, with one native
thread. Static checks use the existing bundled Python. Reused the workers' actual
focused results after reviewing their diffs; no duplicate scientific suite.

| Check | Outcome | Measured test time |
| --- | --- | ---: |
| W12 publishing, assembly, ports and graph | 33 pass; native source inventory unchanged | 104.130 s; 107.317847 s including imports |
| Bundle synthetic archive/lifecycle | 14 pass, one symlink-privilege skip initially | 0.875 s |
| Project/session plus corrected Windows-junction bundle test | 37 pass, no skips; closes the preceding skipped path case | 12.097 s |
| Digest guard and two retained subduction-evidence checks | 4 pass; no coupled campaign | 0.391 s |
| Acceptance-report and W12-worker guards, including LF writes | 16 pass | 0.158 s |
| Required coding-safety tests | 30 pass; one existing unrelated Windows symlink-privilege skip | 0.112 s |
| Required static source map | 13 maps / 41 paths pass | Not separately timed |

**134 distinct methods passed**, plus one remaining unrelated static skip.
The digest guard also passed after adding the new records (0.377 s); that is not
counted twice. The unchanged full Linux suites supplied by Claude remain evidence
for their own source/platform, not a full-suite pass for these newer changes.

### Actual native connections

- The [complete Step 7 r2 report](../evidence/new-world-s7-r2.json), with its
  [predeclared matrix](../evidence/new-world-s7-r2-matrix.json), records all three
  worlds and all nine fresh-process create/evolve/resume phases: **PASS**, total
  fresh-process wall time **46.767698 s**. The reported source/runtime bindings
  agree across phases. No failed seed was replaced or scope reduced.
- Independent finite-area, thickness and column-weight checks pass. Exact
  inventories, unchanged committed prefixes, fresh-process result parity and
  meaningful seed diversity pass. The corrected regional mean surface changes
  are **181.254509 / 119.939201 / 1.644192 m**, not the old r1 values. Details and
  measured restoration savings are in [combined acceptance](NEW_WORLD_ACCEPTANCE.md).
- The [native bundle check](../evidence/new-world-bundle-r2.json) reused the
  already-created seed42 world and results. Current and simulated foreign-runtime
  inspection, exact restored world bytes, exact saved result access and refused
  mismatched resume pass in **3.875754 s**. No physics owner or generator is
  constructed while inspecting. This is not an actual Linux/Windows transfer.
- The first native-bundle harness used the wrong exception class for the expected
  resume refusal. The product correctly returned `SOURCE_MISMATCH`; only that
  harness catch was corrected before the successful check. Its first artefacts
  were preserved locally, not overwritten or reported as a product failure.

Reproduce the scoped source tests from the repository root, using the declared
scientific Python and `tectonics/src`, `tectonics/tools`, `tectonics/tests` on the
import path:

```text
python -I -B -c "import sys,unittest; sys.path[:0]=['tectonics/src','tectonics/tools','tectonics/tests']; names=['test_w12_publishing','test_w12_assembly','test_w12_ports','test_w12_graph']; r=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(names)); sys.exit(not r.wasSuccessful())"
python -B -m unittest tectonics.tests.test_new_world_bundle tectonics.tests.test_new_world_project.NewWorldProjectTests tectonics.tests.test_new_world_session.WorldSessionTests
python -B -m unittest tectonics.tests.test_digest_line_endings tectonics.tests.test_new_world_acceptance tectonics.tests.test_w12_job_worker
python -B tectonics/tools/check_new_world_acceptance.py --output NEW_DIRECTORY
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py
```

The native bundle check is an integration observation, not a new public benchmark
tool. Its recorded bindings identify the tested adapters; no speedup over the old
implementation was measured in this repair. Reopening savings are measured reuse,
not a claim that the physics solver became faster.

## A6: one current status page

Replaced the accumulated 499-line current-state log with one maintained summary
of delivery, evidence limits, active ownership and next work. At the owner's
request, there is no dated archive copy. Necessary current method information,
relied-on test receipts and imported predecessor code are not removed. Committed
document versions remain available through Git history.

The tectonics plan now points to that summary while retaining module ownership
and method specifications. Coding guidance calls for scoped, descriptive commits
when authorised and explicit evidence impact, not repeated whole-suite checks.
No scientific source, receipt, runtime, dependency or native identity changed.

Focused documentation checks covered local links and anchors, the retained
ownership anchor and the removal of obsolete archive references. The required
static map check passed (13 maps/41 paths); coding-safety tests: 30 passed and
one existing Windows privilege skip in 0.117 s. Public-path tests: 14 passed in
0.644 s; the public-path scan passed. Commands from the repository root:

```text
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py
python -B tools/check_public_paths.py
python -B -m unittest discover -s tests -p test_public_paths.py
```

This was document maintenance, not a generator benchmark or scientific rerun.
No new software or scientific method was selected; no new paper review was
required. No commit or push was made.

## A5: Windows environment record and metadata check

Reviewed and integrated Claude's seven new files: the Windows AMD64 CPython
3.12.14 JSON record, three pip inputs, [environment guide](../../docs/TECTONICS_ENVIRONMENT.md),
read-only checker and focused tests. The 39 exact pins comprise 28 core, one
acceptance and ten visual packages. Eight versions have historical Windows receipt
strings; the other 31 are installed-only, not independently tested. Current
numerical acceptance and exact native continuation identity are not inferred.

Integration found and corrected two checker defects: omission of the wheel-only
directive could pass, and repeated includes could multiply reads. Two new targeted
tests failed on the delivered checker in 0.019 s, then passed after requiring the
directive in each expanded route, refusing repeated paths and limiting a route to
32 files (retaining four nesting levels and 1 MB per file). No package pin changed.
The guide now avoids promising an untested reinstallation and follows the owner's
current-record policy rather than recommending routine dated copies.

Checks actually run from the repository root:

- `python -B -m unittest discover -s tests -p test_tectonics_environment.py`:
  ten passed in 0.136 s, including installed-metadata fixtures, pin-file consistency,
  receipt strings, privacy and the new regressions.
- With the scientific interpreter, `python -I -B tools/check_tectonics_environment.py --all`:
  PASS in 0.195 s wall time. All 39 pins match; the only extra distribution is pip.
  This reads metadata without importing numerical packages.
- `python -B tools/check_coding_safety.py`: PASS, 13 maps and 41 required paths.
- `python -B -m unittest discover -s tests -p test_coding_safety.py`:
  30 passed, one existing Windows symlink-privilege skip, 0.121 s.
- `python -B -m unittest discover -s tests -p test_public_paths.py`:
  14 passed in 0.643 s.
- `python -B tools/check_public_paths.py`: PASS. All 118 local file links in
  the affected guides resolve; the seven new files have no trailing whitespace,
  and the scoped Git diff check passes.

Linked the record from README, CURRENT_STATE, the roadmap and the W12 run guide;
added scoped checking guidance to CODING_SAFETY. Source-bound numerical code,
historical receipt bytes and runtime identities are unchanged. No install, fresh
environment, simulation, benchmark, commit or push was performed. Linux, Python
3.13, a current Windows visual run and index-based reconstruction remain unverified
by this record. No new scientific algorithm or physics-paper review was needed.

## Remaining work

A5's bounded Windows record is integrated; next is the boundary/continent/ocean-age
realism sequence. Supplied boundary-measurement code is not yet integrated. No full suite,
held R4.4, whole-world run, morphology acceptance or UI adaptation is claimed.

Software inspected/reused: the supplied Claude v2 patch and review, Atlas native
ArrayStore/geometry/job guards, Python tempfile/pathlib/ZIP, NumPy typed-array
conversion, and existing W04 finite-reservoir/reference-load contracts. No new
scientific method was selected; no new physics-paper review was required or claimed.
