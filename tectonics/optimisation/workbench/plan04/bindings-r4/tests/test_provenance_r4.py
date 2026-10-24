"""Focused controls for the Plan 04 r4 producer provenance.

Static inputs only: real package source trees (p1820c-r4 baseline, c/wr2 W/E/M for the
width arm) and small synthetic W/E records built to the producers' own relations.
No runtime import, no interval data.
usage: python -B test_provenance_r4.py [-v]
"""
import hashlib
import importlib.util
import json
import os
import unittest
from fractions import Fraction as Q
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = Path(os.environ.get("ATLAS_T", "."))       # private source root; the controls skip without it
R4 = T / "ac/p1820c-r4/src/atlas_tectonics"
WR2 = T / "ps/c/wr2/src/atlas_tectonics"
spec = importlib.util.spec_from_file_location("field_provenance_r4", HERE.parent / "n9-tools-r21/field_provenance.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
WIDTH = ("integration_wall_measures.py", "integration_exterior_mesh.py", "integration_differential_mesh.py")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root, replace=None, extra=None, drop=()):
    """Inventory + exact bytes of one package tree (keys like atlas_tectonics/x.py)."""
    files = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel not in drop:
            files["atlas_tectonics/" + rel] = path.read_bytes()
    for rel, raw in (replace or {}).items():
        files["atlas_tectonics/" + rel] = raw
    for rel, raw in (extra or {}).items():
        files["atlas_tectonics/" + rel] = raw
    pins = {name: sha(raw) for name, raw in files.items()}
    scanned = P.source_paths(pins)
    return pins, {name: files[name] for name in scanned}


def width_arm(replace=None, **kw):
    merged = {name: (WR2 / name).read_bytes() for name in WIDTH}
    merged.update(replace or {})
    return tree(R4, replace=merged, **kw)


def assess(before, after, records=None, pairs=(), manifests=None):
    manifests = manifests or {"before": sha(b"m-before"), "after": sha(b"m-after")}
    records = records or {"before": {}, "after": {}}
    return P.assess_records(manifests, {"before": before[0], "after": after[0]},
                            {"before": before[1], "after": after[1]}, records, list(pairs))


def codes(result, slot=None):
    return {P.code_of(issue) for row in result["receipts"] if slot in (None, row["slot"]) for issue in row["issues"]}


REVIEWED = ["W.wall-normal", "W.volume-plane-normal", "W.inverse-grid-vertex", "E.representative-quaternion",
            "E.pose-operator-error", "D.ray-box", "D.pose-binding", "D.source-planes", "D.boundary-leaf",
            "D.constraint-pose", "D.posed-boundary", "P.current-force-pose"]


def require_sources():
    if not (R4 / "integration_wall_measures.py").is_file() or not (WR2 / "integration_wall_measures.py").is_file():
        raise unittest.SkipTest("ATLAS_T source root with the r4 and wr2 trees is required")


