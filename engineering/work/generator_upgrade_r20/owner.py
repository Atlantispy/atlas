"""Final Political-owner working method; predecessor gates remain untouched."""
import json
import os
from pathlib import Path
from . import provenance as p

ROOT = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-6/outputs/r20_political_owner')
PINS = {'OWNER_CONTRACT.json': '5edb204682ca6881e3259108cc3a00f60d7898680dcb93f85024dce26bb09ead',
        'ACCEPTANCE_CASES.json': '985ad127c77a16e8f26032a9d96c3dc117e37b2cc20a98473c2852d2cbb560f6'}


def read(name):
    return json.loads(p.checked(ROOT/name, PINS[name]))


def contract():
    value = read('OWNER_CONTRACT.json')
    if (value['id'] != 'GEO-R20-POLITICAL-INPUTS-2026-09-14' or value['revision'] != 1
            or value['decision'] != 'OWNER_ASSIGNED_WORKING_METHOD_FOR_IMPLEMENTATION_AND_BOUNDED_REFERENCE_VERIFICATION'
            or value['formation_and_hierarchy']['method_id'] != 'R20-F1-PHYSICAL-MULTICUT-REFERENCE'
            or value['numerical_working_profile']['score_tolerance_u'] != 0):
        raise ValueError('explicit final owner R20-W1 method required')
    return value


def read_cases():
    contract()
    return read('ACCEPTANCE_CASES.json')


def source_path(row, value):
    key, _, rest = row['path'].partition('/')
    if key in value['roots']:
        root = Path(value['roots'][key]).resolve()
        path = (root/rest).resolve()
        if not path.is_relative_to(root):
            raise ValueError('owner source escapes declared root')
        # Four immutable predecessor controls already have long Windows names.
        # This read-only spelling does not rename them or extend cache paths.
        return Path('\\\\?\\'+str(path)) if os.name == 'nt' and len(str(path)) >= 260 else path
    path = Path(row['path'])
    if not path.is_absolute():
        raise ValueError('absolute owner source path required')
    return path


def read_matrix():
    value = contract()
    row = next(row for row in value['sources'] if row['id'] == 'CM')
    path = source_path(row, value)
    return json.loads(p.checked(path, row['sha256']))


def binding(*, verify_sources=False):
    value = contract()
    p.checked(ROOT/'ACCEPTANCE_CASES.json', PINS['ACCEPTANCE_CASES.json'])
    rows = {str(ROOT/name): {'sha256': digest, 'status': value['status']} for name, digest in PINS.items()}
    for row in value['sources']:
        path = source_path(row, value)
        if verify_sources:
            p.checked(path, row['sha256'])
        rows[str(path)] = {'sha256': row['sha256'], 'status': row['status'], 'use': row['use']}
    return {'id': value['id'], 'revision': value['revision'], 'sources': rows,
            'status': value['status'], 'scope': 'WORKING METHOD AND SYNTHETIC VERIFICATION; NOT ACTUAL DIADEM MAP ACCEPTANCE'}
