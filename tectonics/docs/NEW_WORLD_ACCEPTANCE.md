# New-world Step 7: combined acceptance

24 September 2026 — **PASS for the bounded initial-world and regional workflow**.
WORKING NON-CANON. This closes the planned technical acceptance increment; it
does not promote the candidate plate morphology to geological acceptance.

## What ran and why

The [fixed runner](../tools/check_new_world_acceptance.py) declares its matrix
before work and retains every attempt. It adds the missing composition check,
not another full scientific suite:

| Case | Seed | Plates | Spherical support patches |
| --- | ---: | ---: | ---: |
| seed42 | 42 | 6 | 192 |
| seed43 | 43 | 6 | 192 |
| seed42-finer | 42 | 12 | 512 |

All use Earth radius/gravity and continental-lithosphere fraction 0.3. Each
creates and saves an actual world, reopens it in a new process, samples a declared
40 x 20 km regional footprint into four material parcels, saves the initial time,
then continues in another process to 50,000 and 100,000 years. All three passed
on their first attempt. No seed replacement or automatic scope reduction occurred.

Reopened views are exactly equal. Continuation restores one output, computes
only the two missing outputs and takes **zero initial-resampling time**. Every
scientific field matches direct evaluation from the original initial state;
the committed initial/prefix bytes remain unchanged. Completed reuse computes
no new outputs and returns the same scientific result.

The independent checks ask whether the area follows the exact finite-deformation
law, whether thickness changes compensate for that area change, and whether
the changing crust's weight balances the displaced mantle. All pass. Material
mass and reference-volume arrays remain exactly unchanged; unknown heat and
absolute elevation stay unknown. This checks the stated model, not observational
accuracy of the randomly prescribed forcing.

## Worlds really differ

The equal-settings seeds differ in quantities that rotating or recolouring a map
cannot change: sorted plate-area fractions have L1 separation **0.1225684**;
the largest sorted crust-thickness difference is **8,040.88 m**; boundary RMS
speed differs by **1.96266 cm/year**. Their selected regional mean surface changes
are **2.768 m** and **120.330 m** after 100,000 years. These are scenario outputs,
not a predicted global mountain-height distribution.

Changing seed42's plate count/support preserves its exact underlying geological
structure identity but changes its dependent layout and motion. The corresponding
regional surface change is **26.849 m**. Thus the code neither regenerates an
unrelated geological field just because the grid changes nor reuses stale motion.

## Measured time and storage

One pair per case, Windows / CPython 3.12.14, unchanged scientific sources/runtime.
API call seconds exclude interpreter startup and acceptance-only checking. Both
creation and reopening take place in fresh processes; no warm-process initial
generation is being compared with a cold process here.

| Case | Create/save/view | Reopen same view | Saved by reopening | Regional partial + resume | Verified completed reuse |
| --- | ---: | ---: | ---: | ---: | ---: |
| seed42 | 4.071710 s | 1.085177 s | 2.986534 s / 73.3484% | 3.621826 + 2.532902 s | 0.750637 s |
| seed43 | 3.350658 s | 1.102328 s | 2.248330 s / 67.1011% | 3.603155 + 2.478284 s | 0.778608 s |
| seed42-finer | 4.358053 s | 1.599103 s | 2.758949 s / 63.3069% | 4.047953 + 2.481086 s | 0.753338 s |

These are reuse savings, not a faster physics solver. Partial + resume includes
two execution attempts, so no uninterrupted-cold-run speedup is inferred from it.
The unchanged [S5 matched cold/reuse measurement](NEW_WORLD_EVOLUTION.md#measured-implementation-checkpoint-24-september-2026)
remains 4.937890 to 0.788870 s, saving 4.149019 s / 84.0241%.

Initial archives occupy **331,263 / 331,263 / 736,775 bytes**. Complete jobs occupy
**408,530 / 406,461 / 814,255 bytes**, each already including its frozen input
archive. Keeping both the original project and the job intentionally adds that
original archive once; audit views/logs are separate acceptance artefacts.
The largest measured process peak working set is **203,538,432 bytes (194.11 MiB)**,
including Python, libraries and validation. Native evolution's accounted peak
is **2,428,894 bytes**. The declared 128 MiB work budget is native workspace
accounting, **not a 128 MiB ceiling on total process memory**.

## Reused evidence and limits

The [combined receipt](../evidence/new-world-s7-r1.json) binds the new measurements
and source identities, and records the precise reused receipts:

- S2 numerical geometry, rotation, seed diversity and independent/withheld
  reference diagnostics, including its retained stress refusal. Its subsequent
  report-guard correction does not change the historical campaign or establish
  accepted geological morphology.
- S3 unchanged structure/thermal and per-cohort conservation checks. Its old
  project/session implementation is superseded by the S4 evidence, not repinned.
- S4 current motion/arcs, project/session guards, and 1024-patch archive evidence.
- S5's 27 sampling/evolution/lifecycle checks, including analytic pure-shear,
  translation, shortening/extension, fake-backend cancellation, source/input/
  request invalidation, corrupted-prefix refusal and real single-seed restart.
  The live native execution identity and adapter hashes match this new matrix.
- The UI owner's already integrated 132 focused checks and actual browser/native
  run remain valid within their recorded scope; they were not repeated here.

Four new acceptance-report guard tests pass in 0.231 s. The static checker passes
13 maps/41 paths; 30 safety tests pass, with one existing Windows symlink-privilege
skip (31 methods, 0.112 s). No production simulation code changed. Linux was
unavailable: `wsl --list --quiet` reports WSL is not installed. This is actual
Windows evidence, not Linux coverage or a request to install another runtime.

Supported limits are unchanged: interactive initial worlds up to 1024 support
patches, 256 MiB declared work and 120 s; regional jobs up to 256 output times,
2 MiB per record, 64 MiB outputs and 300 s per attempt, subject to the native
footprint and finite-horizon admission proof. This matrix uses a 100,000-year
regional horizon; that is not a global-evolution duration promise.

To reproduce only this matrix in the declared scientific environment:

```text
python -B tectonics/tools/check_new_world_acceptance.py --output NEW_DIRECTORY
python -B -m unittest discover -s tectonics/tests -p test_new_world_acceptance.py -v
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py
```

No new physical method was chosen in this pass. It reuses the existing native
sampling/deformation implementation and the documented pyGPlates/gFlex/Wickert
[research basis](NEW_WORLD_EVOLUTION.md#research-and-software-checked); no fresh
paper review is claimed. Next: one portable file containing the initial world
**and** its evolved results. At present the initial `.atlas` and persistent
regional job remain separate. Broader global plate-network evolution is later work.
