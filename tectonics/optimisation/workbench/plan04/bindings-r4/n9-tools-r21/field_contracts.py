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
# Source-proved E pose rows (Plan04 bindings r1). Both reviewed E builders store
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


def refusal_result(before, after):
    if type(before) is not bool or type(after) is not bool:
        return result("REVIEW", "MISSING_PROVED_REFUSAL_OUTCOME")
    return result("FAIL" if before != after else "PASS",
                  "REFUSAL_FLIP" if before != after else "NO_REFUSAL_FLIP")


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
