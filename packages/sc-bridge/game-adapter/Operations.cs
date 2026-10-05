using System.Text.Json.Nodes;
using Engine;
namespace Game;
public static partial class AgentHost
{
    sealed class Operation
    {
        public string Id=Guid.NewGuid().ToString("N"),State="ready",Action,Risk,Recovery;
        public JsonObject Identity,Arguments,Before,After,Error,Planned;
        public long Created=Now;
        public bool Backup;
        public Task Persistence;
        public string RestoreOf;
        public string Client;
        public bool LateBind;
        public JsonObject Guards;
        public JsonObject FullBackup;
        public Task<JsonObject> BackupWork;
        public long MaintenanceStarted;
        public JsonArray Steps=[];
        public ComponentMiner PendingMiner;
        public bool? InteractionResult;
        public string ClimateWaitState;
        public long ClimateWaitStarted;
        public string AuditError;
        public int InteractionReadbackFrame;
        public JsonObject Observations;
        public List<ClimateColumn> Climate=[];
        public int ClimateCursor,ClimateBatchSize=512,ClimateBatch,TotalColumns;
        public bool Cancel;
        public List<ClimateColumn> ClimatePending;
    }
    static readonly Dictionary<string,Operation> operations=[];
    static string operationActive;
    static string OperationDir=>Path.Combine(root,"operations");
    static void Closed(JsonObject args,params string[] allowed)
    {if(args==null||args.Any(k=>!allowed.Contains(k.Key)))throw new HostError("INVALID_ARGUMENT","Unknown operation field");}
    static string RequiredText(JsonObject args,string key)
    {if(args[key] is not JsonValue value||!value.TryGetValue<string>(out var text)||string.IsNullOrEmpty(text))throw new HostError("INVALID_ARGUMENT",key+" must be text");return text;}
    static string GuidText(JsonObject args,string key)
    {var id=RequiredText(args,key);if(!Guid.TryParseExact(id,"N",out _))throw new HostError("INVALID_ARGUMENT","GUID required");return id;}
    static double Number(JsonObject args,string key,double lo,double hi)
    {if(args[key] is not JsonValue value||!value.TryGetValue<double>(out var n)||!double.IsFinite(n)||n<lo||n>hi)throw new HostError("INVALID_ARGUMENT",key+" outside native bounds");return n;}
    static bool Boolean(JsonObject args,string key)
    {if(args[key] is not JsonValue v||!v.TryGetValue<bool>(out var b))throw new HostError("INVALID_ARGUMENT",key+" must be boolean");return b;}
    static string OperationSideEffects(Operation o)=>o.Action switch {
        "creature_patch"=>"Direct creature fields only; later movement, damage and ecosystem effects are irreversible. One-shot changes do not persist as overrides; save/load persistence is field-dependent.",
        "interact_block"=>"Native circuits, sounds, entity/loot creation and UI opening may follow. Restoring a door/switch direct state does not undo downstream behavior; button pulses and container opening are irreversible.",
        "inventory_transfer"=>o.Recovery=="none"?"Creative supply to real inventory generates items; real inventory to creative supply destroys items. Native callbacks may partially execute; inspect recorded steps and compensation, never repeat blindly.":"Real item quantities are conserved on completion. Native callbacks are not transactional; direct slot compensation is best effort and conflicts are reported.",
        "inventory_edit"=>"Selected items may be generated or destroyed intentionally. No automatic drop, consumption or wearing. Native callbacks may have irreversible side effects.",
        "environment_patch"=>o.Backup?"World mode/season maintenance saves, fully backs up and reloads the same registered target. Inventory components/rules and ecosystem outcomes may change; this operation cannot be locally restored.":"Weather, clock, rendering and native world rules can cause irreversible downstream changes. Only explicitly recoverable direct fields are compared and restored; elapsed game time never rewinds.",
        "climate_patch"=>"Column climate and downstream vegetation/weather may change irreversibly. Cancellation retains completed batches; full backup and batch snapshots remain available without automatic replay.",
        "player_override"=>"Enabled movement/attack/defense overrides affect future simulation. Disabling releases owned direct values; past movement, damage and other mod effects cannot be undone.",
        _=>"Natural physiology drift, damage, consumption and downstream effects are not reversed; restore rejects changed direct values."};
    static JsonObject OperationRecord(Operation o)=>new() {
        ["operation_id"]=o.Id,["state"]=o.State,["action"]=o.Action,["risk"]=o.Risk,["recovery"]=o.Recovery,
        ["boot"]=Boot,["client_id"]=o.Client,["identity"]=o.Identity.DeepClone(),["arguments"]=o.Arguments.DeepClone(),
        ["before"]=o.Before?.DeepClone(),["after"]=o.After?.DeepClone(),["intended_after"]=o.Planned?.DeepClone(),["error"]=o.Error?.DeepClone(),
        ["comparison"]=o.LateBind?"Dynamic physiology snapshot is captured and durably saved in the execution frame; stable fields and guards remain bound to preflight":"exact preflight fields",
        ["guards"]=o.Guards?.DeepClone(),
        ["full_backup"]=o.FullBackup?.DeepClone(),
        ["steps"]=o.Steps.DeepClone(),
        ["audit_error"]=o.AuditError??(o.Persistence?.IsFaulted==true?"AUDIT_WRITE_FAILED: "+o.Persistence.Exception.GetBaseException().Message:null),
        ["audit_state"]=o.Persistence?.IsFaulted==true?"failed":o.Persistence?.IsCompletedSuccessfully==true?"durable":"writing",
        ["observed_result"]=o.Observations?.DeepClone(),
        ["execution_steps"]=new JsonArray("persist intent and before state",o.Backup?"save/unload/export/checksum/reload current target":"revalidate affected fields in current game frame","execute registered native effects","read back actual fields","persist result; never replay an uncertain effect"),
        ["affected_resources"]=o.Action is "inventory_edit" or "inventory_transfer"?o.Planned?.DeepClone():o.Arguments.DeepClone(),
        ["persistence"]=o.Action=="player_override"?"configuration persists; enable state expires at world reload/host restart":o.Action=="environment_patch"?"World settings/time offset and commandblock rendering colors persist; simulation factor/day duration are session fields; weather consequences evolve naturally":"native world/player state; natural updates may change fields",
        ["created_at"]=o.Created,["expires_at"]=o.Created+120000,["backup_required"]=o.Backup,["restore_of"]=o.RestoreOf,
        ["processed"]=o.ClimateCursor,["columns"]=o.TotalColumns,["batch_count"]=o.ClimateBatch,["snapshot_directory"]=o.Action=="climate_patch"?Path.Combine(OperationDir,o.Id):null,
        ["side_effects"]=OperationSideEffects(o) };
    static void PersistOperation(Operation o)
    {var record=OperationRecord(o);var path=Path.Combine(OperationDir,o.Id+".json");var prior=o.Persistence;o.Persistence=Task.Run(async()=>{if(prior!=null)await prior;Save(path,record);});}
    static Operation GetOperation(string id,JsonObject identity)
    {
        if(!operations.TryGetValue(id,out var o))throw new HostError("STALE_OPERATION","This boot has no executable plan; query the durable record");
        if(o.Action=="creature_patch"&&o.Client!=requestClient)throw new HostError("IDENTITY_MISMATCH","Creature operation belongs to another client");
        if(!JsonNode.DeepEquals(o.Identity,identity))throw new HostError("IDENTITY_MISMATCH","Operation target/session/player changed");return o;
    }
    static JsonObject ReadOperationRecord(string id,int player,JsonObject identity=null)
    {
        var record=operations.TryGetValue(id,out var live)?OperationRecord(live):File.Exists(Path.Combine(OperationDir,id+".json"))?JsonNode.Parse(File.ReadAllText(Path.Combine(OperationDir,id+".json"))).AsObject():throw new HostError("UNKNOWN_OPERATION","No operation record");
        foreach(var key in new[]{"world_token","directory","name"})if((string)record["identity"][key]!=(string)settings["target"][key])throw new HostError("IDENTITY_MISMATCH","Record belongs to another configured target");
        if((int)record["identity"]["player_index"]!=player)throw new HostError("IDENTITY_MISMATCH","Record belongs to another selected player");
        if(identity!=null)
        {
            foreach(var key in new[]{"world_token","directory","name","player_name"})if((string)record["identity"][key]!=(string)identity[key])throw new HostError("IDENTITY_MISMATCH","Record target/player changed");
        }
        record["interrupted"]=(string)record["boot"]!=Boot&&(string)record["state"] is not ("ready" or "completed" or "failed" or "cancelled");return record;
    }
    static JsonNode Operations(string op,JsonObject args,JsonObject identity)
    {
        if(op!="operation_status")Identity(identity,true,false);
        if(op!="operation_status"&&!OperationCapabilityAllowed(op))throw new HostError("CAPABILITY_DISABLED","Unverified non-building operation is closed outside registered LAB targets");
        if(op=="operation_preflight")
        {
            Closed(args,"action","parameters");string action=RequiredText(args,"action");
            if(!OperationCapabilityAllowed(action))throw new HostError("CAPABILITY_DISABLED","Selected operation action has not passed LAB acceptance");
            if(args["parameters"] is not JsonObject parameters)throw new HostError("INVALID_ARGUMENT","Structured parameters required");
            foreach(var old in operations.Values.Where(o=>o.State=="ready"&&Now-o.Created>120000).ToArray())operations.Remove(old.Id);
            foreach(var old in operations.Values.Where(o=>o.State is "completed" or "failed" or "cancelled"&&o.Persistence?.IsCompleted==true).OrderBy(o=>o.Created).Take(Math.Max(0,operations.Count-64)).ToArray())operations.Remove(old.Id);
            if(operations.Count>=128)throw new HostError("OPERATION_CAPACITY","128 active records; restart only after inspecting records");
            var o=new Operation { Client=requestClient,Action=action,Arguments=parameters.DeepClone().AsObject(),Identity=identity.DeepClone().AsObject() };
            DescribeOperation(o);o.Before=CaptureOperation(o);operations.Add(o.Id,o);PersistOperation(o);return OperationRecord(o);
        }
        Closed(args,"operation_id","accept_risk","player_index");var id=GuidText(args,"operation_id");
        if(op=="operation_status")
        {
            return ReadOperationRecord(id,Integer(args,"player_index",0,15),identity);
        }
        if(op=="operation_submit"&&(!operations.TryGetValue(id,out var duplicate)||duplicate.State!="ready"))
        {
            var record=ReadOperationRecord(id,(int)identity["player_index"],identity);
            if(RequiredText(args,"accept_risk")!=(string)record["risk"])throw new HostError("RISK_ACK_REQUIRED","Exact risk acknowledgement required");
            if((string)record["boot"]!=Boot&&(string)record["state"]=="ready")throw new HostError("STALE_OPERATION","Previous boot plans are never submitted again");
            if((string)record["state"]=="scanning")throw new HostError("PLAN_NOT_READY","Asynchronous preflight has not completed; no submission occurred");
            return record;
        }
        Operation plan;
        if(op=="operation_restore")
        {
            var record=ReadOperationRecord(id,(int)identity["player_index"],identity);
            if((string)record["action"]=="creature_patch"&&(string)record["client_id"]!=requestClient)throw new HostError("IDENTITY_MISMATCH","Creature restoration belongs to another client");
            plan=new Operation {Client=(string)record["client_id"],Id=id,Action=(string)record["action"],Arguments=record["arguments"].DeepClone().AsObject(),Identity=identity.DeepClone().AsObject(),RestoreOf=id,Planned=record["intended_after"]?.DeepClone().AsObject()};
            if(plan.Action is "inventory_edit" or "inventory_transfer")DescribeInventoryRestore(plan);else DescribeOperation(plan); // Re-establish the closed capability policy; never trust record metadata to grant new paths.
            if(plan.Recovery!=(string)record["recovery"])throw new HostError("STALE_OPERATION","Recovery contract changed; inspect record");
            plan.State=(string)record["state"];plan.Before=record["before"]?.DeepClone().AsObject();plan.After=record["after"]?.DeepClone().AsObject();plan.Planned=record["intended_after"]?.DeepClone().AsObject();
        }
        else plan=GetOperation(id,identity);
        if(op=="operation_cancel"){if(plan.Action!="climate_patch")throw new HostError("NOT_CANCELLABLE","Only asynchronous climate tasks support batch cancellation");plan.Cancel=true;if(plan.State is "paused" or "ready"){plan.State="cancelled";PersistOperation(plan);}return OperationRecord(plan);}
        if(op=="operation_restore")
        {
            if(plan.Recovery=="none")throw new HostError("NOT_RECOVERABLE","Operation is explicitly irreversible");
            if(plan.State!="completed"||plan.After==null)throw new HostError("NOT_COMPLETED","Only completed operations have a verified restoration target");
            var restore=new Operation {Client=plan.Client,Action=plan.Action,Arguments=plan.Arguments.DeepClone().AsObject(),Identity=identity.DeepClone().AsObject(),Risk=plan.Risk,Recovery=plan.Recovery,Backup=plan.Backup,Before=plan.After.DeepClone().AsObject(),After=plan.Before.DeepClone().AsObject(),Planned=plan.Planned?.DeepClone().AsObject(),RestoreOf=id};
            if(RequiredText(args,"accept_risk")!=restore.Risk)throw new HostError("RISK_ACK_REQUIRED","Exact risk acknowledgement required");
            if(!OperationMatches(restore))throw new HostError("RESTORE_CONFLICT","Current direct fields no longer equal the recorded after values");
            if(operations.Count>=128)throw new HostError("OPERATION_CAPACITY","Operation capacity reached");
            operations.Add(restore.Id,restore);plan=restore;
        }
        else if(plan.State!="ready")return OperationRecord(plan); // Durable id deduplication, never repeat a completed effect.
        if(Now-plan.Created>120000)throw new HostError("STALE_PLAN","Preflight expired");
        if(RequiredText(args,"accept_risk")!=plan.Risk)throw new HostError("RISK_ACK_REQUIRED","Submit must acknowledge the exact preflight risk");
        if(active!=null||operationActive!=null)throw new HostError("WORLD_BUSY","World already has a modification task");
        Identity(identity,true,plan.Backup);
        if(!OperationMatches(plan))throw new HostError("STALE_PLAN","Affected fields or guards changed; preflight again");
        plan.State="persisting_intent";operationActive=plan.Id;PersistOperation(plan);return OperationRecord(plan);
    }
    static void TickOperations()
    {
        foreach(var scanning in operations.Values.Where(o=>o.State=="scanning").ToArray())TickClimateScan(scanning);
        if(operationActive==null)return;
        var o=operations[operationActive];
        if(o.Action=="creature_patch"&&labHoldCreature&&settings["target"]["test_only"]?.GetValue<bool>()==true)return;
        try
        {
            if(o.Persistence is {IsCompleted:false})return;
            o.Persistence?.GetAwaiter().GetResult();
            if(o.Backup&&o.FullBackup==null&&!TickFreshOperationBackup(o))return;
            if(o.State=="waiting_backup_reload"&&!FinishBackupReload(o))return;
            if(o.State=="waiting_interaction_readback")
            {
                Identity(o.Identity,true,false);if(Time.FrameIndex<o.InteractionReadbackFrame)return;
                o.After=CaptureInteract(o,false);o.State="persisting_result";PersistOperation(o);return;
            }
            if(o.State=="waiting_native")
            {
                Identity(o.Identity,true,false);
                if(!o.InteractionResult.HasValue)
                {
                    if(Now-o.MaintenanceStarted>10000)throw new HostError("UNKNOWN_RESULT","Native pending interaction did not report completion; never replay");
                    return;
                }
                o.After=CaptureInteract(o,false);
                if(!o.InteractionResult.Value)throw new HostError("INTERACTION_REJECTED","Native pending behavior rejected interaction");
                o.State="waiting_interaction_readback";o.InteractionReadbackFrame=Time.FrameIndex+2;PersistOperation(o);return;
            }
            if(o.Action=="climate_patch"){TickClimateWrite(o);return;}
            if(o.State=="waiting_reload")
            {
                if(Now-o.MaintenanceStarted>60000)throw new HostError("WORLD_RELOAD_TIMEOUT","Maintenance reload exceeded 60 seconds; inspect record");
                if(GameManager.Project==null)return;
                if(Sub<SubsystemPlayers>().PlayersData.SingleOrDefault(p=>p.PlayerIndex==(int)o.Identity["player_index"])?.ComponentPlayer==null)return;
                if(GameManager.IsNetworkProject||NetworkManager.IsClientRunning||NetworkManager.ServerSessions.Any()||Players().Count!=1)throw new HostError("MULTIPLAYER_DISABLED","Maintenance requires isolated local player");
                NetworkManager.Stop();
                var rebound=o.Identity.DeepClone().AsObject();rebound["session"]=session;Identity(rebound,true,false);
                o.Identity=rebound;o.After=CaptureOperation(o);VerifyOperationReadback(o);o.After["new_session"]=session;o.State="persisting_result";PersistOperation(o);return;
            }
            if(o.State=="persisting_result"){o.State=o.Error==null?"completed":"failed";PersistOperation(o);operationActive=null;return;}
            Identity(o.Identity,true,o.Backup);
            if(active!=null)throw new HostError("WORLD_BUSY","Construction started during persistence");
            if(!OperationMatches(o))throw new HostError("STALE_PLAN","Affected fields or guards changed during durable intent persistence");
            if(o.LateBind&&o.RestoreOf==null)
            {
                o.Before=CaptureOperation(o);
                o.State="executing";Save(Path.Combine(OperationDir,o.Id+".json"),OperationRecord(o)); // Small same-frame durable snapshot: no game update occurs between capture and effect.
            }
            o.State="executing";interactionOperationId=o.Id;
            var expectedInventory=o.RestoreOf==null?o.Planned:o.After?.DeepClone();
            try
            {
                ApplyOperation(o);if(o.State is not ("waiting_reload" or "waiting_native"))o.After=CaptureOperation(o);
                if(o.Action=="interact_block"&&o.State!="waiting_native"){o.State="waiting_interaction_readback";o.InteractionReadbackFrame=Time.FrameIndex+2;}
                if(o.Action is "inventory_edit" or "inventory_transfer"&&!JsonNode.DeepEquals(o.After,expectedInventory))throw new HostError("READBACK_MISMATCH","Inventory did not retain requested state");
                if(o.State is not ("waiting_reload" or "waiting_native"))VerifyOperationReadback(o,expectedInventory);
            }
            finally {interactionOperationId=null;}
            if(o.State is "waiting_reload" or "waiting_native" or "waiting_interaction_readback"){PersistOperation(o);return;}
            o.State="persisting_result";PersistOperation(o);
        }
        catch(Exception e)
        {
            o.Error=new JsonObject {["code"]=e is HostError h?h.Code:"OPERATION_ERROR",["message"]=e.Message};
            if(o.Persistence?.IsFaulted==true)o.AuditError="AUDIT_WRITE_FAILED: "+o.Persistence.Exception.GetBaseException().Message;
            if(o.State=="executing")try{o.After=CaptureOperation(o);}catch{}
            o.State="failed";try{var record=OperationRecord(o);o.Persistence=Task.Run(()=>Save(Path.Combine(OperationDir,o.Id+".json"),record));}catch{}operationActive=null;
        }
    }
}
