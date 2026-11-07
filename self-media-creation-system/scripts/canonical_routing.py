#!/usr/bin/env python3
"""Load the registered routing suite atomically for self-media consumers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BINDING_PATH = REPOSITORY_ROOT / "routing-binding.v1.json"


class CanonicalRoutingError(ValueError):
    """Raised when the canonical binding is unavailable, stale, or mixed."""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise CanonicalRoutingError(f"{path.name} must contain a JSON object")
    return value


def load_binding(path: Path = BINDING_PATH) -> dict[str, Any]:
    binding = _load_json(path)
    required = {
        "schema_version",
        "binding_id",
        "binding_version",
        "workspace_root_relative_to_repository",
        "canonical_root_relative_to_workspace",
        "canonical_contract_set_id",
        "canonical_contract_set_version",
        "load_policy",
        "fallback_policy",
        "mixed_roots_prohibited",
        "legacy_root_snapshots",
        "operational_extensions",
        "boundaries",
        "provenance",
    }
    if set(binding) != required:
        raise CanonicalRoutingError("routing binding shape is invalid")
    if binding["schema_version"] != "self-media-routing-binding.v1":
        raise CanonicalRoutingError("routing binding schema version is unsupported")
    if binding["load_policy"] != "whole-contract-set-only":
        raise CanonicalRoutingError("partial routing component loading is prohibited")
    if binding["fallback_policy"] != "fail-closed-no-legacy-fallback":
        raise CanonicalRoutingError("legacy routing fallback is prohibited")
    if binding["mixed_roots_prohibited"] is not True:
        raise CanonicalRoutingError("mixed routing roots must remain prohibited")
    if binding["boundaries"].get("publication") != "manual-only":
        raise CanonicalRoutingError("publication boundary drift")
    return binding


def canonical_root(binding: dict[str, Any], repository_root: Path = REPOSITORY_ROOT) -> Path:
    workspace_root = (repository_root / binding["workspace_root_relative_to_repository"]).resolve()
    return (workspace_root / binding["canonical_root_relative_to_workspace"]).resolve()


def load_contracts(
    repository_root: Path = REPOSITORY_ROOT,
    canonical_root_override: Path | None = None,
) -> dict[str, Any]:
    binding = load_binding(repository_root / "routing-binding.v1.json")
    root = canonical_root_override.resolve() if canonical_root_override else canonical_root(binding, repository_root)
    validator_path = root / "validate_contract_set.py"
    if not validator_path.is_file():
        raise CanonicalRoutingError("canonical routing validator is missing; legacy fallback is disabled")

    spec = importlib.util.spec_from_file_location("registered_routing_contract_set", validator_path)
    if not spec or not spec.loader:
        raise CanonicalRoutingError("canonical routing validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.load_contract_set(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise CanonicalRoutingError(str(error)) from error

    manifest = result["manifest"]
    if manifest.get("contract_set_id") != binding["canonical_contract_set_id"]:
        raise CanonicalRoutingError("canonical contract set id drift")
    if manifest.get("contract_set_version") != binding["canonical_contract_set_version"]:
        raise CanonicalRoutingError("canonical contract set version drift")
    return {"binding": binding, **result}


def main() -> int:
    try:
        result = load_contracts()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"BLOCKED: {error}")
        return 1
    print(
        f"PASS: self-media consumers are bound to registered-content-routing "
        f"{result['manifest']['contract_set_version']}; "
        "legacy same-name files are not authoritative."
    )
    print(result["manifest"]["contract_set_id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
