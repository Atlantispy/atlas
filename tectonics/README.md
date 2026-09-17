# Atlas tectonics remake

**Branch: `remake`. WORKING NON-CANON. Mathematical verification, not accepted terrain.**
Vibe-coded with OpenAI ChatGPT/Codex under Michael's direction.

This isolated package follows the [tectonics plan](docs/TECTONICS_PLAN.md) and
[consolidated optimisation reference](docs/OPTIMISATION_REFERENCE.md). It imports
neither `engineering/work` nor `shared_generator`. Historical bindings, numerical
limits, checkpoints, `main` and the original Windows installation remain separate.

## Implemented calculations

| Component | Capability | Boundary |
| --- | --- | --- |
| Rotations and boundary motion | Finite quaternion rotations, ordered composition, inverse, batch positions and relative motion; scale-safe normalisation | No generated plates, force balance or geometric sidedness audit |
| Thickness transport | Conservative, positivity-preserving periodic 1D upwind update; private scratch reuse and accurate `math.fsum` accounting | No open boundaries, material birth or subduction |
| Half-space cooling | Analytical temperature with explicit depth/age/parameters; reference and opt-in SciPy array backends | No evolving thermal PDE or calibrated material profile |
| Periodic flexure | Uniform 1D centred-difference operator solved with FFT; immutable setup reuse and scaled extreme-range arithmetic | Not continuous spectral k^4, variable rigidity, open edges or the cause of uplift |
| Parameter records | Immutable typed SI values and identities, without hidden Earth/Diadem defaults | No user customisation UI or new scientific calibration |

These do not complete W01-W04 or supply the W05 coupled extension experiment.
Physical validation and production integration remain outstanding.

## Memory and persistence increment (17 September 2026)

- Masked numerical inputs are refused before their missing-value information can
  be discarded. Shapes and projected array work are checked before bulk allocation.
- `WorkBudget` bounds estimated simultaneous kernel allocations, including shared
  reservations across threads. The default local envelope is 256 MiB; callers can
  supply a different explicit budget. This is **not a total process RSS cap**:
  caller-owned inputs, retained outputs and native allocator overhead remain separate.
- Transport reuses private donor/scratch arrays without mutating the input or
  changing the shared-face update. Accurate budget summations are retained.
- `backend="scipy"` opts into bulk error-function evaluation. It is numerically
  compared, not claimed bit-identical to `math.erf`. Missing dependencies cause an
  explicit error, never a silent backend substitution.
- Flexure restoration rebuilds its immutable coefficients from the typed definition.
  The method identity is versioned for range handling. Transport-result restoration
  also re-establishes immutable array backing; generic NumPy pickle is not a storage contract.
- `ArrayStore` provides typed, immutable array snapshots in a **local SQLite file**,
  with chunk deduplication, exact uniform encoding, optional integer palettes,
  optional Zstd via Blosc2, and byte/bit/no-shuffle choices. Compression uses one
  thread per call. Encoding records name codec/filter/version; raw storage is used
  when it is smaller. This is a declared encoding choice, not missing-dependency fallback.
- A repeated snapshot reuses unchanged chunks; one changed chunk stores one new
  payload. Each manifest references chunks directly, without long temporal delta
  chains. There is no automatic deletion or history migration.
- Reads validate stored and logical hashes, lengths, shape and dtype. Arrays restore
  with immutable byte backing. A bounded decoded-chunk LRU, direct chunk reads and
  streaming avoid requiring a complete decoded snapshot in RAM.
- SQLite transactions coordinate writers and publish complete snapshots. Conflicting
  results for one identity, corrupt records, missing chunks and exceeded limits are
  errors. `backup_to()` makes a consistent independent copy to a new file.
- `cached_temperature` and `cached_flexure` are optional wrappers outside the physics.
  Keys include typed input bytes, resolved parameters, selected backend, package
  source, loaded Python instructions and selected runtime binary identities.
  Profiles and input descriptors remain in the stored manifest, not just a filename.
  Source/instruction identity is rechecked before publication.

SHA-256 here detects corruption and supports identity; it is not a signature or a
security boundary against an attacker controlling the process or database. The
local directory must be owned/trusted. Binary runtime files are assumed immutable
for the lifetime of a process. This is not a recursively sealed historical runtime.

### Example: optional persistent cooling

