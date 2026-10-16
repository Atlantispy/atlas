"""Explicit caller-owned endpoint restart storage in an additive ALE successor.

No implicit directory, identity, store, or policy change. The caller keeps the
strict checkpoint owner alive around the whole pass. The ordinary default path
remains identical, and scientific query validation precedes any cached reuse.
"""
from pathlib import Path


def _replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError('ALE checkpoint seam missing or ambiguous: '+old[:80])
    return source.replace(old, new)


def candidate_source(package):
    source = (Path(package)/'integration_differential_ale.py').read_text(encoding='utf8')
    source = _replace(source,
        'parallel=None, _component_parallel=None):',
        'parallel=None, _component_parallel=None, _endpoint_checkpoints=None):')
    source = _replace(source,
        '                _component_parallel=_component_parallel)',
        '                _component_parallel=_component_parallel,\n'
        '                _endpoint_checkpoints=_endpoint_checkpoints)')
    source = _replace(source,
        'max_native_mask_leaves=None, _parallel=None, _observer=None, _component_parallel=None):',
        'max_native_mask_leaves=None, _parallel=None, _observer=None, _component_parallel=None,\n'
        '              _endpoint_checkpoints=None):')
    source = _replace(source,
        '                            else _component_parallel.claim)))',
        '                            else _component_parallel.claim),\n'
        '                        _checkpoint=_endpoint_checkpoints))')
    return source
