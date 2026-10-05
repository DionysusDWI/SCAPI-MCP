// SC_BRIDGE_PROTOCOL_2 — generated deployment configuration precedes this file.
var SC_SYS = importNamespace('System');
var SC_FILE = SC_SYS.IO.File;
var SC_DIR = SC_SYS.IO.Directory;
var SC_BOOT = String(new Date().getTime()) + '-' + Math.random().toString(16).slice(2);
var SC_PROJECT = null;
var SC_SESSION = SC_BOOT + '-0';
var SC_GENERATION = 0;
var SC_REQUEST = null;
var SC_POLL = 0;
var SC_HEARTBEAT = 0;
SC_DIR.CreateDirectory(SC_CONFIG.runtime);
// Retain the OS lock until game exit. Two game hosts must never share runtime.
var SC_LOCK = SC_FILE.Open(SC_CONFIG.runtime + '/host.lock', SC_SYS.IO.FileMode.OpenOrCreate,
    SC_SYS.IO.FileAccess.ReadWrite, SC_SYS.IO.FileShare.None);

function scError(code, message) {
    var e = new Error(message); e.code = code; throw e;
}
function scAtomic(path, object) {
    var temporary = path + '.tmp';
    SC_FILE.WriteAllText(temporary, JSON.stringify(object));
    SC_FILE.Move(temporary, path, true);
}
function scLog(message) {
    try { SC_FILE.AppendAllText(SC_CONFIG.runtime + '/host.log', new Date().toISOString() + ' ' + message + '\n'); }
    catch (e) { }
}
function scProject() {
    var project = getProject();
    if (project !== SC_PROJECT) {
        SC_PROJECT = project; SC_GENERATION++;
        SC_SESSION = SC_BOOT + '-' + SC_GENERATION;
    }
    return project;
}
function scNetwork() {
    try {
        var server = Game.NetworkManager.IsServerRunning;
        var client = Game.NetworkManager.IsClientRunning;
        if (server === true || client === true) return 'multiplayer';
        if (server === false && client === false) return 'singleplayer';
    } catch (e) { }
    return 'unknown';
}
function scPlayers() {
    if (!scProject()) return [];
    var data = findSubsystem('Players').PlayersData, players = [];
    for (var i = 0; i < data.Count; i++) {
        var p = data.get_Item(i), position = null, view = null;
        if (p.ComponentPlayer) {
            var body = p.ComponentPlayer.ComponentBody.Position;
            position = [Number(body.X), Number(body.Y), Number(body.Z)];
            try {
                var camera = p.ComponentPlayer.GameWidget.ActiveCamera;
                view = {position:[Number(camera.ViewPosition.X),Number(camera.ViewPosition.Y),Number(camera.ViewPosition.Z)],
                    direction:[Number(camera.ViewDirection.X),Number(camera.ViewDirection.Y),Number(camera.ViewDirection.Z)]};
            } catch (e) { }
        }
        players.push({index: Number(p.PlayerIndex), name: String(p.Name), position: position, view:view});
    }
    return players;
}
function scWorld() {
    if (!scProject()) return {loaded: false, session: SC_SESSION, network: scNetwork(), players: []};
    var info = findSubsystem('GameInfo');
    return {loaded: true, session: SC_SESSION, directory: String(info.DirectoryName),
            name: String(info.WorldSettings.Name), network: scNetwork(), players: scPlayers()};
}
function scStatus() {
    var gameVersion = null, apiVersion = null, mods = [];
    try { gameVersion = String(Game.VersionsManager.Version); } catch (e) { }
    try { apiVersion = String(Game.APIUpdateManager.CurrentVersion); } catch (e) { }
    try {
        // ModsManager is in the global .NET namespace in API 1.9.3.2.
        var list = importNamespace('').ModsManager.ModList;
        for (var i = 0; i < list.Count; i++) {
            var info = list.get_Item(i).modInfo;
            mods.push({name: String(info.Name), package: String(info.PackageName), version: String(info.Version), api: String(info.ApiVersion)});
        }
    } catch (error) { scError('MOD_STATUS_UNAVAILABLE', 'Cannot enumerate loaded mods: ' + String(error)); }
    return {version: SC_CONFIG.version, protocol: 2, boot: SC_BOOT,
        game_version: gameVersion, api_version: apiVersion,
        installed_mods: SC_CONFIG.installed_mods || [],
        loaded_mods: mods,
        mod_version_source: 'loaded ModsManager.ModList plus deployment package metadata',
        capabilities: ['world_info', 'players', 'read_region', 'modify_cells', 'restore_operation'],
        limits: SC_CONFIG.limits, world: scWorld()};
}
function scIdentity(identity, writing) {
    var world = scWorld();
    if (!world.loaded) scError('NO_WORLD', 'No world is loaded');
    if (!identity || identity.session !== world.session || identity.directory !== world.directory || identity.name !== world.name)
        scError('IDENTITY_MISMATCH', 'World session or identity changed');
    if (world.directory !== SC_CONFIG.target.directory || world.name !== SC_CONFIG.target.name)
        scError('WRONG_WORLD', 'World is not the registered target');
    var present = false;
    for (var i = 0; i < world.players.length; i++) if (world.players[i].index === identity.player_index) present = true;
    if (!present) scError('NO_PLAYER', 'Selected player is absent');
    if (writing) {
        if (world.network !== 'singleplayer' || world.players.length !== 1) scError('MULTIPLAYER_DISABLED', 'Only proven singleplayer writes are allowed');
        if (SC_CONFIG.target.validated !== true || !SC_CONFIG.backup_path || !SC_FILE.Exists(SC_CONFIG.backup_path))
            scError('BACKUP_UNAVAILABLE', 'Validated migration and full backup are required');
        try {
            var digest = SC_SYS.Security.Cryptography.SHA256.HashData(SC_FILE.ReadAllBytes(SC_CONFIG.backup_path));
            var checksum = String(SC_SYS.Convert.ToHexString(digest)).toLowerCase();
            if (checksum !== SC_CONFIG.target.backup_sha256) scError('BACKUP_MISMATCH', 'Full backup checksum changed');
        } catch (error) {
            if (error.code) throw error;
            scError('BACKUP_UNAVAILABLE', 'Cannot independently verify full backup checksum');
        }
    }
    return world;
}
function scPosition(p) {
    if (!Array.isArray(p) || p.length !== 3) scError('INVALID_ARGUMENT', 'Expected three integer coordinates');
    for (var i = 0; i < 3; i++) if (typeof p[i] !== 'number' || !isFinite(p[i]) || Math.floor(p[i]) !== p[i])
        scError('INVALID_ARGUMENT', 'Expected integer coordinates');
    if (Math.abs(p[0]) > 1000000 || Math.abs(p[2]) > 1000000 || p[1] < 0 || p[1] >= 256)
        scError('INVALID_ARGUMENT', 'Coordinates exceed v1 limits');
    return p;
}
function scLoaded(terrain, p) {
    var chunk = terrain.GetChunkAtCell(p[0], p[2]);
    if (chunk === null || chunk === undefined || (String(chunk.State) !== 'Valid' && Number(chunk.State) !== 9))
        scError('CHUNK_NOT_READY', 'Chunk is absent or has not reached Valid state');
}
function scNormalize(value) { return Number(Game.Terrain.ReplaceLight(value, 0)); }
function scValue(value) {
    if (typeof value !== 'number' || Math.floor(value) !== value || value < 0 || value > 2147483647)
        scError('INVALID_ARGUMENT', 'Expected non-negative int32 packed value');
    return scNormalize(value);
}
function scRead(args) {
    var low = scPosition(args.minimum), high = scPosition(args.maximum), count = 1;
    for (var i = 0; i < 3; i++) {
        if (low[i] > high[i]) scError('INVALID_ARGUMENT', 'Invalid region bounds');
        count *= high[i] - low[i] + 1;
    }
    if (count > SC_CONFIG.limits.max_region_cells) scError('LIMIT_EXCEEDED', 'Read region is too large');
    var terrain = findSubsystem('Terrain').Terrain, cells = [];
    for (var x = low[0]; x <= high[0]; x++) for (var z = low[2]; z <= high[2]; z++) {
        scLoaded(terrain, [x, low[1], z]);
        for (var y = low[1]; y <= high[1]; y++) cells.push({position: [x, y, z], value: scNormalize(terrain.GetCellValue(x, y, z))});
    }
    return {cells: cells, count: count, light_bits: 'removed; lighting is transient'};
}
function scOperationId(id) {
    if (typeof id !== 'string' || !/^[0-9a-f]{32}$/.test(id)) scError('INVALID_ARGUMENT', 'Invalid operation id');
    return id;
}
function scJournalPath(id) { return SC_CONFIG.runtime + '/operations/' + scOperationId(id) + '.json'; }
function scIsolateLocal(identity) {
    var world = scIdentity(identity, false);
    if (Game.GameManager.IsNetworkProject !== false || Game.NetworkManager.IsClientRunning !== false || world.players.length !== 1)
        scError('NOT_LOCAL_WORLD', 'Isolation requires one local player in a local project');
    var enumerator = Game.NetworkManager.ServerSessions.GetEnumerator(), peers = 0;
    try { while (enumerator.MoveNext()) peers++; } finally { enumerator.Dispose(); }
    if (peers !== 0) scError('REMOTE_PLAYERS_PRESENT', 'Refusing to disconnect remote players');
    Game.NetworkManager.Stop();
    if (scNetwork() !== 'singleplayer') scError('ISOLATION_FAILED', 'Networking did not stop');
    scLog('isolated local target ' + world.directory + '; explicit operator action');
    return {network: 'singleplayer', directory: world.directory, name: world.name};
}
function scExportBackup(args, identity) {
    if (scWorld().loaded) scError('WORLD_STILL_LOADED', 'Exit the world before exporting locked region files');
    var info = Game.WorldsManager.GetWorldInfo(SC_CONFIG.target.directory);
    if (!info || String(info.WorldSettings.Name) !== SC_CONFIG.target.name)
        scError('WRONG_WORLD', 'Registered backup target does not match');
    var world = {directory:SC_CONFIG.target.directory, name:SC_CONFIG.target.name};
    var id = scOperationId(args.backup_id), folder = SC_CONFIG.backups + '/ssgc/game-exports';
    SC_DIR.CreateDirectory(folder);
    var path = folder + '/' + id + '.scworld';
    if (SC_FILE.Exists(path)) scError('DUPLICATE_OPERATION', 'Backup already exists');
    var stream = SC_FILE.Create(path);
    try { Game.WorldsManager.ExportWorld(world.directory, stream); } finally { stream.Dispose(); }
    return {path: path, source: world.directory, name: world.name, producer: 'Game.WorldsManager.ExportWorld'};
}
function scVerifyBackupImport(args) {
    if (scWorld().loaded) scError('WORLD_STILL_LOADED', 'Exit the world before backup import verification');
    var id = scOperationId(args.backup_id);
    var path = SC_CONFIG.backups + '/ssgc/game-exports/' + id + '.scworld';
    if (!SC_FILE.Exists(path)) scError('BACKUP_UNAVAILABLE', 'Export package is unavailable');
    var stream = SC_FILE.OpenRead(path), directory;
    try { directory = Game.WorldsManager.ImportWorld(stream); } finally { stream.Dispose(); }
    var info = Game.WorldsManager.GetWorldInfo(directory);
    if (!info || String(info.WorldSettings.Name) !== SC_CONFIG.target.name)
        scError('BACKUP_INVALID', 'Imported backup has unexpected world identity');
    var originalName = String(info.WorldSettings.Name);
    info.WorldSettings.Name = 'BACKUP VERIFY ' + id.slice(0,8);
    Game.WorldsManager.ChangeWorld(directory, info.WorldSettings);
    return {directory:String(directory), original_name:originalName, name:String(info.WorldSettings.Name),
        producer:'Game.WorldsManager.ImportWorld', backup_id:id};
}
function scWrite(args, identity, restoring) {
    var id = scOperationId(args.operation_id), path = scJournalPath(id), journal, changes;
    if (restoring) {
        if (!SC_FILE.Exists(path)) scError('NO_OPERATION', 'Host operation journal is unavailable');
        journal = JSON.parse(String(SC_FILE.ReadAllText(path)));
        if (journal.identity.directory !== identity.directory || journal.identity.name !== identity.name)
            scError('WRONG_WORLD', 'Operation belongs to another world');
        if (journal.state !== 'applied') scError('UNSAFE_RESTORE', 'Operation is not fully applied');
        changes = journal.before.map(function(c) { return {position:c.position, expected:c.value_after, value:c.value}; });
    } else {
        if (SC_FILE.Exists(path)) scError('DUPLICATE_OPERATION', 'Operation already exists; never replay');
        changes = args.changes;
        journal = {operation_id: id, identity: identity, before: [], state: 'prepared', applied: 0};
    }
    if (!Array.isArray(changes) || changes.length < 1 || changes.length > SC_CONFIG.limits.max_write_cells)
        scError('LIMIT_EXCEEDED', 'Invalid write count');
    var subsystem = findSubsystem('Terrain'), terrain = subsystem.Terrain, seen = {};
    for (var i = 0; i < changes.length; i++) {
        var c = changes[i], p = scPosition(c.position), key = p.join(',');
        if (seen[key]) scError('INVALID_ARGUMENT', 'Duplicate coordinate');
        seen[key] = true;
        c.expected = scValue(c.expected); c.value = scValue(c.value);
        // v1 guarantees cell-data recovery, not inventory/furniture/entity recovery.
        var contents = Number(Game.Terrain.ExtractContents(c.value));
        if (contents !== 0 && contents !== 3) scError('UNSUPPORTED_BLOCK', 'v1 write surface supports air and granite (id 3) only');
        scLoaded(terrain, p);
        var before = scNormalize(terrain.GetCellValue(p[0], p[1], p[2]));
        if (before !== c.expected) scError('CONFLICT', 'Cell changed since snapshot: ' + key);
        var priorContents = Number(Game.Terrain.ExtractContents(before));
        if (priorContents !== 0 && priorContents !== 3) scError('UNSUPPORTED_BLOCK', 'v1 cannot safely recover entity-bearing or unvalidated blocks');
        if (!restoring) journal.before.push({position: p, value: before, value_after: c.value});
    }
    if (restoring) { journal.state = 'restoring'; journal.restored = 0; }
    scAtomic(path, journal); // Persist the snapshot before touching the world.
    try {
        for (var j = 0; j < changes.length; j++) {
            var change = changes[j], pos = change.position;
            subsystem.ChangeCell(pos[0], pos[1], pos[2], change.value, true, null);
            if (scNormalize(terrain.GetCellValue(pos[0], pos[1], pos[2])) !== change.value)
                scError('WRITE_NOT_OBSERVED', 'Readback differs from requested value');
            if (restoring) journal.restored++; else journal.applied++;
            scAtomic(path, journal);
        }
        journal.state = restoring ? 'restored' : 'applied';
        scAtomic(path, journal);
        return {operation_id: id, state: journal.state, count: changes.length, mesh_update: 'SubsystemTerrain.ChangeCell'};
    } catch (error) {
        journal.state = 'partial'; journal.error = String(error);
        scAtomic(path, journal); throw error;
    }
}
function scRunRequest() {
    var r = SC_REQUEST, result;
    try {
        if (r.protocol !== 2) scError('INCOMPATIBLE_VERSION', 'Protocol mismatch');
        if (r.boot !== SC_BOOT) scError('STALE_BOOT', 'Host restarted');
        if (typeof r.expires !== 'number' || r.expires <= new Date().getTime()) scError('EXPIRED', 'Request expired');
        if (r.op === 'status') result = scStatus();
        else if (r.op === 'world_info') result = scWorld();
        else if (r.op === 'players') result = scPlayers();
        else if (r.op === 'isolate_local') result = scIsolateLocal(r.identity);
        else if (r.op === 'export_backup') result = scExportBackup(r.args, r.identity);
        else if (r.op === 'verify_backup_import') result = scVerifyBackupImport(r.args);
        else if (r.op === 'read_region') { scIdentity(r.identity, false); result = scRead(r.args); }
        else if (r.op === 'modify_cells' || r.op === 'restore_operation') {
            scIdentity(r.identity, true); result = scWrite(r.args, r.identity, r.op === 'restore_operation');
        } else scError('UNKNOWN_OPERATION', 'Unknown operation');
        scAtomic(SC_CONFIG.runtime + '/outbox/' + r.id + '.json', {id:r.id, boot:SC_BOOT, ok:true, data:result});
    } catch (error) {
        scAtomic(SC_CONFIG.runtime + '/outbox/' + r.id + '.json', {id:r.id, boot:SC_BOOT, ok:false,
            error:{code:error.code || 'HOST_ERROR', message:String(error.message || error)}});
    }
}
['inbox', 'claimed', 'outbox', 'operations'].forEach(function(name) { SC_DIR.CreateDirectory(SC_CONFIG.runtime + '/' + name); });
scLog('boot ' + SC_BOOT + ' protocol 2; claimed requests are never replayed');
OnProjectLoadedHandlers.push(function(project) {
    SC_PROJECT = project; SC_GENERATION++; SC_SESSION = SC_BOOT + '-' + SC_GENERATION;
});
OnProjectDisposedHandlers.push(function() {
    SC_PROJECT = null; SC_GENERATION++; SC_SESSION = SC_BOOT + '-' + SC_GENERATION;
});
frameHandlers.push(function() {
    var now = new Date().getTime();
    if (now - SC_HEARTBEAT > 1000) {
        SC_HEARTBEAT = now;
        try { scAtomic(SC_CONFIG.runtime + '/heartbeat.json', {time:now, boot:SC_BOOT, version:SC_CONFIG.version, protocol:2}); }
        catch (error) { scLog('heartbeat ' + error); }
    }
    if (now - SC_POLL < 50) return;
    SC_POLL = now;
    try {
        var files = SC_DIR.GetFiles(SC_CONFIG.runtime + '/inbox', '*.json');
        var length = files.Length === undefined ? files.length : files.Length;
        if (!length) return;
        var file = String(files[0]), filename = String(SC_SYS.IO.Path.GetFileName(file));
        if (!/^[0-9a-f]{32}\.json$/.test(filename)) { scLog('ignored invalid filename'); return; }
        var claimed = SC_CONFIG.runtime + '/claimed/' + filename;
        if (SC_FILE.Exists(claimed)) { SC_FILE.Move(file, file + '.duplicate'); return; }
        SC_FILE.Move(file, claimed); // Claim first; restart cannot replay a write.
        var request = JSON.parse(String(SC_FILE.ReadAllText(claimed)));
        if (request.id + '.json' !== filename) { scLog('request filename/id mismatch'); return; }
        SC_REQUEST = request;
        // The outer frame performs only IPC. The inner runner owns game interop.
        Game.JsInterface.Execute('scRunRequest()');
        var response = SC_CONFIG.runtime + '/outbox/' + request.id + '.json';
        if (!SC_FILE.Exists(response)) scAtomic(response, {id:request.id, boot:SC_BOOT, ok:false,
            error:{code:'EXECUTION_ABORTED', message:'Game interop aborted; inspect journal before retry'}});
    } catch (error) { scLog('poll ' + error); }
});
