"""Uninstalled joined-caller seam for the q297 diagnostic END provider.

The selected derived joined source remains unchanged. This creates only a
separate candidate and does not select a provider or open a run/store.
"""

def transform(source):
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
    text = source
    for label, old, new in (('signature', signature, signature_new), ('call', call, call_new)):
        if text.count(old) != 1:
            raise ValueError('source-text anchor missing or ambiguous: q297-provider-'+label)
        text = text.replace(old, new, 1)
    compile(text, 'runtime_joined_control.py[q297-provider-candidate]', 'exec', dont_inherit=True)
    return text
