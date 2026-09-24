# Portable world projects

**WORKING NON-CANON — backend implemented, UI integration pending.**

`tools/new_world_bundle.py` saves an initial world and selected regional results
in one `.atlas` file. Loading restores the original world, saved times and the
prepared inputs needed to continue a partial run. Neither saving nor loading
generates a world, samples geology or runs the physics. Resume is a separate,
explicit action using the existing native job manager.

## What the file contains

The versioned outer ZIP contains `bundle.json`, the exact original `world.atlas`,
and, for each selected job, its original `request.json`, `initial.json`,
`prefix.json`, `status.json` and the prefix's committed `output-NNNN.json` files.
The original world is stored **once**, even when several jobs use it. Every job
must name those exact original bytes, not a regenerated equivalent planet.

The manifest schema is `atlas.world-bundle.v1`. It records world/project identity,
job IDs, exact member names, sizes, SHA-256 digests and a digest of the canonical
manifest. These establish integrity and consistency, not a digital signature or
independent scientific approval. Scientific definitions, original job IDs,
request/source/runtime bindings, attempts, errors and timing records are not
rewritten. Only committed output prefixes are saved. Lock files, cancellation
requests, temporary files, orphan outputs and machine-specific UI records are
not portable state and are excluded.

The outer ZIP uses stored members: the native initial-world array store already
uses lossless Zstandard. This avoids recompressing that data and requires no new
codec. Transfer/import is streamed in 64 KiB chunks. Active restored controls are
ordinary JSON. Import recreates each native job's isolated frozen input file;
deduplication applies to the portable archive, not a change to the native job
storage contract.

## Integrity and recovery rules

- Initial-world v1/v2/v3 files remain loadable without modification. A legacy
  file returns `kind: initial-only`, `bundle_id: null` and no jobs.
- Regional jobs must have a complete initial/prefix pair, even when the prefix
  has zero outputs. Cancellation during incomplete preparation is not magically
  restartable and returns `INITIAL_INCOMPLETE`.
- Busy jobs return `RUN_BUSY`. A stale active state or unreconciled status counts
  returns `UNSTABLE_JOB` or an integrity refusal: settle/recover the original job
  first. Stable completed, partial, cancelled, failed or interrupted checkpoints
  retain their real state; a failure is not relabelled successful because files
  exist. The original attempt ceiling is preserved.
- The native request, every prefix record, original input identity, initial
  identity, scientific output digest, context/time and world pairing are checked.
  Saved dependencies must match the current code/runtime for regional import and
  export. No automatic installation, compatibility migration or silent repin is
  performed. Portability is of data, not a bundled operating system/environment.
- Strict member allowlists, record/total limits, duplicate/linked/encrypted/
  compressed-member refusal, bounded central-directory parsing and manual member
  copying prevent archive-path extraction and unbounded decompression. No
  `extractall` is used. Native codecs still enforce their own limits.
- Saving publishes a complete, fsynced file exclusively. Loading validates all
  data in an owned staging directory, then publishes into an exclusively new
  managed directory. `ready.json` is published last. Callers adopt the new world
  only after the successful response; failure retains the previously open world.
  Rollback removes only unchanged files created by that call and its empty owned
  directories, never an existing project or arbitrary recursive tree.

Existing source-bound project/session/job/native modules remain byte-unchanged;
old saved jobs remain compatible. The new wrapper is outside the native package.

## Stable backend and UI interface

Use the declared scientific Python and trusted server-owned paths:

```text
python -B tectonics/tools/new_world_bundle.py save --file NEW.atlas --world ORIGINAL.atlas --root JOBS_ROOT
python -B tectonics/tools/new_world_bundle.py inspect --file SAVED.atlas
python -B tectonics/tools/new_world_bundle.py load --file SAVED.atlas --directory NEW_DIRECTORY
```

