import io
import json
import unittest
from sc_bridge import BridgeError
from sc_mcp.server import Server

class FakeBridge:
    def status(self): raise BridgeError('HOST_OFFLINE','Game unavailable')
    def read_region(self, **arguments): return arguments

class ServerTests(unittest.TestCase):
    def setUp(self): self.server=Server(FakeBridge())
    def initialize(self):
        result=self.server.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{
            'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        self.assertEqual(result['result']['protocolVersion'],'2025-03-26')
        self.assertIsNone(self.server.handle({'jsonrpc':'2.0','method':'notifications/initialized'}))
    def test_lifecycle(self):
        self.assertIn('error',self.server.handle({'jsonrpc':'2.0','id':0,'method':'tools/list'}))
        self.initialize()
        tools=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools']
        self.assertGreaterEqual(len(tools),30)
        self.assertNotIn('exec_js',[t['name'] for t in tools])
    def test_offline_is_tool_error(self):
        self.initialize()
        result=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'status'}})
        self.assertTrue(result['result']['isError'])
    def test_input_types_and_extra_fields(self):
        self.initialize()
        for arguments in [{'minimum':[0,False,0],'maximum':[0,0,0]},
                          {'minimum':[0,0,0],'maximum':[0,0,0],'extra':1}]:
            result=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call',
                'params':{'name':'read_region','arguments':arguments}})
            self.assertEqual(result['error']['code'],-32602)
    def test_stdio_has_only_json_and_notifications_have_no_reply(self):
        output=io.StringIO()
        self.server.serve(io.StringIO('invalid\n{"jsonrpc":"2.0","method":"unknown/notification"}\n'),output)
        lines=output.getvalue().splitlines()
        self.assertEqual(len(lines),1)
        self.assertEqual(json.loads(lines[0])['error']['code'],-32700)
    def test_finite_bounded_loading_timeout(self):
        self.initialize()
        for number in (-1,31,float('nan'),float('inf')):
            result=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'prepare_region','arguments':{'minimum':[0,0,0],'maximum':[0,0,0],'timeout_seconds':number}}})
            self.assertEqual(result['error']['code'],-32602)

    def test_closed_readonly_condition_and_inventory_schema(self):
        self.initialize()
        cases=[('condition_query',{'name':'fileexist'}),('condition_query',{'name':'statsrange','subtype':'arbitrary'}),
            ('condition_query',{'name':'levelrange','minimum':float('nan'),'maximum':10}),
            ('condition_query',{'name':'levelrange','minimum':10**400,'maximum':10**401}),
            ('inventory_read',{'offset':False}),('inventory_read',{'limit':65}),('player_state',{'path':'Health'})]
        for name,arguments in cases:
            with self.subTest(name=name,arguments=arguments):
                result=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':name,'arguments':arguments}})
                self.assertEqual(result['error']['code'],-32602)

    def test_entity_schema_guards(self):
        self.initialize()
        bounds={'minimum':[0,0,0],'maximum':[1,1,1]}
        for extra in ({'limit':65},{'limit':True},{'kind':'npc'},{'template':''},{'template':'x'*129},{'cursor':'arbitrary'},{'script':'anything'}):
            result=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'entity_query','arguments':bounds|extra}})
            self.assertEqual(result['error']['code'],-32602)

    def test_creature_click_not_exposed(self):
        self.initialize()
        tools=self.server.handle({'jsonrpc':'2.0','id':2,'method':'tools/list'})['result']['tools']
        event=next(t for t in tools if t['name']=='event_subscribe')
        self.assertNotIn('creature_click',event['inputSchema']['properties']['kinds']['items']['enum'])
        result=self.server.handle({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'event_subscribe','arguments':{'kinds':['creature_click']}}})
        self.assertEqual(result['error']['code'],-32602)

if __name__ == '__main__': unittest.main()
