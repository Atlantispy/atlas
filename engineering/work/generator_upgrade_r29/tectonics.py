"""New snapshot producer; exact outputs, raw-only external checks on cache hits."""
from pathlib import Path
from work.generator_upgrade_r26 import physical as original
from work.diadem_tectonics_r3 import snapshot
from . import provenance as p

OPERATIONS = {'tectonic_snapshot':('plate_tectonics',)}

def _inputs(inputs,incoming):
    original.common.encoded(inputs)
    original.common.encoded(incoming)
    original._exact(inputs,('package_dir','package_pins','domain_decisions'),'tectonic snapshot')
    if incoming:
        raise ValueError('tectonic snapshot has no implicit predecessor inputs')
    path = Path(inputs['package_dir'])
    if not path.is_absolute():
        raise ValueError('absolute immutable tectonic package required')
    return path

def _decision_sources(decisions):
    if decisions is not None:
        for source in decisions['source_refs']:
            original.common.checked(Path(source['path']),source['sha256'])

class Adapter:
    def __init__(self,operation,cache=True,cache_root=None,shared=None):
        if operation != 'tectonic_snapshot':
            raise ValueError('R3 tectonic snapshot operation required')
        self.binding = p.tectonic_sources()
        self.source_signature = original.common.sha({'operation':operation,'tectonics_r3':self.binding})

    def verify(self):
        if p.tectonic_sources() != self.binding:
            raise ValueError('tectonic producer source/runtime changed; no repin')

    def run(self,inputs,incoming):
        path = _inputs(inputs,incoming)
        _decision_sources(inputs['domain_decisions'])
        result = snapshot.build_snapshot(path,inputs['domain_decisions'],package_pins=inputs['package_pins'])
        _decision_sources(inputs['domain_decisions'])
        return original.scientific(result)

    def validate_result(self,result,inputs,incoming):
        path = _inputs(inputs,incoming)
        snapshot.verify_package(path,inputs['package_pins'])
        _decision_sources(inputs['domain_decisions'])
        original.common.encoded(result)
        if result.get('validation',{}).get('category_complete') is not False or set(
                result.get('products',{})) != set(snapshot.PRODUCT_NAMES):
            raise ValueError('unpromoted complete native tectonic product inventory required')
