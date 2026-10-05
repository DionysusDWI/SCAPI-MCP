"""A bounded stdlib-only MCP 2025-03-26 implementation over newline stdio."""
import json
import re
from sc_bridge import BridgeError

POSITION = {'type': 'array', 'items': {'type': 'integer'}, 'minItems': 3, 'maxItems': 3}
PLAYER = {'type': 'integer', 'minimum': 0}
PACKED = {'type': 'integer', 'minimum': 0, 'maximum': 2147483647}

def tool(name, description, properties=None, required=None, read_only=True):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties or {},
                            'required': required or [], 'additionalProperties': False},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': not read_only,
                            'idempotentHint': read_only, 'openWorldHint': False}}

TOOLS = [
    tool('entity_query','读取已加载区域的活动实体；短时快照分页，身份不能用于写入',{
        'minimum':POSITION,'maximum':POSITION,'kind':{'type':'string','enum':['all','player','creature','body']},'template':{'type':'string','minLength':1,'maxLength':128},
        'limit':{'type':'integer','minimum':1,'maximum':64},'cursor':{'type':'string','pattern':'^[0-9a-f]{32}:(0|[1-9][0-9]{0,4})$'},'player_index':PLAYER},['minimum','maximum']),
    tool('pickable_query','读取已加载区域的活动掉落物；按完整物品值过滤，快照分页',{
        'minimum':POSITION,'maximum':POSITION,'value':PACKED,'limit':{'type':'integer','minimum':1,'maximum':64},
        'cursor':{'type':'string','pattern':'^[0-9a-f]{32}:(0|[1-9][0-9]{0,4})$'},'player_index':PLAYER},['minimum','maximum']),
    tool('environment_info','读取登记世界的模式、时间和环境开关；不修改环境',{'player_index':PLAYER}),
    tool('player_state','读取指定玩家的属性、位置和速度，返回原生值及单位',{'player_index':PLAYER}),
    tool('lighting_query','读取已完成计算的现有区块光照；未加载或计算中明确报错',{'position':POSITION,'player_index':PLAYER},['position']),
    tool('inventory_read','分页读取指定玩家库存；创造模式供给与实体库存数量分别标记',{'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':64},'player_index':PLAYER}),
    tool('condition_query','只读登记条件：返回观察值、单位及包含端点的判定；错误不当作false',{
        'name':{'type':'string','enum':['levelrange','heightrange','timerange','modcount','gamemode','statsrange','blocklight']},'position':POSITION,
        'subtype':{'type':'string','enum':['default','health','food','stamina','sleep','wetness','speed','attack','defense','temperature']},
        'minimum':{'type':'number'},'maximum':{'type':'number'},
        'mode':{'type':'string','enum':['Creative','Survival','Challenging','Harmless','Cruel','Adventure']},'player_index':PLAYER},['name']),
    tool('status', '探针版本、能力、联机状态与目标世界状态'),
    tool('world_info', '已加载世界的路径、名称、会话与玩家'),
    tool('players', '列出玩家索引、名称与位置'),
    tool('read_region', '读取已加载区域；返回全部格子，包含空气，移除瞬时光照位',
         {'minimum': POSITION, 'maximum': POSITION, 'player_index': PLAYER}, ['minimum', 'maximum']),
    tool('modify_cells', '备份已核验的单人目标中比较原值后修改；最多 64 格，拒绝未知资源',
         {'changes': {'type': 'array', 'minItems': 1, 'maxItems': 64,
             'items': {'type': 'object', 'properties': {'position': POSITION, 'expected': PACKED, 'value': PACKED},
                       'required': ['position', 'expected', 'value'], 'additionalProperties': False}},
          'player_index': PLAYER}, ['changes'], False),
    tool('restore_operation', '恢复已成功应用的操作，当前值冲突时拒绝覆盖',
         {'operation_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'}, 'player_index': PLAYER},
         ['operation_id'], False),
]