class Catalog(unittest.TestCase):
    """Package-wide call-site catalog on the real r4 and width-arm sources."""
    @classmethod
    def setUpClass(cls):
        require_sources()
        cls.base, cls.width = tree(R4), width_arm()

    def test_real_sites_and_width_verdict(self):
        result = assess(self.base, self.width)
        self.assertEqual(result["mandatory_slots"], REVIEWED)
        self.assertEqual(result["verdict"], "REVIEW")
        by = {row["slot"]: row for row in result["receipts"]}
        for slot in REVIEWED:
            self.assertEqual(by[slot]["binding"]["relation"], "n9-rounding", slot)
        for slot in ("D.ray-box", "D.pose-binding", "D.source-planes", "D.boundary-leaf", "D.constraint-pose",
                     "D.posed-boundary", "P.current-force-pose"):
            self.assertEqual(set(by[slot]["issues"]), {"POSE_CONSUMER_NO_PROPAGATED_BOUND"}, slot)
        self.assertEqual(len(by["D.constraint-pose"]["arms"]["after"]["call_sites"]), 2)
        self.assertIn("NO_READER_BOUND_W_OUTPUT", codes(result, "W.wall-normal"))
        self.assertIn("NO_READER_BOUND_E_OUTPUT", codes(result, "E.representative-quaternion"))
        self.assertNotIn("FAIL", {row["verdict"] for row in result["receipts"]})

    def test_identity_control_is_bound(self):
        result = assess(self.base, self.base)
        self.assertEqual(result["verdict"], "BOUND", result["issues"])
        self.assertEqual({row["binding"]["relation"] for row in result["receipts"]}, {"identity"})

    def test_reversed_pair_not_proved(self):
        result = assess(self.width, self.base)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("SOURCE_PAIR_NOT_PROVED", codes(result, "D.ray-box"))

    def test_unknown_producer_bytes(self):
        raw = (WR2 / "integration_wall_measures.py").read_bytes() + b"\n# edited\n"
        after = tree(R4, replace={"integration_wall_measures.py": raw})
        result = assess(self.base, after)
        self.assertIn("UNREVIEWED_SELECTED_PRODUCER", codes(result, "W.wall-normal"))
        self.assertEqual(result["verdict"], "REVIEW")

    def test_unreviewed_accesses(self):
        probes = {
            "zz_ref.py": (b"from . import integration_wall_measures as W\nf = W._pose_vector\n",
                          "PRODUCER_REFERENCED_NOT_CALLED"),
            "zz_call.py": (b"from . import integration_wall_measures as W\ndef g(v):\n"
                           b"    return W._pose_vector(v, 0, 0, 0, 0, None)\n", "UNREVIEWED_CALL_SITE"),
            "zz_dyn.py": (b"from . import integration_wall_measures as W\ndef g(n):\n    return getattr(W, n)\n",
                          "DYNAMIC_PRODUCER_MODULE_ACCESS"),
            "zz_from.py": (b"from .integration_exterior_mesh import _representative_pose as rp\n"
                           b"def g(s, q):\n    return rp(s, q, None)\n", "UNREVIEWED_CALL_SITE"),
            "zz_star.py": (b"from .integration_wall_measures import *\n", "STAR_IMPORT_FROM_PRODUCER_MODULE"),
            "zz_attr.py": (b"def g(m, v):\n    return m._representative_pose(v, 1, None)\n",
                           "UNRESOLVED_PRODUCER_ATTRIBUTE"),
            # Refuter r4 escapes: each now surfaces.
            "zz_rebind.py": (b"from . import integration_wall_measures as W\nM = W\n", "PRODUCER_MODULE_ESCAPES"),
            "zz_passed.py": (b"from . import integration_wall_measures as W\ndef g(f):\n    return f(W)\n",
                             "PRODUCER_MODULE_ESCAPES"),
            "zz_import_module.py": (b"import importlib\ndef g():\n"
                                    b"    return importlib.import_module('atlas_tectonics.integration_exterior_mesh')\n",
                                    "PRODUCER_MODULE_NAME_STRING"),
            "zz_attrgetter.py": (b"import operator\nf = operator.attrgetter('_pose_vector')\n", "PRODUCER_NAME_STRING"),
            "zz_dunder.py": (b"from . import integration_wall_measures as W\ndef g(n):\n"
                             b"    return W.__getattribute__(n)\n", "DYNAMIC_PRODUCER_MODULE_ACCESS"),
            "zz_setattr.py": (b"from . import integration_wall_measures as W\ndef g(f):\n"
                              b"    setattr(W, '_pose' + '_vector', f)\n", "DYNAMIC_PRODUCER_MODULE_ACCESS"),
            "zz_reexport.py": (b"from .integration_wall_measures import _pose_vector as rotate\n", "PRODUCER_REEXPORTED"),
            "zz_relayed.py": (b"from .zz_relay import _representative_pose\n", "PRODUCER_NAME_IMPORTED_FROM_NON_PRODUCER"),
            "zz_globals.py": (b"from . import integration_wall_measures as W\ndef g(n):\n    return globals()[n]\n",
                              "DYNAMIC_PRODUCER_NAMESPACE_ACCESS"),
            "zz_fixture.py": (b"from ._fixtures.tests import i04_fixtures\n", "IMPORT_FROM_EXCLUDED_PATH"),
        }
        for name, (raw, code) in probes.items():
            with self.subTest(name):
                result = assess(self.base, width_arm(extra={name: raw}))
                family = "E" if b"exterior" in raw or b"_representative_pose" in raw else "W"
                self.assertIn(family + ".unreviewed-access", result["mandatory_slots"])
                self.assertIn(code, codes(result, family + ".unreviewed-access"))
                self.assertEqual(result["verdict"], "REVIEW")

    def test_renamed_relay_surfaces_at_the_relay(self):
        # The consumer alone is an ordinary import; the relay's module-level binding is the re-export.
        extra = {"zz_relay.py": b"from .integration_wall_measures import _pose_vector as rotate\n",
                 "zz_user.py": b"from .zz_relay import rotate\ndef g(v):\n    return rotate(v, 0, 0, 0, 0, None)\n"}
        result = assess(self.base, width_arm(extra=extra))
        issues = next(row for row in result["receipts"] if row["slot"] == "W.unreviewed-access")["issues"]
        self.assertTrue(any("zz_relay.py" in issue and issue.endswith("PRODUCER_REEXPORTED") for issue in issues))
        self.assertEqual(result["verdict"], "REVIEW")

    def test_relays_names_and_writes_surface_under_identity(self):
        # Each form reaches producer code the per-module scan does not see, so even identical arms stay
        # REVIEW. A relay through another module's binding is judged as a direct read would be.
        hub = {"zz_hub.py": b"from . import integration_wall_measures as W\n"}

        def user(body, head=b"from . import zz_hub as X\n"):
            return dict(hub, **{"zz_user.py": head + body})
        overlap = b"from . import integration_volume_overlap as O\n"
        probes = {
            "global-import": ({"zz_g.py": b"def install():\n    global pv\n"
                               b"    from .integration_wall_measures import _pose_vector as pv\n"},
                              "PRODUCER_REEXPORTED"),
            "docstring": ({"zz_d.py": b'"""integration_wall_measures _pose_vector"""\nimport importlib\n'
                           b"def g():\n    m, n = __doc__.split()\n"
                           b"    return getattr(importlib.import_module('atlas_tectonics.' + m), n)\n"},
                          "PRODUCER_NAME_STRING"),
            "name-dunder": ({"zz_n.py": hub["zz_hub.py"] + b"import importlib\n"
                             b"def g():\n    return importlib.import_module(W.__name__)._endpoint_volume\n"},
                            "DYNAMIC_PRODUCER_MODULE_ACCESS"),
            "class-module": ({"zz_c.py": b"class C:\n    from . import integration_wall_measures as W\n"},
                             "PRODUCER_REEXPORTED"),
            "relay-route": (user(b"def g(*a):\n    return X.W.measure_walls(*a)\n"), "PRODUCER_MODULE_RELAYED"),
            "relay-from": (user(b"def g(*a):\n    return W.measure_walls(*a)\n", b"from .zz_hub import W\n"),
                           "PRODUCER_MODULE_RELAYED"),
            "relay-getattr": (user(b"def g(n):\n    return getattr(X, n)\n"), "PRODUCER_MODULE_RELAYED"),
            "relay-alias": (user(b"def g(*a):\n    w = X.W\n    return w.enclose_rotating_wall(*a)\n"),
                            "PRODUCER_MODULE_RELAYED"),
            "relay-escape": (user(b"def g(f):\n    return f(X.W)\n"), "PRODUCER_MODULE_RELAYED"),
            "relay-namespace": (user(b"def g(n):\n    return X.__dict__[n]\n"), "PRODUCER_MODULE_RELAYED"),
            "relay-import-module": (user(b"def g(*a):\n    return importlib.import_module('atlas_tectonics.zz_hub')"
                                         b".W.measure_walls(*a)\n", b"import importlib\n"),
                                    "PRODUCER_MODULE_RELAYED"),
            "relay-relative-import": (user(b"def g(*a):\n    return importlib.import_module('.zz_hub', __package__)"
                                           b".W.measure_walls(*a)\n", b"import importlib\n"),
                                      "PRODUCER_MODULE_RELAYED"),
            "relay-sys-modules": (user(b"def g(*a):\n    hub = sys.modules[__package__ + '.zz_hub']\n"
                                       b"    return hub.W.measure_walls(*a)\n", b"import sys\n"),
                                  "PRODUCER_MODULE_RELAYED"),
            "relay-star": (user(b"def g(*a):\n    return W.measure_walls(*a)\n", b"from .zz_hub import *\n"),
                           "PRODUCER_MODULE_RELAYED"),
            "write-sys-modules": (user(b"sys.modules['atlas_tectonics.zz_hub'] = None\n", b"import sys\n"),
                                  "PACKAGE_MODULE_MUTATED"),
            "write-attribute": ({"zz_w.py": overlap + b"O._cross = lambda a, b: (0, 0, 0)\n"},
                                "PACKAGE_MODULE_MUTATED"),
            "write-setattr": ({"zz_w.py": hub["zz_hub.py"] + b"def g(f):\n    setattr(W, '_rotated_normal', f)\n"},
                              "PACKAGE_MODULE_MUTATED"),
            "write-vars": ({"zz_w.py": overlap + b"def g(f):\n    vars(O)['_cross'] = f\n"},
                           "PACKAGE_MODULE_MUTATED"),
            "write-alias": (user(b"def g(f):\n    w = X.W\n    w._q = f\n"), "PACKAGE_MODULE_MUTATED"),
        }
        for name, (extra, code) in probes.items():
            with self.subTest(name):
                arm = self.base_with(extra)
                result = assess(arm, arm)
                self.assertIn(code, codes(result, "W.unreviewed-access"))
                self.assertEqual(result["verdict"], "REVIEW")
        # Ordinary members read through a relay, or a relay module's own text dunders, stay bound.
        for body in (b"def g(t):\n    return X.W._decode(t)\n", b"def g(t):\n    w = X.W\n    return w._decode(t)\n",
                     b"def g():\n    return X.__file__, hasattr(X, 'W')\n",
                     b"import sys\ndef g(t):\n    return sys.modules[__name__].X.W._q(t)\n"):
            with self.subTest(body):
                arm = self.base_with(user(body))
                result = assess(arm, arm)
                self.assertEqual(result["verdict"], "BOUND", result["issues"])

    def test_producer_bindings_roots_scopes_and_text_surface_under_identity(self):
        # Round 3: W read through E's own module binding, modules read through names bound to the import
        # machinery, aliases in class or nonlocal scope, source text run in place and namespace writes.
        hub = {"zz_hub.py": b"from . import integration_wall_measures as W\n"}
        call = b".W.measure_walls(*a)\n"
        overlap = b"from . import integration_volume_overlap as O\n"
        probes = {
            "producer-binding": ({"zz_p.py": b"from . import integration_exterior_mesh as E\n"
                                  b"def g(*a):\n    return E.W.measure_walls(*a)\n"}, "PRODUCER_MODULE_RELAYED"),
            "producer-binding-from": ({"zz_p.py": b"from .integration_exterior_mesh import W as M\n"
                                       b"def g(*a):\n    return M.measure_walls(*a)\n"}, "PRODUCER_MODULE_RELAYED"),
            "producer-binding-alias": ({"zz_p.py": b"from . import integration_exterior_mesh as E\nM = E.W\n"
                                        b"def g(*a):\n    return M.measure_walls(*a)\n"}, "PRODUCER_MODULE_RELAYED"),
            "root-import-module-name": (dict(hub, **{"zz_r.py": b"from importlib import import_module as load\n"
                                                     b"def g(*a):\n    return load('atlas_tectonics.zz_hub')" + call}),
                                        "PRODUCER_MODULE_RELAYED"),
            "root-modules-name": (dict(hub, **{"zz_r.py": b"from sys import modules\n"
                                               b"def g(*a):\n    return modules['atlas_tectonics.zz_hub']" + call}),
                                  "PRODUCER_MODULE_RELAYED"),
            "root-modules-alias": (dict(hub, **{"zz_r.py": b"import sys\nm = sys.modules\n"
                                                b"def g(*a):\n    return m.get('atlas_tectonics.zz_hub')" + call}),
                                   "PRODUCER_MODULE_RELAYED"),
            "root-package-keyword": (dict(hub, **{"zz_sub/__init__.py": b"", "zz_sub/zz_k.py":
                                                  b"import importlib\ndef g(*a):\n    return importlib.import_module("
                                                  b"'.zz_hub', package='atlas_tectonics')" + call}),
                                     "PRODUCER_MODULE_RELAYED"),
            "root-computed-package": (dict(hub, **{"zz_sub/__init__.py": b"", "zz_sub/zz_k.py":
                                                   b"import importlib\ndef g(p, *a):\n    return importlib."
                                                   b"import_module('.zz_hub', package=p)" + call}),
                                      "PRODUCER_MODULE_RELAYED"),
            "root-link-name": (dict(hub, **{"zz_r.py": b"import importlib\nfrom . import zz_hub as X\n"
                                            b"def g(*a):\n    return importlib.import_module(X.__name__)" + call}),
                               "PRODUCER_MODULE_RELAYED"),
            "root-relative-dunder-import": (dict(hub, **{"zz_r.py": b"def g(*a):\n    return __import__('zz_hub', "
                                                         b"globals(), None, ['W'], 1)" + call}),
                                            "PRODUCER_MODULE_RELAYED"),
            "class-alias": (dict(hub, **{"zz_c.py": b"from . import zz_hub as X\nclass K:\n    M = X.W\n"
                                         b"    def g(self, *a):\n        return self.M.measure_walls(*a)\n"}),
                            "PRODUCER_MODULE_RELAYED"),
            "class-alias-write": ({"zz_c.py": overlap + b"class K:\n    M = O\nK.M._cross = None\n"},
                                  "PACKAGE_MODULE_MUTATED"),
            "nonlocal-alias": (dict(hub, **{"zz_n.py": b"from . import zz_hub as X\ndef outer(*a):\n    w = None\n"
                                            b"    def bind():\n        nonlocal w\n        w = X.W\n"
                                            b"    bind()\n    return w.measure_walls(*a)\n"}),
                               "PRODUCER_MODULE_RELAYED"),
            "code-text": ({"zz_t.py": b"exec('import atlas_tectonics.integration_volume_overlap as O; "
                                      b"O._cross = None')\n"}, "DYNAMIC_CODE_TEXT"),
            "code-text-name": ({"zz_t.py": b"_T = 'import atlas_tectonics.integration_volume_overlap as O; "
                                           b"O._cross = None'\nexec(_T)\n"}, "DYNAMIC_CODE_TEXT"),
            "code-text-attribute": ({"zz_t.py": b"class K:\n    T = b'import atlas_tectonics.integration_volume_overlap'"
                                                b"\ndef g():\n    exec(K.T)\n"}, "DYNAMIC_CODE_TEXT"),
            "code-text-alias": ({"zz_t.py": b"_T = f'import atlas_tectonics.integration_volume_overlap'\n_U = _T\n"
                                            b"def g():\n    exec(compile(source=_U, filename='t', mode='exec'))\n"},
                                "DYNAMIC_CODE_TEXT"),
            "write-namespace-method": ({"zz_w.py": overlap + b"def g(f):\n    vars(O).update(_cross=f)\n"},
                                       "PACKAGE_MODULE_MUTATED"),
            "write-dunder-method": ({"zz_w.py": overlap + b"def g(f):\n    object.__setattr__(O, '_cross', f)\n"},
                                    "PACKAGE_MODULE_MUTATED"),
            "write-operator": ({"zz_w.py": b"import operator\n" + overlap +
                                b"def g(f):\n    operator.setitem(O.__dict__, '_cross', f)\n"}, "PACKAGE_MODULE_MUTATED"),
        }
        for name, (extra, code) in probes.items():
            with self.subTest(name):
                arm = self.base_with(extra)
                result = assess(arm, arm)
                self.assertIn(code, codes(result, "W.unreviewed-access"))
                self.assertEqual(result["verdict"], "REVIEW")
        # Ordinary reads through E's bindings, class attributes holding plain functions, frozen-dataclass
        # setters and compile of read source stay bound.
        for body in (b"from . import integration_exterior_mesh as E\ndef g(a, b):\n    return E.O._dot(a, b)\n",
                     overlap + b"class K:\n    dot = O._dot\n",
                     b"class K:\n    def __init__(self):\n        object.__setattr__(self, 'x', 1)\n",
                     b"def g(raw, name):\n    return compile(raw, name, 'exec')\n",
                     b"def g(path):\n    raw = path.read_bytes()\n    return compile(raw, str(path), 'exec')\n"):
            with self.subTest(body):
                arm = self.base_with({"zz_b.py": body})
                result = assess(arm, arm)
                self.assertEqual(result["verdict"], "BOUND", result["issues"])

    def test_alias_fan_out_is_bounded(self):
        # Each alias statement follows at most ALIAS_ORIGINS origins: these 40 + 64 self-rebinding aliases
        # gave 40 * 64**3 (about 10.5 million) relay reads before the cap.
        text = (b"from . import integration_volume as V\n" + b"".join(b"x = V.a%d\n" % i for i in range(40)) +
                b"".join(b"x = x.b%d\n" % j for j in range(64)))
        relays = P._scan(text, None, {}, "atlas_tectonics/zz_a.py",
                         frozenset({"atlas_tectonics", "atlas_tectonics.integration_volume"}))[6]
        self.assertLess(len(relays), 100_000)
        arm = self.base_with({"zz_a.py": text})
        self.assertEqual(assess(arm, arm)["verdict"], "BOUND")

    def test_too_deep_inputs_fail_integrity(self):
        deep = b"[" * 100000 + b"]" * 100000
        records = {"before": {"k": {"identity": sha(deep), "raw": deep}}, "after": {}}
        long_sum = self.base_with({"zz_long.py": b"x = " + b"+".join([b"1"] * 5000) + b"\n"})
        for label, after, recs in (("record", self.base, records), ("source", long_sum, None)):
            with self.subTest(label):
                result = assess(self.base, after, recs)
                self.assertEqual((result["verdict"], result["code"]), ("FAIL", "PROVENANCE_INPUT_INTEGRITY"))

    def test_shadowing_sources_fail_integrity(self):
        # Python imports a package directory or an extension module ahead of x.py.
        pins, data = self.base
        for key in ("integration_wall_measures/__init__.py", "integration_wall_measures/__init__.pyc",
                    "integration_wall_measures.cp311-win_amd64.pyd", "integration_volume.so"):
            with self.subTest(key):
                key, raw = "atlas_tectonics/" + key, b"x = 1\n"
                after = (dict(pins, **{key: sha(raw)}), dict(data, **({key: raw} if key.endswith(".py") else {})))
                result = assess(self.base, after)
                self.assertEqual((result["verdict"], result["code"]), ("FAIL", "PROVENANCE_INPUT_INTEGRITY"))
        cache = (dict(pins, **{"atlas_tectonics/__pycache__/integration_wall_measures.cpython-311.pyc": sha(b"x")}),
                 data)
        self.assertEqual(assess(cache, cache)["verdict"], "BOUND")

    def test_consequence_routes(self):
        # E builders and spatial ALE call W functions that reach W._pose_vector: no joined record covers them.
        result = assess(self.base, self.width)
        by = {row["slot"]: row for row in result["receipts"]}

        def routes(slot):
            return {issue for issue in by[slot]["issues"] if issue.endswith(":POSE_CONSEQUENCE_ROUTE_UNBOUND")}
        volume = {"%s:%s->_endpoint_volume:POSE_CONSEQUENCE_ROUTE_UNBOUND" % (arm, site) for arm in ("before", "after")
                  for site in ("integration_exterior_mesh.py:build_exterior_mesh",
                               "integration_exterior_mesh.py:_build_exterior_mesh_record",
                               "integration_spatial_ale.py:enclose_spatial_ale")}
        wall = {arm + ":integration_spatial_ale.py:enclose_spatial_ale->enclose_rotating_wall:"
                "POSE_CONSEQUENCE_ROUTE_UNBOUND" for arm in ("before", "after")}
        self.assertEqual(routes("W.volume-plane-normal"), volume)
        self.assertEqual(routes("W.wall-normal"), wall)
        self.assertEqual(routes("W.inverse-grid-vertex"), set())
        self.assertEqual(len(by["W.volume-plane-normal"]["arms"]["after"]["consequence_routes"]), 4)
        same = assess(self.base, self.base)
        self.assertFalse(any(issue.endswith("POSE_CONSEQUENCE_ROUTE_UNBOUND") for issue in same["issues"]))

    def test_dependency_closure_change_is_review(self):
        raw = (R4 / "integration_volume.py").read_bytes() + b"\n# edited\n"
        for before, after in ((self.base, width_arm(replace={"integration_volume.py": raw})),
                              (self.base, tree(R4, replace={"integration_volume.py": raw}))):
            result = assess(before, after)
            self.assertEqual(result["verdict"], "REVIEW")
            for slot in ("W.wall-normal", "E.representative-quaternion", "D.ray-box"):
                row = next(r for r in result["receipts"] if r["slot"] == slot)
                self.assertIn("atlas_tectonics/integration_volume.py:PRODUCER_DEPENDENCY_SOURCE_CHANGED", row["issues"])
                self.assertIsNone(row["binding"]["relation"])
        # The W and E transforms are tolerated inside the shared closure; the M transform is tolerated in
        # none, so an unchanged module that imports it withdraws the relation.
        plain = next(r for r in assess(self.base, self.width)["receipts"] if r["slot"] == "W.wall-normal")
        self.assertEqual(plain["binding"]["relation"], "n9-rounding")
        self.assertFalse(any(i.endswith("PRODUCER_DEPENDENCY_SOURCE_CHANGED") for i in plain["issues"]))
        bridge = (R4 / "integration_volume.py").read_bytes() + b"\n\ndef _zz():\n    from . import integration_differential_mesh\n"
        result = assess(tree(R4, replace={"integration_volume.py": bridge}),
                        width_arm(replace={"integration_volume.py": bridge}))
        for slot in ("W.wall-normal", "E.representative-quaternion"):
            row = next(r for r in result["receipts"] if r["slot"] == slot)
            self.assertEqual([i for i in row["issues"] if i.endswith("PRODUCER_DEPENDENCY_SOURCE_CHANGED")],
                             ["atlas_tectonics/integration_differential_mesh.py:PRODUCER_DEPENDENCY_SOURCE_CHANGED"])
            self.assertIsNone(row["binding"]["relation"])

    def test_inventory_keys_are_canonical(self):
        pins, data = self.width
        for bad in ("/abs/atlas_tectonics/zz.py", "C:/x/atlas_tectonics/zz.py", "atlas_tectonics/../zz.py",
                    "atlas_tectonics\\zz.py", "atlas_tectonics//zz.py"):
            with self.subTest(bad):
                result = assess(self.base, (dict(pins, **{bad: sha(b"x = 1\n")}), dict(data, **{bad: b"x = 1\n"})))
                self.assertEqual((result["verdict"], result["code"]), ("FAIL", "PROVENANCE_INPUT_INTEGRITY"))
        # An excluded directory name above the package directory never drops a module from the scan.
        raw, key = b"from . import integration_wall_measures as W\nf = W._pose_vector\n", "tests/atlas_tectonics/zz.py"
        result = assess(self.base, (dict(pins, **{key: sha(raw)}), dict(data, **{key: raw})))
        self.assertIn("PRODUCER_REFERENCED_NOT_CALLED", codes(result, "W.unreviewed-access"))

    def test_receipt_json_distinct_values_fail(self):
        context = P.Context({"before": sha(b"b"), "after": sha(b"a")}, {"before": self.base[0], "after": self.width[0]},
                            {"before": self.base[1], "after": self.width[1]}, {"before": {}, "after": {}}, [])
        receipt = json.loads(json.dumps(P.emit_receipt("D.ray-box", context)))
        for edit in (lambda r: r.update(mandatory=1),       # True == 1 in Python, not in canonical JSON
                     lambda r: r["arms"]["after"].update(dependency_modules=float(r["arms"]["after"]["dependency_modules"]))):
            changed = json.loads(json.dumps(receipt))
            edit(changed)
            self.assertEqual(P.validate_receipt(changed, context)["code"],
                             "PRODUCER_RECEIPT_CONTRADICTS_INDEPENDENT_INPUTS")
        self.assertEqual(P.validate_receipt(dict(receipt, binding={1, 2}), context)["code"],
                         "MALFORMED_PRODUCER_RECEIPT")

    def test_literal_non_producer_getattr_is_fine(self):
        raw = b"from . import integration_wall_measures as W\ndef g():\n    return getattr(W, '_decode')\n"
        result = assess(self.base, self.base_with({"zz_ok.py": raw}))
        self.assertEqual(result["verdict"], "BOUND", result["issues"])

    def base_with(self, extra):
        return tree(R4, extra=extra)

    def test_test_and_fixture_paths_excluded(self):
        raw = b"from . import integration_wall_measures as W\nf = W._pose_vector\n"
        for name in ("_fixtures/tests/zz_probe.py", "tests/zz_probe.py", "test_zz_probe.py"):
            with self.subTest(name):
                result = assess(self.base, self.base_with({name: raw}))
                self.assertEqual(result["verdict"], "BOUND", result["issues"])

    def test_reviewed_site_count_change(self):
        raw = (R4 / "integration_differential_geometry.py").read_bytes()
        head, sep, tail = raw.partition(b"normal, error = W._pose_vector(normal, omega, a, b, level, arena)")
        self.assertTrue(sep)
        after = width_arm(replace={"integration_differential_geometry.py": head + b"normal, error = normal, 0" + tail})
        result = assess(self.base, after)
        self.assertIn("REVIEWED_CALL_SITE_ABSENT", codes(result, "D.constraint-pose"))
        self.assertIn("UNREVIEWED_CALL_SITE", codes(result, "W.unreviewed-access"))
        self.assertIn("CALLER_SOURCE_CHANGED", codes(result, "D.ray-box"))
        # The differential geometry module is a caller, outside both producers' import closures.
        self.assertNotIn("PRODUCER_DEPENDENCY_SOURCE_CHANGED", codes(result))

    def test_forged_source_bytes_fail(self):
        pins, data = self.width
        data = dict(data)
        name = next(path for path in data if path.endswith("integration_current_force_pose.py"))
        data[name] = data[name] + b"\n"
        result = assess(self.base, (pins, data))
        self.assertEqual((result["verdict"], result["code"]), ("FAIL", "PROVENANCE_INPUT_INTEGRITY"))

    def test_receipt_forgery_fails(self):
        context = P.Context({"before": sha(b"b"), "after": sha(b"a")}, {"before": self.base[0], "after": self.width[0]},
                            {"before": self.base[1], "after": self.width[1]}, {"before": {}, "after": {}}, [])
        receipt = P.emit_receipt("D.ray-box", context)
        self.assertEqual(P.validate_receipt(json.loads(json.dumps(receipt)), context)["verdict"], "REVIEW")
        forged = json.loads(json.dumps(receipt))
        forged["issues"], forged["verdict"] = [], "BOUND"
        self.assertEqual(P.validate_receipt(forged, context)["code"], "PRODUCER_RECEIPT_CONTRADICTS_INDEPENDENT_INPUTS")
        forged = json.loads(json.dumps(receipt))
        forged["arms"]["after"]["call_sites"][0]["line"] += 1
        self.assertEqual(P.validate_receipt(forged, context)["verdict"], "FAIL")


