"""Finite supply/export inventories in the ONE joined spatial transport solve.

Inventory nodes are not thermal cells or a geometric mantle model. Their
directed exchanges must come from the caller's physical interval certificate.
This module checks finite stock, exact volume closure and actual result binding;
it does not manufacture geometry or independently publish/commit anything.
SPDX-License-Identifier: AGPL-3.0-only
"""
from contextlib import ExitStack
from dataclasses import dataclass, field
from fractions import Fraction as Q
import hashlib
import json
from pathlib import Path
import weakref

from ._validation import TectonicsError
from .integration_mimetic_heat import _enc, _q
from .integration_regional_inventory import _width
from .integration_spatial_transport import (SpatialTransportResult, _json_encoding_capacity,
    _workspace, _preserve_workspace)
from .resources import WorkBudget, _ResizableLease
from .integration_routing_views import _decoded_json_capacity, _decode_workspace

_LOADED = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MATERIAL_QUADRATURE = 'material_quadrature_m3'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _name(value):
    if type(value) is not str or not value or len(value) > 512:
        raise TectonicsError('bounded nonempty inventory identity required')
    return value



def _clone_graph(record, budget, owned):
    """Fund the actual complete mutable graph and release finished codec work."""
    capacity, scratch = _json_encoding_capacity(record, budget)
    with _workspace(budget, capacity, 'finite-stock-graph-bytes'):
        with _workspace(budget, scratch, 'finite-stock-graph-encode'):
            encoded = _json(record)
        if len(encoded)+64 > capacity:
            raise RuntimeError('Canonical finite graph exceeded its admitted byte capacity')
        owned.enter_context(budget.reserve(_decoded_json_capacity(encoded),
                                           category='finite-stock-live-graph-copy'))
        with _workspace(budget, _decode_workspace(encoded), 'finite-stock-graph-decode'):
            return json.loads(encoded)


def _proposal_work(physical_graph, physical_stocks, exchanges, state):
    """Additional numeric tables and new rows, excluding copied provenance."""
    # Keep the preceding generous arithmetic allowance for every consumed
    # numeric/identity field. Complete copied geometry is separately charged.
    size = _width(physical_stocks)+_width(exchanges)
    for row in physical_graph['cells']:
        size += sum(_width(row[key]) for key in ('cell_id', 'start_volume_m3', 'end_volume_m3'))
    for row in physical_graph['transfers']:
        size += sum(_width(row[key]) for key in ('face_id', 'donor', 'receiver', 'volume_m3'))
    # The existing state wrapper plus stock arithmetic/new inventory rows.
    size += _decoded_json_capacity(state._encoded)
    return 131072+12*size+_decode_workspace(state._encoded)


def _issue(cls, record, owner):
    capacity, scratch = _json_encoding_capacity(record, owner._budget)
    # One immutable byte buffer lives with the issued result. Admission occurs
    # before encoding; string/encoder workspace ends when issuance returns.
    retained = ExitStack()
    live = retained.enter_context(_ResizableLease(owner._budget, category='finite-spatial-stock-record'))
    live.resize(8192+capacity)
    committed = False
    try:
        with _workspace(owner._budget, scratch, 'finite-stock-issue-encode'):
            encoded = _json(record)
            if len(encoded)+64 > capacity:
                raise RuntimeError('Canonical finite record exceeded its admitted byte capacity')
            live.resize(8192+len(encoded))
            obj = object.__new__(cls)
            object.__setattr__(obj, '_encoded', encoded)
            object.__setattr__(obj, '_owner', owner)
            weakref.finalize(obj, retained.close)
            committed = True
            return obj
    except BaseException as error:
        failure_owner = _preserve_workspace(error, retained)
        raise
    finally:
        if not committed:
            retained.close()


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FiniteStockState:
    _encoded: bytes = field(repr=False)
    _owner: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('finite states are issued by their prepared owner')

    @property
    def state_id(self):
        return hashlib.sha256(self._encoded).hexdigest()

    def record(self):
        return dict(state_id=self.state_id, **json.loads(self._encoded))


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class FiniteStockProposal:
    _encoded: bytes = field(repr=False)
    _owner: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        raise TypeError('finite proposals are issued from retained stock')

    @property
    def proposal_id(self):
        return hashlib.sha256(self._encoded).hexdigest()

    def record(self):
        return dict(proposal_id=self.proposal_id, **json.loads(self._encoded))

    def graph(self):
        return json.loads(self._encoded)['graph']

    def stocks(self):
        return {k: tuple(map(_q, v)) for k, v in json.loads(self._encoded)['stocks'].items()}

    def _transport_inputs(self):
        """One privately owned decode for the joined consumer; no shared cache."""
        decoded = graph = stocks = None
        try:
            decoded = json.loads(self._encoded)
            graph = decoded['graph']
            stocks = {key: tuple(map(_q, values)) for key, values in decoded['stocks'].items()}
            return graph, stocks
        finally:
            # Outputs belong to the caller on success. A held failure traceback
            # must not retain the complete decoded proposal through these locals.
            decoded = graph = stocks = None


