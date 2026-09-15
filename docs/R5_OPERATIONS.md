# R5 shared-store backup and recovery

Atlas is vibe-coded with OpenAI ChatGPT/Codex under the owner's direction.
**WORKING NON-CANON.** These operational tools preserve selected bytes; they do not
accept terrain physics, run a simulation or establish runtime compatibility.

Implementation: [`tools/r5_recovery.py`](../tools/r5_recovery.py), Python 3.10+,
standard library only. It never imports Atlas, loads a DLL, decodes/recompresses a
history frame, repins a checkpoint, deletes history or writes to a live control.
The source-bound `engineering/work/` and `shared_generator/` trees are unchanged.

## What must travel together

An R5 branch control is **not** an independent backup. Select every control needed
for the recovery point. The tool reads each control's `history_store` and ordered
`history_refs`, inventories their shared frame dependencies and records which
store each control needs. Identical file bytes are stored once in the bundle,
while original root/path mappings are retained for recovery.

Explicitly include these additional dependency groups:

| Group | Required scope |
| --- | --- |
| Source | The exact original source closure, retained predecessors, policy files and `engineering/outputs/native-terrain-r1/checkpoint_io.py`. Do not substitute the sanitised public export for source bound to a historical run. |
| Runtime | Original interpreter/environment, numerical and geospatial packages, pinned Zstandard DLL and dependent native libraries. Source files and a requirements list alone are not an installed runtime. |
| Inputs | All private authority data needed by the selected run. Only a genuinely input-free run may declare an empty list, with an explanation. |
| Provenance | Run/configuration records, original bindings/environment inventory, acceptance records and recovery instructions. |

The tool requires declared coverage of all four groups, but **does not discover or
prove the entire dependency closure**. It additionally checks recognised absolute
`sources` SHA256 entries and `library_path`/`library_sha256` pairs in the saved JSON
against selected files. Missing or mismatched recognised pins cause refusal.
Relative native source maps and other binding formats remain unresolved and are
reported as such. The native validators remain mandatory; the tool neither
reimplements them nor changes their decisions.

Stores outside the plan's explicitly allowed roots are refused. Roots must be
disjoint. Select each external location under its own alias; never rewrite a saved
store path merely to make it fit. Only referenced frames are automatically
selected. Unselected branches and unreferenced store objects are not covered and
are never deleted. An empty referenced store directory is retained on recovery.

## Private plan and explicit execution

Copy [`examples/r5-recovery-plan.example.json`](examples/r5-recovery-plan.example.json)
to a **private location outside the public repository**. Replace every placeholder
with verified original locations. Paths in selections use `/`; root locations must
be absolute and valid on the machine doing the inventory. Directory selections
include all regular files recursively, without silently excluding files. Review
these selections for sensitive data and size before use.

The example is intentionally not runnable against the public source-only export.
It does not provide missing codecs, libraries, authority data or checkpoints. A
live local backup and Windows integration remain separately authorised operations;
no automatic backup, scheduler, cloud upload or cleanup is installed here.

After local integration is authorised, run from the Atlas repository root using a
compatible Python interpreter. The following are command shapes, not instructions
to run an unrequested generator job. Replace the example paths and digest.

### 1. Stop changes and inspect dependencies

Stop all selected generator, control, input, source and runtime writers; keep them
stopped until backup publication finishes. `--quiescent` is an operator confirmation,
**not** a process-stopping facility or filesystem snapshot. Existing R5 `.lock`
files cause refusal. Never delete a lock simply to clear the error.

```text
python -B tools/r5_recovery.py inventory --plan C:/Private/r5-plan.json
```

This reads files without changing them. Inspect the control/store mappings,
selected roles, unresolved relative source pins and original execution-binding
digests. The output contains private locations: do not paste it into a public
issue or commit it to GitHub. A successful inventory is not native validation.

### 2. Create the selected recovery bundle

Choose a **new** destination outside every source root, under an existing, secured
backup parent directory. No destination or prior backup is ever overwritten.

```text
python -B tools/r5_recovery.py backup --plan C:/Private/r5-plan.json --destination E:/AtlasBackups/r5-point-001 --quiescent
```

The tool checks free space, copies bytes into a private staging directory,
checks the copies, and re-enumerates/re-hashes the selected source scope before
publishing the completed directory. This detects changed controls, dependency
membership and copied bytes during the operation. It does not replace the need
for stopped writers, and cannot prove the absence of changes between observations.

A bundle contains:

- `MANIFEST.json`: original root locations, selected dependency declarations,
  per-file SHA256/size/role, control/store mappings and explicit verification limits.
- `blobs/<sha256>`: unique, unchanged source bytes, including controls and frames.
- `COMPLETE.json`: the manifest digest for completion checking.

**Save the returned `manifest_sha256` separately in a trusted private record**, not
only beside the bundle. Later verification requires that digest. A digest obtained
from a suspected damaged bundle cannot establish its original identity. The
internal marker is not an independent trust anchor; there is no signature system.

### 3. Verify and maintain independent recovery copies

