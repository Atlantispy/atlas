"""Source-bound spatial owner derivative and explicit witness reporting.

Owner functions keep the selected heat-method keyword/forwarding derivative.
Initial metrics comes from the separately pinned production observer port.
No module rebinding, mocking or historical fixture loading is performed.
"""
from atlas_tectonics.reuse import helper_source_digest as _helper_source_digest

from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _HERE / 'runtime_spatial_fixture.py'
_SOURCE_SHA = '7bc05c704edf55488b95b316430377f5af03b236f3c5d93eadea39a66c7ad502'
_METRICS_SOURCE = _HERE / 'runtime_initial_metrics.py'
_METRICS_SHA = '9ffff2dbec8ca6d169ea15cb3e8cb49d14efec036dc1c75ddbe3587ccbc4a923'
_SELF_SHA = _sha256(_Path(__file__).read_bytes()).hexdigest()
_EDITS = (
    ('explicit-method-parameter',
     'def initial_spatial_owner(case, partition, bounds, mesh, *, created_tracers=(), measure_policy=None):',
     "def initial_spatial_owner(case, partition, bounds, mesh, *, created_tracers=(), measure_policy=None,\n"
     "                          heat_method='hybrid-mimetic'):"),
    ('forward-declared-method',
     '            measure_policy=measure_policy) as owner:',
     '            measure_policy=measure_policy, heat_method=heat_method) as owner:'),
)


def _derive(source):
    result = source
    for label, before, after in _EDITS:
        if result.count(before) != 1:
            raise ValueError('Original spatial derivative anchor differs: '+label)
        result = result.replace(before, after, 1)
    return result


def _read_bound(path, expected):
    raw = path.read_bytes()
    if _sha256(raw).hexdigest() != expected:
        raise ValueError('Original spatial source changed while loading: '+str(path))
    return raw.decode('utf8').replace('\r\n', '\n')


def source_bindings():
    """Check frozen fixture plus this separately named implementation."""
    pins = {str(_SOURCE): _SOURCE_SHA, str(_METRICS_SOURCE): _METRICS_SHA,
            str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _helper_source_digest(_Path(path), owner_file=__file__) != expected:
            raise ValueError('Original spatial fixture source changed: '+path)
    return pins


def derivation():
    """Inspectable, deterministic mechanical-change evidence; no setup runs."""
    source_bindings()
    return dict(schema='atlas.private.original-spatial-derivation.r1',
                source=str(_SOURCE), source_sha256=_SOURCE_SHA,
                derived_text_sha256=_DERIVED_SHA,
                changes=[label for label, _, _ in _EDITS],
                scientific_changes=False)


source_bindings()
_ORIGINAL_TEXT = _read_bound(_SOURCE, _SOURCE_SHA)
_DERIVED_TEXT = _derive(_ORIGINAL_TEXT)
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_spatial_r1]', 'exec'), globals())

from atlas_tectonics._private.runtime_initial_metrics import initial_metrics
