import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from sc_bridge import BridgeError
from sc_bridge.blueprint import inspect

class BlueprintTests(unittest.TestCase):
    def package(self, cells, extra=None, corrupt=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'test.scblueprint';raw=json.dumps(cells).encode()
        manifest={'format':'scblueprint','format_version':1,'protocol':3,'api':'1.9.3.2','count':len(cells),'dependencies':[], 'cells_sha256':hashlib.sha256(raw).hexdigest() if not corrupt else '0'*64}
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('cells.json',raw);archive.writestr('manifest.json',json.dumps(manifest))
            if extra:archive.writestr(extra,'unsafe')
        return path
    def test_checksum_and_traversal(self):
        cells=[{'position':[0,0,0],'data':{'value':3}}]
        self.assertEqual(inspect(self.package(cells))['manifest']['count'],1)
        for path, code in [(self.package(cells,corrupt=True),'TEMPLATE_CHECKSUM'),(self.package(cells,extra='../file'),'INVALID_TEMPLATE')]:
            with self.assertRaises(BridgeError) as error:inspect(path)
            self.assertEqual(error.exception.code,code)
    def test_duplicate_coordinates_and_bool(self):
        cell={'position':[0,0,0],'data':{'value':3}}
        for cells in [[cell,cell],[{'position':[0,True,0],'data':{'value':3}}]]:
            with self.assertRaises(BridgeError):inspect(self.package(cells))
