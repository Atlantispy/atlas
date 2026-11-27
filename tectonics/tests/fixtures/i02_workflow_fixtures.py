"""Re-export of the packaged fixture."""
import sys

from atlas_tectonics._fixtures.tests import i02_workflow_fixtures

sys.modules[__name__] = i02_workflow_fixtures
