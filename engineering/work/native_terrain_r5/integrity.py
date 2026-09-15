"""R4 verification with explicit R5 references, independent of store location."""
import hashlib
from pathlib import Path
from work.native_terrain_r3.session import _adapt
from work.native_terrain_r4 import integrity as retained
from . import history as h

SCHEMA = 'diadem.native-history-commitment.r5'


def _verify_source():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != globals().get('_R12_EXECUTED_SHA256'):
        raise ValueError('executed R5 integrity source differs; no repin')


_verify_history = _adapt(retained.verify_history, h=h, _verify_source=_verify_source)


def verify_history(history, *, full=False):
    # The retained bytecode adapter does not copy keyword-only defaults.
    return _verify_history(history, full=full)


commitment = _adapt(retained.commitment, h=h, SCHEMA=SCHEMA,
                    verify_history=verify_history, _verify_source=_verify_source)


def scientific_sha(body):
    _verify_source()
    from .provenance import scientific_sha as logical_sha
    return logical_sha(body)
