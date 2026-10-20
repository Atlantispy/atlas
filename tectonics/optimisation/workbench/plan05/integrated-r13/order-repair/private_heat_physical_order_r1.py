"""Physical scratch ordering for the unchanged private LOW/HIGH equations.

Only the source-issued indexed collar/exterior geometry family is supported.
Native row owners and the original startup owner stay live through consumers.
New pointer/container storage is admitted before allocation. The figures below
are the existing 1024-byte native container policy, not a heap or RSS bound.
No source identity, public row order, precision or tolerance is replaced.
"""
import traceback

import private_heat_decimal_sparse_core_r1 as P
import private_heat_gmp_resources_r1 as R


POLICY = "physical-support-scratch-order-v1"
UNIT = 1024
PREPARED_FIELDS = frozenset((
    "rows", "boundary", "conductivity", "cells", "face_ids", "geometry_id"))
ROW_FIELDS = frozenset((
    "face_id", "owners", "kind", "weights", "conductance",
    "owner_normal_distances"))


class _Operation:
    """Funded operation custody, including its suspended native producer frames."""
    __slots__ = ("identity", "work", "dependencies", "native_rows", "error", "trace", "state")

    def __init__(self, work, dependencies):
        self.identity = id(self)
        self.work, self.dependencies = work, dependencies
        self.native_rows = self.error = self.trace = None
        self.state = "active"

    def fail(self, error):
        # Fixed existing slots only. The primary is kept as well as its original
        # traceback: subsequent native outer unwinding attaches its owners there.
        self.state, self.error = "failed", error
        self.trace = BaseException.__getattribute__(error, "__traceback__")
        try:
            error.physical_order_failure_id = self.identity
        except BaseException:
            pass  # diagnostic publication must never replace the primary

    def complete(self, value):
        result = P.OwnedSolve(value, self.work)
        # No body allocation/callback remains after constructing the native owner.
        self.work = self.dependencies = self.native_rows = None
        self.state = "transferred"
        del _operations[self.identity]
        return result

    def release(self):
        # Called ONLY after explicit acknowledgement that all escaped borrows
        # have been dropped. Clear these owned suspended frames while the full
        # workspace is still funded, then close that workspace.
        self.state = "releasing"
        trace, self.trace = self.trace, None
        if trace is not None:
            traceback.clear_frames(trace)
        trace = None
        self.dependencies = self.native_rows = self.error = None
        if self.work is not None:
            self.work.__exit__(None, None, None)
            self.work = None
        self.state = "released"


_operations = {}
# A pre-existing, fixed emergency slot retains admission even if allocating or
# registering the normal control owner fails. Such a failure blocks subsequent
# ORDER admission until explicit release. The native forward caller is serial.
_registration = _Operation(None, ())
_registration.state = "idle"


def _begin(work):
    # work was admitted before control/registry storage is allocated.
    _registration.work = work
    _registration.state = "registering"
    try:
        operation = _Operation(work, None)
        _operations[operation.identity] = operation
    except BaseException as error:
        _registration.fail(error)
        raise
    _registration.work = _registration.dependencies = None
    _registration.state = "idle"
    return operation


def retained_failures():
    """Caller-owned diagnostic snapshot; no release follows from absence/death."""
    values = [operation for operation in _operations.values()
              if operation.state in ("failed", "releasing")]
    if _registration.state in ("failed", "releasing"):
        values.append(_registration)
    return tuple(dict(failure_id=operation.identity, state=operation.state,
                      accounted_bytes=operation.work.lease.count if operation.work is not None else 0)
                 for operation in values)


def release_failure(identity, *, acknowledge_no_borrows=False):
    """Release only after all extracted aliases and traceback borrows are gone.

    Until then, do not clear/mutate owned traceback frames or close the input
    producers. Ordinary exception/traceback reference death releases nothing.
    Native outer owners attached to an externally retained primary may continue
    their own native lifetime after this helper's explicit release.
    """
    if acknowledge_no_borrows is not True:
        raise ValueError("Explicit acknowledgement that all escaped borrows are dropped is required")
    operation = (_registration if identity == _registration.identity
                 else _operations[identity])
    if operation.state not in ("failed", "releasing"):
        raise ValueError("Only a retained failed ORDER operation may be released")
    operation.release()
    if operation is _registration:
        operation.state = "idle"
    else:
        del _operations[identity]


def _admission_ready():
    if _registration.state != "idle":
        raise RuntimeError("Release retained ORDER registration failure before another operation")


def _check(cancel):
    # Forward passes its raising check callback; native callbacks may return bool.
    if cancel is not None and cancel():
        from concurrent.futures import CancelledError
        raise CancelledError("Physical scratch order cancelled")


def _digest(value):
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("Native physical support must have a canonical digest")
    return value


