using System.Text.Json.Nodes;
using Engine;
using HarmonyLib;
namespace Game;
public static partial class AgentHost
{
    static readonly HashSet<string> EventKinds=["block_click","longpress_start","longpress_end","item_use","eat","wear","capture"];
    static bool OperationCapabilityAllowed(string action)=>settings["target"]["test_only"]?.GetValue<bool>()==true&&((string)settings["target"]["name"]).StartsWith("SC MCP LAB")||settings["capabilities"] is JsonArray entries&&entries.Any(e=>(string)e["action"]==action&&(string)e["availability"]=="lab_verified");
    sealed class EventSubscription {public string Client;public JsonObject Identity;public HashSet<string> Kinds;public long Cursor;}
    static readonly Dictionary<string,EventSubscription> subscriptions=[];
    sealed class HistoryRequest {public string Client;public JsonObject Identity;public Task<JsonObject> Work;public long Created=Now;}
    static readonly Dictionary<string,HistoryRequest> historyRequests=[];
    static readonly Queue<JsonObject> eventBuffer=[];
    static readonly Queue<JsonObject> eventPending=[];
    static long eventSequence;
    static Task eventWriter;
    static string eventLogError,interactionOperationId;
    static string interactionSource="unknown";
    sealed class InteractionScope {public string Source;public int Depth;}
    static int nativeInteractionDepth;
    static bool pendingInteractionExecuting;
    static readonly Dictionary<int,(int Frame,Point3 Point)> nativeInputTargets=[];
    static void TrackNativeInput(ComponentPlayer p,Ray3 ray)
    {var hit=p.ComponentMiner.Raycast<TerrainRaycastResult>(ray,RaycastMode.Interaction,true,false,false);if(hit.HasValue)nativeInputTargets[p.PlayerData.PlayerIndex]=(Time.FrameIndex,hit.Value.CellFace.Point);}
    static bool ConfirmedNativeInput(ComponentMiner miner,Point3 point)=>miner.ComponentPlayer!=null&&nativeInputTargets.TryGetValue(miner.ComponentPlayer.PlayerData.PlayerIndex,out var input)&&Time.FrameIndex-input.Frame<=1&&input.Point==point;
    static readonly HashSet<int> aimingPlayers=[];
    public static void CaptureEvent()=>EmitEvent("capture",null,"success");
    public static void PlayerInputInteraction(ComponentPlayer p)
    {
        if(!EventTarget()||!p.ComponentInput.PlayerInput.Interact.HasValue)return;
        TrackNativeInput(p,p.ComponentInput.PlayerInput.Interact.Value);

    }
    public static void PlayerInputAim(ComponentPlayer p,bool aiming)
    {
        if(!EventTarget())return;bool emit=aiming?aimingPlayers.Add(p.PlayerData.PlayerIndex):aimingPlayers.Remove(p.PlayerData.PlayerIndex);if(!emit)return;
        if(aiming&&p.ComponentInput.PlayerInput.Aim.HasValue)TrackNativeInput(p,p.ComponentInput.PlayerInput.Aim.Value);
        string old=interactionSource;interactionSource="user";try{EmitEvent(aiming?"longpress_start":"longpress_end",p,"unknown",value:p.ComponentMiner.ActiveBlockValue);}finally{interactionSource=old;}
    }
    static bool EventTarget()
    {
        if(GameManager.Project==null||settings==null)return false;
        var w=World();if((string)w["directory"]!=(string)settings["target"]["directory"]||(string)w["name"]!=(string)settings["target"]["name"]||(string)w["network"]!="singleplayer"||Players().Count!=1)return false;
        var marker=Storage.CombinePaths((string)w["directory"],"scagent-world-id.txt");return Storage.FileExists(marker)&&Storage.ReadAllText(marker)==(string)settings["target"]["world_token"];
    }
    static void EmitEvent(string kind,ComponentPlayer player,string outcome,JsonObject target=null,int? value=null)
    {
        try
        {
            if(!EventTarget()||!EventKinds.Contains(kind))return;
            var e=new JsonObject { ["sequence"]=++eventSequence,["time_utc_ms"]=Now,["boot"]=Boot,["session"]=session,
                ["world_token"]=settings["target"]["world_token"].DeepClone(),["directory"]=World()["directory"].DeepClone(),["name"]=World()["name"].DeepClone(),
                ["kind"]=kind,["outcome"]=outcome,["player_index"]=player?.PlayerData.PlayerIndex,["player_name"]=player?.PlayerData.Name,
                ["source"]=interactionOperationId!=null?"agent":interactionSource,["operation_id"]=interactionOperationId,["target"]=target,["value"]=value };
            eventBuffer.Enqueue(e);while(eventBuffer.Count>4096)eventBuffer.Dequeue();
            if(eventPending.Count>=4096){eventLogError="AUDIT_BACKLOG_OVERFLOW";return;}eventPending.Enqueue(e.DeepClone().AsObject());
        }
        catch(Exception error){eventLogError="EVENT_CAPTURE_ERROR: "+error.Message;}
    }
    static void ResetInteractionSession(){subscriptions.Clear();eventBuffer.Clear();aimingPlayers.Clear();nativeInputTargets.Clear();playerOverrideEnabled=false;}
    static void TickInteractionEvents()
    {
        TickInteractionLab();
        if(eventWriter is {IsCompleted:false})return;
        if(eventWriter?.IsFaulted==true)eventLogError="AUDIT_WRITE_FAILED: "+eventWriter.Exception.GetBaseException().Message;
        if(eventPending.Count==0){eventWriter=null;return;}
        var batch=new List<string>();for(int i=0;i<64&&eventPending.Count>0;i++)batch.Add(eventPending.Dequeue().ToJsonString(Json));
        var directory=Path.Combine(root,"events");var file=Path.Combine(directory,Boot+"-"+session+".jsonl");
        bool injectFailure=labEventLogFail&&settings["target"]["test_only"]?.GetValue<bool>()==true;labEventLogFail=false;
        eventWriter=Task.Run(()=>
        {
            if(injectFailure)throw new IOException("LAB injected event audit write failure");
            Directory.CreateDirectory(directory);
            long incoming=batch.Sum(line=>(long)System.Text.Encoding.UTF8.GetByteCount(line)+1);
            if(File.Exists(file)&&new FileInfo(file).Length+incoming>16*1024*1024)
            {for(int i=7;i>=1;i--){var old=file+"."+i;if(File.Exists(old)){if(i==7)File.Delete(old);else File.Move(old,file+"."+(i+1),true);}}File.Move(file,file+".1",true);}
            using(var stream=new FileStream(file,FileMode.Append,FileAccess.Write,FileShare.Read))
            {foreach(var line in batch){var bytes=System.Text.Encoding.UTF8.GetBytes(line+"\n");stream.Write(bytes);}stream.Flush(true);}
            foreach(var old in Directory.EnumerateFiles(directory,"*.jsonl*").Where(p=>System.Text.RegularExpressions.Regex.IsMatch(Path.GetFileName(p),"^[0-9a-f]{32}-[0-9a-f]{32}\\.jsonl(?:\\.[1-7])?$" )).OrderByDescending(File.GetLastWriteTimeUtc).Skip(8))File.Delete(old);
        });
    }
    static JsonNode InteractionEvents(string op,JsonObject args,JsonObject identity)
    {
        Identity(identity,true,false);string client=GuidText(args,"client_id");
        if(!OperationCapabilityAllowed(op))throw new HostError("CAPABILITY_DISABLED","Unverified event path is closed outside registered LAB targets");
        if(op=="event_subscribe")
        {
            Closed(args,"client_id","kinds");
            if(subscriptions.Count>=64)throw new HostError("SUBSCRIPTION_CAPACITY","At most 64 subscriptions per host");
            if(args["kinds"] is not JsonArray kinds||kinds.Count<1||kinds.Count>EventKinds.Count)throw new HostError("INVALID_ARGUMENT","Nonempty event kinds required");
            var selected=kinds.Select(k=>k.GetValue<string>()).ToHashSet();if(!selected.IsSubsetOf(EventKinds))throw new HostError("UNREGISTERED_COMMAND","Unknown event kind");
            var id=Guid.NewGuid().ToString("N");subscriptions[id]=new EventSubscription {Client=client,Identity=identity.DeepClone().AsObject(),Kinds=selected,Cursor=eventSequence};
            return new JsonObject {["subscription_id"]=id,["cursor"]=eventSequence,["session"]=session,["audit_error"]=eventLogError};
        }
        if(op=="event_history")
        {
            Closed(args,"client_id","after","limit","boot","history_id");
            foreach(var old in historyRequests.Where(h=>Now-h.Value.Created>30000&&h.Value.Work.IsCompleted).ToArray())historyRequests.Remove(old.Key);
            if(args["history_id"]!=null)
            {
                string id=GuidText(args,"history_id");if(!historyRequests.TryGetValue(id,out var h))throw new HostError("SNAPSHOT_EXPIRED","History request expired");
                if(h.Client!=client||!JsonNode.DeepEquals(h.Identity,identity))throw new HostError("CURSOR_MISMATCH","History request belongs to another client/session");
                if(!h.Work.IsCompleted)return new JsonObject {["state"]="loading",["history_id"]=id};var result=h.Work.GetAwaiter().GetResult().DeepClone();historyRequests.Remove(id);return result;
            }
            if(historyRequests.Count>=16||historyRequests.Values.Count(h=>h.Client==client)>=4)throw new HostError("OBSERVATION_CAPACITY","History worker capacity reached");
            int limit=Integer(args,"limit",1,64);double n=Number(args,"after",0,9007199254740991);if(n!=Math.Floor(n))throw new HostError("INVALID_ARGUMENT","Event sequence must be integer");long after=(long)n;string requestedBoot=args["boot"]!=null?GuidText(args,"boot"):Boot;
            string directory=Path.Combine(root,"events"),token=(string)identity["world_token"];int playerIndex=(int)identity["player_index"];string logError=eventLogError;
            var request=new HistoryRequest {Client=client,Identity=identity.DeepClone().AsObject(),Work=Task.Run(()=>ReadEventHistory(directory,requestedBoot,token,playerIndex,after,limit,logError))};
            string historyId=Guid.NewGuid().ToString("N");historyRequests.Add(historyId,request);return new JsonObject {["state"]="loading",["history_id"]=historyId};
        }
        Closed(args,"client_id","subscription_id","limit");string subId=GuidText(args,"subscription_id");
        if(!subscriptions.TryGetValue(subId,out var sub))throw new HostError("SUBSCRIPTION_EXPIRED","World reload/restart invalidates subscriptions");
        if(sub.Client!=client||!JsonNode.DeepEquals(sub.Identity,identity))throw new HostError("CURSOR_MISMATCH","Subscription belongs to another client/target");
        if(op=="event_unsubscribe"){subscriptions.Remove(subId);return new JsonObject {["unsubscribed"]=true};}
        int page=Integer(args,"limit",1,64);var events=new JsonArray();long earliest=eventBuffer.Count>0?(long)eventBuffer.Peek()["sequence"]:eventSequence+1;
        bool gap=sub.Cursor<earliest-1;if(gap)sub.Cursor=earliest-1;
        foreach(var e in eventBuffer)
        {
            long seq=(long)e["sequence"];if(seq<=sub.Cursor)continue;sub.Cursor=seq;
            if(sub.Kinds.Contains((string)e["kind"])&&e["player_index"]!=null&&(int)e["player_index"]!=(int)identity["player_index"])continue;
            if(sub.Kinds.Contains((string)e["kind"])){events.Add(e.DeepClone());if(events.Count==page)break;}
        }
        return new JsonObject {["events"]=events,["cursor"]=sub.Cursor,["gap"]=gap,["earliest_available"]=earliest,["audit_error"]=eventLogError};
    }
    static JsonObject ReadEventHistory(string directory,string boot,string token,int player,long after,int limit,string error)
    {
        var rows=new List<JsonObject>();int invalid=0;long largest=0,earliest=long.MaxValue;
        if(Directory.Exists(directory))foreach(var path in Directory.EnumerateFiles(directory,boot+"-*.jsonl*").OrderBy(p=>File.GetCreationTimeUtc(p)).TakeLast(8))
        {
            using var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete);using var reader=new StreamReader(stream);
            while(reader.ReadLine() is string line)
            {
                JsonObject e;try{e=JsonNode.Parse(line).AsObject();}catch{invalid++;continue;}
                if((string)e["world_token"]!=token||(string)e["boot"]!=boot||e["player_index"]!=null&&(int)e["player_index"]!=player)continue;
                earliest=Math.Min(earliest,(long)e["sequence"]);if((long)e["sequence"]<=after)continue;
                long seq=(long)e["sequence"];
                if(rows.Count<limit){rows.Add(e);largest=Math.Max(largest,seq);}
                else if(seq<largest){int at=rows.FindIndex(r=>(long)r["sequence"]==largest);rows[at]=e;largest=rows.Max(r=>(long)r["sequence"]);}
            }
        }
        var selected=rows.OrderBy(e=>(long)e["sequence"]).Take(limit).ToArray();
        return new JsonObject {["state"]="completed",["events"]=new JsonArray(selected.Select(e=>(JsonNode)e).ToArray()),["next_after"]=selected.Length>0?(long)selected[^1]["sequence"]:after,["historical"]=true,["boot"]=boot,["invalid_lines"]=invalid,["audit_error"]=error,["earliest_available"]=earliest==long.MaxValue?null:earliest,["retention_gap"]=earliest==long.MaxValue||after<earliest-1||invalid>0,["coverage"]="retained audit files only; eight files total",
            ["available_boots"]=Directory.Exists(directory)?new JsonArray(Directory.EnumerateFiles(directory,"*.jsonl*").Select(p=>Path.GetFileName(p).Split('-')[0]).Distinct().Select(p=>(JsonNode)JsonValue.Create(p)).ToArray()):new JsonArray(),["automatic_actions"]=false};
    }
    static void InstallInteractionEvents()
    {
        var harmony=new Harmony("local.sc.agentbridge.events1932");
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"Save"),prefix:new HarmonyMethod(typeof(AgentHost),nameof(OverrideMinerSave)),finalizer:new HarmonyMethod(typeof(AgentHost),nameof(OverrideMinerSaved)));
        harmony.Patch(AccessTools.Method(typeof(ComponentPlayer),"DealWithPlayerInteract"),prefix:new HarmonyMethod(typeof(AgentHost),nameof(UserInteractionStart)),finalizer:new HarmonyMethod(typeof(AgentHost),nameof(UserInteractionEnd)));
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"Interact",[typeof(TerrainRaycastResult)]),prefix:new HarmonyMethod(typeof(AgentHost),nameof(InteractAttempt)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(InteractResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"DoInteractTerrain"),prefix:new HarmonyMethod(typeof(AgentHost),nameof(NativeInteractStart)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(NativeInteractResult)),finalizer:new HarmonyMethod(typeof(AgentHost),nameof(NativeInteractEnd)));
        foreach(var type in typeof(SubsystemBlockBehavior).Assembly.GetTypes().Where(t=>t.IsSubclassOf(typeof(SubsystemBlockBehavior))))
        {var method=AccessTools.DeclaredMethod(type,"OnInteract",[typeof(TerrainRaycastResult),typeof(ComponentMiner)]);if(method!=null&&!method.IsAbstract)harmony.Patch(method,prefix:new HarmonyMethod(typeof(AgentHost),nameof(BehaviorInteractStart)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(BehaviorInteractResult)),finalizer:new HarmonyMethod(typeof(AgentHost),nameof(NativeInteractEnd)));}
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"ExecuteInteract"),prefix:new HarmonyMethod(typeof(AgentHost),nameof(PendingInteractionStart)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(PendingInteractionResult)),finalizer:new HarmonyMethod(typeof(AgentHost),nameof(PendingInteractionEnd)));
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"Use",[typeof(Ray3)]),prefix:new HarmonyMethod(typeof(AgentHost),nameof(UseAttempt)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(UseResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"ExecuteUse"),prefix:new HarmonyMethod(typeof(AgentHost),nameof(PendingUseBefore)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(PendingUseResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentVitalStats),"Eat",[typeof(int)]),prefix:new HarmonyMethod(typeof(AgentHost),nameof(EatAttempt)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(EatResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentMiner),"Aim",[typeof(Ray3),typeof(AimState)]),postfix:new HarmonyMethod(typeof(AgentHost),nameof(AimResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentClothing),"SetClothes",[typeof(ClothingSlot),typeof(IEnumerable<int>)]),prefix:new HarmonyMethod(typeof(AgentHost),nameof(WearBefore)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(WearResult)));
        harmony.Patch(AccessTools.Method(typeof(ComponentClothing),"ProcessSlotItems",[typeof(int),typeof(int),typeof(int),typeof(int),typeof(int).MakeByRefType(),typeof(int).MakeByRefType()]),prefix:new HarmonyMethod(typeof(AgentHost),nameof(WearProcessBefore)),postfix:new HarmonyMethod(typeof(AgentHost),nameof(WearProcessResult)));
    }
    static JsonObject RayTarget(TerrainRaycastResult r)=>new() {["position"]=new JsonArray(r.CellFace.X,r.CellFace.Y,r.CellFace.Z),["face"]=r.CellFace.Face,["value"]=r.Value,["distance"]=r.Distance};
    static void UserInteractionStart(PlayerInput playerInput,out string __state){__state=interactionSource;if(playerInput.Interact.HasValue)interactionSource="user";}
    static Exception UserInteractionEnd(Exception __exception,string __state){interactionSource=__state;return __exception;}
    static void InteractAttempt(ComponentMiner __instance,TerrainRaycastResult raycastResult){if(__instance.RequiresPending(ComponentMiner.PendingAction.Interact))EmitEvent("block_click",__instance.ComponentPlayer,"attempt",RayTarget(raycastResult),__instance.ActiveBlockValue);}
    static void InteractResult(ComponentMiner __instance,TerrainRaycastResult raycastResult,bool __result){if(__instance.RequiresPending(ComponentMiner.PendingAction.Interact))EmitEvent("block_click",__instance.ComponentPlayer,__instance.AnyIsPending?"unknown":__result?"success":"failed",RayTarget(raycastResult),__instance.ActiveBlockValue);}
    static void NativeInteractStart(ComponentMiner __instance,TerrainRaycastResult raycastResult,out InteractionScope __state)
    {__state=new InteractionScope {Source=interactionSource,Depth=nativeInteractionDepth};nativeInteractionDepth++;if(interactionOperationId==null&&ConfirmedNativeInput(__instance,raycastResult.CellFace.Point))interactionSource="user";if(!pendingInteractionExecuting)EmitEvent("block_click",__instance.ComponentPlayer,"attempt",RayTarget(raycastResult),__instance.ActiveBlockValue);}
    static void NativeInteractResult(ComponentMiner __instance,TerrainRaycastResult raycastResult,bool __result)
    {if(!pendingInteractionExecuting)EmitEvent("block_click",__instance.ComponentPlayer,__result?"success":"failed",RayTarget(raycastResult),__instance.ActiveBlockValue);}
    static Exception NativeInteractEnd(Exception __exception,InteractionScope __state){if(__state!=null){interactionSource=__state.Source;nativeInteractionDepth=__state.Depth;}return __exception;}
    static void BehaviorInteractStart(TerrainRaycastResult __0,ComponentMiner __1,out InteractionScope __state)
    {__state=new InteractionScope {Source=interactionSource,Depth=nativeInteractionDepth};if(nativeInteractionDepth==0&&!pendingInteractionExecuting){if(interactionOperationId==null&&ConfirmedNativeInput(__1,__0.CellFace.Point))interactionSource="user";EmitEvent("block_click",__1.ComponentPlayer,"attempt",RayTarget(__0),__1.ActiveBlockValue);}nativeInteractionDepth++;}
    static void BehaviorInteractResult(TerrainRaycastResult __0,ComponentMiner __1,bool __result,InteractionScope __state)
    {if(__state.Depth==0&&!pendingInteractionExecuting)EmitEvent("block_click",__1.ComponentPlayer,__result?"success":"failed",RayTarget(__0),__1.ActiveBlockValue);}
    static void UseAttempt(ComponentMiner __instance,out int __state){__state=__instance.ActiveBlockValue;EmitEvent("item_use",__instance.ComponentPlayer,"attempt",value:__state);}
    static void UseResult(ComponentMiner __instance,bool __result,int __state)=>EmitEvent("item_use",__instance.ComponentPlayer,__instance.AnyIsPending?"unknown":__result?"success":"failed",value:__state);
    static void PendingUseBefore(ComponentMiner __instance,out int __state)=>__state=__instance.ActiveBlockValue;
    static void PendingUseResult(ComponentMiner __instance,bool __result,int __state)=>EmitEvent("item_use",__instance.ComponentPlayer,__result?"success":"failed",new JsonObject {["stage"]="native_pending_completion"},__state);
    static void PendingInteractionStart(ComponentMiner __instance,out string __state)
    {__state=interactionOperationId;pendingInteractionExecuting=true;var o=operations.Values.FirstOrDefault(o=>o.PendingMiner==__instance);if(o!=null)interactionOperationId=o.Id;}
    static void PendingInteractionResult(ComponentMiner __instance,bool __result)
    {
        var o=operations.Values.FirstOrDefault(o=>o.PendingMiner==__instance);if(o==null)return;
        o.InteractionResult=__result;o.PendingMiner=null;EmitEvent("block_click",__instance.ComponentPlayer,__result?"success":"failed",new JsonObject {["position"]=o.Arguments["position"].DeepClone(),["stage"]="native_pending_completion"});
        if(o.State=="failed"){try{o.After=CaptureInteract(o,false);o.Steps.Add(new JsonObject {["state"]="late_native_completion",["accepted"]=__result});PersistOperation(o);}catch{}}
    }
    static Exception PendingInteractionEnd(Exception __exception,string __state){interactionOperationId=__state;pendingInteractionExecuting=false;return __exception;}
    static void EatAttempt(ComponentVitalStats __instance,int value)=>EmitEvent("eat",__instance.Entity.FindComponent<ComponentPlayer>(),"attempt",value:value);
    static void EatResult(ComponentVitalStats __instance,int value,bool __result)=>EmitEvent("eat",__instance.Entity.FindComponent<ComponentPlayer>(),__result?"success":"failed",value:value);
    static void AimResult(ComponentMiner __instance,AimState state)
    {
        var p=__instance.ComponentPlayer;if(p==null)return;int index=p.PlayerData.PlayerIndex;
        if(state==AimState.InProgress&&aimingPlayers.Add(index))EmitEvent("longpress_start",p,"unknown",value:__instance.ActiveBlockValue);
        else if(state!=AimState.InProgress&&aimingPlayers.Remove(index))EmitEvent("longpress_end",p,state==AimState.Cancelled?"cancelled":"unknown",value:__instance.ActiveBlockValue);
    }
    static void WearBefore(ComponentClothing __instance,ClothingSlot slot,out int[] __state)=>__state=__instance.GetClothes(slot).ToArray();
    static void WearProcessBefore(ComponentClothing __instance,int value,out int[] __state)
    {__state=null;if(!BlocksManager.Blocks[Terrain.ExtractContents(value)].CanWear(value))return;__state=__instance.m_clothes.Values.SelectMany(v=>v).ToArray();EmitEvent("wear",__instance.Entity.FindComponent<ComponentPlayer>(),"attempt",value:value);}
    static void WearProcessResult(ComponentClothing __instance,int value,int[] __state)
    {if(__state!=null)EmitEvent("wear",__instance.Entity.FindComponent<ComponentPlayer>(),__instance.m_clothes.Values.SelectMany(v=>v).SequenceEqual(__state)?"failed":"success",new JsonObject {["stage"]="native_clothing_process"},value);}
    static void WearResult(ComponentClothing __instance,ClothingSlot slot,int[] __state)
    {var values=__instance.GetClothes(slot).ToArray();if(!values.SequenceEqual(__state))EmitEvent("wear",__instance.Entity.FindComponent<ComponentPlayer>(),"unknown",new JsonObject {["slot"]=slot.Name,["slot_id"]=slot.StableId,["values"]=new JsonArray(values.Select(v=>(JsonNode)JsonValue.Create(v)).ToArray()),["stage"]="native_clothing_state_change"});}
}
