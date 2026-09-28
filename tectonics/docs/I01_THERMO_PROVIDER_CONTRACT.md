# I01 common thermodynamic provider: connection contract

**WORKING NON-CANON — common-provider contract and experimental Gibbs connection.**
MC-03 remains open. Sections 1–7 specify the connection; section 8 records the
implemented bounded route and its acceptance limits. No retained solver,
historical evidence, W08 law or release default changes.

## 1. What crosses the connection

Melting, removing liquid and receiving magma must agree on what the material is
and what its energy means. A melt fraction or temperature alone cannot carry that
information. The provider determines equilibrium properties; extraction, movement,
heat exchange and persistent transaction ownership remain separate processes.

The names below describe proposed records, not existing public Python classes:

| Record | Required meaning |
| --- | --- |
| `ProviderDefinition` | Exact implementation and parameter identity; conserved component definitions/order and mass or mole/activity convention; phase definitions; Gibbs/energy/entropy references; supported operations; validity domain; calibration and verification sources/status. A display name or caller-supplied source label alone is not its identity. |
| `Inventory` | Identified provider and ordered component masses in **kg**. Preserve finite inventory; neither mass fractions nor normalised wt% replace it. Persistent material identity/availability belongs to I02. |
| `StateRequest` | Inventory, pressure in **Pa**, and exactly one selected constraint: temperature **K**, total enthalpy **J**, or total entropy **J/K**. Also the declared numerical allowance and execution budget. No implicit constraint change on failure. |
| `EquilibriumResult` | Status; provider/request identities; pressure/temperature when determined; per-phase, per-component masses; total **H [J], S [J/K], V [m3]**; residuals and numerical uncertainty. Requested derivatives include their units, held-fixed variables and branch/validity status. |
| `TransferProposal` | Donor/receiver/parent identities; actual component masses and enthalpy removed/carried/received; provider and pressure/path references; explicit heat/work exchanges. A numerical proposal is not an I02 committed or once-only transfer. |

I01 selects these semantics. I05/I06 implement the producer/receiver connection;
I02 supplies durable state identities and transactions. No additional repository,
cache framework, event ledger or UI is introduced by this document.

## 2. Identity, basis and domain before calculation

Use an immutable provider definition shared by many states. Its numerical identity
includes equations/implementation, all coefficients, component and phase basis,
reference conventions and validity rules. Reuse the existing source/version
machinery when integrated; do not copy the complete definition into every cell.
Separate numerical-source identity from calibration evidence and acceptance for
a particular requested use: identical bytes do not establish physical validity.

For a transfer, require matching component semantics and energy references, not
just equal array length, familiar names or units. "MORB-like" is not an oxide
composition. Mass/mole conversion needs defined molar masses and mixing/activity
rules. A basis change needs an explicit conservative mapping, including elemental
conservation where those definitions exist. Do not infer one for effective
components lacking a chemical interpretation. The first connection refuses
unimplemented mappings, arbitrary law changes and open-component reservoirs.

The domain includes **pressure, temperature, bulk composition/depletion, phase
assemblages and model assumptions**, not just a rectangular P/T box. Valid source
mantle does not imply valid extracted liquid, cooled residue or crustal receiver.
Check all participating states and the declared transport domain. Endpoint checks
alone do not certify an entire path. Dry-only models cannot silently admit water,
carbon dioxide or exchange with an external oxygen reservoir.

An analytical-control status stays analytical. A proposed calibration is not an
accepted parameter set. Numerical convergence never promotes either status.

## 3. Operations, outputs and honest failures

Required eventual operations are equilibrium at P/T and inversions at P/H and
P/S. The provider must report unsupported operations instead of implementing
P/S as constant H or substituting a different equation of state.

At pure/congruent melting, P/T can leave the phase amount undetermined. Return
that explicit condition or require an additional admissible constraint; never
invent a liquid fraction. P/H or P/S can determine the phase amount on the
plateau. Derivatives at a phase boundary may be one-sided, singular or undefined:
report their status, not a fabricated zero. Distinguish fixed-phase heat capacity
from an equilibrium derivative that includes changing phase amounts.

