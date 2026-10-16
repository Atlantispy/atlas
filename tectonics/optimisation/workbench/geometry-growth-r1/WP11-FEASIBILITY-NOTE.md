# WP11 feasibility: cross-query certified-fact cache

16 Oct 2026, 14:50. This note only scopes the cache. Nothing is built or wired, and no runtime file was edited.
Paths are relative to G (geometry-growth-r1) unless written in full.
- RC1 = `composed-r1/runtime-src/atlas_tectonics`.
- W6 = `T/gg/workers6-r6/atlas_tectonics` (the current test composition).
- DG = `integration_differential_geometry.py` in either one.

Every saving below is PROJECTED and is an upper bound. None of it was measured.

## Answer in brief

- **Repeats across queries are high, but the time they cost is small.**
  - A component's literal family (ordered literals plus their constraints) recurs across the voxels of a chart. It never recurs inside one support.
  - IV2: 90.5% of 27,004 endpoint queries share their cone key with an earlier query (2,564 distinct keys). 91.5% share their pair-prefix key (2,306 distinct).
  - IV1: 91.2% share the cone key (635 distinct of 7,181) and 93.0% the pair-prefix key (503 distinct).
  - If each of 6 workers keeps its own cache, the proxy gives 51.5–56.6% for IV2 and 57.4–64.5% for IV1.
- **Projected saving: at most about 66 CPU-s serial in the IV2 endpoint pass.**
  - That is 15% of a 433.7 CPU-s pass.
  - With per-worker caches it falls to about 38–41 CPU-s, roughly 6–7 s of wall time with 6 workers.
  - The interface path saves nothing: these predicates are never called there.
- **Memory: each fact is charged about 8.9 KB of fixed overhead plus its contents.** About 3,900–6,800 facts fit in 64 MiB. The IV2 serial working set is about 4.9–5.3k facts.
- **Recommendation: do not build it now.** The reasons are in section 5.

## 1. Candidate predicates and their exact inputs

Each query is (support, logical component, endpoint).
- The endpoint time is t = 0 at the start and the support's `duration_s` at the end (RC1 DG:4893).
- One arena per query owns a `_ComponentRayCache` (RC1 DG:4981; W6 DG:5509).
- The predicate order at each leaf is in `_component_volume_leaf` (RC1 DG:4395-4449; W6 DG:4773-4827).

| # | Predicate (RC1 / W6) | Call site | Exact inputs | Cell-independent? | Per-query reuse today |
|---|---|---|---|---|---|
| A | `_common_ray_cone_zero_volume` (RC1 DG:4011 / W6 DG:4389) | leaf, `cell=None` (RC1 DG:4432; W6 DG:4810) | ordered `[name, sign]` literals; `constraints[name]` for those names (RC1 DG:4037); a = b = t; level | **Yes** | Declines only, as a 64-bit level mask (RC1 DG:4429-4436). Successes are recomputed at every leaf. |
| A' | same function with `cell=cell` | root only, after clipping (RC1 DG:4513-4515) | as A, plus the cell | No | none |
| B | `_corotating_plane_pair_zero_volume` (RC1 DG:3847-3910 / W6 DG:4225) | every leaf (RC1 DG:4411) | literals; constraints. **No time, no level.** The cell is used only in `_voxel_projection_maximum(cell, inward)` (RC1 DG:3900). | **Prefix: yes** | Impossibility bit 1 (RC1 DG:3863-3871, 3906-3909). A "possible" family recomputes the whole prefix at every leaf. |
| C | `_coaxial_edge_pair_zero_volume` (RC1 DG:3913-3991 / W6 DG:4291) | every leaf (RC1 DG:4416) | Impossibility uses literals and constraints only (RC1 DG:3934-3965). After that: `_ray_box(…, a, b, level)` (RC1 DG:3968) and the cell (RC1 DG:3980). | **Impossibility part: yes** | Bit 2 (RC1 DG:3929-3930, 3987-3990) |
| D | `integration_cone_zero.certificate` (:154) | root only (RC1 DG:4406-4408) | cell vertices and axes, literals, constraints, t | No | none |
| E | `integration_cone_zero.plane_certificate` (:94-151) | root only (RC1 DG:4444-4446) | Per literal: (cell vertices, constraint, sign, t). The certificate names the literal (:142-143). | No | none |
| F | `_clipped_voxel_edge_zero_volume` (RC1 DG:4225) | root only (RC1 DG:4518) | cell, literals, constraints, t, level | No | none |