`save` reads exactly `{"job_ids":["lowercase-32-hex-job-id"]}` from standard input.
An empty list saves the initial world alone; `--root` may then be omitted.
At most 32 distinct IDs, 256 times per job, 64 MiB output data per job and 256 MiB
total payload are admitted. Individual native bounds remain unchanged. The
manifest is at most 2 MiB and the complete archive at most 260 MiB.

All commands return a path-free envelope:

```json
{"schema":"atlas.world-bundle-response.v1","status":"ok","data":{"kind":"combined","bundle_id":"64-hex","project_id":"64-hex","title":"World title","status":"WORKING NON-CANON","jobs":[],"generated_on_open":false,"world_file":"world.atlas","jobs_directory":"jobs"}}
```

`save` additionally reports `archive_bytes`, `stored_world_copies: 1` and
`avoided_frozen_world_copies`. Each job summary contains `job_id`, `producer_id`,
`state`, `attempt`, `completed_outputs`, `total_outputs`, `requested_elapsed_s`,
`output_ids`, `continuation_compatible`, `attempts_remaining` and its safe `error`
or null. Compatibility is not permission to reset an exhausted attempt count.
Failures return `status: error`, safe `error.code/message` and exit 2, never
private filesystem paths or raw exceptions.

After successful load, `NEW_DIRECTORY/world.atlas` works with the existing
`new_world_session.py read`. `NEW_DIRECTORY/jobs/<ORIGINAL_JOB_ID>/` works with
the existing `new_world_job.py status/result/resume/cancel` interface. UI owns
registration/routing to that imported jobs root and collision handling; it must
not rename IDs, merge into an existing conflicting job, or call submit instead
of resume. It should select committed saved times without initiating physics.
The `.atlas` upload must not be treated as the old smaller initial-only format
before its type and bounds are checked by this adapter.

Python API: `save_bundle(path, world_path, *, jobs_root=None, job_ids=())`,
`inspect_bundle(path)`, `load_bundle(path, new_directory)`. Each returns the
envelope's `data` value; `response(argv, stdin)` also supplies the exit code.

## Measured native checkpoint

One unchanged Step 7 seed42 world and its 0/50,000/100,000-year results were used,
not a new generated planet. Complete save/load took **1.845434 / 0.916799 s**;
partial save/load **0.908372 / 0.978513 s**. Calls include verification; the first
save includes lazy native startup. These single observations are not a broad
performance benchmark. An imported partial resumed in a fresh process in
**2.463330 s**, restoring one output and computing only two, with zero resampling
and exact complete scientific-field parity against the retained uninterrupted
result. Original archive and original complete job bytes were unchanged.

The complete bundle is **411,515 bytes**, versus **739,792 bytes** for the separate
original world plus complete job excluding lock files: **328,277 bytes saved (44.3742%)**
by removing the duplicate world, after container/manifest overhead. The partial
bundle is **399,059 bytes**. This is storage reduction, not a claimed solver
speedup. Native evidence is Windows-only; no new Linux run is claimed.

The native run measured the initial wrapper version. A subsequent rollback-only
hardening preserves those success-path measurements; its final guards and a
current-wrapper native read are recorded in the delivery evidence. No scientific
or source-bound job code changed. Tests replace preparation/evolution with
throwing guards during save/load to prove that opening does not regenerate.

The [bound delivery evidence](../evidence/new-world-bundle-r1.json) records source
identities, archive hashes and raw-measurement bindings. Twelve focused synthetic
archive/lifecycle methods pass in 0.645 s, alongside the real native checks above.
The required static map check passes (13 maps/41 paths); 30 safety tests pass,
with one existing Windows symlink-privilege skip (31 methods, 0.117 s).

Software inspected/reused: Atlas's native project/ArrayStore-Zstd reader, its
existing committed-prefix job protocol, and Python's ZIP container implementation.
No physical algorithm or empirical law changed, so no new physics-paper review
or realism claim is attached to this storage increment.