Use an existing compatible environment; no command here installs dependencies.
The directory must already exist. Values below are **synthetic test values**, not
an Earth profile. The storage limits are example execution limits, not owner budgets.

```python
from pathlib import Path
import numpy as np
from atlas_tectonics.parameters import ThermalParameters
from atlas_tectonics.resources import WorkBudget
from atlas_tectonics.storage import ArrayStore, StoreLimits, Compression
from atlas_tectonics.reuse import cached_temperature

limits = StoreLimits(chunk_bytes=32768, max_array_bytes=8*1024**2,
                     max_store_bytes=32*1024**2, decoded_cache_bytes=128*1024)
profile = ThermalParameters("synthetic", "example only", 300., 1300., 1.)
with ArrayStore(Path("existing-cache-directory") / "fields.sqlite", limits,
                Compression(codec="zstd", level=3, shuffle="byte")) as store:
    temperature = cached_temperature(np.linspace(0, 10, 4096), 1., profile,
        store=store, backend="scipy", budget=WorkBudget(32*1024**2))
```

The same call with `store=None` computes without persistent I/O. Imports use the
`tectonics/src` layout; use a declared environment or a separately prepared editable
installation. Core calculations require NumPy. SciPy (`fast` extra) and Blosc2
(`storage` extra) are optional, explicit dependencies; no package auto-installs.
Blosc2's level 0-9 scale is not the direct Zstd level scale.

### Memory/storage limits

Storage chunks are flat C-order pieces of a typed array, not physical boundaries.
Non-native byte order is losslessly normalised to little endian. Shapes, signed
zeros and categorical values are retained; masked/object/nonfinite arrays are
refused. A mask can be a separately identified boolean dataset only when its
scientific consumer actually supports that policy.

`max_array_bytes` limits individual writes and complete snapshot materialisation;
use `read_chunk()`/`iter_chunks()` for partial reads. `max_store_bytes` bounds
retained database pages/records; provision **up to another database-sized rollback
journal**, plus backups. SQLite cache and codec workspace are separate costs.
Input arrays must not be mutated during a store write. Returned data can outlive
an LRU entry, so caller-held arrays must still be counted in the application's RAM.

This is result persistence, not a demonstrated restart of an evolving world. No
Zstd dictionaries, global voxel engine, automatic GC, lossy history, GPU solver,
distributed mechanics or old R5 conversion is introduced.

## Verification and evidence

```sh
# Existing NumPy environment: original 53 mathematical cases
python -I -B tectonics/verify.py --core
# Full increment, with the explicitly prepared fast/storage extras
python -I -B tectonics/verify.py
```

The verifier refuses local `.pyc` files: `-B` alone prevents writes, not reads.
It writes test details to stderr and a fresh versioned record to stdout. Missing
optional dependencies block full verification rather than silently skipping it.

The 17 September delivery passed **93 tests (53 existing + 40 new), no failures,
errors or skips**, on Linux/CPython 3.13.5/NumPy 2.3.5, with SciPy 1.17.0,
Blosc2 4.3.3 and its Zstd 1.5.7. See
[evidence](evidence/memory-storage-tests.json). Tests include independent numerical
references, masked/range regressions, allocation refusal, immutable restore,
fresh-process cache reuse, changed-input identities, Zstd/palette round trips,
concurrent writers, corruption/oversized decoding, rollback, and isolated backup.

[Bounded measurements](evidence/memory-storage-measurements.json) compare synthetic
65,536-element kernels and a 1,179,648-byte three-field storage sample. They are not
world-scale forecasts or physical validation. Transport reduced tracked peak
allocations by about 22%, without a demonstrated timing improvement. The opt-in
cooling backend was faster in warmed comparisons; its results were not bit-identical.
Compression/deduplication gains depend on the field and must not be extrapolated.

Windows/macOS, Python 3.12, other dependency builds, power-loss behaviour on other
filesystems, large-world memory and geological realism were not verified here.
The [first delivery record](evidence/DELIVERY.md) remains historical and unchanged.

## Next development gate

Continue the physical foundation: open boundaries, conservative material
creation/recycling and a physically defined load connection before a coupled
extension claim. Apply memory, ownership, cache and batching checks in each coding
increment, not a separate after-the-fact module audit. Keep the two consolidated
planning documents as the maintained references; do not create further roadmaps.
