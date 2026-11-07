from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "content_packaging_review.py"
FIXTURES = ROOT / "fixtures" / "content-packaging-review-v1"
SPEC = importlib.util.spec_from_file_location("content_packaging_review", SCRIPT)
assert SPEC and SPEC.loader
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class ContentPackagingReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_parent = ROOT / "tests" / ".runtime" / "content-packaging-review" / "unit"
        cls.runtime_parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        for candidate in (cls.runtime_parent, cls.runtime_parent.parent):
            try:
                candidate.rmdir()
            except OSError:
                pass

    def setUp(self) -> None:
        self.runtime = self.runtime_parent / f"{os.getpid()}-{self._testMethodName}"
        if self.runtime.exists():
            shutil.rmtree(self.runtime)
        self.runtime.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.runtime.exists():
            shutil.rmtree(self.runtime)

    @staticmethod
    def rehash(receipt: dict) -> dict:
        receipt["receipt_payload_sha256"] = packaging.canonical_sha256(
            {key: value for key, value in receipt.items() if key != "receipt_payload_sha256"}
        )
        return receipt

    def load_input(self, name: str = "synthetic.input.json") -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def runtime_ref(self, path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    def create_from_runtime_value(self, value: dict, name: str = "reviewed-input.json") -> dict:
        input_path = self.runtime / name
        packaging.write_json(input_path, value)
        return packaging.create_receipt(input_path)

    def runtime_package(self) -> tuple[dict, dict, Path]:
        body = self.runtime / "body.md"
        body.write_text(
            "Synthetic context. Synthetic answer. Synthetic payoff.\n",
            encoding="utf-8",
            newline="\n",
        )
        body_ref = self.runtime_ref(body)
        title = "Synthetic packaging title"
        cover = {
            "headline": "Synthetic cover",
            "visual_direction": "Fictional cards only.",
            "supporting_text": None,
        }
        opening = "Synthetic opening."
        standalone = {
            "audience_question": "Synthetic packaging title",
            "entry_strategy": "other-reviewed",
            "title_cover_opening_same_promise": True,
            "context_excerpt": "Synthetic context.",
            "progression_excerpts": ["Synthetic context.", "Synthetic answer.", "Synthetic payoff."],
            "core_answer_excerpt": "Synthetic answer.",
            "payoff_excerpt": "Synthetic payoff.",
            "current_item_payoff_delivered": True,
            "insurance_entry_mode": "not-applicable",
            "prior_item_required": False,
            "future_item_required_for_payoff": False,
        }
        scope = packaging.review_scope(
            "content-synthetic-runtime-001",
            "synthetic-platform",
            "synthetic-only",
            body_ref,
            packaging.sha256_file(body),
            packaging.sha256_bytes(title.encode("utf-8")),
            packaging.canonical_sha256(cover),
            packaging.sha256_bytes(opening.encode("utf-8")),
            packaging.canonical_sha256(standalone),
        )
        credential = self.runtime / "human-review.json"
        packaging.write_json(
            credential,
            {
                "schema_version": "content-packaging-human-review-credential.v1",
                "reviewer": "runtime-human-reviewer",
                "reviewed_at": "2026-08-24T12:00:00+08:00",
                "decision": "approved",
                "review_scope_sha256": scope,
                "authority": copy.deepcopy(packaging.AUTHORITY),
            },
        )
        value = {
            "schema_version": "content-packaging-review-input.v1",
            "content_id": "content-synthetic-runtime-001",
            "platform": "synthetic-platform",
            "body_ref": body_ref,
            "body_sha256": packaging.sha256_file(body),
            "title": title,
            "cover_brief": cover,
            "opening_text": opening,
            "standalone_review": standalone,
            "data_classification": "synthetic-only",
            "human_review": {
                "credential_ref": self.runtime_ref(credential),
                "credential_sha256": packaging.sha256_file(credential),
                "reviewer": "runtime-human-reviewer",
                "reviewed_at": "2026-08-24T12:00:00+08:00",
            },
            "privacy_review": None,
        }
        input_path = self.runtime / "reviewed-input.json"
        packaging.write_json(input_path, value)
        return value, packaging.create_receipt(input_path), body

    def assert_code(self, expected: str, operation) -> None:
        with self.assertRaises(packaging.PackagingReviewError) as raised:
            operation()
        self.assertEqual(expected, raised.exception.code)

    def test_synthetic_fixture_matches_expected_and_is_stable(self) -> None:
        first = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        second = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        expected = json.loads((FIXTURES / "synthetic.expected.json").read_text(encoding="utf-8"))
        self.assertEqual(expected, first)
        self.assertEqual(packaging.canonical_bytes(first), packaging.canonical_bytes(second))
        self.assertEqual("passed", packaging.validate_receipt_value(first)["status"])

    def test_deidentified_fixture_requires_and_binds_privacy_review(self) -> None:
        receipt = packaging.create_receipt(FIXTURES / "deidentified-operational.input.json")
        expected = json.loads(
            (FIXTURES / "deidentified-operational.expected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(expected, receipt)
        self.assertEqual("passed", receipt["privacy_review"]["decision"])
        missing = self.load_input("deidentified-operational.input.json")
        missing["privacy_review"] = None
        self.assert_code("privacy_review_required", lambda: self.create_from_runtime_value(missing))

    def test_operational_classification_cannot_be_downgraded_after_review(self) -> None:
        receipt = packaging.create_receipt(FIXTURES / "deidentified-operational.input.json")
        downgraded = copy.deepcopy(receipt)
        downgraded["data_classification"] = "synthetic-only"
        downgraded["privacy_review"] = None
        self.rehash(downgraded)
        self.assert_code("classification_drift", lambda: packaging.validate_receipt_value(downgraded))

    def test_receipt_never_grants_publish_execution_or_send_authority(self) -> None:
        receipt = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        self.assertEqual("candidate-only", receipt["artifact_status"])
        self.assertEqual("manual-only", receipt["publication_boundary"])
        self.assertEqual(
            {"publish_authorized": False, "execution_authorized": False, "external_send_authorized": False},
            receipt["authority"],
        )
        escalated = copy.deepcopy(receipt)
        escalated["authority"]["publish_authorized"] = True
        self.rehash(escalated)
        self.assert_code("schema_validation_failed", lambda: packaging.validate_receipt_value(escalated))

    def test_body_byte_change_invalidates_receipt(self) -> None:
        _, receipt, body = self.runtime_package()
        body.write_text("Synthetic runtime frozen body changed.\n", encoding="utf-8", newline="\n")
        self.assert_code("body_hash_drift", lambda: packaging.validate_receipt_value(receipt))

    def test_title_cover_and_opening_changes_invalidate_human_review(self) -> None:
        original = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        title = copy.deepcopy(original)
        title["packaging"]["title"] = "Changed title"
        title["packaging"]["title_sha256"] = packaging.sha256_bytes(b"Changed title")
        self.rehash(title)
        self.assert_code("packaging_input_drift", lambda: packaging.validate_receipt_value(title))

        cover = copy.deepcopy(original)
        cover["packaging"]["cover_brief"]["headline"] = "Changed cover"
        cover["packaging"]["cover_brief_sha256"] = packaging.canonical_sha256(
            cover["packaging"]["cover_brief"]
        )
        self.rehash(cover)
        self.assert_code("packaging_input_drift", lambda: packaging.validate_receipt_value(cover))

        opening = copy.deepcopy(original)
        opening["packaging"]["opening_sha256"] = "1" * 64
        self.rehash(opening)
        self.assert_code("opening_hash_drift", lambda: packaging.validate_receipt_value(opening))

    def test_series_sequence_labels_alone_are_allowed(self) -> None:
        cases = (
            ("title", "保单整理第1集"),
            ("headline", "家庭保障第二期"),
            ("supporting_text", "Episode 03"),
            ("headline", "Part 4: a synthetic checklist"),
        )
        for index, (field, text) in enumerate(cases):
            value = self.load_input()
            if field == "title":
                value["title"] = text
            else:
                value["cover_brief"][field] = text
            packaging.reject_series_sequence_label(value["title"], value["cover_brief"])

        allowed = self.load_input()
        allowed["title"] = "第1步：先把保单找齐"
        allowed["cover_brief"]["supporting_text"] = "家庭保障整理系列"
        packaging.validate_input(allowed)

    def test_standalone_review_requires_frozen_context_answer_and_payoff(self) -> None:
        missing = self.load_input()
        missing.pop("standalone_review")
        self.assert_code("missing_required_field", lambda: packaging.validate_input(missing))

        missing_excerpt = self.load_input()
        missing_excerpt["standalone_review"]["payoff_excerpt"] = "This payoff is absent."
        self.assert_code(
            "standalone_excerpt_missing",
            lambda: self.create_from_runtime_value(missing_excerpt, "missing-excerpt.json"),
        )

        misaligned = self.load_input()
        misaligned["standalone_review"]["title_cover_opening_same_promise"] = False
        self.assert_code(
            "packaging_promise_misaligned",
            lambda: self.create_from_runtime_value(misaligned, "misaligned-promise.json"),
        )

        out_of_order = self.load_input()
        out_of_order["standalone_review"]["progression_excerpts"] = list(
            reversed(out_of_order["standalone_review"]["progression_excerpts"])
        )
        self.assert_code(
            "information_progression_missing",
            lambda: self.create_from_runtime_value(out_of_order, "out-of-order.json"),
        )

    def test_series_dependency_or_withheld_payoff_is_fail_closed(self) -> None:
        prior_required = self.load_input()
        prior_required["standalone_review"]["prior_item_required"] = True
        self.assert_code(
            "series_item_not_standalone",
            lambda: self.create_from_runtime_value(prior_required, "prior-required.json"),
        )

        dependency_body = self.runtime / "dependency-body.md"
        dependency_body.write_text(
            "接着上一集，具体做法下期再讲。\n",
            encoding="utf-8",
            newline="\n",
        )
        dependent = self.load_input()
        dependent["body_ref"] = self.runtime_ref(dependency_body)
        dependent["body_sha256"] = packaging.sha256_file(dependency_body)
        dependent["standalone_review"].update(
            {
                "context_excerpt": "接着上一集",
                "progression_excerpts": ["接着上一集", "具体做法", "下期再讲"],
                "core_answer_excerpt": "具体做法",
                "payoff_excerpt": "下期再讲",
            }
        )
        self.assert_code(
            "series_dependency_prohibited",
            lambda: self.create_from_runtime_value(dependent, "dependent.json"),
        )

    def test_complete_item_may_point_to_a_separate_future_topic(self) -> None:
        body = self.runtime / "separate-next-topic.md"
        body.write_text(
            "本条先把保单整理方法讲清楚。下一条讨论理赔材料，这是另一个问题。\n",
            encoding="utf-8",
            newline="\n",
        )
        value = self.load_input()
        value["body_ref"] = self.runtime_ref(body)
        value["body_sha256"] = packaging.sha256_file(body)
        value["standalone_review"].update(
            {
                "context_excerpt": "本条先把保单整理方法讲清楚。",
                "progression_excerpts": ["本条先把保单整理方法讲清楚。", "下一条讨论理赔材料"],
                "core_answer_excerpt": "保单整理方法",
                "payoff_excerpt": "讲清楚",
            }
        )
        packaging.validate_standalone_review(
            value["standalone_review"],
            title=value["title"],
            opening_text=value["opening_text"],
            body_text=body.read_text(encoding="utf-8"),
        )

    def test_opening_change_in_reviewed_input_invalidates_existing_receipt(self) -> None:
        value, receipt, _ = self.runtime_package()
        value["opening_text"] = "A changed upstream opening."
        packaging.write_json(ROOT / receipt["reviewed_input_binding"]["input_ref"], value)
        self.assert_code("input_hash_drift", lambda: packaging.validate_receipt_value(receipt))

    def test_create_api_blocks_value_and_reviewed_input_mismatch(self) -> None:
        value = self.load_input("synthetic.input.json")
        mismatched_input = FIXTURES / "deidentified-operational.input.json"
        self.assert_code(
            "classification_drift",
            lambda: packaging._create_receipt_from_value(
                value,
                input_ref=self.runtime_ref(mismatched_input),
                input_sha256=packaging.sha256_file(mismatched_input),
            ),
        )

    def test_missing_or_drifted_human_credential_is_fail_closed(self) -> None:
        missing = self.load_input()
        missing.pop("human_review")
        self.assert_code("missing_required_field", lambda: self.create_from_runtime_value(missing))

        _, receipt, _ = self.runtime_package()
        credential = ROOT / receipt["human_review"]["credential_ref"]
        credential.write_text(credential.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n")
        self.assert_code("credential_hash_drift", lambda: packaging.validate_receipt_value(receipt))

    def test_unknown_fields_are_rejected_in_input_and_receipt(self) -> None:
        value = self.load_input()
        value["unexpected"] = True
        self.assert_code("unexpected_field", lambda: self.create_from_runtime_value(value))
        receipt = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        receipt["unexpected"] = True
        self.rehash(receipt)
        self.assert_code("schema_validation_failed", lambda: packaging.validate_receipt_value(receipt))

    def test_sensitive_paths_and_secrets_are_rejected(self) -> None:
        absolute = self.load_input()
        absolute["body_ref"] = "C:" + r"\Users\Example\private.md"
        self.assert_code("sensitive_path", lambda: self.create_from_runtime_value(absolute))
        secret = self.load_input()
        secret["opening_text"] = "api_" + "key=synthetic-but-secret-shaped-value"
        self.assert_code("secret_detected", lambda: self.create_from_runtime_value(secret))

        slack = self.load_input()
        slack["cover_brief"]["supporting_text"] = "xoxb-" + "1234567890-secret-shaped"
        self.assert_code("secret_detected", lambda: self.create_from_runtime_value(slack, "slack.json"))

        body = self.runtime / "unsafe-body.md"
        body.write_text(
            "Local path: /" + "tmp/private-material.json\n",
            encoding="utf-8",
            newline="\n",
        )
        unsafe_body = self.load_input()
        unsafe_body["body_ref"] = self.runtime_ref(body)
        unsafe_body["body_sha256"] = packaging.sha256_file(body)
        self.assert_code("sensitive_path", lambda: self.create_from_runtime_value(unsafe_body, "unsafe-body.json"))

        aws_body = self.runtime / "aws-secret-body.md"
        aws_body.write_text(
            "AWS_SECRET_ACCESS_" + "KEY=synthetic-secret-value\n",
            encoding="utf-8",
            newline="\n",
        )
        unsafe_secret = self.load_input()
        unsafe_secret["body_ref"] = self.runtime_ref(aws_body)
        unsafe_secret["body_sha256"] = packaging.sha256_file(aws_body)
        self.assert_code("secret_detected", lambda: self.create_from_runtime_value(unsafe_secret, "aws-secret.json"))

        for index, path_value in enumerate(
            (
                "/" + "usr/local/config.json",
                "/" + "data/customer/export.json",
                "/" + "workspace/project/file.md",
                "/" + "Library/Application Support/app.db",
            )
        ):
            posix = self.load_input()
            posix["opening_text"] = f"Local artifact {path_value}"
            self.assert_code(
                "sensitive_path",
                lambda value=posix, name=f"posix-{index}.json": self.create_from_runtime_value(value, name),
            )

    def test_payload_hash_and_direct_component_hash_drift_are_rejected(self) -> None:
        receipt = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        receipt["packaging"]["title"] = "Changed without rehash"
        self.assert_code("receipt_hash_drift", lambda: packaging.validate_receipt_value(receipt))
        receipt = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        receipt["packaging"]["title_sha256"] = "2" * 64
        self.rehash(receipt)
        self.assert_code("title_hash_drift", lambda: packaging.validate_receipt_value(receipt))
        receipt = packaging.create_receipt(FIXTURES / "synthetic.input.json")
        receipt["packaging"]["standalone_review_sha256"] = "3" * 64
        self.rehash(receipt)
        self.assert_code("standalone_review_hash_drift", lambda: packaging.validate_receipt_value(receipt))

    def test_cli_create_validate_and_check(self) -> None:
        output = self.runtime / "receipt.json"
        create = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--input", str(FIXTURES / "synthetic.input.json"), "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, create.returncode, create.stderr)
        create_payload = json.loads(create.stdout)
        self.assertEqual("created", create_payload["status"])
        self.assertFalse(Path(create_payload["receipt_ref"]).is_absolute())

        repeated = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--input", str(FIXTURES / "synthetic.input.json"), "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual("already-identical", json.loads(repeated.stdout)["status"])
        validate = subprocess.run(
            [sys.executable, str(SCRIPT), "validate", "--receipt", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validate.returncode, validate.stderr)
        check = subprocess.run(
            [sys.executable, str(SCRIPT), "check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, check.returncode, check.stderr)
        self.assertEqual("byte-stable", json.loads(check.stdout)["idempotency"])
        self.assertEqual(2, len(json.loads(check.stdout)["fixtures"]))

    def test_cli_refuses_to_overwrite_a_different_receipt(self) -> None:
        output = self.runtime / "receipt.json"
        output.write_text("{}\n", encoding="utf-8", newline="\n")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--input", str(FIXTURES / "synthetic.input.json"), "--output", str(output)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("output_conflict", json.loads(result.stderr)["code"])

    def test_cli_concurrent_first_writers_cannot_overwrite_each_other(self) -> None:
        output = self.runtime / "concurrent-receipt.json"
        commands = [
            [
                sys.executable,
                str(SCRIPT),
                "create",
                "--input",
                str(FIXTURES / fixture),
                "--output",
                str(output),
            ]
            for fixture in ("synthetic.input.json", "deidentified-operational.input.json")
        ]
        processes = [
            subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for command in commands
        ]
        results = []
        for process in processes:
            stdout, stderr = process.communicate()
            results.append((process.returncode, stdout, stderr))
        self.assertEqual([0, 2], sorted(result[0] for result in results), results)
        blocked = next(result for result in results if result[0] == 2)
        self.assertEqual("output_conflict", json.loads(blocked[2])["code"])
        self.assertEqual("passed", packaging.validate_receipt(output)["status"])

    def test_cli_output_is_restricted_to_runtime_roots(self) -> None:
        prohibited = ROOT / "fixtures" / "content-packaging-review-v1" / "must-not-write.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--input", str(FIXTURES / "synthetic.input.json"), "--output", str(prohibited)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("output_path_prohibited", json.loads(result.stderr)["code"])
        self.assertFalse(prohibited.exists())


if __name__ == "__main__":
    unittest.main()
