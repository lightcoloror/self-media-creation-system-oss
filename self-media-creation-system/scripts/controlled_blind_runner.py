#!/usr/bin/env python3
"""Run the five synthetic self-media cold starts and emit auditable receipts."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "scripts" / "self_media_agent.py"
OUT = ROOT / "outputs" / "controlled-blind-20260822" / "two-layer-handoff-retest"
RECIPES = [
    ("T01", "moments-short-post"),
    ("T02", "xhs-evidence-graphic"),
    ("T03", "case-video-candidate"),
    ("T04", "publication-feedback-review"),
    ("T05", "context-efficient-rework"),
]

SPEC = importlib.util.spec_from_file_location("controlled_blind_self_media_agent", AGENT)
assert SPEC and SPEC.loader
AGENT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGENT_MODULE)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(recipe: str) -> dict:
    fixture = ROOT / "fixtures" / "agent-entry" / f"{recipe}.request.json"
    input_bytes = fixture.read_bytes()
    command = [sys.executable, "-B", str(AGENT), "run-example", "--recipe", recipe]
    p = subprocess.run(command, cwd=ROOT, capture_output=True)
    stdout = p.stdout
    result = json.loads(stdout)
    capsule = result if result.get("schema_version") == "self-media-task-capsule.v2" else None
    capsule_bytes = json.dumps(capsule, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() if capsule else b""
    return {
        "command": " ".join(command),
        "exit_code": p.returncode,
        "stderr_bytes": len(p.stderr),
        "error_or_retry": {"error": None if p.returncode == 0 else result.get("error_code"), "automatic_retry": result.get("automatic_retry", False), "retry_count": 0},
        "inputs": {"fixture": fixture.relative_to(ROOT).as_posix(), "entry_bytes": len(input_bytes), "entry_sha256": sha(input_bytes), "synthetic_only": True},
        "capsule": capsule,
        "capsule_bytes": len(capsule_bytes),
        "capsule_sha256": sha(capsule_bytes) if capsule else None,
    }


def validate(case: dict, first: dict, second: dict) -> dict:
    c = first["capsule"]
    checks = {
        "exit_zero": first["exit_code"] == 0,
        "synthetic_only": first["inputs"]["synthetic_only"] and c["provenance"]["synthetic_only"],
        "capsule_ready": c["status"] == "routing_ready",
        "capsule_hash_valid": c["payload_sha256"] == sha(json.dumps({k: v for k, v in c.items() if k != "payload_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
        "schema_route_bound": c["canonical_route"] == {"contract_set_id": "registered-content-routing", "contract_set_version": "1.0.0", "load_policy": "whole-contract-set-only", "legacy_fallback": False},
        "human_stop": c["step_index"][-1]["interface"] == "human_gate" and all(s["stop_on_error"] for s in c["step_index"]),
        "every_step_requires_handoff": all(s["handoff_required"] and s["output_receipt_required"] for s in c["step_index"]),
        "tool_index_complete": len(c["tool_index"]) == len(c["step_index"]),
        "publication_boundary": c["boundaries"] == {"publication": "manual-only", "external_send": "not-authorized", "customer_contact": "not-authorized", "crm_write": "not-authorized", "knowledge_base_write": "not-authorized", "provider_call": "not-authorized-by-this-entry"},
        "double_run_byte_stable": first["capsule_sha256"] == second["capsule_sha256"] and first["capsule_bytes"] == second["capsule_bytes"],
        "no_retry": first["error_or_retry"]["automatic_retry"] is False and second["error_or_retry"]["automatic_retry"] is False,
    }
    return {"passed": all(checks.values()), "checks": checks}


def exercise_handoffs(recipe: str, capsule: dict) -> list[dict]:
    rows = []
    for step in capsule["step_index"]:
        step_root = OUT / "handoffs" / recipe / step["step_id"]
        step_root.mkdir(parents=True, exist_ok=True)
        capsule_path = step_root / "capsule.json"
        AGENT_MODULE.write_or_print(capsule, capsule_path)
        artifacts = []
        for index, source_role in enumerate(step["input_roles"]):
            source = step_root / f"input-{index}.json"
            source.write_text(
                json.dumps({"synthetic_only": True, "source_role": source_role}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            artifacts.append(
                {
                    "artifact_id": f"input-{index}",
                    "role": "source_manifest",
                    "source_role": source_role,
                    "path": source.name,
                    "load_mode": "reference",
                    "expected_sha256": AGENT_MODULE.sha256_file(source),
                }
            )
        manifest_path = step_root / "context-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "self-media-context-input.v1",
                    "task_id": capsule["request_id"],
                    "stage": step["context_stage"],
                    "budget": {"max_inline_bytes": 4096},
                    "artifacts": artifacts,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        handoff_path = step_root / "handoff.json"
        handoff = AGENT_MODULE.prepare_step_handoff(
            capsule_path,
            step["step_id"],
            manifest_path,
            step_root / "context-receipt.json",
            handoff_path,
        )
        candidate = step_root / "candidate.json"
        candidate.write_text('{"synthetic_only":true}\n', encoding="utf-8")
        receipt = {
            "schema_version": "self-media-step-output-receipt.v1",
            "status": "human_gate_recorded" if step["interface"] == "human_gate" else "candidate_ready",
            "handoff": {"path": handoff_path.name, "sha256": AGENT_MODULE.sha256_file(handoff_path)},
            "step_id": step["step_id"],
            "tool_id": step["tool_id"],
            "output_contract": step["output_contract"],
            "outputs": [{"path": candidate.name, "sha256": AGENT_MODULE.sha256_file(candidate)}],
            "boundaries": capsule["boundaries"],
        }
        receipt["payload_sha256"] = AGENT_MODULE.sha256_value(receipt)
        receipt_path = step_root / "output-receipt.json"
        AGENT_MODULE.write_or_print(receipt, receipt_path)
        verification = AGENT_MODULE.verify_step_output(handoff_path, receipt_path)
        rows.append(
            {
                "step_id": step["step_id"],
                "handoff_sha256": AGENT_MODULE.sha256_file(handoff_path),
                "handoff_bytes": handoff_path.stat().st_size,
                "tool_discovery_mode": handoff["tool_contract"]["discovery_mode"],
                "registry_or_source_bound": bool(
                    handoff["tool_contract"].get("registry_entry_sha256")
                    or handoff["tool_contract"].get("source_ref")
                    or handoff["tool_contract"]["discovery_mode"] == "human_gate"
                ),
                "consumer_command_present": "consumer_command" in handoff["tool_contract"],
                "output_receipt_verified": verification["ok"],
            }
        )
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for test_id, recipe in RECIPES:
        first, second = run(recipe), run(recipe)
        first_handoffs = exercise_handoffs(recipe, first["capsule"])
        second_handoffs = exercise_handoffs(recipe, second["capsule"])
        decision = {"owner": os.environ.get("VALIDATION_ACTOR", "Codex deterministic contract runner"), "route": first["capsule"]["recipe_id"], "inputs": first["inputs"], "stop_conditions": first["capsule"]["stop_conditions"], "command": first["command"], "quality_gates": first["capsule"]["quality_gates"], "publication_boundary": first["capsule"]["boundaries"]}
        validation = validate({}, first, second)
        validation["checks"]["all_step_handoffs_verified"] = all(
            row["registry_or_source_bound"] and row["output_receipt_verified"]
            for row in first_handoffs
        )
        validation["checks"]["step_handoffs_byte_stable"] = first_handoffs == second_handoffs
        validation["passed"] = all(validation["checks"].values())
        case = {"test_id": test_id, "recipe_id": recipe, "decision": decision, "result": {"run_1": first, "run_2": second, "step_handoffs": first_handoffs, "validation": validation}}
        (OUT / f"{test_id}-{recipe}.json").write_text(json.dumps(case, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        cases.append(case)
    summary = {"schema_version": "controlled-blind-retest.v2", "run_id": "20260822-two-layer-handoff-retest", "owner": os.environ.get("VALIDATION_ACTOR", "Codex deterministic contract runner"), "synthetic_only": True, "cases": cases, "passed": all(x["result"]["validation"]["passed"] for x in cases)}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "cases": len(cases), "passed": summary["passed"]}, ensure_ascii=False))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
