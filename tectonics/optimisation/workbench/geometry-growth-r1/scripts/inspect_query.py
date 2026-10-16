"""Read-only: literal structure of one saved IV2 query (support index, cell prefix)."""
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

path, want_index, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3]
rc1_env.install()
from atlas_tectonics import integration_differential_geometry as G  # noqa: E402
from atlas_tectonics import integration_wall_measures as W  # noqa: E402


def chain(c):
    out = []
    while c['kind'] == 'snapshot-rotated':
        out.append('snap(off=%s, wz=%s)' % (float(W._decode(c['snapshot_offset_s'])), float(W._decode(c['angular_velocity_rad_s'][2]))))
        c = c['constraint']
    if c['kind'] == 'moving-ray-edge':
        rays = []
        for r in c['rays']:
            hist = [(float(w[2]), float(dt)) for w, dt in G._history(r.get('prior_rotations', ()))]
            rays.append('dir=%s wz=%s hist=%s' % ([round(float(W._decode(q)), 4) for q in r['direction']],
                                                  float(W._decode(r['angular_velocity_rad_s'][2])), hist))
        out.append('edge[' + ' | '.join(rays) + ']')
    elif c['kind'] == 'rotated-normal':
        out.append('normal=%s wz=%s' % ([round(float(W._decode(q)), 4) for q in c['normal']], float(W._decode(c['angular_velocity_rad_s'][2]))))
    else:
        out.append(c['kind'])
    return ' -> '.join(out)


with gzip.open(path, 'rt', encoding='utf8') as f:
    header = json.loads(f.readline())
    for index, line in enumerate(f):
        if index != want_index:
            continue
        s = json.loads(line)
        print('support', index, s['kind'], s['plate_id'], 'voxel', s['voxel_index'], 'material wz',
              float(W._decode(s['material_angular_velocity_rad_s'][2])), 'duration', float(W._decode(s['duration_s'])))
        for c in s['components']:
            if not c['logical_cell_id'].startswith(prefix):
                continue
            print('component', c['logical_cell_id'][:16], c['partition_path'], 'parent', c.get('parent_cell_id'))
            for name, sign in c['constraints']:
                value = s['constraints'][name]
                print('  %+d %-60s rigid=%s' % (sign, name[:60], G._rigid_plane_path(value) is not None))
                print('       ', chain(value))
        break
