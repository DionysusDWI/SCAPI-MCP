using System.Text.Json.Nodes;
using Engine;

namespace Game;
public static partial class AgentHost
{
    static PlayerData labPlayer;
    static readonly List<FurnitureDesign> capacityFixture=[];
    static ComponentInventoryBase invalidInventoryFixture;
    static int invalidInventoryValue,invalidInventoryCount;
    static GameEntitySystem.Entity observationWolf;
    static readonly List<Pickable> observationDrops=[];
    // Internal acceptance fixtures. These are deliberately absent from MCP tools.
    // They are enabled only by an explicit test-only world registration.
    static JsonNode Lab(string op,JsonObject identity)
    {
        if(settings["target"]["test_only"]?.GetValue<bool>()!=true)throw new HostError("LAB_DISABLED","Test-only configuration required");
        if(!((string)settings["target"]["name"]).StartsWith("SC MCP LAB"))throw new HostError("LAB_DISABLED","Only named LAB targets support fixtures");
        if(op is "lab_climate_unavailable" or "lab_climate_available"){Identity(identity,true);labClimateUnavailable=op=="lab_climate_unavailable";return new JsonObject {["simulated_unavailable"]=labClimateUnavailable};}
        if(op=="lab_interrupt_process")
        {
            Identity(identity,true);
            if(!(settings["target"]["name"]?.GetValue<string>()??"").StartsWith("SC MCP LAB"))throw new HostError("LAB_DISABLED","Lab name required");
            GameManager.SaveProject(true,false);if(active!=null)Record(plans[active]);
            System.Diagnostics.Process.GetCurrentProcess().Kill();
            return null;
        }
        if((active!=null||operationActive!=null)&&op is not ("lab_pending_complete" or "lab_fixture_state"))throw new HostError("WORLD_BUSY","Finish/cancel jobs before lab lifecycle actions");
        if(op.StartsWith("lab_fixture_")||op is "lab_journal_fail_next" or "lab_event_log_fail_next" or "lab_override_external_change" or "lab_pending_enable" or "lab_pending_complete" or "lab_native_event_suite" or "lab_inventory_fail_second" or "lab_inventory_failure_release")return InteractionLab(op,identity);
        if(op is "lab_create_world" or "lab_create_survival_copy" or "lab_verify_backup_import" or "lab_load_target" or "lab_export_b")
        {
            if(GameManager.Project!=null)throw new HostError("WORLD_LOADED","World must be saved and unloaded");
            WorldInfo info;
            if(op=="lab_export_b")
            {
                WorldsManager.UpdateWorldsList();info=WorldsManager.WorldInfos.Single(w=>w.WorldSettings.Name=="SC MCP LAB B");
                string path=Path.Combine((string)settings["backups"],"mcp-lab","exports",Guid.NewGuid().ToString("N")+".scworld");Directory.CreateDirectory(Path.GetDirectoryName(path));
                using(var stream=File.Create(path))WorldsManager.ExportWorld(info.DirectoryName,stream);
                using var input=File.OpenRead(path);return new JsonObject { ["directory"]=info.DirectoryName,["name"]=info.WorldSettings.Name,["path"]=path,["sha256"]=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(input)).ToLowerInvariant() };
            }
            if(op=="lab_load_target")
            {
                info=WorldsManager.GetWorldInfo((string)settings["target"]["directory"]);
                if(info==null||info.WorldSettings.Name!=(string)settings["target"]["name"])throw new HostError("WRONG_WORLD","Lab target differs");
                ScreensManager.SwitchScreen("GameLoading",info,null);
                return new JsonObject { ["requested"]=true,["directory"]=info.DirectoryName };
            }
            if(op=="lab_create_world")
                info=WorldsManager.CreateWorld(new WorldSettings { Name="SC MCP LAB B",GameMode=GameMode.Creative,TerrainGenerationMode=TerrainGenerationMode.FlatContinent,EnvironmentBehaviorMode=EnvironmentBehaviorMode.Static,TerrainLevel=64,Seed="1932" });
            else
            {
                string backup=(string)settings["target"]["backup_path"];VerifyBackup(backup);
                string directory;using(var stream=File.OpenRead(backup))directory=WorldsManager.ImportWorld(stream);
                info=WorldsManager.GetWorldInfo(directory);info.WorldSettings.Name=op=="lab_create_survival_copy"?"SC MCP LAB SURVIVAL":"SC MCP LAB BACKUP VERIFY";
                if(op=="lab_create_survival_copy")info.WorldSettings.GameMode=GameMode.Challenging;
                WorldsManager.ChangeWorld(directory,info.WorldSettings);
            }
            return new JsonObject { ["directory"]=info.DirectoryName,["name"]=info.WorldSettings.Name };
        }
        Identity(identity);
        switch(op)
        {
            case "lab_event_native_attempt":
                var eventPlayer=Sub<SubsystemPlayers>().PlayersData.Single(p=>p.PlayerIndex==(int)identity["player_index"]).ComponentPlayer;
                bool eaten=eventPlayer.ComponentVitalStats.Eat(3);return new JsonObject {["eat_stone_result"]=eaten};
            case "lab_event_overflow":
                for(int i=0;i<4100;i++)EmitEvent("capture",null,"unknown",new JsonObject {["test_fixture"]=true});return new JsonObject {["emitted"]=4100};
            case "lab_create_observation_fixture":
                Identity(identity,true);
                if(observationWolf!=null||observationDrops.Count!=0)throw new HostError("LAB_BUSY","Observation fixture exists");
                observationWolf=DatabaseManager.CreateEntity(GameManager.Project,"Wolf",true);
                observationWolf.FindComponent<ComponentBody>(true).Position=new Vector3(-146.5f,67,-94.5f);
                GameManager.Project.AddEntity(observationWolf);
                for(int i=0;i<4;i++)observationDrops.Add(Sub<SubsystemPickables>().AddPickable(i%2==0?3:15,i+2,new Vector3(-145.5f+i,100,-92.5f),Vector3.Zero,null));
                if(observationDrops.Any(p=>p==null))throw new HostError("NO_FIXTURE","Pickable creation failed");
                return new JsonObject { ["wolf_id"]=observationWolf.Id,["pickable_ids"]=new JsonArray(observationDrops.Select(p=>(JsonNode)JsonValue.Create(p.Id)).ToArray()) };
            case "lab_remove_observation_fixture":
                Identity(identity,true);
                if(observationWolf?.IsAddedToProject==true)GameManager.Project.RemoveEntity(observationWolf,true);
                observationWolf=null;foreach(var drop in observationDrops)drop.ToRemove=true;
                int removed=observationDrops.Count;observationDrops.Clear();return new JsonObject { ["removed_pickables"]=removed,["removed_wolf"]=true };
            case "lab_expire_observation_snapshots":
                foreach(var snapshot in observationSnapshots.Values)snapshot.Expires=0;
                return new JsonObject { ["expired"]=observationSnapshots.Count };
            case "lab_invalid_inventory":
                Identity(identity,true);
                if(invalidInventoryFixture!=null)throw new HostError("LAB_BUSY","Invalid inventory fixture exists");
                var fixtureEntity=Sub<SubsystemBlockEntities>().GetBlockEntity(-151,75,-95);
                if(fixtureEntity==null||Terrain.ExtractContents(Raw(new Point3(-151,75,-95)))!=45)throw new HostError("NO_FIXTURE","Expected lab chest missing");
                invalidInventoryFixture=fixtureEntity.Entity.FindComponent<ComponentInventoryBase>(true);
                invalidInventoryValue=invalidInventoryFixture.m_slots[0].Value;invalidInventoryCount=invalidInventoryFixture.m_slots[0].Count;
                invalidInventoryFixture.m_slots[0].Value=3;invalidInventoryFixture.m_slots[0].Count=10000;
                return new JsonObject { ["count"]=10000 };
            case "lab_release_invalid_inventory":
                Identity(identity,true);
                if(invalidInventoryFixture==null)throw new HostError("NO_FIXTURE","Invalid inventory fixture missing");
                int fixtureCount=invalidInventoryFixture.m_slots[0].Count;
                invalidInventoryFixture.m_slots[0].Value=invalidInventoryValue;invalidInventoryFixture.m_slots[0].Count=invalidInventoryCount;invalidInventoryFixture=null;
                return new JsonObject { ["observed_count"]=fixtureCount,["released"]=true };
            case "lab_circuit_outputs":
                var outputs=new JsonArray();var electricity=Sub<SubsystemElectricity>();
                foreach(int x in new[]{-148,-146,-144})
                {
                    var element=electricity.GetElectricElement(x,70,-93,x==-144?0:4);
                    outputs.Add(new JsonObject { ["position"]=new JsonArray(x,70,-93),["type"]=element?.GetType().FullName,["voltage"]=element?.GetOutputVoltage(0) });
                }
                return outputs;
            case "lab_stabilize_environment":
                Identity(identity,true);var world=Sub<SubsystemGameInfo>().WorldSettings;
                var prior=new JsonObject { ["environment"]=world.EnvironmentBehaviorMode.ToString(),["weather"]=world.AreWeatherEffectsEnabled };
                world.EnvironmentBehaviorMode=EnvironmentBehaviorMode.Static;world.AreWeatherEffectsEnabled=false;
                return new JsonObject { ["before"]=prior,["environment"]="Static",["weather"]=false };
            case "lab_fill_design_capacity":
                Identity(identity,true);
                if(capacityFixture.Count!=0)throw new HostError("LAB_BUSY","Capacity fixture exists");
                var furniture=Sub<SubsystemFurnitureBlockBehavior>();
                for(int i=0;i<furniture.m_furnitureDesigns.Length;i++)if(furniture.m_furnitureDesigns[i]==null)
                {
                    var values=new TemplatesDatabase.ValuesDictionary();values.SetValue("Name","SC MCP capacity fixture "+i);values.SetValue("TerrainUseCount",0);values.SetValue("Resolution",2);values.SetValue("InteractionMode",FurnitureInteractionMode.None);values.SetValue("Values","8*3,");
                    var design=new FurnitureDesign(-1,ST,values);furniture.AddDesign(i,design);design.m_terrainUseCount=1;capacityFixture.Add(design);
                }
                return new JsonObject { ["reserved"]=capacityFixture.Count,["free"]=furniture.m_furnitureDesigns.Count(d=>d==null) };
            case "lab_release_design_capacity":
                Identity(identity,true);var behavior=Sub<SubsystemFurnitureBlockBehavior>();
                foreach(var design in capacityFixture)if(design.Index>=0&&ReferenceEquals(behavior.GetDesign(design.Index),design)){behavior.m_furnitureDesigns[design.Index]=null;design.Index=-1;}
                capacityFixture.Clear();return new JsonObject { ["released"]=true };
            case "lab_save_unload":
                if(observationWolf!=null||observationDrops.Count!=0)throw new HostError("LAB_BUSY","Clean up observation fixtures before saving");
                GameManager.SaveProject(true,false);GameManager.DisposeProject();ScreensManager.SwitchScreen("MainMenu");return new JsonObject { ["saved"]=true,["unloaded"]=true };
            case "lab_add_player":
                if(labPlayer!=null||Players().Count!=1)throw new HostError("LAB_BUSY","A fixture player already exists");
                labPlayer=new PlayerData(GameManager.Project) { Name="SC MCP fixture" };
                Sub<SubsystemPlayers>().AddPlayerData(labPlayer);return Players();
            case "lab_remove_player":
                if(labPlayer==null)throw new HostError("NO_FIXTURE","No fixture player to remove");
                Sub<SubsystemPlayers>().RemovePlayerData(labPlayer);labPlayer=null;return Players();
            default:throw new HostError("UNREGISTERED_COMMAND","Unknown lab fixture");
        }
    }
}
