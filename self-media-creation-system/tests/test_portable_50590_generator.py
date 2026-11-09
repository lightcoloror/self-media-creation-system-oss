"""Owner-run tests for the portable 50590 fixture generator candidate.

These tests exercise only ``scripts/generate_content_contract_50590_fixtures.py``.
The owner assembles the public project layout and supplies:

- ``fixtures/content-contract-50590-owner.v1.json``
- ``fixtures/content-contract-50590-owner.v1.negative-cases.json``
- ``fixtures/declared-synthetic-baseline.json``

All fixture references are relative to the project root. No task-private or
absolute workspace paths are embedded.

The overlay does not ship ``fixtures/declared-synthetic-baseline.json``. The
owner derives it from the already-public ``positive_cases.legacy_baseline``
payload before running the suite; see the portable generator document for the
stdlib extraction recipe.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_content_contract_50590_fixtures.py"
FIXTURES = ROOT / "fixtures"
BASELINE = FIXTURES / "declared-synthetic-baseline.json"
POSITIVE = FIXTURES / "content-contract-50590-owner.v1.json"
NEGATIVE = FIXTURES / "content-contract-50590-owner.v1.negative-cases.json"

POSITIVE_FILENAME = "content-contract-50590-owner.v1.json"
NEGATIVE_FILENAME = "content-contract-50590-owner.v1.negative-cases.json"

FIRST_FIELDS = (
    "audience_entry_question",
    "client_decision",
    "hidden_assumptions",
    "professional_core_question",
    "public_expertise_level",
    "question_structure_route",
    "scope_boundary",
    "surface_answer",
)
SECOND_FIELDS = (
    "current_piece_decision",
    "manual_route_override",
    "next_piece_candidates",
    "planning_scope",
    "series_question",
    "structure_route",
    "structure_route_note",
)
ALL_FIELDS = FIRST_FIELDS + SECOND_FIELDS
EXPECTED_CASE_ORDER = ("legacy_baseline",) + FIRST_FIELDS + SECOND_FIELDS + ("all_fields",)

EXPECTED_FIRST = {
    "audience_entry_question": "家庭已经有基础保障时，真正要决定什么？",
    "client_decision": "决定继续补充、暂缓，或先处理现金流问题。",
    "hidden_assumptions": ["保额越多越好", "所有家庭的优先顺序相同"],
    "professional_core_question": "现有风险缺口是否超过家庭可承受范围？",
    "public_expertise_level": "client-usable",
    "question_structure_route": "decision-reframe",
    "scope_boundary": "这是完全虚构的结构 fixture，不构成产品或个案建议。",
    "surface_answer": "先看缺口、现金流和家庭优先事项，再决定是否补充。",
}
EXPECTED_SECOND = {
    "current_piece_decision": "本篇只解释决策顺序，不推荐产品。",
    "manual_route_override": {
        "stage": "draft",
        "from": "direct-answer",
        "to": "decision-reframe",
        "reason": "人工判断本篇应先澄清家庭决策任务。",
        "changed_by": "human",
    },
    "next_piece_candidates": ["怎样盘点现金流", "怎样记录已有保障"],
    "planning_scope": "single",
    "series_question": "家庭保障应该按什么顺序梳理？",
    "structure_route": "decision-reframe",
    "structure_route_note": "先回答表面问题，再向前重构一层。",
}

STANDALONE_BASELINE = {
    "schema_version": "0.2",
    "content_id": "demo-standalone-alias-baseline",
    "title": "合成 alias 回归基线",
    "status": "candidate",
    "gates": {
        "fact": {"status": "not-checked"},
        "privacy": {"status": "not-checked"},
        "compliance": {"status": "not-checked"},
        "rights": {"status": "not-checked"},
    },
    "intent": {"topic": "合成 alias 回归基线"},
    "publication": {"boundary": "manual-only", "receipts": []},
}


def load_generator_module():
    spec = importlib.util.spec_from_file_location("portable_50590_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import candidate generator: {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cli(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *arguments],
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_files(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


class Portable50590GeneratorTests(unittest.TestCase):
    def test_generates_byte_exact_public_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "out"
            completed = run_cli("--baseline", str(BASELINE), "--output-dir", str(output))
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                {POSITIVE_FILENAME, NEGATIVE_FILENAME},
                {path.name for path in output.iterdir()},
            )
            self.assertEqual(POSITIVE.read_bytes(), (output / POSITIVE_FILENAME).read_bytes())
            self.assertEqual(NEGATIVE.read_bytes(), (output / NEGATIVE_FILENAME).read_bytes())

    def test_repeated_runs_preserve_bytes_and_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "out"
            sources = (BASELINE, POSITIVE, NEGATIVE)
            before = {path.name: sha256(path) for path in sources}
            first = run_cli("--baseline", str(BASELINE), "--output-dir", str(output))
            self.assertEqual(0, first.returncode, first.stderr)
            first_bytes = {
                name: (output / name).read_bytes()
                for name in (POSITIVE_FILENAME, NEGATIVE_FILENAME)
            }
            second = run_cli("--baseline", str(BASELINE), "--output-dir", str(output))
            self.assertEqual(0, second.returncode, second.stderr)
            second_bytes = {
                name: (output / name).read_bytes()
                for name in (POSITIVE_FILENAME, NEGATIVE_FILENAME)
            }
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(before, {path.name: sha256(path) for path in sources})

    def test_relocated_unicode_space_project_produces_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            moved = Path(raw) / "移动 项目 副本"
            shutil.copytree(ROOT / "scripts", moved / "scripts")
            shutil.copytree(FIXTURES, moved / "fixtures")
            output = Path(raw) / "generated out"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(moved / "scripts" / GENERATOR.name),
                    "--baseline",
                    str(moved / "fixtures" / BASELINE.name),
                    "--output-dir",
                    str(output),
                ],
                cwd=str(moved),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(POSITIVE.read_bytes(), (output / POSITIVE_FILENAME).read_bytes())
            self.assertEqual(NEGATIVE.read_bytes(), (output / NEGATIVE_FILENAME).read_bytes())

    def test_positive_structure_matches_17_cases_and_15_fields(self) -> None:
        fixture = read_json(POSITIVE)
        cases = fixture["positive_cases"]
        self.assertEqual(list(EXPECTED_CASE_ORDER), list(cases))
        self.assertEqual(17, len(cases))
        self.assertEqual(8, len(FIRST_FIELDS))
        self.assertEqual(7, len(SECOND_FIELDS))
        baseline_intent = read_json(BASELINE)["intent"]
        for field in ALL_FIELDS:
            self.assertIn(field, cases[field]["intent"], field)
            self.assertEqual(1, len(set(cases[field]["intent"]) - set(baseline_intent)), field)
        self.assertEqual(
            list(baseline_intent) + list(FIRST_FIELDS) + list(SECOND_FIELDS),
            list(cases["all_fields"]["intent"]),
        )

    def test_negative_matrix_structure_matches_26_cases_and_15_fields(self) -> None:
        cases = read_json(NEGATIVE)["cases"]
        self.assertEqual(26, len(cases))
        self.assertEqual(26, len({case["id"] for case in cases}))
        field_cases = [case for case in cases if case.get("kind") == "field_negative"]
        self.assertEqual(15, len(field_cases))
        self.assertEqual(set(ALL_FIELDS), {case["field"] for case in field_cases})
        for case in field_cases:
            self.assertEqual(1, len(case["operations"]), case["id"])
            self.assertTrue(
                case["operations"][0]["path"].startswith(f"intent.{case['field']}"),
                case["id"],
            )

    def test_declared_negative_flag_controls_are_preserved(self) -> None:
        cases = read_json(NEGATIVE)["cases"]
        invalid = []
        valid_rejected = []
        valid_accepted = []
        for case in cases:
            self.assertIsInstance(case["expect_schema_valid"], bool, case["id"])
            self.assertIsInstance(case["expect_facade_accepted"], bool, case["id"])
            if case["expect_schema_valid"] is False:
                invalid.append(case["id"])
            elif case["expect_facade_accepted"] is False:
                valid_rejected.append(case["id"])
            else:
                valid_accepted.append(case["id"])
        self.assertEqual(21, len(invalid))
        self.assertEqual(3, len(valid_rejected))
        self.assertEqual(2, len(valid_accepted))
        self.assertEqual(
            ["publication_receipt_attached", "status_publish_ready", "status_published"],
            valid_rejected,
        )
        self.assertEqual(
            ["privacy_gate_blocked_preserved", "review_gate_needs_review_preserved"],
            valid_accepted,
        )

    def test_first_second_values_and_case_independence(self) -> None:
        module = load_generator_module()
        self.assertEqual(EXPECTED_FIRST, module.FIRST)
        self.assertEqual(EXPECTED_SECOND, module.SECOND)
        baseline = read_json(BASELINE)
        cases = read_json(POSITIVE)["positive_cases"]
        self.assertEqual(baseline, cases["legacy_baseline"])
        for field, value in {**EXPECTED_FIRST, **EXPECTED_SECOND}.items():
            expected = copy.deepcopy(baseline)
            expected["intent"][field] = copy.deepcopy(value)
            self.assertEqual(expected, cases[field], field)
        expected_all = copy.deepcopy(baseline)
        expected_all["intent"].update(copy.deepcopy(EXPECTED_FIRST))
        expected_all["intent"].update(copy.deepcopy(EXPECTED_SECOND))
        self.assertEqual(expected_all, cases["all_fields"])

    def test_synthetic_markers_are_preserved(self) -> None:
        positive = read_json(POSITIVE)
        negative = read_json(NEGATIVE)
        self.assertEqual("content-contract-50590-owner-fixture.v1", positive["schema_version"])
        self.assertEqual(
            "content-contract-50590-owner-negative-fixture.v1",
            negative["schema_version"],
        )
        self.assertIs(True, positive["synthetic_only"])
        self.assertIs(True, negative["synthetic_only"])
        for name, payload in positive["positive_cases"].items():
            self.assertEqual("0.2", payload["schema_version"], name)
            self.assertNotIn("real_data", payload, name)
            self.assertEqual("candidate", payload["status"], name)
            self.assertEqual("manual-only", payload["publication"]["boundary"], name)
            self.assertEqual([], payload["publication"]["receipts"], name)

    def test_missing_required_cli_arguments_fail_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workdir = Path(raw)
            attempts = (
                (),
                ("--baseline", str(BASELINE)),
                ("--output-dir", str(workdir / "out")),
            )
            for arguments in attempts:
                with self.subTest(arguments=arguments):
                    completed = run_cli(*arguments, cwd=workdir)
                    self.assertNotEqual(0, completed.returncode)
                    self.assertFalse((workdir / "out").exists())
                    self.assertEqual([], list(workdir.glob("content-contract-50590-*")))

    def test_invalid_baseline_fails_before_any_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workdir = Path(raw)
            invalid_inputs = {
                "malformed.json": "{",
                "array.json": "[]\n",
                "missing-intent.json": '{"schema_version": "0.2"}\n',
                "intent-array.json": '{"intent": []}\n',
            }
            for name, text in invalid_inputs.items():
                with self.subTest(baseline=name):
                    baseline = workdir / name
                    baseline.write_text(text, encoding="utf-8")
                    output = workdir / f"out-{name}"
                    completed = run_cli(
                        "--baseline", str(baseline), "--output-dir", str(output), cwd=workdir
                    )
                    self.assertNotEqual(0, completed.returncode)
                    self.assertFalse(output.exists())
            missing = workdir / "missing-baseline.json"
            missing_output = workdir / "out-missing"
            completed = run_cli(
                "--baseline", str(missing), "--output-dir", str(missing_output), cwd=workdir
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertFalse(missing_output.exists())
            self.assertEqual([], list(workdir.glob("content-contract-50590-*")))

    def test_baseline_output_alias_refusal_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workdir = Path(raw)
            sentinels = {}
            for name in ("unrelated-sentinel-a.txt", "unrelated-sentinel-b.txt"):
                sentinel = workdir / name
                sentinel.write_text(f"keep {name}\n", encoding="utf-8")
                sentinels[name] = sentinel.read_bytes()
            baseline_text = json.dumps(STANDALONE_BASELINE, ensure_ascii=False, indent=2) + "\n"
            alias_cases = (
                (POSITIVE_FILENAME, str(workdir / POSITIVE_FILENAME)),
                (NEGATIVE_FILENAME, str(workdir / NEGATIVE_FILENAME)),
                (POSITIVE_FILENAME + ".tmp", str(workdir / (POSITIVE_FILENAME + ".tmp"))),
                (NEGATIVE_FILENAME + ".tmp", str(workdir / (NEGATIVE_FILENAME + ".tmp"))),
                (POSITIVE_FILENAME, f"./{POSITIVE_FILENAME}"),
                (POSITIVE_FILENAME + ".tmp", f"./{POSITIVE_FILENAME}.tmp"),
            )
            for target_name, alias in alias_cases:
                with self.subTest(alias=alias):
                    target = workdir / target_name
                    target.write_text(baseline_text, encoding="utf-8")
                    baseline_before = target.read_bytes()
                    completed = run_cli(
                        "--baseline", alias, "--output-dir", str(workdir), cwd=workdir
                    )
                    self.assertNotEqual(0, completed.returncode, alias)
                    self.assertTrue(target.exists(), target_name)
                    self.assertEqual(baseline_before, target.read_bytes(), target_name)
                    for name, content in sentinels.items():
                        self.assertEqual(content, (workdir / name).read_bytes(), name)
                    self.assertEqual(
                        {target_name} | set(sentinels),
                        {path.name for path in workdir.iterdir()},
                        target_name,
                    )
                    target.unlink()

    def test_cli_writes_only_requested_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            output = parent / "requested-out"
            project_before = project_files(ROOT)
            fixtures_before = {path.name: sha256(path) for path in FIXTURES.iterdir() if path.is_file()}
            completed = run_cli("--baseline", str(BASELINE), "--output-dir", str(output))
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                {POSITIVE_FILENAME, NEGATIVE_FILENAME},
                {path.name for path in output.iterdir()},
            )
            self.assertEqual([], list(output.glob("*.tmp")))
            self.assertEqual({"requested-out"}, {path.name for path in parent.iterdir()})
            self.assertEqual(project_before, project_files(ROOT))
            self.assertEqual(
                fixtures_before,
                {path.name: sha256(path) for path in FIXTURES.iterdir() if path.is_file()},
            )


if __name__ == "__main__":
    unittest.main()
