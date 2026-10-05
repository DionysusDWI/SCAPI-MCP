from pathlib import Path
import hashlib
import json
import os
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET

class BridgeError(RuntimeError):
    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code, self.detail = code, detail

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)

def coordinate(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(v) is not int for v in value):
        raise BridgeError('INVALID_ARGUMENT', 'Coordinates must contain three integers')
    if any(abs(v) > 1000000 for v in (value[0], value[2])) or not 0 <= value[1] < 256:
        raise BridgeError('INVALID_ARGUMENT', 'Coordinates are outside v1 limits')
    return list(value)

class Bridge:
    def __init__(self, config):
        self.config = config
        self.client_id = uuid.uuid4().hex

    def heartbeat(self):
        try:
            deadline=time.monotonic()+.25
            while True:
                try:
                    data = json.loads((self.config.runtime_dir / 'heartbeat.json').read_text(encoding='utf-8-sig'))
                    break
                except PermissionError:
                    if time.monotonic()>=deadline: raise
                    time.sleep(.01)
        except (OSError, ValueError) as error:
            raise BridgeError('HOST_OFFLINE', 'No valid host heartbeat') from error
        if data.get('protocol') != 3 or data.get('version') != '0.5.0':
            raise BridgeError('INCOMPATIBLE_VERSION', 'Host/client protocol or package mismatch')
        age = time.time() * 1000 - data.get('time', 0)
        if age > 10000 or age < -5000:
            raise BridgeError('HOST_OFFLINE', 'Host heartbeat is stale')
        return data

    def call(self, op, args=None, identity=None):
        host = self.heartbeat()
        request_id = uuid.uuid4().hex
        request = {'id': request_id, 'protocol': 3, 'boot': host['boot'], 'op': op,
                   'client_id': self.client_id, 'expires': int((time.time() + self.config.timeout) * 1000),
                   'args': args or {}, 'identity': identity}
        atomic_json(self.config.runtime_dir / 'inbox' / (request_id + '.json'), request)
        response_path = self.config.runtime_dir / 'outbox' / (request_id + '.json')
        deadline = time.monotonic() + self.config.timeout
        while time.monotonic() < deadline:
            if response_path.exists():
                try:
                    result = json.loads(response_path.read_text(encoding='utf-8-sig'))
                except PermissionError:
                    # Windows indexing/rename sharing races: reread this response,
                    # never resubmit the request or replay its mutation.
                    time.sleep(.025)
                    continue
                if result.get('id') != request_id or result.get('boot') != host['boot']:
                    raise BridgeError('IDENTITY_MISMATCH', 'Response does not match request')
                if not result.get('ok'):
                    error = result.get('error', {})
                    raise BridgeError(error.get('code', 'HOST_ERROR'), error.get('message', 'Host error'), error)
                return result['data']
            time.sleep(.025)
        # Never retry a mutating request: execution may have succeeded before reply loss.
        raise BridgeError('TIMEOUT', 'Response timeout; inspect operation journal before any retry', {'id': request_id})

    def status(self):
        return self.call('status')

    def world_info(self):
        return self.call('world_info')

    def players(self):
        return self.call('players')

    def environment_info(self, player_index=0):
        return self.call('environment_info', {}, self.identity(player_index))

    def operation_preflight(self, action, parameters, player_index=0):
        from .operation_contract import SCHEMAS,validate
        if action not in SCHEMAS:raise BridgeError('UNREGISTERED_COMMAND','Operation not registered')
        try:
            validate(parameters,SCHEMAS[action])
            if not parameters:raise ValueError('Nonempty parameters required')
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        return self.call('operation_preflight',{'action':action,'parameters':parameters},self.identity(player_index))

    def creature_inspect(self, native_id, player_index=0):
        from .operation_contract import validate
        try:validate(native_id,{'type':'integer','minimum':0,'maximum':2147483647})
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        return self.call('creature_inspect',{'native_id':native_id},self.identity(player_index))

    def creature_patch(self, target_id, fields, player_index=0):
        return self.operation_preflight('creature_patch',{'target_id':target_id,'fields':fields},player_index)

    def player_patch(self, player_index=0, **fields):
        return self.operation_preflight('player_patch',fields,player_index)

    def environment_patch(self, player_index=0, **fields):
        return self.operation_preflight('environment_patch',fields,player_index)

    def player_override(self, mode, fields=None, player_index=0):
        if mode=='query':
            if fields is not None:raise BridgeError('INVALID_ARGUMENT','Query does not accept fields')
            return self.call('player_override_query',{},self.identity(player_index))
        args={'mode':mode}
        if fields is not None:args['fields']=fields
        return self.operation_preflight('player_override',args,player_index)

    def inventory_edit(self, target, mode, player_index=0, **parameters):
        return self.operation_preflight('inventory_edit',{'target':target,'mode':mode,**parameters},player_index)

    def inventory_transfer(self, source, destination, value, count, player_index=0):
        return self.operation_preflight('inventory_transfer',{'source':source,'destination':destination,'value':value,'count':count},player_index)

    def interact_block(self, position, player_index=0):
        return self.operation_preflight('interact_block',{'position':coordinate(position)},player_index)

    def climate_patch(self, minimum, maximum, temperature=None, humidity=None, player_index=0):
        args={'minimum':minimum,'maximum':maximum}
        if temperature is not None:args['temperature']=temperature
        if humidity is not None:args['humidity']=humidity
        return self.operation_preflight('climate_patch',args,player_index)

    def climate_query(self, positions, player_index=0):
        from .operation_contract import COLUMN,validate
        try:validate(positions,{'type':'array','items':COLUMN,'minItems':1,'maxItems':64})
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        return self.call('climate_query',{'positions':positions},self.identity(player_index))

    def operation_cancel(self, operation_id, player_index=0):
        return self._operation_request('operation_cancel',operation_id,player_index)

    def _operation_request(self, op, operation_id, player_index=0, accept_risk=None):
        from .operation_contract import IDENTIFIER,validate
        try:validate(operation_id,IDENTIFIER)
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        args={'operation_id':operation_id}
        if accept_risk is not None:
            if accept_risk not in ('state_change','side_effects','dangerous'):raise BridgeError('INVALID_ARGUMENT','Registered risk required')
            args['accept_risk']=accept_risk
        if op=='operation_status':args['player_index']=player_index
        try:identity=self.identity(player_index)
        except BridgeError as error:
            if op!='operation_status' or error.code not in ('NO_WORLD','PLAYER_NOT_READY'):raise
            identity=None
        return self.call(op,args,identity)

    def operation_submit(self, operation_id, accept_risk, player_index=0):
        return self._operation_request('operation_submit',operation_id,player_index,accept_risk)

    def operation_status(self, operation_id, player_index=0):
        return self._operation_request('operation_status',operation_id,player_index)

    def operation_restore(self, operation_id, accept_risk, player_index=0):
        return self._operation_request('operation_restore',operation_id,player_index,accept_risk)

    def event_subscribe(self, kinds, player_index=0):
        from .operation_contract import EVENT_KINDS,validate
        try:validate(kinds,{'type':'array','items':{'type':'string','enum':EVENT_KINDS},'minItems':1,'maxItems':8})
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        return self.call('event_subscribe',{'kinds':kinds,'client_id':self.client_id},self.identity(player_index))

    def event_poll(self, subscription_id, limit=64, player_index=0):
        return self._event_request('event_poll',subscription_id,limit,player_index)

    def event_unsubscribe(self, subscription_id, player_index=0):
        return self._event_request('event_unsubscribe',subscription_id,64,player_index)

    def _event_request(self, op, subscription_id, limit, player_index):
        from .operation_contract import IDENTIFIER,validate
        try:
            validate(subscription_id,IDENTIFIER);validate(limit,{'type':'integer','minimum':1,'maximum':64})
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        return self.call(op,{'subscription_id':subscription_id,'limit':limit,'client_id':self.client_id},self.identity(player_index))

    def event_history(self, after=0, limit=64, boot=None, player_index=0):
        from .operation_contract import validate
        try:
            validate(after,{'type':'integer','minimum':0});validate(limit,{'type':'integer','minimum':1,'maximum':64})
        except ValueError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        args={'after':after,'limit':limit,'client_id':self.client_id}
        if boot is not None:
            self.checked_id(boot);args['boot']=boot
        identity=self.identity(player_index);result=self.call('event_history',args,identity);deadline=time.monotonic()+self.config.timeout
        while result.get('state')=='loading':
            if time.monotonic()>deadline:raise BridgeError('TIMEOUT','History worker still loading',result)
            time.sleep(.025);result=self.call('event_history',{'client_id':self.client_id,'history_id':result['history_id']},identity)
        return result

    def player_state(self, player_index=0):
        return self.call('player_state', {}, self.identity(player_index))

    def _object_query(self, op, minimum, maximum, limit, cursor, player_index, **filters):
        import re
        lo,hi=coordinate(minimum),coordinate(maximum)
        if any(a>b for a,b in zip(lo,hi)):
            raise BridgeError('INVALID_ARGUMENT','Reversed observation bounds')
        volume=1
        for a,b in zip(lo,hi):volume*=b-a+1
        chunks=((hi[0]>>4)-(lo[0]>>4)+1)*((hi[2]>>4)-(lo[2]>>4)+1)
        if volume>1000000 or chunks>256:
            raise BridgeError('LIMIT_EXCEEDED','Observation limited to one million cells and 256 columns')
        if type(limit) is not int or not 1<=limit<=64:
            raise BridgeError('INVALID_ARGUMENT','Object pages limited to 64 records')
        if cursor is not None and (not isinstance(cursor,str) or not re.fullmatch(r'[0-9a-f]{32}:(0|[1-9][0-9]{0,4})',cursor)):
            raise BridgeError('INVALID_CURSOR','Invalid observation cursor')
        args={'minimum':lo,'maximum':hi,'limit':limit,'cursor':cursor,'client_id':self.client_id,**filters}
        return self.call(op,args,self.identity(player_index))

    def entity_query(self, minimum, maximum, kind='all', template=None, limit=64, cursor=None, player_index=0):
        if kind not in ('all','player','creature','body') or template is not None and (not isinstance(template,str) or not 1<=len(template)<=128):
            raise BridgeError('INVALID_ARGUMENT','Invalid kind or template')
        return self._object_query('entity_query',minimum,maximum,limit,cursor,player_index,kind=kind,template=template)

    def pickable_query(self, minimum, maximum, value=None, limit=64, cursor=None, player_index=0):
        if value is not None and (type(value) is not int or not 0<=value<=2147483647):
            raise BridgeError('INVALID_ARGUMENT','Packed item value must be a nonnegative int32')
        return self._object_query('pickable_query',minimum,maximum,limit,cursor,player_index,value=value)

    def lighting_query(self, position, player_index=0):
        return self.call('lighting_query', {'position':coordinate(position)}, self.identity(player_index))

    def inventory_read(self, offset=0, limit=64, player_index=0):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 64:
            raise BridgeError('INVALID_ARGUMENT', 'Inventory page is limited to 64 slots')
        return self.call('inventory_read', {'offset':offset,'limit':limit}, self.identity(player_index))

    def condition_query(self, name, subtype='default', minimum=None, maximum=None, mode=None, position=None, player_index=0):
        from .commands import NON_BUILDING_CONDITIONS
        if (name,subtype) not in NON_BUILDING_CONDITIONS:
            raise BridgeError('UNREGISTERED_COMMAND', 'Condition name/subtype is not registered')
        args={'name':name,'subtype':subtype}
        if name=='blocklight':args['position']=coordinate(position)
        elif position is not None:raise BridgeError('INVALID_ARGUMENT','Position is only registered for blocklight')
        if name=='gamemode':
            if mode not in ('Creative','Survival','Challenging','Harmless','Cruel','Adventure') or minimum is not None or maximum is not None:
                raise BridgeError('INVALID_ARGUMENT', 'Game mode condition requires an exact registered mode')
            args['mode']=mode
        else:
            import math
            if mode is not None or any(type(v) not in (int,float) or not -2**63<=v<=2**63 or not math.isfinite(v) for v in (minimum,maximum)) or minimum>maximum:
                raise BridgeError('INVALID_ARGUMENT', 'Inclusive finite range required')
            args.update(minimum=minimum,maximum=maximum)
        return self.call('condition_query',args,self.identity(player_index))

    def capabilities(self):
        from .commands import descriptor
        return {'host': self.call('capabilities'), 'commands': descriptor()}

    def command(self, name, subtype, parameters, player_index=0):
        from .commands import REGISTRY
        item = REGISTRY.get((name, subtype))
        if item is None: raise BridgeError('UNREGISTERED_COMMAND', 'Command name/subtype is not registered')
        if not isinstance(parameters, dict): raise BridgeError('INVALID_ARGUMENT', 'Structured parameters required')
        from .commands import OPERATION_PATHS
        if (name,subtype) in OPERATION_PATHS:
            return self.operation_preflight(item[0],parameters,player_index)
        if item[0] in ('entity_query','pickable_query'):
            allowed={'minimum','maximum','limit','cursor'}|({'kind','template'} if item[0]=='entity_query' else {'value'})
            if set(parameters)-allowed:raise BridgeError('INVALID_ARGUMENT','Unregistered object observation parameter')
            try:return getattr(self,item[0])(**parameters,player_index=player_index)
            except TypeError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        if item[0]=='condition_query':
            if set(parameters)-{'range_minimum','range_maximum','mode','position'}:raise BridgeError('INVALID_ARGUMENT','Unregistered condition parameter')
            converted={ {'range_minimum':'minimum','range_maximum':'maximum'}.get(k,k):v for k,v in parameters.items() }
            return self.condition_query(name,subtype,**converted,player_index=player_index)
        if item[0] in ('environment_info','player_state','inventory_read','lighting_query'):
            allowed={'offset','limit'} if item[0]=='inventory_read' else ({'position'} if item[0]=='lighting_query' else set())
            if set(parameters)-allowed:raise BridgeError('INVALID_ARGUMENT','Unregistered observation parameter')
            try:return getattr(self,item[0])(**parameters,player_index=player_index)
            except TypeError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        if name=='place':
            if set(parameters)!={'position','value'}:raise BridgeError('INVALID_ARGUMENT','place/default requires position and value')
            return self.fill(parameters['position'],parameters['position'],parameters['value'],player_index)
        registered={
            'resource_write':{'position','value','resource'},'teleport':{'position'},'camera':{'position','target'},
            'measure':{'minimum','maximum'},'screenshot':set(),'heading':{'yaw','pitch'},'condition':{'position','value'},
            'command_config':{'position','query_position','value'}}
        if item[0] in registered:
            if set(parameters)-registered[item[0]]:raise BridgeError('INVALID_ARGUMENT','Unregistered command parameter')
            if item[0]=='resource_write' and parameters.get('resource',{}).get('kind')!=subtype:raise BridgeError('INVALID_ARGUMENT','Resource subtype differs')
            try:return getattr(self,item[0])(**parameters,player_index=player_index)
            except TypeError as error:raise BridgeError('INVALID_ARGUMENT',str(error)) from error
        allowed = {'minimum','maximum','value','match','destination','rotation','mirror','hollow'}
        if set(parameters) - allowed: raise BridgeError('INVALID_ARGUMENT', 'Unregistered command parameter')
        args = dict(parameters)
        if name == 'geometry': args['shape'] = subtype
        return self.preflight(action=item[0], player_index=player_index, **args)

    def fill(self, minimum, maximum, value, player_index=0):
        return self.preflight('fill', minimum, maximum, value=value, player_index=player_index)

    def clear(self, minimum, maximum, player_index=0):
        return self.preflight('clear', minimum, maximum, player_index=player_index)

    def replace(self, minimum, maximum, match, value, player_index=0):
        return self.preflight('replace', minimum, maximum, value=value, match=match, player_index=player_index)

    def copy(self, minimum, maximum, destination, rotation=0, mirror='none', player_index=0):
        return self.preflight('copy', minimum, maximum, destination=destination, rotation=rotation, mirror=mirror, player_index=player_index)

    def move(self, minimum, maximum, destination, rotation=0, mirror='none', player_index=0):
        return self.preflight('move', minimum, maximum, destination=destination, rotation=rotation, mirror=mirror, player_index=player_index)

    def geometry(self, minimum, maximum, shape, value, hollow=False, player_index=0):
        return self.preflight('geometry', minimum, maximum, value=value, shape=shape, hollow=hollow, player_index=player_index)

    def materials(self):
        return self.call('materials')

    def preflight(self, action, minimum, maximum, value=0, match=None, player_index=0,
                  destination=None, rotation=0, mirror='none', shape=None, hollow=False, resource=None):
        low, high = coordinate(minimum), coordinate(maximum)
        volume = 1
        for a, b in zip(low, high):
            if a > b: raise BridgeError('INVALID_ARGUMENT', 'Reversed range')
            volume *= b-a+1
        if volume > 1000000: raise BridgeError('LIMIT_EXCEEDED', 'Region volume exceeds one million')
        if action not in ('fill', 'clear', 'replace', 'copy', 'move', 'geometry', 'resource'): raise BridgeError('UNREGISTERED_COMMAND', 'Unknown action')
        args = {'action': action, 'minimum': low, 'maximum': high, 'value': value}
        if action == 'replace':
            if type(match) is not int: raise BridgeError('INVALID_ARGUMENT', 'replace requires match')
            args['match'] = match
        if action in ('copy', 'move'):
            args.update(destination=coordinate(destination), rotation=rotation, mirror=mirror)
        if action == 'geometry': args.update(shape=shape, hollow=hollow)
        if action == 'resource': args['resource'] = resource
        return self.call('preflight', args, self.identity(player_index, writing=True))

    def submit(self, plan_id, player_index=0):
        return self.call('submit', {'plan_id': self.checked_id(plan_id)}, self.identity(player_index, writing=True))

    @staticmethod
    def checked_id(value):
        if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
            raise BridgeError('INVALID_ARGUMENT', 'Expected 32 lowercase hexadecimal identifier')
        return value

    def job_status(self, job_id, player_index=0):
        return self.call('job_status', {'job_id': self.checked_id(job_id)}, self.identity(player_index))

    def cancel_job(self, job_id, player_index=0):
        return self.call('cancel_job', {'job_id': self.checked_id(job_id)}, self.identity(player_index, writing=True))

    def resume_job(self, job_id, player_index=0):
        return self.call('resume_job', {'job_id':self.checked_id(job_id)},self.identity(player_index,writing=True))

    def restore_job(self, job_id, player_index=0):
        return self.call('restore_job', {'job_id': self.checked_id(job_id)}, self.identity(player_index, writing=True))

    def interrupted_jobs(self):
        return self.call('interrupted_jobs')

    def resource_query(self, position, player_index=0):
        return self.call('resource_query', {'position': coordinate(position)}, self.identity(player_index))

    def resource_write(self, position, value, resource, player_index=0):
        if not isinstance(resource,dict) or resource.get('kind') not in ('container','sign','memory','truth_table','furniture'):
            raise BridgeError('UNREGISTERED_RESOURCE','Resource type is not publicly writable')
        return self.preflight('resource',position,position,value=value,resource=resource,player_index=player_index)

    def command_config(self, position, query_position, value, player_index=0):
        query=coordinate(query_position)
        if type(value) is not int or not 0<=value<=2147483647:raise BridgeError('INVALID_ARGUMENT','Invalid packed value')
        metadata=self.materials()
        block=next((m for m in metadata if m['type']=='Game.CommandBlock'),None)
        if block is None:raise BridgeError('MISSING_DEPENDENCY','Command block not installed')
        line='if:blockexist type:default pos:'+','.join(map(str,query))+' id:'+str(value)
        return self.preflight('resource',position,position,value=block['id'],resource={'kind':'command','line':line},player_index=player_index)

    def condition(self, position, value, player_index=0):
        cell=self.resource_query(position,player_index)
        return {'matches':cell['value']==value,'actual':cell['value']}

    def template_export(self, minimum, maximum, player_index=0):
        return self.call('template_export', {'minimum':coordinate(minimum),'maximum':coordinate(maximum)}, self.identity(player_index))

    def template_inspect(self, template_id):
        from .blueprint import inspect
        path=self.config.artifacts_dir/'templates'/(self.checked_id(template_id)+'.scblueprint')
        return inspect(path)

    def template_import(self, template_id, destination, player_index=0):
        self.template_inspect(template_id)
        return self.call('template_import', {'template_id':self.checked_id(template_id),'destination':coordinate(destination)}, self.identity(player_index,writing=True))

    def measure(self, minimum, maximum, player_index=0):
        return self.call('measure', {'minimum':coordinate(minimum),'maximum':coordinate(maximum)}, self.identity(player_index))

    def prepare_region(self, minimum, maximum, player_index=0, timeout_seconds=0):
        if type(timeout_seconds) not in (int,float) or not __import__('math').isfinite(timeout_seconds) or not 0<=timeout_seconds<=30:
            raise BridgeError('INVALID_ARGUMENT','Preparation timeout must be 0..30 seconds')
        args={'minimum':coordinate(minimum),'maximum':coordinate(maximum)}
        identity=self.identity(player_index);started=time.monotonic()
        while True:
            result=self.call('prepare_region',args,identity)
            result['wait_seconds']=time.monotonic()-started
            result['timed_out']=not result['ready'] and result['wait_seconds']>=timeout_seconds
            if result['ready'] or result['timed_out']:return result
            time.sleep(min(.05,max(0,timeout_seconds-result['wait_seconds'])))

    def teleport(self, position, player_index=0):
        return self.call('teleport', {'position':coordinate(position)}, self.identity(player_index,writing=True))

    def camera(self, position, target, player_index=0):
        return self.call('camera', {'position':coordinate(position),'target':coordinate(target)}, self.identity(player_index,writing=True))

    def heading(self, yaw, pitch=0, player_index=0):
        import math
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (yaw,pitch)) or abs(yaw)>360 or abs(pitch)>82:raise BridgeError('INVALID_ARGUMENT','Invalid heading angles')
        return self.call('heading',{'yaw':yaw,'pitch':pitch},self.identity(player_index,writing=True))

    def screenshot(self, player_index=0):
        return self.call('screenshot', {}, self.identity(player_index))

    def read_region_page(self, minimum, maximum, offset=0, limit=4096, player_index=0):
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=4096:
            raise BridgeError('INVALID_ARGUMENT','Invalid page offset or limit')
        return self.call('read_region_page', {'minimum':coordinate(minimum),'maximum':coordinate(maximum),'offset':offset,'limit':limit},self.identity(player_index))

    def region_statistics(self, minimum, maximum, player_index=0):
        return self.template_export(minimum,maximum,player_index)

    def await_small_job(self, result, player_index):
        if 'job_id' not in result: return result
        deadline = time.monotonic() + self.config.timeout
        while result['state'] in ('running', 'scanning', 'loading_restore', 'validating_source', 'loading_template','waiting_region') and time.monotonic() < deadline:
            time.sleep(.05)
            result = self.job_status(result['job_id'], player_index)
        if result['state'] not in ('completed', 'restored'):
            raise BridgeError('JOB_NOT_COMPLETE', 'Inspect job before retrying', result)
        return result

    def isolate_local(self, player_index=0):
        return self.call('isolate_local', {}, self.identity(player_index))

    def export_backup(self, player_index=0):
        result = self.call('export_backup', {'backup_id': uuid.uuid4().hex})
        path = Path(result['path']).resolve()
        path.relative_to(self.config.backups_dir)
        with zipfile.ZipFile(path) as package:
            bad = package.testzip()
            if bad: raise BridgeError('BACKUP_INVALID', 'Exported zip has a corrupt entry: ' + bad)
            project = ET.fromstring(package.read('Project.xml'))
            name = project.find("./Subsystems/Values[@Name='GameInfo']/Value[@Name='WorldName']")
            if name is None or name.get('Value') != self.config.target['name']:
                raise BridgeError('BACKUP_INVALID', 'Exported world name does not match target')
            result['entries'] = len(package.namelist())
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
        result['sha256'] = h.hexdigest()
        atomic_json(path.with_suffix('.manifest.json'), result)
        return result

    def identity(self, player_index=0, writing=False):
        if type(player_index) is not int or player_index < 0:
            raise BridgeError('INVALID_ARGUMENT', 'player_index must be a non-negative integer')
        info = self.world_info()
        if not info.get('loaded'):
            raise BridgeError('NO_WORLD', 'No world is loaded')
        target = self.config.target
        for key in ('directory', 'name'):
            if not target.get(key) or info[key] != target[key]:
                raise BridgeError('WRONG_WORLD', 'Loaded world does not match configured target')
        if not any(p['index'] == player_index for p in info['players']):
            raise BridgeError('NO_PLAYER', 'Selected player is not present')
        if writing:
            if info.get('network') != 'singleplayer' or len(info['players']) != 1:
                raise BridgeError('MULTIPLAYER_DISABLED', 'Writes require proven local singleplayer')
            self.verify_backup()
        return {'session': info['session'], 'directory': info['directory'], 'name': info['name'],
                'player_index': player_index,'player_name':next(p['name'] for p in info['players'] if p['index']==player_index), 'world_token': target.get('world_token')}

    def verify_backup(self):
        target = self.config.target
        if target.get('validated') is not True:
            raise BridgeError('TARGET_NOT_VALIDATED', 'Target migration has not passed validation')
        path = (self.config.path.parent / target.get('backup', '')).resolve()
        try:
            path.relative_to(self.config.backups_dir)
            h = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    h.update(chunk)
        except (OSError, ValueError) as error:
            raise BridgeError('BACKUP_UNAVAILABLE', 'Configured backup is unavailable') from error
        if h.hexdigest() != target.get('backup_sha256'):
            raise BridgeError('BACKUP_MISMATCH', 'Backup checksum mismatch')

    def read_region(self, minimum, maximum, player_index=0):
        low, high = coordinate(minimum), coordinate(maximum)
        count = 1
        for a, b in zip(low, high):
            if a > b:
                raise BridgeError('INVALID_ARGUMENT', 'minimum must not exceed maximum')
            count *= b - a + 1
        if count > self.config.limits['max_region_cells']:
            raise BridgeError('LIMIT_EXCEEDED', 'Region exceeds read limit')
        return self.call('read_region', {'minimum': low, 'maximum': high}, self.identity(player_index))

    def modify_cells(self, changes, player_index=0):
        if not isinstance(changes, list) or not 1 <= len(changes) <= self.config.limits['max_write_cells']:
            raise BridgeError('LIMIT_EXCEEDED', 'Invalid change count')
        checked, seen = [], set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {'position', 'expected', 'value'}:
                raise BridgeError('INVALID_ARGUMENT', 'Each change needs position, expected and value')
            position = coordinate(change['position'])
            if tuple(position) in seen:
                raise BridgeError('INVALID_ARGUMENT', 'Duplicate cell position')
            seen.add(tuple(position))
            for key in ['expected', 'value']:
                if type(change[key]) is not int or not 0 <= change[key] <= 2147483647:
                    raise BridgeError('INVALID_ARGUMENT', 'Packed values must be non-negative int32')
            checked.append({**change, 'position': position})
        identity = self.identity(player_index, writing=True)
        operation = uuid.uuid4().hex
        journal = {'operation_id': operation, 'identity': identity, 'changes': checked,
                   'state': 'prepared', 'created': time.time()}
        path = self.config.artifacts_dir / 'operations' / (operation + '.json')
        atomic_json(path, journal)
        try:
            result = self.await_small_job(self.call('modify_cells', {'operation_id': operation, 'changes': checked}, identity), player_index)
            result['operation_id'] = operation
        except BridgeError as error:
            journal.update(state='unknown' if error.code == 'TIMEOUT' else 'failed', error=str(error))
            atomic_json(path, journal)
            raise
        journal.update(state='applied', result=result)
        atomic_json(path, journal)
        return result

    def restore_operation(self, operation_id, player_index=0):
        if not isinstance(operation_id, str) or len(operation_id) != 32 or any(c not in '0123456789abcdef' for c in operation_id):
            raise BridgeError('INVALID_ARGUMENT', 'Invalid operation id')
        path = self.config.artifacts_dir / 'operations' / (operation_id + '.json')
        try:
            journal = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise BridgeError('NO_OPERATION', 'Operation record is unavailable') from error
        identity = self.identity(player_index, writing=True)
        if any(journal['identity'][k] != identity[k] for k in ['directory', 'name']):
            raise BridgeError('WRONG_WORLD', 'Operation belongs to a different world')
        if journal['state'] != 'applied':
            raise BridgeError('UNSAFE_RESTORE', 'Only verified applied operations can be restored')
        # The host journal is authoritative and includes a pre-change snapshot.
        result = self.await_small_job(self.call('restore_operation', {'operation_id': operation_id}, identity), player_index)
        journal.update(state='restored', restore_result=result)
        atomic_json(path, journal)
        return result
