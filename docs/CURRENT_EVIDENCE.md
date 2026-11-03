# Current evidence: status, use and writing

This guide explains the bounded register and source/status rules.
[CURRENT_STATE.md](CURRENT_STATE.md) owns delivery status; the
[register](../tectonics/evidence/current-evidence.json) owns individual entries,
and specialist method documents own interpretation. Changed bound sources or known
dependencies can invalidate current claims; moving prose creates no qualification.

## Run it

From the repository root, standard library only (Python 3.10 or later):

```text
python -B tools/check_current_evidence.py
python -B -m unittest discover -s tests -p test_current_evidence.py -v
```

The checker never imports Atlas, runs a campaign, edits a receipt, repins a
digest or writes a file. It exits 0 on a pass and 1 on any failure. Each failure
names the record, the receipt field, the bound file and both digests. `--register`
selects another repository-relative register; paths inside a register are always
repository-relative.

## What each status means

| Status | Meaning | Checked |
| --- | --- | --- |
| `current` | Relied upon for a claim about this checkout. | The receipt must keep its registered bytes. Every repository file it binds must still have the recorded SHA-256. Every digest-bearing receipt field must be either a checked binding or an explicit `not_checked` entry (`runtime`, `artefact` or `historical`) with a reason. |
| `historical` | Retained for its recorded source snapshot; not a current claim or new validation. | Only that the file still exists with its registered bytes. Code moving on never fails it. |
| `superseded` | Replaced for current claims by the named `superseded_by` record. | As historical. The successor must exist, must not be invalid and must not form a cycle. No current record may bind it. |
| `invalid` | Known to be wrong for its own sources; kept only as a trail. | As historical. No current record may bind it, and it cannot be a successor. |

A pass means only that the declared bytes match. It is **not** runtime,
native-execution, platform or scientific verification. Recorded timings and PASS
results remain observations of the original run. Nothing is re-executed.

