"""Source-bound spatial owner derivative and explicit witness reporting.

Owner functions keep the selected heat-method keyword/forwarding derivative.
Initial metrics comes from the separately pinned production observer port.
No module rebinding, mocking or historical fixture loading is performed.
"""

from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _HERE.parent / 'geometry/runtime_spatial_fixture.py'
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
        result = result.replace(before, after, 1)
    return result


def _read_source(path):
    return path.read_bytes().decode('utf8').replace('\r\n', '\n')


def derivation():
    """Inspectable, deterministic mechanical-change evidence; no setup runs."""
    return dict(schema='atlas.private.original-spatial-derivation.r1',
                source=str(_SOURCE),
                derived_text_sha256=_DERIVED_SHA,
                changes=[label for label, _, _ in _EDITS],
                scientific_changes=False)


_ORIGINAL_TEXT = _read_source(_SOURCE)
_DERIVED_TEXT = _derive(_ORIGINAL_TEXT)
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_spatial_r1]', 'exec'), globals())

from atlas_tectonics._private.integration.runtime_initial_metrics import initial_metrics
