"""Run-exact R-2: the exchange composite identity is hashed in the pack pass (stage 1) and the
packer hashes and checks once a block (stage 2); ids equal the streamed composite identity.
  python -B -I test_exchange_composite_r2.py <package parent folder>"""
import sys
import unittest
from hashlib import sha256
from types import SimpleNamespace

if __name__ == '__main__':
    sys.path.insert(0, sys.argv.pop(1))

from atlas_tectonics._private.codecs.content_cache import create_retained_scope  # noqa: E402
from atlas_tectonics._private.codecs.record_tables import RecordCodec  # noqa: E402
from atlas_tectonics._private.codecs.record_views import LogicalExchange  # noqa: E402
from atlas_tectonics._private.integration.geometry import exchange_record_patch as XP  # noqa: E402
from atlas_tectonics.integration.resources import WorkBudget  # noqa: E402

BODY = {'graph': {'nodes': [{'id': 'n%d' % i, 'x': i/7} for i in range(400)]},
        'transport': ['t'*300, 'u'*70000, 12, None, True], 'note': 'exchange'}
STATE_ID, OTHER_ID = 'a'*64, 'b'*64


class ExchangeComposite(unittest.TestCase):
    def setUp(self):
        self.scope = create_retained_scope(WorkBudget(256*1024**2), process_epoch='exchange-composite-r2')

    def pack(self, also=None):
        return RecordCodec().pack_record(BODY, record_schema=XP.BODY_SCHEMA, scope=self.scope,
                                         check=lambda: None, also=also)

    def streamed(self, record, state_id):
        body = LogicalExchange(record, record._root)
        try:
            return body.composite_identity(state_id).sha256
        finally:
            body.close()

    def composite(self, state_id):
        return XP._pack_with_composite(BODY, state_id, self.scope, lambda: None)

    def holder(self, record):
        state = SimpleNamespace(state_id=STATE_ID, _budget=self.scope.run_budget)
        return SimpleNamespace(_record=record, state=state)

    def test_e1_second_hash_leaves_body_identity(self):
        plain, fed = self.pack(), self.pack(sha256())
        self.assertEqual(plain.identity(), fed.identity())

    def test_e2_result_id_from_pack_pass(self):
        record = self.composite(STATE_ID)
        self.assertEqual(record._composite[1], self.streamed(record, STATE_ID))
        holder = self.holder(record)
        XP.initialise(holder)
        self.assertEqual(holder._result_id, self.streamed(record, STATE_ID))

    def test_e3_other_state_is_computed(self):
        record = self.composite(OTHER_ID)
        holder = self.holder(record)
        XP.initialise(holder)
        self.assertEqual(holder._result_id, self.streamed(record, STATE_ID))
        self.assertNotEqual(holder._result_id, record._composite[1])
    def test_e5_block_hash_equals_canonical_bytes(self):
        from atlas_tectonics.integration.resources import canonical_json
        record = self.pack()
        self.assertEqual(record.identity().sha256, sha256(canonical_json(BODY)).hexdigest())
        self.assertEqual(record.identity().canonical_bytes, len(canonical_json(BODY)))


if __name__ == '__main__':
    unittest.main()
