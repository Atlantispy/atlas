# Changelog

Versions of the Atlas tectonics package, newest first. Tagged versions link to their tags. Tags dev0 to dev41 mark the first commit that carried that version. Passing tests,
review and scientific acceptance are separate outcomes. No entry claims acceptance.

## Unreleased

### Tools

- Added quick tests that run on every push and pull request. Static checks and the optimised snapshot
  tests must pass. The older package tier reports its results only.
- Documented the target folders, module skeleton, file moves and code retirement rules.
- Extended the public-path check to scan the planned `shared/` folder once it exists.
- Added a scratch landing command that captures and seals diagnostic END outputs for later comparison.
- Added a scratch landing command for saved-output comparison. The comparator preserves strict failures
  and limits a historical exception to its approved pair.
- Added a scratch landing command that binds the exact source diff and comparison result in a repeatable
  preparation receipt.
- Added an optional one-cell finite-stock adoption check for the collar identity path.

### Tectonics

- Moved exact arithmetic selection into `atlas_shared`. Tectonics still chooses the backend at the first
  request, and issued geometry and heat workers bind it from their selected packages.
- Declared the existing `gmpy2==2.3.2` requirement in `atlas_shared`.

### Optimisations

#### Dispatch and execution

- Reused shared validation, record-writing, geometry and worker helpers in the optimised snapshot.
  Caller-specific calculations are retained where sharing would change the route or add work.
- Reused normalised heat-worker receipts.
- Reused dispatch input digests.
- Reused diagnostic sidecar identities.
- Passed the checked mapped-worker binding into the worker continuation call.
- Removed a repeated positivity assertion from runtime compatibility checks. Funded scratch stays live
  through the last evidence read.
- Reused the two verified native products in W12's direct reports. Graph reporting keeps its own copies.

#### Geometry and transport

- Removed common box values from the differential geometry sort key. Supports within each voxel are
  ordered by the remaining support fields.
- Evaluated admitted subduction transport quadrature points directly with the shared basis value
  routine. Standalone and transport evaluation retain their numerical order.
- Reused a clipping incidence result within each moving-face and moving-interface cut. The scalar and
  signed moving-face checks matched outputs and work budgets, with 20 and 32 fewer incidence calls
  respectively.
- Reused exact moving-face paths.
- Reused the active-edge order.
- Skipped unused rational conversions under the existing work budgets.
- Reused admitted native face records.
- Reused belt edge endpoints and lookup maps.
- Reused spherical face identifiers and projective transforms.
- Used the verified finite-stock registry identifier in differential geometry without decoding the whole
  definition.
- Reused exact operand values for joined finite stocks. Public preparation keeps its eager copies.
- Decoded the just-issued graph and stock inputs together in legacy finite transport.
- Borrowed the support's decoded rays for owner-edge identities and the angular proof.
- Read three vertices per face in end-mesh classifiers and issued the full rings.
- Reused the issued offer duration, offer ID and outbound volume array in coarse exterior transport.
- Reused each selected face deviation in geometric circulation's positive transfers and kept separate
  output lists.
- Reused the issued wall measure ID across the rigid workflow's ordered flow, geometry and thermal
  checks.
- Reused the matched exact-string ID in the unindexed endpoint scan.
- Used the already admitted initial interval or midpoint in the moving-interface reduced-line caller.
- Removed a repeated incidence check from exterior mortar issuance.
- Removed a repeated exact-rate check from coaxial pose rounding.
- Read the same immutable parent once in spatial enclosure and kept both late owner checks.
- Reused the producer's positive width in the native cap.
- Used one index lookup per boundary in END piece construction.
- Reused immutable inventory coverage for fresh funded partitions.
- Reused the checked outward width in differential mesh builders and looked up each row once.
- Reused the exact fractions and paired rows issued by geometry producers in native closure and mimetic
  moments. Physical identities and workspace checks still apply.
- Reused derived affine extrema for boxed wall lines.
- Carried the exponent used to construct the quantum in coaxial rounding.
- Used the enclosure's terminal two-operand bound in legacy routing diagnostics.
- Reused the caller's geometry type check in boundary projection.
- Computed finite-arc invariants once per arc in both package layouts and preserved each point's
  reduction order.
- Computed each scalar–endpoint product once in WP23 rational rotation and Bernstein bounds.
- Shared exact triangle weights through degree eight between static and moving-face moment integrals.
- Moved the planar geometry cancellation exception import out of its per-check path in both layouts.

#### Regional mechanics and workflow

- Carried decoded material pieces through pressure and strength assembly.
- Reused radial Picard plan metadata.
- Reused the first column thickness during temperature recovery in the reference-prism pressure and
  strength ports.
- Reused admitted physical fields, inventory and native map descriptors in funded regional evolution.
- Shared the checked mechanical request descriptors with context and effect checks in both package
  layouts.
- Used the volume map's bound source in radial strength.
- Reused the admitted coefficient digest in the viscosity factor path.
- Used the validated state descriptor for the first surface rate.
- Reused the bound map's issued radius and stored patch coverage in radial strength.
- Used the already capped immutable history when saving a regional workflow.
- Reused the selected side in regional wall preparation.
- Reused the issued pose descriptor in regional pose preparation.
- Reused validated fields in history producers.
- Carried the issued layout, catalogue, boundary stocks and checked W07 terminal energy through regional
  runs. Public and restored entry points retain their checks.
