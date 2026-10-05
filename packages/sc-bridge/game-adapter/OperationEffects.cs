using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    static ComponentPlayer OperationPlayer(Operation o)
    {var p=Sub<SubsystemPlayers>().PlayersData.Single(p=>p.PlayerIndex==(int)o.Identity["player_index"]).ComponentPlayer;return p??throw new HostError("PLAYER_NOT_READY","Selected player not spawned");}
    static void DescribeOperation(Operation o)
    {
        if(o.Action=="creature_patch"){DescribeCreature(o);return;}
        if(o.Action=="climate_patch"){DescribeClimate(o);return;}
        if(o.Action=="environment_patch"){DescribeEnvironment(o);return;}
        if(o.Action=="player_override"){DescribeOverride(o);return;}
        if(o.Action is "inventory_edit" or "inventory_transfer"){DescribeInventory(o);return;}
        if(o.Action=="interact_block"){DescribeInteract(o);return;}
        if(o.Action!="player_patch")throw new HostError("UNREGISTERED_COMMAND","Operation action is not implemented and accepted");
        Closed(o.Arguments,"level","health","food","stamina","sleep","wetness","temperature");
        if(o.Arguments.Count==0)throw new HostError("INVALID_ARGUMENT","At least one player field required");
        foreach(var p in o.Arguments)Number(o.Arguments,p.Key,p.Key=="health"?.001:p.Key=="level"?1:0,p.Key=="level"?100:p.Key=="temperature"?24:1);
        if(OperationPlayer(o).ComponentHealth.Health<=0)throw new HostError("PLAYER_DEAD","Dead player cannot be patched");
        if(Sub<SubsystemGameInfo>().WorldSettings.GameMode==GameMode.Creative&&o.Arguments.Any(k=>k.Key is "food" or "stamina" or "sleep" or "wetness" or "temperature"))throw new HostError("UNSUPPORTED_MODE","Creative mode does not retain these physiology settings");
        o.Risk="state_change";o.Recovery="direct_fields";o.Backup=false;
        o.LateBind=o.Arguments.Any(k=>DynamicPlayerFields.Contains(k.Key));o.Guards=PlayerGuards(o);
    }
    static readonly HashSet<string> DynamicPlayerFields=["food","stamina","sleep","wetness","temperature"];
    static JsonObject PlayerGuards(Operation o)=>new() {["player_entity_id"]=OperationPlayer(o).Entity.Id,["game_mode"]=Sub<SubsystemGameInfo>().WorldSettings.GameMode.ToString(),["alive"]=OperationPlayer(o).ComponentHealth.Health>0};
    static bool OperationMatches(Operation o)
    {
        var current=CaptureOperation(o);
        if(o.LateBind&&o.RestoreOf==null)
        {
            if(!JsonNode.DeepEquals(PlayerGuards(o),o.Guards))return false;
            foreach(var key in DynamicPlayerFields){current.Remove(key);}
            var old=o.Before.DeepClone().AsObject();foreach(var key in DynamicPlayerFields)old.Remove(key);
            return JsonNode.DeepEquals(current,old);
        }
        return JsonNode.DeepEquals(current,o.Before);
    }
    static JsonObject CaptureOperation(Operation o)
    {
        if(o.Action=="creature_patch")return CaptureCreature(o);
        if(o.Action=="climate_patch")return o.Arguments.DeepClone().AsObject();
        if(o.Action=="environment_patch")return CaptureEnvironment(o);
        if(o.Action=="player_override")return CaptureOverride(o);
        if(o.Action is "inventory_edit" or "inventory_transfer")return CaptureInventory(o);
        if(o.Action=="interact_block")return CaptureInteract(o,o.RestoreOf==null&&o.State is "ready" or "persisting_intent");
        var p=OperationPlayer(o);var result=new JsonObject();
        foreach(var field in o.Arguments.Select(k=>k.Key))result[field]=field switch {
            "level"=>p.PlayerData.Level,"health"=>p.ComponentHealth.Health,"food"=>p.ComponentVitalStats.Food,
            "stamina"=>p.ComponentVitalStats.Stamina,"sleep"=>p.ComponentVitalStats.Sleep,"wetness"=>p.ComponentVitalStats.Wetness,
            "temperature"=>p.ComponentVitalStats.Temperature,_=>throw new HostError("UNREGISTERED_COMMAND","Unknown player field")};return result;
    }
    static void ApplyOperation(Operation o)
    {
        if(o.Action=="creature_patch"){ApplyCreature(o);return;}
        if(o.Action=="environment_patch"){ApplyEnvironment(o);return;}
        if(o.Action=="player_override"){ApplyOverride(o);return;}
        if(o.Action is "inventory_edit" or "inventory_transfer"){ApplyInventory(o);return;}
        if(o.Action=="interact_block"){ApplyInteract(o);return;}
        var p=OperationPlayer(o);if(p.ComponentHealth.Health<=0)throw new HostError("PLAYER_DEAD","Player died after preflight");
        var desired=o.RestoreOf==null?o.Arguments:o.After;
        foreach(var field in desired)
        {
            float n=System.Text.Json.JsonSerializer.Deserialize<float>(field.Value.ToJsonString());
            switch(field.Key){case "level":p.PlayerData.Level=n;break;case "health":p.ComponentHealth.Health=n;break;
                case "food":p.ComponentVitalStats.Food=n;break;case "stamina":p.ComponentVitalStats.Stamina=n;break;
                case "sleep":p.ComponentVitalStats.Sleep=n;break;case "wetness":p.ComponentVitalStats.Wetness=n;break;case "temperature":p.ComponentVitalStats.Temperature=n;break;}
        }
    }
    static void VerifyOperationReadback(Operation o,JsonNode restoreTarget=null)
    {
        if(o.Action=="creature_patch"){VerifyCreature(o,restoreTarget);return;}
        if(o.Action=="player_patch")
        {
            var desired=o.RestoreOf==null?o.Arguments:restoreTarget?.AsObject();
            foreach(var pair in desired){float requested=System.Text.Json.JsonSerializer.Deserialize<float>(pair.Value.ToJsonString()),actual=System.Text.Json.JsonSerializer.Deserialize<float>(o.After[pair.Key].ToJsonString());if(!EqualOverride(actual,requested))throw new HostError("READBACK_MISMATCH","Player field did not take effect: "+pair.Key);}
        }
        if(o.Action=="environment_patch")
        {
            o.Observations=new JsonObject {["time_of_day"]=Sub<SubsystemTimeOfDay>().TimeOfDay,["elapsed_game_seconds"]=Sub<SubsystemGameInfo>().TotalElapsedGameTime,["rain_intensity"]=Sub<SubsystemWeather>().PrecipitationIntensity,["fog_intensity"]=Sub<SubsystemWeather>().FogIntensity};
            if(o.RestoreOf==null)foreach(var pair in o.Arguments)
            {
                if(pair.Key=="time_of_day"){float target=System.Text.Json.JsonSerializer.Deserialize<float>(pair.Value.ToJsonString());if(!EqualOverride(Sub<SubsystemTimeOfDay>().TimeOfDay,target))throw new HostError("READBACK_MISMATCH","Clock did not reach requested phase");continue;}
                if(pair.Key is "simulation_factor" or "day_duration_seconds" or "season"){if(!EqualOverride(System.Text.Json.JsonSerializer.Deserialize<float>(o.After[pair.Key].ToJsonString()),System.Text.Json.JsonSerializer.Deserialize<float>(pair.Value.ToJsonString())))throw new HostError("READBACK_MISMATCH","Environment field did not take effect: "+pair.Key);}
                else if(!JsonNode.DeepEquals(o.After[pair.Key],pair.Value))throw new HostError("READBACK_MISMATCH","Environment field did not take effect: "+pair.Key);
            }
            else if(restoreTarget!=null&&!JsonNode.DeepEquals(o.After,restoreTarget))throw new HostError("READBACK_MISMATCH","Direct environment restoration did not retain recorded fields");
        }
    }
}
