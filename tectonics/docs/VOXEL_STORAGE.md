# Storage design note: lessons from Minecraft and sparse volumes

**16 September 2026 — design influence only; no voxel engine implemented.**
Michael asked whether Minecraft's large, volumetric maps suggest ways to store
Atlas geology efficiently. Yes: chunked, compact storage and limited resident
working sets are relevant. This note does not change the physical equations or
claim Minecraft-sized speed/memory for geological simulation.

## What the reference methods demonstrate

- Minecraft developer documentation separates simulation distance, rendering and
  explicit ticking areas. Stored or visible world data is not all actively updated.
  [Microsoft's guide](https://learn.microsoft.com/en-us/minecraft/creator/documents/simulationrenderdistanceguide?view=minecraft-bedrock-stable)
- Tommaso Checchi's Bedrock format note describes local block palettes and packed
  per-block indices. The protocol note is historical, not a claim that every
  current Java/Bedrock detail is identical.
  [Developer palette note](https://gist.github.com/Tomcc/a96af509e275b1af483b25c543cfbf37)
- His client-cache note describes content-addressed reuse of unchanged blobs.
  Network reuse is distinct from reducing a physics solver's computational work.
  [Developer cache note](https://gist.github.com/Tomcc/4be79d3eafcd158c5059abd4ab2e8d35)
- OpenVDB gives a more directly relevant continuous-volume reference: individual
  voxels, uniform tiles and background values, with active/inactive states.
  [OpenVDB overview](https://www.openvdb.org/documentation/doxygen/overview.html)
  This is an additional method-study reference, not a selected dependency.

## Candidate Atlas design

| Concern | Proposed adaptation | Required scientific boundary |
| --- | --- | --- |
| Large 3D material regions | Spatial chunks, material-ID palettes, uniform tiles or layer descriptions; allocate detail only where it varies | The same material may have nonuniform temperature, stress or porosity. Constant material ID is not a constant physical state. |
| Continuous physical fields | Separate contiguous arrays or sparse/implicit field representations where justified | Do not quantise temperature/stress to a tiny palette merely to improve compression. Any approximation needs an error policy. |
| RAM residency | Load required chunks/fields, with an explicit byte budget and bounded I/O prefetch | Storage residency is not permission to ignore physical influence from outside the loaded region. |
| Changed regions | Dirty flags, dependency-aware invalidation and immutable chunk identities | A changed region may affect distant drainage, heat or mechanically coupled fields; do not invalidate by viewer distance alone. |
| Uniform regions | Losslessly represent exactly identical values once | Near-uniform replacement is lossy. Unknown, empty, absent, unloaded and uniform are different states. |
| Material history | Stable material/origin IDs separate from chunk and computational-node IDs | Remapping/deformation cannot move fixed voxel IDs and assume material conservation follows. |
| Resolution | Coarse planetary/regional support plus optional fine volumetric domains/output | Output voxels are not necessarily solver cells. Scientific 3D fields, voxel storage and block rendering are independent choices. |
| Parallel chunks | Batch independent storage/encoding, bounded workers, owned writes | Coupled solvers need consistent face fluxes/halo exchange and often global solves; chunks are not automatically independent mechanics. |
| Recovery | Reuse existing verified immutable objects and publish a consistent manifest | Unchanged bytes do not make a missing dependency safe to discard; no duplicate generic cache/recovery framework. |

### Arithmetic example, not a benchmark

For a 32 cubed chunk there are 32,768 locations. Sixteen categorical material types
need 4 bits per index in an ideal bit-packed representation: 16,384 bytes (16 KiB),
plus palette and metadata. One binary64 scalar at those locations uses 262,144
bytes (256 KiB). Eight such fields use 2,097,152 bytes (2 MiB), before working copies,
solver state or history. Uniform fields can compress well; continuously varying
fields may not. These are raw storage calculations, not measured Minecraft/Atlas
memory or proposed final chunk dimensions.

The 3D count grows with depth as well as area. A hypothetical 1 km cubed domain at
1 m spacing contains 1 billion voxels. One binary64 field alone takes 8 billion
bytes (8 GB decimal). Do not extrapolate a game's visible block count into a
planet-wide simultaneous thermomechanical workload.

## Evaluation gate, when relevant storage work is authorised

Compare candidate chunks/palettes, layer columns and sparse tiles on uniform,
layered, faulted and highly heterogeneous synthetic geology. Include smooth and
sharp continuous fields. Record total resident and persistent bytes, indexing,
encoding/decoding, random access, halo reads, write amplification and actual
solver time. Match physical accuracy and conservation, not just displayed detail.

Require exact round trips for lossless data, explicit unknown/missing handling,
finite memory budget, restart after source changes, conservative material remap,
and cross-chunk results matching a monolithic reference under the declared policy.
Only then choose chunk dimensions, codec or sparse hierarchy. The current small
1D reference kernels are intentionally storage-agnostic, not the permanent world
representation and not an obstacle to 3D development.
