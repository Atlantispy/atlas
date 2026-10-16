"""One genuine W4 owner/transport call on a fresh compact mesh and r13 issuer.

This checks the heat result and its checkpoint roundtrip; WP8 owns joined
advance/commit/cold run integration. The common-rigid fixture has no differential partition owner, so
its freshly packed mesh uses the explicit in-memory compact compatibility path.
"""
import ast
from contextlib import contextmanager
from fractions import Fraction as Q
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
T = HERE.parents[4]
H = HERE.parents[3]/'heat-repair-20261007'
FIXTURE = HERE.parent/'composed-checks/w4_owner_heat_child.py'
FIXTURE_SHA = '5a850e22790e23b25dbaa8ce99ead91e7eef264c9251d38110c8293f30ddfabb'
BUDGET_BYTES = 6 << 30


def phase(name):
    print(name, flush=True)


def owner_check(paths):
    sys.path[:0] = paths
    raw = FIXTURE.read_bytes()
    if sha256(raw).hexdigest() != FIXTURE_SHA:
        raise ValueError('original W4 fixture changed')
    text = raw.decode('utf8')
    tree = ast.parse(text)
    selected = []
    for name in ('funded_collar_fixture', 'actual_spatial_fixture'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        selected.append('@contextmanager\n'+ast.get_source_segment(text, node))
    # Select the two authentic fixture producers without executing the old
    # frozen-composition driver, monkeypatches, polling or diagnostic fallbacks.
    fixtures = dict(contextmanager=contextmanager, Q=Q, BUDGET_BYTES=BUDGET_BYTES)
    exec(compile('\n\n'.join(selected), str(FIXTURE), 'exec'), fixtures)
    import private_heat_native_issuer_r13 as I
    import private_heat_joined_consumer_r6 as J
    import private_heat_checkpoint_consumer_r10 as CAS
    import test_i04_spatial_workflow as FLOW
    import mesh_tables as MT
    from atlas_tectonics.integration_exterior_mesh import ExteriorMesh
    from content_cache import create_retained_scope
    from heat_ledger_tables import CompactHeatSnapshot
    from compact_contracts import SegmentRef
    from interval_store_set import IntervalStoreSet
    from threadpoolctl import threadpool_limits
    started = time.perf_counter()
    phase('actual source, funding and collar')
    with threadpool_limits(1), fixtures['actual_spatial_fixture']() as case:
        budget, collar, funding = (case[k] for k in ('budget', 'collar', 'funding'))
        phase('actual initial thermal mesh and spatial owner')
        initial_mesh = FLOW.thermal_mesh(case, case['wall'], 'start')
        with FLOW.PreparedSpatialOwner(funding, collar, case['bounds'], initial_mesh,
                method='implicit-upwind', max_projection_errors=FLOW.allowances(case), budget=budget,
                heat_method=J.METHOD) as owner:
            scope = create_retained_scope(budget, process_epoch='step7-owner-heat-fixture')
            owner._record_scope = scope
            parent = collar.initial_state_from_funding(funding, case['owner'])
            route = SimpleNamespace(exterior_state=owner.initial_state,
                source_flow_stage=lambda duration, _parent=parent, **kw: collar.source_flow_stage(_parent, duration, **kw))
            phase('next genuine source, geometry and transport')
            source, bounds, mesh, wall = FLOW.next_interval(case, route)
            graph = owner.close_graph(owner.initial_state, source, bounds)
            step = owner.transport(owner.initial_state, source, graph)
            record = mesh.record()
            boundary = {row['face_id']: ('power', 0.) for row in record['faces'] if len(row['owners']) == 1}
            blobs = {}
            metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
            view = MT.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
                expected_geometry_id=mesh.geometry_id, budget=budget)
            compact = ExteriorMesh.from_compact(view, budget=budget)
            del record, arrays, metadata
            phase('fresh compact owner bind and r13 advance')
            with I.ExecutionContext('scipy') as execution:
                call = I.bind_owner_call(owner, step, compact, boundary=boundary,
                    absolute_residual_target='1e-24', execution=execution)
                result = I.advance(call)
                assert not call._fixture
                assert call._origin_objects[0] is owner and call._origin_objects[1] is step
                assert compact.is_compact and call._geometry._encoded is None
                assert type(result._snapshot) is CompactHeatSnapshot
                assert I._snapshot_identity(result._snapshot, budget) == result.result_id
                with result._snapshot.field('genuine_forward_origin') as origin:
                    assert origin.value is True
                with result._snapshot.field('production_acceptance') as acceptance:
                    assert acceptance.value is False
                phase('same genuine result r10 validation, save and sealed restore')
                with tempfile.TemporaryDirectory(prefix='step7-owner-ledger-', dir=T/'_t') as directory:
                    stores = IntervalStoreSet.create_migration(str(Path(directory)/'catalog.json'),
                        workflow_id='a'*64, scope=scope)
                    candidate = stores.begin_interval(None, producer_identity='b'*64, runtime_identity='c'*64)
                    receipt = CAS.save(candidate, result, call)
                    reference = SegmentRef.from_wire(receipt['metadata']['ledger'])
                    stores.promote(candidate.seal(reference), expected_catalog_digest=stores.catalog_digest)
                    with CAS.restore(stores, receipt, call, expected_result_id=result.result_id) as restored:
                        assert restored.value.result_id == result.result_id
                        assert restored.value.fixture_only is False
                        restored.value.validate_live_call()
                        for name in result.array_names:
                            assert restored.value.array(name).tobytes() == result.array(name).tobytes()
                    checkpoint = dict(schema=receipt['metadata']['schema'], result_id=result.result_id,
                        metadata_sha256=receipt['metadata']['metadata_sha256'],
                        sealed_restore_exact_arrays=True, fixture_only=False)
                    candidate.close(); stores.close()
                    del restored, candidate, stores
                output = dict(status='PASS', scope='genuine W4 owner compact heat packaging only',
                    elapsed_seconds=time.perf_counter()-started,
                    native_cells=list(collar._native.cells), collar_cells=list(collar.cells),
                    cell_count=view.cell_count, face_count=view.face_count,
                    actual_owner=type(owner).__name__, actual_transport=type(step).__name__,
                    result_id=result.result_id, metadata_sha256=result._snapshot.metadata_identity.sha256,
                    metadata_bytes=result._snapshot.metadata_identity.canonical_bytes,
                    genuine_forward_origin=True, fixture_only=False, production_acceptance=False,
                    numerical_kernel_sha256=sha256(Path(I.F.__file__).read_bytes()).hexdigest(),
                    issuer_sha256=sha256(Path(I.__file__).read_bytes()).hexdigest(),
                    checkpoint=checkpoint,
                    mesh='fresh in-memory compact columns; no differential partition on this fixture',
                    arrays={name: dict(shape=list(result.array(name).shape),
                        sha256=sha256(result.array(name).tobytes()).hexdigest()) for name in result.array_names},
                    source_fixture_sha256=FIXTURE_SHA)
                result._snapshot.close()
                del result, call
            del route, parent, step, source, bounds, graph, compact, view, mesh, wall
            scope.close()
            output['retained_reserved_bytes_after_close'] = scope.retained_budget.reserved_bytes
            assert output['retained_reserved_bytes_after_close'] == 0
        del initial_mesh
    phase('owner heat check completed')
    return output


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        result = owner_check(json.loads(sys.argv[2]))
        Path(sys.argv[3]).write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
        return
    import test_step7_bundle as B
    with tempfile.TemporaryDirectory(prefix='step7-owner-', dir=T/'_t') as directory:
        root, helpers, ram, _ = B.write_layout(directory)
        paths = [str(root), str(helpers), str(ram), str(H/'source/tectonics/tests')]
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent/'test-results/step7-owner-heat-final.json'
        environment = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1',
                           TMP=str(T/'_t'), TEMP=str(T/'_t'))
        subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--child', json.dumps(paths),
                        str(output)], cwd=directory, env=environment, check=True, timeout=900)
        print(output, flush=True)


if __name__ == '__main__':
    main()
