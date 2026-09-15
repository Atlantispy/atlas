"""Current executed successor code plus unchanged native source/runtime pins."""
import hashlib
import json
from pathlib import Path
import sys
from types import CodeType

from work.topography_r1 import provenance as retained
from work.terrain_model_r7 import hillslope_kernel as r7
from . import HERE, hillslope

RUNTIME_FILES = ('__init__.py', 'hillslope.py', 'materials.py', 'domain.py',
                 'evolve.py', 'receiver.py', 'provenance.py')


def plain(value):
    from fractions import Fraction
    if type(value) is Fraction:
        return str(value)
    if type(value) is dict:
        return {str(k): plain(v) for k, v in value.items()}
    if type(value) in (tuple, list):
        return [plain(v) for v in value]
    return value


def encoded(value):
    return json.dumps(plain(value), sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def _code_members(code):
    return {item.co_name: item for item in code.co_consts if isinstance(item, CodeType)}


def identity():
    sources = {}
    for name in RUNTIME_FILES:
        path = HERE / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sources[str(path)] = digest
        module_name = 'work.native_terrain_r1' + ('' if name == '__init__.py' else '.' + path.stem)
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, '_R12_EXECUTED_SHA256', None) != digest:
            raise ValueError('executed native terrain successor differs from source: ' + name)
    path = Path(r7.__file__)
    raw = path.read_bytes()
    codes = _code_members(compile(raw, str(path), 'exec', dont_inherit=True))
    for name in ('number', '_positive_product', '_harmonic_mean', 'field', 'gradients'):
        function = getattr(r7, name)
        if function.__code__ != codes[name] or getattr(hillslope, name) is not function:
            raise ValueError('executed retained hillside helper differs: ' + name)
    grid_codes = _code_members(codes['Grid'])
    for name in ('__post_init__', 'xy'):
        if getattr(r7.Grid, name).__code__ != grid_codes[name]:
            raise ValueError('executed retained Grid differs: ' + name)
    for name in ('size', 'area_m2'):
        if getattr(r7.Grid, name).fget.__code__ != grid_codes[name]:
            raise ValueError('executed retained Grid property differs: ' + name)
    if hillslope.Grid is not r7.Grid:
        raise ValueError('hillside support type differs')
    sources[str(path)] = hashlib.sha256(raw).hexdigest()
    contract_path = path.with_name('NUMERICAL_CONTRACT.json')
    contract_raw = contract_path.read_bytes()
    if json.loads(contract_raw) != r7.CONTRACT or hillslope.CONTRACT is not r7.CONTRACT:
        raise ValueError('retained hillside numerical contract differs')
    sources[str(contract_path)] = hashlib.sha256(contract_raw).hexdigest()
    return {'schema': 'diadem.native-terrain-execution.r1', 'sources': sources,
            'retained_native': retained.identity(),
            'limits': {'cells': 256, 'connectors': 2048, 'layers': 8192, 'exact_bits': 8192}}


def verify(binding):
    if identity() != binding:
        raise ValueError('native terrain source/runtime binding changed; no silent repin')
