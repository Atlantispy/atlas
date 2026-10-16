"""Diagnostic-only exception capture, without retaining any traceback/frame.

Called while unittest still owns the exception. Copy only primitive admission
facts and stream already-immutable producer bytes. This is not a typed restore
factory or a scientific resource-accounting change. No decode of large inputs.
"""
import gzip
from hashlib import sha256
from pathlib import Path


def write_blob(directory, label, blob):
    if type(blob) is not bytes:
        raise TypeError('Capture requires existing immutable bytes')
    path = Path(directory)/(label+'.gz')
    digest = sha256()
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
            view = memoryview(blob)
            for at in range(0, len(view), 65536):
                chunk = view[at:at+65536]
                digest.update(chunk)
                stream.write(chunk)
    return dict(path=path.name, uncompressed_bytes=len(blob), raw_sha256=digest.hexdigest(),
                gzip_bytes=path.stat().st_size)


def capture(error, directory):
    """Return JSON primitives only; no exception, frame, owner or array escapes."""
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    report = dict(admissions=[], json_shapes=[], saved_inputs={}, frames=[], limitations=[
        'Existing immutable input bytes only; no arbitrary saved snapshot becomes a live owner call.',
        'Diagnostic gzip streaming uses bounded chunks outside the scientific allocation proof.'])
    seen = set()

    def blob(label, value):
        if label not in report['saved_inputs']:
            report['saved_inputs'][label] = write_blob(directory, label, value)

    def snapshot(label, value):
        if value is None or id(value) in seen:
            return
        seen.add(id(value))
        data = getattr(value, '_metadata', None)
        if type(data) is bytes:
            blob(label+'-metadata', data)
        fields = getattr(value, '_fields', ())
        shapes = []
        for at,entry in enumerate(fields):
            if (type(entry) is not tuple or len(entry) != 3 or type(entry[0]) is not str
                    or type(entry[1]) is not tuple or any(type(v) is not int for v in entry[1])
                    or type(entry[2]) is not bytes):
                raise ValueError('Unexpected immutable native snapshot field')
            key,shape,raw = entry
            saved = label+'-field-'+str(at)
            blob(saved, raw)
            shapes.append(dict(key=key, shape=list(shape), bytes_record=saved))
        if shapes:
            report.setdefault('snapshot_fields', {})[label] = shapes

    def step_inputs(step, mesh):
        if mesh is not None:
            blob('endpoint-mesh', mesh._json)
        if step is not None:
            blob('closed-graph', step.graph._json)
            snapshot('transported', step.result._snapshot)
            snapshot('parent-spatial', step.parent._snapshot)
            snapshot('source-inventory', step.source.inventory)
            snapshot('native-source-inventory', step.source.source_stage.inventory)
            snapshot('native-source-audit', getattr(step.source.source_stage, 'source_audit', None))

    tb = error[2]
    try:
        while tb is not None:
            frame = tb.tb_frame
            name, filename = frame.f_code.co_name, Path(frame.f_code.co_filename).name
            local = frame.f_locals
            report['frames'].append(dict(file=filename, function=name, line=tb.tb_lineno))
            if name == '_admit_budgets' and filename == 'resources.py':
                report['admissions'].append(dict(requested_bytes=local.get('count'),
                    category=local.get('category'), budgets=[b.statistics() for b in local.get('ordered', ())]))
            if name == 'decoded' and filename == 'private_heat_issuer_resources_r1.py' and 'shape' in local:
                shape = local['shape']
                fields = ('encoded_bytes','strings','containers','separators','string_storage','largest_string','outside_bytes')
                report['json_shapes'].append(dict(**{k:getattr(shape,k) for k in fields},
                    decode_bytes=shape.decode_bytes, stream_codec_bytes=shape.stream_codec_bytes,
                    requested_bytes=shape.decode_bytes+shape.stream_codec_bytes))
            if name == 'bind_owner_call' and filename == 'private_heat_native_issuer_r8.py':
                step, mesh = local.get('step'), local.get('mesh')
                step_inputs(step, mesh)
                owner = local.get('owner')
                if owner is not None:
                    report['owner_budget_at_capture'] = owner._budget.statistics()
            # After bind returned, a later solve/endpoint failure still has the
            # authentic call/result in the fixed joined-consumer forward frame.
            if name == 'forward' and filename == 'private_heat_joined_consumer_r2.py':
                step_inputs(local.get('step'), local.get('mesh'))
                call, result = local.get('call'), local.get('result')
                if call is not None:
                    snapshot('issued-call', call._snapshot)
                if result is not None:
                    snapshot('heat-result', result._snapshot)
            if name == 'completed' and filename == 'private_heat_native_joined_fixture_r2.py':
                ready = local.get('ready')
                if ready is not None:
                    source,bounds,mesh,wall = ready['arguments']
                    blob('ale-bounds', bounds._json)
                    blob('endpoint-mesh', mesh._json)
                    blob('wall-measures', wall._json)
                    snapshot('source-inventory', source.inventory)
            tb = tb.tb_next
    finally:
        # This function's returned report cannot prolong scientific ownership.
        # The actual exception remains owned solely by unittest/caller.
        del tb
    return report
