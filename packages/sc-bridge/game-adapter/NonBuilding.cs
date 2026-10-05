using System.Text.Json.Nodes;
using Engine;

namespace Game;
public static partial class AgentHost
{
    // Read-only observations use the selected identity, never commandblock's global player cache.
    static JsonNode NonBuilding(string op,JsonObject args,JsonObject identity)
    {
        Identity(identity);
        var data=Sub<SubsystemPlayers>().PlayersData.Single(p=>p.PlayerIndex==(int)identity["player_index"]);
        var player=data.ComponentPlayer;
        if(player==null)throw new HostError("PLAYER_NOT_READY","Selected player has not spawned");
        var info=Sub<SubsystemGameInfo>();var day=Sub<SubsystemTimeOfDay>();
        switch(op)
        {
            case "lighting_query":
                var lightPoint=Position(args["position"]);var lightChunk=ST.Terrain.GetChunkAtCell(lightPoint.X,lightPoint.Z);
                if(lightChunk==null||lightChunk.State!=TerrainChunkState.Valid)throw new HostError("REGION_NOT_LOADED","Light requires a fully valid existing chunk");
                return new JsonObject { ["position"]=args["position"].DeepClone(),["light"]=ST.Terrain.GetCellLight(lightPoint.X,lightPoint.Y,lightPoint.Z),["unit"]="native light level 0..15",["observed_at_utc_ms"]=Now };
            case "environment_info":
                return new JsonObject { ["world"]=World(),["game_mode"]=info.WorldSettings.GameMode.ToString(),
                    ["environment_mode"]=info.WorldSettings.EnvironmentBehaviorMode.ToString(),["weather_enabled"]=info.WorldSettings.AreWeatherEffectsEnabled,
                    ["time_of_day"]=day.TimeOfDay,["day"]=day.Day,["elapsed_game_seconds"]=info.TotalElapsedGameTime,
                    ["time_of_day_mode"]=info.WorldSettings.TimeOfDayMode.ToString(),["day_duration_seconds"]=day.DayDuration,
                    ["time_of_day_offset"]=day.TimeOfDayOffset,["adventure_survival"]=info.WorldSettings.AreAdventureSurvivalMechanicsEnabled,
                    ["season"]=info.WorldSettings.TimeOfYear,["seasons_changing"]=info.WorldSettings.AreSeasonsChanging,
                    ["simulation_factor"]=Sub<SubsystemTime>().BasicGameTimeFactor,["rain"]=Sub<SubsystemWeather>().IsPrecipitationStarted,["fog"]=Sub<SubsystemWeather>().IsFogStarted,
                    ["sky_color"]=ColorJson(Sub<SubsystemCommandDef>().m_skyColor),["precipitation_color"]=ColorJson(Sub<SubsystemCommandDef>().m_rainColor),
                    ["session_fields"]=new JsonArray("simulation_factor","day_duration_seconds"),["commandblock_persisted_fields"]=new JsonArray("sky_color","precipitation_color"),["render_scope"]="Registered commandblock sky/precipitation fields; other Mod rendering may differ",
                    ["mod_count"]=ModsManager.ModList.Count,["observed_at_utc_ms"]=Now };
            case "player_state":
                var pos=player.ComponentBody.Position;var velocity=player.ComponentBody.Velocity;var vital=player.ComponentVitalStats;
                return new JsonObject { ["player_index"]=data.PlayerIndex,["player_name"]=data.Name,["level"]=data.Level,
                    ["position"]=new JsonArray(pos.X,pos.Y,pos.Z),["velocity"]=new JsonArray(velocity.X,velocity.Y,velocity.Z),
                    ["health"]=player.ComponentHealth.Health,["food"]=vital.Food,["stamina"]=vital.Stamina,["sleep"]=vital.Sleep,
                    ["temperature"]=vital.Temperature,["wetness"]=vital.Wetness,["walk_speed"]=player.ComponentLocomotion.WalkSpeed,
                    ["attack_power"]=player.ComponentMiner.AttackPower,["attack_resilience"]=player.ComponentHealth.AttackResilience,
                    ["units"]=new JsonObject { ["health_food_stamina_sleep_wetness"]="native fraction",["temperature"]="native game scale",
                        ["position"]="world blocks",["velocity_walk_speed"]="blocks per game second",["level"]="native floating level" },["observed_at_utc_ms"]=Now };
            case "inventory_read":
                var inventory=player.ComponentMiner.Inventory;
                if(inventory==null)throw new HostError("RESOURCE_NOT_READY","Player inventory missing");
                int offset=(int)args["offset"],limit=(int)args["limit"];
                if(offset<0||offset>inventory.SlotsCount||limit<1||limit>64)throw new HostError("INVALID_ARGUMENT","Inventory page limited to 64 slots");
                var slots=new JsonArray();bool creative=inventory is ComponentCreativeInventory;
                for(int i=offset;i<Math.Min(inventory.SlotsCount,offset+limit);i++)
                {
                    int count=inventory.GetSlotCount(i),itemValue=inventory.GetSlotValue(i);
                    slots.Add(new JsonObject { ["index"]=i,["value"]=itemValue,["contents"]=Terrain.ExtractContents(itemValue),["reported_count"]=count,
                        ["count_kind"]=creative&&count>0?"creative_supply":"physical_stack" });
                }
                return new JsonObject { ["slots"]=slots,["total"]=inventory.SlotsCount,["offset"]=offset,
                    ["next_offset"]=offset+slots.Count<inventory.SlotsCount?offset+slots.Count:null,["active_slot"]=inventory.ActiveSlotIndex,
                    ["inventory_type"]=inventory.GetType().FullName,["creative_supply"]=creative,["observed_at_utc_ms"]=Now };
            case "condition_query":
                string name=(string)args["name"],type=(string)args["subtype"];
                if(name=="blocklight")
                {
                    if(type!="default"||args.Count!=5||args["position"]==null||args["minimum"]==null||args["maximum"]==null)throw new HostError("INVALID_ARGUMENT","Point and inclusive range required");
                    double lightMinimum=(double)args["minimum"],lightMaximum=(double)args["maximum"];
                    if(!double.IsFinite(lightMinimum)||!double.IsFinite(lightMaximum)||lightMinimum>lightMaximum)throw new HostError("INVALID_ARGUMENT","Invalid light range");
                    var observation=NonBuilding("lighting_query",new JsonObject { ["position"]=args["position"].DeepClone() },identity);
                    int light=(int)observation["light"];
                    return new JsonObject { ["name"]=name,["subtype"]=type,["observed"]=light,["native_value"]=light,["scale"]=1,["unit"]="native light level 0..15",
                        ["minimum"]=lightMinimum,["maximum"]=lightMaximum,["matches"]=light>=lightMinimum&&light<=lightMaximum,["observed_at_utc_ms"]=observation["observed_at_utc_ms"].DeepClone() };
                }
                if(name=="gamemode")
                {
                    if(type!="default"||args.Count!=3||args["mode"]==null||!Enum.TryParse<GameMode>((string)args["mode"],false,out var requested)||!Enum.IsDefined(requested)||(string)args["mode"]!=requested.ToString())throw new HostError("INVALID_ARGUMENT","Registered game mode required");
                    string mode=info.WorldSettings.GameMode.ToString();return new JsonObject { ["name"]=name,["subtype"]=type,["observed"]=mode,["matches"]=mode==requested.ToString(),["observed_at_utc_ms"]=Now };
                }
                if(args.Count!=4||args["minimum"]==null||args["maximum"]==null)throw new HostError("INVALID_ARGUMENT","Inclusive finite range required");
                double minimum=(double)args["minimum"],maximum=(double)args["maximum"];
                if(!double.IsFinite(minimum)||!double.IsFinite(maximum)||minimum>maximum)throw new HostError("INVALID_ARGUMENT","Invalid condition range");
                double value,nativeValue,scale=1;string unit;
                if(name=="statsrange")
                {
                    (nativeValue,unit,scale)=type switch {
                        "health"=>((double)player.ComponentHealth.Health,"native fraction x100",100d),
                        "food"=>((double)player.ComponentVitalStats.Food,"native fraction x100",100d),
                        "stamina"=>((double)player.ComponentVitalStats.Stamina,"native fraction x100",100d),
                        "sleep"=>((double)player.ComponentVitalStats.Sleep,"native fraction x100",100d),
                        "wetness"=>((double)player.ComponentVitalStats.Wetness,"native fraction x100",100d),
                        "speed"=>((double)player.ComponentLocomotion.WalkSpeed,"native walk speed x10",10d),
                        "attack"=>((double)player.ComponentMiner.AttackPower,"native attack power",1d),
                        "defense"=>((double)player.ComponentHealth.AttackResilience,"native attack resilience",1d),
                        "temperature"=>((double)player.ComponentVitalStats.Temperature,"native game temperature scale",1d),
                        _=>throw new HostError("UNREGISTERED_COMMAND","Unknown statsrange subtype") };
                    value=(double)((float)nativeValue*(float)scale); // Match official commandblock's float scaling.
                }
                else
                {
                    if(type!="default")throw new HostError("UNREGISTERED_COMMAND","Only default subtype is registered");
                    (value,unit)=name switch {
                        "levelrange"=>((double)(int)data.Level,"level truncated toward zero"),
                        "heightrange"=>((double)player.ComponentBody.Position.Y,"world blocks"),
                        "timerange"=>((double)(int)(day.TimeOfDay*4096f),"time of day x4096 truncated"),
                        "modcount"=>((double)ModsManager.ModList.Count,"loaded mod count"),
                        _=>throw new HostError("UNREGISTERED_COMMAND","Condition is not registered") };
                    nativeValue=name=="levelrange"?data.Level:name=="timerange"?day.TimeOfDay:value;
                    if(name=="timerange")scale=4096;
                }
                if(!double.IsFinite(value))throw new HostError("INVALID_OBSERVATION","Native value is not finite");
                return new JsonObject { ["name"]=name,["subtype"]=type,["observed"]=value,["native_value"]=nativeValue,["scale"]=scale,["unit"]=unit,
                    ["minimum"]=minimum,["maximum"]=maximum,["matches"]=value>=minimum&&value<=maximum,["observed_at_utc_ms"]=Now };
            default:throw new HostError("UNREGISTERED_COMMAND","Non-building operation not registered");
        }
    }
}
