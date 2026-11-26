#!/usr/bin/env python3
"""Local, explicit-root media catalog. Metadata only; no media mutation or publishing.

One atomic JSON catalog is authoritative. Project links are conservative protection
markers: a failed second write leaves an orphan to review, never deletion permission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ".personal-media-library.json"
LINKS = ".personal-media-links.json"
SCHEMA = ROOT / "schemas/personal-media-library.v1.schema.json"


class LibraryError(ValueError):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibraryError("metadata_unreadable", path.name) from exc


def validate(value):
    errors = list(Draft202012Validator(read(SCHEMA), format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise LibraryError("catalog_invalid", errors[0].message)
    ids = [a["asset_id"] for a in value["assets"]]
    refs = [r["reference_id"] for r in value["references"]]
    if len(ids) != len(set(ids)) or len(refs) != len(set(refs)):
        raise LibraryError("duplicate_id", "Catalog IDs must be unique")
    for item in value["assets"]:
        if not math.isfinite(item["duration_seconds"]):
            raise LibraryError("invalid_duration", item["asset_id"])
    for ref in value["references"]:
        if not all(math.isfinite(ref[k]) for k in ["in_seconds", "out_seconds"]) or ref["in_seconds"] >= ref["out_seconds"]:
            raise LibraryError("invalid_range", ref["asset_id"])


def atomic(path, value):
    if path.is_symlink():
        raise LibraryError("metadata_symlink", path.name)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def locked(root):
    lock = root / (CATALOG + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise LibraryError("catalog_busy", "Retry after writer exits; stale locks require review") from exc
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def media_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or rel.drive or ":" in relative or ".." in rel.parts or not rel.parts:
        raise LibraryError("path_escape", "Only root-relative media paths are accepted")
    candidate = root / rel
    for part in (candidate, *candidate.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise LibraryError("path_alias", "Media aliases are not accepted")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise LibraryError("path_escape", "Media must remain inside the explicit library root")
    if any(p.startswith(".personal-media") for p in rel.parts):
        raise LibraryError("metadata_as_media", "Catalog metadata cannot be an asset")
    return resolved


def load(root):
    root = Path(root).resolve(strict=True)
    if (root / CATALOG).is_symlink():
        raise LibraryError("metadata_symlink", CATALOG)
    value = read(root / CATALOG)
    validate(value)
    if value["library_root"] != str(root):
        raise LibraryError("library_root_drift", "Moved catalogs require explicit migration review")
    return root, value


def init(root, *, synthetic_only=False, confirmed=False):
    if not confirmed:
        raise LibraryError("root_confirmation_required", "Choose and confirm the private local library root")
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise LibraryError("root_unavailable", "Library root must already exist")
    if not synthetic_only and any((p / ".git").exists() for p in (root, *root.parents)):
        raise LibraryError("repository_root_prohibited", "Real catalog metadata must stay outside Git repositories")
    for p in root.parents:
        if (p / CATALOG).exists():
            raise LibraryError("nested_library", "Nested libraries are not supported")
    with locked(root):
        if (root / CATALOG).exists():
            raise LibraryError("already_initialized", "Existing catalog was not overwritten")
        value = {"schema_version": "personal-media-library.v1", "library_id": "library-" + uuid.uuid4().hex,
                 "library_root": str(root), "synthetic_only": synthetic_only, "created_at": now(),
                 "assets": [], "references": []}
        validate(value)
        atomic(root / CATALOG, value)
    return value


def asset(value, asset_id):
    for item in value["assets"]:
        if item["asset_id"] == asset_id:
            return item
    raise LibraryError("asset_unknown", asset_id)


def verify_asset(root, item):
    try:
        path = media_path(root, item["relative_path"])
        if not path.is_file():
            raise LibraryError("asset_missing", item["asset_id"])
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise LibraryError("asset_hash_drift", item["asset_id"])
    except OSError as exc:
        raise LibraryError("asset_unreadable", item["asset_id"]) from exc


def register(root, relative, metadata, *, confirmed=False):
    if not confirmed:
        raise LibraryError("registration_confirmation_required", "Explicit metadata registration is required")
    if not isinstance(metadata, dict):
        raise LibraryError("metadata_invalid", "Registration metadata must be an object")
    root, _ = load(root)
    with locked(root):
        _, value = load(root)
        if value["synthetic_only"] and metadata.get("data_classification") != "synthetic-only":
            raise LibraryError("synthetic_only", "This root accepts synthetic fixtures only")
        path = media_path(root, relative)
        if not path.is_file():
            raise LibraryError("asset_missing", "Media file does not exist")
        if any(a["relative_path"] == path.relative_to(root).as_posix() for a in value["assets"]):
            raise LibraryError("already_registered", "Use the existing stable asset ID")
        item = dict(metadata)
        item.update(asset_id="asset-" + uuid.uuid4().hex, relative_path=path.relative_to(root).as_posix(),
                    bytes=path.stat().st_size, sha256=digest(path), registered_at=now())
        value["assets"].append(item)
        validate(value)
        verify_asset(root, item)
        atomic(root / CATALOG, value)
    return item


def project_links(project):
    path = project / LINKS
    if path.is_symlink():
        raise LibraryError("project_links_invalid", "Project marker cannot be a symlink")
    if not path.exists():
        return {"schema_version": "personal-media-project-links.v1", "project_root": str(project), "references": []}
    value = read(path)
    if (set(value) != {"schema_version", "project_root", "references"}
            or value["schema_version"] != "personal-media-project-links.v1"
            or value["project_root"] != str(project) or not isinstance(value["references"], list)):
        raise LibraryError("project_links_invalid", "Project marker binding is invalid")
    for ref in value["references"]:
        if (not isinstance(ref, dict) or set(ref) != {"library_root", "library_id", "reference_id", "asset_id"}
                or not all(isinstance(v, str) and v for v in ref.values())):
            raise LibraryError("project_links_invalid", "Malformed reference marker")
    return value


def reference(root, asset_id, project, start, end, *, confirmed=False):
    if not confirmed:
        raise LibraryError("per_use_confirmation_required", "Confirm this project and time range; publication is separate")
    project = Path(project).resolve(strict=True)
    root, _ = load(root)
    if not project.is_dir() or project.is_relative_to(root) or root.is_relative_to(project):
        raise LibraryError("library_project_overlap", "Library and project workspaces must be disjoint")
    with locked(root), locked(project):
        _, value = load(root)
        item = asset(value, asset_id)
        verify_asset(root, item)
        if not item["rights"]["cross_project_reference_allowed"] or item["rights"]["status"] != "confirmed":
            raise LibraryError("rights_review_required", asset_id)
        if not all(math.isfinite(t) for t in [start, end]) or not 0 <= start < end <= item["duration_seconds"]:
            raise LibraryError("invalid_range", asset_id)
        links = project_links(project)
        ref = {"reference_id": "ref-" + uuid.uuid4().hex, "asset_id": asset_id,
               "project_root": str(project), "in_seconds": start, "out_seconds": end,
               "confirmed_at": now(), "publication_authorized": False, "external_upload_authorized": False}
        value["references"].append(ref)
        validate(value)
        # Authoritative record first. A failed marker write retains the reference
        # as an orphan requiring repair; it never releases source protection.
        atomic(root / CATALOG, value)
        links["references"].append({"library_root": str(root), "library_id": value["library_id"],
                                     "reference_id": ref["reference_id"], "asset_id": asset_id})
        atomic(project / LINKS, links)
    return ref


def inspect(root, *, tag=None, asset_id=None):
    root, value = load(root)
    selected = [asset(value, asset_id)] if asset_id else value["assets"]
    candidates, blocked = [], []
    for item in selected:
        if tag and tag not in item["tags"]:
            continue
        try:
            verify_asset(root, item)
            if item["rights"]["status"] != "confirmed" or not item["rights"]["cross_project_reference_allowed"]:
                raise LibraryError("rights_review_required", item["asset_id"])
            candidates.append(item)
        except LibraryError as exc:
            blocked.append({"asset_id": item["asset_id"], "reason": exc.code})
    return {"status": "blocked" if blocked else "passed", "candidate_only": True,
            "automatic_insert": False, "publication_authorized": False, "assets": candidates, "blocked": blocked}


def references(root):
    root, value = load(root)
    rows = []
    for ref in value["references"]:
        issue = None
        try:
            item = asset(value, ref["asset_id"])
            verify_asset(root, item)
            if ref["out_seconds"] > item["duration_seconds"]:
                raise LibraryError("invalid_range", ref["asset_id"])
            project = Path(ref["project_root"])
            links = project_links(project)
            expected = {"library_root": str(root), "library_id": value["library_id"],
                        "reference_id": ref["reference_id"], "asset_id": ref["asset_id"]}
            if not project.is_dir() or expected not in links["references"]:
                issue = "orphan_reference"
        except (LibraryError, OSError) as exc:
            issue = getattr(exc, "code", "reference_unreadable")
        rows.append(dict(ref, integrity=issue or "passed", cleanup_protected=True))
    return rows


def cleanup_guard(workspace):
    """Called by existing lifecycle plan AND apply. Never mutates a catalog."""
    workspace = Path(workspace).resolve()
    for parent in (workspace, *workspace.parents):
        if (parent / CATALOG).exists() or (parent / CATALOG).is_symlink():
            raise LibraryError("personal_media_library_protected", "Library roots and descendants are excluded from project cleanup")
    links = project_links(workspace)
    protections = []
    for link in links["references"]:
        root, value = load(link["library_root"])
        if root.is_relative_to(workspace) or workspace.is_relative_to(root) or value["library_id"] != link["library_id"]:
            raise LibraryError("library_binding_invalid", link["asset_id"])
        ref = next((r for r in value["references"] if r["reference_id"] == link["reference_id"]), None)
        if ref is None or ref["asset_id"] != link["asset_id"] or ref["project_root"] != str(workspace):
            raise LibraryError("orphan_reference", link["asset_id"])
        verify_asset(root, asset(value, ref["asset_id"]))
        protections.append({"asset_id": link["asset_id"], "reason": "cross_project_original_protected",
                            "reference_id": link["reference_id"], "outside_workspace": True})
    return protections


def cleanup_path_reason(path):
    path = Path(path).resolve()
    if path.name in {LINKS, CATALOG, CATALOG + ".lock"}:
        return "personal_media_metadata_protected"
    if any((p / CATALOG).exists() or (p / CATALOG).is_symlink() for p in path.parents):
        return "personal_media_library_protected"
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--library-root", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("init"); i.add_argument("--confirm-root", action="store_true"); i.add_argument("--synthetic-only", action="store_true")
    a = sub.add_parser("register"); a.add_argument("--path", required=True); a.add_argument("--metadata", required=True); a.add_argument("--confirm-registration", action="store_true")
    s = sub.add_parser("search"); s.add_argument("--tag")
    s = sub.add_parser("show"); s.add_argument("--asset-id", required=True)
    sub.add_parser("check"); sub.add_parser("references")
    r = sub.add_parser("reference"); r.add_argument("--asset-id", required=True); r.add_argument("--project-root", required=True); r.add_argument("--in-seconds", type=float, required=True); r.add_argument("--out-seconds", type=float, required=True); r.add_argument("--confirm-use", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.command == "init": result = init(args.library_root, synthetic_only=args.synthetic_only, confirmed=args.confirm_root)
        elif args.command == "register": result = register(args.library_root, args.path, read(Path(args.metadata)), confirmed=args.confirm_registration)
        elif args.command == "reference": result = reference(args.library_root, args.asset_id, args.project_root, args.in_seconds, args.out_seconds, confirmed=args.confirm_use)
        elif args.command == "references": result = {"references": references(args.library_root)}
        else:
            result = inspect(args.library_root, tag=getattr(args, "tag", None), asset_id=getattr(args, "asset_id", None))
            if args.command == "check":
                result["references"] = references(args.library_root)
                if any(r["integrity"] != "passed" for r in result["references"]): result["status"] = "blocked"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("status") == "blocked" else 0
    except (LibraryError, OSError) as exc:
        print(json.dumps({"status": "blocked", "code": getattr(exc, "code", "filesystem_unavailable"), "detail": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
