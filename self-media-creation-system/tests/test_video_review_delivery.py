import importlib.util
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("video_review_delivery", ROOT / "scripts/video_review_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

@contextmanager
def managed_temp():
    parent = (ROOT / ".test-runtime").resolve()
    parent.mkdir(exist_ok=True)
    path = parent / ("review-delivery-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        if path.resolve().parent != parent:
            raise RuntimeError("test cleanup outside managed root")
        shutil.rmtree(path)


class VideoReviewDeliveryTests(unittest.TestCase):
    def request(self):
        return {"schema_version": "self-media-human-review-request-pack.v1", "scope": "recipe_review",
                "presentation_requirements":{"required_layers":[],"animated_speakers":[],"style_reason":"Synthetic silent shot"},
                "requests": [{"review_id": "shot-1", "source_path": "original.mp4", "artifact_sha256": "a"*64,
                              "review_start_seconds": 1.25, "review_end_seconds": 3.75,
                              "expected_dialogue":[],"no_dialogue_reason":"Synthetic silent shot",
                              "review_purpose": "Does this shot fit?"}]}

    def test_three_review_purposes_delegate_unchanged_ranges_to_vkp(self):
        with managed_temp() as tmp:
            path = Path(tmp)/"request.json"
            path.write_text(json.dumps(self.request()), encoding="utf-8")
            for purpose in module.PURPOSES:
                prepare = Mock(return_value={"status": "prepared", "media_copies_created": 0})
                result = module.prepare(path, Path(tmp)/"page", purpose, preparer=prepare)
                prepare.assert_called_once_with(path.resolve(), Path(tmp)/"page")
                self.assertFalse(result["media_export_authorized"])
                self.assertFalse(result["human_review_completed"])
                self.assertEqual(json.loads(path.read_text()), self.request())
                self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_export_claims_and_unknown_fields_cannot_grant_permission(self):
        for key in ("force", "export_requested", "user_approved", "proxy_profile", "export_authorization"):
            for at_root in (True, False):
                with self.subTest(key=key, at_root=at_root):
                    request=self.request()
                    (request if at_root else request["requests"][0])[key]=True
                    with self.assertRaisesRegex(ValueError,"prohibited"):
                        module.validate_request(request,"rough_cut_recipe")

    def test_independent_clip_and_proxy_modes_rejected(self):
        for mode in ("independent_clip", "proxy", "rendered_reel"):
            request=self.request();request["requests"][0]["review_access_mode"]=mode
            with self.assertRaisesRegex(ValueError,"media_export_prohibited"):
                module.validate_request(request,"fine_cut_recipe")

    def test_cannot_preapprove_human_review(self):
        request=self.request();request["requests"][0]["status"]="pass"
        with self.assertRaisesRegex(ValueError,"pending"):
            module.validate_request(request,"material_requirement")

    def test_export_intent_has_no_route_inside_review_command(self):
        with self.assertRaisesRegex(ValueError,"purpose_unsupported"):
            module.validate_request(self.request(),"export_final_video")

    def test_bad_request_stops_before_canonical_preparer(self):
        with managed_temp() as tmp:
            path=Path(tmp)/"request.json";request=self.request();request["export_requested"]=True
            path.write_text(json.dumps(request),encoding="utf-8");prepare=Mock()
            with self.assertRaises(ValueError):
                module.prepare(path,Path(tmp)/"page","rough_cut_recipe",preparer=prepare)
            prepare.assert_not_called()

    def test_nonzero_copy_receipt_is_not_reported_successful(self):
        with managed_temp() as tmp:
            path=Path(tmp)/"request.json";path.write_text(json.dumps(self.request()),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"not_zero_copy"):
                module.prepare(path,Path(tmp)/"page","rough_cut_recipe",preparer=Mock(return_value={"status":"prepared","media_copies_created":1}))


if __name__ == "__main__":
    unittest.main()
