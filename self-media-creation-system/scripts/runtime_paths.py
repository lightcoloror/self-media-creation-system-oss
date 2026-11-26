#!/usr/bin/env python3
"""Shared runtime state routing and file-lock helpers for Mode B releases.

Allows immutable read-only code releases under ``self-media-releases/<id>`` to
share mutable operational state in an external ``self-media-state`` directory
(or ``SELF_MEDIA_RUNTIME_HOME``) while preserving repo-local ``.runtime`` and
``tests/.runtime`` compatibility for isolated unit tests.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ENV_RUNTIME_HOME = "SELF_MEDIA_RUNTIME_HOME"
ENV_ACTIVE_RELEASE = "SELF_MEDIA_ACTIVE_RELEASE"


def find_invoke_main(repo_root: Path) -> Path | None:
    resolved = repo_root.resolve()
    for base in (resolved.parent, *resolved.parents):
        candidate = base / "self-media-main-20261029" / "invoke_main.py"
        if candidate.is_file():
            return candidate.resolve()
    return None


def managed_self_argv(repo_root: Path, rel_script: str, *args: object) -> list[str]:
    """Build a Mode B front-door CLI argv when an active release is bound, else direct sys.executable."""
    rel_norm = Path(rel_script).as_posix()
    active_release = os.environ.get(ENV_ACTIVE_RELEASE, "").strip()
    if active_release:
        launcher = find_invoke_main(repo_root)
        if launcher is not None:
            return [
                sys.executable,
                str(launcher),
                "--require-release",
                active_release,
                "self",
                rel_norm,
                *(str(a) for a in args),
            ]
    return [sys.executable, str((repo_root / rel_norm).resolve()), *(str(a) for a in args)]


def _candidate_external_state(repo_root: Path) -> Path | None:
    resolved = repo_root.resolve()
    for base in (resolved.parent.parent, resolved.parent):
        candidate = base / "self-media-state"
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _running_in_release_tree(repo_root: Path) -> bool:
    parts = [part.lower() for part in repo_root.resolve().parts]
    return "self-media-releases" in parts


def runtime_root(repo_root: Path) -> Path:
    """Resolve the active mutable runtime directory without hardcoding machine paths."""
    override = os.environ.get(ENV_RUNTIME_HOME, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    external = _candidate_external_state(repo_root)
    if external is not None and (
        _running_in_release_tree(repo_root)
        or (repo_root.parent.name.lower() == "self-media-source" and not (repo_root / ".runtime").exists())
    ):
        return external
    return (repo_root / ".runtime").resolve()


def allowed_runtime_roots(repo_root: Path) -> tuple[Path, ...]:
    """Return deduplicated allowed runtime roots for boundary checks."""
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.resolve(strict=False)
        if resolved not in seen:
            seen.add(resolved)
            candidates.append(resolved)

    _add(runtime_root(repo_root))
    _add(_candidate_external_state(repo_root))
    _add(repo_root / ".runtime")
    _add(repo_root / "tests" / ".runtime")
    return tuple(candidates)


def resolve_runtime_arg(repo_root: Path, raw_path: Path, subdir: str | None = None) -> Path:
    """Resolve CLI ``--store`` or output paths, rerouting relative ``.runtime/...`` when external state is active."""
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve(strict=False)
    active = runtime_root(repo_root)
    repo_resolved = repo_root.resolve(strict=False)
    parts = path.parts
    if parts and parts[0] == ".runtime" and active != (repo_resolved / ".runtime").resolve(strict=False):
        if not (repo_resolved / path).exists():
            return (active / Path(*parts[1:])).resolve(strict=False)
    if subdir and not parts:
        return (active / subdir).resolve(strict=False)
    return (repo_resolved / path).resolve(strict=False)


@contextmanager
def file_lock(lock_path: Path, timeout_seconds: float = 10.0) -> Iterator[None]:
    """Acquire an advisory cross-process file lock for Windows/POSIX state writes."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.1, float(timeout_seconds))
    handle = lock_path.open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring lock: {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
