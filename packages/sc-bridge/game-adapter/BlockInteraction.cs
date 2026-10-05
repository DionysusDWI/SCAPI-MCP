using Engine;
using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    static readonly HashSet<int> InteractableBlocks=[56,57,58,83,84,141,142,27,45,64,216];
    static TerrainRaycastResult InteractionRay(Operation o)
    {
        var p=OperationPlayer(o);var point=Position(o.Arguments["position"]);
        int value=Raw(point);SafeBlock(value,true);if(!InteractableBlocks.Contains(Terrain.ExtractContents(value)))throw new HostError("UNREGISTERED_COMMAND","Only registered interactive block families supported");
        if(p.ComponentMiner.AnyIsPending)throw new HostError("PLAYER_BUSY","Native miner already has a pending action");
        var direction=p.GameWidget.ActiveCamera.ViewDirection;
        float reach=Sub<SubsystemGameInfo>().WorldSettings.GameMode==GameMode.Creative?Math.Min(SettingsManager.CreativeReach,SettingsManager.VisibilityRange):5;
        var origin=p.GameWidget.ActiveCamera.ViewPosition;
        if(Vector3.Distance(origin,p.ComponentCreatureModel.EyePosition)>3)throw new HostError("CAMERA_DETACHED","Detached observation camera cannot drive interaction");
        var hit=p.ComponentMiner.Raycast<TerrainRaycastResult>(new Ray3(origin,Vector3.Normalize(direction)),RaycastMode.Interaction,true,false,false,reach:reach);
        if(!hit.HasValue||hit.Value.CellFace.Point!=point)throw new HostError("TARGET_NOT_VISIBLE","Target must be within native reach and unobstructed current player view");return hit.Value;
    }
    static void DescribeInteract(Operation o)
    {
        Closed(o.Arguments,"position");int id=Terrain.ExtractContents(o.RestoreOf==null?InteractionRay(o).Value:Raw(Position(o.Arguments["position"])));
        if(!InteractableBlocks.Contains(id))throw new HostError("RESTORE_CONFLICT","Registered interaction target was replaced");
        o.Risk="side_effects";o.Recovery=id is 56 or 57 or 58 or 83 or 84 or 141?"direct_fields":"none";o.Backup=false;
    }
    static JsonObject CaptureInteract(Operation o,bool requireView=true)
    {
        var point=requireView?InteractionRay(o).CellFace.Point:Position(o.Arguments["position"]);var result=new JsonObject {["target"]=Capture(point)};
        int id=Terrain.ExtractContents(Raw(point));if(id is 56 or 57 or 58){var other=new Point3(point.X,point.Y+(DoorBlock.IsTopPart(ST.Terrain,point.X,point.Y,point.Z)?-1:1),point.Z);result["paired_position"]=new JsonArray(other.X,other.Y,other.Z);result["paired"]=Capture(other);}
        if(Containers.Contains(id)){result["entity_id"]=Sub<SubsystemBlockEntities>().GetBlockEntity(point.X,point.Y,point.Z)?.Entity.Id;result["modal"]=OperationPlayer(o).ComponentGui.ModalPanelWidget?.GetType().FullName;}
        return result;
    }
    static void ApplyInteract(Operation o)
    {
        var p=OperationPlayer(o);
        if(o.RestoreOf!=null)
        {
            var point=Position(o.Arguments["position"]);ST.ChangeCell(point.X,point.Y,point.Z,(int)o.After["target"]["value"]);
            if(o.After["paired_position"]!=null){var other=Position(o.After["paired_position"]);ST.ChangeCell(other.X,other.Y,other.Z,(int)o.After["paired"]["value"]);}return;
        }
        var hit=InteractionRay(o);
        bool result=p.ComponentMiner.Interact(hit);
        if(p.ComponentMiner.AnyIsPending){o.PendingMiner=p.ComponentMiner;o.State="waiting_native";o.MaintenanceStarted=Now;return;}
        if(!result)throw new HostError("INTERACTION_REJECTED","Native behavior did not accept the interaction");
    }
}
