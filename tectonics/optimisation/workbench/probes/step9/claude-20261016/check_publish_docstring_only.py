"""Read-only: the 10:40 publish_mesh_patch edit changed its two route docstrings and nothing else.

Reverses exactly those two text replacements in memory and checks that the result hashes to the
previous pin (0971631c, recorded in decision-05), then that the module's AST with every
docstring removed is identical between the reconstructed previous text and the live file.
"""
import ast
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE.parents[2]/'compact-geometry-r1'/'publish_mesh_patch.py'
EDITS = (
    ("CompactMesh that writes nothing. Under the composed partition stage (live_partition_patch.transform,\n"
     "live_memory_composition.STAGES) a proposal is compact when its parent is a restored PartitionV2,\n"
     "from interval 2 on: the mesh then shares every differential support with the partition. Interval\n"
     "1's parent is the native root partition, so its proposal is native, and live_mesh_patch copies\n"
     "the support bodies into its in-memory static table. note_end_mesh records which for run.json.\n",
     "CompactMesh that writes nothing. Over compact supports it shares every differential support\n"
     "with the partition; over the native supports the selected partition route issues\n"
     "(live_partition_patch.transform_lifetimes keeps the original output route), live_mesh_patch\n"
     "copies their bodies into its in-memory static table, which note_end_mesh records for run.json.\n"),
    ("    The proposal's supports are the native tuple (interval 1, native root parent: their bodies\n"
     "    are copied into the mesh's in-memory static table) or the compact sequence over a sealed\n"
     "    in-memory PartitionV2 in that scope (from interval 2: shared). A compact sequence in another\n"
     "    scope is refused.",
     "    The proposal's supports are the native tuple (the selected partition route: their bodies\n"
     "    are copied into the mesh's in-memory static table) or the compact sequence over a sealed\n"
     "    in-memory PartitionV2 in that scope (shared). A compact sequence in another scope is\n"
     "    refused."),
)


def stripped(text):
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body and \
                isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and \
                isinstance(node.body[0].value.value, str):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.dump(tree)


def main():
    live = LIVE.read_bytes().decode('utf8')
    previous = live
    for new, old in EDITS:
        assert previous.count(new) == 1, 'edit text not found exactly once'
        previous = previous.replace(new, old)
    digest = sha256(previous.encode()).hexdigest()
    print('reconstructed previous', digest[:16], '| live', sha256(live.encode()).hexdigest())
    print('previous pin 0971631c matches:', digest.startswith('0971631c'))
    print('code identical apart from docstrings:', stripped(previous) == stripped(live))


if __name__ == '__main__':
    main()
