using System.Globalization;
using System.Text.Json.Nodes;
using Engine;

namespace Game;
public static partial class AgentHost
{
    sealed class ObservationSnapshot
    {
        public string Operation,Client;
        public JsonObject Identity,Query;
        public JsonArray Rows;
        public long Observed,Expires;
    }
    static readonly Dictionary<string,ObservationSnapshot> observationSnapshots=[];
    static bool InObservationRegion(Vector3 position,Point3 lo,Point3 hi) => position.X>=lo.X&&position.X<hi.X+1d&&position.Y>=lo.Y&&position.Y<hi.Y+1d&&position.Z>=lo.Z&&position.Z<hi.Z+1d;
    static JsonArray ObservationVector(Vector3 value)
    {
        if(!float.IsFinite(value.X)||!float.IsFinite(value.Y)||!float.IsFinite(value.Z))throw new HostError("INVALID_OBSERVATION","Object vector is not finite");
        return new JsonArray(value.X,value.Y,value.Z);
    }
    static JsonNode EntityObservation(string op,JsonObject args,JsonObject identity)
    {
        Identity(identity);
        if((string)World()["network"]!="singleplayer"||Players().Count!=1)throw new HostError("MULTIPLAYER_DISABLED","Active object observations require local singleplayer");
        string[] allowed=op=="entity_query"?["minimum","maximum","kind","template","limit","cursor","client_id"]:["minimum","maximum","value","limit","cursor","client_id"];
        if(args.Any(p=>!allowed.Contains(p.Key)))throw new HostError("INVALID_ARGUMENT","Unknown observation field");
        var lo=Position(args["minimum"]);var hi=Position(args["maximum"]);
        if(hi.X<lo.X||hi.Y<lo.Y||hi.Z<lo.Z)throw new HostError("INVALID_ARGUMENT","Reversed observation region");
        long volume=((long)hi.X-lo.X+1)*(hi.Y-lo.Y+1)*((long)hi.Z-lo.Z+1);
        long chunks=((long)(hi.X>>4)-(lo.X>>4)+1)*((long)(hi.Z>>4)-(lo.Z>>4)+1);
        if(volume>1000000||chunks>256)throw new HostError("LIMIT_EXCEEDED","Observation limited to one million cells and 256 chunk columns");
        string client=(string)args["client_id"],cursor=(string)args["cursor"];
        if(!Guid.TryParseExact(client,"N",out _))throw new HostError("INVALID_ARGUMENT","Client identity required");
        int limit=(int)args["limit"];
        if(limit<1||limit>64)throw new HostError("LIMIT_EXCEEDED","Object pages limited to 64 records");
        var query=args.DeepClone().AsObject();query.Remove("client_id");query.Remove("limit");query.Remove("cursor");
        string kind=(string)args["kind"]??"all",template=(string)args["template"];
        if(op=="entity_query"&&(!new[]{"all","creature","player","body"}.Contains(kind)||template!=null&&(template.Length<1||template.Length>128)))throw new HostError("INVALID_ARGUMENT","Invalid kind or template filter");
        int? filterValue=args["value"]==null?null:(int)args["value"];
        if(filterValue<0)throw new HostError("INVALID_ARGUMENT","Packed item value must be nonnegative");
        ObservationSnapshot snapshot;string id;int offset=0;
        if(cursor!=null)
        {
            var parts=cursor.Split(':');
            if(parts.Length!=2||!Guid.TryParseExact(parts[0],"N",out _)||!int.TryParse(parts[1],NumberStyles.None,CultureInfo.InvariantCulture,out offset))throw new HostError("INVALID_CURSOR","Invalid observation cursor");
            id=parts[0];
            if(!observationSnapshots.TryGetValue(id,out snapshot)||snapshot.Expires<Now)throw new HostError("SNAPSHOT_EXPIRED","Snapshot expired or host/world session changed");
            if(snapshot.Client!=client||snapshot.Operation!=op||!JsonNode.DeepEquals(snapshot.Identity,identity)||!JsonNode.DeepEquals(snapshot.Query,query))throw new HostError("CURSOR_MISMATCH","Snapshot belongs to a different client, query or target");
            if(offset<0||offset>=snapshot.Rows.Count)throw new HostError("INVALID_CURSOR","Cursor offset outside snapshot");
        }
        else
        {
            foreach(var key in observationSnapshots.Where(p=>p.Value.Expires<Now).Select(p=>p.Key).ToArray())observationSnapshots.Remove(key);
            if(observationSnapshots.Count>=32||observationSnapshots.Count(p=>p.Value.Client==client)>=8)throw new HostError("OBSERVATION_CAPACITY","Too many live snapshots; wait for expiry");
            // Existing terrain only; an empty object list must not hide unloaded columns.
            for(int x=lo.X>>4;x<=hi.X>>4;x++)for(int z=lo.Z>>4;z<=hi.Z>>4;z++)
            {var chunk=ST.Terrain.GetChunkAtCell(x*16,z*16);if(chunk==null||chunk.State!=TerrainChunkState.Valid)throw new HostError("REGION_NOT_LOADED","Observation requires fully loaded existing columns");}
            var rows=new JsonArray();
            if(op=="entity_query")
            {
                var bodies=Sub<SubsystemBodies>().Bodies;
                if(bodies.Count>4096)throw new HostError("LIMIT_EXCEEDED","More than 4096 active bodies; no partial result returned");
                foreach(var body in bodies)
                {
                    var position=ObservationVector(body.Position);var velocity=ObservationVector(body.Velocity);
                    if(!InObservationRegion(body.Position,lo,hi))continue;
                    var player=body.Entity.FindComponent<ComponentPlayer>();var creature=body.Entity.FindComponent<ComponentCreature>();
                    string type=player!=null?"player":creature!=null?"creature":"body";
                    string name=body.Entity.ValuesDictionary.DatabaseObject.Name;
                    if(kind!="all"&&kind!=type||template!=null&&template!=name)continue;
                    float? health=creature?.ComponentHealth?.Health;
                    if(health.HasValue&&!float.IsFinite(health.Value))throw new HostError("INVALID_OBSERVATION","Entity health is not finite");
                    rows.Add(new JsonObject { ["observation_id"]=Guid.NewGuid().ToString("N"),["native_id"]=body.Entity.Id,["kind"]=type,["template"]=name,
                        ["position"]=position,["velocity"]=velocity,["health"]=health,["player_index"]=player?.PlayerData.PlayerIndex,["player_name"]=player?.PlayerData.Name });
                }
            }
            else
            {
                var pickables=Sub<SubsystemPickables>().Pickables;
                if(pickables.Count>4096)throw new HostError("LIMIT_EXCEEDED","More than 4096 active pickables; no partial result returned");
                foreach(var pickable in pickables)
                {
                    if(pickable.ToRemove)continue;
                    var position=ObservationVector(pickable.Position);var velocity=ObservationVector(pickable.Velocity);
                    if(!InObservationRegion(pickable.Position,lo,hi)||filterValue.HasValue&&pickable.Value!=filterValue.Value)continue;
                    if(pickable.Count<1)throw new HostError("INVALID_OBSERVATION","Active pickable has invalid count");
                    rows.Add(new JsonObject { ["observation_id"]=Guid.NewGuid().ToString("N"),["native_id"]=pickable.Id,["value"]=pickable.Value,
                        ["contents"]=Terrain.ExtractContents(pickable.Value),["count"]=pickable.Count,["position"]=position,["velocity"]=velocity });
                }
            }
            id=Guid.NewGuid().ToString("N");snapshot=new ObservationSnapshot { Operation=op,Client=client,Identity=identity.DeepClone().AsObject(),Query=query,
                Rows=rows,Observed=Now,Expires=Now+30000 };observationSnapshots.Add(id,snapshot);
        }
        var page=new JsonArray();for(int i=offset;i<Math.Min(snapshot.Rows.Count,offset+limit);i++)page.Add(snapshot.Rows[i].DeepClone());
        return new JsonObject { ["records"]=page,["total"]=snapshot.Rows.Count,["offset"]=offset,["snapshot_id"]=id,
            ["next_cursor"]=offset+page.Count<snapshot.Rows.Count?id+":"+(offset+page.Count).ToString(CultureInfo.InvariantCulture):null,
            ["observed_at_utc_ms"]=snapshot.Observed,["expires_at_utc_ms"]=snapshot.Expires,["host_boot"]=Boot,["world_session"]=session,
            ["scope"]=op=="entity_query"?"active registered bodies only; dormant/unspawned entities excluded":"active native pickables only; pending removal excluded",
            ["bounds"]=snapshot.Query.DeepClone(),["positions"]= "continuous coordinates inside inclusive cell bounds: min <= position < max+1",
            ["persistent_identity"]=false };
    }
}
