# I01: physical contracts and discriminating controls

**26 September 2026. WORKING NON-CANON. Version 1 design/candidate contract.**
This continues the research checkpoint, not a second tectonics implementation.
[Current state](../../docs/CURRENT_STATE.md) owns progress; the
[integration plan](INTEGRATION_PLAN.md) owns I01–I12 scope. The machine-readable
[design record](../cases/i01_closures_v1.json) is not production configuration.

I01 freezes the interfaces below and identifies the remaining physical decisions.
It does **not** label a numerical prototype, prescribed event, or running solver
as a realistic generated world. New controls live outside the source-bound native
package. No native solver is changed by this document or its controls.

## 1. User routes, clock and starting assumptions

Two explicitly named modes share records, not claims:

- `prescribed_history_v1`: admitted rotations, events and material/heat supplies
  reconstruct a declared history; useful for reference and conservative transfer.
- `coupled_generated_candidate_v1`: forces and evolving properties determine
  motion; admitted failure/transition laws determine subsequent reorganisation.
  This route must remain unavailable as a completed generator while D2/D6 below
  lack their required physical closure and coupled controls.

Use metres, seconds forward from a named epoch, kilograms, kelvin and joules.
Angular velocity is rad/s; torque is N m. Calendar/years-to-seconds conversion is
explicit (controls use 365.25 days/year). Ma-before-present is an import convention,
not a negative timestep. A request declares its history start and selected endpoint;
there is no silently assumed universally adequate spin-up duration.

Seed, initial plate count and initial continental fraction describe the **initial
state**. Their final values evolve. Matching a final fraction/count would be a
separate inverse problem, never a post-run area correction. The initial geological
scenario supplies crust, inheritance, temperature, any initial slab inventory and
mantle forcing; supplied assumptions retain their origin. Plate IDs are not rock
IDs. Initial layout is not the final tectonic world.

Inherited ocean has independent formation-age and thermal-history fields, with
unknown masks. For hot-born ocean, cooling onset may equal birth; reheating never
resets formation age. Initial continental geotherms are not reapplied every step.
Publish how much retained material still depends on assumed initial histories.

## 2. Product and feedback ownership

| Product / exchange | Producer and state required | Consumer / single owner |
| --- | --- | --- |
| Shared spherical geometry, coverage and event lineage | I03 geometry from I02 accepted state; D2/D6 event proposal | D1/D3 and regions use the same boundary, never a smoothed display substitute |
| Angular velocities, full vectors and driving/resisting work | D1 global solve plus regional reactions from accepted material/properties | I03 trajectories and regional boundary conditions; never two displacements for one amount |
| Cohorts, thickness, phase inventory and formation history | D3/I05 conservative transfers and finite birth/sink stores | D4 properties, D5 support, geology and native exports |
| Temperature/enthalpy and heat transfers | D4 with reference heat capacities and owned source/boundary terms | D1 density/GPE, D2 strength, D5 density/load; no average-age replacement |
| Strength, raw plastic history and filtered state | D2/I05 material-following update | Mechanical response and admitted event triggers; display sampling cannot change history |
| Slab, accretion and mantle/exterior inventory | D3/D6 named destinations | D1 attached-slab force; no force from missing or already detached material |
| Dry tectonic elevation and regional correction | D5 using one datum and disjoint contribution ownership | Water-load solve, terrain, inspection; terrain receives change/reference once |
| Water/sediment/geology feedback | Identified external owner and dated exchange; declared zero only in a named dry control | D4/D5/I09 reserve/debit/credit once; no inferred absent input |
| Save/continue/export/inspect | I02 atomic accepted state; I10 existing lifecycle adapters | UI/downstream read identified state; cancellation preserves previous committed state |

Every proposed interval has a parent ID, common endpoint, source/model/parameter
identities, spatial support, frame/datum and units. Reserve all material and heat
debits before mutation. Geometry, inventories, energy and event records commit
together or not at all. Numerical success of individual components is insufficient:
I09 must converge the coupled endpoint or demonstrate its split-error bound.

## 3. D1 — Reduced spherical driving and resistance

**Selection:** `atlas.plate-torque-resistance.v1`, a reduced forward candidate,
not a full mantle solution and not a rerun of the held R4.4 experiment. Preserve
prescribed rotations as an independent reference mode.

For plate i, position r (m), velocity `v_i = omega_i cross r`, supplied mantle
velocity `v_m`, and positive basal coefficient `D=eta_a/H_a` (Pa s/m):

