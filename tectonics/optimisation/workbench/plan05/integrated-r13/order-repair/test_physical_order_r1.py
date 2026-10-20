"""Bounded actual-native ordering controls; root executes through its queue.

Small manufactured LOW/full-forward solves and native ownership fault controls.
No W4 CONTROL, worker processes or scientific pair.
"""
from concurrent.futures import CancelledError
from contextlib import ExitStack, contextmanager
from fractions import Fraction
from hashlib import sha256
import gc
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
ARM = os.environ.get("PLAN05_ORDER_TEST_LAYOUT", "lf3")
if ARM not in ("lf3", "lh"):
    raise ValueError("Exactly one selected native test layout required")
LAYOUT = T / "hs" / ARM
sys.path[:0] = json.loads((LAYOUT / "control.json").read_text(encoding="utf8"))["paths"]
sys.path.insert(0, str(HERE))

import private_heat_physical_order_r1 as ORDER
import private_heat_low_solver_kernel_r5 as LOW
import private_heat_geometry_inventory_r3 as GEOMETRY
import private_heat_decimal_sparse_core_r1 as P
import private_heat_gmp_resources_r1 as R
from atlas_tectonics.resources import WorkBudget, MemoryLimitError
from atlas_tectonics import exact_arithmetic


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepared_fixture(order):
    """Nonconstant seven-cell rational network, same physical edge sequence."""
    G = exact_arithmetic.library()
    n = len(order)
    inverse = {physical: at for at, physical in enumerate(order)}
    edges = [(i, i+1) for i in range(n-1)] + [(0, 3), (1, 5), (2, 6)]
    rows = []
    for f, (left, right) in enumerate(edges):
        i, j = inverse[left], inverse[right]
        k = Fraction(11+f, 7+2*f)
        owners = sorted(((i, 1), (j, -1)))
        weights = [(("cell", i), G.mpq(k.numerator, k.denominator)),
                   (("cell", j), G.mpq(-k.numerator, k.denominator))]
        rows.append(dict(face_id=f"face-{f}", owners=owners, kind="interior",
                         weights=weights, conductance=k,
                         owner_normal_distances=[Fraction(1), Fraction(1)]))
    capacity = [float(Fraction(17+3*i, 13)) for i in order]
    old = [float(Fraction(17+3*i, 13))*float(Fraction(23+2*i, 17)) for i in order]
    source = [0.] * n
    prepared = dict(rows=rows, boundary={}, conductivity=[Fraction(1)]*n,
                    cells=n, face_ids=[row["face_id"] for row in rows], geometry_id="1"*64)
    payload = dict(cells=[{"cell_id": f"cell-{i}"} for i in order],
                   faces=[{"face_id": row["face_id"]} for row in rows])
    keys = [("physical", f"{i:064x}") for i in order]
    return prepared, payload, keys, old, capacity, source


def physical_result(value, original_order):
    energy = [None] * len(original_order)
    residual = [None] * len(original_order)
    for at, physical in enumerate(original_order):
        energy[physical] = value["energy"][at]
        residual[physical] = value["residual_exact"][at]
    # The original row's first owner may reverse; restore physical orientation.
    faces = []
    for i, j, amount in value["faces"]:
        a, b = original_order[i], original_order[j]
        faces.append((a, b, amount) if a < b else (b, a, -amount))
    return energy, residual, faces


