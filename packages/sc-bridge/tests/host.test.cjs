const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../sc_bridge/legacy/host-v2.js'), 'utf8');

function harness(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'sc-host-'));
    t.after(() => fs.rmSync(root, {recursive:true, force:true}));
    fs.writeFileSync(path.join(root, 'backup.scworld'), 'backup');
    const cells = new Map(), project = {};
    const terrain = {GetChunkAtCell: () => ({State:'Valid'}),
        GetCellValue: (x,y,z) => cells.get([x,y,z].join(',')) || 0};
    const subsystem = {Terrain:terrain, ChangeCell:(x,y,z,value) => cells.set([x,y,z].join(','), value)};
    const player = {PlayerIndex:0, Name:'Test', ComponentPlayer:{ComponentBody:{Position:{X:0,Y:80,Z:0}}}};
    const mods = {Count:1, get_Item:() => ({modInfo:{Name:'Command',PackageName:'zh.command',Version:'4.1.8',ApiVersion:'1.9'}})};
    const io = {File:{WriteAllText:fs.writeFileSync, ReadAllText:p=>fs.readFileSync(p,'utf8'),
        AppendAllText:fs.appendFileSync, Exists:fs.existsSync, Delete:fs.unlinkSync, Move:fs.renameSync,
        Open:()=>({}), ReadAllBytes:fs.readFileSync},
        Directory:{CreateDirectory:p=>fs.mkdirSync(p,{recursive:true}), GetFiles:p=>fs.readdirSync(p).filter(n=>n.endsWith('.json')).map(n=>path.join(p,n))},
        Path:{GetFileName:path.basename}, FileMode:{OpenOrCreate:0},FileAccess:{ReadWrite:0},FileShare:{None:0}};
    const context = vm.createContext({console, SC_CONFIG:{runtime:root,version:'0.1.0',protocol:2,
        backup_path:path.join(root,'backup.scworld'), target:{directory:'app:/doc/Worlds/World1',name:'SSGC bata3',validated:true,
            backup_sha256:crypto.createHash('sha256').update('backup').digest('hex')},
        limits:{max_region_cells:4096,max_write_cells:64}},
        importNamespace:()=>({ModsManager:{ModList:mods}, IO:io, Security:{Cryptography:{SHA256:{HashData:bytes=>crypto.createHash('sha256').update(bytes).digest()}}},
            Convert:{ToHexString:bytes=>bytes.toString('hex')}}), getProject:()=>project,
        frameHandlers:[],OnProjectLoadedHandlers:[],OnProjectDisposedHandlers:[],
        findSubsystem:n=>n==='Terrain'?subsystem:n==='GameInfo'?{DirectoryName:'app:/doc/Worlds/World1',WorldSettings:{Name:'SSGC bata3'}}:
            {PlayersData:{Count:1,get_Item:()=>player}},
        Game:{GameManager:{IsNetworkProject:false}, NetworkManager:{IsServerRunning:false,IsClientRunning:false,
            ServerSessions:{GetEnumerator:()=>({MoveNext:()=>false,Dispose:()=>{}})},
            Stop:()=>{context.Game.NetworkManager.IsServerRunning=false; context.Game.NetworkManager.IsClientRunning=false;}},
            ModsManager:{ModList:mods},VersionsManager:{Version:'2.4'},APIUpdateManager:{CurrentVersion:'1.9.3.2'},
            Terrain:{ReplaceLight:v=>v & ~0x3c00,ExtractContents:v=>v & 1023},
            JsInterface:{Execute:code=>vm.runInContext(code,context)}}});
    vm.runInContext(source,context);
    const identity=()=>({session:context.scWorld().session,directory:'app:/doc/Worlds/World1',name:'SSGC bata3',player_index:0});
    let sequence=0;
    const call=(op,args={},overrides={})=>{
        const id=(++sequence).toString(16).padStart(32,'0');
        context.SC_REQUEST={id,protocol:2,boot:context.SC_BOOT,expires:Date.now()+5000,op,args,identity:identity(),...overrides};
        context.scRunRequest();
        return JSON.parse(fs.readFileSync(path.join(root,'outbox',id+'.json'),'utf8'));
    };
    return {context,cells,terrain,root,identity,call};
}

