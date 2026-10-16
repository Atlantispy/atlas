"""One bounded before/after publication run; no historical store or IV2."""
from contextlib import ExitStack
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

import psutil
import test_live_publication as F


def run(module_path):
    spec = importlib.util.spec_from_file_location('measured_publication', module_path)
    publication = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publication)
    case = F.LifetimeTests('test_geometry_decode_released_before_commit_and_exact_arrays')
    case.setUp()
    budget = case.budget
    process = psutil.Process()
    observations = []
    started = perf_counter()
    def checkpoint(label):
        memory = process.memory_info()
        observations.append(dict(label=label, seconds=perf_counter()-started,
            rss_bytes=memory.rss, private_bytes=memory.private, peak_wset_bytes=memory.peak_wset,
            logical_reserved_bytes=budget.reserved_bytes, logical_peak_bytes=budget.peak_reserved_bytes))
    solution, cls, raw, field = F.certification_fixture(budget, count=1262)
    class Interval:
        def descriptor(self):
            return json.loads(self._json)
    interval = Interval()
    interval._resource = budget
    values = {key: 'a'*64 for key in publication.DIFFERENTIAL_NAMES}
    values.update(start_time_s=['0x0', '0x1'], end_time_s=['0x1', '0x1'],
                  cells=F.F.fixture_records(239)['state']['cells'])
    interval._json = json.dumps(values).encode()
    interval.endpoint_network = SimpleNamespace(nbytes=field.nbytes,
        descriptor=lambda: dict(network_id='c'*64), arrays=lambda: dict(positions=field))
    checkpoint('constructed inputs')
    with patch('atlas_tectonics.integration_differential_geometry.DifferentialInterval', Interval), ExitStack() as stack:
        cert, cert_arrays = stack.enter_context(publication.certification_payload(
            cls, solution, budget, store=case.candidate, source_producer=F.F.PRODUCER))
        checkpoint('certification published')
        geometry, geometry_arrays = stack.enter_context(publication.differential_payload(
            interval, budget, store=case.candidate, source_producer=F.F.PRODUCER))
        checkpoint('geometry published; commit begins')
        row = dict(certification=cert, differential=geometry)
        arrays = dict(cert_arrays, **geometry_arrays)
        with F.F.ArrayStore(case.root/'head.sqlite', case.candidate.limits, budget=budget) as head:
            head.put('7'*64, arrays, row, budget=budget)
        checkpoint('commit complete')
    logical = {key: {name: header['record_blob'][name] for name in ('bytes', 'sha256')}
               for key, header in (('certification', cert), ('differential', geometry))}
    size = sum(p.stat().st_size for p in case.root.rglob('*') if p.is_file())
    elapsed = perf_counter()-started
    del cert, geometry, row, arrays, cert_arrays, geometry_arrays
    checkpoint('publication contexts released')
    result = dict(status='PASS', scope='bounded size-scaled publication/commit fixture; not real IV2',
        module_sha256=sha256(Path(module_path).read_bytes()).hexdigest(),
        fixture=dict(certification_cells=1262, geometry_cells=239,
                     certification_input_bytes=len(raw), geometry_input_bytes=len(interval._json)),
        elapsed_seconds=elapsed, physical_bytes=size, logical_identities=logical, observations=observations)
    case.tearDown()
    result['reserved_after_close'] = budget.reserved_bytes
    return result


if __name__ == '__main__':
    result = run(sys.argv[1])
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result), flush=True)