- Carried already admitted inventory bindings through concrete funded owners.
- Used the validated prefix and its one new receipt in fresh W08 issuance.

#### Storage and restore

- Reused detached metadata during issued-ledger history scans in the optimised snapshot and maintained
  wheel. External commit implementations retain both independent reads.
- Removed eight trailing scratch-holder assertions from historical snapshot transfers. The holders still
  live through transfer or generator close, and source verification stays in place.
- Removed the write-time decode of newly encoded array chunks. Cold reads, concurrent-write checks and
  atomic publication retain their checks.
- Reused admitted chunk metadata.
- Reused bounded storage reads.
- Reused history checkpoint keys.
- Reused raw capture digests.
- Kept detached arrays in regional history packs and borrowed their same-pack catalogue digests.
- Carried the verified shape, bytes and digest into issuance during late snapshot restore.
- Reused the checkpoint ID in the stable history codec.
- Skipped an unused regional copy in the stable history codec.
- Borrowed detached arrays and checked catalogue digests in the stable regional pack.
- Passed the verified shape, bytes and digest to the private issuer in stable W07 restore.
- Used the shared read-only opener to initialise session verification for both historical roles.
- Reused the canonical bytes of checked metadata when converting and reopening compact partitions.
- Fetched bounded metadata and bytes in one query for stable cold chunk reads.
- Reused the checked manifest body on interval candidate writes.
- Skipped decoding a raw miss on interval candidate writes only when the admitted payload is the same
  bytes object.
- Used one query for each root and index read in the dedicated bounded candidate reader.
- Built raw chunks from admitted bytes. Transformed candidates retain their verification.
- Retained the read-only history opener's exact authenticated settings for the live session check.
- Capped historical admission audit rows once before allocating the owner.
- Borrowed the already sized sealed subtree in compact record export. Container and memo-subtree bounds
  still apply.
- Reused enclosing depth admission for scalar rows. Container and memo-subtree bounds still apply.
- Removed repeated positive-size assertions from transfer scratch storage. Its reservations stay in
  place.
- Verified both pinned historical raw files and decoded only the mapped totals in the q297 END
  correspondence path. The standalone totals reader retains full decode and validation.

#### Heat

- Removed repeat plan validation at joined heat finish exit. Entry still fully validates the plan, and
  exit retains live owner and cancellation checks. The focused finish check matched endpoint bytes and
  preserved four refusal cases.
- Reused thermal face values.
- Reused the checked physical-column view from material admission in thermal column assembly.
- Reused compact mesh metric seals in both indexed heat restore routes.
- Reused admitted issuer metadata at heat completion. Caller-owned receipt copies and live source checks
  stay in place.
- Carried the checked legacy heat fixture selection into lookup.
- Reused canonical metadata bytes in compact heat saves.
- Removed the second compact column publishing block bound after minimum-size admission.
- Removed a redundant heat physical-order count assertion before workspace admission.
- Reused admitted compact rows in issued heat ordering.
- Omitted unused HIGH restore energy reads in issued heat ordering.
- Removed the repeated sparse heat ordering inventory bound.
- Passed the reference prism's checked boundary shapes directly in both package layouts. Standalone
  boundary and ordering calls retain their checks.
- Validated the already parsed physical columns and terminal target in detached heat restore without
  repeating their encodes.
- Reused checked dimensions in sparse factor admission.
- Passed the audit's factor count into the LOW solve.
- Carried the forward heat issuer's sealed numerical input into projection. Independent projection calls
  retain the full identity, temperature and face checks.
- Reused the exact paired rounding widths already measured for the same shapes in endpoint inventory.
- Reused the returned-string width bounded by earlier scratch admission in decimal inventory.
- Reused the admitted boundary dictionary and conductivity type checks in heat geometry.

### Bugfixes

- Fixed the hosted quick-test jobs to install their pinned dependencies.
- Fixed three hosted quick tests that depended on which form of the temporary path the machine reports.
- Streamed the checked cell identifiers of persisted shared-mesh heat ledgers into the canonical result
  hash. A bounded save and reopen matched the independent result ID and rejected incorrect or missing
  mesh bindings.

### Evidence

- Paired checks covered scalar and signed moving-face bounds, thermal mesh closure, pressure and
  strength, belt line assembly, native-face contact dispatch, array round trips, history restore,
  capture and worker receipt handling.
- The installed one-shot mapped worker exited cleanly and returned exactly the serial endpoint bytes in
  its verified receipt and funded result.
- The isolated finite-arc kernel matched output bits and reduced warmed kernel medians by 4–43% across
  six cases with 1–4,096 points and 4 or 96 arcs. Whole-simulation performance, scientific acceptance
  and production acceptance remain open.
- Strict graph comparison of the Unit 4 baseline against the preceding snapshot failed on four
  source-fingerprint pairs. The 1,989 substitutions were accepted for this pair only. Stored
  identifiers, the full partition and all 2,016 ordered supports matched.
- The fresh diagnostic chain passed all eight steps on the Unit 4 baseline. Six admitted heat workers
  computed all 5,315 faces and exited cleanly without fallback.
