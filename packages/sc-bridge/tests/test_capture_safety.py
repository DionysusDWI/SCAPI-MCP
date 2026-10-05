"""Opt-in destructive snapshot validation in a registered lab only."""
import os
import time
import unittest
from sc_bridge import Bridge, Config
from sc_bridge.client import atomic_json


@unittest.skipUnless(os.environ.get('SC_LIVE_TEST_CONFIG'), 'Explicit lab required')
class CaptureSafetyTests(unittest.TestCase):
    def test_invalid_inventory_blocks_clear_before_mutation(self):
        b = Bridge(Config.load(os.environ['SC_LIVE_TEST_CONFIG']))
        assert b.config.target.get('test_only') and b.config.target['name'].startswith('SC MCP LAB')
        b.isolate_local()
        def wait(result, terminal):
            deadline = time.monotonic() + 30
            while result['state'] not in terminal:
                self.assertLess(time.monotonic(), deadline, str(result))
                time.sleep(.05)
                result = b.job_status(result['job_id'])
            return result
        pos = [-151,75,-95]
        before = b.resource_query(pos)
        self.assertEqual(before['value'], 0)
        ready = wait(b.fill(pos,pos,45), ('ready','paused'))
        self.assertEqual(ready['state'], 'ready')
        created = wait(b.submit(ready['plan_id']), ('completed','paused'))
        self.assertEqual(created['state'], 'completed')
        seeded = False
        try:
            b.call('lab_invalid_inventory', {}, b.identity()); seeded = True
            rejected = wait(b.clear(pos,pos), ('ready','paused'))
            self.assertEqual(rejected['state'], 'paused')
            self.assertIn('INVALID_RESOURCE', rejected['error'])
            release = b.call('lab_release_invalid_inventory', {}, b.identity()); seeded = False
            self.assertEqual(release['observed_count'], 10000)
            self.assertEqual(b.resource_query(pos)['value'], 45)
        finally:
            if seeded: b.call('lab_release_invalid_inventory', {}, b.identity())
            restored = wait(b.restore_job(created['job_id']), ('restored','paused'))
            self.assertEqual(restored['state'], 'restored')
        self.assertEqual(b.resource_query(pos), before)
        atomic_json(b.config.artifacts_dir/'capture-safety-live.json', {
            'invalid_inventory_rejected_before_clear': rejected,
            'original_invalid_count_retained': release, 'restored': restored})
