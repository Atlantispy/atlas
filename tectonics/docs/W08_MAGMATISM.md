# W08 step 5: finite-source magmatism

23 September 2026. WORKING NON-CANON. Step5 is COMPLETE for the prescribed
finite-transfer C06 route. The frozen design and original A04-A06 gates remain
unchanged. Step6 owns joined regime histories, checkpoint/restart and combined
acceptance; this increment does not replay R4.4.

## Implemented route and ownership

- `magmatic_thermodynamics.py`: exact supplied common-Tm enthalpy inversion,
  unequal component heat capacities, phase-change plateau, signed external heat,
  and heat-paid finite solid-to-liquid conversion. Already-liquid extraction
  does not pay latent heat again. Empty stocks have no invented temperature or
  melt fraction. Properties and the enthalpy reference are identity-bound.
- `magmatic_transfer.py`: finite source-melt, well-mixed reservoirs, intrusive,
  extrusive and export stocks. Mass rates are supplied kg/s, donor rows and
  receiver columns. Components and isobaric enthalpy evolve together; exports
  sample the evolving reservoir, not its initial mixture. Solid melting is a
  separate paid conversion. Sorted IDs make simultaneous outlets order-neutral.
- `magmatic_emplacement.py`: mass-weighted placement at receiving density,
  surface extrusion or basal underplating, and finite host displacement or
  replacement. Host volume, components and signed enthalpy go to an explicit
  destination. Incoming/outgoing thermal conventions must match. Net structural
  load is incoming minus outgoing host mass per area, not gross injected mass.

`result.payload(edge_index, source_density)` only exposes terminal intrusive or
extrusive transfers. Placement entries give one owner for their volume, net
load and advected enthalpy; advected heat is not also a new heat source. An entry
does not itself run the W03/W04/W07 structural or thermal solvers. The Step6
history owner must book it once and reject incompatible alternative branches.
`accounting_entries` already refuses repeated transfer IDs and reuse of the
same host-stock snapshot in a supplied batch. It is not a persistent transaction
ledger: different-duration evaluations are alternatives from the same start,
not additive increments. Consecutive evolution uses the returned remaining
inventory and an explicitly supplied next segment.

## Numerical design and efficiency

Homogeneous finite feeds and constant-mass mixed reservoirs use an augmented
matrix exponential, including cumulative edge transfers. Held feed states stay
extensive and coefficients use q/M0: the operator is not made badly scaled merely
by changing the mass unit or source size. Positive and negative heat have separate
nonnegative source maps, combined with signed energies only at materialisation.
No negative component mass is clipped into a pass.

Changing-mass mixtures use DOP853 with every accepted transfer map checked for
nonnegative material-origin coefficients, finite values and final compensated
extensive closure. DOP853 is not an unconditionally positivity-preserving method;
the supported route is admission-gated and refuses a negative map. It retains
only active integration state, not a growing history. A mixed-reservoir endpoint
with simultaneous recharge and exact depletion is singular in this formulation
and is refused unless a separately resolved endpoint law is supplied. Exact
homogeneous finite-source exhaustion, including competing outlets, is supported;
continuation beyond it is refused, never silently clamped or extrapolated.

Per segment: at most64 nodes,64 components,256 simultaneous edges,256 accepted
integration intervals and4096 derivative evaluations; one native thread and
128MiB admitted work. These are explicit prototype admission limits, not an RSS
measurement or planetary performance claim. Thermal/placement detached snapshots
are caller-owned, as in the existing column kernels; retained transfer arrays
remain leased for their lifetime. Plans are thread-bound, non-reentrant and
source-verified. They keep one latest result and one latest exact operator.
All three new modules participate in the existing execution source identity.

## Acceptance and measured evidence

The [r1 fixture](../cases/w08_magmatism_r1.json) was frozen before the joined
candidate run; SHA256
`b0eade66ba4c196f9775dc83039bb210a8182e42913673652771389d550c2cb4`.

52 new focused methods have passing evidence:20 thermodynamics,21 emplacement,
11 transfer/integration. The final changed transfer code and9 shared identity
methods passed together in5.093s. The unchanged thermal/emplacement methods had
already passed in the first joined run. Static checks passed13 maps/41 paths;
31 coding-safety methods completed in0.114s with one environmental skip.

