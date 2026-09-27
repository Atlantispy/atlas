# Atlas future modules: connected completion scopes

**Planning revision: 27 September 2026. Status: WORKING NON-CANON.**

This is the detailed scope behind [Phase C of the roadmap](ATLAS_ROADMAP.md#6-phase-c--complete-all-other-modelling-categories), covering **all 17 categories after tectonics**. Category numbers match the existing registry; they are not implementation order. Category 1 remains governed by the [tectonics integration plan](../tectonics/docs/INTEGRATION_PLAN.md). [CURRENT_STATE.md](CURRENT_STATE.md) remains the progress authority: these scopes neither certify existing code nor start another module while tectonics work is active.

The objective is to avoid another round of apparently finished components followed by discovery that their actual world-generation route was never built. Scope includes producing the inputs, connecting the methods, returning feedback, using the result and proving that route. It does not promise that research will uncover no necessary corrections.

Atlas 1.0 generates a **selected epoch with compatible seasonal conditions**. Geological construction, seasonal evolution and scenario allocation have distinct clocks. Complete planetary evolution, a general ocean/atmosphere simulator, evolutionary history and civilisation history are not prerequisites. Supported approximations must still generate coherent worlds within the declared conditions. World profiles, protected Diadem constraints and run/detail profiles remain separate under the [product and scale contract](PRODUCT_AND_SCALE_CONTRACT.md).

## Common scope: part of every module, not a later integration project

1. **A real entry-to-output route.** Name the user-visible result, public backend entry point, retained implementations and real downstream consumers. For each required input, name its upstream producer, explicit scenario parameter or supported import. A fixture, unexplained array or an assumed already-complete world is not the ordinary generation route. Standalone use accepts declared external inputs; full-world use supplies them through registered producers. Seeded defaults carry their assumptions and provenance. Missing required inputs produce an actionable unsupported/incomplete result.
2. **Methods and scope decided before dependent coding.** In the module's existing method/design document, resolve the specific questions below using applicable primary papers and existing scientific software. Record what is adopted, adapted or rejected, licences/dependencies, valid parameter ranges, and the conservation/closure laws involved. Test the highest-risk unknown with a small feasibility case before building its consumers. Do not spend weeks exhaustively researching every option or design all future modules in detail now. New evidence can revise a design; changed responsibilities must update both sides before integration.
3. **Explicit data and state ownership.** Contracts specify units, extensive versus intensive quantities, support, coordinate frame, vertical datum, masks, epoch/calendar, uncertainty, source/status and version. Identify initial conditions, boundary conditions, finite stocks and external fluxes. One owner commits each physical or allocated quantity; an exchange is counted once on each side of the same transaction. Remapping preserves the appropriate inventories rather than interpolating every field identically. Update relevant state at a common accepted endpoint, or refuse/restore the coupled change without partially publishing it.
4. **Scale and time are scientific choices.** Name the regional boundary treatment, finite-domain exchanges, process support, exchange support and output support. Include tile seams, islands, disconnected domains and, where planetary support is claimed, spherical geometry/poles. Define seasonal sampling, spin-up/history assumptions and permitted approximations. A seasonal solver need not resolve every weather event; an event model must not be presented as a seasonal probability distribution. Geomorphic change need not run at the same interval as crop or soil calculations.
5. **Integration accompanies every increment.** Deliver connected slices from a producer through the normal recipe to a saved, inspectable output and an actual consumer. Use explicit temporary drivers only for development, with the final producer and replacement point named. Close affected feedbacks before calling the module complete. A schema match, standalone benchmark or diagnostic renderer alone is insufficient. Do not add a catch-all final stage whose hidden job is to write all missing producers.
6. **Usability and recovery belong to the scope.** Expose valid masks, units, legends, statuses and provenance to the UI contract; preserve generated/imported distinctions and dependency-based staleness. New/Save/Load, read-only inspection, cancellation and supported resume must work with the new state. Supply the UI owner a small real result and exercise the connection. Save algorithm/input identities and supported continuation state without silently upgrading old results. Explain the processes and evidence in a plain-English “How this is made” section, listing papers/software actually consulted.
7. **Accuracy and efficiency are accepted together.** Declare relevant scientific tests and tolerances before tuning; use analytical/limiting controls, conservation, resolution/time-step sensitivity and reference or withheld cases as appropriate. Inspect maps/sections where morphology or placement is part of the result. Check at least one material upstream change reaches its real consumers. Measure the complete changed route, not just a kernel: cold, reused and invalidated work, and continuation where applicable. Use existing caches, prepared operators, lazy loading, bounded parallelism and storage machinery where beneficial; preserve output quality, deterministic contracts and recovery. Report raw seconds and percentages only from matched work. Estimate representative production cost before authorising large runs.

These are acceptance responsibilities, **not seven new audit rounds, a new status ledger or mandatory new infrastructure**. Reuse adequate unchanged evidence and existing adapters. A bounded increment can finish while its module remains incomplete. Module completion requires its connected capabilities and applicable feedbacks; release-scale evidence remains governed by the roadmap.

## Shared ownership and interfaces

This is the **planned responsibility split**, not a claim that current code already follows it. Confirm the retained implementation's mapping when starting each connected slice. Resolve a necessary change here and in the owning methods rather than letting two modules independently own the same state.

| Shared quantity or consequence | Owning state and required exchange |
| --- | --- |
| Tectonic forcing and inherited structure | C01 supplies identified deformation, crustal/material and thermal/history exports. C02 interprets materials; surface modules consume forcing without independently replaying the same uplift or subsidence. Existing bounded cross-domain helpers may remain; expansion belongs to the relevant owner. |
| Geological layers, soil and surface geometry | C02 owns geological identity and bedrock/stratigraphic inventories; C12 owns active soil layers/state. C03 commits the common elevation/bathymetry and geometric connectivity from accepted deformation/material changes. C13/C14 propose identified transfers. No separate competing “final terrain” in each consumer. |
| Inland water, snow and ground ice | C04 owns channels, lakes, aquifers and land snow/ice inventories for the supported model. C12 owns soil water/ice/heat. C04–C12 exchange infiltration, drainage and groundwater fluxes once; snowpack is not independently duplicated in climate and soil. |
| Atmospheric energy, moisture and precipitation | C09 owns atmospheric stores/transport and the energy balance. C10 calculates condensation/fallout and rain/snow delivery; C09 debits moisture and applies associated energy once, while C04/C12/C14 receive the same water transfer. |
| Marine boundaries and thermal forcing | C14 owns marine water/sea-level assumptions, shoreline boundaries and the supported ocean thermal/sea-ice boundary provider. C09 consumes and returns defined heat/moisture exchanges. A prescribed boundary is labelled external, not mistaken for a closed global ocean budget. |
| Sediment and changes of material | C13 owns terrestrial detachment/transport/storage exchanges; C14 owns marine transport after a named handover. C02/C12 receive the same accepted deposits/removals and C03 derives their geometric consequence, including porosity. Crossing a river mouth cannot create or lose a second copy. |
| Vegetation, biome and species fields | C08 owns shared vegetation structure/function and biome classification; C11 owns species occupancy/abundance. Cover, roots and biomass need one shared accounting basis: species-level detail refines or aggregates into functional vegetation, not a duplicate biomass stock. C12 owns soil nutrient pools for the supported biology, receiving explicit uptake/return exchanges. |
| Land, water, harvest, people and transport | C16 owns land commitments and food-production/storage accounts; C04/C12 supply allocated water; C07 owns residents and demand; C06 owns sites/hinterlands; C17 owns network capacity. Shared resources are reserved/consumed once. C15 exposes potential and recoverability, not additional copies of those stocks. |
| Hazards, political choices and consequences | C18 derives scenarios/exposure from owning physical processes; C05 owns political assignments and institutional constraints. Material damage, closures or allocation changes return to the state owner. A susceptibility map or institutional assumption cannot silently rewrite physical history. |

## Bootstrap, feedback and implementation order

Build the dependency groups below as connected increments, **not 17 isolated completion projects**. Future consumers can start with contracted drivers, but final completion must replace them with the intended producer or declare the supported external boundary.

| Group | Starting state that breaks the circular dependency | Completion connection |
| --- | --- | --- |
| Physical surface: C02, C03, C13, C14 with C04 interfaces | Tectonic exports; declared inherited materials; initial elevation/bathymetry; water inventory or explicit sea-level boundary. Use a labelled initial forcing scenario while the seasonal producer is developed. | Materials and forcing make a surface; water erodes it; sediment reaches sinks; accepted changes rebuild drainage and coasts. Do not claim a final generated landscape from a temporary forcing fixture. |
| Seasonal environment: C09, C10, C04, C12 plus C14 thermal boundary | World/orbit/calendar/atmosphere parameters, initial atmospheric/ocean state, soil profile, water/snow stores and provisional vegetation cover. These are explicit initial-condition producers, not an assumption of finished climate maps. | Climate → precipitation → water/soil/ground phase → evaporation/heat feedback. Slower surface changes return through a defined interval. |
| Ecology: C08, C11 | Parameterised functional groups and initial establishment/cover; numerical species inputs and initial occupancy/stock where species are requested. | Environment drives growth and movement; vegetation/roots/nutrients return to ground, water, climate and erosion; biome labels summarise the result. |
| Physical opportunity: C18, C15 | The shared physical/ecological fields and declared hazard/resource scenarios. | Supported hazards and finite accessible resources become constraints for actual land use and habitation. Physical hazard producers can be built earlier within their owners. |
| Human allocation: C16, C06, C07, C17 | Declared/generated demand and population totals, technology/management rules, candidate land/sites/corridors and explicit external trade boundaries. Candidates are not already realised farms, residents or roads. | Joint allocation reconciles land, water, food, labour where modelled, residents and seasonal transport. Feed realised access/supply back into locations and cultivation. |
| Political geography: C05 | Physical districts, realised human layers and supplied/generated institutional scenario. | Assignments and service constraints feed back through the same allocation mechanism without manufacturing political legitimacy from terrain. |

For each feedback group, declare the dependency graph, update order, exchange intervals, maximum iterations/work, stopping criteria and unsupported conditions in the owning recipe. Distinguish a finite transient year from a converged repeating seasonal cycle; neither is silently substituted for the other. Include relevant conserved quantities, not only small changes in output maps. Retain unmet demand and unresolved balances; do not accept the last iteration solely because the budget ran out. Terrain/coast changes invalidate dependent connectivity and routing before downstream use.

A common small **mountain-to-coast seasonal region** should grow with these increments: layered geology, ridges/valleys, a genuine lake basin, contrasting soils, a river/estuary, vegetation, then farms/settlements/network and districts. It connects the modules early and supplies reusable integration evidence. It is not by itself evidence for every climate, island geometry, species or planetary extent: add small edge/reference cases only where the claimed scope needs them. The replacement-Diadem year and scaled product cases follow the roadmap, not repeated full runs on superseded terrain.

## C02 — Geology

**Deliverable and inputs.** Generate inspectable material domains, lithology, structures and layered columns with usable mechanical, hydraulic and thermal properties and uncertainty. Tectonic exports do not supply all geological inheritance: provide declared inherited/synthetic stratigraphy, material composition and property producers alongside supported imports. Retained R26 regional/column work is a starting point, not automatic completion.

**Connected implementation slices.**

1. Tectonic exports and inherited material → consistent geological columns/structures → an actual terrain consumer.
2. Supported faulting, magmatic, metamorphic and depositional effects → changed materials/properties → soil, water and resource consumers. Clearly distinguish calculated transformations from conditioned initialisation.
3. Conservative erosion/deposition and exposure → updated finite layers and composition → terrain, sediment, soil-parent-material and resource updates.

**Ownership and feedback.** C02 owns material identity, geological columns and properties, not a second elevation model. C01 supplies deformation/history, C13/C14 supply accepted removals/deposits and C12 owns the active soil profile.

**Decide before implementation.** Discontinuity/layer representation; supported transformations; temperature/pressure/composition assumptions; property ranges; porosity/mass conventions; unresolved structures versus synthetic inheritance. A complete rock-cycle history is not required merely to initialise credible materials.

**Connected acceptance.** A generated layered catchment exposes resistant material beneath weaker cover. Exposure changes erosion and sediment composition downstream without inventing layer mass. Check cross-sections, property contrasts, layer exhaustion and discontinuities at the claimed resolution.

## C03 — Topography and topology

**Deliverable and inputs.** Produce multiscale elevation/bathymetry, mountains, ridges, valleys, scarps/cliffs and plains, plus surface connectivity and inspectable sections. Select the production connection from C01 forcing and C02 materials through C13/C14 surface processes; existing builders consuming terrain or bounded native demonstrations are not that connection by themselves.

**Connected implementation slices.**

1. Tectonic/geological baseline → initial surface and connectivity → hydrology and coast consumers.
2. Real water/material forcing → resolved landforms and changing geometry → updated drainage, exposures and sediment sinks.
3. Nested/finite regions and resolution transfers → consistent seams, coast masks and topology changes → all affected consumers and visual outputs.

**Ownership and feedback.** C03 publishes one accepted surface version. C01/C13/C14 provide identified physical changes; C04 owns water routing over the geometry. Catchment diagnostics and routing use the same surface and outlet conventions.

**Decide before implementation.** Construction horizon/process laws; modelled versus synthesised fine structure; ridge/cliff representation; depression treatment; material-to-height conversion; regional boundaries and planetary geometry. Fix generative causes of unrealistic terrain, not a post-generation beautification filter that conceals them.

**Connected acceptance.** An orogen-to-coast case produces distinct ridges, valleys and finite basins. Incision changes drainage and downstream sediment. Assess scale-matched relief, slope, curvature and drainage statistics alongside maps/sections and reference terrain; preserve real depressions, avoid grid-shaped features and uniformly gentle mountain summits. Test a relevant tile/resolution interface without claiming unsupported detail is accurate.

## C04 — Hydrology

**Deliverable and inputs.** Connected catchments, rivers, lakes and supported groundwater/snow stores with seasonal discharge, storage and usable water. C10 precipitation, C12 soil exchanges, C03 geometry and C14 downstream conditions replace runoff-only fixtures; generate or explicitly supply initial finite water stores.

**Connected implementation slices.**

1. Precipitation and soil runoff → surface routing → channel/lake/outlet accounts.
2. Infiltration, evaporation, snow accumulation/melt and aquifer exchanges → seasonal storage/discharge → soils, ecology and available-water consumers.
3. Lake spill/merge/split and changing terrain/coastal boundaries → rebuilt routing and water allocations → irrigation and settlement supply.

**Ownership and feedback.** C04 owns inland channels/lakes/aquifers and land snow/ice; C12 owns soil water/ice. Climate owns atmospheric moisture. External and marine exchanges are named boundaries, not missing balances.

**Decide before implementation.** Routing/channel approximation; lake geometry and legitimate endorheic basins; groundwater closure; snow energy/melt law; initial storage and boundary conditions. Assign land-ice mass balance here and any glacial material transport to C13. If moving glaciers are excluded initially, identify unsupported glaciated scenarios explicitly rather than producing apparently accepted ice-shaped terrain without the process.

**Connected acceptance.** A snow-fed catchment fills and spills from a basin into an estuary; every seasonal water transfer reconciles across owners. Include a closed basin, dry/low-water state and a terrain/outlet change. Withdrawals cannot exceed available storage/flow, and routing must not cross invalid divides.

## C05 — Political borders

**Deliverable and inputs.** Valid districts and political assignments, including authored constraints and explicit unassigned/disputed areas. Retain physical district/assignment work, but supply institutional actors, rules, exclusions and service assumptions through a declared authored or seeded scenario. Geography constrains access; it does not create legitimacy.

**Connected implementation slices.**

1. Physical districts → actual settlement/population/accessibility joins.
2. Supplied/generated institutional scenario → political assignments and aggregates.
3. Islands, enclaves, discontinuities and disputes → valid coverage and administration; service constraints → human-allocation feedback without overwriting protected decisions.

**Ownership and feedback.** C05 owns assignments; C06/C07/C17 own settlements, residents and services. Institutional constraints return through their normal allocation interfaces.

**Decide before implementation.** District representation; assignment objectives; permitted discontinuities/overlaps; uncertainty/conflict treatment; administrative hierarchy. Do not require a simulated civilisation history or infer culture deterministically from landforms.

**Connected acceptance.** Area/population coverage and adjacency reconcile, including islands and unassigned areas. Changing an institutional rule changes the appropriate assignment/service result without inventing terrain change or silently erasing an authored border.

## C06 — Settlements

**Deliverable and inputs.** Actual selected settlement sites, roles, sizes and supporting hinterlands, with provisional or unsupported choices visible. Terrain, seasonal water, hazards, food/resources and candidate travel costs supply opportunities; a supplied/generated demand and technology scenario supplies the social assumptions. Extend retained candidates rather than relabel them realised settlements.

**Connected implementation slices.**

1. Physical candidates and exclusion reasons → inspectable site options.
2. Roles, provisional sizes and catchments → coupled farm/population/network allocation.
3. Accepted supply/access → realised sites/hinterlands; seasonal shortage, closure and corrected terrain → explicit reallocation or relocation.

**Ownership and feedback.** C06 owns sites and hinterlands; C07 owns residents; C16/C17 own realised food and access. Overlapping hinterlands share allocated supplies rather than each claiming full capacity.

**Decide before implementation.** Site-selection model; roles/spacing; support distances; density and technology assumptions; relocation policy for provisional versus protected locations. Suitability alone does not explain urban form.

**Connected acceptance.** Selected sites are feasible and jointly supported. A blocked route or lost water source affects placement/capacity; insufficient support remains an explicit shortage, not an invented supply. Corrected terrain can relocate a provisional capital without rewriting protected provenance.

## C07 — Populations

**Deliverable and inputs.** Settlement/rural distributions, permanent and seasonal residence, reconciled totals and visible unplaced balances. Totals and demographic/demand assumptions are either supplied or generated by an explicit scenario; physical capacity is not itself desired population. Reuse retained constrained placement where suitable.

**Connected implementation slices.**

1. Population/demand scenario → candidate sites and rural areas.
2. Finite water/food/access/service capacity → accepted spatial placement and unmet balances.
3. Seasonal residence and demand → agricultural/network allocation; shortages or closures → bounded reallocation and aggregation.

**Ownership and feedback.** C07 owns persons, residence and demand. Other modules return allocated support; administrative totals are views of the same people, not separately generated populations.

**Decide before implementation.** Density/allocation rules; demand units and age/role distinctions needed by consumers; seasonal mobility; external populations/trade. Birth, mortality and long-term migration history are optional later capabilities, not necessary to place a fixed-epoch population.

**Connected acceptance.** World, district, settlement and rural totals reconcile. Seasonal movers are not counted twice, and unsupported people remain unplaced/unsupported. Altering actual food delivery must change feasible placement, not only an accompanying suitability score.

## C08 — Biomes

**Deliverable and inputs.** Seasonal vegetation structure/function and defensible biome classification, ecotones and uncertainty. Climate, water, soils and relief supply forcing; a numerical functional-type registry and declared establishment/initial-cover producer supply vegetation. Preserve biome classification as a summary, not a substitute for generating vegetation.

**Connected implementation slices.**

1. Seasonal environment and functional types → establishment/cover/productivity → ecological and land-surface consumers.
2. Vegetation roots, water/energy use and biomass → soil/hydrology/climate exchanges → changed growth conditions.
3. Accepted vegetation/environment → biome classification and transitions; supported disturbance/cultivation → updated cover and dependent fields.

**Ownership and feedback.** C08 owns the shared functional vegetation representation; C11 owns species detail. Define one biomass/cover accounting basis so aggregation or refinement does not create duplicate vegetation. C12 owns receiving soil nutrient state; supported uptake/litter returns are exchanges.

**Decide before implementation.** Functional-type representation; establishment/productivity laws; classification and seasonal aggregation; nutrient limitation, competition and disturbance scope. Fire or another disturbance needs an explicit driver/consequence model if used, not unexplained random vegetation deletion.

**Connected acceptance.** Limiting conditions and transitions affect vegetation and downstream water/energy exchanges. Cover fractions and biomass exchanges reconcile. Reclassifying a cell cannot manufacture vegetation or prove a particular species occupies it.

## C09 — Climate

**Deliverable and inputs.** Geographically coherent seasonal temperature and atmospheric forcing, including the winds/moisture transport required by consumers. Supply world/orbit/calendar/atmospheric parameters, C03 relief/land cover and C14 ocean thermal boundary. Develop a declared regional/planetary forcing producer; a finished climate map or prescribed transect is not the ordinary full-world prerequisite.

**Connected implementation slices.**

1. Planetary parameters, geography and initial atmosphere/ocean boundary → seasonal atmospheric fields.
2. Transport and surface exchanges ↔ C10 precipitation and C14 ocean boundary → atmospheric water/energy accounts.
3. Vegetation, soil heat/water and changing geography → bounded feedback → compatible seasonal forcing for the generated world.

**Ownership and feedback.** C09 owns atmospheric energy/moisture and circulation/transport. C10 reports condensation/fallout; surface owners return identified fluxes, albedo and roughness. Prescribed external heat/moisture sources remain explicit.

**Decide before implementation.** Model class and circulation closure; radiation/composition; ocean thermal approximation; geometry; seasonal sampling; valid world-parameter range and spin-up. Choose affordable consumer approximations and reference methods deliberately; do not imply general climate support from an Earth-like calibration or a small transect.

**Connected acceptance.** A seasonal coastal mountain region exhibits justified land–ocean contrasts and orographic forcing that consistently drive precipitation, soil temperature and discharge. Test model-appropriate energy/transport balances and reference regimes, with additional global circulation/seam/pole controls before claiming planetary coverage.

## C10 — Precipitation

**Deliverable and inputs.** Seasonal rain/snow amounts and rates on hydrology-compatible supports, with moisture sources and orographic effects inspectable. Connect actual C09 moisture transport and evaporation sources; a temperature-dependent phase law alone does not generate precipitation.

**Connected implementation slices.**

1. Atmospheric moisture transport → condensation/fallout → water delivered to surface owners.
2. Orography and rain/snow partition → snow, soil and river responses.
3. Evaporation recycling and support/time conversion → closed coupled seasonal transfers and consistent downstream totals.

**Ownership and feedback.** C10 calculates the transfer; C09 applies the atmospheric debit and latent-energy contribution once. C04/C12/C14 receive the same delivered water, not independent precipitation copies.

**Decide before implementation.** Condensation/orographic closure; transport/depletion; phase transition; sub-grid variability; event versus seasonal representation; recycling and latent-heat coupling. Stochastic disaggregation must preserve its declared totals and not invent empirical extreme-event frequencies.

**Connected acceptance.** Onshore moisture crosses a mountain barrier, producing justified windward rain, leeward depletion and snow storage that lead to different catchment discharge. Check moisture limits, dry/wet cases and rate–volume conversions across spatial/time resolutions.

## C11 — Plant and animal ranges

**Deliverable and inputs.** Separate suitable, accessible and occupied ranges, with finite density/stocks, growth/recruitment and seasonal residence where supported. Require numerical biological parameters, initial occupancy/stock or a declared seeded establishment scenario, dispersal barriers and resources/interactions. Obtain Diadem biological inputs through the Species coordinator; missing coefficients remain unknown rather than guessed from prose.

**Connected implementation slices.**

1. Parameter contracts and generated environment → suitable habitat with limiting factors.
2. Dispersal/accessibility and initial occupancy → realised ranges distinct from merely suitable cells.
3. Growth, reproduction, resource/nutrient limits and seasonal movement → finite abundance/residence → supported vegetation, soil and interacting-species feedback.

**Ownership and feedback.** C11 owns species stocks and response. Shared vegetation/roots/biomass map to C08's accounting basis; soils and hydrology retain their own resources. Consumption, reproduction, mortality and movement must reconcile rather than separately rescale each distribution to look plausible.

**Decide before implementation.** Species versus functional groups; habitat/dispersal formulation; required interactions; coefficient evidence/ranges; seasonal mobility and residence. Full evolution or an exhaustive food web is not compulsory, but any claimed trophic limitation needs its actual resource provider.

**Connected acceptance.** Unsuitable, unreachable and suitable-but-empty habitat stay distinct. Barriers and seasonal resources change occupancy/movement. Abundance/residence and resource exchanges reconcile; the same animal or food stock cannot support multiple simultaneous allocations.

## C12 — Soils and ground conditions

**Deliverable and inputs.** Seasonal soil moisture, heat, frozen fraction, layer/porosity/root conditions and supported nutrient/ground properties. C02 parent material needs a declared initial soil-profile producer; C09/C10/C04 supply forcing and boundaries. Initial roots/cover are labelled until C08 supplies them.

**Connected implementation slices.**

1. Parent material and initial profile → coupled water/heat state → runoff, infiltration and ground outputs.
2. Seasonal freezing/thawing, roots, evaporation and supported nutrient exchanges → water/climate/ecological feedback.
3. Erosion/deposition, deformation and cultivation → conservative remapping of the profile → changed soil, suitability and drainage conditions.

**Ownership and feedback.** C12 owns active soil layers and their water, ice, energy and supported nutrient stores. C02 owns underlying geology; C04 owns aquifers/snow; C08/C11 own growth; C13/C14 supply identified material exchanges.

**Decide before implementation.** Profile formation assumptions; constitutive/property laws; phase-change energy; rooting/nutrient scope; groundwater boundary and changing-ground remapping. Initial soil development can be a declared conditioned model, not a mandatory long pedogenesis simulation. Temperature must respond to evolving moisture, not permanently retain its starting value.

**Connected acceptance.** Contrasting soils change seasonal infiltration, freeze/thaw and catchment runoff. A deposit carries its material and accounted water/energy into the receiving profile; an eroded layer cannot leave hidden water or nutrients behind. Test dry/saturated and freeze/thaw limits under the supported laws.

## C13 — Erosion and sediment transport

**Deliverable and inputs.** Source-to-sink detachment, transport, stored/deposited sediment and supported stratigraphy that actually change terrain. Use C04 discharge, C02/C12 finite exposed materials and downstream accommodation/boundaries, not only prescribed fixture forcing. Reuse applicable retained terrain/W09 work.

**Connected implementation slices.**

1. Real runoff, slopes and finite layers → hillslope/channel erosion and transport → C03 geometry change.
2. Grain/material sorting, channel/hillslope storage and deposition → soil/geological inventories and exposure updates.
3. River export → C14 estuary/coastal sinks → changed coast/drainage → updated subsequent forcing.

**Ownership and feedback.** C13 owns terrestrial sediment transfers/stores, not duplicate geological layers or final elevation. Material owners commit removals/deposits and C03 publishes their geometric consequence. Marine transport takes ownership at the declared interface.

**Decide before implementation.** Required hillslope/fluvial and any glacial/aeolian processes; grain classes; transport/capacity laws; channel support; porosity and source-to-height conversion; geological construction versus seasonal exchange timescales. Excluding a process must also bound the terrain/settings that can be accepted.

**Connected acceptance.** A sediment pulse from a layered hillslope passes through channel stores and deposits at the coast. Finite grain/material balances, exposure, bed elevation and drainage all respond consistently. Check exhausted layers, deposition, export and a relevant change of resolution without counting transferred mass twice.

## C14 — Seas and coastal processes

**Deliverable and inputs.** Consistent sea level, bathymetry, shorelines/estuaries, supported coastal flow/sediment behaviour and the ocean thermal boundary needed by climate. Supply a declared water/sea-level scenario, C03 bathymetry, river delivery and tidal/wave/current forcing producers or explicit external scenarios. A coastal flow solver is not an ocean-climate provider by itself.

**Connected implementation slices.**

1. Bathymetry, datum and water reference → wet/dry mask, river-mouth joins and initial thermal boundary.
2. River water/sediment and supported forcing → estuary/coastal exchanges, deposition and wetting/drying.
3. Updated bed/shoreline and supported heat/moisture exchange → terrain, inland routing and atmospheric boundary updates.

**Ownership and feedback.** C14 owns marine boundary/state and marine sediment after handover. C03 commits bed geometry, C04 owns inland delivery and C09 consumes/returns thermal/moisture exchanges. Sea ice, if supported, belongs to this boundary model rather than duplicated atmospheric ice.

**Decide before implementation.** Prescribed sea level versus finite-volume solution; datum; estuary representation; forcing/tide/wave/current scope; thermal/sea-ice approximation; open-ocean boundaries. Unsupported ocean physics remains a declared boundary, not a claim of a full global ocean model.

**Connected acceptance.** A river pulse reaches an estuary under selected coastal forcing, changes deposition/wet areas and updates inland boundaries without losing water/sediment. Include dry-to-wet transition and sea-level sensitivity; climate sees the declared thermal boundary and its actual exchange assumptions.

## C15 — Resources and land suitability

**Deliverable and inputs.** Resource occurrence/potential, supported finite stocks, access/recoverability and purpose-specific suitability with limiting factors. C02/C08/C11 supply occurrence or a declared conditioned synthetic producer; technology/management and use requirements come from the scenario. Existing resource arrays/registers are retained inputs, not proof of reserves.

**Connected implementation slices.**

1. Provenance-linked materials/biological resources → potential and supported stock layers.
2. Purpose-specific physical constraints and technology → suitability, recoverability and limiting factors.
3. Real access/extraction allocations → supported productive capacity → depletion/renewal feedback where claimed.

**Ownership and feedback.** Each finite stock has its physical/biological owner; C15 publishes its resource interpretation and available allocation, not a second stock. C16/C17 consume allocations and return usage/access constraints.

**Decide before implementation.** Resource classes; geological/ecological occurrence assumptions; extraction/renewal scope; suitability method and units; competing users. Distinguish mineral occurrence, reserve, accessible stock and production rate. Do not turn arbitrary scores into probabilities or invent a deposit to satisfy demand.

**Connected acceptance.** A material/resource contrast affects actual access and use. Competing consumers cannot spend the same stock twice; depletion/renewal reconciles where supported, and unknown inputs remain visible rather than scoring as zero or ideal.

## C16 — Land use and agriculture

**Deliverable and inputs.** Actual cultivated/other committed land, crops/calendars, finite irrigation and seasonal harvest/food accounts. Supply numerical crop/management, labour/technology and nutritional-demand assumptions, generated climate/soil/water, candidate land and provisional access. Route Diadem biological parameters through the Species coordinator.

**Connected implementation slices.**

1. Seasonal conditions, crop parameters and constraints → feasible crop/land options.
2. Options, population demand and site/network candidates → joint accepted land/crop commitments.
3. Coupled soil, finite irrigation and management → harvest, storage/loss accounts and delivered food → shortage, land-cover and soil feedback.

**Ownership and feedback.** C16 owns land commitments and production/storage; C04/C12 own water, C07 owns demand and C17 owns transport. Suitability is not harvested food. Non-crop land uses, protected land and competing commitments share one area account.

**Decide before implementation.** Crop response/yield model; calendars and management; labour/input limits; nutrition units; storage/loss/trade assumptions and supported irrigation methods. Do not require economic history, but do supply the management/technology assumptions needed to generate realised cultivation.

**Connected acceptance.** A seasonal farm-to-settlement case reconciles area, irrigation, crop growth, harvest, losses and delivered food. Drought or network closure changes support and allocations. Compare relevant crop-response controls; no irrigation or imported food appears without a source.

## C17 — Infrastructure and connectivity

**Deliverable and inputs.** Feasible routes/facilities with modes, travel costs, finite capacity and seasonal availability. Terrain, coasts and hydrology supply barriers/crossings; settlements, farms and resources supply provisional endpoints; the scenario supplies technology, construction constraints and demand. Existing static fields/network joins do not automatically build a usable network.

**Connected implementation slices.**

1. Physical barriers, endpoints and supported modes → candidate corridors, crossings and ports.
2. Declared selection objectives and construction limits → realised network and capacity.
3. Seasonal flow/service allocation → delivered access/support → closure, rerouting and settlement/land-use feedback.

**Ownership and feedback.** C17 owns network assets/capacities and accepted flows; C06/C07/C16 own the locations, people and goods being served. A geometric connection is not proof of throughput or food delivery.

**Decide before implementation.** Network objectives; modes; slope/crossing/port feasibility; travel/capacity laws; construction/resource limits and external links. History of construction is optional, not a hidden prerequisite for a fixed-epoch network.

**Connected acceptance.** A farm/resource-to-settlement network respects barriers and finite capacity. An isolated site and seasonal crossing closure produce explicit unmet flows and changed delivered support; a route cannot silently cross an impossible river or slope.

## C18 — Natural hazards

**Deliverable and inputs.** Supported susceptibility and event-scenario fields joined to actual population, settlement, land-use and infrastructure exposure. Tectonics, slopes, rivers and coasts supply their identified physical processes. Existing shallow-soil stability is retained work, not evidence that all hazards exist.

**Connected implementation slices.**

1. Explicit supported hazard catalogue and producer contracts → shared physical inputs.
2. Justified event/susceptibility models → footprints and intensity/severity with provenance.
3. Seasonal assets/residence → exposure and supported vulnerability/consequence models → physical damage/closures and allocation feedback through state owners.

**Ownership and feedback.** C18 joins process outputs and exposure; it does not independently invent earthquake, flood or coastal forcing. The affected owner applies any accepted material loss, route closure or population consequence once.

**Decide before implementation.** Initial hazard set; event definitions; susceptibility versus occurrence/frequency; compound-event dependence; vulnerability/consequence assumptions. Consider relevant tectonic, slope, river and coastal hazards explicitly; add fire/drought or other hazards only with real drivers. Return periods/loss probabilities require justified frequency evidence, not a score renamed as a probability.

**Connected acceptance.** A supported physical event shares the same terrain/water/material state as the normal generator, yields zero exposure where no asset/person is present, and produces a consistent closure or support consequence where one is present. Overlapping events cannot double-count the same loss; changed seasonal residence changes exposure without changing hazard physics.

## Completion and change control

Before claiming a future module complete, its common responsibilities, category-specific slices, real consumers and applicable feedbacks above must be covered by the current supported route. Required decisions are resolved in its owning method document before dependent code is built; an unresolved scientific producer is unfinished scope, not a reason to call the module complete and schedule another integration pass later.

Use [CURRENT_STATE.md](CURRENT_STATE.md) for progress and the owning method/evidence documents for results. Keep this file a scope, not a duplicate status report. Extend existing tests only for changed behaviour or missing necessary coverage; do not start a new blanket review of already accepted code because this planning document exists. If research changes the supported model, record the reason, affected consumers and completion consequence in the existing plan. No code, simulations, installations, commits or pushes are authorised by the document alone.
