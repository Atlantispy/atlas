"""Read-only: literal structure of next charts the census could not prove empty."""
import gzip
import json
import sys
from collections import Counter
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

capture, census, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])
rc1_env.install()
from atlas_tectonics import integration_differential_geometry as G  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402

rows = json.load(open(census))['rows']
wanted = {r['chart'] for r in rows if r['all_zero_end'] and not r['proved']}
data = json.loads(gzip.decompress(Path(capture).read_bytes()))
seen = set()
shapes = Counter()
shown = 0
for s in data['supports']:
    for c in s['components']:
        ident = dict(parent_partition_id='ada1e1288643132f367db9b27388fc6d0b3ee8c1ede0291009543c50e0dee356',
                     parent_source_chart_id=s['source_chart_id'], parent_partition_path=c['partition_path'],
                     plate_id=s['plate_id'], radial_layer=s['radial_layer'])
        key = W._hash(ident)[:16]
        if key not in wanted or key in seen:
            continue
        seen.add(key)
        desc = []
        for name, sign in c['constraints']:
            v = s['constraints'][name]
            chain, inner = [], v
            while inner['kind'] == 'snapshot-rotated':
                chain.append('snap')
                inner = inner['constraint']
            kind = inner['kind']
            rigid = G._rigid_plane_path(v) is not None
            omegas = ()
            if kind == 'moving-ray-edge':
                omegas = tuple(str(W._decode(r['angular_velocity_rad_s'][2])) for r in inner['rays'])
            desc.append((name.split(':')[0] + ':' + ('/'.join(chain) or '-') + ':' + kind, sign, rigid, omegas))
        shapes[tuple(sorted((d[0], d[2]) for d in desc))] += 1
        if shown < limit:
            shown += 1
            print('CHART', key, 'path', c['partition_path'], 'plate', s['plate_id'], 'material omega_z',
                  str(W._decode(s['material_angular_velocity_rad_s'][2])))
            for d in desc:
                print('    ', d)
print('unproved all-zero charts', len(wanted), 'inspected', len(seen))
for shape, n in shapes.most_common(8):
    print(n, shape)
