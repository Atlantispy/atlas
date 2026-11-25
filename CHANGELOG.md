# Changelog

Versions of the Atlas tectonics package, newest first. Each version is the version text of the package;
each heading links its tag. Tags dev0 to dev41 mark the first commit that carried that text. Passing tests,
review and scientific acceptance are separate outcomes; no entry here claims acceptance.

## Unreleased

### Added
- Added quick tests that run on every push and pull request: static checks and the optimised snapshot
  tests must pass; the older package tier reports only.
- Fixed the quick tests on the hosted runner: the jobs install their pinned dependencies, and three tests no
  longer depend on which form of the temporary path the machine reports.
- Added the repository layout rules: the target folders, the module skeleton, how files move and how old
  code is retired. The public-path check scans the planned `shared/` folder once it exists.

### Changed
- Differential geometry orders supports within each voxel by the remaining support fields. The common
  box values no longer enter each sort key.
- Subduction transport preparation evaluates its admitted quadrature points directly with the shared
  basis value routine. Standalone and transport evaluation retain their existing numerical order.
- The optimised snapshot and maintained wheel reuse detached metadata during issued-ledger history scans.
  External commit implementations retain both independent reads.
- Removed eight trailing scratch-holder assertions from historical snapshot transfers. The holders
  still live through transfer or generator close, and existing source verification stays in place.
- The q297 END correspondence path verifies both pinned historical raw files and decodes only the
  mapped totals. The standalone totals reader retains its full decode and validation.
- Moved exact arithmetic selection into `atlas_shared` and declared the existing
  `gmpy2==2.3.2` requirement there. Tectonics still chooses the backend at the first
  request, and issued geometry and heat workers bind it from their selected packages.
- Reused shared validation, record-writing, geometry and worker helpers in the optimised snapshot. Kept the
  existing caller-specific calculations where sharing would change the route or add work.
- Reused a clipping incidence result within each moving-face and moving-interface cut. The scalar and signed
  moving-face checks matched outputs and work budgets, with 20 and 32 fewer incidence calls respectively.
- Kept full plan validation at joined heat finish entry and retained live owner and cancellation checks
  at exit. The focused finish check matched endpoint bytes and preserved four refusal cases.
- Reused exact moving-face paths, active-edge order and thermal face values in the optimised snapshot.
  Skipped unused rational conversions under the existing work budgets, and carried decoded material pieces
  through pressure and strength assembly. Reused admitted native face records, belt edge endpoints and
  lookup maps, spherical face identifiers and projective transforms, and radial Picard plan metadata.
  Differential geometry uses the verified finite-stock registry identifier without decoding the whole definition.
  Joined finite stocks reuse exact operand values while public preparation keeps its eager copies.
  Legacy finite transport decodes its just-issued graph and stock inputs together.
  Reference-prism pressure and strength ports reuse the first column thickness during temperature recovery.
  Owner-edge identities and the angular proof borrow the support's decoded rays. End-mesh classifiers
  read three vertices per face and issue the full rings.
  Coarse exterior transport reuses the issued offer duration, offer ID and outbound volume array.
  Geometric circulation reuses each selected face deviation in the positive transfers and keeps separate output lists.
  The rigid workflow reuses the issued wall measure ID across its ordered flow, geometry and thermal checks.
  The unindexed endpoint scan reuses its matched exact-string ID. The moving-interface reduced-line
  caller uses its already admitted initial interval or midpoint.
  Exterior mortar issuance drops a repeated incidence check, and coaxial pose rounding drops a repeated
  exact-rate check. Spatial enclosure reads the same
  immutable parent once and keeps both late owner checks.
  The native cap reuses its producer's positive width. END piece construction uses one index lookup per
  boundary. Fresh funded partitions reuse their immutable inventory coverage. Differential mesh
  builders use the already checked outward width and look up each row once.
  Native closure and mimetic moments use the exact fractions and paired rows already issued by their
  geometry producers. Their physical identities and workspace checks stay.
  Boxed wall lines reuse their derived affine extrema, and coaxial rounding carries the exponent used
  to construct its quantum. Legacy routing diagnostics use the enclosure's terminal two-operand bound.
  Transfer scratch storage keeps its reservations and drops repeated positive-size assertions.
  Funded regional evolution reuses its admitted physical fields, inventory and native map descriptors.
  Boundary projection reuses the caller's geometry type check, and mechanical requests share the
  checked descriptors with their context and effect checks in both package layouts.
  Radial strength uses the volume map's bound source, the viscosity factor path reuses the admitted
  coefficient digest, and the first surface rate uses the validated state descriptor.
  Radial strength also reuses the bound map's issued radius and stored patch coverage.
  Regional workflow save uses its already capped immutable history. Regional wall and pose preparation
  reuse the selected side and the issued pose descriptor. Thermal column assembly reuses the checked
  physical-column view from material admission.
  History producers reuse their own validated fields. Regional runs carry the issued layout, catalogue,
  boundary stocks and checked W07 terminal energy. Public and restored entry points keep their checks.
  Concrete funded owners carry the already admitted inventory bindings, and fresh W08 issue uses the
  validated prefix and its one new receipt.
  Both package layouts compute finite-arc invariants once per arc and preserve each point's reduction order.
  The WP23 rational rotation and Bernstein bounds compute each scalar–endpoint product once. Static and
  moving-face moment integrals share exact triangle weights through degree eight.
