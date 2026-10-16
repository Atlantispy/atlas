"""Well-formed mutants for compare_records_relabelled.py: each must make the comparison FAIL.

From a real record B (the relabelled twin of A), writes mutated copies to OUT and runs the
comparator against A for each. Mutants:
  number      one hex digit of one volume bound changed in one cell
  swap        the x and y centroid coordinates of one cell exchanged (a positional numeric list)
  id-crossed  one face reference inside a cell re-pointed at a different (existing) face id
  drop        one cell removed
  sign        one face orientation sign flipped
Exit 0 only if every mutant fails and the unmutated twin passes.
Usage: mutants_compare_relabelled.py A.json.gz B.json.gz OUT_DIR
"""
import copy
import gzip
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(a, b):
    out = subprocess.run([sys.executable, '-B', '-I', str(HERE / 'compare_records_relabelled.py'), a, b],
                         capture_output=True, text=True)
    return out.returncode == 0, out.stdout[-400:]


def main():
    a, b, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=False)
    base = json.loads(gzip.decompress(Path(b).read_bytes()))
    cells = base['cells']
    target = next(i for i, c in enumerate(cells) if c.get('faces') and len(c['faces']) > 1
                  and c.get('physical_volume_bounds_m3'))

    def number(r):
        cell = r['cells'][target]
        text = cell['physical_volume_bounds_m3'][0][0]
        cell['physical_volume_bounds_m3'][0][0] = text[:-1] + ('1' if text[-1] != '1' else '2')

    def swap(r):
        c = r['cells'][target]['centroid_m']
        c[0], c[1] = c[1], c[0]

    def crossed(r):
        faces = r['cells'][target]['faces']
        others = [f[0] for c in r['cells'] for f in c.get('faces', []) if f[0] not in {g[0] for g in faces}]
        faces[0][0] = others[0]

    def drop(r):
        del r['cells'][target]

    def sign(r):
        r['cells'][target]['faces'][0][1] = -r['cells'][target]['faces'][0][1]

    results = {'twin': run(a, b)[0]}
    for name, mutate in (('number', number), ('swap', swap), ('id-crossed', crossed), ('drop', drop),
                         ('sign', sign)):
        record = copy.deepcopy(base)
        mutate(record)
        path = out / (name + '.json.gz')
        path.write_bytes(gzip.compress(json.dumps(record, sort_keys=True).encode()))
        results[name] = run(a, str(path))[0]
    ok = results['twin'] and not any(v for k, v in results.items() if k != 'twin')
    print(json.dumps(dict(ok=ok, passes=results, target_cell=target)))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
