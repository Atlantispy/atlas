"""W3 M12: pack_mesh scratch booking is derived from per-structure costs.

Base booked 12*width+...: about 6x the traced peak on IV1-shaped meshes
(all rationals unique, 800-bit faces, 4000-bit cells: the review's
reproducer shape). The derived bound must cover the traced peak for every
shape (unique, small unique, shared, many supports) and stay within 1.3x on
IV1-shaped unique meshes. Output metadata and columns are byte-identical to
the base module (w3ref_mesh_tables). tracemalloc measures memory only.
"""
import random
import sys
import tracemalloc
import unittest
from hashlib import sha256
from math import gcd
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_mesh_tables  # noqa: F401  (side effect: puts the runtime path on sys.path)

# isort: split
import mesh_tables as M
import w3ref_mesh_tables as BASE
from atlas_tectonics.resources import MemoryLimitError, WorkBudget


def ident(text):
    return sha256(text.encode()).hexdigest()


def build(n_cells, n_faces, face_bits, cell_bits, *, shared=False, supports=1, seed=7):
    rng = random.Random(seed)

    def q(bits):
        if shared:
            return ['0x1', '0x3']
        n = rng.getrandbits(bits) | 1
        d = rng.getrandbits(bits) | (1 << (bits-1))
        g = gcd(n, d)
        n, d = n//g, d//g
        return [hex(-n if rng.random() < 0.5 else n), hex(d)]
    cells = [{'cell_id': ident(f'c{i}'), 'kind': 'collar', 'index': [i, 0, 0], 'volume_m3': q(cell_bits),
              'centroid_m': [q(cell_bits) for _ in range(3)],
              'physical_volume_bounds_m3': [q(cell_bits), q(cell_bits)],
              'geometry_volume_max_deviation_m3': q(cell_bits),
              'volume_centroid_m': [q(cell_bits) for _ in range(3)], 'faces': []} for i in range(n_cells)]
    faces = []
    for j in range(n_faces):
        a, b = j % n_cells, (j*7+1) % n_cells
        owners = [cells[a]['cell_id']] if a == b else [cells[a]['cell_id'], cells[b]['cell_id']]
        fid = ident(f'f{j}')
        faces.append({'face_id': fid, 'kind': 'internal', 'geometry_kind': 'differential-component-interface',
                      'relative_advection': 'issued physical moving-interface measure, never assumed comoving',
                      'centroid_m': [q(face_bits) for _ in range(3)],
                      'area_vector_m2': [q(face_bits) for _ in range(3)],
                      'owners': owners, 'vertices_m': [[q(face_bits) for _ in range(3)] for _ in range(4)]})
        cells[a]['faces'].append([fid, 1])
        if a != b:
            cells[b]['faces'].append([fid, -1])
    return {'schema': M.LEGACY, 'method': M.METHOD, 'funding_id': ident('funding'), 'source': {'fixture_only': True},
            'support_id': ident('support'), 'trajectory_id': M.digest([]), 'trajectory_segments': [],
            'endpoint': 'end', 'time_s': ['0x0', '0x1'], 'grid_id': ident('grid'),
            'grid_lines': [[['0x0', '0x1'], ['0x1', '0x1']]]*3, 'cells': cells, 'faces': faces,
            'support_tables': {'voxels': {ident(f'v{k}'): {'probe': k} for k in range(supports)}},
            'geometry_volume_max_deviation_m3': ['0x0', '0x1'], 'max_geometry_volume_error_m3': ['0x0', '0x1'],
            'scope': 'synthetic booking probe'}


def pack(module, record, *, trace):
    budget = WorkBudget(8 << 30)
    blobs = {}
    if trace:
        tracemalloc.start()
        base = tracemalloc.get_traced_memory()[0]
    try:
        metadata, arrays, owner = module.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget,
                                                   _defer_freeze=True)
        peak = tracemalloc.get_traced_memory()[1]-base if trace else None
    finally:
        if trace:
            tracemalloc.stop()
    booked = owner.size
    columns = {k: (v.dtype.str, v.shape, v.tobytes()) for k, v in arrays.items()}
    del arrays, owner
    return metadata, columns, blobs, booked, peak, budget