For zero total mass, extensive H/S/V are zero and composition fractions and
material temperature need not be defined. An empty result still carries the
provider/basis identity. A zero transfer can skip an equilibrium solve but must
not bypass compatibility or ownership checks. Unknown, non-finite, negative or
numerically unrepresentable positive inventory is not silently clipped away.

Failure results distinguish incompatible provider/basis/reference, unsupported
domain or phase, underdetermined constraint, unresolved numerical solution,
cancelled execution and exhausted budget. These are proposed outcome meanings,
not new mandatory string values for retained helpers. No failure returns a
committable partial transfer or changes donor/receiver inventories.

## 4. Energy and units

The selected provider owns both phase equilibrium and phase energies from the
same declared thermodynamic potential or demonstrably compatible formulation.
At fixed composition, the defining identities include `s=-g_T`, `h=g+T*s`,
`v=g_P`; derivative tests must state the branch and held-fixed variables.
Partition data alone do not determine the common part of the Gibbs potential.

Liquid of mass `dm` carries component masses `dm*c_liquid[i]` and enthalpy
`dm*h_liquid`. Here `h_liquid` is **specific J/kg**, unlike total `H` in a state.
Latent heat already present in h is not debited or credited again. Mixing at
constant pressure sums component masses and H, not temperatures or entropies.
Pressure transport requires an explicit path: reversible fixed-composition
motion obeys `dh=T*ds+v*dP`, not generally constant h. Gravitational, kinetic,
dissipative and external heat/work accounts must be declared by the transport
model; the equilibrium call does not manufacture them.

External adapters convert units once, explicitly and at the boundary. For example,
1000 g, total H=2,000,000 J and V=400 cm3 mean 1 kg, H unchanged and V=0.0004 m3;
specific h is 2,000,000 J/kg and density is 2500 kg/m3. These are manufactured unit
checks, not rock calibration. Conversions include bar-to-Pa (100000) and Celsius
to Kelvin (+273.15), with no speculative conversions based on numerical size.
Metadata alone cannot detect numbers falsely labelled with the right unit: each
adapter needs independently known conversion cases tied to its actual API.

## 5. Reuse the retained implementation without overstating it

The [phase-energy control](I01_PHASE_ENERGY.md) already provides immutable
`Model`, `PressureLaw` and `State`, ordered component masses, extensive H/S/V,
P/T equilibrium, P/H inversion and finite extraction. The
[pressure control](I01_PHASE_PRESSURE.md) supplies P/S inversion and a reversible
pressure connection. The [receiver](I01_MAGMA_RECEIVER.md) validates incoming
accounts, requires matching laws/pressure and proposes compatible mixing and
transfer. Reuse these as the analytical reference implementation; do not rewrite
their law or receipts to make a new provider appear interchangeable.

They are not a calibrated-provider plug-in framework. Their component model,
constant phase volumes, shared mixing constant and derivative bounds are specific
to the retained analytical law. A future provider may need different phase or
component structure and numerical solvers. It must meet the connection semantics,
not fit into that law's coefficient slots. W08 remains separate until a real,
checked adapter or compatible replacement exists.

Preparation reuse is keyed by complete provider identity and required pressure/
composition inputs. A warm solution is only an initial guess, revalidated for the
new request. Do not reuse results after extraction changes composition. Any later
table/surrogate must represent composition and phase boundaries and preserve
thermodynamic consistency; independently interpolating F/H/S/V is not assumed safe.
No speedup or installed external-software compatibility is claimed here.

The experimental implementation described in section 8 now provides a separate
route. It does not make the analytical coefficients interchangeable with G25.

## 6. Bounded implementation acceptance, when the provider is chosen

| Check | Required distinction |
| --- | --- |
| Known external unit/basis examples | Extensive versus specific, kg versus g, Pa versus bar, mass versus mole; no normalisation losing inventory. |
| Identity changes | Changed coefficient, component order/meaning, pressure, reference or provider version cannot reuse incompatible states. |
| Depletion and finite transfers | Repeated extraction uses remaining component inventory; no duplicated latent heat or created magma. |
| P/T, P/H, P/S reference cases | Unique solutions, latent plateaux, empty inventories and unsupported states are distinguished. |
| Thermodynamic identities | Independent derivatives/reference values, pressure-loop checks and uncertainty; no circular comparison of one formula with itself. |
| Domain and failure atomicity | Invalid residue/receiver, cancellation, nonconvergence and budget failure leave original inventories unchanged. |
| Physical calibration | Withheld composition/P/T/phase/depletion observations separate from fitted data and software comparisons. |
| Connected delivery | The same material and energy references reach an actual receiver; conserved analytical fixtures alone do not establish geological realism. |

