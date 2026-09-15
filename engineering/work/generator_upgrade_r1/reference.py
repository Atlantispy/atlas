"""Tiny explicit synthetic example exercising real coupled production and flow."""
from .agroclimate import RootZone, DayForcing, crop_season
from .land_food import LandParcel, WaterPool, option_from_crop_season
from .transport import Link
from .integration import Settlement, food_transport_snapshot


EVIDENCE = "SYNTHETIC TEST: explicit engineering oracle, not a proposed Diadem parameter set"


def food_network_reference(*, water_m3=2.0, road_capacity_kg=8.0, population=2):
    # This deliberately tiny season is not a realistic agronomic calibration.
    # 10 m², one crop/year, 1 kg/m² potential, 0.2 m³/m² net irrigation,
    # efficiency 1/2 => 0.4 m³/m² withdrawn => 2 m³ can grow 5 m² / 5 kg.
    root = RootZone(.3, .1, 1, .5, EVIDENCE, "SYNTHETIC TEST")
    days = [DayForcing(0, 0, 50, 0, 50)]*4
    season = crop_season(root, days, initial_depletion_mm=0,
                         potential_yield_kg_m2=1, yield_response_factor=1,
                         minimum_valid_et_ratio=.5, evidence=EVIDENCE, source_status="SYNTHETIC TEST")
    option = option_from_crop_season(season_result=season, option_id="grain-cycle", parcel_id="field",
        crop_id="grain", edible_fraction=1, loss_fraction=0, edible_energy_kcal_kg=1000,
        irrigation_efficiency=.5, evidence=EVIDENCE, source_status="SYNTHETIC TEST",
        one_crop_season_per_year=True)
    result = food_transport_snapshot(
        [LandParcel("field", (0,0,10,1), "shared-pool", EVIDENCE, "SYNTHETIC TEST")],
        [option], [WaterPool("shared-pool", water_m3, EVIDENCE, "SYNTHETIC TEST")],
        settlements=[Settlement("farm",0,EVIDENCE), Settlement("town",population,EVIDENCE)],
        parcel_to_node={"field":"farm"},
        links=[Link("road", "farm", "town", 1000, 1, road_capacity_kg, 0, True, "foot", EVIDENCE)],
        frame_id="synthetic-metre-grid", snapshot_id="synthetic-one-annual-cycle",
        annual_period_seconds=365*86400, annual_energy_kcal_per_person=3000,
        commodity_id="grain", commodity_energy_kcal_kg=1000, network_complete=True,
        evidence=EVIDENCE, source_status="SYNTHETIC TEST")
    return {"crop_season":season, "food_network":result}