The first joined run exposed a signed-heat matrix issue; retaining nonnegative
source maps fixed it. A stronger physical-scale benchmark then exposed poorly
scaled held-feed coefficients; q/M0 fixed that without changing the governing
equations or acceptance thresholds. A test requiring bit-exact recipient masses
was corrected to the frozen floating-point gate (observed discrepancy below
2e-15kg); the exhausted source still has exactly zero mass and enthalpy.

Controls cover A04 finite throughflow and competing source exhaustion; A05 exact
continuous mixing/cumulative exports, unequal-cp325K mixing and2200J complete
crystallisation; A06 receiving volume and finite host accounting;1/2/4 event
partitions and8/16/32 spatial cells. A separate variable-mass analytic solution
checks the adaptive route to the unchanged1e-10 normalised gate. Extensive gates
remain128 binary64 eps times account magnitude, with compensated sums.

Independent physical control uses Calogero et al.'s basalt cp1480J/(kg K),
latent heat400000J/kg, melt density2830kg/m3 and solid density3100kg/m3.
Cooling a declared1m3 parcel from1423.15K to473.15K releases5.11098GJ and yields
0.9129032258064516m3 solid, preserving2830kg. Finite host replacement uses the
paper's granitoid density2650kg/m3. Endpoint/area/volume normalisation and common
Tm1200K are explicit scenario choices, not paper parameters. Complete cooling
energy is independent of the chosen Tm between these endpoints. This checks
calorimetry and density conversion, not the paper's full transient sill model.

Three rotated repeats on native Windows, with identical materialised output
identities, include input setup, context creation, source verification, transfer,
phase inversion and32-cell emplacement:

| Three requested outputs | Fresh preparation | Prepared reuse | Saved |
| --- | ---: | ---: | ---: |
| Different durations1/2/3s |0.8076002s|0.3577272s|0.4498730s /55.7049%|
| Identical duration3/3/3s |0.8101634s|0.3253394s|0.4848240s /59.8427%|

These are medians, not a first-ever-process import or whole-generator speedup.
Both routes share immutable scenario inputs; the baseline rebuilds the plan and
execution context for each output. The largest measured operation reservation
was231808bytes, excluding separately owned inputs/context/interpreter baseline.
The [raw timing report](../evidence/w08-magmatism-timing.json) retains every trial,
full source digests, fixture identity and output identities.

Commands run from the repository root with `PYTHONPATH=tectonics/src;tectonics/tests`
(native Windows science environment; no Linux run claimed):

```text
python -B -m unittest test_w08_magmatic_transfer test_w08_magmatic_thermodynamics test_w08_magmatic_emplacement -v
python -B -m unittest test_w08_magmatic_transfer -q
python -B tectonics/tools/check_w08_magmatism.py --report <local-report.json>
python -B -m unittest test_w08_magmatic_transfer test_execution_reuse.IdentityTests -q
python -B tools/check_coding_safety.py
python -B -m unittest discover -s tests -p test_coding_safety.py -q
```

## Papers and software checked

- [Spera and Bohrson (2002), EC-RAFC](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2002GC000315)
  and [author software page](https://magma.geol.ucsb.edu/papers/ECAFC.html):
  coupled finite energy/mass/species accounts and recharge. Guidance, not a
  reproduced EC-RAFC crystallisation/assimilation model; spreadsheet not executed.
- [Keller and Suckale (2019)](https://doi.org/10.1093/gji/ggz287), equation39c
  and AppendixB6: separate transport and latent reaction energy.
- [ASPECT latent-heat source](https://raw.githubusercontent.com/geodynamics/aspect/main/source/heating_model/latent_heat_melt.cc):
  reaction heating is not advected enthalpy a second time. Source inspected;
  ASPECT was not installed or run.
- [Calogero, Hetland and Lange (2020)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2018JB016773),
  Table1 and section3: independently sourced calorimetric/density inputs above.
- [Rhodes et al. (2024)](https://doi.org/10.1038/s41598-023-50880-0): host
  accommodation requires explicit mechanics; no universal accommodation ratio
  was imported from this paper.
- [SciPy expm](https://docs.scipy.org/doc/scipy/reference/generated/scipy.linalg.expm.html)
  (Al-Mohy and Higham's scaling/squaring method) and
  [DOP853](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.DOP853.html):
  official algorithm/API documentation. The implementation ran withSciPy1.17.1;
  documentation access does not imply installation of its latest version.
