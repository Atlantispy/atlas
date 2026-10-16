"""Pinned historical continuation helper with its two work ceilings as keywords.

The source is ``source/tectonics/tests/i04_differential_continuation_control.py``
(``continuation_pressure_force``: the force of a second interval, rebuilt from
an accepted endpoint). It runs the endpoint pressure forcing with a literal
``max_leaves=4096`` and the current-state trace with a literal
``max_leaves=64``. The first-interval helper has the same two figures as the
defaults of keywords (``pressure_max_leaves``, ``initial_trace_max_leaves``)
and says of them: "Explicit leaf keywords change work ceilings only;
physical/error limits and omitted-keyword behaviour remain the retained
control's declarations". The producer driver gives the first interval 2**19
for both. On the original ACTUATED case the endpoint pressure refuses at 4096
leaves ("owned wall pressure enclosure exceeds declared torque width/leaf
budget").

This module is that source after five exact replacements, each of which must
match once: the two literals become keywords ``pressure_max_leaves`` and
``current_trace_max_leaves`` whose defaults are the literals, the keywords are
validated as the first-interval helper validates its own, and the record of
the trace's arguments names the ceiling actually used. Nothing else differs:
the torque width, operator error, moment width, volume width, the authored
force, the checks of identity and clock, and what is handed to the callback are
the source's own lines. Called without the keywords it is the source.

No native science module or historical test helper is patched: the source file
is read, never written, and is pinned by SHA-256.
"""
from hashlib import sha256 as _sha256
from pathlib import Path as _Path

_HERE = _Path(__file__).resolve().parent
_SOURCE = _Path('C:\\Users\\LOCAL_USER\\Documents\\Codex\\2026-09-02\\the-diadem-local-tasks-10\\fidelity-integration-20261005\\heat-repair-20261007\\source\\tectonics\\tests\\i04_differential_continuation_control.py')
_SOURCE_SHA = '9bae6ed33ed9e223ef7a8e0cdf447fc621ad78583d3a97760ff400e25ed80e60'
_SELF_SHA = _sha256(_Path(__file__).read_bytes()).hexdigest()
_EDITS = (
    ('work-ceilings-as-keywords-with-the-literals-as-defaults',
     'def continuation_pressure_force(test, case, workflow, prepared_control, *, force_control=ORIGINAL_CONTROL):\n',
     'def continuation_pressure_force(test, case, workflow, prepared_control, *, force_control=ORIGINAL_CONTROL,\n'
     '                                pressure_max_leaves=4096, current_trace_max_leaves=64):\n'),
    ('validate-work-ceilings-as-the-first-interval-helper-does',
     "    budget, native, collar, funding = (case[k] for k in ('budget', 'native', 'collar', 'funding'))\n",
     "    for name, value in (('pressure_max_leaves', pressure_max_leaves),\n"
     "                        ('current_trace_max_leaves', current_trace_max_leaves)):\n"
     "        if type(value) is not int or value < 1:\n"
     "            raise ValueError(name+' must be an explicit positive integer work ceiling')\n"
     "    budget, native, collar, funding = (case[k] for k in ('budget', 'native', 'collar', 'funding'))\n"),
    ('pressure-work-ceiling',
     "            max_operator_error=Q(1, 10**20), max_leaves=4096, budget=budget)\n",
     "            max_operator_error=Q(1, 10**20), max_leaves=pressure_max_leaves, budget=budget)\n"),
    ('retained-trace-arguments-name-the-ceiling-used',
     "                 max_volume_width=V._encoded(Q(0)), max_leaves=64), budget)\n",
     "                 max_volume_width=V._encoded(Q(0)), max_leaves=current_trace_max_leaves), budget)\n"),
    ('current-trace-work-ceiling',
     "                max_moment_width=Q(1, 10**24), max_volume_width=0, max_leaves=64,\n",
     "                max_moment_width=Q(1, 10**24), max_volume_width=0, max_leaves=current_trace_max_leaves,\n"),
)


def _replace_exact(source, edits):
    result = source
    for label, before, after in edits:
        if result.count(before) != 1:
            raise ValueError('Original continuation derivative anchor differs: '+label)
        result = result.replace(before, after, 1)
    return result


def _read_bound(path, expected):
    raw = path.read_bytes()
    if _sha256(raw).hexdigest() != expected:
        raise ValueError('Original continuation source changed while loading: '+str(path))
    return raw.decode('utf8').replace('\r\n', '\n')


def source_bindings():
    pins = {str(_SOURCE): _SOURCE_SHA, str(_Path(__file__).resolve()): _SELF_SHA}
    for path, expected in pins.items():
        if _sha256(_Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError('Original continuation helper source changed: '+path)
    return pins


def derivation():
    """Exact frozen input and deterministic changes; no scientific execution."""
    source_bindings()
    return dict(schema='atlas.private.original-continuation-derivation.r1',
                source=str(_SOURCE), source_sha256=_SOURCE_SHA, derived_text_sha256=_DERIVED_SHA,
                changes=[label for label, _, _ in _EDITS]+['compact-partition-selected-fields-and-indexed-material-record', 'compact-trace-inputs-streamed-without-whole-support-decode', 'original-funding-transfer-forwarded-to-both-pressure-calls'],
                defaults_are_the_source_literals=dict(pressure_max_leaves=4096, current_trace_max_leaves=64),
                error_limits_changed=False, scientific_changes=False,
                scope='work ceilings of the endpoint pressure forcing and of the current-state trace; '
                      'compact partition/material readers, streamed trace-input capture and the '
                      'original funding transfer of both pressure calls (no physical change)')


source_bindings()
_ORIGINAL_TEXT = _read_bound(_SOURCE, _SOURCE_SHA)
from partition_routing_transform import continuation_control_source as _compact_continuation
from funding_transfer import continuation_control_source_after_limits as _funding_continuation
_DERIVED_TEXT = _funding_continuation(_compact_continuation(_replace_exact(_ORIGINAL_TEXT, _EDITS)))
_DERIVED_SHA = _sha256(_DERIVED_TEXT.encode('utf8')).hexdigest()
exec(compile(_DERIVED_TEXT, str(_SOURCE)+'[private_heat_original_continuation_r1]', 'exec'), globals())
