using Engine;
using System.Text.Json.Nodes;
namespace Game;
public static partial class AgentHost
{
    static bool labClimateUnavailable;
    readonly record struct ClimateColumn(int X,int Z,int Temperature,int Humidity);
    static Point2 ColumnPoint(JsonNode node)
    {if(node is not JsonArray a||a.Count!=2)throw new HostError("INVALID_ARGUMENT","X/Z pair required");int x=(int)a[0],z=(int)a[1];if(Math.Abs((long)x)>1000000||Math.Abs((long)z)>1000000)throw new HostError("INVALID_ARGUMENT","Column bounds exceeded");return new Point2(x,z);}
    static void DescribeClimate(Operation o)
    {
        Closed(o.Arguments,"minimum","maximum","temperature","humidity");var lo=ColumnPoint(o.Arguments["minimum"]);var hi=ColumnPoint(o.Arguments["maximum"]);
        long count=(long)(hi.X-lo.X+1)*(hi.Y-lo.Y+1),chunks=(long)((hi.X>>4)-(lo.X>>4)+1)*((hi.Y>>4)-(lo.Y>>4)+1);
        if(hi.X<lo.X||hi.Y<lo.Y||count>1000000||chunks>4096)throw new HostError("LIMIT_EXCEEDED","Climate limited to 1000000 columns and 4096 chunks");
        if(o.Arguments["temperature"]==null&&o.Arguments["humidity"]==null)throw new HostError("INVALID_ARGUMENT","Temperature or humidity required");
        foreach(var key in new[]{"temperature","humidity"})if(o.Arguments[key]!=null)Integer(o.Arguments,key,0,15);
        o.Risk="dangerous";o.Backup=true;o.Recovery="none";o.State="scanning";o.TotalColumns=(int)count;
    }
    static ClimateColumn ReadColumn(int x,int z)
    {
        if(labClimateUnavailable&&settings["target"]["test_only"]?.GetValue<bool>()==true)throw new HostError("REGION_NOT_LOADED","LAB simulates an existing chunk that does not finish loading; no generation");
        var c=ST.Terrain.GetChunkAtCell(x,z);if(c==null||c.State<TerrainChunkState.InvalidLight)throw new HostError("REGION_NOT_LOADED","Existing climate column must be loaded");
        return new ClimateColumn(x,z,c.GetTemperatureFast(x&15,z&15),c.GetHumidityFast(x&15,z&15));
    }
    static void TickClimateScan(Operation o)
    {
        try
        {
            Identity(o.Identity,true,false);if(o.Cancel){o.State="cancelled";PersistOperation(o);return;}
            var lo=ColumnPoint(o.Arguments["minimum"]);var hi=ColumnPoint(o.Arguments["maximum"]);int nz=hi.Y-lo.Y+1,total=(hi.X-lo.X+1)*nz;
            var timer=System.Diagnostics.Stopwatch.StartNew();for(int i=0;i<4096&&o.Climate.Count<total&&timer.Elapsed.TotalMilliseconds<4;i++){int index=o.Climate.Count;o.Climate.Add(ReadColumn(lo.X+index/nz,lo.Y+index%nz));}
            if(o.Climate.Count==total){o.State="ready";o.Created=Now;PersistOperation(o);}
        }
        catch(Exception e){o.State="failed";o.Error=new JsonObject {["code"]=e is HostError h?h.Code:"CLIMATE_ERROR",["message"]=e.Message};PersistOperation(o);}
    }
    static JsonObject ColumnJson(ClimateColumn c)=>new() {["position"]=new JsonArray(c.X,c.Z),["temperature"]=c.Temperature,["humidity"]=c.Humidity};
    static JsonNode ClimateQuery(JsonObject args,JsonObject identity)
    {Identity(identity);Closed(args,"positions");if(args["positions"] is not JsonArray points||points.Count<1||points.Count>64)throw new HostError("INVALID_ARGUMENT","1..64 X/Z columns required");return new JsonObject {["columns"]=new JsonArray(points.Select(p=>{var at=ColumnPoint(p);return (JsonNode)ColumnJson(ReadColumn(at.X,at.Y));}).ToArray()),["observed_at_utc_ms"]=Now};}
    static void TickClimateWrite(Operation o)
    {
        var updater=ST.TerrainUpdater;if(!updater.UpdateEvent.WaitOne(0)){updater.m_pauseEvent.Reset();return;}
        try
        {
            if(o.State=="waiting_region")o.State=o.ClimateWaitState;
            TickClimateWriteOwned(o);o.ClimateWaitStarted=0;
        }
        catch(HostError error)when(error.Code=="REGION_NOT_LOADED")
        {
            if(o.ClimateWaitStarted==0){o.ClimateWaitStarted=Now;o.ClimateWaitState=o.State;}
            if(Now-o.ClimateWaitStarted>10000){o.State="paused";o.Error=new JsonObject {["code"]="REGION_LOAD_TIMEOUT",["message"]="Existing columns were not ready within 10 seconds; no generation requested; inspect executed batches before a new preflight"};operationActive=null;PersistOperation(o);}
            else{o.State="waiting_region";PersistOperation(o);}
        }
        finally{updater.UpdateEvent.Set();updater.UnpauseUpdateThread();}
    }
    static void TickClimateWriteOwned(Operation o)
    {
        Identity(o.Identity,true,true);
        if(o.Cancel){o.State="cancelled";PersistOperation(o);o.Climate=[];o.ClimatePending=null;operationActive=null;return;}
        if(o.State=="persisting_climate_batch")
        {
            foreach(var c in o.ClimatePending)if(ReadColumn(c.X,c.Z)!=c)throw new HostError("CONFLICT","Column changed after snapshot persistence");
            var after=new JsonArray();var timer=System.Diagnostics.Stopwatch.StartNew();
            foreach(var c in o.ClimatePending)
            {
                var chunk=ST.Terrain.GetChunkAtCell(c.X,c.Z);if(o.Arguments["temperature"]!=null)chunk.SetTemperatureFast(c.X&15,c.Z&15,(int)o.Arguments["temperature"]);if(o.Arguments["humidity"]!=null)chunk.SetHumidityFast(c.X&15,c.Z&15,(int)o.Arguments["humidity"]);
                var read=ReadColumn(c.X,c.Z);if(o.Arguments["temperature"]!=null&&read.Temperature!=(int)o.Arguments["temperature"]||o.Arguments["humidity"]!=null&&read.Humidity!=(int)o.Arguments["humidity"])throw new HostError("READBACK_MISMATCH","Climate write verification failed");after.Add(ColumnJson(read));o.ClimateCursor++;
            }
            foreach(var c in o.ClimatePending.Select(c=>ST.Terrain.GetChunkAtCell(c.X,c.Z)).Distinct()){c.ModificationCounter++;ST.TerrainUpdater.DowngradeChunkNeighborhoodState(c.Coords,0,TerrainChunkState.InvalidVertices1,false);}
            if(timer.Elapsed.TotalMilliseconds>4)o.ClimateBatchSize=Math.Max(1,o.ClimateBatchSize/2);
            int batch=o.ClimateBatch++;var path=Path.Combine(OperationDir,o.Id,batch+".after.json");var record=OperationRecord(o);o.Persistence=Task.Run(()=>{Save(path,after);Save(Path.Combine(OperationDir,o.Id+".json"),record);});o.State="climate_running";return;
        }
        if(o.Cancel||o.ClimateCursor>=o.Climate.Count)
        {o.State=o.Cancel?"cancelled":"completed";o.After=new JsonObject {["processed"]=o.ClimateCursor,["temperature"]=o.Arguments["temperature"]?.DeepClone(),["humidity"]=o.Arguments["humidity"]?.DeepClone()};PersistOperation(o);o.Climate=[];o.ClimatePending=null;operationActive=null;return;}
        o.ClimatePending=o.Climate.Skip(o.ClimateCursor).Take(o.ClimateBatchSize).ToList();
        foreach(var c in o.ClimatePending)if(ReadColumn(c.X,c.Z)!=c)throw new HostError("STALE_PLAN","Climate changed since preflight");
        var before=new JsonArray(o.ClimatePending.Select(c=>(JsonNode)ColumnJson(c)).ToArray());var file=Path.Combine(OperationDir,o.Id,o.ClimateBatch+".before.json");
        o.State="persisting_climate_batch";var intent=OperationRecord(o);o.Persistence=Task.Run(()=>{Save(file,before);Save(Path.Combine(OperationDir,o.Id+".json"),intent);});
    }
}
