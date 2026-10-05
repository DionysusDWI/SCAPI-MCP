using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    static JsonObject playerOverrideFields;
    static JsonObject playerOverrideIdentity;
    static bool playerOverrideEnabled;
    static JsonObject playerOverrideOriginal;
    static string playerOverrideError;
    static bool playerOverrideApplied;
    static string OverridePath(JsonObject identity)=>Path.Combine(root,"player-overrides",(string)identity["world_token"]+"-"+(int)identity["player_index"]+".json");
    static void DescribeOverride(Operation o)
    {
        Closed(o.Arguments,"mode","fields");string mode=RequiredText(o.Arguments,"mode");if(mode is not ("save" or "enable" or "disable"))throw new HostError("INVALID_ARGUMENT","Override mode must be save/enable/disable");
        if(mode=="save")
        {if(o.Arguments["fields"] is not JsonObject fields||fields.Count==0)throw new HostError("INVALID_ARGUMENT","Override fields required");Closed(fields,"walk_speed","attack_power","attack_resilience");foreach(var p in fields)Number(fields,p.Key,p.Key=="attack_resilience"?.001:0,p.Key=="walk_speed"?64:10000);}
        else if(o.Arguments.ContainsKey("fields"))throw new HostError("INVALID_ARGUMENT","Fields only accepted when saving");
        o.Risk="state_change";o.Recovery="none";o.Backup=false;
    }
    static JsonObject CaptureOverride(Operation o)
    {
        var path=OverridePath(o.Identity);JsonNode saved=File.Exists(path)?JsonNode.Parse(File.ReadAllText(path)):null;
        return new JsonObject {["saved"]=saved,["enabled"]=playerOverrideEnabled,["world_token"]=o.Identity["world_token"].DeepClone(),["actual"]=playerOverrideFields==null?null:OverrideActual(OperationPlayer(o)),["error"]=playerOverrideError};
    }
    static void ApplyOverride(Operation o)
    {
        var mode=(string)o.Arguments["mode"];
        if(mode=="save")
        {
            ReleasePlayerOverride();
            var saved=new JsonObject {["world_token"]=o.Identity["world_token"].DeepClone(),["player_index"]=o.Identity["player_index"].DeepClone(),["player_name"]=o.Identity["player_name"].DeepClone(),["fields"]=o.Arguments["fields"].DeepClone()};Save(OverridePath(o.Identity),saved);
            playerOverrideEnabled=false;
        }
        else if(mode=="enable")
        {
            var path=OverridePath(o.Identity);if(!File.Exists(path))throw new HostError("NO_CONFIGURATION","Save override first");var saved=JsonNode.Parse(File.ReadAllText(path));
            foreach(var key in new[]{"world_token","player_name"})if((string)saved[key]!=(string)o.Identity[key])throw new HostError("IDENTITY_MISMATCH","Override target changed");
            if((int)saved["player_index"]!=(int)o.Identity["player_index"])throw new HostError("IDENTITY_MISMATCH","Override selected player changed");
            ReleasePlayerOverride();playerOverrideFields=saved["fields"].DeepClone().AsObject();playerOverrideIdentity=o.Identity.DeepClone().AsObject();playerOverrideOriginal=OverrideActual(OperationPlayer(o));playerOverrideApplied=false;playerOverrideError=null;playerOverrideEnabled=true;TickPlayerOverride();
        }
        else ReleasePlayerOverride();
    }
    static float OverrideValue(ComponentPlayer p,string key)=>key switch {"walk_speed"=>p.ComponentLocomotion.WalkSpeed,"attack_power"=>p.ComponentMiner.AttackPower,"attack_resilience"=>p.ComponentHealth.AttackResilience,_=>throw new HostError("UNREGISTERED_COMMAND","Unknown override field")};
    static JsonObject OverrideActual(ComponentPlayer p){var result=new JsonObject();foreach(var pair in playerOverrideFields)result[pair.Key]=OverrideValue(p,pair.Key);return result;}
    static void SetOverrideValue(ComponentPlayer p,string key,float n)
    {switch(key){case "walk_speed":p.ComponentLocomotion.WalkSpeed=n;break;case "attack_power":p.ComponentMiner.AttackPower=n;break;case "attack_resilience":if(!float.IsFinite(p.ComponentHealth.AttackResilienceFactor)||p.ComponentHealth.AttackResilienceFactor<=0)throw new HostError("UNSUPPORTED_RULE","Native resilience factor does not support target");p.ComponentHealth.AttackResilience=n/p.ComponentHealth.AttackResilienceFactor;break;}}
    static bool EqualOverride(float actual,float target)=>Math.Abs(actual-target)<=Math.Max(.00001f,Math.Abs(target)*.000001f);
    static void ReleasePlayerOverride()
    {
        if(playerOverrideEnabled&&playerOverrideApplied&&GameManager.Project!=null)
        {
            try{Identity(playerOverrideIdentity,true,false);var p=Sub<SubsystemPlayers>().PlayersData.Single(x=>x.PlayerIndex==(int)playerOverrideIdentity["player_index"]).ComponentPlayer;
                foreach(var pair in playerOverrideFields){float target=System.Text.Json.JsonSerializer.Deserialize<float>(pair.Value.ToJsonString());if(EqualOverride(OverrideValue(p,pair.Key),target))SetOverrideValue(p,pair.Key,System.Text.Json.JsonSerializer.Deserialize<float>(playerOverrideOriginal[pair.Key].ToJsonString()));else playerOverrideError="OVERRIDE_CONFLICT: externally changed "+pair.Key;}}
            catch(Exception error){playerOverrideError="OVERRIDE_RELEASE_FAILED: "+error.Message;}
        }
        playerOverrideEnabled=false;playerOverrideApplied=false;
    }
    static void TickPlayerOverride()
    {
        if(!playerOverrideEnabled)return;
        try
        {
            Identity(playerOverrideIdentity,true,false);var p=Sub<SubsystemPlayers>().PlayersData.Single(p=>p.PlayerIndex==(int)playerOverrideIdentity["player_index"]).ComponentPlayer;if(p==null)return;
            foreach(var v in playerOverrideFields){float n=System.Text.Json.JsonSerializer.Deserialize<float>(v.Value.ToJsonString());if(playerOverrideApplied&&!EqualOverride(OverrideValue(p,v.Key),n)){playerOverrideError="OVERRIDE_CONFLICT: another update changed "+v.Key;ReleasePlayerOverride();return;}SetOverrideValue(p,v.Key,n);if(!EqualOverride(OverrideValue(p,v.Key),n))throw new HostError("OVERRIDE_INEFFECTIVE","Requested override did not take effect");}playerOverrideApplied=true;
        }
        catch(Exception error){playerOverrideError="OVERRIDE_DISABLED: "+error.Message;ReleasePlayerOverride();}
    }
    static void OverrideMinerSave(ComponentMiner __instance,out float? __state)
    {__state=null;if(playerOverrideEnabled&&playerOverrideApplied&&playerOverrideFields.ContainsKey("attack_power")&&__instance.ComponentPlayer?.PlayerData.PlayerIndex==(int)playerOverrideIdentity["player_index"]){__state=__instance.AttackPower;__instance.AttackPower=System.Text.Json.JsonSerializer.Deserialize<float>(playerOverrideOriginal["attack_power"].ToJsonString());}}
    static Exception OverrideMinerSaved(ComponentMiner __instance,float? __state,Exception __exception){if(__state.HasValue)__instance.AttackPower=__state.Value;return __exception;}
}