This acceptance table is a design specification. Section 8 describes the bounded
implementation and its explicit checks; neither renews the older analytical
receipts or implies that every item in the table is complete.

## 7. Sources and provenance

- Atlas's retained phase-energy, pressure and receiver source/interfaces and
  method documents were inspected. Their current implementation is distinguished
  above from the proposed external-provider contract.
- [Cantera 3.2 thermodynamic properties](https://cantera.org/stable/python/thermo.html):
  mass/molar basis, explicitly specific Gibbs/enthalpy/volume properties and
  supported-state concepts inspected for interface design, not magma physics.
- [alphaMELTS interface at 9b92b1e](https://github.com/magmasource/alphaMELTS/blob/9b92b1e0e6d1538a0f498572d6c6651d5d3aca7e/bases/alphamelts/py/meltsengine.py):
  the previously inspected extensive phase properties and gram/cc units informed
  the conversion boundary. No installation or runtime test is implied.
- The reviewed MC-03 research compared Katz/pyMelt, Keller-Katz/R_DMC and pMELTS.
  The source/code divergence and common-energy warning were checked against
  [R_DMC's pinned equilibrium code](https://github.com/richard-katz/R_DMC/blob/21d22e4d6fae26d47dc7ec9d9983a613dba69947/src/R_DMC_Equilibrium.m#L313-L325)
  and [Keller & Katz (2016)](https://eprints.gla.ac.uk/195948/1/195948.pdf) in that
  review and are reused here, not reread or adopted as a calibration. Concrete
  target datasets, model/component choice, extraction, focusing and the thermal
  lid remain separate MC-03 work.

## 8. Implemented common-Gibbs connection

The source-only [provider](../tools/i01_gibbs_provider.py) accepts a closed-system
equilibrium calculation: component amounts, stable phases and their common
chemical potentials. Its [MAGEMin process adapter](../tools/magemin_g25.py) and
[Julia worker](../tools/magemin_g25.jl) select the corrected Green et al. (2025)
igneous model (`ig`, `tc_ds636`), MAGEMin_C 2.3.7 at commit
`99d71b51171d85a1e37d41430d5f8c99a7bd0917`, and native MAGEMin 2.0.4.
The isolated test environment is not an Atlas release dependency or installer.

### Why not copy the software's heat fields?

The pinned backend's solution entropy sums endmember derivatives, whereas its
full Gibbs objective also includes configurational mixing and interaction terms.
Its phase/property exports also use different formula, oxide-mole and mass bases.
In particular `V_cm3` is numerically cm3/kg, not a parcel's total cm3. The adapter
therefore does **not** import raw phase/system H, S or V and guess a scale factor.
This is a source-level interface finding, not a claim that its phase diagrams are
invalid or a quantified assessment of every property error.

The live native check also identified a separate inventory defect: after
calculating its convergence residual, `phase_merge_function` adds phase amounts
but takes an **unweighted midpoint** of their nonlinear internal coordinates.
The resulting reported components no longer reconstruct the solved bulk. The
worker disables that operation with `merge_value=0`, retains every solved slot,
and uses solver 1 with the stricter native mass-residual tolerance `1e-10`.
It sums component amounts for accounting only; it never recalculates composition
from averaged internal coordinates. Nearby support vertices are grouped by model
only when the maximum spread of composition/internal coordinates is at most
`1e-3`; their full coordinate envelopes remain in the branch checks. Widely
separated same-model states are refused, not collapsed into one physical phase.
The matched native test reduced maximum component-mole mismatch from `5.31e-5`
to `1.39e-14` without changing Atlas's `1e-7` numerical admission tolerance.

### The common-potential calculation

At equilibrium each phase satisfies `G_phase = sum(n_i * mu_i)`. Differentiating
this expression and applying Gibbs–Duhem cancels the changes in phase amount and
composition. Using the **centre state's** component moles therefore gives

```text
S_phase = -sum(n_i * d(mu_i)/dT)       [J/K, constant pressure]
V_phase =  sum(n_i * d(mu_i)/dP)       [m3, constant temperature]
H_phase =  sum(n_i * mu_i) + T*S_phase [J]
```

Both perturbed solves retain the same complete bulk inventory. Importantly,
differencing a phase's changing molar Gibbs value directly would include its
changing composition and give the wrong entropy. This implementation avoids that
term; the independent binary-mixture test demonstrates the difference.

The worker converts kJ/oxide-mol chemical potentials to J/oxide-mol, kbar to Pa
and Celsius to Kelvin. Oxide mole fractions do not replace inventory: Atlas keeps
the original kg and exact backend molar masses. The 11 ordered components are
SiO2, Al2O3, CaO, MgO, FeO, K2O, Na2O, TiO2, **additional atomic O**, Cr2O3 and H2O.
O is not O2 and does not duplicate the oxygen already in an oxide. Missing water
or oxidation measurements are not filled with invented values. A wrapper request
that would raise small core components or delete a small optional component is
refused instead of changing the rock.

One centre plus four temperature and four pressure samples supplies nested
central differences. The default widths are 1 K and 1 MPa, and their halves.
Stable phase identities, multiplicity, compositions and internal coordinates must
stay on a supported continuous branch. Per-phase specific derivative discrepancies
must meet declared numerical controls; checking only the large bulk would hide a
bad tiny phase. Width agreement is an **estimated discrepancy**, not a certified
error bound. A narrow unsampled discontinuity is not mathematically excluded.
Sampled phase appearances/disappearances, unresolved solvus branches, latent
plateaux, nonconvergence and negative/unrepresentable inventories refuse the
calculation. Local derivative agreement is not a whole-interval branch
certificate. No unsupported branch is smoothed or clipped to obtain a result.

### Extraction, pressure changes and receiving material

`extract` proposes a finite fraction of the calculated liquid inventory and its
own enthalpy. Subtracting it leaves changed component amounts and remaining H;
latent heat is not charged again. The proposal does not persist a transaction.
`flash` inverts H or S on an explicitly declared and bracketed continuous thermal branch.
Thus a declared reversible pressure endpoint can retain S, while mixing at one
pressure sums H and ingredients. `receive` uses that same provider and pressure,
not a different W08 melting law. Full pressure-path work, extraction rates,
permeability, focusing and the axial thermal lid are not supplied by equilibrium.

Both `flash(..., branch=...)` and a nonempty `receive(..., branch=...)` now require
an immutable `ThermalBranch` declaration made with
`provider.declare_thermal_branch(mass, pressure, temperature_bounds,
phase_keys=..., support=...)`. It binds the provider identity, numerical controls,
component ordering and exact component masses, pressure, temperature interval,
expected stable phase identities and the caller's support provenance. Receiving
material needs a declaration for the **combined** inventory; a donor's or unmixed
receiver's declaration does not cover the changed composition. Even a change in
inventory scale needs a new declaration, while the existing equilibrium cache
can still reuse identical normalised compositions.

Declaring support performs no equilibrium calculations and grants no physical
acceptance. The caller must supply a physical/model basis covering the whole
interval; the API does not manufacture it from endpoint agreement. Before
inversion, the requested inventory, pressure and bracket must fit that declaration.
Both bracket endpoints and every bisection state must retain its exact phase
identities, in addition to the existing local derivative, monotonicity and error
checks. A mismatch refuses the inversion, including one encountered between
matching endpoint assemblages. No endpoint can return before both endpoints have
passed their phase checks. An empty-parcel receive is an unchanged-state no-op,
not a thermal inversion.

These checks close a specific former gap: a wide solid-only to liquid-only bracket
could return a mixed-phase midpoint without ever sampling a local phase crossing.
They do **not** mathematically exclude a narrow unsampled transition, certify a
solvus path, or implement a moving freezing front. A production caller without
whole-interval support must refuse rather than label a sampled interval certified.
The native KLB1 comparison retains its short `T_reference +/- 2 K` branch as an
explicit conditional software-control assumption, recorded in the new result;
it is not promoted to a validated geological branch. Existing numerical tolerances
and phase-front restrictions are unchanged. The `branch` keyword is a deliberate
API requirement; callers of these common-Gibbs operations must now provide it.

### Efficiency and checks

One prepared worker retains the native database; it does not relaunch Julia for
each sample. A bounded 256-point cache keeps only compact phase/potential results,
keyed by exact pressure, temperature and complete normalised composition within
one provider. Amount scaling reuses equilibrium; changed depletion does not.
The identity includes the worker, locked environment, loaded native library,
component basis and declared numerical domain. There is no timestep-history
accumulation or hidden network/install on use. Cancellation/timeouts terminate
the owned worker, and no failed response becomes a later request's result.

[Focused tests](../tests/test_i01_gibbs_provider.py) independently calculate phase
H/S/V for a binary mixture with unequal molar masses, variable equilibrium
compositions and known latent heat. They also cover stoichiometric multiplier
ambiguity, absent components, branch/noise refusal, finite extraction, depleted
re-equilibration, same-provider receiving, H/S inversion, scaling, bounded reuse,
identity changes, cancellation, required branch declarations and their exact
bindings, the solid/liquid wide-bracket refusal, sampled interior phase changes
despite matching endpoints, and supported same-branch inversion. These analytical checks validate the method,
not geological calibration. Current installed-backend results and remaining work
are recorded in [CURRENT_STATE](../../docs/CURRENT_STATE.md).

The opt-in [native connection campaign](../tools/check_i01_gibbs_provider.py)
uses the pinned software's KLB1 input, not an independent experiment. It checks a
solid and partly molten state, finer differences, the same coexisting phases
under changed bulk proportions, finite extraction/recombination, H/S recovery,
phase-boundary refusal and matched cache timing. It accepts explicit installed
Julia/project/depot paths and creates a new no-overwrite receipt; it installs
nothing and does not enter the generator's default production route.

### Sources actually consulted for this implementation

- [Green et al. corrected/recalibrated igneous model](https://hpxeosandthermocalc.org/2025/01/06/correction-to-the-holland-et-al-2018-and-tomlinson-holland-2021-models/)
  and [MAGEMin model/software documentation](https://computationalthermodynamics.github.io/MAGEMin_C.jl/dev/):
  corrected model choice and explicitly limited calibration domain.
- [Pinned Julia wrapper](https://github.com/ComputationalThermodynamics/MAGEMin_C.jl/blob/99d71b51171d85a1e37d41430d5f8c99a7bd0917/julia/MAGEMin_wrappers.jl)
  and its installed source: component conversion, result structure, worker API
  and the existing system-only Gibbs finite-difference option.
- [Native property calculations](https://github.com/ComputationalThermodynamics/MAGEMin/blob/a09537602701e753f5f36cc508f90b0b403d9eeb/src/toolkit.c),
  [output construction](https://github.com/ComputationalThermodynamics/MAGEMin/blob/a09537602701e753f5f36cc508f90b0b403d9eeb/src/dump_function.c),
  [solution objectives](https://github.com/ComputationalThermodynamics/MAGEMin/blob/a09537602701e753f5f36cc508f90b0b403d9eeb/src/TC_database/objective_functions.c)
  and ds636 reference definitions: amounts, energy basis and missing raw-property
  terms. Atlas's derivative above follows Gibbs–Duhem; it is not claimed as a new
  thermodynamic law or an independently validated MAGEMin feature.
- [Native phase merging](https://github.com/ComputationalThermodynamics/MAGEMin/blob/a09537602701e753f5f36cc508f90b0b403d9eeb/src/phase_update_function.c)
  and [solve/merge ordering](https://github.com/ComputationalThermodynamics/MAGEMin/blob/a09537602701e753f5f36cc508f90b0b403d9eeb/src/PGE_function.c):
  inspected source, matched merge-enabled/disabled experiment and native/Julia
  structure-layout check, not a modified upstream binary.
