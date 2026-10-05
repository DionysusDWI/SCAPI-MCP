using System.Text.Json.Nodes;
using Engine;
namespace Game;
public static partial class AgentHost
{
    static readonly string[] EnvironmentFields=["weather_enabled","environment_mode","adventure_survival","time_of_day_mode","time_of_day","rain","fog","sky_color","precipitation_color","game_mode","season","seasons_changing","simulation_factor","day_duration_seconds"];
    static void EnumField<T>(JsonObject args,string key) where T:struct,Enum
    {var text=RequiredText(args,key);if(!Enum.TryParse<T>(text,false,out var value)||!Enum.IsDefined(value)||value.ToString()!=text)throw new HostError("INVALID_ARGUMENT","Unknown "+key);}
    static Color ColorField(JsonNode node)
    {if(node is not JsonArray a||a.Count!=4)throw new HostError("INVALID_ARGUMENT","RGBA array required");var n=a.Select(v=>System.Text.Json.JsonSerializer.Deserialize<int>(v.ToJsonString())).ToArray();if(n.Any(v=>v<0||v>255))throw new HostError("INVALID_ARGUMENT","RGBA byte range");return new Color(n[0],n[1],n[2],n[3]);}
    static JsonArray ColorJson(Color c)=>new(c.R,c.G,c.B,c.A);
    static void DescribeEnvironment(Operation o)
    {
        Closed(o.Arguments,EnvironmentFields);if(o.Arguments.Count==0)throw new HostError("INVALID_ARGUMENT","At least one environment field");
        foreach(var field in o.Arguments.Select(v=>v.Key))switch(field)
        {
            case "weather_enabled":case "adventure_survival":case "rain":case "fog":case "seasons_changing":Boolean(o.Arguments,field);break;
            case "environment_mode":EnumField<EnvironmentBehaviorMode>(o.Arguments,field);break;
            case "time_of_day_mode":EnumField<TimeOfDayMode>(o.Arguments,field);break;
            case "game_mode":EnumField<GameMode>(o.Arguments,field);break;
            case "time_of_day":case "season":Number(o.Arguments,field,0,.999999999);break;
            case "simulation_factor":Number(o.Arguments,field,.1,10);break;
            case "day_duration_seconds":Number(o.Arguments,field,60,86400);break;
            case "sky_color":case "precipitation_color":ColorField(o.Arguments[field]);break;
        }
        o.Backup=o.Arguments.ContainsKey("game_mode")||o.Arguments.ContainsKey("season")||o.Arguments.ContainsKey("seasons_changing");
        o.Risk=o.Backup?"dangerous":o.Arguments.ContainsKey("rain")||o.Arguments.ContainsKey("fog")?"side_effects":"state_change";
        o.Recovery=o.Backup||o.Arguments.ContainsKey("rain")||o.Arguments.ContainsKey("fog")?"none":"direct_fields";
        if(o.Arguments.ContainsKey("game_mode")&&o.Arguments.Count!=1)throw new HostError("INVALID_ARGUMENT","Mode switch is an independent maintenance operation");
        if(o.Arguments.ContainsKey("time_of_day")&&((string)o.Arguments["time_of_day_mode"]??Sub<SubsystemGameInfo>().WorldSettings.TimeOfDayMode.ToString())!="Changing")throw new HostError("UNSUPPORTED_SETTING","Clock positioning requires Changing time-of-day mode");
    }
    static JsonObject CaptureEnvironment(Operation o)
    {
        var result=new JsonObject();var w=Sub<SubsystemGameInfo>().WorldSettings;var t=Sub<SubsystemTimeOfDay>();var weather=Sub<SubsystemWeather>();
        foreach(var key in o.Arguments.Select(v=>v.Key))result[key]=key switch {
            "weather_enabled"=>JsonValue.Create(w.AreWeatherEffectsEnabled),"environment_mode"=>JsonValue.Create(w.EnvironmentBehaviorMode.ToString()),
            "adventure_survival"=>JsonValue.Create(w.AreAdventureSurvivalMechanicsEnabled),"time_of_day_mode"=>JsonValue.Create(w.TimeOfDayMode.ToString()),
            "time_of_day"=>JsonValue.Create(t.TimeOfDayOffset),"rain"=>JsonValue.Create(weather.IsPrecipitationStarted),"fog"=>JsonValue.Create(weather.IsFogStarted),
            "game_mode"=>JsonValue.Create(w.GameMode.ToString()),"season"=>JsonValue.Create(w.TimeOfYear),"seasons_changing"=>JsonValue.Create(w.AreSeasonsChanging),
            "simulation_factor"=>JsonValue.Create(Sub<SubsystemTime>().BasicGameTimeFactor),"day_duration_seconds"=>JsonValue.Create(t.DayDuration),
            "sky_color"=>ColorJson(Sub<SubsystemCommandDef>().m_skyColor),"precipitation_color"=>ColorJson(Sub<SubsystemCommandDef>().m_rainColor),_=>null};
        return result;
    }
    static void ApplyEnvironment(Operation o)
    {
        var w=Sub<SubsystemGameInfo>().WorldSettings;var t=Sub<SubsystemTimeOfDay>();var weather=Sub<SubsystemWeather>();var desired=o.RestoreOf==null?o.Arguments:o.After;
        foreach(var pair in desired.OrderBy(p=>p.Key=="time_of_day_mode"?0:p.Key=="day_duration_seconds"?1:p.Key=="time_of_day"?3:2))
        {
            double n=pair.Key is "time_of_day" or "season" or "simulation_factor" or "day_duration_seconds"?System.Text.Json.JsonSerializer.Deserialize<double>(pair.Value.ToJsonString()):0;
            switch(pair.Key)
            {
                case "weather_enabled":w.AreWeatherEffectsEnabled=pair.Value.GetValue<bool>();break;
                case "environment_mode":w.EnvironmentBehaviorMode=Enum.Parse<EnvironmentBehaviorMode>((string)pair.Value);break;
                case "adventure_survival":w.AreAdventureSurvivalMechanicsEnabled=pair.Value.GetValue<bool>();break;
                case "time_of_day_mode":w.TimeOfDayMode=Enum.Parse<TimeOfDayMode>((string)pair.Value);break;
                case "time_of_day":t.TimeOfDayOffset=o.RestoreOf==null?t.TimeOfDayOffset+MathUtils.Remainder(n-t.TimeOfDay,1):n;break;
                case "rain":if(pair.Value.GetValue<bool>())weather.ManualPrecipitationStart();else weather.ManualPrecipitationEnd();break;
                case "fog":if(pair.Value.GetValue<bool>())weather.ManualFogStart();else weather.ManualFogEnd();break;
                case "game_mode":w.GameMode=Enum.Parse<GameMode>((string)pair.Value);break;
                case "season":w.TimeOfYear=(float)n;t.UpdateStarts();break;
                case "seasons_changing":w.AreSeasonsChanging=pair.Value.GetValue<bool>();break;
                case "simulation_factor":Sub<SubsystemTime>().BasicGameTimeFactor=(float)n;break;
                case "day_duration_seconds":t.DayDuration=(float)n;break;
                case "sky_color":Sub<SubsystemCommandDef>().m_skyColor=ColorField(pair.Value);break;
                case "precipitation_color":Sub<SubsystemCommandDef>().m_rainColor=ColorField(pair.Value);break;
            }
        }
        if(o.Backup)
        {
            o.After=CaptureEnvironment(o);o.State="waiting_reload";o.MaintenanceStarted=Now;
            string directory=(string)o.Identity["directory"];GameManager.SaveProject(true,true);GameManager.DisposeProject();var world=WorldsManager.GetWorldInfo(directory);if(world==null||world.WorldSettings.Name!=(string)o.Identity["name"])throw new HostError("WRONG_WORLD","Saved maintenance target changed");ScreensManager.SwitchScreen("GameLoading",world,null);
        }
    }
}
