"""Offline tests of registry configuration, not real owner execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('public_toolchain', Path(__file__).with_name('public_toolchain.py'))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicToolchainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'self-media-creation-system').mkdir()
        (self.root / 'docs').mkdir()
        (self.root / 'docs/public-owner-boundaries.md').write_text('Synthetic boundary', encoding='utf-8')
        self.lock = {'tools': {'missing-owner': {'directory': 'missing', 'discovery': 'README.md',
                     'commit': 'a' * 40, 'source_status': 'reviewed-source-only'}}}

    def test_missing_owner_is_metadata_only_and_not_runtime_ready(self):
        MODULE.initialize(self.root, self.lock)
        card = MODULE.discover(self.root, 'missing-owner')
        self.assertFalse(card['current_checkout']['checkout_present'])
        self.assertFalse(card['runtime_verified'])
        self.assertFalse(card['current_checkout']['pinned_checkout_verified'])
        self.assertEqual(card['commands_executed'], [])

    def test_existing_registry_is_never_overwritten(self):
        target = MODULE.initialize(self.root, self.lock)
        before = target.read_bytes()
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.initialize(self.root, self.lock)
        self.assertEqual(target.read_bytes(), before)

    def test_unknown_tool_blocks(self):
        MODULE.initialize(self.root, self.lock)
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.discover(self.root, 'invented-owner')

    def test_path_escape_blocks(self):
        self.lock['tools']['missing-owner']['directory'] = '../outside'
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.initialize(self.root, self.lock)
        self.assertFalse((self.root / 'tool-registry.json').exists())

    def test_tampered_discovery_outside_workspace_blocks(self):
        target = MODULE.initialize(self.root, self.lock)
        value = json.loads(target.read_text(encoding='utf-8'))
        value['tools']['missing-owner']['discovery_markdown'] = str(self.root.parent / 'outside.md')
        target.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(MODULE.ConfigurationError):
            MODULE.discover(self.root, 'missing-owner')

    def test_directory_presence_is_not_pinned_or_runtime_verification(self):
        (self.root / 'missing').mkdir()
        MODULE.initialize(self.root, self.lock)
        value = MODULE.discover(self.root, 'missing-owner')
        self.assertTrue(value['current_checkout']['checkout_present'])
        self.assertFalse(value['current_checkout']['pinned_checkout_verified'])
        self.assertFalse(value['runtime_verified'])

    def test_shared_consumer_aliases_resolve_the_same_existing_owner(self):
        spec = {'directory': 'self-media-creation-system', 'discovery': 'README.md',
                'source_status': 'synthetic-local-framework', 'commit': None}
        value = MODULE.build_registry(self.root, {'tools': {'content-creation-system': spec}})
        owner = value['tools']['content-creation-system']
        self.assertEqual(owner['path'], owner['self_media_path'])
        self.assertEqual(owner['path'], owner['runtime_main']['repositories']['self']['path'])
        self.assertFalse(owner['availability']['runtime_verified'])


if __name__ == '__main__':
    unittest.main()
