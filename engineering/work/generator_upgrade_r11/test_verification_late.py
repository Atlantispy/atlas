"""Late orchestration failures cannot leave a successful worker receipt.

These are isolated verifier-control tests, not scientific execution evidence.
No ancestor run, real source replacement or saved production artifact is used.
"""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace as N
import unittest
from unittest.mock import Mock, patch
from . import binding, verify as v


class LateVerificationTests(unittest.TestCase):
    def test_pinned_reader_hashes_the_exact_once_consumed_bytes(self):
        raw=b'{"proof":"the checked bytes"}'
        reader=Mock(side_effect=[raw,b'{"proof":"different second read"}'])
        path=N(is_file=lambda:True,stat=lambda:N(st_size=len(raw)),read_bytes=reader)
        decoder=Mock(side_effect=json.loads)
        storage=N(plain_path=lambda ignored:path,decoded=decoder,MAX_BYTES=8*1024*1024)
        result=v.read_pinned_json(storage,'isolated fake path',v.sha(raw))
        self.assertEqual(result,{'proof':'the checked bytes'})
        reader.assert_called_once_with(); decoder.assert_called_once_with(raw)

    def test_pinned_reader_rejects_mismatch_before_decoding(self):
        raw=b'{"proof":"changed"}'
        reader=Mock(return_value=raw)
        path=N(is_file=lambda:True,stat=lambda:N(st_size=len(raw)),read_bytes=reader)
        decoder=Mock(side_effect=AssertionError('unverified bytes were decoded'))
        storage=N(plain_path=lambda ignored:path,decoded=decoder,MAX_BYTES=8*1024*1024)
        with self.assertRaises(ValueError):
            v.read_pinned_json(storage,'isolated fake path','a'*64)
        reader.assert_called_once_with(); decoder.assert_not_called()

    def test_late_execution_failure_cannot_be_pass(self):
        ids=['isolated.verifier_control_case']
        tests={'status':'PASS','tests':1,'test_ids':ids,'started':ids[:],
            'stopped':ids[:],'passed':ids[:],'failures':0,'errors':0,
            'skips':0,'expected_failures':0,'unexpected_successes':0}
        source={'schema':'ISOLATED_SOURCE_IDENTITY_NOT_REAL_SCIENCE'}; digest='a'*64
        saved={}
        storage=N(read_json=lambda path:{'source_identity':deepcopy(source),'source_sha256':digest},
            write_json=lambda path,value:saved.update({str(path):deepcopy(value)}))
        bundle=N(storage=storage,identity=source,source_sha256=digest,graph=N(executed={}),parent=N())
        capture=N(executed={},active=True)
        retained=N(private_executions=Mock(return_value={}),validate_private_executions=Mock())
        output=io.StringIO(); path=Path('isolated-worker.json')
        with patch.object(v,'install',return_value=(retained,N(),capture)), \
                patch.object(binding,'load',return_value=bundle), \
                patch.object(v,'discover',return_value=(None,ids)), \
                patch.multiple(v,RELEASE_READY=True,EXPECTED_COUNT=1,INVENTORY_SHA256=v.sha(v.encoded(ids))), \
                patch.object(v,'tests',return_value=tests), \
                patch.object(v,'artifacts',return_value={'explicit_mock':'not a scientific artifact'}), \
                patch.object(v,'stable'), \
                patch.object(v,'validate_execution',side_effect=ValueError('LATE_EXECUTION_BINDING_FAILURE')) as late, \
                redirect_stdout(output):
            code=v.worker(path,Path('isolated-parent-source.json'),sys.flags.optimize)
        self.assertEqual(late.call_count,1,saved.get(str(path),{}).get('failure'))
        self.assertEqual(code,1)
        record=saved[str(path)]
        self.assertEqual(record['status'],'FAIL')
        self.assertEqual(record['optimisation_flag'],sys.flags.optimize)
        self.assertIn('LATE_EXECUTION_BINDING_FAILURE',record['failure'])
        self.assertIn('Traceback (most recent call last)',record['failure_traceback'])
        self.assertIn('LATE_EXECUTION_BINDING_FAILURE',record['failure_traceback'])
        self.assertFalse(capture.active)
        self.assertIn('"status": "FAIL"',output.getvalue())


if __name__=='__main__':
    unittest.main()
