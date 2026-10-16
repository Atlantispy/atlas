"""Focused test: parallel adoption of complementary-cut records (and no regression for others).

Issues one proved interval-2 record (support 880) and one ordinary Taylor-route record
through the composed runtime, then calls integration_parallel_results._validated exactly
as the dispatcher does (parent digests, canonical encoding, sha256), with a fit stub that
admits any work. Expected: both adopted; every tampered variant refused. Also re-derives
the certificate digest from the loaded geometry file (helper region + call site) and checks
it equals the record's source_sha256 and the parent's _CP_SOURCE_SHA256.
Usage: test_cp_adopt.py --runtime test:<folder>
"""
import argparse
import copy
import gzip
import json
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402

W2 = ('0xef6aca6e197d9db2f69d62da0b', '0xc6ae51dc48000000000000000000000000000000000000')
SUPPORTS = HERE.parent / 'work' / 'iv2-supports.jsonl.gz'
CASES = [  # (support index, cell, other, constraint)
    (880, '8af8d62b9f7812da', '3289be82c3bc321d', 'owner:vertex:m02-p03>vertex:m01-p03'),   # proved
    (880, '3289be82c3bc321d', '8cda37209ae93bef', 'owner:vertex:m02-p03>face-centre:s01-b03'),  # cheap, ordinary
]


class Fit:
    def admits_work(self, work):
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True)
    args = ap.parse_args()
    if sys.flags.hash_randomization:
        raise SystemExit('set PYTHONHASHSEED=0')
    rc1_env.install(args.runtime)
    from atlas_tectonics import integration_differential_geometry as G
    from atlas_tectonics import integration_interface_exclusion as IE
    from atlas_tectonics import integration_moving_interface_moments as IM
    from atlas_tectonics import integration_parallel_results as PR
    from atlas_tectonics import integration_wall_measures as W
    from atlas_tectonics.resources import WorkBudget
    budget = WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    width = W._decode(list(W2))
    with gzip.open(SUPPORTS, 'rt', encoding='utf8') as f:
        f.readline()
        row = next(json.loads(line) for i, line in enumerate(f) if i == 880)
    support = G._issue(G.DifferentialSupport, row, budget)
    full = {p['logical_cell_id'][:16]: p['logical_cell_id'] for p in row['components']}
    digests = {PR.ZERO_AREA: IE.source_digest(), PR.MOMENTS: IM.source_digest()}
    results = []
    helper_ok = None
    for _, cell, other, name in CASES:
        record = G.enclose_component_interface(support, full[cell], name, other_support=support,
            other_logical_cell_id=full[other], max_width_m3=width, max_leaves=524288, budget=budget).record()
        request = PR.canonical({k: record[k] for k in PR.REQUEST_FIELDS})

        def adopt(rec):
            encoded = PR.canonical(rec)
            return PR._validated(encoded, sha256(encoded).hexdigest(), request, digests, Fit(), None)
        variants = {'as issued': (record, True)}
        if record['rule'] == 'exact-zero-area-from-complementary-moving-cuts':
            cert = record['zero_area_certificate']
            # Re-derive the digest from the loaded file: helper region + call site.
            import importlib.util
            spec = importlib.util.spec_from_file_location('cpcut_transform', HERE.parent / 'transforms' / 'complementary_cut.py')
            transform = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(transform)
            text = Path(G.__file__).read_bytes().decode('utf8')
            head = "_CP_SOURCE_SHA256 = '%s'  # sha256 of the certificate helper below + its call site\n" % G._CP_SOURCE_SHA256
            start = text.index(head) + len(head)
            end = text.index('def enclose_component_interface(support, logical_cell_id, constraint_name, *,\n')
            recomputed = sha256((text[start:end] + transform.NEW_CALL).encode()).hexdigest()
            helper_ok = (cert['source_sha256'] == G._CP_SOURCE_SHA256 == recomputed
                         and text.count(transform.NEW_CALL) == 1)
            bad = copy.deepcopy(record); bad['zero_area_certificate']['source_sha256'] = IE.source_digest()
            variants['certificate digest = exclusion module'] = (bad, False)
            bad = copy.deepcopy(record); bad['zero_area_certificate']['source_sha256'] = '0'*64
            variants['certificate digest forged'] = (bad, False)
            bad = copy.deepcopy(record); bad['leaves'] = 2
            variants['leaves 2'] = (bad, False)
            bad = copy.deepcopy(record); del bad['zero_area_certificate']
            variants['certificate missing'] = (bad, False)
            bad = copy.deepcopy(record); bad['moving_interface_moments'] = dict(source_sha256=IM.source_digest())
            variants['extra moments key'] = (bad, False)
        else:
            bad = copy.deepcopy(record)
            if 'moving_interface_moments' in bad:
                bad['moving_interface_moments']['source_sha256'] = G._CP_SOURCE_SHA256
                variants['moments digest = certificate helper'] = (bad, False)
        for label, (rec, expected) in variants.items():
            got = adopt(rec)
            results.append(dict(case=cell, rule=record['rule'], variant=label, expected=expected, adopted=got,
                                ok=got is expected))
    ok = all(r['ok'] for r in results) and helper_ok is True
    print(json.dumps(dict(ok=ok, certificate_digest_matches_parent=helper_ok, results=results), indent=1))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
