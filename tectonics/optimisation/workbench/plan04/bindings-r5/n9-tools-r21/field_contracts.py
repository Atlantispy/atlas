"""D01 quantity contracts. No runtime import, source repin, or readiness change.

The caller supplies independently verified evidence, never the contract's own
assertions as evidence. Hashes establish identity, not the truth of a claim.
Compare a complete declared quantity before walking its component leaves.
"""
from fractions import Fraction
import hashlib
import json
import math
import re
import struct
import copy
from pathlib import PurePosixPath

SCHEMA = "atlas.private.n9-field-contract.v3"
DEVIATION = "geometry_volume_max_deviation_m3"
WIDTH = "max_geometry_volume_error_m3"
MESH_SCHEMA = "atlas.source-bound-exterior-thermal-mesh.v1"
MAX_INTEGER_BITS = 8_388_608
HEX = re.compile(r"-?0x[0-9a-fA-F]+\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
E_SOURCE = "d338238e1abe11db8e01a4b4ee91f99443727fb082f9d9cb6799344e82d445f4"
M_SOURCE = "ab0f31f8231a792df45c0016c090496180abe4847ab0194491f6910125dd8138"
E_ROUNDED = "4b5b11c46d5602ab20ad46a2401ef3c34f64e281d86cdf9c1efd127e3f22840d"
M_ROUNDED = "bfe89a0e5f9cfcc3135f2f6910c5f22526d2eb462f88bc034dbdcc9c1eea241e"
# Historical exact sources inspected for the E/M total derivation. A selected
# successor must be reviewed and added explicitly, never accepted by basename.
HEADER_PRODUCERS = {
    ("integration_exterior_mesh.py", E_SOURCE): "E",
    ("integration_differential_mesh.py", M_SOURCE): "M",
    ("integration_exterior_mesh.py", E_ROUNDED): "E",
    ("integration_differential_mesh.py", M_ROUNDED): "M",
}
# Source-proved E pose rows. Both reviewed E builders store
# representative_quaternion and pose_operator_error_bound (= 4*e) from one
# _representative_pose(trajectory_segments, goal) call; goal depends only on the
# stored width and the funding/sphere source. For identical invocation inputs,
# E_SOURCE -> E_ROUNDED rounds after each nonzero-delta segment by quantum <=
# 2**-12*delta, so |q_after-q_before|_2 <= 2**-12*e_before (quaternion norms
# multiply; |q_seg| <= 1+delta) and e_before <= e_after < (1+2**-11)*e_before.
E_POSE_FIELDS = ("representative_quaternion", "pose_operator_error_bound")
E_QUAT_PROOF = "E-b-quat-cross-arm-r1"
E_RADIUS_PROOF = "E-b-quat-radius-growth-r1"
E_INVOCATION_INPUTS = ("trajectory_id", "trajectory_segments", "endpoint", WIDTH, "funding_id", "source")
W_SOURCE = "d6b7d472246af0e8a9415b01465f035c0c860c7b358126fd1bba5c0025e671e0"
W_ROUNDED = "a7a7dc432a45439aa47d912fd6d1424be7f7c1081d03bd079aa075be6550ebef"
# The reviewed differential geometry source. The rows on the W transform rest on its lines (DG:550-551,
# DG:711-736, DG:3047), so DesignRows takes DG as 'identical' only at this pin in both arms.
DG_SOURCE = "a680b479b9dcc8414b43bcf331c6b6d84bf7c20c6226e95e0f2df9806de56e7a"
# The proof covers E_SOURCE -> E_ROUNDED with every other selected module unchanged, apart from the
# reviewed width transforms, matched by canonical key and exact pins. E's producer reads W._decode,
# which the W transform leaves unchanged, and on the width arm the new W rounding helpers, which the
# proof executed from the pinned W_ROUNDED. The differential mesh is outside E's import closure on
# r4; this module cannot see closures, so field_provenance withdraws the relation if a selection
# brings it inside.
TRANSFORMS = frozenset({("atlas_tectonics/integration_wall_measures.py", W_SOURCE, W_ROUNDED),
                        ("atlas_tectonics/integration_exterior_mesh.py", E_SOURCE, E_ROUNDED),
                        ("atlas_tectonics/integration_differential_mesh.py", M_SOURCE, M_ROUNDED)})


def transforms_only(source_pins):
    """True when the two arms' selected inventories differ only by reviewed width transforms."""
    before, after = (source_pins.get(arm, {}) for arm in ("before", "after"))
    for path in set(before) | set(after):
        pins = before.get(path), after.get(path)
        if pins[0] != pins[1] and (path, *pins) not in TRANSFORMS:
            return False
    return True


class ContractError(ValueError):
    """Malformed or contradicted source/contract identity (FAIL, not REVIEW)."""


def need(condition, message):
    if not condition:
        raise ContractError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def identical(x, y):
    """Canonical-JSON equality: exact and type-strict (5 and 5.0, 0.0 and -0.0, 1 and True all differ)."""
    return digest(x) == digest(y)


WALK_HEX = re.compile(r"-?0x[0-9a-f]+\Z")     # the comparator walk's hex-integer leaf


def _walk_rational(value):
    return (type(value) is list and len(value) == 2 and all(type(v) is str and WALK_HEX.match(v) for v in value)
            and int(value[1], 16) > 0)


def encoded_alike(x, y):
    """True only when the comparator's type-strict field walk would see no label or structure change from x
    to y: the same JSON types, list lengths, key sets and rational form throughout, equal strings unless both
    are hex integers, equal booleans, and one sign for a pair of zeros. Numbers may differ in value. Lists
    are compared position by position: where the walk pairs a keyed list by key, a reordered list can be
    alike here yet show label changes in the walk. Exclusions use it only on fields the settled rows
    exclude."""
    if type(x) is not type(y):
        return False
    if type(x) is float:
        return not (x == y == 0.0 and math.copysign(1.0, x) != math.copysign(1.0, y))
    if type(x) is str:
        return x == y or bool(WALK_HEX.match(x) and WALK_HEX.match(y))
    if type(x) is bool:
        return x == y
    if type(x) is dict:
        return set(x) == set(y) and all(encoded_alike(x[k], y[k]) for k in x)
    if type(x) is list:
        if _walk_rational(x) or _walk_rational(y):
            return _walk_rational(x) and _walk_rational(y)
        return len(x) == len(y) and all(encoded_alike(u, v) for u, v in zip(x, y, strict=True))
    return True


def exact(value):
    """A finite exact value, including the exact value of an input binary64."""
    if type(value) is bool:
        raise ContractError("boolean is not a numerical quantity")
    if type(value) is Fraction:
        result = value
    elif type(value) is int:
        result = Fraction(value)
    elif type(value) is float:
        need(math.isfinite(value), "non-finite numerical value")
        result = Fraction.from_float(value)
    elif type(value) is str and HEX.fullmatch(value):
        result = Fraction(int(value, 16))
    elif (type(value) in (list, tuple) and len(value) == 2
          and all(type(v) is str and HEX.fullmatch(v) for v in value)):
        numerator = int(value[0], 16)
        denominator = int(value[1], 16)
        need(denominator > 0, "exact rational denominator is not positive")
        need(max(abs(numerator).bit_length(), denominator.bit_length()) <= MAX_INTEGER_BITS,
             "encoded integer exceeds the existing 1 MiB integer limit")
        result = Fraction(numerator, denominator)
    else:
        raise ContractError("not an exact rational or finite binary64")
    need(max(abs(result.numerator).bit_length(), result.denominator.bit_length())
         <= MAX_INTEGER_BITS, "numerical input exceeds the existing 1 MiB integer limit")
    return result


def encoded(value):
    return [hex(value.numerator), hex(value.denominator)]


def source_exact(value):
    need(type(value) is not float, "exact source quantity is binary64")
    return exact(value)


def at(record, path):
    """No wildcard expansion, inferred join, value sort, or sibling assumption."""
    need(type(path) is list, "field path must be a list")
    value = record
    for key in path:
        need(type(key) is str and key and key not in ("#", "[]", "*"),
             "concrete field path required")
        if type(value) is dict:
            need(key in value, "missing field at " + ".".join(path))
            value = value[key]
        elif type(value) in (tuple, list):
            need(key.isdecimal() and str(int(key)) == key and int(key) < len(value),
                 "invalid concrete sequence index")
            value = value[int(key)]
        else:
            raise ContractError("field path crosses a scalar")
    return value


def result(verdict, code, **details):
    return dict(verdict=verdict, code=code, **details)


def _components(value, count, representation):
    values = [value] if count == 1 else value
    need(type(values) in (list, tuple) and len(values) == count, "quantity shape differs")
    if representation == "binary64":
        need(all(type(v) is float for v in values), "binary64 quantity has another type")
    else:
        need(all(type(v) is not float for v in values), "exact quantity contains binary64")
    numbers = [exact(v) for v in values]
    labels = [(type(v).__name__, math.copysign(1, v) if type(v) is float and v == 0 else None)
              for v in values]
    return numbers, labels


def _norm_measure(deltas, norm):
    if norm == "l2":
        return sum((x*x for x in deltas), Fraction(0))
    if norm == "l1":
        return sum(map(abs, deltas), Fraction(0))
    return max(map(abs, deltas), default=Fraction(0))


def _diagnostics(before, after, deltas, norm):
    scale = max(map(abs, before + after), default=Fraction(0))
    maximum = max(map(abs, deltas), default=Fraction(0))
    return dict(norm=norm, norm_measure=encoded(_norm_measure(deltas, norm)),
                measure_is_squared=norm == "l2", max_component_change=encoded(maximum),
                relative_to_max_component=encoded(maximum/scale) if scale else encoded(Fraction(0)))


def _ulps(a, b):
    def ordered(value):
        bits = struct.unpack(">q", struct.pack(">d", value))[0]
        return bits if bits >= 0 else -(bits & 0x7fffffffffffffff)
    return abs(ordered(a)-ordered(b))


class FieldContracts:
    """Compile v3 rows against external source pins and verified proof records.

    ``verified_evidence`` is an external trust boundary. Its keys are digests of
    exact retained proof files already checked by the comparator's reader route.
    It must NOT be populated by loading arbitrary contract-nominated files.
    Missing evidence stays REVIEW. Contradictory evidence is FAIL.
    """
    def __init__(self, document, manifests, source_pins, verified_evidence=None):
        self.rows = {}
        self.evidence = copy.deepcopy(verified_evidence or {})
        need(type(self.evidence) is dict and all(type(k) is str and SHA.fullmatch(k) and type(v) is dict
                                                for k, v in self.evidence.items()),
             "verified evidence must be independently checked digest/record pairs")
        self.manifests = copy.deepcopy(manifests)
        self.source_pins = copy.deepcopy(source_pins)
        if document is None:
            self.status = "DEPENDENCY-OPEN"
            return
        need(type(document) is dict and set(document) == {"schema", "composition", "quantities"},
             "v3 field contract is not closed")
        need(document["schema"] == SCHEMA, "unsupported field contract schema")
        need(set(manifests) == {"before", "after"} and
             all(type(v) is str and SHA.fullmatch(v) for v in manifests.values()),
             "invalid independently verified manifest pins")
        need(document["composition"] == manifests, "field contract names another composition")
        need(type(document["quantities"]) is list, "quantities must be a list")
        self.status = "BOUND" if document["quantities"] else "DEPENDENCY-OPEN"
        required = {"id", "path", "quantity", "units", "norm", "components", "representation",
                    "producer", "context", "bound", "coverage_evidence", "correspondence_evidence"}
        for row in copy.deepcopy(document["quantities"]):
            need(type(row) is dict and set(row) == required, "quantity contract row is not closed")
            path = row["path"]
            need(type(path) is list and len(path) >= 2 and
                 all(type(p) is str and p and p not in ("#", "[]", "*") for p in path),
                 "quantity selectors must be complete concrete paths")
            key = tuple(path)
            need(key not in self.rows, "duplicate quantity selector")
            need(not any(key[:len(k)] == k or k[:len(key)] == key for k in self.rows),
                 "overlapping quantity selectors")
            need(all(type(row[k]) is str and row[k] for k in ("id", "quantity", "units")),
                 "quantity identity/units absent")
            need(row["norm"] in ("scalar", "l1", "l2", "linf"), "unknown norm")
            need(type(row["components"]) is int and row["components"] >= 1,
                 "invalid quantity component count")
            need((row["norm"] == "scalar") == (row["components"] == 1), "norm/shape mismatch")
            need(row["representation"] in ("exact", "binary64"), "unknown representation")
            need(type(row["producer"]) is dict and set(row["producer"]) == {"before", "after"},
                 "producer pair missing")
            for arm, producer in row["producer"].items():
                need(type(producer) is dict and set(producer) == {"path", "sha256"},
                     "producer identity malformed")
                need(type(producer["path"]) is str and producer["path"] and
                     type(producer["sha256"]) is str and SHA.fullmatch(producer["sha256"]),
                     "producer path/hash invalid")
                need(source_pins.get(arm, {}).get(producer["path"]) == producer["sha256"],
                     "producer not in independently verified source manifest")
            need(type(row["context"]) is dict and set(row["context"]) ==
                 {"level", "history", "projection", "layout"}, "semantic context is incomplete")
            self._validate_bound(row["bound"])
            level = row["context"]["level"]
            need((type(level) is int and level >= 0) or
                 (level is None and row["bound"].get("kind") != "design-5"),
                 "applicable refinement level missing")
            if row["bound"]["kind"] in ("pose-quaternion", "radius-growth"):
                # E's pose has no refinement-level parameter; its goal is width-derived.
                shape = ("l2", 4) if row["bound"]["kind"] == "pose-quaternion" else ("scalar", 1)
                need(level is None and (row["norm"], row["components"]) == shape and
                     row["representation"] == "exact", "E pose bound applied to another quantity shape")
                need((row["producer"]["before"]["sha256"], row["producer"]["after"]["sha256"]) ==
                     (E_SOURCE, E_ROUNDED) and transforms_only(source_pins),
                     "E pose bound outside its proved source pair and unchanged dependencies")
            need(type(row["context"]["history"]) is dict and set(row["context"]["history"]) ==
                 {"before", "after"} and all(type(s) is str and SHA.fullmatch(s)
                                            for s in row["context"]["history"].values()),
                 "source history pins missing")
            need(all(type(row["context"][k]) is str and row["context"][k]
                     for k in ("projection", "layout")), "projection/layout absent")
            for key_name in ("coverage_evidence", "correspondence_evidence"):
                need(row[key_name] is None or type(row[key_name]) is str and SHA.fullmatch(row[key_name]),
                     "invalid evidence digest")
            self.rows[key] = row

    @staticmethod
    def _validate_bound(bound):
        need(type(bound) is dict and "kind" in bound, "bound missing")
        kind = bound["kind"]
        if kind in ("exact", "unresolved"):
            need(set(bound) == {"kind"}, "exact/unresolved bound is not closed")
        elif kind == "radius-growth":
            need(set(bound) == {"kind", "shift", "proof"} and type(bound["shift"]) is int and
                 bound["shift"] == 11 and bound["proof"] == E_RADIUS_PROOF,
                 "radius-growth bound is not the source-proved E rule")
        elif kind in ("design-5", "pose-quaternion"):
            if kind == "design-5":
                need(set(bound) == {"kind", "radius", "certifies"}, "design bound is not closed")
            else:
                need(set(bound) == {"kind", "radius", "certifies", "proof"} and bound["proof"] == E_QUAT_PROOF,
                     "pose-quaternion bound is not the source-proved E rule")
            need(bound["certifies"] == "same-quantity", "radius certifies another quantity")
            radius = bound["radius"]
            need(type(radius) is dict and set(radius) == {"before_path", "after_path", "scale"},
                 "radius selectors/scale missing")
            for arm in ("before", "after"):
                need(type(radius[arm+"_path"]) is list and radius[arm+"_path"]
                     and all(type(p) is str and p and p not in ("#", "[]", "*")
                             for p in radius[arm+"_path"]), "radius path is not concrete")
            need(exact(radius["scale"]) > 0, "radius scale is not positive")
        elif kind == "independent-absolute":
            need(set(bound) == {"kind", "limit", "strict", "method"} and bound["strict"] is True
                 and type(bound["method"]) is str and bound["method"],
                 "independent bound needs an explicit strict source-backed method")
            need(exact(bound["limit"]) >= 0, "negative independent bound")
        else:
            raise ContractError("unknown bound kind; no generic epsilon route")

    def summary(self):
        return dict(schema=SCHEMA, status=self.status, selectors=len(self.rows),
                    verified_evidence=len(self.evidence), composition=self.manifests)

    def _evidence(self, row, correspondence):
        coverage = self.evidence.get(row["coverage_evidence"])
        mapping = self.evidence.get(row["correspondence_evidence"])
        if coverage is None or mapping is None or correspondence is None:
            return result("REVIEW", "MISSING_INDEPENDENT_FIELD_EVIDENCE")
        # A reader receipt alone has no field-semantics proof: it remains REVIEW.
        if coverage.get("kind") != "field-semantics" or mapping.get("kind") != "quantity-correspondence":
            return result("REVIEW", "UNSUPPORTED_FIELD_EVIDENCE_KIND")
        expected = {k: row[k] for k in ("path", "quantity", "units", "norm", "components",
                                        "representation", "producer", "context", "bound")}
        expected.update(kind="field-semantics", composition=self.manifests)
        if coverage != expected:
            return result("FAIL", "CONTRADICTED_FIELD_SEMANTICS")
        required = {"kind", "composition", "path", "layout", "before_identity", "after_identity"}
        if set(mapping) != required or mapping["composition"] != self.manifests or \
                mapping["path"] != row["path"] or mapping["layout"] != row["context"]["layout"]:
            return result("FAIL", "CONTRADICTED_CORRESPONDENCE")
        if type(correspondence) is not dict or set(correspondence) != {"before_identity", "after_identity"}:
            return result("REVIEW", "MISSING_PROOF_DERIVED_QUANTITY_IDENTITIES")
        if any(type(mapping[k]) is not str or not mapping[k] or correspondence[k] != mapping[k]
               for k in correspondence):
            return result("FAIL", "CORRESPONDENCE_IDENTITY_MISMATCH")
        return None

    def compare(self, path, before, after, *, before_record=None, after_record=None,
                correspondence=None):
        row = self.rows.get(tuple(path))
        if row is None:
            return None
        try:
            a, labels_a = _components(before, row["components"], row["representation"])
            b, labels_b = _components(after, row["components"], row["representation"])
            deltas = [y-x for x, y in zip(a, b, strict=True)]
            changed = any(deltas) or labels_a != labels_b
            details = dict(quantity=row["id"], changed=changed,
                           diagnostics=_diagnostics(a, b, deltas, row["norm"]))
            if row["representation"] == "binary64":
                aa = [before] if row["components"] == 1 else before
                bb = [after] if row["components"] == 1 else after
                details["diagnostics"]["max_ulps"] = max(_ulps(x, y) for x, y in zip(aa, bb, strict=True))
            issue = self._evidence(row, correspondence)
            if issue:
                return dict(issue, **details)
            if row["bound"]["kind"] == "exact":
                return result("FAIL" if changed else "PASS",
                              "EXACT_UNAFFECTED_CHANGED" if changed else "EXACT_EQUAL", **details)
            if row["bound"]["kind"] == "unresolved":
                return result("REVIEW", "NO_APPLICABLE_QUANTITY_BOUND", **details)
            if row["bound"]["kind"] == "radius-growth":
                # E stored operator bound: outward, and strictly below 2**-11 relative growth.
                old, new = a[0], b[0]
                need(old >= 0 and new >= 0, "negative certified radius")
                if new < old:
                    return result("FAIL", "RADIUS_NOT_OUTWARD", **details)
                if old == 0:
                    return result("PASS" if new == 0 else "FAIL",
                                  "EXACT_EQUAL" if new == 0 else "RADIUS_GROWTH_FROM_ZERO", **details)
                shift = row["bound"]["shift"]
                details["strict_limit"] = encoded(old/2**shift)
                if (new-old)*2**shift >= old:
                    return result("FAIL", "STRICT_RADIUS_GROWTH_VIOLATION", **details)
                return result("PASS", "EXACT_EQUAL" if not changed else "COVERED_RADIUS_GROWTH", **details)
            if row["bound"]["kind"] in ("design-5", "pose-quaternion"):
                r = row["bound"]["radius"]
                if before_record is None or after_record is None:
                    return result("REVIEW", "MISSING_CERTIFIED_RADIUS_RECORD", **details)
                read = source_exact if row["bound"]["kind"] == "pose-quaternion" else exact
                old = read(at(before_record, r["before_path"]))
                new = read(at(after_record, r["after_path"]))
                need(old >= 0 and new >= 0, "negative certified radius")
                # The independently checked semantics explicitly certifies both
                # radii for this same quantity/norm, including radius scale.
                limit = min(old, new)*exact(r["scale"])/2048
            else:
                limit = exact(row["bound"]["limit"])
            measured = _norm_measure(deltas, row["norm"])
            threshold = limit*limit if row["norm"] == "l2" else limit
            details["strict_limit"] = encoded(limit)
            if any(deltas) and measured >= threshold:
                return result("FAIL", "STRICT_QUANTITY_BOUND_VIOLATION", **details)
            if labels_a != labels_b:
                return result("REVIEW", "TYPE_OR_SIGN_LABEL_CHANGED", **details)
            return result("PASS", "EXACT_EQUAL" if not changed else "COVERED_QUANTITY_CHANGE", **details)
        except (ContractError, OverflowError, ValueError, TypeError, KeyError) as error:
            return result("FAIL", "MALFORMED_QUANTITY_OR_CONTRACT", quantity=row["id"], reason=str(error))

    def compare_record(self, kind, before, after, correspondence):
        """Evaluate only concrete selectors; caller retains its ordinary walk.

        Returns (quantity_results, consumed_paths). Remove/suppress ordinary
        numeric classification only for each complete consumed subtree. Retain
        all other proof, identity, structure, refusal and unbound-field checks.
        ``correspondence`` is a mapping from selector tuples to external proofs.
        """
        results, consumed = [], set()
        for path in self.rows:
            if path[0] != kind:
                continue
            try:
                a, b = at(before, list(path[1:])), at(after, list(path[1:]))
            except ContractError as error:
                results.append(result("REVIEW", "QUANTITY_SELECTOR_UNAVAILABLE",
                                      path=list(path), reason=str(error)))
                continue
            item = self.compare(path, a, b, before_record=before, after_record=after,
                                correspondence=correspondence.get(path))
            results.append(dict(item, path=list(path)))
            consumed.add(path)
        return results, consumed


def evaluate_header(stored, exact_total, width):
    """Arithmetic only: caller must use derive_header_total for source binding."""
    try:
        stored, total, width = map(source_exact, (stored, exact_total, width))
        need(stored >= 0 and total >= 0 and width >= 0, "negative header quantity")
        if total > width:
            return result("FAIL", "EXACT_TOTAL_EXCEEDS_WIDTH")
        if total == 0:
            return result("PASS" if stored == 0 else "FAIL", "EXACT_ZERO_HEADER")
        if stored < total:
            return result("FAIL", "HEADER_NOT_OUTWARD")
        if (stored-total)*2**64 >= total:
            return result("FAIL", "HEADER_EXCESS_NOT_STRICT")
        if stored > width:
            return result("FAIL", "STORED_HEADER_EXCEEDS_WIDTH")
        return result("PASS", "ADDENDUM_E_HEADER", exact_total=encoded(total))
    except (ContractError, ValueError, TypeError) as error:
        return result("FAIL", "MALFORMED_HEADER_QUANTITY", reason=str(error))


def derive_header_total(header, producer_module, producer_sha256):
    """Recompute historical E per-cell or M per-component pre-rounding total.

    The caller must obtain the producer pair from the independently verified
    manifest/reader, not from a field in this header. Unknown source -> REVIEW.
    """
    variant = HEADER_PRODUCERS.get((producer_module, producer_sha256))
    if variant is None:
        return result("REVIEW", "UNREVIEWED_HEADER_PRODUCER")
    try:
        need(type(header) is dict and header.get("schema") == MESH_SCHEMA, "wrong mesh schema")
        differential = header.get("physical_geometry_family") == "differential-plate-component-partition-v1"
        need(differential == (variant == "M"), "producer/header layout mismatch")
        cells = header.get("cells")
        need(type(cells) is list, "missing cell list")
        groups, seen = {}, set()
        for cell in cells:
            need(type(cell) is dict and type(cell.get("cell_id")) is str and cell["cell_id"],
                 "cell identity missing")
            need(cell["cell_id"] not in seen, "duplicate emitted cell identity")
            seen.add(cell["cell_id"])
            volume = source_exact(cell["volume_m3"])
            bounds = cell["physical_volume_bounds_m3"]
            need(type(bounds) is list and len(bounds) == 2, "physical volume bounds missing")
            lo, hi = map(source_exact, bounds)
            deviation = source_exact(cell[DEVIATION])
            need(volume > 0 and 0 <= lo <= hi and deviation >= 0, "invalid physical volume/enclosure")
            kind = cell.get("kind")
            need(kind in ("collar", "exterior"), "unknown emitted cell kind")
            if kind == "collar":
                need(lo == hi == volume and deviation == 0, "collar volume/deviation mismatch")
                continue
            if variant == "E":
                key = (cell["cell_id"],)
            else:
                support = cell.get("physical_support")
                need(type(support) is dict and type(support.get("differential_support_id")) is str
                     and support["differential_support_id"] and type(cell.get("logical_cell_id")) is str
                     and cell["logical_cell_id"] and support.get("logical_cell_id") == cell["logical_cell_id"],
                     "differential component correspondence missing")
                key = (support["differential_support_id"], cell["logical_cell_id"])
            if key in groups:
                group = groups[key]
                need(group[1:] == [lo, hi, deviation], "split-piece metadata disagree")
                group[0] += volume
            else:
                groups[key] = [volume, lo, hi, deviation]
        total = Fraction(0)
        for volume, lo, hi, deviation in groups.values():
            recomputed = max(abs(volume-lo), abs(volume-hi))
            need(deviation == recomputed, "per-cell/component deviation differs from exact computation")
            total += recomputed
        checked = evaluate_header(header[DEVIATION], encoded(total), header[WIDTH])
        return dict(checked, producer_variant=variant, groups=len(groups), exact_total=encoded(total))
    except (ContractError, ValueError, KeyError, TypeError) as error:
        return result("FAIL", "HEADER_SOURCE_CONTRACT_VIOLATION", reason=str(error))


def refusal_result(before, after, row=None):
    """Proved per-arm refusal outcomes at one producer site (design rows 1-G, 1b-G, 2.7, 5.11; REFUSAL_SITES).

    A flip is REVIEW: every listed site can refuse legitimately when pose-affected inputs differ, and heat
    differences under identical inputs are REVIEW too (the design rows' record, DESIGN_RETURN). A
    missing outcome is REVIEW. NO_REFUSAL_FLIP speaks for the outcome only and grants no PASS to any value.
    A resource stop attributed to a guarded step stays with the comparator's D01 stage rule (robustness).
    """
    if type(before) is not bool or type(after) is not bool:
        return result("REVIEW", "MISSING_PROVED_REFUSAL_OUTCOME", row=row)
    return result("REVIEW" if before != after else "PASS",
                  "REFUSAL_FLIP" if before != after else "NO_REFUSAL_FLIP", row=row)


def compile_source_evidence(manifests, source_pins, record_pairs, selectors):
    """Independently derive the currently source-proved numerical row subset.

    No caller-supplied semantics/bound enters this compiler. ``record_pairs`` is
    keyed by record kind; each before/after item has ``record``, ``identity``
    (the comparator's independently re-derived reader target), and ``producer``
    {path, sha256} from that verified producer's actual selected source manifest.
    These are required trust-boundary inputs from the existing reader proof.

    Currently source-proved rows: E/M exact time_s (s) and exact geometry-volume
    budget (m3); E representative_quaternion and pose_operator_error_bound when
    both arms' stored segments authenticate their trajectory_id and every E
    invocation input is identical. The operator bound becomes the quaternion's
    same-quantity radius only through the source-proved scale 1/4 (stored = 4*e)
    and only for E_SOURCE -> E_ROUNDED with every other selected source unchanged
    (reviewed width transforms aside), or an unchanged reviewed source; any other
    pairing, changed dependency or differing input stays unresolved.
    The returned contract/evidence/correspondence is ready for FieldContracts.
    """
    need(type(manifests) is dict and set(manifests) == {"before", "after"} and
         all(type(v) is str and SHA.fullmatch(v) for v in manifests.values()),
         "selected verified manifest pair required")
    known = {
        "time_s": ("mesh endpoint time", "s"),
        WIDTH: ("pre-existing total geometry volume-error budget", "m3"),
        "representative_quaternion": ("representative pose quaternion", "1"),
        "pose_operator_error_bound": ("rotation operator error bound", "1"),
    }
    rows, evidence, correspondence, unresolved = [], {}, {}, []
    for selector in selectors:
        need(type(selector) in (list, tuple), "source selector must be a path list/tuple")
        path = tuple(selector)
        need(len(path) >= 2 and all(type(x) is str and x for x in path),
             "invalid source-evidence selector")
        if len(path) != 2 or path[1] not in known:
            unresolved.append(dict(path=list(path), code="NO_SOURCE_PROVED_QUANTITY_MAPPING"))
            continue
        pair = record_pairs.get(path[0])
        if not pair or set(pair) != {"before", "after"}:
            unresolved.append(dict(path=list(path), code="MISSING_VERIFIED_RECORD_PAIR"))
            continue
        producer, history, identities, variants, inputs = {}, {}, {}, {}, {}
        pose = path[1] in E_POSE_FIELDS
        missing = False
        for arm in ("before", "after"):
            item = pair[arm]
            need(type(item) is dict and set(item) == {"record", "identity", "producer"},
                 "verified record-pair item malformed")
            p = item["producer"]
            need(type(p) is dict and set(p) == {"path", "sha256"} and type(p["path"]) is str,
                 "verified producer malformed")
            need(source_pins.get(arm, {}).get(p["path"]) == p["sha256"],
                 "verified record producer absent from selected source manifest")
            module = PurePosixPath(p["path"].replace("\\", "/")).name
            variant = HEADER_PRODUCERS.get((module, p["sha256"]))
            if variant is None:
                missing = True
                break
            record = item["record"]
            need(type(record) is dict and record.get("schema") == MESH_SCHEMA,
                 "verified producer record has another schema")
            need((record.get("physical_geometry_family") == "differential-plate-component-partition-v1")
                 == (variant == "M"), "verified producer/record layout mismatch")
            need(type(item["identity"]) is str and item["identity"], "reader target identity absent")
            if type(record.get("trajectory_id")) is not str or not SHA.fullmatch(record["trajectory_id"]):
                missing = True
                break
            if path[1] not in record or pose and (variant != "E" or
                                                  any(k not in record for k in E_INVOCATION_INPUTS)):
                missing = True
                break
            if path[1] == "representative_quaternion":
                need(type(record[path[1]]) is list and len(record[path[1]]) == 4,
                     "source-defined quaternion shape differs")
                for component in record[path[1]]:
                    source_exact(component)
            else:
                source_exact(record[path[1]])
            if pose:
                # Chronological history: E stores the very segments passed to
                # _representative_pose and their W trajectory identity. A stored
                # list that does not hash to it is a contradiction; any other
                # segment layout is unresolved context, never a FAIL.
                if type(record["trajectory_segments"]) is not list:
                    missing = True
                    break
                need(digest(record["trajectory_segments"]) == record["trajectory_id"],
                     "E trajectory_id does not identify its stored trajectory segments")
                inputs[arm] = digest({k: record[k] for k in E_INVOCATION_INPUTS})
            producer[arm], history[arm], variants[arm] = p, record["trajectory_id"], variant
            identities[arm+"_identity"] = item["identity"] + "/" + "/".join(path[1:])
        if missing:
            unresolved.append(dict(path=list(path), code="UNKNOWN_SOURCE_OR_MISSING_RECORD_CONTEXT"))
            continue
        if variants["before"] != variants["after"]:
            unresolved.append(dict(path=list(path), code="DIFFERENT_PRODUCER_LAYOUTS_REQUIRE_CORRESPONDENCE"))
            continue
        norm, components, bound = "scalar", 1, {"kind": "exact"}
        if pose:
            if inputs["before"] != inputs["after"]:
                unresolved.append(dict(path=list(path), code="E_POSE_INVOCATION_INPUTS_DIFFER"))
                continue
            sources = (producer["before"]["sha256"], producer["after"]["sha256"])
            # Exact pose identity also depends on the selected helper sources.
            if (sources[0] == sources[1] or sources == (E_SOURCE, E_ROUNDED)) and \
                    not transforms_only(source_pins):
                unresolved.append(dict(path=list(path), code="E_POSE_DEPENDENCY_SOURCES_DIFFER"))
                continue
            if sources == (E_SOURCE, E_ROUNDED):
                if path[1] == "representative_quaternion":
                    radius = [E_POSE_FIELDS[1]]
                    bound = {"kind": "pose-quaternion", "certifies": "same-quantity", "proof": E_QUAT_PROOF,
                             "radius": {"before_path": radius, "after_path": radius, "scale": ["0x1", "0x4"]}}
                else:
                    bound = {"kind": "radius-growth", "shift": 11, "proof": E_RADIUS_PROOF}
            elif sources[0] != sources[1]:
                unresolved.append(dict(path=list(path), code="E_POSE_SOURCE_PAIR_NOT_PROVED"))
                continue
            if path[1] == "representative_quaternion":
                norm, components = "l2", 4
        context = dict(level=None, history=history, projection="identity-exact",
                       layout=variants["before"]+":mesh-header")
        quantity, units = known[path[1]]
        semantics = dict(kind="field-semantics", composition=manifests, path=list(path),
                         quantity=quantity, units=units, norm=norm, components=components,
                         representation="exact", producer=producer, context=context, bound=bound)
        mapping = dict(kind="quantity-correspondence", composition=manifests, path=list(path),
                       layout=context["layout"], **identities)
        semantics_sha, mapping_sha = digest(semantics), digest(mapping)
        row = {key: value for key, value in semantics.items() if key not in ("kind", "composition")}
        row.update(id=".".join(path), coverage_evidence=semantics_sha, correspondence_evidence=mapping_sha)
        rows.append(row)
        evidence[semantics_sha], evidence[mapping_sha] = semantics, mapping
        correspondence[path] = identities
    return dict(document=dict(schema=SCHEMA, composition=manifests, quantities=rows),
                verified_evidence=evidence, correspondence=correspondence, unresolved=unresolved)


# ---- Design rows ------------------------------------------------------------------------------------------
# RULE and REFUSAL_ONLY rows in their BINDING CORRECTION forms, plus the corrected FAIL-only controls of the
# NO_RULE rows 1-D and 1-E. DESIGN_RETURN holds the SHA-256 digests of the private design-row record these
# rules were encoded from: reproducibility provenance only, not a document shipped with this module. A row
# decides PASS or FAIL only when every stated precondition holds, each precondition by canonical-JSON
# identity (identical); otherwise it is REVIEW and the field stays with the ordinary walk. Only fields a row
# decides (PASS or FAIL) are consumed, and a PASS only where the type-strict walk would see no encoding
# change (encoded_alike). A record layout this reading does not recognise is REVIEW, never FAIL: the layout
# reading is this module's, not the producer's contract. 'before' is the reference arm, 'after' the width
# arm. The rows take DG as identical only at its reviewed pin (DG_SOURCE); the rest of the reference
# composition is the replay operator's precondition. Family 3 (W records) is enforced in field_provenance;
# rows 4.1 and 5.10 are the existing E pose rows and the Addendum E header rule; the REFUSAL_ONLY rows are
# the comparator's stage refusal rule, which is stricter by a recorded departure from row 1-G (D01: a
# resource-stop flip FAILs; any other one-arm refusal stays VOID-SUSPECT until its cause is bound).
DESIGN_RETURN = {"DESIGN-RETURN-r1.md": "cdf375f8c47937ec34aded17ea37d34030f188f1caa9ebc8a2839d596941b80d",
                 "design-return-r1.json": "aa0748ec99ae76e1f1ed34d5e983fb377ec0429350f0c5627cffe4c1591994d0"}
RULE, REFUSAL_ONLY, NO_RULE = "RULE", "REFUSAL_ONLY", "NO_RULE_STAYS_REVIEW"
STAGE_RULE = "compare_arms stage refusal rule"
# Every design row: (family, final verdict, where it is enforced; None = catalogued, REVIEW by the walk).
DESIGN_ROWS = {
    "1-A": ("1", RULE, "DesignRows.interval"), "1-B": ("1", RULE, "DesignRows.interval"),
    "1-C": ("1", RULE, "DesignRows.posed_support"),
    "1-D": ("1", NO_RULE, "DesignRows.posed_support (FAIL-only control)"),
    "1-E": ("1", NO_RULE, "DesignRows.measure (FAIL-only controls)"), "1-F": ("1", NO_RULE, None),
    "1-G": ("1", REFUSAL_ONLY, STAGE_RULE),
    "1b-A": ("1b", RULE, "DesignRows.mesh"), "1b-B": ("1b", NO_RULE, None), "1b-C": ("1b", NO_RULE, None),
    "1b-D": ("1b", RULE, "DesignRows.mesh"), "1b-E": ("1b", NO_RULE, None), "1b-F": ("1b", NO_RULE, None),
    "1b-G": ("1b", REFUSAL_ONLY, STAGE_RULE),
    "2.1": ("2", RULE, "DesignRows.boundary_pose"), "2.2": ("2", RULE, "DesignRows.boundary_pose"),
    "2.3": ("2", RULE, "DesignRows.boundary_pose"), "2.4": ("2", NO_RULE, None), "2.5": ("2", NO_RULE, None),
    "2.6": ("2", RULE, "DesignRows.force_pose"), "2.7": ("2", REFUSAL_ONLY, STAGE_RULE),
    "2.8": ("2", RULE, "DesignRows.force_background"), "2.9": ("2", NO_RULE, None),
    "3.1": ("3", RULE, "field_provenance W_POSE_INDEPENDENT_FACES_CHANGED"),
    "3.2": ("3", RULE, "field_provenance W_FACE_CLOSURE_CONTRADICTION, W_FACE_PARTITION_CONTRADICTION"),
    "3.3": ("3", NO_RULE, None),
    "3.4": ("3", NO_RULE, None), "3.5": ("3", NO_RULE, None),
    "3.6": ("3", RULE, "field_provenance W_SETTLED_CELL_CHOSEN_CHANGED"), "3.7": ("3", NO_RULE, None),
    "3.8": ("3", RULE, "field_provenance W_EXACT_START_BOUNDS_CHANGED"), "3.9": ("3", NO_RULE, None),
    "3.10": ("3", NO_RULE, None), "3.11": ("3", NO_RULE, None),
    "4.1": ("4", RULE, "compile_source_evidence E pose rows"), "4.2": ("4", RULE, "DesignRows.mesh"),
    "4.3": ("4", RULE, "DesignRows.mesh"), "4.4": ("4", RULE, "DesignRows.mesh"), "4.5": ("4", NO_RULE, None),
    "4.6": ("4", RULE, "DesignRows.mesh"), "4.7": ("4", RULE, "DesignRows.mesh"), "4.8": ("4", NO_RULE, None),
    "4.9": ("4", NO_RULE, None),
    "5.1": ("5", NO_RULE, None), "5.2": ("5", NO_RULE, None), "5.3": ("5", NO_RULE, None),
    "5.4": ("5", NO_RULE, None), "5.5": ("5", NO_RULE, None), "5.6": ("5", RULE, "DesignRows.heat"),
    "5.7a": ("5", RULE, "DesignRows.heat"), "5.7b": ("5", NO_RULE, None), "5.8": ("5", RULE, "DesignRows.heat"),
    "5.9": ("5", RULE, "DesignRows.heat"), "5.10": ("5", RULE, "evaluate_header / derive_header_total"),
    "5.11": ("5", REFUSAL_ONLY, STAGE_RULE), "5.12": ("5", NO_RULE, None),
}
# Missed consumers found by the design's own checks (7 W-pose, 7 E-pose, 6 W-enclosure, 9 heat): REVIEW,
# or refusal-only where stated. Catalogued; none grants a PASS.
MISSED_CONSUMERS = (
    ("W-pose", "DG:123-125 interval_id cascade (support ids, birth cells, stock key, posed/measure/partition"
               " records, differential_coupling:365)", "REVIEW"),
    ("W-pose", "DG:3521-3538 _moving_interface_leaf (added to row 1-E)", "REVIEW"),
    ("W-pose", "DG:2428-2437 support work_units and constraint set (both enter support_id)", "REVIEW"),
    ("W-pose", "DG:497-503 component ray cache retention (work_units)", "REVIEW"),
    ("W-pose", "callers of pose-affected DG outputs: differential_ale, differential_coupling, differential_trace,"
               " dual_geometry, initial_parallel, parallel_dispatch, regional_workflow, spatial_owner", "REVIEW"),
    ("W-pose", "DG:2266-2268, DG:5747 snapshot-rotated wrapping of moving-ray-edge certificates", "REVIEW"),
    ("W-pose", "spatial_owner:611 close_spatial_ale and the importers of integration_exterior_mesh", "REVIEW"),
    ("E-pose", "SP:522-536, SP:619-636 PressureCouplingRefused notes (pose_rotation, pose_error, pose_axis)",
     "REVIEW"),
    ("E-pose", "pressure_walls:152,190,219,347,395 worker transport of _KernelPose (route choice)", "REVIEW"),
    ("E-pose", "DP:203-226, DP:476-487 cut torques and cut_face_certificates: DG face enclosures read the rounded"
               " W._pose_vector and certificate_id hashes interval_id (row 1-E: REVIEW; FAIL only if disjoint)",
     "REVIEW"),
    ("E-pose", "E:301,315,332,347,354-358,731 (E:944) pose-dependent refusal tests", "REFUSAL_ONLY"),
    ("E-pose", "D:99, P:127, P:177-179 budget reservations sized from rounded pose bytes", "REFUSAL_ONLY"),
    ("E-pose", "regional_driving:305-306,310 lift descriptor and lift_id (unreachable in the base)", "REVIEW"),
    ("E-pose", "family 4 cell volumes, centroids and faces into heat (use the corrected F4-3 radius)", "REVIEW"),
    ("W-enclosure", "regional_collar3d:627,630 rigid_motion source_id and wall_measure_id", "REVIEW"),
    ("W-enclosure", "XS:563,566 wall_measure_id in exterior-fv metadata and the exchange record", "REVIEW"),
    ("W-enclosure", "E:735,950 and spatial_ale:594 wall_measure_id on those routes", "REVIEW"),
    ("W-enclosure", "XS:512-514 receiver rows selected by outward_max_deviation_m3", "REVIEW"),
    ("W-enclosure", "XS:382-383, XS:406-407 donor and native-stream refusals", "REFUSAL_ONLY"),
    ("W-enclosure", "checked absent: no other reader of W rows/exterior_cells (DG:3902ff, dual_geometry:64,"
                    " spatial_owner:85/267/582, spatial_ale:290 read their own records)", "REVIEW"),
    ("Heat", "spatial_owner:177-180 joined-heat audit arrays (verdicts of 5.1, 5.3, 5.6)", "REVIEW"),
    ("Heat", "regional_collar3d:967-977 collar joint-heat snapshot incl. exact_capacity_projection_j_k",
     "REVIEW"),
    ("Heat", "regional_collar3d:991-1000 collar fields record and native endpoint refresh", "REVIEW"),
    ("Heat", "prepared_interval_driver:272-276 public_temperature_k summary", "REVIEW"),
    ("Heat", "check_global_accounts after publication (driver capture)", "REFUSAL_ONLY"),
    ("Heat", "regional_collar3d:933-937, 961-962 collar adoption refusals", "REFUSAL_ONLY"),
    ("Heat", "private_heat_checkpoint_consumer_r10:64-145 reload revalidation", "REFUSAL_ONLY"),
    ("Heat", "integration_private_heat_cold recovery seam (plan and target reread)", "REFUSAL_ONLY"),
    ("Heat", "projection r5:42 private_result_id (an identity field, never compared numerically)", "REVIEW"),
)
# Added by an independent refutation of these rows; kept apart so the design's 7+7+6+9 stays traceable.
REFUTER_ADDITIONS = (
    ("W-pose", "M:325-335 (no thermal surrogate) and M:674-676 (exact total above width), downstream of DG"
               " posed planes", "REFUSAL_ONLY"),
    ("W-pose", "M:327-330 compact-witness branch: a pose-driven persisted choice of cell or witness", "REVIEW"),
    ("W-pose", "DG:4105-4106 GCLInfeasible trial selection, persisted as graph booked_end_selection and the"
               " closed record: a decision, not a refusal", "REVIEW"),
    ("E-pose", "E._representative_pose budget refusal reached through DG:772 (base E:406-407, wr2 E:460-461)",
     "REFUSAL_ONLY"),
    ("E-pose", "DP:220-221, DP:485-486, DP:493-494 PressureCouplingRefused (SP:518, SP:618 note and re-raise)",
     "REFUSAL_ONLY"),
)
# Outcome-level sites of the REFUSAL_ONLY rows (BINDING CORRECTION 1-G). Each is
# judged by refusal_result on proved per-arm outcomes, which the nine-kind dump does not hold: REVIEW until supplied.
REFUSAL_SITES = {
    "1-G": ("DG:550-551 band", "DG:377-378, 661-662, 706-707 orientation", "DG:3792-3793 chart",
            "DG:1288 disjoint partition", "DG max_leaves and width tests",
            "V reserve() MemoryLimitError (integration_volume.py:49-56, with the DG:506 cache reserve)",
            "DG:99 _issue reserve", "M:325-335, M:674-676",
            "E._representative_pose budget via DG:772 (base E:406-407, wr2 E:460-461)",
            "DP:220-221, DP:485-486, DP:493-494 PressureCouplingRefused"),
    "1b-G": ("ALE:290-291 containment through DG:4104 and DG:4116 (the only site on the differential route)",),
    "2.7": ("regional_driving:252-254 PlateRegionalLift (unreachable in the base)",),
    "5.11": ("issuer r13 residual-target, UnresolvedRounding, positivity and 1e-11 gate refusals",
             "check_global_accounts after publication (driver capture)",
             "regional_collar3d:933-937, 961-962 collar adoption", "private_heat_checkpoint_consumer_r10:64-145"),
}
DG_SCHEMA = "atlas.differential-physical-geometry.v1"
DG_METHOD = "coaxial-physical-ownership-fan-v1"
POSED_SUPPORT_SCHEMA = "atlas.differential-posed-support.v1"
DG_MEASURE_SCHEMA = "atlas.differential-physical-wall.v1"
BOUNDARY_POSE_SCHEMA = "atlas.differential-boundary-pose.v1"
FORCE_POSE_SCHEMA = "atlas.current-common-force-pose.v1"
FORCE_BACKGROUND_SCHEMA = "atlas.current-force-background.v1"
HEAT_SCHEMA = "atlas.private.composed-heat-advance.r12"
HEAT_PLAN_SCHEMA = "atlas.private.composed-heat-plan.r1"
HEAT_REF_SCHEMA = "atlas.private.joined-heat-reference.r1"
HEAT_METHOD = "private:uniform-k-composed-forward-contract.r12"
GRAPH_SCHEMA = "atlas.source-bound-spatial-ale-graph.v1"
DUAL_CLOSURE_METHOD = "true-minus-selected G;"     # DG:3948; the carried closure writes "true-minus-booked volume;"
FORCING_SCHEMA = "atlas.differential-pressure-forcing.v1"
AUDIT_SOURCE = "spatial-audit:joined-heat:input_source_w"
STATE_SCHEMA = "atlas.spatial-exterior-state.v1"
DIFFERENTIAL_FAMILY = "differential-plate-component-partition-v1"
ZERO_SOURCE_POLICY = "already-booked-transport; zero added heat source"
FINISHER = "private:standalone-conservative-physical-face-finish-r7"
DESIGN_MODULES = {"W": "integration_wall_measures.py", "E": "integration_exterior_mesh.py",
                  "M": "integration_differential_mesh.py", "DG": "integration_differential_geometry.py"}
REVIEWED_TRANSFORMS = {"W": (W_SOURCE, W_ROUNDED), "E": (E_SOURCE, E_ROUNDED), "M": (M_SOURCE, M_ROUNDED)}
# DifferentialMeasure outputs (DG:1558-1575, DG:1833-1845); every other field is an input of the measure.
MEASURE_OUTPUTS = frozenset({"inward_volume_bounds_m3", "outward_volume_bounds_m3", "moment_bounds", "leaves",
                             "met", "work_units", "segments"})
SEGMENT_OUTPUTS = frozenset({"inward_volume_bounds_m3", "outward_volume_bounds_m3", "leaves", "met"})
# E cell fields that read the posed polytope or W's bounds; every other cell field is pose-independent (4.2).
CELL_METRICS = ("volume_m3", "centroid_m", "physical_volume_bounds_m3", DEVIATION, "faces")
E_STATIC_HEADER = ("support_id", "time_s", "grid_id", "grid_lines", "support_tables")
HEAT_NUMERICAL = ("independently_supplied_absolute_residual_target", "exact_corrected_enthalpy_j",
                  "exact_retained_solver_residual_j", "exact_stock_projection_residual_j",
                  "exact_cell_storage_residual_j", "exact_paired_face_energy_j", "exact_source_energy_j",
                  "exact_outward_boundary_energy_j")
DESIGN_SCHEMAS = frozenset({DG_SCHEMA, POSED_SUPPORT_SCHEMA, DG_MEASURE_SCHEMA, BOUNDARY_POSE_SCHEMA,
                            FORCE_POSE_SCHEMA, FORCE_BACKGROUND_SCHEMA, MESH_SCHEMA, HEAT_SCHEMA, GRAPH_SCHEMA,
                            FORCING_SCHEMA, HEAT_PLAN_SCHEMA, HEAT_REF_SCHEMA})
# Non-pose inputs of one DifferentialInterval (DG:711-736): the 1-A corrected precondition (every _pose_binding
# and band input; the endpoint error bounds are the outputs), the 1-B inputs and the motion history. Ids among
# them hash pose-free motion or network data only (never the interval id, which hashes the error bounds).
MOTION_INPUTS = ("parent_network_id", "endpoint_network_id", "motion_id", "motion", "plate_angular_velocity_rad_s",
                 "duration_s", "start_time_s", "end_time_s", "endpoint_binding_limit_rad", "rays", "ownership_fans",
                 "orientation_max_leaves", "trajectory", "trajectory_id", "prior_trajectory_id")
# Inputs of the cut-face torque besides the interval geometry (DP:203-226, DP:505-521): the reservoir pressure
# (its excluded cells and polynomials), densities, radial datum, plates, time and the width/leaf request.
FORCING_INPUTS = ("time_s", "plate_ids", "source", "funding_id", "native_plan_id", "native_material_source",
                  "pressure_reference", "radial_datum", "reservoir_native_side", "reservoir_pressure",
                  "physical_densities", "request")


def floor_log2(value):
    """floor(log2(value)) of a positive exact rational."""
    need(value > 0, "log2 of a non-positive value")
    n, d = value.numerator, value.denominator
    k = n.bit_length()-d.bit_length()
    if (n << -k if k < 0 else n) < (d if k < 0 else d << k):
        k -= 1
    return k


def stored_deviation(total, width):
    """The width arm's outward 64-bit header (wr2 E:29-39 and M; DEVIATION_STORED_BITS = 64)."""
    if total == 0:
        return total
    quantum = Fraction(2)**(floor_log2(total)-64)
    return min(math.ceil(total/quantum)*quantum, width)


def sqrt_bounds(square):
    """Rational l <= sqrt(square) <= u carrying about 64 significant bits."""
    need(square >= 0, "negative square")
    if square == 0:
        return Fraction(0), Fraction(0)
    k = 64-floor_log2(square)//2
    scaled = square*Fraction(4)**k
    low, high = math.isqrt(math.floor(scaled)), math.isqrt(math.ceil(scaled))
    if high*high < scaled:
        high += 1
    unit = Fraction(2)**k
    return low/unit, high/unit


def rotation_of(q):
    """V.CartesianCell.rotated's exact map M(q)/|q|^2 (integration_volume.py:287-309), rows."""
    w, x, y, z = q
    norm = w*w+x*x+y*y+z*z
    need(norm != 0, "a zero quaternion defines no rotation")
    rows = ((w*w+x*x-y*y-z*z, 2*(x*y-w*z), 2*(x*z+w*y)),
            (2*(x*y+w*z), w*w-x*x+y*y-z*z, 2*(y*z-w*x)),
            (2*(x*z-w*y), 2*(y*z+w*x), w*w-x*x-y*y+z*z))
    return tuple(tuple(v/norm for v in row) for row in rows)


def within_norm_band(q, p):
    """E's per-arm pose invariant |q - unit| <= p/4 (E:391-408; the rounded arm keeps it, wr2 E:436-462) in its
    exact necessary form max(0, 1-p/4)^2 <= |q|^2 <= (1+p/4)^2, with no square root. C1-C4 do not imply it, and
    the rotation radius r_R needs it where no rotation is stored."""
    norm, quarter = sum((Fraction(x)**2 for x in q), Fraction(0)), Fraction(p)/4
    return max(Fraction(0), 1-quarter)**2 <= norm <= (1+quarter)**2


def common_axis(rotation, steps):
    """SP._common_axis (integration_spatial_pressure.py:34-43) in exact arithmetic."""
    def cross(a, b):
        return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

    def dot(a, b):
        return sum((x*y for x, y in zip(a, b, strict=True)), Fraction(0))
    vectors = [vector for vector in steps if any(vector)]
    if not vectors or any(any(cross(vector, vectors[0])) for vector in vectors[1:]):
        return None
    axis = vectors[0]
    if any(dot(row, axis) != q or dot(column, axis) != q
           for row, column, q in zip(rotation, zip(*rotation, strict=True), axis, strict=True)):
        return None
    return axis


def _vec(value, count=3):
    need(type(value) is list and len(value) == count, "exact vector shape differs")
    return tuple(source_exact(v) for v in value)


def _matrix(value):
    need(type(value) is list and len(value) == 3, "exact matrix shape differs")
    return tuple(_vec(row) for row in value)


def _locate(record, schemas):
    """schema -> {concrete path: dict} for every dict carrying one of the schemas, nested ones included."""
    found, pending = {}, [((), record)]
    while pending:
        path, value = pending.pop()
        if type(value) is dict:
            if type(value.get("schema")) is str and value["schema"] in schemas:
                found.setdefault(value["schema"], {})[path] = value
            pending.extend((path + (key,), child) for key, child in value.items())
        elif type(value) is list:
            pending.extend((path + (str(index),), child) for index, child in enumerate(value))
    return found


def _exists(record, path):
    """True when the concrete path (string keys, decimal list indices) names a value in the record."""
    value = record
    for key in path:
        if type(value) is dict and key in value:
            value = value[key]
        elif type(value) is list and type(key) is str and key.isdecimal() and int(key) < len(value):
            value = value[int(key)]
        else:
            return False
    return True


def _value(record, path):
    """The value at a concrete path that _exists found in the record."""
    for key in path:
        record = record[int(key)] if type(record) is list else record[key]
    return record


def _constraint_kinds(tree):
    """Kinds in a physical constraint record, following nested 'constraint' fields (row 1-C correction a)."""
    kinds, node = [], tree
    while node is not None:
        need(type(node) is dict and type(node.get("kind")) is str, "constraint record layout differs")
        kinds.append(node["kind"])
        node = node.get("constraint")
    return kinds


class DesignRows:
    """The encoded design-return rows on one interval's record pairs (see the section comment)."""

    def __init__(self, source_pins):
        self.parity = transforms_only(source_pins)
        self.pins = {}
        for family, module in DESIGN_MODULES.items():
            pins = []
            for arm in ("before", "after"):
                found = [pin for path, pin in source_pins.get(arm, {}).items()
                         if PurePosixPath(path.replace("\\", "/")).name == module]
                pins.append(found[0] if len(found) == 1 else None)
            self.pins[family] = tuple(pins)
        self.context = {"before": {}, "after": {}}
        self.counts = {}
        self.motion = False     # set by observe('differential'): the interval's non-pose inputs are identical

    def route(self, family):
        """'transform' (reviewed source -> rounded), 'identical', or None (REVIEW: unreviewed pairing). DG is
        'identical' only at its reviewed pin DG_SOURCE in both arms: the rows on the W transform rest on its
        lines, and an unreviewed DG identical in both arms proves nothing about them."""
        before, after = self.pins[family]
        if not self.parity or before is None or after is None:
            return None
        if family == "DG":
            return "identical" if before == after == DG_SOURCE else None
        if before == after:
            return "identical"
        return "transform" if (before, after) == REVIEWED_TRANSFORMS.get(family) else None

    def differential_route(self):
        return self.route("W") if self.route("DG") == "identical" else None

    def observe(self, kind, before, after):
        """Keep the small context later rows read. Per arm: the state's thermal mesh id, the mesh's cell count
        and one-owner faces, the joined heat plan and reference, and the differential interval id. Across arms:
        whether the interval's non-pose inputs are byte-identical (self.motion). compare_arms observes
        'differential' and 'exchange' before its record walk, and every other kind as it is walked."""
        for arm, record in (("before", before), ("after", after)):
            if type(record) is not dict:
                continue
            context = self.context[arm]
            if kind == "mesh" and record.get("schema") == MESH_SCHEMA:
                faces, cells = record.get("faces"), record.get("cells")
                if type(faces) is list and all(type(f) is dict and type(f.get("face_id")) is str and
                                               type(f.get("owners")) is list for f in faces):
                    context["one_owner_faces"] = frozenset(f["face_id"] for f in faces if len(f["owners"]) == 1)
                if type(cells) is list:
                    context["mesh_cells"] = len(cells)
            if record.get("schema") == STATE_SCHEMA:
                context["thermal_mesh_id"] = record.get("thermal_mesh_id")
            plan = record.get("joined_heat_plan")
            if type(plan) is dict and plan.get("schema") == HEAT_PLAN_SCHEMA:
                context["heat_plan"] = plan
            for reference in (record, record.get("joined_heat")):
                if type(reference) is dict and reference.get("schema") == HEAT_REF_SCHEMA:
                    context["heat_reference"] = reference
            interval = record.get("interval") if kind == "differential" else None
            if type(interval) is dict and interval.get("schema") == DG_SCHEMA:
                context["interval_id"] = interval.get("interval_id")
        if kind == "differential" and type(before) is dict and type(after) is dict:
            self.motion = self.motion_same(before.get("interval"), after.get("interval"))

    @staticmethod
    def motion_same(old, new):
        """The interval pair's non-pose inputs are byte-identical: MOTION_INPUTS, the plate key sets and every
        boundary path row (in order, by boundary_id) without its endpoint_operator_error_bound."""
        if not (type(old) is dict and type(new) is dict and old.get("schema") == new.get("schema") == DG_SCHEMA and
                old.get("method") == new.get("method") == DG_METHOD):
            return False
        rows = [r.get("boundary_paths") for r in (old, new)]
        plates = [r.get("plate_endpoint_operator_error_bounds") for r in (old, new)]
        if not (all(type(x) is list and all(type(row) is dict for row in x) for x in rows) and
                all(type(x) is dict for x in plates)):
            return False
        inputs = [[{k: v for k, v in row.items() if k != "endpoint_operator_error_bound"} for row in x] for x in rows]
        return (identical(inputs[0], inputs[1]) and set(plates[0]) == set(plates[1]) and
                all(identical(old.get(k), new.get(k)) for k in MOTION_INPUTS))

    def summary(self):
        return dict(design_return=DESIGN_RETURN, results=dict(sorted(self.counts.items())),
                    rows={v: sum(1 for row in DESIGN_ROWS.values() if row[1] == v) for v in (RULE, REFUSAL_ONLY, NO_RULE)},
                    missed_consumers=len(MISSED_CONSUMERS), refuter_additions=len(REFUTER_ADDITIONS),
                    motion_inputs_identical=self.motion)

    def evaluate(self, kind, before, after):
        """(results, consumed paths) for every design record pair found at the same path in both arms."""
        # The plan precedes the references that must repeat its target; the ledger record follows both.
        methods = {DG_SCHEMA: self.interval, POSED_SUPPORT_SCHEMA: self.posed_support,
                   DG_MEASURE_SCHEMA: self.measure, BOUNDARY_POSE_SCHEMA: self.boundary_pose,
                   FORCE_POSE_SCHEMA: self.force_pose, FORCE_BACKGROUND_SCHEMA: self.force_background,
                   MESH_SCHEMA: self.mesh, GRAPH_SCHEMA: self.graph, FORCING_SCHEMA: self.forcing,
                   HEAT_PLAN_SCHEMA: self.heat_plan, HEAT_REF_SCHEMA: self.heat_reference, HEAT_SCHEMA: self.heat}
        found = [_locate(before, DESIGN_SCHEMAS), _locate(after, DESIGN_SCHEMAS)]
        results, consumed = [], set()
        for schema, method in methods.items():
            a, b = found[0].get(schema, {}), found[1].get(schema, {})
            if schema == MESH_SCHEMA:
                # Only the logical mesh record itself (mesh.json, v3 decode bound to state.thermal_mesh_id),
                # never a compact stored copy inside another record (the row 5.10 hazard).
                a, b = ({(): x[()]} if kind == "mesh" and () in x else {} for x in (a, b))
            for path in sorted(set(a) | set(b)):
                where = (kind,) + path
                if path not in a or path not in b:
                    results.append(result("REVIEW", "DESIGN_RECORD_IN_ONE_ARM", path=list(where), schema=schema))
                    continue
                # Each record pair decides on its own lists. A layout error keeps the pair's FAIL and REVIEW
                # items but none of its PASSes or consumed paths: a rule it did not finish decides nothing.
                items, taken = [], set()
                try:
                    method(where, a[path], b[path], items, taken)
                except (ContractError, AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError,
                        IndexError) as error:
                    items = [item for item in items if item["verdict"] != "PASS"]
                    items.append(result("REVIEW", "DESIGN_ROW_LAYOUT_UNRECOGNISED", path=list(where),
                                        schema=schema, reason=str(error)))
                    taken = set()
                results.extend(items)
                consumed |= taken
        # A decided field is scrubbed from the walk only at one concrete path present in both arms. The rules
        # compare values (== or exact rationals), which do not tell 5 from 5.0 or 0.0 from -0.0, so a PASS
        # scrubs its field only where the type-strict walk would see no encoding change (encoded_alike); any
        # other PASS becomes REVIEW and its field stays walked unless a FAIL holds the same path.
        consumed = {path for path in consumed if _exists(before, path[1:]) and _exists(after, path[1:])}
        held = {tuple(item["path"]) for item in results if item["verdict"] == "FAIL"}
        for index, item in enumerate(results):
            path = tuple(item["path"])
            if item["verdict"] == "PASS" and path in consumed and not encoded_alike(
                    _value(before, path[1:]), _value(after, path[1:])):
                results[index] = dict(item, verdict="REVIEW", code="DESIGN_ENCODING_DIFFERS", passed=item["code"])
                if path not in held:
                    consumed.discard(path)
        for item in results:
            key = "%s:%s" % (item.get("row", "-"), item["verdict"])
            self.counts[key] = self.counts.get(key, 0)+1
        return results, consumed

    @staticmethod
    def _add(results, consumed, verdict, code, path, row, consume=True, **details):
        results.append(result(verdict, code, path=list(path), row=row, **details))
        if consume and verdict in ("PASS", "FAIL"):
            consumed.add(tuple(path))

    # -- family 1: W pose consumers in differential geometry (DG on the W transform, DG bytes identical)
    def interval(self, where, old, new, results, consumed):
        """Rows 1-A and 1-B on one DifferentialInterval record (DG:711-736)."""
        need(old.get("method") == new.get("method") == DG_METHOD, "unreviewed differential interval method")
        route = self.differential_route()
        rows_old, rows_new = old["boundary_paths"], new["boundary_paths"]
        plates_old = old["plate_endpoint_operator_error_bounds"]
        plates_new = new["plate_endpoint_operator_error_bounds"]
        need(type(rows_old) is list and type(rows_new) is list and all(type(r) is dict for r in rows_old + rows_new)
             and type(plates_old) is dict and type(plates_new) is dict, "differential interval layout differs")

        # 1-A BINDING CORRECTION: every _pose_binding/band input byte-identical (motion_same: boundary rows in
        # order by boundary_id, plate key sets, motion, history and limits), on the reviewed route (DG identical,
        # W the reviewed transform or identical, nothing else changed). The T._moved limits are not in the record:
        # they are geometry.DEFAULT_GEOMETRY_LIMITS unless a caller passes them, and source parity binds both.
        same = route is not None and self.motion_same(old, new)
        limit = old.get("endpoint_binding_limit_rad")
        limit = Fraction(limit) if type(limit) in (int, float) and math.isfinite(limit) else None
        pairs = [(("plate_endpoint_operator_error_bounds", plate), plates_old[plate], plates_new[plate])
                 for plate in sorted(set(plates_old) & set(plates_new))]
        pairs += [(("boundary_paths", str(i), "endpoint_operator_error_bound"), x.get("endpoint_operator_error_bound"),
                   y.get("endpoint_operator_error_bound"))
                  for i, (x, y) in enumerate(zip(rows_old, rows_new, strict=False))]   # extra rows stay walked
        for tail, x, y in pairs:
            path = where + tail
            if not same:
                if x != y:
                    self._add(results, consumed, "REVIEW", "DESIGN_1A_PRECONDITION_DIFFERS", path, "1-A")
                continue
            eb, ea = source_exact(x), source_exact(y)
            need(eb >= 0 and ea >= 0, "negative endpoint operator error bound")
            if limit is not None and max(ea, eb) > limit:
                # Per-arm writer check: the producer refuses a bound above its binding limit (DG:550-551).
                self._add(results, consumed, "FAIL", "DESIGN_1A_ABOVE_BINDING_LIMIT", path, "1-A")
                continue
            if route == "identical" or eb == 0:
                ok, code = ea == eb, "DESIGN_1A_EXACT"
            else:
                m = min(eb, Fraction(1, 2**80))
                ok, code = -m <= (ea-eb)*2**13 <= 7*m, "DESIGN_1A_BAND"
            self._add(results, consumed, "PASS" if ok else "FAIL", code if ok else code+"_VIOLATION", path, "1-A")
        # 1-B: radius 0; the only mechanisms of a difference are decision flips, so a difference is REVIEW.
        same = route is not None and all(identical(old.get(k), new.get(k)) for k in (
            "rays", "ownership_fans", "duration_s", "orientation_max_leaves"))
        for name in ("certified_time_partition_s", "orientation_work_units"):
            if old.get(name) != new.get(name):
                self._add(results, consumed, "REVIEW", "ORIENTATION_DECISION_FLIP" if same else
                          "DESIGN_1B_PRECONDITION_DIFFERS", where + (name,), "1-B")
            elif same and name in old:
                self._add(results, consumed, "PASS", "DESIGN_1B_EQUAL", where + (name,), "1-B")

    def posed_support(self, where, old, new, results, consumed):
        """Row 1-C (exact recomputation) and the 1-D FAIL-only control on one posed-support record (DG:3047)."""
        route = self.differential_route()
        posed_old, posed_new = old["constraints"], new["constraints"]
        tree_old, tree_new = old["physical_constraint_record"], new["physical_constraint_record"]
        need(all(type(v) is dict for v in (posed_old, posed_new, tree_old, tree_new)), "posed support layout differs")
        # 1-C correction b: endpoint, time_s, the support's start/end/duration and the whole constraint tree
        # identical; ids are not compared. The support times are not in this record, and only the start
        # endpoint's pose time (0, or the tree's snapshot offset) does not read them, so 'end' stays REVIEW.
        start = (route is not None and old.get("endpoint") == new.get("endpoint") == "start" and
                 identical(old.get("time_s"), new.get("time_s")))
        for name in sorted(set(posed_old) | set(posed_new)):
            path = where + ("constraints", name)
            x, y = posed_old.get(name), posed_new.get(name)
            if x == y:
                continue
            if x is None or y is None:
                self._add(results, consumed, "REVIEW", "DESIGN_1C_ENTRY_IN_ONE_ARM", path, "1-C")
                continue
            if not (start and name in tree_old and identical(tree_old.get(name), tree_new.get(name))):
                self._add(results, consumed, "REVIEW", "DESIGN_1C_PRECONDITION_NOT_PROVED", path, "1-C")
                continue
            tree = tree_old[name]
            kinds = _constraint_kinds(tree)
            need(type(x) is dict and type(y) is dict and set(x) == set(y) == {"normal", "error_euclidean", "offset"},
                 "posed constraint layout differs")
            nb, eb, ob = _vec(x["normal"]), source_exact(x["error_euclidean"]), source_exact(x["offset"])
            na, ea, oa = _vec(y["normal"]), source_exact(y["error_euclidean"]), source_exact(y["offset"])
            need(eb >= 0 and ea >= 0, "negative posed error")
            if route == "identical":
                self._add(results, consumed, "FAIL", "DESIGN_1C_IDENTICAL_CODE_CHANGED", path, "1-C")
            elif eb == 0:
                # correction a: a zero-error difference is a decision flip wherever the tree holds a
                # moving-ray-edge; it FAILs only for rotated-normal, fixed-plane and snapshot-rotated trees.
                if "moving-ray-edge" in kinds:
                    self._add(results, consumed, "REVIEW", "AXIS_CERTIFICATE_DECISION_FLIP", path, "1-C")
                elif set(kinds) <= {"rotated-normal", "fixed-plane", "snapshot-rotated"}:
                    self._add(results, consumed, "FAIL", "DESIGN_1C_ZERO_ERROR_CHANGED", path, "1-C")
                else:
                    self._add(results, consumed, "REVIEW", "DESIGN_1C_UNREVIEWED_KIND", path, "1-C")
            elif kinds in (["rotated-normal"], ["snapshot-rotated", "rotated-normal"]):
                n_in = _vec((tree if len(kinds) == 1 else tree["constraint"])["normal"])
                scale = max(map(abs, n_in))
                need(scale > 0, "zero constraint normal")
                q = Fraction(2)**(floor_log2(min(eb, scale/2**80))-12)
                ok = (na == tuple(round(c/q)*q for c in nb) and ea == math.ceil((eb+q)/q)*q and oa == ob)
                self._add(results, consumed, "PASS" if ok else "FAIL", "DESIGN_1C_RECOMPUTED" if ok else
                          "DESIGN_1C_RECOMPUTATION_DIFFERS", path, "1-C")
            elif "moving-ray-edge" in kinds:
                # 1-D narrowing: the stored entry does not show whether an axis-certificate
                # return (an exact rescaling, not the posed vector) was taken anywhere under a moving-ray-edge.
                self._add(results, consumed, "REVIEW", "DESIGN_1D_CERTIFICATE_POSSIBLE", path, "1-D")
            else:
                gap = sum(((p-r)**2 for p, r in zip(na, nb, strict=True)), Fraction(0))
                consistent = gap <= (ea+eb)**2
                self._add(results, consumed, "REVIEW" if consistent else "FAIL", "DESIGN_1D_NO_RULE" if consistent else
                          "DESIGN_1D_ENCLOSURES_INCONSISTENT", path, "1-D")

    def measure(self, where, old, new, results, consumed):
        """Row 1-E corrected FAIL-only controls on one DifferentialMeasure record (never a PASS)."""
        if old == new:
            return
        route = self.differential_route()

        def inputs(record, outputs):
            return {k: v for k, v in record.items() if k not in outputs}
        seg_old, seg_new = old.get("segments", []), new.get("segments", [])
        need(type(seg_old) is list and type(seg_new) is list and all(type(s) is dict for s in seg_old + seg_new),
             "measure segment layout differs")
        same = (route is not None and identical(inputs(old, MEASURE_OUTPUTS), inputs(new, MEASURE_OUTPUTS)) and
                identical([inputs(s, SEGMENT_OUTPUTS) for s in seg_old], [inputs(s, SEGMENT_OUTPUTS) for s in seg_new]))
        if not same:
            self._add(results, consumed, "REVIEW", "DESIGN_1E_INPUTS_DIFFER", where, "1-E", consume=False)
            return
        widths = old.get("max_widths")
        met = old.get("met") is True and new.get("met") is True
        pairs = [(name, old.get(name), new.get(name), index) for index, name in
                 enumerate(("inward_volume_bounds_m3", "outward_volume_bounds_m3")) if name in old]
        # Moments: disjointness only. DG's met semantics for moment widths were not verified.
        pairs += [("moment_bounds/%d" % k, x, y, None)
                  for k, (x, y) in enumerate(zip(old.get("moment_bounds", []), new.get("moment_bounds", []), strict=True))]
        pairs += [("segments/%d/%s" % (i, name), x[name], y[name], None)
                  for i, (x, y) in enumerate(zip(seg_old, seg_new, strict=True))
                  for name in ("inward_volume_bounds_m3", "outward_volume_bounds_m3") if name in x]
        failed = False
        for name, x, y, index in pairs:
            (lo_b, hi_b), (lo_a, hi_a) = _vec(x, 2), _vec(y, 2)
            need(lo_b <= hi_b and lo_a <= hi_a, "inverted measure enclosure")
            if max(lo_a, lo_b) > min(hi_a, hi_b):
                failed = True
                self._add(results, consumed, "FAIL", "DESIGN_1E_ENCLOSURES_DISJOINT", where, "1-E", consume=False,
                          quantity=name)
            elif met and type(widths) is list and index is not None and index < len(widths):
                # Both arms met their declared width: two enclosures of one value, each no wider than w.
                w = source_exact(widths[index])
                if abs(lo_a-lo_b) > w or abs(hi_a-hi_b) > w:
                    failed = True
                    self._add(results, consumed, "FAIL", "DESIGN_1E_WIDTH_CONTRADICTION", where, "1-E",
                              consume=False, quantity=name)
        if not failed:
            self._add(results, consumed, "REVIEW", "DESIGN_1E_MET_FLIP" if old.get("met") != new.get("met") else
                      "DESIGN_1E_NO_PROPAGATED_BOUND", where, "1-E", consume=False)

    def _disjoint(self, where, x, y, row, code, results, consumed, **details):
        """FAIL-only: two outward enclosures of one true value cannot be disjoint. True when it FAILs."""
        (lo_b, hi_b), (lo_a, hi_a) = _vec(x, 2), _vec(y, 2)
        need(lo_b <= hi_b and lo_a <= hi_a, "inverted enclosure")
        if max(lo_a, lo_b) > min(hi_a, hi_b):
            self._add(results, consumed, "FAIL", code, where, row, consume=False, **details)
            return True
        return False

    def graph(self, where, old, new, results, consumed):
        """Row 1-E FAIL-only control on the DG closure graph (ACTIVE on the dump). Only the dual closure, which
        the selected driver uses, keeps the DG enclosures it was given: original start, end and face bounds
        (DG:3850-3960 via D.select_geometry, D:520-545; geometry_error_method DG:3948). The carried closure
        stores the arm's own carried start and an outer feasibility end range (DG:4018-4029), so a graph that
        is not dual in both arms is REVIEW. Each graph must also carry its own arm's
        differential interval_id (the bounds record's, DG:2764, kept by the closure), else REVIEW. The carried
        volumes, representatives and booked_end_selection are decisions, left to the walk as REVIEW. Rows pair
        by cell_id: a component id hashes its region definition (DG:2421-2427; a birth component's also hashes
        its birth interval, so it pairs only under one interval identity). Finite-inventory rows hold retained
        stocks, not enclosures; faces pair by a unique (face_id, donor, receiver) and finite exchanges are
        skipped. Never PASS; nothing is consumed."""
        if self.differential_route() is None or not self.motion:
            if old != new:
                self._add(results, consumed, "REVIEW", "DESIGN_1E_GRAPH_INPUTS_NOT_PROVED", where, "1-E", consume=False)
            return
        dual = all(type(r.get("geometry_error_method")) is str and r["geometry_error_method"].startswith(
            DUAL_CLOSURE_METHOD) for r in (old, new))
        bound = all(r.get("interval_id") is not None and r.get("interval_id") == self.context[arm].get("interval_id")
                    for arm, r in (("before", old), ("after", new)))
        if not (dual and bound):
            if old != new:
                self._add(results, consumed, "REVIEW", "DESIGN_1E_GRAPH_NOT_DUAL_CLOSURE" if not dual else
                          "DESIGN_1E_GRAPH_INTERVAL_NOT_BOUND", where, "1-E", consume=False)
            return

        def cells(record):
            found = {}
            for name in ("cells", "inactive_zero_measure_cells"):
                rows = record.get(name, [])
                need(type(rows) is list and all(type(r) is dict and type(r.get("cell_id")) is str for r in rows),
                     "graph cell layout")
                for index, row in enumerate(rows):
                    if row.get("kind") in ("exterior", "collar"):
                        found.setdefault(row["cell_id"], []).append((name, str(index), row))
            return {key: rows[0] for key, rows in found.items() if len(rows) == 1}

        def faces(record):
            rows = record.get("selected_face_representatives", [])
            need(type(rows) is list and all(type(r) is dict for r in rows), "graph face layout")
            found = {}
            for index, row in enumerate(rows):
                if not (row.get("finite_exchange") or row.get("partition_total") or
                        any(str(row.get(k, "")).startswith("finite-stock:") for k in ("donor", "receiver"))):
                    found.setdefault((row.get("face_id"), row.get("donor"), row.get("receiver")), []).append(
                        (str(index), row))
            return {key: rows[0] for key, rows in found.items() if len(rows) == 1 and None not in key}
        failed = False
        cells_old, cells_new = cells(old), cells(new)
        for key in sorted(set(cells_old) & set(cells_new)):
            (name, i, x), (_, _, y) = cells_old[key], cells_new[key]
            for bound in ("start_volume_bounds_m3", "end_volume_bounds_m3", "true_end_volume_bounds_m3"):
                if bound in x and bound in y:
                    failed |= self._disjoint(where + (name, i, bound), x[bound], y[bound], "1-E",
                                             "DESIGN_1E_GRAPH_ENCLOSURES_DISJOINT", results, consumed, cell_id=key)
        faces_old, faces_new = faces(old), faces(new)
        for key in sorted(set(faces_old) & set(faces_new), key=repr):
            (i, x), (_, y) = faces_old[key], faces_new[key]
            failed |= self._disjoint(where + ("selected_face_representatives", i, "volume_bounds_m3"),
                                     x["volume_bounds_m3"], y["volume_bounds_m3"], "1-E",
                                     "DESIGN_1E_GRAPH_FACE_ENCLOSURES_DISJOINT", results, consumed)
        if not failed and old != new:
            self._add(results, consumed, "REVIEW", "DESIGN_1E_NO_PROPAGATED_BOUND", where, "1-E", consume=False)

    def forcing(self, where, old, new, results, consumed):
        """Row 1-E FAIL-only control on one differential pressure forcing (DP:203-226, DP:505-521; the dumped
        certification force). Each cut_face_certificates bounds_n_m row encloses one plate's cut-face moment;
        both arms enclose the same value when, in each arm, the forcing ran on that arm's interval (geometry_id
        is its interval_id, DP:411), the interval's non-pose inputs are identical and FORCING_INPUTS are
        identical. Rows pair by (cell_id, axis, end, plate_id) of the native cut box, never by certificate_id
        (it hashes interval_id). reservoir_imposed_cut_torque_n_m is their per-plate sum. The width test stays
        REVIEW (moment met semantics unverified). Never PASS; nothing is consumed."""
        ids = [self.context[arm].get("interval_id") for arm in ("before", "after")]
        if not (self.differential_route() is not None and self.motion and all(type(i) is str for i in ids) and
                old.get("geometry_id") == ids[0] and new.get("geometry_id") == ids[1] and
                all(identical(old.get(k), new.get(k)) for k in FORCING_INPUTS)):
            if old != new:
                self._add(results, consumed, "REVIEW", "DESIGN_1E_FORCING_INPUTS_NOT_PROVED", where, "1-E",
                          consume=False)
            return

        def certificates(record):
            rows = record["cut_face_certificates"]
            need(type(rows) is list and all(type(r) is dict and type(r.get("bounds_n_m")) is list for r in rows),
                 "cut face certificate layout")
            found = {}
            for index, row in enumerate(rows):
                found.setdefault(json.dumps([row.get(k) for k in ("cell_id", "axis", "end", "plate_id")]),
                                 []).append((str(index), row))
            return {key: rows[0] for key, rows in found.items() if len(rows) == 1}
        failed = False
        rows_old, rows_new = certificates(old), certificates(new)
        for key in sorted(set(rows_old) & set(rows_new)):
            (i, x), (_, y) = rows_old[key], rows_new[key]
            for k, (p, r) in enumerate(zip(x["bounds_n_m"], y["bounds_n_m"], strict=True)):
                failed |= self._disjoint(where + ("cut_face_certificates", i, "bounds_n_m", str(k)), p, r, "1-E",
                                         "DESIGN_1E_CUT_TORQUE_DISJOINT", results, consumed, face=key)
        name = "reservoir_imposed_cut_torque_n_m"
        exact_old, exact_new = old["exact_torque_bounds"], new["exact_torque_bounds"]
        need(type(exact_old) is dict and type(exact_new) is dict, "exact torque bounds layout")
        if name in exact_old and name in exact_new:
            for j, (row_old, row_new) in enumerate(zip(exact_old[name], exact_new[name], strict=True)):
                for k, (p, r) in enumerate(zip(row_old, row_new, strict=True)):
                    failed |= self._disjoint(where + ("exact_torque_bounds", name, str(j), str(k)), p, r, "1-E",
                                             "DESIGN_1E_CUT_TORQUE_DISJOINT", results, consumed, plate_index=j)
        if not failed and old != new:
            self._add(results, consumed, "REVIEW", "DESIGN_1E_NO_PROPAGATED_BOUND", where, "1-E", consume=False)

    # -- family 2: E pose consumers outside E (records transient or unreachable in the selected base)
    def _pose_pair(self, where, old, new, names, rows, results, consumed):
        """C1/C2/C4 on (quaternion, operator bound) under the E route, then the rotation row; True if both PASS."""
        qname, pname, rname = names
        route = self.route("E")
        qb, qa = _vec(old[qname], 4), _vec(new[qname], 4)
        pb, pa = source_exact(old[pname]), source_exact(new[pname])
        need(pb >= 0 and pa >= 0, "negative operator error bound")
        dq = sum(((x-y)**2 for x, y in zip(qa, qb, strict=True)), Fraction(0))
        if route == "identical" or pa == pb == 0:
            ok = qa == qb and pa == pb
        else:
            ok = pa >= pb and (pa-pb)*2**11 < pb and 16*dq <= (pa-pb)**2
        for name in (qname, pname):
            self._add(results, consumed, "PASS" if ok else "FAIL", "DESIGN_QUATERNION_C1_C2_C4" if ok else
                      "DESIGN_QUATERNION_RULE_VIOLATION", where + (name,), rows[0])
        if not ok:
            return False
        rb, ra = _matrix(old[rname]), _matrix(new[rname])
        if rb != rotation_of(qb) or ra != rotation_of(qa):
            # Within each arm R = M(q)/|q|^2 exactly, hence R R^T = I exactly.
            self._add(results, consumed, "FAIL", "DESIGN_ROTATION_NOT_FROM_QUATERNION", where + (rname,), rows[1])
            return False
        if pb >= 4:
            if ra != rb:
                self._add(results, consumed, "REVIEW", "DESIGN_ROTATION_RADIUS_UNDEFINED", where + (rname,), rows[1])
            return False
        radius = (pa-pb)/(1-pb/4)
        deltas = [y-x for row_a, row_b in zip(ra, rb, strict=True) for y, x in zip(row_a, row_b, strict=True)]
        ok = all(abs(d) <= radius for d in deltas) and sum((d*d for d in deltas), Fraction(0)) <= 3*radius*radius
        self._add(results, consumed, "PASS" if ok else "FAIL", "DESIGN_ROTATION_WITHIN_RADIUS" if ok else
                  "DESIGN_ROTATION_RADIUS_VIOLATION", where + (rname,), rows[1])
        return ok

    def boundary_pose(self, where, old, new, results, consumed):
        """Rows 2.1-2.3 on one DifferentialBoundaryPose record (D:778-800; transient in the selected route)."""
        if self.route("DG") != "identical" or self.route("E") is None or any(
                not identical(old.get(k), new.get(k)) for k in ("boundary_rotations", "requested_operator_error")):
            if old != new:
                self._add(results, consumed, "REVIEW", "DESIGN_2_PRECONDITION_DIFFERS", where, "2.1", consume=False)
            return
        if not self._pose_pair(where, old, new, ("representative_quaternion", "pose_operator_error_bound",
                                                 "rotation_matrix"), ("2.1", "2.2"), results, consumed):
            return
        steps = [_vec(step["angular_velocity_rad_s"]) for step in old["boundary_rotations"]]
        same = common_axis(_matrix(old["rotation_matrix"]), steps) == common_axis(_matrix(new["rotation_matrix"]), steps)
        self._add(results, consumed, "PASS" if same else "FAIL", "DESIGN_2_3_AXIS_CERTIFICATE_EQUAL" if same else
                  "DESIGN_2_3_AXIS_CERTIFICATE_CHANGED", where, "2.3", consume=False)

    def force_pose(self, where, old, new, results, consumed):
        """Row 2.6 on one CurrentForcePose record (P:112-122): no production caller in the base."""
        self._add(results, consumed, "REVIEW", "DESIGN_2_6_CURRENT_FORCE_POSE_REACHED", where, "2.6", consume=False)
        if self.route("E") is None or any(not identical(old.get(k), new.get(k))
                                          for k in ("trajectory_id", "requested_operator_error")):
            return
        self._pose_pair(where, old, new, ("representative_quaternion", "operator_error_bound",
                                          "representative_rotation"), ("2.6", "2.6"), results, consumed)

    def force_background(self, where, old, new, results, consumed):
        """Row 2.8 record part on one CurrentForceBackground snapshot (P:176-212). The force/resistance arrays
        are snapshot arrays outside this record: the array route judges them (REVIEW)."""
        self._add(results, consumed, "REVIEW", "DESIGN_2_8_CURRENT_FORCE_BACKGROUND_REACHED", where, "2.8",
                  consume=False)
        if self.route("E") is None or any(not identical(old.get(k), new.get(k)) for k in (
                "exterior_balance_id", "exterior_prepared_id", "angular_rate_l2_bound_s_inv",
                "requested_torque_error_n_m", "requested_power_error_w")):
            return
        pose_old, pose_new = old["pose"], new["pose"]
        need(type(pose_old) is dict and type(pose_new) is dict, "background pose layout differs")
        if not identical(pose_old.get("trajectory_id"), pose_new.get("trajectory_id")) or not self._pose_pair(
                where + ("pose",), pose_old, pose_new, ("representative_quaternion", "operator_error_bound",
                                                        "representative_rotation"), ("2.6", "2.6"), results, consumed):
            return
        rate = source_exact(old["angular_rate_l2_bound_s_inv"])
        terms = {}
        for arm, record, pose in (("before", old, pose_old), ("after", new, pose_new)):
            residual = sum((abs(source_exact(v)) for v in record["force_projection_residual_n_m"]), Fraction(0))
            matrix = sum((abs(source_exact(v)) for row in record["resistance_projection_residual_j_s"] for v in row),
                         Fraction(0))
            force, operator, power = (source_exact(record[k]) for k in (
                "force_error_bound_n_m", "resistance_operator_error_bound_j_s", "power_error_bound_w"))
            terms[arm] = (source_exact(pose["operator_error_bound"]), force-residual, operator-matrix,
                          power == force*rate+operator*rate**2)
        (pb, fb, mb, wb), (pa, fa, ma, wa) = terms["before"], terms["after"]
        # P:197-199: force_error = p*sum|f| + sum|res| and matrix_error = 2p*sum|M| + sum|mres|, with f and
        # M the same in both arms (identical balance and prepared ids): cross-multiplied, no division.
        ok = wb and wa and fa*pb == fb*pa and ma*pb == mb*pa and (pb > 0 or (fb == fa == 0 and mb == ma == 0))
        for name in ("force_error_bound_n_m", "resistance_operator_error_bound_j_s", "power_error_bound_w"):
            self._add(results, consumed, "PASS" if ok else "FAIL", "DESIGN_2_8_ERROR_IDENTITIES" if ok else
                      "DESIGN_2_8_ERROR_IDENTITY_VIOLATION", where + (name,), "2.8")

    # -- families 1b and 4: the E thermal mesh (E on its reviewed transform, W reviewed or identical)
    def mesh(self, where, old, new, results, consumed):
        """Rows 4.2-4.7, 1b-A and 1b-D on one E thermal mesh record (E:549-755; width wr2 E:603-811)."""
        if DIFFERENTIAL_FAMILY in (old.get("physical_geometry_family"), new.get("physical_geometry_family")):
            # M meshes (ACTIVE on the dump): row 5.10 is the existing per-arm Addendum E header rule. This adds
            # its exact form by producer: the base M stores the exact group total T (M:733,
            # M:1016); the width M stores _stored_deviation(T, width) (wr2 M:32-42, applied at 694 and 974).
            for arm, record, pin in (("before", old, self.pins["M"][0]), ("after", new, self.pins["M"][1])):
                if pin not in (M_SOURCE, M_ROUNDED):
                    continue
                checked = derive_header_total(record, DESIGN_MODULES["M"], pin)
                if checked["verdict"] != "PASS":
                    continue        # the existing per-arm rule reports it
                total, width = source_exact(checked["exact_total"]), source_exact(record[WIDTH])
                expected = total if pin == M_SOURCE else stored_deviation(total, width)
                if source_exact(record[DEVIATION]) != expected:
                    self._add(results, consumed, "FAIL", "DESIGN_5_10_EXACT_HEADER_FORMULA", where + (DEVIATION,),
                              "5.10", consume=False, arm=arm)
            return
        e_route = self.route("E")
        if e_route is None or self.route("W") is None or any(not identical(old.get(k), new.get(k))
                                                             for k in E_INVOCATION_INPUTS):
            if old != new:
                self._add(results, consumed, "REVIEW", "DESIGN_4_PRECONDITION_DIFFERS", where, "4.2", consume=False)
            return
        add = self._add
        static = True
        for name in E_STATIC_HEADER:
            if not identical(old.get(name), new.get(name)):
                static = False      # an encoding-only change (5 and 5.0) is no FAIL, but it is no static premise
                if old.get(name) != new.get(name):
                    add(results, consumed, "FAIL", "DESIGN_4_2_POSE_INDEPENDENT_CHANGED", where + (name,), "4.2")

        def cells(record):
            rows = record["cells"]
            need(type(rows) is list and all(type(c) is dict and type(c.get("cell_id")) is str and
                                            c.get("kind") in ("collar", "exterior") for c in rows), "E cell layout")
            found = {c["cell_id"]: (str(i), c) for i, c in enumerate(rows)}
            need(len(found) == len(rows), "duplicate E cell identity")
            return found
        cells_old, cells_new = cells(old), cells(new)
        paired = sorted(set(cells_old) & set(cells_new))
        exterior = []
        for key in paired:
            (i, x), (j, y) = cells_old[key], cells_new[key]
            here = i == j      # a field is consumable only at one concrete path in both arms
            for name in sorted((set(x) | set(y)) - set(CELL_METRICS)):
                if x.get(name) != y.get(name):
                    add(results, consumed, "FAIL", "DESIGN_4_2_POSE_INDEPENDENT_CHANGED", where + ("cells", i, name),
                        "4.2", consume=here)
            if x.get("kind") != y.get("kind"):
                continue
            if x["kind"] == "collar":
                for name in CELL_METRICS[:4]:
                    if x.get(name) != y.get(name):
                        add(results, consumed, "FAIL", "DESIGN_4_2_COLLAR_CHANGED", where + ("cells", i, name), "4.2",
                            consume=here)
            else:
                exterior.append((key, i, here, x, y))
        kinds = [{key for key, (_, c) in found.items() if c["kind"] == "exterior"} for found in (cells_old, cells_new)]
        bounds_same = all(identical(x["physical_volume_bounds_m3"], y["physical_volume_bounds_m3"])
                          for _, _, _, x, y in exterior)
        members = kinds[0] == kinds[1]
        if not members:
            add(results, consumed, "FAIL" if bounds_same else "REVIEW", "DESIGN_4_2_MEMBERSHIP_CHANGED" if bounds_same
                else "DESIGN_4_2_MEMBERSHIP_WITH_CHANGED_BOUNDS", where + ("cells",), "4.2", consume=False)
        elif ([c["cell_id"] for c in old["cells"] if c["cell_id"] in cells_new] !=
              [c["cell_id"] for c in new["cells"] if c["cell_id"] in cells_old]):
            add(results, consumed, "FAIL", "DESIGN_4_2_CELL_ORDER_CHANGED", where + ("cells",), "4.2", consume=False)
        if {k for k, (_, c) in cells_old.items() if c["kind"] == "collar"} != \
                {k for k, (_, c) in cells_new.items() if c["kind"] == "collar"}:
            add(results, consumed, "FAIL", "DESIGN_4_2_COLLAR_CELLS_CHANGED", where + ("cells",), "4.2", consume=False)
        # 1b-A: no step with a nonzero rate leaves every W pose step at delta 0, so W never rounds.
        zero_motion = all(not any(_vec(s["angular_velocity_rad_s"])) for s in old["trajectory_segments"])
        if zero_motion and static:
            for _, i, here, x, y in exterior:
                same = x["physical_volume_bounds_m3"] == y["physical_volume_bounds_m3"]
                add(results, consumed, "PASS" if same else "FAIL", "DESIGN_1B_A_ZERO_MOTION_IDENTITY" if same else
                    "DESIGN_1B_A_ZERO_MOTION_BOUNDS_CHANGED", where + ("cells", i, "physical_volume_bounds_m3"),
                    "1b-A", consume=here)
        # 4.1 prerequisite: the existing E pose rows (C1-C4 on stored = 4e under the named proof), pb < 4 and E's
        # per-arm norm band. The header stores no rotation, so r_R rests on the band, which C1-C4 do not imply.
        # Every E arm keeps it (E:738, wr2 E:793 store _representative_pose's pair), so a violation is FAIL.
        qb, qa = _vec(old["representative_quaternion"], 4), _vec(new["representative_quaternion"], 4)
        pb, pa = source_exact(old["pose_operator_error_bound"]), source_exact(new["pose_operator_error_bound"])
        dq = sum(((x-y)**2 for x, y in zip(qa, qb, strict=True)), Fraction(0))
        if e_route == "identical" or pa == pb == 0:
            pose = (identical(old["representative_quaternion"], new["representative_quaternion"]) and
                    identical(old["pose_operator_error_bound"], new["pose_operator_error_bound"]))
        else:
            pose = pa >= pb and (pa-pb)*2**11 < pb and 16*dq <= (pa-pb)**2
        outside = [arm for arm, q, p in (("before", qb, pb), ("after", qa, pa)) if not within_norm_band(q, p)]
        if outside:
            add(results, consumed, "FAIL", "DESIGN_4_1_QUATERNION_NORM_OUTSIDE_BAND",
                where + ("representative_quaternion",), "4.1", consume=False, arms=outside)
        radius = (pa-pb)/(1-pb/4) if pose and not outside and pb < 4 and static else None
        width = source_exact(old[WIDTH])
        tables = old["support_tables"]
        sums, nonvacuous, lohi_same = [], True, members
        for _, i, here, x, y in exterior:
            vb, va = source_exact(x["volume_m3"]), source_exact(y["volume_m3"])
            need(vb > 0 and va > 0, "non-positive E cell volume")
            lohi = identical(x["physical_volume_bounds_m3"], y["physical_volume_bounds_m3"])
            lohi_same = lohi_same and lohi
            dev_b, dev_a = source_exact(x[DEVIATION]), source_exact(y[DEVIATION])
            for value, cell, arm in ((dev_b, x, "before"), (dev_a, y, "after")):
                lo, hi = _vec(cell["physical_volume_bounds_m3"], 2)
                v = source_exact(cell["volume_m3"])
                if value != max(abs(v-lo), abs(v-hi)):
                    add(results, consumed, "FAIL", "DESIGN_4_6_WITHIN_ARM_IDENTITY", where + ("cells", i, DEVIATION),
                        "4.6", consume=here, arm=arm)
            if radius is None:
                for name in ("volume_m3", "centroid_m", DEVIATION):
                    if x[name] != y[name]:
                        add(results, consumed, "REVIEW", "DESIGN_4_POSE_PREREQUISITE_NOT_MET", where + ("cells", i, name),
                            "4.3", consume=False)
                nonvacuous = False
                continue
            refs = x["physical_support"]
            need(type(refs) is dict and identical(refs, y["physical_support"]), "E cell support refs differ")
            cone, voxel = tables["cones"][refs["cone_id"]], tables["voxels"][refs["voxel_id"]]
            need(type(cone) is list and len(cone) >= 3, "E cone layout")
            lower, upper, origin = _vec(voxel["lower_m"]), _vec(voxel["upper_m"]), _vec(voxel["origin_m"])
            basis = tuple(tuple(Fraction(v) if type(v) is int else source_exact(v) for v in row) for row in voxel["basis"])
            need(len(basis) == 3 and all(len(row) == 3 for row in basis), "E voxel basis layout")
            o = [sum((basis[k][j]*origin[k] for k in range(3)), Fraction(0)) for j in range(3)]
            rho2 = sum((max((lower[j]+o[j])**2, (upper[j]+o[j])**2) for j in range(3)), Fraction(0))
            diag2 = sum(((upper[j]-lower[j])**2 for j in range(3)), Fraction(0))
            # F4-3 BINDING CORRECTION: S_c = N_c*r_R*min((8/3)*rho^3, 2*rho*D^2), checked squared.
            s2 = len(cone)**2*radius**2*rho2*min(Fraction(64, 9)*rho2**2, 4*diag2**2)
            small = s2 < min(va, vb)**2        # non-vacuity: PASS only if S_c < min(V_a, V_b)
            nonvacuous = nonvacuous and small
            sums.append(s2)

            def judge(changed, violated, code, name, row, small=small, i=i, here=here):
                if not changed:
                    verdict = "PASS"
                elif violated:
                    verdict = "FAIL"
                else:
                    verdict = "PASS" if small else "REVIEW"
                add(results, consumed, verdict, code + ("_VIOLATION" if verdict == "FAIL" else "_VACUOUS"
                    if verdict == "REVIEW" else ""), where + ("cells", i, name), row, consume=here)
            judge(va != vb, (va-vb)**2 > s2, "DESIGN_4_3_VOLUME", "volume_m3", "4.3")
            cb, ca = _vec(x["centroid_m"]), _vec(y["centroid_m"])
            gap = sum(((p-r)**2 for p, r in zip(ca, cb, strict=True)), Fraction(0))
            judge(ca != cb, gap*max(va, vb)**2 > diag2*s2, "DESIGN_4_4_CENTROID", "centroid_m", "4.4")
            if lohi:
                judge(dev_a != dev_b, (dev_a-dev_b)**2 > s2, "DESIGN_4_6_DEVIATION", DEVIATION, "4.6")
            elif dev_a != dev_b:
                add(results, consumed, "REVIEW", "DESIGN_4_6_BOUNDS_CHANGED", where + ("cells", i, DEVIATION), "4.6",
                    consume=False)
        # Header: 4.7 within-arm identities, then 1b-D (exact rule (ce)) or the 4.7 cross-arm bound.
        header = where + (DEVIATION,)
        hb, ha = source_exact(old[DEVIATION]), source_exact(new[DEVIATION])
        totals = []
        for arm, record, found, pin in (("before", old, cells_old, self.pins["E"][0]), ("after", new, cells_new,
                                                                                       self.pins["E"][1])):
            total = sum((source_exact(c[DEVIATION]) for _, c in found.values() if c["kind"] == "exterior"), Fraction(0))
            totals.append(total)
            expected = total if pin == E_SOURCE else stored_deviation(total, width) if pin == E_ROUNDED else None
            if expected is None or source_exact(record[DEVIATION]) != expected:
                add(results, consumed, "FAIL" if expected is not None else "REVIEW", "DESIGN_4_7_HEADER_IDENTITY",
                    header, "4.7", arm=arm)
                return
        if members and all(identical(x[DEVIATION], y[DEVIATION]) for _, _, _, x, y in exterior):
            expected = hb if e_route == "identical" else stored_deviation(hb, width)
            add(results, consumed, "PASS" if ha == expected else "FAIL", "DESIGN_1B_D_RULE_CE" if ha == expected else
                "DESIGN_1B_D_RULE_CE_VIOLATION", header, "1b-D")
        elif ha != hb:
            if not (lohi_same and radius is not None):
                add(results, consumed, "REVIEW", "DESIGN_4_7_PRECONDITION_NOT_MET", header, "4.7")
                return
            # |dH| <= sum S_c + 2**-64 sum dev_a holds without non-vacuity (4.6 under identical lo, hi), so the
            # FAIL uses the upper sqrt bounds; a PASS also needs every cell non-vacuous and the lower bounds.
            bounds = [sqrt_bounds(s2) for s2 in sums]
            low, high = sum((b[0] for b in bounds), Fraction(0)), sum((b[1] for b in bounds), Fraction(0))
            excess = totals[1]/2**64
            gap = abs(ha-hb)
            if gap > high+excess:
                add(results, consumed, "FAIL", "DESIGN_4_7_HEADER_BOUND_VIOLATION", header, "4.7")
            elif gap <= low+excess and nonvacuous:
                add(results, consumed, "PASS", "DESIGN_4_7_HEADER_WITHIN_BOUND", header, "4.7")
            else:
                add(results, consumed, "REVIEW", "DESIGN_4_7_SQRT_PRECISION" if nonvacuous else
                    "DESIGN_4_7_VACUOUS", header, "4.7")

    # -- family 5: the composed heat record (heat helpers untransformed; closure parity)
    def heat_route(self):
        """The selected private heat route in both arms: closure parity, each joined heat reference on the heat
        method, and identical consumer_sources, which pin the r13 issuer and forward kernel bytes (r6:37-41,
        63-66, 155). Package parity alone does not see these profile-bound helpers."""
        refs = [self.context[arm].get("heat_reference") for arm in ("before", "after")]
        return bool(self.parity and all(type(r) is dict and r.get("method_id") == HEAT_METHOD for r in refs) and
                    identical(refs[0].get("consumer_sources"), refs[1].get("consumer_sources")))

    def heat(self, where, old, new, results, consumed):
        """Rows 5.6, 5.7a, 5.8 and 5.9 on one composed heat record (issuer r13:633-648)."""
        add, arms = self._add, (("before", old), ("after", new))
        plans = [self.context[arm].get("heat_plan") for arm, _ in arms]
        # 5.6: the zero-source policy books no added heat, so the source energy is exactly 0 in each arm.
        path = where + ("exact_source_energy_j",)
        if self.parity and all(r.get("source_policy") == ZERO_SOURCE_POLICY and type(r.get("caller_snapshot")) is dict
                               and r["caller_snapshot"].get("source_policy") == ZERO_SOURCE_POLICY for _, r in arms):
            bad = [arm for arm, r in arms if r.get("exact_source_energy_j") != ["0x0", "0x1"]]
            add(results, consumed, "FAIL" if bad else "PASS", "DESIGN_5_6_SOURCE_ENERGY_NOT_ZERO" if bad else
                "DESIGN_5_6_ZERO_SOURCE", path, "5.6", arms=bad)
        else:
            add(results, consumed, "REVIEW", "DESIGN_5_6_SOURCE_POLICY_NOT_ZERO_SOURCE", path, "5.6")
        # 5.8: a caller-supplied target with provenance, unaffected by pose.
        name = "independently_supplied_absolute_residual_target"
        path = where + (name,)
        need(name in old and name in new, "heat target missing")
        if old[name] == new[name]:
            add(results, consumed, "PASS", "DESIGN_5_8_TARGET_EQUAL", path, "5.8")
        elif None in plans or not identical(plans[0].get("original_target"), plans[1].get("original_target")):
            add(results, consumed, "REVIEW", "DESIGN_5_8_DECLARED_TARGETS_DIFFER", path, "5.8")
        elif not self.heat_route():
            add(results, consumed, "REVIEW", "DESIGN_5_8_ROUTE_NOT_ESTABLISHED", path, "5.8")
        else:
            add(results, consumed, "FAIL", "DESIGN_5_8_TARGET_CHANGED", path, "5.8")
        # 5.7a: no Dirichlet face, so the finisher fixes each one-owner face at its declared energy dt*v.
        name = "exact_outward_boundary_energy_j"
        path = where + (name,)
        declared, issue, failed = [], None, []
        for (arm, record), plan in zip(arms, plans, strict=True):
            if record.get("private_correction_method_id") != FINISHER:
                issue = "DESIGN_5_7_FINISHER_NOT_ESTABLISHED"
                break
            if type(plan) is not dict or plan.get("geometry_id") != record.get("geometry_id"):
                issue = "DESIGN_5_7_PLAN_NOT_BOUND"
                break
            boundary = plan["boundary"]
            need(type(boundary) is dict and all(type(e) is list and len(e) == 2 and e[0] in ("power", "temperature")
                                                for e in boundary.values()), "heat plan boundary layout")
            if any(e[0] == "temperature" for e in boundary.values()):
                issue = "DESIGN_5_7B_DIRICHLET_FACE"
                break
            dt, total = exact(record["duration_s"]), Fraction(0)
            faces = self.context[arm].get("one_owner_faces")
            for face, (_, value) in boundary.items():
                if exact(value) == 0:
                    continue
                if faces is None or self.context[arm].get("thermal_mesh_id") != record.get("geometry_id"):
                    issue = "DESIGN_5_7_INCIDENCE_NOT_BOUND"
                    break
                if face in faces:
                    total += dt*exact(value)
            if issue:
                break
            declared.append(total)
            if source_exact(record[name]) != total:
                failed.append(arm)
        if failed:
            add(results, consumed, "FAIL", "DESIGN_5_7A_OUTWARD_NOT_DECLARED", path, "5.7a", arms=failed)
        elif issue:
            if old[name] != new[name]:
                add(results, consumed, "REVIEW", issue, path, "5.7a")
        elif declared[0] != declared[1]:
            add(results, consumed, "REVIEW", "DESIGN_5_7A_DECLARED_DIFFER", path, "5.7a")
        else:
            add(results, consumed, "PASS", "DESIGN_5_7A_DECLARED_OUTWARD", path, "5.7a")
        # 5.9 BINDING CORRECTION: bitwise equality under identical inputs PASSes; a difference there is
        # REVIEW, not FAIL (decisions 4 and 11 are not extended to heat). Inactive on the differential
        # route, where geometry_id hashes the rounded M header.
        if (self.parity and plans[0] is not None and identical(plans[0], plans[1]) and
                all(identical(old.get(k), new.get(k)) for k in ("geometry_id", "plan_id", "duration_s"))):
            differ = [k for k in HEAT_NUMERICAL if not identical(old.get(k), new.get(k))]
            for k in differ:
                add(results, consumed, "REVIEW", "DESIGN_5_9_DIFFERENCE_UNDER_IDENTICAL_INPUTS", where + (k,), "5.9")
            if not differ:
                add(results, consumed, "PASS", "DESIGN_5_9_BITWISE_EQUAL", where, "5.9", consume=False)

    def heat_plan(self, where, old, new, results, consumed):
        """Row 5.8 on one joined heat plan descriptor (issuer r13:419-424; exchange.joined_heat_plan, r6:357-365;
        ACTIVE on the dump). The exact target is a function of the caller's original target alone (r13:107-121)
        and must be positive (r13:343-344). Equal original targets on the heat route (heat_route: parity, the
        heat method and identical consumer sources) give equal targets, else FAIL; without that route, or with
        differing original targets (caller inputs), a difference is REVIEW. _target_text is not re-implemented:
        the original target is compared by bytes only."""
        add, names = self._add, ("absolute_residual_target", "absolute_residual_target_decimal", "original_target")
        for arm, record in (("before", old), ("after", new)):
            target, text = source_exact(record["absolute_residual_target"]), record["absolute_residual_target_decimal"]
            need(type(text) is str and type(record["original_target"]) is dict, "heat plan target layout")
            if not (target > 0 and Fraction(text) == target):
                add(results, consumed, "FAIL", "DESIGN_5_8_PLAN_TARGET_INCONSISTENT",
                    where + ("absolute_residual_target",), "5.8", consume=False, arm=arm)
                return
        if all(old[k] == new[k] for k in names):
            for k in names:
                add(results, consumed, "PASS", "DESIGN_5_8_TARGET_EQUAL", where + (k,), "5.8")
        elif identical(old["original_target"], new["original_target"]) and self.heat_route():
            for k in names[:2]:
                if old[k] != new[k]:
                    add(results, consumed, "FAIL", "DESIGN_5_8_TARGET_CHANGED", where + (k,), "5.8")
        else:
            code = ("DESIGN_5_8_ROUTE_NOT_ESTABLISHED" if identical(old["original_target"], new["original_target"])
                    else "DESIGN_5_8_DECLARED_TARGETS_DIFFER")
            for k in names:
                if old[k] != new[k]:
                    add(results, consumed, "REVIEW", code, where + (k,), "5.8")

    def heat_reference(self, where, old, new, results, consumed):
        """Row 5.8 per-arm binding on one joined heat reference (r6:152-160; the dumped heat child and
        exchange.joined_heat): its original_target is that arm's plan's (r6:150-151). Ids are never compared."""
        plans = [self.context[arm].get("heat_plan") for arm in ("before", "after")]
        path = where + ("original_target",)
        if any(type(plan) is not dict for plan in plans):
            return
        bad = [arm for arm, record, plan in (("before", old, plans[0]), ("after", new, plans[1]))
               if not identical(record.get("original_target"), plan.get("original_target"))]
        if bad:
            self._add(results, consumed, "FAIL", "DESIGN_5_8_REFERENCE_TARGET_NOT_PLAN", path, "5.8", arms=bad)
        elif "original_target" in old and old.get("original_target") == new.get("original_target"):
            self._add(results, consumed, "PASS", "DESIGN_5_8_REFERENCE_TARGET_EQUAL", path, "5.8")

    def audit_source(self, where, rows, folders):
        """Row 5.6 on the dumped audit copy of the composed heat input source (spatial_owner:176-179; ACTIVE on
        the dump at interval 1). On the selected private route (heat method_id, consumer sources identical) the
        zero-source policy (r13:430) books no added heat, so each element is +0.0 in each arm. -0.0, another
        dtype or shape, unbound bytes or a missing array is REVIEW; any other element is FAIL. rows: per arm
        the dump's array rows; folders: per arm the dump folder (Path). The cell count is the mesh.json one."""
        path = [where, AUDIT_SOURCE]
        if not self.heat_route():
            items = [result("REVIEW", "DESIGN_5_6_ROUTE_NOT_ESTABLISHED", path=path, row="5.6")]
        else:
            items = []
            for arm in ("before", "after"):
                row = {r.get("name"): r for r in rows[arm] if type(r) is dict}.get(AUDIT_SOURCE)
                cells = self.context[arm].get("mesh_cells")
                raw = None
                if (type(row) is dict and type(cells) is int and row.get("dtype") == "<f8" and
                        row.get("shape") == [cells] and type(row.get("file")) is str):
                    raw = (folders[arm]/"arrays"/row["file"]).read_bytes()
                if raw is None or len(raw) != 8*cells or hashlib.sha256(raw).hexdigest() != row.get("sha256"):
                    items.append(result("REVIEW", "DESIGN_5_6_AUDIT_ARRAY_UNBOUND", path=path, row="5.6", arm=arm))
                    continue
                if raw.count(0) == len(raw):
                    continue
                words = {v for (v,) in struct.iter_unpack("<Q", raw) if v}
                if words - {1 << 63}:
                    items.append(result("FAIL", "DESIGN_5_6_NONZERO_SOURCE", path=path, row="5.6", arm=arm))
                else:
                    items.append(result("REVIEW", "DESIGN_5_6_NEGATIVE_ZERO", path=path, row="5.6", arm=arm))
            if not items:
                items.append(result("PASS", "DESIGN_5_6_ZERO_SOURCE_AUDIT", path=path, row="5.6"))
        for item in items:
            key = "%s:%s" % (item["row"], item["verdict"])
            self.counts[key] = self.counts.get(key, 0)+1
        return items


# ---- Field-contract addendum: a settled disposition for each design row left REVIEW above, plus the identity,
# heat-copy and module rows (G-*), for the N9 two-arm width replay only: both arms on one composition; stages root,
# adopt, i0, interval 1 and i1; interval 1 is the only interval advanced (no prior interval). Encoded here: the
# route guards (a record or field the replay route never writes gives REVIEW), row 2.4 per arm, row 2.5 as
# REVIEW without a reader-proved spatial_state_id pair (it grants no PASS beyond the walk's own equality), the
# 5.4 per-arm checks, the 5.12 and G-WU exclusions, and the G-ID and 4.9 labels with the unchanged-interval check.
# Every other row is catalogued and stays REVIEW in the walk. 1-F and G-ID stay REVIEW: no comparator-derived
# identity pairing is built. The digests pin the settled rows (reproducibility provenance); the two exclusion
# labels are copied verbatim from them.
CONTRACT_ADDENDUM = {"ADDENDUM-r1.md": "82346a996a8c188b77a854c2192b49d92effe9fcc0c81024a13008af4864b16c",
                     "rows.json": "c7e9577a113a7a7ec93fabfe0b9090886bc5e6e1a76e943e862b8214ef5ebd3c"}
NOT_REACHED, DROPPED, DERIVED, REVIEW_ROW = "NOT REACHED", "DROPPED (route)", "DERIVED", "REVIEW"
EXCLUDED_K, EXCLUDED_L = "DROPPED (excluded by D-27k)", "DROPPED (excluded by D-27l)"
GUARDS = "AddendumRows.guards"
# Every addendum row: (disposition, where it is enforced; None = catalogued, REVIEW by the walk).
ADDENDUM_ROWS = {
    "1-D": (REVIEW_ROW, GUARDS + " (route guard; the live content is G-M)"), "1-E": (REVIEW_ROW, None),
    "1-F": (REVIEW_ROW, None), "1b-B": (DROPPED, GUARDS), "1b-C": (DROPPED, GUARDS), "1b-E": (DROPPED, GUARDS),
    "1b-F": (DROPPED, GUARDS), "2.4": (DERIVED, "AddendumRows.forcing"),
    "2.5": (RULE, "AddendumRows.forcing (REVIEW without a reader-proved spatial_state_id pair)"),
    "2.9": (NOT_REACHED, GUARDS), "4.5": (DROPPED, GUARDS), "4.8": (DROPPED, GUARDS),
    "4.9": (DERIVED, "AddendumRows.mesh_identity (REVIEW by derivation: G-M is REVIEW)"),
    "3.3": (DROPPED, GUARDS), "3.4": (DROPPED, GUARDS), "3.5": (DROPPED, GUARDS), "3.7": (DROPPED, GUARDS),
    "3.9": (DROPPED, GUARDS), "3.10": (DROPPED, GUARDS), "3.11": (DROPPED, GUARDS),
    "5.1": (REVIEW_ROW, None), "5.2": (REVIEW_ROW, None), "5.3": (REVIEW_ROW, None), "5.5": (REVIEW_ROW, None),
    "5.4": (RULE, "AddendumRows.heat (exact per-arm settled energy, bound, storage and projection checks)"),
    "5.7b": (NOT_REACHED, GUARDS), "5.12": (EXCLUDED_K, "AddendumRows.heat"),
    "G-ID": (DERIVED, "AddendumRows.identities, interval_identity (REVIEW: no identity recomputation)"),
    "G-M": (REVIEW_ROW, None), "G-ALE": (REVIEW_ROW, None), "G-TRANSPORT": (REVIEW_ROW, None),
    "G-TRACE": (REVIEW_ROW, None),
    "G-WU": (EXCLUDED_L, "AddendumRows.support (no FAIL or VOID before the field pass)"),
    "G-REF": (REFUSAL_ONLY, STAGE_RULE), "G-HEATCOPY": (REVIEW_ROW, None), "G-DR253": (DROPPED, GUARDS),
    "G-DR716": (DROPPED, GUARDS), "G-EPOSE": (NOT_REACHED, GUARDS),
    "G-MOD-differential_ale": (REVIEW_ROW, None), "G-MOD-differential_coupling": (DERIVED, None),
    "G-MOD-differential_trace": (REVIEW_ROW, None), "G-MOD-dual_geometry": (REVIEW_ROW, None),
    "G-MOD-initial_parallel": (NOT_REACHED, "compare_arms i0 cascade label"),
    "G-MOD-parallel_dispatch": (REVIEW_ROW, None), "G-MOD-regional_workflow": (DERIVED, None),
    "G-MOD-spatial_owner": (REVIEW_ROW, None),
}
WALL_SCHEMA = "atlas.rigid-space-time-wall-measures.v1"
ALE_BOUNDS_SCHEMA = "atlas.source-bound-spatial-ale-bounds.v1"
SPATIAL_CORRECTION_SCHEMA = "atlas.current-spatial-pressure-correction.v1"
SUPPORT_SCHEMA = "atlas.differential-physical-support.v1"
# Row 2.5 precondition 2: forcing inputs byte-identical across arms (DP:505-521).
FORCING_25_INPUTS = ("geometry_id", "native_state_id", "funding_id", "reservoir_closure_id", "radial_datum",
                     "physical_densities", "request")
# G-ID rule (b): identities whose source record is not in the i1 dump (the dump is not extended for them).
UNDUMPED_IDS = ("partition_id", "ale_bounds_id", "bounds_id", "iteration_id", "proposal_id", "heat_id")
# The replay route's expected i0 differences besides the 5.10 mesh header (record level, never per element).
I0_CASCADE = frozenset({"geometry_id", "thermal_mesh_id", "initial_mesh_id", "owner_id", "state_id",
                        "workflow_id", "root_key"})
RESIDUALS_54 = ("exact_corrected_enthalpy_j", "exact_retained_solver_residual_j",
                "exact_stock_projection_residual_j", "exact_cell_storage_residual_j")


def _strings(value):
    """Every leaf of a nested dict/list value; None if any leaf is not a string."""
    if type(value) is str:
        return [value]
    children = value.values() if type(value) is dict else value if type(value) is list else None
    if children is None:
        return None
    found = []
    for child in children:
        leaves = _strings(child)
        if leaves is None:
            return None
        found.extend(leaves)
    return found


def _pair(value):
    """An exact [numerator, denominator] hex pair (private_heat_native_projection_r5:36), not a bare hex value."""
    return type(value) is list and len(value) == 2 and all(type(v) is str and HEX.fullmatch(v) for v in value)


def _public(value):
    """The exact value of the producer's binary64 for an exact value: integer true division, correctly rounded
    with ties to even and subnormals (private_heat_public_float_r1:14-18); None when it overflows."""
    try:
        return Fraction(value.numerator / value.denominator)
    except OverflowError:
        return None


def i0_outside(kind, names):
    """The changed walk names at i0 outside the replay route's cascade: the 5.10 mesh header and the cascade ids at
    record level (a path through a list element is never part of the cascade)."""
    allowed = {kind + "." + DEVIATION} if kind == "mesh" else set()
    return sorted(n for n in names if n not in allowed and
                  not (n.rsplit(".", 1)[-1] in I0_CASCADE and "[]" not in n.split(".")))


class AddendumRows:
    """The encoded addendum rows on one interval's record pairs (see the section comment). 'ids' are the
    comparator's reader-proved identity translations (before -> after). 'parity': no FAIL or VOID was recorded
    before the field pass; a one-arm refusal is one (the stage rule), so this is stricter than refusal parity."""

    def __init__(self, interval, ids=None, parity=False):
        self.interval, self.ids, self.parity = interval, dict(ids or {}), parity
        self.counts = {}
        self.work_units = {"before": 0, "after": 0}
        self.mesh: dict[str, dict | None] = {"before": None, "after": None}
        self.records = {}

    def summary(self):
        rows = {}
        for disposition, _ in ADDENDUM_ROWS.values():
            rows[disposition] = rows.get(disposition, 0)+1
        return dict(addendum=CONTRACT_ADDENDUM, rows=dict(sorted(rows.items())),
                    results=dict(sorted(self.counts.items())), refusal_parity=self.parity,
                    support_work_units_record_only=dict(self.work_units))

    def evaluate(self, kind, before, after):
        """(results, consumed paths) for one record pair; a byte-identical record is passed as both arms."""
        shared = before is after
        self.records = {"before": before, "after": after}
        if kind == "mesh":
            for arm, record in self.records.items():
                # Keep only the independently dumped mesh identity and signed incidence.
                self.mesh[arm] = None
                if type(record) is dict and record.get("schema") == MESH_SCHEMA:
                    cells, faces = record.get("cells"), record.get("faces")
                    if type(cells) is list and type(faces) is list:
                        self.mesh[arm] = dict(geometry_id=record.get("geometry_id"),
                            cells=[{k: c.get(k) for k in ("cell_id", "faces")} if type(c) is dict else c
                                   for c in cells],
                            face_ids=[f.get("face_id") if type(f) is dict else None for f in faces])
        results, consumed = [], set()
        for arm, record in (("both", before),) if shared else (("before", before), ("after", after)):
            results.extend(self.guards((kind,), record, arm))
            for support in _locate(record, {SUPPORT_SCHEMA}).get(SUPPORT_SCHEMA, {}).values():
                if type(support.get("work_units")) is int:
                    for name in ("before", "after") if shared else (arm,):
                        self.work_units[name] += support["work_units"]
        schemas = frozenset({FORCING_SCHEMA, HEAT_SCHEMA, SUPPORT_SCHEMA, DG_SCHEMA, MESH_SCHEMA})
        found = [_locate(before, schemas), _locate(after, schemas)]
        methods = {FORCING_SCHEMA: self.forcing, HEAT_SCHEMA: self.heat, SUPPORT_SCHEMA: self.support,
                   DG_SCHEMA: self.interval_identity, MESH_SCHEMA: self.mesh_identity}
        for schema, method in methods.items():
            a, b = found[0].get(schema, {}), found[1].get(schema, {})
            if schema == MESH_SCHEMA:
                # Only the logical mesh record itself, never a compact stored copy inside another record (as 5.10).
                a, b = ({(): x[()]} if () in x and kind == "mesh" else {} for x in (a, b))
            for path in sorted(set(a) & set(b)):
                items, taken = [], set()
                try:
                    method((kind,) + path, a[path], b[path], items, taken)
                except (ContractError, AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError,
                        IndexError) as error:
                    items = [item for item in items if item["verdict"] in ("FAIL", "REVIEW")]
                    items.append(result("REVIEW", "ADDENDUM_ROW_LAYOUT_UNRECOGNISED", path=list((kind,) + path),
                                        schema=schema, reason=str(error)))
                    taken = set()
                results.extend(items)
                consumed |= taken
        if not shared:
            results.extend(self.identities(kind, before, after))
        # An exclusion scrubs a field only at one concrete path in both arms, and only where both values are
        # encoded alike position by position (encoded_alike); otherwise the field stays walked (REVIEW).
        consumed = {path for path in consumed if _exists(before, path[1:]) and _exists(after, path[1:])}
        for index, item in enumerate(results):
            path = tuple(item["path"])
            if item["verdict"] == "EXCLUDED" and (path not in consumed or not encoded_alike(
                    _value(before, path[1:]), _value(after, path[1:]))):
                results[index] = dict(item, verdict="REVIEW", code="ADDENDUM_EXCLUSION_NOT_APPLIED",
                                      excluded=item["code"])
                consumed.discard(path)
        for item in results:
            key = "%s:%s" % (item.get("row", "-"), item["verdict"])
            self.counts[key] = self.counts.get(key, 0)+1
        return results, consumed

    def guards(self, where, record, arm):
        """REVIEW for each place in one arm's record that the replay route never writes: rows 1-D (prior ray
        history, a posed_support record, a snapshot-rotated constraint with snapshot_offset_s != 0), 1b, 3.x,
        4.5, 4.8 and G-DR253/G-DR716 (a W record, an exterior_cells or wall_measure_id field, rows with inward_*
        or outward_* fields, a rigid motion, E pose header fields, a thermal mesh, ALE bounds or graph outside
        the differential family), 2.9 (current force pose,
        background or spatial pressure correction), G-EPOSE (a boundary pose record) and 5.7b (a 'temperature'
        heat face). One item per guard and arm: its first place and the number found."""
        found, pending = {}, [((), record)]

        def hit(rows, code, path):
            found.setdefault(code, [rows, list(where + path), 0])[2] += 1

        while pending:
            path, value = pending.pop()
            if type(value) is list:
                pending.extend((path + (str(i),), child) for i, child in enumerate(value))
                continue
            if type(value) is not dict:
                continue
            schema, family = value.get("schema"), value.get("physical_geometry_family")
            # A family field outside the differential one, or none on the dumped record itself. A nested record
            # without a family field is exempt (a narrowing of the settled note): the differential producers
            # write the family on the bounds and the graph themselves (differential_ale:806-807); the W route's
            # bounds carry wall_measure_id (spatial_ale:591-594), which the wall-field guard reports anywhere.
            foreign = family != DIFFERENTIAL_FAMILY and (family is not None or path == ())
            if schema == POSED_SUPPORT_SCHEMA:
                hit("1-D", "ADDENDUM_1D_POSED_SUPPORT_RECORD", path)
            if schema == BOUNDARY_POSE_SCHEMA:
                hit("G-EPOSE", "ADDENDUM_G_EPOSE_BOUNDARY_POSE_RECORD", path)
            if schema in (FORCE_POSE_SCHEMA, FORCE_BACKGROUND_SCHEMA, SPATIAL_CORRECTION_SCHEMA):
                hit("2.9", "ADDENDUM_2_9_CURRENT_FORCE_RECORD", path)
            if schema == WALL_SCHEMA:
                hit("1b-B,1b-C,1b-E,1b-F,3.3-3.11,G-DR716", "ADDENDUM_1B_3X_W_RECORD", path)
            if schema == MESH_SCHEMA and where == ("mesh",) and foreign:
                hit("4.5,4.8", "ADDENDUM_4_E_MESH_RECORD", path)
            if schema == MESH_SCHEMA and any(key in value for key in E_POSE_FIELDS):
                hit("4.5,4.8", "ADDENDUM_4_E_POSE_FIELD", path)
            if schema == GRAPH_SCHEMA and foreign:
                hit("1b-E,1b-F,G-DR253", "ADDENDUM_1B_GRAPH_NOT_DIFFERENTIAL", path)
            if schema == ALE_BOUNDS_SCHEMA and foreign:
                hit("1b-B,1b-C,1b-E,1b-F,4.5,4.8", "ADDENDUM_1B_4_BOUNDS_NOT_DIFFERENTIAL", path)
            rays = value.get("rays") if schema == DG_SCHEMA else None
            for name, ray in (rays.items() if type(rays) is dict else
                              enumerate(rays) if type(rays) is list else ()):
                if type(ray) is dict and ray.get("prior_rotations"):
                    hit("1-D", "ADDENDUM_1D_PRIOR_RAY_HISTORY", path + ("rays", str(name), "prior_rotations"))
            if value.get("kind") == "snapshot-rotated" and "snapshot_offset_s" in value:
                try:
                    late = exact(value["snapshot_offset_s"]) != 0
                except ContractError:
                    late = True
                if late:
                    hit("1-D", "ADDENDUM_1D_SNAPSHOT_OFFSET_NOT_ZERO", path + ("snapshot_offset_s",))
            if schema == HEAT_PLAN_SCHEMA and type(value.get("boundary")) is dict:
                if any(type(e) is list and e[:1] == ["temperature"] for e in value["boundary"].values()):
                    hit("5.7b", "ADDENDUM_5_7B_DIRICHLET_FACE", path + ("boundary",))
            for key, child in value.items():
                # Only W routes write wall_measure_id (spatial_ale:594, E:735,950, current_force_pose:115) and a
                # rigid motion (regional_collar3d:627); only W (wall_measures:697) and the collar's finite exterior
                # heat plan (exterior_heat:142) write exterior_cells. RD:588-589 writes current_background only
                # when a current background exists.
                if key == "wall_measure_id" or (key == "rigid_motion" and child is not None):
                    hit("1b-B,1b-C,1b-E,1b-F,4.5,4.8,G-DR253", "ADDENDUM_1B_4_WALL_FIELD", path + (key,))
                elif key == "current_background":
                    hit("2.9", "ADDENDUM_2_9_CURRENT_BACKGROUND", path + (key,))
                elif key == "exterior_cells":
                    hit("3.3-3.11,G-DR716", "ADDENDUM_3X_EXTERIOR_CELLS", path + (key,))
                elif key == "rows" and any(
                        type(row) is dict and any(type(name) is str and name.startswith(("inward_", "outward_"))
                                                  for name in row)
                        for row in (child.values() if type(child) is dict else
                                    child if type(child) is list else ())):
                    # Settled note 3.3-3.11: any rows/*/inward_* or rows/*/outward_* path; no differential-route
                    # writer of such rows was found.
                    hit("3.3-3.11,G-DR716", "ADDENDUM_3X_EXTERIOR_ROWS", path + (key,))
                pending.append((path + (key,), child))
        return [result("REVIEW", code, path=place, row=rows, arm=arm, found=count)
                for code, (rows, place, count) in sorted(found.items())]

    # -- 2.4 and 2.5: the interval-1 forcing, posed only at the accepted-start static geometry on this route
    def forcing(self, where, old, new, results, consumed):
        """Row 2.4 in each arm (every boundary_pose_ids entry is that arm's geometry_id, DP:284) and row 2.5 as
        REVIEW attribution: precondition 1 (2.4), 2 (FORCING_25_INPUTS identical) and 3 (spatial_state_id equal
        or a reader-proved pair). Neither row grants a PASS: equality is the walk's. Nothing is consumed."""
        posed = []
        for arm, record in (("before", old), ("after", new)):
            leaves = _strings(record.get("boundary_pose_ids"))
            if leaves is None or any(leaf != record.get("geometry_id") for leaf in leaves):
                posed.append(arm)
        if posed:
            self._add(results, "REVIEW", "ADDENDUM_2_4_POSE_ID_NOT_GEOMETRY", where + ("boundary_pose_ids",),
                      "2.4,G-EPOSE", arms=posed)
        if old.get("geometry_id") != new.get("geometry_id"):
            self._add(results, "REVIEW", "ADDENDUM_2_4_GEOMETRY_DIFFERS", where + ("geometry_id",), "2.4")
        if old is new or identical(old, new):
            return
        spatial = [old.get("spatial_state_id"), new.get("spatial_state_id")]
        if posed:
            code = "ADDENDUM_2_5_PRECONDITION_2_4"
        elif not all(identical(old.get(k), new.get(k)) for k in FORCING_25_INPUTS):
            code = "ADDENDUM_2_5_INPUTS_DIFFER"
        elif not (type(spatial[0]) is str and spatial[0] and
                  (spatial[0] == spatial[1] or self.ids.get(spatial[0]) == spatial[1])):
            code = "ADDENDUM_2_5_NO_SPATIAL_STATE_PAIR"
        elif not identical(dict(old, spatial_state_id=spatial[1]), new):
            code = "ADDENDUM_2_5_FORCING_DIFFERS"
        else:
            return
        self._add(results, "REVIEW", code, where, "2.5")

    # -- 5.4 (per arm) and 5.12 (the projection resource policy, excluded)
    def settled_heat(self, where, arm, record, corrected, retained, projection, storage, target, results):
        """Bind one arm's captured stocks and zero sources to its independently dumped mesh.

        Pair cell/face axes by their stored identities, never by values or a recomputed identity.
        The heat metadata's sibling arrays are the native projection's captured inputs/outputs.
        A total source of zero alone cannot establish zero in each cell.
        """
        mesh = self.mesh[arm]
        geometry = record.get("geometry_id")
        if not (type(geometry) is str and geometry and type(mesh) is dict and
                mesh.get("geometry_id") == geometry):
            self._add(results, "REVIEW", "ADDENDUM_5_4_GEOMETRY_UNBOUND", where, "5.4", arm=arm)
            return False
        path = where[1:]
        parent = _value(self.records[arm], path[:-1]) if path and path[-1] == "metadata" else None
        arrays = parent.get("arrays") if type(parent) is dict and parent.get("metadata") is record else None
        names = ("input_enthalpy_j", "enthalpy_j", "input_source_w")
        if not (type(arrays) is dict and all(type(arrays.get(k)) is list and
                len(arrays[k]) == len(corrected) for k in names)):
            self._add(results, "REVIEW", "ADDENDUM_5_4_CAPTURED_ARRAYS_UNBOUND", where, "5.4", arm=arm)
            return False
        old, stored, sources = ([exact(v) for v in arrays[k]] for k in names)
        source_total = record.get("exact_source_energy_j")
        if not (_pair(source_total) and source_exact(source_total) == 0 and all(v == 0 for v in sources)):
            self._add(results, "REVIEW", "ADDENDUM_5_4_ZERO_SOURCE_UNPROVED", where, "5.4", arm=arm)
            return False
        cell_ids, face_ids = record.get("cell_ids"), record.get("face_ids")
        energies = record.get("exact_paired_face_energy_j")
        cells, mesh_faces = mesh["cells"], mesh["face_ids"]
        if not (type(cell_ids) is list and len(cell_ids) == len(corrected) and
                all(type(v) is str and v for v in cell_ids) and len(set(cell_ids)) == len(cell_ids) and
                type(face_ids) is list and all(type(v) is str and v for v in face_ids) and
                len(set(face_ids)) == len(face_ids) and type(energies) is list and
                len(energies) == len(face_ids) and all(_pair(v) for v in energies) and
                all(type(c) is dict and type(c.get("cell_id")) is str and type(c.get("faces")) is list
                    for c in cells) and len(cells) == len(cell_ids) and
                len({c["cell_id"] for c in cells}) == len(cells) and
                {c["cell_id"] for c in cells} == set(cell_ids) and
                all(type(v) is str and v for v in mesh_faces) and len(set(mesh_faces)) == len(mesh_faces) and
                set(mesh_faces) == set(face_ids)):
            self._add(results, "REVIEW", "ADDENDUM_5_4_AXES_UNBOUND", where, "5.4", arm=arm)
            return False
        face_energy = dict(zip(face_ids, map(source_exact, energies), strict=True))
        incidence = {c["cell_id"]: c["faces"] for c in cells}
        for links in incidence.values():
            if not (links and all(type(link) is list and len(link) == 2 and type(link[0]) is str and
                    link[0] in face_energy and type(link[1]) is int and link[1] in (-1, 1) for link in links)
                    and len({link[0] for link in links}) == len(links)):
                self._add(results, "REVIEW", "ADDENDUM_5_4_SIGNED_INCIDENCE_UNBOUND", where, "5.4", arm=arm)
                return False
        bad = {}
        for i, cell_id in enumerate(cell_ids):
            outward = sum((sign * face_energy[f] for f, sign in incidence[cell_id]), Fraction(0))
            expected = corrected[i] - old[i] + outward  # source is independently proved zero above
            if retained[i] != expected:
                bad.setdefault("ADDENDUM_5_4_SETTLED_ENERGY_IDENTITY", i)
            if stored[i] != _public(corrected[i]) or projection[i] != stored[i] - corrected[i]:
                bad.setdefault("ADDENDUM_5_4_CAPTURED_PROJECTION_IDENTITY", i)
            round_bound = abs(stored[i]) / 2**53 + Fraction(1, 2**1075)
            if abs(projection[i]) > round_bound or abs(storage[i]) > target + round_bound:
                bad.setdefault("ADDENDUM_5_4_ROUNDING_ENCLOSURE", i)
        for code, i in sorted(bad.items()):
            self._add(results, "FAIL", code, where, "5.4", arm=arm, cell_index=i)
        return not bad

    def heat(self, where, old, new, results, consumed):
        """Exact per-arm 5.4: R=new-old+out-src, P=Q(stored)-new, S=R+P and the settled enclosures.

        Mesh geometry/axes and sibling captured arrays must be bound; an absent proof stays REVIEW.
        Equal violations in both arms FAIL. Only the three residual fields are excluded when both
        arms pass; corrected energy (5.1), face energy (5.3) and cumulative heat (5.5) stay walked.
        Row 5.12 excludes only the projection resource policy, subject to the common encoding veto.
        """
        valid = True
        for arm, record in (("before", old), ("after", new)):
            lists = [record.get(name) for name in RESIDUALS_54]
            target = record.get("independently_supplied_absolute_residual_target")
            if not (all(type(x) is list and all(_pair(v) for v in x) for x in lists) and
                    len({len(x) for x in lists}) == 1 and _pair(target)):
                self._add(results, "REVIEW", "ADDENDUM_5_4_LAYOUT_NOT_DECODED", where, "5.4", arm=arm)
                valid = False
                continue
            target = source_exact(target)
            corrected, retained, projection, storage = ([source_exact(v) for v in x] for x in lists)
            bad = {}
            for i, (n, r, p, s) in enumerate(zip(corrected, retained, projection, storage, strict=True)):
                if abs(r) > target:
                    bad.setdefault("ADDENDUM_5_4_RETAINED_ABOVE_TARGET", i)
                if s != r + p:
                    bad.setdefault("ADDENDUM_5_4_STORAGE_NOT_RETAINED_PLUS_PROJECTION", i)
                if _public(n) != n + p:
                    bad.setdefault("ADDENDUM_5_4_PROJECTION_NOT_ROUNDING", i)
            for code, i in sorted(bad.items()):
                self._add(results, "FAIL", code, where, "5.4", arm=arm, cell_index=i)
            # Do not short-circuit the identity on a preceding per-arm violation.
            settled = self.settled_heat(where, arm, record, corrected, retained, projection, storage, target, results)
            valid = valid and not bad and settled
        if valid:
            for name in RESIDUALS_54[1:]:
                self._add(results, "EXCLUDED", "ADDENDUM_5_4_PER_ARM_EXACT", where + (name,), "5.4", consumed)
        if "projection_resource_policy" in old and "projection_resource_policy" in new:
            self._add(results, "EXCLUDED", "ADDENDUM_5_12_EXCLUDED",
                      where + ("projection_resource_policy",), "5.12", consumed)

    # -- G-WU (work units: cost figures, excluded as values while refusal counts are equal)
    def support(self, where, old, new, results, consumed):
        """G-WU: a support record's work_units are excluded as values while no FAIL or VOID precedes the field
        pass (refusal parity). Per-arm totals are record-only (summary). The identity cascade they feed
        (support_id, interval_id) stays G-ID REVIEW."""
        if self.parity and type(old.get("work_units")) is int and type(new.get("work_units")) is int:
            self._add(results, "EXCLUDED", "ADDENDUM_G_WU_EXCLUDED", where + ("work_units",), "G-WU",
                      consumed)

    # -- G-ID and 4.9 labels
    def interval_identity(self, where, old, new, results, consumed):
        """G-ID negative 2: at interval 1 the width arm's interval_id must differ (rounding re-derives it)."""
        if self.interval == 1 and old.get("interval_id") is not None and \
                old.get("interval_id") == new.get("interval_id"):
            self._add(results, "REVIEW", "ADDENDUM_G_ID_INTERVAL_UNCHANGED", where + ("interval_id",), "G-ID")

    def mesh_identity(self, where, old, new, results, consumed):
        """4.9: a differing mesh geometry_id is REVIEW by derivation, its content rows (G-M) being REVIEW."""
        if old.get("geometry_id") != new.get("geometry_id"):
            self._add(results, "REVIEW", "ADDENDUM_4_9_DERIVED_FROM_REVIEW_CONTENT", where + ("geometry_id",),
                      "4.9,G-ID")

    def identities(self, kind, old, new):
        """G-ID rule (b): an UNDUMPED_IDS identity that differs at one concrete path in both arms, with its
        first path and count (its source record is not in the dump). Rule (c): a reader-proved pair is
        no difference."""
        found, pending = {}, [((kind,), old, new)]
        while pending:
            path, x, y = pending.pop()
            if type(x) is dict and type(y) is dict:
                for key in sorted(x.keys() & y.keys()):
                    if key in UNDUMPED_IDS and x[key] != y[key] and not (
                            type(x[key]) is str and self.ids.get(x[key]) == y[key]):
                        found.setdefault(key, [list(path + (key,)), 0])[1] += 1
                    pending.append((path + (key,), x[key], y[key]))
            elif type(x) is list and type(y) is list:
                pending.extend((path + (str(i),), u, v) for i, (u, v) in enumerate(zip(x, y, strict=False)))
        return [result("REVIEW", "ADDENDUM_G_ID_SOURCE_NOT_DUMPED", path=place, row="G-ID", key=key, found=count)
                for key, (place, count) in sorted(found.items())]

    @staticmethod
    def _add(results, verdict, code, path, row, consumed=None, **details):
        results.append(result(verdict, code, path=list(path), row=row, **details))
        if consumed is not None and verdict == "EXCLUDED":
            consumed.add(tuple(path))
