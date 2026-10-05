"""Two-launch irreversible pending operation test; only an explicitly registered LAB."""
import json,os,time,unittest
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json

class OperationRestartAcceptance(unittest.TestCase):
    def test_phase(self):
        b=Bridge(Config.load(os.environ['SC_SURVIVAL_TEST_CONFIG']));assert b.config.target.get('test_only') and b.config.target['name']=='SC MCP LAB SURVIVAL'
        b.isolate_local();path=b.config.artifacts_dir/'operation-restart-live.json'
        if os.environ['SC_RESTART_PHASE']=='interrupt':
            fixture=b.call('lab_fixture_switch',identity=b.identity());sub=b.event_subscribe(['block_click']);ready=b.player_patch(level=9)
            b.call('lab_pending_enable',identity=b.identity());pending=b.interact_block(fixture['target']);pending=b.operation_submit(pending['operation_id'],pending['risk'])
            deadline=time.monotonic()+10
            while pending['state']!='waiting_native':
                self.assertLess(time.monotonic(),deadline);time.sleep(.03);pending=b.operation_status(pending['operation_id'])
            atomic_json(path,{'boot':b.heartbeat()['boot'],'pending':pending,'ready':ready,'subscription':sub,'client_id':b.client_id,'target':fixture['target'],'value':b.resource_query(fixture['target'])['value']})
            with self.assertRaises(BridgeError) as e:b.call('lab_interrupt_process',identity=b.identity())
            self.assertEqual(e.exception.code,'TIMEOUT')
        else:
            record=json.loads(path.read_text(encoding="utf-8"));self.assertNotEqual(record['boot'],b.heartbeat()['boot'])
            status=b.operation_status(record['pending']['operation_id']);self.assertTrue(status['interrupted']);self.assertEqual(status['state'],'waiting_native')
            first=b.resource_query(record['target'])['value'];time.sleep(.5);self.assertEqual(b.resource_query(record['target'])['value'],first);self.assertEqual(first,record['value'])
            self.assertEqual(b.operation_submit(status['operation_id'],status['risk'])['state'],'waiting_native')
            with self.assertRaises(BridgeError) as e:b.operation_submit(record['ready']['operation_id'],record['ready']['risk'])
            self.assertEqual(e.exception.code,'STALE_OPERATION')
            b.client_id=record['client_id']
            with self.assertRaises(BridgeError) as e:b.event_poll(record['subscription']['subscription_id'])
            self.assertEqual(e.exception.code,'SUBSCRIPTION_EXPIRED')
            history=b.event_history(boot=record['boot']);self.assertTrue(any(e['operation_id']==status['operation_id'] for e in history['events']));self.assertFalse(history['automatic_actions'])
            record.update(status_after_restart=status,no_replay_verified=True,history_after_restart=history,boot_after=b.heartbeat()['boot']);atomic_json(path,record)
if __name__=='__main__':unittest.main()
