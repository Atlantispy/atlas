# Atlas: current development state

Source date: 15 September 2026. WORKING NON-CANON. This page is a public technical handover, not an accepted scientific model or a world dataset.

## Latest route

The wider generator programme has implementations through [generator upgrade R31](../engineering/work/generator_upgrade_r31/). The latest bounded native experiment is [native terrain R5](../engineering/work/native_terrain_r5/), building on R1–R4, [runtime R12](../engineering/work/generator_runtime_r12/) and other generator/model predecessors. It is only one part of the generator.

Recent changes:

- Native R2 addressed numerical representation and continuation limits in a saved synthetic example.
- R3 reduced repeated state copying and expanded history construction, retaining immutable compressed records.
- R4 selected interval prediction and versioned history commitments. Mapping reuse did not provide a reliable gain. Parallel trial workers were not selected because short-workload startup overhead outweighed the useful warm-worker result. Active state and accepted receipts matched in the bounded comparison; requested/rejected/refinement history changed, so full historical-body or long-run trajectory identity must not be inferred.
- R5 shares identical immutable Zstandard history frames across independent run controls. In three matched already-loaded branch-creation comparisons, time fell from 3.696854 to 0.680990 seconds and added disk from 7,996,951 to 879,786 bytes. Ordinary interval timing was essentially unchanged (observed 0.60% slower including load/proposal). This is a branch-creation/storage improvement, not another solver speedup or a whole-world timing forecast.
- A separately authorised local cleanup consolidated 828 old closed-history copies with exact recovery retained. It did not change physics or authorise further simulation. Do not repeat it from this source export.

Existing local R5 tests established bounded storage/session behaviour and a relocated portable checkpoint restart in the original environment. They do not prove that this public export runs in a different environment. No new generator tests or simulations were run merely to prepare this repository.

## Boundaries

- Physical mountain realism remains unaccepted. Earlier inconclusive or failed morphology/Landlab experiments are not positive validation of the native route.
- No full Diadem or whole-year run is authorised by this handover. The existing 256 accepted-step ceiling, physical assumptions, numerical policy and acceptance tolerances have not been relaxed.
- Successive speed measurements have different scopes and must not be added together.
- Shared history stores are dependencies, not disposable caches. The local controls, stores, private authority inputs and provenance records are deliberately absent here. A control copied without its source/store/runtime dependencies is not a restartable delivery.
- Local user-directory names and a private project identifier are sanitised in the public copy. Historical execution hashes therefore cannot automatically authenticate these bytes. Never silently repin historical runs.

## Practical next work

For a new authorised coding request, inspect the relevant current module and its retained imports, make a separate change, then run only the relevant tests in a compatible environment. Record untested assumptions plainly. A portability change must preserve source-binding, integrity and numerical checks rather than bypassing them.

This repository is a public point-in-time source handover. It does not mount or automatically synchronise the original Windows workspace. A GitHub change is not a local integration until it has actually been reviewed and applied there.

## Independent public development (separate from historical execution)

The [public development package](INDEPENDENT_DEVELOPMENT.md) provides an offline
editable source environment, new public execution identities, a synthetic integer
fixture and focused tests of the actual R12 runtime and selected native numerical
components. See its [obtained evidence](INDEPENDENT_DEVELOPMENT_EVIDENCE.md).
This does not supply the excluded recursive scientific seal, native R5 codec,
Windows runtime, private inputs or saved checkpoints. All original physical,
numerical and source-identity boundaries above remain in force.