- Retained the [bounded i02 timing rerun](tectonics/evidence/i02-workflow-timing-r13.json) as historical
  evidence for `dcc1fc4`. Runtime cleanup changed 22 i02 timing bindings. The evidence register records
  their historical scope.
- Retained the [clean Windows installation](tectonics/evidence/environment-install-r2.json) as
  historical evidence for `dcc1fc4`. The install included gmpy2 2.3.2.
- Runtime cleanup changed the shared heat source bound by three I01 controls. The evidence register
  records their historical scope.

## [0.1.0.dev88](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev88) - 2026-11-27

### Tests

- Case B of the i04 controls is split into three classes that run in parallel. The slowest now takes under
  5 minutes (measured at 284 seconds).

## [0.1.0.dev87](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev87) - 2026-11-27

### Tests

- The i04 feedback provenance checks now run as 5 separate units. The longest takes 137 seconds instead of the
  previous 418-second single unit.

## [0.1.0.dev86](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev86) - 2026-11-27

### Tests

- The i04 family review worlds now run as 37 separate units, so the two i04 modules finish in about 22 minutes
  on 5 workers instead of one 71-minute unit.

## [0.1.0.dev85](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev85) - 2026-11-27

### Optimisations

- Differential trace calls no longer build a descriptor that nothing used.
- Differential geometry reuses bounds it has already decoded.
- Thermal and bridge steps drop repeated work.

## [0.1.0.dev84](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev84) - 2026-11-27

### Optimisations

- Advancing the regional inventory no longer re-checks the whole snapshot it has just built. New exported
  accounts keep their sign test, and the 256-interval cap stays.

## [0.1.0.dev83](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev83) - 2026-11-27

### Optimisations

- Saved exterior meshes and width tables no longer carry the trajectory segment list. Three list compares that
  repeated an id compare are removed.

### Pin records

- `private_heat_original_joined_r8._PUBLIC_ACCOUNTS_SHA` changes from
  `86dfeda43e3fdaa8776cf92b9ce67f77e864eed2404415f0fd5d1e8c1fdb5efe` to
  `cf897ac53deaac15f063ec4556a0ac2270fb87b16585eabce43d81a4f41c2021`, because the segment-list removal edits
  `regional_workflow.py`.

## [0.1.0.dev82](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev82) - 2026-11-27

### Optimisations

- Each step's stock record is now hashed as it is built. This removes one encode, one decode, one hash and one
  lease of 8 KiB or more per step.
- Snapshot metadata no longer rebuilds the manifest. Each metadata read with external fields no longer walks
  every array entry or renders, hashes and parses the whole manifest.
- One split now serves both mirror clips. Each hole plane saves one side filter, one row pass, one set of
  crossing points and two reservations.

### Cleanup

- Removed three text patchers that nothing called, all anchored on a function that had already been deleted.

### Pin records

- `owned_assessment_inventory._PINS['exact_gmp.py']` changes from
  `880223a8d807a6dfc4ca3c323923d5ac2db3e02c1f22e289181f88fd25c973a2` to
  `59452e0134b960580bda89adc9e763e30221636752ca0ad6cc5c5b8955d532dd`, because the single-split change edits
  `exact_gmp.py`.
- `owned_interval_assessment.INVENTORY_SHA` changes from
  `d752080fa6b91006ffee8d63f78b2978435f5ac314db19e33c4fad04089f15f9` to
  `c1f571dbd39dd21f6b3e2acaf1b12a6f5880fbcb1dc47e4153536a9d5b03e0d0`, because the pin above edits
  `owned_assessment_inventory.py`.

## [0.1.0.dev81](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev81) - 2026-11-27

### Tests

- Removed eight retired source-inventory and identity tests. Code-identity checks are no longer part of any run
  mode, so these tests were checking records that no longer exist.
- Six refusal tests now expect the messages the solvers give today.
- Removed six imports the deleted tests left unused.

## [0.1.0.dev80](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev80) - 2026-11-27

### Optimisations

- Kept the heat face pool's workers from a pass's main call for its refine call. A kept worker was ready in
  0.002 s, against 3.37 s for a fresh one (measured on dev75), so each refine call saves one pool start. Runs
  with no refine call save nothing.

### Bugfixes

- Fixed the heat face pool refusing every worker when run from a repository checkout, where the shared package
  sits in its own source folder. Such runs had fallen back to computing every face in one process.

## [0.1.0.dev79](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev79) - 2026-11-27

### Optimisations

#### Dispatch and execution

- A kept worker now signals each finished batch on its output pipe. The parent sees a batch finish within about
  1 ms instead of polling for up to 50 ms, and checks for the finished file only on a signal or a survey round.
- Memory readings no longer re-check that a process is alive just after the survey has done so.
- A survey no longer asks again about processes it has already seen alive in the same call.
- Once a worker's record has been verified and owned, the process, start-time and command look-ups are skipped.
  Its figures are still read.

## [0.1.0.dev78](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev78) - 2026-11-27

### Optimisations

#### Repeated checks removed

