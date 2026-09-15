"""Final bounded owner decisions, not crop calibration or geographic authority."""
from pathlib import Path
import hashlib
from . import provenance as p

W = Path('C:/Users/LOCAL_USER/Documents/The Diadem - Local Workspace')
T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-4')
SOILS = W/'02_Working_Files/Geography/Climate_Biomes_Soils/Scientific_Upgrade_Decisions/2026-09-14-R21'
WATER = T/'02_Working_Files/Irrigation_Water_R21'
PINS = {
    W/'02_Working_Files/Geography/R21_Agriculture_Resources_Owner_Decision_2026-09-14_R1.md':
        '987b330c126138f8b76a06632be352b88242cb6f36c7483cb458a8658cd02397',
    SOILS/'R21_AGRICULTURE_SOILS_DECISION_2026-09-14_R1.md':
        'c1065da8feb0c7793a8164aab9adfc5416c367e65330eec7c8a8f775529f32ad',
    SOILS/'R21_AGRICULTURE_SOILS_SOURCES_2026-09-14_R1.md':
        '1a7ad014c0b62dc01c73936530543db9dd2783e744c98fc10905935caa3e64ad',
    WATER/'CONTRACT_R1.json': 'cbcae834471869ad025b75c11e98c02b23c07f1364228ec7d869f45006b17242',
    WATER/'REFERENCE_R1.json': 'bbd657f56146621527f2a8cbd4d3cd9e4b13d53bf332bc47963570b16feb11d5',
    WATER/'SOURCES_R1.json': 'd8668c2773ad6088822f53a827060cbd81103554a5d9f35fd33616cc4e852a05',
    Path(__file__).resolve().parents[1]/'generator_upgrade_r1/reference.py':
        'd7285fb3983334c97d2a2dd56aca5ec2a6bccb5c696f8961d6635d76a70ace2a',
}


def binding():
    return {str(path): hashlib.sha256(p.checked(path, expected)).hexdigest()
            for path, expected in PINS.items()}
