from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import cli,storage as st,provenance as pv
from .reference import recipe


class PublicRunnerTests(unittest.TestCase):
    def test_actual_saved_joint_state_readback(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)):
            root,receipt=cli.execute(recipe(),'initial',stop_after=0)
            read=st.read_reference(root)
            self.assertEqual(read['receipt'],receipt)
            self.assertEqual(read['checkpoint.json']['state'],read['result.json']['state'])
            self.assertEqual(len(read['result.json']['state']['members']),3)
            self.assertFalse(receipt['production_installed'])

    def test_no_overwrite_completed_run(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'retained',stop_after=0);before=st.read_reference(root)
            with self.assertRaises(FileExistsError):cli.execute(recipe(),'retained',stop_after=0)
            self.assertEqual(st.read_reference(root),before)

    def test_source_drift_before_save_leaves_no_artefact(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)),patch.object(pv,'verify_identity',side_effect=ValueError('source drift')):
            with self.assertRaisesRegex(ValueError,'source drift'):cli.execute(recipe(),'drift',stop_after=0)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_changed_input_checkpoint_refused_before_save(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'initial',stop_after=0);cp=st.read_reference(root)['checkpoint.json']
            changed=recipe();changed['events'][0]['atmosphere']['reference_temperature_c']+=1
            with self.assertRaisesRegex(ValueError,'different recipe or actual source'):cli.execute(changed,'changed',stop_after=0,resume=cp)
            self.assertFalse((Path(folder)/'changed').exists())

    def test_extra_artefact_refused(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'initial',stop_after=0);st.write_json(root/'unbound.json',{})
            with self.assertRaisesRegex(ValueError,'inventory'):st.read_reference(root)

    def test_foreign_run_id_refused(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(st,'OUTPUT_ROOT',Path(folder)):
            with self.assertRaisesRegex(ValueError,'run ID'):cli.execute(recipe(),'../elsewhere',stop_after=0)
            self.assertEqual(list(Path(folder).iterdir()),[])


if __name__=='__main__':unittest.main()
