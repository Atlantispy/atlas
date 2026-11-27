"""Owned exact intersections of newly certified SAME-functional face rows.

Input rows, their validity certificates and producer identity remain separately
owned by the fixed forward method. This checks original face/key/owner order
and intersects rational enclosures, never inventing their validity. Unchanged
rows and endpoint values are shared by reference; their input owners must stay
live. New containers and GMP comparison scratch are admitted before creation.
"""
from concurrent.futures import CancelledError
import sys
from atlas_tectonics._private import private_heat_decimal_sparse_core_r1 as P


def intersect(rows, refined, selected, *, budget, cancel=None):
    return _intersect(rows, refined, selected, budget, cancel, None)


def _intersect(rows, refined, selected, budget, cancel, original_maximum):
    def check():
        if cancel is not None and cancel():
            raise CancelledError('Selective functional refinement cancelled')
    check()
    from atlas_tectonics._exact_runtime import selected as exact_backend
    exact_backend.library()
    from atlas_tectonics._private.integration.heat import gmp_resources as R
    count, largest = 0, 1
    for row in refined:
        check()
        count += len(row['bounds'])
        for pair in row['bounds'].values():
            for value in pair:
                largest = max(largest, sys.getsizeof(value))
    if original_maximum is None:
        for row in rows:
            check()
            for pair in row['bounds'].values():
                for value in pair:
                    largest = max(largest, sys.getsizeof(value))
    else:
        for _ in rows:
            check()
        largest = max(largest, original_maximum)
    # Shallow native sizes are upper bounds for represented integer widths,
    # not allocated capacity claims. Source owners retain actual endpoint data.
    scratch = R.native_workspace_allowance(32*largest, 32)
    amount = scratch+1024*(2*len(rows)+12*len(refined)+6*count+32)
    workspace = R.OwnedWorkspace(budget, amount, category='heat-selective-refinement-merge', cancelled=cancel)
    workspace.__enter__()
    try:
        selected_set = set(selected)
        originals = [row for row in rows if row['face_id'] in selected_set]
        replacements, bounds_checked = {}, 0
        for old, new in zip(originals, refined, strict=True):
            check()
            bounds = {}
            for key in old['ordered_keys']:
                check()
                a,b = old['bounds'][key]
                c,d = new['bounds'][key]
                low,high = max(a,c),min(b,d)
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
