"""R14 private composition: successor erosion, unchanged R3 sediment routing.

No sealed module or its globals are mutated. The inherited callable's verified
code is reused with a private dependency view; R14 source identity binds this
composition and its new erosion arithmetic. Receipts explicitly name R14.
"""
from dataclasses import replace
from types import FunctionType, SimpleNamespace

from . import erosion, provenance as p


def trial(state, local_runoff_m3, connectors, laws, sediment_laws, *,
          duration_years, controls, evidence_id):
    _, native = p.backend()
    p.verify_backend()
    source = native.terrain_trial
    view = SimpleNamespace(Forcing=native.landscape.Forcing,
                           advance=erosion.advance,
                           _verify_sources=native.landscape._verify_sources)
    scope = dict(source.__globals__, landscape=view)
    composed = FunctionType(source.__code__, scope, source.__name__,
                            source.__defaults__, source.__closure__)
    composed.__kwdefaults__ = None if source.__kwdefaults__ is None else dict(source.__kwdefaults__)
    result = composed(state, local_runoff_m3, connectors, laws, sediment_laws,
                      duration_years=duration_years, controls=controls, evidence_id=evidence_id)
    receipt = dict(result.receipt)
    successor = receipt.pop('actual_R1_erosion_receipt')
    if successor.get('schema') != erosion.SCHEMA:
        raise ValueError('R14 terrain requires its actual successor erosion receipt')
    receipt.update(schema='diadem.runoff-layered-sediment-trial.r14',
                   actual_R14_erosion_receipt=successor,
                   numerical_composition='R14 private successor erosion; unchanged sealed R3 routing/settling code; no sealed module mutation',
                   solid_model='R14 contact-resolved finite erosion with bounded represented rates/partial transfers and exact applied material splits; R3 per-material steady settling with binary64 factor and exact split')
    p.verify_backend()
    return replace(result, receipt=receipt)
