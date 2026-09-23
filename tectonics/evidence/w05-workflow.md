# W05 step 4 — recoverable, optimised requested-output workflow

22 September 2026. **WORKING NON-CANON; PASS within the declared engineering scope.**
No physical equations, accuracy limits or case inputs changed. Combined W05
acceptance remains the next step; no whole-Diadem or held R4.4 run was performed.

## Implemented and checked

`extension_workflow.py` joins the existing characteristic motion and prepared dry
support over an explicit schedule, capped at 256 outputs. Each completed output
is one atomic publication in the existing ArrayStore, with unchanged Zstd/checksum/
deduplication and SQLite FULL durability. Failed publication does not advance the
visible current state. Closed/reopened runs restore the last completed output and
continue its actual parent lineage without accumulating support onto old surfaces.

The key binds initial reference, motion/support plans, schedule and source/runtime.
Changed definitions get new keys; no old checkpoint is repinned. Exact material,
exchange, support-result and execution identities are checked, with account,
geometry, load, clock and validity-envelope reconstruction. No motion or flexure
solver is called for a completed hit. Earlier payloads are checked when loaded,
not all decoded merely to resume; missing intermediate manifests fail visibly.

Only current state is retained by the runner. Callers retaining returned arrays
must account for them. Optional persistence distinguishes cheap one-off execution
from durable recovery; it is not an automatic slow-down applied to every kernel.
Fixed edges and nine cheap derived mean fields are omitted from stored arrays,
then reconstructed bit-exactly as part of the required restore checks. Mean w and
point response are retained, so no FFT or quadrature is repeated.

## Matched measurements

Windows / Python 3.12, reference reduction backend, one numerical thread, 3200
cells at 125 m, two cohorts, requested displacements 250/500/1000 m. Three repeats;
fresh motion and workflow preparations plus closure included for every path.
Durable paths also include store open/close. Warm means a fresh connection, not a
flushed operating-system cache. Configuration, source hashing and untimed exact
comparison are excluded symmetrically. See [full timing record](w05-workflow-timing.json)
for samples, environment, budgets and every package source hash.

| Path | Median seconds | Difference from recalculation |
| --- | ---: | ---: |
| Calculate all outputs without persistence | 0.767235100 | baseline |
| First durable calculation and save | 0.857438100 | +0.090203000 / +11.7569% cost |
| Reopen completed run | 0.365163300 | -0.402071800 / 52.4053% saved |
| Resume with first output already saved | 0.757400200 | -0.009834900 / 1.2819% saved |

The small partial-resume difference is not a robust large speedup: preparation,
verification and remaining saves dominate. First-output seed cost was separately
0.458186700 s median. The paired seed-plus-resume median is 1.216164700 s, 58.5127%
more than one uninterrupted no-store run. Recovery protects completed work; it
does not make an interrupted tiny run cheaper overall. No full-generator timing
claim or recommendation to add a process pool follows from this test.

Final store: three snapshots, 619,839 encoded payload bytes, 671,744 database bytes.
Removing redundant mean fields reduced payload from the initial implementation's
1,032,553 bytes by 412,714 bytes / 39.9702%; database size fell from 1,105,920 bytes.
Raw input saving is 230,400 bytes per output. This matched-layout comparison is
recorded separately from wall time; output hashes/bytes still match. Shared
accounted peak was 38,533,376 bytes, with zero remaining reservations. This is an
allocation allowance measurement, not process RSS.

## Proportionate verification

- Seven focused workflow checks PASS in 7.929 s after the compact-layout change:
  all requested outputs, close/reopen continuation, exact material/support bytes,
  warm-hit solver call count zero, in-transaction cancellation/rollback, corruption,
  missing outputs, relabelling/schema/source/schedule refusal, budgets and lifetime.
- Nine affected shared execution-identity checks PASS in 1.514 s. The later compact
  array-layout change was covered by the workflow checks, including live-code
  invalidation; the shared identity mechanism was not changed again.
- Benchmark PASS for all three output identities, receipts and immutable arrays
  across no-store, first save, reopened reuse and partial restart. No physics sweep
  was repeated for this storage/workflow increment.
- Required source-only checker PASS: 13 selected maps / 41 required paths.
  Safety suite: 30 passed, one Windows symlink skip (31 reported, 0.105 s).
  These do not substitute for the runtime checks above.

Commands (repository root; installed scientific environment, `PYTHONPATH` set to
`tectonics/src;tectonics/tests` on Windows, the equivalent colon-separated path on
Linux; numerical thread environment set to one):

```text
python -B -m unittest test_w05_workflow -q
python -B -m unittest test_execution_reuse.IdentityTests -q
python -B tectonics/tools/benchmark_w05_workflow.py --output OUTPUT.json
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -q
```

Windows execution is measured here; no new Linux run or physical power-cut test
was performed. Rollback was tested by an injected exception inside publication.
Normal local SQLite/filesystem guarantees are retained, not extended to arbitrary
network/sync behaviour. Use existing store backup APIs, not a live file copy.

## Software and papers actually checked

- Existing Atlas `storage.py`, W02 material restoration, W03 workflow restoration
  and W05 motion/support source: reused their contracts and bounded storage rather
  than introducing a new history system. These implementations were executed.
- Official [SQLite atomic commit/recovery documentation](https://sqlite.org/atomiccommit.html),
  especially 3.11 and 4: informed one-transaction output publication and rollback.
  WAL documentation was checked for comparison; the established DELETE/FULL
  policy was retained, with no durability downgrade.
- Official [SciPy FFT convolution documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html)
  was checked for context; the existing zero-padded support algorithm was unchanged.
  This was documentation access, not execution of an external geology simulator.

No new scientific paper was needed for an engineering-only persistence increment.
The mechanism's previously reviewed Landlab/gFlex references and physical claims
are unchanged. This step establishes recoverable execution, not field realism.
