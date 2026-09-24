# New-world initialisation: step 1 contract

WORKING NON-CANON. This increment configures a reproducible candidate; it does not
generate geometry, evolve physics or certify a realistic planet. Existing native
sources, jobs and saved outputs are unchanged. Implementation lives outside the
source-bound scientific package in `tools/new_world_contract.py`.

## Request and reference settings

`atlas.new-world-request.v1` has exactly these keys:

```json
{
  "schema": "atlas.new-world-request.v1",
  "seed": "00000000000000000000000000000029",
  "recipe": "atlas-initial-contract-v1",
  "mode": "statistical-kinematic",
  "epoch": {"id": "initial-epoch", "time_s": 0.0},
  "frame": {"id": "world-frame", "coordinate_system": "planet-centred-cartesian", "length_unit": "m", "vertical_reference": "radial-depth-below-reference-sphere"},
  "settings": {
    "radius_m": {"mode": "fixed", "value": 6371000.0},
    "gravity_m_s2": {"mode": "fixed", "value": 9.81},
    "plate_count": {"mode": "auto", "minimum": 8, "maximum": 20},
    "continental_fraction": {"mode": "auto", "minimum": 0.25, "maximum": 0.45}
  },
  "resolution": {"support_cells": 1024},
  "resources": {"max_work_bytes": 134217728, "max_wall_seconds": 120.0}
}
```

Seeds are **32 lowercase hexadecimal characters**, never a JSON number. This
preserves all 128 bits in JavaScript. New random world obtains fresh OS randomness;
reproduce/load/resume preserves the stored seed. There is no random fallback when
validation or loading fails. Fixed values stay fixed. Auto draws from the user's
explicit closed integer or half-open continuous interval; equal endpoints give
that endpoint. Numeric physical settings use binary64; booleans are not numbers.

The small reference recipe is an **uncalibrated engineering configuration** for
testing parameter wiring, not a distribution of plausible planets. Its Auto
bounds must not be advertised as empirical science. Structural setting envelopes:
radius 100,000..100,000,000 m; gravity 0.01..100 m/s²; plate count 2..52;
continental-lithosphere fraction 0..1. These are representation/input limits, not
physical acceptance. Unsupported scenario/mode/unit/frame contracts refuse. Later
producers must declare and enforce their narrower physical admission criteria.
Continental fraction is not exposed-land fraction or a water/sea-level model.

Support cells are an integer 8..65,536 and at least four times the largest
requested plate count, including the Auto upper bound. This is generating support,
not screen pixels or a solver mesh. Work budget: integer 1 MiB..8 GiB; duration:
finite 1..86,400 s. These are requested limits, not enforcement or a runtime
estimate at this configuration-only stage. No automatic quality reduction.
Epoch is named and finite, with seconds in [-1e18,1e18]; it is not planet age.

## Python API and identities

Pure standard-library API:

- `new_request(seed=None, *, settings=None, epoch=None, frame=None,
  support_cells=1024, resources=None)` creates and validates a detached request.
  Omitted seed uses `secrets.token_hex(16)`; omitted settings use the reference
  recipe. Supplied settings replace that complete mapping, not merge silently.
- `validate_request(record)` returns a detached, canonicalised request or raises
  `ContractError(code, message)`.
- `resolve_request(record)` returns `atlas.new-world-plan.v1`: `status` is
  `CONFIGURED_NOT_GENERATED`; includes request/request_id, scientific_id,
  resolved_settings, setting_origins, named streams, output_contract,
  capabilities, binding and plan_id. No arrays, result or simulation is produced.
- `validate_plan(record)` checks exact keys, IDs, current binding and recomputes
  all sampled settings/streams; returns the canonical plan. Changed source/runtime
  bindings fail rather than repinning a saved plan. This is accidental-corruption
  and reproducibility checking, not authentication against a hostile editor.
- `stream_seed(seed, name)` gives 32 lowercase hex characters from a versioned
  SHA-256 domain-separated stream; names are lowercase ASCII [a-z0-9_.-], 1..64.
- `output_contract()` returns the immutable-by-copy future output requirements;
  `validate_world_descriptor(record, plan)` validates references/context/units
  structurally, not stored bytes, conservation, realism or restart readiness.
- `contract_description()` returns schemas, reference request with seed zero,
  setting domains, seed rule, output requirements and current capabilities.

