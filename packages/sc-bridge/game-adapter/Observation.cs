using Engine;
using System.Text.Json.Nodes;

namespace Game;
public static partial class AgentHost
{
    static JsonNode Observe(string op,JsonObject args,JsonObject identity)
    {
        Identity(identity,op is "teleport" or "camera" or "heading");
        var player=Sub<SubsystemPlayers>().PlayersData.Single(p=>p.PlayerIndex==(int)identity["player_index"]).ComponentPlayer;
        switch(op)
        {
            case "read_region_page":
                var minimum=Position(args["minimum"]);var maximum=Position(args["maximum"]);
                if(maximum.X<minimum.X||maximum.Y<minimum.Y||maximum.Z<minimum.Z)throw new HostError("INVALID_ARGUMENT","Reversed bounds");
                int ny=maximum.Y-minimum.Y+1,nz=maximum.Z-minimum.Z+1;
                long total=(long)(maximum.X-minimum.X+1)*ny*nz;
                int offset=(int)args["offset"],limit=(int)args["limit"];
                if(total>1000000||offset<0||offset>=total||limit<1||limit>4096)throw new HostError("LIMIT_EXCEEDED","Invalid page range");
                var page=new JsonArray();
                for(int index=offset;index<Math.Min(total,(long)offset+limit);index++)
                {
                    var q=new Point3(minimum.X+index/(ny*nz),minimum.Y+(index/nz)%ny,minimum.Z+index%nz);
                    page.Add(new JsonObject { ["position"]=new JsonArray(q.X,q.Y,q.Z),["value"]=Raw(q) });
                }
                return new JsonObject { ["cells"]=page,["total"]=total,["offset"]=offset,["next_offset"]=offset+page.Count<total?offset+page.Count:null };
            case "measure":
                var lo=Position(args["minimum"]);var hi=Position(args["maximum"]);
                if(hi.X<lo.X||hi.Y<lo.Y||hi.Z<lo.Z)throw new HostError("INVALID_ARGUMENT","Reversed bounds");
                var count=(long)(hi.X-lo.X+1)*(hi.Y-lo.Y+1)*(hi.Z-lo.Z+1);
                return new JsonObject { ["volume"]=count,["size"]=new JsonArray(hi.X-lo.X+1,hi.Y-lo.Y+1,hi.Z-lo.Z+1),["diagonal"]=Math.Sqrt(Math.Pow(hi.X-lo.X,2)+Math.Pow(hi.Y-lo.Y,2)+Math.Pow(hi.Z-lo.Z,2)) };
            case "teleport":
                var pos=Position(args["position"]);
                player.ComponentBody.Position=new Vector3(pos.X+.5f,pos.Y,pos.Z+.5f);
                player.ComponentBody.Velocity=Vector3.Zero;
                return Players();
            case "camera":
                var cp=Position(args["position"]);var target=Position(args["target"]);
                if(cp==target)throw new HostError("INVALID_ARGUMENT","Camera direction has zero length");
                var camera=new FixedCamera(player.GameWidget);
                player.GameWidget.ActiveCamera=camera;
                camera.SetupPerspectiveCamera(new Vector3(cp.X,cp.Y,cp.Z),Vector3.Normalize(new Vector3(target.X-cp.X,target.Y-cp.Y,target.Z-cp.Z)),Vector3.UnitY);
                return new JsonObject { ["mode"]="fixed",["position"]=args["position"].DeepClone(),["target"]=args["target"].DeepClone() };
            case "heading":
                double yaw=(double)args["yaw"],pitch=(double)args["pitch"];
                if(!double.IsFinite(yaw)||!double.IsFinite(pitch)||Math.Abs(yaw)>360||Math.Abs(pitch)>82)throw new HostError("INVALID_ARGUMENT","Yaw must be -360..360 and pitch -82..82 degrees");
                player.ComponentBody.Rotation=Quaternion.CreateFromAxisAngle(Vector3.UnitY,MathUtils.DegToRad((float)yaw));
                player.ComponentLocomotion.LookAngles=new Vector2(0,MathUtils.DegToRad((float)pitch));
                return new JsonObject { ["yaw"]=yaw,["pitch"]=pitch };
            case "prepare_region":
                var low=Position(args["minimum"]);var high=Position(args["maximum"]);
                if(high.X<low.X||high.Y<low.Y||high.Z<low.Z)throw new HostError("INVALID_ARGUMENT","Reversed preparation bounds");
                var volume=(long)(high.X-low.X+1)*(high.Y-low.Y+1)*(high.Z-low.Z+1);
                if(volume<1||volume>1000000)throw new HostError("LIMIT_EXCEEDED","Preparation bounded to one million volume");
                int missing=0;
                for(int x=low.X>>4;x<=high.X>>4;x++)for(int z=low.Z>>4;z<=high.Z>>4;z++)
                {var c=ST.Terrain.GetChunkAtCell(x*16,z*16);if(c==null||c.State<TerrainChunkState.InvalidLight)missing++;}
                return new JsonObject { ["ready"]=missing==0,["missing_chunks"]=missing,["generation_requested"]=false };
            case "screenshot":
                string name=Guid.NewGuid().ToString("N")+".png";
                ScreenCaptureManager.Capture(1280,720,name);
                string destination=Path.Combine((string)settings["artifacts"],"screenshots",name);
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using(var input=Storage.OpenFile(Storage.CombinePaths(ScreenCaptureManager.ScreenshotDir,name),OpenFileMode.Read))
                using(var output=File.Create(destination)) input.CopyTo(output);
                return new JsonObject { ["path"]=destination,["width"]=1280,["height"]=720 };
            default:throw new HostError("CAPABILITY_UNAVAILABLE","Observation not registered");
        }
    }
}
