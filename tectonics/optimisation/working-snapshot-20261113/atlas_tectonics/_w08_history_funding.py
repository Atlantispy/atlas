"""Allocation allowances for the isolated S6 qualification route."""
from contextlib import contextmanager
import weakref

from .resources import _ResizableLease


GRAPH = 626688
PARSE = 931328
ENCODE = 901120
BODY = 196672
NUMERIC = 262144
SESSION = 65536


class Hold:
    """Keep the existing lease alive for the locals or result that own it."""
    def __init__(self, count, *roots, category):
        lease = _ResizableLease(*roots, category=category)
        lease.__enter__()
        self._lease = lease
        weakref.finalize(self, lease.__exit__, None, None, None)
        lease.resize(count)

    def resize(self, count):
        self._lease.resize(count)

@contextmanager
def retained_context(count, *roots, category):
    """The caller binds the ticket to a local through return or traceback."""
    yield Hold(count, *roots, category=category)


@contextmanager
def bind(target, name, value):
    absent = object()
    previous = getattr(target, name, absent)
    setattr(target, name, value)
    try:
        yield
    finally:
        if previous is absent:
            delattr(target, name)
        else:
            setattr(target, name, previous)


class ManifestFunds:
    """Funding for the original manifest decode and the later get tail."""
    def __init__(self, *roots):
        self.roots = roots
        self.session = Hold(SESSION, *roots, category='w08-store-session')
        self.read = self.raw = self.graph = self.chunks = None

    def enter(self, count):
        self.read = Hold(count, *self.roots, category='store-read')

    def before_fetch(self, body_length):
        if self.read is None:
            self.raw = Hold(64+body_length, *self.roots, category='w08-store-manifest-body')

    def before_parse(self, body_length):
        if self.read is not None:
            self.read.resize(64+body_length)
        self.graph = Hold(GRAPH+PARSE, *self.roots, category='w08-store-manifest-decode')

    def parsed(self):
        if self.read is not None:
            self.read.resize(0)
        self.raw = None
        self.graph.resize(GRAPH)

    def before_chunks(self, count):
        self.chunks = Hold(count, *self.roots, category='w08-store-chunk-work')
