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

The tests create synthetic SQLite files. They establish this component's receiver
behaviour, not performance, full-stack qualification, real interval compatibility
or scientific acceptance. Historical mutant results remain historical. The
reopen comparison and chain/replay qualification remain separate.
