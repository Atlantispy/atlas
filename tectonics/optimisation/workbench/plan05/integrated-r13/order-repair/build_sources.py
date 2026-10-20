"""Strict additive source transform. No imports/execution of scientific code."""
import ast
from hashlib import sha256
from pathlib import Path


HERE = Path(__file__).resolve().parent
T = Path("C:/Users/LOCAL_USER/Documents/Codex/2026-09-02/the-diadem-local-tasks-10")
BASES = {
    "lf3": "5c9ad7371e30f29ad56865cbad109c5bfce9fc0c5dab8fc0a015fa52e512826d",
    "lh": "081aac58460c097109bb1c0c522717265386da71be1bfe7aaa08c7c2b9003c7d",
}
NAME = "private_heat_forward_kernel_r13.py"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Forward source seam absent or ambiguous: " + old[:80])
    return source.replace(old, new, 1)


def transform(raw, arm):
    if arm not in BASES or sha256(raw).hexdigest() != BASES[arm]:
        raise ValueError("Exact selected forward predecessor required")
    source = raw.decode("utf8").replace("\r\n", "\n")
    source = replace_once(source, "import private_heat_process_meter_r1 as METER\n",
                          "import private_heat_process_meter_r1 as METER\n"
                          "import private_heat_physical_order_r1 as ORDER\n")
    source = replace_once(source,
        "    pending = [GEOMETRY, LOW, FUNCTIONS, ASSEMBLY, REFINEMENT, SPARSE, INVENTORY, FINISH, LIFE]\n",
        "    pending = [GEOMETRY, LOW, FUNCTIONS, ASSEMBLY, REFINEMENT, SPARSE, INVENTORY, FINISH, LIFE, ORDER]\n"
        "    roots = {HERE, Path(FUNCTIONS.__file__).resolve().parent, Path(ORDER.__file__).resolve().parent}\n")
    source = replace_once(source,
        "                    and Path(value.__file__).resolve().parent == HERE):\n",
        "                    and Path(value.__file__).resolve().parent in roots):\n")
    source = replace_once(source,
        "        prepared, payload = startup.value['prepared'], startup.value['payload']\n",
        "        order_owner = retain(ORDER.prepare(geometry, startup, old, capacity, source,\n"
        "            budget=budget, cancel=check))\n"
        "        ordered = order_owner.value\n"
        "        prepared, payload = ordered['prepared'], ordered['payload']\n"
        "        old, capacity, source = ordered['old'], ordered['capacity'], ordered['source']\n")
    source = replace_once(source,
        "            startup = retain(LIFE.compact(startup, budget=budget, path=('prepared',),\n"
        "                cancelled=check, category='heat-completed-prepared-inputs'))\n",
        "            # Canonical scratch borrows original prepared/payload leaves.\n"
        "            # Retain their complete original startup owner through FINISH.\n")
    source = replace_once(source,
        "            finished = retain(FINISH.finish(old, capacity, dt, source, normalized,\n"
        "                prepared['face_ids'], low.value, high.value, _SOURCES, target,\n",
        "            finish_inputs = retain(ORDER.finish_inputs(order_owner, low, high,\n"
        "                budget=budget, cancel=check))\n"
        "            original_old, original_capacity, original_source = ordered['original_inputs']\n"
        "            finished = retain(FINISH.finish(original_old, original_capacity, dt, original_source, normalized,\n"
        "                prepared['face_ids'], finish_inputs.value['low'], finish_inputs.value['high'], _SOURCES, target,\n")
    source = replace_once(source,
        "        info.update(connected_seconds=perf_counter()-began, reconstruction=proof,\n",
        "        info.update(physical_scratch_order=ORDER.POLICY,\n"
        "            public_cell_and_face_order_preserved=True,\n"
        "            connected_seconds=perf_counter()-began, reconstruction=proof,\n")
    ast.parse(source)
    # Both source-specific H5a operations survive verbatim: only their operand
    # row order changes before either selected preparation implementation.
    for needle in ("FUNCTIONS.prepare_shared(", "prepared=prepared_shared.value"):
        if source.count(needle) != raw.decode("utf8").count(needle):
            raise AssertionError("Selected H5a implementation was changed")
    return source.encode("utf8")


def main():
    for arm in BASES:
        raw = (T / "hs" / arm / "helpers" / NAME).read_bytes()
        output = transform(raw, arm)
        target = HERE / arm / NAME
        target.parent.mkdir(exist_ok=True)
        # Refuse overwrite; generated predecessors and their receipts survive.
        with target.open("xb") as stream:
            stream.write(output)
        print(arm, sha256(output).hexdigest(), target)


if __name__ == "__main__":
    main()
