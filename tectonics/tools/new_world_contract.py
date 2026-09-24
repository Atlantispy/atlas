"""Versioned, bounded new-world configuration; no physical generator is run.

SPDX-License-Identifier: AGPL-3.0-only
Keep outside atlas_tectonics: existing scientific source identities stay intact.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import platform
import re
import secrets
import sys


REQUEST_SCHEMA = 'atlas.new-world-request.v1'
PLAN_SCHEMA = 'atlas.new-world-plan.v1'
WORLD_SCHEMA = 'atlas.initial-world-descriptor.v1'
RECIPE = 'atlas-initial-contract-v1'
MODE = 'statistical-kinematic'
RANDOM_ALGORITHM = 'sha256-named-u128-rejection-u64-top53-v1'
MAX_JSON_BYTES = 65536
_SOURCE = Path(__file__).resolve()
_LOADED_SOURCE_DIGEST = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()
_STREAMS = ('plate_layout', 'plate_sizes', 'continental_structure',
            'crustal_structure', 'thermal_structure', 'plate_motion')
_DOMAINS = {
    'radius_m': (100000., 100000000., 'm', False),
    'gravity_m_s2': (.01, 100., 'm/s2', False),
    'plate_count': (2, 52, '1', True),
    'continental_fraction': (0., 1., '1', False),
}
_PRODUCT_UNITS = {'topology': '1', 'material': 'kg', 'thermal': 'K',
                  'motion': 'rad/s', 'boundaries': '1'}
_FRAME = {'id': 'world-frame', 'coordinate_system': 'planet-centred-cartesian',
          'length_unit': 'm', 'vertical_reference': 'radial-depth-below-reference-sphere'}


class ContractError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _fail(code, message):
    raise ContractError(code, message)


def _plain(value):
    """Bound structure before serialisation; no implicit custom-type coercion."""
    remaining = 10000

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if depth > 16 or remaining < 0:
            _fail('INPUT_TOO_LARGE', 'JSON structure exceeds the contract limit.')
        if item is None or type(item) in (bool, str):
            if type(item) is str and len(item) > MAX_JSON_BYTES:
                _fail('INPUT_TOO_LARGE', 'JSON text exceeds the contract limit.')
        elif type(item) is int:
            if item.bit_length() > 256:
                _fail('INVALID_JSON', 'JSON integers exceed the contract representation.')
        elif type(item) is float:
            if not math.isfinite(item):
                _fail('INVALID_JSON', 'JSON numbers must be finite.')
        elif type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    _fail('INVALID_JSON', 'JSON object keys must be strings.')
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        else:
            _fail('INVALID_JSON', 'Only plain JSON values are supported.')
    visit(value, 0)


def canonical_bytes(record):
    _plain(record)
    try:
        data = json.dumps(record, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')
    except (ValueError, TypeError, OverflowError, RecursionError):
        _fail('INVALID_JSON', 'The record is not supported JSON.')
    if len(data) > MAX_JSON_BYTES:
        _fail('INPUT_TOO_LARGE', 'JSON exceeds the 64 KiB contract limit.')
    return data


def parse_json(text):
    if type(text) not in (str, bytes):
        _fail('INVALID_JSON', 'UTF-8 JSON text is required.')
    try:
        raw = text.encode('utf-8') if type(text) is str else text
        if len(raw) > MAX_JSON_BYTES:
            _fail('INPUT_TOO_LARGE', 'JSON exceeds the 64 KiB contract limit.')

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    _fail('INVALID_JSON', 'Duplicate JSON keys are not allowed.')
                result[key] = value
            return result

        def constant(_):
            _fail('INVALID_JSON', 'JSON numbers must be finite.')
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        _fail('INVALID_JSON', 'The record is not valid bounded UTF-8 JSON.')
    _plain(result)
    return result


def _copy(record):
    return parse_json(canonical_bytes(record))


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        _fail('INVALID_CONTRACT', label + ' has missing or unsupported fields.')


def _number(value, lower, upper, label, integer=False):
    if (type(value) is not int if integer else type(value) not in (int, float)):
        _fail('INVALID_SETTING', label + ' has an invalid numeric type.')
    if not math.isfinite(value) or not lower <= value <= upper:
        _fail('INVALID_SETTING', label + ' is outside the supported structural range.')
    return value if integer else (0. if value == 0 else float(value))


def _name(value, label):
    if type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
        _fail('INVALID_CONTRACT', label + ' must be a bounded identifier, not a path.')
    return value


def _hex(value, count, label):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{' + str(count) + '}', value):
        _fail('INVALID_CONTRACT', label + ' must be lowercase hexadecimal text.')
    return value


def _hash(record):
    return hashlib.sha256(canonical_bytes(record)).hexdigest()


def _capabilities():
    return dict(configure=True, generate_world=False, evolve_world=False, native_restart=False)


def new_request(seed=None, *, settings=None, epoch=None, frame=None,
                support_cells=1024, resources=None):
    request = dict(schema=REQUEST_SCHEMA, seed=secrets.token_hex(16) if seed is None else seed,
        recipe=RECIPE, mode=MODE,
        epoch=dict(id='initial-epoch', time_s=0.) if epoch is None else epoch,
        frame=dict(_FRAME) if frame is None else frame,
        settings={
            'radius_m': dict(mode='fixed', value=6371000.),
            'gravity_m_s2': dict(mode='fixed', value=9.81),
            'plate_count': dict(mode='auto', minimum=8, maximum=20),
            'continental_fraction': dict(mode='auto', minimum=.25, maximum=.45),
        } if settings is None else settings,
        resolution=dict(support_cells=support_cells),
        resources=dict(max_work_bytes=128 << 20, max_wall_seconds=120.)
        if resources is None else resources)
    return validate_request(request)


def validate_request(record):
    request = _copy(record)
    _keys(request, ('schema', 'seed', 'recipe', 'mode', 'epoch', 'frame', 'settings',
                    'resolution', 'resources'), 'Request')
    if request['schema'] != REQUEST_SCHEMA or request['recipe'] != RECIPE or request['mode'] != MODE:
        _fail('UNSUPPORTED_CONTRACT', 'The request schema, recipe or mode is unsupported.')
    _hex(request['seed'], 32, 'Seed')
    epoch = request['epoch']
    _keys(epoch, ('id', 'time_s'), 'Epoch')
    _name(epoch['id'], 'Epoch ID')
    epoch['time_s'] = _number(epoch['time_s'], -1e18, 1e18, 'Epoch seconds')
    frame = request['frame']
    _keys(frame, _FRAME, 'Frame')
    _name(frame['id'], 'Frame ID')
    if any(frame[key] != value for key, value in _FRAME.items() if key != 'id'):
        _fail('UNSUPPORTED_CONTRACT', 'Explicit planet-centred metre coordinates and radial depth are required.')
    settings = request['settings']
    _keys(settings, _DOMAINS, 'Settings')
    for name, (lower, upper, unit, integer) in _DOMAINS.items():
        item = settings[name]
        if type(item) is not dict or item.get('mode') not in ('fixed', 'auto'):
            _fail('INVALID_SETTING', 'Settings require an explicit Fixed or Auto mode.')
        if item['mode'] == 'fixed':
            _keys(item, ('mode', 'value'), 'Fixed setting')
            item['value'] = _number(item['value'], lower, upper, name, integer)
        else:
            _keys(item, ('mode', 'minimum', 'maximum'), 'Auto setting')
            for key in ('minimum', 'maximum'):
                item[key] = _number(item[key], lower, upper, name, integer)
            if item['minimum'] > item['maximum']:
                _fail('INVALID_SETTING', 'Auto minimum cannot exceed maximum.')
    resolution = request['resolution']
    _keys(resolution, ('support_cells',), 'Resolution')
    count = _number(resolution['support_cells'], 8, 65536, 'Support cells', True)
    plate = settings['plate_count']
    if count < 4 * plate['value' if plate['mode'] == 'fixed' else 'maximum']:
        _fail('INVALID_SETTING', 'Support must cover at least four cells per possible plate.')
    resources = request['resources']
    _keys(resources, ('max_work_bytes', 'max_wall_seconds'), 'Resources')
    resources['max_work_bytes'] = _number(resources['max_work_bytes'], 1 << 20, 8 << 30,
                                         'Work bytes', True)
    resources['max_wall_seconds'] = _number(resources['max_wall_seconds'], 1., 86400.,
                                           'Wall seconds')
    return request


def stream_seed(seed, name):
    _hex(seed, 32, 'Seed')
    if type(name) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}', name):
        _fail('INVALID_CONTRACT', 'Random stream names must be bounded lowercase identifiers.')
    message = (b'atlas.new-world.stream.v1\0' + bytes.fromhex(seed) + b'\0' + name.encode('ascii'))
    return hashlib.sha256(message).hexdigest()[:32]


def _draw(seed, name, counter=0):
    message = (b'atlas.new-world.draw.v1\0' + bytes.fromhex(stream_seed(seed, name))
               + counter.to_bytes(8, 'big'))
    return int.from_bytes(hashlib.sha256(message).digest()[:8], 'big')


def _sample(seed, name, setting, integer):
    if setting['mode'] == 'fixed':
        return setting['value']
    lower, upper = setting['minimum'], setting['maximum']
    if lower == upper:
        return lower
    if integer:
        span = upper - lower + 1
        limit = (1 << 64) - ((1 << 64) % span)
        for counter in range(128):
            draw = _draw(seed, 'setting.' + name, counter)
            if draw < limit:
                return lower + draw % span
        _fail('SAMPLING_FAILED', 'The bounded integer sampler did not produce an admissible draw.')
    unit = (_draw(seed, 'setting.' + name) >> 11) * (2. ** -53)
    # The final arithmetic can round to upper; preserve the half-open contract.
    return min(math.nextafter(upper, lower), lower + (upper - lower) * unit)


def _binding():
    current = hashlib.sha256(_SOURCE.read_bytes()).hexdigest()
    if current != _LOADED_SOURCE_DIGEST:
        _fail('SOURCE_MISMATCH', 'The contract source changed while loaded; restart before preparing a new plan.')
    if sys.float_info.radix != 2 or sys.float_info.mant_dig != 53:
        _fail('UNSUPPORTED_RUNTIME', 'The contract requires binary64 floating-point arithmetic.')
    return dict(contract_sha256=current, python_implementation=platform.python_implementation(),
                python_version=platform.python_version(), float_format='ieee754-binary64')


def output_contract():
    return dict(schema=WORLD_SCHEMA, status='WORKING NON-CANON',
        required_products=dict(_PRODUCT_UNITS),
        required_reference_fields=['product_id', 'support_id', 'unit', 'frame_id',
                                   'epoch_id', 'known_mask_id', 'origin'],
        origin='generated-assumption', shared_support=True,
        verification='Structural references only; native bytes, closure and physics are not verified.')


def resolve_request(record):
    request = validate_request(record)
    binding = _binding()
    values = {name: _sample(request['seed'], name, item, _DOMAINS[name][3])
              for name, item in request['settings'].items()}
    streams = {name: stream_seed(request['seed'], name)
               for name in _STREAMS + tuple('setting.' + key for key in _DOMAINS)}
    scientific = {key: value for key, value in request.items() if key != 'resources'}
    scientific.update(resolved_settings=values, random_algorithm=RANDOM_ALGORITHM)
    plan = dict(schema=PLAN_SCHEMA, status='CONFIGURED_NOT_GENERATED',
        request=request, request_id=_hash(request), scientific_id=_hash(scientific),
        resolved_settings=values,
        setting_origins={name: 'fixed' if item['mode'] == 'fixed' else 'sampled-uncalibrated-uniform'
                         for name, item in request['settings'].items()},
        streams=streams, random_algorithm=RANDOM_ALGORITHM,
        recipe_status='uncalibrated-engineering-configuration', output_contract=output_contract(),
        capabilities=_capabilities(), binding=binding)
    plan['plan_id'] = _hash(plan)
    if binding != _binding():
        _fail('SOURCE_MISMATCH', 'The contract source/runtime changed during configuration.')
    return plan


def validate_plan(record):
    candidate = _copy(record)
    if type(candidate) is not dict or 'request' not in candidate:
        _fail('INVALID_PLAN', 'A complete saved new-world plan is required.')
    expected = resolve_request(candidate['request'])
    _keys(candidate, expected, 'Plan')
    if candidate['binding'] != expected['binding']:
        _fail('SOURCE_MISMATCH', 'The saved plan source/runtime differs; no automatic rebind is allowed.')
    if canonical_bytes(candidate) != canonical_bytes(expected):
        _fail('INVALID_PLAN', 'Saved plan identities, sampled values or declarations differ.')
    return expected


def validate_world_descriptor(record, plan):
    """Validate a future manifest's structure, NEVER authenticate its products."""
    plan = validate_plan(plan)
    result = _copy(record)
    _keys(result, ('schema', 'status', 'plan_id', 'scientific_id', 'epoch', 'frame',
                   'origins', 'products'), 'Initial-world descriptor')
    if result['schema'] != WORLD_SCHEMA or result['status'] != 'WORKING NON-CANON':
        _fail('UNSUPPORTED_CONTRACT', 'An explicit working initial-world descriptor is required.')
    for key in ('plan_id', 'scientific_id'):
        if result[key] != plan[key]:
            _fail('CONTEXT_MISMATCH', 'World references belong to another configured plan.')
    for key in ('epoch', 'frame'):
        if canonical_bytes(result[key]) != canonical_bytes(plan['request'][key]):
            _fail('CONTEXT_MISMATCH', 'World frame or epoch differs; IDs do not perform coordinate conversion.')
    origins = dict(recipe=plan['request']['recipe'], mode=plan['request']['mode'])
    if result['origins'] != origins:
        _fail('INVALID_CONTRACT', 'Initial-world origins must retain their declared recipe and mode.')
    _keys(result['products'], _PRODUCT_UNITS, 'World products')
    supports = set()
    for name, unit in _PRODUCT_UNITS.items():
        reference = result['products'][name]
        _keys(reference, output_contract()['required_reference_fields'], 'Product reference')
        for key in ('product_id', 'support_id', 'known_mask_id'):
            _hex(reference[key], 64, 'Product reference')
        if (reference['unit'] != unit or reference['frame_id'] != result['frame']['id']
                or reference['epoch_id'] != result['epoch']['id']
                or reference['origin'] != 'generated-assumption'):
            _fail('CONTEXT_MISMATCH', 'Product units, frame, epoch or origin differ from the output contract.')
        supports.add(reference['support_id'])
    if len(supports) != 1:
        _fail('CONTEXT_MISMATCH', 'Different product supports need an explicit transfer contract.')
    return result


def contract_description():
    return dict(schema='atlas.new-world-contract-description.v1',
        request_schema=REQUEST_SCHEMA, plan_schema=PLAN_SCHEMA,
        reference_request=new_request('0' * 32), recipe_status='uncalibrated-engineering-configuration',
        setting_domains={name: dict(minimum=lo, maximum=hi, unit=unit, integer=integer)
                         for name, (lo, hi, unit, integer) in _DOMAINS.items()},
        seed_format='32 lowercase hexadecimal characters; 128 bits; never a JSON number',
        random_algorithm=RANDOM_ALGORITHM, output_contract=output_contract(),
        capabilities=_capabilities())