IDENTIFIER = {'type': 'string', 'pattern': '^[0-9a-f]{32}$'}
from sc_bridge.operation_contract import SCHEMAS as BRIDGE_SCHEMAS,PLAYER_PATCH,EVENT_KINDS
from copy import deepcopy
SCHEMAS=deepcopy(BRIDGE_SCHEMAS)
TOOLS += [
    tool('creature_inspect','重新核验活动非玩家生物，返回绑定客户端与会话的短期目标句柄',{'native_id':{'type':'integer','minimum':0,'maximum':2147483647},'player_index':PLAYER},['native_id']),
    tool('operation_preflight','预检非建筑操作，报告副作用、风险及恢复等级；不执行效果',{'action':{'type':'string','enum':list(SCHEMAS)},'parameters':{'type':'object','properties':{k:v for s in SCHEMAS.values() for k,v in s['properties'].items()},'additionalProperties':False},'player_index':PLAYER},['action','parameters']),
    tool('player_patch','预检原生单位玩家属性修改；不承诺倒转自然漂移或连锁结果',PLAYER_PATCH['properties']|{'player_index':PLAYER}),
    tool('operation_submit','显式提交已预检操作，风险必须与预检一致；禁止自动重试',{'operation_id':IDENTIFIER,'accept_risk':{'type':'string','enum':['state_change','side_effects','dangerous']},'player_index':PLAYER},['operation_id','accept_risk'],False),
    tool('operation_status','查询当前或持久操作记录；中断记录不自动重放',{'operation_id':IDENTIFIER,'player_index':PLAYER},['operation_id']),
    tool('operation_restore','仅恢复仍匹配操作后值的登记直接字段；不可回退操作拒绝',{'operation_id':IDENTIFIER,'accept_risk':{'type':'string','enum':['state_change','side_effects','dangerous']},'player_index':PLAYER},['operation_id','accept_risk'],False),
    tool('event_subscribe','创建独立会话事件游标，不消费其他客户端事件',{'kinds':{'type':'array','minItems':1,'maxItems':len(EVENT_KINDS),'items':{'type':'string','enum':EVENT_KINDS}},'player_index':PLAYER},['kinds']),
    tool('event_poll','读取至多64条事件，明确报告缺口与审计错误',{'subscription_id':IDENTIFIER,'limit':{'type':'integer','minimum':1,'maximum':64},'player_index':PLAYER},['subscription_id']),
    tool('event_unsubscribe','解除自己的事件订阅',{'subscription_id':IDENTIFIER,'player_index':PLAYER},['subscription_id']),
    tool('event_history','查持久事件审计；历史不会自动触发行动',{'after':{'type':'integer','minimum':0},'boot':IDENTIFIER,'limit':{'type':'integer','minimum':1,'maximum':64},'player_index':PLAYER}),
]
TOOLS += [tool(name,'预检登记非建筑操作；提交前确认风险，不承诺倒转连锁结果',schema['properties']|{'player_index':PLAYER},schema['required']) for name,schema in SCHEMAS.items() if name!='player_patch']
next(t for t in TOOLS if t['name']=='operation_preflight')['inputSchema']['properties']['parameters']['properties']['mode']={'type':'string','enum':['set','add','remove','clear','save','enable','disable']}
next(t for t in TOOLS if t['name']=='player_override')['inputSchema']['properties']['mode']['enum']=['save','enable','disable','query']
TOOLS += [tool('operation_cancel','在气候批次边界取消，保留已执行部分和快照证据',{'operation_id':IDENTIFIER,'player_index':PLAYER},['operation_id'],False)]
from sc_bridge.operation_contract import COLUMN
TOOLS += [tool('climate_query','读取至多64个已加载X/Z列的原生温湿度，不生成地形',{'positions':{'type':'array','minItems':1,'maxItems':64,'items':COLUMN},'player_index':PLAYER},['positions'])]
for t in TOOLS:
    if t['name'] in {'creature_inspect'}|set(SCHEMAS)|{'operation_preflight','event_subscribe','event_poll','event_history'}:t['annotations']['idempotentHint']=False
for key in ('minimum','maximum'):
    next(t for t in TOOLS if t['name']=='operation_preflight')['inputSchema']['properties']['parameters']['properties'][key]={'type':'array','minItems':2,'maxItems':3,'items':{'type':'integer'}}
