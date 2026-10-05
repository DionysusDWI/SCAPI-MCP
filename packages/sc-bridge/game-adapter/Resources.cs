using Engine;
using System.Text.Json.Nodes;
using System.Xml.Linq;
using TemplatesDatabase;

namespace Game;
public static partial class AgentHost
{
    static T Sub<T>() where T: GameEntitySystem.Subsystem => GameManager.Project.FindSubsystem<T>(true);
    static readonly HashSet<int> Containers=[27,45,64,216];
    static readonly HashSet<int> Signs=[97,98,210,211];
    static int SlotCount(int id)
    {
        string template=id switch { 27=>"CraftingTable",45=>"Chest",64=>"Furnace",216=>"Dispenser",_=>throw new HostError("UNKNOWN_RESOURCE","Not a container") };
        var definition=DatabaseManager.FindEntityValuesDictionary(template,true);
        return definition.GetValue<ValuesDictionary>(template).GetValue<int>("SlotsCount");
    }
    static JsonObject Desired(int value,JsonNode resource=null)
    {
        var result=new JsonObject { ["value"]=value };
        int id=Terrain.ExtractContents(value);
        if(resource!=null)result["resource"]=resource.DeepClone();
        else if(Containers.Contains(id))
        {
            var slots=new JsonArray();for(int i=0;i<SlotCount(id);i++)slots.Add(new JsonObject { ["value"]=0,["count"]=0 });
            var container=new JsonObject { ["kind"]="container",["slots"]=slots };
            if(id==64){container["fire_time"]=0f;container["heat"]=0f;}
            result["resource"]=container;
        }
        ValidateResourceValue(value,result["resource"]);
        if(result["resource"]?["kind"]?.GetValue<string>() is "memory" or "truth_table")
            result["resource"]["data"]=((string)result["resource"]["data"]).ToUpperInvariant().TrimEnd('0');
        if(id==227)
        {
            var designs=DecodeFurniture(result["resource"].AsObject());
            result["resource"]=FurnitureContent(designs);
            result["value"]=Terrain.ReplaceData(value,FurnitureBlock.SetDesignIndex(Terrain.ExtractData(value),0,designs[0].ShadowStrengthFactor,designs[0].IsLightEmitter));
        }
        if(Containers.Contains(id))foreach(var slot in result["resource"]["slots"].AsArray())
        {
            if(Terrain.ExtractContents((int)slot["value"])!=227)continue;
            var item=Desired((int)slot["value"],slot["resource"]);
            slot["value"]=item["value"].DeepClone();slot["resource"]=item["resource"].DeepClone();
        }
        return result;
    }
    static bool CellEquals(JsonNode a,JsonNode b)
    {
        if(a["resource"]?["kind"]?.GetValue<string>()=="container" && b["resource"]?["kind"]?.GetValue<string>()=="container")
        {
            var ac=a.DeepClone();var bc=b.DeepClone();
            foreach(var cell in new[]{ac,bc})foreach(var slot in cell["resource"]["slots"].AsArray())
                if(Terrain.ExtractContents((int)slot["value"])==227)slot["value"]=NormalizeFurniture((int)slot["value"]);
            return JsonNode.DeepEquals(ac,bc);
        }
        if(a["resource"]?["kind"]?.GetValue<string>()!="furniture" || b["resource"]?["kind"]?.GetValue<string>()!="furniture")return JsonNode.DeepEquals(a,b);
        // World-local design IDs have no portable meaning. Compare content,
        // rotation and emitted-light/shadow flags instead of the assigned index.
        int av=(int)a["value"],bv=(int)b["value"];
        return NormalizeFurniture(av)==NormalizeFurniture(bv)&&JsonNode.DeepEquals(a["resource"],b["resource"]);
    }
    static int NormalizeFurniture(int v){int d=Terrain.ExtractData(v);return Terrain.ReplaceData(v,FurnitureBlock.SetDesignIndex(d,0,FurnitureBlock.GetShadowStrengthFactor(d),FurnitureBlock.GetIsLightEmitter(d)));}
    static void ValidateResourceValue(int value,JsonNode resource,bool inventoryItem=false)
    {
        SafeBlock(value,inventoryItem);
        int id=Terrain.ExtractContents(value);
        if(id==227 && resource==null)throw new HostError("RESOURCE_REQUIRED","Furniture requires design contents");
        if(resource==null)return;
        string kind=(string)resource["kind"];
        string[] fields=kind switch { "container"=>["kind","slots","fire_time","heat"],"sign"=>["kind","lines","colors","url"],"memory" or "truth_table"=>["kind","data"],"command"=>["kind","line"],"furniture"=>["kind","designs"],_=>[] };
        if(resource.AsObject().Any(p=>!fields.Contains(p.Key)))throw new HostError("UNKNOWN_RESOURCE","Unregistered resource field");
        if(kind=="container")
        {
            if(!Containers.Contains(id))throw new HostError("INVALID_RESOURCE","Container resource/block mismatch");
            var slots=resource["slots"].AsArray();
            if(slots.Count!=SlotCount(id))throw new HostError("RESOURCE_CAPACITY","Container slot count differs from current entity template");
            foreach(var slot in slots)
            {
                if(slot.AsObject().Any(p=>p.Key is not ("value" or "count" or "resource")))throw new HostError("UNKNOWN_RESOURCE","Unregistered inventory field");
                int count=(int)slot["count"],item=(int)slot["value"];
                if(count<0||count>9999||count>0&&item==0)throw new HostError("INVALID_RESOURCE","Invalid stack count/value");ValidateResourceValue(item,slot["resource"],true);
                if(count>BlocksManager.Blocks[Terrain.ExtractContents(item)].GetMaxStacking(item))throw new HostError("RESOURCE_CAPACITY","Item stack exceeds registered block capacity");
            }
            foreach(var field in new[]{"fire_time","heat"})if(resource[field]!=null)
            {double number=System.Text.Json.JsonSerializer.Deserialize<double>(resource[field].ToJsonString());if(id!=64||!double.IsFinite(number)||number<0)throw new HostError("INVALID_RESOURCE","Invalid furnace state");}
        }
        else if(kind=="sign")
        {
            if(!Signs.Contains(id)||resource["lines"].AsArray().Count!=4||resource["colors"].AsArray().Count!=4)throw new HostError("INVALID_RESOURCE","Sign needs four lines and colors");
            foreach(var line in resource["lines"].AsArray())if(((string)line).Length>4096)throw new HostError("LIMIT_EXCEEDED","Sign text too long");
        }
        else if(kind=="memory"&&id==186 || kind=="truth_table"&&id==188)
        {string data=(string)resource["data"];if(data.Length>(kind=="memory"?256:16)||data.Any(c=>!"0123456789ABCDEFabcdef".Contains(c)))throw new HostError("INVALID_RESOURCE","Circuit data must contain at most 256/16 hex digits; transient output is excluded");}
        else if(kind=="command"&&id==CommandBlock.Index)
        {
            var command=new CommandData(Point3.Zero,(string)resource["line"]);command.TrySetValue();
            if(!command.Valid||command.OutRange||command.Mode!=WorkingMode.Condition||command.Name!="blockexist"||command.Type!="default"||command.Coordinate!=CoordinateMode.Default||command.Data.Keys.Any(k=>k is not ("pos" or "id")))throw new HostError("UNREGISTERED_COMMAND","Only registered blockexist/default condition configs are portable");
            if(command.GetValue("pos") is not Point3 || command.GetValue("id") is not int)throw new HostError("INVALID_RESOURCE","Invalid condition parameters");
        }
        else if(kind=="furniture"&&id==227)
        {
            var chain=resource["designs"].AsArray();
            if(chain.Count<1||chain.Count>256)throw new HostError("RESOURCE_CAPACITY","Furniture chain exceeds limit");
            foreach(var xml in chain)
            {
                if(((string)xml).Length>8*1024*1024)throw new HostError("LIMIT_EXCEEDED","Furniture content exceeds limit");
                var node=XElement.Parse((string)xml);
                var types=new Dictionary<string,string> { ["Name"]="string",["TerrainUseCount"]="int",["Resolution"]="int",["InteractionMode"]="Game.FurnitureInteractionMode",["Values"]="string",["LinkedDesign"]="int" };
                if(node.Name!="Values"||node.HasAttributes||node.Elements().Any(v=>v.Name!="Value"||v.HasElements||v.Attributes().Any(a=>a.Name.LocalName is not ("Name" or "Type" or "Value"))||!types.TryGetValue((string)v.Attribute("Name")??"",out var type)||(string)v.Attribute("Type")!=type)||node.Elements().Select(v=>(string)v.Attribute("Name")).Distinct().Count()!=node.Elements().Count())throw new HostError("INVALID_RESOURCE","Furniture fields/types are not registered");
                var resolution=node.Elements("Value").Single(v=>(string)v.Attribute("Name")=="Resolution");
                int size=int.Parse((string)resolution.Attribute("Value"));
                if(size<2||size>64)throw new HostError("RESOURCE_CAPACITY","Registered furniture resolution is 2..64");
            }
            DecodeFurniture(resource.AsObject()); // Also validate linked designs and their embedded block types before a snapshot.
        }
        else throw new HostError("UNKNOWN_RESOURCE","Unregistered resource type or mismatched block");
        // Additional data is captured for every known entity/behavior below. Unknown
        // entity families are rejected before any destructive change.
    }
    static JsonObject Capture(Point3 point)
    {
        int value=Raw(point);SafeBlock(value);int id=Terrain.ExtractContents(value);
        var result=new JsonObject { ["value"]=value };
        var entity=Sub<SubsystemBlockEntities>().GetBlockEntity(point.X,point.Y,point.Z);
        if(entity!=null)
        {
            if(!Containers.Contains(id))throw new HostError("UNKNOWN_RESOURCE","Unregistered block entity");
            var inventory=entity.Entity.FindComponent<ComponentInventoryBase>(true);
            var slots=new JsonArray();
            foreach(var slot in inventory.m_slots)
            {
                var item=new JsonObject { ["value"]=slot.Count>0?slot.Value:0,["count"]=slot.Count };
                if(slot.Count>0&&Terrain.ExtractContents(slot.Value)==227)
                {var design=Sub<SubsystemFurnitureBlockBehavior>().GetDesign(FurnitureBlock.GetDesignIndex(Terrain.ExtractData(slot.Value)));if(design==null)throw new HostError("MISSING_DESIGN","Inventory furniture has absent design");item["resource"]=FurnitureContent(design.ListChain());}
                slots.Add(item);
            }
            var container=new JsonObject { ["kind"]="container",["slots"]=slots };
            if(inventory is ComponentFurnace furnace) { container["fire_time"]=furnace.m_fireTimeRemaining;container["heat"]=furnace.m_heatLevel; }
            result["resource"]=container;
        }
        else if(Containers.Contains(id))throw new HostError("RESOURCE_NOT_READY","Container entity missing");
        if(Signs.Contains(id))
        {
            var sign=Sub<SubsystemSignBlockBehavior>().GetSignData(point);
            if(sign!=null)result["resource"]=new JsonObject { ["kind"]="sign",["lines"]=new JsonArray(sign.Lines.Select(s=>(JsonNode)JsonValue.Create(s)).ToArray()),["colors"]=new JsonArray(sign.Colors.Select(c=>(JsonNode)JsonValue.Create(c.PackedValue)).ToArray()),["url"]=sign.Url??"" };
        }
        if(id==186)
        {
            var bank=Sub<SubsystemMemoryBankBlockBehavior>().GetBlockData(point);
            if(bank!=null)result["resource"]=new JsonObject { ["kind"]="memory",["data"]=bank.SaveString(false) };
        }
        if(id==188)
        {
            var table=Sub<SubsystemTruthTableCircuitBlockBehavior>().GetBlockData(point);
            if(table!=null)result["resource"]=new JsonObject { ["kind"]="truth_table",["data"]=table.SaveString() };
        }
        if(id==CommandBlock.Index)
        {
            var data=Sub<SubsystemCommandBlockBehavior>().GetCommandData(point);
            if(data!=null)result["resource"]=new JsonObject { ["kind"]="command",["line"]=data.Line };
        }
        if(id==227)
        {
            var design=Sub<SubsystemFurnitureBlockBehavior>().GetDesign(FurnitureBlock.GetDesignIndex(Terrain.ExtractData(value)));
            if(design==null)throw new HostError("MISSING_DESIGN","Furniture references absent design");
            var chain=design.ListChain();var content=new JsonArray();
            foreach(var d in chain)
            {
                var values=d.Save();values.SetValue("TerrainUseCount",0);
                values.SetValue("LinkedDesign",d.LinkedDesign==null?-1:chain.IndexOf(d.LinkedDesign));
                var node=new XElement("Values");values.Save(node);content.Add(node.ToString(SaveOptions.DisableFormatting));
            }
            result["resource"]=new JsonObject { ["kind"]="furniture",["designs"]=content };
        }
        // Reject unsupported contents before capturing a destructive operation.
        // A journal that cannot be applied again is not a recovery snapshot.
        if(result["resource"]!=null)ValidateResourceValue(value,result["resource"]);
        return result;
    }
    static int FurnitureValue(int value,JsonObject resource)
    {
        var behavior=Sub<SubsystemFurnitureBlockBehavior>();var designs=DecodeFurniture(resource);
        var mapped=behavior.TryAddDesignChain(designs[0],false);
        if(mapped==null)throw new HostError("RESOURCE_CAPACITY","Furniture design capacity exhausted");
        return Terrain.ReplaceData(value,FurnitureBlock.SetDesignIndex(Terrain.ExtractData(value),mapped.Index,mapped.ShadowStrengthFactor,mapped.IsLightEmitter));
    }
    static List<FurnitureDesign> DecodeFurniture(JsonObject resource)
    {
        var designs=new List<FurnitureDesign>();
        foreach(var node in resource["designs"].AsArray())
        {
            var values=new ValuesDictionary();values.ApplyOverrides(XElement.Parse((string)node));
            designs.Add(new FurnitureDesign(-1,ST,values));
            foreach(int value in designs[^1].m_values)SafeBlock(value,true);
        }
        for(int i=0;i<designs.Count;i++)
        { int linked=designs[i].m_loadTimeLinkedDesignIndex; if(linked>=0){if(linked>=designs.Count)throw new HostError("INVALID_RESOURCE","Furniture link out of bounds");designs[i].LinkedDesign=designs[linked];} }
        return designs;
    }
    static JsonObject FurnitureContent(List<FurnitureDesign> designs)
    {
        var content=new JsonArray();
        foreach(var design in designs)
        {
            var values=design.Save();values.SetValue("TerrainUseCount",0);
            values.SetValue("LinkedDesign",design.LinkedDesign==null?-1:designs.IndexOf(design.LinkedDesign));
            var node=new XElement("Values");values.Save(node);content.Add(node.ToString(SaveOptions.DisableFormatting));
        }
        return new JsonObject { ["kind"]="furniture",["designs"]=content };
    }
    static void ReserveResources(Plan plan,JsonNode desired)
    {
        var resource=desired["resource"];if(resource==null)return;
        if((string)resource["kind"]=="container")
        {foreach(var slot in resource["slots"].AsArray())ReserveResources(plan,slot);return;}
        if((string)resource["kind"]!="furniture")return;
        string key=resource.ToJsonString();if(!plan.FurnitureContents.Add(key))return;
        var designs=DecodeFurniture(resource.AsObject());var behavior=Sub<SubsystemFurnitureBlockBehavior>();
        if(behavior.FindMatchingDesignChain(designs[0])==null)plan.RequiredFurnitureDesigns+=designs.Count;
        if(plan.RequiredFurnitureDesigns>behavior.m_furnitureDesigns.Count(d=>d==null))throw new HostError("RESOURCE_CAPACITY","Insufficient furniture design slots before execution");
    }
    static void Apply(Point3 point,JsonObject desired)
    {
        int value=(int)desired["value"];var resource=desired["resource"]?.AsObject();
        ValidateResourceValue(value,resource);
        if(resource!=null&&(string)resource["kind"]=="furniture")value=FurnitureValue(value,resource);
        int old=Raw(point);
        if(Containers.Contains(Terrain.ExtractContents(old)))
        {
            // Removing a container normally drops inventory into the world. The
            // durable resource snapshot owns these items during a controlled edit.
            var original=Sub<SubsystemBlockEntities>().GetBlockEntity(point.X,point.Y,point.Z).Entity.FindComponent<ComponentInventoryBase>(true);
            foreach(var slot in original.m_slots){slot.Value=0;slot.Count=0;}
            ST.ChangeCell(point.X,point.Y,point.Z,0);
        }
        // The safe synchronous place/default route is the official command backend.
        // Resource attachment and batch bookkeeping remain native game-thread work.
        var command=new CommandData(point,"") { Name="place",Type="default" };
        command.Data["pos"]=point;command.Data["id"]=value;
        var result=Sub<SubsystemCommand>().Submit("place",command,false);
        if(result!=SubmitResult.Success)throw new HostError("COMMAND_FAILED","place/default returned "+result);
        if(resource==null)return;
        switch((string)resource["kind"])
        {
            case "container":
                var entity=Sub<SubsystemBlockEntities>().GetBlockEntity(point.X,point.Y,point.Z);
                var inventory=entity.Entity.FindComponent<ComponentInventoryBase>(true);
                var slots=resource["slots"].AsArray();
                if(slots.Count!=inventory.m_slots.Count)throw new HostError("RESOURCE_CAPACITY","Container slots differ");
                for(int i=0;i<slots.Count;i++){int itemValue=(int)slots[i]["value"];if(Terrain.ExtractContents(itemValue)==227)itemValue=FurnitureValue(itemValue,slots[i]["resource"].AsObject());inventory.m_slots[i].Value=itemValue;inventory.m_slots[i].Count=(int)slots[i]["count"];inventory.OnSlotChange(i);}
                if(inventory is ComponentFurnace furnace){furnace.m_fireTimeRemaining=(float)resource["fire_time"];furnace.m_heatLevel=(float)resource["heat"];}
                break;
            case "sign": Sub<SubsystemSignBlockBehavior>().SetSignData(point,resource["lines"].AsArray().Select(v=>(string)v).ToArray(),resource["colors"].AsArray().Select(v=>new Color((uint)v)).ToArray(),(string)resource["url"]);break;
            case "memory":var bank=new MemoryBankData();bank.LoadString((string)resource["data"]);Sub<SubsystemMemoryBankBlockBehavior>().SetBlockData(point,bank);break;
            case "truth_table":var table=new TruthTableData();table.LoadString((string)resource["data"]);Sub<SubsystemTruthTableCircuitBlockBehavior>().SetBlockData(point,table);break;
            case "command":Sub<SubsystemCommandBlockBehavior>().SetCommandData(point,(string)resource["line"]);break;
            case "furniture":break;
            default:throw new HostError("UNKNOWN_RESOURCE","Resource is not registered");
        }
    }
}
