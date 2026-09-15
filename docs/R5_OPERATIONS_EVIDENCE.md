# R5 operational tooling: obtained evidence

Date: 15 September 2026. Requested change: make the bounded native R5 route
operationally dependable through backup, dependency inventory and recovery tooling.
Vibe-coded with OpenAI ChatGPT under the owner's direction. WORKING NON-CANON.

Review basis: public `main` commit
`fd4677c512b46dbc6d0ebd712fd90637daffbce6` (merged coding-safety change).
The inspected native implementation is the unchanged public R5 storage/session
route with its R3/R4 dependencies. The engineering tree in the local source fixture
matches public Git tree `de32de5bbbff9a31640321f459d8c90fbb034246`.

## Delivered scope

- `tools/r5_recovery.py`: explicit dependency inventory, shared-byte backup,
  separately trusted manifest verification and new-directory staged restoration.
- `tests/test_r5_recovery.py`: synthetic byte-storage and failure-path tests.
- `docs/R5_OPERATIONS.md`: coverage requirements, private plan instructions,
  recovery/isolated-restart procedure and unresolved operational boundaries.
- `docs/examples/r5-recovery-plan.example.json`: deliberately incomplete private-plan
  template; no actual private paths, runtime or checkpoint data.
- This evidence record.
- `AGENTS.md`: route future recovery work to the runbook and honour the owner's
  requested delivery route with checked, non-forced writes.

No file under `engineering/work/` or `shared_generator/` was changed. No physics,
source binding, numerical policy, acceptance tolerance, 256-step boundary, existing
checkpoint or shared object was altered. No native import, dependency installation,
benchmark, simulation, live backup, cleanup or original Windows integration ran.
The tests make temporary synthetic recovery files only.

## Checks actually run

Environment: Linux, Python 3.13.5; standard library only.

```text
python -B tools/check_coding_safety.py
PASS: 13 selected source maps; 41 required paths.

python -B -m unittest discover -s tests -p test_coding_safety.py -v
Ran 31 tests: OK

python -B -m unittest discover -s tests -p test_r5_recovery.py -v
Ran 49 tests: OK

git diff --check
No whitespace errors.
```

The recovery tests include shared-reference deduplication, independent restored
copies, relative stores, empty stores, verification/recovery after the original
fixture directories are deleted, relocation, corruption/missing frames, malformed
metadata, traversal, symlinks, a simulated Windows reparse flag, lock refusal,
source/control mutation during copy, source-directory membership drift,
insufficient space, injected write failures/interruption, stale/tampered manifests,
case/prefix collisions, cross-platform Windows-origin path metadata, recognised
absolute dependency pin checks, unresolved relative pins and nonzero CLI refusal.

## What these results do not establish

The fixture frames are opaque bytes, **not** Zstandard produced by the native
codec. Fixture controls are storage-shaped records, **not** accepted scientific
checkpoints. No Atlas package was imported. The tool's parser/pin checks do not
replace native source/runtime, logical-row, summary or scientific-body validation.

No real Windows filesystem, native DLL, saved historical control, crash/power-loss
recovery or isolated native restart was tested. Simulated reparse flags and lexical
Windows-path tests are not Windows integration tests. The tool cannot prove a
complete dependency closure from operator declarations. NTFS permissions, service
state and hardware/network durability are outside this byte-recovery boundary.

Before relying on a real recovery point: integrate the tool separately, prepare a
private plan from the original environment, stop writers, create and independently
verify the backup, then perform the runbook's isolated native load drill without
silently repinning anything. A staged control that still resolves an absolute
reference to a live original store is not evidence of recovered-store restart.

## Tested file SHA256 values

| File | SHA256 |
| --- | --- |
| `tools/r5_recovery.py` | `7c0e25d7b9563cd1afce982e80fc379f44f41b2ea6cb2716d7393d3d0be770c0` |
| `tests/test_r5_recovery.py` | `bac2a2a6df41eeef7a8ab2ea7cba30b912dfc275d9379d1821630dbad2a23146` |
| `docs/R5_OPERATIONS.md` | `24f6013acad7eefec3df09f19235feb1758256ea95b1b02caf9495945357d0b2` |
| `docs/examples/r5-recovery-plan.example.json` | `517ffbd788c1663e386b45be5cb1b4ac9bb711a6e1453c5b0ab4721f9d149850` |
| `AGENTS.md` | `8a6c0acab57e879913a5897a5ab650e16c66539b943abe36faa5b8ab40d1b1ef` |

These are identities of this public operational-tool change, not historical native
execution bindings. This evidence file does not contain its own recursive hash.
