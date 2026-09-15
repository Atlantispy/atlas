"""Independent mass/cost/path/cut oracles for exact static transport."""
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction as F
import itertools
import json
import random
import unittest
from unittest.mock import patch

from . import transport as t


def node(name,supply=0,demand=0):return t.Node(name,supply,demand,'SYNTHETIC_FIXTURE_EXPLICIT')
def link(name,a,b,capacity=10,time=1):
    return t.Link(name,a,b,time,1,capacity,0,True,'synthetic_carrier','SYNTHETIC_FIXTURE_EXPLICIT')
def solve(nodes,links,**kwargs):
    return t.solve_transport(nodes,links,period_seconds=86400,commodity_id='synthetic_fungible_food_kg',
        network_complete=True,evidence_id='EXPLICIT_SYNTHETIC_NETWORK',**kwargs)
def q(record):return F(record['exact'])


def brute_force(nodes,links):
    """Enumerate ALL integral link flows; no shortest-path/flow solver reused."""
    best=None
    for flows in itertools.product(*(range(int(e.capacity_kg)+1) for e in links)):
        net={n.node_id:0 for n in nodes};cost=0
        for e,flow in zip(links,flows):
            net[e.from_node]-=flow;net[e.to_node]+=flow
            cost+=flow*(F(e.length_m)/F(e.speed_m_s)+F(e.handling_time_s))
        delivered=0;valid=True
        for n in nodes:
            value=net[n.node_id]
            if n.supply_kg and n.demand_kg:raise ValueError('oracle fixtures keep sources and sinks disjoint')
            if n.supply_kg:valid &= -n.supply_kg<=value<=0
            elif n.demand_kg:valid &= 0<=value<=n.demand_kg;delivered+=value
            else:valid &= value==0
        if valid and (best is None or (-delivered,cost)<best):best=(-delivered,cost)
    return -best[0],best[1]


