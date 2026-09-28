# I01: melt focusing and the axial cooling barrier

WORKING NON-CANON. **Model route selected; spatial implementation and physical
acceptance remain open.** The [companion decision record](../cases/i01_melt_route_v1.json)
is a design contract, not executable configuration or a calibration receipt.
This completes the focusing/lid choice without assigning a universal lid depth,
extraction efficiency or crustal thickness. It does not modify the separately
owned melt-segregation control or the corrected-G25 provider.

## Selected route and its smallest supported branch

Use coupled porous melt flow, matrix compaction and conservative thermal evolution
on the same regional support. Focusing is the resulting lateral liquid flux under
the calculated pressure and permeability fields. The cooling barrier is the
thermally evolving loss of connected liquid permeability. Neither is a prescribed
path to the nearest ridge or an output inferred from spreading speed alone.

Select **non-reactive transport with respect to the traversed host** as the first
chemical approximation: segregated liquid carries its component inventory without
dissolving or chemically equilibrating with unrelated mantle on its route. This
does not mean zero source melting or zero crystallisation. Source production and
receiver cooling use the common thermodynamic provider and explicit finite
accounts. This branch cannot describe reactive channelisation, metasomatism,
volatile exchange, disequilibrium mineral reaction or arbitrary melt-rock mixing.

The presently implementable bounded branch is narrower still: transport existing
liquid on a supported continuous thermodynamic branch, with declared boundaries
and no phase birth/death crossed. The current common-Gibbs `equilibrate` and
`flash` explicitly refuse derivative stencils crossing phase boundaries.
Therefore existing native G25 controls do **not** establish a propagating freezing
front or a generated cooling lid. The full selected route needs that connection
in I05/I06; its absence is genuine missing implementation, not a reason to invent
a cutoff. Pre-existing-liquid segregation feasibility may pass independently.

## Flow, inventories and focusing

The first spatial branch is creeping, viscous two-phase porous flow. It uses
isotropic permeability, one interconnected liquid network and a coherent solid
matrix. Start with a 2D ridge-normal section only for declared along-axis
invariance; use a finite documented strike width to convert section accounts to
kg/J. Segmented ridges and junctions need 3D support. No dike, fracture opening,
surface eruption, capillary barrier or high-liquid-fraction suspension is supplied
by this porous-flow approximation.

Let `phi` be liquid **volume fraction**, `v_s,v_l` velocities [m/s], `p_l` liquid
mechanical pressure [Pa], `p_c` compaction pressure [Pa], `g` gravity [m/s2],
`eta` effective aggregate shear viscosity [Pa s], `zeta` compaction viscosity
[Pa s], and `q=phi*(v_l-v_s)` relative liquid volume flux [m/s]. The selected
mechanical equations are

```text
q = -(k/mu_l)*(grad(p_l)-rho_l*g)
p_c = -zeta*div(v_s)
-div(2*eta*D_dev(v_s)) + grad(p_l) + grad(p_c) = rho_bar*g
rho_bar = (1-phi)*rho_s + phi*rho_l
```

Here `p_c=(1-phi)*(p_s-p_l)` is the aggregate compaction convention; it is not
silently equated to the unweighted phase-pressure difference. Retain the same
convention in the shared segregation/mechanical connection. There is no separate
focusing force or second copy of buoyancy added to these equations.

For the first Boussinesq mechanical branch, `rho_s,rho_l` in phase transport are
positive declared **reference transport densities**, constant in each admitted
material family. The two phase-volume balances are

```text
partial_t((1-phi)*rho_s) + div((1-phi)*rho_s*v_s) = -Gamma
partial_t(phi*rho_l)     + div(phi*rho_l*v_l)     =  Gamma
div(v_s+q) = Gamma*(1/rho_l-1/rho_s)
```

`Gamma` is signed local solid-to-liquid mass production [kg/m3/s], supplied by
the compatible thermal/source update, never standing liquid stock divided by a
chosen duration. The non-reactive transport-only control has `Gamma=0` along the
route and finite input/output fluxes. For component i replace each phase mass by
its component mass and use paired `Gamma_i`, with `sum_i Gamma_i=Gamma`.
Transported composition, depletion and finite donor availability remain explicit.