def _indices(value, count):
    if (type(value) not in (list, tuple) or len(value) != count
            or any(type(v) is not int or v < 0 for v in value)):
        raise ValueError("Native physical coordinate annotation differs")
    return tuple(value)


def _physical_key(row):
    """Use authenticated physical support references, never numerical results."""
    support = row.get("physical_support")
    if type(support) is not dict:
        raise ValueError("Native physical support is required")
    if row.get("kind") == "collar":
        if set(support) != {"voxel_id"}:
            raise ValueError("Unsupported collar support")
        voxel = _digest(support["voxel_id"])
        if row.get("physical_cell_id") != voxel:
            raise ValueError("Collar physical cell and support differ")
        return ("collar", voxel, _indices(row.get("index"), 3))
    if row.get("kind") == "exterior":
        if set(support) != {"voxel_id", "radial_layer_id", "cone_id"}:
            raise ValueError("Unsupported exterior/differential support")
        source = row.get("source_key")
        if type(source) is not list or len(source) != 2 or type(source[1]) is not int or source[1] < 0:
            raise ValueError("Native source component key required")
        band, chart = row.get("radial_band"), row.get("chart")
        if type(band) is not int or type(chart) is not int or min(band, chart) < 0:
            raise ValueError("Native radial band/chart required")
        return ("exterior", _digest(support["voxel_id"]),
                _digest(support["radial_layer_id"]), _digest(support["cone_id"]),
                _digest(source[0]), source[1],
                _indices(row.get("voxel_index"), 3), band, chart)
    raise ValueError("Unsupported physical cell family")


def _permutation(keys, cancel):
    # Caller has admitted key tables, uniqueness set and sorting workspace.
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Complete unique physical cell keys required")
    order = sorted(range(len(keys)), key=keys.__getitem__)
    inverse = [None] * len(keys)
    for new, old in enumerate(order):
        _check(cancel)
        inverse[old] = new
    return order, inverse


def _prepared_copy(prepared, payload, order, inverse, cancel):
    """Copy only containers; exact scalar and payload leaves retain their owner."""
    if set(prepared) != PREPARED_FIELDS:
        raise ValueError("Prepared LOW schema changed")
    n = len(order)
    if (prepared["cells"] != n or len(prepared["conductivity"]) != n
            or len(payload["cells"]) != n
            or len(prepared["rows"]) != len(payload["faces"])
            or len(prepared["face_ids"]) != len(payload["faces"])):
        raise ValueError("Complete prepared physical cell/face coverage required")
    rows, original_incidence = [], []
    for face_index, row in enumerate(prepared["rows"]):
        _check(cancel)
        if set(row) != ROW_FIELDS or row["face_id"] != prepared["face_ids"][face_index]:
            raise ValueError("Prepared LOW row schema/order changed")
        owners = row["owners"]
        if (not 1 <= len(owners) <= 2 or len(owners) != len(row["owner_normal_distances"])
                or any(type(i) is not int or not 0 <= i < n or sign not in (-1, 1)
                       for i, sign in owners)):
            raise ValueError("Complete original face incidence required")
        owner_order = sorted(range(len(owners)), key=lambda j: inverse[owners[j][0]])
        mapped = [(inverse[owners[j][0]], owners[j][1]) for j in owner_order]
        weights = []
        for key, value in row["weights"]:
            kind, at = key
            if kind == "cell":
                if type(at) is not int or not 0 <= at < n:
                    raise ValueError("LOW coefficient cell is outside its inventory")
                key = (kind, inverse[at])
            elif kind not in ("wall", "power") or at != row["face_id"]:
                raise ValueError("Unknown LOW coefficient key")
            weights.append((key, value))
        weights.sort(key=lambda item: item[0])
        rows.append(dict(row, owners=mapped, weights=weights,
                         owner_normal_distances=[row["owner_normal_distances"][j] for j in owner_order]))
        original_incidence.append(tuple(owners))
    result = dict(prepared, rows=rows,
                  conductivity=[prepared["conductivity"][i] for i in order])
    projected = dict(cells=[payload["cells"][i] for i in order], faces=payload["faces"])
    return result, projected, original_incidence


def _inventory(n, nf, weights):
    if any(type(v) is not int or v < 0 for v in (n, nf, weights)):
        raise ValueError("Bounded scratch dimensions required")
    # Per cell: key tuple/nested index tuples, 2 permutation tables, sorting
    # workspace/set, three input lists/scalars, conductivity and payload pointers.
    # Per face: copied row, owner/order/distance containers and original incidence.
    # Per weight: pair and (possibly rewritten) observation key. Exact numerical
    # leaves remain borrowed from the still-live startup producer.
    return 65536 + UNIT * (32*n + 32*nf + 8*weights + 32)


