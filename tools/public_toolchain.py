#!/usr/bin/env python3
"""Configure and inspect the existing workspace registry; never install or execute owners."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

WORKSPACE = Path(__file__).resolve().parents[1]
LOCK = Path(__file__).with_name('public_toolchain.lock.json')


class ConfigurationError(ValueError):
    pass


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ConfigurationError('Expected a JSON object')
    return value


def checkout_evidence(path: Path, expected: str | None) -> dict:
    """A local Git identity check is not an installation or runtime test."""
    result = {'checkout_present': path.is_dir(), 'expected_commit': expected,
              'actual_commit': None, 'pinned_checkout_verified': False,
              'runtime_verified': False, 'execution_authority': 'none'}
    if not path.is_dir() or not expected:
        return result
    # Do not let git search an unrelated parent repository.
    if not (path / '.git').exists():
        return result
    try:
        head = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True, timeout=10, check=False)
        status = subprocess.run(['git', '-C', str(path), 'status', '--porcelain'],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return result
    if head.returncode == 0:
        result['actual_commit'] = head.stdout.strip()
    result['pinned_checkout_verified'] = bool(
        head.returncode == status.returncode == 0 and not status.stdout.strip()
        and result['actual_commit'] == expected)
    return result


def build_registry(workspace: Path, lock: dict) -> dict:
    workspace = workspace.resolve()
    tools = {}
    main = workspace / 'self-media-creation-system'
    for tool_id, spec in lock['tools'].items():
        relative = Path(spec['directory'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ConfigurationError('Owner paths must stay inside the workspace')
        owner = (workspace / relative).resolve()
        if not owner.is_relative_to(workspace):
            raise ConfigurationError('Owner path escapes the workspace')
        discovery = owner / spec['discovery']
        if not discovery.is_file():
            discovery = workspace / 'docs/public-owner-boundaries.md'
        if not discovery.is_file():
            raise ConfigurationError('Missing public owner boundary document')
        commands = dict(spec.get('commands', {}))
        tools[tool_id] = {
            'path': str(owner), 'discovery_markdown': str(discovery),
            'preferred_interfaces': ['cli'], 'commands': commands, 'cli': commands,
            'repository': spec.get('repository'), 'pinned_commit': spec.get('commit'),
            'public_source_status': spec['source_status'],
            'availability': checkout_evidence(owner, spec.get('commit')),
            'avoid_or_boundary': [
                'Metadata and file presence never establish runtime readiness.',
                'Missing owners and unsupported consumer commands must block execution.',
                'No model, network, upload, publication, account or customer authority.',
                'No private source tree, media or author profile is supplied.'],
        }
        if tool_id == 'content-creation-system':
            # Existing shared consumers require these two aliases to agree;
            # both derive from the same configured owner, not a second router.
            tools[tool_id]['self_media_path'] = str(owner)
            tools[tool_id]['runtime_main'] = {'repositories': {'self': {'path': str(owner)}}}
    # Keep the existing editor alias bound to the one configured Studio owner.
    # This adds no owner, fallback search, installation or readiness assertion.
    if 'content-studio' in tools:
        tools['content-creation-system']['editor_path'] = tools['content-studio']['path']
    if not main.is_dir():
        raise ConfigurationError('The existing self-media framework directory is required')
    return {'schema_version': 'public-workspace-registry.v1',
            'metadata_only': True, 'execution_authority': 'none', 'tools': tools}


def initialize(workspace: Path, lock: dict) -> Path:
    target = workspace / 'tool-registry.json'
    value = build_registry(workspace, lock)
    # Exclusive creation: never replace an operator's existing registry.
    try:
        with target.open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    except FileExistsError as error:
        raise ConfigurationError('Registry already exists; inspect it without overwriting') from error
    return target


def discover(workspace: Path, tool_id: str) -> dict:
    registry = load(workspace / 'tool-registry.json')
    entry = (registry.get('tools') or {}).get(tool_id)
    if not isinstance(entry, dict):
        raise ConfigurationError('Unknown tool id')
    owner = Path(entry['path']).resolve()
    root = workspace.resolve()
    discovery = Path(entry['discovery_markdown']).resolve()
    if not owner.is_relative_to(root) or not discovery.is_relative_to(root):
        raise ConfigurationError('Configured owner or discovery escapes this workspace')
    if not discovery.is_file():
        raise ConfigurationError('Discovery document is missing')
    return {'tool_id': tool_id, 'entry': entry,
            'current_checkout': checkout_evidence(owner, entry.get('pinned_commit')),
            'discovery_sha256': hashlib.sha256(discovery.read_bytes()).hexdigest(),
            'metadata_only': True, 'commands_executed': [], 'runtime_verified': False,
            'execution_authority': 'none'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init', help='Create a local metadata registry only; no clone or install')
    inspect = sub.add_parser('discover', help='Read one owner card and current local Git identity')
    inspect.add_argument('tool_id')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            target = initialize(WORKSPACE, load(LOCK))
            result = {'registry': str(target), 'metadata_only': True,
                      'commands_executed': [], 'execution_authority': 'none'}
        else:
            result = discover(WORKSPACE, args.tool_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ConfigurationError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({'status': 'blocked', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