class PreparedFiniteStocks:
    """Frozen registry and finite stocks, advanced by an existing joined solve.

    A source only exports; a sink only receives. An explicitly declared
    reservoir receives and exports through the same well-mixed unknown in the
    joint implicit solve. Both directed streams are retained, not netted away.
    For a source with no incoming
    flux, BE gives c=old/V_start, so depletion is exact in the discrete model.
    Export reservoirs retain the actual solved donor mix, including signed
    enthalpy and history. Empty exhausted stocks remain in the retained record
    but are omitted from the matrix until they participate again. No mutable
    head exists here: the workflow's existing compare-and-swap publishes both
    physical and reservoir successors, or neither.

    volume_m3 is the geometric measure G used by the transport graph. An
    optional exact material_quadrature_m3 field declares an independent material
    measure B, carried once through the same solve and numerical accounts as
    every other extensive stock. Neither admission nor restoration infers B
    from G, component densities or masses. Omission preserves the legacy schema.
    """
    def __init__(self, registry_id, rows, *, field_names, nonnegative_fields, budget):
        self._closed, self._guard, self._initial = False, None, None
        if type(budget) is not WorkBudget or type(rows) is not list or not rows:
            raise TectonicsError('finite declared source/export rows and shared budget required')
        self._budget = budget
        self._names = tuple(field_names)
        self._positive = tuple(nonnegative_fields)
        if (not self._names or len(set(self._names)) != len(self._names) or
                len(set(self._positive)) != len(self._positive) or
                not set(self._positive) <= set(self._names)):
            raise TectonicsError('unique complete stock fields and declared positivity required')
        for name in self._names:
            _name(name)
        if _MATERIAL_QUADRATURE in self._names and _MATERIAL_QUADRATURE not in self._positive:
            raise TectonicsError('material quadrature must be declared nonnegative')
        self._guard = budget.reserve(65536+8*_width(rows), category='finite-spatial-stock-admission')
        self._guard.__enter__()
        try:
            seen = set()
            for row in rows:
                if type(row) is not dict or set(row) != {'stock_id', 'kind', 'lineage', 'volume_m3', 'exact'}:
                    raise TectonicsError('complete finite stock identity, lineage and exact inventory required')
                ident = _name(row['stock_id'])
                if ident in seen or row['kind'] not in ('source', 'sink', 'reservoir'):
                    raise TectonicsError('unique source/export stock identity required')
                seen.add(ident)
                if type(row['lineage']) is not dict or not row['lineage']:
                    raise TectonicsError('actual authored source or receiving export lineage required')
                self._check_fields(row)
            self._definition = dict(schema='atlas.finite-spatial-stocks.v1', registry_id=_name(registry_id),
                field_names=list(self._names), nonnegative_fields=list(self._positive),
                initial_stocks=json.loads(_json(sorted(rows, key=lambda r: r['stock_id']))))
            self.owner_id = _hash(self._definition)
            self._initial = self._state(dict(schema='atlas.finite-spatial-stock-state.v1', owner_id=self.owner_id,
                intervals=0, parent_state_id=None, transport_id=None, stocks=self._definition['initial_stocks'],
                projection_accounts={r['stock_id']: {k: _enc(0) for k in self._names} for r in rows}))
        except BaseException:
            self.close(); raise

    def _check_fields(self, row):
        if type(row['exact']) is not dict or set(row['exact']) != set(self._names):
            raise TectonicsError('every declared extensive field must be present')
        volume = _q(row['volume_m3'])
        values = {k: _q(v) for k, v in row['exact'].items()}
        self._check_values(volume, values)

    def _check_values(self, volume, values):
        if volume < 0 or any(values[k] < 0 for k in self._positive):
            raise TectonicsError('negative finite volume or declared positive stock')
        if not volume and any(values.values()):
            raise TectonicsError('zero physical stock volume cannot contain material or heat')
        if (_MATERIAL_QUADRATURE in values and not values[_MATERIAL_QUADRATURE] and
                any(v for k, v in values.items() if k != _MATERIAL_QUADRATURE)):
            raise TectonicsError('zero material quadrature cannot contain other extensive stocks')

    def _verify(self):
        if self._closed or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED:
            raise TectonicsError('closed or changed finite spatial stock owner')

    def definition(self):
        self._verify()
        return dict(owner_id=self.owner_id, **json.loads(_json(self._definition)))

    def initial(self):
        self._verify()
        return self._initial

    def _state(self, record):
        return _issue(FiniteStockState, record, self)

    def restore(self, record):
        """Immutable saved state validation, no transport or source reconstruction."""
        self._verify()
        with self._budget.reserve(65536+8*_width(record), category='finite-spatial-stock-restore'):
            if (type(record) is not dict or record.get('schema') != 'atlas.finite-spatial-stock-state.v1' or
                    record.get('owner_id') != self.owner_id or type(record.get('intervals')) is not int or
                    record['intervals'] < 0 or type(record.get('stocks')) is not list):
                raise TectonicsError('saved finite stock owner/state differs')
            if len(record['stocks']) != len(self._definition['initial_stocks']):
                raise TectonicsError('saved finite stock coverage differs')
            for row, original in zip(record['stocks'], self._definition['initial_stocks']):
                if (set(row) != set(original) or any(row[k] != original[k] for k in ('stock_id', 'kind', 'lineage'))):
                    raise TectonicsError('saved finite stock lineage/order differs')
                self._check_fields(row)
            if set(record.get('projection_accounts', {})) != {r['stock_id'] for r in record['stocks']}:
                raise TectonicsError('saved finite projection account coverage differs')
            for account in record['projection_accounts'].values():
                if set(account) != set(self._names):
                    raise TectonicsError('saved finite numerical fields differ')
                tuple(map(_q, account.values()))
            if not record['intervals']:
                if record != self.initial().record():
                    raise TectonicsError('saved finite root differs from its declared funding')
                return self.initial()
            _name(record.get('parent_state_id')); _name(record.get('transport_id'))
            body = {k: v for k, v in record.items() if k != 'state_id'}
            if _hash(body) != record.get('state_id'):
                raise TectonicsError('saved finite stock identity differs')
            return self._state(body)

    def prepare(self, state, physical_graph, physical_stocks, exchanges, *, source_stage_id,
                transport_parent_id=None):
        """Attach certified positive physical exchange volumes before transport.

        Each exchange has one stock_id, physical_cell_id, direction ('supply'
        or 'export'), unique face_id, volume_m3 and physical_certificate_id.
        The physical graph may be open before augmentation; its start/end
        volumes cannot be changed by this helper to hide a missing exchange.
        """
        self._verify()
        if type(state) is not FiniteStockState or state._owner is not self:
            raise TectonicsError('actual retained finite stock state required')
        _name(source_stage_id)
        transport_parent_id = state.state_id if transport_parent_id is None else _name(transport_parent_id)
        if type(exchanges) is not list or type(physical_graph) is not dict:
            raise TectonicsError('physical graph and explicit certified exchange list required')
        size = _proposal_work(physical_graph, physical_stocks, exchanges, state)
        with _workspace(self._budget, size, 'finite-spatial-stock-proposal') as owned:
            old = state.record()
            # Encoding copies exact declared geometry, not caller-owned mutable lists.
            graph = _clone_graph(physical_graph, self._budget, owned)
            cells, transfers = graph['cells'], graph['transfers']
            ids = [r['cell_id'] for r in cells]
            if len(set(ids)) != len(ids) or type(physical_stocks) is not dict or set(physical_stocks) != set(self._names):
                raise TectonicsError('unique physical cells and complete retained fields required')
            stocks = {k: [Q(v) for v in physical_stocks[k]] for k in self._names}
            if any(len(v) != len(ids) for v in stocks.values()):
                raise TectonicsError('physical stock shape differs from graph')
            if _MATERIAL_QUADRATURE in self._names:
                for at, cell in enumerate(cells):
                    self._check_values(_q(cell['start_volume_m3']), {k: v[at] for k, v in stocks.items()})
            by_id = {r['stock_id']: r for r in old['stocks']}
            nodes = {key: 'finite-stock:'+key for key in by_id}
            if set(ids) & set(nodes.values()):
                raise TectonicsError('physical cell ID aliases an inventory node')
            delta = dict.fromkeys(by_id, Q(0))
            used = set(); face_ids = {r['face_id'] for r in transfers}
            for row in exchanges:
                if set(row) != {'stock_id', 'physical_cell_id', 'direction', 'face_id', 'volume_m3', 'physical_certificate_id'}:
                    raise TectonicsError('complete certified finite exchange required')
                key, cell, fid = row['stock_id'], row['physical_cell_id'], _name(row['face_id'])
                _name(row['physical_certificate_id'])
                if key not in by_id or cell not in ids or fid in face_ids:
                    raise TectonicsError('finite exchange owner/cell/face mismatch')
                volume = _q(row['volume_m3'])
                if volume <= 0:
                    raise TectonicsError('positive physical exchange volume required')
                if row['direction'] == 'supply' and by_id[key]['kind'] in ('source', 'reservoir'):
                    donor, receiver = nodes[key], cell
                    delta[key] -= volume
                elif row['direction'] == 'export' and by_id[key]['kind'] in ('sink', 'reservoir'):
                    donor, receiver = cell, nodes[key]
                    delta[key] += volume
                else:
                    raise TectonicsError('supply/export direction disagrees with declared finite owner')
                used.add(key); face_ids.add(fid)
                transfers.append(dict(face_id=fid, donor=donor, receiver=receiver, volume_m3=_enc(volume),
                                      physical_certificate_id=row['physical_certificate_id']))
            active = []
            for key, row in by_id.items():
                before = _q(row['volume_m3']); after = before+delta[key]
                if after < 0:
                    raise TectonicsError('finite material supply exhausted; no implicit refill')
                if not before and key not in used:
                    continue
                active.append(key)
                cells.append(dict(cell_id=nodes[key], kind='inventory', stock_id=key,
                                  start_volume_m3=_enc(before), end_volume_m3=_enc(after)))
                for name in stocks:
                    stocks[name].append(_q(row['exact'][name]))
            volume_balance = {r['cell_id']: _q(r['start_volume_m3'])-_q(r['end_volume_m3']) for r in cells}
            for row in transfers:
                if row['donor'] not in volume_balance or row['receiver'] not in volume_balance:
                    raise TectonicsError('unowned physical transfer in finite graph')
                amount = _q(row['volume_m3'])
                volume_balance[row['donor']] -= amount
                volume_balance[row['receiver']] += amount
            if any(volume_balance.values()):
                raise TectonicsError('physical plus finite-stock graph violates exact GCL')
            graph['finite_inventory'] = dict(owner_id=self.owner_id, state_id=state.state_id,
                registry_id=self._definition['registry_id'], exchanges=exchanges)
            return _issue(FiniteStockProposal, dict(schema='atlas.finite-spatial-stock-proposal.v1',
                owner_id=self.owner_id, parent=old, source_stage_id=source_stage_id,
                transport_parent_id=transport_parent_id,
                graph=graph, physical_cell_ids=ids, active_stock_ids=active,
                stocks={k: list(map(_enc, v)) for k, v in stocks.items()}), self)

    def finish(self, proposal, result):
        """Read actual joined face transfers; return an uncommitted successor."""
        self._verify()
        if (type(proposal) is not FiniteStockProposal or proposal._owner is not self or
                type(result) is not SpatialTransportResult or result._budget is not self._budget):
            raise TectonicsError('actual finite proposal and same-budget joined transport required')
        p, r = proposal.record(), result.record()
        with self._budget.reserve(131072+8*(_width(p)+_width(r)), category='finite-spatial-stock-finish'):
            return self._state(self._finished_record(p, r))

    def _finished_record(self, p, r):
        if (r['geometry_id'] != _hash(p['graph']) or r['state_id'] != p['transport_parent_id'] or
                    r['source_stage_id'] != p['source_stage_id'] or r['exact_input_stocks'] != p['stocks'] or
                    tuple(r['nonnegative_fields']) != tuple(sorted(self._positive))):
            raise TectonicsError('joined transport differs from actual finite proposal/input')
        positions = {key: i for i, key in enumerate(r['cell_ids'])}
        endvol = {row['cell_id']: row['end_volume_m3'] for row in p['graph']['cells']}
        new = json.loads(_json(p['parent']))
        for row in new['stocks']:
            node = 'finite-stock:'+row['stock_id']
            if node not in positions:
                continue
            at = positions[node]
            # G follows geometric face-volume debits; B below is read from
            # the actual joined solve, never recomputed from this endpoint G.
            row['volume_m3'] = endvol[node]
            for name in self._names:
                row['exact'][name] = r['exact_stocks'][name][at]
                account = new['projection_accounts'][row['stock_id']]
                account[name] = _enc(_q(account[name])+_q(r['exact_projection_accounts'][name][at]))
            self._check_fields(row)
        new.pop('state_id')
        new.update(intervals=new['intervals']+1, parent_state_id=p['parent']['state_id'], transport_id=r['result_id'])
        return new

    def validate_saved(self, state_record, proposal_record, transport_record):
        """Bind saved stock to the caller-authenticated actual numerical audit.

        No solve or replay. Caller must first authenticate the saved transport
        arrays against its result_id, as SpatialOwner.validate_exchange does.
        """
        self._verify()
        with self._budget.reserve(131072+8*sum(map(_width, (state_record, proposal_record, transport_record))),
                                  category='finite-spatial-stock-audit'):
            if (type(proposal_record) is not dict or proposal_record.get('owner_id') != self.owner_id or
                    _hash({k: v for k, v in proposal_record.items() if k != 'proposal_id'}) != proposal_record.get('proposal_id')):
                raise TectonicsError('saved finite proposal identity differs')
            self.restore(proposal_record['parent'])
            expected = self._finished_record(proposal_record, transport_record)
            if dict(state_id=_hash(expected), **expected) != state_record:
                raise TectonicsError('saved finite state is not the actual transported successor')

    def close(self):
        if not self._closed:
            self._closed = True
            self._initial = None
            if self._guard is not None:
                self._guard.__exit__(None, None, None)
                self._guard = None

    def __enter__(self):
        self._verify()
        return self

    def __exit__(self, *_):
        self.close()