def cube_record(order):
    """Three exact unit cubes with complete physical incidences and support."""
    import mesh_tables as MT
    def q(value):
        value = Fraction(value)
        return [hex(value.numerator), hex(value.denominator)]
    def xyz(values):
        return [q(v) for v in values]
    cells, faces, voxels = [], [], {}
    for i in range(3):
        voxel = dict(lower_m=xyz((i, 0, 0)), upper_m=xyz((i+1, 1, 1)))
        vid = digest(voxel)
        voxels[vid] = voxel
        cid = digest(dict(kind="collar", funding_id="1"*64, cell_id=vid))
        cells.append(dict(kind="collar", index=[i, 0, 0], cell_id=cid,
                          logical_cell_id=cid, physical_cell_id=vid,
                          physical_support=dict(voxel_id=vid), volume_m3=q(1),
                          centroid_m=xyz((Fraction(2*i+1, 2), Fraction(1, 2), Fraction(1, 2))),
                          faces=[]))
    specs = [(0, p, None) for p in range(4)]
    specs += [(axis, end, i) for i in range(3) for axis in (1, 2) for end in (0, 1)]
    for axis, plane, cell in specs:
        fid = digest([axis, plane, cell])
        linked = ([(i, sign) for i, sign in ((plane-1, 1), (plane, -1)) if 0 <= i < 3]
                  if axis == 0 else [(cell, 1 if plane else -1)])
        centre = [Fraction(1, 2)] * 3
        centre[0] = Fraction(plane) if axis == 0 else Fraction(2*cell+1, 2)
        centre[axis] = Fraction(plane)
        normal = [0, 0, 0]
        normal[axis] = 1
        # Positive-axis polygon orientation, right-handed tangent pair.
        a, b = ((1, 2), (2, 0), (0, 1))[axis]
        vertices = []
        for u, v in ((0, 0), (1, 0), (1, 1), (0, 1)):
            point = list(centre)
            point[a] += Fraction(2*u-1, 2)
            point[b] += Fraction(2*v-1, 2)
            vertices.append(xyz(point))
        for i, sign in linked:
            cells[i]["faces"].append([fid, sign])
        faces.append(dict(face_id=fid, owners=[cells[i]["cell_id"] for i, _ in linked],
                          centroid_m=xyz(centre), area_vector_m2=xyz(normal), vertices_m=vertices,
                          kind="interior" if len(linked) == 2 else "boundary", geometry_kind="cartesian"))
    return dict(schema=MT.LEGACY, method=MT.METHOD, funding_id="1"*64, source={},
                support_id="2"*64, trajectory_id=digest([]), trajectory_segments=[],
                endpoint="end", time_s=q(1), grid_id="3"*64,
                grid_lines=[[q(i) for i in range(4)], [q(0), q(1)], [q(0), q(1)]],
                cells=[cells[i] for i in order], faces=faces,
                support_tables=dict(voxels=voxels, radial_layers={}, cones={}))


def block_record():
    """Eight unit cubes; 8 centres + 24 wall centres span the cubic basis."""
    def q(value):
        value = Fraction(value)
        return [hex(value.numerator), hex(value.denominator)]
    def xyz(values):
        return [q(value) for value in values]
    record = cube_record((0, 1, 2))
    cells, faces, voxels = {}, [], {}
    coordinates = [(x, y, z) for x in range(2) for y in range(2) for z in range(2)]
    for index in coordinates:
        voxel = dict(lower_m=xyz(index), upper_m=xyz(v+1 for v in index))
        vid = digest(voxel)
        voxels[vid] = voxel
        cid = digest(dict(kind="collar", funding_id="1"*64, cell_id=vid))
        cells[index] = dict(kind="collar", index=list(index), cell_id=cid,
            logical_cell_id=cid, physical_cell_id=vid, physical_support=dict(voxel_id=vid),
            volume_m3=q(1), centroid_m=xyz(Fraction(2*v+1, 2) for v in index), faces=[])
    for axis in range(3):
        a, b = ((1, 2), (2, 0), (0, 1))[axis]
        for plane in range(3):
            for u in range(2):
                for v in range(2):
                    centre = [None] * 3
                    centre[axis], centre[a], centre[b] = plane, Fraction(2*u+1, 2), Fraction(2*v+1, 2)
                    normal = [0, 0, 0]
                    normal[axis] = 1
                    linked = []
                    for at, sign in ((plane-1, 1), (plane, -1)):
                        if 0 <= at < 2:
                            index = [None] * 3
                            index[axis], index[a], index[b] = at, u, v
                            linked.append((tuple(index), sign))
                    fid = digest(["block", axis, plane, u, v])
                    vertices = []
                    for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        point = list(centre)
                        point[a] += Fraction(2*du-1, 2)
                        point[b] += Fraction(2*dv-1, 2)
                        vertices.append(xyz(point))
                    for index, sign in linked:
                        cells[index]["faces"].append([fid, sign])
                    faces.append(dict(face_id=fid, owners=[cells[index]["cell_id"] for index, _ in linked],
                        centroid_m=xyz(centre), area_vector_m2=xyz(normal), vertices_m=vertices,
                        kind="interior" if len(linked) == 2 else "boundary", geometry_kind="cartesian"))
    # Deliberately noncanonical public order; physical annotations are unchanged.
    record.update(cells=[cells[coordinates[i]] for i in (6, 1, 4, 3, 0, 7, 2, 5)],
        faces=faces, grid_lines=[[q(0), q(1), q(2)] for _ in range(3)],
        support_tables=dict(voxels=voxels, radial_layers={}, cones={}))
    return record


