"""Split mesh_tables._decode_charge(raw) for the authenticated graph into its terms.

Read-only on sources and input; adds analysis.decode_charge_terms to result.json
beside this file. The term loop mirrors mesh_tables.py:115-131 and must sum to
the real function's result (checked).
"""
from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
R = HERE.parents[3]
C = R/'compact-geometry-r1'
RUNTIME = R.parent/'runtime-integration-r1'/'runtime-src'
GRAPH = R/'probes/structure-census-r2/structure-scratch/record-004.json'
EXPECTED = '5847e28a779395279e6270188cdc90eea2db10ac7b7a8dd017428822bcd16063'
sys.path[:0] = [str(C), str(R), str(RUNTIME)]


def terms(raw):
    strings = containers = separators = 0
    quoted = escaped = False
    for value in raw:
        if quoted:
            if escaped:
                escaped = False
            elif value == 92:
                escaped = True
            elif value == 34:
                quoted = False
        elif value == 34:
            quoted = True
            strings += 1
        elif value in (123, 91):
            containers += 1
        elif value in (44, 58):
            separators += 1
    return dict(fixed=65536, per_byte=4*len(raw), strings=128*strings, containers=256*containers,
                separators=128*separators, string_count=strings, container_count=containers,
                separator_count=separators)


def main():
    import mesh_tables as M
    raw = GRAPH.read_bytes()
    if sha256(raw).hexdigest() != EXPECTED:
        raise SystemExit('graph bytes differ')
    t = terms(raw)
    total = t['fixed']+t['per_byte']+t['strings']+t['containers']+t['separators']
    t['total'] = total
    t['matches_mesh_tables_decode_charge'] = total == M._decode_charge(raw)
    path = HERE/'result.json'
    result = json.loads(path.read_text(encoding='utf8'))
    by_type = result['decode']['full_deep_sizeof']['by_type']
    t['real_by_type_deep_sizeof'] = by_type
    t['note'] = ('charge terms vs real json.loads objects: strings term + per_byte share covers str objects; '
                 'containers + separators cover list/dict objects')
    result.setdefault('analysis', {})['decode_charge_terms'] = t
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(result, indent=1, sort_keys=True, default=str)+'\n', encoding='utf8')
    os.replace(tmp, path)
    print(json.dumps(t, indent=1))


if __name__ == '__main__':
    main()