```text
t_b = -D (v_i - v_m)                              [Pa]
M_i = integral_A D (|r|² I - r r^T) dA             [N m s]
b_i = integral_A r cross (t_drive + D v_m) dA
      + integral_boundary r cross f_drive dl       [N m]
M_i omega_i + regional/interface reactions = b_i
```

The sign is explicit: basal resistance does negative work on relative slip.
Positive linear interface resistance `f_ij=-k_ij(v_i-v_j)` (k in Pa s) gives
symmetric block coupling with diagonal `+B_ij` and off-diagonal `-B_ij`, where
`B_ij=integral_edge k_ij(|r|²I-rr^T)dl`. Equal/opposite internal reactions cancel
in total torque. This linear interface law is a verification option; it does not
replace nonlinear yielding in a resolved deforming belt. An interface with a
regional reaction must not also receive the surrogate resistance.

Driving-force inputs are named, not hidden fitted velocities:

- GPE uses compensated column mass/temperature and a shared reference. A candidate
  distributed traction is `-(L0/L) grad_s U`, with `U` in J/m², `L0/L` declared and
  the surface gradient in Pa. Calculate U from the same supported columns and
  datum as D5; no separate ridge-push line force where this term already owns it.
- Slab pull uses attached slab negative buoyancy per trench length:
  `f_sp=C g integral_slab_cross_section (rho_slab-rho_m) dA_section n` (N/m).
  Initial slab geometry is an assumption; later inventory comes from D3/D6.
  C and any explicit bending/interface resistance must have non-overlapping
  meanings. Do not both hide resistance in C and add the same resistance again.
  No universal 700 km slab length or automatic force for every convergent edge.
- Prescribed mantle tractions/velocity, when selected, are recorded external
  forcing with work accounts. A missing force is not zero unless the scenario
  explicitly selects the reduced omission.

Clennett's paper assesses supplied motions with a reduced torque model. Solving
for motion here is an Atlas extension. Its fitted Earth coefficients are not
automatically portable constants. The baseline control uses authored inputs,
not fit-to-output speeds; a doubled resistance must reduce speed accordingly.

Positive drag on a finite-area plate anchors it to the declared mantle frame.
Do not subtract net rotation after solving: that changes the drag problem.
If only relative resistances exist, specify the physical frame constraint and
remove the nullspace in the solve, or refuse. Net rotation is a diagnostic.
Report torque residual, work, dissipation and missing force terms separately.
Couple belt reactions and surface ownership before accepting a global step;
independently balanced rigid plates need not form a kinematically closed sphere.

**Control:** exact two-hemisphere second moments and equatorial resistance,
analytic angular velocities, frame rotation, zero drive, inverse drag scaling,
and independently integrated power. **Still required:** supported force-parameter
challenges and changing-geometry/regional-reaction tests in I04/I09.

## 4. D2 — Strength and physical-length localisation

**Candidate:** `atlas.nonlocal-weakening-candidate.v1`. Compare against the retained
local-law controls without changing them. Select an isochoric, rate-dependent
frictional/creep model for the first reduced belt, with no unowned dilatancy.
At a common material state:

```text
P_eff = max(P_hydrostatic + P_dynamic - P_pore, 0)    [Pa]
Y = C(kappa_bar,T) cos(phi) + P_eff sin(phi)         [Pa, 2D convention]
kappa_bar - ell² Laplacian(kappa_bar) = kappa
normal gradient(kappa_bar) = 0 on declared closed belt sides
Dkappa/Dt = lambda_plastic - h(T) kappa
```

This is a declared plane-strain yield convention, not an unconverted 3D Mohr–
Coulomb law. Incompressible dynamic pressure alone lacks the absolute lithostatic
reference needed for friction. Cohesion/friction versus history, residual strength,
creep law, pore pressure, ell and h(T) must be explicit scenario/material inputs.
Raw kappa is preserved; only its influence on strength saturates. Do not repeatedly
filter and overwrite raw history. A transported memory field is required before
claiming evolving damage in a moving region; the existing frozen-damage route is
not that bridge. An elastic branch, if selected for bending/onset, also needs its
stress memory and objective transport; the present control does not supply it.

The new 1D feasibility control closes momentum rather than merely drawing a
Gaussian band. For fixed-temperature positive simple shear, constant stress tau
follows from equilibrium and imposed integrated velocity V:

```text
gamma_dot = tau/eta_v + max(tau-Y,0)/eta_p
integral_0^L gamma_dot dy = V
lambda_plastic = max(tau-Y,0)/eta_p
Y = Y0(y) - (Y0(y)-Yr(y)) min(kappa_bar/kappa_c,1)
```