- `bridges.extract` no longer re-verifies a parent that `step()` has already verified.
- Preseal reads the head metadata directly. `RegionalWorkflow._r2_metadata_chain` is deleted.
- `exterior_state.validate_exchange` reads the stored wall body, which the exchange `result_id` binds, instead of
  restoring it. `WallMeasures.restore` is deleted.

### Pin records

- `private_heat_original_joined_r8._PUBLIC_ACCOUNTS_SHA` (`regional_workflow.py`) changes from
  `87ef361d68310d116eb94106bea8880f13d15e62b8fed92c159925793566a3be` to
  `86dfeda43e3fdaa8776cf92b9ce67f77e864eed2404415f0fd5d1e8c1fdb5efe`, because the metadata-chain removal edits that
  file. The extracted `retained_inventory_accounts` text is unchanged.

## [0.1.0.dev77](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev77) - 2026-11-27

### Tools

- Added `--exclude` to the test runner and to the impact map's `record`. An excluded test, class or module is not
  run, and the unit it belongs to is always selected afterwards. An ID that matches no test is refused before any
  test runs.

## [0.1.0.dev76](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev76) - 2026-11-27

### Tools

- The planner's report now counts the requests the parent process ran itself, with their seconds, grouped by
  the reason that stood when the parent took each one (`parent_reasons`). This measures where parallel work
  falls back to the parent; no scheduling decision changes.

## [0.1.0.dev75](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev75) - 2026-11-27

### Bugfixes

- Fixed the parallel test runner to start its workers with `-B`. The heat worker pool copies its caller's
  interpreter flags and refuses to start without `-B`, so pool tests run through the runner never used the pool:
  every call fell back to the serial route.

## [0.1.0.dev74](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev74) - 2026-11-27

### Tools

- The quick-tests workflow groups branch pushes by commit, so a later push no longer cancels the run of the
  commit before it and every pushed commit gets a finished result. Pull requests still cancel their older run.

## [0.1.0.dev73](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev73) - 2026-11-27

### Optimisations

#### Dispatch and execution

- Budget admission builds each budget's ancestor chain once, when the budget is made, instead of walking and
  sorting it on every reservation. The cyclic-ancestry check that this walk carried is removed, because a
  budget's parent is fixed at creation.

#### Geometry and transport

- Cell geometry is read once per volume certificate instead of once per literal.

## [0.1.0.dev72](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev72) - 2026-11-27

### Optimisations

#### Heat

- Each heat worker prepares the inputs that do not depend on the face once, at worker start. An invalid
  observation is now refused when the worker starts, not at the first face.
- The support basis builds each power from the one before and forms pair products once.
- Residual cell sums are added as a balanced tree instead of one long running sum. This raises the booked
  memory peak from 1.73 GB to 2.10 GB reserved; three record fields carry the new peak.
- The projection audit compares encoded pairs before decoding them.
- The certification kernel computes interval midpoints once.
- A column that is exactly nought is recognised before the first precision rung, so the audit's
  `attempts` list no longer holds the rungs this skips and gains one proof entry instead.

## [0.1.0.dev71](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev71) - 2026-11-27

### Optimisations

#### Geometry and transport

- The moments of a polygon over an annulus are now taken over both disks in one pass that shares the polygon's
  vertex and edge tables, instead of one full pass per disk. The results are the same intervals as before.

## [0.1.0.dev70](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev70) - 2026-11-27

### Optimisations

#### Geometry and transport

- Plate poses along a trajectory are remembered by a digest of their history, so a pose one step longer than
  a remembered one folds in only its new step instead of the whole history again. The memo holds at most
  4,096 entries (oldest first out) and is carried between interval processes in a file beside the store
  folder, never inside it; it is not an input to any result, and the first interval starts empty.

### Pin records

- The fresh-interval driver `_private/integration/run_fresh_interval.py` now loads and saves the pose memo,
  so its profile record changes in this landing (no repin of any existing record): sha256 `f4fa526558a1631eaf2c10b7098eb4d95618875a2440efa74d75053eabb29efb`
  becomes `cbf93a869453436a00577c20a079222ec56931231e7241d6b91b68fa7d8f79d2`.

## [0.1.0.dev69](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev69) - 2026-11-27

### Optimisations

#### Geometry and transport

- Trajectory and support ids are kept as running hashes of the segment list, so issuing an interval hashes
  only its new segment instead of the whole list again. The ids are the same bytes as before; a record
  without a remembered state falls back to hashing the full list.

## [0.1.0.dev68](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev68) - 2026-11-27

### Bugfixes

- Deleted three tests of checks that were removed in earlier landings (a code-change refusal on continued
  thermal state, a mocked step-record source check and a module-list assertion), and updated one expected
  refusal message to the current plan-change wording.

## [0.1.0.dev67](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev67) - 2026-11-27

### Tools

- The quick-tests workflow installs the acceptance requirements (core plus psutil), so test discovery no
  longer stops at a missing psutil import. Tag pushes no longer start a second run of the same commit.

## [0.1.0.dev66](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev66) - 2026-11-27

### Optimisations

#### Geometry and transport

- The exact 3D clip finds the largest and least row while it makes the rows, in place of two more passes:
  1.4% less clip time on 4,000 captured clips. Whole-faces-first and points-by-number orderings were timed
  4% to 6% slower and were not landed.

