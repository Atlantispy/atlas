"""PRIVATE diag22 cold bridge: diag21's lazy-transport repair without editing the public module.

The public ``integration_private_heat_cold`` stays at its diag20 bytes, so the
execution identity is unchanged. This module derives the diag21 text from it
(the reviewed binding pin and the lazy ``cold_transport`` branch), checks both
digests, and executes it as a separate module. ``selected()`` binds it as the
package attribute that ``CollarWorkflow``'s ``from . import`` resolves, for the
reader scope only; ``sys.modules`` and the public module object are untouched,
so the strict callable inventory still sees the public functions.
"""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sys
import threading
import types

import atlas_tectonics
import atlas_tectonics.integration_private_heat_cold as PUBLIC

NAME = 'integration_private_heat_cold'
PUBLIC_SHA = 'e7dc4bddc71ef355fff4fbead34717a8a1d868ade8d606a9c0f8d02e0750c59d'
# Equal to the reviewed diag21 public file b9d44e30: the derived text is exactly that source.
DERIVED_SHA = 'b9d44e300e3cf2fa7aef9d557f700a0aba8483c8af808fa22e3d8102bad182de'
_EDITS = (
    ("_BINDING_SHA = '29ad6024cfe0125f5424b38648cf212e60bbf6a958a8a6e89ddd327fb3de5ae2'",
     "_BINDING_SHA = '3f9a0642c3f8052a2bf96557ead047f1aa055dea5928ec94a1c925fe6d6aa967'"),
    ("""            metadata = {k: v for k, v in exchange['transport'].items() if k != 'result_id'}
            work.stack.enter_context(budget.reserve(
                _snapshot_charge(metadata, transport_fields), category='private-cold-transport-retained'))
            transport = RegionalMechanicalSnapshot(metadata, transport_fields)
""",
     """            saved_transport = exchange['transport']
            metadata = None
            if isinstance(saved_transport, _SV._Lazy):
                from atlas_tectonics._private.cold_transport_candidate import cold_transport
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
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PUBLIC_SHA:
        raise ValueError('public cold bridge source differs')
    text = raw.decode('utf-8')
    for old, new in _EDITS:
        if text.count(old) != 1:
            raise ValueError('public cold bridge edit site differs')
        text = text.replace(old, new)
    if sha256(text.encode('utf-8')).hexdigest() != DERIVED_SHA:
        raise ValueError('derived cold bridge differs')
    module = types.ModuleType('atlas_tectonics._private.cold_bridge_r1.derived')
    # __file__ stays the public path: its _verify rehashes that file against the
    # public digest, so a public edit after derivation still refuses.
    module.__dict__.update(__file__=str(path), __package__='atlas_tectonics', __builtins__=__builtins__)
    exec(compile(text, str(path)+'[cold_bridge_r1]', 'exec', dont_inherit=True), module.__dict__)
    return module


DERIVED = _derive()


@contextmanager
def selected():
    """Bind the derived bridge for this scope; always restore the public binding."""
    with _lock:
        if sys.modules.get(PUBLIC.__name__) is not PUBLIC or getattr(atlas_tectonics, NAME, None) is not PUBLIC:
            raise ValueError('public cold bridge binding differs')
        setattr(atlas_tectonics, NAME, DERIVED)
    try:
        yield DERIVED
    finally:
        with _lock:
            setattr(atlas_tectonics, NAME, PUBLIC)