Here kappa is accumulated **engineering plastic shear**, not a silently reused
tensor invariant. `epsilon_II=|gamma_dot|/2` in this simple-shear control. The 2D
flow rule must preserve that factor and its plastic-multiplier convention.
The smooth inherited strength field has the same physical coordinates on every
mesh. Its presence is an initial geological assumption, not claimed spontaneous
fault nucleation. The control holds temperature/pressure fixed and selects zero
healing. No planetary parameter calibration is inferred from its values.

Use prepared banded Cholesky for the fixed-length operator and a monotone scalar
stress solve. Split off a constant before the linear solve and restore it after:
the exact operator maps constants to themselves. This well-balanced evaluation
prevents filter round-off from acting as an invented inherited weakness in the
uniform softening control; it does not remove genuine material heterogeneity.
This prototype mirrors the existing 1D operator mathematically,
without importing or changing the source-bound package. The full paper/software
comparison distinguishes nonlocal weakening, gradient plasticity, viscoplastic
regularisation and Cosserat models; they are not interchangeable implementations.

**Predeclared checks:** operator second-order convergence; 80/160/320-cell force
and width comparison; 128/256-step endpoint comparison; homogeneous invariance;
physical strength, speed and length sensitivity. Final force and width changes
must be at most 3% in the declared comparisons; that is a feasibility tolerance,
not an accepted geological uncertainty. Keep failures, do not loosen the gate.

**Open before generated boundary acceptance:** 2D mesh-orientation and spatial/time
refinement, material/temperature feedback, physical parameter provenance and a
through-lithosphere separation/rupture criterion. A successful 1D band and the
existing Helmholtz filter cannot close these. Do not optimise boundary bends,
insert a universal critical thickness, or relabel the candidate as a validated
global fault model. D2's rupture decision is also a D6 dependency.

## 5. D3 — Ocean birth, history and recycling

**Contract:** `atlas.spherical-cohort-transactions.v1`. Reuse W06's cohort/finite-
stock semantics; the spherical transport/geometry bridge is new I03/I06 work.
Let n point from left to right across a ridge, and all velocities be in m/s:

```text
b_left  = (v_ridge-v_left) dot n
b_right = (v_right-v_ridge) dot n
dA_birth = (b_left+b_right) dl dt
dM_phase = rho_reference,phase h_reference,phase dA_birth
```

Admit conjugate spreading only when both half-rates are nonnegative and actual
sources exist. Shear creates no area. Ridge migration needs a declared law or
supplied history; equal half-rates are a prescribed option, not a prediction.
Integrate moving segments in space and time; planar length × rate × duration is
only a restricted control. Track actual birth position/time and material path.
Finite rotations preserve spherical trajectories; today's nearest ridge is not
the age origin. Retain continuous birth-time intervals and cohort intersections.

At a trench, `c=(v_down-v_trench) dot n_in > 0` gives incoming area `c dl dt`.
Require polarity, actual intersecting cohorts and named slab/accretion/exterior
destinations. Debit area, reference mass and enthalpy once. Crossing a label or
entering a distance buffer is not consumption physics. Continental arrival invokes
D6 rather than deleting buoyant crust. Formation ages survive plate reassignment.

Unique ownership must cover `4 pi R²`. Ocean birth need not globally equal ocean
consumption when continental deformation/category transfer changes occupied area.
The small control deliberately fixes the other area and prescribes equal sinks;
this is not a production area-renormalisation algorithm. Mass/phase volume and
area have separate balances. All material, hot-birth, basal-heat and water supplies
are finite named accounts; exhaustion refuses the transaction, never clips stocks.

**Control:** staged moving-ridge spherical lune, `A=2R² delta_longitude`, separate
birth/sink/source/heat accounts, finite-stock refusal, material trajectories and
exact age intervals. The opening rate changes: current distance/current rate
would give 4.2 Myr for a parcel actually 4 Myr old. **Later seam checks:**
general moving intersections, one-time debits, rollback, competition for stocks,
shear-only no-birth, heterogeneous exports and arbitrary spherical topology.

## 6. D4 — Enthalpy first, then density and strength

**Contract:** `atlas.cohort-enthalpy-coupling.v1`. Keep restricted analytical
cooling, but never feed a mixed history to it through a mean age.
For the retained constant-property, fixed-thickness hot plate:

```text
T_t = kappa T_zz; T(0,t)=Ts; T(L,t)=Tb; T(z,0)=Tb for z>0
T = Ts+(Tb-Ts)[z/L + (2/pi) sum_n sin(n pi z/L)
                                    exp(-n² pi² kappa age/L²)/n]
C_volume = k/kappa = rho_reference Cp
```

Kelvin, metres and seconds are mandatory. Tb is actual basal temperature, not
mantle potential temperature. Use W03/W06 integrated heat at zero age; the
instantaneous surface flux is singular, not a reason to invent an age floor.
Retain the existing convergence bounds and thermal-account tolerance. Initial
layered continental steady conduction solves `k_i T''+H_i=0` with temperature and
flux continuity; it is an initial condition, not a resetting boundary history.

For new moving heterogeneous control volumes, choose constant-per-material Cp/k
first, with explicit perfect-contact or disjoint-cohort interface treatment:

```text
e_phase = rho_reference Cp (T-T_reference)             [J/m³]
d/dt integral_Omega e dV = -integral_boundary e(v-w) dot n dS
                         +integral_boundary k grad(T) dot n dS
                         +integral_Omega Q dV + named exchanges
```

Mesh velocity w is not material velocity v. Material and heat transfers must share
intersections. Variable conductivity uses the interface resistance; variable Cp
would require its caloric integral. Preserve per-cohort enthalpy/history unless
an explicit mixing law establishes local thermal equilibrium. No averaging of
viscosities or ages to manufacture a compatible W07 input.

Sources are independently owned: birth/advection, basal and external conduction,
radiogenic heat, and any admitted dissipation/latent terms. A no-phase-change,
reduced Boussinesq mode explicitly omits compressional/latent terms; a melt route
cannot inherit those omissions without a new admitted law. Mechanical work is
not automatically all heat. Finite thermal budgets are boundary supply records,
not proof of a self-consistent mantle heat engine.

At the common endpoint derive buoyancy density and D2 properties from the same
material/T state. Thermally varying buoyancy does not change Boussinesq reference
inventory mass. Thermal lithosphere thickness, material thickness and equivalent
elastic thickness Te are distinct; Te needs an explicit bending/rheology closure
or a labelled prescribed value.

**Existing seams:** `PreparedSpreadingCooling`/`PreparedHistoryCooling` own cohort
cooling and finite heat accounts; `PreparedMarginCooling` is stationary conduction.
W07 `PreparedHeatTransport` uses one scalar conductivity/capacity and its advancing
bridge admits uniform translation, not arbitrary deformation or advected damage.
Do not remove these guards. I05 owns the missing heterogeneous/deforming bridge.
Reuse existing component controls after identity/scope checks; new tests cover
two-age mixtures, interface flux, translating enthalpy, variable capacity and
coupled endpoint/time/space error. No component suite rerun is implied by I01.

## 7. D5 — One tectonic surface, datum and water load

**Selection:** `atlas.fixed-datum-support-water.v1`: coarse local Airy support,
with explicitly owned regional mechanical/flexural replacement. The chosen datum
is a fixed compensation-pressure reference plus a declared geometric offset.
It is a modelled tectonic baseline, not a predicted geoid or finished terrain.

Dry column pressure balance is `integral_{z_comp}^{z_surface} rho(z) g dz = P_ref`.
For a constant-density crust of thickness h in mantle rho_m, relative to a named
reference column, `delta_z_dry=(1-rho_c/rho_m) delta_h`, with other column anomaly
loads included once. Thermal excess mass per area Sigma depresses the dry surface
by `Sigma/rho_m` under the same reference. A mechanically resolved buoyancy
contribution replaces, rather than supplements, this reduced response.

For one declared connected, constant-density water reservoir and fixed pressure
datum, let dry bed z0 be upward-positive, downward water-load displacement w,
sea level S, depth d and `beta=1-rho_w/rho_m > 0`:

```text
w = (rho_w/rho_m) d
z = z0-w
d = max(0,S-z) = max(0,S-z0)/beta
sum_j A_j d_j = V_water
```

The density factor converts a level-to-dry-bed gap into depth, **not** into an
extra sea-level rise or an extra thermal-subsidence correction. Solve the monotone
volume equation with an exact piecewise-linear active set. Zero water leaves the
bed unchanged and sea level undefined. A global common level requires declared
communication; isolated inland basins need their own inventories/connectivity.
This reduced mode omits self-gravity, rotation, geoid change and mantle volume
closure. Those are explicit model boundaries, not silently satisfied constraints.
It uses thin-column volume `sum(A*d)`: planetary admission must declare its
geometric tolerance and check a bound such as `2H/R+(H/R)²`, where H bounds bed
and water-surface distance from the reference radius. Exact spherical-shell volume
requires compatible curved-column pressure/geometry, not a silent formula swap.