RESOURCE = {'type':'object','properties':{
    'kind':{'type':'string','enum':['container','sign','memory','truth_table','furniture']},
    'slots':{'type':'array','maxItems':64,'items':{'type':'object','properties':{'value':PACKED,'count':{'type':'integer','minimum':0,'maximum':9999}},'required':['value','count'],'additionalProperties':False}},
    'lines':{'type':'array','minItems':4,'maxItems':4,'items':{'type':'string'}},
    'colors':{'type':'array','minItems':4,'maxItems':4,'items':{'type':'integer','minimum':0,'maximum':4294967295}},
    'url':{'type':'string'},'data':{'type':'string'},'fire_time':{'type':'number','minimum':0},'heat':{'type':'number','minimum':0},'designs':{'type':'array','minItems':1,'maxItems':256,'items':{'type':'string'}}},
    'required':['kind'],'additionalProperties':False}
RESOURCE['properties']['slots']['items']['properties']['resource']={'type':'object','properties':{'kind':{'type':'string','enum':['furniture']},'designs':RESOURCE['properties']['designs']},'required':['kind','designs'],'additionalProperties':False}
TOOLS += [
    tool('region_statistics','异步统计区域，任务完成后通过模板清单读取统计及文件引用',{'minimum':POSITION,'maximum':POSITION,'player_index':PLAYER},['minimum','maximum']),
    tool('read_region_page','百万格区域分页读取；每页最多 4096 格',{'minimum':POSITION,'maximum':POSITION,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':4096},'player_index':PLAYER},['minimum','maximum']),
    tool('command_config','预检命令方块配置：登记的 blockexist/default 条件；不接受命令文本',{'position':POSITION,'query_position':POSITION,'value':PACKED,'player_index':PLAYER},['position','query_position','value'],False),
    tool('condition','按世界绝对坐标查询完整方块值是否匹配',{'position':POSITION,'value':PACKED,'player_index':PLAYER},['position','value']),
    tool('resource_write','预检容器库存、告示牌、家具设计和电路配置写入',{'position':POSITION,'value':PACKED,'resource':RESOURCE,'player_index':PLAYER},['position','value','resource'],False),
    tool('capabilities', '登记命令、后端、恢复等级及验收状态'),
    tool('materials', '方块类型和来源程序集目录'),
    tool('resource_query', '读取容器、告示牌、家具和电路的持久配置',
         {'position': POSITION, 'player_index': PLAYER}, ['position']),
    tool('preflight', '异步预检建筑操作，返回 plan_id；状态 ready 后才可提交',
         {'action': {'type': 'string', 'enum': ['fill','clear','replace','copy','move','geometry','resource']},
          'minimum': POSITION, 'maximum': POSITION, 'value': PACKED, 'match': PACKED,
          'destination': POSITION, 'rotation': {'type':'integer','enum':[0,90,180,270]},
          'mirror': {'type':'string','enum':['none','x','z']},
          'shape': {'type':'string','enum':['line','cuboid','sphere','cylinder','cone']},
          'hollow': {'type':'boolean'}, 'resource':RESOURCE, 'player_index': PLAYER}, ['action','minimum','maximum'], False),
    tool('submit', '提交已准备且未过期的预检计划', {'plan_id': IDENTIFIER,'player_index':PLAYER}, ['plan_id'], False),
    tool('job_status', '查询任务进度、暂停原因和批次耗时', {'job_id': IDENTIFIER,'player_index':PLAYER}, ['job_id']),
    tool('cancel_job', '批次边界取消，保留恢复记录', {'job_id': IDENTIFIER,'player_index':PLAYER}, ['job_id'], False),
    tool('restore_job', '比较操作后数据并分批恢复；有冲突时拒绝', {'job_id': IDENTIFIER,'player_index':PLAYER}, ['job_id'], False),
    tool('resume_job','显式重新预检中断任务；检查完整记录与当前数据，ready 后仍需 submit',{'job_id':IDENTIFIER,'player_index':PLAYER},['job_id'],False),
    tool('interrupted_jobs', '查询旧启动任务记录，绝不自动重放'),
]
REGION = {'minimum': POSITION, 'maximum': POSITION, 'player_index': PLAYER}
COPY = {**REGION, 'destination': POSITION, 'rotation': {'type':'integer','enum':[0,90,180,270]}, 'mirror': {'type':'string','enum':['none','x','z']}}
TOOLS += [
    tool('template_export','异步导出包含资源内容和校验值的 .scblueprint',REGION,['minimum','maximum']),
    tool('template_inspect','检查模板格式、内容校验及依赖',{'template_id':IDENTIFIER},['template_id']),
    tool('template_import','异步预检模板导入，家具按内容映射编号',{'template_id':IDENTIFIER,'destination':POSITION,'player_index':PLAYER},['template_id','destination'],False),
    tool('measure','计算包含端点的区域尺寸、体积和对角距离',REGION,['minimum','maximum']),
    tool('prepare_region','有界等待已存在区块完成加载；不主动生成地形', {**REGION,'timeout_seconds':{'type':'number','minimum':0,'maximum':30}},['minimum','maximum']),
    tool('teleport','移动登记世界中选定玩家',{'position':POSITION,'player_index':PLAYER},['position'],False),
    tool('camera','设置固定相机位置和观察目标',{'position':POSITION,'target':POSITION,'player_index':PLAYER},['position','target'],False),
    tool('heading','设置玩家身体朝向和俯仰，单位为度',{'yaw':{'type':'number','minimum':-360,'maximum':360},'pitch':{'type':'number','minimum':-82,'maximum':82},'player_index':PLAYER},['yaw'],False),
    tool('screenshot','游戏侧截图，返回产物文件引用',{'player_index':PLAYER}),
    tool('fill', '预检区域填充；返回计划后需显式提交', {**REGION,'value':PACKED}, ['minimum','maximum','value'],False),
    tool('clear', '预检区域清除', REGION, ['minimum','maximum'],False),
    tool('replace', '预检按完整方块值替换', {**REGION,'match':PACKED,'value':PACKED}, ['minimum','maximum','match','value'],False),
    tool('copy', '预检重叠安全复制及 Y 旋转、X/Z 镜像', COPY, ['minimum','maximum','destination'],False),
    tool('move', '预检搬移；来源快照先于目标覆盖', COPY, ['minimum','maximum','destination'],False),
    tool('geometry', '预检实心/空心几何', {**REGION,'value':PACKED,'shape':{'type':'string','enum':['line','cuboid','sphere','cylinder','cone']},'hollow':{'type':'boolean'}}, ['minimum','maximum','shape','value'],False),
    tool('command', '仅登记命令名、子类型和结构化参数；返回预检计划',
         {'name': {'type':'string'},'subtype':{'type':'string'},'parameters':{'type':'object','properties':{**{k:v for k,v in COPY.items() if k!='player_index'},'kind':{'type':'string','enum':['all','player','creature','body']},'template':{'type':'string','minLength':1,'maxLength':128},'cursor':{'type':'string','pattern':'^[0-9a-f]{32}:(0|[1-9][0-9]{0,4})$'},'range_minimum':{'type':'number'},'range_maximum':{'type':'number'},'mode':{'type':'string','enum':['Creative','Survival','Challenging','Harmless','Cruel','Adventure']},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':64},'value':PACKED,'match':PACKED,'hollow':{'type':'boolean'},'position':POSITION,'target':POSITION,'query_position':POSITION,'resource':RESOURCE,'yaw':{'type':'number','minimum':-360,'maximum':360},'pitch':{'type':'number','minimum':-82,'maximum':82}},'additionalProperties':False},'player_index':PLAYER}, ['name','subtype','parameters'],False),
]

command_parameters=next(t for t in TOOLS if t['name']=='command')['inputSchema']['properties']['parameters']['properties']
for schema in SCHEMAS.values():
    for key,value in schema['properties'].items():
        if key in command_parameters and command_parameters[key]!=value:
            command_parameters[key]={'anyOf':[command_parameters[key],deepcopy(value)]}
        else:command_parameters[key]=deepcopy(value)

def validate(value, schema, path='arguments'):
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:validate(value,choice,path);return
            except ValueError:pass
        raise ValueError(f'{path}: no registered parameter shape matches')
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'integer': type(value) is int, 'number':type(value) in (int,float) and -2**63<=value<=2**63 and __import__('math').isfinite(value), 'string': isinstance(value, str), 'boolean': type(value) is bool}
    if kind and not valid.get(kind, False):
        raise ValueError(f'{path}: expected {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: value is not registered')
    if kind == 'object':
        properties = schema.get('properties', {})
        if not set(schema.get('required', [])).issubset(value):
            raise ValueError(f'{path}: missing required field')
        if schema.get('additionalProperties') is False and set(value) - set(properties):
            raise ValueError(f'{path}: unknown field')
        for key, item in value.items():
            if key in properties: validate(item, properties[key], path + '.' + key)
    if kind == 'array':
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 100000):
            raise ValueError(f'{path}: invalid item count')
        for index, item in enumerate(value): validate(item, schema['items'], f'{path}[{index}]')
    if kind in ('integer','number') and not schema.get('minimum', -2**63) <= value <= schema.get('maximum', 2**63):
        raise ValueError(f'{path}: integer out of range')
    if kind == 'string' and 'pattern' in schema and not re.fullmatch(schema['pattern'], value):
        raise ValueError(f'{path}: invalid format')
    if kind == 'string' and not schema.get('minLength',0)<=len(value)<=schema.get('maxLength',1000000):
        raise ValueError(f'{path}: string length outside bounds')

def rpc_error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}

class Server:
    def __init__(self, bridge):
        self.bridge = bridge
        self.initializing = False
        self.ready = False

    def handle(self, message):
        if isinstance(message, list):
            if not message: return rpc_error(None, -32600, 'Empty batch')
            responses = [self.handle(item) for item in message]
            return [r for r in responses if r is not None] or None
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return rpc_error(None, -32600, 'Invalid request')
        request_id = message.get('id')
        if 'id' in message and (type(request_id) not in (str, int)):
            return rpc_error(None, -32600, 'Invalid request id')
        method, params = message['method'], message.get('params', {})
        if not isinstance(params, dict):
            return rpc_error(request_id, -32602, 'params must be an object') if 'id' in message else None
        if 'id' not in message:
            if method == 'notifications/initialized' and self.initializing:
                self.ready = True
            return None
        if method == 'initialize':
            if self.initializing: return rpc_error(request_id, -32600, 'Already initialized')
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return rpc_error(request_id, -32602, 'Invalid initialize parameters')
            self.initializing = True
            result = {'protocolVersion': '2025-03-26', 'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'sc-mcp', 'version': '0.5.0'}}
        elif method == 'ping':
            result = {}
        elif not self.ready:
            return rpc_error(request_id, -32000, 'Initialization has not completed')
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            name, arguments = params.get('name'), params.get('arguments', {})
            definition = next((t for t in TOOLS if t['name'] == name), None)
            if definition is None: return rpc_error(request_id, -32602, 'Unknown tool')
            try:
                validate(arguments, definition['inputSchema'])
            except ValueError as error:
                return rpc_error(request_id, -32602, str(error))
            try:
                data = getattr(self.bridge, name)(**arguments)
                result = {'content': [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}], 'isError': False}
            except BridgeError as error:
                result = {'content': [{'type': 'text', 'text': json.dumps({'code': error.code, 'message': str(error), 'detail': error.detail}, ensure_ascii=False)}], 'isError': True}
            except Exception as error:
                result = {'content': [{'type': 'text', 'text': json.dumps({'code': 'INTERNAL_ERROR', 'message': str(error)}, ensure_ascii=False)}], 'isError': True}
        else:
            return rpc_error(request_id, -32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}

    def serve(self, input_stream, output_stream):
        for line in input_stream:
            try:
                if len(line) > 1024 * 1024: raise ValueError('Message too large')
                response = self.handle(json.loads(line))
            except ValueError:
                response = rpc_error(None, -32700, 'Parse error')
            if response is not None:
                output_stream.write(json.dumps(response, ensure_ascii=False) + '\n')
                output_stream.flush()
