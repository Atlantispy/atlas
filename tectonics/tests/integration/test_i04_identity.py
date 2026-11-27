"""Check membership of the selected modules in the source and execution inventories.
SPDX-License-Identifier: AGPL-3.0-only
"""
import unittest

from atlas_tectonics.integration import reuse

NEW = (
    'integration.ports',
    'integration.coupling.driving',
    'integration.family',
)


class ExecutionIdentityTests(unittest.TestCase):
    def test_the_new_modules_are_in_the_source_membership_inside_the_file_limit(self):
        sources = reuse._source_bytes()
        for name in NEW:
            self.assertIn(name.replace('.', '/')+'.py', sources)
        self.assertLess(len(sources), reuse._SOURCE_FILES)
        self.assertEqual(reuse._SOURCE_FILES, 512)

if __name__ == "__main__":
    unittest.main()
