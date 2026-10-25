# S1A sealed-reader lifetime repair

This is an explicit, additive source component over the public Plan39 selection.
It connects `ReadOnlyNative` acquisition, identity checks, failure cleanup and close
to the repaired guard module. The Plan39 store-open and publication boundaries
remain intact. It does not select a default, install a package or admit interval work.

From the repository root, using an existing compatible Python environment:

```text
python -B tectonics/optimisation/workbench/plan30/s1a/build_candidate.py --repo . --output NEW_SOURCE_DIRECTORY
```

The builder verifies the exact Plan39 builder, source map and selected members,
then applies three strict diffs and adds the guard and its existing test module.
It produces 694 files in a new `helpers`/`src` layout, with a new source manifest.
Existing destinations and changed source pins are refused. Use those two import
roots together; the inherited science/native dependencies are still required.

The repair shares one handle lifetime, lock and closed state between acquisition
cleanup, explicit close and the registered finalizer. Finalization cannot close
handles during a token query; interrupted finalizer registration cannot close the
same descriptors twice. Statistics increments are locked. `released` continues
to count first explicit closes, excluding fallback and garbage-collection cleanup.
This does not claim safety against arbitrary interruption at every OS close call.

The E2 expectation change now disables guards only in the seven freshness tests
that rewrite sealed contents in place. The other three retain guards. The first
store diff also adds a module-level import; its changes are not confined to the
reader class. All untouched selected members retain their public Plan39 bytes.

Per-batch drive-remap detection runs first and answers through the current path
walk when the mapping differs. The recorded D1-anc exception remains limited to
an ancestor-only ACL lookup error while the original objects are held. New reader
acquisition still falls back to the walk and refuses inaccessible paths. File,
sidecar, token and reparse checks remain. NTFS already refuses ancestor renames
of an open SQLite file; the guard adds prevention of sealed-file write opens.

Each resident interval consumes one CRT descriptor per ancestor (including the
drive root) plus one for the file. At the design's seven-component example and
eight-reader cap this is 56 extra descriptors. These share the process's CRT
descriptor table with other open files. Acquisition failure releases acquired
handles and retains the walk.
Evicted intervals retain the unchanged path checks.

The focused private repair evidence is reused for identical guard bytes: seven
lifetime/concurrency controls and the original 26 native guard tests passed.
The new public receiver additionally passed all 36 affected native tests (the
original 26 plus ten freshness cases), with no skips. The three unaffected E2
cases recorded 2, 4 and 2 guarded acquisitions. See `EVIDENCE.json` for source pins.

To run that bounded receiver check explicitly on Windows with the compatible
Atlas science interpreter and a new disposable scratch directory:

```text
python -B tectonics/optimisation/workbench/plan30/s1a/check_receiver.py --source-root NEW_SOURCE_DIRECTORY --scratch NEW_SCRATCH_DIRECTORY
```

The tests above create synthetic SQLite files. They establish this component's
receiver behaviour. The original `EVIDENCE.json` retains that initial source and
receiver scope; the later private-chain result below does not rewrite its receipt.

## Integrated component and private-chain disposition

The S1A source and existing-caller integration is complete and was published in
[`c4410911`](https://github.com/Atlantispy/atlas/commit/c4410911fcece5dfc61122ba3cdc082bb38d28a2).
Its store acquisition, identity checks, read batches, cleanup, close and finalizer
remain connected to the existing catalog and Plan39 publication boundaries.
The standalone public component still authenticates 694 members. The subsequent
Plan21 B constructor extends that authenticated parent with its selected storage
bindings and B rows; its separate public B source lineage has 697 members.
These are actual component source/caller connections, separate from the later
assembled and folded generation.

The selected public B-only source also passes 20 lazy-row cases, 17 actual-owner
consumer cases and two stored-carry/fallback cases: **39 passes, zero skips**.
Each mode authenticates all 697 source members before and after execution,
restricts loaded modules to the selected source and library roots, and leaves no
temporary residue. The consumer cases execute the selected owner's real methods.
This checks the public B reader `61f78511` with predecessor resources `fc81fd87`;
it does not relabel the earlier A1 consumer results as B-only proof. Its receiving
summary is identified by SHA-256
`f6bcd112ed486662b67e3e4ddb957cfe1999496340b3e7b766f929320fab31fd`.

The completed controlled private chain selects repaired S1A and full B1+B2+B3.
The private five-row A1 overlay is **UNCERTAIN / NOT ENABLED**. Existing source
and default-authority flags are unchanged; this disposition does not install a
package or activate a global default.

Measured workload: the retained private heat-ledger reopen, with fresh owned
copies, two mirrored blocks, four timed samples per arm, CPU index 3 and quiet,
exclusive resource admission. Percentages use each immediate predecessor.

| Increment | Predecessor mean (s) | Candidate mean (s) | Reduction (s) | Reduction | Both-block result |
| --- | ---: | ---: | ---: | ---: | --- |
| S1A | 12.282150 | 10.095125 | 2.187025 | 17.806532% | SELECTED |
| Full B1+B2+B3 | 10.095125 | 9.457000 | 0.638125 | 6.321120% | SELECTED |
| Private A1 | 9.457000 | 9.415725 | 0.041275 | 0.436449% | UNCERTAIN / NOT ENABLED |

S1A and B pass both predeclared blocks. A1 passes the first and fails the second;
its pooled positive mean cannot select it. All 20 timed/count children retain
five equal result fields, 8,321 page misses and 247 page hits. Required, optional
and carry refusals are zero; scopes close with zero outstanding reserved, booked
and raw bytes. Guarded samples acquire and release without fallback. All four
count samples account for 19,506 identity checks: the base performs 19,506 path
walks, while guarded arms perform two walks plus 19,504 token checks.

The private result is identified by SHA-256
`1ced0e22e0fd214ab5189b6ab68efd276d5f07be0ce7ddfea6bc42d98ac34617`.
Its selected private B reader is `74f49a0f`, distinct from the public B reader
`61f78511`. The experiment also retains the earlier S3 predecessor. These time
reductions therefore belong to the exact private reopen lineage; they are not
added together or transferred to public, final-S3, folded or whole-interval gains.
The private inputs and original execution environment are not supplied here.

Current private-source mutation checks killed 29 of 29 applicable mutants, with no
invalid kills, survivors or skips. Four obsolete mutation anchors retain the
accepted seven lifetime controls instead; this is not a claim of 33 fresh kills.
The completed combined S3/L3/S1A gate retains its exact 359 checks across 96 jobs,
including equal inherited debt and skips. Its unchanged scope was not repeated
for this integration record.

## Completion scope

Component integration, the receiving checks and the private selection above are
complete. The project owner cancelled the separate post-assembly B17/item14
verification; that requirement is **CANCELLED**, rather than a passed check.
Historical B17 measurements retain their original workload.

Assembly and fold owners retain their own implementation and checks. Installed
delivery, run admission and scientific acceptance remain separate. The existing
no-IV and other execution holds remain.
