from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
CANONICAL_ROOT = WORKSPACE_ROOT / "docs" / "content-creation-system" / "routing"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROUTING = load_module("self_media_canonical_routing_test", ROOT / "scripts" / "canonical_routing.py")
VALIDATOR = load_module("registered_routing_validator_test", CANONICAL_ROOT / "validate_contract_set.py")


class RoutingConvergenceTests(unittest.TestCase):
    def test_binding_loads_the_complete_registered_contract_set(self) -> None:
        first = ROUTING.load_contracts()
        second = ROUTING.load_contracts()
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(first["components"], second["components"])
        self.assertEqual(first["manifest"]["contract_set_id"], "registered-content-routing")
        self.assertEqual(first["manifest"]["contract_set_version"], "1.9.1")
        router = first["components"]["task_router"]
        quality = first["components"]["quality_gates"]
        registry = first["components"]["skill_registry"]
        self.assertIn("conditional-serious-content-translation-precheck", router["routing_order"])
        self.assertIn("conditional-story-design-card", router["routing_order"])
        self.assertIn("conditional-serious-content-translation-postcheck", router["routing_order"])
        self.assertIn("serious_content_translation_review_ref", router["output_contract"])
        order = router["routing_order"]
        scope_to_fact = [
            "task-type",
            "account-ip",
            "content-job-and-single-primary-goal",
            "primary-audience",
            "format-adapter",
            "platform-overlay",
            "conditional-research-plan-execute-and-verified-output",
            "conditional-canonical-fact-card",
            "conditional-fact-revision-lock",
        ]
        self.assertEqual([order.index(step) for step in scope_to_fact], sorted(order.index(step) for step in scope_to_fact))
        self.assertLess(order.index("visual-profile"), order.index("design-context-review"))
        self.assertEqual(router["defaults"]["route_execution_mode"], "selected-recipe-applicable-subset-only")
        self.assertEqual(router["defaults"]["unknown_applicability"], "fail-closed")
        self.assertIn("serious_content_translation_gates", quality)
        self.assertIn("story_emotion_design_gates", quality)
        self.assertTrue(any(item["id"] == "self-media-serious-content-translation-gate" for item in registry["tool_refs"]))
        self.assertTrue(any(item["id"] == "self-media-story-design-gate" for item in registry["tool_refs"]))
        self.assertEqual(
            set(first["components"]),
            {"task_router", "format_adapters", "platform_overlays", "skill_registry", "quality_gates"},
        )

    def test_legacy_same_name_component_cannot_be_mixed_into_the_set(self) -> None:
        with self.assertRaisesRegex(VALIDATOR.RoutingContractError, "mixed routing root prohibited"):
            VALIDATOR.load_contract_set(
                CANONICAL_ROOT,
                component_overrides={"task_router": ROOT / "task-router.json"},
            )

    def test_stale_component_hash_fails_closed(self) -> None:
        router = json.loads((CANONICAL_ROOT / "task-router.json").read_text(encoding="utf-8"))
        router["defaults"]["publication_boundary"] = "automatic"
        with self.assertRaisesRegex(VALIDATOR.RoutingContractError, "canonical hash drift"):
            VALIDATOR.load_contract_set(
                CANONICAL_ROOT,
                component_value_overrides={"task_router": router},
            )

    def test_missing_canonical_root_never_falls_back_to_legacy_files(self) -> None:
        missing = ROOT / ".test-runtime" / "canonical-does-not-exist"
        self.assertFalse(missing.exists())
        with self.assertRaisesRegex(ROUTING.CanonicalRoutingError, "legacy fallback is disabled"):
            ROUTING.load_contracts(canonical_root_override=missing)

    def test_manual_route_override_is_route_metadata_not_execution_authority(self) -> None:
        loaded = ROUTING.load_contracts()
        router = loaded["components"]["task_router"]
        self.assertEqual(router["defaults"]["publication_boundary"], "manual-only")
        self.assertEqual(router["output_contract"]["publication_authority"], "never")
        self.assertIn(
            "never-publish-send-execute-authority",
            router["output_contract"]["manual_route_override"],
        )
        self.assertEqual(loaded["manifest"]["boundaries"]["external_send"], "not-authorized")

    def test_operational_extensions_cannot_replace_canonical_components(self) -> None:
        binding = ROUTING.load_binding()
        self.assertTrue(binding["operational_extensions"])
        self.assertTrue(
            all(
                extension["may_replace_canonical_component"] is False
                for extension in binding["operational_extensions"]
            )
        )


if __name__ == "__main__":
    unittest.main()
