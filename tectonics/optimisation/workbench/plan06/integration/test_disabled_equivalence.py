"""Compare original and disabled-successor pin records on identical synthetic sources."""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BASE = HERE / "reference_assemble_r3.py"


def load(path, pin, name):
    if sha256(path.read_bytes()).hexdigest() != pin:
        raise ValueError("source pin differs")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Disabled(unittest.TestCase):
    def test_identical_pin_record(self):
        original = load(BASE, "bd298b2b19b6a967a19345044d28e46c7daf40c6eee1eeebf79d43a2b5d3583a", "original")
        candidate = load(HERE / "assemble_r3_plan06.py",
                         "345d00311f8b7521ed63225054530c1aa2fe2391446d2c236871aa1dd47e4322", "candidate")
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            root = Path(temporary)
            src = root / "rc1/runtime-src/atlas_tectonics"
            src.mkdir(parents=True)
            (src / "integration_wall_measures.py").write_text("fixture = 1\n", encoding="utf8")
            extra = (root / "i/atlas_tectonics/integration_mimetic_heat.py",
                     root / "i/atlas_tectonics/integration_private_heat_cold.py",
                     root / "r/endpoint-checkpoints/integration_endpoint_checkpoints.py")
            for path in extra:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# fixture\n", encoding="utf8")
            sources = {"atlas_tectonics/integration_wall_measures.py": "fixture = 1\n"}
            dry = root / "dry.json"
            dry.write_text(json.dumps({"src_files": {k: sha256(v.encode()).hexdigest() for k, v in sources.items()}}))
            for mod in (original, candidate):
                mod.T, mod.R, mod.RC1, mod.I_RUNTIME = root, root / "r", root / "rc1", root / "i"
                mod.compose = lambda pins=None: (dict(sources), [], {}, {})
                mod.helper_sources = lambda: {}
            candidate.PLAN06_D5_BASE_SOURCES = dict(sources)
            candidate.plan06_select_d5(None, None)
            for name, mod in (("old", original), ("new", candidate)):
                mod.pin(root / (name + ".json"), dry, mod.file_sha(dry), root / "composed-r1", {"fixture": "same"})
            self.assertEqual((root / "old.json").read_bytes(), (root / "new.json").read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
