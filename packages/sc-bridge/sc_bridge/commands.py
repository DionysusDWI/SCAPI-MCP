"""Closed registry: no DSL, scripts, paths or recursive commands enter the host."""
REGISTRY = {
    ('place','default'): ('fill', 'commandblock/place/default'),
    ('fill','region'): ('fill','native_scheduler+commandblock/place/default'),
    ('clear','region'): ('clear','native_scheduler+commandblock/place/default'),
    ('replace','region'): ('replace','native_scheduler+commandblock/place/default'),
    ('copy','region'): ('copy','native_snapshot+commandblock_transforms'),
    ('move','region'): ('move','native_snapshot+commandblock_transforms'),
    **{('geometry',shape): ('geometry','native_scheduler') for shape in ('line','cuboid','sphere','cylinder','cone')},
    **{('resource',kind):('resource_write','native_resources') for kind in ('container','sign','memory','truth_table','furniture')},
    ('observe','teleport'):('teleport','native_player'),
    ('observe','camera'):('camera','native_camera'),
    ('observe','heading'):('heading','native_player'),
    ('observe','measure'):('measure','native_region'),
    ('observe','screenshot'):('screenshot','native_graphics'),
    ('condition','blockexist'):('condition','native_region'),
    ('command_config','blockexist'):('command_config','commandblock/condition'),
}
NON_BUILDING_CONDITIONS = {
    *((name,'default') for name in ('levelrange','heightrange','timerange','modcount','gamemode','blocklight')),
    *(('statsrange',kind) for kind in ('health','food','stamina','sleep','wetness','speed','attack','defense','temperature')),
}
REGISTRY.update({pair:('condition_query','native_selected_player_and_world') for pair in NON_BUILDING_CONDITIONS})
REGISTRY.update({('observe',name):(name,'native_readonly') for name in ('environment_info','player_state','inventory_read','lighting_query')})
REGISTRY.update({('observe',name):(name,'native_snapshot_paging') for name in ('entity_query','pickable_query')})
OPERATION_PATHS={('environment','patch'):'environment_patch',('player','patch'):'player_patch',('player','override'):'player_override',('inventory','edit'):'inventory_edit',('inventory','transfer'):'inventory_transfer',('interact','block'):'interact_block'}
OPERATION_PATHS[('climate','patch')]='climate_patch'
OPERATION_PATHS[('creature','patch')]='creature_patch'
REGISTRY.update({pair:(action,'native_audited_operation') for pair,action in OPERATION_PATHS.items()})

def descriptor():
    result=[]
    for (name,subtype),(action,backend) in sorted(REGISTRY.items()):
        if (name,subtype) in OPERATION_PATHS:
            from .operation_contract import SCHEMAS
            result.append({'name':name,'type':subtype,'action':action,'backend':backend,'parameters':list(SCHEMAS[action]['properties']),
                'availability':'lab_verified','impact':'selected registered resources; reported by operation_preflight','recovery':'declared_per_preflight: direct_fields|best_effort|none',
                'completion':'preflight -> explicit acknowledged submit -> durable result and readback','evidence':['tests/test_creatures.py','tests/creature_restart_acceptance.py'] if action=='creature_patch' else ['tests/test_operations.py','tests/test_survival_operations.py','tests/test_operations_extended.py','tests/test_maintenance.py','tests/test_interactions.py'],'constraints':['local singleplayer','no automatic replay','downstream effects not reversed']})
            continue
        objects=action in ('entity_query','pickable_query')
        extension=objects or action in ('condition_query','environment_info','player_state','inventory_read','lighting_query')
        building=name in ('place','fill','clear','replace','copy','move','geometry','resource','command_config')
        parameters={
            'place':['position','value'], 'fill':['minimum','maximum','value'],
            'clear':['minimum','maximum'], 'replace':['minimum','maximum','match','value'],
            'copy':['minimum','maximum','destination','rotation=0|90|180|270','mirror=none|x|z'],
            'move':['minimum','maximum','destination','rotation=0|90|180|270','mirror=none|x|z'],
            'geometry':['minimum','maximum','value','hollow=false'],
            'resource':['position','value','resource(kind='+subtype+')'],
            'command_config':['position','query_position','value'],
            'condition':['position','value'],
        }.get(name,{'teleport':['position'],'camera':['position','target'],'heading':['yaw','pitch=0'],
                    'measure':['minimum','maximum'],'screenshot':[]}.get(subtype,[]))
        if action=='condition_query':parameters=['mode'] if name=='gamemode' else ['range_minimum','range_maximum']
        if action=='inventory_read':parameters=['offset=0','limit=64']
        if action=='lighting_query':parameters=['position']
        if name=='blocklight':parameters+=['position']
        if objects:parameters=['minimum','maximum','limit=64','cursor']+(['kind','template'] if action=='entity_query' else ['value'])
        readonly=objects or name=='condition' or action=='condition_query' or (name=='observe' and subtype in ('measure','screenshot','environment_info','player_state','inventory_read','lighting_query'))
        result.append({'name':name,'type':subtype,'action':action,'backend':backend,'parameters':parameters,
            'impact':'inclusive affected cells (union for move), <=1000000' if building else ('none; artifact for screenshot' if readonly else 'selected player or camera'),
            'recovery':'local_compare_and_set' if building else ('not_needed' if readonly else 'set_position_or_heading_or_camera_again'),
            'completion':'preflight ready -> explicit submit -> job completed with cell/resource readback' if building else ('synchronous bounded observation' if extension else 'synchronous result; screenshot file exists'),
            'availability':'lab_verified',
            'evidence':['tests/test_entities.py'] if objects else (['tests/test_nonbuilding.py'] if extension else (['tests/test_live.py','tests/test_faults.py','tests/lifecycle_acceptance.py'] if building else ['tests/test_live.py'])),
            'validation_scope':'SC MCP LAB fixtures; registered block families only; see docs/coverage.md',
            'constraints':['singleplayer writes only','unknown mods/resources rejected','flow/collapse/explosion rejected for terrain writes','unregistered orientation transforms rejected','no implicit retry']})
    for action in ('operation_preflight','operation_submit','operation_status','operation_restore','operation_cancel','event_subscribe','event_poll','event_unsubscribe','event_history','climate_query','player_override_query','creature_inspect'):
        result.append({'name':'api','type':action,'action':action,'backend':'native_audited_operation' if action.startswith('operation_') else 'native_observation',
            'availability':'lab_verified','completion':'documented API result with explicit audit errors','recovery':'declared per operation; histories never trigger actions',
            'evidence':['tests/test_operations.py','tests/test_survival_operations.py','tests/test_interactions.py'],'constraints':['local singleplayer','world token/player/session bound','no replay']})
    return result
