#!/usr/bin/env python3
"""Validate reusable case-video governance contracts without rendering or publishing.

The module deliberately owns only thin validation and deletion planning. Existing
ASR, editing, rendering, review, and publication implementations remain canonical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "financial": ROOT / "schemas" / "case-financial-facts.v1.schema.json",
    "localized_subtitles": ROOT / "schemas" / "localized-subtitle-review.v1.schema.json",
    "lifecycle": ROOT / "schemas" / "artifact-lifecycle-manifest.v1.schema.json",
    "publication": ROOT / "schemas" / "platform-publication-package.v1.schema.json",
    "publication_release": ROOT / "schemas" / "platform-publication-package.v2.schema.json",
    "publication_post_upload": ROOT / "schemas" / "platform-publication-package.v2.schema.json",
}

PREPUBLICATION_PRIVACY_GATE_SCHEMA = (
    ROOT / "schemas" / "prepublication-privacy-gate.v1.schema.json"
)

RELEASE_CREDENTIAL_AUTHORITY = {
    "automatic_publish": False,
    "execution_authorized": False,
    "external_send_authorized": False,
}

PUBLICATION_V1_PLATFORM_KEYS = {
    "platform_id",
    "enabled",
    "title",
    "short_title",
    "description",
    "tags",
    "collection_name",
    "collection_description",
    "collection_cover",
    "scheduled_at",
    "covers",
    "rules",
    "human_preview_status",
    "copy_human_review_status",
}

REQUIRED_POST_UPLOAD_CHECKS = {
    "playback",
    "audio",
    "subtitles",
    "cover",
    "privacy",
    "metadata",
}

ROLE_SCOPES = {
    "charge_item": {"charge_item", "treatment_stage"},
    "encounter_total": {"hospital_encounter"},
    "actual_payment": {"hospital_encounter", "cashflow"},
    "reimbursement": {"insurance_claim"},
    "cash_required": {"cashflow"},
    "borrowed_principal": {"borrowing"},
    "repaid_principal": {"borrowing"},
}

PROTECTED_LIFECYCLE_STATUSES = {
    "raw_source",
    "reviewed_source",
    "fine_cut",
    "candidate",
    "locked_master",
    "archival_review",
}
DELETION_ELIGIBLE_STATUSES = {"superseded", "rejected", "deletion_approved"}


class CaseGovernanceError(ValueError):
    """Stable fail-closed error returned by the governance validator."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CaseGovernanceError("artifact_unreadable", f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise CaseGovernanceError("schema_validation_failed", f"{path} must contain an object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CaseGovernanceError("artifact_unreadable", f"{path}: {error}") from error
    return digest.hexdigest()


def _validate_schema(document: dict[str, Any], kind: str) -> None:
    schema = load_json(SCHEMAS[kind])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        messages = [
            f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in errors
        ]
        raise CaseGovernanceError("schema_validation_failed", "; ".join(messages))


def _validate_schema_path(
    document: dict[str, Any], schema_path: Path, label: str
) -> None:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    if errors:
        messages = [
            f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in errors
        ]
        raise CaseGovernanceError(
            "schema_validation_failed", f"{label}: {'; '.join(messages)}"
        )


def _resolve_artifact(workspace_root: Path, artifact: dict[str, Any]) -> Path:
    root = workspace_root.resolve()
    target = (root / artifact["path"]).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise CaseGovernanceError("artifact_outside_workspace", artifact["path"]) from error
    if not target.is_file():
        raise CaseGovernanceError("artifact_unreadable", f"missing artifact: {artifact['path']}")
    actual = sha256_file(target)
    if actual != artifact["expected_sha256"]:
        raise CaseGovernanceError("source_hash_drift", artifact["path"])
    return target