**Pose layer (listed for context; it is not WP11's fact cache).**
- `_constraint_pose(constraint, t, t, level)` (RC1 DG:1684; W6 DG:1846).
  - A snapshot-rotated literal poses its nested constraint at its own `snapshot_offset_s`. That nested pose does not depend on the endpoint.
- `_ray_box(ray, ω, a, b, level, prior)` (RC1 DG:509-519) is keyed per query (RC1 DG:486-489).
- W6 adds the WP23 rotation memo (W6 DG:1171-1205, limit 4096 at W6 DG:1051). It lives on the per-query arena and replays the original work charges on a hit (W6 DG:1188-1192).

**Interface and wall routes (W6; checked for per-query memoised proofs).**
- `integration_interface_exclusion.py` has no memo. Line 336 says "no persistent decoded-path cache is added" (`zero_area` is at :317).
- `integration_rigid_intersection.py` has no memo (`intersect_world_line` :144, `intersect_world_line_reduced` :163).
- The per-call memos on the interface path depend on the face or cell:
  - In `integration_moving_interface_moments.py`, the locals at :731-732 include `factor_cache` (key `(name, edge, section)`, filled by `_common_plane_factor` at :982-986). A `'voxel'` section passes the fixed voxel face. `corner_cache` (:1150) is keyed by the face corner.
  - In `integration_moving_face_moments.py`, `_fixed_corner_predicate` (:291) keeps one cache per face.
- Cost shares:
  - `_common_plane_factor` 0.1% (0.43 s of 742 s in `wp22-profile/cand-deep-s0.prof`).
  - `zero_area` and `intersect_world_line` 0.1% each.
  - Predicates A–F have **0 calls** in every interface profile.
- The interface path has no cross-query candidate worth caching.

## 2. Why reuse would be exact, and what a hit must replay

**Result and certificate are pure functions of the key.**
- A, B, C, E and F read only `constraints[name]` for the literal names (RC1 DG:3868, 3876, 3934, 4037; cone_zero:115).
- Beyond those they read a, b, level, and the cell where the table lists it.
- The iteration order is fixed by the inputs: literal order, list order inside each constraint, and sorted integer sets inside A.
- So byte-identical inputs give the same result and the same certificate.
- In the census, named and name-free keys gave identical counts. Names therefore never alias different content, but they must stay in the key because the certificates carry them (`literals`, `triangle_literals`, RC1 DG:3902-3905, 4131-4167).

**Mathematical declines differ from budget, cancel and time declines.**
- `None` is returned only after a completed evaluation, so it is a deterministic mathematical decline at that precision.
- Budget exhaustion raises an exception. It never returns `None`:
  - `_Arena.work` reserves predicate work, or bytes, before it counts (RC1 `integration_volume_bounds.py`:61-73).
  - Operand admission (`V._work`) also raises.
- Cancel and time caps are also exceptions (the replay's `QueryCap`).
- The existing per-query writes are reached only on a normal return ("exceptions never reach this write", RC1 DG:3908, 3989).
- **A hook must store only normal returns (`None` or a certificate) and nothing on an exception.**

**Precision schedule and the `prior` field.**
- `level` sets the pose target, norm/2^(32+2·level) (RC1 DG:1025; W6 DG:1143). It reaches A and the post-impossibility part of C through `_ray_box`, so it belongs in their keys.
- B's prefix and C's impossibility part use no level and no time.
- `prior` in the ray-cache key is the ray's rotation history, not earlier query state. That history is `prior_rotations` plus snapshot offsets, via `_constraint_edge_ray_paths` (RC1 DG:3994-4008). It comes from the constraint bytes, so it is an operand.

**Prior state changes the record bytes, not the result. A hit must replay all of it.**
1. **Work charges.** The record carries `work_units=arena.work_units` (RC1 DG:5080; W6 DG:5621).
   - The predicates charge work: 128 per equal-rotation pair in B (RC1 DG:3886-3887), 64+32·n in C (:3955), and 128+64·paths plus later steps in A (:4050-4210).
   - A hit must replay these charges in their original order, as WP23 already does (W6 DG:1188-1192).
2. **Per-query ray-cache contents.** A and C call `_ray_box` (RC1 DG:4083, 3968), which stores poses in the query's `_ComponentRayCache` (`retain`, RC1 DG:492-506; at most 256 entries / 2 MiB, each with its own reservation).
   - A ray-cache hit skips `W._pose_vector` and its charges. So whether the cone ran decides whether later `_ray_box`/`_constraint_pose` calls in the same query hit, and that changes `work_units`.
   - A cone or coaxial fact must therefore also carry, and re-`retain` in order, the ray boxes it produced.
   - In W6, the WP23 memo fills the same way. Its hits are charge-neutral, but its `arena.keep` reservations differ.
3. **Per-query bits.** On a hit, `declined_cone_levels` and `impossible_pair_families` must be set exactly as on a miss, because they gate later calls.
4. **Transient admission.** A miss admits operand bytes through `V._work`; a hit does not. Under a tight budget, a miss could refuse where the hit succeeds.
   - WP23 accepted a replay of charges only.
   - WP11 must either state the same or re-admit the peak bytes.

**What goes into the key (`fact_key`, `composed-r2/helpers/certified_fact_cache.py`:14-36).**
- Operands:
  - the ordered `[name, sign]` literal bytes;
  - each literal's constraint as its exact stored bytes, in literal order;
  - a and b as exact rational bytes;
  - `level`, for A, and for C after the impossibility test;
  - the cell only for D–F. These are not recommended, because they have 0 repeats.
- Parameters: the predicate variant, for example `cell=None`.
- Method identity: a digest of the predicate's source and its callees (`_rigid_plane_path`, `_ray_box`, `_pose_vector`, `_rotation_boxes`), plus the replay-record format.
- Execution identity:
  - the runtime package digest (interval files carry `rc1_package_digest`);
  - the Python and gmpy2 versions (the mpq path in WP23);
  - `PYTHONHASHSEED=0` (HANDOFF.md:37).
- Certificate and verifier schemas.
- `process_epoch` (per process, so per worker).

## 3. Memory per fact

The charge comes from `composed-r2/helpers/content_cache.py`.
- **Value allocation:** backing bytes + `OWNER_BYTES` 4096 (:24, :72-73).
- **Carrier:** 4096 + 512 + 4·len(epoch) + 32 (:773-775).
- **Fixed overhead:** 8,864–8,992 B for a 32–64-character epoch, plus one `CACHE_CONTROL_BYTES` charge of 2048 (:25).
- **Key:** a 32-byte SHA-256, covered by the index charge.
- **Every hit also calls the verifier** (:752).

Backing is `CertifiedFact(result: bool, certificate: bytes)` (`certified_fact_cache.py`:39-49) plus the replay data from section 2:

| Fact | Backing estimate | Charged total |
|---|---|---|
| B prefix: ordered pair outcomes (inward, α, β) + charges | ~0.3–1 KB | ~9.2–9.9 KB |
| A decline: empty certificate + charges + replayed ray boxes (the runtime books ≥1024+128·values per box, RC1 DG:500-501) | ~1–8 KB | ~10–17 KB |
| A success: certificate (RC1 DG:4131-4167) + replay | ~2–10 KB | ~11–19 KB |

`FACT_CACHE_BYTES` is 64 MiB (`composed-r2/helpers/compact_contracts.py`:30).
- That holds 7,557 facts with zero backing, about 6,800 at 1 KB and about 3,900 at 8 KB.
- **IV2 serial working set:** 2,306 B facts + 2,564 to about 2,991 A (key, level) facts ≈ 4.9–5.3k facts, or about 47–90 MiB charged. That is at or over the cap.
- Packing the facts into one owned allocation per literal family would remove most of the 8.9 KB fixed overhead per fact.

## 4. Key census and projected saving

**How the census was run.**
- Script: `scripts/wp11_key_census.py` (sha256 b9201009…e4534).
  - Pure JSON processing: no runtime import and no geometry.
  - Queries are enumerated as in `scripts/replay_queries.py`:172-176.
  - Keys are SHA-256 over canonical JSON, with rationals reduced to lowest terms.
- Run once with `PYTHONHASHSEED=0` through `runq.py small --cores 1`, 14:42:23–14:43:08. Peak 0.07 GiB.
- Output: `evidence/wp11-census-r1/census.json`.

**What the counts measure.**
- Exact per-call keys add the level, and some cell-free predicates are called once per leaf. Getting those counts would mean running the leaf queue.
- So the census counts **queries** that share a key (literals + constraints + endpoint time). That is an upper bound on cross-query hits: a later query can hit only at levels an earlier query already visited.
- Replay rows from `evidence/final-f2/cand-iv2-endpoints-s*.jsonl` supply `cpu_s`, `leaves` and `max_level`. They joined 27,004 of 27,004 rows, all `met`.

**IV1 replay rows did not join.** The final-f2 IV1 replay was built from `evidence/final-f2/iv1-supports.jsonl.gz`, not from `work/iv1-supports.jsonl.gz`: 7,075 of 7,181 support ids differ. IV1 CPU weights are therefore not used. Its counts come from the requested input.

| Candidate key | IV2 total / distinct (repeats) | IV2, 6 private caches (proxy) | IV1 total / distinct (repeats) | Repeats inside one support |
|---|---|---|---|---|
| A cone (literals + constraints + t) | 27,004 / 2,564 (90.5%) | 13,912 (51.5%) | 7,181 / 635 (91.2%); proxy 4,125 | 0 / 0 |
| B prefix and C impossibility (literals + constraints) | 27,004 / 2,306 (91.5%) | 15,297 (56.6%) | 7,181 / 503 (93.0%); proxy 4,629 | 258 / 72 |
| D/E/F root cell (voxel + literals + constraints + t) | 27,004 / 27,004 (0%) | 0 | 7,181 / 7,181 (0%) | 0 |
| E per-literal sub-test (voxel, name, sign, constraint, t) | 237,002 / 33,002 (86.1%) | 165,269 | 52,748 / 17,326 (67.2%) | 60,362 / 16,530 |
| Pose: constraint + t (level-free) | 237,002 / 2,228 (99.1%) | 224,213 | 52,748 / 1,412 (97.3%) | 4,284 / 1,077 |
| Pose: snapshot nested (nested + offset) | 167,927 / 966 (99.4%) | 162,454 | 29,314 / 510 (98.3%) | 4,817 / 838 |
| Pose: ray (direction, ω, history, t) | 348,580 / 397 (99.9%) | 346,248 | 61,254 / 240 (99.6%) | 3,359 / 629 |

- **Group sizes.** IV2 A groups: at most 50 queries; 1,272 groups have 9–16 and 299 have 17–64.
- **Where the CPU sits.** Repeat queries used 380.8 (A) and 388.8 (B) of the 433.7 CPU-s in the IV2 pass.
- **Leaf counts.** The pass has 30,573 leaves for 27,004 queries, so almost every query is a single root leaf. Within-query reuse can remove at most 3,569 leaf calls in total.

**Projection.** The only endpoint profile is `evidence/profile-iv2-rc1-858-r1.prof`: RC1, one deep query (support 858, end endpoint, 11 literals, 1,391 leaves, 60.3 s).

| Predicate | Cumulative time in profile | Share | Calls | Mean per call |
|---|---|---|---|---|
| B | 9.63 s | 16.0% | 1,390 | 6.93 ms |
| A | 0.669 s | 1.1% | 32 | 20.9 ms |
| C | 0.002 s | 0.003% | 1,390 | — |
| D | 0.108 s | 0.18% | 1 | — |
| E | 0.008 s | — | 1 | — |
| F | 0.022 s | — | 1 | — |

1. **Repeated calls × mean cost per call** (the requested form). Removable calls are at most leaves minus distinct keys.
   - B: 28,267 calls × 6.93 ms = 196 s.
   - A: 28,009 calls × 20.9 ms = 585 s.
   - The sum, 781 s, exceeds the 388.8 CPU-s that all repeat queries used in total. The deep query's per-call costs do not carry over to typical ~16 ms candidate queries.
   - The only strict ceiling is 388.8 CPU-s. It assumes the predicates are the whole of every repeat query, which they are not: poses, clipping and the root proofs remain.
2. **Shares × CPU of the repeat queries** (assumes 858's shares hold for every query).
   - IV2 serial: (16.0 + 1.1 + 0.003)% × 388.8 = **≤ 66.5 CPU-s**, which is 15.3% of the IV2 endpoint pass.
   - Per-worker caches (proxy kept 56.6–62% of the repeats): ≈ 38–41 CPU-s, or ≈ 6–7 s of wall time at 6 workers.
   - IV1: final-f2 replay is 97.2 CPU-s on a different support build, so ≈ 0.171 × 0.93 × 97.2 ≈ 15 CPU-s serial.
3. **Interface path: 0.** Predicates A–F are never called there. That path dominates geometry: deep IV2 interfaces took 2,134 s in final-f1.

**SLOT: q14 profile `evidence/wp23r-prof-r1`.**
- At 14:48 it was still running: 5 of 49 interfaces done, 249.4 s profiled.
- A–F had **0 calls**. `_rotation_boxes` was 9.1%, `_constraint_pose` 4.4%, `_pose_vector` 3.9% and `_ray_box` 2.2%.
- Final merged figures, to fill in when q14 finishes:

| Item | Final value |
|---|---|
| Share of A | ____ |
| Share of B | ____ |
| Share of C | ____ |
| Share of D | ____ |
| Share of E | ____ |
| `_rotation_boxes` | ____ |
| `_constraint_pose` | ____ |

- q14 profiles interfaces only, so it cannot give the endpoint share that projection 2 assumes.
- The payoff gate needs a profile of the endpoint pass: `replay_queries.py --profile` over the IV2 endpoint set, or a stratified sample of it, in the small lane.

## 5. Where it should live, who owns it, and the recommendation

**Where and who (if it is ever built).**
- Storage owns `content_cache.py`, `certified_fact_cache.py` and the `facts` quota: 64 MiB inside the single 256 MiB retained scope (`compact_contracts.py`:28-30).
- The geometry owner writes `certified_fact_patch` at the existing per-query reuse site: the leaf block at RC1 DG:4410-4436 / W6 DG:4789-4814, as plan line 692 says.
- There is one cache per worker process, because `process_epoch` is in the key. The hit-rate proxy above already reflects that.
- Build order:
  1. B's prefix first. It is free of time, level and cell, needs one key per literal family, and is the simplest to replay (ordered pair outcomes plus 128 work units per pair).
  2. A's declines second. They need the ray-box re-retain.
  3. Never D–F: they have 0 repeats.

**Recommendation: do not build WP11's fact cache now.**
- **Payoff.** The keys repeat often enough to pass the §7 hit-rate test, but the bounded payoff is small and unmeasured.
  - ≤ 66.5 CPU-s serial, or about 40 CPU-s with per-worker caches, out of a 433.7 CPU-s endpoint pass.
  - 0 on the interface path, which dominates.
  - The per-call cost basis is one RC1 deep query whose per-call figures demonstrably do not transfer.
  - §7 also states that a high hit rate never overrides slower elapsed time or excess memory.
- **Exactness makes the hook invasive.** Keeping records bit-identical means replaying work charges, the per-query bits and the per-query ray-cache retains at the leaf. Each fact then holds more than its result.
- **Memory.** About 8.9 KB of fixed charge per entry puts the IV2 working set at or over 64 MiB unless the facts are packed.
- **Better target: the pose layer** (§11 posed-support/rotation transforms, plan lines 1288-1296).
  - 397 distinct ray poses serve 348,580 query-level uses in IV2.
  - That layer is 23–38% of the deep endpoint query and 9–11% of interface profiles even after WP23.
  - A process-level extension of WP23's per-arena memo, with the same charge replay, would apply to both paths.
- **When to revisit WP11.** Run an endpoint-pass profile. Revisit only if B + A come to ≥5% of measured endpoint time; then build B's prefix alone first.
