# Atlas tectonics remake — first development increment

**Branch: `remake`. WORKING NON-CANON. Mathematical verification, not accepted terrain.**
Vibe-coded with OpenAI ChatGPT/Codex doing the coding under Michael's direction.

This new, isolated package starts the revision 3 tectonics plan. It imports neither
`engineering/work` nor `shared_generator`, alters no historical bindings and does
not form a new chain of copied predecessor globals. `main` and the original Windows
installation are not changed by this branch.

## Implemented now

| Kernel | Actual capability | Not yet supplied |
| --- | --- | --- |
| `Rotation`, `rigid_velocity` | Normalised finite quaternion rotations, ordered composition, inverse, batched positions and instantaneous omega cross r | Plate polygons, automatic topology, rotations inferred from forces |
| `boundary_motion` | Relative and boundary-frame planar motion, with explicit east/north orientation and right/left declarations | Geometric sidedness auditing or inferred physical fault slip |
| `advect_thickness` | One conservative, positivity-preserving upwind step on a periodic 1D grid, including spatially varying prescribed velocity | Open boundaries, sources/sinks, fault creation, subduction or historical integer-ledger migration |
| `half_space_temperature` | Analytical half-space cooling with explicit zero-age/surface conditions and batched queries | Evolving thermal PDE, finite cooling plate, heat sources or calibrated material law |
| `PeriodicFlexure` | Batched uniform-rigidity periodic 1D finite-difference flexure, diagonalised using FFT; reusable immutable coefficients | Variable rigidity, free edges, spherical shells, load construction or the cause of uplift |
| Parameter records | Immutable typed SI parameters, validation, content identities and explicit derived values | Public customisation UI or an approved Earth calibration |

These are usable scientific kernels with tests, not empty interfaces. They do not
complete W01–W04, close all geological decisions or implement the coupled W05
extensional experiment. No mantle dynamics, real-world geology validation, full
Diadem generation or benchmark is included.

## Run the focused verification

Use an existing CPython 3.12/3.13 environment with NumPy 2.x. The tested combination
is recorded in `evidence/foundation-tests.json`; other combinations are compatibility
intentions, not observed passes. No installation, network access or scientific
package execution is performed by this command:

```sh
python -I -B tectonics/verify.py
```

From inside `tectonics`, the equivalent command is `python -I -B verify.py`.
The script writes test detail to stderr and a new verification record to stdout.
It refuses missing dependencies rather than installing them. An optional editable
installation can use `pyproject.toml` in a separately prepared environment; that
packaging route was not used or tested in this delivery.

Tests check analytical rotations and invariance; independent flux-loop transport;
Courant rejection and closed budgets; error-function thermal values and limits;
and flexure against an independently assembled real-space linear system. Smooth
refinement cases test first-order transport and second-order finite differences.
A passed comparison is mathematical evidence only, not geological acceptance.

## Design choices

- Physical parameters are passed explicitly; no Earth/Diadem values are buried in
  kernels. `cases/foundations.json` contains deliberately synthetic labelled values.
- Arrays are binary64 process fields. They do not replace the old fixed-quantum
  material ledger. Input arrays are detached; returned arrays and coefficient
  arrays have immutable byte backing.
- Rotations, thermal queries and loads can be processed in batches. No per-cell
  worker pool, GPU backend or speed-up claim is added for these small fixtures.
- Flexure reuses an unchanged operator, not previous answers. Its identity includes
  grid, material parameters and numerical method. It is not a signed run receipt.
- Periodic domains are an explicit first verification choice, not a global-world
  assumption. Storage chunks must not become independent physical boundaries.
- Read the [scientific case](docs/FOUNDATIONS.md) and the
  [voxel/chunk storage design note](docs/VOXEL_STORAGE.md).

## Next development gate

Review these equations and tests independently, then extend the narrowly specified
initial-condition/transport/support cases. Open boundaries, conservative material
creation/recycling and a physically defined load connection precede a claimed
extensional terrain experiment. Do not jump to production integration because
mathematical tests pass. Full 3D storage and global mechanics remain separate tasks.
