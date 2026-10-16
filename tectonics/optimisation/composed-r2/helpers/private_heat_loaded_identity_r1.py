"""Private dependency identity binding disk bytes AND actual loaded semantics.

Uses the native execution identity's code normalisation and constant encoding.
An old cached module beside changed source must have a different identity from
a fresh import, even before this guard exists. This records both realities; it
does not claim that loaded instructions were compiled from current disk bytes.
No module is reloaded, executed, patched or repinned by this helper. No native
resource admission or adversarial-Python security boundary is claimed.
"""
from concurrent.futures import CancelledError
from hashlib import sha256
import marshal
from pathlib import Path
from types import FunctionType, ModuleType

from atlas_tectonics import reuse as R


def _check(cancel):
    if cancel is not None and cancel():
        raise CancelledError('Private loaded identity cancelled')


def _members(module):
    for label, value in sorted(vars(module).items()):
        yield label, value
        if isinstance(value, type) and value.__module__ == module.__name__:
            for name, member in sorted(vars(value).items()):
                if isinstance(member, (staticmethod, classmethod)):
                    yield label+'.'+name, member.__func__
                elif isinstance(member, property):
                    for suffix, getter in (('get', member.fget), ('set', member.fset), ('del', member.fdel)):
                        if getter is not None:
                            yield label+'.'+name+'.'+suffix, getter
                else:
                    yield label+'.'+name, member


def _inventory(modules, cancel):
    functions, constants, sources, tokens = {}, {}, {}, []
    names = set()
    for module in modules:
        _check(cancel)
        if type(module) is not ModuleType or module.__name__ in names:
            raise ValueError('Unique actual dependency modules required')
        names.add(module.__name__)
        path = Path(module.__file__).resolve()
        sources[module.__name__] = dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
        for label, value in sorted(vars(module).items()):
            _check(cancel)
            if label.isupper() and R._captured(value):
                constants[module.__name__+'.'+label] = R._constant(value)
        for label, function in _members(module):
            _check(cancel)
            key = module.__name__+'.'+label
            if type(function) is FunctionType:
                defaults = R._json((R._constant(function.__defaults__), R._constant(function.__kwdefaults__)))
                if key in functions:
                    raise ValueError('Ambiguous private callable name: '+key)
                functions[key] = dict(code=sha256(marshal.dumps(R._normal_code(function.__code__), 2)).hexdigest(),
                                      defaults=sha256(defaults).hexdigest())
                tokens.append((key, function, function.__code__, defaults))
            elif callable(function) and not isinstance(function, type):
                tokens.append((key, function, None, None))
    record = R._json(dict(schema='atlas.private.loaded-dependencies.r1',
        sources=sources, functions=functions, constants=constants, marshal_protocol=2,
        source_matches_loaded_not_asserted=True))
    return record, tuple(tokens)


class LoadedIdentity:
    """Keep this guard with its source/runtime-bound owner; no fresh re-capture."""
    def __init__(self, modules, *, cancel=None):
        self._modules = tuple(sorted(modules, key=lambda module: module.__name__))
        self._encoded, self._tokens = _inventory(self._modules, cancel)
        self.identity = sha256(self._encoded).hexdigest()

    def descriptor(self):
        return dict(schema='atlas.private.loaded-dependencies.r1', identity=self.identity,
                    source_and_loaded_semantics_bound=True, source_matches_loaded_not_asserted=True)

    def verify(self, modules, *, cancel=None):
        current = tuple(sorted(modules, key=lambda module: module.__name__))
        if len(current) != len(self._modules) or any(a is not b for a, b in zip(current, self._modules, strict=True)):
            raise ValueError('Private dependency membership or module binding changed')
        encoded, tokens = _inventory(current, cancel)
        if encoded != self._encoded or len(tokens) != len(self._tokens):
            raise ValueError('Private source or loaded implementation changed')
        for old, new in zip(self._tokens, tokens, strict=True):
            if old[0] != new[0] or old[1] is not new[1] or old[2] is not new[2] or old[3] != new[3]:
                raise ValueError('Private callable binding or defaults changed')
        return self.identity
