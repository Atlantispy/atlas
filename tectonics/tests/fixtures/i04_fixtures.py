"""Re-export of the packaged fixture."""
import sys

from atlas_tectonics._fixtures.tests import i04_fixtures

sys.modules[__name__] = i04_fixtures