def enc(value):
    value = Q(value)
    return [hex(value.numerator), hex(value.denominator)]


def digest(value):
    return P.digest(value)


SEGMENTS = [{"start_time_s": enc(0), "end_time_s": enc(10), "angular_velocity_rad_s": [enc(0), enc(0), enc(1)]},
            {"start_time_s": enc(10), "end_time_s": enc(20), "angular_velocity_rad_s": [enc(0), enc(1), enc(0)]}]


def support_ids(segments):
    """_measure_walls.support_id at start (prior prefix) and end (completed trajectory)."""
    base = {"funding_id": "fund", "grid_cell_ids": ["g"]}
    return (digest(dict(base, time_s=enc(10), trajectory_prefix=segments[:-1])),
            digest(dict(base, time_s=enc(20), trajectory_prefix=segments)))


def zero_cell(key, segments=SEGMENTS):
    """An exterior cell with no wall rows (zero flux) that still satisfies every cell relation."""
    start, end = support_ids(segments)
    zero = enc(0)
    return dict(exterior_cell_key=key, start_support_id=digest({"key": key, "support_id": start}),
                end_support_id=digest({"key": key, "support_id": end}),
                start_volume_bounds_m3=[enc(1), enc(2)], end_volume_bounds_m3=[enc(1), enc(2)],
                geometry_volume_change_bounds_m3=[enc(-1), enc(1)], flux_volume_change_bounds_m3=[zero, zero],
                gcl_intersection_bounds_m3=[zero, zero], chosen_volume_change_m3=zero,
                chosen_volume_change_error_m3=zero, chosen_change_admissible_bounds_m3=[zero, zero])