test('write, readback and conflict-safe restoration',t=>{
    const h=harness(t), id='a'.repeat(32);
    assert.equal(h.call('modify_cells',{operation_id:id,changes:[{position:[0,80,0],expected:0,value:3}]}).ok,true);
    assert.equal(h.call('read_region',{minimum:[0,80,0],maximum:[0,80,0]}).data.cells[0].value,3);
    h.cells.set('0,80,0',0);
    assert.equal(h.call('restore_operation',{operation_id:id}).error.code,'CONFLICT');
    h.cells.set('0,80,0',3);
    assert.equal(h.call('restore_operation',{operation_id:id}).data.state,'restored');
    assert.equal(h.cells.get('0,80,0'),0);
});
test('preflight conflict leaves every cell unchanged',t=>{
    const h=harness(t);
    const result=h.call('modify_cells',{operation_id:'a'.repeat(32),changes:[
        {position:[0,80,0],expected:0,value:3},{position:[1,80,0],expected:3,value:0}]});
    assert.equal(result.error.code,'CONFLICT'); assert.equal(h.cells.size,0);
});
test('network and unknown state both reject writes',t=>{
    const h=harness(t), changes=[{position:[0,80,0],expected:0,value:3}];
    h.context.Game.NetworkManager.IsServerRunning=true;
    assert.equal(h.call('modify_cells',{operation_id:'a'.repeat(32),changes}).error.code,'MULTIPLAYER_DISABLED');
    delete h.context.Game.NetworkManager.IsServerRunning;
    assert.equal(h.call('modify_cells',{operation_id:'b'.repeat(32),changes}).error.code,'MULTIPLAYER_DISABLED');
});
test('local splitscreen also refuses v1 writes',t=>{
    const h=harness(t);
    const original=h.context.findSubsystem;
    h.context.findSubsystem=n=>n==='Players'?{PlayersData:{Count:2,get_Item:i=>({PlayerIndex:i,Name:'Local',ComponentPlayer:null})}}:original(n);
    assert.equal(h.call('modify_cells',{operation_id:'a'.repeat(32),changes:[{position:[0,80,0],expected:0,value:3}]}).error.code,'MULTIPLAYER_DISABLED');
});
test('unloaded chunks are errors rather than air',t=>{
    const h=harness(t); h.terrain.GetChunkAtCell=()=>null;
    assert.equal(h.call('read_region',{minimum:[0,80,0],maximum:[0,80,0]}).error.code,'CHUNK_NOT_READY');
});
test('Jint numeric chunk enum accepts only Valid (9)',t=>{
    const h=harness(t), args={minimum:[0,80,0],maximum:[0,80,0]};
    h.terrain.GetChunkAtCell=()=>({State:9});
    assert.equal(h.call('read_region',args).ok,true);
    h.terrain.GetChunkAtCell=()=>({State:8});
    assert.equal(h.call('read_region',args).error.code,'CHUNK_NOT_READY');
});
test('stale boot, stale world session, expiry and protocol are rejected',t=>{
    const h=harness(t);
    assert.equal(h.call('status',{}, {boot:'old'}).error.code,'STALE_BOOT');
    assert.equal(h.call('status',{}, {expires:0}).error.code,'EXPIRED');
    assert.equal(h.call('status',{}, {protocol:1}).error.code,'INCOMPATIBLE_VERSION');
    assert.equal(h.call('read_region',{minimum:[0,80,0],maximum:[0,80,0]}, {identity:{...h.identity(),session:'old'}}).error.code,'IDENTITY_MISMATCH');
});
test('claimed request is not replayed; queued old boot is rejected',t=>{
    const h=harness(t), id='c'.repeat(32), filename=id+'.json';
    const r={id,protocol:2,boot:'old',expires:Date.now()+5000,op:'modify_cells',identity:h.identity(),args:{}};
    fs.writeFileSync(path.join(h.root,'claimed',filename),JSON.stringify(r));
    fs.writeFileSync(path.join(h.root,'inbox',filename),JSON.stringify(r));
    h.context.SC_POLL=0; h.context.frameHandlers[0]();
    assert.equal(h.cells.size,0); assert.equal(fs.existsSync(path.join(h.root,'outbox',filename)),false);
    const other='d'.repeat(32); fs.writeFileSync(path.join(h.root,'inbox',other+'.json'),JSON.stringify({...r,id:other}));
    h.context.SC_POLL=0; h.context.frameHandlers[0]();
    assert.equal(JSON.parse(fs.readFileSync(path.join(h.root,'outbox',other+'.json'))).error.code,'STALE_BOOT');
});
test('unvalidated target, unavailable backup and unsupported blocks fail closed',t=>{
    const h=harness(t), request={operation_id:'e'.repeat(32),changes:[{position:[0,80,0],expected:0,value:3}]};
    h.context.SC_CONFIG.target.validated=false;
    assert.equal(h.call('modify_cells',request).error.code,'BACKUP_UNAVAILABLE');
    h.context.SC_CONFIG.target.validated=true; fs.unlinkSync(h.context.SC_CONFIG.backup_path);
    assert.equal(h.call('modify_cells',request).error.code,'BACKUP_UNAVAILABLE');
    fs.writeFileSync(h.context.SC_CONFIG.backup_path,'backup'); request.changes[0].value=54;
    assert.equal(h.call('modify_cells',request).error.code,'UNSUPPORTED_BLOCK');
});
test('operator isolates local auto-server but refuses remote sessions',t=>{
    const h=harness(t);
    h.context.Game.NetworkManager.IsServerRunning=true;
    assert.equal(h.call('isolate_local').data.network,'singleplayer');
    h.context.Game.NetworkManager.IsServerRunning=true;
    let visited=false;
    h.context.Game.NetworkManager.ServerSessions.GetEnumerator=()=>({MoveNext:()=>{if(visited)return false;visited=true;return true;},Dispose:()=>{}});
    assert.equal(h.call('isolate_local').error.code,'REMOTE_PLAYERS_PRESENT');
    assert.equal(h.context.Game.NetworkManager.IsServerRunning,true);
});