## [0.1.0.dev65](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev65) - 2026-11-27

### Bugfixes

- Repinned the joined control source and its derived text after the dev54 import move, so the fresh
  interval route loads again. Four source pins had stayed on their pre-dev54 values.

## [0.1.0.dev64](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev64) - 2026-11-27

### Optimisations

#### Geometry and transport

- Removed the publish-time rebuild and comparison of spatial record recipes. One stream of the original
  record now gives its identity and width scan; a proving read still rebuilds the record from its stored
  segments and checks it.

## [0.1.0.dev63](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev63) - 2026-11-27

### Optimisations

#### Storage and restore

- Stopped capturing the mesh and closed graph before each compact restart advance. Nothing read those two
  captures, so each advance now skips encoding and comparing them; only the bounds capture remains.
- Dropped an unused encoder parameter from the legacy mesh table JSON writer. No caller passed it.

## [0.1.0.dev62](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev62) - 2026-11-27

### Bugfixes

- Updated the heat assessment inventory's source pin for `exact_gmp.py` after the dev61 geometry change,
  and the interval assessment's pin of that inventory. On dev61 the heat assessment source check refused.

## [0.1.0.dev61](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev61) - 2026-11-27

### Optimisations

#### Geometry and transport

- Resumed the projection bound's cosine and sinc partial sums when a plane certificate raises the series
  order for the same vertex, endpoint and plane. Skipped terms are still charged at the same rate.
- Remembered the ordered identity of each fan edge within one partition when both ray records are the same.
- Computed Bernstein basis weights for a rotating normal once per degree and applied them to every
  coefficient.
- Skipped exactly-zero pairs in truncated moving-face jet products with one nonzero coefficient on a side.
- Rotated each voxel and owned box into the pose frame once per spatial pressure correction and reused it on
  every wall.
- Added per-process rotation and jet-column tables, off until a byte cap is set from a measured Debug peak.
  Every result, enclosure and refusal is unchanged; equality tests compare each step with the old route.

## [0.1.0.dev60](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev60) - 2026-11-27

### Bugfixes

- Two I03 network and transfer tests now read their W01 case file from the tectonics `cases` folder; the
  packaged fixture folder has no W01 case.

## [0.1.0.dev59](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev59) - 2026-11-27

### Optimisations

#### Geometry and transport

- Sizing a transport graph copy no longer walks the record byte by byte (3.4 s measured in the walk;
  about 8 s in all, estimated).

#### Storage and restore

- Stopped decoding each interval-store chunk again straight after encoding it (0.054 s per store,
  measured).

### Bugfixes

- A reuse-override test now restores the argument list, import path and the Atlas modules it loads, so a
  later test sharing its parallel worker no longer meets modules imported outside the checked loader.

## [0.1.0.dev58](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev58) - 2026-11-27

### Optimisations

#### Geometry and transport

- Hashed the exchange record's composite identity in the same pass that packs it, so initialisation reuses
  that id instead of streaming the record body again. A record naming another state still gets the computed id.
- Collected the packed bytes in one 64 KiB block and ran the cancel check and the hashes once a block instead
  of once a token. The bytes hashed are unchanged; each pack books 64 KiB more at its peak. The saving is not
  yet measured.

## [0.1.0.dev57](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev57) - 2026-11-27

### Optimisations

#### Heat

- Computed the fixed correction allowance once per peak instead of on every reserve. A put reserves again only
  when it released something.
- Checked the exact-arithmetic backend policy once per process, and skipped the lease call when a workspace is
  resized to its current size. Booked amounts and counts are unchanged.
- Updated the source pins of the heat files that hold the two changed files' hashes.

## [0.1.0.dev56](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev56) - 2026-11-27

### Tools

- The test runner's worker count now defaults to the queue ticket's booking (`RUNQ_WORKERS`) when run
  from the queue, and to this machine's cores less two otherwise. An explicit `--workers` still wins.

## [0.1.0.dev55](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev55) - 2026-11-27

### Tectonics

- Reusing a previous run is now a miss and recompute, not a refusal, when the two trees differ in a
  control case file or the previous run has another execution identity. The reader prints the reason,
  writes nothing and exits with code 76, so this run's producer runs instead.
- In a diagnostic tree a failed measurement seed is now a miss: files at the copy target are moved aside,
  never deleted, and run B starts unseeded, still anchored to run A's verdict and adoption for interval 2.

## [0.1.0.dev54](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev54) - 2026-11-27

### Optimisations

#### Dispatch and execution

- The execution identity now comes only from the solver backend, the runtime library record and the package
  version. The package no longer keeps a list of its own source files or hashes them at import, so
  `_application_sources.json` and its checksum file are gone.
- Every cache key, checkpoint id and plan id built from the execution identity misses once and is recomputed.
  No science value moves.
- A file edited without a version change keeps the same identity.
- Removed the installed-module check and the fixture-source check. Test fixtures are now an ordinary
  sub-package.
- Worker startup records no longer carry source bindings.
- Batch workers no longer re-hash the input files that the parent wrote in the same run.
- Removed the mid-run re-hash of the admission helper's own file.

### Bugfixes

