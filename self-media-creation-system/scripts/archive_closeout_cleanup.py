"""Plan and apply explicitly approved, backup-bound project cleanup."""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path, PureWindowsPath

PLAN = "self-media.archive-cleanup-plan.v1"
SPEC = "self-media.archive-cleanup-spec.v1"
ARCHIVED_DUPLICATE_ROLES = {"audio", "reference", "intermediate_master", "cache"}
PROTECTED_SUFFIXES = {".py", ".ps1", ".sh", ".exe", ".dll"}


def snapshot(owner, archive, path):
    if archive.linked(path):
        raise owner.LifecycleError("dependency_link_protected", str(path))
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise owner.LifecycleError("regular_file_required", str(path))
    value = {
        "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
        "device": info.st_dev, "inode": info.st_ino, "sha256": owner._sha256(path),
    }
    current = path.lstat()
    if (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) != (
        current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size
    ) or archive.linked(path):
        raise owner.LifecycleError("cleanup_file_changed", str(path))
    return value


def inventory(archive, root):
    total = 0
    errors = []
    skipped_links = []
    for base, dirs, files in os.walk(root, followlinks=False, onerror=lambda exc: errors.append(str(exc))):
        for name in dirs[:]:
            path = Path(base) / name
            try:
                if archive.linked(path):
                    dirs.remove(name)
                    skipped_links.append(str(path))
            except OSError as exc:
                dirs.remove(name)
                errors.append(str(exc))
        for name in files:
            path = Path(base) / name
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    skipped_links.append(str(path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
            except OSError as exc:
                errors.append(str(exc))
    return {"readable_file_bytes": total, "access_errors": errors, "skipped_links": skipped_links}


def _control_path(owner, archive, value):
    path = archive.absolute(value)
    if archive.linked(path) or not path.is_file():
        raise owner.LifecycleError("cleanup_control_invalid", str(path))
    return path


def _artifact_refs(value):
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            yield value
        for child in value.values():
            yield from _artifact_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _artifact_refs(child)


def build(owner, args, spec, *, control_paths=()):
    archive = owner._archive_workflow()
    root = archive.absolute(args.workspace_root)
    if not root.is_dir() or archive.linked(root):
        raise owner.LifecycleError("cleanup_workspace_invalid", str(root))
    manifest_path = _control_path(owner, archive, args.manifest)
    receipt_path = _control_path(owner, archive, args.archive_receipt)
    confirmation = _control_path(owner, archive, args.backup_confirmation)
    binding, protected_paths = archive.cleanup_guard(owner, receipt_path, confirmation, root)
    manifest = owner._load_manifest(manifest_path)
    if manifest.get("archive_closure") and manifest["archive_closure"] != binding:
        raise owner.LifecycleError("archive_cleanup_binding_changed", str(manifest_path))
    media, _ = owner._personal_media_guard(root)
    archived = owner._read_json(receipt_path)
    assets = archived["assets"]
    current_zip = archive.absolute(archived["archive"])
    current_members = {x["sha256"] for x in assets if x["included"]}
    key = lambda p: os.path.normcase(str(p))
    archive_assets = {key(x["path"]): x for x in assets}
    controls = {key(x) for x in (*control_paths, manifest_path, receipt_path, confirmation, current_zip)}
    live = owner._artifact_index(manifest)
    registered = {key(x["path"]): x for x in live.values() if x["status"] != "purged"}
    if spec.get("schema_version") != SPEC or not isinstance(spec.get("items"), list) or not spec["items"]:
        raise owner.LifecycleError("cleanup_spec_invalid", "Expected a nonempty reviewed item list")
    recipes = spec.get("active_recipe_refs", [])
    if (not isinstance(recipes, list) or any(not isinstance(row, dict)
            or set(row) != {"path", "sha256"} for row in recipes)):
        raise owner.LifecycleError("cleanup_active_recipe_refs_invalid", "Expected bound paths and hashes")
    targets = {}
    kept = {}
    items = []

    def keep(value):
        path = archive.absolute(value)
        if not Path(value).is_absolute():
            path, _ = archive.relative_path(owner, root, value)
        if key(path) not in kept:
            kept[key(path)] = {"path": str(path), **snapshot(owner, archive, path)}
        return kept[key(path)]

    if keep(str(current_zip))["sha256"] != archived["sha256"]:
        raise owner.LifecycleError("archive_integrity_changed", str(current_zip))
    for asset in assets:
        if asset["role"] in {"final", "cover", "recipe"} and asset["included"]:
            retained = keep(asset["path"])
            if retained["sha256"] != asset["sha256"]:
                raise owner.LifecycleError("retained_asset_changed", asset["path"])
    for value in spec.get("retain", []):
        keep(value)
    for control in recipes:
        path = Path(control["path"])
        if path.is_absolute() and path.is_relative_to(root):
            path = path.relative_to(root)
        path, _ = archive.relative_path(owner, root, path)
        if keep(path)["sha256"] != control["sha256"]:
            raise owner.LifecycleError("active_cleanup_recipe_changed", str(path))
        for reference in _artifact_refs(owner._read_json(path)):
            candidate = Path(reference["path"])
            if candidate.is_absolute():
                if not candidate.is_relative_to(root):
                    continue
                candidate = candidate.relative_to(root)
            target, _ = archive.relative_path(owner, root, candidate)
            if keep(target)["sha256"] != reference["sha256"]:
                raise owner.LifecycleError("active_cleanup_reference_changed", str(target))

    for entry in spec["items"]:
        path, rel = archive.relative_path(owner, root, entry["path"])
        if any(part != part.rstrip(" .") or ":" in part or PureWindowsPath(part).is_reserved()
               for part in Path(rel).parts):
            raise owner.LifecycleError("cleanup_path_not_canonical", rel)
        kind = entry["kind"]
        reason = entry.get("reason", "").strip()
        if kind not in {"superseded", "duplicate", "obsolete_archive"} or not reason or key(path) in targets:
            raise owner.LifecycleError("cleanup_item_invalid", rel)
        if key(path) in controls or key(path) in kept or path.suffix.lower() in PROTECTED_SUFFIXES:
            raise owner.LifecycleError("cleanup_path_protected", rel)
        if archive.linked(path) or media.cleanup_path_reason(path):
            raise owner.LifecycleError("cleanup_path_protected", rel)
        item = registered.get(key(rel))
        if item and (item["status"] == "locked" or owner._active_referrers(manifest, item["artifact_id"])
                     or item["artifact_kind"] in owner.PROTECTED_KINDS - {"raw_source"}):
            raise owner.LifecycleError("cleanup_active_or_protected", rel)
        meta = snapshot(owner, archive, path)
        asset = archive_assets.get(key(rel))
        # Hash-matched archived obsolete copies may leave the workspace. Explicit
        # protected prefixes and any final or recipe are still preserved.
        archive_duplicate = (
            asset and asset["included"] and asset["role"] in ARCHIVED_DUPLICATE_ROLES
            and asset["sha256"] == meta["sha256"]
            and path.suffix.lower() in {".wav", ".mp3", ".m4a", ".mp4", ".srt", ".ass", ".vtt"}
        )
        raw_duplicate = kind == "duplicate" and asset and asset["role"] == "raw_source"
        if (archive.protected(rel, archived["protected_paths"])
                and not raw_duplicate):
            raise owner.LifecycleError("cleanup_path_protected", rel)
        if archive.protected(rel, protected_paths) and not (archive_duplicate or raw_duplicate):
            raise owner.LifecycleError("cleanup_path_protected", rel)
        if item and item["artifact_kind"] == "raw_source" and not raw_duplicate:
            raise owner.LifecycleError("cleanup_path_protected", rel)
        if path.suffix.lower() == ".zip" and kind != "obsolete_archive":
            raise owner.LifecycleError("old_archive_receipt_required", rel)
        if kind in {"superseded", "duplicate"}:
            retained = keep(entry["retained_path"])
            if kind == "duplicate" and retained["sha256"] != meta["sha256"]:
                raise owner.LifecycleError("duplicate_hash_mismatch", rel)
            if kind == "superseded" and (
                not item or item["status"] != "superseded"
                or not item["superseded_by"]
                or item["superseded_by"] not in live
                or live[item["superseded_by"]]["status"] in {"quarantine", "purged"}
                or key(root / live[item["superseded_by"]]["path"]) != key(retained["path"])
            ):
                raise owner.LifecycleError("registered_supersession_required", rel)
        else:
            old_receipt = _control_path(owner, archive, entry["old_archive_receipt"])
            keep(str(old_receipt))
            old = archive.verify_receipt(owner, old_receipt)
            if (old["project_id"] != binding["project_id"] or archive.absolute(old["workspace_root"]) != root
                    or archive.absolute(old["archive"]) != path or meta["sha256"] != old["sha256"]):
                raise owner.LifecycleError("old_archive_mismatch", rel)
            extra = {x["sha256"] for x in old["assets"] if x["included"]} - current_members
            retained_hashes = {keep(value)["sha256"] for value in entry.get("retained_members", [])}
            if extra - retained_hashes:
                raise owner.LifecycleError("old_archive_unique_members_unverified", rel)
        targets[key(path)] = rel
        items.append({"path": rel, "kind": kind, "reason": reason,
                      "artifact_id": item["artifact_id"] if item else None, **meta})
    if targets.keys() & kept.keys():
        raise owner.LifecycleError("cleanup_retained_target_overlap", "A retained file is also selected for deletion")
    return {"schema_version": PLAN, "workspace_root": str(root), "archive_closure": binding,
            "manifest_sha256": owner._json_sha256(manifest), "spec": spec, "items": items,
            "retained": list(kept.values()), "planned_bytes": sum(x["bytes"] for x in items)}


def plan(owner, args):
    archive = owner._archive_workflow()
    spec_path = _control_path(owner, archive, args.spec)
    output = archive._new(owner, args.output)
    result = build(owner, args, owner._read_json(spec_path), control_paths=(spec_path, output))
    owner._write_json_atomic(output, result)
    return {"plan": str(output), "plan_sha256": owner._json_sha256(result),
            "items": len(result["items"]), "planned_bytes": result["planned_bytes"]}


def apply(owner, args):
    archive = owner._archive_workflow()
    root = archive.absolute(args.workspace_root)
    if not root.is_dir() or archive.linked(root):
        raise owner.LifecycleError("cleanup_workspace_invalid", str(root))
    lock = root / ".archive-closeout-cleanup.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError as exc:
        raise owner.LifecycleError("cleanup_already_running", str(lock)) from exc
    try:
        return _apply(owner, args, lock)
    finally:
        lock.unlink()


def _apply(owner, args, lock):
    archive = owner._archive_workflow()
    if not args.confirm_skip_wait or not args.authorized_by.strip() or not args.reason.strip():
        raise owner.LifecycleError("cleanup_explicit_authorization_required", "Record the user's explicit wait waiver")
    plan_path = _control_path(owner, archive, args.plan)
    receipt = archive._new(owner, args.receipt)
    approved = owner._read_json(plan_path)
    if approved.get("schema_version") != PLAN or owner._json_sha256(approved) != args.expected_plan_sha256:
        raise owner.LifecycleError("cleanup_plan_hash_mismatch", str(plan_path))
    checked = build(owner, args, approved["spec"], control_paths=(plan_path, receipt, lock))
    if checked != approved:
        raise owner.LifecycleError("cleanup_plan_stale", str(plan_path))
    root = Path(checked["workspace_root"])
    manifest_path = Path(args.manifest)
    manifest = owner._load_manifest(manifest_path)
    if owner._json_sha256(manifest) != checked["manifest_sha256"]:
        raise owner.LifecycleError("cleanup_plan_stale", str(manifest_path))
    before = inventory(archive, root)
    free_before = shutil.disk_usage(root).free
    result = {
        "schema_version": "self-media.archive-cleanup-execution.v1", "status": "running",
        "started_at": owner._iso(owner._utc_now()), "plan_sha256": args.expected_plan_sha256,
        "archive_closure": checked["archive_closure"], "authorized_by": args.authorized_by,
        "reason": args.reason, "skip_wait": True, "removed": [], "failed": [],
        "directory_before": before, "disk_free_before_bytes": free_before,
    }
    owner._write_json_atomic(receipt, result)
    live = owner._artifact_index(manifest)
    recipes = approved["spec"].get("active_recipe_refs", [])
    recipe_paths = {}
    for reference in recipes:
        cand = Path(reference["path"])
        if cand.is_absolute() and cand.is_relative_to(root):
            cand = cand.relative_to(root)
        resolved_recipe, _ = archive.relative_path(owner, root, cand)
        recipe_paths[resolved_recipe] = reference["sha256"]
    # Verify full SHA-256 of all retained assets ONCE before deleting anything (avoids O(N*M) TiB re-reads),
    # then verify O(1) stat identity (dev, ino, mtime_ns, size) before each unlink, plus full SHA-256 after loop.
    retained_identities = {}
    for entry in checked["retained"]:
        rp = Path(entry["path"])
        snap = snapshot(owner, archive, rp)
        if snap["sha256"] != entry["sha256"]:
            raise owner.LifecycleError("retained_asset_changed", str(rp))
        retained_identities[rp] = (snap["device"], snap["inode"], snap["mtime_ns"], snap["bytes"])
    for item in checked["items"]:
        path = root / item["path"]
        try:
            if owner._json_sha256(owner._load_manifest(manifest_path)) != owner._json_sha256(manifest):
                raise owner.LifecycleError("cleanup_plan_stale", str(manifest_path))
            for recipe, digest in recipe_paths.items():
                if snapshot(owner, archive, recipe)["sha256"] != digest:
                    raise owner.LifecycleError("active_cleanup_recipe_changed", str(recipe))
            for retained_p, expected_id in retained_identities.items():
                info = retained_p.lstat()
                if archive.linked(retained_p) or (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) != expected_id:
                    raise owner.LifecycleError("retained_asset_changed", str(retained_p))
            actual = snapshot(owner, archive, path)
            if any(item[k] != v for k, v in actual.items()):
                raise owner.LifecycleError("cleanup_file_changed", str(path))
            path.unlink()
        except (OSError, owner.LifecycleError) as exc:
            result["failed"].append({"path": item["path"], "error": str(exc)})
            break
        result["removed"].append(item)
        owner._write_json_atomic(receipt, result)
        if item["artifact_id"]:
            record = live[item["artifact_id"]]
            now = owner._utc_now()
            record["status"] = "purged"
            record["updated_at"] = owner._iso(now)
            owner._record_history(manifest, owner._operation_id("closeout-purge"), now,
                                  "closeout_purge", [item["artifact_id"]], args.reason)
            try:
                owner._write_json_atomic(manifest_path, manifest, owner.MANIFEST_SCHEMA)
            except (OSError, owner.LifecycleError) as exc:
                result["failed"].append({"path": item["path"], "error": f"Manifest update failed: {exc}"})
                break
    for entry in checked["retained"]:
        try:
            path = Path(entry["path"])
            if snapshot(owner, archive, path)["sha256"] != entry["sha256"]:
                raise owner.LifecycleError("retained_asset_changed", str(path))
        except (OSError, owner.LifecycleError) as exc:
            result["failed"].append({"path": entry["path"], "error": str(exc)})
    free_after = shutil.disk_usage(root).free
    after = inventory(archive, root)
    result.update(
        status="passed" if not result["failed"] else "blocked",
        completed_at=owner._iso(owner._utc_now()), directory_after=after,
        disk_free_after_bytes=free_after, disk_free_delta_bytes=free_after - free_before,
        deleted_file_bytes=sum(item["bytes"] for item in result["removed"]),
        unprocessed_count=len(checked["items"]) - len(result["removed"]),
    )
    owner._write_json_atomic(receipt, result)
    return result
