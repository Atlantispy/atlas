"""Refuter p1d, check 2: parent ownership, exact-type lookup and decode parity (r4).

On real regions from ps/cap1/wall-0.json (the small case's own exact values):
A. owned: an _OwnedPlanes region through _shared_inputs; the parent's dict, its
   _physical_planes object, its _owner and every other value are untouched (same ids),
   and the worker decode (_decode_shared) gives a plain tuple equal pair by pair, with
   the same element types, and the same encoding as the plain region.
B. subclass of _OwnedPlanes -> TypeError from _enc (serial), never sent.
C. helper absent from sys.modules -> TypeError (serial).
D. a different module object under the same name (fresh ModuleType with its own
   _OwnedPlanes) -> TypeError (serial).
E. importlib.reload(helper): an instance of the old class -> TypeError (serial); a new
   instance -> sent, identical bytes.
F. decoded bound: parent _shared_inputs value == worker formula on the joined chunks.
Reads only. Usage: r2_ownership.py <frozen:folder> <capture dir>
"""
import importlib
import json
import sys
import types
import weakref
from pathlib import Path

T = Path('C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10')
sys.path.insert(0, str(T/'ps'/'scripts'))
import rc1_env  # noqa: E402


class Owner:
    pass


def main():
    rc1_env.install(sys.argv[1])
    capture = Path(sys.argv[2])
    from atlas_tectonics import integration_pressure_walls as W
    from atlas_tectonics import resources as RS
    import pressure_indexed_patch as X
    budget = RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44)
    record = json.loads((capture/'wall-0.json').read_bytes())
    rays, profiles, selected, native_box, reservoirs, pose = W._dec(record['call'], budget)
    args = dict(W._dec(record['args'], budget), budget=budget)
    plain = [{k: v for k, v in r.items() if k != 'side'} for r in selected if r.get('_physical_planes')][:6]
    walls = [(None, None, rays, pose, None)]*4
    fails = []

    def send(regions):
        return W._shared_inputs(walls, regions, profiles, native_box, reservoirs, args)

    ref_inputs, ref_ids, ref_size, ref_decoded = send(plain)
    # A. owned regions
    owner = Owner()
    alive = weakref.ref(owner)
    owned = [dict(r, _physical_planes=X._OwnedPlanes(r['_physical_planes'], owner)) for r in plain]
    before = [(id(r), list(r), [id(v) for v in r.values()], type(r['_physical_planes']),
               r['_physical_planes']._owner) for r in owned]
    inputs, ids, size, decoded = send(owned)
    after = [(id(r), list(r), [id(v) for v in r.values()], type(r['_physical_planes']),
              r['_physical_planes']._owner) for r in owned]
    if before != after:
        fails.append('A: a parent region, its planes object or owner changed')
    if any(type(r['_physical_planes']) is not X._OwnedPlanes for r in owned):
        fails.append('A: parent lost its _OwnedPlanes')
    if (ids, size, decoded) != (ref_ids, ref_size, ref_decoded) or inputs != ref_inputs:
        fails.append('A: owned encoding differs from the plain (ordinary-route) encoding')
    shared = W._decode_shared(inputs, ids, RS.WorkBudget(16 << 30, max_predicate_work_units=1 << 44))
    for i, (got, want) in enumerate(zip(shared['regions'], plain)):
        planes = got['_physical_planes']
        if type(planes) is not tuple:
            fails.append('A: worker region %d planes type %s' % (i, type(planes).__name__))
        if len(planes) != len(want['_physical_planes']) or any(
                a != b or type(a[1]) is not type(b[1]) or type(a[0]) is not type(b[0])
                for a, b in zip(planes, want['_physical_planes'])):
            fails.append('A: worker region %d pairs differ' % i)
        if list(got) != list(want):
            fails.append('A: worker region %d key order differs' % i)
    del owned
    if alive() is None:
        fails.append('A: owner died while the test still held it (unexpected)')
    print('A owned', 'PASS' if not fails else 'FAIL', 'regions', len(plain), 'pairs',
          sum(len(r['_physical_planes']) for r in plain), 'raw', size, 'decoded', decoded, flush=True)

    def refused(label, regions):
        try:
            send(regions)
        except TypeError as error:
            print(label, 'REFUSED (serial):', error, flush=True)
            return
        fails.append(label+': sent instead of refused')
        print(label, 'SENT (unexpected)', flush=True)

    class Sub(X._OwnedPlanes):
        pass
    refused('B subclass', [dict(plain[0], _physical_planes=Sub(plain[0]['_physical_planes'], owner))])
    keep = sys.modules.pop('pressure_indexed_patch')
    try:
        refused('C helper absent', [dict(plain[0], _physical_planes=keep._OwnedPlanes(plain[0]['_physical_planes'], owner))])
        fake = types.ModuleType('pressure_indexed_patch')

        class _OwnedPlanes(tuple):
            pass
        fake._OwnedPlanes = _OwnedPlanes
        sys.modules['pressure_indexed_patch'] = fake
        refused('D other module object', [dict(plain[0], _physical_planes=keep._OwnedPlanes(plain[0]['_physical_planes'], owner))])
    finally:
        sys.modules['pressure_indexed_patch'] = keep
    old = X._OwnedPlanes(plain[0]['_physical_planes'], owner)
    importlib.reload(X)
    if X._OwnedPlanes is type(old):
        fails.append('E: reload kept the class (test vacuous)')
    refused('E reload old instance', [dict(plain[0], _physical_planes=old)])
    one = send([dict(plain[0], _physical_planes=X._OwnedPlanes(plain[0]['_physical_planes'], owner))])
    if one[0] != send([plain[0]])[0]:
        fails.append('E: new-class instance after reload encodes differently')
    # F. the worker's number from the joined chunks
    worker = W._decoded_bound(b''.join(inputs[i] for i in ids))
    if worker != decoded:
        fails.append('F: worker bound %d != parent %d' % (worker, decoded))
    print('F decoded bound parent == worker:', worker == decoded, flush=True)
    print('OWNERSHIP', 'PASS' if not fails else 'FAIL', fails, flush=True)


if __name__ == '__main__':
    main()
