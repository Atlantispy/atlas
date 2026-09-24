# W08 Step 6 — joined finite-stock histories and recovery

Status: WORKING NON-CANON, local implementation, 23 September 2026.
The original [W08 design](W08_REGIMES.md) and [case register](../cases/w08_regimes.json)
remain unchanged. The new [joined fixture](../cases/w08_joined_r1.json) was frozen
before candidate execution, SHA256
`01269a9de5e3c94f7adf04f8aed5e970364af5f8af49889bd733e9f97d4395d4`.

## Supported joined route

`PreparedW08Workflow` serialises an explicit dated sequence of finite shortening,
full-vector affine transform/oblique motion, prescribed crust/mantle retirement,
finite magma transfer and cessation. It composes the existing finite affine maps,
retirement and reservoir algorithms; it does not replace their physical laws.
The inputs are `W08Inventory`, `W08Region` and immutable `RegimeInterval` records.

Each physical node owns its complete component masses and signed isobaric
enthalpy once. Crust, mantle, melt, solid source, reservoir, intrusion, extrusion,
accretion, deep storage and export remain distinct. Incoming retirement material
credits declared destinations simultaneously. Magmatic outlets compete in the
existing coupled transfer solve. Unselected stocks survive every regime change.
In particular, cessation changes the clock, not the reservoir contents.

Node origin/formation labels describe the supplied stores, not the age of a
newly mixed receiving rock. Tagged donor/component/enthalpy transfer receipts are
preserved for the entire bounded history; mixing never silently assigns the
receiver's initial age to incoming material. No new birth or phase conversion is
inferred merely from a regime label. A supplied thermal closure is forwarded to
the existing magmatic phase checks.

Transitions require a unique event ID, old/new regime, named boundary,
continuous represented geometry, polarity and coupling/kinematic/thermal source
bindings. Changed forcing starts a new segment and a new material operator;
changed coefficients cannot reuse an old numerical factor. Supplied dates split
the history. If a finite stock exhausts earlier, the supported exact endpoint is
computed and committed before `W08ExhaustionError` stops unspecified continuation.
The exception exposes its retained `.output`; loading it does not spend it again.
The existing refusal of singular mixed-recharge depletion remains unchanged.

This joined route uses prescribed affine footprints and homogeneous stock
withdrawal/placement. The previously accepted non-affine fault/network tools,
steady wedge diagnostics, explicit host-replacement and heat-paid melting tools
remain separate typed component operations. They are not silently converted into
arbitrary transient histories. Unsupported continental entry, geometry jumps,
empty pass-through and an unspecified simultaneous retirement/melting law refuse.

## Regional physical owners

`W08Region` conservatively allocates selected current stocks to disjoint planar
parcels using supplied unit-sum mass weights and receiving densities. It exposes
immutable component mass, mass, advected enthalpy, volume and thickness. Density
changes affect volume but do not manufacture mass or heat.

The reference and current footprints are retained. The load contribution is
`g*(current mass/current area - reference mass/reference area)`; shortening and
emplacement therefore enter once. Intrusive underplating and surface extrusion
have separate volume/thickness contributions. The terminal stock and its spatial
view are one material, not two inventories. Advected enthalpy is not an extra
latent-heat or radiogenic source. The view is a physical input to the W03/W04/W07
owners, not a second flexure, thermal PDE or free-surface solve. Host displacement
or replacement still requires its explicit finite-host Step 5 operation.

## Checkpoint and cache contract

Only a completed supplied interval or a validated exact-exhaustion endpoint may
be saved. One `ArrayStore.put` transaction publishes current/reference geometry,
reference stocks, component/enthalpy stocks, formation/origin bindings, finite
deformation, completed event cursor, exhausted nodes, owners and transfer history.
The output identity and parent checkpoint/output identities are checked together.
The immutable chunk store reuses identical payloads; no new history-storage stack
or copied grid for every intermediate evaluation was added.

Restore verifies the contiguous metadata prefix and latest payload, recreates
the typed state, reconciles every node against its tagged transfers, checks
reference geometry/finite deformation, then continues at the next interval.
Completed material solves are not replayed. Corrupt or incomplete payloads,
partial events, missing prefix entries, changed owners or source/runtime bindings
refuse. Explicit foreign checkpoint IDs refuse rather than becoming a cache miss.
This is active-state recovery, not a full re-read of every historical payload.

Candidates are immutable and separately admitted before publication. They become
the active state only after commit. Both pre-commit rollback and interruption
after commit/before adoption are tested. All producer and store work shares the
128 MiB accounting envelope, one native numerical thread and 256 cumulative
accepted intervals, including internal variable-mass integration steps. The
tagged-history metadata is bounded to 512 KiB. Accounted work is not process RSS.
Only the latest live output is retained; caller-retained older outputs require
their own allowance. Source membership remains bounded to 128 files (115 now).

## Acceptance and timing

