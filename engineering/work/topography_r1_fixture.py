"""One cached-in-process selected seed, not owner-supplied evolution forcing."""
from functools import lru_cache
from copy import deepcopy
from work.generator_upgrade_r18 import working
from work.generator_upgrade_r22 import terrain as previous
from work.test_r22_terrain import clock, forcing
from work.topography_r1 import terrain


@lru_cache(maxsize=1)
def fixture():
    seed = working.build({'r120_c80': {'xy_m': [2000, 2000], 'area_m2': 16000000}}, alternative='DEFAULT')
    old = previous.from_seed(seed, clock())
    new = terrain.from_seed(seed, clock())
    return seed, old, new, forcing(old)


def science(envelope):
    """Normalise only changed composition text and its dependent row checksum."""
    body = deepcopy(envelope['body'])
    for row in body['history']:
        row.pop('row_sha256')
        row['native_result']['receipt'].pop('numerical_composition')
    return body
