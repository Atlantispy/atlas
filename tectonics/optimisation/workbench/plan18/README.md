# Plan18: geometry endpoint lookahead and compact header retention

This record describes the accepted Plan18 source
changes selected for the optimisation review branch. Their private receiving
integration was accepted on 23 October 2026. The [public source map](SOURCE-MAP.json)
adds those changes to the preceding public selection while preserving historical
mappings. It records new publication identities; the original private receipts
and receiving-integration evidence remain bound to their original sources.

The reader chapter explains
[endpoint lookahead](../../../docs/how-it-works/06-physical-integration.md#look-ahead-across-supports-to-keep-endpoint-workers-busy)
and [header retention](../../../docs/how-it-works/06-physical-integration.md#retain-only-plain-support-headers-on-the-compact-route).

## What changes

The public selection extends the [Plans19–20 selection](../../README.md#plans19-20-source-selection):
631 members are retained, six are replaced and four are added, giving 239 native
files and 402 helpers. The two later Plan19 geometry implementations remain selected.
The independently published heat and pressure receiving generations remain available;
this source selection does not perform the programme's final combined-runtime assembly.

To create a new source layout from the repository root:

```text
python -B tectonics/optimisation/workbench/plan18/build_selection.py --repo . --output ../atlas-endpoint-source
```

Use the resulting `helpers` and `src` import roots together in a fresh process.
The existing ALE endpoint loop and compact support paths then import the selected
automatic endpoint controller, routing helper and carrier accounting. The builder
checks every selected file and refuses an existing output; it starts no simulation,
worker or checkpoint migration. Full drivers still require their separate controlled
inputs and runtime admission. Historical receipts do not authenticate this new layout.

**Endpoint lookahead** (`atlas_tectonics/integration_component_volume_auto.py`):
- The earlier endpoint clamp of 32 jobs and 64 requests is replaced by the
  scheduler's reviewed general `batch_jobs` and `horizon`. Their defaults are
  512 jobs and 4,096 requests; both are configurable policy, not physical limits.
- The inherited cache bound follows `2*horizon + 64` (8,256 entries at the
  default).
- One or two endpoint workers compute ahead across later supports; the measured
  case used two.
- The parent projects every routing row and adopts results in serial router order.
- An ahead-read support is bound to its index and identifier. A mismatch stops
  the lookahead and leaves serial continuation.
- `project_compact` is never called ahead of its router position.
- Engagement needs the projected remaining endpoint time to pass a gate (120 s by
  default). A machine refusal defers rather than stopping.

**Plain header retention** (`partition_routing_patch.py`):
- `retain_support` keeps deep-copied header values, charged at their measured
  size to the run budget, and releases the record-field exports.
- Before this change, the exports were booked at about 0.2 MiB per handle against
  the fixed 256 MiB retained budget, and interval 1 was refused after about 1,168
  of 2,016 supports.

**Carrier booking** (`content_cache.py`):
- A retained share's ownership carrier books 2,112 B instead of the 4,096 B owner
  floor: 1.25 times the tracemalloc-measured worst of 1,674.8 B, rounded up to
  64 B.
- Only that carrier-only charge changes. Every other charge and the 256 MiB cap
  are unchanged.
- After release, about 142 B per peak carrier of holder-set and charge-table
  capacity stays allocated, unbooked, until the owning allocation's or scope's
  storage is released. The booking margin covers it only while enough peak
  carriers remain live: about a quarter at the mean measured size, about a third
  at the worst. This is not enforced.

**Retained-handle diagnostic** (`retained_header_problems`, in
`partition_routing_patch.py`):
- It walks a handle's ownership graph and compares its header with a fresh read
  of the support record.
- It checks the exact carrier set, that no record export or extra run-budget
  allocation is reachable, exact header keys on both sides, canonical JSON bytes,
  and live, fully charged allocations.
- It first confirms that the record reference is usable the way
  `partition_native_patch._view_fields` uses it, so closed or incomplete
  references are reported as unavailable. Errors raised inside the read
  propagate.
- It cannot prove that nothing else is retained.

**Tests:**
- Four selftests are added: header retention, carrier booking, the diagnostic,
  and the order-independence of the spatial-owner allocation.
- `test_content_cache` expects the carrier booking for a retained child share.
- `test_r1a_export_booking` and `test_r1_views` default their temporary files to
  a per-process folder under the system temp, and refuse one inside the
  composition. On Windows, keep the system temp path short: native store paths
  under it can exceed the 260-character path limit.

## Endpoint ordering, lifetime and parity contract

Part 1 selects general 512-job/4096-request bounds plus cross-support lookahead at
two endpoint workers. More workers are deferred; the separate EndpointBatchPass
prototype is unchanged. Hardest-first was abandoned because available labels did
not predict cost; no ahead-of-router project_compact or ALE/Step8 algorithm change
is selected.

The scheduler retains _weigh/_fits and MAX_BATCH_INPUT. Future supports contribute
only logical cell ID, parent presence, constraint count and partition-path length.
Noncompact lookahead uses the prepaid decode envelope; compact lookahead retains
a real charged handle/support_fields and drops its temporary native support.

- Read ahead while a session exists OR the current first-batch plan still asks
  for offers (offered<_wanted). Session-open-only would deadlock first-batch formation.
- Without a session, stop renewed read-ahead when the horizon is sated; below-
  threshold/estimate-free work cannot eagerly scan the pass twice.
- Remaining-work estimates combine current jobs and unread supports times observed
  jobs/support; this is scheduling estimation, not changed geometry.
- Bind support index and identifier; mismatch stops scheduling and leaves serial
  continuation without adopting the wrong result.
- Keep actual compact handles, prune passed memo entries, drop current/held
  references on stop and close already-offered work before partition close.
- Preserve request/adoption/checkpoint order, reservations, cancellation/failure
  and bounded handle peaks. Session revocation on reservation shortage and one
  failed job declining the remainder of a 512-job batch remain efficiency limits.

The authentic detached proof has five arms:

| Order/arm | Route | Required engagement |
| --- | --- | --- |
| 1 IV2 serial | Serial reference | None |
| 2 IV2 w2 | Auto2, default 120-second minimum | started>0, adopted>0, refused=0 |
| 3 IV1 serial | Serial reference | None |
| 4 IV1 w2 | Auto2, default 120-second minimum | Equality only; legitimate serial allowed |
| 5 IV1 w2-min30 | Auto2,30-second minimum | started>0, adopted>0, refused=0 |

The retained harness supports full sets or shard 0/N in every arm; its smoke used
shard 0/10. Header max_volume_error_m3/max_leaves and support-ID/index agreement
remain binding. Existing exact stream widths are retained, not new tolerances:

| Input | Numerator | Denominator |
| --- | --- | --- |
| IV1 | 0x2f00cbfcd7c08aad8918ab19af | 0x4e3bbe22f900000000000000000000000000000000000 |
| IV2 | 0xef6aca6e197d9db2f69d62da0b | 0xc6ae51dc48000000000000000000000000000000000000 |

Each arm needs positive record count, exact serial ordered list/hash of measure
ID/canonical-record digest/met, same nonmissing package binding, no error and
successful child exit. Started work alone does not prove simultaneous children.
The default IV1 arm may remain serial; fallback cannot replace required engagement
in IV2 or min30. A report followed by nonzero child exit must fail the complete
wrapper, even if JSON looks acceptable; missing telemetry cannot become proof.
The old wrapper-exit concern and fake-handle-only/mismatch-borrow gaps are
historical scope limits, not a revived request after the accepted replay and
real-partition/worker closure evidence below.

Freeze source/harness/input identities and use new exclusive outputs. Runtime
imports use cleaned seed 0/B/one-thread settings, not-I; pure helpers may isolate.
Report actual gate/load, parent/child/RSS/session observations as samples, not
continuous upper bounds. No 15% hurdle exists. The old 402→217 s/91→57 s estimates
remain projections, not the measured detached replay or successor interval result.
The IV1 threshold/default decision belongs to its owner, separately from proof.

## Deferred first-session retry (S4)

The three scheduling transforms preserve parent order and adopted results:
s4roll, s4sel and s4auto, with s4auto after wp18. They were excluded from q18's
attributable WP18 proof runtime; their source availability is not default adoption
or a new run request.

On a momentary machine/ledger refusal before the first session, _open may return
LATER before any session, funding or worker count exists. Schedule retries on its
own clock after 15 s, doubling to a 120 s maximum, for at most 24 deferrals; the 25th
refusal stops with session not opened. Missing psutil is permanent and stops
immediately. CPU, memory, budget and predicate hints may improve, but nothing is
reserved; actual session/funding refusal returning None still stops immediately.

Between retries advance returns before planning/offering/launching/holding work.
The existing reached/hungry/horizon rules remain bounded; WP18 no-session
lookahead offers only the last plan's remaining demand, never the full pass.
A late open is an ordinary first session; retries stop mattering once it exists.
Repeated same-gate refusals replace their latest note within the 8-note window.
Ending mid-deferral retains stopped='session not opened' and refusal detail;
late-open/no-launch can retain reason='session deferred' with stopped None.

The bounded claim is at most 25 probes, each about 50 ms plus one plan and at least 15 s
apart: roughly 1.75 s cost per affected pass, not a measured global overhead.
The retry span is about 45 minutes, not a required wait or proof deadline.
The old 125 s lost-opportunity figure is PROJECTED, with zero opportunity when
first open succeeds. Any later authorised affected-pass measurement must record
session-deferred reasons, open time, started batches and serial-relative wall.
It is not owed as a new dispatch merely because this explanation moved.

Retained evidence is six retry controls, fixed lower-priority review findings,
no P0–P2 owner-review defect and no introduced lint finding. Scheduling invariance
does not replace real compact lifetime/partition parity or imply no process-memory
cost. The accepted header/worker evidence below remains separately scoped.

## Original private identities (provenance)

| Private generation | Composition | Run manifest | Profile |
| --- | --- | --- | --- |
| Accepted successor | `350496a3f3ddfadef2f3f8ee3353565f56b5c6339534ef93591ed81908200a7f` | `28cc2cb38599bbd50f8c51475c8144a05a3d36b21d72367c48e5f0e241853dc7` | `215075c2e97fe760ff4ca8146c163d5ac11fc1a614d80c4922896ccebe56821a` |
| Lineage parent (Plan20 r1 composition) | `e14c05a8…` | – | – |

Members that differ from the lineage parent. The native count stays at 239, and
helpers rise from 398 to 402.

| Member | Parent | Accepted successor (SHA256) |
| --- | --- | --- |
| `atlas_tectonics/integration_component_volume_auto.py` | `2b9d9fc5…` | `96cbf772e7e68b361ffb46ef234087511a7b02bfca733e343cb5bde13e87f70b` |
| `helpers/content_cache.py` | `de7d3e45…` | `85fe9a5f421d8c693d44f23ca4c5189f2696d89cb2dcffd16a06c52ce90850f5` |
| `helpers/partition_routing_patch.py` | `c7eebabf…` | `ffb95381a45643be191e49ce00f99afc36d0bf4de773f7686a3d9f01c50328a5` |
| `helpers/test_compact_header_retention.py` | new | `696ca77fa67020564db2695be80dfef3cefcc880680b14dc969e20ca469cfbd4` |
| `helpers/test_content_cache.py` | `e3754c32…` | `50f4f3e1a38d6e7763dd561c2bdf38d471cb5725e88fce43250fb722cd62474f` |
| `helpers/test_owner_carrier_booking.py` | new | `ee424fd9aaf35a6ff85a2db64e204487b98f7ddca2d7bcf1d06720687da390d2` |
| `helpers/test_r1_views.py` | `5eefb4e0…` | `24e464092ba96d82e81f39d3b1f8fa0b51811861110a47080cddc2e350ecef3a` |
| `helpers/test_r1a_export_booking.py` | `937811a9…` | `5160cacbc83f1afcab4bcb8e157d9abe32925f7aadb2877178925faa8d8fcc35` |
| `helpers/test_retained_handle_check.py` | new | `8b3c8ed16fcb805b7a3dcfd10c0c51a925a12ac1b9296576bfcfc61a89131df9` |
| `helpers/test_spatial_allocation_order.py` | new | `e7b9e8fa0a2fc5acba8da15218a39709439d11b3442df9e20696d9ba85a255d6` |

## Evidence and its scope

[Publication checks](CHECKS.json) bind this public selection separately: all 641
materialised files match the map; 50 retention/accounting tests and 99 synthetic
endpoint checks pass. The source builder's 11 controls have ten passes and one
Windows symlink-privilege skip, with an injected reparse-point control passing.
Static publication checks pass with no new lint findings. These checks launch
neither real endpoint workers nor an interval and do not renew private receipts.

| Evidence | Result | Scope |
| --- | --- | --- |
| Five-arm endpoint replay, run once | Records identical in every arm (IV2 27,004; IV1 7,181). Two workers: IV2 451.32 → 274.23 s (39.2% less, 1.65×); IV1 111.00 → 96.35 s (13.2% less); 30 s gate 96.97 s. Whole-run peak 0.64 GiB | Detached endpoint loop on captured supports in a dedicated endpoint runtime. Not the successor composition; no whole interval timed |
| Unit and replay checks of the lookahead | All pass (96 and 99 checks); the refusal test exits 1, as required | Detached runtime and first successor |
| Closure proofs | Fake-handle and real-partition cases 9/9 plus 2 sensitivity controls; probe 16/16; compact reference 16/16 and legacy reference 9/9, with identical records and all 2,016 retained headers clean | Successor that introduced header retention |
| Real-worker closure cases | All seven pass, including both mismatch stops; no outstanding borrows; job peak 0.59 GiB | Same successor |
| Carrier sweep | 24,000 carriers; mean 1,486.0 B, worst 1,674.8 B | Synthetic, tracemalloc |
| Focused tests | 50/50 on the accepted successor; the three real-reader cases fail on the previous successor, as intended | Synthetic |

The accepted successor differs from the closure-proof successor only in carrier
booking, the diagnostic and tests. Records and routing order are unchanged.

## Limits and holds

These carrier limits describe this Plan18 predecessor. The later
[combined selection](../combined-runtime-r1/README.md) adds a paid allowance for
three ownership carriers per support and retains the fixed budget for transient
reads/exports. Its own whole-run and machine guards still apply; the old fixed-cap
forecast below is not a limit of every later source selection.

- **Larger intervals.** The IV4 projection of 87,000 supports books 551.2 MB
  (525.7 MiB) on carriers alone, against the 256 MiB retained cap. The
  carrier-only ceiling is about 42,400 supports. The cap or the retention design
  must change first; the cap is not raised here.
- **The horizon** bounds requests, not every projected support. It is not a
  global support-memory bound.
- **No interval run** and no IV check of the accepted successor has been made. The
  IV1 gate projection of 226.4 s is a projection.
- **Holds.** Existing scientific, individual-run and fresh full-interval holds
  remain. No default or main-package adoption follows from publication.

## Corrections carried here

- Earlier integration notes attributed the endpoint replay's timing to the
  successor composition. The replay measured the endpoint loop alone.
- The same notes said released carrier capacity stays allocated "until the scope
  closes". It stays allocated until the owning allocation's or scope's storage is
  released.

The original receipts are unchanged.
