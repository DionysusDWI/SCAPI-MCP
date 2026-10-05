"""Bounded portable package inspection, without extracting untrusted entries."""
import hashlib
import json
import zipfile
from pathlib import Path
from .client import BridgeError

def inspect(path):
    try:
        with zipfile.ZipFile(path) as archive:
            if sorted(archive.namelist()) != ['cells.json', 'manifest.json']:
                raise BridgeError('INVALID_TEMPLATE', 'Unexpected or duplicate archive entries')
            if archive.getinfo('manifest.json').file_size > 65536 or archive.getinfo('cells.json').file_size > 256*1024*1024:
                raise BridgeError('LIMIT_EXCEEDED', 'Decompressed template size exceeds limit')
            manifest = json.loads(archive.read('manifest.json'))
            if any(manifest.get(k) != v for k,v in {'format':'scblueprint','format_version':1,'protocol':3,'api':'1.9.3.2'}.items()):
                raise BridgeError('INCOMPATIBLE_TEMPLATE', 'Template version mismatch')
            raw = archive.read('cells.json')
            if hashlib.sha256(raw).hexdigest() != manifest.get('cells_sha256'):
                raise BridgeError('TEMPLATE_CHECKSUM', 'Template payload checksum differs')
            cells = json.loads(raw)
            if not isinstance(cells,list) or len(cells) != manifest.get('count') or not 1 <= len(cells) <= 1000000:
                raise BridgeError('INVALID_TEMPLATE', 'Template cell count differs')
            seen = set()
            for cell in cells:
                if not isinstance(cell,dict) or set(cell) != {'position','data'}:
                    raise BridgeError('INVALID_TEMPLATE', 'Unknown cell fields')
                pos = cell['position']
                if not isinstance(pos,list) or len(pos)!=3 or any(type(v) is not int or v<0 or v>1000000 for v in pos):
                    raise BridgeError('INVALID_TEMPLATE', 'Invalid relative position')
                if tuple(pos) in seen: raise BridgeError('INVALID_TEMPLATE','Duplicate cell position')
                seen.add(tuple(pos))
                data=cell['data']
                if not isinstance(data,dict) or set(data)-{'value','resource'} or type(data.get('value')) is not int or not 0 <= data['value'] <= 2147483647:
                    raise BridgeError('INVALID_TEMPLATE','Invalid cell data')
            return {'manifest':manifest,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(), 'bytes':len(raw)}
    except BridgeError: raise
    except (OSError,ValueError,KeyError,zipfile.BadZipFile) as error:
        raise BridgeError('INVALID_TEMPLATE',str(error)) from error
