"""Refuter i19, R3: request canonicalisation, family separation and record validation (no fixture).

Usage: python -B r3_requests.py TREE_SRC OUT.json
  TREE_SRC: ck/ip4/src (candidate) or the composed-r2 base src. On the base tree only the
  request_fields/_validated table for the pre-existing families runs (parity check).
Real worker-format records come read-only from ck/initpar/t4/serial.sqlite (the serial arm's
measurement store), so nothing here builds the fixture.
"""
import hashlib
import json
import sqlite3
import sys
from fractions import Fraction as Q
from pathlib import Path
from types import SimpleNamespace

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
R = T/'fidelity-integration-20261005/continuation-repair-20261013/optimisation-20261014/resumability-r1'
tree, out_path = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
sys.path[:0] = [str(tree), str(R/'composed-r2/helpers'),
                str(T/'fidelity-integration-20261005/heat-repair-20261007/source/tectonics/tests')]
import atlas_tectonics  # noqa: E402
assert Path(atlas_tectonics.__file__).resolve().is_relative_to(tree)
from atlas_tectonics import integration_parallel_binding as B  # noqa: E402
from atlas_tectonics import integration_parallel_results as PR  # noqa: E402
from atlas_tectonics import integration_differential_geometry as G  # noqa: E402
candidate = hasattr(B, 'INITIAL_VOLUME_REQUEST_FIELDS')


def store_queries():
    con = sqlite3.connect('file:%s?mode=ro' % (T/'ck/initpar/t4/serial.sqlite').as_posix(), uri=True)
    found = {}
    for (payload,) in con.execute('select payload from chunks'):
        try:
            row = json.loads(bytes(payload))
        except Exception:  # noqa: BLE001 - non-JSON chunks are not measurements
            continue
        if type(row) is dict and 'queries' in row:
            query = row['queries'][0]
            kind = 'positive' if G.W._decode(query['upper_m3']) > 0 else 'empty'
            found.setdefault(kind, query)
            if 'whole_voxel_pose_levels' in query:
                found.setdefault('poses', query)
    return found


def outcome(fn, *args):
    try:
        value = fn(*args)
        return sorted(value) if isinstance(value, frozenset) else value
    except Exception as error:  # noqa: BLE001
        return '%s: %s' % (type(error).__name__, error)