Thermodynamic phase volumes from G25 are not overwritten by the reference
densities. This is a stated Boussinesq approximation: its implied geometric
volumes and the provider volumes must be compared over the admitted path, with a
predeclared volume/density error allowance. If that allowance fails, use an
appropriately derived variable-density connection; do not call the reference
density volume exact or renormalise masses to fill a cell. Dynamic/compaction
pressure versus thermodynamic pressure likewise requires an explicit pressure
mapping and an assessed error bound before a geological run.

Choose the bounded isotropic permeability family

```text
k(phi,d) = k_ref*(d/d_ref)^2*(phi/phi_ref)^n   for phi>0
k(0,d) = 0
zeta = zeta_ref*(eta/eta_ref)*(phi/phi_ref)^(-m)   for phi>0
```

`k_ref` [m2], reference grain size `d_ref` [m], `phi_ref`, exponent `n>0`, and
the actual grain-size field `d>0` are explicit case inputs with physical support.
No numerical value is adopted here. The selected porosity-dependent compaction
family also requires `zeta_ref,eta_ref>0` [Pa s] and exponent `m>0`, with its
calibrated or explicitly assumed support. Matrix and liquid viscosities use their
declared material models. A fitted cutoff porosity, evolving grain size, anisotropic permeability
or capillary entry law would be a distinct extension, not an invisible default.
At zero porosity solve the dry branch with no liquid flux; a numerical liquid
floor must not create inventory or count as a physical pathway.

The compaction length `delta_c=sqrt(k*(zeta+4*eta/3)/mu_l)` indicates a physical
resolution scale for this isotropic viscous branch. It does not itself impose a
channel or select the thickness of a thermal barrier. Coefficient variation,
source exhaustion and the porous-matrix validity limit still need resolution and
admission checks.

Measure delivered melt by the outward physical receiver flux, integrated in
time and over the declared surface:

```text
Delta_M_i,out = integral_dt integral_receiver rho_l*c_l,i*v_l dot n dA
Delta_H_out   = integral_dt integral_receiver rho_l*h_l*v_l dot n dA
```

Use the positive outward part only for an outflow account; backflow is a separate
finite incoming account with its own composition/enthalpy. The surface normal,
moving-face correction when needed, and full velocity belong to the same
geometry. Source-labelled parcels or conservative tracers can diagnose focusing
distance and capture fraction; they do not steer the flow. A receiver outlet's
location and pressure/accommodation are explicit boundary inputs. Selecting it
does not prove that the model generated a ridge, dike or crustal opening.

## Cooling barrier, shared enthalpy and transfer

Use Fourier heat flux `q_T=-K_T*grad(T)`, with positive conductivity [W/m/K],
actual thermal boundary conditions and conservative advection of each phase's
own enthalpy. The common provider supplies phase `h`, `s`, `v` and equilibrium
where an operation is admitted. Retain `u=h-P*v` and the declared physical
thermodynamic pressure reference. At fixed phase composition,
`dh=T*ds+v*dP`; a pressure-changing transfer is not automatically isenthalpic.

The coupled discrete update must satisfy the first law: stored internal plus
gravitational energy changes by incoming minus outgoing material energy, net
conductive heat, radiogenic/declared heating and exterior mechanical work. Use
actual phase tractions/velocities and relative boundary fluxes. Pressure-flow
work may be included through enthalpy flux **or** through the equivalent internal
energy/traction form, never both. Matrix shear, compaction and Darcy drag
contribute nonnegative internal heating

```text
Phi = 2*eta*D_dev:D_dev + zeta*(div(v_s))^2 + (mu_l/k)*q dot q
```

on the supported wet branch; the dry limit has `q=0`. Their conversion from
mechanical/gravitational work to heat is an internal exchange, not an extra
external energy source. A quasi-static Boussinesq update must state which
compressional/kinetic terms it neglects and check the resulting allowance; the
formula above is not permission to mix inconsistent energy approximations.

Phase enthalpies already include fusion energy. Do not add a second latent-heat
term to an enthalpy update, mix temperatures instead of H, or reuse Katz's batch
fraction inside W08's different common-melting-temperature law. After extraction,
the donor is its remaining composition and H. After pressure adjustment, the
receiver sums compatible component masses and H before its supported inversion.
The heat released by receiver crystallisation has an explicit destination.

In the full selected route the barrier is the boundary of the supported connected
liquid-permeable domain, diagnosed from the evolving phase state and `k(phi,d)`.
Its axial depth, if single-valued, is measured relative to the common surface
datum. If there are several lenses, disconnected pockets or no barrier, return
that geometry/status; do not force a single `z_lid`. A plotting porosity contour
is a labelled diagnostic, never a new extraction or freezing criterion.

