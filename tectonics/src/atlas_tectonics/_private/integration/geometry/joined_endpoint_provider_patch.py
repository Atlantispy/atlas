"""Uninstalled joined-caller seam for the q297 diagnostic END provider.

The selected derived joined source remains unchanged. This creates only a
separate candidate and does not select a provider or open a run/store.
"""
import ast


def transform(source):
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
    text = source.replace(signature, signature_new, 1).replace(call, call_new, 1)
    after = ast.parse(text)
    {n.name: ast.dump(n) for n in before.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    {n.name: ast.dump(n) for n in after.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    [ast.dump(n) for n in before.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    [ast.dump(n) for n in after.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    compile(text, 'runtime_joined_control.py[q297-provider-candidate]', 'exec', dont_inherit=True)
    return text
