# Changelog

Versions of the Atlas tectonics package, newest first. Each version is the version text of the package;
each heading links its tag. Tags dev0 to dev41 mark the first commit that carried that text. Passing tests,
review and scientific acceptance are separate outcomes; no entry here claims acceptance.

## Unreleased

### Added
- Added quick tests that run on every push and pull request: static checks and the optimised snapshot
  tests must pass; the older package tier reports only.

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
