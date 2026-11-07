from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publication_version_freeze.py"
SPEC = importlib.util.spec_from_file_location("publication_version_freeze", SCRIPT)
assert SPEC and SPEC.loader
FREEZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FREEZE)


class PublicationVersionFreezeTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FREEZE.FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(FREEZE.FreezeError) as caught:
            FREEZE.create(value)
        self.assertEqual(code, caught.exception.code)

    def test_freezes_exact_packaging_and_media_identity_without_copies(self) -> None:
        receipt = FREEZE.create(self.load())
        self.assertEqual("frozen-candidate", receipt["artifact_status"])
        self.assertEqual("single-master-synchronized", receipt["capacity_mode"])
        self.assertFalse(receipt["cover"]["image_copy_stored"])
        self.assertFalse(receipt["media"]["media_copy_stored"])
        self.assertEqual(5, len(receipt["platforms"]))
        self.assertFalse(any(receipt["authority"].values()))
        FREEZE.validate_receipt(receipt)

    def test_opening_and_media_changes_are_detected(self) -> None:
        receipt = FREEZE.create(self.load())
        receipt["opening"]["first_two_sentences"][0] += " changed"
        unsigned = copy.deepcopy(receipt)
        unsigned.pop("payload_sha256")
        receipt["payload_sha256"] = FREEZE.digest(unsigned)
        with self.assertRaises(FREEZE.FreezeError) as caught:
            FREEZE.validate_receipt(receipt)
        self.assertEqual("opening_hash_drift", caught.exception.code)

    def test_image_and_media_copies_are_prohibited(self) -> None:
        value = self.load()
        value["cover"]["image_copy_stored"] = True
        self.assert_code(value, "image_copy_prohibited")
        value = self.load()
        value["media"]["media_copy_stored"] = True
        self.assert_code(value, "media_copy_prohibited")

    def test_publication_and_absolute_path_are_fail_closed(self) -> None:
        value = self.load()
        value["publication_boundary"] = "auto"
        self.assert_code(value, "publication_boundary_drift")
        value = self.load()
        value["source_content_ref"] = "D:/private/content.json"
        self.assert_code(value, "source_ref_unsafe")

    def test_double_run_is_stable(self) -> None:
        self.assertEqual(FREEZE.create(self.load()), FREEZE.create(self.load()))

    def test_media_file_binding_uses_probed_release_metadata_without_storing_path(self) -> None:
        observed = {
            "sha256": "3" * 64,
            "duration_seconds": 96.521,
            "media_copy_stored": False,
        }
        release = Path("E:/synthetic/final-release.mp4")
        with patch.object(FREEZE, "probe_media_file", return_value=observed) as probe:
            receipt = FREEZE.create(self.load(), media_path=release)
        probe.assert_called_once_with(release)
        self.assertEqual(observed, receipt["media"])
        self.assertNotIn(str(release), json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
