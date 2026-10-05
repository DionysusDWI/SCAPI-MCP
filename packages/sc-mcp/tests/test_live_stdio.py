import json
import os
import subprocess
import sys
import unittest

@unittest.skipUnless(os.environ.get('SC_MCP_LIVE_CONFIG'),'Explicit lab configuration required')
class LiveStdioTests(unittest.TestCase):
    def test_050_audited_operation_and_event_lifecycle(self):
        from sc_bridge import Bridge,Config
        from sc_bridge.client import atomic_json
        import time
        config=os.environ['SC_MCP_LIVE_CONFIG'];target=Config.load(config);assert target.target.get('test_only') and target.target['name'].startswith('SC MCP LAB')
        old=Bridge(target).environment_info()['weather_enabled'];responses=[]
        process=subprocess.Popen([sys.executable,'-m','sc_mcp','--config',config],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        def rpc(method,params):
            ident=len(responses)+1;process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n');process.stdin.flush();r=json.loads(process.stdout.readline());responses.append(r);self.assertEqual(r['id'],ident);return r['result']
        def call(name,arguments):
            r=rpc('tools/call',{'name':name,'arguments':arguments});self.assertFalse(r['isError'],r);return json.loads(r['content'][0]['text'])
        try:
            rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'050-acceptance','version':'1'}})
            process.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');process.stdin.flush()
            sub=call('event_subscribe',{'kinds':['eat']});self.assertEqual(call('event_poll',{'subscription_id':sub['subscription_id']})['events'],[]);self.assertTrue(call('event_unsubscribe',{'subscription_id':sub['subscription_id']})['unsubscribed'])
            plan=call('environment_patch',{'weather_enabled':not old});result=call('operation_submit',{'operation_id':plan['operation_id'],'accept_risk':plan['risk']});deadline=time.monotonic()+10
            while result['state']!='completed':
                self.assertLess(time.monotonic(),deadline);time.sleep(.02);result=call('operation_status',{'operation_id':plan['operation_id']})
            self.assertEqual(result['after']['weather_enabled'],not old)
            restored=call('operation_restore',{'operation_id':plan['operation_id'],'accept_risk':plan['risk']})
            while restored['state']!='completed':
                self.assertLess(time.monotonic(),deadline);time.sleep(.02);restored=call('operation_status',{'operation_id':restored['operation_id']})
            self.assertEqual(restored['after']['weather_enabled'],old);call('event_history',{'limit':1})
        finally:
            process.stdin.close();process.wait(timeout=10);self.assertEqual(process.returncode,0,process.stderr.read());process.stdout.close();process.stderr.close()
            atomic_json(target.artifacts_dir/'operations-mcp-stdio.json',{'responses':responses})
    def test_actual_stdio_bridge(self):
        config=os.environ['SC_MCP_LIVE_CONFIG']
        from sc_bridge import Config
        self.assertTrue(Config.load(config).target.get('test_only'))
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'lab-acceptance','version':'1'}}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'status','arguments':{}}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'read_region','arguments':{'minimum':[-150,80,-98],'maximum':[-150,80,-98]}}}]
        result=subprocess.run([sys.executable,'-m','sc_mcp','--config',config],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        responses=[json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([r['id'] for r in responses],[1,2,3,4]);self.assertEqual(responses[0]['result']['serverInfo']['version'],'0.5.0')
        self.assertGreaterEqual(len(responses[1]['result']['tools']),35)
        for response in responses[2:]:self.assertFalse(response['result']['isError'],response)
        status=json.loads(responses[2]['result']['content'][0]['text']);self.assertEqual(status['protocol'],3);self.assertEqual(status['world']['name'],'SC MCP LAB')

    def test_nonbuilding_stdio_tools(self):
        config=os.environ['SC_MCP_LIVE_CONFIG']
        from sc_bridge import Config
        from sc_bridge.client import atomic_json
        target=Config.load(config);self.assertTrue(target.target.get('test_only'))
        calls=[('entity_query',{'minimum':[-180,60,-120],'maximum':[-120,120,-70],'kind':'player','limit':1}),
            ('pickable_query',{'minimum':[-180,60,-120],'maximum':[-120,120,-70],'limit':1}),
            ('command',{'name':'observe','subtype':'entity_query','parameters':{'minimum':[-180,60,-120],'maximum':[-120,120,-70],'kind':'player'}}),
            ('environment_info',{}),('player_state',{}),('inventory_read',{'limit':2}),
            ('condition_query',{'name':'gamemode','mode':'Creative'}),('lighting_query',{'position':[-150,100,-98]}),
            ('command',{'name':'statsrange','subtype':'health','parameters':{'range_minimum':0,'range_maximum':100}})]
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'nonbuilding-lab','version':'1'}}},
            {'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'}]
        messages.extend({'jsonrpc':'2.0','id':i+3,'method':'tools/call','params':{'name':name,'arguments':args}} for i,(name,args) in enumerate(calls))
        process=subprocess.run([sys.executable,'-m','sc_mcp','--config',config],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stderr)
        responses=[json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([r['id'] for r in responses],list(range(1,len(calls)+3)))
        tools={t['name']:t for t in responses[1]['result']['tools']}
        for name in ('entity_query','pickable_query','environment_info','player_state','inventory_read','condition_query','lighting_query'):
            self.assertTrue(tools[name]['annotations']['readOnlyHint'])
        for response in responses[2:]:self.assertFalse(response['result']['isError'],response)
        self.assertTrue(json.loads(responses[-1]['result']['content'][0]['text'])['matches'])
        atomic_json(target.artifacts_dir/'entity-mcp-stdio.json',{'responses':responses,'stderr':process.stderr})
