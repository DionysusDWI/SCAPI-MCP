using System.Text.Json.Nodes;
using GameEntitySystem;
namespace Game;
public static partial class AgentHost
{
    static int Integer(JsonObject args,string key,int lo,int hi)
    {if(args[key] is not JsonValue v||!v.TryGetValue<int>(out var n)||n<lo||n>hi)throw new HostError("INVALID_ARGUMENT",key+" must be bounded integer");return n;}
    static IInventory InventoryEndpoint(JsonObject descriptor,Operation o)
    {
        Closed(descriptor,"kind","position");string kind=RequiredText(descriptor,"kind");IInventory inv;
        if(kind=="player")
        {if(descriptor.Count!=1)throw new HostError("INVALID_ARGUMENT","Player endpoint does not accept coordinates");inv=OperationPlayer(o).ComponentMiner.Inventory;}
        else if(kind=="container")
        {
            var p=Position(descriptor["position"]);int value=Raw(p);if(!Containers.Contains(Terrain.ExtractContents(value)))throw new HostError("UNKNOWN_RESOURCE","Only registered containers supported");
            var block=Sub<SubsystemBlockEntities>().GetBlockEntity(p.X,p.Y,p.Z);if(block==null)throw new HostError("RESOURCE_NOT_READY","Container has no active entity; open it first");
            inv=block.Entity.FindComponent<ComponentInventoryBase>(true);
        }
        else throw new HostError("UNREGISTERED_COMMAND","Endpoint must be player or container");
        if(inv==null||inv.GetType().Assembly!=typeof(ComponentInventory).Assembly||inv is not (ComponentInventoryBase or ComponentCreativeInventory))throw new HostError("UNKNOWN_RESOURCE","Unknown inventory implementation");return inv;
    }
    static int EditableSlots(IInventory inv)=>inv is ComponentCreativeInventory c?c.OpenSlotsCount:inv.SlotsCount;
    static JsonObject InventorySnapshot(IInventory inv)
    {
        var slots=new JsonArray();bool creative=inv is ComponentCreativeInventory;
        for(int i=0;i<EditableSlots(inv);i++){var slot=new JsonObject {["index"]=i,["value"]=inv.GetSlotValue(i),["count"]=creative?(inv.GetSlotValue(i)==0?0:1):inv.GetSlotCount(i)};SlotFurnitureContent(slot);slots.Add(slot);}
        return new JsonObject {["type"]=inv.GetType().FullName,["entity_id"]=(inv as Component)?.Entity.Id,["creative"]=creative,["slots"]=slots,["active_slot"]=inv.ActiveSlotIndex};
    }
    static void ValidateItem(int value)
    {if(value!=0){SafeBlock(value,true);if(Terrain.ExtractContents(value)==227)ValidateResourceValue(value,ExistingFurnitureContent(value),true);}}
    static JsonObject ExistingFurnitureContent(int value)
    {var design=Sub<SubsystemFurnitureBlockBehavior>().GetDesign(FurnitureBlock.GetDesignIndex(Terrain.ExtractData(value)))??throw new HostError("UNKNOWN_RESOURCE","Furniture design missing");return FurnitureContent(design.ListChain());}
    static void SlotFurnitureContent(JsonObject slot)
    {slot.Remove("resource");int value=(int)slot["value"];if((int)slot["count"]>0){ValidateItem(value);if(Terrain.ExtractContents(value)==227)slot["resource"]=ExistingFurnitureContent(value);}}
    static int AdjustInventory(JsonObject snapshot,IInventory inv,int value,int count,bool add)
    {
        var slots=snapshot["slots"].AsArray();int remaining=count;bool creative=(bool)snapshot["creative"];
        if(creative)throw new HostError("INVALID_ARGUMENT","Use explicit creative slot editing or transfer generation/destruction");
        foreach(var slot in slots)
        {
            int index=(int)slot["index"],oldValue=(int)slot["value"],oldCount=(int)slot["count"];
            if(add)
            {
                if(oldCount!=0&&oldValue!=value)continue;int amount=Math.Min(remaining,Math.Max(0,inv.GetSlotCapacity(index,value)-oldCount));
                if(amount>0){slot["value"]=value;slot["count"]=oldCount+amount;remaining-=amount;}
            }
            else if(oldValue==value){int amount=Math.Min(remaining,oldCount);slot["count"]=oldCount-amount;if(oldCount==amount)slot["value"]=0;remaining-=amount;}
            if(remaining==0)break;
        }
        return remaining;
    }
    static void DescribeInventory(Operation o)
    {
        var endpoints=new JsonArray();var original=new List<JsonObject>();var desired=new List<JsonObject>();var inventories=new List<IInventory>();
        if(o.Action=="inventory_edit")
        {
            Closed(o.Arguments,"target","mode","slots","value","count","active_slot");
            if(o.Arguments["target"] is not JsonObject target)throw new HostError("INVALID_ARGUMENT","Inventory endpoint required");
            endpoints.Add(target.DeepClone());inventories.Add(InventoryEndpoint(target,o));original.Add(InventorySnapshot(inventories[0]));desired.Add(original[0].DeepClone().AsObject());
            var inv=inventories[0];var data=desired[0];string mode=RequiredText(o.Arguments,"mode");
            if(mode=="set")
            {
                if(o.Arguments["slots"] is not JsonArray edits||edits.Count>64)throw new HostError("INVALID_ARGUMENT","At most 64 slot edits");var seen=new HashSet<int>();
                foreach(var edit in edits)
                {
                    var e=edit.AsObject();Closed(e,"index","value","count");int index=Integer(e,"index",0,EditableSlots(inv)-1),value=Integer(e,"value",0,int.MaxValue),count=Integer(e,"count",0,9999);
                    if(!seen.Add(index))throw new HostError("INVALID_ARGUMENT","Duplicate slot");ValidateItem(value);
                    if((count==0)!=(value==0))throw new HostError("INVALID_ARGUMENT","Empty slots require value=0,count=0");
                    if(inv is ComponentCreativeInventory&&count>1)throw new HostError("INVALID_ARGUMENT","Creative slots are supplies, not physical counts");
                    if(count>inv.GetSlotCapacity(index,value))throw new HostError("RESOURCE_CAPACITY","Slot capacity exceeded");
                    data["slots"][index]["value"]=value;data["slots"][index]["count"]=count;
                }
            }
            else if(mode is "add" or "remove")
            {int value=Integer(o.Arguments,"value",1,int.MaxValue),count=Integer(o.Arguments,"count",1,9999);ValidateItem(value);if(AdjustInventory(data,inv,value,count,mode=="add")!=0)throw new HostError("RESOURCE_CAPACITY","Insufficient items or capacity; no mutation");}
            else if(mode=="clear")foreach(var s in data["slots"].AsArray()){s["value"]=0;s["count"]=0;}
            else throw new HostError("UNREGISTERED_COMMAND","Inventory mode must be set/add/remove/clear");
            if(o.Arguments["active_slot"]!=null){if((string)target["kind"]!="player")throw new HostError("INVALID_ARGUMENT","Active slot is player-only");data["active_slot"]=Integer(o.Arguments,"active_slot",0,Math.Min(inv.VisibleSlotsCount,EditableSlots(inv))-1);}
            if(mode!="set"&&o.Arguments["slots"]!=null||mode is "set" or "clear"&&(o.Arguments["value"]!=null||o.Arguments["count"]!=null))throw new HostError("INVALID_ARGUMENT","Parameters do not match inventory mode");
        }
        else
        {
            Closed(o.Arguments,"source","destination","value","count");
            if(o.Arguments["source"] is not JsonObject source||o.Arguments["destination"] is not JsonObject destination||JsonNode.DeepEquals(source,destination))throw new HostError("INVALID_ARGUMENT","Two distinct endpoints required");
            endpoints.Add(source.DeepClone());endpoints.Add(destination.DeepClone());
            foreach(var d in new[]{source,destination}){var inv=InventoryEndpoint(d,o);inventories.Add(inv);original.Add(InventorySnapshot(inv));desired.Add(original[^1].DeepClone().AsObject());}
            int value=Integer(o.Arguments,"value",1,int.MaxValue),count=Integer(o.Arguments,"count",1,9999);ValidateItem(value);
            bool sourceCreative=(bool)original[0]["creative"],destinationCreative=(bool)original[1]["creative"];
            if(sourceCreative&&destinationCreative)throw new HostError("INVALID_ARGUMENT","Creative-to-creative is slot editing, not transfer");
            if(sourceCreative&&!original[0]["slots"].AsArray().Any(s=>(int)s["value"]==value))throw new HostError("RESOURCE_NOT_READY","Creative source must select the requested supply");
            if(!sourceCreative&&AdjustInventory(desired[0],inventories[0],value,count,false)!=0)throw new HostError("RESOURCE_CAPACITY","Insufficient source items");
            if(!destinationCreative&&AdjustInventory(desired[1],inventories[1],value,count,true)!=0)throw new HostError("RESOURCE_CAPACITY","Destination capacity insufficient");
            o.Risk=sourceCreative||destinationCreative?"side_effects":"state_change";o.Recovery=sourceCreative||destinationCreative?"none":"best_effort";
        }
        var affected=new JsonArray();var wanted=new JsonArray();int involved=0;
        for(int i=0;i<desired.Count;i++)
        {
            foreach(var slot in desired[i]["slots"].AsArray())SlotFurnitureContent(slot.AsObject());
            var rows=new JsonArray();var beforeRows=new JsonArray();for(int j=0;j<desired[i]["slots"].AsArray().Count;j++)if(!JsonNode.DeepEquals(original[i]["slots"][j],desired[i]["slots"][j])||o.Action=="inventory_transfer"&&i==0&&(bool)original[i]["creative"]&&(int)original[i]["slots"][j]["value"]==(int)o.Arguments["value"]){rows.Add(desired[i]["slots"][j].DeepClone());beforeRows.Add(original[i]["slots"][j].DeepClone());involved++;}
            affected.Add(new JsonObject {["endpoint"]=endpoints[i].DeepClone(),["type"]=original[i]["type"].DeepClone(),["slots"]=beforeRows,["active_slot"]=original[i]["active_slot"].DeepClone()});
            wanted.Add(new JsonObject {["endpoint"]=endpoints[i].DeepClone(),["type"]=desired[i]["type"].DeepClone(),["entity_id"]=desired[i]["entity_id"]?.DeepClone(),["slots"]=rows,["active_slot"]=desired[i]["active_slot"].DeepClone()});
        }
        if(involved>64)throw new HostError("LIMIT_EXCEEDED","Operation involves more than 64 slots");
        o.Planned=new JsonObject {["inventories"]=wanted};o.Risk??="state_change";o.Recovery??="best_effort";o.Backup=false;
    }
    static JsonObject CaptureInventory(Operation o)
    {
        var rows=new JsonArray();foreach(var target in o.Planned["inventories"].AsArray())
        {
            var inv=InventoryEndpoint(target["endpoint"].AsObject(),o);var snap=InventorySnapshot(inv);var slots=new JsonArray();
            foreach(var s in target["slots"].AsArray()){int index=(int)s["index"];if(index>=EditableSlots(inv))throw new HostError("STALE_PLAN","Inventory shape changed");slots.Add(snap["slots"][index].DeepClone());}
            rows.Add(new JsonObject {["endpoint"]=target["endpoint"].DeepClone(),["type"]=snap["type"].DeepClone(),["entity_id"]=snap["entity_id"]?.DeepClone(),["slots"]=slots,["active_slot"]=snap["active_slot"].DeepClone()});
        }
        return new JsonObject {["inventories"]=rows};
    }
    static void DescribeInventoryRestore(Operation o)
    {
        if(o.Planned?["inventories"] is not JsonArray targets||targets.Count!=(o.Action=="inventory_edit"?1:2))throw new HostError("INVALID_RECORD","Inventory record shape differs");
        int involved=0;bool creative=false;
        foreach(var target in targets)
        {
            var inv=InventoryEndpoint(target["endpoint"].AsObject(),o);creative|=inv is ComponentCreativeInventory;
            if(target["slots"] is not JsonArray slots)throw new HostError("INVALID_RECORD","Slot record missing");involved+=slots.Count;
            foreach(var slot in slots){Integer(slot.AsObject(),"index",0,EditableSlots(inv)-1);Integer(slot.AsObject(),"value",0,int.MaxValue);Integer(slot.AsObject(),"count",0,9999);}
        }
        if(involved>64)throw new HostError("LIMIT_EXCEEDED","Inventory record exceeds 64 slots");
        o.Risk=o.Action=="inventory_transfer"&&creative?"side_effects":"state_change";o.Recovery=o.Action=="inventory_transfer"&&creative?"none":"best_effort";
    }
    static void ApplyInventory(Operation o)
    {
        var wanted=o.RestoreOf==null?o.Planned:o.After;
        var applied=new List<(IInventory Inv,int Index,int Value,int Count,int OldValue,int OldCount)>();
        foreach(var target in wanted["inventories"].AsArray())
        {
            var inv=InventoryEndpoint(target["endpoint"].AsObject(),o);
            if((inv as Component)?.Entity.Id!=(int?)target["entity_id"])throw new HostError("STALE_PLAN","Inventory entity changed");
            foreach(var s in target["slots"].AsArray()){int index=Integer(s.AsObject(),"index",0,EditableSlots(inv)-1),value=Integer(s.AsObject(),"value",0,int.MaxValue),count=Integer(s.AsObject(),"count",0,9999);ValidateItem(value);if(s["resource"]!=null&&!JsonNode.DeepEquals(s["resource"],ExistingFurnitureContent(value)))throw new HostError("RESOURCE_CHANGED","Furniture contents changed since the recorded plan; no slot write");if(count>inv.GetSlotCapacity(index,value))throw new HostError("RESOURCE_CAPACITY","Capacity changed before any write");}
        }
        try
        {
        foreach(var target in wanted["inventories"].AsArray())
        {
            var inv=InventoryEndpoint(target["endpoint"].AsObject(),o);
            foreach(var s in target["slots"].AsArray())
            {
                int index=(int)s["index"],value=(int)s["value"],count=(int)s["count"],oldValue=inv.GetSlotValue(index),oldCount=inv is ComponentCreativeInventory?(oldValue==0?0:1):inv.GetSlotCount(index);
                if(oldValue==value&&oldCount==count)continue;
                var step=new JsonObject {["endpoint"]=target["endpoint"].DeepClone(),["slot"]=index,["before_value"]=oldValue,["before_count"]=oldCount,["value"]=value,["count"]=count,["state"]="intent"};o.Steps.Add(step);Save(Path.Combine(OperationDir,o.Id+".json"),OperationRecord(o));
                applied.Add((inv,index,value,count,oldValue,oldCount));
                inv.SetSlotValue(index,new ComponentInventoryBase.Slot {Value=value,Count=count});if(inv is ComponentCreativeInventory)inv.OnSlotChange(index);
                if(labInventoryFailure&&settings["target"]["test_only"]?.GetValue<bool>()==true&&++labInventoryWrites==2){labInventoryFailure=false;throw new HostError("LAB_INJECTED_FAILURE","Injected after second native slot callback; verify compensation");}
                step["actual_value"]=inv.GetSlotValue(index);step["actual_count"]=inv is ComponentCreativeInventory?(inv.GetSlotValue(index)==0?0:1):inv.GetSlotCount(index);step["state"]="executed";Save(Path.Combine(OperationDir,o.Id+".json"),OperationRecord(o));
                if((int)step["actual_value"]!=value||(int)step["actual_count"]!=count)throw new HostError("READBACK_MISMATCH","Native callback changed slot; stop and inspect partial result");
            }
            if((string)target["endpoint"]["kind"]=="player")inv.ActiveSlotIndex=(int)target["active_slot"];
        }
        }
        catch
        {
            foreach(var row in applied.AsEnumerable().Reverse())
            {
                var step=new JsonObject {["slot"]=row.Index,["state"]="compensation_conflict"};o.Steps.Add(step);
                try
                {
                    int currentCount=row.Inv is ComponentCreativeInventory?(row.Inv.GetSlotValue(row.Index)==0?0:1):row.Inv.GetSlotCount(row.Index);
                    if(row.Inv.GetSlotValue(row.Index)!=row.Value||currentCount!=row.Count)continue;
                    row.Inv.SetSlotValue(row.Index,new ComponentInventoryBase.Slot {Value=row.OldValue,Count=row.OldCount});if(row.Inv is ComponentCreativeInventory)row.Inv.OnSlotChange(row.Index);
                    step["state"]=row.Inv.GetSlotValue(row.Index)==row.OldValue&&(row.Inv is ComponentCreativeInventory?(row.Inv.GetSlotValue(row.Index)==0?0:1):row.Inv.GetSlotCount(row.Index))==row.OldCount?"compensated":"compensation_failed";
                }
                catch(Exception error){step["state"]="compensation_failed";step["error"]=error.Message;}
            }
            throw;
        }
    }
}