- Moved the planar geometry cancellation exception import out of its per-check path in both layouts.
- Removed the write-time decode of newly encoded array chunks. Reused admitted chunk metadata, bounded
  storage reads, history checkpoint keys and raw capture digests. Cold reads, concurrent-write checks
  and atomic publication retain their existing checks. Regional history packs keep their detached arrays
  and borrow their same-pack catalogue digests. Late snapshot restore carries the verified shape, bytes
  and digest into issuance. The stable history codec reuses the checkpoint ID and skips an unused regional
  copy. The stable regional pack borrows its detached arrays and checked catalogue digests, and stable
  W07 restore gives the private issuer the verified shape, bytes and digest. The shared read-only opener
  initialises session verification for both historical roles. Compact
  partition conversion and reopen reuse the canonical bytes of the checked metadata. Stable cold chunk reads
  fetch bounded metadata and bytes in one query. Interval candidate writes reuse their checked manifest
  body and skip decoding a raw miss only when the admitted payload is the same bytes object.
  A dedicated bounded candidate reader uses one query for each root and index read. The raw writer builds
  a raw chunk from its admitted bytes, while transformed candidates keep their verification.
  The read-only history opener
  retains its exact authenticated settings for the live session check. Historical admission caps
  the audit rows once before owner allocation.
  Compact record export borrows the already sized sealed subtree, and scalar rows reuse their
  enclosing depth admission. Container and memo-subtree bounds still apply.
- Reused normalised heat-worker receipts, dispatch input digests and diagnostic sidecar identities.
  Reused compact mesh metric seals in both indexed heat restore routes and admitted issuer metadata at
  heat completion. Kept caller-owned receipt copies and live source checks. Legacy heat fixture reuse
  carries the checked selection into lookup. Compact heat saves reuse the canonical metadata bytes,
  and worker continuation carries the checked mapped-worker binding into the call.
  Compact column publishing drops the second block bound after minimum-size admission. Heat
  physical-order setup drops a redundant count assertion before the existing workspace admission.
  Issued heat ordering reuses admitted compact rows and omits unused HIGH restore energy reads. Sparse
  heat ordering drops its repeated inventory bound. The reference prism passes its own checked boundary
  shapes directly in both package layouts. Standalone boundary and ordering calls retain their checks.
  Detached heat restore validates its already parsed physical columns and terminal target without
  repeating their encodes. Sparse factor admission reuses checked dimensions and the LOW solve
  carries its audit's factor count.
  The forward heat issuer carries its sealed numerical input into projection. Independent projection
  calls retain the full identity, temperature and face checks.
  Endpoint inventory uses the exact paired rounding widths already measured for the same shapes.
  Decimal inventory uses the returned-string width bounded by its earlier scratch admission.
  Runtime compatibility keeps its funded scratch through the last evidence read and drops the
  repeated positivity assertion. Heat geometry reuses its already admitted boundary dictionary and
  conductivity type checks.
- Reused the two verified native products in W12's direct reports. Graph reporting keeps its own copies.