class TransportTests(unittest.TestCase):
    def assert_ledgers(self,result,nodes,links):
        self.assertTrue(result['solved']);self.assertFalse(result['production_authorised'])
        by_link={e.link_id:e for e in links};by_node={n.node_id:n for n in nodes}
        incoming={n: F(0) for n in by_node};outgoing=incoming.copy();route_flow={e.link_id:F(0) for e in links}
        cost=F(0)
        for row in result['flows']:
            edge=by_link[row['link_id']];flow=q(row['flow_kg']);capacity=F(edge.capacity_kg) if edge.available else F(0)
            self.assertGreaterEqual(flow,0);self.assertLessEqual(flow,capacity)
            self.assertEqual(flow+q(row['unused_capacity_kg']),capacity)
            outgoing[edge.from_node]+=flow;incoming[edge.to_node]+=flow
            cost+=flow*(F(edge.length_m)/F(edge.speed_m_s)+F(edge.handling_time_s))
        delivered=F(0);used=F(0)
        for row in result['nodes']:
            n=by_node[row['node_id']];d=q(row['delivered_kg']);s=q(row['used_supply_kg'])
            self.assertEqual(d+q(row['shortage_kg']),F(n.demand_kg))
            self.assertEqual(s+q(row['unused_supply_kg']),F(n.supply_kg))
            self.assertEqual(incoming[n.node_id]+s,outgoing[n.node_id]+d)
            delivered+=d;used+=s
        self.assertEqual(delivered,used);self.assertEqual(delivered,q(result['totals']['served_kg']))
        self.assertEqual(cost,q(result['totals']['transport_cost_kg_s']))
        for route in result['routes']:
            at=route['from_node'];time=F(0)
            for identifier in route['link_ids']:
                e=by_link[identifier];self.assertEqual(at,e.from_node);at=e.to_node
                route_flow[identifier]+=q(route['quantity_kg']);time+=F(e.length_m)/F(e.speed_m_s)+F(e.handling_time_s)
            self.assertEqual(at,route['to_node']);self.assertEqual(time,q(route['travel_time_s']))
        self.assertEqual(route_flow,{r['link_id']:q(r['flow_kg']) for r in result['flows']})
        self.assertEqual(F(result['certificate']['maximum_served_cut_capacity_kg']),delivered)
        self.assertGreaterEqual(F(result['certificate']['minimum_cost_residual_reduced_cost']),0)
        # Reconstruct the certificate from public input/output alone: no private
        # solver arcs, distances, reachability or certificate functions reused.
        names=sorted(by_node);pos={name:i for i,name in enumerate(names)};source=len(names);sink=source+1
        potentials=[F(x) for x in result['certificate']['minimum_cost_potentials_s']]
        self.assertEqual(len(potentials),len(names)+2)
        source_side={source}|{pos[name] for name in result['certificate']['maximum_flow_cut_source_side_nodes']}
        declared_arcs=[];flow_map={r['link_id']:q(r['flow_kg']) for r in result['flows']}
        for e in links:
            declared_arcs.append((pos[e.from_node],pos[e.to_node],F(e.capacity_kg) if e.available else F(0),flow_map[e.link_id],F(e.length_m)/F(e.speed_m_s)+F(e.handling_time_s)))
        for row in result['nodes']:
            n=by_node[row['node_id']];i=pos[n.node_id]
            declared_arcs.extend(((source,i,F(n.supply_kg),q(row['used_supply_kg']),F(0)),(i,sink,F(n.demand_kg),q(row['delivered_kg']),F(0))))
        cut=F(0)
        for a,b,capacity,flow,cost in declared_arcs:
            if a in source_side and b not in source_side:cut+=capacity
            if flow<capacity:self.assertGreaterEqual(cost+potentials[a]-potentials[b],0)
            if flow>0:self.assertGreaterEqual(-cost+potentials[b]-potentials[a],0)
        self.assertEqual(cut,delivered)
        json.dumps(result,allow_nan=False)

    def test_physical_path_ignores_direct_distance(self):
        nodes=[node('A',10),node('B'),node('C',demand=10)]
        links=[link('slow_direct','A','C',10,100),link('leg1','A','B',10,3),link('leg2','B','C',10,4)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(result['routes'][0]['link_ids'],['leg1','leg2'])
        self.assertEqual(q(result['totals']['transport_cost_kg_s']),70)

    def test_bottleneck_and_alternate_route(self):
        nodes=[node('A',10),node('B'),node('C',demand=10)]
        links=[link('ab','A','B',3,1),link('bc','B','C',3,1),link('ac','A','C',4,5)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),7);self.assertEqual(q(result['totals']['transport_cost_kg_s']),26)
        self.assertEqual(q(result['totals']['additional_network_limited_deficit_kg']),3)

    def test_shared_link_capacity_not_repeated_per_settlement(self):
        nodes=[node('A',5),node('B',5),node('X'),node('Y'),node('D',demand=5),node('E',demand=5)]
        links=[link('ax','A','X'),link('bx','B','X'),link('xy','X','Y',6),link('yd','Y','D'),link('ye','Y','E')]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),6)
        self.assertEqual(q(next(r for r in result['flows'] if r['link_id']=='xy')['flow_kg']),6)

    def test_residual_reroutes_early_cheapest_assignment(self):
        nodes=[node('A',1),node('B',1),node('X',demand=1),node('Y',demand=1)]
        links=[link('ax','A','X',1,1),link('ay','A','Y',1,2),link('bx','B','X',1,2)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),2);self.assertEqual(q(result['totals']['transport_cost_kg_s']),4)
        self.assertEqual({r['link_id']:q(r['flow_kg']) for r in result['flows']},{'ax':0,'ay':1,'bx':1})

    def test_antiparallel_physical_link_not_residual_reverse(self):
        nodes=[node('A',1),node('B',1),node('X',demand=1),node('Y',demand=1)]
        links=[link('ax','A','X',1,1),link('xa','X','A',3,5),link('ay','A','Y',1,2),link('bx','B','X',1,2)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),2)
        self.assertEqual(q(next(r for r in result['flows'] if r['link_id']=='xa')['flow_kg']),0)

    def test_parallel_links_remain_distinct(self):
        nodes=[node('A',5),node('B',demand=5)];links=[link('fast','A','B',2,1),link('slow','A','B',5,3)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['transport_cost_kg_s']),11)

    def test_maximum_delivery_precedes_time_efficiency(self):
        nodes=[node('A',2),node('X',demand=1),node('Y',demand=1)]
        links=[link('cheap','A','X',1,1),link('costly','A','Y',1,10**20)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),2)

    def test_exact_fractional_conservation(self):
        nodes=[node('A',F(2,3)),node('B',demand=F(2,3))];links=[link('ab','A','B',F(1,3),F(7,9))]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(result['totals']['served_kg']['exact'],'1/3')
        self.assertEqual(result['totals']['transport_cost_kg_s']['exact'],'7/27')

    def test_decimal_physical_values(self):
        nodes=[node('A',Decimal('.3')),node('B',demand=Decimal('.3'))]
        links=[replace(link('ab','A','B',Decimal('.3')),length_m=Decimal('1.2'),speed_m_s=Decimal('.4'),handling_time_s=Decimal('.5'))]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(result['totals']['transport_cost_kg_s']['exact'],'21/20')

    def test_float_is_exact_supplied_binary_value(self):
        nodes=[node('A',.1),node('B',demand=.1)];links=[link('ab','A','B',.1)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(q(result['totals']['served_kg']),F(.1))

    def test_local_demand_consumes_without_invented_link(self):
        nodes=[node('A',7,3)];result=solve(nodes,[]);self.assert_ledgers(result,nodes,[])
        self.assertEqual(result['routes'][0]['link_ids'],[])
        self.assertEqual(q(result['nodes'][0]['unused_supply_kg']),4)

    def test_undelivered_local_stock_retained(self):
        nodes=[node('A',10),node('B',demand=10)];result=solve(nodes,[]);self.assert_ledgers(result,nodes,[])
        self.assertEqual(result['nodes'][1]['status'],'NO_PATH_FROM_KNOWN_SUPPLY')
        self.assertEqual(q(result['nodes'][0]['unused_supply_kg']),10)

    def test_no_supply_is_shortage_not_unknown_or_no_path(self):
        nodes=[node('A',0,5)];result=solve(nodes,[]);self.assert_ledgers(result,nodes,[])
        self.assertEqual(result['nodes'][0]['status'],'SHORTAGE');self.assertEqual(q(result['totals']['minimum_supply_deficit_kg']),5)

    def test_zero_capacity_known_route_is_capacity_shortage(self):
        nodes=[node('A',2),node('B',demand=2)];links=[link('ab','A','B',0)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(result['nodes'][1]['status'],'SHORTAGE')

    def test_explicit_closed_link_cannot_carry_flow(self):
        nodes=[node('A',2),node('B',demand=2)];links=[replace(link('ab','A','B'),available=False)]
        result=solve(nodes,links);self.assert_ledgers(result,nodes,links)
        self.assertEqual(result['nodes'][1]['status'],'NO_PATH_FROM_KNOWN_SUPPLY')

    def test_direction_is_not_assumed_bidirectional(self):
        nodes=[node('A',2),node('B',demand=2)];result=solve(nodes,[link('ba','B','A')])
        self.assertEqual(q(result['totals']['served_kg']),0)

    def test_missing_node_evidence_is_unsolved(self):
        result=solve([node('A',None),node('B',demand=2)],[])
        self.assertEqual(result['status'],'MISSING_EVIDENCE');self.assertFalse(result['solved']);self.assertIsNone(result['flows'])
        self.assertEqual(result['missing'],['node:A:supply_kg'])

    def test_missing_physical_link_field_is_unsolved(self):
        for name in ('length_m','speed_m_s','capacity_kg','handling_time_s','available'):
            with self.subTest(name=name):
                result=solve([node('A',1),node('B',demand=1)],[replace(link('ab','A','B'),**{name:None})])
                self.assertEqual(result['status'],'MISSING_EVIDENCE');self.assertIn(f'link:ab:{name}',result['missing'])

    def test_incomplete_network_never_certifies_no_path(self):
        result=t.solve_transport([node('A',1),node('B',demand=1)],[],period_seconds=1,commodity_id='food',network_complete=False,evidence_id='fixture')
        self.assertEqual(result['status'],'MISSING_EVIDENCE');self.assertIn('network:topology_completeness',result['missing'])

    def test_all_zero_valid_input(self):
        result=solve([node('A'),node('B')],[])
        self.assertEqual(result['status'],'ALL_DEMAND_SERVED');self.assertEqual(result['routes'],[])

    def test_permutation_determinism(self):
        nodes=[node('A',5),node('B',5),node('D',demand=6)]
        links=[link('ad','A','D',5,2),link('bd','B','D',5,2)]
        self.assertEqual(solve(nodes,links),solve(list(reversed(nodes)),list(reversed(links))))

    def test_input_identity_changes_for_evidence_or_capacity(self):
        nodes=[node('A',1),node('B',demand=1)];links=[link('ab','A','B')]
        first=solve(nodes,links)['input_sha256']
        self.assertNotEqual(first,solve(nodes,[replace(links[0],capacity_kg=20)])['input_sha256'])
        self.assertNotEqual(first,solve(nodes,[replace(links[0],evidence_id='different source')])['input_sha256'])

    def test_bruteforce_forty_directed_three_node_graphs(self):
        rng=random.Random(408);nodes=[node('A',2),node('B'),node('C',demand=2)]
        pairs=list(itertools.permutations('ABC',2))
        for case in range(40):
            links=[link(a+b,a,b,rng.randrange(3),rng.randrange(1,5)) for a,b in pairs]
            expected=brute_force(nodes,links);result=solve(nodes,links)
            with self.subTest(case=case):
                self.assert_ledgers(result,nodes,links)
                self.assertEqual((q(result['totals']['served_kg']),q(result['totals']['transport_cost_kg_s'])),expected)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(t.TransportError):solve([node('A'),node('A')],[])
        with self.assertRaises(t.TransportError):solve([node('A'),node('B')],[link('ab','A','B'),link('ab','B','A')])

    def test_invalid_numeric_inputs_rejected(self):
        for bad in (True,float('nan'),float('inf'),-1,'1',F(1,2**129),2**257):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(t.TransportError):solve([node('A',bad)],[])

    def test_invalid_link_geometry_and_schema_rejected(self):
        nodes=[node('A'),node('B')];edge=link('ab','A','B')
        for changed in ({'length_m':0},{'speed_m_s':0},{'available':1},{'from_node':'missing'},
                        {'to_node':'A'},{'from_node':[]},{'handling_time_s':-1},{'capacity_kg':-1},{'mode':''},{'evidence_id':''}):
            with self.subTest(changed=changed):
                with self.assertRaises(t.TransportError):solve(nodes,[replace(edge,**changed)])

    def test_invalid_solver_contract_rejected(self):
        for bad in (0,-1,True,4097):
            with self.assertRaises(t.TransportError):solve([node('A')],[],max_augmentations=bad)
        with self.assertRaises(t.TransportError):solve([],[])
        with self.assertRaises(t.TransportError):solve([node(str(i)) for i in range(129)],[])
        with self.assertRaises(t.TransportError):solve([{'node_id':'A'}],[])

    def test_augmentation_budget_never_returns_partial_optimum(self):
        nodes=[node('A',2),node('B',demand=1),node('C',demand=1)]
        with self.assertRaisesRegex(t.TransportError,'augmentation budget'):
            solve(nodes,[link('ab','A','B',1),link('ac','A','C',1)],max_augmentations=1)

    def test_work_budget_never_returns_false_certificate(self):
        with patch.object(t,'MAX_RELAXATIONS',1):
            with self.assertRaisesRegex(t.TransportError,'work budget'):solve([node('A',1),node('B',demand=1)],[link('ab','A','B')])

    def test_certificate_detects_corrupt_negative_cycle(self):
        arcs=[];adj=[[],[]]
        t._add(arcs,adj,0,1,F(1),F(-1),'one','link');t._add(arcs,adj,1,0,F(1),F(0),'two','link')
        with self.assertRaisesRegex(t.TransportError,'negative cycle'):t._minimum_cost_potentials(arcs,2,[0])


if __name__=='__main__':unittest.main()