def main():
    queries = store_queries()
    positive = queries['positive']
    endpoint_request = {k: positive[k] for k in B.VOLUME_REQUEST_FIELDS}
    wall = dict(schema=G.MEASURE_SCHEMA, kind=B.WALL_KIND, support_id=positive['support_id'],
                interval_id='0'*64, logical_cell_id=positive['logical_cell_id'], axis=0, end=0,
                start_time_s=positive['time_s'], end_time_s=positive['time_s'],
                max_width_m3=positive['max_width_m3'], max_leaves=8)
    iface = {k: None for k in B.REQUEST_FIELDS}
    rel = positive['relative_error']
    table = {
        'endpoint-start': endpoint_request,
        'endpoint-end': dict(endpoint_request, endpoint='end'),
        'endpoint+rel': dict(endpoint_request, relative_error=rel),
        'endpoint-end+rel': dict(endpoint_request, endpoint='end', relative_error=rel),
        'endpoint+rel-null': dict(endpoint_request, relative_error=None),
        'endpoint+rel-negative': dict(endpoint_request, relative_error=['-0x1', '0x64']),
        'endpoint+rel-unreduced': dict(endpoint_request, relative_error=['0x2', '0xc8']),
        'endpoint+rel-int': dict(endpoint_request, relative_error=1),
        'wall': wall, 'wall+rel': dict(wall, relative_error=rel),
        'iface+rel': dict(iface, relative_error=rel),
    }
    report = dict(tree=str(tree), candidate=candidate,
                  request_fields={name: outcome(B.request_fields, req) for name, req in table.items()})
    # Structural validation through the real _validated entry (no worker): record x request families.
    fit = SimpleNamespace(admits_work=lambda units: True)
    endpoint_record = {k: v for k, v in positive.items() if k not in ('relative_error', 'relative_error_bound')}
    records = {'initial-record': positive, 'endpoint-shaped-record': endpoint_record,
               'initial-record-bound-null': dict(positive, relative_error_bound=None),
               'initial-record-rel-changed': dict(positive, relative_error=['0x1', '0x2'])}
    requests = {'initial-request': {k: positive[k] for k in B.VOLUME_REQUEST_FIELDS | {'relative_error'}},
                'endpoint-request': endpoint_request}
    validated = {}
    for rname, record in records.items():
        encoded = PR.canonical(record)
        digest = hashlib.sha256(encoded).hexdigest()
        for qname, request in requests.items():
            validated[rname+' x '+qname] = outcome(PR._validated, encoded, digest, PR.canonical(request),
                                                  {}, fit, object())
    report['validated'] = validated
    if candidate:
        from atlas_tectonics import integration_initial_parallel as IP
        # Token equality between the pass's batch member and the serial-position claim, for the
        # Python forms each side can actually be handed (start: enclose's raw relative_error and
        # local_width; claim: Q(relative_error), Q(absolute_width_m3)).
        raw = {'start_time_s': positive['time_s'], 'end_time_s': positive['time_s'], 'interval_id': '1'*64,
               'components': []}
        support = SimpleNamespace(support_id=positive['support_id'], _json=b'{}', record=lambda: raw)
        budget = atlas_tectonics.resources.WorkBudget(1 << 30)
        tokens = {}
        cases = {'rel int 0 / Q(0)': (0, Q(0), Q(32000)/969, Q(32000)/969),
                 'rel Q(1,100)': (Q(1, 100), Q(1, 100), Q(32000)/969, Q(32000)/969),
                 'rel Q(2,200) / Q(1,100)': (Q(2, 200), Q(1, 100), Q(32000), Q(32000)),
                 'width int / Q': (Q(1, 100), Q(1, 100), 32, Q(32)),
                 'width differs by 1/10**30': (Q(1, 100), Q(1, 100), Q(32), Q(32)+Q(1, 10**30))}
        for name, (r_start, r_claim, w_start, w_claim) in cases.items():
            session = IP.InitialParallelSession(budget=budget, max_width_m3=w_start, max_leaves=1 << 30,
                                                workers=1, relative_error=r_start)
            member = session.member_request(support, positive['logical_cell_id'], 'start', {})
            claim = IP.initial_request(support, positive['logical_cell_id'], raw['start_time_s'],
                                       Q(w_claim), 1 << 30, Q(r_claim))
            tokens[name] = dict(equal=PR.canonical(member) == PR.canonical(claim),
                                fields=outcome(B.request_fields, claim))
        report['tokens'] = tokens
        # Initial vs endpoint validator parity: each mutation the endpoint validator refuses on the
        # endpoint-shaped record must also be refused on the initial record.
        endpoint_req = PR.canonical(endpoint_request)
        initial_req = PR.canonical(requests['initial-request'])
        mutations = {
            'pristine': {}, 'leaves-over': {'leaves': positive['max_leaves']+1}, 'leaves-zero': {'leaves': 0},
            'leaves-bool': {'leaves': True}, 'work-bool': {'work_units': True}, 'work-float': {'work_units': 1.0},
            'met-int': {'met': 1}, 'lower-neg': {'lower_m3': ['-0x1', '0x1']}, 'lower-bad': {'lower_m3': ['0x01', '0x1']},
            'witness-neg': {'positive_witness_m3': ['-0x1', '0x1']}, 'max-leaves-bool': {'max_leaves': True},
            'poses-bad': {'whole_voxel_pose_levels': [0, 8]}, 'extra': {'extra': 1},
            'point-short': {'positive_witness_point_m': positive.get('positive_witness_point_m', [])[:2]},
            'rule-other': {'positive_witness_point_rule': 'other'}}
        parity = {}
        for name, change in mutations.items():
            try:
                e = PR._validated_volume(dict(endpoint_record, **change), endpoint_req, fit)
            except Exception as error:  # noqa: BLE001
                e = 'raises %s' % type(error).__name__
            try:
                i = IP.validated_initial_volume(dict(positive, **change), initial_req, fit)
            except Exception as error:  # noqa: BLE001
                i = 'raises %s' % type(error).__name__
            parity[name] = dict(endpoint=e, initial=i, weaker=(e is False and i is True))
        report['validator_parity'] = parity
    text = json.dumps(report, indent=1, default=str)
    out_path.write_text(text, encoding='utf8')
    print(text)


if __name__ == '__main__':
    main()
