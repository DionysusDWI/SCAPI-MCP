using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    // Save and unload on the game thread. Only offline files are packed by the worker.
    static bool TickFreshOperationBackup(Operation o)
    {
        if(o.State=="backing_up")
        {
            if(o.BackupWork is {IsCompleted:false}){if(Now-o.MaintenanceStarted>60000)throw new HostError("BACKUP_TIMEOUT","Offline export exceeded 60 seconds; world remains unloaded, inspect audit and package before any next action");return false;}
            var backup=o.BackupWork.GetAwaiter().GetResult();
            if(GameManager.Project!=null)throw new HostError("WORLD_BUSY","Another world loaded during offline backup; do not resume automatically");
            var wi=WorldsManager.GetWorldInfo((string)o.Identity["directory"]);if(wi==null||wi.WorldSettings.Name!=(string)o.Identity["name"])throw new HostError("WRONG_WORLD","Backup reload target changed");
            o.FullBackup=backup;o.State="waiting_backup_reload";PersistOperation(o);ScreensManager.SwitchScreen("GameLoading",wi,null);return false;
        }
        if(o.State=="waiting_backup_reload")return false;
        Identity(o.Identity,true,true);if(!OperationMatches(o))throw new HostError("STALE_PLAN","Preflight changed before current full backup");
        string directory=(string)o.Identity["directory"],name=(string)o.Identity["name"],token=(string)o.Identity["world_token"];
        GameManager.SaveProject(true,true);GameManager.DisposeProject();ScreensManager.SwitchScreen("MainMenu");
        string file=Path.Combine((string)settings["backups"],"nonbuilding",o.Id+".scworld");o.State="backing_up";o.MaintenanceStarted=Now;
        o.BackupWork=Task.Run(()=>
        {
            Directory.CreateDirectory(Path.GetDirectoryName(file));using(var stream=File.Create(file))WorldsManager.ExportWorld(directory,stream);
            using(var package=System.IO.Compression.ZipFile.OpenRead(file))
            {
                var marker=package.GetEntry("scagent-world-id.txt")??throw new IOException("Backup lacks world identity marker");using(var reader=new StreamReader(marker.Open()))if(reader.ReadToEnd()!=token)throw new IOException("Backup world token mismatch");
                var entry=package.GetEntry("Project.xml")??throw new IOException("Backup lacks Project.xml");using(var stream=entry.Open())
                {var xml=System.Xml.Linq.XDocument.Load(stream);var value=xml.Root.Element("Subsystems")?.Elements("Values").SingleOrDefault(e=>(string)e.Attribute("Name")=="GameInfo")?.Elements("Value").SingleOrDefault(e=>(string)e.Attribute("Name")=="WorldName");if((string)value?.Attribute("Value")!=name)throw new IOException("Backup name mismatch");}
            }
            using var input=File.OpenRead(file);var result=new JsonObject {["path"]=file,["sha256"]=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(input)).ToLowerInvariant(),["world_token"]=token,["directory"]=directory,["name"]=name,["created_at_utc_ms"]=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),["import_verified"]=false};Save(file+".manifest.json",result);return result;
        });PersistOperation(o);return false;
    }
    static bool FinishBackupReload(Operation o)
    {
        if(o.State!="waiting_backup_reload")return true;
        if(Now-o.MaintenanceStarted>60000)throw new HostError("WORLD_RELOAD_TIMEOUT","Backup reload timed out");
        if(GameManager.Project==null||Sub<SubsystemPlayers>().PlayersData.SingleOrDefault(p=>p.PlayerIndex==(int)o.Identity["player_index"])?.ComponentPlayer==null)return false;
        if(GameManager.IsNetworkProject||NetworkManager.IsClientRunning||NetworkManager.ServerSessions.Any()||Players().Count!=1)throw new HostError("MULTIPLAYER_DISABLED","Maintenance requires proven isolated local reload");
        NetworkManager.Stop();
        o.Identity["session"]=session;Identity(o.Identity,true,false);o.State="persisting_intent";PersistOperation(o);return false;
    }
}
