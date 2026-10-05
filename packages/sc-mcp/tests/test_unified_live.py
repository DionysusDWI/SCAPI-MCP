import os,json,time,subprocess,sys,unittest
from sc_bridge import Bridge,Config
from sc_bridge.client import atomic_json

@unittest.skipUnless(os.getenv('SC_MCP_LIVE_CONFIG'),'Explicit LAB required')
class UnifiedLiveTests(unittest.TestCase):
    def test_all_operation_groups_via_unified_stdio(self):
        config=Config.load(os.environ['SC_MCP_LIVE_CONFIG']);assert config.target.get('test_only') and config.target['name']=='SC MCP LAB';b=Bridge(config);b.isolate_local();fixture=b.call('lab_creature_create',identity=b.identity());rows=[]
        process=subprocess.Popen([sys.executable,'-m','sc_mcp.cli','--config',str(config.path),'serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',bufsize=1)
        def rpc(method,params):
            ident=len(rows)+1;process.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n');process.stdin.flush();r=json.loads(process.stdout.readline());rows.append(r);self.assertEqual(r['id'],ident);return r['result']
        def call(name,args={}):
            r=rpc('tools/call',{'name':name,'arguments':args});self.assertFalse(r['isError'],r);return json.loads(r['content'][0]['text'])
        def wait(r,tool,key,desired):
            end=time.monotonic()+30
            while r['state'] not in desired:
                self.assertNotIn(r['state'],('failed','paused','cancelled'));self.assertLess(time.monotonic(),end);time.sleep(.025);r=call(tool,{key:r[key]})
            return r
        def operation(plan):return wait(call('operation_submit',{'operation_id':plan['operation_id'],'accept_risk':plan['risk']}),'operation_status','operation_id',['completed'])
        def restore(done):return wait(call('operation_restore',{'operation_id':done['operation_id'],'accept_risk':done['risk']}),'operation_status','operation_id',['completed'])
        try:
            rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'unified-live','version':'0.5.0'}});process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n');process.stdin.flush()
            call('status');call('capabilities')
            point=[-150,80,-98];plan=wait(call('fill',{'minimum':point,'maximum':point,'value':3}),'job_status','job_id',['ready']);job=wait(call('submit',{'plan_id':plan['plan_id']}),'job_status','job_id',['completed']);self.assertEqual(call('read_region',{'minimum':point,'maximum':point})['cells'][0]['value'],3);wait(call('restore_job',{'job_id':job['job_id']}),'job_status','job_id',['restored'])
            environment=call('environment_info');restore(operation(call('environment_patch',{'weather_enabled':not environment['weather_enabled']})))
            player=call('player_state');restore(operation(call('player_patch',{'level':player['level']+1})))
            restore(operation(call('inventory_edit',{'target':{'kind':'player'},'mode':'set','slots':[{'index':0,'value':3,'count':1}]})))
            subscription=call('event_subscribe',{'kinds':['capture']});call('screenshot');end=time.monotonic()+20
            while True:
                page=call('event_poll',{'subscription_id':subscription['subscription_id']})
                if page['events']:break
                self.assertLess(time.monotonic(),end);time.sleep(.1)
            self.assertEqual(page['events'][0]['kind'],'capture');call('event_unsubscribe',{'subscription_id':subscription['subscription_id']})
            target=call('creature_inspect',{'native_id':fixture['native_id']});done=operation(call('creature_patch',{'target_id':target['target_id'],'fields':{'walk_speed':2,'attack_power':7,'attack_resilience':40}}));self.assertEqual(done['after']['fields']['attack_power'],7);restore(done)
        finally:
            process.stdin.close();process.wait(timeout=10);self.assertEqual(process.returncode,0,process.stderr.read());process.stdout.close();process.stderr.close();b.call('lab_remove_observation_fixture',identity=b.identity());atomic_json(config.artifacts_dir/'unified-mcp-stdio-live.json',{'responses':rows})