def prepare(geometry, startup_owner, old, capacity, source, *, budget, cancel=None):
    """Actual native metric -> owned canonical scratch; no public mesh mutation.

    The caller MUST keep startup_owner open until this owner and all consumers
    close. The forward transform does so on its existing work stack. Borrowed
    input arrays are also caller-owned for the complete forward invocation.
    """
    _admission_ready()
    from atlas_tectonics.integration_mimetic_heat import MimeticGeometry
    from mesh_tables import CompactMesh
    if (type(geometry) is not MimeticGeometry
            or type(getattr(geometry, "_indexed", None)) is not CompactMesh
            or geometry._budget is not budget or geometry._indexed.budget is not budget):
        raise TypeError("Actual indexed native metric and shared budget required")
    startup = startup_owner.value
    prepared, payload = startup["prepared"], startup["payload"]
    view, n, nf = geometry._indexed, len(geometry._cells), len(geometry._face_ids)
    if not (len(old) == len(capacity) == len(source) == n == view.cell_count
            and nf == view.face_count):
        raise ValueError("Complete original input coverage required")
    weights = sum(len(row["weights"]) for row in prepared["rows"])
    work = R.OwnedWorkspace(budget, _inventory(n, nf, weights),
                           category="heat-physical-scratch-order", cancelled=cancel)
    work.__enter__()
    custody = _begin(work)
    try:
        custody.dependencies = (geometry, startup_owner, old, capacity, source)
        # Retain wrappers, not just their values. This also funds key strings.
        native_rows = [None] * n
        custody.native_rows = native_rows
        keys = [None] * n
        for i in range(n):
            _check(cancel)
            native_rows[i] = view.cell(i)
            row = native_rows[i].value
            if row["cell_id"] != payload["cells"][i]["cell_id"]:
                raise ValueError("Native physical and numerical row alignment changed")
            keys[i] = _physical_key(row)
        order, inverse = _permutation(keys, cancel)
        mapped, projected, incidence = _prepared_copy(prepared, payload, order, inverse, cancel)
        value = dict(policy=POLICY, prepared=mapped, payload=projected,
                     old=[old[i] for i in order], capacity=[capacity[i] for i in order],
                     source=[source[i] for i in order], canonical_to_original=order,
                     original_to_canonical=inverse, original_incidence=incidence,
                     original_inputs=(old, capacity, source), keys=keys,
                     native_rows=native_rows, startup_owner=startup_owner)
        _check(cancel)
        return custody.complete(value)
    except BaseException as error:
        custody.fail(error)
        raise


def _finish_view(predictor, order, incidence, cancel):
    """Only the fields FINISH actually consumes; restore every consumed axis."""
    n = len(order)
    if len(predictor["energy"]) != n:
        raise ValueError("Predictor energy coverage changed")
    energy = [None] * n
    for new, old in enumerate(order):
        energy[old] = predictor["energy"][new]
    original = predictor["evidence"]["raw_outward_energy_decimal"]
    if len(original) != len(incidence):
        raise ValueError("Predictor face coverage changed")
    raw = []
    for face, expected in zip(original, incidence, strict=True):
        _check(cancel)
        if len(face) != len(expected):
            raise ValueError("Predictor incidence count changed")
        mapped = {}
        for at, sign, amount in face:
            if type(at) is not int or not 0 <= at < n or sign not in (-1, 1):
                raise ValueError("Predictor incidence lies outside original cells")
            key = (order[at], sign)
            if key in mapped:
                raise ValueError("Duplicate predictor owner")
            mapped[key] = amount
        if set(mapped) != set(expected):
            raise ValueError("Predictor incidence differs from original metric")
        raw.append([(at, sign, mapped[at, sign]) for at, sign in expected])
    return dict(energy=energy, evidence=dict(
        absolute_target_decimal=predictor["evidence"]["absolute_target_decimal"],
        raw_outward_energy_decimal=raw))


def finish_inputs(order_owner, low_owner, high_owner, *, budget, cancel=None):
    """Fund inverse-map containers while retaining both complete predictors."""
    _admission_ready()
    value = order_owner.value
    order, incidence = value["canonical_to_original"], value["original_incidence"]
    work = R.OwnedWorkspace(budget, 65536 + UNIT*(8*len(order)+32*len(incidence)+32),
                           category="heat-original-order-finish-inputs", cancelled=cancel)
    work.__enter__()
    custody = _begin(work)
    try:
        custody.dependencies = (order_owner, low_owner, high_owner)
        low = _finish_view(low_owner.value, order, incidence, cancel)
        high = _finish_view(high_owner.value, order, incidence, cancel)
        _check(cancel)
        return custody.complete(dict(low=low, high=high,
                                     dependencies=(order_owner, low_owner, high_owner)))
    except BaseException as error:
        custody.fail(error)
        raise
