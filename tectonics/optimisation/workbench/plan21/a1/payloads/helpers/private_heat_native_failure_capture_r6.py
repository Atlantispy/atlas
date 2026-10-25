"""Pinned diagnostic successor: inspect locals only for recognised captures.

CPython3.12 caches frame.f_locals. Reading an active, unrelated caller can keep
its handled exception alive in that cache and thus retain the scientific frames
after the except suite. R2 records every frame's primitive location, but skips
locals entirely outside the five original diagnostic dispatches. The five
capture bodies and streaming/exclusive-file behaviour are unchanged.

This separate module is not wired into any existing or running driver.

R3 recognises the resources r4 chain by its file names, where R2 named the r1
chain, and reports the r4 token counters and bookings of a refused decode. The
joined fixture is the pinned R2 source bound in memory by the control driver,
whose frames carry the name private_heat_native_joined_fixture_r2.py[resources-r4].
R4 names the issuer and the joined consumer of the forward kernel r11 chain.
R5 names those of the forward kernel r12 chain.
R6 names those of the forward kernel r13 chain.
"""
from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_SOURCE = _Path(__file__).resolve().with_name('private_heat_native_failure_capture_r1.py')
_SOURCE_SHA = 'aa869d5b71a2c63215f0f3fe88208479b19c45faa17ae537c35810f246b39841'
_SELF_SHA = _sha256(_Path(__file__).read_bytes()).hexdigest()
_OLD = '''            local = frame.f_locals
            report['frames'].append(dict(file=filename, function=name, line=tb.tb_lineno))
'''
_NEW = '''            report['frames'].append(dict(file=filename, function=name, line=tb.tb_lineno))
            if (name, filename) not in (
                    ('_admit_budgets', 'resources.py'),
                    ('_admit_optional', 'resources.py'),
                    ('decoded', 'private_heat_issuer_resources_r4.py'),
                    ('bind_owner_call', 'private_heat_native_issuer_r12.py'),
                    ('forward', 'private_heat_joined_consumer_r6.py'),
                    ('completed', 'private_heat_native_joined_fixture_r2.py[resources-r4]')):
                tb = tb.tb_next
                continue
            local = frame.f_locals
'''
_ENTRY = '''    directory = Path(directory)
    directory.mkdir(exist_ok=False)
'''
_NAMES = (("'private_heat_native_issuer_r8.py'", "'private_heat_native_issuer_r12.py'"),
          ("'private_heat_joined_consumer_r2.py'", "'private_heat_joined_consumer_r6.py'"),
          ("'private_heat_native_joined_fixture_r2.py'", "'private_heat_native_joined_fixture_r2.py[resources-r4]'"))
_OLD_SHAPE = '''            if name == 'decoded' and filename == 'private_heat_issuer_resources_r1.py' and 'shape' in local:
                shape = local['shape']
                fields = ('encoded_bytes','strings','containers','separators','string_storage','largest_string','outside_bytes')
                report['json_shapes'].append(dict(**{k:getattr(shape,k) for k in fields},
                    decode_bytes=shape.decode_bytes, stream_codec_bytes=shape.stream_codec_bytes,
                    requested_bytes=shape.decode_bytes+shape.stream_codec_bytes))
'''
_NEW_SHAPE = '''            if name == 'decoded' and filename == 'private_heat_issuer_resources_r4.py' and 'cost' in local:
                cost = local['cost']
                fields = ('encoded_bytes','strings','string_storage','largest_string','dicts','lists',
                          'commas','colons','outside_bytes','largest_gap','writer_storage',
                          'writer_strings','string_blocks')
                report['json_shapes'].append(dict(**{k:getattr(cost,k) for k in fields},
                    policy=local.get('policy'), requested_bytes=local.get('peak'),
                    retained_bytes=local.get('retained'), decode_peak_bytes=cost.decode_peak_bytes,
                    decode_retained_bytes=cost.decode_retained_bytes,
                    stream_codec_bytes=cost.stream_codec_bytes,
                    r1_requested_bytes=cost.legacy_decode_bytes+cost.legacy_stream_codec_bytes))
'''


def source_bindings():
    pins = {str(_SOURCE): _SOURCE_SHA, str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _sha256(_Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned failure-capture implementation changed: '+path)
    return pins


def derivation():
    source_bindings()
    return dict(source=str(_SOURCE), source_sha256=_SOURCE_SHA,
        derived_text_sha256=_DERIVED_SHA,
        changes=['check pinned source bytes at entry',
                 'skip unrelated frame locals; preserve all primitive frame records',
                 'recognise the resources r4 chain; report its counters and bookings'],
        recognised_dispatches_preserved=5, optional_admission_dispatches=1, numerical_or_active_driver_changes=False)


source_bindings()
_TEXT = _SOURCE.read_bytes().decode('utf8').replace('\r\n', '\n')
if (_TEXT.count(_OLD) != 1 or _TEXT.count(_ENTRY) != 1 or _TEXT.count(_OLD_SHAPE) != 1
        or any(_TEXT.count(before) != 1 for before, _ in _NAMES)):
    raise ValueError('Frozen failure-capture derivative anchors changed')
_DERIVED_TEXT = _TEXT.replace(_OLD, _NEW, 1).replace(
    _ENTRY, '    source_bindings()\n'+_ENTRY, 1).replace(_OLD_SHAPE, _NEW_SHAPE, 1)
for _before, _after in _NAMES:
    _DERIVED_TEXT = _DERIVED_TEXT.replace(_before, _after, 1)
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_native_failure_capture_r6]', 'exec'), globals())
