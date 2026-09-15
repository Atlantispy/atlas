"""Bounded exact static, single-commodity transport assignment on known links.

No roads, demand, capacities or policy are inferred. Maximise served mass, then
minimise mass-weighted travel/handling time. This is not a time-expanded traffic
model or a multi-commodity allocation model. No file or production side effects.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from typing import Sequence


MAX_NODES=128
MAX_LINKS=512
MAX_AUGMENTATIONS=4096
MAX_RELAXATIONS=2_000_000


class TransportError(ValueError):
    """Invalid contract, resource envelope, or failed exact certificate."""


@dataclass(frozen=True)
class Node:
    node_id: str
    supply_kg: object
    demand_kg: object
    evidence_id: str


@dataclass(frozen=True)
class Link:
    link_id: str
    from_node: str
    to_node: str
    length_m: object
    speed_m_s: object
    capacity_kg: object
    handling_time_s: object
    available: bool | None
    mode: str
    evidence_id: str


def _label(value,name):
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise TransportError(name+': nonblank bounded text required')
    return value


def _quantity(value,name,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float,Fraction,Decimal)):
        raise TransportError(name+': finite real number required')
    if isinstance(value,(float,Decimal)) and not math.isfinite(value):
        raise TransportError(name+': finite real number required')
    try:q=Fraction(value)
    except (ValueError,OverflowError,ZeroDivisionError) as exc:
        raise TransportError(name+': unrepresentable rational input') from exc
    if q<0 or (positive and q==0):
        raise TransportError(name+': outside nonnegative/positive physical range')
    if q.numerator.bit_length()>256 or q.denominator.bit_length()>128:
        raise TransportError(name+': exact-rational input envelope exceeded')
    return q


def _exact(q):
    return str(q.numerator) if q.denominator==1 else f'{q.numerator}/{q.denominator}'


def _number(q):
    value=float(q)
    if not math.isfinite(value) or (q and not value):
        raise TransportError('result is not representable as a finite nonzero reporting number')
    return value


def _report(q):
    return {'value':_number(q),'exact':_exact(q)}


@dataclass
class _Arc:
    source:int
    target:int
    capacity:Fraction
    cost:Fraction
    reverse:int
    initial:Fraction
    label:str
    kind:str


def _add(arcs,adj,source,target,capacity,cost,label,kind):
    i=len(arcs)
    arcs.extend((_Arc(source,target,capacity,cost,i+1,capacity,label,kind),
                 _Arc(target,source,Fraction(0),-cost,i,Fraction(0),label,'reverse')))
    adj[source].append(i);adj[target].append(i+1)


def _charge(budget,amount):
    budget[0]+=amount
    if budget[0]>MAX_RELAXATIONS:raise TransportError('exact solver work budget exhausted; no optimal result released')


def _shortest(arcs,adj,source,budget):
    """Bellman-Ford accepts negative reverse costs; no greedy allocation lock-in."""
    count=len(adj);distance=[None]*count;parent=[None]*count;distance[source]=Fraction(0)
    for iteration in range(count):
        _charge(budget,len(arcs))
        changed=False
        for i,arc in enumerate(arcs):
            if arc.capacity<=0 or distance[arc.source] is None:continue
            candidate=distance[arc.source]+arc.cost
            if distance[arc.target] is None or candidate<distance[arc.target]:
                distance[arc.target]=candidate;parent[arc.target]=i;changed=True
        if not changed:return distance,parent
    raise TransportError('negative residual cycle: minimum-cost invariant failed')


def _reachable(arcs,adj,start):
    reached={start};queue=deque([start])
    while queue:
        for index in adj[queue.popleft()]:
            arc=arcs[index]
            if arc.capacity>0 and arc.target not in reached:
                reached.add(arc.target);queue.append(arc.target)
    return reached


def _minimum_cost_potentials(arcs,count,budget):
    # A virtual zero-cost source reaches every node. Nonnegative reduced cost on
    # every positive residual arc proves no negative-cost residual circulation.
    potential=[Fraction(0)]*count
    for _ in range(count):
        _charge(budget,len(arcs))
        changed=False
        for arc in arcs:
            if arc.capacity>0 and potential[arc.target]>potential[arc.source]+arc.cost:
                potential[arc.target]=potential[arc.source]+arc.cost;changed=True
        if not changed:return potential
    raise TransportError('negative cycle invalidates cost optimality')


def _decompose(arcs,adj,source,sink):
    remaining={i:a.initial-a.capacity for i,a in enumerate(arcs) if a.kind!='reverse'}
    routes=[]
    while any(remaining.get(i,0)>0 for i in adj[source]):
        parent={source:None};queue=deque([source])
        while queue and sink not in parent:
            for i in adj[queue.popleft()]:
                a=arcs[i]
                if remaining.get(i,0)>0 and a.target not in parent:
                    parent[a.target]=i;queue.append(a.target)
        if sink not in parent:raise TransportError('positive supply flow lacks a delivery path')
        path=[];at=sink
        while at!=source:
            i=parent[at];path.append(i);at=arcs[i].source
        path.reverse();quantity=min(remaining[i] for i in path)
        for i in path:remaining[i]-=quantity
        routes.append((quantity,path))
    if any(remaining.values()):raise TransportError('unattributed circulation remains in route decomposition')
    return routes


def _validate(nodes,links,period_seconds,commodity_id,network_complete,evidence_id,max_augmentations):
    period=_quantity(period_seconds,'accounting period seconds',True)
    _label(commodity_id,'commodity');_label(evidence_id,'network evidence')
    if type(network_complete) is not bool:raise TransportError('network_complete must be explicitly Boolean')
    if type(max_augmentations) is not int or not 1<=max_augmentations<=MAX_AUGMENTATIONS:
        raise TransportError('augmentation limit outside bounded solver envelope')
    if not isinstance(nodes,(list,tuple)) or not 1<=len(nodes)<=MAX_NODES:
        raise TransportError('bounded nonempty node sequence required')
    if not isinstance(links,(list,tuple)) or len(links)>MAX_LINKS:
        raise TransportError('bounded link sequence required')
    if any(type(n) is not Node for n in nodes) or any(type(e) is not Link for e in links):
        raise TransportError('typed Node/Link objects required')
    missing=[];node_values={};link_values={}
    for n in nodes:
        _label(n.node_id,'node ID');_label(n.evidence_id,'node evidence')
        if n.node_id in node_values:raise TransportError('duplicate node ID')
        values=[]
        for name in ('supply_kg','demand_kg'):
            value=getattr(n,name)
            if value is None:missing.append(f'node:{n.node_id}:{name}');values.append(None)
            else:values.append(_quantity(value,f'{n.node_id}:{name}'))
        node_values[n.node_id]=tuple(values)
    for e in links:
        _label(e.link_id,'link ID');_label(e.mode,'link mode');_label(e.evidence_id,'link evidence')
        _label(e.from_node,'source node ID');_label(e.to_node,'target node ID')
        if e.link_id in link_values:raise TransportError('duplicate link ID')
        if e.from_node not in node_values or e.to_node not in node_values:raise TransportError('link endpoint not in network')
        if e.from_node==e.to_node:raise TransportError('self links are not physical transport links')
        if e.available is not None and type(e.available) is not bool:raise TransportError('link availability must be Boolean or UNKNOWN')
        if e.available is None:missing.append(f'link:{e.link_id}:available')
        values=[]
        for name in ('length_m','speed_m_s','capacity_kg','handling_time_s'):
            value=getattr(e,name)
            if value is None:missing.append(f'link:{e.link_id}:{name}');values.append(None)
            else:values.append(_quantity(value,f'{e.link_id}:{name}',name in ('length_m','speed_m_s')))
        link_values[e.link_id]=tuple(values)
    if not network_complete:missing.append('network:topology_completeness')
    return period,node_values,link_values,sorted(missing)


def solve_transport(nodes:Sequence[Node],links:Sequence[Link],*,period_seconds,
                    commodity_id:str,network_complete:bool,evidence_id:str,
                    max_augmentations:int=MAX_AUGMENTATIONS):
    """Return certified maximum-served minimum-travel-time feasible flows.

    Supply, demand and capacity are kg of ONE fungible commodity in the same
    explicitly supplied accounting period. Transit nodes need explicit zero
    supply/demand. Links are directed; opposite-direction shared resources must
    be explicitly modelled, not supplied as two independent capacities.

    `None` means missing evidence and returns an unsolved MISSING_EVIDENCE record.
    With complete input, exact rational certificates prove mass conservation,
    link bounds, max-flow cut and minimum cost. Numeric values are accompanied
    by lossless rational strings. No access, priority or fairness is inferred.
    """
    period,nv,lv,missing=_validate(nodes,links,period_seconds,commodity_id,network_complete,evidence_id,max_augmentations)
    ordered_nodes=sorted(nodes,key=lambda n:n.node_id);ordered_links=sorted(links,key=lambda e:e.link_id)
    canonical={'commodity_id':commodity_id,'period_seconds':_exact(period),'network_complete':network_complete,'evidence_id':evidence_id,
        'nodes':[{'node_id':n.node_id,'supply_kg':None if nv[n.node_id][0] is None else _exact(nv[n.node_id][0]),
                  'demand_kg':None if nv[n.node_id][1] is None else _exact(nv[n.node_id][1]),'evidence_id':n.evidence_id} for n in ordered_nodes],
        'links':[{'link_id':e.link_id,'from_node':e.from_node,'to_node':e.to_node,'mode':e.mode,'available':e.available,'evidence_id':e.evidence_id,
                  'physical_values':[None if q is None else _exact(q) for q in lv[e.link_id]]} for e in ordered_links]}
    identity=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    base={'schema':'diadem.static-transport.r1','source_status':'WORKING NON-CANON','commodity_id':commodity_id,
          'period_seconds':_report(period),'input_sha256':identity,'objective':'MAXIMISE_SERVED_KG_THEN_MINIMISE_KG_SECONDS',
          'production_authorised':False,'network_evidence_id':evidence_id}
    if missing:return {**base,'status':'MISSING_EVIDENCE','missing':missing,'solved':False,'flows':None,'routes':None,'certificate':None}
    names=[n.node_id for n in ordered_nodes];index={name:i for i,name in enumerate(names)}
    count=len(names);source=count;sink=count+1;adj=[[] for _ in range(count+2)];arcs=[]
    for e in ordered_links:
        length,speed,capacity,handling=lv[e.link_id]
        cost=length/speed+handling
        _add(arcs,adj,index[e.from_node],index[e.to_node],capacity if e.available else Fraction(0),cost,e.link_id,'link')
    for n in ordered_nodes:
        supply,demand=nv[n.node_id]
        _add(arcs,adj,source,index[n.node_id],supply,Fraction(0),n.node_id,'supply')
        _add(arcs,adj,index[n.node_id],sink,demand,Fraction(0),n.node_id,'demand')
    served=Fraction(0);iterations=0;budget=[0]
    while True:
        distance,parent=_shortest(arcs,adj,source,budget)
        if distance[sink] is None:break
        if iterations>=max_augmentations:raise TransportError('augmentation budget exhausted; no optimal result released')
        path=[];at=sink;seen=set()
        while at!=source:
            if at in seen or parent[at] is None:raise TransportError('invalid shortest residual path')
            seen.add(at);i=parent[at];path.append(i);at=arcs[i].source
        amount=min(arcs[i].capacity for i in path)
        if amount<=0:raise TransportError('augmentation must be positive')
        for i in path:arcs[i].capacity-=amount;arcs[arcs[i].reverse].capacity+=amount
        served+=amount;iterations+=1
    physical=[(i,a) for i,a in enumerate(arcs) if a.kind=='link']
    balance=[Fraction(0)]*len(adj);cost=Fraction(0)
    for a in arcs:
        if a.kind=='reverse':continue
        flow=a.initial-a.capacity
        if not 0<=flow<=a.initial:raise TransportError('capacity certificate failed')
        balance[a.source]-=flow;balance[a.target]+=flow;cost+=flow*a.cost
    if any(balance[:count]) or balance[source]!=-served or balance[sink]!=served:
        raise TransportError('exact node mass-balance certificate failed')
    reached=_reachable(arcs,adj,source)
    cut=sum((a.initial for a in arcs if a.kind!='reverse' and a.source in reached and a.target not in reached),Fraction(0))
    if sink in reached or cut!=served:raise TransportError('max-flow/min-cut certificate failed')
    potentials=_minimum_cost_potentials(arcs,len(adj),budget)
    reduced=[a.cost+potentials[a.source]-potentials[a.target] for a in arcs if a.capacity>0]
    if any(value<0 for value in reduced):raise TransportError('minimum-cost reduced-cost certificate failed')
    routes=[]
    for amount,path in _decompose(arcs,adj,source,sink):
        path_arcs=[arcs[i] for i in path]
        travel=sum((a.cost for a in path_arcs),Fraction(0))
        routes.append({'from_node':path_arcs[0].label,'to_node':path_arcs[-1].label,
                       'link_ids':[a.label for a in path_arcs if a.kind=='link'],
                       'quantity_kg':_report(amount),'travel_time_s':_report(travel)})
    if sum((Fraction(r['quantity_kg']['exact']) for r in routes),Fraction(0))!=served:
        raise TransportError('route mass attribution failed')
    allocations={a.label:a.initial-a.capacity for a in arcs if a.kind=='demand'}
    used={a.label:a.initial-a.capacity for a in arcs if a.kind=='supply'}
    topology={name:[] for name in names}
    for e in ordered_links:
        if e.available:topology[e.from_node].append(e.to_node)
    supply_reach={name for name,(s,d) in nv.items() if s>0};queue=deque(sorted(supply_reach))
    while queue:
        for target in topology[queue.popleft()]:
            if target not in supply_reach:supply_reach.add(target);queue.append(target)
    demand_total=sum((v[1] for v in nv.values()),Fraction(0));supply_total=sum((v[0] for v in nv.values()),Fraction(0))
    node_results=[]
    for n in ordered_nodes:
        supply,demand=nv[n.node_id];short=demand-allocations[n.node_id]
        status=('NO_DEMAND' if demand==0 else 'FULFILLED' if short==0 else
                'NO_PATH_FROM_KNOWN_SUPPLY' if supply_total>0 and n.node_id not in supply_reach else 'SHORTAGE')
        node_results.append({'node_id':n.node_id,'status':status,'demand_kg':_report(demand),
            'delivered_kg':_report(allocations[n.node_id]),'shortage_kg':_report(short),
            'used_supply_kg':_report(used[n.node_id]),'unused_supply_kg':_report(supply-used[n.node_id])})
    flows=[{'link_id':a.label,'from_node':names[a.source],'to_node':names[a.target],
            'flow_kg':_report(a.initial-a.capacity),'available_capacity_kg':_report(a.initial),
            'unused_capacity_kg':_report(a.capacity),'travel_time_s':_report(a.cost)} for _,a in physical]
    supply_deficit=max(Fraction(0),demand_total-supply_total)
    return {**base,'status':'ALL_DEMAND_SERVED' if served==demand_total else 'PARTIAL_OR_UNSERVED_DEMAND',
        'solved':True,'flows':flows,'routes':routes,'nodes':node_results,
        'totals':{'supply_kg':_report(supply_total),'demand_kg':_report(demand_total),'served_kg':_report(served),
                  'shortage_kg':_report(demand_total-served),'minimum_supply_deficit_kg':_report(supply_deficit),
                  'additional_network_limited_deficit_kg':_report(demand_total-served-supply_deficit),'transport_cost_kg_s':_report(cost)},
        'certificate':{'arithmetic':'EXACT_RATIONAL','node_mass_residual_kg':'0','capacity_violations':0,
                       'maximum_served_cut_capacity_kg':_exact(cut),'minimum_cost_residual_reduced_cost':_exact(min(reduced,default=Fraction(0))),
                       'minimum_cost_potentials_s':[_exact(p) for p in potentials],
                       'maximum_flow_cut_source_side_nodes':[names[i] for i in sorted(reached) if i<count],
                       'augmentations':iterations,'residual_arc_scan_count':budget[0],'route_attribution':'EXACT_ALL_FLOW_NO_CIRCULATION'},
        'limitations':['single fungible commodity; shared capacities across commodities require one coupled model',
                      'steady accounting-period flow; transit times are costs, not delivery deadlines',
                      'fixed supplied network and physical speed/capacity; no road placement, traffic congestion or maintenance simulation',
                      'maximum total delivered mass before travel efficiency; no fairness, political priority or economic demand inferred']}
