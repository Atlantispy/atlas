"""Uninstalled joined-caller seam for the q297 diagnostic END provider.

The selected derived joined source remains unchanged. This creates only a
separate candidate and does not select a provider or open a run/store.
"""
import ast
import hashlib

SELECTED_JOINED_DERIVATION = '3569c539b18b852841f6a03939ed9905f602f49ff3a4f86a00509a39b0a4d605'


def transform(source):
    if type(source) is not str or hashlib.sha256(source.encode('utf-8')).hexdigest() != SELECTED_JOINED_DERIVATION:
        raise ValueError('selected joined derivation differs')
    before = ast.parse(source)
    signature = ('                              before_advance=None, completed_observer=None, max_partition_components=8192,\n'
                 '                              endpoint_checkpoints=None):\n')
    signature_new = ('                              before_advance=None, completed_observer=None, max_partition_components=8192,\n'
                     '                              endpoint_checkpoints=None, end_geometry_provider_factory=None):\n')
    call = ('                closed_graph=solution.graph, budget=budget,\n'
            '                **_PUBLISH_MESH.mesh_options(workflow, partition))\n')
    call_new = ('                closed_graph=solution.graph, budget=budget,\n'
                "                **({} if end_geometry_provider_factory is None else {'end_geometry_provider':\n"
                '                    end_geometry_provider_factory(interval=interval, partition=partition,\n'
                '                        funding=funding, bounds=bounds, closed_graph=solution.graph, budget=budget)}),\n'
                '                **_PUBLISH_MESH.mesh_options(workflow, partition))\n')
    if source.count(signature) != 1 or source.count(call) != 1:
        raise ValueError('selected joined provider anchor missing or ambiguous')
    text = source.replace(signature, signature_new, 1).replace(call, call_new, 1)
    after = ast.parse(text)
    original = {n.name: ast.dump(n) for n in before.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    candidate = {n.name: ast.dump(n) for n in after.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if (set(original) != set(candidate) or
            {name for name in original if original[name] != candidate[name]} != {'_advance_current_interval'}):
        raise ValueError('joined provider transform changed unexpected functions')
    other_before = [ast.dump(n) for n in before.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    other_after = [ast.dump(n) for n in after.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if other_before != other_after:
        raise ValueError('joined provider transform changed module structure')
    compile(text, 'runtime_joined_control.py[q297-provider-candidate]', 'exec', dont_inherit=True)
    return text
