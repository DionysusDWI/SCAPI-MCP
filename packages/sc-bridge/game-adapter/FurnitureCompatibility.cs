using Engine;
using HarmonyLib;
namespace Game;
public static partial class AgentHost
{
    // API_1.9.3.2_MP source sets m_furnitureDesigns[k]=null and then reads
    // m_furnitureDesigns[k].Index. Replace only this registered world's collector.
    static void InstallFurnitureCompatibility()
    {
        if(ModsManager.APIVersionString!="1.9.3.2")return;
        var method=AccessTools.Method(typeof(SubsystemFurnitureBlockBehavior),"GarbageCollectDesigns",[typeof(ReadOnlyList<ScannedItemData>)]);
        new Harmony("local.sc.agentbridge.furniture1932").Patch(method,prefix:new HarmonyMethod(typeof(AgentHost),nameof(CollectFurnitureSafely)));
    }
    static bool CollectFurnitureSafely(SubsystemFurnitureBlockBehavior __instance,ReadOnlyList<ScannedItemData> allExistingItems)
    {
        if(GameManager.Project==null || NetworkManager.IsClientRunning)return true;
        var info=GameManager.Project.FindSubsystem<SubsystemGameInfo>(true);
        if(info.DirectoryName!=(string)settings["target"]["directory"] || info.WorldSettings.Name!=(string)settings["target"]["name"])return true;
        string marker=Storage.CombinePaths(info.DirectoryName,"scagent-world-id.txt");
        if(!Storage.FileExists(marker)||Storage.ReadAllText(marker)!=(string)settings["target"]["world_token"])return true;
        var designs=__instance.m_furnitureDesigns;
        foreach(var d in designs)if(d!=null)d.m_gcUsed=d.m_terrainUseCount>0;
        foreach(var item in allExistingItems)if(Terrain.ExtractContents(item.Value)==227)
        {var d=__instance.GetDesign(FurnitureBlock.GetDesignIndex(Terrain.ExtractData(item.Value)));if(d!=null)d.m_gcUsed=true;}
        foreach(var d in designs)if(d!=null&&d.m_gcUsed)
        {var linked=d.LinkedDesign;while(linked!=null&&!linked.m_gcUsed){linked.m_gcUsed=true;linked=linked.LinkedDesign;}}
        for(int i=0;i<designs.Length;i++)if(designs[i]!=null&&!designs[i].m_gcUsed&&designs[i].FurnitureSet==null)
        {designs[i].Index=-1;designs[i]=null;}
        return false;
    }
}
