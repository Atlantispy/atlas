"""Pinned additive derivative of the actual differential initial-owner fixture.

Only an explicit heat_method keyword and its native constructor forwarding
are added. No scientific setup, funding, projection allowance or source file
is changed. Import this after selecting the intended private native package.
"""
from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\heat-repair-20261007\\source\\tectonics\\tests\\i04_differential_spatial_fixture.py')
_SOURCE_SHA = 'f13d48b68e0b6f0b2de92e2bb903c71fe6beb92e56f2795be131ea2488b760ee'
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
    pins = {str(_SOURCE): _SOURCE_SHA, str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _sha256(_Path(path).read_bytes()).hexdigest() != expected:
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