@contextmanager
def native_cube(budget):
    """Actual native owners; catch injected faults inside this caller scope."""
    import mesh_tables as MT
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    with budget.reserve(2 << 20, category="order-fault-fixture"):
        record, blobs = cube_record((2, 0, 1)), {}
        metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
        view = MT.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
                              expected_geometry_id=digest(record), budget=budget)
        geometry = MimeticGeometry.from_compact(view, budget=budget)
        boundary = {f["face_id"]: ("power", 0.) for f in record["faces"] if len(f["owners"]) == 1}
        with GEOMETRY.prepare(geometry, Fraction(1), boundary, budget=budget) as startup:
            yield geometry, startup, [1.75, 1.25, 1.5], [1.]*3, [0.]*3


def captured_failure(operation):
    """Unlike assertRaises, retain the original exception's complete traceback."""
    try:
        operation()
    except BaseException as error:
        return error, error.__traceback__
    raise AssertionError("Injected native-boundary failure did not happen")


def positive_frame_local(trace, code, name):
    """Inspect one known failing frame, never infer release from a negative scan."""
    while trace is not None:
        if trace.tb_frame.f_code is code:
            return trace.tb_frame.f_locals[name]
        trace = trace.tb_next
    raise AssertionError("The expected concrete owner-bearing frame is absent")