Named streams are `plate_layout`, `plate_sizes`, `continental_structure`,
`crustal_structure`, `thermal_structure`, `plate_motion`, and one `setting.NAME`
stream per setting. Drawing one parameter cannot advance another's stream.
This is random-number independence, **not physical independence**. Changed crust,
thermal structure or inherited weakness invalidates every dependent plate/network
or motion calculation. A stable stream may provide repeatable candidate draws,
but never permission to reuse an incompatible physical result. Joint generation
must recompute or reject the coupled candidate when its physical inputs change.
Integer sampling uses rejection to avoid modulo bias. Continuous sampling uses
the top 53 bits of a SHA-256 draw; both mappings are versioned. These streams are
allocated for future producers, not claims that those producers are connected.

`request_id` hashes the complete normalised request. `scientific_id` binds its
seed, recipe, mode, epoch, frame, settings, resolved values, physical support and
random algorithm, but excludes execution resource limits. `plan_id` additionally
binds the complete plan and implementation/runtime. None is a complete future
simulation-cache key: a producer must also bind its own laws, source/runtime,
inputs, forcing and dependencies. No persistent result cache is introduced here.

## Initial-world output boundary

Future `atlas.initial-world-descriptor.v1` fields: schema, status
`WORKING NON-CANON`, plan_id, scientific_id, epoch, frame, origins, products.
Products must name exactly topology, material, thermal, motion and boundaries.
Each is a structural reference `{product_id, support_id, unit, frame_id, epoch_id,
known_mask_id, origin}`. IDs are full SHA-256 hex. Units respectively are `1`,
`kg`, `K`, `rad/s`, `1`; material means an extensive mass inventory, not an
unlabelled concentration. Actual field inventories/metadata remain inside the
referenced typed products. Origin is `generated-assumption` in this initial mode;
no claimed observed or dynamically simulated history. Shared support is required
until an explicit transfer contract exists. Origins records the request recipe
and `statistical-kinematic` mode. No fabricated zero arrays fill missing products.

Descriptor validation verifies declarations only. Real product bytes, native
closure and physical acceptance must be checked by the later producer/consumer.
Current capabilities: configure true; generate_world, evolve_world and
native_restart all false. UI must not enable those actions or send this request
to the synthetic W12 column job.

## CLI and UI ownership

`tools/new_world.py describe` prints the contract; `seed` returns a new seed;
`prepare` reads one bounded request from stdin and prints a resolved plan.
`save --file PATH` takes a plan on stdin and creates a new immutable JSON file;
`load --file PATH` strictly validates it without changes. JSON inputs reject
duplicate keys, non-finite values, excess size and unknown keys. Failures have
`schema: atlas.new-world-response.v1`, status error, path-free code/message,
exit 2. Success has the same envelope, status ok and data. Save never overwrites.
Raw Python API returns the records above, without the CLI envelope.

The UI owner owns New-world draft controls, Fixed/Auto settings, randomise and
reproduce semantics, project persistence/migration, bounded prepare bridge and
browser checks. Persist the seed before any future generation. Editing parameters
invalidates an old prepared plan without changing an existing generated world.
Keep these drafts separate from illustrative maps and existing managed jobs.

## Method basis and verification scope

This is a software contract, not a new geological model. Method references:
Python `secrets` for OS entropy and `hashlib` for deterministic domain-separated
digests; existing Atlas SHA-256/canonical JSON and typed-reference conventions.
GPlates' explicit initial geometry/scalar/rotation inputs informed the separation
of configuration from evolution. No new external runtime dependency is needed.
Checked official sources: [Python 3.13 secrets](https://docs.python.org/3.13/library/secrets.html),
[Python 3.13 hashlib](https://docs.python.org/3.13/library/hashlib.html), and
[pyGPlates TopologicalModel](https://www.gplates.org/docs/pygplates/generated/pygplates.topologicalmodel).
No new geology paper or physical law is needed for this software-only increment;
the physical initialisation research remains in the existing proposed plan.
Tests cover fixed/Auto resolution, stream independence, identities, strict
round trips, malformed data, units/frames/epoch/support and persistence refusal.
Multi-seed differences here demonstrate configuration variation only; physical
planet diversity remains an acceptance requirement for subsequent increments.