Cooling/freezing, inherited temperature, melt enthalpy flux, conductive loss,
matrix motion, permeability and finite supply all affect this boundary. Spreading
speed enters through actual motion and heat/material transport. Consequently
there is no universal `z_lid(rate)`, fixed collecting horizon or default fraction
of all mantle melt that reaches the axis.

For non-reactive transport, never equilibrate an incoming parcel together with
the traversed host and then describe that operation as chemically inert. Keep
their inventories separate. Source-local melting and crystallisation of the
carried material are permissible named operations, but depositing its crystals
into the solid needs an explicit conservative phase-transfer/accounting law.
The present G25 derivative branch cannot carry phase appearance/disappearance;
it must refuse at that boundary until I05 provides event/one-sided or otherwise
validated common-potential handling. Skipping directly from liquid to cold solid
does not establish the path or a freezing front.

## Inputs, observations and limits of present evidence

A runnable spatial case must supply: domain and datum; parent/epoch; initial
finite phase/component inventories and inherited temperatures; the chosen common
provider identity and pressure mapping; basal/side/top thermal, mechanical and
material conditions; solid motion or work-consistent driving; permeability,
grain size, shear/compaction/liquid viscosities and conductivity; receiver
geometry/pressure and capacity; physical duration; approximation domains;
and numerical/time/memory allowances. Missing inputs are not defaults.

The corrected Green et al. (2025) `ig`/`tc_ds636` model has a published calibration
basis. Atlas need not refit that entire model to select it. The installed native
controls check Atlas's interface and accounting; KLB1 supplied by the software
is not an independent held-out experiment. Published model validity, reproducing
software output, numerical conservation and validation of this connected route
are four different claims.

The minimal evidence packet for a **specific requested physical domain** is:

- Identify the original G25 fitting data and their covered P/T/compositions,
  including source mantle, depleted residue and extracted-liquid/receiver paths.
  Keep the published coefficients fixed unless a separately stated refit is
  needed. A missing range is a support gap, not evidence that the model is invalid
  everywhere.
- Recover independent phase-equilibrium observations covering each participating
  role and the claimed melting/crystallisation interval: P/T uncertainty, measured
  bulk and phase compositions, oxidation/water state, phase assemblage and melt
  fraction with uncertainty. Hold out complete experimental runs/compositions or
  pressure paths, not neighbouring points already used to fit the same curve.
  Check fit-set membership before calling a dataset withheld. No dataset is
  newly admitted or claimed withheld in this decision.
- Where Atlas claims heat/volume accuracy, require independent constraints on
  relevant phase heat capacity/enthalpy differences and density/volume, with
  provenance and uncertainty, or explicitly restrict that accuracy claim.
  Differentiating the same Gibbs function twice is a consistency check, not such
  experimental evidence. Total enthalpy's arbitrary datum is compared through
  reference-consistent differences and accounts.
- Fit only route-specific unknowns that need fitting: permeability versus
  porosity/grain size, liquid viscosity, compaction response, and the thermal
  boundary/hydrothermal treatment for the selected case. Use independently
  constrained values where available. Bound the non-reactive assumption using
  transport versus chemical-reaction times and the common-temperature assumption
  using thermal equilibration times; otherwise the route's chemistry/thermal
  claims remain unsupported.
- Keep at least an independently observed thermal/geometry response and an
  independently observed material-delivery response outside tuning: for example
  ridge heat loss or magma-lens constraints together with erupted/magmatic volume
  or crustal thickness and composition. Their geological uncertainties and
  omitted dike/hydrothermal processes must enter the comparison. Crustal thickness
  alone cannot uniquely calibrate both permeability and cooling. No exact number
  of experiments or universal tolerance is invented; adequate coverage is set by
  the admitted domain and identifiable parameters.

Dry, closed-system transport is the first restricted use. Nonzero water/redox
components must come from declared source measurements and supported provider
states; no open oxygen reservoir, exsolved gas or carbon-bearing extension is
implied. If reaction times are not demonstrably long compared with transit, this
non-reactive approximation is a sensitivity case, not a claim of realistic
chemistry. No dry KLB1 result validates all of these other materials or paths.

## Acceptance and ownership

