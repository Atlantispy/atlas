# I01: a compatible finite magma receiver

WORKING NON-CANON. This connects the [ideal-mixture energy provider](I01_PHASE_ENERGY.md)
to a finite receiving body at the **same pressure and with exactly the same law**.
It does not reinterpret that material through W08's different energy convention.

## What happens, in generation order

1. Start with finite donor and receiver inventories, each already at equilibrium
   under the declared composition/energy law. They may have different temperatures.
2. Extract a prescribed share of the donor's existing liquid, carrying its actual
   components and enthalpy. The donor retains its depleted composition.
3. Add those components and that enthalpy to the receiver. Solve once for the new
   equilibrium temperature and phase amounts. Incoming magma can crystallise,
   heat the receiver, or melt some of its original solid; none is imposed afterwards.
4. Return the proposed donor and receiver states together only after the checks
   succeed. Inputs are immutable and an error leaves both unchanged.

For parcels co-added before anything is removed, cooled externally or otherwise
acted on, their component masses and enthalpies are additive. `receive_many`
collects at most 64 parcels and performs one equilibrium solve, not one per parcel.
This is not a shortcut for a time-resolved sequence with intervening losses.
An empty receiver taking one validated parcel, or a zero receipt, needs no new solve.
There is no growing history, disk cache or worker overhead for these tiny operations.

## Physical and numerical accounts

The receiver plus incoming material is treated as a closed adiabatic system at
fixed external pressure P, with only pressure-volume work and no kinetic or
gravitational energy change. After mixing:

```text
component_mass_final_i = component_mass_receiver_i + sum(parcel_mass_i)
H_final = H_receiver + sum(H_parcel)
U = H - P V
work_done_by_combined_material = P (V_final - V_receiver - sum(V_parcel))
delta_U + work_done_by_combined_material = 0
entropy_production = S_final - S_receiver - sum(S_parcel) >= 0
```

Latent heat is already part of H; adding another crystallisation credit would
count it twice. Likewise no extra incoming flow-work term is added to enthalpy.
The reported boundary work refers to the **combined material**, not a receiver-only
control volume. Volume and entropy are not conserved: crystallisation changes
volume, while mixing and thermal equilibration generally produce entropy.
Negative `net_crystallised_kg` means net melting of solid, not a failed inventory.

All stored phase/energy accounts are reconstructed before use. Pressure, component
order, coefficients, datum and source identity must match exactly. Changed laws,
solid-bearing incoming parcels, unresolved tiny credits, invalid quantities,
cancellation, expired deadlines and non-finite work refuse without returning a
candidate. Bounds come from the retained solver's mass/temperature policies plus
floating-point summation allowances; no tolerance in that solver is changed.
The entropy check includes the enthalpy error and retained phase uncertainty
divided by the minimum supported temperature. These are numerical diagnostics,
not interval-arithmetic certification.

## Independent answers and integration checks

For pure material with cp=1000 J/kg/K, L=300000 J/kg, Tm=1500 K and T0=1000 K,
1000 kg of liquid at 1800 K carries 1.1 GJ. Adding it to 1000 kg solid at 1000 K
gives 2000 kg at 1500 K, of which 333.333333 kg remains liquid. Exactly 666.666667 kg
crystallises; entropy production is 89810.217981 J/K. With the solid instead at
1200 K, the final liquid is 1000 kg and entropy production 40821.994520 J/K.
Receiving the same hot parcel into 3000 kg solid at 1000 K gives entirely solid
material at 1275 K. These follow algebraically from total enthalpy, not the solver.

The retained binary donor supplies (666.666667,333.333333) kg liquid and 0.9 GJ.
Added to (0,8000) kg solid at 1000 K, the independent answer is 9000 kg entirely
solid at 1100 K, entropy production 336550.367259 J/K and combined boundary work
-40153641.9334 J at 1 GPa. The ideal mixing entropy is included; its heat of mixing
remains zero. Repeated transfer tests preserve donor depletion and receiver stocks.

Other focused tests cover empty/zero additions, signed energy references, changed
pressure/law/order, forged accounts, complete freezing, induced melting, failure
atomicity and cancellation. The bounded campaign compares eight simultaneous
parcels solved together versus the same eight additions solved sequentially with
no intervening exchange: identical material law and numerical tolerances. It records
three interleaved batches of 20 calls, final-state parity and raw/percentage timing.
It is a local kernel comparison, not a world-generation forecast.

## Research and software actually checked

- [Cantera's constant-H/P Quantity mixing example](https://cantera.org/stable/examples/python/thermo/mixing.html):
  inspected the way separately defined material quantities combine under an
  enthalpy/pressure constraint. Its reacting-gas model is not used as magma physics.
- [Keller & Katz (2016), Appendix A.2.1-A.2.2](https://eprints.gla.ac.uk/195948/1/195948.pdf):
  re-read component mass and phase enthalpy/latent-energy transport bookkeeping.
  The continuum flow/reaction equations are not claimed implemented here.
- The retained phase/energy derivation and analytical controls were reused.
  A separate bounded mathematical calculation supplied the independent pure and
  binary answers above. No external solver was installed, executed or vendored.

## Execution and remaining boundary

From the repository root:

```text
python -B -m unittest discover -s tectonics/tests -p test_i01_magma_receiver.py -v
python -B tectonics/tools/check_i01_magma_receiver.py --output NEW_PATH.json
```

The exclusive-create evidence binds this tool, test, method, case and the unchanged
energy/partition providers and their analytical input. Results belong in the
[current evidence register](../../docs/CURRENT_EVIDENCE.md), not hand-authored here.
All material parameters remain an analytical ideal mixture, not calibrated mantle.
Pressure transport, extraction rates, compaction/focusing, emplacement geometry and
thermal embedding remain separate. The API proposes immutable numerical states;
it has no persistent material IDs, retry deduplication or I02 commit ledger. A
caller supplying parcels owns their availability and once-only delivery. The
connected `transfer` computes the donor debit and receiver credit together but
does not persist either. Native W08 and its old receipts are unchanged.
