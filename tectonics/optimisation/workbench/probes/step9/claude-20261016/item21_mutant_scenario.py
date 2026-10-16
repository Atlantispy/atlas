"""Item 21 mutants: one test_prepared_interval_driver scenario, with a mutated driver first on sys.path.

Usage (run by item21_mutants.py): python -B item21_mutant_scenario.py <mutant-folder> <scenario> <output-folder>
The mutant folder holds only prepared_interval_driver.py; every other module resolves from the resumability
folder three levels up, as in the unmutated scenario run.
"""
import sys
from pathlib import Path

RESUMABILITY = Path(__file__).resolve().parents[3]
mutant, scenario, directory = sys.argv[1:4]
sys.path[:0] = [mutant, str(RESUMABILITY)]

import test_prepared_interval_driver as T  # noqa: E402

T.scenario_main(scenario, directory)