```text
python -B tools/r5_recovery.py verify --bundle E:/AtlasBackups/r5-point-001 --expected-manifest-sha256 REPLACE_WITH_64_HEX_DIGEST
```

Verification checks the trusted manifest digest, completion marker, selected blobs,
control-to-frame closure and recognised selected source/library pins. It does not
need the original workspace or runtime. It can inspect a copied Windows-origin
bundle on another operating system without opening its original Windows paths.

Keep a verified copy on independent storage and protect both copies and the
private plan. Copying to a second folder on the same failing disk is not independent
recovery. Keep at least one known-good earlier recovery point. Verify a secondary
copy against the separately retained digest, including after transfer or suspected
damage. These are operating procedures, not scheduled actions added by this change.

### 4. Restore into a separate staging directory

```text
python -B tools/r5_recovery.py restore --bundle E:/AtlasBackups/r5-point-001 --destination E:/AtlasRecovery/r5-point-001 --expected-manifest-sha256 REPLACE_WITH_64_HEX_DIGEST
```

The tool verifies the bundle, creates independent files under
`<destination>/<root-alias>/<original-relative-path>`, checks the restored bytes,
and publishes only a verified new staging directory. It never restores into the
original roots, overwrites a destination, links writable files to backup blobs or
edits embedded locations. `RESTORE_RECEIPT.json` records the original location map
and explicitly states that live integration and native validation were not done.

**Do not load a staged control as proof of an isolated native restart while its
absolute references still point to the original live store.** That may read the
old store instead of the recovered data. Relative `store` layouts are preserved,
but source/runtime/authority bindings can still have original absolute locations.

### 5. Separate native restart acceptance from byte recovery

On a separately authorised, isolated recovery target, reconstruct the original
source/store/runtime/authority locations and dependencies without altering their
bytes. Confirm that all references resolve to the recovered inputs, not the old
live installation. Recheck the restored manifest file hashes after any transfer.

Use the original compatible native loader and its normal integrity/source checks.
Confirm expected control/body commitments, ordered history, accepted-step count and
execution binding before any separately authorised advance. Record the native
load result and the exact runtime used. Do not silently install newer packages,
recompute historical bindings, replace the codec, relax tolerances or raise the
256-step limit to obtain a pass. A different layout/platform requiring changes is
an explicit migration/portability task, not this tool's restoration procedure.

Do not retire the previous recovery point until this isolated drill has succeeded.
No native Windows load or historical checkpoint drill was possible in this public
source-only session; see [the obtained evidence](R5_OPERATIONS_EVIDENCE.md).

## Failure handling and explicit limitations

| Situation | Required response |
| --- | --- |
| Missing/corrupt frame or mismatched recognised pin | Stop. Keep the affected control/store and recover the exact bytes from a verified recovery point. Never invent a frame or repin. |
| Changed source selection during backup | Keep writers stopped, inspect what changed and start a new destination. The failed candidate is not published. |
| Stale control/publication lock | Establish ownership and that the owning process has stopped before any separately authorised recovery action. There is no force/unlock command. |
| Interrupted copy/publication | Published earlier backups remain untouched. A hidden `.incomplete-*` directory and possibly a `.recovery-lock` may remain. Inspect explicitly; no automatic cleanup or reuse occurs. |
| Missing selected dependency | Correct the private recovery plan or restore the missing dependency. Do not relabel the backup as a restartable delivery. |
| Destination already exists | Use a new empty destination name. The tool never overwrites or merges recoveries. |

These are local, cooperative-writer tools, not a hostile-filesystem security
boundary or a transactional snapshot across disks. They reject symlinks, Windows
reparse points, path traversal, alternate streams, non-regular files and ambiguous
case/path destinations. No claim is made against hostile concurrent ancestor or
mount replacement. Recovery is **file bytes and layout**, not NTFS ACLs, ownership,
alternate streams, a bootable system image or installed-service state. The tool
does not preserve executable permissions or original file timestamps.

Files are flushed and synchronised before publication, but there is no universal
power-cut guarantee for directory metadata, network filesystems or hardware caches.
Validate the completed bundle after copying or a storage failure. Directory rename
and file flush behaviour are described by the Python standard library's
[OS interfaces](https://docs.python.org/3/library/os.html); Windows junction
handling is described by [pathlib](https://docs.python.org/3/library/pathlib.html).

Backups can contain private paths, inputs, proprietary binaries and credentials
inside deliberately selected runtime/configuration trees. They are **not public
source artefacts**. Use secured parent directories and appropriate encryption/access
controls. The tool makes no encryption or Windows ACL-configuration claim.

There is no garbage collector, retention deletion, history consolidation,
automatic synchronisation, source update or simulation command. Shared stores stay
live dependencies until a separate, authorised ownership/retention review decides
otherwise.

## Focused source-only checks

```text
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -v
python -B -m unittest discover -s tests -p test_r5_recovery.py -v
```

The new tests use temporary synthetic byte fixtures, not real codec libraries or
accepted terrain checkpoints. They verify the recovery tooling, including failure
paths, without importing or running Atlas. Passing them is not native Windows,
checkpoint-continuation, physical or full-world acceptance.