### Fixed
- Persisted shared-mesh heat ledgers stream their checked cell identifiers into the canonical result hash.
  A bounded save and reopen matched the independent result ID and rejected incorrect or missing mesh bindings.

### Evidence
- Paired checks covered scalar and signed moving-face bounds, thermal mesh closure, pressure and strength,
  belt line assembly, native-face contact dispatch, array round trips, history restore, capture and worker
  receipt handling. The installed one-shot mapped worker exited cleanly and returned exactly the serial
  endpoint bytes in its verified receipt and funded result. The isolated finite-arc kernel matched output
  bits and reduced warmed kernel medians by 4–43% across six cases with 1–4,096 points and 4 or 96 arcs.
  Whole-simulation performance,
  scientific acceptance and production acceptance remain open.
- On the Unit 4 baseline, strict graph comparison with the preceding snapshot failed on four source-fingerprint pairs, with
  1,989 substitutions accepted for this pair only. Stored identifiers, the full partition and all 2,016
  ordered supports matched. The fresh diagnostic chain passed all eight steps. Six admitted heat workers
  computed all 5,315 faces and exited cleanly without fallback. That chain covered the Unit 4 baseline.
- Retained the [bounded i02 timing rerun](tectonics/evidence/i02-workflow-timing-r13.json) and [clean Windows
  installation](tectonics/evidence/environment-install-r2.json) as historical evidence for `dcc1fc4`. The install
  included gmpy2 2.3.2. The runtime cleanup changed 22 i02 timing bindings and the shared heat source
  bound by three I01 controls. The evidence register records their historical scope.

## [0.1.0.dev44](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev44) - 2026-11-21

### Changed
- Made the graph, partition, owner, funding, bounds and geometry identifiers digests of each record's content,
  so a code change that moves no value no longer moves them. The byte checks stay where bytes are meant: a
  stored record's digest is still checked against its bytes on load.
- Bound a continued state and a solver's starting guess to the code that made them, outside the identifiers,
  so a resumed or warm-started run under changed code is still refused.
- Switched the profiling stack sampler off unless `ATLAS_PROFILE_SAMPLER=1`.
- Issued the end pins again for the new identity.

### Added
- Added tests of the content identifiers, the content record, the identity rules for the moved records and the
  sampler switch; two repository tests now pass the continued state's code identity.

### Notes
- The identifiers above move once, at this version: the graph identifier and the partition identifier change
  value, and so does every identifier hashed from them (14,582 of 42,126 identifier values in the reference
  chain). Each maps one to one, except the graph's old identifier, which was also its stored bytes' digest
  and now splits into the content identifier and that byte digest. Decoded results equal
  dev43's apart from these identifiers and digests; no floating-point value differs.
- A build differing only by a comment gives the same identifiers.
- Two reference chains took 1,536 s and, resumed after a stop, 1,263 s plus a reused first step; dev43 took
  1,445 s. The second chain was not slower than dev43; most of the first chain's extra time was in one root build.
- A resumed run reuses its stored first step under the same code, and a changed build is refused before it
  starts. A changed build with its own valid pins and layout was not resumed against a stopped run, so the
  identity check itself was not reached by a run; the guard tests cover it.
- Old-store admission is not proven by a run.

## [0.1.0.dev43](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev43) - 2026-11-20

### Changed
- Left four scheduling-only modules (machine measurement and work placement) out of the run identity, so a
  scheduling change alone no longer needs a new capture, new pins or cold caches.
- Changed the execution module to read the core count itself, so no kernel reads a value from a listed module.
- Issued the end pins again for the new identity (end provider, end factory, runner and source tables).
- Removed internal reference numbers from code comments, keeping the reasons.

### Added
- Added a test of the arithmetic runtime and the listed modules in the identity record.
- Added a test that a reuse override is refused in a proof run.

### Notes
- The reference chain took 1,445 s against 1,486 s for dev42 on the same machine; decoded results equal
  dev42's apart from known identifiers and digests.

## [0.1.0.dev42](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev42) - 2026-11-20

Covers 21 Sep to 20 Nov 2026 (234 commits).