def validate_financial(document: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    _validate_schema(document, "financial")
    indexed: dict[str, dict[str, Any]] = {}
    for fact in document["facts"]:
        fact_id = fact["fact_id"]
        if fact_id in indexed:
            raise CaseGovernanceError("duplicate_fact_id", fact_id)
        indexed[fact_id] = fact
        if fact["scope"] not in ROLE_SCOPES[fact["amount_role"]]:
            raise CaseGovernanceError(
                "amount_role_scope_mismatch",
                f"{fact_id}: {fact['amount_role']} cannot use scope {fact['scope']}",
            )
        if fact["evidence_status"] == "unknown":
            raise CaseGovernanceError("amount_evidence_unresolved", fact_id)
        for source in fact["source_refs"]:
            _resolve_artifact(workspace_root, source)
        wording = fact["public_wording"]
        if wording is not None:
            lower = float(wording["lower_bound"])
            upper = float(wording["upper_bound_exclusive"])
            exact = float(fact["exact_amount"])
            if upper <= lower or not (lower <= exact < upper):
                raise CaseGovernanceError(
                    "public_amount_range_mismatch",
                    f"{fact_id}: exact amount is outside its public wording range",
                )
    for fact_id, fact in indexed.items():
        for related in fact["related_fact_refs"]:
            if related == fact_id or related not in indexed:
                raise CaseGovernanceError(
                    "related_amount_fact_invalid", f"{fact_id} -> {related}"
                )
    return {
        "schema_version": document["schema_version"],
        "ledger_id": document["ledger_id"],
        "fact_count": len(indexed),
        "amount_roles": sorted({fact["amount_role"] for fact in indexed.values()}),
        "status": "passed",
        "publication_boundary": "facts_validated_only",
    }


def validate_localized_subtitles(
    document: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    _validate_schema(document, "localized_subtitles")
    _resolve_artifact(workspace_root, document["source_media"])
    if document["source_language"] == document["display_language"]:
        raise CaseGovernanceError(
            "cross_language_receipt_not_applicable",
            "source and display languages are identical",
        )
    if document["status"] != "human_confirmed":
        raise CaseGovernanceError("translation_review_incomplete", document["status"])
    seen: set[str] = set()
    prior_end = 0.0
    for segment in document["segments"]:
        segment_id = segment["segment_id"]
        if segment_id in seen:
            raise CaseGovernanceError("duplicate_subtitle_segment", segment_id)
        seen.add(segment_id)
        start = float(segment["start_seconds"])
        end = float(segment["end_seconds"])
        if end <= start:
            raise CaseGovernanceError("subtitle_time_range_invalid", segment_id)
        if start < prior_end - 1e-6:
            raise CaseGovernanceError("subtitle_segments_overlap", segment_id)
        prior_end = end
        if segment["review_status"] != "human_confirmed":
            raise CaseGovernanceError("translation_review_incomplete", segment_id)
        tags = set(segment["high_risk_tags"])
        if "none" in tags and len(tags) > 1:
            raise CaseGovernanceError("subtitle_risk_tags_invalid", segment_id)
    return {
        "schema_version": document["schema_version"],
        "receipt_id": document["receipt_id"],
        "segment_count": len(seen),
        "timing_authority": document["timing_authority"],
        "status": "passed",
        "publication_boundary": "translation_and_timing_review_only",
    }


def validate_lifecycle(document: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    _validate_schema(document, "lifecycle")
    by_id: dict[str, dict[str, Any]] = {}
    by_path: set[str] = set()
    all_parent_hashes: set[str] = set()
    for artifact in document["artifacts"]:
        artifact_id = artifact["artifact_id"]
        if artifact_id in by_id:
            raise CaseGovernanceError("duplicate_artifact_id", artifact_id)
        if artifact["path"] in by_path:
            raise CaseGovernanceError("duplicate_artifact_path", artifact["path"])
        by_id[artifact_id] = artifact
        by_path.add(artifact["path"])
        all_parent_hashes.update(artifact["parent_sha256s"])
        _resolve_artifact(workspace_root, artifact)
        if artifact["status"] in PROTECTED_LIFECYCLE_STATUSES and not artifact["locked"]:
            raise CaseGovernanceError(
                "protected_artifact_not_locked", f"{artifact_id}: {artifact['status']}"
            )
        if artifact["status"] == "superseded" and artifact["superseded_by"] is None:
            raise CaseGovernanceError("superseded_target_missing", artifact_id)

    request = document.get("deletion_request")
    if request is None:
        return {
            "schema_version": document["schema_version"],
            "manifest_id": document["manifest_id"],
            "artifact_count": len(by_id),
            "status": "passed",
            "deletion_plan": None,
        }
    if not request["user_approved"] or not request["approver"] or not request["approved_at"]:
        raise CaseGovernanceError("deletion_not_user_approved", request["request_id"])
    approved_targets: list[dict[str, str]] = []
    for artifact_id in request["target_artifact_ids"]:
        if artifact_id not in by_id:
            raise CaseGovernanceError("deletion_target_unknown", artifact_id)
        artifact = by_id[artifact_id]
        if artifact["locked"]:
            raise CaseGovernanceError("deletion_target_locked", artifact_id)
        if artifact["customer_sensitive"]:
            raise CaseGovernanceError("deletion_target_customer_sensitive", artifact_id)
        if artifact["status"] not in DELETION_ELIGIBLE_STATUSES:
            raise CaseGovernanceError(
                "deletion_status_blocked", f"{artifact_id}: {artifact['status']}"
            )
        if artifact["expected_sha256"] in all_parent_hashes:
            raise CaseGovernanceError("deletion_target_still_referenced", artifact_id)
        approved_targets.append({"artifact_id": artifact_id, "path": artifact["path"]})
    return {
        "schema_version": document["schema_version"],
        "manifest_id": document["manifest_id"],
        "artifact_count": len(by_id),
        "status": "passed",
        "deletion_plan": {
            "mode": "quarantine_only",
            "targets": approved_targets,
            "filesystem_mutation_performed": False,
        },
    }


def _character_count(value: str | None) -> int:
    return len(value or "")


def validate_publication(document: dict[str, Any], workspace_root: Path) -> dict[str, Any]:
    _validate_schema(document, "publication")
    _resolve_artifact(workspace_root, document["video"])
    created_at = datetime.fromisoformat(document["created_at"])
    seen: set[str] = set()
    enabled = 0
    for platform in document["platforms"]:
        platform_id = platform["platform_id"]
        if platform_id in seen:
            raise CaseGovernanceError("duplicate_platform", platform_id)
        seen.add(platform_id)
        for cover in platform["covers"]:
            _resolve_artifact(workspace_root, cover["artifact"])
        if platform["collection_cover"] is not None:
            _resolve_artifact(workspace_root, platform["collection_cover"]["artifact"])
        if not platform["enabled"]:
            continue
        enabled += 1
        rules = platform["rules"]
        if rules["source_status"] == "unknown":
            raise CaseGovernanceError("platform_rules_unverified", platform_id)
        title_limit = rules["title_max_characters"]
        if title_limit is None or _character_count(platform["title"]) > title_limit:
            raise CaseGovernanceError("platform_title_limit_failed", platform_id)
        short_limit = rules["short_title_max_characters"]
        if platform["short_title"] is not None:
            if short_limit is None or _character_count(platform["short_title"]) > short_limit:
                raise CaseGovernanceError("platform_short_title_limit_failed", platform_id)
        collection_limit = rules["collection_name_max_characters"]
        if platform["collection_name"] is not None:
            if collection_limit is None or _character_count(platform["collection_name"]) > collection_limit:
                raise CaseGovernanceError("platform_collection_limit_failed", platform_id)
        collection_description_limit = rules["collection_description_max_characters"]
        if platform["collection_description"] is not None:
            if (
                collection_description_limit is None
                or _character_count(platform["collection_description"])
                > collection_description_limit
            ):
                raise CaseGovernanceError(
                    "platform_collection_description_limit_failed", platform_id
                )
        ratios = [cover["ratio"] for cover in platform["covers"]]
        if len(ratios) < rules["minimum_cover_candidates"]:
            raise CaseGovernanceError("platform_cover_candidates_missing", platform_id)
        maximum_cover_candidates = rules["maximum_cover_candidates"]
        if maximum_cover_candidates is not None and len(ratios) > maximum_cover_candidates:
            raise CaseGovernanceError("platform_cover_candidates_exceeded", platform_id)
        missing_ratios = set(rules["required_cover_ratios"]) - set(ratios)
        if missing_ratios:
            raise CaseGovernanceError(
                "platform_cover_ratio_missing",
                f"{platform_id}: {sorted(missing_ratios)}",
            )
        collection_cover = platform["collection_cover"]
        if rules["collection_cover_required"] and collection_cover is None:
            raise CaseGovernanceError("platform_collection_cover_missing", platform_id)
        if collection_cover is not None:
            required_collection_ratios = set(rules["required_collection_cover_ratios"])
            if required_collection_ratios and collection_cover["ratio"] not in required_collection_ratios:
                raise CaseGovernanceError(
                    "platform_collection_cover_ratio_invalid",
                    f"{platform_id}: {collection_cover['ratio']}",
                )
        if not platform["tags"]:
            raise CaseGovernanceError("platform_tags_missing", platform_id)
        if (
            rules.get("temporary_title_field_tag_recognition") is True
            and rules.get("final_title_restore_required") is not True
        ):
            raise CaseGovernanceError("platform_final_title_restore_missing", platform_id)
        if rules.get("collection_creation_during_publish_supported") is False:
            if rules.get("attach_during_publish_requires_existing_collection") is not True:
                raise CaseGovernanceError("platform_existing_collection_gate_missing", platform_id)
            if rules.get("post_publish_add_to_collection_supported") is not True:
                raise CaseGovernanceError("platform_post_publish_collection_route_missing", platform_id)
        if platform["human_preview_status"] != "passed":
            raise CaseGovernanceError("platform_preview_pending", platform_id)
        if platform["copy_human_review_status"] != "passed":
            raise CaseGovernanceError("platform_copy_review_pending", platform_id)
        if platform["scheduled_at"] is not None:
            lead = rules["minimum_schedule_lead_minutes"]
            if lead is None:
                raise CaseGovernanceError("platform_schedule_rule_unknown", platform_id)
            scheduled_at = datetime.fromisoformat(platform["scheduled_at"])
            schedule_delta_seconds = (scheduled_at - created_at).total_seconds()
            if schedule_delta_seconds < lead * 60:
                raise CaseGovernanceError("platform_schedule_lead_failed", platform_id)
            maximum_lead = rules.get("maximum_schedule_lead_minutes")
            if maximum_lead is not None and schedule_delta_seconds > maximum_lead * 60:
                raise CaseGovernanceError("platform_schedule_horizon_failed", platform_id)
    if enabled == 0:
        raise CaseGovernanceError("no_enabled_platform", document["package_id"])
    return {
        "schema_version": document["schema_version"],
        "package_id": document["package_id"],
        "enabled_platforms": enabled,
        "status": "passed",
        "publication_mode": "manual_only",
        "automatic_publish": False,
    }


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def publication_release_scope(document: dict[str, Any]) -> str:
    """Hash immutable release inputs while excluding mutable post-upload results.

    The scope deliberately excludes package_phase, review credentials, and
    post_upload_result. A credential can therefore remain valid when a manual
    upload appends destination observations, but any change to the video,
    privacy gate, copy, covers, platform rules, correction route, or verification
    plan invalidates the approval.
    """

    platforms = []
    for platform in document["platforms"]:
        platforms.append(
            {
                key: value
                for key, value in platform.items()
                if key != "post_upload_result"
            }
        )
    return _canonical_sha256(
        {
            "schema_version": "self-media-platform-publication-release-scope.v1",
            "package_id": document["package_id"],
            "content_item_ref": document["content_item_ref"],
            "created_at": document["created_at"],
            "video": document["video"],
            "privacy_gate": document["privacy_gate"],
            "automatic_publish": document["automatic_publish"],
            "publication_mode": document["publication_mode"],
            "platforms": platforms,
        }
    )


def _publication_v1_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "self-media-platform-publication-package.v1",
        "package_id": document["package_id"],
        "content_item_ref": document["content_item_ref"],
        "created_at": document["created_at"],
        "video": document["video"],
        "automatic_publish": document["automatic_publish"],
        "publication_mode": document["publication_mode"],
        "platforms": [
            {
                key: value
                for key, value in platform.items()
                if key in PUBLICATION_V1_PLATFORM_KEYS
            }
            for platform in document["platforms"]
        ],
    }


def _validate_privacy_gate(
    document: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    gate_path = _resolve_artifact(workspace_root, document["privacy_gate"])
    gate = load_json(gate_path)
    _validate_schema_path(
        gate, PREPUBLICATION_PRIVACY_GATE_SCHEMA, "prepublication_privacy_gate"
    )
    if gate["status"] != "customer_confirmed_candidate":
        raise CaseGovernanceError(
            "privacy_gate_not_customer_confirmed", gate["status"]
        )
    if gate["manual_publication_eligible"] is not True:
        raise CaseGovernanceError(
            "privacy_gate_not_publication_eligible", gate["gate_id"]
        )
    if gate["automatic_publish"] is not False:
        raise CaseGovernanceError("authority_escalation", gate["gate_id"])
    candidate = gate["candidate"]
    video = document["video"]
    if (
        candidate["path"] != video["path"]
        or candidate["expected_sha256"] != video["expected_sha256"]
    ):
        raise CaseGovernanceError(
            "privacy_gate_candidate_drift", document["package_id"]
        )
    return gate


def _validate_release_credential(
    review_kind: str,
    reference: dict[str, Any],
    expected_scope: str,
    workspace_root: Path,
) -> None:
    credential_path = _resolve_artifact(
        workspace_root,
        {
            "path": reference["credential_ref"],
            "expected_sha256": reference["credential_sha256"],
        },
    )
    credential = load_json(credential_path)
    expected_keys = {
        "schema_version",
        "approval_kind",
        "reviewer",
        "reviewed_at",
        "decision",
        "release_scope_sha256",
        "authority",
    }
    if set(credential) != expected_keys:
        raise CaseGovernanceError(
            "credential_schema_mismatch", reference["credential_ref"]
        )
    if credential["schema_version"] != "self-media-publication-release-credential.v1":
        raise CaseGovernanceError(
            "credential_schema_mismatch", reference["credential_ref"]
        )
    if credential["approval_kind"] != review_kind:
        raise CaseGovernanceError("credential_kind_drift", review_kind)
    if (
        credential["reviewer"] != reference["reviewer"]
        or credential["reviewed_at"] != reference["reviewed_at"]
    ):
        raise CaseGovernanceError("credential_identity_drift", review_kind)
    try:
        datetime.fromisoformat(credential["reviewed_at"])
    except (TypeError, ValueError) as error:
        raise CaseGovernanceError(
            "credential_time_invalid", review_kind
        ) from error
    if credential["decision"] != "approved":
        raise CaseGovernanceError("publication_approval_pending", review_kind)
    if credential["release_scope_sha256"] != expected_scope:
        raise CaseGovernanceError("publication_approval_scope_drift", review_kind)
    if credential["authority"] != RELEASE_CREDENTIAL_AUTHORITY:
        raise CaseGovernanceError("authority_escalation", review_kind)


def _validate_release_reviews(
    document: dict[str, Any], workspace_root: Path, expected_scope: str
) -> None:
    for review_kind, review in document["release_reviews"].items():
        status = review["status"]
        if status == "not_required":
            if review_kind != "institution_final_publication":
                raise CaseGovernanceError(
                    "publication_approval_not_permitted", review_kind
                )
            continue
        if status != "approved":
            raise CaseGovernanceError("publication_approval_pending", review_kind)
        _validate_release_credential(
            review_kind,
            review["credential"],
            expected_scope,
            workspace_root,
        )


def _validate_correction_route(platform: dict[str, Any]) -> None:
    platform_id = platform["platform_id"]
    route = platform["correction_route"]
    if (
        route["source_status"] == "unknown"
        or route["source_replacement_support"] == "unknown"
    ):
        raise CaseGovernanceError(
            "platform_correction_capability_unverified", platform_id
        )
    support = route["source_replacement_support"]
    action = route["on_source_error"]
    expected_action = {
        "supported": "replace_source",
        "unsupported": "delete_and_repost",
        "conditional": "recheck_current_ui",
    }[support]
    if action != expected_action:
        raise CaseGovernanceError("platform_correction_route_mismatch", platform_id)
    if action == "delete_and_repost" and not route["preserve_metrics_before_action"]:
        raise CaseGovernanceError(
            "platform_metrics_preservation_missing", platform_id
        )


def _validate_post_upload_plan(platform: dict[str, Any]) -> None:
    plan = platform["post_upload_plan"]
    if set(plan["checks"]) != REQUIRED_POST_UPLOAD_CHECKS:
        raise CaseGovernanceError(
            "post_upload_verification_plan_incomplete", platform["platform_id"]
        )


def _validate_publication_release_core(
    document: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    _validate_schema(document, "publication_release")
    base_receipt = validate_publication(
        _publication_v1_projection(document), workspace_root
    )
    _validate_privacy_gate(document, workspace_root)
    expected_scope = publication_release_scope(document)
    if document["release_scope_sha256"] != expected_scope:
        raise CaseGovernanceError(
            "publication_release_scope_drift", document["package_id"]
        )
    _validate_release_reviews(document, workspace_root, expected_scope)
    for platform in document["platforms"]:
        if not platform["enabled"]:
            continue
        _validate_correction_route(platform)
        _validate_post_upload_plan(platform)
    return {
        **base_receipt,
        "schema_version": document["schema_version"],
        "release_scope_sha256": expected_scope,
        "privacy_gate_status": "customer_confirmed_candidate",
    }


def validate_publication_release(
    document: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    receipt = _validate_publication_release_core(document, workspace_root)
    if document["package_phase"] != "release_candidate":
        raise CaseGovernanceError(
            "publication_phase_mismatch", document["package_phase"]
        )
    if any(platform["post_upload_result"] is not None for platform in document["platforms"]):
        raise CaseGovernanceError(
            "post_upload_result_present_before_upload", document["package_id"]
        )
    return {
        **receipt,
        "package_phase": "release_candidate",
        "manual_publication_eligible": True,
        "automatic_publish": False,
    }


def validate_publication_post_upload(
    document: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    receipt = _validate_publication_release_core(document, workspace_root)
    if document["package_phase"] != "post_upload_checked":
        raise CaseGovernanceError(
            "publication_phase_mismatch", document["package_phase"]
        )
    checked_platforms = 0
    rework_platforms: list[str] = []
    for platform in document["platforms"]:
        result = platform["post_upload_result"]
        if not platform["enabled"]:
            if result is not None:
                raise CaseGovernanceError(
                    "disabled_platform_has_post_upload_result", platform["platform_id"]
                )
            continue
        if result is None:
            raise CaseGovernanceError(
                "post_upload_result_missing", platform["platform_id"]
            )
        checked_platforms += 1
        failed = {
            name for name, status in result["checks"].items() if status == "failed"
        }
        expected_correction = bool(failed)
        if result["correction_required"] != expected_correction:
            raise CaseGovernanceError(
                "post_upload_correction_flag_mismatch", platform["platform_id"]
            )
        expected_route = (
            platform["correction_route"]["on_source_error"]
            if failed
            else "none"
        )
        if result["failure_route_used"] != expected_route:
            raise CaseGovernanceError(
                "post_upload_failure_route_mismatch", platform["platform_id"]
            )
        if failed:
            rework_platforms.append(platform["platform_id"])
    return {
        **receipt,
        "package_phase": "post_upload_checked",
        "checked_platforms": checked_platforms,
        "status": "rework_required" if rework_platforms else "passed",
        "rework_platforms": sorted(rework_platforms),
        "automatic_action_performed": False,
    }


VALIDATORS = {
    "financial": validate_financial,
    "localized_subtitles": validate_localized_subtitles,
    "lifecycle": validate_lifecycle,
    "publication": validate_publication,
    "publication_release": validate_publication_release,
    "publication_post_upload": validate_publication_post_upload,
}


def validate(kind: str, document_path: Path, workspace_root: Path) -> dict[str, Any]:
    return VALIDATORS[kind](load_json(document_path), workspace_root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(VALIDATORS))
    parser.add_argument("document", type=Path)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = validate(args.kind, args.document, args.workspace_root)
    except CaseGovernanceError as error:
        print(json.dumps({"ok": False, "error_code": error.code, "message": str(error)}, ensure_ascii=False))
        return 2
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
