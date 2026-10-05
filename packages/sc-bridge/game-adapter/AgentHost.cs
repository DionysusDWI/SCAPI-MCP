using System.Text.Json.Nodes;
using Engine;
using GameEntitySystem;

namespace Game;

public sealed class AgentBridgeLoader : ModLoader
{
    public override void __ModInitialize() { AgentHost.Start();foreach(var hook in new[]{"OnCapture","OnPlayerInputInteract","UpdatePlayerInputAim"})ModsManager.RegisterHook(hook,this); }
    public override void OnCapture()=>AgentHost.CaptureEvent();
    public override void OnPlayerInputInteract(ComponentPlayer p,ref bool operated,ref double interval,ref int use,ref int interact,ref int place)=>AgentHost.PlayerInputInteraction(p);
    public override void UpdatePlayerInputAim(ComponentPlayer p,bool aiming,ref bool operated,ref float interval,bool skipped,out bool skipVanilla){skipVanilla=false;AgentHost.PlayerInputAim(p,aiming);}
}

// Window.Frame runs in menus as well as worlds. No game object leaves this thread.
public static partial class AgentHost
{
    static readonly string Boot = Guid.NewGuid().ToString("N");
    static JsonObject settings;
    static string root, session;
    static Project previous;
    static FileStream lease;
    static long heartbeatAt;
    static readonly System.Text.Json.JsonSerializerOptions Json = new() { WriteIndented = false };
    public static void Start()
    {
        var config = Path.Combine(AppContext.BaseDirectory, "scagentbridge.json");
        if (!File.Exists(config)) return;
        settings = JsonNode.Parse(File.ReadAllText(config)).AsObject();
        InstallFurnitureCompatibility();
        InstallInteractionEvents();
        root = settings["runtime"].GetValue<string>();
        Directory.CreateDirectory(root);
        try { lease = new FileStream(Path.Combine(root,"host.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { Log.Error("SC Agent Bridge: another host owns this queue"); return; }
        Directory.CreateDirectory(Path.Combine(root,"inbox"));
        Directory.CreateDirectory(Path.Combine(root,"outbox"));
        Window.Frame += Tick;
    }
    static long Now => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    public static void Save(string path, JsonNode value)
    {
        if(root!=null&&Path.GetFullPath(path).StartsWith(Path.GetFullPath(OperationDir)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&settings?["target"]?["test_only"]?.GetValue<bool>()==true&&System.Threading.Interlocked.CompareExchange(ref labJournalFail,0,1)==1)throw new IOException("LAB injected operation journal write failure");
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var stream = new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None))
        {
            var bytes = System.Text.Encoding.UTF8.GetBytes(value.ToJsonString(Json));
            stream.Write(bytes); stream.Flush(true);
        }
        try { File.Move(temporary,path,true); }
        finally { if(File.Exists(temporary))File.Delete(temporary); }
    }
    static void Tick()
    {
        try
        {
            if (!ReferenceEquals(previous,GameManager.Project))
            { previous=GameManager.Project; session=Guid.NewGuid().ToString("N"); observationSnapshots.Clear(); creatureTargets.Clear(); ResetInteractionSession(); }
            if (Now-heartbeatAt >=1000)
            {
                try
                {Save(Path.Combine(root,"heartbeat.json"),new JsonObject { ["protocol"]=3,["version"]="0.5.0",["boot"]=Boot,["time"]=Now,["host"]="csharp" });heartbeatAt=Now;}
                catch(Exception error) when(error is IOException or UnauthorizedAccessException) { /* Windows can report a short rename sharing race as access denied. Keep scheduling; retry heartbeat next frame. */ }
            }
            foreach (var path in Directory.EnumerateFiles(Path.Combine(root,"inbox"),"*.json").Take(4))
            {
                JsonObject request=null;
                try
                {
                    if(new FileInfo(path).Length>1024*1024)throw new HostError("LIMIT_EXCEEDED","Request exceeds one megabyte");
                    request=JsonNode.Parse(File.ReadAllText(path)).AsObject();
                    var id=request["id"].GetValue<string>();
                    if (!Guid.TryParseExact(id,"N",out _) || Path.GetFileNameWithoutExtension(path)!=id) throw new HostError("INVALID_REQUEST","Invalid request identity");
                    var processing=path+".processing";
                    File.Move(path,processing); // Restart never replays claimed requests.
                    JsonObject response;
                    try
                    {
                        if ((int)request["protocol"]!=3) throw new HostError("INCOMPATIBLE_VERSION","Protocol 3 required");
                        if ((string)request["boot"]!=Boot) throw new HostError("STALE_BOOT","Host has restarted");
                        if ((long)request["expires"]<Now) throw new HostError("EXPIRED_REQUEST","Request expired before execution");
                        requestClient=(string)request["client_id"];
                        response=new JsonObject { ["ok"]=true,["data"]=Execute((string)request["op"],request["args"].AsObject(),request["identity"]?.AsObject()) };
                    }
                    catch(Exception error) { response=new JsonObject { ["ok"]=false,["error"]=new JsonObject { ["code"]=error is HostError h?h.Code:"HOST_ERROR",["message"]=error.Message } }; }
                    response["id"]=id; response["boot"]=Boot;
                    if(labDropCreatureReply&&(string)request["op"]=="operation_submit"&&(string)response["data"]?["action"]=="creature_patch"){labDropCreatureReply=false;}else Save(Path.Combine(root,"outbox",id+".json"),response);
                    File.Delete(processing);
                }
                catch(Exception error) when((error is IOException or UnauthorizedAccessException)&&File.Exists(path))
                {
                    // A transient Windows sharing lock does not claim or reject a
                    // request. Leave it for a later frame, without replaying writes.
                    Log.Warning("SC Agent Bridge sharing retry: "+error.Message);
                }
                catch(Exception error)
                {
                    Log.Error("SC Agent Bridge request: "+error.Message);
                    if(File.Exists(path))
                    {var quarantine=Path.Combine(root,"quarantine");Directory.CreateDirectory(quarantine);File.Move(path,Path.Combine(quarantine,Guid.NewGuid().ToString("N")+".json"));}
                }
            }
            TickJobs();
            TickOperations();
            TickInteractionEvents();
            TickPlayerOverride();
        }
        catch(Exception error) { Log.Error("SC Agent Bridge frame: "+error.Message); }
    }
    static JsonArray Players()
    {
        var result=new JsonArray();
        if (GameManager.Project==null) return result;
        foreach(var p in GameManager.Project.FindSubsystem<SubsystemPlayers>(true).PlayersData)
        {
            var pos=p.ComponentPlayer?.ComponentBody.Position;
            result.Add(new JsonObject { ["index"]=p.PlayerIndex,["name"]=p.Name,["position"]=pos.HasValue?new JsonArray(pos.Value.X,pos.Value.Y,pos.Value.Z):null });
        }
        return result;
    }
    static JsonObject World()
    {
        if(GameManager.Project==null) return new JsonObject { ["loaded"]=false };
        var info=GameManager.Project.FindSubsystem<SubsystemGameInfo>(true);
        return new JsonObject { ["loaded"]=true,["session"]=session,["directory"]=info.DirectoryName,["name"]=info.WorldSettings.Name,["players"]=Players(),["network"]=!GameManager.IsNetworkProject&&!NetworkManager.IsServerRunning&&!NetworkManager.IsClientRunning&& !NetworkManager.ServerSessions.Any()?"singleplayer":"network" };
    }
    static void Identity(JsonObject identity,bool writing=false,bool requireBackup=true)
    {
        if(ModsManager.APIVersionString!="1.9.3.2")throw new HostError("INCOMPATIBLE_VERSION","Host requires actual API 1.9.3.2");
        var w=World();
        if((bool)w["loaded"]!=true) throw new HostError("NO_WORLD","No world loaded");
        if(identity==null) throw new HostError("IDENTITY_REQUIRED","World identity required");
        foreach(var key in new[]{"session","directory","name"})
            if((string)identity[key]!=(string)w[key]) throw new HostError("IDENTITY_MISMATCH",key+" mismatch");
        foreach(var key in new[]{"directory","name"})
            if((string)settings["target"][key]!=(string)w[key]) throw new HostError("WRONG_WORLD","World is not registered target");
        var token=(string)settings["target"]["world_token"];
        if(string.IsNullOrEmpty(token))throw new HostError("TARGET_NOT_REGISTERED","A unique world registration is required");
        if((string)identity["world_token"]!=token)throw new HostError("IDENTITY_MISMATCH","World registration identity changed");
        using(var marker=Storage.OpenFile(Storage.CombinePaths((string)w["directory"],"scagent-world-id.txt"),OpenFileMode.Read))
        using(var reader=new StreamReader(marker))
            if(reader.ReadToEnd()!=token)throw new HostError("WRONG_WORLD","World registration token differs");
        if(!Players().Any(p=>(int)p["index"]==(int)identity["player_index"])) throw new HostError("NO_PLAYER","Player missing");
        if((string)identity["player_name"]!=Players().Single(p=>(int)p["index"]==(int)identity["player_index"])["name"]?.GetValue<string>())throw new HostError("IDENTITY_MISMATCH","Selected player identity changed");
        if(writing && ((string)w["network"]!="singleplayer" || Players().Count!=1)) throw new HostError("MULTIPLAYER_DISABLED","Writes require isolated singleplayer");
        if(writing)
        {
            if(settings["target"]["validated"]?.GetValue<bool>()!=true) throw new HostError("TARGET_NOT_VALIDATED","Target has no validated backup");
            if(!requireBackup)return;
            var backup=settings["target"]["backup_path"]?.GetValue<string>();
            if(backup==null||!File.Exists(backup)) throw new HostError("BACKUP_UNAVAILABLE","Full backup unavailable");
            // Hash once per file identity; a changed backup forces revalidation.
            VerifyBackup(backup);
        }
    }
    static JsonNode Execute(string op,JsonObject args,JsonObject identity)
    {
        switch(op)
        {
            case "lab_creature_save_unload":case "lab_creature_create":case "lab_creature_adopt":case "lab_creature_hold":case "lab_creature_release":case "lab_creature_drop_reply":case "lab_creature_external":case "lab_creature_factor":case "lab_creature_dead":return CreatureLab(op,args,identity);
            case "creature_inspect":return CreatureInspect(args,identity);
            case "player_override_query":Identity(identity);return CaptureOverride(new Operation {Identity=identity});
            case "operation_preflight":case "operation_submit":case "operation_status":case "operation_restore":case "operation_cancel":return Operations(op,args,identity);
            case "event_subscribe":case "event_poll":case "event_unsubscribe":case "event_history":return InteractionEvents(op,args,identity);
            case "entity_query":case "pickable_query":return EntityObservation(op,args,identity);
            case "climate_query":return ClimateQuery(args,identity);
            case "lighting_query":case "environment_info":case "player_state":case "inventory_read":case "condition_query":return NonBuilding(op,args,identity);
            case "lab_climate_unavailable":case "lab_climate_available":case "lab_fixture_blocker":case "lab_fixture_far":case "lab_fixture_recover":case "lab_fixture_user_camera":case "lab_journal_fail_next":case "lab_event_log_fail_next":case "lab_override_external_change":case "lab_fixture_door":case "lab_fixture_trapdoor":case "lab_fixture_switch":case "lab_fixture_button":case "lab_fixture_container":case "lab_fixture_remove":case "lab_fixture_state":case "lab_pending_enable":case "lab_pending_complete":case "lab_native_event_suite":case "lab_inventory_fail_second":case "lab_inventory_failure_release":case "lab_event_native_attempt":case "lab_event_overflow":case "lab_create_survival_copy":case "lab_create_observation_fixture":case "lab_remove_observation_fixture":case "lab_expire_observation_snapshots":case "lab_invalid_inventory":case "lab_release_invalid_inventory":case "lab_circuit_outputs":case "lab_create_world":case "lab_load_target":case "lab_verify_backup_import":case "lab_export_b":case "lab_save_unload":case "lab_stabilize_environment":case "lab_interrupt_process":case "lab_fill_design_capacity":case "lab_release_design_capacity":case "lab_add_player":case "lab_remove_player":return Lab(op,identity);
            case "read_region_page":case "teleport":case "camera":case "heading":case "prepare_region":case "measure":case "screenshot": return Observe(op,args,identity);
            case "export_backup":
                if(GameManager.Project!=null) throw new HostError("WORLD_LOADED","Export requires a saved, unloaded world");
                var dir=(string)settings["target"]["directory"];
                var wi=WorldsManager.GetWorldInfo(dir);
                if(wi==null||wi.WorldSettings.Name!=(string)settings["target"]["name"]) throw new HostError("WRONG_WORLD","Backup target mismatch");
                var backupFile=Path.Combine((string)settings["backups"],"mcp-lab","exports",Guid.NewGuid().ToString("N")+".scworld");
                Directory.CreateDirectory(Path.GetDirectoryName(backupFile));
                using(var stream=File.Create(backupFile)) WorldsManager.ExportWorld(dir,stream);
                return new JsonObject { ["path"]=backupFile,["directory"]=dir,["name"]=wi.WorldSettings.Name };
            case "status":
                var mods=new JsonArray();
                foreach(var m in ModsManager.ModList)mods.Add(new JsonObject { ["package"]=m.modInfo.PackageName,["version"]=m.modInfo.Version,["api_version"]=m.modInfo.ApiVersion });
                return new JsonObject { ["protocol"]=3,["version"]="0.5.0",["boot"]=Boot,["api_version"]=ModsManager.APIVersionString,["game_version"]=ModsManager.GameVersion,["mods"]=mods,["world"]=World(),["capabilities"]=ExecuteBuilding("capabilities",args,identity) };
            case "world_info": return World();
            case "players": return Players();
            case "isolate_local":
                Identity(identity);
                if(GameManager.IsNetworkProject||NetworkManager.ServerSessions.Any()||Players().Count!=1) throw new HostError("MULTIPLAYER_DISABLED","Not an empty local server");
                NetworkManager.Stop(); return World();
            case "read_region":
                Identity(identity);
                var lo=Position(args["minimum"]); var hi=Position(args["maximum"]);
                var volume=(long)(hi.X-lo.X+1)*(hi.Y-lo.Y+1)*(hi.Z-lo.Z+1);
                if(hi.X<lo.X||hi.Y<lo.Y||hi.Z<lo.Z||volume>4096) throw new HostError("LIMIT_EXCEEDED","Read pages are bounded to 4096 cells");
                var terrain=GameManager.Project.FindSubsystem<SubsystemTerrain>(true).Terrain;
                var cells=new JsonArray();
                for(int x=lo.X;x<=hi.X;x++)for(int y=lo.Y;y<=hi.Y;y++)for(int z=lo.Z;z<=hi.Z;z++)
                {
                    var chunk=terrain.GetChunkAtCell(x,z);
                    if(chunk==null||chunk.State!=TerrainChunkState.Valid) throw new HostError("REGION_NOT_LOADED","Chunk is not valid");
                    cells.Add(new JsonObject { ["position"]=new JsonArray(x,y,z),["value"]=Terrain.ReplaceLight(terrain.GetCellValue(x,y,z),0) });
                }
                return new JsonObject { ["cells"]=cells,["count"]=cells.Count };
            default: return ExecuteBuilding(op,args,identity);
        }
    }
    static Point3 Position(JsonNode node)
    {
        var a=node.AsArray();
        if(a.Count!=3) throw new HostError("INVALID_ARGUMENT","Three coordinates required");
        var p=new Point3((int)a[0],(int)a[1],(int)a[2]);
        if(Math.Abs((long)p.X)>1000000||Math.Abs((long)p.Z)>1000000||p.Y<0||p.Y>255) throw new HostError("INVALID_ARGUMENT","Coordinates out of bounds");
        return p;
    }
}
public sealed class HostError(string code,string message) : Exception(message)
{ public string Code { get; }=code; }
