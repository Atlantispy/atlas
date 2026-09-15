"""Source-bound coastal continuation with finite once-only river pulse stores.

One accepted substep is transactional. A failing substep leaves its preceding
state intact. Boundary/forcing endpoints and saved time are exact; constitutive
flow, momentum and erosion rates use the disclosed binary64 reference.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
from work.generator_upgrade_r18 import composite

from . import state as s, provenance as p, owner


class CoastalRun:
    def __init__(self, cells, palette, faces, links, *, evidence, lineage, parameters=None):
        from . import flow
        if type(cells) is not dict or not 1 <= len(cells) <= 32:
            raise ValueError('bounded explicit coastal cells required')
        if not evidence or type(lineage) is not dict or not lineage:
            raise ValueError('explicit source/scenario lineage required')
        self.cells, self.palette = deepcopy(cells), deepcopy(palette)
        if type(palette) is not dict or not 1 <= len(palette) <= 2048:
            raise ValueError('bounded composition palette required')
        for mid in palette:
            composite._validated(mid, palette)
        self.faces, self.links = deepcopy(faces), deepcopy(links)
        self.evidence, self.lineage = evidence, deepcopy(lineage)
        self.parameters = owner.parameters() if parameters is None else deepcopy(parameters)
        self.constants = owner.inputs()[1]['constants']
        self.owner = owner.binding()
        self.time = F(); self.pulses = {}; self.consumed = {}; self.source_packets = {}
        self.intervals = []; self.active_interval = None
        self.initial = s.inventory(self.cells, self.palette)
        self.imported = {'water_m3': F(), 'materials_kg': {}, 'solid_m3': {}}
        self.receipts = []
        self.execution = p.identity()
        flow.validate_geometry(self.cells, self.faces, self.links)

    def enqueue(self, packet_id, receiver, water_m3, materials_kg, *, duration_s,
                source, attached_pore_liquid_m3=0, momentum=(0., 0.)):
        """A finite source store, not a discharge-derived sediment guess.

        Momentum supplied is the packet's total integrated mixture momentum.
        Thermal parcels are unsupported here and must use their thermal owner;
        an absent pore term is the explicit caller default zero, not inferred
        from rock porosity. Carrier and attached liquid are disjoint inputs.
        """
        if not packet_id or packet_id in self.consumed or packet_id in self.pulses:
            raise ValueError('duplicate or empty coastal transfer ID')
        if self.active_interval is not None:
            raise ValueError('cannot change source inventory during an interrupted forcing interval')
        if receiver not in self.cells or not source:
            raise ValueError('named receiving store and source evidence required')
        duration = s.q(duration_s, positive=True)
        free = s.q(water_m3, nonnegative=True)+s.q(attached_pore_liquid_m3, nonnegative=True)
        masses = {mid: s.q(mass, nonnegative=True) for mid, mass in materials_kg.items()}
        for mid in masses:
            s.density(mid, self.palette)
        if len(momentum) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in momentum):
            raise ValueError('explicit packet momentum required')
        record = {'receiver': receiver, 'water': free, 'materials': masses,
                  'momentum': tuple(momentum), 'end': self.time+duration, 'source': source,
                  'carrier': str(s.q(water_m3)), 'attached_pores': str(s.q(attached_pore_liquid_m3))}
        self.pulses[packet_id] = record
        self.consumed[packet_id] = p.sha(s.plain(record))
        self.source_packets[packet_id] = {'start_s': str(self.time), 'packet': s.plain(record)}

    def _inject(self, dt):
        applied = []
        for identity, pulse in list(sorted(self.pulses.items())):
            remaining = pulse['end']-self.time
            if remaining <= 0 or dt > remaining:
                raise ValueError('pulse endpoint must bound the substep')
            fraction = dt/remaining
            def amount(stock):
                return stock if fraction == 1 else min(stock, s.represented(stock*fraction))
            water = amount(pulse['water'])
            materials = {mid: amount(mass) for mid, mass in pulse['materials'].items()}
            cell = self.cells[pulse['receiver']]
            cell.free = s.q(cell.free+water, nonnegative=True); pulse['water'] -= water
            self.imported['water_m3'] = s.q(self.imported['water_m3']+water, nonnegative=True)
            for mid, mass in materials.items():
                cell.suspended[mid] = s.q(cell.suspended.get(mid, F())+mass, nonnegative=True)
                pulse['materials'][mid] -= mass
                self.imported['materials_kg'][mid] = s.q(self.imported['materials_kg'].get(mid, F())+mass, nonnegative=True)
                self.imported['solid_m3'][mid] = s.q(self.imported['materials_kg'][mid]/s.density(mid, self.palette), nonnegative=True)
            momentum = tuple(value*float(fraction) for value in pulse['momentum'])
            cell.momentum = tuple(a+b for a, b in zip(cell.momentum, momentum))
            pulse['momentum'] = tuple(a-b for a, b in zip(pulse['momentum'], momentum))
            applied.append({'packet': identity, 'water_m3': str(water), 'materials_kg': s.plain(materials),
                            'momentum': list(momentum), 'source': pulse['source']})
            if fraction == 1:
                del self.pulses[identity]
        return applied

    def advance(self, end_s, forcing, *, max_step_s=30, max_steps=10000):
        """Advance one constant-forcing interval fully or retain a failed prefix.

        Bed exchange is split half/full/half around the water stage; the
        receiving-water solver itself is first order. Refinement is required
        evidence, not an assertion that this composition is second order.
        """
        from . import flow, sediment
        end = s.q(end_s)
        maximum = s.q(max_step_s, positive=True)
        if end < self.time or type(max_steps) is not int or max_steps <= 0:
            raise ValueError('forward bounded coastal interval required')
        p.verify(self.execution)
        if owner.binding() != self.owner:
            raise ValueError('coastal owner binding changed')
        if end == self.time:
            return self.checkpoint()
        forcing_hash = p.sha(forcing)
        if self.active_interval is None:
            self.intervals.append({'start_s': str(self.time), 'end_s': str(end),
                'forcing': deepcopy(forcing), 'forcing_sha256': forcing_hash, 'complete': False})
            self.active_interval = len(self.intervals)-1
        interval = self.intervals[self.active_interval]
        if s.q(interval['end_s']) != end or interval['forcing_sha256'] != forcing_hash:
            raise ValueError('interrupted coastal interval requires its bound end and forcing')
        count = 0
        while self.time < end:
            if count >= max_steps:
                raise ValueError('coastal step budget exhausted; retained prefix is not completion')
            count += 1
            remaining = min(end-self.time, maximum,
                min((v['end']-self.time for v in self.pulses.values()), default=end-self.time))
            dt = min(remaining, F(flow.stable_dt(self.cells, self.palette, self.faces, self.links,
                self.constants, self.parameters, forcing, float(remaining))))
            if dt <= 0 or self.time+dt == self.time:
                raise ValueError('non-progressing coastal timestep')
            before = deepcopy((self.cells, self.pulses, self.imported))
            try:
                injection = self._inject(dt)
                bed_before = {key: str(cell.column.surface_m) for key, cell in self.cells.items()}
                first = {key: sediment.evolve(cell, self.palette, float(dt)/2,
                         self.parameters, forcing) for key, cell in sorted(self.cells.items())}
                # New input and bed changes can tighten the stability bound.
                allowed = flow.stable_dt(self.cells, self.palette, self.faces, self.links,
                    self.constants, self.parameters, forcing, float(dt))
                if allowed < float(dt)*(1-1e-12):
                    self.cells, self.pulses, self.imported = before
                    maximum = min(maximum, F(allowed)*F(9, 10))
                    continue
                water = flow.advance(self.cells, self.palette, self.faces, self.links,
                    float(dt), self.constants, self.parameters, forcing)
                second = {key: sediment.evolve(cell, self.palette, float(dt)/2,
                          self.parameters, forcing) for key, cell in sorted(self.cells.items())}
                if sum(len(cell.column.layers) for cell in self.cells.values()) > 2048:
                    raise ValueError('native finite layer budget exceeded')
                current = s.inventory(self.cells, self.palette)
                for cell in self.cells.values():
                    volume = cell.volume(self.palette)
                    if volume and (volume-cell.free)/volume > s.q(self.parameters['dilute_suspended_solid_volume_fraction_max']):
                        raise ValueError('coastal accepted state exceeds owner dilute applicability')
                account = s.balances(self.initial, self.imported, current, self.palette)
            except Exception:
                self.cells, self.pulses, self.imported = before
                raise
            self.receipts.append({'start_s': str(self.time), 'duration_s': str(dt), 'imports': injection,
                'forcing_sha256': forcing_hash, 'forcing_interval': self.active_interval,
                'flow': water, 'first_bed': first, 'second_bed': second,
                'bed_before_m': bed_before,
                'bed_after_m': {key: str(cell.column.surface_m) for key, cell in self.cells.items()},
                'water_residual_m3': account['water_residual_m3']})
            self.time += dt
        p.verify(self.execution)
        interval['complete'] = True
        self.active_interval = None
        return self.checkpoint()

    def checkpoint(self):
        current = s.inventory(self.cells, self.palette)
        status = 'SYNTHETIC TEST' if any(cell.column.source_status == 'SYNTHETIC TEST' for cell in self.cells.values()) else 'WORKING NON-CANON'
        science = {'schema': 'diadem.coastal-continuation.r19', 'status': status,
            'time_s': str(self.time), 'cells': {key: cell.as_dict() for key, cell in sorted(self.cells.items())},
            'palette': self.palette, 'faces': self.faces, 'links': self.links,
            'parameters': self.parameters, 'constants': self.constants,
            'evidence': self.evidence, 'lineage': self.lineage, 'owner': self.owner,
            'pulses': s.plain(self.pulses), 'consumed': self.consumed,
            'source_packets': self.source_packets,
            'intervals': deepcopy(self.intervals), 'active_interval': self.active_interval,
            'initial': s.plain(self.initial), 'imported': s.plain(self.imported),
            'receipts': deepcopy(self.receipts),
            'accounts': s.balances(self.initial, self.imported, current, self.palette)}
        return {'scientific': deepcopy(science), 'execution': self.execution,
                'scientific_sha256': p.sha(science)}

    @classmethod
    def restore(cls, checkpoint):
        p.verify(checkpoint['execution'])
        science = checkpoint['scientific']
        if p.sha(science) != checkpoint['scientific_sha256'] or science['owner'] != owner.binding():
            raise ValueError('coastal checkpoint source/science mismatch')
        if science['schema'] != 'diadem.coastal-continuation.r19':
            raise ValueError('coastal checkpoint schema differs')
        palette = science['palette']
        result = cls({key: s.Cell.from_dict(row, palette) for key, row in science['cells'].items()},
            palette, science['faces'], science['links'], evidence=science['evidence'],
            lineage=science['lineage'], parameters=science['parameters'])
        result.time = s.q(science['time_s'])
        result.consumed = deepcopy(science['consumed'])
        result.source_packets = deepcopy(science['source_packets'])
        result.intervals = deepcopy(science['intervals'])
        result.active_interval = science['active_interval']
        result.pulses = deepcopy(science['pulses'])
        for pulse in result.pulses.values():
            for name in ('water', 'end'):
                pulse[name] = s.q(pulse[name])
            pulse['materials'] = {mid: s.q(value) for mid, value in pulse['materials'].items()}
            pulse['momentum'] = tuple(pulse['momentum'])
        def account(record):
            return {key: ({mid: s.q(value) for mid, value in row.items()} if isinstance(row, dict) else s.q(row))
                    for key, row in record.items()}
        result.initial, result.imported = account(science['initial']), account(science['imported'])
        result.receipts = deepcopy(science['receipts'])
        result._verify_history()
        if result.constants != science['constants'] or result.execution != checkpoint['execution']:
            raise ValueError('coastal runtime/configuration changed')
        if result.checkpoint()['scientific_sha256'] != checkpoint['scientific_sha256']:
            raise ValueError('coastal checkpoint semantic readback differs')
        return result

    def _verify_history(self):
        """Reconcile once-only packet stores and the actual accepted clock."""
        if set(self.consumed) != set(self.source_packets) or not set(self.pulses) <= set(self.consumed):
            raise ValueError('coastal transfer cursor differs from its original source inventory')
        delivered = {key: {'water': F(), 'materials': {}, 'momentum': [[], []]} for key in self.consumed}
        def momentum(vector):
            if type(vector) not in (list, tuple) or len(vector) != 2 or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                raise ValueError('finite source/pending/delivered momentum vector required')
            return vector
        previous = F()
        for index, interval in enumerate(self.intervals):
            start, end = s.q(interval['start_s']), s.q(interval['end_s'])
            if start != previous or end <= start or p.sha(interval['forcing']) != interval['forcing_sha256']:
                raise ValueError('coastal forcing schedule/binding differs')
            if interval['complete'] is not (index != self.active_interval):
                raise ValueError('coastal interval completion cursor differs')
            if interval['complete'] and end > self.time:
                raise ValueError('completed forcing interval extends past accepted time')
            previous = end
        if self.active_interval is not None and (type(self.active_interval) is not int
                or self.active_interval != len(self.intervals)-1
                or not s.q(self.intervals[-1]['start_s']) <= self.time < s.q(self.intervals[-1]['end_s'])):
            raise ValueError('invalid interrupted forcing continuation')
        elapsed = F()
        for row in self.receipts:
            duration = s.q(row['duration_s'], positive=True)
            if s.q(row['start_s']) != elapsed:
                raise ValueError('coastal receipt clock is not contiguous')
            index = row['forcing_interval']
            if type(index) is not int or not 0 <= index < len(self.intervals):
                raise ValueError('accepted substep has no bound forcing interval')
            interval = self.intervals[index]
            if (row['forcing_sha256'] != interval['forcing_sha256']
                    or elapsed < s.q(interval['start_s']) or elapsed+duration > s.q(interval['end_s'])):
                raise ValueError('accepted substep forcing/interval differs')
            for item in row['imports']:
                identity = item['packet']
                if identity not in delivered:
                    raise ValueError('delivered packet absent from once-only source inventory')
                original = self.source_packets[identity]
                packet = original['packet']
                if (elapsed < s.q(original['start_s']) or elapsed+duration > s.q(packet['end'])
                        or item['source'] != packet['source']):
                    raise ValueError('delivered source interval/provenance differs')
                delivered[identity]['water'] += s.q(item['water_m3'], nonnegative=True)
                for axis, value in enumerate(momentum(item['momentum'])):
                    delivered[identity]['momentum'][axis].append(value)
                for mid, value in item['materials_kg'].items():
                    delivered[identity]['materials'][mid] = delivered[identity]['materials'].get(mid, F())+s.q(value, nonnegative=True)
            elapsed += duration
        if elapsed != self.time:
            raise ValueError('saved coastal time differs from accepted receipt prefix')
        total_water = F(); total_mass = {}
        for identity, original in self.source_packets.items():
            packet = original['packet']
            if self.consumed[identity] != p.sha(packet) or packet['receiver'] not in self.cells:
                raise ValueError('original coastal packet binding/receiver differs')
            start, end = s.q(original['start_s'], nonnegative=True), s.q(packet['end'])
            if not start <= self.time or end <= start:
                raise ValueError('invalid original packet interval')
            pending = self.pulses.get(identity, {'water': F(), 'materials': {}, 'momentum': [0., 0.]})
            if identity in self.pulses and (pending['end'] != end or end <= self.time
                    or pending['receiver'] != packet['receiver'] or pending['source'] != packet['source']):
                raise ValueError('pending packet continuation differs')
            done = delivered[identity]
            original_momentum, pending_momentum = momentum(packet['momentum']), momentum(pending['momentum'])
            for axis in range(2):
                operands = [original_momentum[axis], -pending_momentum[axis],
                            *(-v for v in done['momentum'][axis])]
                allowance = 64*2.220446049250313e-16*math.fsum(abs(v) for v in operands)
                if abs(math.fsum(operands)) > allowance:
                    raise ValueError('packet momentum delivered/remaining does not close')
            if done['water']+s.q(pending['water'], nonnegative=True) != s.q(packet['water'], nonnegative=True):
                raise ValueError('packet liquid delivered/remaining does not close')
            if s.q(packet['carrier'], nonnegative=True)+s.q(packet['attached_pores'], nonnegative=True) != s.q(packet['water']):
                raise ValueError('packet carrier and attached pore water are not disjoint')
            for mid in set(packet['materials']) | set(done['materials']) | set(pending['materials']):
                s.density(mid, self.palette)
                if done['materials'].get(mid, F())+s.q(pending['materials'].get(mid, 0), nonnegative=True) != s.q(packet['materials'].get(mid, 0), nonnegative=True):
                    raise ValueError('packet grain inventory delivered/remaining does not close')
                total_mass[mid] = total_mass.get(mid, F())+done['materials'].get(mid, F())
            total_water += done['water']
        if total_water != self.imported['water_m3'] or any(total_mass.get(mid, F()) != self.imported['materials_kg'].get(mid, F())
                for mid in set(total_mass) | set(self.imported['materials_kg'])):
            raise ValueError('accepted imports differ from the once-only source ledger')
