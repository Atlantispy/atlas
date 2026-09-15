from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import cli,storage,provenance
from .pipeline import run
from .reference import recipe


class PublicRunnerTests(unittest.TestCase):
    def test_actual_save_and_readback(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)):
            root,receipt=cli.execute(recipe(),'reference')
            read=storage.read_reference(root)
            self.assertEqual(read['result.json'],run(recipe()))
            self.assertEqual(read['receipt'],receipt)
            self.assertFalse(receipt['production_installed'])

    def test_saved_checkpoint_resumes_actual_run(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)):
            first,_=cli.execute(recipe(),'first',stop_after=1)
            checkpoint=storage.read_reference(first)['checkpoint.json']
            second,_=cli.execute(recipe(),'second',resume=checkpoint)
            self.assertEqual(storage.read_reference(second)['result.json'],run(recipe()))

    def test_no_overwrite_completed_run(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'retained',stop_after=0)
            before=storage.read_reference(root)
            with self.assertRaises(FileExistsError):cli.execute(recipe(),'retained',stop_after=0)
            self.assertEqual(storage.read_reference(root),before)

    def test_current_source_drift_fails_before_save(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)),patch.object(
            provenance,'source_identity',side_effect=[({'revision':1},'a'*64),({'revision':2},'b'*64)]):
            with self.assertRaisesRegex(ValueError,'source changed'):cli.execute(recipe(),'drift',stop_after=0)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_extra_artifact_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'extra',stop_after=0)
            storage.write_json(root/'foreign.json',{'not':'part of run'})
            with self.assertRaisesRegex(ValueError,'inventory'):storage.read_reference(root)

    def test_tampered_result_readback_rejected(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'OUTPUT_ROOT',Path(folder)):
            root,_=cli.execute(recipe(),'tamper',stop_after=0)
            # Test corruption is scoped to a newly created temporary fixture.
            (root/'result.json').write_bytes(b'{}')
            with self.assertRaisesRegex(ValueError,'checksum'):storage.read_reference(root)

    def test_duplicate_recipe_key_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):storage.decoded(b'{"schema":1,"schema":2}')

    def test_current_prior_sources_and_contracts_verified(self):
        identity,digest=provenance.source_identity()
        self.assertEqual(len(identity['protected_sources']),161)
        self.assertEqual(len(identity['category_contracts']),4)
        self.assertEqual(len(identity['predecessors']),3)
        self.assertEqual(len(digest),64)
        self.assertTrue(all(r['tests_rerun'] is False for r in identity['predecessors']))


if __name__=='__main__':unittest.main()