### Added
- Added the tectonics module chain W01 to W08 and its integration (I01 to I05): spherical network, bridges
  and events, a 3D multigrid solver, and the roadmap (`docs/ATLAS_ROADMAP.md`).
- Added completion plans 01 to 25 and their reviewed successors: admission generation, preservation guards,
  heat correctness, comparison and extraction tools, geometry parity, and restart validators.
- Added the optimisation programme: measured geometry and heat workers, compiled heat, reduced heat and
  pressure arithmetic, endpoint lookahead, lazy carried-start rows, page carry, and the files query store.
- Added working snapshots of the optimisation package from 13 Nov, with issued pins and source tables for
  each batch and for the first and second result-moving breaks.
- Added the differential geometry phase with measured machine resources.
- Added offline dev tools and local review tool guidance.

### Changed
- Made results independent of identifiers, labels and traversal order across geometry, heat, cohorts,
  plates and regional reductions; replaced order-dependent sums with accurate, fixed-order reductions.
- Kept workers between batches (root, geometry and heat), ran source checks once per heat worker and ran the
  heat predictor beside the reconstruction.
- Moved self-checks and audits that repeated earlier proofs into tests and proof mode; save-time equations
  run only with proofs on.
- Reused results already computed upstream on the run route: issued rows, registries, trusted inputs,
  validated fields and fresh history results.
- Consolidated the documentation: status and entry points, method guides, optimisation catalogue and
  category contracts; retired redundant reports.
- Checked out text with LF line endings everywhere.

### Fixed
- Fixed review defects of 28 and 29 Sep: LF receipt writers, successor receipts, the before-commit guard,
  Windows R5 recovery and public development.
- Fixed exact heat capacity projection, decimal representation, power-plane traces and cached heat
  support keys.
- Fixed allocation refusal so it propagates without changing the numerical method.
- Fixed force range handling, history readers, proposal selection, junction operand order and ring edge
  reductions.
- Verified the checkpoint partition id before compact restore.

### Removed
- Removed repeated checks found by the repeated-work sweep, duplicate dispatch and measurement checks, and
  a redundant reconstruction assertion.
- Removed obsolete experiments, receipts, duplicate sources and the sanitisation hash catalogue.
- Known limit: the sealed-mesh reuse stays disabled; Plan06 ships with D5 disabled; R4 acceptance is paused.

## [0.1.0.dev41](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev41) - 2026-09-21

- Added a velocity multigrid stage to the variable-viscosity Stokes solve for R4.4.

## [0.1.0.dev40](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev40) - 2026-09-21

- Changed R4.4 convection settings and generator registries to shorten the run time.

## [0.1.0.dev39](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev39) - 2026-09-21

- Added R4.4 convection cases: Anderson, nonlinear and cross-step starts, preconditioner reuse and source
  verification, with a campaign example.

## [0.1.0.dev30](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev30) - 2026-09-19

- Added R4.1 to R4.3: Stokes, thermochemical and variable-viscosity Stokes cases with review records.

## [0.1.0.dev25](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev25) - 2026-09-19

- Added R3 physical closure cases.
- Added the tectonics licence and the repository licensing page.

## [0.1.0.dev23](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev23) - 2026-09-19

- Changed the optimisation reference to remove repeated material.
- Added third-party notices and test records for the cleanup.

## [0.1.0.dev22](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev22) - 2026-09-18

- Added R1 plate reference data with its use policy.
- Added R2 precursor cases and scaling, and optimised R2.

## [0.1.0.dev20](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev20) - 2026-09-18

- Added W01 cases: boundaries, coordinates, earth materials, geological description and geometry.
- Added the plate reference case and extended the tectonics README.

## [0.1.0.dev10](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev10) - 2026-09-17

- Completed W02 material and regional transport, with optimisation foundations.

## [0.1.0.dev1](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev1) - 2026-09-17

- Added the tectonics plan and the optimisation reference.
- Added bounded, deduplicated array persistence with memory and storage measurements.
- Changed the remake kernels to validate their inputs.

## [0.1.0.dev0](https://github.com/Atlantispy/atlas/releases/tag/v0.1.0.dev0) - 2026-09-16

- Added the tectonics remake package with mathematical foundations, foundation cases and voxel storage notes.
