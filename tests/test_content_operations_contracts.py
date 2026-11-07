from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CONTENT_SYSTEM = ROOT / "docs" / "content-creation-system"
OPERATIONS = ROOT / "docs" / "content-creation-system" / "operations"
DIAGNOSTICS = ROOT / "docs" / "content-creation-system" / "diagnostics"
VALIDATOR_PATH = ROOT / "scripts" / "validate-content-operations.py"

BASE_CONTRACTS = (
    "operating-goal",
    "account",
    "topic",
    "publication-event",
    "performance-snapshot",
)
NEW_CONTRACTS = (
    "interaction-event",
    "lead-event",
    "experiment-run",
    "diagnostic-run",
    "operating-review",
    "resource-ledger-event",
    "revenue-attribution-event",
    "account-security-event",
    "account-continuity-plan",
)


def contract_root(kind: str) -> Path:
    return DIAGNOSTICS if kind == "diagnostic-run" else OPERATIONS


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def errors_for(kind: str, document: dict) -> list:
    schema = load_json(contract_root(kind) / f"{kind}.schema.json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return list(validator.iter_errors(document))


def error_paths_for(kind: str, document: dict) -> set[tuple[object, ...]]:
    return {tuple(error.absolute_path) for error in errors_for(kind, document)}


def load_semantic_validator():
    spec = importlib.util.spec_from_file_location("content_operations_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load validator: {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SEMANTIC_VALIDATOR = load_semantic_validator()


class ContentOperationsContractTests(unittest.TestCase):
    def fixture(self, name: str) -> dict:
        return load_json(contract_root(name) / "fixtures" / f"{name}.json")

    def all_fixtures(self) -> dict[str, dict]:
        return {
            kind: self.fixture(kind)
            for kind in BASE_CONTRACTS + NEW_CONTRACTS
        }

    def content_items(self) -> list[dict]:
        items = [
            load_json(path)
            for path in sorted(
                (ROOT / "docs" / "content-creation-system" / "shadow-imports").glob("*.json")
            )
        ]
        items.append(load_json(ROOT / "docs" / "content-creation-system" / "example-content-item.json"))
        return items

    def semantic_errors(self, fixtures: dict[str, dict]) -> list[str]:
        errors: list[str] = []
        SEMANTIC_VALIDATOR.validate_fixture_privacy(fixtures, errors)
        SEMANTIC_VALIDATOR.validate_cross_object_semantics(
            fixtures, self.content_items(), errors
        )
        return errors

    def test_all_fixtures_are_valid(self) -> None:
        for kind in BASE_CONTRACTS + NEW_CONTRACTS:
            with self.subTest(kind=kind):
                self.assertEqual(errors_for(kind, self.fixture(kind)), [])

    def test_all_fixtures_pass_cross_object_semantics(self) -> None:
        self.assertEqual(self.semantic_errors(self.all_fixtures()), [])

    def test_atomic_contract_set_loads_all_14_components(self) -> None:
        first = SEMANTIC_VALIDATOR.load_contract_set(CONTENT_SYSTEM)
        second = SEMANTIC_VALIDATOR.load_contract_set(CONTENT_SYSTEM)
        expected = set(BASE_CONTRACTS + NEW_CONTRACTS)
        self.assertEqual(set(first["schemas"]), expected)
        self.assertEqual(set(first["fixtures"]), expected)
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(
            first["manifest"]["boundaries"]["publication"],
            "manual-only",
        )

    def test_atomic_contract_set_rejects_hash_drift(self) -> None:
        manifest = load_json(CONTENT_SYSTEM / "operations-contract-set.v1.json")
        manifest["components"]["account"]["schema"]["canonical_json_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "account.schema: canonical hash drift"):
            SEMANTIC_VALIDATOR.load_contract_set(
                CONTENT_SYSTEM,
                manifest_value_override=manifest,
            )

    def test_atomic_contract_set_rejects_mixed_component_path(self) -> None:
        manifest = load_json(CONTENT_SYSTEM / "operations-contract-set.v1.json")
        manifest["components"]["account"]["schema"]["path"] = (
            "operations/topic.schema.json"
        )
        with self.assertRaisesRegex(ValueError, "account.schema: path is not canonical"):
            SEMANTIC_VALIDATOR.load_contract_set(
                CONTENT_SYSTEM,
                manifest_value_override=manifest,
            )

    def test_atomic_contract_set_rejects_missing_component(self) -> None:
        manifest = load_json(CONTENT_SYSTEM / "operations-contract-set.v1.json")
        manifest["components"].pop("diagnostic-run")
        with self.assertRaisesRegex(ValueError, "operations manifest schema invalid"):
            SEMANTIC_VALIDATOR.load_contract_set(
                CONTENT_SYSTEM,
                manifest_value_override=manifest,
            )

    def test_atomic_contract_set_rejects_fixture_version_drift(self) -> None:
        fixture = self.fixture("account")
        fixture["schema_version"] = "0.2"
        with self.assertRaisesRegex(ValueError, "account.fixture: schema version drift"):
            SEMANTIC_VALIDATOR.load_contract_set(
                CONTENT_SYSTEM,
                artifact_value_overrides={("account", "fixture"): fixture},
            )

    def test_semantics_reject_duplicate_signal_layer(self) -> None:
        fixtures = self.all_fixtures()
        fixtures["operating-review"]["layer_summaries"][-1]["layer"] = "admission"
        errors = self.semantic_errors(fixtures)
        self.assertTrue(any("layer_summaries.layer: duplicate admission" in item for item in errors))
        self.assertTrue(any("must contain each of six layers once" in item for item in errors))

    def test_operating_goal_rejects_automatic_authority(self) -> None:
        goal = self.fixture("operating-goal")
        goal["authority"].update(
            {
                "execution_authorized": True,
                "automatic_resource_reallocation": True,
                "automatic_goal_status_change": True,
            }
        )
        self.assertTrue(
            {
                ("authority", "execution_authorized"),
                ("authority", "automatic_resource_reallocation"),
                ("authority", "automatic_goal_status_change"),
            }.issubset(error_paths_for("operating-goal", goal))
        )

    def test_active_operating_goal_requires_human_receipt(self) -> None:
        goal = self.fixture("operating-goal")
        goal.pop("review")
        self.assertIn((), error_paths_for("operating-goal", goal))

    def test_account_and_topic_goal_refs_must_resolve(self) -> None:
        fixtures = self.all_fixtures()
        unknown_goal = "goal_01ARZ3NDEKTSV4RRFFQ69G5FBZ"
        fixtures["account"]["goal_ids"] = [unknown_goal]
        fixtures["topic"]["goal_ids"] = [unknown_goal]
        errors = self.semantic_errors(fixtures)
        self.assertTrue(any("account.goal_ids: unresolved" in item for item in errors))
        self.assertTrue(any("topic.goal_ids: unresolved" in item for item in errors))

    def test_goal_review_must_cover_each_registered_criterion(self) -> None:
        fixtures = self.all_fixtures()
        fixtures["operating-review"]["goal_reviews"][0]["criterion_results"] = []
        self.assertTrue(
            any(
                "criterion_results: must cover goal criteria exactly" in item
                for item in self.semantic_errors(fixtures)
            )
        )

    def test_goal_review_met_requires_evidence_and_all_criteria_met(self) -> None:
        fixtures = self.all_fixtures()
        goal_review = fixtures["operating-review"]["goal_reviews"][0]
        goal_review["status"] = "met"
        goal_review["evidence_refs"] = []
        errors = self.semantic_errors(fixtures)
        self.assertTrue(any("met requires every criterion met" in item for item in errors))
        self.assertTrue(any("evidence_refs: required for met" in item for item in errors))

    def test_no_signal_cannot_be_used_to_mark_goal_not_met(self) -> None:
        fixtures = self.all_fixtures()
        interaction = fixtures["interaction-event"]
        interaction.update(
            {
                "source_type": "no-signal",
                "signal_class": "no-signal",
                "disposition": "observe-only",
                "lead_promotion_status": "not-requested",
            }
        )
        goal_review = fixtures["operating-review"]["goal_reviews"][0]
        goal_review["status"] = "not-met"
        goal_review["evidence_refs"] = [interaction["interaction_event_id"]]
        criterion = goal_review["criterion_results"][0]
        criterion["status"] = "not-met"
        criterion["evidence_refs"] = [interaction["interaction_event_id"]]
        self.assertTrue(
            any(
                "no-signal or unavailable evidence cannot prove not-met" in item
                for item in self.semantic_errors(fixtures)
            )
        )

    def test_semantics_reject_diagnostic_sample_mismatch(self) -> None:
        fixtures = self.all_fixtures()
        fixtures["diagnostic-run"]["sample_size"] = 2
        self.assertTrue(
            any(
                "diagnostic-run.sample_size: must equal publication_ids count" in item
                for item in self.semantic_errors(fixtures)
            )
        )

    def test_semantics_reject_duplicate_variant_publication(self) -> None:
        fixtures = self.all_fixtures()
        publication_id = fixtures["publication-event"]["publication_id"]
        experiment = fixtures["experiment-run"]
        experiment["publication_ids"] = [publication_id]
        for variant in experiment["variants"]:
            variant["publication_ids"] = [publication_id]
        self.assertTrue(
            any(
                "experiment-run.variants.publication_ids: assigned twice" in item
                for item in self.semantic_errors(fixtures)
            )
        )

    def test_semantics_reject_continuity_recovery_order_drift(self) -> None:
        fixtures = self.all_fixtures()
        fixtures["account-continuity-plan"]["recovery_order"] = []
        self.assertTrue(
            any(
                "recovery_order: must contain every plan account exactly once" in item
                for item in self.semantic_errors(fixtures)
            )
        )

    def test_semantics_reject_sensitive_text_in_fixture(self) -> None:
        fixtures = self.all_fixtures()
        fixtures["interaction-event"]["deidentified_summary"] = (
            "synthetic-looking text accidentally contains 13800000000"
        )
        self.assertTrue(
            any("forbidden phone-number" in item for item in self.semantic_errors(fixtures))
        )

    def test_interaction_no_signal_cannot_be_promoted_to_lead(self) -> None:
        interaction = self.fixture("interaction-event")
        interaction.update(
            {
                "source_type": "no-signal",
                "signal_class": "business-candidate",
                "disposition": "lead-candidate",
                "lead_promotion_status": "promoted",
            }
        )
        self.assertTrue(
            {
                ("signal_class",),
                ("disposition",),
                ("lead_promotion_status",),
            }.issubset(error_paths_for("interaction-event", interaction))
        )

    def test_promoted_interaction_requires_auditable_evidence(self) -> None:
        interaction = self.fixture("interaction-event")
        interaction.pop("evidence_refs")
        interaction["evidence_status"] = "unknown"
        self.assertTrue(
            {
                (),
                ("evidence_status",),
            }.issubset(error_paths_for("interaction-event", interaction))
        )

    def test_lead_event_requires_human_confirmation_and_forbids_side_effects(self) -> None:
        lead = self.fixture("lead-event")
        lead["review"]["human_confirmed"] = False
        lead["authority"].update(
            {
                "execution_authorized": True,
                "crm_write_performed": True,
                "do_not_auto_contact": False,
            }
        )
        self.assertTrue(
            {
                ("review", "human_confirmed"),
                ("authority", "execution_authorized"),
                ("authority", "crm_write_performed"),
                ("authority", "do_not_auto_contact"),
            }.issubset(error_paths_for("lead-event", lead))
        )

    def test_completed_lead_handoff_requires_receipt(self) -> None:
        lead = self.fixture("lead-event")
        lead["handoff"]["status"] = "completed"
        lead["handoff"]["receipt_ref"] = None
        self.assertIn(("handoff", "receipt_ref"), error_paths_for("lead-event", lead))

    def test_observational_experiment_cannot_claim_controlled_causality(self) -> None:
        experiment = self.fixture("experiment-run")
        experiment["causal_scope"] = "controlled-eligible"
        experiment["authority"]["automatic_winner_selection"] = True
        self.assertTrue(
            {
                ("causal_scope",),
                ("authority", "automatic_winner_selection"),
            }.issubset(error_paths_for("experiment-run", experiment))
        )

    def test_running_experiment_requires_start_and_pending_neutral_conclusion(self) -> None:
        experiment = self.fixture("experiment-run")
        experiment["state"] = "running"
        experiment["started_at"] = None
        experiment["conclusion"].update(
            {
                "effect_direction": "positive",
                "data_quality": "high",
                "evidence_refs": ["synthetic:premature-result"],
            }
        )
        paths = error_paths_for("experiment-run", experiment)
        self.assertTrue(
            {
                ("started_at",),
                ("conclusion", "effect_direction"),
                ("conclusion", "data_quality"),
                ("conclusion", "evidence_refs"),
            }.issubset(paths)
        )

    def test_diagnostic_run_cannot_authorize_account_action(self) -> None:
        diagnostic = self.fixture("diagnostic-run")
        diagnostic["authority"].update(
            {
                "execution_authorized": True,
                "publication_authority": "manual",
                "automatic_account_action": True,
            }
        )
        self.assertTrue(
            {
                ("authority", "execution_authorized"),
                ("authority", "publication_authority"),
                ("authority", "automatic_account_action"),
            }.issubset(error_paths_for("diagnostic-run", diagnostic))
        )

    def test_human_reviewed_diagnostic_requires_review_receipt(self) -> None:
        diagnostic = self.fixture("diagnostic-run")
        diagnostic["report_state"] = "human-reviewed"
        self.assertIn((), error_paths_for("diagnostic-run", diagnostic))

    def test_operating_review_cannot_reallocate_resources_automatically(self) -> None:
        review = self.fixture("operating-review")
        review["revenue_summary"]["causal_claim"] = True
        review["authority"]["automatic_resource_reallocation"] = True
        self.assertTrue(
            {
                ("revenue_summary", "causal_claim"),
                ("authority", "automatic_resource_reallocation"),
            }.issubset(error_paths_for("operating-review", review))
        )

    def test_human_reviewed_operating_review_requires_review_receipt(self) -> None:
        review = self.fixture("operating-review")
        review["review_state"] = "human-reviewed"
        self.assertIn((), error_paths_for("operating-review", review))

    def test_resource_event_cannot_authorize_payment_or_include_credentials(self) -> None:
        resource = self.fixture("resource-ledger-event")
        resource["privacy"]["account_credentials_included"] = True
        resource["authority"].update(
            {"payment_authorized": True, "execution_authorized": True}
        )
        self.assertTrue(
            {
                ("privacy", "account_credentials_included"),
                ("authority", "payment_authorized"),
                ("authority", "execution_authorized"),
            }.issubset(error_paths_for("resource-ledger-event", resource))
        )

    def test_revenue_event_requires_human_evidence_and_rejects_causal_claim(self) -> None:
        revenue = self.fixture("revenue-attribution-event")
        revenue["review"]["human_confirmed"] = False
        revenue["causal_claim"] = True
        revenue["authority"]["content_metrics_used_as_proof"] = True
        self.assertTrue(
            {
                ("review", "human_confirmed"),
                ("causal_claim",),
                ("authority", "content_metrics_used_as_proof"),
            }.issubset(error_paths_for("revenue-attribution-event", revenue))
        )

    def test_revenue_event_requires_evidence_refs(self) -> None:
        revenue = self.fixture("revenue-attribution-event")
        revenue.pop("evidence_refs")
        self.assertIn((), error_paths_for("revenue-attribution-event", revenue))

    def test_security_event_rejects_secret_material_and_account_actions(self) -> None:
        security = self.fixture("account-security-event")
        security["privacy"].update(
            {
                "secrets_included": True,
                "recovery_codes_included": True,
                "totp_seed_included": True,
            }
        )
        security["authority"].update(
            {
                "execution_authorized": True,
                "credential_action_authorized": True,
                "account_action_authorized": True,
            }
        )
        self.assertTrue(
            {
                ("privacy", "secrets_included"),
                ("privacy", "recovery_codes_included"),
                ("privacy", "totp_seed_included"),
                ("authority", "execution_authorized"),
                ("authority", "credential_action_authorized"),
                ("authority", "account_action_authorized"),
            }.issubset(error_paths_for("account-security-event", security))
        )

    def test_continuity_plan_rejects_recovery_secrets_and_credential_actions(self) -> None:
        plan = self.fixture("account-continuity-plan")
        plan["privacy"].update(
            {
                "secrets_included": True,
                "recovery_codes_included": True,
                "totp_seed_included": True,
                "direct_recovery_identifiers_included": True,
            }
        )
        plan["authority"].update(
            {
                "execution_authorized": True,
                "credential_rotation_authorized": True,
                "account_action_authorized": True,
            }
        )
        self.assertTrue(
            {
                ("privacy", "secrets_included"),
                ("privacy", "recovery_codes_included"),
                ("privacy", "totp_seed_included"),
                ("privacy", "direct_recovery_identifiers_included"),
                ("authority", "execution_authorized"),
                ("authority", "credential_rotation_authorized"),
                ("authority", "account_action_authorized"),
            }.issubset(error_paths_for("account-continuity-plan", plan))
        )

    def test_account_id_rejects_personal_or_freeform_identifier(self) -> None:
        account = self.fixture("account")
        account["account_id"] = "acct_phone_13800000000"
        self.assertTrue(errors_for("account", account))

    def test_published_event_requires_frozen_version(self) -> None:
        event = self.fixture("publication-event")
        event.pop("frozen_version")
        self.assertTrue(errors_for("publication-event", event))

    def test_partial_freeze_requires_missing_reason(self) -> None:
        event = self.fixture("publication-event")
        event["frozen_version"].pop("unavailable_reason")
        self.assertTrue(errors_for("publication-event", event))

    def test_complete_freeze_requires_real_hash(self) -> None:
        event = self.fixture("publication-event")
        frozen = event["frozen_version"]
        frozen["freeze_status"] = "complete"
        frozen["body_sha256"] = None
        self.assertTrue(errors_for("publication-event", event))

    def test_missing_metric_value_requires_reason(self) -> None:
        snapshot = self.fixture("performance-snapshot")
        snapshot["metrics"][0].pop("unavailable_reason")
        self.assertTrue(errors_for("performance-snapshot", snapshot))


if __name__ == "__main__":
    unittest.main()