- Removed five calls to a context method that the dev52 regroup had dropped; the fresh-interval, restart
  and heat-restore routes stopped there.
- Reusing a previous run now refuses when that run was computed under another execution identity, or
  when the two code trees differ in a control case file (it names the files).
- Prepared restarts made before this version do not reopen after it; none is planned or queued. Older run
  folders and history stores were not searched for one.
- A measurement store made before this version cannot seed a run made after it.
- The chain driver finds the shared package in a source checkout and hashes the selected package tree once
  per run for the overlap sources.

## [0.1.0.dev53](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev53) - 2026-11-27

### Bugfixes

- Updated the W11 invalidation selection to check that changes to inputs, parameters or backend
  still invalidate cached execution results after the source-edit test was retired.
- Fixed W11 scale evidence validation to use the native and tool digests checked at admission and
  the full declared shared-source list. Older receipts still need matching source and runtime bindings.

## [0.1.0.dev52](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev52) - 2026-11-27

### Tectonics

- Moved the maintained tectonics package into `tectonics/src` and grouped modules by scientific stage.
  The installed package keeps the supported tectonics entry points.
- Shared unsigned spherical arc calculations across the geometry, transport, heat and reference callers.
  The driving minor-arc check, Voronoi edge construction and public ring sampling retain their existing
  angle variants.
- Shared the conversion from plain longitude and latitude to Cartesian directions.
- Preserved stored event bindings when reading prior material transfers. Fresh events still establish
  their own bindings.

### Tools

- Grouped tectonics launchers, checks and reports by purpose and updated the documented commands.
- Unified quick test discovery around the maintained tectonics layout. Registered slow methods are
  reported as omitted.
- Bound adaptive convection resume and reporting to the selected case and reference data. A legacy run
  keeps its original configuration ID and receipt chain.
- Reused the assessment receipt binding between the W10 capacity assessment and the W11 reader.

### Optimisations

- Carried the declared solver identity through matching solver contexts and workers. The cache uses a
  separate key for the new execution identity.
- Reused the funded regional solve plan for the final two forces in the junction test while keeping all
  eight solves.
- Reused the physical heat update when constructing the new temperature and energy change.
- Reused authenticated support identifiers during single-worker dispatch.
- Kept the selected source binding through installed Fresh and Prepared startup and removed repeated
  source-tree scans.
- Removed readbacks after writing adaptive receipts and the prepared checkpoint copy. Adaptive receipt
  links use the bytes passed to the atomic write.
- Removed timed source rescans from overlap idle waits. Initial source loading and live guard checks
  remain.
- Removed unused per-tree checkpoint hashes and carried the accepted verdict and adoption digests
  through the driver. The combined checkpoint digest remains.

### Bugfixes

- Resolved spherical layout ownership after validating the atlas and its boundaries.

## 0.1.0.dev51 - 2026-11-26

### Optimisations

- Reused the authenticated source identity for the lifetime of a frozen execution context.
- Reused startup source digests at worker readiness and checked only newly loaded names during face
  processing. Worker result admission keeps its independent checks.
- Reused the selected GMP version pair when reporting runtime facts.
- Reused the profiling row lookup for repeated source paths.
- Reused the source inventory during heat interval assessment.
- Carried the source bindings proved by the same heat operation through FINISH.
- Reused the accepted area and mass calculations in free-surface processing.
- Reused one funded zero vector during flexure setup.
- Reused the current residual norm in the mimetic precision solve.
- Carried the first request digest through regional history processing.
- Dropped discarded masked-geometry digests and kept the digest used by the evidence record.


## 0.1.0.dev50 - 2026-11-26

### Tectonics

- Moved rolling scheduling for endpoint, wall and interface workers into the shared execution package.
- Moved single-contact job selection and its cost model into the shared scheduler.
- Shared the checks and result ownership used to restore joined heat state from cold storage or RAM.

### Optimisations

- Removed a second walk of the budget ancestry when funding a parallel batch owner.
- Reused the checked catalogue path when reading an interval catalogue image.
- Reused authenticated producer records when admitting an overlap reader.
- Read the durable finalisation gate once while checking it against the producer's four recorded pins.
- Reused the validated root verdict and runner identity when seeding interval one.
- Reused the authenticated root-runner hash in both stock seal paths.
- Reused the frozen heat-source identity during restore.
- Reused the validated packed-array edge span when walking record children.
- Reused stored enthalpy array views throughout the heat endpoint loop.
- Used the transported-cell index to reject duplicate cell IDs before field access.
- Carried the policy, source inventories, manifests and evidence already authenticated at prepared
  admission into the materialisation receipt.
- Reused the startup code identity throughout scheduler timing. Timing still checks live runtime and
  instrumentation changes.
- Sorted eligible positions once per paying-set search in the shared scheduler.
- Reused the checked ledger ancestry paths during worker fit preflight.
- Checked each required interval catalogue path once before using its saved file stat.

### Bugfixes

- Bounded the memory used to read wide maps during cold restore. Cancelled reads now release their
  temporary allocations.
- Kept interrupted one-shot worker returns available for retry and cleared each return only after it
  succeeded.
- Isolated the heat-plan content identity test so a reused worker cannot load the wrong copy of the
  tectonics package.

