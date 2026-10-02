# I01: phase-aware melt delivery into W08

27 September 2026. WORKING NON-CANON. Bounded interface/control, not a world run.

## What this adds

The mantle's existing melt is a stock, not a supply rate. This interface removes
only an explicitly selected share of the liquid actually available in a finite
source. It returns the rest of that source and connects the liquid to W08's
existing emplacement, enthalpy and duplicate-transfer checks. Nothing modifies
the native package, the D6 batch-melt estimate or Claude's thermal/history work.

This is phase-selective separation, which ordinary well-mixed bulk transfer is
not. The source retains its solid and its unextracted liquid. Placed magma is not
declared solid crust until an explicit cooling account makes it solid.

## Physical contract and derivation

Use the existing W08 isobaric, congruent, common-melting-temperature law only:

`H = sum(m_i cp_i) (T - Tref) + sum(m_i L_i) f`.

Every component shares liquid mass fraction `f` and temperature `T`. This is not
peridotite chemistry, a pressure-dependent mantle solidus or fractional melting.
For supplied extraction fraction `alpha` in [0,1] of the **available liquid**:

- `dm_i = alpha f m_i`;
- `H_out = sum(dm_i cp_i) (T - Tref) + sum(dm_i L_i)`;
- `m'_i = m_i - dm_i`, `f' = (f-alpha f)/(1-alpha f)`;
- residual temperature is unchanged, with `H'` evaluated from `m'_i,T,f'`;
- `H' + H_out = H` to the frozen floating-point account tolerance.

Full depletion of an entirely liquid source gives an empty source with zero
enthalpy and no temperature. Empty/dry sources yield no payload. A zero-latent
law cannot establish phase availability and is refused. A W08 transfer plan
checks a *declared* zero-latent source kind against temperature
([phase admission](W08_MAGMATISM.md#declared-source-kinds-and-the-supplied-phase-rule));
that does not establish an extractable liquid fraction here. All inputs are borrowed;
no caller state is mutated. Extreme unresolved arithmetic is refused, not clipped
into a plausible-looking result.

Removing a proportion of bulk enthalpy would leave latent energy behind with the
solid and incorrectly cool the separated liquid. Here latent enthalpy travels
with that liquid. It is not generated again by transport or emplacement.

W08 places the finite payload using declared positive areas, densities and mass
weights; its thickness is `delivered_mass / (receiving_density * receiving_area)`.
This interface supports additive underplating or extrusion, not host replacement.
Placement retains the full hot enthalpy. Subsequent W08 `reheat` removes explicitly
accounted heat to cool/crystallise it; the surroundings must receive that energy.
Placement is not a support/elevation solution and density changes are not a
compaction calculation. Source-volume accommodation remains a mechanics concern.

## Ownership, limits and next connection

The upstream physical model must supply extraction amount, timing, route and
receiver/accommodation authority. There is deliberately no default efficiency,
no inventory divided by an invented duration, and no standing-column estimate
treated as emitted crust. `extract_liquid` has no implicit heat source.

The caller atomically replaces the old source by the residual and places the
payload **once**. Native `accounting_entries` detects duplicate transfer IDs in
the full pending set; persistent replay prevention belongs to the transaction
owner. Reusing a stale input snapshot is not prevented by a pure calculation.
Retaining both the upstream payload and its placed copy as active mass is wrong.

The prototype is limited to one source, at most 64 components and 64 receiving
cells, with a shared 128 KiB work-admission budget (not a measured process-RAM
limit). It uses direct phase arithmetic and existing native kernels: no mesh,
iteration, numerical transport, background process, cache or parallel overhead.
Phase separation performs O(component count) work. No runtime saving is claimed
against an alternative with different physics.

Actual melt-production/extraction/focusing laws and their pressure/composition
feedback are still an I01 closure decision. The D6 closed-batch Katz/Brune
inventory cannot simply be passed in as cumulative production or porosity under
a different thermodynamic law. General two-phase compaction is not added here.

## Checks and how they establish correctness

The case file fixes tolerance at 1e-12 before the campaign. Dry material, partial
extraction, multicomponent full-available extraction, superheated-liquid exhaustion
and a signed enthalpy datum have independent mass/phase expectations. Tests also
cover invalid fractions, ambiguous phase laws, cancellation, allocation refusal,
unresolved debits, input immutability, repeated incremental extraction, replay
rejection and unchanged-phase transport.

The connected analytical case starts with 10,000 kg at 20% melt and extracts half
the liquid: 1,000 kg travels and 9,000 kg remains. Placement sends 250/750 kg to
two declared footprints, giving 0.044642857142857 and 0.083333333333333 m of hot
material. Cooling it from 1500 K to 1000 K and fully solidifying it transfers
1.08e9 J to the surroundings. Source + final solid + released heat must recover
the starting enthalpy. No mass, sensible heat or latent heat appears for free.

Run `python -B -m unittest discover -s tectonics/tests -p test_i01_delivery.py -v`
from the repository root. Produce a NEW receipt with
`python -B tectonics/tools/check_i01_delivery.py --output NEW_PATH.json`.
The receipt binds this tool, case, tests, document and the unchanged entire native
source tree before/after execution because package imports traverse `__init__`.
Installed binaries/external publications are not sealed. Timings exclude imports.

## Software/research consulted

- [ASPECT melt-transport methods](https://aspect-documentation.readthedocs.io/en/latest/user/methods/melt-transport.html),
  phase conservation equations and the approximate-Darcy limitations: melt
  inventory and transported melt are distinct; ignoring matrix compaction is not
  a general mass-conserving extraction solution. This informed the decision not
  to introduce an unvalidated Darcy shortcut.
- [ASPECT latent_heat_melt implementation](https://github.com/geodynamics/aspect/blob/main/source/heating_model/latent_heat_melt.cc),
  `evaluate`: latent reaction heat is distinct from phase transport. Consulted
  directly; no implementation copied.
- Existing Atlas W08 `magmatic_thermodynamics.py` and
  `magmatic_emplacement.py`: reused rather than duplicating their thermodynamic,
  placement and single-owner accounting machinery. The phase split above is an
  algebraic consequence of that declared law, not a new mantle-melting model.

A research cross-check of the more ambitious steady-column option identified
that prescribed cumulative production fixes the top flux, independently of
permeability; it would still need extraction boundary and thermodynamic closures.
That option was not implemented. This receipt does not validate such a column.
