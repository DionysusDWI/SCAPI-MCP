using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Engine;

namespace Game;
public static partial class AgentHost
{
    static string TemplateDir=>Path.Combine((string)settings["artifacts"],"templates");
    static string TemplatePath(string id)
    {
        if(!Guid.TryParseExact(id,"N",out _))throw new HostError("INVALID_ARGUMENT","Template identity must be UUID");
        return Path.Combine(TemplateDir,id+".scblueprint");
    }
    static JsonObject BeginExport(JsonObject args,JsonObject identity)
    {
        if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
        var p=new Plan { Identity=identity.DeepClone().AsObject(),Arguments=new JsonObject { ["action"]="export",["minimum"]=args["minimum"].DeepClone(),["maximum"]=args["maximum"].DeepClone() },Kind="export" };
        p.Scan=Area(Position(args["minimum"]),Position(args["maximum"])).GetEnumerator();
        p.FilePath=TemplatePath(p.Id);plans.Add(p.Id,p);active=p.Id;Record(p);return Summary(p);
    }
    static void FinishExport(Plan p)
    {
        var dependencies=new JsonArray();
        foreach(var m in ModsManager.ModList.Where(m=>m.modInfo.PackageName=="zh.command"))dependencies.Add(new JsonObject { ["package"]=m.modInfo.PackageName,["version"]=m.modInfo.Version });
        var origin=Position(p.Arguments["minimum"]);
        // Plain immutable records cross the worker boundary, never terrain/entities.
        var source=p.Source;
        var path=p.FilePath;
        var manifest=new JsonObject { ["format"]="scblueprint",["format_version"]=1,["protocol"]=3,["api"]="1.9.3.2",["dependencies"]=dependencies,["count"]=source.Count };
        p.FileWork=Task.Run(()=>
        {
            var cells=new JsonArray();
            var counts=new Dictionary<int,int>();var resources=new Dictionary<string,int>();
            foreach(var entry in source)
            {
                var q=entry.Key-origin;cells.Add(new JsonObject { ["position"]=new JsonArray(q.X,q.Y,q.Z),["data"]=entry.Value.DeepClone() });
                int value=(int)entry.Value["value"];counts[value]=counts.GetValueOrDefault(value)+1;
                var kind=(string)entry.Value["resource"]?["kind"];if(kind!=null)resources[kind]=resources.GetValueOrDefault(kind)+1;
            }
            var materials=new JsonObject();foreach(var c in counts)materials[c.Key.ToString()]=c.Value;
            var kinds=new JsonObject();foreach(var c in resources)kinds[c.Key]=c.Value;
            manifest["material_counts"]=materials;manifest["resource_counts"]=kinds;
            var bytes=Encoding.UTF8.GetBytes(cells.ToJsonString());
            manifest["cells_sha256"]=Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            using(var archive=ZipFile.Open(path+".tmp",ZipArchiveMode.Create))
            {
                using(var stream=archive.CreateEntry("cells.json").Open())stream.Write(bytes);
                using(var writer=new StreamWriter(archive.CreateEntry("manifest.json").Open()))writer.Write(manifest.ToJsonString());
            }
            File.Move(path+".tmp",path,true);
        });
        p.State="exporting";Record(p);
    }
    static JsonObject ReadBlueprint(string path)
    {
        using var archive=ZipFile.OpenRead(path);
        if(archive.Entries.Count!=2||archive.GetEntry("manifest.json")==null||archive.GetEntry("cells.json")==null)throw new HostError("INVALID_TEMPLATE","Unexpected package entries");
        if(archive.GetEntry("manifest.json").Length>65536||archive.GetEntry("cells.json").Length>256*1024*1024)throw new HostError("LIMIT_EXCEEDED","Template decompression size exceeds limit");
        using var reader=new StreamReader(archive.GetEntry("manifest.json").Open());
        var manifest=JsonNode.Parse(reader.ReadToEnd()).AsObject();
        if((string)manifest["format"]!="scblueprint"||(int)manifest["format_version"]!=1||(int)manifest["protocol"]!=3||(string)manifest["api"]!="1.9.3.2")throw new HostError("INCOMPATIBLE_TEMPLATE","Template version mismatch");
        using var memory=new MemoryStream();using(var stream=archive.GetEntry("cells.json").Open())stream.CopyTo(memory);
        var bytes=memory.ToArray();
        if(Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant()!=(string)manifest["cells_sha256"])throw new HostError("TEMPLATE_CHECKSUM","Template checksum failed");
        var cells=JsonNode.Parse(bytes).AsArray();
        if(cells.Count!=(int)manifest["count"]||cells.Count<1||cells.Count>1000000)throw new HostError("INVALID_TEMPLATE","Template cell count differs");
        var seen=new HashSet<string>();
        foreach(var entry in cells)
        {
            if(entry is not JsonObject cell || cell.Count!=2 || cell["position"] is not JsonArray position || position.Count!=3 || cell["data"] is not JsonObject data || data.Any(k=>k.Key is not ("value" or "resource")))throw new HostError("INVALID_TEMPLATE","Unexpected cell fields");
            foreach(var coordinate in position)
                if(coordinate is not JsonValue number || !number.TryGetValue<int>(out int value) || value<0 || value>1000000)throw new HostError("INVALID_TEMPLATE","Relative coordinates must be nonnegative bounded integers");
            if(data["value"] is not JsonValue packed || !packed.TryGetValue<int>(out int blockValue) || blockValue<0)throw new HostError("INVALID_TEMPLATE","Invalid block value");
            if(!seen.Add(position.ToJsonString()))throw new HostError("INVALID_TEMPLATE","Duplicate cell coordinate");
        }
        return new JsonObject { ["manifest"]=manifest,["cells"]=cells };
    }
    static JsonObject BeginImport(JsonObject args,JsonObject identity)
    {
        if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
        var path=TemplatePath((string)args["template_id"]);Position(args["destination"]);
        var p=new Plan { Identity=identity.DeepClone().AsObject(),Arguments=args.DeepClone().AsObject(),State="loading_template",Kind="import",ImportWork=Task.Run(()=>ReadBlueprint(path)) };
        plans.Add(p.Id,p);active=p.Id;Record(p);return Summary(p);
    }
    static IEnumerable<Point3> ImportScan(Plan p,JsonObject data)
    {
        var origin=Position(p.Arguments["destination"]);var seen=new HashSet<Point3>();
        foreach(var cell in data["cells"].AsArray())
        {
            var a=cell["position"].AsArray();var point=origin+new Point3((int)a[0],(int)a[1],(int)a[2]);
            Position(new JsonArray(point.X,point.Y,point.Z));
            if(!seen.Add(point))throw new HostError("INVALID_TEMPLATE","Duplicate cell coordinate");
            var desired=cell["data"].DeepClone().AsObject();ValidateResourceValue((int)desired["value"],desired["resource"]);
            ReserveResources(p,desired);
            p.Cells.Add(new JsonObject { ["position"]=new JsonArray(point.X,point.Y,point.Z),["before"]=Capture(point),["after"]=desired });
            yield return point;
        }
    }
}