W04's finite prescribed-water columns instead use dry restoring coefficient
`K=(rho_compensation-rho_air)g`. Their existing water amount is the load: substituting
`rho_m-rho_w` there double counts water created by deflection. Keep prescribed-load
and self-consistent connected-volume modes distinct.

For downward-positive regional isotropic flexure, use the full map-view operator:

```text
dxx[D(wxx+nu*wyy)] + 2*dxy[D(1-nu)*wxy]
                  + dyy[D(wyy+nu*wxx)] + K*w = q
D = E Te³/[12(1-nu²)]                              [N m]
```

For constant D it reduces to `D biharmonic(w)+K w=q`; with variable D, do not drop
the Poisson terms. Existing 1D profiles cannot become a 2D/spherical response by
tiling them. Regional boundaries and exterior loads require sensitivity controls.
Use dry K with explicit water loads in a coupled regional/sea-level iteration;
the local Airy factor cannot multiply a general flexural response.

Regional response replaces a named coarse response: `z=z_base-w_regional+w_coarse`
on an admitted footprint/transition, from the same reference. The transition
mapping must itself be validated, not cosmetically blended after the fact.
At later times apply the change of total equilibrium deflection, not the sum of
successive total deflections. Declared overlap ownership prevents double loading.

**Control:** independent three-cell volume solution, datum shift, cell partition
invariance, zero water and hydrostatic relation. Regional replacement, exterior
sensitivity and variable-rigidity map-view mechanics remain I08 tests; the scalar
water solve does not validate them.

## 8. D6 — Physical events, not label switches

**Contract:** `atlas.regime-transactions.v1`. An event records parent/interval,
trigger law/version, root bracket, footprint, input memory, proposed topology,
conservative intersections, source reservations, output destination and work/heat
ownership. Same-time events sharing material/geometry are one joint proposal or
an explicit refusal; execution order must not change the accepted world.

| Transition | Required physical trigger and transfer | Prohibited shortcut |
| --- | --- | --- |
| Extending continent → separated/exhumed mantle | Admitted through-lithosphere separation law, physical history and bracketed connectivity change | A generic crust-thickness cutoff; pure shear h=h0/stretch never reaches zero at finite stretch |
| Separation → magmatic spreading | Opening plus an actual supplied/melt-derived material and enthalpy source; new cohorts and ridge law | Resetting exposed mantle/thin continental crust to age-zero basalt |
| Ocean entry → supported underthrust/subduction | Actual incoming cohort, polarity and supported fault/slab geometry; bending/interface response and sink ownership | Convergent velocity alone creates an established slab |
| Continental arrival → collision | Composition/connected arrival and compatible mechanics; preserve accreted/underthrust material | Delete continental material through the former ocean sink |
| Transform/oblique regime | Continuous full normal/tangential vectors; regime adapter preserves both components | Angle threshold discards motion or creates uplift/material from pure shear |
| Plate split/merge/retirement or ridge relocation | Shared network and junction closure, compatible velocity/material/history transfer; bracket event time | Recolour cells, smooth a curve, or renormalise areas to hide gaps |

Generated breakup remains **open**. Brune's magma-poor rift result includes
hyperextended continents and mantle exposure, not a universal thin-crust-to-basalt
law. The inspected subduction-initiation experiments likewise do not provide one
universal convergence-distance threshold; initial structure and resisting forces
matter. A prescribed event can exercise transfers but cannot close these physical
generation decisions. Do not silently substitute fully established inherited
subduction for a promised generated initiation experiment.

## 9. Predeclared acceptance and efficiency

Run `python -B tectonics/tools/check_i01_closures.py --output NEW.json` with the
existing scientific environment. It claims its file without overwrite, records
each control failure, binds source/spec bytes before and after, and reports raw
elapsed seconds for the controls after library imports. All four controls must
pass for `PASS_BOUNDED_CONTROLS_ONLY`;
scientific acceptance remains false. Focused tests cover malformed inputs and
analytical/edge cases. No install, native source edit or full world is requested.

