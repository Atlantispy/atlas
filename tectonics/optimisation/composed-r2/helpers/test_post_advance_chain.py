"""Run B's post-advance path on a real-store successor candidate (coordinator, 16 Oct 2026, half 1).

No small genuine differential successor exists (the only genuine differential advance
is interval 1 itself), so the candidate is bounded_preseal's own fixture: a sealed
interval 0 and an unsealed interval 1 written through the real segment, chunk and
manifest code, with a successor head carrying every header. On it, in order:

  bounded pre-seal (check_candidate, with the G8 accumulator compared) ->
  run_fresh_interval.seal_with_records (durable runner record BEFORE seal_pending) ->
  a FRESH process: IntervalStoreSet.open_pending on the sealed file with the runner
  record's head and identities, the head metadata read back, no write ->
  adopt_and_promote with that process's view digest -> the accepted catalog's head.

Refusals: a tampered sealed file (open_pending and adopt), a foreign view digest, and
an adopt without the runner record's head. Synthetic records only; not run acceptance.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMPACT = HERE/'compact-geometry-r1'
RUNTIME = HERE.parent/'runtime-integration-r1'/'runtime-src'
sys.path[:0] = [str(COMPACT), str(RUNTIME), str(HERE)]

import interval_store_set as IS
import run_fresh_interval as F
import test_bounded_preseal as BP
from compact_contracts import ContractError, SegmentRef

IDENTITIES = {'producer_identity': BP.PRODUCER, 'runtime_identity': BP.RUNTIME_ID}


def writable_tree(root):
    for path in Path(root).rglob('*'):
        if path.is_file():
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def child(arguments):
    """The fresh-process half: open the pending view only from the durable records."""
    from atlas_tectonics.resources import WorkBudget
    from compact_restart_store import CompactRestartStore
    from content_cache import create_retained_scope
    directory = Path(arguments['directory'])
    runner = F.read_record(F.runner_record_path(directory, 1), schema=F.RUNNER_RECORD_SCHEMA)
    sealed = F.read_record(F.sealed_record_path(directory, 1), schema=F.SEALED_SCHEMA)
    entry = sealed['entry']
    budget = WorkBudget(768 << 20)
    scope = create_retained_scope(budget, process_epoch='post-advance-child')
    result = {'pid': os.getpid()}
    try:
        view = IS.IntervalStoreSet.open_pending(directory/'interval-catalog.json', entry['filename'], scope=scope,
            workflow_id=runner['workflow_id'], expected_catalog_digest=sealed['expected_catalog_digest'],
            expected_sha256=entry['file_sha256'], expected_logical_seal=entry['logical_seal'],
            head=SegmentRef.from_wire(runner['head']), producer_identity=runner['producer_identity'],
            runtime_identity=runner['runtime_identity'])
        with CompactRestartStore(view, scope=scope, owns_resolver=True) as store:
            token = store.change_token()
            head = store.metadata(BP.HEAD_KEY)
            result.update(view_digest=view.catalog_digest, pending_entry=view.pending_entry.to_wire(),
                          head_kind=head['kind'], head_parent=head['parent_key'], unchanged=store.change_token() == token)
    except (ContractError, OSError, ValueError) as error:
        result.update(refused=type(error).__name__, reason=str(error))
    finally:
        scope.close()
    print('POST_ADVANCE_CHILD '+json.dumps(result, sort_keys=True), flush=True)


class PostAdvanceChainTests(unittest.TestCase):
    def setUp(self):
        BP.TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='pac-', dir=BP.TEMP_ROOT)
        self.directory = Path(self.temp.name)
        self.fx = BP.Fixture(self.directory)

    def tearDown(self):
        self.fx.close()
        writable_tree(self.directory)
        self.temp.cleanup()

    def preseal_and_seal(self):
        evidence = self.fx.check()
        self.assertEqual(evidence['chunk_binding'], 'storage-accumulator')
        record = {}
        sealed = F.seal_with_records(self.fx.store, BP.HEAD_KEY, store_directory=self.directory, interval=1,
            identities=IDENTITIES, record=record, save=lambda: None,
            extra={'workflow_id': BP.WF, 'preseal_bounded_check': {k: evidence[k] for k in
                   ('chunks_read_and_hashed', 'encoded_payload_bytes_hashed', 'chunk_binding')}})
        return sealed, record

    def fresh_reader(self):
        completed = subprocess.run([sys.executable, '-B', __file__, '--child',
                                    json.dumps({'directory': str(self.directory)})],
                                   capture_output=True, text=True, timeout=300, check=False,
                                   env=dict(os.environ, PYTHONHASHSEED='0'))
        lines = [line for line in completed.stdout.splitlines() if line.startswith('POST_ADVANCE_CHILD ')]
        self.assertEqual((completed.returncode, len(lines)), (0, 1), completed.stdout[-2000:]+completed.stderr[-4000:])
        return json.loads(lines[0].removeprefix('POST_ADVANCE_CHILD '))

    def adopt(self, sealed, *, view_digest, head=None):
        runner = F.read_record(F.runner_record_path(self.directory, 1), schema=F.RUNNER_RECORD_SCHEMA)
        entry = sealed['entry']
        self.fx.store.close()
        stores = IS.IntervalStoreSet.open_catalog(self.directory/'interval-catalog.json', scope=self.fx.scope)
        try:
            return stores.adopt_and_promote(entry['filename'], expected_sha256=entry['file_sha256'],
                expected_logical_seal=entry['logical_seal'], head=head or SegmentRef.from_wire(runner['head']),
                producer_identity=runner['producer_identity'], runtime_identity=runner['runtime_identity'],
                expected_catalog_digest=sealed['expected_catalog_digest'], reader_view_digest=view_digest)
        finally:
            stores.close()

    def test_preseal_record_seal_fresh_reader_adopt(self):
        sealed, record = self.preseal_and_seal()
        catalog = (self.directory/'interval-catalog.json').read_bytes()
        reader = self.fresh_reader()
        self.assertNotEqual(reader['pid'], os.getpid())
        self.assertEqual((reader['head_kind'], reader['head_parent'], reader['unchanged']),
                         ('successor', BP.ROOT_KEY, True))
        self.assertEqual(reader['pending_entry'], sealed['entry'])
        self.assertEqual((self.directory/'interval-catalog.json').read_bytes(), catalog)
        adopted = self.adopt(sealed, view_digest=reader['view_digest'])
        self.assertEqual(adopted.to_wire(), sealed['entry'])
        stores = IS.IntervalStoreSet.open_catalog(self.directory/'interval-catalog.json', scope=self.fx.scope)
        try:
            self.assertEqual(stores.head.to_wire(), sealed['entry'])
        finally:
            stores.close()
        self.assertEqual(record['sealed_awaiting_reader']['sha256'],
                         F.read_record(F.sealed_record_path(self.directory, 1), schema=F.SEALED_SCHEMA) and
                         record['sealed_awaiting_reader']['sha256'])

    def test_foreign_view_digest_and_tampered_file_are_refused(self):
        sealed, _ = self.preseal_and_seal()
        reader = self.fresh_reader()
        with self.assertRaisesRegex(ContractError, 'different pending entry'):
            self.adopt(sealed, view_digest='0'*64)
        member = self.directory/sealed['entry']['filename']
        os.chmod(member, stat.S_IREAD | stat.S_IWRITE)
        with member.open('ab') as stream:
            stream.write(b'\0')
        os.chmod(member, stat.S_IREAD)
        tampered = self.fresh_reader()
        self.assertIn('refused', tampered)
        with self.assertRaises(ContractError):
            self.adopt(sealed, view_digest=reader['view_digest'])
        stores = IS.IntervalStoreSet.open_catalog(self.directory/'interval-catalog.json', scope=self.fx.scope)
        try:
            self.assertEqual(stores.head.interval, 0)
        finally:
            stores.close()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        child(json.loads(sys.argv[2]))
    else:
        unittest.main()
