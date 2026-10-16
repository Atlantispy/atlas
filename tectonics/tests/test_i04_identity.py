"""Focused I04 check: the execution identity binds the new I04 Part A package modules, inside its file limit.

reuse.py derives the bound module set from the package's own source membership. This confirms, rather than assumes,
that integration_ports, integration_driving and integration_family are in that membership, that their source bytes
and loaded code are part of the execution identity, and that the package stays inside the inventory's file limit.
SPDX-License-Identifier: AGPL-3.0-only
"""
from pathlib import Path
import unittest
from unittest import mock

import atlas_tectonics
from atlas_tectonics import integration_driving, integration_family, integration_ports, reuse
from atlas_tectonics._validation import TectonicsError

NEW = ('integration_ports', 'integration_driving', 'integration_family')


class ExecutionIdentityTests(unittest.TestCase):
    def test_the_new_modules_are_in_the_source_membership_inside_the_file_limit(self):
        sources = reuse._source_bytes()
        root = Path(atlas_tectonics.__file__).parent
        self.assertEqual(sorted(sources), sorted(path.relative_to(root).as_posix() for path in root.rglob('*.py')))
        for name in NEW:
            self.assertIn(name+'.py', sources)
        self.assertLess(len(sources), reuse._SOURCE_FILES)
        self.assertEqual(reuse._SOURCE_FILES, 512)

    def test_their_source_bytes_and_loaded_code_are_bound(self):
        fresh = reuse.execution_identity('scipy')
        with reuse.ExecutionContext('scipy') as context:
            for name in NEW:
                self.assertIn(name, context._modules)
            for name in NEW:
                altered = reuse._source_bytes()
                altered[name+'.py'] += b' '
                with mock.patch.object(reuse, '_source_bytes', return_value=altered):
                    with self.assertRaises(TectonicsError):
                        context.verify()
            context.verify()
        # Same source bytes, different loaded code: the identity must not claim the fresh source.
        for module, name in ((integration_ports, 'trace_support'), (integration_driving, 'edge_sum'),
                             (integration_family, 'starting_family')):
            with self.subTest(module=module.__name__):
                with reuse.ExecutionContext('scipy') as context:
                    original = getattr(module, name)
                    stale = lambda *args, _original=original, **kwargs: _original(*args, **kwargs)
                    with mock.patch.object(module, name, stale):
                        with self.assertRaisesRegex(TectonicsError, 'loaded implementation changed'):
                            context.verify()
                        self.assertNotEqual(reuse.execution_identity('scipy'), fresh)
                self.assertEqual(reuse.execution_identity('scipy'), fresh)


if __name__ == '__main__':
    unittest.main()
