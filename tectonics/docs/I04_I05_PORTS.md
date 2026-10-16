# I04/I05 port record: the values that pass between motion and material state

**WORKING NON-CANON. Record written 3 October 2026 by I04 Part A (single writer); not yet accepted.**
- **Conditions applied.** The coordinator's rulings on the decisions proposal, and its round-1 verification
  (3 October 2026), are written into this record.
- **Order of work.** I05 codes against this record only after Codex accepts it. Until then I04 Part A tests its own
  controls against these shapes, using authored, labelled inputs.
- **Amendments.** Proposed changes from I05 or later stages go in their handoffs as amendments, not into a parallel
  adapter.
- **I04b amendments (4 October 2026; candidate, coordinator verification pending).** The coupled P5, the endpoint
  P1/P2 headers, the P6 and P7 types, the new P9 boundary reaction, D-P3 decided for the coupled route, and P8 not
  issued in v1. They follow the coordinator's rulings on the I04b decisions proposal (P1-P7, B5).

The [integration plan](INTEGRATION_PLAN.md) asks I04 and I05 to "develop against one interface; complete their
coupled checks together rather than repeatedly designing adapters". This page is that interface.
- [I04_CAUSAL_START.md](I04_CAUSAL_START.md) explains how I04 uses it.
- The I03↔I05 transport port
  ([I03_SPHERICAL_NETWORK.md §7](I03_SPHERICAL_NETWORK.md#7-transport-port-i03--i05)) remains the record for moving
  material. Nothing here changes how material amounts are transferred.

## 1. Rules common to every port value

**One header.** Every value carries a `Header`
([`integration_ports.py`](../src/atlas_tectonics/integration_ports.py)) with these fields:

| Field | Meaning |
| --- | --- |
| `port` | P1 to P9. P4 is reserved: a P4 header refuses `unsupported` |
| `parent_state_id` | the accepted I02/I03 state the values belong to |
| `interval` | `(start_step, end_step, start_s, end_s)` |
| `endpoint_s` | the one time both sides evaluate at. Part A uses `endpoint_s = start_s`, at the network's step and time; the coupled route (I04b) uses `endpoint_s = end_s` at the candidate endpoint (section 3, D-P3) |
| `network_id` | the I03 `network_id` (I03 uses `geometry_id` for its atlas, so the name differs) |
| `support_id` | the sha256 of a versioned support record bound to `network_id`. P1: the trace support `atlas.i04-trace-support.v1`, with its ordered points and sides. P5: the per-plate support `atlas.i04-plate-support.v1`, with the network's plates in order |
| `datum_id` | the sha256 of the shared datum record (pressure, compensation elevation, mantle density, gravity, reference temperature), or none for a value whose producer used no datum. P1 always needs one |
| `parameter_id` | the producer's model and parameter identity: the starting family's `family_id`, the forcing's identity for a Part A P5, sha256 of (forcing identity, D2 declaration identity) for the coupled P5, the moving state's `moving_id` for P1/P2 from I05, and the endpoint balance's `balance_id` for P6, P7 and P9 |
| `frame_id` | the network's frame, meaning the axes every vector in the value is expressed in. The declared mantle frame is those axes. A mantle label is kept only as a kinematic description |
| `owner`, `producer` | the stage responsible, and its route |

**Other rules:**
- **Units.** Each port's field names fix its units (SI, listed below), and the units are recorded in its identity.
- **One common endpoint** (CM-05, "properties from one endpoint state").
- **Owned, immutable arrays.** Values are frozen copies, never aliases of a caller's buffer. The identity is the
  sha256 of the canonical record, followed by every array's descriptor and bytes, as for I03 records.
- **Unknowns are explicit.** A required value that is unknown or absent refuses. It is never read as zero.
- **Values, not transfers.** A port never debits or credits an account. Material, mass, enthalpy and slab inventory
  move only through the I02 ledger and the I03 transfer, once.
- **Interval exchange records.** I04 port values are bound to `parent_state_id` and `network_id`.
  - Binding them to the I03 `motion_id` that consumes them is the Part B persistence requirement of section 4. Part
    A values do not carry it.
  - They are **not** entries in the I02 quantity catalogue. A catalogue edit changes `CATALOGUE_ID`, which every
    stored state carries, and would make stored sphere states unrestorable. Such a migration is a Codex or owner
    decision.

**Refusals.** Every port refusal raises `PortRefused`, a `TectonicsError`. It has one `.code` per refusal. When the
refusal wraps an I01 `REFUSED_*` code, a kernel message or a header field, that goes in `.detail`. The two P1
consumers (the starting family's producer and the D1 balance) use the same code for the same fault.

| Code | Meaning, and the faults that map to it |
| --- | --- |
| `missing value` | a required field, column, name or interval value is absent or not finite (`detail` names it) |
| `stale identity` | the header names a different parent state, interval, network, frame, datum, forcing or support from the one the consumer holds; `detail` names the field (`parent_state_id`, `interval`, `network_id`, `frame_id`, `datum_id`, `parameter_id`, `support_id`) |
| `incompatible support` | the values are not on the support the consumer evaluates: a P1 `support_id` that differs from the trace support's, a support that is not a trace support (`detail = support`), or a point index. A P5 `support_id` mismatch is `stale identity`, because P5 is checked field by field against its balance |
| `unit mismatch` | reserved. Units are fixed by field names in Part A, so no Part A path produces this code |
| `unresolved column` | the producer could not say which material occupies a support point |
| `unsupported` | a port, regime, field, source or value this record does not admit. `detail` carries the I01 code or reason |

## 2. The ports

| Port | Direction | Support | Owner and timing | Refusal codes |
| --- | --- | --- | --- | --- |
| **P1 columns** | I05 → I04 | **Trace support**: the midpoint of every plate-boundary edge, twice (left, then right) | I05; Part A uses authored or starting-family columns, labelled as such. Evaluated at `endpoint_s = start_s`. Amended 4 October 2026: a face of bitwise-equal layer structure gives an `fv-cell-mean` column, flagged per point (D-P2) | `missing value` (absent layer, name or datum); `unresolved column`; `unsupported` (water without an admitted source, `detail = water_source`; a kernel refusal, `detail` = the kernel message; rock lighter than water, `detail = REFUSED_WATER_IN_ROCK_COLUMN`) |
| **P2 strength state** | I05 → I04 | I03 cohort pieces per face, keyed by cohort or `history_id` | I05; at `endpoint_s`: the interval start (Part A) or the candidate endpoint `E^k` (coupled route); consumed by I04.3 | `missing value` (an unknown value, or a missing `healing_law_id`); `unsupported` (a healing law other than `atlas.i04-healing-none.v1`) |
| **P3 rigidity** | declared input → I04, I08 | per declaration (one core) | **selected** by the owner or I08; **carried** with the columns by I05, never manufactured; **consumed** by I04 and I08; static | each `I01_ELASTIC_CORE` §6 refusal, applied in that section's order, maps to `unsupported` with the I01 code in `detail`. These include `REFUSED_UNSUPPORTED_CONTRACT`, `REFUSED_INVALID_COLUMNS`, `REFUSED_CORE_PLACEMENT_ABSENT`, `REFUSED_UNSUPPORTED_CORE`, `REFUSED_INVALID_CORE`, `REFUSED_CORE_OUTSIDE_ROCK`, `REFUSED_ZERO_RIGIDITY_NOT_A_CORE` and `REFUSED_CORE_SOLVER_MISMATCH` |
| **P4 belt and basal state** | I05 → I04 | — | reserved | `unsupported` |
| **P5 motion** | I04 → I05, via I03 | the per-plate support | I04. Part A: issued only by `integration_driving.motion_port` from a solved balance, at `endpoint_s = start_s`, `omega` held over the interval (explicit). Coupled route: issued by the private `integration_feedback._motion_port`, the committed value only from a converged interval (`_finish`), at `endpoint_s = end_s` (D-P3) | `missing value` (a balance bound to no parent state and interval; a plate without a value); `stale identity` (any header field that differs from the balance, `detail` names it); `unsupported` (a Part A endpoint not at the start of the interval). Deforming-region velocities have no field |
| **P6 mechanical increment** | I04 → I05 | the endpoint's piece support (sublayer material points) | I04 D2 (I04b, `integration_ports.MechanicalIncrement`), from the integration at the committed endpoint | `missing value` (an absent increment); `unsupported` with `detail = negative increment` (a negative increment while `h = 0`); `unsupported` with `detail = increment above 2∫e dt` (an increment above its D-P1 bound) |
| **P7 dissipation** | I04 → I05 | the endpoint's piece support; faces for drag | I04 (I04b, `integration_ports.Dissipation`), from the **same** D2 integration as P6, so heat is booked once | `missing value` (absent interval energy); `unsupported` (heat outside the declared IN-05 rule, or elastic or boundary work offered as heat) |
| **P8 force-driven sides** | I04 → I05 | strip sides | I04 or I09; **not issued in v1** (no admitted open-base strip exists) | each `I01_BASAL_CLOSURE` refusal maps to `unsupported` with the I01 code in `detail`, for example `REFUSED_SIDE_INFLOW`, `REFUSED_UNIT`, `REFUSED_OVERDETERMINED_COMPONENT`, `REFUSED_INCOMPATIBLE_NORMAL_FLUX`, `REFUSED_PRESSURE_NULLSPACE` and `REFUSED_LOCAL_FIELD_UNSPECIFIED` |
| **P9 boundary reaction** | I04 → I07, I09 | the P1 trace support | I04 (I04b, `integration_ports.BoundaryReaction`, `atlas.i04-boundary-reaction.v1`), from the endpoint balance of a converged interval | `missing value` (one ownership flag per trace edge; absent arrays); `incompatible support` (not the trace support); `unsupported` (another header port) |

**P1 columns.**
- Per support point, layers bottom to top: `thickness_m` (m), `reference_density_kg_m3`, `alpha_per_k` (1/K),
  `bottom_temperature_k` and `top_temperature_k` (K). This is the `I01_GPE` representation, at most 32 layers.
- Optional `water_depth_m`, admitted only from:
  - a `test:`-labelled test input; or
  - a declared D5 producer. None exists yet (I08), so the list is empty.

  Any other source refuses.
- Optional `representation` (amendment of 4 October 2026). It is None, or one entry per point: None (one piece's
  own column), or `('fv-cell-mean', sorted contributing cohort names)` (D-P2 below).
  - When given, it is recorded and bound into `port_id`.
  - An all-None tuple is normalised to None, so one value has one identity.
  - A P1 without cell means keeps its earlier record.
- Reference mass and effective load are derived and reported separately.
- The GPE kernel keeps its refusals: an anomaly above 0.1, negative mantle fill, rock lighter than water.

**P2 strength state.**
- `temperature_k`.
- `lithostatic_pressure_pa`, from the same `I01_GPE` column representation and the same datum as P1, evaluated on
  P2's own support.
- `pore_pressure_pa` (declared).
- Raw `kappa` (dimensionless, transported, never filtered).
- `material_id`, `creep_law_id` and `healing_law_id`. The only admitted healing law is the zero-healing selection
  `atlas.i04-healing-none.v1`.

**P2 layout (amendment of 4 October 2026; accepted at coordinator level, Codex to confirm).** I05a codes it as
`integration_properties.strength_port`. P2 is issued with `parameter_id` the I05 moving state's `moving_id`.
- **Support:** the piece support `atlas.i05-piece-support.v1`. It is the ordered (face, cohort) pieces of one I03
  state, bound to its network and material; `support_id` is its digest.
- **Per piece**, sublayers bottom to top, with offsets as P1:
  - `thickness_m` and `temperature_k` (the sublayer's finite-volume mean);
  - `vertical_stress_bottom_pa` and `vertical_stress_top_pa`: the lithostatic vertical stress, integrated from zero at
    the column's top with `rho_ref (1 - alpha (T - T_ref))` and the datum's gravity. It is not a mean pressure; the
    consumer applies its own closure;
  - `pore_pressure_pa`, declared;
  - `material_id` and `creep_law_id`, declared;
  - raw `kappa`, at each sublayer's material point.
- **P6 support.** P6 increments are given on the piece support of the interval's **endpoint** state, one per endpoint
  piece and sublayer. In Part A, P2 is issued on the pieces of the moving state at the interval's start, its
  `piece_support_id`. The two supports differ whenever plates move or the mesh changes, and the consumer maps from the
  P2 support through the step's rows (wording corrected 4 October 2026, review basal-06).
- **Coupled route (I04b amendment).** P2 (and P1) are issued at the candidate endpoint `E^k` of each outer iterate.
  The header names the interval's parent `S0` as `parent_state_id`, carries the commit interval with
  `endpoint_s = end_s`, and binds `E^k` through its `network_id`, its piece `support_id` and `parameter_id = moving_id`
  (`integration_properties._endpoint` admits it: `endpoint_s == interval[3]` equals the state's time and
  `interval[1]` its step). P2 and P6 then share `E^k`'s piece support, and no row mapping is needed.
- **Refusals:**
  - `missing value`: a missing pore pressure, creep law or healing law;
  - `unsupported`: another healing law;
  - `stale identity` or `incompatible support`: as for P1.

**P3 rigidity.**
- Exactly the `ElasticCore` fields: `material`, `basis`, `depth_reference = rock_surface`, `top_depth_m`,
  `bottom_depth_m`, `young_pa`, `poisson`.
- One horizontally constant core per declaration. Lateral variation refuses `REFUSED_UNSUPPORTED_CORE`.
- `b <= min H` is re-checked against the P1 columns.
- `Te`, `D` and `c` are never accepted as inputs.

**P5 motion.**
- **Coupled P5 (I04b amendment, ruling P6).** Issued by the private `integration_feedback._motion_port`: trial
  values (residual None) advance the outer iterates in memory, and the committed value is issued only from a
  converged interval (`_finish`); no public issuer takes a raw omega. Header: `parent_state_id = S0`; `network_id`
  and per-plate `support_id` are S0's (the plates being rotated); `interval` is the commit interval; `endpoint_s =
  interval[3]`; `parameter_id` = sha256 of (forcing identity, D2 declaration identity). Value: the applied
  `omega^k` (the rotation that advanced I03), `balance_id` = the endpoint balance at `E^k` (which gives
  `omega^(k+1)`), the recorded `coupling_residual = max|omega^(k+1) - omega^k| / max|omega| <= 1e-8` and the label
  "implicit endpoint evaluation (backward Euler, first order in time)…".
  The Part A rule (header equals the balance's parent, network and support; omega is the balance's omega) cannot hold
  here, so the coupled P5 is verified on reopen by replay (section 4). `coupling_residual` is recorded only when not
  None, so Part A P5 identities are unchanged.
- `omega_rad_s` (rad/s) per plate, in the network's axes.
- `frame_id` and the D1 `balance_id`.
- The evaluation label "explicit, single evaluation at the start of the interval; no temporal-accuracy or convergence
  claim".
- **Binding.** The header must match the balance it carries, including the datum (none exactly when the balance used
  none). The fields checked are:
  - parent state;
  - interval;
  - network;
  - per-plate support;
  - frame;
  - forcing.
- **Rotations for I03** are taken from the P5 value, so the stage duration is the P5 interval's.
- Rigid material velocity is `omega × r`.

**P6 mechanical increment.**
- `kappa_increment` (dimensionless): the change of raw `kappa` over the interval, from `kappa_dot = 2 e_p`
  (`I01_WEAKENING` §7 engineering convention).
- Plastic and creep rates (1/s) as diagnostics.
- This is an amendment to the brief's P6 row, which named a rate.
- **Type (I04b).** `MechanicalIncrement`: `pieces` and `offsets` (the endpoint piece support, sublayers bottom to top
  as P2), `kappa_increment` and its per-sublayer `bound`, with `increments()` returning `((face, cohort), values top
  down)` in the I05 `MovingAdvance` order. The bound is the D-P1 check made per piece and sublayer: `0 <= dkappa <=
  sum over crossings (dy L_e / A) 2 dt e_k (1 + 2e-11 + 4 eps)`, `e_k` the belt cell's invariant and `2e-11` the
  kernel's rate tolerance (ruling B5(1)). Its keys are post-split (sub-cohorts named by the pure function
  `integration_feedback.history_reference(cohort, increment, interval)`); the outer convergence compares increments on
  pass-1 keys `(face, parent cohort)`.

**P7 dissipation.**
- Interval-integrated creep and plastic energy (J/m³), and basal and external drag energy (J/m², per face), reported
  separately.
- Alternatively, the interval-mean power, defined as that integral divided by `end_s − start_s`.
- **Type (I04b).** `Dissipation`: per endpoint piece and sublayer `creep_energy_j_m3` and `plastic_energy_j_m3`, with
  `heat_rule = atlas.i04-dissipation-not-heated.v1` (v1 converts no dissipation to heat; IN-05). The driving record
  reports, per piece, the omitted energy's pointwise adiabatic bound and the interval's maximum, beside I05's lateral
  allowance when lateral heat is omitted; `integration_feedback.omission_labels` labels the temperatures of any later
  state (ruling P4). The per-edge belt
  power (W/m) is a D1/P9 balance diagnostic, not a P7 field, because P7's support is material points (ruling B5).

**P8 force-driven sides.** Side velocities `v_L, v_R >= 0` (m/s) from the D1 balance, for admitted open-base strips.
Not issued in v1 (I04b): no open-base strip is admitted.

**P9 boundary reaction (I04b amendment, ruling P3).** The work-conjugate reaction of each reduced-belt edge, for a
regional replacement (I07) or the final coupled solve (I09).
- On the P1 trace support, per edge: `velocity_jump_m_s` (`v_R - v_L` at the midpoint), `traction_left_n_m` (the line
  traction on the left plate; the right plate takes the opposite), `edge_length_m`, and an `owned` flag per edge
  (exclusive ownership: an edge is owned by a belt, an interface `k` or a regional reaction, never two).
- `power_w() = sum f.dv L` over owned edges, the belt's dissipation; no sign is imposed on regional replacements.
- **Part A record change (disclosed).** Ruling P3 moves regional-reaction work out of `driving_w` onto its own
  `regional_reaction_w` line. `balance_id` and `forcing_id` are unchanged (power is outside the digest), but a Part A
  balance with regional reactions now records a different `power` dict than at I04a.
- `torques(...)` gives `R m x f L` on the left plate and the opposite on the right, the D1 belt term's own midpoint
  quadrature, so tractions returned here enter D1 as exactly these torques. The swap control checks `omega_swap =
  omega* - M^-1 r(omega*)` to `1e-11`; regional-reaction work is reported on its own power line.

Part A codes P1 and P5 (`Columns`, `TraceSupport`, `PlateMotion`); I04b codes P6, P7 and P9 and the coupled P5. The
other rows are fixed here, so that I05 and later stages code against one record. **Amendment noted:** the I05 and
I08 briefs describe P3 as an I05 product. This record makes it a declared input that I05 only carries.

## 3. Decisions the record fixes

### D-P1. Which stage integrates `kappa`

The contract assigns the update to the "D2/I05 material-following update". The I01 column route integrates history
inside its own evolution, and I05 transports history without constitutive updates. This record decides:

1. **The D2 response integrates** `d kappa/dt = 2 e_p - h(T) kappa` within the interval, together with the strength
   it controls, as the I01 column route does within its own steps.
2. **P6 returns the increment**, and P7 returns the energy from that same integration.
3. **I05 commits the increment once** to the transported raw `kappa` at the endpoint. That is the material-following
   update. I05 never filters it.

The rate depends on strength, which depends on `kappa`. Integrating across a lagged port would split a stiff
feedback.

**Conditions:**
- **Healing.** `h = 0` is an explicitly declared IN-04 selection (`atlas.i04-healing-none.v1`), because
  `I01_WEAKENING.md` refuses healing.
  - A missing `healing_law_id` refuses `missing value` and never defaults.
  - Any other law refuses `unsupported`.
- **Exactly one mechanical owner per support integrates `kappa`.** That is I04 D2 for the reduced belt, or I07 where
  a regional replacement owns the support, never both. This is recorded against the I05 brief's wording that "I07
  owns constitutive updates".
- **The increment is checked:** `0 <= increment <= 2 ∫ e dt`, with `e` the total equivalent strain rate.

### D-P2. Mapping I04 supports to I05 material points

- **Area terms** use I03 faces: the measured area and closed-form second moments of each face. A material-dependent
  area coefficient, such as basal drag `D`, is supplied per face. Part A supplies per-plate scenario values.
- **GPE uses only plate-boundary traces.** The GPE torque on a rigid plate is a boundary integral
  ([I04_CAUSAL_START.md, R4-2](I04_CAUSAL_START.md#r4-2-gpe-on-the-sphere)). So P1 is evaluated at each boundary
  edge midpoint, on both sides, for the material occupying that point.

**Part A.**
- The starting-family P1 producer resolves trace points from its continuous polygons at the initial state, for the
  shared datum.
- Authored controls use boundary faces that each hold a single cohort.

**After any I03 advance, for a P1 producer that reads an I03 state (I05).** It must refuse `unresolved column` for a
trace point whose adjacent face holds several cohort pieces whose material at that point it cannot place.
- This is a rule for that producer. It is **not coded in Part A**, which has no such producer.
- An area-weighted average of per-piece `U` is not a default.

**P1 representation `fv-cell-mean` (amendment of 4 October 2026, coordinator ruling).** For one case only, this
supersedes "columns are never averaged". I05's `moving_columns` codes it.
- **When it applies.** A face holding several pieces is admitted when every piece has bitwise-equal layer structure:
  the same material, phase, `rho_ref`, `alpha` and `cp` per sublayer, and identical tuples of sublayer thicknesses
  and depths (not equal within a tolerance).
- **The column.** Per sublayer, `T` is the caloric inverse of the exact `ΣH_i / Σ(rho t A)_i`, rounded once: the
  enthalpy-consistent first-order finite-volume cell average, which conserves heat.
- **The record.** Each point carries a representation entry (`Columns.representation`): None for one piece's own
  column, or `('fv-cell-mean', sorted contributing cohorts)`. The entry is bound into `port_id`. An all-None tuple is
  normalised to None, so a P1 without mixed faces keeps its old record and identity.
- **What it does not touch.** Histories and kappa are not averaged; P2 and P6 stay per piece.
- **Refusals.** A different layer structure still refuses `unresolved column`.
- **Controls** (predeclared):
  - identical pieces give the single-piece column bit for bit;
  - a two-piece face gives the exact enthalpy mean. This pins the mean only to rounding: under bitwise-equal
    structure `ΣH/Σ(rho t A)` equals the area-weighted temperature mean in real arithmetic, so on this fixture a
    float or area-weighted mean rounds to the same bits (review P1-NOTE-2);
  - a mismatch refuses.
  - Each piece of a mixed face is still guarded.
- **Consumers.** Recording the trace indices that used `fv-cell-mean` on the consumer side was **I04b's
  obligation**, and is discharged: a balance with GPE records `cell_mean_points` (the points whose representation
  entry is not None, from the consumed P1) beside `columns_id`; the field is absent when empty, so other balances keep
  their identities, and it is replay-checked with the balance on reopen. A focused single-evaluation test of the
  coupled balance on the I05a `s00-merged` fixture discharges it (ruling P7(2)).

**Family datum for I05's P1 and P2 (4 October 2026).** If the moving state's I03 cohorts come from a starting family,
I04a's v1 gate applies: the datum must be exactly 3300 kg/m³ at 293.15 K, else `stale identity` (`datum_id`).

**The lasting fix is not I05's:**
- it belongs to I04.1, through faces that conform to material contacts, or to an I03 amendment that adds sub-face
  geometry. Lagrangian material-point histories are the third option;
- it is flagged as a probable blocker for runs of more than one interval, and is the main open owner decision. Under
  relative motion, history splits make pieces per face grow quadratically (I05 §4). I04b controls report pieces per
  face for every interval.

**P4 (ruling of 4 October 2026).** R-6, the belt state, is deferred to I05b/I07. P4 stays reserved and refuses
`unsupported`. I04.3 must not depend on it.

### D-P3. Coupling at the common endpoint

- **Part A is an explicit start-of-interval evaluation.** `endpoint_s = start_s`, at the network's step and time: P1
  is evaluated at the parent state, D1 is solved there, and `omega` is held constant over the interval.
- **Label.** Every Part A balance and P5 value carries the label "explicit, single evaluation at the start of the
  interval; no temporal-accuracy or convergence claim". That label cites the contract's unmet split-error and
  convergence requirement (§2), not a breach of CM-05. Any chaining of intervals in Part A carries the same label.
- **The coupled route (I04b, decided by the coordinator's rulings C1-C3 of 4 October 2026).** Route
  `d1d2_endpoint_fixed_point_v1`: implicit at the endpoint (backward Euler, first order). Each outer iterate advances
  I03/I05 from S0 with `omega^k` and `dkappa^k`, evaluates P1/P2 at the candidate endpoint `E^k` and solves D1 with
  the belts there, giving `omega^(k+1)`, `dkappa^(k+1)` (P6) and P7 from the same integration. The interval converges
  when the relative changes fall to `1e-8` (cap 40, the regional-strength precedent); it refuses when the change grows
  twice running after the second iterate, or when the last contraction is `>= 1`
  ([I04_CAUSAL_START.md, R4-7](I04_CAUSAL_START.md#r4-7-first-feedback-coupling)).
- **Non-convergence.** A nonconverged interval refuses without ageing rock or spending accounts; nothing is
  committed.
- **I09** owns the final multi-region convergence.

## 4. Persistence and later requirements

- **D1 provenance after reopen (implemented by I04b, ruling P1).** A D1-driven interval enters I03 as an ordinary
  `prescribed_history_v1` motion; it is never labelled `coupled_generated_candidate_v1`.
  - The coupled interval's `MovingAdvance` carries an optional `driving` record (canonical JSON, Python floats only,
    no wall-clock or cost data, emitted only when present), committed with the step in the same I02 transaction.
  - **Inheritance from the parent commit (round 1).** Every iterate seed (the parent interval's omega, its labels,
    cumulative belt strain and heat-omission bound) comes from the parent interval's own record, never a caller's:
    `integration_feedback.step(ledger, inputs)` reads the head commit's record, replays it (or accepts the Verified
    value `commit` returned for that head) and inherits from it. The record carries the parent record's digest.
  - **At commit (ruling P2(e)).** `integration_feedback.commit(ledger, coupled)` binds the interval to the ledger's
    next interval field by field (ledger `(start_s, end_s, start_step, end_step)` against P5 `(interval[2],
    interval[3], interval[0], interval[1])`) and requires the record to inherit from the head's own record, before
    writing. On every commit path, including the plain one, I05 (`integration_material._bound_driving`) checks the
    record's parent state, endpoint state, motion and interval against the step being committed, field by field.
  - **Unbroken history (v1).** A non-coupled interval after a coupled one, and any committed I03 topology event,
    refuse the coupled route and the reader by name (`chain`, `events`): E_b and the labels are not carried across
    them, and there is no lineage mapping for E_b.
  - **Replay.** `integration_feedback.find_driving` returns a record labelled "recorded, not replayed". Only
    `integration_feedback.verify_driving` makes it D1 provenance: it verifies the parent commit's record first, then
    solves the whole interval again from the parent commit's restored states (forcing and declaration from the record,
    supplies and sinks from the committed motion, births and conduction from the committed advance), inheriting from
    the verified parent. The replayed record must equal the stored one in every field (labels, cumulative strain, heat,
    coupling report, start balance, P5, P6 and its bound, the P7/P9 identities); the replayed advance must equal the
    committed one, so the committed increments are the replayed D2 products and the split names are reproduced; and
    the replayed motion and endpoint states must be the committed ones. A forged or altered record, or one that
    dropped its inheritance, refuses `stale identity` naming the first differing field; a malformed record refuses
    `missing value`. Each record is verified once and cached by commit key: a chain of n intervals costs n coupled
    solves with one shared cache (n(n+1)/2 if every commit is verified with a fresh one). Nothing is persisted, so on
    reopen the first `step` replays the coupled history from a cold cache, one solve per coupled interval. A cache hit
    is accepted only for an issued verification of the very record and endpoint stored at that commit (the key is
    positional and a same-identity ledger shares it) and only when the chain behind it is this ledger's (the parent
    commit validated the same way, and the record's parent digest equal to that of the parent's stored record); only
    Verified values issued by `verify_driving` or `commit` in this process are trusted. A declared mesh replacement is
    not replayable in v1.
- **Advancing I03 from a P5 value (implemented by I04b, ruling P2).** `integration_feedback.advance_from_motion`
  checks `state.state_id == P5.parent_state_id`, `state.step == interval[0]`, `state.time_s == interval[2]`,
  `end_time_s == interval[3]`, the frame, the plate IDs, and P5's `network_id` and per-plate `support_id`; rotations
  come only from P5. Its template admits only supplies, sinks and a mesh: rotations, events, regional returns,
  junction paths and history splits refuse by name (splits come only from I05's `split_for_increments`).
- **Per-piece `kappa`.** I03 keys intensive content by cohort, but D2 increments vary within a cohort. When two
  pieces of one cohort merge into one receiver, their `kappa` can be neither averaged nor kept.
  - **Resolved by I05a** (ruling I05-2): one raw history per cohort. Divergent increments are committed only after
    the I03 history split of the same interval (`I03_SPHERICAL_NETWORK.md` §7).
  - The flow is two-pass: advance without splits; take the increments per endpoint piece; split; advance again;
    commit once per sub-cohort.
  - Without the split, the update refuses `history divergence`.

## 5. What the record does not do

- It does not move material, create inventory or replace the I03↔I05 transport port.
- It does not make P3 an I05 product. Thermal thickness cannot manufacture an elastic core.
- It does not admit a healing law or a pore-pressure evolution law.
- It does not admit water from any source other than a `test:`-labelled test input or a declared D5 producer (none
  exists yet).
- It does not decide I05's transport or constitutive content. I05 writes those against this record.