class PhysicalOrder(unittest.TestCase):
    def test_native_low_permutation_failure_and_canonical_exact_repair(self):
        budget = WorkBudget(256 << 20)
        orders = (tuple(range(7)), tuple(reversed(range(7))), (3, 0, 6, 2, 5, 1, 4))
        before, after = [], []
        with ExitStack() as stack:
            # Fixture-created graphs and result-view pointer containers retained
            # here; all numerical producer graphs retain their native owners.
            stack.enter_context(budget.reserve(4 << 20, category="order-regression-fixture"))
            for original_order in orders:
                prepared, payload, keys, old, capacity, source = prepared_fixture(original_order)
                plain = stack.enter_context(LOW.solve(prepared, old, capacity, .1, source,
                    target="1e-24", budget=budget))
                before.append(physical_result(plain.value, original_order))
                scratch = stack.enter_context(R.OwnedWorkspace(
                    budget, ORDER._inventory(7, len(prepared["rows"]), 2*len(prepared["rows"])),
                    category="order-regression-scratch"))
                canonical, inverse = ORDER._permutation(keys, None)
                mapped, _, _ = ORDER._prepared_copy(prepared, payload, canonical, inverse, None)
                fixed = stack.enter_context(LOW.solve(mapped, [old[i] for i in canonical],
                    [capacity[i] for i in canonical], .1, [source[i] for i in canonical],
                    target="1e-24", budget=budget))
                after.append(physical_result(fixed.value, [original_order[i] for i in canonical]))
                self.assertGreater(scratch.lease.count, 0)
            self.assertTrue(any(value != before[0] for value in before[1:]),
                            "Fixture must demonstrate the native exact ordering failure")
            self.assertTrue(all(value == after[0] for value in after[1:]),
                            "Canonical inputs must give EXACT native energy/residual/face equality")
            # Drop borrowed exact-result aliases before the producer stack exits.
            before.clear()
            after.clear()
        del before, after, plain, fixed, scratch
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_compact_metric_prepare_and_input_owner_lifetime(self):
        import mesh_tables as MT
        from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
        budget = WorkBudget(256 << 20)
        with budget.reserve(2 << 20, category="order-cube-fixture"):
            record = cube_record((2, 0, 1))
            blobs = {}
            metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
            view = MT.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
                                  expected_geometry_id=digest(record), budget=budget)
            geometry = MimeticGeometry.from_compact(view, budget=budget)
            boundary = {face["face_id"]: ("power", 0.) for face in record["faces"] if len(face["owners"]) == 1}
            old, capacity, source = [1.75, 1.25, 1.5], [1.]*3, [0.]*3
            with GEOMETRY.prepare(geometry, Fraction(1), boundary, budget=budget) as startup:
                before = budget.reserved_bytes
                with ORDER.prepare(geometry, startup, old, capacity, source, budget=budget) as ordered:
                    value = ordered.value
                    self.assertEqual(value["keys"], [ORDER._physical_key(row.value) for row in value["native_rows"]])
                    self.assertEqual(value["old"], [old[i] for i in value["canonical_to_original"]])
                    self.assertIs(value["startup_owner"], startup)
                    self.assertGreater(budget.reserved_bytes, before)
                    self.assertEqual([row["cell_id"] for row in record["cells"]],
                                     [view.cell_id(i) for i in range(3)])
                    value = None
                self.assertEqual(budget.reserved_bytes, before)
            geometry = view = arrays = metadata = record = blobs = None
        self.assertEqual(budget.reserved_bytes, 0)

    def test_inverse_map_restores_cells_and_exact_original_owner_order(self):
        budget = WorkBudget(1 << 20)
        with R.OwnedWorkspace(budget, 65536, category="order-inverse-fixture"):
            order = [2, 0, 1]
            incidence = [((0, 1), (2, -1)), ((1, -1),)]
            predictor = dict(energy=[30, 10, 20], evidence=dict(
                absolute_target_decimal="1e-24",
                raw_outward_energy_decimal=[[(0, -1, "-7"), (1, 1, "7")], [(2, -1, "11")]]))
            result = ORDER._finish_view(predictor, order, incidence, None)
            self.assertEqual(result["energy"], [10, 20, 30])
            self.assertEqual(result["evidence"]["raw_outward_energy_decimal"],
                             [[(0, 1, "7"), (2, -1, "-7")], [(1, -1, "11")]])
            result = None

    def test_cancel_after_one_native_row_preserves_exact_exception_and_funding(self):
        import mesh_tables as MT
        budget = WorkBudget(256 << 20)
        with native_cube(budget) as (geometry, startup, old, capacity, source):
            baseline = budget.reserved_bytes
            primary = CancelledError("cancel after one actual native row")
            acquired = 0
            native_cell = MT.CompactMesh.cell
            def cell(view, index):
                nonlocal acquired
                row = native_cell(view, index)
                acquired += 1
                return row
            def cancelled():
                if acquired == 1:
                    raise primary
                return False
            with patch.object(MT.CompactMesh, "cell", cell):
                error, trace = captured_failure(lambda: ORDER.prepare(
                    geometry, startup, old, capacity, source, budget=budget, cancel=cancelled))
            self.assertIs(error, primary)
            self.assertEqual(acquired, 1)
            rows = positive_frame_local(trace, ORDER.prepare.__code__, "native_rows")
            work = positive_frame_local(trace, ORDER.prepare.__code__, "work")
            self.assertIs(type(rows[0]), MT.OwnedRow)
            self.assertIsNone(rows[1])
            self.assertIsNone(rows[2])
            self.assertEqual(rows[0].value["cell_id"], geometry._indexed.cell_id(0))
            self.assertEqual(work.lease.count, work.count)
            retained = budget.reserved_bytes
            self.assertGreaterEqual(retained-baseline, work.count+rows[0]._owner.size)
            failure_id = error.physical_order_failure_id
            escaped = rows[0].value["centroid_m"]
            rows = work = None
            error.__traceback__ = None
            error = primary = trace = None
            gc.collect()
            self.assertEqual(budget.reserved_bytes, retained,
                             "Registered failure owner must outlive caller exception/traceback references")
            self.assertEqual(len(escaped), 3)
            self.assertEqual([r["failure_id"] for r in ORDER.retained_failures()], [failure_id])
            with self.assertRaisesRegex(ValueError, "Explicit acknowledgement"):
                ORDER.release_failure(failure_id)
            self.assertEqual(budget.reserved_bytes, retained)
            escaped = None
            ORDER.release_failure(failure_id, acknowledge_no_borrows=True)
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
        geometry = startup = old = capacity = source = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_partial_native_row_allocation_failure_retains_both_native_owners(self):
        import mesh_tables as MT
        budget = WorkBudget(256 << 20)
        with native_cube(budget) as (geometry, startup, old, capacity, source):
            baseline = budget.reserved_bytes
            primary = MemoryError("native row decoding allocation fault")
            calls = 0
            native_tag = MT.CompactMesh._tag
            def tag(view, index):
                nonlocal calls
                value = native_tag(view, index)
                calls += 1
                if calls == 2:
                    raise primary
                return value
            with patch.object(MT.CompactMesh, "_tag", tag):
                error, trace = captured_failure(lambda: ORDER.prepare(
                    geometry, startup, old, capacity, source, budget=budget))
            self.assertIs(error, primary)
            self.assertEqual(calls, 2)
            rows = positive_frame_local(trace, ORDER.prepare.__code__, "native_rows")
            partial = positive_frame_local(trace, MT.CompactMesh.cell.__code__, "owner")
            work = positive_frame_local(trace, ORDER.prepare.__code__, "work")
            self.assertIs(type(rows[0]), MT.OwnedRow)
            self.assertIsNone(rows[1])
            self.assertIs(type(partial), MT._Allocation)
            self.assertIsNotNone(partial.guard)
            retained = budget.reserved_bytes
            self.assertGreaterEqual(retained-baseline, work.count+rows[0]._owner.size+partial.size)
            failure_id = error.physical_order_failure_id
            escaped = positive_frame_local(trace, tag.__code__, "value")
            first_alias = rows[0].value["centroid_m"]
            rows = partial = work = None
            error.__traceback__ = None
            error = primary = trace = None
            gc.collect()
            self.assertEqual(budget.reserved_bytes, retained)
            self.assertEqual(escaped["kind"], "collar")
            self.assertEqual(len(first_alias), 3)
            self.assertEqual([r["failure_id"] for r in ORDER.retained_failures()], [failure_id])
            escaped = first_alias = None
            ORDER.release_failure(failure_id, acknowledge_no_borrows=True)
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
        geometry = startup = old = capacity = source = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_inverse_map_allocation_failure_retains_complete_low_and_partial_high(self):
        budget = WorkBudget(256 << 20)
        with native_cube(budget) as (geometry, startup, old, capacity, source):
            with ORDER.prepare(geometry, startup, old, capacity, source, budget=budget) as ordered:
                value = ordered.value
                with LOW.solve(value["prepared"], value["old"], value["capacity"], .1,
                               value["source"], target="1e-24", budget=budget) as low:
                    baseline = budget.reserved_bytes
                    primary = MemoryError("inverse-map high dictionary allocation fault")
                    calls = 0
                    def allocate_dict(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        # LOW evidence and outer dict have completed. HIGH's
                        # actual lists exist before its evidence dict allocation.
                        if calls == 3:
                            raise primary
                        return dict(*args, **kwargs)
                    with patch.object(ORDER, "dict", allocate_dict, create=True):
                        error, trace = captured_failure(lambda: ORDER.finish_inputs(
                            ordered, low, low, budget=budget))
                    self.assertIs(error, primary)
                    self.assertEqual(calls, 3)
                    completed = positive_frame_local(trace, ORDER.finish_inputs.__code__, "low")
                    partial = positive_frame_local(trace, ORDER._finish_view.__code__, "raw")
                    work = positive_frame_local(trace, ORDER.finish_inputs.__code__, "work")
                    self.assertEqual(len(completed["energy"]), 3)
                    self.assertEqual(len(partial), 16)
                    self.assertIs(positive_frame_local(trace, ORDER.finish_inputs.__code__, "low_owner"), low)
                    retained = budget.reserved_bytes
                    self.assertEqual(retained-baseline, work.count)
                    failure_id = error.physical_order_failure_id
                    escaped_complete = completed["energy"]
                    escaped_partial = partial[0]
                    completed = partial = work = None
                    error.__traceback__ = None
                    error = primary = trace = None
                    gc.collect()
                    self.assertEqual(budget.reserved_bytes, retained)
                    self.assertEqual(len(escaped_complete), 3)
                    self.assertTrue(escaped_partial)
                    self.assertEqual([r["failure_id"] for r in ORDER.retained_failures()], [failure_id])
                    escaped_complete = escaped_partial = None
                    ORDER.release_failure(failure_id, acknowledge_no_borrows=True)
                    gc.collect()
                    self.assertEqual(budget.reserved_bytes, baseline)
                value = None
        geometry = startup = old = capacity = source = ordered = low = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_failed_control_registration_retains_admission_until_explicit_release(self):
        import mesh_tables as MT
        class UnreportableMemoryError(MemoryError):
            def __setattr__(self, name, value):
                if name == "physical_order_failure_id":
                    raise RuntimeError("secondary diagnostic publication fault")
                super().__setattr__(name, value)
        budget = WorkBudget(256 << 20)
        with native_cube(budget) as (geometry, startup, old, capacity, source):
            baseline = budget.reserved_bytes
            primary = UnreportableMemoryError("registry insertion allocation fault")
            class RefusingRegistry(dict):
                def __setitem__(self, key, value):
                    raise primary
            with patch.object(ORDER, "_operations", RefusingRegistry()):
                with patch.object(MT.CompactMesh, "cell", side_effect=AssertionError("Body ran before registration")):
                    error, trace = captured_failure(lambda: ORDER.prepare(
                        geometry, startup, old, capacity, source, budget=budget))
            self.assertIs(error, primary)
            self.assertIs(ORDER._registration.error, primary)
            self.assertIsNotNone(trace)
            self.assertIsNotNone(ORDER._registration.work)
            failure_id = ORDER.retained_failures()[0]["failure_id"]
            retained = budget.reserved_bytes
            self.assertEqual(retained-baseline, ORDER._registration.work.count)
            error.__traceback__ = None
            error = primary = trace = None
            gc.collect()
            self.assertEqual(budget.reserved_bytes, retained)
            with self.assertRaisesRegex(RuntimeError, "registration failure"):
                ORDER.prepare(geometry, startup, old, capacity, source, budget=budget)
            ORDER.release_failure(failure_id, acknowledge_no_borrows=True)
            gc.collect()
            self.assertEqual(budget.reserved_bytes, baseline)
            self.assertFalse(ORDER.retained_failures())
        geometry = startup = old = capacity = source = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_full_forward_cancel_retains_outer_native_workspace_until_explicit_release(self):
        import mesh_tables as MT
        forward = load("physical_order_cancel_forward_"+ARM,
                       HERE / ARM / "private_heat_forward_kernel_r13.py")
        # Permit the actual native process meter when its normal runtime checks
        # support this process. Cancellation happens before LOW or any worker.
        budget = WorkBudget(2 << 30)
        with native_cube(budget) as (geometry, startup, old, capacity, source):
            baseline = budget.reserved_bytes
            primary = CancelledError("full forward cancellation after ORDER row")
            acquired = 0
            native_cell = MT.CompactMesh.cell
            def cell(view, index):
                nonlocal acquired
                row = native_cell(view, index)
                if any(operation.state == "active" for operation in ORDER._operations.values()):
                    acquired += 1
                return row
            def cancelled():
                if acquired == 1:
                    raise primary
                return False
            with patch.object(MT.CompactMesh, "cell", cell):
                error, trace = captured_failure(lambda: forward.advance(
                    geometry, old, capacity, .1, source, startup.value["prepared"]["boundary"],
                    conductivity=1., absolute_residual_target="1e-24",
                    budget=budget, cancelled=cancelled))
            self.assertIs(error, primary)
            self.assertEqual(acquired, 1)
            self.assertIsNotNone(trace)
            self.assertTrue(error._integration_workspace_owners,
                            "Actual outer native orchestration must retain its failure workspace")
            failure_id = error.physical_order_failure_id
            operation = ORDER._operations[failure_id]
            self.assertIs(operation.error, error)
            escaped_row = operation.native_rows[0].value["centroid_m"]
            escaped_startup = operation.dependencies[1].value["payload"]["cells"][0]["centroid_m"]
            retained = budget.reserved_bytes
            self.assertGreater(retained, baseline)
            operation = None
            error.__traceback__ = None
            error = primary = trace = None
            gc.collect()
            self.assertEqual(budget.reserved_bytes, retained)
            self.assertEqual(len(escaped_row), 3)
            self.assertEqual(len(escaped_startup), 3)
            escaped_row = escaped_startup = None
            ORDER.release_failure(failure_id, acknowledge_no_borrows=True)
            gc.collect()
            self.assertTrue(forward.METER.settle(budget))
            self.assertEqual(budget.reserved_bytes, baseline)
            self.assertFalse(ORDER.retained_failures())
        geometry = startup = old = capacity = source = None
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_actual_full_forward_entry_eight_cell_cube(self):
        import mesh_tables as MT
        import private_heat_functionals_parallel_r1 as PARALLEL
        from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
        forward = load("physical_order_complete_forward_"+ARM,
                       HERE / ARM / "private_heat_forward_kernel_r13.py")
        budget = WorkBudget(512 << 20)
        previous_workers = PARALLEL.configure()
        PARALLEL.configure(workers=0)
        stages = []
        try:
            with budget.reserve(8 << 20, category="order-full-forward-fixture"):
                record, blobs = block_record(), {}
                metadata, arrays = MT.pack_mesh(record, support_writer=blobs.__setitem__, budget=budget)
                view = MT.CompactMesh(metadata, arrays, support_reader=lambda identity, size: blobs[identity],
                                      expected_geometry_id=digest(record), budget=budget)
                geometry = MimeticGeometry.from_compact(view, budget=budget)
                boundary = {f["face_id"]: ("temperature", 1.5)
                            for f in record["faces"] if len(f["owners"]) == 1}
                old = [1.25 + sum(c["index"])/32 for c in record["cells"]]
                capacity, source = [1.]*8, [0.]*8
                original_ids = [view.cell_id(i) for i in range(8)]
                with forward.advance(geometry, old, capacity, .1, source, boundary,
                        conductivity=1., absolute_residual_target="1e-24", budget=budget,
                        observe=stages.append) as result_owner:
                    result, info = result_owner.value
                    self.assertEqual(info["physical_scratch_order"], ORDER.POLICY)
                    self.assertTrue(info["public_cell_and_face_order_preserved"])
                    self.assertEqual(info["high_backend"], "MPFR512_PARTIAL_PIVOT_SAME_DECIMAL80_SYSTEM")
                    self.assertTrue(info["paired_global_identity"])
                    self.assertIn("solve-certified-high", stages)
                    self.assertIn("finish-conservative-ledger", stages)
                    self.assertEqual(info["reconstruction"]["total_physical_faces"], 36)
                    self.assertEqual(original_ids, [view.cell_id(i) for i in range(8)])
                    # record() checks the sealed identity and all bound sources;
                    # its new debug allocation belongs to this fixture lease.
                    issued = result.record()
                    self.assertEqual(len(issued["physical_faces"]), 36)
                    self.assertEqual(len(issued["corrected_energy_exact"]), 8)
                    self.assertTrue(issued["exact_cell_residual_target_pass"])
                    self.assertTrue(issued["projection_audit_reconciles_exactly"])
                    self.assertTrue(issued["actual_public_bounds_pass"])
                    for face, incidence in zip(issued["physical_faces"], geometry._incidence, strict=True):
                        self.assertEqual(face[:2], [incidence[0][0],
                            incidence[1][0] if len(incidence) == 2 else None])
                    face = incidence = issued = result = info = None
                geometry = view = arrays = metadata = record = blobs = None
                old = capacity = source = boundary = original_ids = None
                stages.clear()
        finally:
            PARALLEL.configure(workers=previous_workers)
        gc.collect()
        self.assertEqual(budget.reserved_bytes, 0)

    def test_wrong_incidence_duplicate_keys_and_budget_refuse(self):
        with self.assertRaisesRegex(ValueError, "unique physical"):
            ORDER._permutation([("same",), ("same",)], None)
        with self.assertRaisesRegex(ValueError, "incidence differs"):
            ORDER._finish_view(dict(energy=[1, 2], evidence=dict(
                absolute_target_decimal="1e-24", raw_outward_energy_decimal=[[(0, 1, "1")]])),
                [1, 0], [((0, 1),)], None)
        budget = WorkBudget(1)
        with self.assertRaises(MemoryLimitError):
            with R.OwnedWorkspace(budget, ORDER._inventory(3, 16, 24),
                                  category="order-admission-negative"):
                self.fail("Body ran before insufficient-budget refusal")
        self.assertEqual(budget.reserved_bytes, 0)

    def test_strict_both_source_transforms_preserve_dependency_coverage_and_h5a(self):
        build = load("physical_order_source_transform_test", HERE / "build_sources.py")
        for arm in (ARM,):
            with self.subTest(arm=arm):
                path = T / "hs" / arm / "helpers" / build.NAME
                raw = path.read_bytes()
                output = build.transform(raw, arm)
                self.assertEqual(output, (HERE / arm / build.NAME).read_bytes())
                with self.assertRaises(ValueError):
                    build.transform(raw + b"\n", arm)
                original = load("physical_order_native_forward_" + arm, path)
                overlay = load("physical_order_overlay_forward_" + arm, HERE / arm / build.NAME)
                required = set(original._SOURCES) - {str(path.resolve())}
                self.assertTrue(required <= set(overlay._SOURCES))
                self.assertIn(str(Path(ORDER.__file__).resolve()), overlay._SOURCES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
