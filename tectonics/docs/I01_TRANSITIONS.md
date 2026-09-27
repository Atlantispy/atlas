# I01 D6: physical transitions and event transactions

**27 September 2026. WORKING NON-CANON. D6 candidate v1, task
atlas-i01-d6-20260926.** This refines D6 of the
[I01 physical contract](I01_PHYSICAL_CONTRACT.md#8-d6--physical-events-not-label-switches)
(`atlas.regime-transactions.v1`); it does not replace that contract or its r1
controls. [Current state](../../docs/CURRENT_STATE.md) owns progress and the
[integration plan](INTEGRATION_PLAN.md) owns I06/I07 scope. The machine-readable
[design record](../cases/i01_transitions_v1.json) is not production configuration;
the [bounded controls](../tools/check_i01_transitions.py) write the
[reviewed transition evidence](../evidence/i01-transitions-r2.json).

No native solver, shared status file or earlier receipt is changed by this
document or its controls. A passing control demonstrates only its stated reduced
slice. **Generated continental breakup and generated subduction initiation remain
blocked**; section 10 names the exact missing decisions and supported routes.

## 1. What D6 decides, in plain language

Plate boundaries change their kind. A stretching continent becomes two plates
with new sea floor between them; old ocean starts sinking at a new trench; a
continent reaches a trench and jams it. In Atlas each of these is also a change of
*representation*: a resolved deforming belt is replaced by a thin boundary, or a
boundary gains a slab and a sink. D6 says when such a change may happen, what is
transferred, who owns the work and heat, and when Atlas must refuse.

Two rules run through every transition:

1. **A physical trigger, located in time.** The change happens when a declared
   physical quantity crosses a value: a force ratio, a buoyancy balance or a
   material supply. The crossing is a bracketed root of that quantity, evaluated
   from the committed parent state. A thickness cutoff, a label, an angle
   threshold or a display test is not a trigger.
2. **A switch that does not change the answer.** Switching representation at the
   trigger may change downstream accepted quantities (plate motion, material and
   heat accounts) by no more than a declared tolerance. Where a switch cannot
   show that, or the physical law is not closed, Atlas refuses.

Prescribed events remain useful: they test transfers, bookkeeping and refusal.
They never count as a generated transition.

## 2. Common event transaction: `atlas.event-transaction.v1`

An event record extends I01 section 8 with: parent state and interval; law and
parameter identities; trigger function `g` with units, sign and crossing
direction; the law's certificate (monotone over the step, or `|dg/dt| <= L`);
the located bracket; footprint (boundary segments, junctions, plates, cohorts,
finite stocks, regions); proposed topology with fresh IDs; exact intersections for
every transfer; reservations; work and heat owners; outcome or refusal reason.

```text
g(t) is re-integrated from the committed parent, never read from display samples.
step h = max(|g(t)|/L, tau_t)        no zero lies closer than |g|/L
sign change in [t, t+h]  -> Brent root to tau_t; split the interval at t*
g(t0) = 0                -> belongs to the previous interval (DUE_AT_START)
sampled zero             -> require a sign change across it; otherwise refuse
same-sign endpoints      -> certify |g_left|+|g_right| > L h, subdividing if needed
|g| local minimum <= g_res without a sign change, or sample budget exhausted
                         -> UNRESOLVED: refuse the step, reformulate the law
```

SUNDIALS CVODE and SciPy `solve_ivp` both locate roots from sign changes over each
step. CVODE finds only roots of odd multiplicity, and SciPy warns that several
crossings within one step may be missed. Atlas therefore requires the law, not the
integrator's step choice, to certify that no crossing is skipped. `tau_t` must satisfy
`|d(state)/dt| tau_t <= state tolerance` for every affected account.
The minimum step can span two crossings closer than `tau_t`; calling those
simultaneous does not permit losing them. Uncertain same-sign intervals are
subdivided within the shared evaluation budget until every subinterval has the
strict endpoint exclusion certificate (including conservative floating-point
margin). An interior zero/sign change or exhausted time resolution instead
refuses as `UNRESOLVED_CROSSINGS`; budget exhaustion also refuses. An exact zero
at the right endpoint is unresolved without
a crossing certificate beyond it; the bounded helper never extrapolates outside
the interval. Every evaluation, including Brent's, uses the same sample budget.
Nonfinite endpoints and a clock too coarse to advance are refused.

**Simultaneous events** (triggers within `tau_t`):

- Disjoint footprints commute. They are applied in canonical event-ID order, and
  the control checks that both orders give the identical committed state.
- Any shared footprint makes one joint proposal. Demands on each finite stock are
  aggregated; all commit or all refuse. There is no first-come allocation and no
  clipping. Dividing a scarce stock between competitors needs an admitted
  physical law; v1 admits none, so such a conflict is refused.
  Each component transaction must first be finite, nonnegative and balanced;
  invalid proposals must not cancel into an apparently valid aggregate. Parent
  stocks and committed amounts must also stay finite and nonnegative.
- Events more than `tau_t` apart cascade: commit the earlier one, then
  re-evaluate every remaining trigger from the committed state. Evaluating all
  triggers once from the parent trajectory is prohibited; the control shows it
  fires an event that the first event suppresses.
- Each split interval counts against the existing ceilings, including the 256
  accepted-interval limits of the W workflows and native terrain R5. Exceeding a
  ceiling refuses the request; ceilings are not raised to fit events.

An event is instantaneous. It moves amounts between named accounts and changes the
operators used by later intervals; it performs no work itself. Transferred material
keeps its formation age, thermal history and D2 memory.

Existing seams: `topology.py` binds each event to its parent model, refuses replay,
keeps retired IDs reserved and integrates exact ownership intersections;
`w08_workflow.py` requires dated transitions with geometry, polarity, coupling and
thermal provenance and refuses simultaneous retirement and magmatic demands on one
inventory. D6 generalises these rules; it does not relax them.

## 3. Continental separation: `atlas.rift-decoupling-handoff.v1`

**Physical basis.** In Brune et al. (2014), rifting first localises through strain
softening. A lateral strength gradient then drives steady rift migration through
sequential faults and lower-crustal flow; the active zone stays about 30 km wide
while hyper-extended margins exceed 200 km. Migration stops when the lower crust
cools and embrittles; faults then reach the mantle, the crust separates and mantle
is exhumed with little melt. Large parts of one margin come from the opposite side
of the rift. Faster extension gives wider margins; thin, hot lithosphere gives
symmetric wide rifts without migration.

**What is decided.** When does the belt stop being a continental region that
couples two plates, and become a divergent plate boundary? The answer is
mechanical: when the belt no longer controls the plates' relative motion.

```text
F_drive - R_far(v) - F_belt(state, v) = 0      D1 balance, per side, per unit length
linear zero-intercept control ONLY:
Pi = (dF_belt/dv) / (dR_far/dv)                belt / far-field resistance
handoff when Pi <= Pi_c,   Pi_c = eps_v / (1 - eps_v)
nonlinear/history/plastic belt: actual coupled-versus-uncoupled error certificate required
```

`eps_v` is the relative plate-velocity tolerance already accepted by the coupled
controller (declared in I02's numerical contract, enforced by I09), not a geological
constant. It is measured here against the uncoupled speed `v_inf`, not the old
coupled speed; no production tolerance value is selected by this control.
For the linear control, with active
width `w`, far-field drag `R_far = D W v` and a Newtonian plane-strain belt
`F_belt = 4 eta h (2v/w)`:

```text
v(h)  = F / (D W + 8 eta h / w)
dh/dt = -(2 v / w) h
t(h)  = (w D W / (2 F)) ln(h0/h) + (4 eta / F)(h0 - h)
Pi(h) = 8 eta h / (w D W)
```

Three consequences follow, and the control checks each:

- With any positive far-field resistance, the belt reaches zero thickness only as
  `t -> infinity`. A thickness cutoff `h_c` then gives an event time that grows by
  at least `(w D W / 2F) ln 10` for every factor of ten in `h_c`: there is no physical
  event time. A prescribed-velocity (kinematic) run behaves the same way and has no
  force balance at all, so it cannot generate separation.
- Only an idealised zero-resistance far field gives finite-time pinch-off
  (`t -> 4 eta h0 / F`); real plates always have resistance.
- In this positive, zero-intercept linear control, once `Pi <= Pi_c`, replacing
  the belt with a zero-resistance divergent boundary changes each plate's speed
  by at most `Pi_c / (1 + Pi_c)` **of `v_inf`**. The later displacement bound
  also depends on this control's monotonically decreasing belt resistance.

The derivative ratio is not a general release criterion: with `F_drive=1`,
`R_far(v)=v` and a yield plateau `F_belt=0.9`, `Pi=0` but releasing the belt
changes `v=0.1` to `v_inf=1`, a 90% difference. A nonlinear/plastic handoff must
compare the actual coupled and proposed replacement solutions, with a declared
norm/reference scale and history-window error bound. Until that certificate and
the resolved physical separation law exist, generated separation stays blocked.

**Transfer at handoff.** Split the belt's material at the separation axis, the
locus of minimum integrated strength in the resolved solution, by exact
intersection of *current material position*: ownership follows material, not the
original plate ID. All thinned crust and mantle stay continental margin cohorts
with their ages, thermal histories and D2 memory. The new boundary has a fresh ID;
its new area comes only from D3 birth with the section 4 supply. In D1, the belt's
coupling term is removed. Before handoff, driving work equals far-field
dissipation plus belt dissipation; after it, the belt term is zero.

**Required inputs.** D1 driving forces and the far-field resistance operator; D2
depth-integrated belt strength with temperature, effective pressure, strain
softening memory and physical length; D4 temperature including advection in the
thinning column; the active width and axis from resolved regional mechanics (I07).

**Refused:** a thickness-cutoff trigger; a label change from rift to ridge;
kinematic-only generated separation; a handoff with `Pi > Pi_c`; converting
thinned continental crust or exhumed mantle into age-zero basalt; and a "split"
whose new boundary does not connect to the network at both ends. A boundary tip
inside a plate is a deforming zone, not a plate split.

## 4. New sea floor after separation: `atlas.decompression-supply.v1`

**Physical basis.** Brune et al. (2014, Methods) post-process batch melting of
peridotite using the anhydrous Katz et al. (2003) law, as quoted there. They
estimate at most 0.8 km of melt before crustal break-up and about 1.2 km after
it, rising to several kilometres at 1350 °C. Here it supplies a column melt
inventory and an ideal crust equivalent under complete extraction, not an
established evolving sea-floor supply:

```text
p(z)    = rho_m g z                     Pa (GPa inside the quoted polynomials)
Tsol(p) = -5.1 p^2 + 132.9 p + 1085.7   °C
Tliq(p) = -3.2 p^2 +  80.0 p + 1475     °C
X       = ((T - Tsol)/(Tliq - Tsol))^(3/2),   0 below the solidus
T       = T0 - X dS (T + 273) / Cp      dS = 300 J/kg/K, Cp = 1200 J/kg/K (root)
T0(z)   = Tp + gamma z                  supplied mantle path; gamma is an input
H       = integral from z_lid to z_sol of X dz        melt-equivalent thickness
h_crust_equivalent = rho_m H / rho_crust              full-extraction end member
```

`z_lid` is the axial conductive lid from D4; spreading-rate dependence enters
through it. `z_sol` is where `T0` meets the solidus.

- When `z_lid >= z_sol`, `H = 0` and the new surface is **exhumed mantle**: a
  separate D3 phase (peridotite, no crust), never basalt. Serpentinisation needs
  an owned water account; otherwise it is a named omission.
- The change from magma-poor to magmatic spreading is continuous in `H`, not an
  event; a diagnostic may record when `H` first exceeds zero.
- Per unit of represented column area, processed mantle `rho_m max(z_sol - z_lid,0)` equals melt
  `rho_m H` plus residue. Latent heat `integral rho X dS (T+273) dz` equals the
  sensible deficit `integral rho Cp (T0 - T) dz`. This is the column's enthalpy
  identity, not a transport/extraction calculation. An eventual D4 coupling must
  return crystallisation heat to actually extracted new crust once.

**Validity.** The single-branch anhydrous law as quoted: no clinopyroxene
exhaustion and no water. A melt fraction of 0.3 is an authored guard, not a
literature bound. The column is 1D and instantaneous, with no melt migration,
focusing or extraction efficiency; Brune notes that not all melt reaches the
surface. `endmember_surface` and `crust_equivalent_m` in the receipt assume full
extraction explicitly. They are not generated terrain/material supply. The control
uses pressures below about 2.2 GPa.

## 5. Boundary and ridge migration: `atlas.boundary-migration.v1`

Each boundary moves according to its own rule, with velocities in the local
tangent plane and junction velocity `J`:

```text
ridge L|R        n.J = n.((1-f) v_L + f v_R)   f = 1/2: declared symmetric accretion
trench O over S  n.J = n.v_O                    moves with the overriding plate edge
transform L|R    n.J = n.v_L = n.v_R            requires n.(v_R - v_L) = 0
```

- **Ridges.** Given D1 velocities, symmetric accretion predicts axis migration
  relative to the mantle. Asymmetric accretion (`f != 1/2`) needs an admitted law
  or a prescribed history. Gurnis et al. (2012) likewise assume symmetric
  spreading for ridge poles.
- **Trenches.** A trench moves with the edge of its overriding plate (Gurnis et
  al. 2012). Rollback beyond that needs a resolved back-arc belt or a microplate
  with its own boundaries; Atlas has no free rollback velocity.
- **Rifts.** Rift migration (Brune 2014) is an output of a resolved belt and
  transfers material across the rift. Generated rift migration is blocked in the
  reduced mode. Prescribed migration requires exact ownership transfers.
- **Junctions.** Junction closure uses the velocity-triangle construction of
  McKenzie and Morgan (1969), derived here from rigid kinematics; that paper was
  not accessed. Solve `A J = b` over the meeting boundaries, with residual
  `r = ||A J - b|| / max_ij |v_i-v_j|`, using relative constraint velocities in
  both the solve and its scale. A common frame velocity must not change acceptance.
  Stationary compatible full-rank constraints have zero residual; a rank-deficient
  system is refused as underdetermined. If `r` is within the algebra tolerance, the junction
  persists and advances with `J`. Otherwise it must reorganise (a segment
  shortens to zero, or new segments form). That is a topology event needing an
  admitted law; v1 refuses it.
- **Shared geometry.** Each shared edge has one record, and intersections are
  recomputed each accepted step, as in continuously closing plates. GPlates keeps
  inverted or "slid past" polygons and closes gaps by rubber-banding; Atlas must
  refuse both.

## 6. Subduction initiation: `atlas.subduction-initiation-state.v1`

**Physical basis.** Gurnis, Hall and Lavier (2004) distinguish *forced* from
*self-sustaining* subduction:

- The dominant resistance is elastic bending, with peaks of 1e12–1e13 N/m. Fault
  friction or growth of a lithosphere-cutting shear zone and crustal buoyancy add
  to it.
- The force needed to keep converging follows total convergence, not its rate.
- Weakening must be fast enough. The time at which the force falls scales with
  weakening strain times mesh spacing, and shear zones are 2–4 cells wide.
- Their cases need 100–130 km of convergence. Effective friction below 0.02, with
  near-lithostatic pore pressure, is required to self-sustain within 200 km.

Crameri et al. (2020) define initiation as the onset of downward motion forming a
new slab that later becomes self-sustaining. Their 13 events from the last
100 Myr are:

- horizontally forced, with none purely spontaneous;
- mostly within 500 km of existing subduction;
- up to 5–10 Myr long.

```text
none -> forced_incipient     event supplies polarity, dip, fault geometry, weakness
                             source, incoming cohorts, destinations, resistance source
forced_incipient -> self_sustaining when  C g sum(dm_i l_i) >= R(state)  with F_ext = 0
forced_incipient -> stalled_incipient_underthrust when forcing ends first
dm = (rho_c - rho_m) h_c + alpha dT [rho_c int_0^hc theta dz + rho_m int_hc^L theta dz]
theta = (Tb - T)/(Tb - Ts): I01 plate-cooling series; steady linear for continents
```

- Slab force comes only from actual attached inventory (D3). Convergence alone
  creates underthrust inventory, never an established slab.
- Buoyant young ocean (`dm <= 0`) cannot self-sustain without an admitted
  phase-change law, such as eclogitisation with kinetics. For the control inputs
  the neutral age is about 10.8 Myr.
- The attached length needed to self-sustain, `l* = R/(C g dm)`, depends on age.
  There is no universal convergence threshold.
- Work is owned: `F_ext x + integral C g dm x dx = R x + integral k v^2 dt`. The
  `R` term becomes D4 heat only if frictional heating is admitted, `k` belongs to
  D1 mantle resistance. The `C`-weighted buoyancy term is transmitted slab-force
  work in this reduced model, not a proof of full gravitational/thermal closure;
  untransmitted work and actual sinking geometry remain outside this control.
- `R(state)`, the resisting force through bending and failure, has no validated
  reduced closure. That is the missing decision (section 10).

## 7. Continental arrival and collision: `atlas.collision-buoyancy-handoff.v1`

```text
attached window [max(-l0, x - l_max), x) of subducted incoming material (first in, first out)
F_net(x) = F_ext + C g integral_window dm(s) ds - R
v        = max(F_net, 0) / k                  terminal-velocity balance (Forsyth & Uyeda 1975)
arrival:  x - d_COB = 0                       exact bracketed root
handoff:  v <= eps v_arrival, remaining convergence = eps (x_b - d_COB)
x_b - d_COB = F_net(d_COB) / (C g (dm_ocean - dm_cont))     saturated window; asymptotic entry
```

- **Why collision has no finite jam time.** Continental columns are strongly
  buoyant because of their crustal density deficit. In this reduced balance, as
  continent enters, `F_net` falls and subduction slows only asymptotically, so the
  handoff is bounded by remaining convergence, not by a jam time.
- **Entry depends on the slab.** How much continent enters depends on the attached
  ocean inventory. For the control inputs this is 66.5 km behind 30-Myr ocean and
  168.7 km behind 80-Myr ocean; there is no universal rule.
- **Material destinations.** Entering continent goes to a named destination
  (subducted-continental, accretion or underthrust) under a declared partition or
  a resolved regional solution. It is never deleted through the ocean sink.
  Material leaving the attached window goes to deep storage and stops pulling.
- **After handoff.** The boundary becomes a collision belt: W08 shortening with
  full-vector motion and a high-resistance D1 interface. A later merge is a
  topology event, and the suture keeps its inherited weakness.
- **Slab breakoff.** This needs a D2 strength law within the slab; it is
  prescribed or refused.

## 8. Transform and oblique motion: `atlas.full-vector-adapter.v1`

```text
dv = v_R - v_L;   o = dv.n   opening, n from left to right;   s = dv.t   slip
area rate = o at a divergent boundary with supply; -o at a convergent boundary
with polarity; slip creates no area and no uplift
```

There is no angle threshold. At 61° obliquity, a 60° classifier (the arbitrary
split in Forsyth and Uyeda 1975, or a deviation parameter in GPlately boundary
statistics) would discard 48% of the opening. Statistics may classify; physical
transfer may not. Strain partitioning into a forearc sliver is a resolved I07
output. In the reduced model, tangential slip stays on the boundary as dissipative
work under the D1 interface law. The existing `fault_slip.py` already supplies only
slip; normal creation or convergence needs another physical route.

## 9. Topology events: `atlas.topology-transactions.v1`

| Event | Admission | Transfer and refusal |
| --- | --- | --- |
| Split | Separation handoff, or an initiation segment that joins two existing boundaries or junctions | Fresh IDs; ownership by exact intersection of current material; refused if the new boundary ends inside a plate |
| Merge | Collision handoff, then relative motion within tolerance over an interval | Suture kept as a D2 inheritance; no area renormalisation |
| Retire | Plate area reaches zero through bracketed consumption | All material already in named destinations; ID stays reserved |
| Junction reorganisation | Closure residual above tolerance | Needs an admitted evolution law; refused in v1 |
| Ridge jump or polarity reversal | Prescribed history only (Crameri types: episodic, reversal) | Treated as a split plus retire; never inferred from labels |

Coverage must remain exactly `4 pi R^2` with one owner per point. No rubber-band
closure, no smoothing and no recolouring may hide a gap or overlap.

## 10. Status, missing decisions and supported routes

| Transition | Status | Exact missing decision | Supported now |
| --- | --- | --- | --- |
| Event bracketing, simultaneity | Specified; bounded control implemented | Production trigger certificates per law (I02) | Prescribed and control use |
| Separation trigger and transfer | Proposed; linear control implemented; **generation blocked** | Validated depth-integrated belt strength `F_belt(T, kappa, h)` from D2/D4, a resolved rift and an actual nonlinear replacement-error certificate | Prescribed separation (time and axis supplied) in `prescribed_history_v1` |
| Post-separation supply | Column inventory/end-member control implemented, not actual supply | D4 axial lid `z_lid(rate)`, mantle `Tp` provenance, melt extraction and focusing | Scenario-supplied `Tp` and lid |
| Ridge and trench migration | Proposed (symmetric accretion; upper-plate trench) | Asymmetric accretion law; back-arc rollback | Prescribed asymmetry, resolved back-arc |
| Rift migration | **Blocked** in reduced mode | Resolved belt with lateral strength gradient (I07) | Prescribed migration with exact transfers |
| Junction persistence | Proposed; control implemented | Junction reorganisation law | Refusal plus prescribed reorganisation |
| Subduction initiation | State and inventory specified; control implemented; **generation blocked** | `R(state)`: elasto-plastic bending plus weakening with physical length and pore pressure | Prescribed initiation (tests transfers); resolved I07 benchmark route |
| Collision | Proposed; control implemented | Partition of arriving continent; slab breakoff | Declared partition, or refusal |
| Transform and oblique | Specified; control implemented | Resolved strain partitioning (I07) | Full-vector reduced adapter |

The resolved route for initiation is an I07 regional elasto-visco-plastic
experiment using the D2 physical length. It must reproduce Gurnis et al. (2004)
behaviour: force rising with convergence and falling at plate failure, the
failure offset independent of mesh, and age dependence. A full global convection
model is not the automatic fallback.

## 11. Mechanical inputs a rupture or initiation law needs from D2

These are typed requests for D2 and are not selected here. D6 does not choose
fault lengths or material constants, and the D2 1D control does not supply
through-lithosphere rupture.

1. Elastic stress memory with an objective rate (a visco-elasto-plastic branch):
   bending dominates initiation resistance.
2. Absolute effective pressure including a pore-pressure law, because effective
   friction below 0.02 implies near-lithostatic fluid pressure.
3. Weakening parameters with provenance and a *physical* shear-zone width, so the
   failure offset `dx_c = strain_f * width` does not scale with mesh spacing.
4. Plastic history transported through large deformation (Lagrangian or
   particle), preserved across remeshing.
5. A through-thickness connectivity diagnostic of the weakened zone and its
   integrated strength, computed on physical material fields.
6. Temperature-dependent creep with shear-heating ownership (D4), because
   lower-crustal flow controls rift migration.
7. Free-surface topography and isostatic support from D5, since topographic load
   adds initiation resistance.

## 12. Controls and predeclared acceptance

Run `python -B tectonics/tools/check_i01_transitions.py --output NEW.json` with the
existing scientific environment. The tool claims its output file without
overwriting, requires the case policy and parameters to equal the executable's,
binds the tool, case, focused tests and this document before and after running, and records raw
seconds per control after library imports. All six controls must pass for
`PASS_BOUNDED_CONTROLS_ONLY`; `scientific_acceptance` stays false.

| Control | Predeclared checks |
| --- | --- |
| bracketing | A one-step sign test misses a double crossing; the safeguard finds the first root within `tau_t`; a tangency is refused; a zero at the start belongs to the previous interval; no event is invented |
| simultaneity | Disjoint events give the same state in either order; sequential first-come handling is order dependent; conflicts are refused atomically; a feasible joint proposal is order-free; the cascade re-evaluates triggers after each commit |
| separation | Event time, displacement and exported material match closed forms to `1e-9`; the power balance holds to `1e-11`; cutoff and kinematic event times diverge by at least 99% of `ln 10` times their time scale per decade; the zero-drag limit converges; handoff errors stay within `Pi_c/(1+Pi_c)` |
| supply | Exhumed mantle beneath a lid deeper than the solidus; less melt beneath a thicker lid; more melt from hotter mantle; latent heat reduces melt; two quadratures agree to `1e-8`; the enthalpy identity holds to `1e-9`; the melt-fraction guard holds; full-extraction crust-equivalent thickness is an output, not a constant |
| migration | RRR closes at the circumcentre; a common rotation translates the junction; a constructed RTF closes; a rotated trench and a generic TTT are refused (residual at least `1e-3`); the full vector is preserved; opening varies continuously; a pure transform creates no area; a 60° classifier would discard opening |
| slab | Plate series matches the half-space limit; young ocean is buoyant; no universal initiation length; short forcing stalls and retains inventory; long forcing self-sustains; convergence of young ocean creates no slab; work balances to `1e-9`; collision events match closed forms; accounts close; continental entry depends on the slab inventory |

Control inputs are authored, with sources recorded per value in the case file:

- **From the I01 D1 control:** basal drag.
- **From Clennett et al. (2023, Table S1):** mantle and continental-crust
  densities, expansivity, diffusivity, temperature drop and transmission
  factor `C`.
- **From Gurnis et al. (2004):** ocean-crust thickness and density.
- **As quoted by Brune et al. (2014):** melting constants and the mantle
  temperatures of 1300 and 1350 °C.
- **Authored order-of-magnitude choices:** forces, viscosities, widths, plate
  thickness, slab lengths and resistances. The 30 km active width follows
  Brune's reported zone.

None is an Atlas default or an Earth calibration.

**Plan acceptance cases.** These controls feed matrix cases C (rift to spreading),
D (subduction and continental arrival), E (transform and oblique) and G (topology
events) in the integration plan. They do not accept any of them. I06 must show one
coupled rift-to-spreading case with the same material and heat carried through the
handoff; I07 must show ocean entry, arrival and collision on actual I03 geometry.

**Efficiency.** Triggers are scalar evaluations along an interval that is already
being integrated. Junction closure is a 3×2 least-squares solve per junction, and
joint proposals are local to overlapping footprints. None of this adds global
work. No whole-generator timing is inferred from these tiny controls.

## 13. Sources

Read for this task, methods or relevant sections rather than abstracts:

| Source | What was read and used |
| --- | --- |
| [Brune et al. 2014](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf), Nat. Commun. 5:4014 | Full main text and Methods; supplement not read. Rift migration, crustal break-up and exhumation, numerical setup, softening and melt post-processing |
| Gurnis, Hall and Lavier 2004, G3 5 Q07001 (CaltechAUTHORS copy) | Read fully in the earlier I01 checkpoint; formulation (equations 1–3), parts of section 4 and the discussion re-checked here |
| [Gurnis et al. 2012](https://www.earthbyte.org/Resources/Pdf/Gurnis_cont_closing_plates_CompGeosci2012.pdf), Comput. Geosci. 38:35–42 | Full paper: shared margins, trench and ridge pole rules, intersection handling and stated limits |
| [Crameri et al. 2020](https://www.nature.com/articles/s41467-020-17522-9), Nat. Commun. 11:3750 | Main text, Box 1 definitions, database findings and Methods up to the quantitative metrics; reference list not read |
| Forsyth and Uyeda 1975, GJRAS 43:163 (owner-supplied copy) | Read in the earlier I01 checkpoint; terminal-velocity slab balance and colliding-resistance terms reused |
| Clennett et al. 2023 and Table S1 (owner-supplied supplement) | Read in the earlier I01 checkpoint; parameter values only |
| [SUNDIALS CVODE mathematics](https://sundials.readthedocs.io/en/latest/cvode/Mathematics_link.html) and [SciPy `solve_ivp`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html) | Root-finding sections: sign-change detection, modified secant, missed-root caveats |
| [GPlately `PlateReconstruction`](https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.PlateReconstruction.html) | Subduction and ridge tessellation outputs: obliquity, orthogonal and parallel components, supplied polarity |
| ASPECT continental-extension cookbook | Read in the earlier I01 checkpoint; stated inability to reach breakup without further treatment |
| Existing Atlas code | `topology.py`, `w08_workflow.py`, `spreading_history.py`, `subduction_materials.py`, `fault_slip.py`, `plate_layout.py`, `extension.py` and `damage_regularisation.py`: headers and refusal contracts |

Referenced but **not read**:

- Katz et al. (2003): equations taken as quoted by Brune; the repository copy
  required human verification, which was not bypassed.
- McKenzie and Morgan (1969): the junction rules are derived here.

No external software was installed or run; no model output was fitted.

## 14. Integration review and D2 connection

Codex reviewed the actual delivery, reusing Claude's matching 25-test and six-
control record where unchanged. Review found the sub-tolerance missed crossing,
sampled-touch false event, invalid component transfers cancelling in an aggregate,
and frame-dependent junction residual. Focused regressions reproduce these gaps;
the corrected runner produces r2 without editing [Claude's r1](../evidence/i01-transitions-r1.json).
The derivative-only handoff overclaim and melt/work labels are corrected above;
no numerical acceptance tolerance or physical fixture was loosened.

D2 now supplies bounded [pressure/temperature mechanical snapshots](I01_STRENGTH.md)
and [physical-length weakening/localisation controls](I01_FAULT2D.md). This partly
addresses inputs 2, 3 and 6: absolute reference plus dynamic pressure and supplied
pore pressure, nonlocal physical length, and temperature-dependent creep.
It does **not** supply a pore-fluid evolution law, calibrated weakening, owned
shear heating, elastic memory (1), transported history (4), through-thickness
rupture/integrated strength (5), or a coupled free-surface/D5 load (7).
These remain explicit integration dependencies; neither D2 nor D6 closes I01.