## 0.1.0.dev49 - 2026-11-26

### Tools

- Capture public development source and runtime information once when writing a binding.
- Fingerprint the same source bytes the public development and R12 loaders compile.
- Check late public development imports against the verified source list before they execute.
- Bind each profile result to the requested run and require its status to match the child process exit.
- Reuse verified loader identities inside each development smoke run.

## 0.1.0.dev48 - 2026-11-26

### Optimisations

- Consolidated the heat FINISH entry into the active implementation. It admits getter allocations
  before extraction and reuses the maximum operand width for exact equality checks.

## 0.1.0.dev47 - 2026-11-26

### Tectonics

- Removed the unused fixed-Cartesian belt solver from the working snapshot. Its shared solver
  dependencies and frozen historical implementation remain available.

## 0.1.0.dev46 - 2026-11-26

### Tectonics

- Removed the obsolete first-generation factory, piece assembly and provider adapter for diagnostic
  END capture. The active second-generation capture route remains in use.

## 0.1.0.dev45 - 2026-11-26

### Documentation

- Clarified what the tools, tectonics features and optimisations do in earlier changelog entries,
  including how regional models exchange results with the spherical plate network and how supplied
  plate splits, merges and ridge jumps are recorded.

## [0.1.0.dev44](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev44) - 2026-11-21

### Changed

- Made the graph, partition, owner, funding, bounds and geometry identifiers digests of each record's
  content. Code changes that move no values leave these identifiers intact. On load, a stored record's
  digest is still checked against its bytes.
- Bound a continued state and a solver's starting guess to the code that made them, outside the
  identifiers. A resumed or warm-started run under changed code is refused.
- Switched the profiling stack sampler off unless `ATLAS_PROFILE_SAMPLER=1`.
- Reissued the end pins for the new identity.

### Added

- Added tests that verify content-derived identifiers stay stable when the underlying data stay the
  same.
- Added tests for the record that carries content-derived identifiers and their bindings.
- Added tests of the identity rules for the moved records.
- Added tests that verify the profiling stack sampler stays off unless enabled.
- Updated two repository tests to pass the continued state's code identity.

### Notes

- The graph and partition identifiers and every identifier hashed from them move once at this version,
  affecting 14,582 of 42,126 identifier values in the reference chain. Each maps one to one except the
  old graph identifier, which was also the digest of its stored bytes. It splits into a content
  identifier and a byte digest.
- Decoded results equal dev43's apart from the identifiers and digests. No floating-point value differs.
- A build differing only by a comment gives the same identifiers.
- The reference chains took 1,536 s and, after resuming from a stop, 1,263 s plus a reused first step.
  Dev43 took 1,445 s. The second chain was at least as fast as dev43. Most of the first chain's extra
  time was in one root build.
- A resumed run reuses its stored first step under the same code. A changed build is refused before it
  starts.
- A changed build with its own valid pins and layout was never used to resume a stopped run, so a run
  never reached that identity check. The guard tests cover it.
- Old-store admission remains unproven by a run.

## [0.1.0.dev43](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev43) - 2026-11-20

### Changed

- Left four scheduling-only modules for machine measurement and work placement out of the run identity.
  A scheduling change alone no longer needs a new capture, new pins or cold caches.
- Changed the execution module to read the core count itself, so no kernel reads a value from a listed
  module.
- Reissued the end provider, end factory, runner and source table pins for the new identity.
- Removed internal reference numbers from code comments and kept the reasons.

### Added

- Added a test of the arithmetic runtime and the listed modules in the identity record.
- Added a test that a reuse override is refused in a proof run.

### Notes

- The reference chain took 1,445 s against 1,486 s for dev42 on the same machine.
- Decoded results equal dev42's apart from known identifiers and digests.

## [0.1.0.dev42](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev42) - 2026-11-20

Covers 21 Sep to 20 Nov 2026 (234 commits).

### Added

- Added the W01 to W08 tectonics chain and its I01 to I05 integration.
- Added a closed spherical network with shared plate boundaries, moved by supplied rotations while
  conserving material transfer.
- Added bridges that pass part of the spherical plate network to a regional model and return results to
  the same support and forcing.
- Added support for supplied plate splits, merges and ridge jumps, committed with the intervals they
  end.
- Added a matrix-free multigrid option for 3D regional Stokes solves, applying the velocity equations
  without storing the full matrix.
- Added the tectonics roadmap (`docs/ATLAS_ROADMAP.md`).
- Added completion plans 01 to 25 and their reviewed successors. They cover admission generation,
  preservation guards, heat correctness, comparison and extraction tools, geometry parity and restart
  validators.
- Started the optimisation programme to reduce repeated computation and storage work under existing
  numerical checks.
- Added measured geometry workers.
- Added measured heat workers.
- Added a compiled path for the directed-rounding dot products used in heat certificates. The numerical
  method and acceptance tolerances stay the same.
- Reduced heat arithmetic under the optimisation programme.
- Reduced pressure arithmetic under the optimisation programme.
- Added bounded lookahead to keep endpoint workers busy while preserving serial adoption order.
- Added lazy reads of the carried-start fields needed by each spatial operation, with a bounded
  whole-row fallback.
