"""Bounded real-package import/call check; retained baseline, no replay admission."""
from fractions import Fraction as Q
from hashlib import sha256
import importlib.machinery
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE / "composed-r6"
def digest(path):
    return sha256(path.read_bytes()).hexdigest()

assert sys.dont_write_bytecode
assert digest(ROOT / "composition.json") == "f3bb549b02eac2cb6b6faa0bdc4799b5cb3db69b2b4507eb8fdd1e26234f3991"
manifest = json.loads((ROOT / "composition.json").read_bytes())
pins = {"src/" + k: v for k, v in manifest["outputs"].items()}
pins.update({"helpers/" + k: v for k, v in manifest["helpers"].items()})
assert not any(n == "atlas_tectonics" or n.startswith("atlas_tectonics.") for n in sys.modules)
os.environ["ATLAS_EXACT_ARITHMETIC"] = "gmpy2"

# Same explicit native-first path and hash-checked SourceFileLoader mechanism
# as selected helpers/run_prepared_restart.py: RuntimeSources.selected().
# Its full prepared admission is intentionally not invoked without a profile.
class Loader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        path = Path(self.path).resolve()
        raw = path.read_bytes()
        assert sha256(raw).hexdigest() == pins[path.relative_to(ROOT).as_posix()], fullname
        return compile(raw, str(path), "exec", dont_inherit=True)

class Finder:
    def find_spec(self, fullname, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec and spec.origin and spec.origin.endswith(".py"):
            location = Path(spec.origin).resolve()
            if location.is_relative_to(ROOT):
                spec.loader = Loader(fullname, str(location))
        return spec

sys.path[:0] = [str(ROOT / "src"), str(ROOT / "helpers")]
sys.meta_path.insert(0, Finder())
from atlas_tectonics import exact_arithmetic as X
from atlas_tectonics import integration_wall_measures as W
from atlas_tectonics import integration_wall_measures_gmp as D
from atlas_tectonics import integration_exact_twin as E

assert X.BACKEND == "gmpy2" and E.available()
assert W._D5 is D and D._module is W and D._resident()
poly = ((Q(0), Q(0)), (Q(1), Q(0)), (Q(1), Q(1)), (Q(0), Q(1)))
line = (Q(1), Q(0), Q(-1, 2))
expected = ((Q(1, 2), Q(0)), (Q(1), Q(0)), (Q(1), Q(1)), (Q(1, 2), Q(1)))
assert D.clip2(poly, line, None) == expected
# Trace the real dispatcher without replacing a reference object/residency pin.
calls = []
def trace(frame, event, arg):
    if event == "call" and frame.f_code is D._clip2.__code__:
        calls.append("native_clip")
    return trace
sys.setprofile(trace)
try:
    actual = W._clip2(poly, line)
finally:
    sys.setprofile(None)
assert actual == expected and calls == ["native_clip"] and D._resident()
assert all(type(v) is Q and type(v.numerator) is int and type(v.denominator) is int for p in actual for v in p)
loaded = {}
for name, module in tuple(sys.modules.items()):
    if name == "atlas_tectonics" or name.startswith("atlas_tectonics."):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(ROOT / "src"), (name, path)
        key = path.relative_to(ROOT).as_posix()
        assert digest(path) == pins[key], name
        loaded[key] = pins[key]
runtime = X.runtime()
binaries = {key: {"path": str(path), "sha256": digest(Path(path))}
            for key, path in runtime["binaries"].items()}
assert binaries and runtime["versions"]["gmp_binary_scope"] == "wheel-libraries"
result = dict(passed=True, status="RETAINED_BASELINE_D5_IMPORT_AND_ONE_EXACT_CALL_ONLY",
              not_plan31_selection=True, replay=False,
              composition_sha256=digest(ROOT / "composition.json"),
              test_sha256=digest(Path(__file__)), interpreter=sys.version,
              executable=sys.executable, selection=X.selection(), versions=runtime["versions"],
              binaries=binaries, loaded_sources=loaded, native_dispatch_calls=calls,
              exact_result=[[[v.numerator, v.denominator] for v in p] for p in actual],
              bootstrap="native-first src/helpers; selected source-loader mechanism; no prepared profile admission")
with (HERE / "composed-import-r1.json").open("x", encoding="utf8") as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result))
