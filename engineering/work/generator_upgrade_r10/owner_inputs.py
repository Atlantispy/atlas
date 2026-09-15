"""Explicit owner meanings, not adopted numerical defaults or new canon."""
from pathlib import Path
import hashlib
import stat

ROOT=Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace/02_Working_Files/Geography')
PINS=(
    ('Generator_Terrain_Requirements/Seasonal_Water_R10/Seasonal_Water_Input_Contract_R1.md','ab46c7199d66847bb0c05a5c243dabae8c1cedced478e42ce4e72186c5d26031','R10 owner once-only seasonal liquid forcing, persistent physical water, budget, restart and downstream limits'),
    ('Generator_Terrain_Requirements/Seasonal_Water_R10/Seasonal_Water_Source_Register_R1.md','4e2387582599584219e0aa6322c325325891572e38aa9fd61c503f98f697c3e6','R10 owner water source support and missing dynamic water model distinctions'),
    ('Climate_Biomes_Soils/Seasonal_Inputs/2026-09-11-R1/R10_SEASONAL_CLIMATE_SOILS_INPUTS_2026-09-11_R1.md','02e8a6dd6cd50d9dc5d5f80c6280f32ad9f3532ba6de007d301fdcde4f93f1df','R10 owner seasonal plant demand, persistent water, diagnostic carbon and conditional thermal limits'),
    ('Climate_Biomes_Soils/Seasonal_Inputs/2026-09-11-R1/R10_SEASONAL_CLIMATE_SOILS_SOURCE_BINDINGS_2026-09-11_R1.md','e979c223947a381c37657e1dd14eb7ced981985fdec8e05d4d182cab28335c1b','R10 owner exact climate/soil code sources and input statuses'),
    ('Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-10-R1/CLIMATE_SOILS_OWNER_DECISION_2026-09-10_R1.md',
     'ba909d8a3e34a1722cba51925d602eca28d749a91a7bbf2162baf99221b4de19','owner climate calendar/wind/humidity and soil drainage definitions; source statuses and conditional development limits'),
    ('Ecology/R9_Input_Contract/INPUT_CONTRACT.md','abba2e6b724fc1245f4523d4feb32db08d316e351835f3ede4c14ef40912e7a0','owner fixed-snapshot seasonal ecology/plant constraints; numerical unknowns, not invented phenology'),
    ('Ecology/R9_Input_Contract/ROSTER_BIOLOGY_SOURCES.md','04dc274cea52edd97b091b582a161f198aeb54da8c8b9c26cc8b2ccc2d12de99','exact plant identities and qualitative seasonal biology with separate source statuses'),
)


def source_bindings():
    result=[]
    for relative,expected,role in PINS:
        path=ROOT/relative
        for p in (path,*path.parents):
            info=p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400: raise ValueError('linked owner source refused')
        if not path.is_file() or path.stat().st_size>32768: raise ValueError('bounded explicit owner source required')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ValueError('owner source changed; no silent repin')
        result.append({'path':str(path),'sha256':expected,'role':role})
    return result
