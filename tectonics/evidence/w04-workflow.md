# W04 step 2: integration evidence

22 September 2026. WORKING NON-CANON, local uncommitted/unpushed `remake` work.
Scope: actual supported stationary W01/W02/W03 sources -> prescribed periodic
uniform-plate support projection. Not full W04, non-periodic support, variable
rigidity, external solver agreement, empirical terrain realism or feedback into
W03 material/heat/water geometry. [Contract and sources](../docs/W04_WORKFLOW.md).

## Implemented connection

`src/atlas_tectonics/w04_workflow.py` supplies `W04SurfaceInputs`,
`W04SupportPolicy`, immutable `W04SupportResult`, `PreparedW04Support` and the
one-shot `project_w04_support`. Public exports and existing execution identity
registration are connected. Module SHA256:
`cfd808700d6e2fb2f4e3fa1966135763082d9574cf0265e1b4d43114bd62f3d8`.

The adapter uses actual W01 cell/footprint/frame/datum and geological densities,
actual W02 phase inventories, W03 compaction/pore stocks and reconciled thermal
history. Reservoir volume is explicitly placed on the same named cells and must
close the finite W03 stock. Additional external traction is a separate explicit
input, never guessed from the compaction effective-stress history. The closed
water model uses explicit air/vacuum background and matching mantle-minus-void
restoring stiffness: no extra infinite water infill is silently added.

Thermal load comes directly from the stable finite-plate integral; W03's local
isostatic comparison is excluded. Total-reference deflection, sediment-top change
and masked water-top change are returned without accumulating displacement or
mutating material states. Compatible source identities, budgets, cancellation,
finite support capacity and slope/strain/deflection gates remain active.

## Focused checks actually run

Windows 11, Python 3.12.14, NumPy 2.4.6; existing scientific environment, no new
dependencies. Commands ran with `PYTHONPATH=tectonics/src;tectonics/tests` where
appropriate. No broad suite or full geography/R4.4 run.

| Command/scope | Result | Elapsed |
| --- | --- | --- |
| `python -B -m unittest test_w04_workflow -v` | 13 PASS | 13.737 s |
| `python -B -m unittest test_w04_column_loads test_w04_load_reuse test_execution_reuse.IdentityTests test_w03_workflow.W03WorkflowTests.test_initial_inventory_and_loaded_cooling_close_independent_accounts -q` | 30 PASS | 5.348 s |
| Targeted entry/close/budget/cancellation regression after cleanup hardening | 1 PASS, already part of the 13 above | 5.493 s including shared fixture setup |
| `python -B tools/check_coding_safety.py` | 13 source maps / 41 paths PASS | Not separately timed |
| `python -B -m unittest discover -s tests -p test_coding_safety.py -q` | 30 PASS, 1 Windows symlink skip | 0.104 s |
| `git diff --check` | PASS; existing line-ending conversion warning only | Not separately timed |

There are **43 distinct focused tests**, not 44. Independent integration controls:

- Discrete sinusoidal load/response amplitude, closed-water zero net force,
  mean-displacement relation and cyclic translation equivariance.
- Independently depth-integrated W03 temperature means versus thermal pressure;
  thermal load is counted once and uses the explicitly selected restoring medium.
- Real compaction pore-to-local-reservoir exchange leaves material load unchanged
  while sediment height changes; water-top change accounts for the actual volume.
- Uniform additional pressure, exact zero reference, repeat-idempotence,
  one-shot/prepared equivalence and an explicitly shifted thermal reference.
- Source/cell/datum, reservoir closure, finite capacity, ownership, old water-bath
  stiffness and linear-validity refusals; immutable payloads and dry-cell masks.
- Changed loaded-callable refusal; reservations released on close/cancel/failed
  entry; cache hits for both material load and flexure.
- Existing W03 save/load followed by W04 reconstruction gives identical physical
  values **and result identity**. No checkpoint source rebind is performed.

Root review additionally hardened failed context-manager entry so it releases
prepared resources. The first added test expected the entry message, but close
correctly reported the independently detected changed loaded callable. The test
was corrected to accept the proper source-change refusal; release then passed.
No physical tolerance or source guard was weakened. Linux was not executed here.

## Integration timing

[Raw runs, environment and source hashes](w04-workflow-timing.json), reproduced by:
`python -B tectonics/tools/benchmark_w04_workflow.py --output tectonics/evidence/w04-workflow-timing.json`.

128 columns on a 100 km by 1 km synthetic profile; four actual W03 snapshots with
compaction/cooling and explicit reservoir/external-pressure inputs. Three
alternating timed repeats after one warm comparison. Both routes include W04
setup and closure; identical W01/W03 and surface-input preparation is excluded
from both. The comparison is fresh one-shot preparation per snapshot versus
the public shared-preparation path, **not an old shipped-version comparison**.

| Metric | Result |
| --- | --- |
| Median separate preparation, four complete projections | 3.123138900031 s |
| Median shared preparation, same projections | 1.681624000077 s |
| Time saved | 1.441514899954 s |
| Relative saving | 46.155965075384% |
| Speed ratio | 1.857215941190x |
| Shared input preparation outside both timings | 4.137581199990 s |

Every output and provenance identity is **bit-identical** between the routes.
Source checks, material/thermal/external loads, FFT solve, masks and validity
gates are retained. No disk hits, parallel workers, skipped snapshots or weaker
physics. This is W04 projection timing, not a whole-generator speed claim.

## Delivery boundary

Code, focused tests, benchmark, contract and current source guides updated locally.
The test fixture gained optional length/width inputs, keeping existing defaults,
so the integration measurement uses the declared regional dimensions. Existing
unrelated dirty edits are preserved. No commit, push, dependency installation,
old-source repin or full terrain run was performed.

Next separately scoped work: non-periodic/domain-size treatment, then variable
rigidity and general assembled W04 acceptance. The current result is a one-way
support projection, not a fully coupled evolving terrain simulation.
