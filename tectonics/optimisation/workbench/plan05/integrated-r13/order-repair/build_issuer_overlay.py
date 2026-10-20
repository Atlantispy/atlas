"""Add the selected order helper to immutable issuer identity capture."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
BASE = "549dbc86b9405323993e8d2aeb519ace7b50ad2d0d94e1bed66b59f81f7fe0c4"
replacements = {
    "HERE = Path(__file__).resolve().parent":
        "HERE = Path(INDEXED.__file__).resolve().parent  # selected native lookup root",
    "[sys.modules[__name__], N, F, CERT, FUNCTIONS, LOADED_IDENTITY,":
        "[sys.modules[__name__], N, F, F.ORDER, CERT, FUNCTIONS, LOADED_IDENTITY,",
}
records = []
for layout in ("lf3", "lh"):
    source = T / "hs" / layout / "helpers/private_heat_native_issuer_r13.py"
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASE
    text = raw.decode("utf8")
    for original, changed in replacements.items():
        assert text.count(original) == 1, "Issuer transformation anchor differs"
        text = text.replace(original, changed)
    compile(text, str(source), "exec")
    target = HERE / layout / source.name
    target.parent.mkdir(exist_ok=True)
    with target.open("xb") as stream:
        stream.write(text.encode("utf8"))
    records.append({"layout": layout, "base": str(source), "base_sha256": BASE,
                    "selected": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
with (HERE / "issuer-build.json").open("x", encoding="utf8") as stream:
    json.dump({"replacements": replacements, "records": records}, stream, indent=2)
print(json.dumps(records))
