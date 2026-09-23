# W01 Stage 8: combined acceptance

22 September 2026. WORKING NON-CANON; local unreleased work.

Stage 8 assesses the assembled package, not merely whether Stage 7 imports.
Its executable profile is part of the existing verifier:

```text
python -I -B tectonics/verify.py --w01
```

This explicit profile does not discover every Atlas test or launch the unrelated
convection/resource campaign. `verify.py:W01_GATES` lists its exact selections;
the emitted JSON records every selected test, result, elapsed time, source hashes
before/after and runtime. A changed source, failed check, skip or empty result
cannot produce a technical pass. No installation, historical rebind or persistent
result cache is introduced. The scientific assumptions are recorded in
`cases/w01_acceptance.json`, which is included in the verification inventory.

## Two different decisions

`technical_status = PASS_SUPPORTED_WORKFLOW` means the named representation,
sampling, forcing, material-history, resource, reuse and restoration gates passed
on the recorded runtime. It does **not** mean whole W01 is scientifically accepted.
The same record explicitly retains `whole_W01_status = INCOMPLETE` and
`whole_W01_complete = false`. The command's successful exit reports the technical
checks only. Tests cover this distinction so a successful fixture cannot silently
close a scientific gate.

The original requirements remain active:

| Gate | Assembled coverage |
| --- | --- |
| Original representation | Rigid distances/orthogonality and zero finite strain; rotation order/inverse; frame/unit/epoch conversions; poles/seams; shared boundaries and reversed sided traces; initial thermal boundary limits. |
| Geological meaning | Actual mixed-cell volumes, refinement without redrawing features, explicit unknown porosity/density/temperature and whole-fragment validity rather than only an acceptable mean. |
| Motion and material history | Continuous-section and whole-footprint refusals; exact original interval; per-cohort conservation and exterior accounts; material identity independent of plate identity. |
| Spherical composition | A nonzero axial-transport case crosses longitude 180 degrees, preserves shell/reference-volume meaning and restores complete source/thermal/history records. This is not an unrestricted spherical dynamics test. |
| Numerical policy | Nonuniform MUSCL native/reference fields and accounts agree under existing material-case tolerances; the independent analytic upwind witness does not replace the default. |
| Reuse and recovery | Changed boundaries, interval, metric, geology or code cannot return the wrong cached result; a fresh process restores and continues; interruption after one cached substep leaves the saved accepted state recoverable. Completed pure cache entries are not falsely treated as accepted workflow checkpoints. |
| Resources | Live setup outputs are admitted while later stages allocate; successful/failed/cancelled work releases its reservations. Restore retains the same grid bound as construction. Admission estimates are not operating-system RSS limits. |
| Scientific acceptance | Generated plate realism remains **REOPENED**. All 5,819 PB2002 motion rows were already checked for source/Euler consistency; bounded scale-matched generated shape measurements are now available. Neither establishes independently generated dynamics. R4.4 stays held/incomplete. |

## Corrections made during acceptance

The combined ownership review found that forcing, cell and sample outputs could
remain live between preparation stages after their individual operation leases
ended. The workflow now holds staged reservations until prepared ownership takes
over, including cancellation/failure cleanup. Handover briefly admits both scopes
conservatively; it does not double-charge them for the plan's lifetime.

Restore also checks the existing 4,096-cell wrapper limit before building geometry.
No physical kernel, material policy, accuracy tolerance, transport default or
256-step ceiling changed. Existing source/runtime verification gives these changed
bytes a new execution identity; earlier snapshots are not silently rebound.

## What this does not finish

The supported described-state route has passed its assembled acceptance gates:
supplied geology and supported motion can be sampled, initialised, transported and
restored within the documented limits. R4.4 is not required to use that route.
The inputs' geological truth is not inferred from these mathematical checks.

Whole-W01 **generated geological realism** remains incomplete. R5-R9 include
substantial unimplemented process and spherical-generation capabilities, not just
validation jobs waiting to be run. Do not list them as failed tests of existing
S5-S7 initialisation. Unrestricted spherical mechanics, W03 evolved
heat/compaction, unsupported interface laws and whole-world performance claims
are neither newly implemented nor passed here.
No multi-day simulation is required merely to run this profile, and none was run.

The Stage-7 preparation-reuse benchmark remains a dated comparison of its own
source/workload. Stage 8 makes no new percentage speedup claim: it adds focused
checks and two safety corrections, not a new numerical optimisation. Its elapsed
verification time is reported separately in the obtained evidence.

See [obtained Stage-8 evidence](../evidence/w01-stage8-acceptance.md) and the
[supported workflow contract](W01_REGIONAL_WORKFLOW.md). The subsequent
[short shape validation](../evidence/w01-bounded-validation.md) records actual
generated/reference differences, finite-resolution refusals and reused motion
coverage; it does not turn an attractive outline into a scientific pass.
