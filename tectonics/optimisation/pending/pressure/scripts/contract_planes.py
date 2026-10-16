"""P1 r4 contract: moving_wall_integrals uses only truth, len and iteration of _physical_planes.

On real wall_set calls captured by capture_walls.py (CAPTURE/wall-<n>.json, the small case):
1. replay: the decoded call gives exactly the captured result (canonical tagged bytes);
2. strict: every non-empty _physical_planes becomes a Strict sequence that allows only
   bool(), len() and iter() (so zip); any other use raises ContractBroken, a BaseException
   no `except Exception` can swallow, and is also recorded. Result must be identical and
   no breach recorded; iter() must have been used (the check is not vacuous);
3. owned: the same pairs as pressure_indexed_patch._OwnedPlanes give the identical result;
4. transport (r4): _plain_planes turns the owned region into the plain one: its encoding is
   byte-identical to the ordinary route's plain tuple, an _OwnedPlanes alone is still refused
   by _enc, and a plain region passes unchanged (the same object).
Mutants (each must be CAUGHT; the unmutated control must pass): four uses of _physical_planes
outside the contract compiled into a copy of moving_wall_integrals (slice, ==, .count,
indexing), one isinstance check, and _plain_planes returning the region unchanged.
Usage: contract_planes.py <candidate frozen:folder> CAPTURE [MAX_WALLS]
"""
import inspect
import json
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rc1_env  # noqa: E402


class ContractBroken(BaseException):
    pass


def strict_type(ops):
    def broken(what):
        ops['broken'].append(what)
        raise ContractBroken(what)

    class Strict:
        """Truth, len and iteration only: the _OwnedPlanes contract."""
        __slots__ = ('_items',)

        def __init__(self, items):
            object.__setattr__(self, '_items', tuple(items))

        def __bool__(self):
            ops['bool'] += 1
            return bool(object.__getattribute__(self, '_items'))

        def __len__(self):
            ops['len'] += 1
            return len(object.__getattribute__(self, '_items'))

        def __iter__(self):
            ops['iter'] += 1
            return iter(object.__getattribute__(self, '_items'))

        def __getattribute__(self, name):
            broken('attribute '+name)

        def __setattr__(self, name, value):
            broken('setattr '+name)

    def refuse(name):
        def method(self, *args, **kwargs):
            broken(name)
        method.__name__ = name
        return method
    for name in ('__getitem__', '__contains__', '__reversed__', '__eq__', '__ne__', '__lt__', '__le__',
                 '__gt__', '__ge__', '__hash__', '__add__', '__radd__', '__mul__', '__rmul__', '__repr__',
                 '__str__', '__format__', '__reduce__', '__reduce_ex__', '__copy__', '__deepcopy__',
                 '__delattr__', '__sizeof__', '__dir__'):
        setattr(Strict, name, refuse(name))
    return Strict


def load(W, budget, raw):
    record = json.loads(raw)
    rays, profiles, selected, native_box, reservoirs, pose = W._dec(record['call'], budget)
    args = dict(W._dec(record['args'], budget), budget=budget)
    return record, (rays, profiles, selected, native_box, reservoirs, pose), args


def replay(W, RS, raw, wrap=None):
    """(canonical result bytes or 'raise: ...', captured result bytes)."""
    budget = RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    record, (rays, profiles, selected, native_box, reservoirs, pose), args = load(W, budget, raw)
    if wrap is not None:
        selected = [dict(region, _physical_planes=wrap(region['_physical_planes']))
                    if region.get('_physical_planes') else region for region in selected]
    expected = W.canonical(dict(result=record['result']))
    try:
        result = W.wall_set(rays, profiles, selected, native_box, reservoirs, pose, args)
    except ContractBroken as error:
        return 'contract: %s' % error, expected
    except Exception as error:  # noqa: BLE001
        return 'raise: %s: %s' % (type(error).__name__, error), expected
    return W.canonical(dict(result=W._enc(result))), expected