Classification does not require permanent checkout retention. Finished receipts
with no current consumer can leave the register and active tree after their
references are resolved; their original bytes remain in Git history. The
[pre-retirement snapshot](https://github.com/Atlantispy/atlas/tree/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence)
contains the 77 retired historical/superseded receipts. At that retirement boundary,
37 current and nine older entries remained: three supported named I01 selections
without a current successor, and six had named method-document consumers. Those
counts describe the cleanup checkpoint, not the current classification. The
register owns today's counts and remaining consumers; it does not connect to a
run store or archive.

## Coverage today

The [register](../tectonics/evidence/current-evidence.json) owns each record's
classification, checked bindings, exclusions, successor and limits. Run its
checker for current counts; this guide does not maintain a parallel receipt list.
Unlisted evidence, including W01–W12 receipts, is **unclassified**. A current
classification never means physical, platform or whole-world acceptance.

The connected I01 column chain and I02 timing were originally captured or renewed
after the 5 October optimisation batch; unchanged column and
phase/receiver/separation/G25 evidence was reused at that capture boundary.
Finite-admission r12 records engine-owned restoration and its then-bound method,
tools, restoration modules and prerequisites. On 3 November 2026, documentation-only
reconciliation changed bound method prose for 25 registered controls. Those
receipts are now historical; their original bytes, SHA-256, source bindings,
results and numerical qualification limits are preserved. Scientific contracts,
code, cases, tests and thresholds are unchanged, and no recapture or scientific
suite rerun accompanied the reclassification. The register retains the original
notes, limits and unchecked-digest qualifications for those historical controls.
Receipt references alone do not propagate reclassification: entries whose declared
bytes and bindings still match remain current, including the frozen live column
chain and I02 timing.

I02 timing r12 retains five recorded repetitions, seven passing equality/parity
comparisons and 166 checked source digests; its opaque execution identity remains
an unchecked runtime observation. Its unchanged byte bindings measure no 3-D or
spherical speed. Restoration checks trusted local consistency, not authorship. See
[I02 evidence effects](../tectonics/docs/I02_WORKFLOW.md#8-evidence-effects).

Whole-package identity and declared file binding are different. Adding I02.1
changed source membership without changing existing physical laws. Step 7 r2 and
bundle r2 predate A3's changed native reuse.py; matching adapter hashes cannot
make their native integration current. Motion-frame r2 embeds project/session
observations with changed/unbound dependencies, so the whole receipt is historical
without undoing the motion fix. Its matrix is separately classified. Known unbound
dependency drift requires historical status even when declared bindings match;
classification is no rerun.

Native R5 performance remains historical original-workspace evidence. The
[recovery qualification](R5_OPERATIONS.md#obtained-evidence-15-september-2026)
is synthetic byte-tool evidence, not renewed performance/native restart evidence;
the runbook already changed at 18dfb1d. Installation evidence binds recorded package
versions, not wheels, local smoke script, current package availability or installed
library bytes. Environment consistency has its own metadata checker.

Specialist owners retain interpretation: the [I01 closure matrix](../tectonics/docs/I01_CLOSURE_MATRIX.md)
links the selected controls and open I02–I09 obligations; the
[physical integration chapter](../tectonics/docs/how-it-works/06-physical-integration.md)
connects the column, heat, force, phase, support, admission and event contracts.
[3-D mechanics](../tectonics/docs/REGIONAL_MECHANICS_3D.md) and
[evolution](../tectonics/docs/REGIONAL_EVOLUTION_3D.md) retain fixed-box/first-order
limits. [New-world evolution](../tectonics/docs/NEW_WORLD_EVOLUTION.md#combined-lifecycle-qualification),
[bundles](../tectonics/docs/NEW_WORLD_BUNDLE.md) and
[B1 diagnostics](../tectonics/docs/NEW_WORLD_MOTION.md#matched-boundary-diagnostics-roadmap-b1)
retain scenario/recovery/descriptive limits. Local analytical/manufactured
controls do not establish calibrated rupture, native source-to-crust flow,
physical boundary birth, arbitrary curved plates or generated-world realism.
The [complete previous coverage account](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/CURRENT_EVIDENCE.md#coverage-today)
retains every dated control count, exact timing, original receipt/method link,
failure/repair and qualification limit at its original identity; these are not
fresh measurements of successors.

Every unchecked digest-bearing identity in a current receipt must be named with
a reason. Native execution IDs combine loaded code/runtime and are not file
digests. Source bindings check disk bytes, not installed runtime. Generated
worlds/jobs/output identities outside the repository are artefacts.

## Line-ending digest correction r2

Six I01 phase/receiver/separation/G25 writers used platform newlines; Windows
generated CRLF while Git retained LF. Thirteen register and six closure-matrix
digests therefore named bytes no clone received. Writers now emit LF and
test_digest_line_endings.py guards that contract. The
[r2 trail](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/line-ending-digest-correction-r2.json) retains
all old/new values and proofs. Only digest citations changed; receipt bytes,
measurements and recorded bindings were not rewritten or rerun. Affected current
receipts became historical after the writer change rather than being repinned.
The [original account](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/CURRENT_EVIDENCE.md#line-ending-digest-correction-r2)
retains the exact six-writer list.

## Successor capture after I02.2a and the writer correction

Captures were exclusive new files, ordered so downstream tools bound reviewed
upstream receipts and actual owners. No old receipt/measurement was edited. The
connected dependency order is column → weakening → column heat/motion → column
admission/thermal-motion → finite strain → finite admission/breakup. The register
owns current receipt IDs and exclusions; the I01 closure matrix owns selection.

Fifteen successors passed on 29 September: nine package-extraction controls and
six phase/receiver/separation/G25 LF captures. Eight connected receipts renewed
after 30 September cold-restart stress-resolution repair; unchanged column r2 was
reused. Eight affected controls renewed on 5 October after bitwise-kernel/
persistence integration; finite-admission r12 followed its restoration change.

Recorded closeouts were 633 I01/I02 tests, three LF checks and a 3/3 Git-normalised
guard (29 September); eight captures in 24.72 s, 758 tests and a 3/3 guard
(30 September). The [original capture account](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/CURRENT_EVIDENCE.md#successor-capture-after-i022a-and-the-writer-correction)
retains exact source identities, receipt order, test timings and historical
register counts. These are bounded controls, not full-suite or independent
physical validation. No physical law, case, tolerance or 256-step ceiling changed.
The external separation-performance harness has no successor route; its timing
remains historical. Local capture/registration is separate from Git publication.

## Optimisation integration, 5 October 2026

Integrated tooling corrections refuse incomplete candidate passes, validate quick
I02 partitions against full discovery, retain traced source/runtime provenance in
impact maps and fingerprint inherited import paths. Quick/impact runs remain
labelled; the standard full selection is unchanged. Strict execution reuses deeply
immutable constants, never mutable defaults or source-check outcomes. Numerical
reuse preserves arithmetic order, including geometry, batched special functions,
budgeted multigrid work arrays/CSR transposes. No tolerance, fastmath, solver gate
or step ceiling changed. Default 256 MiB admits the closed 8-cube control and
refuses 9 cubes; explicit 512 MiB admits the latter. The resource expectation was
corrected rather than hidden.

Focused evidence reused unchanged passes: 33 tooling tests, 29 profile tests,
382 affected numerical/geometry tests, 13 new bitwise controls and sixteen extra
baseline-byte comparisons; eight new multigrid controls plus 41 reused passes;
228 storage/reuse/project/bundle/job checks (one host-conditional skip); twelve
release/mutation/capture/retained-byte controls; six packaging and four commit-policy
checks. Eight successor captures, three receipt-binding checks, closure mirror and
seven strict workflow comparisons over five repetitions passed. Final
Git-normalised guard: 3/3 in 8.5 s with an **explicit 33-test optimisation
selection**, not the default I01/I02 suite.

The [operational comparison](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/optimisation-20261005.json)
became historical on 16 October when a bound tool added reuse.py to restoration
inventory; its external harness cannot produce a successor. One Windows machine,
one fresh process/configuration and one pass of seven workloads measured aggregate
92.574 → 78.235 s strict and 44.331 s Release diagnostic. Strict saved 14.339 s
(15.49%); diagnostic Release saved 48.243 s (52.11%) but I02 regressed 2.111 s
(55.39%). A one-pass 1.04% strict I02 change supports no reliable speed claim.
Five original digests matched; New World/job comparisons separated adapter
hash/request-ID/mode provenance from identical scientific payload. Timings include
imports. Diagnostic Release was not an installed EXE or strict scientific
qualification; required persistence checks remained enabled. Causality,
statistical confidence and world-scale benefit were not established.

The [original account](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/CURRENT_EVIDENCE.md#optimisation-integration-5-october-2026)
retains individual workloads, check timings and identity counts. PAR-2 threads,
VAL-1 ring-check removal, persistent desktop worker and bytecode-cache packaging
were excluded. Existing NumPy/SciPy/Numba algorithms and reviewed parity prototypes
were used, with no alternative physics/fresh paper review. Fidelity holds and
installed/scientific acceptance remained unchanged. No full Atlas, Linux or
whole-planet run was claimed.

## Integration checks

These are source-scoped historical integration outcomes. The
[complete original account](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/CURRENT_EVIDENCE.md#integration-checks)
retains exact selections, identities, local logs, timings and guard counts.
No full Atlas/planetary acceptance follows; earlier receipts remain unchanged.

| Integration | Outcome and retained failure/qualification boundary |
| --- | --- |
| I04/I05a, 4 October | Reviewed repairs and predeclared 42/84-row refinement passed all four fixed 3% comparisons (maximum 0.0556096%). No complete launch manifest was captured: refinement is observational, not final-tree source-sealed evidence. Finite-admission r9/timing r11 renewed their own bindings. Final explicit eleven-staircase/LF/register guard passed 3/3. [Owner](../tectonics/docs/I04_CAUSAL_START.md#reviewed-repairs-and-resolved-refinement-4-october-2026). |
| I03 K1–K5, 3 October | Path-preserving replay, all supported vertex traversals including D5 endpoints, bounded exact GEOS overlay recovery, C7 ranges and three bridge representations integrated; old schemas refuse. C1/C4 derivations follow Michael's fix authority, not invented earlier Claude approval. Of initial 323 tests, 320 passed, two expected failures remained and one obsolete refusal assertion was replaced by recovery/conservation/replay controls. Affected seams passed with unchanged results reused. Later clean 323-test run passed with the two historical expected failures. Exact fallback improved 26.2%/32.4% at 48/192 bands with identical rows/state/budget; 96 bands did not use fallback and showed no gain. [Owner](../tectonics/docs/I03_SPHERICAL_NETWORK.md). |
| I03 N1, 3 October evening | Named refusal replaces misleading errors for D1-b inside a D5 transient triangle; a pass outside it beside zero opening remains admitted. Refusal control failed previously and passes repaired; admitted control passes both. Full 325-test selection passed with two expected failures. No tolerance relaxed/new case admitted. Timing r10 superseded r9; finite-admission r8 did not bind the changed transfer file. Default guard passed 3/3 with 759 I01/I02 tests, separately from earlier explicit selections. |
| R7, 2 October | 211 affected checks covered phase/structure/heat/3-D (132), flexure (12) and coupled support/heat/save-reopen/project seams (67). New heat fixture exceeded the existing timestep bound: only its timestep changed, yielding 19 heat passes while retaining the other 113. Independent flexure tolerances stayed unchanged. Timing r7 followed other processes; overlapping capture stayed local and was not performance evidence. Default guard passed 3/3 with 759 I01/I02 tests. Initial candidate-object write refusal resolved by authorised rerun, without changing the real index or committing. |
| R4, 1 October | Corruption/races, never-started retry, accounting, cache and ZIP/input fixes integrated. Focused selections passed: 45 solver, 94 lifecycle, 65 reuse, fifteen history plus four final guards, and one restore regression. Finite-admission/timing r6 renewed their scopes; default guard passed 3/3 with 759 I01/I02 tests and no skips. |
| Original checker | Initial eleven-record register/nineteen tests integrated. Strict exponent overflow now refuses alongside literal NaN/Infinity. Eighteen passed with one Windows file-symlink skip; actual junction refusal passed. Initial one-current/nine-historical/one-superseded classifications and separate fixed-record assertion checked. No numerical campaign. |

I03 full-run/default-guard outcomes are distinct from earlier explicit-test runs.
Local integration, Git publication, installed EXE, Linux coverage and scientific
acceptance remain separate.

## Historical repair qualification

Historical explanatory pages and links may be consolidated without retaining
obsolete files solely to preserve their hashes. Digests in old correction trails
identify the original presentation; they are not repinned to revised prose.
Numerical results and original run identities remain distinguishable. Current
registered receipt/source bindings and live-run integrity have separate contracts.

These summaries preserve the interpretation of the retired narrative reports.
They do not change receipt classifications, exact source bindings or current
delivery. The full [dev40 review](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/docs/REMAKE_REVIEW_FIXES.md)
and [26 September review](https://github.com/Atlantispy/atlas/blob/1f1d78a6dd2ab3d1c533af9f9b5b79e769ce57fd/tectonics/docs/REVIEW_REPAIRS_2026-09-26.md)
retain all original test selections/commands, timings, file-identity observations
and repair chronology. Historical next actions in those versions are not current
instructions. No new scientific execution or paper review accompanies this move.

### Dev40 numerical and identity repairs

The dev39-based repairs (`7aacee7661a96ce35f78dfe61ec5228801ba44dc`) preserve
diagnostic-only recovery: cancellation after an accepted endpoint can append its
missing hash-linked diagnostic receipt before advancing, including step zero/final
step, without replaying physics or rewriting existing receipts. Audit retains
the complete chain; repeated resume adds nothing. Spherical stitching aligns
source rings to the network chart before lookup while retaining exact vertices.
Species adapters authenticate actual declared files before/after execution and
cache/resume restoration; synthetic markers apply only to explicitly synthetic
evidence, never exempt real paths. Fixed-grid/ALE transport refuses rounded clock
intervals; adjacent widths define remap distances independently of large origins.

Authored holes remain strictly interior/disjoint, while exact overlays/WKB may
retain GEOS-valid point contact; no snapping/discarding is introduced. A near-unit
fraction sum may pass its sum check but refuse the stricter conductivity bound:
no renormalisation or invented constituent resolves that separate policy question.
The [numerical assessment](../tectonics/docs/OPTIMISATION_REFERENCE.md#adaptive-accuracy-and-assessment-limits)
retains the thermal-wall, periodic-assessment, schedule/preflight and dependency
corrections. The [adaptive-inner review](../tectonics/docs/OPTIMISATION_REFERENCE.md#adaptive-inner-windows-and-returned-linux-measurements)
retains the restored Tosi-plastic certificate repair, non-unit-SI/adaptive recovery
checks and opt-in policy. Inactive adaptive solving cannot omit a strict certificate.

Focused Python 3.12.14/NumPy 2.4.6/SciPy 1.17.1/Numba 0.65.1 checks, one numerical
thread, passed 155 distinct component/workflow tests (18 material/remap, 47
geometry, 80 convection/recovery, ten species), plus 30 static tests with one
Windows symlink skip. Seven species checks repeated in the delivery checkout are
already included, not added twice. Actual R12/R24 executors/disk Store were used;
full R31/spawned scientific workers were not. Earlier 37-file byte comparison and
its results apply to the preceding checkpoint, not the subsequent adaptive return.
No full suite, mature convection campaign or world generation ran; R4.4/R4
remained IN_PROGRESS and full scientific acceptance false.

### 23 September review of 5ae74dc — reported failures resolved locally

Both surface geometry and variable flexure now import SciPy banded solvers lazily.
NumPy-only reference imports remain usable; SciPy-dependent operations explicitly
raise TectonicsError when unavailable, with no fallback/partial factor cache.
The first local rerun exposed the second eager import masked by the first. Only
tests were corrected to the already authenticated SciPy range `>=1.15,<1.18`
and integrated Tosi references; no requirement widened. Preflight still refuses
an incomplete benchmark and reads no arrays/analysis/solve. Four W07 failures
already repaired during Step 5 were rerun for thermal restart, cancellation,
corrupt-record refusal and dry-strength recovery. All nine externally failing
methods gained local passing evidence: 22 distinct focused checks, plus static
13-map/41-path and 30-pass/one-skip results, using the existing Windows environment.
No Linux/full-suite pass, physics/tolerance/solver/dependency/resource change or
speedup is inferred. Earlier W04/W07 reports remain bound to their own sources.
The observed 2,097,129-byte inventory had only 23 bytes below 2 MiB at that
checkpoint; the later bounded source-inventory representation is its successor,
not permission to increase byte limits.

### A3 follow-on: bounded source-inventory capacity

The 26 September package had 126 Python files, two below the former 128-file cap.
The successor is 512 files (386 spare); the 513th refuses before reading contents.
The 2 MiB canonical-inventory cap, 64 KiB streaming buffer, complete byte counts/
SHA-256, mutation/link guards and native step ceiling are unchanged. Raising a
ceiling allocates no 512-record array for a 126-file package. This is capacity,
not measured speed or new numerical acceptance. Source identity changes normally;
Step 7 r2/bundle r2 remain historical first-batch observations, not post-A3 passes.
Dated W08/W09 128-file statements describe predecessors.

Twenty-two focused Windows/Python 3.12.14 tests passed in 4.559 s (5.326449 s with
imports): exact capacity, a real 129-file context and mutation refusal, encoded
memory/streaming/link/loaded-code guards, both backends and legacy checkpoint
refusal. The original command selects test_source_inventory and
test_execution_reuse.IdentityTests with source/tools/tests on the import path.
Static checks passed 13 maps/41 paths and 30 tests with one unrelated Windows
symlink skip. No Linux/full suite or simulation rerun was required/performed.

### External-review first batch, 26 September 2026

The repair basis was remake e7466e8, using review/patches against 6285d4a.
[W12 assembly](../tectonics/docs/W12_ASSEMBLY.md#what-the-graph-and-recovery-actually-do)
owns exact signed-zero export, initial pressure/reservoir consistency, supplied/
effective input identities and foreign-thread closure semantics. No physical
tolerance was relaxed. [Bundles](../tectonics/docs/NEW_WORLD_BUNDLE.md#integrity-and-recovery-rules)
own foreign-binding inspection with refused native continuation and trusted-temp
staging with distinct environment errors. No metadata-only world fallback,
hidden generation, migration or dependency installation was added.

The first-batch checks passed 134 distinct methods: W12 33, bundle/project/session
51 (the corrected actual junction check closes the initial bundle symlink skip),
digest/subduction four, acceptance/worker sixteen and static thirty. One unrelated
static Windows symlink skip remained. Step 7's three-world/nine-phase r2 check
passed in 46.767698 s; native bundle r2 reused seed42 and passed in 3.875754 s,
preserving exact world/results and refusing mismatched resume. This was a simulated
foreign identity, not an actual Linux transfer. The first bundle harness caught
the wrong exception class; the product correctly returned SOURCE_MISMATCH, and
only that catch was repaired before success. Initial artefacts were retained.
Reproduction selections and first-attempt timings remain in the original report;
document maintenance does not authorise these native runs.

The r1 [line-ending trail](https://github.com/Atlantispy/atlas/blob/00b999430240365ba35af5640da940620ad8edc1/tectonics/evidence/line-ending-digest-correction-r1.json)
retains all 31 reviewed corrections across fourteen holder files and proofs of
exact CRLF/LF transformations. Twenty-two named local evidence files were
normalised with original bytes retained outside the public checkout; no whole-tree
rewrite or numerical repin occurred. Writers explicitly emit LF. The A4
[publication trail](../tectonics/evidence/public-path-redaction-r1.json) separately
records original/public digests for thirteen personal path components in three
W07 reports. Scientific values, timings, source/runtime identities and parent
digest provenance are preserved. The read-only privacy guard accepts only
LOCAL_USER, including escaped JSON paths, and reports location without content.
Thirteen synthetic privacy checks, actual public scan and two digest guards
passed. No source-package identity or Git history changed for that publication.

A2's bounded checker correction/classifications are recorded under
[integration checks](#integration-checks). A6 replaced duplicate status chronology
with CURRENT_STATE, retaining method/evidence/ownership in their homes and Git
history, rather than a new dated copy. A5's
[Windows environment owner](TECTONICS_ENVIRONMENT.md) retains 39 exact pins
(28 core, one acceptance, ten visual): eight have historical receipt strings,
31 are installed-only. Metadata matched all 39 plus extra pip; no installation or
fresh reconstruction was tested. Two failing checker fixtures exposed omitted
wheel-only directives and repeated includes; repaired rules require the directive
per expanded route and refuse repeated paths, with limits of 32 files/four levels/
1 MB per file. Ten environment tests passed; privacy/static/link checks passed.
No Linux, Python 3.13, current visual run or index-based reconstruction was
established. The proposed whole-checkout/full-suite-on-push workflow was rejected.
Holds, generated realism, full-suite and whole-world acceptance remained open.

## When it fails

- **A bound source changed.** Produce a successor receipt from the changed code
  and register it, or reclassify the old record as historical and update the
  documents that cite it. Never edit a recorded digest.
- **A registered file changed.** Review the change. An authorised correction needs
  an explicit trail, like the line-ending correction, before its `sha256` is
  updated in the register.
- **Only CRLF line endings differ.** This is still a failure; the message says so.
  `tectonics/.gitattributes` stores these files with LF. Restore the repository
  bytes of the named file after review, as recorded in the correction trail.
- **An unclassified digest field.** Add a checked binding or a `not_checked` entry
  with its reason. Do not drop the field.

## Writing rules

`pointer` is a JSON Pointer into the receipt. A whole segment `*` matches any key
or list index. `{key}` does the same and passes the matched key into the `file`
template; a rule may have at most one. For example, `/source_sha256/{key}` with
file `{key}` checks every path-to-digest entry. Paths use `/` and must stay inside
the repository. Traversal, drive letters, backslashes, streams, device names,
symlinks and reparse points (including junctions) are refused. A binding can
never target an `_id` field. A rule that matches nothing, or a field claimed by
two rules, is a failure.