The frozen A07 control transfers exactly 6 kg at 4 kg/s up to 1.5 s, then retains
all stocks to 3 s. The five-regime control composes shortening and shear, retires
finite crust/mantle and feeds a mixed reservoir, intrusion and extrusion before
cessation. Its controls cover 8/16/32 parcels and 1/2/4 interval partitions.
The existing 1e-10 exact-map and 128-epsilon extensive gates were not loosened.

Eleven inventory, six regional-view and ten workflow test methods have passing
Windows evidence. Nine shared execution-identity checks also pass. Focused
coverage includes exact restart, no flux replay, exhaustion, source changes,
owners, atomic failure, corruption and missing history. Static safety remains
13 selected source maps and 41 required paths. No Linux execution or whole-world
campaign is claimed by this Windows run.

The [joined timing report](../evidence/w08-joined.json) separately measures cold
preparation/execution/materialisation, a prepared latest-result hit, first write,
verified restore and interrupted continuation, with three rotated repeats. It
also measures three identical requests with and without preparation reuse,
including setup, close and output materialisation on both sides. Faster paths
are not advertised as a whole-generator or new-physics speed-up.

Measured Windows medians (three rotated repeats, all final bytes identical):

| Matched three-request workload, setup included | Seconds |
| --- | ---: |
| Repeated cold preparation | 2.9310746 |
| Prepare once, reuse twice | 1.0546066 |
| Saving | **1.8764680 (64.0198%)** |

The single cold complete result costs 0.9988960 s. Separately timed operations:
prepared latest hit 0.0541844 s; first checkpoint pack/validate/write 0.0614539 s;
verified restore after preparation 0.0673941 s; prefix recovery/remaining two
intervals/checkpointing after preparation 0.4334950 s. These narrow timings
exclude the explicitly recorded setup and are not the setup-inclusive claim.
Including new preparation and close, restore costs 0.5363079 s (0.4625881 s,
46.3099% saved versus cold); continuation costs 0.8833820 s (0.1155140 s,
11.5642% saved). Previous checkpoint creation is a sunk cost, excluded from both
recovery comparisons. First-write timing is one final checkpoint in an empty
store; a complete restorable prefix is used in both recovery routes.

The entire timing/control run took 34.8141 s. Maximum shared admitted work was
36,341,666 bytes (34.6581 MiB), including store work and untimed seed preparation,
against the unchanged 128 MiB cap. This is not RSS. Evidence SHA256:
`d3dcd38bbe98d4d3d4c8faf15afdede5850c8b3fda2993e76cd179537870a8af`.

The Step 2 shortening/foreland, Step 3 distributed-strain, Step 4 five-case
subduction and Step 5 basalt thermal/density references remain their existing
labelled evidence. This integration adds no new geological calibration and does
not repin old reports to the changed package identity. The expensive subduction
campaign was not repeated; its physics, mesh choices and gates were not changed.

Exact execution: the 11 inventory methods passed in the first 21-method run;
the four storage tests initially exposed a test harness error (directory passed
as SQLite filename), corrected before their successful 10.798 s run. The final
10 workflow methods passed in 18.037 s. The regional owner's six methods passed
in 0.033 s. After the final resource-lifetime adjustment, the two affected
restart/atomic methods plus nine identity methods passed in 7.784 s. The static
suite passed 31 methods with one environmental skip in 0.125 s. Passing
unaffected checks were reused; no whole-project suite was rerun.

Reproduction, from the repo with the approved scientific Python environment:

```text
PYTHONPATH=tectonics/src;tectonics/tests
python -B -m unittest test_w08_inventory test_w08_region test_w08_workflow
python -B -m unittest test_execution_reuse.IdentityTests
python -B tools/check_coding_safety.py
python -B tectonics/tools/check_w08_joined.py --repo . --report NEW_REPORT.json
```

On Linux the two `PYTHONPATH` entries use `:` rather than `;`.

## Research and existing software checked

- [PETSc TSSetEventHandler](https://petsc.org/release/manualpages/TS/TSSetEventHandler/):
  documentation read. Event location and the state/equation change are separate;
  the workflow commits their complete event boundary, not a half-applied update.
- [PETSc TSRestartStep](https://petsc.org/release/manualpages/TS/TSRestartStep/):
  documentation read. Discontinuous state or coefficients invalidate continuation
  history. New regime segments prepare fresh material operators.
- [Keller and Suckale (2019)](https://academic.oup.com/gji/article/219/1/185/5523132):
  conservation/transfer excerpts rechecked, not the entire paper. Distinguishing
  internal transfers from external sources and conserving each component informed
  the joint accounts. Atlas does not claim to implement that paper's multiphase
  continuum dynamics.
- Existing Atlas W07 parent-linked recovery, W08 finite-motion/material kernels
  and transactional `ArrayStore` were inspected and reused. No external solver
  was installed or executed for this increment.
