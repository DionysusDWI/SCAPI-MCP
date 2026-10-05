"""Two explicit phases, no automatic write replay or world selection."""
import argparse,time,json
from sc_bridge import Bridge,BridgeError,Config
from sc_bridge.client import atomic_json
p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','verify']);p.add_argument('--config',required=True);a=p.parse_args()
b=Bridge(Config.load(a.config));assert b.config.target.get('test_only') and b.config.target['name']=='SC MCP LAB';b.isolate_local();file=b.config.artifacts_dir/'creature-restart-live.json'
def finish(plan):
    r=b.operation_submit(plan['operation_id'],plan['risk']);end=time.monotonic()+10
    while r['state']!='completed':
        assert r['state']!='failed',r;assert time.monotonic()<end;time.sleep(.025);r=b.operation_status(plan['operation_id'])
    return r
def loaded_wolf():
    end=time.monotonic()+30
    while True:
        try:
            b.prepare_region([-160,60,-112],[-128,95,-80],timeout_seconds=3)
            rows=b.entity_query([-160,60,-112],[-128,95,-80],kind='creature',template='Wolf')['records']
            assert len(rows)==1,rows
            return b.creature_inspect(rows[0]['native_id'])
        except BridgeError as error:
            if error.code!='REGION_NOT_LOADED' or time.monotonic()>end:raise
            time.sleep(.05) # Only repeat a read, never resubmit effects.
if a.phase=='prepare':
    fixture=b.call('lab_creature_create',identity=b.identity());target=b.creature_inspect(fixture['native_id']);done=finish(b.creature_patch(target['target_id'],{'walk_speed':0,'health':.8,'attack_power':77,'attack_resilience':9000}))
    before_reload=b.creature_inspect(fixture['native_id']);b.call('lab_creature_save_unload',{'target_id':target['target_id']},b.identity());b.call('lab_load_target');end=time.monotonic()+30
    while True:
        try:b.isolate_local();break
        except BridgeError:assert time.monotonic()<end;time.sleep(.05)
    try:b.creature_patch(target['target_id'],{'walk_speed':2});raise AssertionError('Old handle accepted')
    except BridgeError as error:assert error.code=='STALE_TARGET'
    loaded=loaded_wolf()
    fields=loaded['fields'];assert abs(fields['health']-before_reload['fields']['health'])<.03;assert fields['attack_power']==77;assert fields['walk_speed']!=0;assert fields['attack_resilience']!=9000
    b.call('lab_creature_adopt',{'target_id':loaded['target_id']},b.identity())
    ready=b.creature_patch(loaded['target_id'],{'attack_power':321});b.call('lab_creature_hold',identity=b.identity());held=b.creature_patch(loaded['target_id'],{'attack_power':456});held=b.operation_submit(held['operation_id'],held['risk'])
    end=time.monotonic()+5
    while held['audit_state']=='writing':assert time.monotonic()<end;time.sleep(.03);held=b.operation_status(held['operation_id'])
    assert held['state']=='persisting_intent' and held['audit_state']=='durable',held
    atomic_json(file,{'client_id':b.client_id,'old_boot':b.heartbeat()['boot'],'original':target,'completed':done,'before_reload':before_reload,'after_reload':loaded,'ready':ready,'held':held,'phase':'prepared'})
    try:b.call('lab_interrupt_process',identity=b.identity())
    except BridgeError as error:assert error.code in ('TIMEOUT','HOST_OFFLINE')
    print('Prepared durable interruption. Restart only the registered game, load LAB, then verify.')
else:
    data=json.loads(file.read_text(encoding='utf-8'));b.client_id=data['client_id'];assert b.heartbeat()['boot']!=data['old_boot']
    ready=data['ready'];held=data['held'];record=b.operation_status(held['operation_id']);assert record['interrupted'] and record['state']=='persisting_intent',record
    assert b.operation_submit(held['operation_id'],held['risk'])['state']=='persisting_intent'
    try:b.operation_submit(ready['operation_id'],ready['risk']);raise AssertionError('Old ready replayed')
    except BridgeError as error:assert error.code=='STALE_OPERATION'
    try:b.creature_patch(data['after_reload']['target_id'],{'attack_power':5});raise AssertionError('Restart reused handle')
    except BridgeError as error:assert error.code=='STALE_TARGET'
    actual=loaded_wolf();assert actual['fields']['attack_power']==77,actual
    b.call('lab_creature_adopt',{'target_id':actual['target_id']},b.identity());b.call('lab_remove_observation_fixture',identity=b.identity())
    data.update(phase='verified',new_boot=b.heartbeat()['boot'],interrupted_record=record,actual_after_restart=actual);atomic_json(file,data);print('Save/load and process restart verified; fixture cleaned, no replay.')
