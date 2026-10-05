using Engine;
using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    static List<(Point3 Point,JsonObject Cell)> interactionFixture=[];
    static Camera fixtureOldCamera;
    static Vector3 fixtureOldPosition;
    static Quaternion fixtureOldRotation;
    static Vector2 fixtureOldLook;
    static int fixtureMaxLight;
    static bool labInventoryFailure;
    static int labInventoryWrites;
    static int labJournalFail;
    static bool labEventLogFail;
    static Point3 FixturePoint=>new(-157,66,-100);
    static JsonNode InteractionLab(string op,JsonObject identity)
    {
        Identity(identity,true);var p=Sub<SubsystemPlayers>().PlayersData.Single(x=>x.PlayerIndex==(int)identity["player_index"]).ComponentPlayer;
        if(op=="lab_fixture_creature"&&Sub<SubsystemGameInfo>().WorldSettings.GameMode!=GameMode.Creative)throw new HostError("UNSUPPORTED_MODE","Creature input fixture is restricted to the creative LAB");
        if(op=="lab_journal_fail_next"){System.Threading.Interlocked.Exchange(ref labJournalFail,1);return new JsonObject {["armed"]=true};}
        if(op=="lab_event_log_fail_next"){labEventLogFail=true;return new JsonObject {["armed"]=true};}
        if(op=="lab_override_external_change"){p.ComponentLocomotion.WalkSpeed+=1;return new JsonObject {["walk_speed"]=p.ComponentLocomotion.WalkSpeed};}
        if(op=="lab_inventory_fail_second"){labInventoryFailure=true;labInventoryWrites=0;return new JsonObject {["armed"]=true};}
        if(op=="lab_inventory_failure_release"){labInventoryFailure=false;return new JsonObject {["armed"]=false};}
        if(op=="lab_pending_enable"){p.ComponentMiner.SetRequiresPending(ComponentMiner.PendingAction.Interact);return new JsonObject {["pending_enabled"]=true};}
        if(op=="lab_pending_complete")
        {bool accepted=p.ComponentMiner.ExecuteInteract(ComponentMiner.TargetMode.Pending);p.ComponentMiner.ClearRequiresPending(ComponentMiner.PendingAction.Interact);return new JsonObject {["accepted"]=accepted};}
        if(op=="lab_fixture_state")return new JsonObject {["target"]=Capture(FixturePoint),["lamp"]=Raw(new Point3(-155,66,-100)),["max_brightness"]=fixtureMaxLight,["pending"]=p.ComponentMiner.AnyIsPending,["modal"]=p.ComponentGui.ModalPanelWidget?.GetType().FullName};
        if(op=="lab_fixture_user_camera"){p.ComponentBody.Rotation=Quaternion.Identity;p.ComponentLocomotion.LookAngles=Vector2.Zero;p.GameWidget.ActiveCamera=p.GameWidget.FindCamera<FppCamera>();return new JsonObject {["camera"]="native first person"};}
        if(op=="lab_fixture_blocker")
        {if(interactionFixture.Count==0)throw new HostError("NO_FIXTURE","Create an interaction fixture first");var at=new Point3(-157,66,-99);interactionFixture.Add((at,Capture(at)));ST.ChangeCell(at.X,at.Y,at.Z,3);return new JsonObject {["obstruction"]=new JsonArray(at.X,at.Y,at.Z)};}
        if(op=="lab_fixture_far")
        {if(interactionFixture.Count==0)throw new HostError("NO_FIXTURE","Create an interaction fixture first");p.ComponentBody.Position=new Vector3(-156.5f,65,-91.5f);var farCamera=new FixedCamera(p.GameWidget);p.GameWidget.ActiveCamera=farCamera;farCamera.SetupPerspectiveCamera(p.ComponentCreatureModel.EyePosition,-Vector3.UnitZ,Vector3.UnitY);return new JsonObject {["distance_exceeds_native_reach"]=true};}
        if(op=="lab_fixture_recover")
        {
            var rows=JsonNode.Parse(File.ReadAllText(Path.Combine((string)settings["artifacts"],"interaction-fixture-before.json"))).AsArray();
            if(rows.Count!=30)throw new HostError("NO_FIXTURE","Unexpected fixture snapshot");
            foreach(var row in rows){var at=Position(row["position"]);if(at.X< -157||at.X> -153||at.Y<65||at.Y>67||at.Z< -101||at.Z> -100)throw new HostError("NO_FIXTURE","Snapshot outside fixed fixture area");}
            foreach(var row in rows)Apply(Position(row["position"]),row["cell"].AsObject());
            return new JsonObject {["restored"]=true,["pose_restored"]=false};
        }
        if(op=="lab_fixture_remove")
        {
            if(interactionFixture.Count==0)throw new HostError("NO_FIXTURE","No live fixture; use explicit LAB snapshot recovery after interruption");
            if(observationWolf?.IsAddedToProject==true)GameManager.Project.RemoveEntity(observationWolf,true);observationWolf=null;
            p.ComponentMiner.ClearRequiresPending(ComponentMiner.PendingAction.Interact);p.ComponentGui.ModalPanelWidget=null;
            foreach(var c in interactionFixture)Apply(c.Point,c.Cell);
            interactionFixture=[];if(fixtureOldCamera!=null)p.GameWidget.ActiveCamera=fixtureOldCamera;p.ComponentBody.Position=fixtureOldPosition;p.ComponentBody.Rotation=fixtureOldRotation;p.ComponentLocomotion.LookAngles=fixtureOldLook;return new JsonObject {["restored"]=true};
        }
        if(op=="lab_native_event_suite")
        {
            var miner=p.ComponentMiner;var oldInventory=miner.Inventory;var oldSlot=oldInventory.ActiveSlotIndex;int slot=0,value=oldInventory.GetSlotValue(slot),count=oldInventory.GetSlotCount(slot);float food=p.ComponentVitalStats.Food;
            var clothing=p.ComponentClothing;int clothingValue=BlocksManager.Blocks[203].GetCreativeValues().First();var clothingSlot=BlocksManager.Blocks[203].GetClothingData(clothingValue).Slot;var clothes=clothing.GetClothes(clothingSlot).ToArray();
            try
            {
                p.ComponentVitalStats.Food=.5f;oldInventory.ActiveSlotIndex=slot;oldInventory.SetSlotValue(slot,new ComponentInventoryBase.Slot {Value=177,Count=1});if(oldInventory is ComponentCreativeInventory)oldInventory.OnSlotChange(slot);
                bool used=miner.Use(new Ray3(p.ComponentCreatureModel.EyePosition,Vector3.UnitZ));
                miner.SetRequiresPending(ComponentMiner.PendingAction.Use);miner.Use(new Ray3(p.ComponentCreatureModel.EyePosition,Vector3.UnitZ));bool pendingUsed=miner.ExecuteUse(ComponentMiner.TargetMode.Pending);miner.ClearRequiresPending(ComponentMiner.PendingAction.Use);
                bool eaten=p.ComponentVitalStats.Eat(177);
                miner.Aim(new Ray3(p.ComponentCreatureModel.EyePosition,Vector3.UnitZ),AimState.InProgress);miner.Aim(new Ray3(p.ComponentCreatureModel.EyePosition,Vector3.UnitZ),AimState.Cancelled);
                clothing.SetClothes(clothingSlot,[]);clothing.ProcessSlotItems(0,clothingValue,1,1,out int processedValue,out int processedCount);bool worn=clothing.GetClothes(clothingSlot).Contains(clothingValue);clothing.SetClothes(clothingSlot,clothes);
                return new JsonObject {["native_use"]=used,["native_pending_use"]=pendingUsed,["native_eat"]=eaten,["clothing_changed"]=worn};
            }
            finally{oldInventory.ActiveSlotIndex=oldSlot;oldInventory.SetSlotValue(slot,new ComponentInventoryBase.Slot {Value=value,Count=count});if(oldInventory is ComponentCreativeInventory)oldInventory.OnSlotChange(slot);p.ComponentVitalStats.Food=food;clothing.SetClothes(clothingSlot,clothes);}
        }
        if(interactionFixture.Count>0)throw new HostError("LAB_BUSY","Remove previous interaction fixture first");
        fixtureOldCamera=p.GameWidget.ActiveCamera;fixtureOldPosition=p.ComponentBody.Position;fixtureOldRotation=p.ComponentBody.Rotation;fixtureOldLook=p.ComponentLocomotion.LookAngles;fixtureMaxLight=0;
        foreach(var point in Area(new Point3(-157,65,-101),new Point3(-153,67,-100)))interactionFixture.Add((point,Capture(point)));
        Save(Path.Combine((string)settings["artifacts"],"interaction-fixture-before.json"),new JsonArray(interactionFixture.Select(c=>(JsonNode)new JsonObject {["position"]=new JsonArray(c.Point.X,c.Point.Y,c.Point.Z),["cell"]=c.Cell.DeepClone()}).ToArray()));
        foreach(var c in interactionFixture)ST.ChangeCell(c.Point.X,c.Point.Y,c.Point.Z,0);
        for(int x=-157;x<=-153;x++)for(int y=65;y<=67;y++)ST.ChangeCell(x,y,-101,3);
        Point3 target=FixturePoint;
        int block=op switch {"lab_fixture_creature"=>0,"lab_fixture_door"=>56,"lab_fixture_trapdoor"=>83,"lab_fixture_switch"=>141,"lab_fixture_button"=>142,"lab_fixture_container"=>45,_=>throw new HostError("LAB_DISABLED","Unknown fixture")};
        if(block==56){ST.ChangeCell(-157,65,-100,56);ST.ChangeCell(-157,66,-100,56);}
        else ST.ChangeCell(target.X,target.Y,target.Z,block);
        if(block is 141 or 142){ST.ChangeCell(-156,66,-100,WireBlock.SetWireFacesBitmask(133,1));ST.ChangeCell(-155,66,-100,139);}
        p.ComponentBody.Position=new Vector3(-156.5f,65,-97.5f);p.ComponentBody.Velocity=Vector3.Zero;
        var camera=new FixedCamera(p.GameWidget);p.GameWidget.ActiveCamera=camera;
        var eye=p.ComponentCreatureModel.EyePosition;var aim=new Vector3(target.X+.5f,target.Y+(block==83?.1f:.5f),target.Z+.5f);
        camera.SetupPerspectiveCamera(eye,Vector3.Normalize(aim-eye),Vector3.UnitY);
        if(op=="lab_fixture_creature")
        {if(observationWolf!=null)throw new HostError("LAB_BUSY","Creature fixture already exists");observationWolf=DatabaseManager.CreateEntity(GameManager.Project,"Wolf",true);observationWolf.FindComponent<ComponentBody>(true).Position=new Vector3(-156.5f,65,-99.5f);GameManager.Project.AddEntity(observationWolf);p.ComponentBody.Rotation=Quaternion.Identity;p.ComponentLocomotion.LookAngles=new Vector2(0,-.35f);p.GameWidget.ActiveCamera=p.GameWidget.FindCamera<FppCamera>();}
        return new JsonObject {["target"]=new JsonArray(target.X,target.Y,target.Z),["block"]=block,["camera_origin"]=new JsonArray(eye.X,eye.Y,eye.Z),["expected_source"]="agent via operation_submit"};
    }
    static void TickInteractionLab()
    {if(interactionFixture.Count>0&&GameManager.Project!=null)try{fixtureMaxLight=Math.Max(fixtureMaxLight,LightbulbBlock.GetLightIntensity(Terrain.ExtractData(Raw(new Point3(-155,66,-100)))));}catch{}}
}
