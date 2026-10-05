using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Engine;

namespace Game;

public static partial class AgentHost
{
    sealed class Plan
    {
        public string Id=Guid.NewGuid().ToString("N"),State="scanning",Error;
        public JsonObject Identity,Arguments;
        public List<JsonObject> Cells=[];
        public IEnumerator<Point3> Scan;
        public int Cursor;
        public long Created=Now;
        public bool Cancel;
        public string Kind="construction";
        public int Batch;
        public double MaxBatchMs;
        public Dictionary<Point3,JsonObject> Source=[];
        public bool CopyPlanning;
        public Task FileWork;
        public Task<JsonObject> ImportWork;
        public string FilePath;
        public string RestoreOf;
        public HashSet<string> FurnitureContents=[];
        public int RequiredFurnitureDesigns;
        public int BatchLimit=128;
        public JsonArray PendingBatch;
        public Task JournalTask;
        public long RecordedAt;
        public int CompletedCells;
        public JsonObject Metadata;
        public string WaitingState;
        public Point3 WaitingPoint;
        public long WaitingDeadline;
    }
    static readonly Dictionary<string,Plan> plans=[];
    static string active;
    static string checkedBackup;
    static long checkedLength,checkedTicks;
    static Point3 unloadedPoint;
    static SubsystemTerrain ST => GameManager.Project.FindSubsystem<SubsystemTerrain>(true);
    static void VerifyBackup(string path)
    {
        var info=new FileInfo(path);
        if(path==checkedBackup&&info.Length==checkedLength&&info.LastWriteTimeUtc.Ticks==checkedTicks) return;
        using var stream=File.OpenRead(path);
        var hash=Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        if(hash!=(string)settings["target"]["backup_sha256"]) throw new HostError("BACKUP_MISMATCH","Backup checksum mismatch");
        checkedBackup=path; checkedLength=info.Length; checkedTicks=info.LastWriteTimeUtc.Ticks;
    }
    static string JobsDir=>Path.Combine(root,"jobs");
    static JsonObject Summary(Plan p)=>new() { ["job_id"]=p.Id,["plan_id"]=p.Id,["state"]=p.State,["processed"]=p.Cursor,["cells"]=Math.Max(p.CompletedCells,p.Cells.Count),["error"]=p.Error,["batch_count"]=p.Batch,["max_batch_ms"]=p.MaxBatchMs,["recovery"]="local_compare_and_set",["preflight"]=p.Metadata?.DeepClone(),["expires"]=p.Created+120000,["file"]=p.FilePath,["working_set_bytes"]=System.Diagnostics.Process.GetCurrentProcess().WorkingSet64,["frame_seconds"]=Time.FrameDuration };
    static void Record(Plan p)
    {
        var record=Summary(p);record["boot"]=Boot;record["identity"]=p.Identity.DeepClone();record["kind"]=p.Kind;
        Save(Path.Combine(JobsDir,p.Id,"job.json"),record);
        p.RecordedAt=Now;
    }
    static int Raw(Point3 p)
    {
        var chunk=ST.Terrain.GetChunkAtCell(p.X,p.Z);
        if(chunk==null||chunk.State<TerrainChunkState.InvalidLight){unloadedPoint=p;throw new HostError("REGION_NOT_LOADED","Unloaded region is never treated as air");}
        return Terrain.ReplaceLight(ST.Terrain.GetCellValue(p.X,p.Y,p.Z),0);
    }
    static IEnumerable<Point3> Area(Point3 lo,Point3 hi)
    {
        var volume=(long)(hi.X-lo.X+1)*(hi.Y-lo.Y+1)*(hi.Z-lo.Z+1);
        if(hi.X<lo.X||hi.Y<lo.Y||hi.Z<lo.Z||volume>1000000) throw new HostError("LIMIT_EXCEEDED","Inclusive region volume must be 1..1000000");
        for(int x=lo.X;x<=hi.X;x++)for(int y=lo.Y;y<=hi.Y;y++)for(int z=lo.Z;z<=hi.Z;z++)yield return new Point3(x,y,z);
    }
    static void SafeBlock(int value,bool allowPhysics=false)
    {
        if(value<0)throw new HostError("INVALID_ARGUMENT","Packed value must be nonnegative int32");
        int id=Terrain.ExtractContents(value);
        if(id>=BlocksManager.Blocks.Length||BlocksManager.Blocks[id]==null||BlocksManager.Blocks[id].BlockIndex!=id) throw new HostError("UNKNOWN_BLOCK","Block is absent");
        var assembly=BlocksManager.Blocks[id].GetType().Assembly.GetName().Name;
        if(assembly!="Survivalcraft"&&assembly!="CommandBlock") throw new HostError("UNKNOWN_MOD_RESOURCE","Unregistered mod block");
        if(!allowPhysics && (BlocksManager.Blocks[id] is FluidBlock or GunpowderKegBlock || BlocksManager.Blocks[id].IsCollapsable))throw new HostError("UNREGISTERED_PHYSICS","Flow, collapse and explosion are outside registered local recovery");
    }
    static JsonNode ExecuteBuilding(string op,JsonObject args,JsonObject identity)
    {
        if(op=="capabilities") return settings["capabilities"]?.DeepClone()??new JsonArray();
        if(op=="materials")
        {
            var result=new JsonArray();
            for(int i=0;i<BlocksManager.Blocks.Length;i++)if(BlocksManager.Blocks[i]!=null&&BlocksManager.Blocks[i].BlockIndex==i) result.Add(new JsonObject { ["id"]=i,["type"]=BlocksManager.Blocks[i].GetType().FullName,["assembly"]=BlocksManager.Blocks[i].GetType().Assembly.GetName().Name,["collidable"]=BlocksManager.Blocks[i].IsCollidable,["transparent"]=BlocksManager.Blocks[i].IsTransparent,["density"]=float.IsFinite(BlocksManager.Blocks[i].Density)?BlocksManager.Blocks[i].Density:null,["dig_resilience"]=float.IsFinite(BlocksManager.Blocks[i].DigResilience)?BlocksManager.Blocks[i].DigResilience:null });
            return result;
        }
        if(op=="interrupted_jobs")
        {
            var result=new JsonArray();
            if(Directory.Exists(JobsDir))foreach(var path in Directory.EnumerateFiles(JobsDir,"job.json",SearchOption.AllDirectories))
            { var j=JsonNode.Parse(File.ReadAllText(path)); if((string)j["boot"]!=Boot && (string)j["state"] is not ("completed" or "restored")) result.Add(j); }
            return result;
        }
        if(operationActive!=null&&op is not ("job_status" or "resource_query" or "measure" or "cancel_job"))throw new HostError("WORLD_BUSY","Non-building operation is active");
        Identity(identity,op is not ("job_status" or "resource_query" or "measure"));
        switch(op)
        {
            case "template_export":return BeginExport(args,identity);
            case "template_import":return BeginImport(args,identity);
            case "resource_query": return Capture(Position(args["position"]));
            case "preflight":
                if(active!=null)throw new HostError("WORLD_BUSY","World mutations are serial");
                var lo=Position(args["minimum"]);var hi=Position(args["maximum"]);
                var action=(string)args["action"];
                if(action is not ("fill" or "clear" or "replace" or "copy" or "move" or "geometry" or "resource")) throw new HostError("UNREGISTERED_COMMAND","Action is not registered");
                if(args.Any(k=>k.Key is not ("minimum" or "maximum" or "action" or "value" or "match" or "destination" or "rotation" or "mirror" or "shape" or "hollow" or "resource")))throw new HostError("INVALID_ARGUMENT","Unknown action argument");
                if(action is not ("copy" or "move"))SafeBlock(action=="clear"?0:(int)args["value"]);
                if(action is "copy" or "move")
                {
                    Position(args["destination"]);
                    int rotation=args["rotation"]==null?0:(int)args["rotation"];
                    if(rotation is not (0 or 90 or 180 or 270))throw new HostError("INVALID_ARGUMENT","Y rotation must be 0,90,180,270");
                    if(args["mirror"]!=null&&(string)args["mirror"] is not ("x" or "z" or "none"))throw new HostError("INVALID_ARGUMENT","Mirror must be x,z,none");
                }
                if(action=="geometry" && (string)args["shape"] is not ("line" or "cuboid" or "sphere" or "cylinder" or "cone"))throw new HostError("INVALID_ARGUMENT","Unknown geometry");
                var p=new Plan { Identity=identity.DeepClone().AsObject(),Arguments=args.DeepClone().AsObject(),Scan=Area(lo,hi).GetEnumerator() };
                plans.Add(p.Id,p);active=p.Id; Record(p);return Summary(p);
            case "job_status": return Summary(Find((string)args["job_id"]));
            case "submit":
                if(operationActive!=null)throw new HostError("WORLD_BUSY","Non-building operation is active");
                var submit=Find((string)args["plan_id"]);
                if(submit.State!="ready"||Now-submit.Created>120000)throw new HostError("STALE_PLAN","Plan is not ready or has expired");
                if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
                if(!JsonNode.DeepEquals(identity,submit.Identity))throw new HostError("IDENTITY_MISMATCH","Plan identity changed");
                if(submit.RequiredFurnitureDesigns>Sub<SubsystemFurnitureBlockBehavior>().m_furnitureDesigns.Count(d=>d==null))throw new HostError("RESOURCE_CAPACITY","Furniture capacity changed after preflight");
                submit.State=submit.Source.Count>0?"validating_source":"running";
                if(submit.Source.Count>0)submit.Scan=VerifySource(submit).GetEnumerator();
                submit.Cursor=0;active=submit.Id;Record(submit);return Summary(submit);
            case "cancel_job":
                var cancel=Find((string)args["job_id"]);cancel.Cancel=true;return Summary(cancel);
            case "restore_job": return PrepareRestore((string)args["job_id"],identity);
            case "resume_job": return ContinueJob((string)args["job_id"],identity);
            case "modify_cells":
                if(operationActive!=null)throw new HostError("WORLD_BUSY","Non-building operation is active");
                if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
                var changes=args["changes"].AsArray();
                if(changes.Count<1||changes.Count>64)throw new HostError("LIMIT_EXCEEDED","Direct changes limited to 64");
                var direct=new Plan { Id=(string)args["operation_id"],Identity=identity.DeepClone().AsObject(),State="running" };
                var seen=new HashSet<Point3>();
                foreach(var c in changes)
                {
                    var point=Position(c["position"]);if(!seen.Add(point))throw new HostError("INVALID_ARGUMENT","Duplicate coordinate");
                    var before=Capture(point);if((int)before["value"]!=(int)c["expected"])throw new HostError("CONFLICT","Original value changed");
                    SafeBlock((int)c["value"]);
                    var after=Desired((int)c["value"]);
                    direct.Cells.Add(new JsonObject { ["position"]=c["position"].DeepClone(),["before"]=before,["after"]=after });
                }
                plans.Add(direct.Id,direct);active=direct.Id;Record(direct);return Summary(direct);
            case "restore_operation": return PrepareRestore((string)args["operation_id"],identity);
            default:throw new HostError("CAPABILITY_UNAVAILABLE","Unregistered capability: "+op);
        }
    }
    static Plan Find(string id)
    {
        if(id==null||!Guid.TryParseExact(id,"N",out _)||!plans.TryGetValue(id,out var p))throw new HostError("NO_JOB","Job does not exist in this boot");
        return p;
    }
    static JsonObject PrepareRestore(string id,JsonObject identity)
    {
        if(active!=null)throw new HostError("WORLD_BUSY","World is busy");
        if(!Guid.TryParseExact(id,"N",out _))throw new HostError("INVALID_ARGUMENT","Invalid job identity");
        var folder=Path.Combine(JobsDir,id);
        var j=JsonNode.Parse(File.ReadAllText(Path.Combine(folder,"job.json")));
        foreach(var key in new[]{"directory","name","world_token"})if((string)identity[key]!=(string)j["identity"][key])throw new HostError("WRONG_WORLD","Recovery belongs to another world");
        var restore=new Plan { Identity=identity.DeepClone().AsObject(),State="loading_restore",Kind="restore",RestoreOf=id };
        restore.ImportWork=Task.Run(()=>
        {
            var cells=new JsonArray();var seen=new HashSet<string>();
            foreach(var file in Directory.EnumerateFiles(folder,"batch-*.json").OrderDescending())
                foreach(var cell in JsonNode.Parse(File.ReadAllText(file)).AsArray().Reverse())
                    if(seen.Add(cell["position"].ToJsonString()))cells.Add(cell.DeepClone());
            return new JsonObject { ["cells"]=cells };
        });
        plans.Add(restore.Id,restore);active=restore.Id;Record(restore);return Summary(restore);
    }
    static void TickJobs()
    {
        if(active==null)return;
        var p=plans[active];var watch=Stopwatch.StartNew();
        TerrainUpdater terrainUpdater=null;bool terrainOwned=false;
        try
        {
            Identity(p.Identity,true);
            terrainUpdater=ST.TerrainUpdater;
            if(!terrainUpdater.UpdateEvent.WaitOne(0))
            {terrainUpdater.m_pauseEvent.Reset();return;}
            terrainOwned=true;
            if(p.Cancel)
            {
                if(p.JournalTask!=null&&!p.JournalTask.IsCompleted || p.State=="persisting_plan"&&p.FileWork!=null&&!p.FileWork.IsCompleted)return;
                p.CompletedCells=p.Cells.Count;p.Cells.Clear();p.Source.Clear();p.Scan=null;p.PendingBatch=null;p.JournalTask=null;
                p.State="cancelled";active=null;Record(p);return;
            }
            if(p.State=="waiting_region")
            {
                var chunk=ST.Terrain.GetChunkAtCell(p.WaitingPoint.X,p.WaitingPoint.Z);
                if(chunk==null||chunk.State<TerrainChunkState.InvalidLight)
                {if(Now>=p.WaitingDeadline)throw new HostError("REGION_TIMEOUT","Existing region did not load within 10 seconds; no generation requested");return;}
                p.State=p.WaitingState;p.Error=null;
                if(p.State=="validating_source")p.Scan=VerifySource(p).GetEnumerator();
                else if(p.State=="scanning")
                {
                    // An iterator that threw cannot be continued. Re-preflight the
                    // whole read-only scan; no partially captured cells are trusted.
                    p.Cells.Clear();p.Source.Clear();p.FurnitureContents.Clear();p.RequiredFurnitureDesigns=0;
                    p.CopyPlanning=p.Kind is "restore" or "resume" or "import";
                    p.Scan=p.Kind switch {
                        "restore"=>RecoveryScan(p,p.ImportWork.GetAwaiter().GetResult()).GetEnumerator(),
                        "resume"=>ResumeScan(p,p.ImportWork.GetAwaiter().GetResult()).GetEnumerator(),
                        "import"=>ImportScan(p,p.ImportWork.GetAwaiter().GetResult()).GetEnumerator(),
                        _=>Area(Position(p.Arguments["minimum"]),Position(p.Arguments["maximum"])).GetEnumerator() };
                }
                Record(p);
            }
            if(p.State=="loading_resume")
            {if(!p.ImportWork.IsCompleted)return;p.Scan=ResumeScan(p,p.ImportWork.GetAwaiter().GetResult()).GetEnumerator();p.CopyPlanning=true;p.State="scanning";}
            if(p.State=="persisting_plan")
            {if(!p.FileWork.IsCompleted)return;p.FileWork.GetAwaiter().GetResult();p.Created=Now;p.State="ready";active=null;Record(p);return;}
            if(p.State=="validating_source")
            {
                int nchecked=0;
                while(nchecked++<4096&&watch.Elapsed.TotalMilliseconds<4)
                    if(!p.Scan.MoveNext()){p.State="running";break;}
                return;
            }
            if(p.State=="loading_restore")
            {
                if(!p.ImportWork.IsCompleted)return;
                p.Scan=RecoveryScan(p,p.ImportWork.GetAwaiter().GetResult()).GetEnumerator();p.CopyPlanning=true;p.State="scanning";
            }
            if(p.State=="exporting")
            {
                if(!p.FileWork.IsCompleted)return;
                p.FileWork.GetAwaiter().GetResult();p.State="completed";active=null;Record(p);return;
            }
            if(p.State=="loading_template")
            {
                if(!p.ImportWork.IsCompleted)return;
                var data=p.ImportWork.GetAwaiter().GetResult();
                foreach(var d in data["manifest"]["dependencies"].AsArray())
                    if(!ModsManager.ModList.Any(m=>m.modInfo.PackageName==(string)d["package"]&&m.modInfo.Version==(string)d["version"]))throw new HostError("MISSING_DEPENDENCY","Template dependency absent or incompatible");
                p.Scan=ImportScan(p,data).GetEnumerator();p.CopyPlanning=true;p.State="scanning";
            }
            if(p.State=="scanning")
            {
                int count=0;
                while(count++<4096 && watch.Elapsed.TotalMilliseconds<4)
                {
                    if(!p.Scan.MoveNext())
                    {
                        if(p.Kind=="restore"){p.State="running";p.Cursor=0;Record(p);return;}
                        if(p.Kind=="export") { FinishExport(p);return; }
                        if(!p.CopyPlanning && (string)p.Arguments["action"] is "copy" or "move")
                        { p.CopyPlanning=true;p.Scan=CopyScan(p).GetEnumerator();return; }
                        if(p.Kind=="resume")
                        {p.FileWork=Task.Run(()=>{p.Metadata=PreflightMetadata(p.Cells,p.RequiredFurnitureDesigns);});p.State="persisting_plan";Record(p);return;}
                        PersistPlan(p);Record(p);return;
                    }
                    if(p.CopyPlanning)continue;
                    var point=p.Scan.Current;var before=Capture(point);var action=(string)p.Arguments["action"];
                    if(p.Kind=="export"){p.Source.Add(point,before);continue;}
                    if(action is "copy" or "move"){p.Source.Add(point,before);continue;}
                    if(action=="geometry"&&!InsideShape(point,p.Arguments))continue;
                    if(action=="replace"&&(int)before["value"]!=(int)p.Arguments["match"])continue;
                    int value=action=="clear"?0:(int)p.Arguments["value"];
                    var after=Desired(value,action=="resource"?p.Arguments["resource"]:null);
                    ReserveResources(p,after);
                    p.Cells.Add(new JsonObject { ["position"]=new JsonArray(point.X,point.Y,point.Z),["before"]=before,["after"]=after });
                }
                return;
            }
            if(p.PendingBatch==null && p.Cursor<p.Cells.Count)
            {
                var batch=new JsonArray();int limit=Math.Min(p.BatchLimit,p.Cells.Count-p.Cursor);
                for(int i=0;i<limit;i++)
                {
                    var cell=p.Cells[p.Cursor+i];
                    if(!CellEquals(Capture(Position(cell["position"])),cell["before"]))throw new HostError("CONFLICT","Preflight state changed before batch");
                    ValidateResourceValue((int)cell["after"]["value"],cell["after"]["resource"]);batch.Add(cell.DeepClone());
                    if(watch.Elapsed.TotalMilliseconds>=1.5)break;
                }
                string path=Path.Combine(JobsDir,p.Id,$"batch-{p.Batch:D6}.json");
                p.PendingBatch=batch;p.JournalTask=Task.Run(()=>Save(path,batch));return;
            }
            var selected=p.PendingBatch;int n=selected?.Count??0;
            if(n>0)
            {
                if(!p.JournalTask.IsCompleted)return;p.JournalTask.GetAwaiter().GetResult(); // Flush completed before any game mutation.
                int done=0;
                foreach(var cell in selected)
                {
                    var point=Position(cell["position"]);
                    if(!CellEquals(Capture(point),cell["before"]))throw new HostError("CONFLICT","Cell changed while durable journal was being written");
                    Apply(point,cell["after"].AsObject());
                    if(!CellEquals(Capture(point),cell["after"]))throw new HostError("VERIFY_FAILED","Post-write verification failed");
                    done++;if(watch.Elapsed.TotalMilliseconds>=4)break;
                }
                // The durable batch contains untouched trailing cells. Recovery skips those.
                p.Cursor+=done;p.Batch++;p.MaxBatchMs=Math.Max(p.MaxBatchMs,watch.Elapsed.TotalMilliseconds);
                double perCell=watch.Elapsed.TotalMilliseconds/Math.Max(1,done);
                p.BatchLimit=Math.Clamp((int)(2.5/Math.Max(.001,perCell)),1,4096);
                p.PendingBatch=null;p.JournalTask=null;
            }
            if(p.Cursor==p.Cells.Count)
            {
                p.State=p.Kind=="restore"?"restored":"completed";active=null;
                if(p.RestoreOf!=null)
                {
                    var original=Path.Combine(JobsDir,p.RestoreOf,"job.json");var j=JsonNode.Parse(File.ReadAllText(original));j["state"]="restored";j["restore_job_id"]=p.Id;Save(original,j);
                    if(plans.TryGetValue(p.RestoreOf,out var prior))
                    {prior.CompletedCells=Math.Max(prior.CompletedCells,prior.Cells.Count);prior.Cells.Clear();prior.Source.Clear();prior.Scan=null;prior.ImportWork=null;prior.PendingBatch=null;prior.JournalTask=null;prior.State="restored";}
                }
                p.CompletedCells=p.Cells.Count;p.Cells.Clear();p.Source.Clear();p.Scan=null;p.ImportWork=null;
            }
            if(p.State is "completed" or "restored" || Now-p.RecordedAt>1000)Record(p);
        }
        catch(HostError e) when(e.Code=="REGION_NOT_LOADED")
        {p.WaitingState=p.State;p.WaitingPoint=unloadedPoint;p.WaitingDeadline=Now+10000;p.State="waiting_region";p.Error=e.Code+": "+e.Message;Record(p);}
        catch(Exception e){p.State="paused";p.Error=e is HostError h?h.Code+": "+e.Message:e.Message;active=null;Record(p);}
        finally {if(terrainOwned){terrainUpdater.UpdateEvent.Set();terrainUpdater.UnpauseUpdateThread();}}
    }
    static IEnumerable<Point3> VerifySource(Plan p)
    {
        foreach(var entry in p.Source)
        {if(!CellEquals(Capture(entry.Key),entry.Value))throw new HostError("STALE_PLAN","Copy source changed since preflight");yield return entry.Key;}
    }
    static IEnumerable<Point3> RecoveryScan(Plan p,JsonObject data)
    {
        foreach(var cell in data["cells"].AsArray())
        {
            var point=Position(cell["position"]);var current=Capture(point);
            if(CellEquals(current,cell["before"])) {yield return point;continue;}
            if(!CellEquals(current,cell["after"]))throw new HostError("RESTORE_CONFLICT","Recovery would overwrite changed data");
            p.Cells.Add(new JsonObject { ["position"]=cell["position"].DeepClone(),["before"]=cell["after"].DeepClone(),["after"]=cell["before"].DeepClone() });
            yield return point;
        }
    }
    static bool InsideShape(Point3 p,JsonObject a)
    {
        var lo=Position(a["minimum"]);var hi=Position(a["maximum"]);
        string shape=(string)a["shape"];bool hollow=a["hollow"]?.GetValue<bool>()??false;
        bool Inside(Point3 q)
        {
            if(q.X<lo.X||q.X>hi.X||q.Y<lo.Y||q.Y>hi.Y||q.Z<lo.Z||q.Z>hi.Z)return false;
            double x=(q.X-(lo.X+hi.X)/2d)/((hi.X-lo.X+1)/2d),y=(q.Y-(lo.Y+hi.Y)/2d)/((hi.Y-lo.Y+1)/2d),z=(q.Z-(lo.Z+hi.Z)/2d)/((hi.Z-lo.Z+1)/2d);
            return shape switch { "cuboid"=>true,"sphere"=>x*x+y*y+z*z<=1,"cylinder"=>x*x+z*z<=1,"cone"=>x*x+z*z<=Math.Pow((hi.Y-q.Y+1d)/(hi.Y-lo.Y+1d),2),"line"=>LineContains(q,lo,hi),_=>false };
        }
        if(!Inside(p))return false;
        if(!hollow||shape=="line")return true;
        return !Inside(p+new Point3(1,0,0))||!Inside(p-new Point3(1,0,0))||!Inside(p+new Point3(0,1,0))||!Inside(p-new Point3(0,1,0))||!Inside(p+new Point3(0,0,1))||!Inside(p-new Point3(0,0,1));
    }
    static bool LineContains(Point3 q,Point3 lo,Point3 hi)
    {
        int steps=Math.Max(hi.X-lo.X,Math.Max(hi.Y-lo.Y,hi.Z-lo.Z));
        if(steps==0)return q==lo;
        int t=hi.X-lo.X==steps?q.X-lo.X:hi.Y-lo.Y==steps?q.Y-lo.Y:q.Z-lo.Z;
        return q==new Point3(lo.X+(int)Math.Round((double)t*(hi.X-lo.X)/steps),lo.Y+(int)Math.Round((double)t*(hi.Y-lo.Y)/steps),lo.Z+(int)Math.Round((double)t*(hi.Z-lo.Z)/steps));
    }
    static IEnumerable<Point3> CopyScan(Plan p)
    {
        var a=p.Arguments;var lo=Position(a["minimum"]);var hi=Position(a["maximum"]);var dest=Position(a["destination"]);
        int rotation=a["rotation"]==null?0:(int)a["rotation"];string mirror=(string)a["mirror"]??"none";
        var desired=new Dictionary<Point3,JsonObject>();
        if((string)a["action"]=="move")foreach(var point in p.Source.Keys){desired[point]=new JsonObject { ["value"]=0 };yield return point;}
        // The immutable source map makes overlapping copies deterministic.
        foreach(var entry in p.Source)
        {
            int x=entry.Key.X-lo.X,z=entry.Key.Z-lo.Z,sx=hi.X-lo.X,sz=hi.Z-lo.Z;
            if(mirror=="x")x=sx-x;if(mirror=="z")z=sz-z;
            (x,z)=rotation switch { 90=>(sz-z,x),180=>(sx-x,sz-z),270=>(z,sx-x),_=>(x,z) };
            var target=dest+new Point3(x,entry.Key.Y-lo.Y,z);
            Position(new JsonArray(target.X,target.Y,target.Z));
            var data=entry.Value.DeepClone().AsObject();
            if(rotation!=0||mirror!="none")data["value"]=TransformValue((int)data["value"],rotation,mirror,data["resource"]?.AsObject());
            desired[target]=data;
            yield return target;
        }
        if(desired.Count>1000000)throw new HostError("LIMIT_EXCEEDED","Combined affected region exceeds one million cells");
        foreach(var entry in desired)
        { var q=entry.Key;ReserveResources(p,entry.Value);p.Cells.Add(new JsonObject { ["position"]=new JsonArray(q.X,q.Y,q.Z),["before"]=Capture(q),["after"]=entry.Value });yield return q; }
    }
    static int TransformValue(int value,int rotation,string mirror,JsonObject resource)
    {
        int id=Terrain.ExtractContents(value);var b=BlocksManager.Blocks[id];
        if(id==227)
        {
            int furnitureData=Terrain.ExtractData(value);int orientation=FurnitureBlock.GetRotation(furnitureData);
            if(mirror!="none")
            {
                var designs=DecodeFurniture(resource);var contents=new JsonArray();
                foreach(var design in designs)
                {
                    design.Rotate(1,(4-orientation)%4);design.Mirror(mirror=="x"?1:0);
                    var values=design.Save();values.SetValue("TerrainUseCount",0);values.SetValue("LinkedDesign",design.LinkedDesign==null?-1:designs.IndexOf(design.LinkedDesign));
                    var node=new System.Xml.Linq.XElement("Values");values.Save(node);contents.Add(node.ToString(System.Xml.Linq.SaveOptions.DisableFormatting));
                }
                resource["designs"]=contents;orientation=0;
            }
            return Terrain.ReplaceData(value,FurnitureBlock.SetRotation(furnitureData,(orientation+4-rotation/90)%4));
        }
        if(b is not (CubeBlock or SlabBlock or StairsBlock or WoodBlock or DoorBlock or LadderBlock or TrapdoorBlock or AttachedSignBlock or PostedSignBlock or FenceGateBlock or DispenserBlock or TorchBlock or FurnitureBlock))throw new HostError("UNSUPPORTED_TRANSFORM","Block orientation transform is not registered");
        var helper=new CopyBlockManager(Sub<SubsystemCommandDef>(),null,new Point3(0,0,0),new Point3(-1,-1,-1));
        var data=new CopyBlockManager.CopyBlockData { Id=id,Value=value,Data=Terrain.ExtractData(value) };
        if(id==227)data.DirectData=Sub<SubsystemFurnitureBlockBehavior>().GetDesign(FurnitureBlock.GetDesignIndex(data.Data));
        if(mirror!="none")helper.SetMirrorValue(data,mirror=="x"?"zoy":"xoy");
        data.Data=Terrain.ExtractData(data.Value);
        if(rotation!=0)helper.SetRotateValue(data,"+y","+"+rotation);
        return data.Value;
    }
}