SHAPES = {
    'iv1-600': ({'n_cells': 60, 'n_faces': 600, 'face_bits': 800, 'cell_bits': 4000}, 1.3),
    'iv1-1500': ({'n_cells': 150, 'n_faces': 1500, 'face_bits': 800, 'cell_bits': 4000}, 1.3),
    'iv1-supports': ({'n_cells': 60, 'n_faces': 600, 'face_bits': 800, 'cell_bits': 4000, 'supports': 2000}, 1.3),
    'unique-64-bit': ({'n_cells': 150, 'n_faces': 1500, 'face_bits': 64, 'cell_bits': 64}, None),
    'shared': ({'n_cells': 150, 'n_faces': 1500, 'face_bits': 800, 'cell_bits': 4000, 'shared': True}, None),
}


class MeshBookingTests(unittest.TestCase):
    def test_booking_covers_traced_peak_and_is_close_on_iv1_shapes(self):
        for label, (shape, ceiling) in SHAPES.items():
            with self.subTest(shape=label):
                record = build(**shape)
                metadata, columns, blobs, booked, peak, budget = pack(M, record, trace=True)
                base = pack(BASE, record, trace=False)
                print('W3 M12', label, 'booked', booked, 'traced peak', peak, 'ratio %.3f' % (booked/peak),
                      'base booked', base[3], flush=True)
                self.assertLessEqual(peak, booked)
                if ceiling is not None:
                    self.assertLessEqual(booked, ceiling*peak)
                    self.assertLess(booked, base[3])
                # Byte-identical output (metadata, columns, support blobs).
                self.assertEqual(M.canonical(metadata), BASE.canonical(base[0]))
                self.assertEqual(columns, base[1])
                self.assertEqual(blobs, base[2])
                self.assertEqual(budget.reserved_bytes, 0)

    def test_frozen_route_and_refusals_unchanged(self):
        record = build(n_cells=20, n_faces=100, face_bits=800, cell_bits=4000)
        budget = WorkBudget(1 << 30)
        metadata, frozen = M.pack_mesh(record, support_writer=lambda h, raw: None, budget=budget)
        base_metadata, base_frozen = BASE.pack_mesh(record, support_writer=lambda h, raw: None, budget=budget)
        self.assertEqual(M.canonical(metadata), M.canonical(base_metadata))
        self.assertEqual({k: v.tobytes() for k, v in frozen.items()}, {k: v.tobytes() for k, v in base_frozen.items()})
        del frozen, base_frozen
        self.assertEqual(budget.reserved_bytes, 0)
        bad_rows = [
            dict(record, cells=record['cells'][:-1]+['not a row']),
            dict(record, faces=record['faces'][:-1]+[dict(record['faces'][-1], vertices_m='x')]),
            dict(record, cells=[dict(record['cells'][0], physical_support='x')]+record['cells'][1:]),
            dict(record, faces=[dict(record['faces'][0], cartesian_support=[{'bad': 1}])]+record['faces'][1:]),
        ]
        for at, bad in enumerate(bad_rows):
            with self.subTest(case=at):
                with self.assertRaises(Exception) as new:
                    M.pack_mesh(bad, support_writer=lambda h, raw: None, budget=budget)
                with self.assertRaises(Exception) as old:
                    BASE.pack_mesh(bad, support_writer=lambda h, raw: None, budget=budget)
                self.assertEqual((type(new.exception).__name__, str(new.exception)),
                                 (type(old.exception).__name__, str(old.exception)))
                self.assertEqual(budget.reserved_bytes, 0)
        # A budget below the derived bound refuses before any column is built.
        small = WorkBudget(M._scratch_bytes(record, record['cells'], record['faces'], record['support_tables'],
                                            sum(map(M._width, ({k: v for k, v in record.items() if k not in M.SPECIAL},
                                                               record['cells'], record['faces'], record['grid_lines']))),
                                            1, M._support_width('voxels', {'probe': 0}))-1)
        with self.assertRaises(MemoryLimitError):
            M.pack_mesh(record, support_writer=lambda h, raw: None, budget=small)
        self.assertEqual(small.reserved_bytes, 0)

    def test_dict_bound_matches_cpython(self):
        for count in (0, 1, 5, 6, 11, 12, 100, 1365, 1366, 5000, 87382):
            d = {}
            tracemalloc.start()
            base = tracemalloc.get_traced_memory()[0]
            for i in range(count):
                d[i+1000] = None
            peak = tracemalloc.get_traced_memory()[1]-base
            tracemalloc.stop()
            keys_and_values = count*32  # the int keys made here (traced 32 B each), not part of the dict
            with self.subTest(count=count):
                self.assertLessEqual(peak-keys_and_values, M._dict_bytes(count)+64)
            del d


if __name__ == '__main__':
    unittest.main()
