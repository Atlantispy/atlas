"""Owned exact intersections of newly certified SAME-functional face rows.

Input rows, their validity certificates and producer identity remain separately
owned by the fixed forward method. This checks original face/key/owner order
and intersects rational enclosures, never inventing their validity. Unchanged
rows and endpoint values are shared by reference; their input owners must stay
live. New containers and GMP comparison scratch are admitted before creation.
"""
from concurrent.futures import CancelledError
import sys
import private_heat_decimal_sparse_core_r1 as P


def intersect(rows, refined, selected, *, budget, cancel=None):
    def check():
        if cancel is not None and cancel():
            raise CancelledError('Selective functional refinement cancelled')
    check()
    from atlas_tectonics.exact_arithmetic import library
    G = library()
    if G is None:
        raise RuntimeError('Selected GMP backend required')
    import private_heat_gmp_resources_r1 as R
    if type(rows) not in (list,tuple) or type(refined) not in (list,tuple) or type(selected) is not tuple:
        raise TypeError('Owned complete row sequence, refined rows and selection tuple required')
    count, largest = 0, 1
    for row in refined:
        check()
        count += len(row['bounds'])
        for pair in row['bounds'].values():
            for value in pair:
                if type(value) not in (G.mpq, int):
                    raise TypeError('Owned exact GMP refinement endpoints required')
                largest = max(largest, sys.getsizeof(value))
    for row in rows:
        check()
        for pair in row['bounds'].values():
            for value in pair:
                if type(value) not in (G.mpq, int):
                    raise TypeError('Owned exact GMP original endpoints required')
                largest = max(largest, sys.getsizeof(value))
    # Shallow native sizes are upper bounds for represented integer widths,
    # not allocated capacity claims. Source owners retain actual endpoint data.
    scratch = R.native_workspace_allowance(32*largest, 32)
    amount = scratch+1024*(2*len(rows)+12*len(refined)+6*count+32)
    workspace = R.OwnedWorkspace(budget, amount, category='heat-selective-refinement-merge', cancelled=cancel)
    workspace.__enter__()
    try:
        if len(set(selected)) != len(selected):
            raise ValueError('Duplicate selected face')
        selected_set = set(selected)
        if tuple(row['face_id'] for row in rows if row['face_id'] in selected_set) != selected:
            raise ValueError('Selection must match original face order and coverage')
        if tuple(row['face_id'] for row in refined) != selected:
            raise ValueError('Complete same-order refined face coverage required')
        replacements, bounds_checked = {}, 0
        originals = {row['face_id']:row for row in rows if row['face_id'] in selected_set}
        if len(originals) != len(selected):
            raise ValueError('Distinct original selected faces required')
        for new in refined:
            check()
            old = originals[new['face_id']]
            if (new['owners'] != old['owners'] or new['ordered_keys'] != old['ordered_keys']
                    or set(new['bounds']) != set(old['bounds'])):
                raise ValueError('Refinement changed owners, observation keys or their order')
            bounds = {}
            for key in old['ordered_keys']:
                check()
                a,b = old['bounds'][key]
                c,d = new['bounds'][key]
                if a>b or c>d:
                    raise ValueError('Reversed certified enclosure')
                low,high = max(a,c),min(b,d)
                if low>high:
                    raise ValueError('Disjoint certificates for supposedly identical functional')
                bounds[key] = low,high
                bounds_checked += 1
            replacements[new['face_id']] = dict(face_id=new['face_id'], owners=old['owners'],
                ordered_keys=old['ordered_keys'],bounds=bounds)
        merged = [replacements.get(row['face_id'],row) for row in rows]
        return P.OwnedSolve((merged, dict(selected_face_ids=selected,
            same_owners_and_observation_order=True, exact_intersection_bounds=bounds_checked,
            validity_requires_fixed_same_functional_producer=True,
            input_owners_must_remain_live=True, admitted_container_and_scratch_bytes=amount)), workspace)
    except BaseException:
        workspace.__exit__(*sys.exc_info())
        raise