I01 has selected the flow/thermal route and its restrictions. The separately owned
segregation work supplies its own bounded feasibility evidence; this document
does not reproduce that tool or certify its results. I05 owns the evolving phase,
component and enthalpy state, pressure-path compatibility, thermal boundaries,
property feedback and phase-front handling. I06 owns shared-ridge geometry,
finite extraction/outlets, receiver accommodation, actual melt-derived crust
birth and formation history. I07/I09 provide regional mechanics and work-consistent
motion; I02 supplies atomic inventories and replay prevention. These are later
integration obligations, not additional unexplained I01 model choices.

For the I01 finish rule, the MC-03 **choice and bounded feasibility** requirement
can close when the selected corrected-G25 provider is bound to its existing
native/analytical checks, the separately owned real segregation controls pass
under the compatible restricted branch, and this focusing/thermal contract and
its explicit refusals are integrated. Published G25 calibration supports choosing
that model family; it does not require Atlas to invent a new experimental fit.
This design document alone is not a passed feasibility test. None of those
conditions closes the original physical-acceptance requirements: moving phase
fronts and complete source-to-crust integration remain I05/I06 work, and the
independent physical observations above remain explicit external acceptance
conditions. Pre-existing-liquid transport is never labelled generated ocean
crust or a validated axial lid. No original physical-acceptance clause is waived.

Before a physical focusing/lid result can be accepted, the runnable case must
freeze its complete inputs, evidence-supported coefficient domain, numerical
allowances and resource bounds, then pass:

1. Dry/zero-gradient and manufactured pressure controls; correct flux direction;
   finite source exhaustion; no porosity floor leaking mass; no illegal exit or
   manufactured axial attraction. An imposed outlet remains labelled imposed.
2. Every component's `M_after=M_before+M_in-M_out`, paired once-only phase transfers,
   and full donor/route/receiver/surroundings energy closure. Include pressure,
   gravitational and viscous/compaction/drag work under the declared approximation.
3. Independent space and time refinement, plus wider/deeper domain and boundary
   sensitivity, resolving compaction and thermal scales. Compare integrated
   delivery, composition/H, pressure/velocity, porosity and barrier geometry/time,
   not only images or solver residuals.
4. Supported thermal/phase-front controls, including freezing/retention and no
   available-liquid cases. Changed heat input or inherited temperature at the
   same spreading rate must affect the computed state; rate is not a lid lookup.
5. An actual compatible source-to-receiver path with depletion, finite heat
   removal and correctly retained birth ages, followed by the withheld physical
   comparisons above. A failure or unsupported phase event leaves the parent
   uncommitted; no fallback law, reset temperature or guessed supply is allowed.

These are acceptance requirements, not results. Their case tolerances must be
derived and fixed before execution; null values in the design record prevent it
from masquerading as runnable configuration. The present document runs no
simulation, native campaign, calibration, installation or new numerical tool.

## Primary sources actually inspected

- [ASPECT melt-transport methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html),
  equations 29–32 and the stated approximate-Darcy limitation: coupled pressure,
  compaction, phase transport and permeability conventions. The manual's warning
  about approximate Darcy transport losing matrix mass is why a prescribed
  buoyancy-only velocity is not adopted for general focusing. Its coefficients
  and implementation are not copied or benchmarked here.
- [Sim et al. (2020), publisher abstract](https://www.sciencedirect.com/science/article/abs/pii/S003192011930202X)
  and the [authors' TerraFERMA publication index](https://terraferma.github.io/)
  identify coupled two-phase focusing with spreading and permeability dependence.
  The full manuscript download was blocked by its host; no unretrieved equation,
  numerical result or calibration from that paper is claimed reproduced.
- [Green's corrected-model notice](https://hpxeosandthermocalc.org/2025/01/06/correction-to-the-holland-et-al-2018-and-tomlinson-holland-2021-models/)
  confirms correction/recalibration rather than an uncalibrated new Atlas law.
  [MAGEMin's official description](https://computationalthermodynamics.github.io/MAGEMin_C.jl/dev/)
  explicitly limits dataset applicability in pressure, temperature and composition.
  These establish the basis for retaining the pinned provider, not validation of
  Atlas's route or permission to update its pinned software.

The inspected local [provider contract](I01_THERMO_PROVIDER_CONTRACT.md),
[phase-energy method](I01_PHASE_ENERGY.md), [Katz control](I01_MELTING.md),
[delivery interface](I01_DELIVERY.md), `i01_gibbs_provider.py` and
`magemin_g25.py` supply the implementation boundary described above. Their
existing numerical receipts are reused by scope; none was rerun or rebound.
