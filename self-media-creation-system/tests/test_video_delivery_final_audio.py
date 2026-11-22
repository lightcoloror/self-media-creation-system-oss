"""Mocked offline unit tests for surgical final_audio support in video_delivery.py."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import video_delivery as vd  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": _sha256(path)}


def _install_mock_mvp(validate_fn=None, measure_fn=None):
    pkg = types.ModuleType("video_creation_pipeline")
    am = types.ModuleType("video_creation_pipeline.audio_mastering")
    ci = types.ModuleType("video_creation_pipeline.contract_io")

    def _default_validate(v):
        if v.get("schema") != "audio_mastering_output_verification.v1":
            raise ValueError("invalid_verification_schema")
        return v

    def _default_write(data, path):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    am.validate_audio_mastering_output_verification = validate_fn or _default_validate
    am.measure_final_audio = measure_fn or (lambda media, plan, out_dir: out_dir / "loudnorm-output-verification.json")
    ci.atomic_write_json = _default_write
    return {
        "video_creation_pipeline": pkg,
        "video_creation_pipeline.audio_mastering": am,
        "video_creation_pipeline.contract_io": ci,
    }


class VideoDeliveryFinalAudioTests(unittest.TestCase):
    def test_acceptance_fingerprint_ignores_final_audio_fields(self):
        base = {
            "schema": vd.SCHEMA,
            "project_id": "proj-1",
            "acceptance_ref": {"path": "acc.json", "sha256": "a" * 64},
            "context_manifest_ref": {"path": "ctx.json", "sha256": "b" * 64},
        }
        fp_base = vd.acceptance_fingerprint(base)

        with_audio = copy.deepcopy(base)
        with_audio["final_audio_measurement_ref"] = {"path": "rep.json", "sha256": "c" * 64, "bytes": 123}
        with_audio["final_audio_auto"] = {"audio_stream": "0:a:0", "plan_ref": {"path": "plan.json", "sha256": "d" * 64}}
        self.assertEqual(vd.acceptance_fingerprint(with_audio), fp_base)

    def test_final_audio_plan_validation(self):
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td).resolve() / "audio-plan.json"
            plan_path.write_text("{}", encoding="utf-8")
            manifest = {"final_audio_auto": {"audio_stream": "0:a:0", "plan_ref": _ref(plan_path)}}
            self.assertEqual(vd.final_audio_plan(manifest), plan_path)

            bad_stream = {"final_audio_auto": {"audio_stream": "0:a:1", "plan_ref": _ref(plan_path)}}
            with self.assertRaisesRegex(ValueError, "0:a:0"):
                vd.final_audio_plan(bad_stream)

            plan_path.write_text('{"changed": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                vd.final_audio_plan(manifest)

    def test_final_audio_check_pass_and_failure_controls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            media = root / "final.mp4"
            media.write_bytes(b"synthetic-mp4-bytes")
            plan = root / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            report = root / "loudnorm-output-verification.json"

            payload = {
                "schema": "audio_mastering_output_verification.v1",
                "mastered_audio": _ref(media),
                "source_plan": _ref(plan),
                "readiness": {"technical_ready": True},
                "measurements": {"input_i": -16.1, "input_tp": -1.5},
            }
            report.write_text(json.dumps(payload), encoding="utf-8")

            data = {"items": [{"video": _ref(media)}]}
            manifest = {
                "final_audio_measurement_ref": {**_ref(report), "bytes": report.stat().st_size},
                "final_audio_auto": {"audio_stream": "0:a:0", "plan_ref": _ref(plan)},
            }

            with mock.patch.object(vd, "renderer_module", return_value=object()), mock.patch.dict(sys.modules, _install_mock_mvp()):
                res = vd.final_audio_check(manifest, data)
                self.assertEqual(res["status"], "verified")
                self.assertEqual(res["audio_stream"], "0:a:0")
                self.assertEqual(res["integrated_lufs"], -16.1)
                self.assertEqual(res["true_peak_dbtp"], -1.5)

                with self.assertRaisesRegex(ValueError, "current_render_required"):
                    vd.final_audio_check(manifest, None)

                bad_size = copy.deepcopy(manifest)
                bad_size["final_audio_measurement_ref"]["bytes"] += 10
                with self.assertRaisesRegex(ValueError, "size_mismatch"):
                    vd.final_audio_check(bad_size, data)

                other_plan = root / "other-plan.json"
                other_plan.write_text('{"other": 1}', encoding="utf-8")
                bad_plan = copy.deepcopy(manifest)
                bad_plan["final_audio_auto"]["plan_ref"] = _ref(other_plan)
                with self.assertRaisesRegex(ValueError, "plan_mismatch"):
                    vd.final_audio_check(bad_plan, data)

                not_ready = copy.deepcopy(payload)
                not_ready["readiness"]["technical_ready"] = False
                report.write_text(json.dumps(not_ready), encoding="utf-8")
                manifest["final_audio_measurement_ref"] = {**_ref(report), "bytes": report.stat().st_size}
                with self.assertRaisesRegex(ValueError, "not_technical_ready"):
                    vd.final_audio_check(manifest, data)

    def test_attach_final_audio_measurement_measured_reused_and_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            media = root / "final.mp4"
            media.write_bytes(b"synthetic-mp4-data")
            plan = root / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            desk_file = root / "desk.json"
            desk_file.write_text("{}", encoding="utf-8")
            output_page = root / "publish-desk.html"

            manifest = {
                "desk_ref": _ref(desk_file),
                "final_audio_auto": {"audio_stream": "0:a:0", "plan_ref": _ref(plan)},
            }
            calls = []

            def fake_measure(m_path, p_path, out_dir):
                calls.append((m_path, p_path, out_dir))
                rep = Path(out_dir) / "loudnorm-output-verification.json"
                rep.write_text(json.dumps({"ok": True}), encoding="utf-8")
                return rep

            mock_desk_data = {"items": [{"video": _ref(media)}]}
            with (
                mock.patch.object(vd.desk, "normalize", return_value=mock_desk_data),
                mock.patch.object(vd, "renderer_module", return_value=object()),
                mock.patch.dict(sys.modules, _install_mock_mvp(measure_fn=fake_measure)),
            ):
                derived1, ref1, origin1 = vd.attach_final_audio_measurement(copy.deepcopy(manifest), output_page)
                self.assertEqual(origin1, "measured")
                self.assertTrue(derived1.is_file())
                self.assertEqual(len(calls), 1)
                self.assertEqual(json.loads(derived1.read_text(encoding="utf-8"))["final_audio_measurement_ref"], ref1)

                derived2, ref2, origin2 = vd.attach_final_audio_measurement(copy.deepcopy(manifest), output_page)
                self.assertEqual(origin2, "reused")
                self.assertEqual(ref2, ref1)
                self.assertTrue(derived2.is_file())
                self.assertEqual(len(calls), 1)

                Path(ref1["path"]).unlink()
                with self.assertRaisesRegex(ValueError, "run_incomplete"):
                    vd.attach_final_audio_measurement(copy.deepcopy(manifest), output_page)

    def test_audit_final_audio_states(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            media = root / "final.mp4"
            media.write_bytes(b"synthetic-mp4")
            plan = root / "plan.json"
            plan.write_text("{}", encoding="utf-8")
            ctx = root / "ctx.json"
            ctx.write_text("{}", encoding="utf-8")

            m_path = root / "delivery.json"
            base_manifest = {
                "schema": vd.SCHEMA,
                "project_id": "proj-1",
                "facts": {"story": "s", "do_not_infer": [], "feedback": []},
                "context_manifest_ref": _ref(ctx),
                "acceptance_ref": None,
                "final_audio_measurement_ref": None,
                "final_audio_auto": None,
            }
            m_path.write_text(json.dumps(base_manifest), encoding="utf-8")

            fake_data = {"items": [{"video": _ref(media)}]}
            with (
                mock.patch.object(vd, "context", return_value=None),
                mock.patch.object(vd.cta, "checked_plan", return_value=({}, {})),
                mock.patch.object(vd, "timeline", return_value=None),
                mock.patch.object(vd.progress, "check", return_value=None),
                mock.patch.object(vd, "identity_selection", return_value=None),
                mock.patch.object(vd, "bgm_selection", return_value=None),
                mock.patch.object(vd, "render_check", return_value=fake_data),
                mock.patch.object(vd, "final_layout_check", return_value={"ai_disclosure": {"required": False}, "identity_decision": "not_applicable"}),
                mock.patch.object(vd.cover_strategy, "review_check", return_value=None),
                mock.patch.object(vd, "renderer_module", return_value=object()),
                mock.patch.dict(sys.modules, _install_mock_mvp()),
            ):
                r1 = vd.audit(m_path, "delivery")
                self.assertEqual(r1["final_audio"], {"status": "not_measured"})
                acc_chk = [c for c in r1["checks"] if c["stage"] == "human_acceptance"][0]
                self.assertEqual(acc_chk["reason"], "current_human_acceptance_required")

                m2 = dict(base_manifest, final_audio_auto={"audio_stream": "0:a:0", "plan_ref": _ref(plan)})
                m_path.write_text(json.dumps(m2), encoding="utf-8")
                r2 = vd.audit(m_path, "delivery")
                self.assertEqual(r2["final_audio"], {"status": "not_measured"})
                fa_chk = [c for c in r2["checks"] if c["stage"] == "final_audio_verification"][0]
                self.assertEqual(fa_chk["status"], "blocked")
                self.assertEqual(fa_chk["reason"], "final_audio_measurement_pending_deliver")


if __name__ == "__main__":
    unittest.main()
