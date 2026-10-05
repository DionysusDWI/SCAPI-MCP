using System.Text.Json.Nodes;
using GameEntitySystem;
namespace Game;
public static partial class AgentHost
{
    sealed class CreatureTarget
    {
        public string Id=Guid.NewGuid().ToString("N"),Client;
        public JsonObject Identity;
        public ComponentCreature Creature;
        public long Expires=Now+120000;
    }
    static readonly Dictionary<string,CreatureTarget> creatureTargets=[];
    static bool labHoldCreature,labDropCreatureReply;
    static string requestClient;
    static readonly string[] CreatureFields=["health","walk_speed","attack_power","attack_resilience"];
    static ComponentCreature ValidCreature(ComponentCreature creature)
    {
        if(creature==null||creature is ComponentPlayer||creature.Entity.FindComponent<ComponentPlayer>()!=null)throw new HostError("INVALID_CREATURE","Only non-player creatures are supported");
        if(!creature.Entity.IsAddedToProject)throw new HostError("TARGET_REMOVED","Creature is no longer active");
        if(creature.GetType().Assembly!=typeof(ComponentCreature).Assembly||creature.ComponentHealth.GetType().Assembly!=typeof(ComponentHealth).Assembly||creature.ComponentLocomotion.GetType().Assembly!=typeof(ComponentLocomotion).Assembly)throw new HostError("UNKNOWN_COMPONENT","Unknown Mod creature components are not writable");
        if(!float.IsFinite(creature.ComponentHealth.Health)||creature.ComponentHealth.Health<=0)throw new HostError("CREATURE_DEAD","Dead or invalid creature cannot be patched");
        var position=creature.ComponentBody.Position;var chunk=ST.Terrain.GetChunkAtCell((int)MathF.Floor(position.X),(int)MathF.Floor(position.Z));
        if(chunk==null||chunk.State!=TerrainChunkState.Valid)throw new HostError("REGION_NOT_LOADED","Creature column is not fully loaded");
        return creature;
    }
    static JsonObject CreatureValues(ComponentCreature c,IEnumerable<string> fields)
    {
        var result=new JsonObject();
        foreach(var field in fields)
        {
            float value;
            switch(field)
            {
                case "health":value=c.ComponentHealth.Health;break;
                case "walk_speed":value=c.ComponentLocomotion.WalkSpeed;break;
                case "attack_resilience":value=c.ComponentHealth.AttackResilience;break;
                case "attack_power":var miner=c.Entity.FindComponent<ComponentMiner>();if(miner==null||miner.GetType().Assembly!=typeof(ComponentMiner).Assembly)throw new HostError("UNSUPPORTED_FIELD","Native miner attack field is unavailable");value=miner.AttackPower;break;
                default:throw new HostError("UNREGISTERED_COMMAND","Unknown creature field");
            }
            if(!float.IsFinite(value))throw new HostError("INVALID_OBSERVATION","Creature field is not finite");result[field]=value;
        }
        return result;
    }
    static JsonNode CreatureInspect(JsonObject args,JsonObject identity)
    {
        Identity(identity,true,false);Closed(args,"native_id");
        if(!OperationCapabilityAllowed("creature_inspect"))throw new HostError("CAPABILITY_DISABLED","Creature inspection not accepted");
        if(!Guid.TryParseExact(requestClient,"N",out _))throw new HostError("INVALID_ARGUMENT","Client identity required");
        int id=Integer(args,"native_id",0,int.MaxValue);
        var body=Sub<SubsystemBodies>().Bodies.SingleOrDefault(b=>b.Entity.Id==id)??throw new HostError("TARGET_REMOVED","Active creature body was not found");
        var c=ValidCreature(body.Entity.FindComponent<ComponentCreature>());
        foreach(var old in creatureTargets.Where(t=>t.Value.Expires<Now&&!operations.Values.Any(o=>(string)o.Arguments?["target_id"]==t.Key)).Select(t=>t.Key).ToArray())creatureTargets.Remove(old);
        if(creatureTargets.Count>=256)throw new HostError("TARGET_CAPACITY","Creature handle capacity reached");
        var target=new CreatureTarget {Client=requestClient,Identity=identity.DeepClone().AsObject(),Creature=c};creatureTargets.Add(target.Id,target);
        var supported=CreatureFields.Where(f=>f!="attack_power"||c.Entity.FindComponent<ComponentMiner>()?.GetType().Assembly==typeof(ComponentMiner).Assembly).ToArray();
        return new JsonObject {["target_id"]=target.Id,["native_id"]=id,["template"]=c.Entity.ValuesDictionary.DatabaseObject.Name,["fields"]=CreatureValues(c,supported),["supported_fields"]=new JsonArray(supported.Select(f=>(JsonNode)JsonValue.Create(f)).ToArray()),["attack_resilience_factor"]=c.ComponentHealth.AttackResilienceFactor,["expires_at_utc_ms"]=target.Expires,["boot"]=Boot,["identity"]=identity.DeepClone(),["persistent_identity"]=false};
    }
    static ComponentCreature OperationCreature(Operation o)
    {
        string id=GuidText(o.Arguments,"target_id");
        if(!creatureTargets.TryGetValue(id,out var target))throw new HostError("STALE_TARGET","Creature handle expired at restart/reload or was removed");
        if(target.Client!=o.Client||!JsonNode.DeepEquals(target.Identity,o.Identity))throw new HostError("IDENTITY_MISMATCH","Creature handle belongs to another client/session/target");
        if(o.RestoreOf==null&&target.Expires<Now)throw new HostError("STALE_TARGET","Creature inspection handle expired; inspect again");
        return ValidCreature(target.Creature);
    }
    static void DescribeCreature(Operation o)
    {
        Closed(o.Arguments,"target_id","fields");
        if(o.Arguments["fields"] is not JsonObject fields||fields.Count==0)throw new HostError("INVALID_ARGUMENT","Nonempty creature fields required");
        Closed(fields,CreatureFields);
        foreach(var f in fields)Number(fields,f.Key,f.Key is "health" or "attack_resilience"?.001:0,f.Key=="health"?1:f.Key=="walk_speed"?64:10000);
        var c=OperationCreature(o);CreatureValues(c,fields.Select(f=>f.Key));
        float factor=c.ComponentHealth.AttackResilienceFactor;
        if(!float.IsFinite(factor)||factor<=0)throw new HostError("UNSUPPORTED_FIELD","Attack resilience factor must be finite and positive");
        o.Risk="side_effects";o.Recovery="direct_fields";o.Backup=false;
    }
    static JsonObject CaptureCreature(Operation o)
    {
        var c=OperationCreature(o);return new JsonObject {["target_id"]=o.Arguments["target_id"].DeepClone(),["native_id"]=c.Entity.Id,["template"]=c.Entity.ValuesDictionary.DatabaseObject.Name,["attack_resilience_factor"]=c.ComponentHealth.AttackResilienceFactor,["fields"]=CreatureValues(c,o.Arguments["fields"].AsObject().Select(f=>f.Key))};
    }
    static void ApplyCreature(Operation o)
    {
        var c=OperationCreature(o);var fields=o.RestoreOf==null?o.Arguments["fields"].AsObject():o.After["fields"].AsObject();
        foreach(var f in fields)
        {
            float n=System.Text.Json.JsonSerializer.Deserialize<float>(f.Value.ToJsonString());
            switch(f.Key){case "health":c.ComponentHealth.Health=n;break;case "walk_speed":c.ComponentLocomotion.WalkSpeed=n;break;case "attack_power":c.Entity.FindComponent<ComponentMiner>(true).AttackPower=n;break;case "attack_resilience":c.ComponentHealth.AttackResilience=n/c.ComponentHealth.AttackResilienceFactor;break;}
        }
    }
    static void VerifyCreature(Operation o,JsonNode restoreTarget)
    {
        var fields=o.RestoreOf==null?o.Arguments["fields"].AsObject():restoreTarget["fields"].AsObject();
        foreach(var f in fields)if(!EqualOverride(System.Text.Json.JsonSerializer.Deserialize<float>(o.After["fields"][f.Key].ToJsonString()),System.Text.Json.JsonSerializer.Deserialize<float>(f.Value.ToJsonString())))throw new HostError("READBACK_MISMATCH","Creature field did not take effect: "+f.Key);
    }
    static JsonNode CreatureLab(string op,JsonObject args,JsonObject identity)
    {
        if(settings["target"]["test_only"]?.GetValue<bool>()!=true||!((string)settings["target"]["name"]).StartsWith("SC MCP LAB"))throw new HostError("LAB_DISABLED","Explicit LAB registration required");
        Identity(identity,true,false);
        if(op=="lab_creature_hold"){labHoldCreature=true;return new JsonObject {["held"]=true};}
        if(op=="lab_creature_release"){labHoldCreature=false;return new JsonObject {["released"]=true};}
        if(op=="lab_creature_drop_reply"){labDropCreatureReply=true;return new JsonObject {["armed"]=true};}
        if(op=="lab_creature_create")
        {
            if(observationWolf?.IsAddedToProject==true)throw new HostError("LAB_BUSY","Creature fixture exists");
            observationWolf=DatabaseManager.CreateEntity(GameManager.Project,"Wolf",true);observationWolf.FindComponent<ComponentBody>(true).Position=new Engine.Vector3(-146.5f,67,-94.5f);GameManager.Project.AddEntity(observationWolf);
            return new JsonObject {["native_id"]=observationWolf.Id};
        }
        if(op=="lab_creature_save_unload")
        {
            Identity(identity,true);Closed(args,"target_id");var selected=OperationCreature(new Operation {Client=requestClient,Identity=identity,Arguments=args});
            if(!ReferenceEquals(selected.Entity,observationWolf)||observationDrops.Count!=0)throw new HostError("NO_FIXTURE","Only the explicit creature-only fixture may be saved");
            if(active!=null||operationActive!=null)throw new HostError("WORLD_BUSY","Finish modifications before saving");
            GameManager.SaveProject(true,false);GameManager.DisposeProject();observationWolf=null;ScreensManager.SwitchScreen("MainMenu");return new JsonObject {["saved"]=true,["unloaded"]=true,["fixture_persisted"]=true};
        }
        if(op=="lab_creature_adopt")
        {
            Closed(args,"target_id");var selected=OperationCreature(new Operation {Client=requestClient,Identity=identity,Arguments=args});
            if(selected.Entity.ValuesDictionary.DatabaseObject.Name!="Wolf")throw new HostError("NO_FIXTURE","Only the explicit Wolf fixture can be adopted");
            observationWolf=selected.Entity;return new JsonObject {["native_id"]=observationWolf.Id};
        }
        var c=observationWolf?.FindComponent<ComponentCreature>(true)??throw new HostError("NO_FIXTURE","Create the observation fixture first");
        if(op=="lab_creature_external")c.ComponentLocomotion.WalkSpeed+=1;
        else if(op=="lab_creature_factor")c.ComponentHealth.AttackResilienceFactor=2;
        else if(op=="lab_creature_dead")c.ComponentHealth.Health=0;
        else throw new HostError("UNREGISTERED_COMMAND","Unknown creature fixture action");
        return new JsonObject {["native_id"]=c.Entity.Id,["health"]=c.ComponentHealth.Health,["walk_speed"]=c.ComponentLocomotion.WalkSpeed,["attack_resilience_factor"]=c.ComponentHealth.AttackResilienceFactor};
    }
}
