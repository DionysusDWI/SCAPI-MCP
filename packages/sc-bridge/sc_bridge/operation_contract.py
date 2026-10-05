"""Closed non-building schemas shared by bridge validation and MCP discovery."""
IDENTIFIER={'type':'string','pattern':'^[0-9a-f]{32}$'}
NUMBER={'type':'number'}
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
PLAYER_PATCH=obj({**{k:{'type':'number','minimum':0,'maximum':1} for k in ('food','stamina','sleep','wetness')},'level':{'type':'number','minimum':1,'maximum':100},'health':{'type':'number','minimum':.001,'maximum':1},'temperature':{'type':'number','minimum':0,'maximum':24}})
EVENT_KINDS=['block_click','longpress_start','longpress_end','item_use','eat','wear','capture']
def validate(value,schema):
    import math,re
    kind=schema['type']
    matches={'object':type(value) is dict,'array':type(value) is list,'string':type(value) is str,'integer':type(value) is int,'number':type(value) in (int,float),'boolean':type(value) is bool}
    if not matches[kind]:raise ValueError('Incorrect field type')
    if kind=='object':
        if set(value)-set(schema['properties']) or not set(schema['required'])<=set(value):raise ValueError('Unknown or missing field')
        for k,v in value.items():validate(v,schema['properties'][k])
    if kind=='array':
        if not schema.get('minItems',0)<=len(value)<=schema.get('maxItems',64):raise ValueError('Array outside bounds')
        for v in value:validate(v,schema['items'])
    if kind in ('number','integer'):
        try:finite=math.isfinite(value)
        except OverflowError:finite=False
        if not finite or not schema.get('minimum',-2**63)<=value<=schema.get('maximum',2**63):raise ValueError('Number outside bounds')
    if kind=='string' and 'pattern' in schema and not re.fullmatch(schema['pattern'],value):raise ValueError('Invalid identifier')
    if 'enum' in schema and value not in schema['enum']:raise ValueError('Unregistered choice')
COLOR={'type':'array','minItems':4,'maxItems':4,'items':{'type':'integer','minimum':0,'maximum':255}}
ENVIRONMENT_PATCH=obj({**{k:{'type':'boolean'} for k in ('weather_enabled','adventure_survival','rain','fog','seasons_changing')},
    'environment_mode':{'type':'string','enum':['Living','Static']},'time_of_day_mode':{'type':'string','enum':['Changing','Day','Night','Sunrise','Sunset']},
    'game_mode':{'type':'string','enum':['Creative','Survival','Challenging','Harmless','Cruel','Adventure']},
    'time_of_day':{'type':'number','minimum':0,'maximum':.999999999},'season':{'type':'number','minimum':0,'maximum':.999999999},
    'simulation_factor':{'type':'number','minimum':.1,'maximum':10},'day_duration_seconds':{'type':'number','minimum':60,'maximum':86400},
    'sky_color':COLOR,'precipitation_color':COLOR})
OVERRIDE=obj({'mode':{'type':'string','enum':['save','enable','disable']},'fields':obj({'walk_speed':{'type':'number','minimum':0,'maximum':64},'attack_power':{'type':'number','minimum':0,'maximum':10000},'attack_resilience':{'type':'number','minimum':.001,'maximum':10000}})},['mode'])
POSITION={'type':'array','minItems':3,'maxItems':3,'items':{'type':'integer','minimum':-1000000,'maximum':1000000}}
ENDPOINT=obj({'kind':{'type':'string','enum':['player','container']},'position':POSITION},['kind'])
VALUE={'type':'integer','minimum':0,'maximum':2147483647}
COUNT={'type':'integer','minimum':0,'maximum':9999}
EDIT=obj({'target':ENDPOINT,'mode':{'type':'string','enum':['set','add','remove','clear']},'slots':{'type':'array','maxItems':64,'items':obj({'index':{'type':'integer','minimum':0,'maximum':63},'value':VALUE,'count':COUNT},['index','value','count'])},'value':VALUE,'count':COUNT,'active_slot':{'type':'integer','minimum':0,'maximum':63}},['target','mode'])
TRANSFER=obj({'source':ENDPOINT,'destination':ENDPOINT,'value':VALUE,'count':COUNT},['source','destination','value','count'])
SCHEMAS={'player_patch':PLAYER_PATCH,'environment_patch':ENVIRONMENT_PATCH,'player_override':OVERRIDE,'inventory_edit':EDIT,'inventory_transfer':TRANSFER,'interact_block':obj({'position':POSITION},['position'])}
COLUMN={'type':'array','minItems':2,'maxItems':2,'items':{'type':'integer','minimum':-1000000,'maximum':1000000}}
SCHEMAS['climate_patch']=obj({'minimum':COLUMN,'maximum':COLUMN,'temperature':{'type':'integer','minimum':0,'maximum':15},'humidity':{'type':'integer','minimum':0,'maximum':15}},['minimum','maximum'])

CREATURE_FIELDS=obj({'health':{'type':'number','minimum':.001,'maximum':1},'walk_speed':{'type':'number','minimum':0,'maximum':64},'attack_power':{'type':'number','minimum':0,'maximum':10000},'attack_resilience':{'type':'number','minimum':.001,'maximum':10000}})
SCHEMAS['creature_patch']=obj({'target_id':IDENTIFIER,'fields':CREATURE_FIELDS},['target_id','fields'])
