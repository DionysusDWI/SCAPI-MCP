"""Inventory upstream registrations; names alone never grant capability access."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
SOURCE=ROOT/'reference/SC-CommandBlock/Game/Subsystem/SubsystemCommandDef.cs'
text=SOURCE.read_text(encoding='utf-8-sig')
entries=[]
pure={'levelrange','heightrange','statsrange','gamemode','camerapos','signtext','modcount','blocklight','timerange','handitem','clothes','entityexist','dropexist','itemexist'}
stateful={'blockchange','creaturedie','clickinteract','longpress','oncapture','eatorwear','patternbutton','actionmake','openwidget','moveset','musicplay'}
for found in re.finditer(r'Add(Function|Condition)\("([^"\r\n]+)"',text):
    kind,name=found.groups();line=text.count('\n',0,found.start())+1
    current=text[found.start():text.find('\n',found.start())]
    comment=current.partition('//')[2].strip()
    category='mutation_review_required' if kind=='Function' else ('readonly_candidate' if name in pure else ('state_or_event_review_required' if name in stateful else 'review_required'))
    if name in {'fileexist','getcell','world'}:category='closed_file_or_world_lifecycle_path'
    entries.append({'kind':kind.lower(),'name':name,'source_line':line,'comment':comment,'review_category':category,'subtypes':'manual source review required','access':'not granted by this inventory'})
record={'commit':'f5bc2ef2c106db28a45d118a9a45387f5fec7c56','source':SOURCE.relative_to(ROOT).as_posix(),
    'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'function_count':sum(e['kind']=='function' for e in entries),'condition_count':sum(e['kind']=='condition' for e in entries),'entries':entries}
output=ROOT/'projects/sc-bridge/docs/upstream-command-inventory.json'
output.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:record[k] for k in ('function_count','condition_count','source_sha256')}))
