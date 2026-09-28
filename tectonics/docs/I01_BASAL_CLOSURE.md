# I01: basal closure of the regional rifting box (MC-04)

**27 September 2026. WORKING NON-CANON. One bounded I01 choice with analytical account
controls and one exact analytical mechanical control; not I05/I07 implementation, a numerical
Stokes or transport solution, melting, a resolved neck, breakup or physical acceptance.** This
specifies the MC-04 prerequisite named in the
[closure matrix](I01_CLOSURE_MATRIX.md#62-choices-that-stay-open): an explicit mechanical base
condition, the incoming and outgoing material and heat, and the moving-domain balance with a
free surface. It does not implement a separation certificate or approve a separation
mechanism; MC-01 and its elastic-memory choice stay open. The
[case](../cases/i01_basal_closure_v1.json), [tool](../tools/check_i01_basal_closure.py) and
[focused tests](../tests/test_i01_basal_closure.py) are new. The contract, transitions, breakup,
finite-strain and matrix records are read-only and unchanged. The tool imports no retained tool
or native module; it reads three retained cases as JSON. Measured results stay outside this
source-bound document (section 10).

## 1. What crosses the bottom, in plain language

The accepted [finite-strain strip](I01_FINITE_STRAIN.md) is closed: its rock stretches and
thins, and its base rises with the rock while being held at 1613 K. Nothing enters. A real
rift is different. As the lithosphere thins, hot mantle rises into the space beneath it, and
ASPECT's continental-extension example states that without an upwelling asthenosphere its box
cannot represent breakup.

The selected closure opens the bottom of the regional rifting box:

- **What enters:** named **asthenosphere**, never new crust. It enters through a fixed base
  150 km down, below the 100 km lithosphere, at a prescribed and uniform upward speed. It
  carries its actual temperature (1613 K), its composition and no deformation history.
- **What leaves:** rock leaves through the sides at its own actual temperature and
  composition, which are never reset to a boundary value. If flow ever reverses at the base,
  rock leaves there too, with the same rule.
- **What moves:** the top is a free surface. No rock crosses it, but it rises and falls, so
  the box's volume can change.

That changes every balance. Constant volume does not mean constant mass: dense mantle replaces
lighter crust that leaves through the sides. Basal inflow equals side outflow only when the
surface's net movement is zero. Heat carried by moving rock, heat conducted through each
boundary and mechanical work are booked separately, so nothing is counted twice.

## 2. The selection and the evidence for it

**Selected law: `atlas.basal-inflow-closure.v1`.** It is the component structure of ASPECT's
continental-extension boundary settings, moved below an explicit asthenosphere layer:

| Route | What it prescribes | Evidence read | Decision |
| --- | --- | --- | --- |
| Closed strip (retained) | Impermeable material base rising with the rock; fixed 1613 K there | [Finite strain](I01_FINITE_STRAIN.md) | Kept as the admitted closed route, unchanged. It cannot carry inflow or represent breakup |
| ASPECT's own base, at the lithosphere base (100 km) | Uniform normal inflow balancing side outflow; free tangential slip; fixed T and composition | Cookbook page and parameter file | Refused for the separation experiment: the cookbook states this box "will not produce a realistic representation of continental breakup due to the lack of an upwelling asthenosphere layer". Admitted only as the classical I05 passive-upwelling special case and as a control |
| **Selected: the same boundary treatment at the base of an asthenosphere layer** | As above, at z_b = 150 km, in named asthenosphere | Cookbook (treatment and breakup statement); Brune et al. (2014) Methods (asthenosphere below the lithosphere, fixed bottom temperature, robustness tests) | Selected for both consumers |
| Winkler foundation (Brune et al. 2014) | Isostatic equilibrium at the bottom | Brune states it and cites Popov and Sobolev (2008), which was not read | Not specified: its formulation was not read. A comparison arm only after it is read |
| Free-slip impermeable base (Brune's alternative test) | No flow through the base | Brune reports "small differences" | Not specified: the sections read do not state its side-mesh convention or volume balance. With fixed open sides, surface subsidence would have to supply the whole side export |

The support for the selection has three parts:

- **The boundary treatment is documented software practice.** The ASPECT cookbook drives
  extension by side-normal velocities and balances them by uniform basal inflow under a free
  surface. The parameter file fixes exactly which components are prescribed.
- **The asthenosphere layer answers the cookbook's own stated limitation.** Its statement names
  two remedies, an asthenosphere layer or modified basal conditions. Only the first can be
  specified from sources actually read.
- **The depth is within a published breakup-capable setup.** Brune et al. (2014) compute their
  rift in a 150 km deep domain, with asthenosphere below lithosphere variants of 120, 105 and
  90 km: layers of 30–60 km. Their robustness tests varied the domain size and replaced the
  Winkler base by free slip "despite small differences". The retained 100 km lithosphere over
  a 150 km base gives a 50 km layer, inside that range.

The depth remains a declared input whose influence I07 must report (section 11); it is not
tuned here.

## 3. The mechanical boundary

**Geometry and signs.** The box is plane strain, per metre of strike: width `W`, base depth
`z_b` below the initial surface. `x` points right and `y` up from the base, as in ASPECT's box.
Outward unit normals point out of the domain. A normal velocity `u.n` is positive outward, so
inflow is negative. Boundary segments are traversed counter-clockwise.

| Segment | Normal component | Tangential component | Mesh motion | Temperature | Composition |
| --- | --- | --- | --- | --- | --- |
| Base (y = 0) | Velocity prescribed: `u.n = -u_in`, uniform. The normal traction is the solved reaction | Traction prescribed: zero. The tangential velocity is solved | Fixed, `w = 0` | Fixed `T_b` on inflow and impermeable parts; zero conductive flux on outflow parts | Fixed (asthenosphere, zero raw plastic history) on inflow parts only |
| Sides (x = 0, W) | Velocity prescribed: outward `v_L, v_R >= 0`. The normal traction is the solved reaction | Traction prescribed: zero | Tangential only: `w.n = 0` | Insulating | Natural: the actual state leaves |
| Top | Traction prescribed: zero | Traction prescribed: zero | Free surface: `w.n = u.n` | Fixed `T_s = 273 K` | None crosses |

- **One condition per component.** Each component carries exactly one prescribed quantity,
  either velocity or traction; the other is the solved reaction. ASPECT describes a
  prescribed-velocity boundary as one "where unknown external forces act to prescribe a
  particular velocity", and a traction boundary as one where outside forces impose a set
  traction. Prescribing both on one component is refused. The ASPECT pages read do not
  themselves state that rule; it is the usual pairing of boundary data for viscous flow, adopted
  here as Atlas's rule. Counting components is a necessary check only. It does not prove that
  the boundary-value problem is well posed, and no control here claims that. The exact
  pure-shear control (section 8) shows only that, in a homogeneous Newtonian box, one flow
  satisfies every selected condition.
- **Pressure datum.** The parameter file sets `Pressure normalization = no`. The traction-free
  surface fixes the constant pressure mode, so the pressure is absolute and has no nullspace.
  ASPECT's global parameters note that "in many cases the pressure is only determined by the
  model up to a constant"; that happens when no boundary carries a normal traction.
- **Compatibility.** For incompressible flow the boundary integral of `u.n` must vanish.
  Without a traction boundary, the prescribed normal fluxes must therefore sum to zero, and the
  pressure is then undetermined up to a constant. The selected law avoids both: the free
  surface takes up any net flux as a change of domain volume. A closed lid is refused, with
  `REFUSED_INCOMPATIBLE_NORMAL_FLUX` or `REFUSED_PRESSURE_NULLSPACE`.
- **No local field from a total.** The base velocity is uniform by declaration, as in the
  cookbook's function. A total basal flux alone does not define the local velocity field and is
  refused.

**Prescribed reference configuration.** The cookbook's `Function expression` is
`if (x < w/2, -v, v) ; v*2*d/w` with `v = 0.0025` m/yr, `d = 100 km` and `w = 200 km`. The
selected reference applies the same rule at the deeper base:

```text
u_in = (v_L + v_R) z_b / W      = 2 (0.25 cm/yr)(150 km)/(200 km) = 0.375 cm/yr
```

ASPECT's year is 365.2425 days (31,556,952 s), because the parameter file sets
`Use years instead of seconds = true`. Its m/yr inputs are converted with that year and no
other.

**Eventual force-driven coupling (not implemented here).** The side velocities would come from
the D1 force balance each interval (I04/I09), keeping the same component structure and basal
rule. The side reactions would then be the D1 regional reactions. The kinematic reference is a
test configuration; it is not generated motion.

**External force and work ownership.** Nothing in this list is added to heat except through
the dissipation line.

| Term | Owner | Booked |
| --- | --- | --- |
| Side normal reaction × prescribed side velocity | Exterior plates: the prescribed reference now; D1 regional reaction later | Mechanical ledger only |
| Side and base tangential traction | None: zero by the law | No work |
| Basal normal reaction × inflow, including the flow work `P/rho` of entering rock | Exterior asthenosphere account | Mechanical ledger only, never heat |
| Free-surface traction | None: traction-free. Water or sediment loads are separately owned D5/I08 exchanges | No work |
| D1 basal drag on the resolved footprint | Replaced by the resolved asthenosphere | Not applied a second time (contract D1) |
| Gravity | D1/D5 GPE ledger | Mechanical ledger |
| Interior dissipation | D2 rheology; D4 heat fraction (IN-05) | Mechanical sink; heat once as `f x dissipation` |
| Elastic storage | Open with the MC-01 elastic-memory choice | Not in this viscoplastic configuration |

## 4. Incoming and outgoing material and heat

**Incoming state.** The incoming state is declared with provenance and checked against the
retained cases at run time:

- **Material.** Named asthenosphere, with role `asthenosphere`. The inflow is never crust or
  instant ocean crust. Its Boussinesq reference density is 3300 kg/m³ and its heat capacity
  is 750 J/kg/K: the cookbook's background material, equal to the retained mantle and thermal
  layers.
- **Composition.** Declared as named components with mass fractions.
- **History and phase.** It enters with zero raw plastic history, which is the cookbook's
  inflow composition, where plastic strain is zero at the base. It is solid.
- **Records.** Each inflow cohort carries its entry interval and source account.
- **Constitutive law.** The incoming rock's rheology is an IN-04 input of the resolved neck
  and is not selected here. The cookbook uses dry olivine for its background, and Brune uses
  wet olivine for the asthenosphere.

The cookbook labels its inflow `mantle_lithosphere`, because its box contains no asthenosphere.
Atlas names it asthenosphere, and keeps the initial asthenosphere layer and each inflow interval
as separate cohorts. Otherwise the mantle-lithosphere connectivity diagnostic that MC-01 needs
could never detect the loss of lithospheric mantle.

**Actual temperature only.** `T_b` is the actual boundary temperature, 1613 K: the retained
strip base and the cookbook's bottom value. The selected energy law is ASPECT's Boussinesq
formulation, and the cookbook's heating model contains compositional heating only, with no
adiabatic term. In that law a rising parcel does not cool adiabatically, so no conversion from
a potential temperature is admitted. A supplied potential temperature is refused
(`REFUSED_POTENTIAL_TEMPERATURE`); it is never equated with `T_b`. The melt route's `Tp`
provenance (MC-03) must supply its own conversion. The initial asthenosphere layer is
isothermal at `T_b`, as Brune's asthenosphere is isothermal at 1300 °C below the lithosphere.

**One caloric datum.** Every stream, cohort, source and receiver books heat as

```text
e = Cp (T - T_ref)      [J/kg],   T_ref = 273 K
```

This is the D4 contract's `rho_reference Cp (T - T_reference)` per unit mass. For
incompressible material the specific enthalpy is `h = e + P/rho`. The extra `P/rho` is flow
work, and the boundary traction power already carries it in the mechanical ledger, so the
thermal account advects `e`, not `h`. At the base the difference is large: `P_b/rho` =
4.66 GPa / 3300 kg/m³ ≈ 1.41 MJ/kg, against `e_b` = 1.005 MJ/kg. Booking `h` as heat as well
as the work would more than double the advected heat. A source recorded with `h` is refused,
and so is any boundary work supplied as a heat source. Changing `T_ref` moves each booked energy
by `m Cp dT`, and the balance changes by exactly `-dT sum(sign m Cp)`. The controls check that
datum invariance; records at a different datum are refused.

**Where temperature and composition are fixed.** ASPECT's `Allow fixed temperature on
outflow boundaries` defaults to true: the fixed value is imposed where material leaves as
well. The documentation cautions that this is reasonable only if diffusion prevents a thin
boundary layer. Atlas adopts the other documented option. Temperature is fixed only on inflow
(and impermeable) parts, and composition only on inflow parts, which is ASPECT's default for
models without melt. Outflow carries the actual outgoing state, with zero conductive flux at an
outflow base. An outgoing temperature must be stated with each outflow and must lie inside the
debited cohort's declared temperature range. After the debit, the rest of the cohort must still
be a mean inside that range. A reset to `T_b` is refused (`REFUSED_OUTFLOW_STATE`).

**Thermal conditions in the accounts.** Each segment's condition follows from its kind, its
mesh motion and its actual flow regime in the interval:

| Segment | Flow regime | Condition | Conductive heat booked |
| --- | --- | --- | --- |
| Free surface | Any, including an owned surface exchange | Fixed `T_s` | Any value: the solved flux |
| Eulerian side (tangential or fixed mesh) | Any | Insulating | Exactly zero |
| Base | Inflow or impermeable | Fixed `T_b` | Any value: the solved flux |
| Base | Outflow | Zero conductive flux | Exactly zero |
| Material-following side of the I05 strip | None crosses | No lateral conduction | Exactly zero |

- **One table.** `propose_interval` derives each segment's regime from that segment's own
  streams. It looks the condition up in the same table that `resolved_prescription` uses, so an
  account cannot declare a condition of its own. A law name carried by the account does not
  bind it to that table.
- **Refusal.** A nonzero term where the table says zero is refused
  (`REFUSED_THERMAL_BOUNDARY_CONDITION`). The proposal reports the condition it applied to each
  segment.
- **Declared routes keep their heat.** An owned surface exchange does not change the fixed
  surface temperature. An inflow or impermeable base still carries its solved conductive heat.
- **The I05 strip's sides.** The strip supplies no lateral conduction
  ([finite strain](I01_FINITE_STRAIN.md), section 3), so no lateral heat can be booked through its
  material-following sides. The MC-06 criterion in the
  [closure matrix](I01_CLOSURE_MATRIX.md) concerns the error of omitting lateral conduction.
  Booking such heat would need the coupled I05 route.
- **Exact zero.** Zero means exactly zero in these analytical accounts. Near-zero diagnostic
  values from a resolved run need the I07 tolerance that is still to be declared (section 11).

**Solid at the boundary (documented hand check, not a gate).** Brune et al. quote the dry
solidus `T_sol = -5.1 p² + 132.9 p + 1085.7` °C, with `p` in GPa. The same Katz et al. (2003)
coefficients appear in the retained melting tool.

- **At the lithosphere base.** The retained densities give 3.0411 GPa at 100 km. There the
  solidus is 1715.85 K, 102.8 K above `T_b`.
- **At the inflow base.** The base at 150 km is at 4.66 GPa, outside the 0–3.5 GPa range
  recorded for that law. The inflow is solid there by declaration, not by a checked law.
- **In the interior (a limitation).** Rock at 1613 K that rises without adiabatic cooling
  crosses that solidus near 2.08 GPa. A resolved run reaching such states needs MC-03 or must
  refuse. This closure supplies no melting.

## 5. Moving-control-volume balances

Per metre of strike, and for each boundary segment `s`, the tool uses the following interval
integrals:

- `q_s` [m²] is the integral over the interval of `(u - w).n dl`: the material crossing the
  segment. It is positive outward.
- `a_s` [m²] is the integral of `w.n dl`: the volume the moving segment sweeps.

Material velocity `u` and mesh velocity `w` are distinct:

```text
dV            = sum_s a_s                                   boundary motion
0             = sum_s integral u.n dl dt                     incompressible material
=> dV         = - sum_s q_s  =  inflow - outflow
dM_j          = - sum_s rho_s c_sj q_s                       per component, reference densities
dE            = - sum_s rho_s e_s q_s + sum_s C_s + R + f D   caloric, datum T_ref
ledger          sum_s W_s + G = D                             Stokes: no inertia, no elastic storage
```

The heat terms are separate inputs:

- `C_s` is the conductive heat into the domain through segment `s`. It is always a separate term
  from the advected heat.
- `R` is radiogenic heat.
- `f D` is the declared heat fraction of the interior dissipation.

`W_s` is the boundary work through each segment and appears only in the ledger. For a fixed
segment with uniform normal stress and zero tangential traction, `W_s = sigma_nn q_s`. At a
lithostatic base this is `P_b V_in`. The ledger is optional; when it is supplied, it must close,
and the free surface must do no work. The manufactured box accounts of section 8 set their
gravity term to close this ledger, so they cannot test its signs. The pure-shear control
supplies every term independently.

**Approximation declared.** Every material is incompressible, with a constant Boussinesq
reference density. This is ASPECT's selected formulation. Mass is density times volume for each
material, and thermal buoyancy does not change the reference inventory (contract D4). No
compressible mass or volume closure is claimed.

**Inventory bound to geometry.** Under those constant reference densities the cohorts must fill
the domain:

```text
sum_c m_c / rho_c                                 = V_start      start cohorts
sum_c (m_c - out_c) / rho_c + sum_k in_k / rho_k  = V_end        after the booked transfers
```

Each equality must hold within the round-off gate of its gross scale. A mismatch is refused
(`REFUSED_INVENTORY_VOLUME_MISMATCH`); no mass or volume is rescaled. Doubling every cohort's mass
and energy in an unchanged box is therefore refused, although each cohort alone still holds a
valid mean state. The end equality follows from the start equality and the two volume checks,
because each transfer's mass is its volume times its own density. It is still recomputed from
the booked masses and recorded with the proposal, because it is the end state that I02 would
commit. Finite-source exhaustion remains an exact comparison.

**Mesh conventions.** The segment types differ as follows:

- **Fixed base:** `w = 0`, so `a = 0`.
- **Sides with tangential mesh motion:** `w.n = 0`, so again `a = 0`.
- **Free surface:** `w.n = u.n`, so `q = 0` but `a` is generally nonzero. An impermeable
  material surface need not be stationary.
- **Material-following sides (the I05 strip):** `w = u`, so `q = 0` and the sides sweep volume.

A supplied balance is checked twice: the domain volume change against the summed swept volume,
and against the net material inflow. Each check uses its own gross scale. A mismatch is refused
(`REFUSED_INCOMPATIBLE_VOLUME_BALANCE`). No flux or surface position is corrected afterwards.

**Why basal inflow equals side outflow only in a special case.** The controls demonstrate
four ways the equality fails or depends on convention:

1. **A moving surface.** Any imbalance moves the free surface. With basal inflow at 0.8 of the
   balanced value, the surface subsides uniformly while no rock crosses it.
2. **ASPECT's own settings.** The parameter file's tangential side mesh lets each side's height
   follow the free-surface corner, while its basal inflow stays `2 v d`. The domain volume
   therefore changes at `-v (eta_L + eta_R)`. A flat corner offset relaxes as
   `eta0 exp(-2 v t / W)`, with a time scale of `W/(2v)`, 40 Myr for the cookbook box. This is
   an Atlas derivation from the settings read, not an ASPECT output.
3. **Mesh conventions for one flow.** Take one pure-shear flow in two conventions.
   - A fixed box of width `w0` has basal inflow equal to side outflow, `w0 z_b ln(lam1/lam0)`.
   - Material-following sides (the strip) have no side outflow at all. Their basal inflow is
     `w0 z_b (lam1 - lam0)`, which equals the volume growth.
4. **Free-surface projection.** ASPECT's documentation says "Mass conservation requires that the
   mesh velocity is in the normal direction of the surface". Its vertical projection has
   "slightly poorer mass conservation of the domain".
   - On a sloping surface, a mesh that follows only the vertical material velocity lets rock
     cross at `-slope u_x W`.
   - Such crossing is refused unless a named surface-process exchange owns it
     (`REFUSED_UNOWNED_SURFACE_CROSSING`).
   - The cookbook's surface diffusion is documented as a stabilisation or as mimicking
     erosion and deposition. It is therefore not part of this law. If I07 uses it, it is
     booked as that exchange.

## 6. The two consumer interfaces

**I07 resolved boundary interface: `resolved_prescription(configuration)`.** It returns the
table of section 3 for a supplied configuration: the components, the mesh convention, the
inflow-only Dirichlet data, the pressure datum, the work ownership and the list of solver
outputs required. Its status is `BOUNDARY_PRESCRIPTION_ONLY`, and it solves nothing. The
resolved run must return, per interval:

- the reaction tractions and the boundary work per segment;
- the free-surface swept volume;
- the crossing volume per segment and cohort, with the actual outgoing temperatures;
- the conductive heat per segment;
- the interior dissipation and gravity work;
- the domain volume at both ends.

`propose_interval` books those outputs, and `diagnose_endpoint` compares the solver's end state
with the booking:

- **The proposal must come from this account.** `diagnose_endpoint` recomputes the proposal
  from the account and compares every field. This small function is pure, so a genuine proposal
  is reproduced exactly.
  - A foreign parent or interval is refused, as are an account edited after booking and edited
    deltas (`REFUSED_FOREIGN_PROPOSAL`). This holds even when the status, law, parent and
    interval fields still match.
  - The proposal records the start inventory it was booked against, so the comparison covers
    the start masses and energies too.
  - No digest is used; a claimed identity never stands in for the contents. No persistence is
    implied.
- **Geometry.** The supplied end volume must equal the booked end volume. The supplied cohort
  masses must fill it at their reference densities.
- **Mass and heat.** Per-cohort mass must match. Only the total caloric energy is compared,
  because conduction moves heat between cohorts.

**I05 open-domain and cohort interface: `strip_open_base`.** The accepted affine strip deforms
in pure shear about its stationary surface, over the full depth to a fixed base
`z_b >= h0`, and its sides follow the material:

```text
V(lam)            = w0 lam z_b
base volume       = w0 z_b |lam1 - lam0|        inflow while stretching, outflow while shortening
each side sweeps  = z_b w0 (lam1 - lam0)/2      no side crossing
inflow at t1      : depths [z_b lam0/lam1, z_b], width w0 lam1
lithosphere base  = h0/lam1
admitted only if  : z_b >= h0,  z_b >= h0/lam0  and  z_b >= h0/lam1
```

With `z_b = h0` this is McKenzie's uniform stretching with the base held at `T1` at fixed depth
by passive upwelling. That is how Angevine, Heller and Paola (1990) present it, as recorded in
the [finite-strain sources](I01_FINITE_STRAIN.md#9-sources).

- **The cohort record.** Each inflow interval becomes one named asthenosphere cohort. It holds
  its mass, components, caloric energy at `T_b`, zero raw plastic history, entry interval,
  source and segment. I05 owns its placement, its conduction afterwards, and converting its own
  temperature representation to absolute `T` before booking.
- **Shortening.** When the strip shortens, the adapter reports the outgoing volume. I05 supplies
  the actual state of the rock crossing the base.
- **The lithosphere stays above the base.** Stretches below 1 thicken the lithosphere to
  `h0/lam`. At each endpoint that base must lie at or above the fixed base. Otherwise lithosphere
  would have to leave through the base, a route this adapter does not provide.
  - It is refused (`REFUSED_NO_ASTHENOSPHERE_LAYER`) and never exported as asthenosphere. For
    example, `h0` = 100 km over a 150 km base at `lam` = 0.6 would put the lithosphere base at
    166.7 km.
  - Equality is admitted. From the reference state, shortening to it exports exactly the
    asthenosphere layer, `w0 (z_b - h0)`, and no lithosphere. If rounding makes the booked
    export exceed the layer, the exact cohort check refuses it; lithosphere is never exported.
- **A moving surface.** A moving I05 surface (D5 support) must be supplied as a swept volume
  together with the fluxes, for the generic check; this adapter covers only the stationary
  surface.
- **The closed strip is untouched.** It remains the default route, and this adapter refuses it
  (`REFUSED_CLOSED_ROUTE`). Its inventory and its fixed material-base temperature do not change.

**Finite accounts and I02.** `propose_interval` validates everything before it builds anything,
never modifies the caller's account and commits nothing.

- **What it returns.** Status `PROPOSED_NOT_COMMITTED`, evidence `SUPPLIED_ACCOUNTS_ONLY` and
  `stokes_solution` false. The proposed deltas are:
  - source debits, with the remainders;
  - receiver credits per part;
  - domain cohort deltas and new inflow cohorts;
  - component totals;
  - the volume ledger with the start and end inventories, and the caloric and mechanical
    ledgers with each segment's thermal condition.

  It also records the start cohorts it was booked against.
- **Finite sources.** Demands on one finite source are summed jointly and compared exactly, with
  no tolerance. Exhaustion refuses the whole proposal and never clips the stock.
- **Receivers.** Outflow never returns to a finite source, because no mixing law is admitted; it
  goes to a separate named receiver.
- **I02.** Once-only persistence belongs to I02.

## 7. Validity and refusals

**Validity.** The following limits apply:

- plane strain;
- incompressible Boussinesq materials with constant `Cp` per material;
- uniform basal normal velocity per base segment;
- solid inflow of named asthenosphere;
- extension, with outward or zero side velocities;
- temperatures of 273–1613 K, the accepted strip's window;
- strip stretches of 0.6–1.4.

The speed limit of 1e-8 m/s (31.6 cm/yr) is a unit guard: an m/yr value passed as m/s is
refused. It is not a physical bound.

| Refusal | Meaning |
| --- | --- |
| `REFUSED_OVERDETERMINED_COMPONENT` / `UNDERDETERMINED` | Both or neither of velocity and traction on one component |
| `REFUSED_NOT_SELECTED_LAW` | Another component structure, mesh motion or law |
| `REFUSED_INCOMPATIBLE_NORMAL_FLUX` / `PRESSURE_NULLSPACE` | No traction boundary: nonzero net flux, or undetermined pressure |
| `REFUSED_LOCAL_FIELD_UNSPECIFIED` | A total basal flux without a declared distribution |
| `REFUSED_NO_ASTHENOSPHERE_LAYER` | Base at or above the lithosphere base for the separation experiment; for I05, a base above the lithosphere base `h0`, or above `h0/lam` at either endpoint |
| `REFUSED_POTENTIAL_TEMPERATURE` / `MELT_BEARING_INFLOW` / `INCOMING_NOT_ASTHENOSPHERE` | Not the admitted actual, solid asthenosphere state |
| `REFUSED_SIDE_INFLOW` | Side inflow: outside the selected rifting configuration |
| `REFUSED_DATUM_MISMATCH` / `SOURCE_STATE_MISMATCH` | Another caloric datum, or a source energy that is not its declared state (including `h` in place of `e`) |
| `REFUSED_SOURCE_EXHAUSTED` | Joint demand above a finite stock |
| `REFUSED_OUTFLOW_STATE` | Missing, out-of-range or reset outgoing state; outflow into a source; a cohort overdrawn |
| `REFUSED_INCOMPATIBLE_VOLUME_BALANCE` | Geometry, swept volumes and crossings disagree; crossing of a material-following side |
| `REFUSED_INVENTORY_VOLUME_MISMATCH` | Cohort masses at their reference densities do not fill the start or end domain volume |
| `REFUSED_THERMAL_BOUNDARY_CONDITION` | Conductive heat through an insulating side, an outflow base or a material-following strip side |
| `REFUSED_FOREIGN_PROPOSAL` | An endpoint proposal that differs from the one its account books |
| `REFUSED_UNOWNED_SURFACE_CROSSING` | Rock crossing the free surface without a named owner, or entering through it |
| `REFUSED_MECHANICAL_LEDGER` / `THERMAL_SOURCE` | Open ledger, work on the free surface, or boundary work or latent heat offered as heat |
| `REFUSED_CLOSED_ROUTE` / `ENDPOINT_MISMATCH` | Inflow asked of the closed strip; a supplied end state that disagrees with the booking |
| `REFUSED_UNIT` / `OUTSIDE_WINDOW` / `INVALID_INPUT` / `INCOMPATIBLE_RETAINED_CASE` | Unit, window, type, finiteness, sign or field errors; inputs that differ from the retained cases |

## 8. Controls (frozen before execution)

The case fixes every input and gate, and the tool refuses a case that differs from its own.
Every account below is **manufactured**, a declared state and not a flow solution: flat
surfaces, unthinned side columns at the retained linear geotherm, and the retained steady-state
conduction. Their gravity work is set to close the mechanical ledger. The one exception is the
mechanical terms of `pure_shear_work`, which come from an exact analytical field.

| Control | Checks and independent oracle |
| --- | --- |
| `constant_volume` | See below |
| `moving_surface` | See below |
| `flow_direction` | See below |
| `accounts` | See below |
| `pure_shear_work` | See below |
| `exhaustion` | See below |
| `refusals` | See below |
| `interfaces` | See below |

**`constant_volume`** checks:

- The cookbook's rule equals its literal `v*2*d/w`, evaluated exactly.
- The cookbook base is refused for separation.
- Both boxes book basal inflow equal to side outflow at constant volume.
- Mass and caloric changes match exact rational arithmetic (`fractions`) for both boxes.
- The mass gain equals the closed form `2 v dt sum (rho_a - rho_i) h_i`: 1.0e11 kg per metre
  per Myr. Constant volume is not constant mass.
- The manufactured ledger closes by construction, because its gravity term is set to close.
  This is not a sign test; `pure_shear_work` is.

**`moving_surface`** checks:

- Under-balanced inflow closes against shoelace polygon areas, and breaks the equality.
- A stationary-surface claim and an after-the-fact flux correction are refused.
- The corner offset (item 2 of section 5) closes against its exponential.
- Material-following sides have no side flux, and a fixed box balances. The two conventions
  book different basal inflow for one flow.
- Normal projection is impermeable; the vertical-mesh crossing equals `-slope u_x W` exactly.
- Unowned crossing is refused, and owned erosion is booked.

**`flow_direction`** checks:

- Zero flow gives an impermeable base with conductive Dirichlet only, no transfer, and heat
  equal to conduction plus sources; the input is unchanged.
- A reversed base is outflow, with no Dirichlet temperature or composition.
- The source is untouched.
- The receiver gets `m Cp (T_actual - T_ref)` at the stated 1605 K.
- A reset to 1613 K, outflow into the source and a missing state are refused.
- Conductive heat through the outflow base is refused, with its input unchanged. Heat through
  the impermeable base is admitted.
- In both regimes the account applies the base condition that the prescription states.

**`accounts`** checks:

- The start and end inventories equal the domain volumes against an exact rational sum of
  `m/rho`.
- Components, source debits and receiver credits match the exact oracle.
- Transfers are consistent between accounts.
- Datum shifts to 0 K and 1000 K leave mass identical and move energy by exactly
  `(T_ref - T') sum(sign rho Cp V)`; a mixed datum is refused.
- `rho V (h - e)` equals the basal flow work `P_b V_in`.
- An `h`-recorded source, boundary work offered as heat, latent heat, an open ledger and
  surface work are refused.

**`pure_shear_work`** is the one independent mechanical-work control. It uses exact Newtonian
pure shear of a homogeneous box, per metre of strike, with `x` in `[-W/2, W/2]` and `y` up from
the base in `[0, H]`:

```text
u        = (a x, a (H - y))          constant eta and rho, gravity (0, -g)
p        = rho g (H - y) - 2 eta a
sigma_xx = 4 eta a - rho g (H - y),   sigma_yy = -rho g (H - y),   sigma_xy = 0
W_base   = a rho g W H^2              base traction x velocity
W_sides  = 4 eta a^2 W H - a rho g W H^2 / 2
G        = -a rho g W H^2 / 2         body force x velocity
D        = 4 eta a^2 W H              stress x strain rate
```

- **Inputs.** `W = 200 km`, `H = z_b = 150 km`, `a = (v_L + v_R)/W`, 3300 kg/m³ and
  9.81 m/s². The basal inflow `a H` is therefore the selected reference rule. The viscosity,
  1e21 Pa s, is a manufactured constant, not a rheology choice.
- **The field meets the stated conditions.** Only `u` and `p` are written down. At the nine
  nodes of the box, exact rational arithmetic gives:
  - zero divergence and zero momentum residual, by central differences that are exact for this
    affine field;
  - the Newtonian stress `-p I + 2 eta D(u)`, equal to the stated components;
  - a traction-free, stationary top, and zero tangential traction on the base and sides;
  - uniform outward side velocity `a W/2` and basal inflow `a H`.
- **Each power from its own physics.** Each term is integrated separately by Simpson's rule,
  which is exact for these polynomials: `integral (sigma n).u dl` per segment,
  `integral rho g.u dA` and `integral sigma : D dA`. The results equal the closed forms above
  exactly, and the top does no work. None is set to close a ledger, and `flow_work` applied to
  the base traction reproduces the base term.
- **The tool's ledger.** Multiplied by `dt`, the terms enter `propose_interval`, whose ledger
  closes.
- **Seven errors are refused.** Each has its exact code, and its input is unchanged:
  - an inward normal on every boundary term;
  - base compression booked as tension;
  - reversed gravity;
  - the base flow work counted twice;
  - the viscous side traction omitted;
  - the dissipation omitted;
  - the base flow work offered as heat, refused with `REFUSED_THERMAL_SOURCE`. The first six
    are refused with `REFUSED_MECHANICAL_LEDGER`.
- **Scope.** This is an exact analytical solution for a homogeneous box, checked in exact
  arithmetic. It is not a numerical Stokes run, and it says nothing about the layered or
  plastic column. Its thermal entries are a declared isothermal state with no conduction booked,
  and they are not tested.

**`exhaustion`** checks:

- Exact depletion leaves a remainder of 0 kg and 0 J, while one ulp short is refused and leaves
  its input unchanged.
- A joint overdraft over two base segments is refused, although each stream fits alone.
- A cohort overdraft is refused.
- Repeating a proposal gives an identical result.

**`refusals`** checks 19 prescription, 23 account and 3 case mutations. Each has its exact
code, and each input is unchanged after the refusal. The account mutations include a doubled
start inventory and heat through an insulating side. Valid inputs pass.

**`interfaces`** checks:

- The I07 prescription is complete and unsolved.
- Supplied accounts are labelled as supplied, not solved.
- The supplied endpoint closes. A 1e-9 change of one cohort's mass or of the end volume is
  refused.
- A foreign parent, a foreign interval, an account edited after booking and an edited delta are
  each refused as foreign, with inputs unchanged. The edited delta comes with a matching end
  state.
- I05 with `z_b = h0` and with 150 km:
  - the inflow volume and its placement equal the closed form exactly;
  - the lithosphere inventory is untouched;
  - one asthenosphere cohort appears, with zero history and the same state per kilogram as the
    I07 Dirichlet value;
  - the endpoint closes on the grown volume and refuses the start volume;
  - the material-following sides report no lateral conduction and refuse a nonzero term.
- Shortening exports only `asthenosphere-initial`, at its actual state.
- The strip guard admits `z_b = h0/lam`, refuses a base one ulp shallower at the start and at the
  end, and refuses `h0` = 100 km over 150 km at `lam` = 0.6 at either end.
- The closed route is refused.

**Tolerances and their reasons.**

- `closure_relative` and `oracle_relative` are 1e-12 of the gross scale (the sum of absolute
  terms). Every account is a short, correctly rounded `math.fsum` of at most about 65 rounded
  products. Its error is therefore below about `65 eps ≈ 1.4e-14` of that scale, a margin of
  about 70.
- Exhaustion and cohort overdraft use exact comparison, never a tolerance. So do the zero
  conduction terms, the endpoint's proposal comparison and the pure-shear power identities.
- The cooperative budget is 10 s after imports, checked at each control's entry and exit. The
  controls are closed forms and should take milliseconds.
- No matched reuse comparison exists, so no speedup is claimed; only raw seconds are recorded.

**What the controls establish, and what they cannot.** They establish the following:

- each component carries exactly one prescribed quantity; this is necessary bookkeeping, not a
  proof of well-posedness;
- the account arithmetic and sign conventions close on supplied fluxes against oracles that
  share no arithmetic with the tool. Inventories are bound to geometry, and conduction to each
  segment's thermal condition;
- the mechanical ledger closes on work terms derived independently from one exact Newtonian
  solution, and it refuses sign and double-count errors;
- datum invariance and the separation of flow work from heat hold;
- endpoint proposals are bound to their accounts, and the refusals are atomic.

They cannot establish that the selected boundary-value problem is well posed in general. They
cannot establish that a Stokes solution with this boundary conserves material within a solver
tolerance. The pure-shear field is one homogeneous case and says nothing about a layered or
plastic column. The controls also cannot show that the resolved neck is insensitive to `z_b` or
to the base law, or that interior melting is absent. Those are I07 comparisons (section 11).

## 9. Sources

**Read for this closure (27 September 2026):**

| Source | Parts read | What it supports |
| --- | --- | --- |
| [ASPECT continental-extension cookbook](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) | Geometry, boundary velocity, free surface, temperature, composition, breakup statement, mesh | Side x-velocities with free y; uniform basal inflow balancing lateral outflow; free surface with normal projection and diffusion; fixed top and bottom temperatures with insulating sides; fixed bottom composition; breakup needs an asthenosphere or modified basal conditions, "e.g. Winkler boundary condition in Brune et al., 2014" |
| ASPECT `cookbooks/continental_extension/continental_extension.prm` (main branch) | Whole file | `Use years instead of seconds = true`; `Pressure normalization = no`; `Formulation = Boussinesq approximation`; `left x: function, right x:function, bottom y:function` with `v*2*d/w`; top free surface (normal) plus diffusion; tangential mesh on left and right; bottom composition `initial composition`; box temperatures 1613/273 K; densities 3300/2700/2900/3300; `Cp` 750; conductivity 2.5; expansivity 2e-5; reference temperature 273; compositional heating only |
| ASPECT parameter pages: [boundary velocity](https://aspect-documentation.readthedocs.io/en/latest/parameters/Boundary_20velocity_20model.html), [boundary traction](https://aspect-documentation.readthedocs.io/en/latest/parameters/Boundary_20traction_20model.html), [boundary temperature](https://aspect-documentation.readthedocs.io/en/latest/parameters/Boundary_20temperature_20model.html), [boundary composition](https://aspect-documentation.readthedocs.io/en/latest/parameters/Boundary_20composition_20model.html), [mesh deformation](https://aspect-documentation.readthedocs.io/en/latest/parameters/Mesh_20deformation.html), [global](https://aspect-documentation.readthedocs.io/en/latest/parameters/global.html) | The named parameters | Unknown external forces behind prescribed velocities; component selectors; traction models; fixed temperature on outflow (default true, with its caution) versus inflow only; fixed composition on inflow only without melt; normal projection for mass conservation; tangential mesh motion; diffusion as stabilisation or erosion/deposition; pressure only up to a constant for some boundary sets; the 365.2425-day year |
| [Brune et al. 2014](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf), Nat. Commun. 5:4014 | Methods, pp. 6–8, read as page images of the PDF | 500 × 150 km domain; lithosphere-base variants at 120/105/90 km; asthenosphere at 1300 °C below the lithosphere; bottom temperature fixed at 1300 °C; insulated sides; 4 mm/yr per side; free surface; Winkler foundation at the bottom (citing Popov and Sobolev 2008); robustness tests with other domain sizes, a free-slip lower boundary and one-sided extension; wet-olivine asthenosphere; the quoted dry solidus |

**Reused, not reread:** Angevine, Heller and Paola (1990), chapter 4, as recorded in
[finite strain](I01_FINITE_STRAIN.md#9-sources) section 9, for McKenzie's passive upwelling. Also
reused are the retained cases for the weakening, column-heat and finite-strain controls, the
contract's D1, D4 and D6 sections, the matrix's MC-04 item, and breakup sections 8, 11 and 13.

**The pure-shear control** uses an elementary exact solution of the incompressible Stokes
equations. No external source was consulted for it, and none is cited. The tool itself verifies
it in exact arithmetic: divergence, momentum balance, constitutive stress and every boundary
condition used.

**Not read and not claimed:** Popov and Sobolev (2008), SLIM3D (the Winkler formulation);
McKenzie (1978), which was earlier recorded as inaccessible; Katz et al. (2003) itself, whose
solidus is taken as quoted by Brune. No software was installed or run. No ASPECT model was run,
and no output was fitted.

## 10. Results

None are recorded here. The coordinator runs the focused tests and the bounded campaign. Any
reviewed receipt belongs in the [current evidence register](../../docs/CURRENT_EVIDENCE.md),
not in this source-bound document.

## 11. Remaining work and blocked parts

- **The I07 closure tolerance** is not selected. The resolved run must predeclare its
  account-closure tolerance from its solver tolerances before execution. This tool fixes only
  the analytical value of 1e-12 and refuses anything looser. The same declaration must cover the
  conduction that a resolved run reports where the law requires exactly zero.
- **The source state and the prescription.** `propose_interval` does not receive a
  prescription. It checks that each source is admissible incoming asthenosphere, but it does
  not compare the source temperature with a particular configuration's `T_b`. I07 must build
  the prescription and its accounts from one configuration.
- **The I07 depth sensitivity.** Report the three separation diagnostics (crustal,
  mantle-lithosphere and mechanical handoff) at `z_b = 150 km` and at a deeper base, with the
  same law, as a sensitivity that is never tuned.
- **The Winkler or free-slip comparison arm** needs the SLIM3D Winkler formulation (Popov and
  Sobolev 2008, not read) and the side-mesh convention of Brune's free-slip test.
- **Interior melting.** Rising 1613 K rock crosses the quoted dry solidus near 2.08 GPa. That
  needs MC-03, or the run must refuse.
- **Force-driven sides**, taken from the D1 balance, belong to I04/I09.
- **I05 transport** will use the cohort interface: moving surfaces, conduction of the inflow
  cohorts and the chain columns.
- **MC-01 and its elastic-memory choice** stay open. This closure issues no event.

## 12. Commands and bindings

From the repository root, with the existing compatible scientific environment (the tool and
tests use the standard library only):

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_basal_closure.py -v
python -B tectonics/tools/check_i01_basal_closure.py --output NEW_PATH.json
```

The receipt is created exclusively. Before and after the controls it binds the four new files
and the three retained cases that are read (`cases/i01_weakening_v1.json`,
`cases/i01_column_heat_v1.json` and `cases/i01_finite_strain_v1.json`). Before any control
runs, it checks that the case equals the executable and that the incoming state and windows
equal the retained values. Its status is `PASS_BOUNDED_BASAL_CLOSURE_ONLY` only if every
control passes and no bound file changed. `scientific_acceptance` and `stokes_solution` stay
false.
