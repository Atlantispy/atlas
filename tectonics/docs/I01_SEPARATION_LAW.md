# I01 MC-01: cohesion-loss separation law (selected candidate; MC-01 stays open)

**28 September 2026. WORKING NON-CANON. A research decision with a prepared local control slice. It is not an
admitted separation mechanism, a resolved neck, an event certificate, a plate split or physical acceptance.**

This record answers the next separation step named by the
[closure matrix](I01_CLOSURE_MATRIX.md#6-separation-rules-open-choices-and-the-next-assignment) and the
[separation decision](I01_SEPARATION_DECISION.md): which route of the bounded-rate argument can make stretched
lithosphere separate, while keeping elastic memory and the actual material accounts.

The [case](../cases/i01_separation_law_v1.json), [tool](../tools/check_i01_separation_law.py) and
[focused tests](../tests/test_i01_separation_law.py) are new. **None of their checks has been executed**
(section 11).

The following are unchanged:

- the contract, transitions, breakup, basal, separation-decision and matrix records;
- every existing tool and receipt, and the evidence register;
- the reader chapter and the native package.

Wording corrections proposed for review are in section 10; none has been applied.

## 1. The decision in plain language

Rock that flows can be stretched extremely thin and still be one connected piece. While its velocity stays smooth,
a continuous motion cannot tear it apart
([matrix §6.1(4)](I01_CLOSURE_MATRIX.md#61-rules-for-any-separation-claim)).

Cold, frictional rock behaves differently: it *breaks*. Along a fault, the bonds that held the rock together are
destroyed. The two sides still touch, press on each other and resist sliding by friction, but they are no longer
one bonded body. No material has been deleted, and no empty gap has opened.

Atlas therefore selects **loss of bonded connectivity through admitted cohesion loss**
(`atlas.cohesion-loss-separation.v1`) as MC-01's candidate mechanism for plastic-dominated or brittle lithosphere.

- **When a point loses its bond.** All three conditions must hold:
  - its strength-controlling plastic history has completed the declared D2 softening;
  - the law's provenance says that the completed state is sliding on a broken (cohesionless) surface;
  - its temperature and effective pressure lie inside the declared range of that evidence.

  Creep and elastic loading never remove cohesion, so flowing (ductile) mantle cannot "fracture" under this law.
- **When a section separates.** No bonded path joins the two predeclared anchors. Crust, mantle lithosphere and the
  two together are checked separately. Touching across a broken surface is not a bond; a bonded film of any
  positive thickness is one.
- **What cannot decide it.** Thickness, cell fraction, an empty gap, a detection level and ladder extrapolation play
  no part. The only threshold is the completion of the softening law itself, the same parameter that sets the
  rock's strength. Its influence is a physical sensitivity to report, not a setting to tune.

The breaking energy is not a universal constant. It follows from the same softening law, the local pressure and a
physical shear-zone width. It does not change under grid refinement, because that width is a declared physical
length, not a number of cells.

**What this supplies:** a research decision and a prerequisite. The prerequisite is the bond-state rule, the
equivalent strength and energy of a band, and exact local controls that keep elastic memory.

**What it does not supply:** an admitted mechanism. MC-01 stays open until the resolved comparison of section 9
passes. No event, split transaction, ocean birth or generated boundary follows from this document.

## 2. The three routes compared

| Route (matrix §6.1(4)) | What it would need here | Status for the retained lithosphere | Decision |
| --- | --- | --- | --- |
| Finite-time singularity | A pinch-off proved from the declared laws' asymptotics | Only the constant-exponent power-law long-wave chain has one ([breakup §§4–5](I01_BREAKUP_CLOSURE.md#4-when-does-necking-separate-the-invariant-and-the-criterion)). The retained law mixes creep with regularised plasticity. Its high-stress asymptote lies outside the coefficients' support ([breakup §6](I01_BREAKUP_CLOSURE.md#6-brittle-plastic-dominated-and-fixed-width-necks-are-refused)). The long-wave assumption fails for n > 4. No result for a resolved visco-elasto-plastic neck with a free surface was found or derived | Not admissible for MC-01. It remains the ductile chain's feasibility result |
| Change of state or composition | Melting with extraction, or an admitted reclassification with its accounts | Melt supply is MC-03, which is open and owned separately. Reclassifying mantle lithosphere as asthenosphere needs an I05 producer law, which is not selected. It could not remove a crustal bridge anyway. Pore-fluid and hydration routes are unowned (UR-07) | Not selected |
| **Failure law that creates a discontinuity** | An admitted constitutive failure with physical inputs, support and energy | Frictional-plastic rock loses cohesion. Resolved geodynamic models already represent faulting by cohesion softening (Lavier et al. 2000, eq. 2). Brune et al. (2014) describe crustal break-up by faults that cut embrittled crust into the mantle | **Selected**, as a cohesion (bond) discontinuity |

**Why this route fits the regime.** MC-01 concerns plastic-dominated or brittle lithosphere, which deforms by fracture
and frictional sliding. That is where rocks physically lose cohesion. The law adds no physics beyond the D2
softening that Atlas already carries (IN-04 inputs). It gives the softening's residual state a stated physical
meaning, and it refuses to give that meaning to creep.

**Consistency with the bounded-rate argument.** That argument concerns the connectivity of the material *point set*
under continuous, invertible motion, and it still holds. Cohesion loss changes the material's *bond state*. It does
so without a velocity discontinuity at the resolved scale and without deleting any material.

When a band is thinner than the grid, the same law may be represented as a closed frictional contact with a
displacement jump, the fault representation used by PyLith (section 7). Across such a surface the argument's
bounded-gradient premise does not hold, by construction.

## 3. The law, with units

### 3.1 Strength and its softening

The retained D2 plane-strain convention
([contract §4](I01_PHYSICAL_CONTRACT.md#4-d2--strength-and-physical-length-localisation), [column](I01_COLUMN.md)):

```text
P_eff = max(P_hydrostatic + P_dynamic - P_pore, 0)                          [Pa]
Y0 = C0 cos(phi0) + P_eff sin(phi0),   Yr = Cr cos(phir) + P_eff sin(phir)   [Pa]
Y(kappa) = Y0 - (Y0 - Yr) min(kappa/kappa_c, 1)                              [Pa]
```

`kappa` is the history that controls strength:

- in a resolved field, D2's filtered history `kappa_bar`;
- in a uniform band, the raw engineering plastic shear.

Linear saturation is the form of the retained 1D control. Peak strength must exceed residual strength everywhere in
the declared support; otherwise the law is refused.

### 3.2 A band of physical width and its slip-weakening equivalent

Take a uniform band of declared physical width `w_s` [m] in simple shear. It follows the retained composite law, in
which the creep and plastic rates add at one stress:

```text
gamma_dot = 2 e_creep(tau) + max(tau - Y(kappa), 0)/eta_p        [1/s]
kappa_dot = max(tau - Y(kappa), 0)/eta_p                         (no healing in the local slice)
band slip rate = w_s gamma_dot,   plastic slip delta_p = w_s kappa   [m]
```

In the rate-independent limit (`eta_p -> 0`, no creep), the band is a linear slip-weakening surface:

```text
tau = Y(delta_p / w_s)                  falls from Y0 to Yr over the breakdown slip
D_c = kappa_c w_s                        [m]
G(P_eff) = (Y0 - Yr) D_c / 2             [J/m2]   breakdown energy per unit band area
k_soft = (Y0 - Yr) / D_c                 [Pa/m]   softening stiffness
```

`D_c` is Lavier et al.'s characteristic offset `Delta x_c = epsilon_c Delta w`, with a physical width in place of
their width of 2–4 grid cells.

`G` is the area between the stress–slip curve and the residual line: the Palmer–Rice shear fracture energy, as
restated by Fei & Choo (their Fig. 1, `G_II = J_p - tau_r delta_p`). Palmer & Rice (1973) itself was not
accessible. Wherever friction softens, `G` depends on `P_eff`, so it is derived, never a universal constant (UR-07).

### 3.3 The bond state

```text
BONDED      kappa = 0                                   no plastic history: creep and elasticity keep cohesion
UNRESOLVED  kappa > 0 and (T, P_eff) outside support    plastic history beyond the reach of the cohesion-loss evidence
BROKEN      residual_state = broken_surface_sliding, kappa >= kappa_c, inside support
BONDED      otherwise                                   partly softened, or residual declared as weakened intact rock
```

The state uses the *current* strength-controlling history. Healing `h(T)` that lowers this history therefore
re-bonds the material; coupled healing belongs to I07. A residual declared as `weakened_intact`, for example a
cohesion merely divided by a factor, never breaks.

### 3.4 Section connectivity and interval records

**Cell and contact states.**

- Tracked cells are `BONDED`, `BROKEN` or `UNRESOLVED`.
- Contacts between cells are `WELDED`, `COHESIONLESS` (an admitted sub-resolution surface) or `UNRESOLVED`.

**Bonded paths.** A bonded path joins `BONDED` cells of the selected materials across `WELDED` contacts. Crust,
mantle lithosphere and their union are assessed separately. Each assessment runs between predeclared anchors, which
must themselves be intact.

**Unresolved states** are evaluated both ways:

- `CONNECTED` only if the anchors stay connected when every unresolved state counts as broken;
- `DISCONNECTED` only if they stay disconnected when every unresolved state counts as bonded;
- `UNRESOLVED` otherwise.

**Point-set connectivity**, which uses every cell and contact, is reported beside the bonded result. It is the
reading questioned in section 10, and it never decides an event.

Across one interval:

| Union: before → after | Record |
| --- | --- |
| CONNECTED → DISCONNECTED | `BRACKETED_UNION_LOSS`, for this section only. A proposal that still needs the checks of section 9, along-strike coverage, the handoff comparison and I02's commit |
| DISCONNECTED → DISCONNECTED | `INHERITED_DISCONNECTION`, not an event |
| DISCONNECTED → CONNECTED | `RECONNECTED`, for example after healing |
| Either one UNRESOLVED | `UNRESOLVED` |
| CONNECTED → CONNECTED | `NO_UNION_EVENT` |

A crust change from CONNECTED to DISCONNECTED is reported separately, only as the crustal milestone. No record
authorises a plate split.

### 3.5 The surface form and objectivity

A band thinner than the grid may be represented as a closed contact with unit normal `n` and tangent `m` (`n` turned
by +90°):

```text
t = sigma n;   tau = |t.m|;   P_eff = max(-t.n - P_pore, 0);   slip = |[u].m|;   opening [u].n = 0
```

In the isochoric simple-shear state of the band, the in-plane normal deviatoric stresses vanish. So `-t.n` equals
the mean pressure, and this surface form is exactly the band's law. In the retained convention its friction
coefficient is `sin(phi)` and its cohesion is `C cos(phi)`.

Every quantity is a scalar formed from vectors in the surface's own frame, so a superposed rigid rotation changes
none of them. Opening is refused, because a void, fluid or magma filling would need accounts that no owner supplies.

### 3.6 Which lengths stay fixed under refinement

| Quantity | Meaning | N → 2N and Δt → Δt/2 | Physical sensitivity |
| --- | --- | --- | --- |
| Grid spacing `h` | Numerical | Varied | None |
| D2 length `ell` | Declared physical/regularisation length of the resolved band (IN-04) | Fixed | Labelled `ell` sensitivity |
| Shear-zone width `w_s` | Physical width of the band the law represents | Fixed | Halved and doubled |
| `D_c = kappa_c w_s` | Breakdown slip | Fixed | Follows `w_s` and `kappa_c` |
| `kappa_c`, `C`, `phi`, `eta_p` | Softening and regularisation inputs | Fixed | Each reported |
| Neck and plastic widths | NA-01 participation diagnostics | Results | Reported |
| Fracture regularisation length | None: no phase-field length is introduced | Not applicable | Not applicable |

**No mesh-dependent loss of toughness.** Lavier et al. report that "the width of the fault Δw is consistently 2 to 4
times the grid size". If the band width were tied to the grid in that way while `kappa_c` stayed fixed, `D_c` and
`G` would halve with every halving of the grid. Lavier et al. compensate by holding `Delta x_c` fixed. Atlas instead
requires a physical `w_s` and refuses any grid-based width.

The width also decides the regime. For Newtonian band creep, the steady creep traction is `eta_v V / w_s`. A width
tied to the grid would therefore make brittleness itself depend on the mesh.

## 4. Regimes, exclusions and the precise remaining obstruction

- **Frictional material inside the support:** the law applies.
- **Material deforming by creep:** its plastic history stays zero, so it stays bonded under any loading.
- **Plastic history outside the declared support:** for example, a pressure-dependent yield cap reached in hot or
  deep mantle, where no evidence shows cohesion loss by cataclasis. Its bond state is `UNRESOLVED`, so no event is
  available.
- **Refused or unowned (UR-07):** tensile opening, a universal fracture energy, and pore-fluid- or magma-assisted
  breakup. No contact opening is admitted.
- **Mixed necks: the obstruction.** A broken upper lithosphere above bonded, creeping lower lithosphere keeps the
  union connected, so only the crustal milestone can follow. Separating such a neck through the whole lithosphere
  needs one of two things that the current contract does not supply:
  - the resolved evolution bringing all the remaining lithosphere into the law's frictional support, by embrittlement
    through cooling, thinning or faster strain; or
  - an admitted I05 law, with its accounts, that reclassifies the lower lithosphere.

  The retained column is mixed in this way at its sampled states. The breakup closure calls it plastic-dominated
  there ([breakup §§1, 6](I01_BREAKUP_CLOSURE.md#6-brittle-plastic-dominated-and-fixed-width-necks-are-refused)),
  and its reviewed plastic work share of 0.550579 is recorded in
  [the current state](../../docs/CURRENT_STATE.md), so creep still carries much of the work.
- **Missing inputs: also an obstruction.** The retained D2 fixture values come from the ASPECT cookbook: 20 MPa
  cohesion and 30° friction, each weakened by a factor of 4. They carry no residual-state semantics and no
  cohesion-loss support. Under this law their plastic history therefore remains `UNRESOLVED` until IN-04 supplies
  both. No default is invented.

**The smallest necessary decision, for the owner and Codex:**

1. Adopt bonded connectivity as the meaning of "material connection" in the separation diagnostics (the wording of
   section 10).
2. Add three declared inputs to IN-04:
   - the residual-state semantics, with provenance;
   - the cohesion-loss support in temperature and effective pressure;
   - the physical shear-zone width and its basis. This one is already requested by
     [transitions §11](I01_TRANSITIONS.md#11-mechanical-inputs-a-rupture-or-initiation-law-needs-from-d2), item 3.

## 5. Elastic memory, work, heat and material accounts

- **Memory is kept.** Stored stress is carried through yield, softening and bond loss; nothing resets. At the instant
  of bond loss the traction is continuous. A sub-resolution surface carries equal and opposite tractions
  (Aagaard et al. 2013, §2), and the bulk keeps its stress with the selected logarithmic-objective direction
  ([elastic memory](I01_ELASTIC_MEMORY.md)).
- **Work.** Per unit band area, `W_ext = Delta E_elastic + D_creep + D_plastic`. The plastic dissipation `D_plastic`
  has three parts:
  - the realised breakdown, which reaches `G` at completion;
  - residual friction, `Yr delta_p`;
  - viscoplastic overstress.

  Each part is computed independently; none is a residual.
- **Heat.** All dissipation goes to D4's conversion rule (IN-05). A change in stored elastic energy is never heat.
- **Unstable softening.** When the stiffness of the surroundings is below `k_soft`, the rate-independent limit has no
  quasi-static path, and the breakdown would be dynamic. The declared `eta_p` turns it into a transient of finite
  rate. Its timing and energy partition depend on `eta_p`, which must be reported as a sensitivity. Inertia and
  radiated energy are not modelled here.
- **Material.** Nothing is deleted. The bond state is derived from transported history, so I05 carries `kappa_bar` and
  one support-violation flag per cohort. If a sub-resolution surface replaces a band, the band's inventory (`w_s`
  times length, per unit strike) goes to the declared sides by current material position, with its stress and
  history. This follows the [transitions §3](I01_TRANSITIONS.md#3-continental-separation-atlasrift-decoupling-handoffv1)
  split rule. The D6 transfers and MC-04's basal accounts are unchanged.

## 6. The executable local slice (prepared, not run)

The tool is outside every source-bound package and imports no retained tool. It reads the retained separation-decision
case only for the negative example, and it binds that case before and after execution.

1. **`SofteningLaw`** validates its inputs and returns:
   - the peak and residual yields, `D_c`, `G` and `k_soft`;
   - the strength at a given history;
   - the bond state of section 3.3.
2. **`Loading`, `State` and `Prepared.advance`** integrate one band exactly. An elastic surroundings spring of stiffness
   `k` [Pa/m] loads the band at the far-field rate `V` [m/s] and keeps the stored traction. Optional Newtonian band
   creep `eta_v` and the viscoplastic plastic branch act in series:

   ```text
   tau_dot   = k V - (k w_s/eta_v) tau - (k w_s/eta_p) max(tau - Y(kappa), 0)
   kappa_dot = max(tau - Y(kappa), 0)/eta_p
   ```

   **Phases.** Each of the three phases (sub-yield, softening, residual) is linear: `x' = B x + c` for
   `x = (tau, kappa)`. Its eigenvalues `m ± q` are real, with `q ≥ |m|`, because `det B ≤ 0`.

   **Exact solution.** With `v = B x0 + c`,

   ```text
   x(t) = x0 + J1(t) v + J2(t) (B - mI) v
   J1 = ∫ e^{ms} cosh(qs) ds,   J2 = ∫ e^{ms} sinh(qs)/q ds
   ```

   Both integrals use a series without cancellation when `qt ≤ 0.5`, and `expm1` forms otherwise.

   **Events and accounts.**
   - Yield, cohesion loss and unloading are bracketed on monotone pieces, to a relative width of 1e-13. Each event
     records its traction and the cumulative accounts at that instant.
   - Work and the creep, plastic and overstress dissipations are 16-point Gauss–Legendre integrals of the exact
     solution. The stored-energy change `(tau1^2 - tau0^2)/(2k)` and the breakdown and residual-friction parts are
     closed forms.
   - Two balances are checked to 1e-10: work against stored energy plus dissipation, and plastic dissipation against
     its three parts. No dissipation is ever set as the residual of a balance.
3. **`rate_independent_reference`** gives the `eta_p -> 0` limit without creep: the loading displacement at
   completion, `G`, and the energy excess that an unstable path would release.
4. **`surface_projection`** returns the objective scalars of section 3.5 and refuses opening.
5. **`connectivity`, `section_diagnostics` and `classify_interval`** implement section 3.4.
6. **`negative_example_thickness`** is the exact field of
   [separation decision §5](I01_SEPARATION_DECISION.md#5-required-refusal-example-and-comparison-plan). No law or
   connectivity function reads a thickness.

**Cost.** Each band keeps an O(1) state of traction, history and time, with no growing history. Each exact segment
uses at most 150 quadrature sub-intervals, and one immutable preparation serves each pairing of law and loading.
There is no dense matrix, iterative solver, worker process or cache.

The campaign has a 60-second cooperative budget after imports. It writes its output exclusively and binds its sources
before and after execution. Timing compares matched arms that reuse and rebuild the preparation, and reports raw
seconds only.

## 7. Sources

| Source | Parts inspected | Used for; limit |
| --- | --- | --- |
| [Lavier, Buck & Poliakov (2000)](https://www.ldeo.columbia.edu/~buck/Publications_files/2000Lavier,BuckPoliakov%28factors%29JGR.pdf), JGR 105(B10):23431–23442, author-hosted scan | All 12 pages: §3.1, eqs. (1)–(2) and the characteristic offset (pp. 23,433–23,434); the 4 MPa residual cohesion kept to avoid numerical instabilities (p. 23,434); Table 1; §5, eqs. (3)–(4); §§6.2–6.3 | The resolved geodynamic fault approach: faults are localised bands of elastic-plastic material whose cohesion falls linearly with plastic strain. "When the plastic strain reaches ε_c, the fault is cohesionless". Band width is 2–4 grid cells, compensated by fixing `Δx_c = ε_c Δw`. Their layer floats on an inviscid fluid, so the paper says nothing about ductile lower lithosphere. Its parameters are not Atlas inputs |
| [Aagaard, Knepley & Williams (2013)](https://arxiv.org/abs/1308.5846), JGR 118, arXiv v1 | §§1–4.2 and eqs. (1)–(56): eq. (4), slip as a displacement jump; Lagrange multipliers as equal and opposite fault tractions (§2); friction bounds and iteration (§2.5); eq. (40) and fault opening at zero traction; cohesive cells inserted along a prescribed fault surface (§3) | The discontinuity representation used by geodynamic software. It needs the fault surface in the mesh beforehand, so it cannot choose a breakup path. It informs the sub-resolution surface form and traction continuity; it is not a separation criterion |
| [PyLith documentation, Fault Interface Conditions](https://pylith.readthedocs.io/en/stable/user/physics/faults/), stable build | The page, as returned by a summarising fetch that quoted its statements; the raw page was not inspected line by line | Zero-thickness cohesive cells along predefined fault vertices; slip forced to zero at buried edges; "Spontaneous rupture is not available in PyLith v3.0+". Documentation only; the software was not run |
| [Fei & Choo (2020)](https://arxiv.org/abs/2003.04779), arXiv v3 | §§1–2.4, Remarks 1–6 and eqs. (1)–(51), pp. 1–14 | Phase-field shear fracture. It restates the Palmer–Rice energy (Fig. 1). A broken interface carries residual friction (eqs. 10–14). Its formulation is insensitive to the phase-field length (eqs. 46–47), and eq. (50) gives the process-zone size. The authors note that `G_II` "depends heavily on the amount of slip", with further changes from normal stress and temperature, yet they prescribe a constant. The model is quasi-brittle, with small strain and no plasticity. Used for length-insensitivity; its constant `G_II` is the universal energy that Atlas refuses |
| [Brune et al. (2014)](https://www.earthbyte.org/Resources/Pdf/Brune_etal_2014_Rift_migration.pdf) | Reused from the [breakup closure](I01_BREAKUP_CLOSURE.md#11-sources) reading; not reread | Crustal break-up by faults penetrating embrittled crust into the mantle; break-up read from the resolved geometry |
| ASPECT continental-extension cookbook, parameter file and `strain_dependent.cc` | Reused from the breakup and [weakening](I01_WEAKENING.md) records; not reread | Continuum strain weakening, with cohesion and friction each divided by 4 between plastic strains 0.5 and 1.5. It is local memory, not a separation law, and its residual keeps cohesion |
| Duretz et al. (2023) and PTsolvers | Reused from the [2D fault record](I01_FAULT2D.md); not reread | Separate time and space regularisation; refinement at a fixed length |
| Hutchinson & Neale (1977); Audoly & Hutchinson (2019) | Reused from the breakup closure; not reread | Route 1: long-wave pinch-off of fixed power laws |

**Not accessible and not used as authority:**

- Palmer & Rice (1973, Proc. R. Soc. A 332:527): the author-hosted PDF failed a TLS certificate check. Its content is
  used only as restated by Fei & Choo.
- Bažant & Oh (1983), crack-band theory: the host's certificate had expired.
- Simo, Oliver & Armero (1993): repository access is restricted; only the abstract was seen.
- Sibson (1977), fault-rock classification: HTTP 403.
- Huismans & Beaumont (2011): still not accessed (matrix §7).

No external software was installed or run.

**Repository sources read for this record:**

- `AGENTS.md`, `CLAUDE.md` and `docs/CODING_SAFETY.md`;
- the current checkpoint in `docs/CURRENT_STATE.md`;
- matrix §§5–7, with the case items MC-01 and `separation`;
- the separation decision and its case;
- contract §§4, 8 and 10;
- elastic memory in full;
- breakup §§1–14;
- basal §§1–3;
- column and 2D fault in full;
- transitions §§3, 10 and 11;
- as implementation patterns only: the elastic-memory and elastic-core tools, the retained column `LocalLaw` and the
  1D shear control in `check_i01_closures.py`.

## 8. What each prepared check would establish

These are expectations fixed before any run, not results.

- **Closed-form law values.** Strengths, breakdown slip and energy equal their equations. When friction softens,
  the energy grows with pressure, so it cannot be a universal constant.
- **Kept memory.**
  - A stored traction `tau0` brings failure forward by exactly `tau0/(k V)`, so resetting it would move the failure
    time.
  - Across bond loss, the traction follows the exact continuous path.
- **Closed-form completion.** The exact phase integration matches independently derived scalar equations in both a
  stable and an unstable configuration, so the event bracket is not a numerical artefact.
- **Energy.** Realised breakdown equals `G`, residual friction equals `Yr D_c`, and both balances close. No energy
  appears or disappears when cohesion is lost.
- **Subdivision.** Splitting the interval changes neither the event time nor the accounts. This is the time
  refinement of an exact kernel.
- **Rate-independent limit.** As `eta_p` falls, completion approaches the rate-independent answer, with the
  regularisation lag `eta_p/(k w_s - s)`.
- **Creep regime and width.**
  - A creeping band never yields and stays bonded.
  - The same band, declared ten times narrower, yields at its closed-form time. The physical width sets the regime.
- **Independent integration.** An explicit Runge–Kutta integration in the tests checks the cases with creep, which
  have no closed form.
- **Objectivity.** Surface scalars are unchanged under rotation, and an opening jump is refused.
- **Connectivity.** Bonded and point-set connectivity disagree exactly where section 10 says the wording is ambiguous.
  Alternating, unresolved and inherited cases give their required records.
- **Negative example.** The exact positive-thickness film stays connected at every ladder opening and at the false
  limit. A supplied thickness field is refused.
- **Refusals and reuse.** Grid-based widths, missing provenance, no softening, healing, reverse loading,
  out-of-support states, broken anchors and opening are refused. A reused preparation gives results identical to a
  rebuilt one.

**What these checks cannot show:** that any resolved neck, or the retained lithosphere, separates; that any parameter
is realistic; or that the diagnostics converge in a resolved field.

## 9. The exact next resolved comparison (predeclared; not implemented)

The owner is I07, with I05 transport and I02 persistence. The same fields are frozen in the case under
`unimplemented_resolved_comparison`.

**Configuration.** The retained lithosphere as one resolved plane-strain x–z neck, with:

- retained composite creep, within its coefficient support;
- the D2 elements of contract §4: plane-strain yield with absolute `P_eff`, linear softening of `Y` in `kappa_bar`
  to a declared residual, `eta_p`, the Helmholtz length `ell`, transported raw `kappa` and `h(T)`;
- a free surface and owned shear heating;
- kept elastic stress, with the logarithmic-objective direction;
- MC-04's basal closure;
- this law's bond state, with declared semantics, support and physical `w_s`.

**Inputs required before execution:**

- the three IN-04 additions of section 4, with provenance;
- material anchors and a candidate footprint, declared before any run;
- the horizon, and the cost budget declared by I07.

**Resolutions.**

- `N` and `2N` cells at fixed `ell`, with at least 4 and 8 cells per `ell` across the band;
- time steps `Δt` and `Δt/2` on the finer grid;
- identical anchors, support and law throughout.

**Separately labelled physical sensitivities:**

- `ell` doubled;
- `w_s`, and hence `D_c`, halved and doubled;
- `kappa_c` and `eta_p`;
- the basal depth of MC-04.

**Diagnostics.**

- Bonded connectivity of crust, mantle lithosphere and union, with point-set connectivity beside it.
- Surface-to-base connectivity of the weak zone.
- The bracket of union loss.
- Ranges of `T`, `P_eff`, strain rate, stress and elastic memory against the declared support along the whole
  approach.
- The traction–slip response measured on the band, and the breakdown energy it realises, compared with the local law
  using the plastic participation width.
- Neck and plastic widths, and the section resultant `S` of NA-01.
- Energy accounts: work, stored energy, dissipation by part, and heat.
- The negative example, passed through the same admission logic.

**Tolerances (feasibility only, fixed now):**

- The union-loss brackets must overlap. Their midpoints in time and opening may differ by at most 3% between `N` and
  `2N`, and between `Δt` and `Δt/2`.
- The realised breakdown energy per unit band length may differ by at most 3% between `N` and `2N`.

These reuse the retained 3% D2 mesh and time gates (`i01_closures_v1` and `i01_fault2d_v1`). They are not geological
uncertainty.

Account closure is predeclared by I07 from its solver tolerances, as MC-04 requires. Two requirements are exact:
every broken cell lies inside the support along the approach, and the negative example is refused.

**Acceptance.** A mechanism is admitted only if all of these hold:

- the event converges as above;
- no threshold other than the constitutive completion enters, and the physical sensitivities are reported;
- the state stays inside the support;
- the negative example is refused;
- the replacement belt meets `E_v ≤ eps_v` over the history window
  ([separation decision §4](I01_SEPARATION_DECISION.md#4-mechanical-handoff-compare-solutions-over-time)).

`eps_v` is I02's and is currently null, so acceptance cannot complete yet. If no configuration passes, the route stays
blocked, and only the owner can reclassify it.

## 10. Wording corrections proposed for review (not applied)

The current diagnostics can be read as connectivity of a *point set*. Under that reading, two intact blocks cut by
an admitted cohesionless fault still touch, so they count as connected. No fault could then ever separate them:
separation would have to wait for deleted material or an empty gap, which both the contract and the constraints
forbid. The tool's `cohesionless_surface` and `broken_band` sections demonstrate this. Both are point-set CONNECTED
but bonded DISCONNECTED.

1. [Separation decision §2](I01_SEPARATION_DECISION.md#2-material-and-geometry-before-a-threshold), third paragraph.
   - Current: "Assess paths through reconstructed material in the declared domain, including interfaces and possible
     paths round the candidate cut."
   - Proposed: "Assess bonded paths through reconstructed material in the declared domain, including possible paths
     round the candidate cut. A path may cross a welded material interface, such as crust to mantle. It may not cross
     material, or a surface, whose admitted law has removed its cohesion. Contact across an admitted cohesionless
     surface is not a material connection; a bonded film of any positive thickness is one."
2. Separation decision §1 table.
   - "removes the last resolved crustal material connection" becomes "removes the last resolved bonded crustal
     connection".
   - "loss of the relevant material connection" becomes "loss of the relevant bonded material connection".
3. [Breakup §1](I01_BREAKUP_CLOSURE.md#1-the-question-and-the-answer-in-plain-language), item 2.
   - Current: "The continental material joining the two sides thins to nothing somewhere."
   - Proposed addition: "This applies to the reduced necking chain. An admitted cohesion-loss law can instead remove
     the bond without zero thickness or an empty gap (I01_SEPARATION_LAW)."
4. Matrix §6.1(4), and the matrix case's `separation.bounded_rate_argument.statement`.
   - Current: "a connected material set therefore stays connected".
   - Proposed: "a connected material point set therefore stays connected; its bonded connectivity can still change
     through an admitted failure law that removes cohesion without a velocity discontinuity".
5. Contract §8, first D6 row. This file is source-bound, so the change is an owner decision.
   - "bracketed connectivity change" becomes "bracketed bonded-connectivity change".

## 11. Commands and status

From the repository root, with the existing scientific environment:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_separation_law.py -v
python -B tectonics/tools/check_i01_separation_law.py --output NEW_PATH.json
python -B tools/check_public_paths.py
python -B tools/check_coding_safety.py
```

**Status.** Nothing has been executed: no test, campaign or static check. There is no receipt, and the evidence
register is unchanged.

The campaign would write its output exclusively and bind the four new files and the retained separation-decision
case and method before and after execution. It records `scientific_acceptance: false` and reports raw timings only.
Any reviewed receipt belongs in the [current evidence register](../../docs/CURRENT_EVIDENCE.md), not here.

## 12. Remaining blockers and the smallest next step

**Blockers:**

1. The resolved I07 comparison of section 9 does not exist.
2. The IN-04 semantics, support and physical `w_s` are absent for the retained inputs.
3. The lower lithosphere of mixed necks needs an owner decision: embrittlement within the resolved route, or an
   admitted I05 reclassification.
4. I02 has not supplied `eps_v`.
5. Along-strike and exterior coverage belong to I03/I07.
6. The sensitivity to `eta_p` where `k < k_soft` must be reported.
7. Coupled healing belongs to I07.

**Smallest next step.** Codex runs the focused tests and the bounded campaign. If they pass and review accepts the
rule, the owner decides on the section 10 wording and the IN-04 additions. I07 then prepares the resolved case of
section 9 with declared inputs. MC-01 remains open throughout.