def make_wall(bounds, exact, *, geometry_pad=1, segments=SEGMENTS, source=None, extra_cells=()):
    """A W record satisfying the producer's reader rules and assembly relations.

    bounds[face] = ((in_lo, in_hi), (out_lo, out_hi)) for the single exterior key; exact[face] = (in, out).
    """
    key = ["layer", 0]
    start_id, end_id = support_ids(segments)
    faces, rows = [], []
    sums = [Q(0)]*7
    for index, ((ib, ob), totals) in enumerate(zip(bounds, exact, strict=True)):
        side, face_index, cell_id = "xyz"[index % 3] + "-", [index, 0], "cell-%d" % index
        faces.append(dict(side=side, face_index=face_index, cell_id=cell_id, inward_exact_volume_m3=enc(totals[0]),
                          outward_exact_volume_m3=enc(totals[1]), normal_has_constant_sign=True))
        values = []
        for (lo, hi), total in ((ib, totals[0]), (ob, totals[1])):
            assert lo <= total <= hi
            values.append((Q(lo), Q(hi), Q(total), max(Q(total)-lo, hi-Q(total))))
        (ilo, ihi, iv, idv), (olo, ohi, ov, odv) = values
        if any(v for v in (iv, ov, idv, odv)):
            rows.append(dict(side=side, face_index=face_index, cell_id=cell_id, exterior_cell_key=key,
                             inward_volume_m3=enc(iv), outward_volume_m3=enc(ov),
                             inward_bounds_m3=[enc(ilo), enc(ihi)], outward_bounds_m3=[enc(olo), enc(ohi)],
                             inward_max_deviation_m3=enc(idv), outward_max_deviation_m3=enc(odv)))
        for i, x in enumerate((ilo, ihi, olo, ohi, iv, ov, idv+odv)):
            sums[i] += x
    ilo, ihi, olo, ohi, iv, ov, err = sums
    flux = (olo-ihi, ohi-ilo)
    geometry = (flux[0]-geometry_pad, flux[1]+geometry_pad)
    common = (max(geometry[0], flux[0]), min(geometry[1], flux[1]))
    chosen = ov-iv
    cell = dict(exterior_cell_key=key, start_support_id=digest({"key": key, "support_id": start_id}),
                end_support_id=digest({"key": key, "support_id": end_id}),
                start_volume_bounds_m3=[enc(5), enc(7)], end_volume_bounds_m3=[enc(5), enc(8)],
                geometry_volume_change_bounds_m3=[enc(geometry[0]), enc(geometry[1])],
                flux_volume_change_bounds_m3=[enc(flux[0]), enc(flux[1])],
                gcl_intersection_bounds_m3=[enc(common[0]), enc(common[1])],
                chosen_volume_change_m3=enc(chosen), chosen_volume_change_error_m3=enc(err),
                chosen_change_admissible_bounds_m3=[enc(common[0]-err), enc(common[1]+err)])
    body = dict(schema=P.WALL, method=P.WALL_METHOD, funding_id="fund", collar_plan_id="collar",
                parent_state_id="parent", source=source or {"sphere_state_id": "sphere"},
                start_time_s=enc(10), end_time_s=enc(20),
                trajectory=dict(rule="r", epoch_s=enc(0), segments=segments),
                start_support_id=start_id, end_support_id=end_id, prior_trajectory_id=digest(segments[:-1]),
                trajectory_id=digest(segments), grid_cell_ids=["g"], rows=rows, faces=faces,
                exterior_cells=[cell] + [zero_cell(extra, segments) for extra in extra_cells],
                max_volume_error_m3=enc(Q(1, 8)), max_leaves=64, support_rule=P.WALL_FIXED["support_rule"],
                scope=P.WALL_FIXED["scope"])
    return dict(body, measure_id=digest(body))


