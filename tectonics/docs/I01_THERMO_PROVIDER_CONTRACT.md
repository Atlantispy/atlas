# I01 common thermodynamic provider: connection contract

**WORKING NON-CANON — selected interface requirements, not an implemented adapter
or calibrated material.** MC-03 remains open. This separates the stable connection
requirements from the pending calibration/component/model choice. It changes no
retained solver, evidence, W08 law or release scope.

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

This is a design specification, so no new numerical campaign or evidence receipt
is implied. These checks will be mapped to the chosen implementation, reusing
adequate existing analytical controls rather than rerunning them for this document.

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
