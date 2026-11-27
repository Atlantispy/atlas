"""PRIVATE diag22 cold bridge: diag21's lazy-transport repair without editing the public module.

The public ``integration_private_heat_cold`` stays at its diag20 bytes, so the
execution identity is unchanged. This module derives the diag21 text from it
(the lazy ``cold_transport`` branch) and executes it as a separate module. ``selected()`` binds it as the
package attribute that ``CollarWorkflow``'s ``from . import`` resolves, for the
reader scope only; ``sys.modules`` and the public module object are untouched,
so the strict callable inventory still sees the public functions.
"""
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
import types

from atlas_tectonics.integration import heat as HEAT
import atlas_tectonics.integration.heat.private_heat_cold as PUBLIC

NAME = 'private_heat_cold'
# The derived text: the public file with diag21's lazy-transport branch; made in memory by _derive.
_EDITS = (
    ("""            metadata = {k: v for k, v in exchange['transport'].items() if k != 'result_id'}
            work.stack.enter_context(budget.reserve(
                _snapshot_charge(metadata, transport_fields), category='private-cold-transport-retained'))
            transport = RegionalMechanicalSnapshot(metadata, transport_fields)
""",
     """            saved_transport = exchange['transport']
            metadata = None
            if isinstance(saved_transport, _SV._Lazy):
                from atlas_tectonics._private.integration.heat.cold_transport import cold_transport
                # The accessor owns saved_transport.ref only until this
                # function returns. Borrow a separate child directly from the
                # caller-owned exchange for the binding's longer lifetime.
                transport_ref = _SV._reference(exchange).field('transport')
                work.stack.callback(transport_ref.close)
                transport = work.stack.enter_context(cold_transport(
                    transport_ref, transport_fields, budget,
                    expected_id=exchange.get('global_transport_id'),
                    check=lambda: R.check(cancel)))
            else:
                metadata = {k: v for k, v in saved_transport.items() if k != 'result_id'}
                work.stack.enter_context(budget.reserve(
                    _snapshot_charge(metadata, transport_fields), category='private-cold-transport-retained'))
                transport = RegionalMechanicalSnapshot(metadata, transport_fields)
"""),
)
_lock = threading.Lock()


def _derive():
    path = Path(PUBLIC.__file__)
    text = path.read_bytes().decode('utf-8')
    for old, new in _EDITS:
        if text.count(old) != 1:
            raise ValueError('public cold bridge edit site differs')
        text = text.replace(old, new)
    module = types.ModuleType(__name__ + '.derived')
    # __file__ stays the public path.
    module.__dict__.update(__file__=str(path), __package__=PUBLIC.__package__, __builtins__=__builtins__)
    exec(compile(text, str(path)+'[cold_bridge_r1]', 'exec', dont_inherit=True), module.__dict__)
    return module


DERIVED = _derive()


@contextmanager
def selected():
    """Bind the derived bridge for this scope; always restore the public binding."""
    with _lock:
        if sys.modules.get(PUBLIC.__name__) is not PUBLIC or getattr(HEAT, NAME, None) is not PUBLIC:
            raise ValueError('public cold bridge binding differs')
        setattr(HEAT, NAME, DERIVED)
    try:
        yield DERIVED
    finally:
        with _lock:
            setattr(HEAT, NAME, PUBLIC)
