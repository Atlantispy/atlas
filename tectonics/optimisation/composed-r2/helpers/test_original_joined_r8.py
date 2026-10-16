"""The r8 joined-control helper adds one derived edit: the compact, unpublished end mesh.

G-R3-1 (b') (coordinator, 16 Oct 2026): the joined control's end thermal mesh (JC 408)
is built with compact_context=publish_mesh_patch.mesh_context(workflow, partition), so
nothing is written between the driver's opening inspect() and CollarWorkflow._publish.
r8 is original_joined_r8_transform.r8_source(r7), byte for byte; its derived text is r7's
with that one call changed. The joined control is never executed here.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
R7 = HERE/'private_heat_original_joined_r7.py'
R8 = HERE/'private_heat_original_joined_r8.py'
sys.path.insert(0, str(HERE))


def constants(path):
    """The module's literal tables and helpers, without executing the joined control."""
    source = path.read_text(encoding='utf8')
    namespace = {'__file__': str(path), '__name__': path.stem+'_constants'}
    exec(compile(source[:source.index('\nsource_bindings()\n')], str(path)+'[constants]', 'exec'),  # noqa: S102
         namespace)
    return namespace


def derived(path):
    from continuation_transfer import joined_control_source
    namespace = constants(path)
    original = namespace['_read_bound'](namespace['_SOURCE'], namespace['_SOURCE_SHA'])
    return namespace['_replace_exact'](joined_control_source(original), namespace['_EDITS'])


class OriginalJoinedR8Tests(unittest.TestCase):
    def test_composer_transform_reproduces_r8_byte_for_byte(self):
        import original_joined_r8_transform as T
        r7 = R7.read_bytes().decode('utf8')
        self.assertEqual(T.r8_source(r7), R8.read_bytes().decode('utf8'))
        with self.assertRaisesRegex(ValueError, 'anchor missing or ambiguous'):
            T.r8_source(T.r8_source(r7))

    def test_only_the_mesh_seams_differ_in_the_derived_text(self):
        import original_joined_r8_transform as T
        old, new = constants(R7), constants(R8)
        count = len(T.MESH_EDITS)
        self.assertEqual(new['_EDITS'][:-count], old['_EDITS'])
        self.assertEqual(new['_EDITS'][-count:], T.MESH_EDITS)
        self.assertEqual((new['_SOURCE_SHA'], new['_ACCOUNTS_SHA'], new['_ACCOUNT_EDITS']),
                         (old['_SOURCE_SHA'], old['_ACCOUNTS_SHA'], old['_ACCOUNT_EDITS']))
        r7, r8 = derived(R7), derived(R8)
        expected = r7
        for _label, before, after in T.MESH_EDITS:
            self.assertEqual(expected.count(before), 1)
            expected = expected.replace(before, after, 1)
        self.assertEqual(r8, expected)
        # JC 408, JC 428 and the joint-advance capture: no compact mesh reaches record() or _json.
        self.assertEqual(r8.count('**_PUBLISH_MESH.mesh_options(workflow, partition)'), 1)
        self.assertEqual(r8.count("mesh.record()['required_thermal_boundary_faces']"), 0)
        self.assertEqual(r8.count('thermal_mesh=mesh.record'), 0)
        self.assertEqual(r8.count('len(mesh._json)'), 0)

    def test_the_rest_of_the_file_is_r7(self):
        old_lines, new_lines = R7.read_text(encoding='utf8').splitlines(), R8.read_text(encoding='utf8').splitlines()
        added = [line for line in new_lines if line not in set(old_lines)]
        removed = [line for line in old_lines if line not in set(new_lines)]
        self.assertEqual(removed, [
            '_EDITS = _EDITS + _PARTITION_EDITS + _RESTART_EDITS',
            "    return dict(schema='atlas.private.original-joined-derivation.r7',",
            "exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_joined_r7]', 'exec'), globals())"])
        self.assertEqual(len(added), 5+2+2)    # the five-line R8 note, the edit table and join, two r8 tags
        self.assertTrue(added[0].startswith("R8 (16 Oct 2026, G-R3-1 (b')) adds three derived edits"))


if __name__ == '__main__':
    unittest.main()