def check_walls(W, RS, X, walls, moving=None):
    """Failing checks for these captured walls; moving replaces P.moving_wall_integrals."""
    P = W.P
    saved = P.moving_wall_integrals
    fails, ops = [], dict(bool=0, len=0, iter=0, broken=[])
    Strict = strict_type(ops)
    try:
        if moving is not None:
            P.moving_wall_integrals = moving
        for path in walls:
            raw = path.read_bytes()
            got, expected = replay(W, RS, raw)
            if got != expected:
                fails.append('%s replay differs: %s' % (path.name, str(got)[:160]))
            got, expected = replay(W, RS, raw, Strict)
            if got != expected:
                fails.append('%s strict differs: %s' % (path.name, str(got)[:160]))
            got, expected = replay(W, RS, raw, lambda planes: X._OwnedPlanes(planes, None))
            if got != expected:
                fails.append('%s owned differs: %s' % (path.name, str(got)[:160]))
    finally:
        P.moving_wall_integrals = saved
    if ops['broken']:
        fails.append('contract breached: %r' % sorted(set(ops['broken'])))
    if not ops['iter']:
        fails.append('vacuous: _physical_planes never iterated')
    return fails, ops


def check_transport(W, RS, X, walls, plain_planes):
    fails = []
    budget = RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    seen = 0
    for path in walls:
        _, (_, _, selected, _, _, _), _ = load(W, budget, path.read_bytes())
        for region in selected:
            planes = region.get('_physical_planes')
            if not planes:
                continue
            seen += 1
            owned = dict(region, _physical_planes=X._OwnedPlanes(planes, None))
            try:
                sent = W.canonical(dict(r=W._enc(plain_planes(owned))))
            except Exception as error:  # noqa: BLE001
                fails.append('%s: owned region not sent: %s' % (path.name, error))
                break
            if sent != W.canonical(dict(r=W._enc(region))):
                fails.append('%s: owned region encodes differently from the plain one' % path.name)
            if plain_planes(region) is not region:
                fails.append('%s: a plain region was rebuilt' % path.name)
            try:
                W._enc(owned)
                fails.append('%s: _enc accepted an _OwnedPlanes' % path.name)
            except TypeError:
                pass
            if list(owned) != list(region) or list(plain_planes(owned)) != list(region):
                fails.append('%s: key order changed' % path.name)
    if not seen:
        fails.append('vacuous: no region with physical planes')
    return fails


MOVING_MUTANTS = (
    ('slice', 'zip(extra, physical)', 'zip(extra, physical[:len(extra)])'),
    ('equality', 'if physical and len(physical) != len(extra):', 'if physical != () and len(physical) != len(extra):'),
    ('method', 'if physical and len(physical) != len(extra):',
     'if physical and physical.count(None) >= 0 and len(physical) != len(extra):'),
    ('index', 'zip(extra, physical)', 'zip(extra, (physical[i] for i in range(len(physical))))'),
    ('isinstance', '        if physical:\n', '        if isinstance(physical, tuple) and physical:\n'),
)


def main():
    rc1_env.install(sys.argv[1])
    capture = Path(sys.argv[2])
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import resources as RS
    import pressure_indexed_patch as X
    walls = sorted(capture.glob('wall-*.json'), key=lambda p: int(p.stem.split('-')[1]))[:limit]
    if not walls:
        raise SystemExit('CONTRACT FAIL no captured walls in %s' % capture)
    bad = []
    fails, ops = check_walls(W, RS, X, walls)
    fails += check_transport(W, RS, X, walls, W._plain_planes)
    print('control', 'PASS' if not fails else 'FAIL', 'walls', len(walls),
          'ops', {k: v for k, v in ops.items() if k != 'broken'}, flush=True)
    for failure in fails:
        print('  ', failure, flush=True)
    if fails:
        bad.append('control')
    source = textwrap.dedent(inspect.getsource(W.P.moving_wall_integrals))
    for label, old, new in MOVING_MUTANTS:
        if source.count(old) != 1:
            raise SystemExit('CONTRACT FAIL mutant anchor %s found %d times' % (label, source.count(old)))
        namespace = dict(vars(W.P))
        exec(compile(source.replace(old, new), '<mutant %s>' % label, 'exec'), namespace)  # noqa: S102
        fails, _ = check_walls(W, RS, X, walls[:2], namespace['moving_wall_integrals'])
        print('mutant', label, 'CAUGHT: '+fails[0][:150] if fails else 'MISSED', flush=True)
        if not fails:
            bad.append(label)
    fails = check_transport(W, RS, X, walls[:2], lambda region: region)
    print('mutant plain-unchanged', 'CAUGHT: '+fails[0][:150] if fails else 'MISSED', flush=True)
    if not fails:
        bad.append('plain-unchanged')
    print('CONTRACT PASS' if not bad else 'CONTRACT FAIL %r' % bad, flush=True)
    raise SystemExit(1 if bad else 0)


if __name__ == '__main__':
    main()
