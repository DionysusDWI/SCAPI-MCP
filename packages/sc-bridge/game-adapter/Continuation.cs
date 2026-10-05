using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Nodes;
using Engine;
namespace Game;
public static partial class AgentHost
{
    static JsonObject PreflightMetadata(List<JsonObject> cells,int requiredDesigns)
    {
        int[] low={int.MaxValue,int.MaxValue,int.MaxValue},high={int.MinValue,int.MinValue,int.MinValue};var resources=new HashSet<string>();
        foreach(var cell in cells)
        {
            for(int axis=0;axis<3;axis++){int v=(int)cell["position"][axis];low[axis]=Math.Min(low[axis],v);high[axis]=Math.Max(high[axis],v);}
            if(cell["after"]["resource"]?["kind"] is JsonValue kind)resources.Add(kind.GetValue<string>());
        }
        return new JsonObject { ["affected_minimum"]=cells.Count==0?null:new JsonArray(low[0],low[1],low[2]),["affected_maximum"]=cells.Count==0?null:new JsonArray(high[0],high[1],high[2]),["estimated_modifications"]=cells.Count,["resource_types"]=new JsonArray(resources.Select(k=>JsonValue.Create(k)).ToArray()),["new_furniture_designs"]=requiredDesigns,["dependencies"]=new JsonArray("API/1.9.3.2","zh.command/4.1.8"),["recovery"]="local_compare_and_set",["blockers"]=new JsonArray() };
    }
    static void PersistPlan(Plan p)
    {
        string path=Path.Combine(JobsDir,p.Id,"plan.json.gz");
        var cells=p.Cells;var source=p.Source;var identity=p.Identity;var arguments=p.Arguments;
        p.FileWork=Task.Run(()=>
        {
            p.Metadata=PreflightMetadata(cells,p.RequiredFurnitureDesigns);
            using(var file=new FileStream(path+".tmp",FileMode.Create,FileAccess.Write,FileShare.None))
            {
                using(var compressed=new GZipStream(file,CompressionLevel.Fastest,true))
                using(var writer=new Utf8JsonWriter(compressed))
                {
                    writer.WriteStartObject();writer.WritePropertyName("identity");identity.WriteTo(writer);
                    writer.WritePropertyName("arguments");arguments.WriteTo(writer);writer.WritePropertyName("cells");writer.WriteStartArray();
                    foreach(var cell in cells)cell.WriteTo(writer);writer.WriteEndArray();
                    writer.WritePropertyName("source");writer.WriteStartArray();
                    foreach(var cell in source)new JsonObject { ["position"]=new JsonArray(cell.Key.X,cell.Key.Y,cell.Key.Z),["data"]=cell.Value.DeepClone() }.WriteTo(writer);
                    writer.WriteEndArray();writer.WriteEndObject();writer.Flush();
                }
                file.Flush(true);
            }
            File.Move(path+".tmp",path,true);
            using var input=File.OpenRead(path);File.WriteAllText(path+".sha256",Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(input)).ToLowerInvariant());
        });
        p.State="persisting_plan";
    }
    static JsonObject ContinueJob(string id,JsonObject identity)
    {
        if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
        if(!Guid.TryParseExact(id,"N",out _))throw new HostError("INVALID_ARGUMENT","Invalid job identity");
        string folder=Path.Combine(JobsDir,id);var record=JsonNode.Parse(File.ReadAllText(Path.Combine(folder,"job.json")));
        if((string)record["state"] is "completed" or "restored")throw new HostError("JOB_FINISHED","Finished jobs cannot be continued");
        foreach(var key in new[]{"directory","name","world_token"})if((string)identity[key]!=(string)record["identity"][key])throw new HostError("WRONG_WORLD","Continuation belongs to another world");
        string file=Path.Combine(folder,"plan.json.gz");if(!File.Exists(file))throw new HostError("NO_CONTINUATION","Historical job has no complete durable plan; restore instead");
        var p=new Plan { Id=id,Identity=identity.DeepClone().AsObject(),State="loading_resume",Kind="resume",Batch=Directory.EnumerateFiles(folder,"batch-*.json").Count() };
        p.ImportWork=Task.Run(()=>{using(var input=File.OpenRead(file))if(Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(input)).ToLowerInvariant()!=File.ReadAllText(file+".sha256"))throw new HostError("PLAN_CHECKSUM","Durable continuation plan was changed");using var stream=new GZipStream(File.OpenRead(file),CompressionMode.Decompress);return JsonNode.Parse(stream).AsObject();});
        plans[id]=p;active=id;Record(p);return Summary(p);
    }
    static IEnumerable<Point3> ResumeScan(Plan p,JsonObject data)
    {
        var cells=data["cells"].AsArray();if(cells.Count>1000000)throw new HostError("LIMIT_EXCEEDED","Continuation exceeds one million cells");
        var desired=new Dictionary<Point3,JsonNode>();
        foreach(var cell in cells)
        {
            var point=Position(cell["position"]);if(!desired.TryAdd(point,cell["after"]))throw new HostError("INVALID_PLAN","Duplicate continuation coordinate");
            var current=Capture(point);
            if(!CellEquals(current,cell["after"]))
            {
                if(!CellEquals(current,cell["before"]))throw new HostError("CONFLICT","Interrupted operation conflicts with current data");
                var after=cell["after"].DeepClone().AsObject();ValidateResourceValue((int)after["value"],after["resource"]);ReserveResources(p,after);
                p.Cells.Add(new JsonObject { ["position"]=cell["position"].DeepClone(),["before"]=current,["after"]=after });
            }
            yield return point;
        }
        foreach(var source in data["source"].AsArray())
        {
            var point=Position(source["position"]);var current=Capture(point);
            if(!CellEquals(current,source["data"])&&(!desired.TryGetValue(point,out var after)||!CellEquals(current,after)))throw new HostError("STALE_PLAN","Source changed since original preflight");
            yield return point;
        }
    }
}
