#!/usr/bin/env python3
"""Bind synthetic content candidates to the existing manual feedback tracker.

This is deliberately a thin batch adapter.  It creates no new feedback state
machine: each item is converted to the existing tracker input and is then
handled by ``publication_feedback_tracker``.  All inputs must be explicitly
synthetic; no platform, CRM, network, or account operation is available.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import publication_feedback_tracker as tracker


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / ".runtime"
WORKSPACE_ROOT = ROOT.parent
EXTERNAL_RECEIPT_ROOT = WORKSPACE_ROOT / "docs" / "codex-session-index"
ACCOUNT_TEMPLATE = ROOT / "fixtures" / "vibe-living-synthetic-loop-v1" / "account.json"
TOPIC_TEMPLATE = (
    ROOT / "fixtures" / "vibe-living-synthetic-loop-v1" / "questions" / "claims-preparation" / "topic.json"
)
EXPECTED_PLAN_KEYS = {
    "schema_version",
    "synthetic_only",
    "batch_id",
    "generated_at",
    "account_template_ref",
    "account_template_sha256",
    "candidate_pack_ref",
    "candidate_pack_sha256",
    "candidate_receipt_ref",
    "candidate_receipt_sha256",
    "items",
}
EXPECTED_ITEM_KEYS = {
    "key",
    "topic_id",
    "title",
    "audience_problem",
    "candidate_ref",
    "candidate_sha256",
    "run_manifest_ref",
    "run_manifest_sha256",
    "review_packet_ref",
    "review_packet_sha256",
    "publication",
    "observations",
}


class BatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise BatchError("invalid_or_missing_json", str(error)) from error
    if not isinstance(value, dict):
        raise BatchError("invalid_json_root", str(path))
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def repo_ref(ref: str) -> Path:
    if not isinstance(ref, str) or not ref:
        raise BatchError("invalid_artifact_ref", "reference must be a non-empty repository-relative string")
    path = (ROOT / ref).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise BatchError("artifact_ref_escape", ref) from error
    if not path.is_file():
        raise BatchError("artifact_missing", ref)
    return path


def source_ref(ref: str) -> Path:
    """Resolve an input artifact from the repo or the read-only receipt ledger.

    The batch adapter may verify the prior dispatch receipt, which is owned by
    the workspace receipt ledger rather than this repository.  This is a
    narrowly allowlisted read-only exception; generated tracker inputs remain
    repository-local and continue to use ``repo_ref``.
    """
    if not isinstance(ref, str) or not ref:
        raise BatchError("invalid_artifact_ref", "reference must be a non-empty repository-relative string")
    path = (ROOT / ref).resolve()
    allowed_roots = (ROOT.resolve(), EXTERNAL_RECEIPT_ROOT.resolve())
    try:
        next(root for root in allowed_roots if path.is_relative_to(root))
    except StopIteration as error:
        raise BatchError("artifact_ref_escape", ref) from error
    if not path.is_file():
        raise BatchError("artifact_missing", ref)
    return path


def runtime_output(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(RUNTIME_ROOT.resolve())
    except ValueError as error:
        raise BatchError("output_outside_runtime", str(path)) from error
    if resolved.is_symlink():
        raise BatchError("output_reparse_prohibited", str(path))
    return resolved


def require_exact_keys(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise BatchError("invalid_shape", f"{label} must be an object")
    if set(value) != keys:
        raise BatchError("unexpected_or_missing_field", f"{label}: expected {sorted(keys)}, got {sorted(value)}")


def verify_ref(ref: str, expected_sha: str, label: str) -> Path:
    path = source_ref(ref)
    observed = sha256_file(path)
    if observed != expected_sha:
        raise BatchError("candidate_hash_drift", f"{label}: expected {expected_sha}, got {observed}")
    return path


def validate_plan(plan: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[dict[str, Any], dict[str, Any]]]]:
    tracker.reject_sensitive_keys(plan)
    require_exact_keys(plan, EXPECTED_PLAN_KEYS, "plan")
    if plan["schema_version"] != "candidate-feedback-batch-plan.v1" or plan["synthetic_only"] is not True:
        raise BatchError("synthetic_only_required", "only synthetic candidate feedback plans are accepted")
    if not isinstance(plan["items"], list) or len(plan["items"]) != 3:
        raise BatchError("candidate_count_invalid", "exactly three candidate chains are required")
    account_path = verify_ref(plan["account_template_ref"], plan["account_template_sha256"], "account_template")
    verify_ref(plan["candidate_pack_ref"], plan["candidate_pack_sha256"], "candidate_pack")
    verify_ref(plan["candidate_receipt_ref"], plan["candidate_receipt_sha256"], "candidate_receipt")
    account = load_json(account_path)
    tracker.validate_schema(account, tracker.ACCOUNT_SCHEMA, "account_template")
    if "synthetic" not in account.get("display_name", "").lower():
        raise BatchError("synthetic_source_required", "account template must be explicitly synthetic")
    keys: set[str] = set()
    content_ids: set[str] = set()
    validated: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for item in plan["items"]:
        require_exact_keys(item, EXPECTED_ITEM_KEYS, "plan.items[]")
        if item["key"] in keys:
            raise BatchError("duplicate_candidate_key", item["key"])
        keys.add(item["key"])
        candidate_path = verify_ref(item["candidate_ref"], item["candidate_sha256"], item["candidate_ref"])
        verify_ref(item["run_manifest_ref"], item["run_manifest_sha256"], item["run_manifest_ref"])
        verify_ref(item["review_packet_ref"], item["review_packet_sha256"], item["review_packet_ref"])
        candidate = load_json(candidate_path)
        tracker.validate_schema(candidate, tracker.CONTENT_SCHEMA, "candidate")
        if "synthetic-only" not in candidate.get("tags", []) or candidate.get("status") != "candidate":
            raise BatchError("synthetic_source_required", item["candidate_ref"])
        if candidate["content_id"] in content_ids:
            raise BatchError("duplicate_content_id", candidate["content_id"])
        content_ids.add(candidate["content_id"])
        if item["title"] != candidate["title"]:
            raise BatchError("title_reference_drift", item["key"])
        if item["publication"].get("platform") != account["platform"]:
            raise BatchError("platform_reference_drift", item["key"])
        validated.append((item, candidate))
    return account, validated


def build_topic(item: dict[str, Any], account_id: str, now: str) -> dict[str, Any]:
    topic = copy.deepcopy(load_json(TOPIC_TEMPLATE))
    topic.update(
        {
            "topic_id": item["topic_id"],
            "title": item["title"],
            "audience_problem": item["audience_problem"],
            "target_account_ids": [account_id],
            "created_at": now,
            "updated_at": now,
            "notes": "Synthetic candidate-feedback bridge. This is not a real frequency, publication or customer record.",
        }
    )
    return topic


def build_content(item: dict[str, Any], candidate: dict[str, Any], account_id: str) -> dict[str, Any]:
    content = copy.deepcopy(candidate)
    content["operating_refs"] = {"account_ids": [account_id], "topic_ids": [item["topic_id"]]}
    content["tags"] = sorted(set(content.get("tags", [])) | {"synthetic-feedback-bridge"})
    content["provenance"]["sources"].append(
        {
            "source_type": "workspace-file",
            "ref": item["candidate_ref"],
            "evidence_status": "verified",
            "note": f"Hash-bound candidate artifact sha256={item['candidate_sha256']}; synthetic-only feedback bridge.",
        }
    )
    return content


def build_tracker_input(item: dict[str, Any], source_dir: Path, account: dict[str, Any], topic: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    refs = {
        "account_ref": (source_dir / "account.json").relative_to(ROOT).as_posix(),
        "account_sha256": sha256_file(source_dir / "account.json"),
        "topic_ref": (source_dir / "topic.json").relative_to(ROOT).as_posix(),
        "topic_sha256": sha256_file(source_dir / "topic.json"),
        "content_item_ref": (source_dir / "content-item.json").relative_to(ROOT).as_posix(),
        "content_item_sha256": sha256_file(source_dir / "content-item.json"),
    }
    return {
        "schema_version": "manual-publication-feedback-input.v1",
        "synthetic_only": True,
        "mode": "manual_entry_only",
        "content_id": content["content_id"],
        "source_objects": refs,
        "publication": item["publication"],
        "privacy": {
            "raw_comments_included": False,
            "tracking_parameters_included": False,
            "direct_identifiers_included": False,
            "customer_text_included": False,
        },
        "observations": item["observations"],
    }


def generate(plan_path: Path, output: Path) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    try:
        plan_ref = plan_path.relative_to(ROOT.resolve()).as_posix()
    except ValueError as error:
        raise BatchError("artifact_ref_escape", str(plan_path)) from error
    plan_path = repo_ref(plan_ref)
    output = runtime_output(output)
    plan = load_json(plan_path)
    account, items = validate_plan(plan)
    plan_hash = canonical_sha256(plan)
    manifest_path = output / "candidate-feedback-batch.manifest.v1.json"
    if output.exists():
        if manifest_path.is_file():
            existing = load_json(manifest_path)
            if existing.get("plan_sha256") == plan_hash:
                validate(output)
                return {"status": "already_completed", "manifest": str(manifest_path), "manifest_sha256": sha256_file(manifest_path)}
        raise BatchError("output_exists", str(output))
    output.mkdir(parents=True)
    write_json(output / "batch-plan.json", plan)
    records: list[dict[str, Any]] = []
    for item, candidate in items:
        source_dir = output / "sources" / item["key"]
        source_dir.mkdir(parents=True)
        topic = build_topic(item, account["account_id"], plan["generated_at"])
        content = build_content(item, candidate, account["account_id"])
        write_json(source_dir / "account.json", account)
        write_json(source_dir / "topic.json", topic)
        write_json(source_dir / "content-item.json", content)
        entry = build_tracker_input(item, source_dir, account, topic, content)
        input_path = output / "inputs" / f"{item['key']}.manual-publication-feedback-input.json"
        write_json(input_path, entry)
        tracker.validate_input(entry)
        pack_root = output / "packs" / item["key"]
        result = tracker.generate_pack(input_path, pack_root)
        tracker.validate_pack_strict(pack_root)
        event = load_json(pack_root / "publication-events.json")["items"][0]
        snapshots = load_json(pack_root / "performance-snapshots.json")["items"]
        feedback = load_json(pack_root / "content-item.json")["feedback"]
        records.append(
            {
                "key": item["key"],
                "content_id": content["content_id"],
                "candidate_ref": item["candidate_ref"],
                "candidate_sha256": item["candidate_sha256"],
                "publication_id": event["publication_id"],
                "publication_event_id": event["event_id"],
                "manual_receipt": {
                    "manual_action": True,
                    "synthetic_only": True,
                    "external_action_performed": False,
                    "platform": event["platform"],
                    "occurred_at": event["occurred_at"],
                    "frozen_content_sha256": sha256_file(source_dir / "content-item.json"),
                },
                "snapshot_ids": {snapshot["window_label"]: snapshot["snapshot_id"] for snapshot in snapshots},
                "feedback_status": {
                    "content": feedback["content_signal_status"],
                    "business": feedback["business_signal_status"],
                    "crm_write_performed": feedback["business_signals"]["crm_write_performed"],
                },
                "pack_manifest_sha256": result["manifest_sha256"],
            }
        )
    manifest = {
        "schema_version": "candidate-feedback-batch.v1",
        "batch_id": plan["batch_id"],
        "synthetic_only": True,
        "status": "synthetic_feedback_validated",
        "plan_sha256": plan_hash,
        "candidate_pack_ref": plan["candidate_pack_ref"],
        "candidate_pack_sha256": plan["candidate_pack_sha256"],
        "candidate_receipt_ref": plan["candidate_receipt_ref"],
        "candidate_receipt_sha256": plan["candidate_receipt_sha256"],
        "boundaries": {
            "manual_action_required": True,
            "external_action_performed": False,
            "publication_automated": False,
            "platform_accessed": False,
            "crm_write_performed": False,
            "real_usage_proof": False,
        },
        "chains": records,
    }
    write_json(manifest_path, manifest)
    validate(output)
    return {"status": "completed", "manifest": str(manifest_path), "manifest_sha256": sha256_file(manifest_path)}


def validate(output: Path) -> None:
    output = runtime_output(output)
    manifest = load_json(output / "candidate-feedback-batch.manifest.v1.json")
    if manifest.get("synthetic_only") is not True or manifest.get("status") != "synthetic_feedback_validated":
        raise BatchError("synthetic_boundary_drift", "batch manifest must remain synthetic-only")
    if manifest.get("boundaries", {}).get("real_usage_proof") is not False:
        raise BatchError("real_usage_proof_forbidden", "synthetic fixture cannot become real usage proof")
    chains = manifest.get("chains", [])
    if not isinstance(chains, list) or len(chains) != 3:
        raise BatchError("candidate_count_invalid", "three feedback chains are required")
    event_ids: set[str] = set()
    for chain in chains:
        key = chain["key"]
        pack = output / "packs" / key
        tracker.validate_pack_strict(pack)
        if chain["publication_event_id"] in event_ids:
            raise BatchError("duplicate_publication_event", key)
        event_ids.add(chain["publication_event_id"])
        if chain["manual_receipt"]["manual_action"] is not True or chain["manual_receipt"]["synthetic_only"] is not True:
            raise BatchError("manual_receipt_drift", key)
        if chain["manual_receipt"]["external_action_performed"] is not False:
            raise BatchError("external_action_forbidden", key)
        if chain["feedback_status"]["crm_write_performed"] is not False:
            raise BatchError("crm_boundary_violation", key)


def check(plan_path: Path, output: Path) -> dict[str, Any]:
    first = generate(plan_path, output)
    second = generate(plan_path, output)
    if second["status"] != "already_completed" or first["manifest_sha256"] != second["manifest_sha256"]:
        raise BatchError("idempotency_failed", "same plan did not return the same completed manifest")
    validate(output)
    return {"status": "passed", "idempotency": "byte-stable-manifest", "manifest_sha256": first["manifest_sha256"]}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("generate", "validate", "check"):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True, type=Path)
        if name != "validate":
            command.add_argument("--plan", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate":
            validate(args.output)
            result = {"status": "passed", "output": str(args.output), "synthetic_only": True}
        elif args.command == "generate":
            result = generate(args.plan, args.output)
        else:
            result = check(args.plan, args.output)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (BatchError, tracker.TrackerError) as error:
        code = getattr(error, "code", "tracker_error")
        print(json.dumps({"status": code, "message": str(error)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
