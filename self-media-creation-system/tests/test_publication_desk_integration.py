"""Repository integration without real media, platform accounts or network."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('desk_agent_integration', ROOT / 'scripts/self_media_agent.py')
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


class PublicationDeskIntegration(unittest.TestCase):
    def test_discovery_entry_and_existing_workflows(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/self_media_agent.py'),
                                 'publication-desk'], cwd=ROOT, capture_output=True, text=True,
                                encoding='utf-8', check=True, timeout=10)
        value = json.loads(result.stdout)
        self.assertEqual(value['tool_id'], 'publication-desk')
        self.assertFalse(value['boundaries']['publishes'])
        self.assertFalse(value['boundaries']['uploads'])
        self.assertFalse(value['auto_pipeline_hook'])
        self.assertEqual(value['workflow_count'], 5)
        self.assertEqual(len(agent.capabilities()['workflows']), 5)
        self.assertEqual(agent.capabilities()['publication_desk'], value)
        self.assertTrue((ROOT / value['guide']).is_file())

    def test_manifest_and_discovery_are_valid_and_bounded(self):
        manifest = agent.load_json(agent.MANIFEST_PATH)
        agent.validate_document(manifest, agent.MANIFEST_SCHEMA_PATH, 'manifest')
        self.assertIn('reusable_offline_publication_desk', manifest['capabilities'])
        command = 'python scripts/self_media_agent.py publication-desk'
        self.assertTrue(any(i['command'] == command for i in manifest['interfaces']['canonical']))
        discovery = agent.DISCOVERY_PATH.read_text(encoding='utf-8')
        self.assertIn(command, discovery)
        self.assertLessEqual(len(discovery.splitlines()), 100)
        self.assertLessEqual(len(discovery.encode('utf-8')), 9216)


if __name__ == '__main__':
    unittest.main()