def reseal(wall):
    body = {k: v for k, v in wall.items() if k != "measure_id"}
    return dict(body, measure_id=digest(body))


BASE_BOUNDS = [((1, 3), (0, 0)), ((0, 0), (2, 5))]
BASE_EXACT = [(2, 0), (0, 4)]


def record_set(wall=None, mesh=None):
    records, raw = {}, {}
    if wall is not None:
        raw["exchange"] = json.dumps({"schema": "exchange", "wall_measures": wall}, sort_keys=True).encode()
    if mesh is not None:
        raw["mesh"] = json.dumps(mesh, sort_keys=True).encode()
    for kind, data in raw.items():
        records[kind] = {"identity": sha(data), "raw": data}
    return records


def we_tree(w, e):
    files = {"atlas_tectonics/integration_wall_measures.py": w, "atlas_tectonics/integration_exterior_mesh.py": e}
    return {name: sha(raw) for name, raw in files.items()}, files


class Records(unittest.TestCase):
    """W record joins and E mesh joins on small synthetic records (W/E-only inventories)."""
    @classmethod
    def setUpClass(cls):
        require_sources()
        cls.src = we_tree((R4 / "integration_wall_measures.py").read_bytes(),
                          (R4 / "integration_exterior_mesh.py").read_bytes())
        cls.rnd = we_tree((WR2 / "integration_wall_measures.py").read_bytes(),
                          (WR2 / "integration_exterior_mesh.py").read_bytes())

    def run_pair(self, old, new, *, pair=True, same_manifest=False, mesh=(None, None)):
        records = {"before": record_set(old, mesh[0]), "after": record_set(new, mesh[1])}
        pairs = [(records["before"][k]["identity"], records["after"][k]["identity"])
                 for k in records["before"] if k in records["after"]] if pair else []
        manifests = {"before": sha(b"m"), "after": sha(b"m")} if same_manifest else None
        return assess(self.src, self.src if same_manifest else self.rnd, records, pairs, manifests)

    def wall(self, **kw):
        return make_wall(kw.pop("bounds", BASE_BOUNDS), kw.pop("exact", BASE_EXACT), **kw)

    def test_equal_records_bound(self):
        # Rounded pair: the E builders' W._endpoint_volume calls carry rounded volume-plane poses past the
        # joined W record, so that slot stays REVIEW even with equal records. Identity binds all three.
        result = self.run_pair(self.wall(), self.wall())
        by = {row["slot"]: row for row in result["receipts"]}
        for slot in ("W.wall-normal", "W.inverse-grid-vertex"):
            self.assertEqual(by[slot]["verdict"], "BOUND", (slot, by[slot]["issues"]))
            self.assertEqual(len(by[slot]["outputs"]), 1)
        self.assertEqual({P.code_of(issue) for issue in by["W.volume-plane-normal"]["issues"]},
                         {"POSE_CONSEQUENCE_ROUTE_UNBOUND"})
        same = self.run_pair(self.wall(), self.wall(), same_manifest=True)
        for slot in ("W.wall-normal", "W.volume-plane-normal", "W.inverse-grid-vertex"):
            row = next(r for r in same["receipts"] if r["slot"] == slot)
            self.assertEqual(row["verdict"], "BOUND", (slot, row["issues"]))

    def test_restore_and_writer_contract_fail(self):
        # WallMeasures.restore and _measure_walls rules beyond the body identity and history.
        def edit_row(w):
            w["rows"][0]["inward_volume_m3"] = ["0x4", "0x2"]       # the value 2, not V._encoded's form

        def edit_float(w):
            w["support_rule"] = 1.5

        def edit_leaves(w):
            w["max_leaves"] = True

        def edit_support(w):
            w["start_support_id"] = "s"

        def edit_cell_support(w):
            w["exterior_cells"][0]["end_support_id"] = "e"

        def edit_required(w):
            del w["collar_plan_id"]

        def edit_times(w):
            w["max_volume_error_m3"] = enc(-1)

        # _measure_walls' exact record, row, face and exterior-cell key sets and fixed text.
        def edit_extra_key(w):
            w["note"] = "x"

        def edit_scope(w):
            w["scope"] = "other"

        def edit_row_key(w):
            w["rows"][0]["note"] = "x"

        def edit_face_key(w):
            del w["faces"][0]["normal_has_constant_sign"]

        def edit_face_sign(w):
            w["faces"][0]["normal_has_constant_sign"] = 1

        def edit_cell_key(w):
            w["exterior_cells"][0]["note"] = "x"
        for edit in (edit_row, edit_float, edit_leaves, edit_support, edit_cell_support, edit_required, edit_times,
                     edit_extra_key, edit_scope, edit_row_key, edit_face_key, edit_face_sign, edit_cell_key):
            new = self.wall()
            edit(new)
            with self.subTest(edit.__name__):
                result = self.run_pair(self.wall(), reseal(new))
                self.assertIn("W_RECORD_CONTRACT_CONTRADICTION", codes(result, "W.wall-normal"))
                self.assertEqual(result["verdict"], "FAIL")
        new = self.wall()
        del new["measure_id"]
        self.assertIn("W_MEASURE_ID_CONTRADICTION", codes(self.run_pair(self.wall(), new)))

    def test_identical_code_extra_cell_fails(self):
        new = self.wall(extra_cells=(["layer", 1],))
        result = self.run_pair(self.wall(), new, same_manifest=True)
        self.assertIn("W_IDENTICAL_CODE_OUTPUT_CHANGED", codes(result, "W.inverse-grid-vertex"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("W_EXTERIOR_CELL_KEYS_DIFFER", codes(self.run_pair(self.wall(), new), "W.wall-normal"))

    def test_changed_intersecting_review(self):
        new = self.wall(bounds=[((Q(3, 2), 3), (0, 0)), ((0, 0), (2, 5))])
        result = self.run_pair(self.wall(), new)
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("W_ENCLOSURE_CHANGED_NO_PROPAGATED_BOUND", codes(result, "W.wall-normal"))

    def test_disjoint_row_fails(self):
        new = self.wall(bounds=[((Q(7, 2), 4), (0, 0)), ((0, 0), (2, 5))], exact=[(Q(7, 2), 0), (0, 4)])
        result = self.run_pair(self.wall(), new)
        self.assertIn("W_FLUX_ENCLOSURES_DISJOINT", codes(result, "W.wall-normal"))
        self.assertEqual(result["verdict"], "FAIL")

    def test_missing_row_is_exact_zero(self):
        # A face whose enclosure is [0,0] has no row; the other arm's [0,0] row equivalent stays equal.
        old = self.wall(bounds=[((1, 3), (0, 0)), ((0, 0), (0, 0))], exact=[(2, 0), (0, 0)])
        new = self.wall(bounds=[((1, 3), (0, 0)), ((0, 0), (0, 0))], exact=[(2, 0), (0, 0)])
        result = self.run_pair(old, new)
        self.assertEqual(next(r for r in result["receipts"] if r["slot"] == "W.wall-normal")["verdict"], "BOUND")
        # versus a positive certified flow in the other arm: disjoint from exact zero.
        new = self.wall(bounds=[((1, 3), (0, 0)), ((0, 0), (1, 2))], exact=[(2, 0), (0, 1)])
        self.assertIn("W_FLUX_ENCLOSURES_DISJOINT", codes(self.run_pair(old, new), "W.wall-normal"))

    def test_faces_changed_fail(self):
        new = self.wall()
        new["faces"][0]["normal_has_constant_sign"] = False
        self.assertIn("W_POSE_INDEPENDENT_FACES_CHANGED", codes(self.run_pair(self.wall(), reseal(new))))

    def test_forged_measure_id_and_history_fail(self):
        new = self.wall()
        new["measure_id"] = "0"*64
        self.assertIn("W_MEASURE_ID_CONTRADICTION", codes(self.run_pair(self.wall(), new)))
        new = self.wall()
        new["trajectory_id"] = digest(SEGMENTS[:1])
        result = self.run_pair(self.wall(), reseal(new))
        self.assertIn("W_HISTORY_IDENTITY_CONTRADICTION", codes(result))
        self.assertEqual(result["verdict"], "FAIL")

    def test_row_and_cell_contract_fail(self):
        new = self.wall()
        new["rows"][0]["inward_volume_m3"] = enc(Q(5, 2))     # moves allocation; deviation/closure now wrong
        self.assertIn("W_ROW_CONTRACT_CONTRADICTION", codes(self.run_pair(self.wall(), reseal(new))))
        new = self.wall()
        new["exterior_cells"][0]["flux_volume_change_bounds_m3"][0] = enc(-100)
        self.assertIn("W_CELL_CONTRACT_CONTRADICTION", codes(self.run_pair(self.wall(), reseal(new))))

    def test_identical_code_change_fails(self):
        new = self.wall(bounds=[((Q(3, 2), 3), (0, 0)), ((0, 0), (2, 5))])
        result = self.run_pair(self.wall(), new, same_manifest=True)
        self.assertIn("W_IDENTICAL_CODE_OUTPUT_CHANGED", codes(result, "W.wall-normal"))
        self.assertEqual(result["verdict"], "FAIL")

    def test_inputs_differ_and_unpaired_review(self):
        new = self.wall(source={"sphere_state_id": "other"})
        result = self.run_pair(self.wall(), new)
        self.assertIn("W_INVOCATION_INPUTS_DIFFER", codes(result, "W.wall-normal"))
        self.assertEqual(result["verdict"], "REVIEW")
        result = self.run_pair(self.wall(), self.wall(), pair=False)
        self.assertIn("W_RECORD_CORRESPONDENCE_MISSING", codes(result, "W.wall-normal"))

    def mesh(self, quaternion=(1, 0, 0, 0), bound=Q(1, 1000), segments=SEGMENTS, **kw):
        record = {"schema": P.MESH, "representative_quaternion": [enc(q) for q in quaternion],
                  "pose_operator_error_bound": enc(bound), "trajectory_id": digest(segments),
                  "trajectory_segments": segments, "endpoint": "end", "max_geometry_volume_error_m3": enc(Q(1, 8)),
                  "funding_id": "fund", "source": {"sphere_state_id": "sphere"}}
        record.update(kw)
        return record

    def test_mesh_join(self):
        result = self.run_pair(None, None, mesh=(self.mesh(), self.mesh(quaternion=(1, Q(1, 10**9), 0, 0))))
        row = next(r for r in result["receipts"] if r["slot"] == "E.representative-quaternion")
        self.assertEqual(row["verdict"], "BOUND", row["issues"])
        self.assertEqual(row["comparison_bound"]["kind"], "pose-quaternion")
        self.assertEqual(len(row["correspondence"]), 1)

    def test_mesh_history_and_inputs(self):
        forged = self.mesh(trajectory_id=digest(SEGMENTS[:1]))
        result = self.run_pair(None, None, mesh=(self.mesh(), forged))
        self.assertIn("E_HISTORY_IDENTITY_CONTRADICTION", codes(result))
        self.assertEqual(result["verdict"], "FAIL")
        result = self.run_pair(None, None, mesh=(self.mesh(), self.mesh(endpoint="start")))
        self.assertIn("E_INVOCATION_INPUTS_DIFFER", codes(result, "E.representative-quaternion"))
        result = self.run_pair(None, None, mesh=(self.mesh(), self.mesh(trajectory_segments={"ref": "x"})))
        self.assertIn("SOURCE_HISTORY_CONTEXT_MISSING", codes(result, "E.representative-quaternion"))
        self.assertEqual(result["verdict"], "REVIEW")

    def test_differential_mesh_not_a_pose_output(self):
        dm = self.mesh(physical_geometry_family=P.DIFFERENTIAL)
        result = self.run_pair(None, None, mesh=(dm, dm))
        self.assertIn("NO_READER_BOUND_E_OUTPUT", codes(result, "E.representative-quaternion"))

    # Ported from field-provenance-r3: same intent, r4 receipt layout.
    def test_identical_records_do_not_waive_missing_context(self):
        bare = {k: v for k, v in self.mesh().items() if k != "endpoint"}
        result = self.run_pair(None, None, mesh=(bare, bare))
        for slot in ("E.representative-quaternion", "E.pose-operator-error"):
            row = next(r for r in result["receipts"] if r["slot"] == slot)
            self.assertEqual(row["verdict"], "REVIEW")
            self.assertIn("SOURCE_HISTORY_CONTEXT_MISSING", codes(result, slot))
            self.assertIsNone(row["applicable_radius"])
        forged = dict(bare, trajectory_id="c"*64)     # a contradicted history fails even with inputs missing
        result = self.run_pair(None, None, mesh=(forged, forged))
        self.assertIn("E_HISTORY_IDENTITY_CONTRADICTION", codes(result, "E.representative-quaternion"))
        self.assertEqual(result["verdict"], "FAIL")

    def test_operator_error_never_becomes_quaternion_radius(self):
        result = self.run_pair(None, None, mesh=(self.mesh(), self.mesh()))
        quat, oper = (next(r for r in result["receipts"] if r["slot"] == slot)
                      for slot in ("E.representative-quaternion", "E.pose-operator-error"))
        self.assertEqual((quat["applicable_radius"], oper["applicable_radius"]), (None, None))
        self.assertEqual((quat["quantity"]["norm"], oper["quantity"]["norm"]), ("l2", "scalar"))
        self.assertIn("4*internal", quat["quantity"]["error_meaning"])
        bound = quat["comparison_bound"]
        self.assertEqual((bound["kind"], bound["scale"], bound["proof"]),
                         ("pose-quaternion", {"path": ["pose_operator_error_bound"], "factor": "1/4"}, P.E_QUAT_PROOF))
        same = self.run_pair(None, None, mesh=(self.mesh(), self.mesh()), same_manifest=True)
        self.assertEqual(next(r for r in same["receipts"] if r["slot"] == "E.representative-quaternion")
                         ["comparison_bound"], {"kind": "exact"})

    def test_receipt_rederivation_rejects_asserted_fields(self):
        records = {"before": record_set(None, self.mesh()),
                   "after": record_set(None, self.mesh(quaternion=(1, Q(1, 10**9), 0, 0)))}
        pairs = [(records["before"]["mesh"]["identity"], records["after"]["mesh"]["identity"])]
        context = P.Context({"before": sha(b"m-before"), "after": sha(b"m-after")},
                            {"before": self.src[0], "after": self.rnd[0]}, {"before": self.src[1], "after": self.rnd[1]},
                            records, pairs)
        receipt = json.loads(json.dumps(P.emit_receipt("E.representative-quaternion", context)))
        self.assertEqual(P.validate_receipt(receipt, context)["verdict"], "BOUND")
        edits = (lambda r: r.update(applicable_radius={"path": ["pose_operator_error_bound"], "scale": "1/4"}),
                 lambda r: r.update(comparison_bound={"kind": "exact"}),
                 lambda r: r.update(verdict="PASS"),
                 lambda r: r["arms"]["before"].update(producer=None),
                 lambda r: r["outputs"][1].update(value_sha256="0"*64),
                 lambda r: r["binding"].update(refinement_level=3),
                 lambda r: r["outputs"][0]["history"].update(trajectory_id="0"*64),
                 lambda r: r["correspondence"][0].update(after_record_identity="0"*64),
                 lambda r: r.update(producer_observation={"self_certified": True}))
        for index, edit in enumerate(edits):
            changed = json.loads(json.dumps(receipt))
            edit(changed)
            with self.subTest(index=index):
                self.assertEqual(P.validate_receipt(changed, context)["verdict"], "FAIL")

    def test_no_producers_claims_no_other_coverage(self):
        result = assess(({}, {}), ({}, {}))
        self.assertEqual((result["verdict"], result["mandatory_slots"]), ("NOT_APPLICABLE", []))
        self.assertIn("no Pressure/Geometry/Heat contract", result["scope"])


if __name__ == "__main__":
    unittest.main()
