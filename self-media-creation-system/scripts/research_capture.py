"""Small adapters for existing acquisition evidence; no crawler or workflow engine.

Codex (GPT-6), 2026-11-02. WCF owns URL identity and extraction; this module
only checks the existing ledger and projects verified receipt components.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 16 * 1024 * 1024
AUTH_KEYS = {'token', 'xsec_token', 'access_token', 'auth_token', 'session', 'sid'}


def _json(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('input_too_large')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return result


def _wcf_module(name, registry):
    tool_root = Path(_json(registry)['tools']['web-content-fetcher']['path']).resolve(strict=True)
    if str(tool_root) not in sys.path:
        sys.path.insert(0, str(tool_root))
    try:
        module = importlib.import_module('web_content_fetcher.' + name)
    except ImportError:
        raise ValueError('wcf_dependency_unavailable') from None
    if not Path(module.__file__).resolve().is_relative_to(tool_root):
        raise ValueError('mixed_wcf_module_root')
    return module


def _public_identity(url, registry):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError('invalid_public_url')
    if any(k.casefold() in AUTH_KEYS and v for k, v in parse_qsl(parsed.query)):
        raise ValueError('authenticated_url_not_allowed')
    if parsed.hostname in {'mp.weixin.qq.com', 'xiaohongshu.com', 'www.xiaohongshu.com'}:
        samples = _wcf_module('platform_samples', registry)
        return samples.canonical_url(url)
    # Reuse WCF's normalizer: significant generic query parameters are retained.
    return _wcf_module('core', registry)._normalize_url_for_match(url)


def policy():
    return {
        'entrypoint': 'python scripts/self_media_agent.py research-capture',
        'guide': 'docs/research-capture-execution.md',
        'actions': ['policy', 'lookup', 'check'],
        'receipt_validator': 'installed_requires_independent_acceptance' if importlib.util.find_spec('capture_receipt_validation') else 'awaiting_delegated_implementation',
        'existing_collectors': ['web-content-fetcher', 'wechat-tools/xhs_opencli_collect.py',
                                'wechat-tools/xhs_opencli_research_collect.py', 'bili-cli'],
        'existing_consumers': ['web_content_fetcher.platform_samples', 'capture_research_candidate', 'research-output.v1'],
        'phase_order': ['search', 'selected_detail', 'archive', 'review'],
        'checkpoint': 'Persist the current platform result before another platform or detail stage.',
        'connection_timeout_seconds': 30,
        'login_persistence': 'unknown_until_same_surface_reopened_and_visibly_verified',
        'browser_recovery': 'Use current available authorized tools; unavailable instance is not model incapability.',
        'component_counts': ['candidates', 'metadata', 'descriptions', 'bodies', 'transcripts', 'images', 'screenshots', 'subtitles'],
        'default_web_reader': 'web-content-fetcher',
        'fallback': 'Jina only after WCF unavailable/unsuitable with reason; never to evade access restrictions.',
        'automatic_retry': False, 'network_performed': False, 'workflow_count': 5,
        'publication_authorized': False, 'new_collector': False,
    }


def lookup(url, *, ledger, registry, now=None, refresh=False, fixed_record=False):
    now = now or datetime.now(timezone.utc)
    identity = _public_identity(url, registry)
    hits = []
    ledger = Path(ledger)
    if ledger.exists():
        if ledger.stat().st_size > MAX_BYTES:
            raise ValueError('ledger_too_large')
        for line in ledger.read_text(encoding='utf-8-sig').splitlines():
            if line.strip():
                row = json.loads(line)
                if _public_identity(row['canonical_url'], registry) == identity:
                    hits.append(row)
    result = dict(canonical_url=identity, matches=len(hits), action='fetch_required',
                  reason='no_successful_fresh_archive', network_performed=False)
    for row in sorted(hits, key=lambda x:x.get('last_success_at', ''), reverse=True):
        try:
            captured = _time(row['last_success_at'])
            ttl_end = captured + timedelta(days=365 if fixed_record else 7)
            expires = min(_time(row['fresh_until']), ttl_end)
            archive = Path(row['archive_path']).resolve(strict=True)
            expected = row.get('extracted_sha256')
            actual = None
            for body in (archive/'preferred_markdown.md', archive/'extracted_text.md'):
                if not body.is_file() or not 0 < body.stat().st_size <= MAX_BYTES:
                    continue
                candidate = hashlib.sha256(body.read_bytes()).hexdigest()
                if expected and expected != candidate:
                    result['reason'] = 'archive_digest_mismatch'
                    continue
                actual = candidate
                break
            if actual is None:
                continue
            if row.get('status') == 'ok' and captured <= now <= expires and not refresh:
                return dict(result, action='reuse_archive', reason='fresh_body_file_verified',
                            archive_path=str(archive), body_sha256=actual,
                            quality_status=row.get('quality_status', 'unknown'),
                            scope='saved_body_only_not_fact_verification')
        except (OSError, KeyError, ValueError, TypeError):
            continue
    if refresh:
        result['reason'] = 'explicit_refresh_requested'
    return result


def check(document, *, root, registry=None):
    # Review is deliberately unavailable until the delegated validator is
    # independently accepted and installed. Never substitute model self-report.
    try:
        from capture_receipt_validation import validate_receipt
    except ImportError:
        raise ValueError('capture_validator_not_installed') from None
    if set(document) - {'receipts', 'minimum_bodies', 'minimum_images'}:
        raise ValueError('unknown_review_fields')
    rows = document.get('receipts')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('receipt_count_invalid')
    root = Path(root).resolve(strict=True)
    registry = registry or ROOT.parent/'tool-registry.json'
    checked_paths = set()
    resolved_artifacts = {}
    def file_digest(value):
        path = Path(value)
        path = path if path.is_absolute() else root/path
        if any(p.is_symlink() or getattr(p, 'is_junction', lambda:False)() for p in (path, *path.parents)):
            raise ValueError('linked_artifact')
        path = path.resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
            raise ValueError('artifact_outside_root_or_invalid')
        if path in checked_paths:
            raise ValueError('duplicate_resolved_artifact')
        checked_paths.add(path)
        resolved_artifacts[value] = path
        return hashlib.sha256(path.read_bytes()).hexdigest()
    counts = dict(candidates=0, metadata=0, descriptions=0, bodies=0, transcripts=0,
                  images=0, screenshots=0, subtitles=0, blocked=0, synthetic=0)
    errors, seen = [], set()
    for i, row in enumerate(rows):
        checked_paths.clear()
        resolved_artifacts.clear()
        found = validate_receipt(row, file_digest=file_digest)
        if found:
            errors.extend(f'receipt_{i}:{code}' for code in found)
            continue
        invalid_media = False
        for n, art in enumerate(row['artifacts']):
            if art['role'] in {'image', 'screenshot'}:
                checked = _wcf_module('completeness', registry)._local_image(
                    row['source_url'], {row['source_url']: dict(
                        asset_path=str(resolved_artifacts[art['path']]), asset_sha256=art['sha256'].lower())}, {})
                if checked['availability'] != 'available':
                    errors.append(f'receipt_{i}:artifact_{n}:image_decode_unverified')
                    invalid_media = True
        if invalid_media:
            continue
        if row['status'] == 'blocked':
            counts['blocked'] += 1
            continue
        if row['evidence_kind'] == 'synthetic':
            counts['synthetic'] += 1
            continue
        if row['status'] != 'captured':
            continue
        identity = row['source_url']
        if identity in seen:
            errors.append(f'receipt_{i}:duplicate_source')
            continue
        seen.add(identity)
        counts['candidates'] += 1
        if row['body_kind'] in {'metadata', 'description', 'body', 'transcript'}:
            field = {'metadata':'metadata', 'description':'descriptions', 'body':'bodies', 'transcript':'transcripts'}[row['body_kind']]
            counts[field] += 1
        for art in row['artifacts']:
            field = {'image':'images', 'screenshot':'screenshots', 'subtitles':'subtitles'}.get(art['role'])
            if field:
                counts[field] += 1
    for key, count in [('minimum_bodies', 'bodies'), ('minimum_images', 'images')]:
        minimum = document.get(key, 0)
        if type(minimum) is not int or minimum < 0:
            raise ValueError('invalid_minimum')
        if counts[count] < minimum:
            errors.append(key + '_not_met')
    if counts['candidates'] == 0:
        errors.append('no_real_usable_capture')
    return dict(status='evidence_files_validated' if not errors else 'needs_rework',
                counts=counts, errors=errors, network_performed=False,
                full_original_verified=False, facts_verified=False, publication_authorized=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('policy').add_argument('--output', type=Path)
    look = sub.add_parser('lookup')
    look.add_argument('--url', required=True)
    look.add_argument('--ledger', type=Path, required=True)
    look.add_argument('--registry', type=Path, required=True)
    look.add_argument('--refresh', action='store_true')
    look.add_argument('--fixed-record', action='store_true')
    look.add_argument('--output', type=Path)
    review = sub.add_parser('check')
    review.add_argument('--input', type=Path, required=True)
    review.add_argument('--artifact-root', type=Path, required=True)
    review.add_argument('--registry', type=Path)
    review.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'policy':
            result = policy()
        elif args.action == 'lookup':
            result = lookup(args.url, ledger=args.ledger, registry=args.registry,
                            refresh=args.refresh, fixed_record=args.fixed_record)
        else:
            result = check(_json(args.input), root=args.artifact_root, registry=args.registry)
        exit_code = 2 if result.get('status') == 'needs_rework' else 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        code = str(error) if type(error) is ValueError and re.fullmatch('[a-z_]+', str(error)) else 'capture_input_invalid'
        result, exit_code = dict(status='error', error_code=code, automatic_retry=False), 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(rendered)
    print(rendered, end='')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