- Added optional reuse of verified pages between read batches of the same view, subject to freshness and
  memory bounds.
- Added a files query store that the prepared-state constructor declares for the snapshot loader.
- Added working snapshots of the optimisation package from 13 Nov, with issued pins and source tables
  for each batch and for the first and second result-moving breaks.
- Added the differential geometry phase with measured machine resources.
- Added offline development tools.
- Added local review tool guidance.

### Changed

- Replaced order-dependent sums with accurate, fixed-order reductions. Results across geometry, heat,
  cohorts, plates and regional reductions are independent of identifiers, labels and traversal order.
- Kept root, geometry and heat workers between batches.
- Ran source checks once per heat worker.
- Ran the heat predictor beside reconstruction.
- Moved self-checks and audits that repeated earlier proofs into tests and proof mode.
- Ran save-time equations only with proofs on.
- Reused issued rows, registries, trusted inputs, validated fields and fresh history results already
  computed upstream on the run route.
- Consolidated the documentation for status and entry points, method guides, the optimisation catalogue
  and category contracts.
- Checked out text with LF line endings everywhere.

### Fixed

- Fixed the LF receipt writers after the 28 and 29 Sep reviews.
- Fixed successor receipts after the 28 and 29 Sep reviews.
- Fixed the guard that checks candidate bytes against the evidence register before commit, following the
  28 and 29 Sep reviews.
- Fixed Windows R5 recovery after the 28 and 29 Sep reviews.
- Fixed public development defects from the 28 and 29 Sep reviews.
- Fixed exact heat capacity projection.
- Fixed decimal representation.
- Fixed power-plane traces.
- Fixed cached heat support keys.
- Fixed allocation refusal so it propagates without changing the numerical method.
- Fixed force range handling.
- Fixed history readers.
- Fixed proposal selection.
- Fixed junction operand order.
- Fixed ring edge reductions.
- Verified the checkpoint partition ID before compact restore.

### Removed

- Retired redundant reports.
- Removed repeated checks found by the repeated-work sweep.
- Removed duplicate dispatch checks.
- Removed duplicate measurement checks.
- Removed a redundant reconstruction assertion.
- Removed obsolete experiments.
- Removed obsolete receipts.
- Removed duplicate sources.
- Removed the sanitisation hash catalogue.

### Notes

- Sealed-mesh reuse stays disabled.
- Plan06 ships with D5 disabled.
- R4 acceptance is paused.

## [0.1.0.dev41](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev41) - 2026-09-21

- Added a velocity multigrid stage to the variable-viscosity Stokes solve for R4.4.

## [0.1.0.dev40](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev40) - 2026-09-21

- Changed the R4.4 convection settings to shorten the run time.
- Changed the generator registries to shorten the run time.

## [0.1.0.dev39](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev39) - 2026-09-21

- Added Anderson starts to the R4.4 convection cases.
- Added nonlinear starts to the R4.4 convection cases.
- Added cross-step starts to the R4.4 convection cases.
- Added preconditioner reuse to the R4.4 convection cases.
- Added source verification to the R4.4 convection cases.
- Added an R4.4 convection campaign example.

## [0.1.0.dev30](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev30) - 2026-09-19

- Added the R4.1 Stokes cases with review records.
- Added the R4.2 thermochemical cases with review records.
- Added the R4.3 variable-viscosity Stokes cases with review records.

## [0.1.0.dev25](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev25) - 2026-09-19

- Added R3 physical closure cases for local rock rheology and retained mechanical memory.
- Added the tectonics licence.
- Added the repository licensing page.

## [0.1.0.dev23](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev23) - 2026-09-19

- Changed the optimisation reference to remove repeated material.
- Added third-party notices.
- Added test records for the cleanup.

## [0.1.0.dev22](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev22) - 2026-09-18

- Added R1 plate reference data with its use policy.
- Added R2 precursor cases for plate-independent initial material volumes and temperature sampling.
- Added an R2 execution case that checks scaling against the original numerical tolerances and
  whole-request inventories.
- Optimised R2 execution by pruning candidates conservatively and admitting independent batches. The
  governing equations stay the same.

## [0.1.0.dev20](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev20) - 2026-09-18

- Added W01 boundary cases.
- Added W01 cases for the coordinate frames and rotations used to describe geological geometry and
  motion.
- Added W01 Earth material cases.
- Added W01 cases for describing starting geology before running the physical models.
- Added W01 geometry cases.
- Added the plate reference case.
- Extended the tectonics README.

## [0.1.0.dev10](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev10) - 2026-09-17

- Completed W02 material transport.
- Completed W02 regional transport, including material cohorts and their histories across regional
  cells.
- Added W02 optimisation foundations.

## [0.1.0.dev1](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev1) - 2026-09-17

- Added the tectonics plan.
- Added the optimisation reference covering execution costs, resource accounting and methods for
  avoiding repeated work.
- Added bounded, deduplicated array persistence with memory and storage measurements.
- Changed the remake kernels to validate their inputs.

## [0.1.0.dev0](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev0) - 2026-09-16

- Added the tectonics remake package.
- Documented its mathematical foundations.
- Added foundation cases.
- Added voxel storage notes.