| Promised route | Later required acceptance beyond the I01 controls |
| --- | --- |
| Generate | A–H/K in the integration plan; causal D1/D2 response, actual D6 transitions, closed evolving full sphere and withheld seeds |
| Inspect | Actual saved fields, matched units/time/datum, no display-only physical geometry |
| Continue | Full material/thermal/mechanical memory, exact parent/source dependencies, interrupted commit and resumed/direct parity |
| Change deliberately | Relevant dependency invalidation, explicit successor, unchanged display inputs reuse state |
| Consume | Same endpoint/frame/support, conserved area/mass/heat transfers and actual downstream native consumer |

No global acceptance seeds/tolerances are selected by looking at these tiny
controls. Freeze later H/K scenarios and physical horizon before those runs.
Preserve all existing W and R4.4 holds and tolerance requirements.

Implementation efficiency is designed in: D1 assembles only 3P rotational unknowns
plus admitted regional responses; geometry/drag changes invalidate its operators.
D2 uses linear-storage banded factors and retains current raw history, not a copy
per inspection. D3 stores cohort/event intervals, not particles per display pixel.
D4 reuses thermal bases only for unchanged coefficients/support. D5 sorting is
O(N log N), with O(N) active-set work; changing elevations invalidates the wet set.
Ordered physical time remains serial; independent controls/regions may run within
the existing resource policy. These are complexity/ownership choices, not measured
whole-generator speedup claims. Raw control timings are feasibility observations.

## 10. Papers/software actually checked for this continuation

| Primary reference | Inspection and decision it informs |
| --- | --- |
| [Clennett et al. 2023](https://adamfholt.github.io/documents/papers/clennett_et_al_scirep2023.pdf) | Force-calculation pp. 4–6/equations 1–8 read; earlier checkpoint includes supplied supplement. Reduced torque accounting informs D1; forward prediction and history-dependent slab inventory here are Atlas extensions. Publisher/PMC pages were inaccessible; author copy used. |
| [Duretz et al. 2023](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022GC010675) and [PTsolvers source repository](https://github.com/PTsolvers/PlasticityRegularisations_G3) | Model/regularisation and single-band comparisons inspected; software overview, not a reproduced code run. Supports separating time/space regularisation and testing width/strength refinement. The Atlas Helmholtz-weakening control is not their Cosserat model. |
| [ASPECT continental extension](https://aspect-documentation.readthedocs.io/en/latest/user/cookbooks/cookbooks/continental_extension/doc/continental_extension.html) | Inherited plastic strain, geotherm, parameter conventions and stated breakup limitation inspected. No installation or ASPECT run. |
| [Karlsen et al. 2019](https://arxiv.org/html/1910.03351v1) and [GPlately SeafloorGrid](https://gplates.github.io/gplately/latest/sphinx/html/generated/gplately.SeafloorGrid.html) | Tracer/birth/transport methods and initial-age/deletion limitations inspected. Kinematic reconstruction informs D3 history separation, not conservative mantle/sink physics. |
| [Richards et al. 2018](https://freddrichards.github.io/documents/papers/richards_etal_2018_jgr.pdf) | Thermal equations, sections 4–5.2.2 and selected section 6 discussion. Supports distinguishing thermal models and independent depth/heat constraints; its full calibrated model is not imported. |
| [Brune et al. 2014](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf) | Results and thermal/numerical/melt Methods, not supplement. Motivates separate hyperextension, mantle exposure and new crust supply in D6. |
| [Wickert 2016](https://gmd.copernicus.org/articles/9/997/2016/) and [gFlex theory](https://gflex.readthedocs.io/en/latest/theory_and_numerics.html) | Finite-difference flexure, boundary conditions and full variable-rigidity operator inform D5; local/spherical validity remains distinct. No gFlex run or copied implementation. |
| [Schachtschneider et al. 2022](https://npg.copernicus.org/articles/29/53/2022/) and [Vishwakarma et al. 2020](https://repository.tudelft.nl/file/File_5f73435a-239a-4d25-b273-ae025f5000b5) | Sea-level/ocean-mask equations and moving-bed volume distinctions inspected (Appendix B and section 2 respectively). D5's scalar level/fixed-pressure datum is an explicit reduction, not their full gravitational sea-level model. |
| [Gurnis, Hall and Lavier 2004](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2003GC000681) | Formulation/discussion checked here; checkpoint reports earlier full reading. Initiation depends on structure, bending and weakening, not a universal scalar trigger. |

Forsyth & Uyeda (1975) and pyGPlates net-rotation reading are retained in the
previous research checkpoint, not claimed as independently reread here. Existing
Atlas method contracts were inspected where reused; their scientific evidence
was not rerun or silently reclassified. No externally supplied software was
installed, vendored or used to generate a claimed new world.
