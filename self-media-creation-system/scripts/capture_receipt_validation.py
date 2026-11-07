"""Offline validation for generic capture receipts.

This module is a standalone draft for review before it is wired into an
existing capture tool.  It contains exactly one public function,
:func:`validate_receipt`.  It deliberately does not capture anything, does not
normalise URLs, does not read files, does not import project code, does not
talk to a network and does not keep state, storage or task status.

Contract
--------
``validate_receipt(receipt, *, file_digest) -> list[str]``

``receipt``
    A plain ``dict`` describing one capture attempt.  The recognised keys are
    listed in :data:`TOP_LEVEL_FIELDS`.  ``has_screenshot`` is accepted but
    ignored, because it is a derived value (see below).

``file_digest``
    Host-injected callable ``file_digest(path) -> sha256_hex``.  For every
    artifact whose ``path`` and ``sha256`` are structurally valid, the
    validator invokes this callable and compares its return value with the
    declared ``sha256``.  The validator never opens files itself, so the host
    keeps full control over path resolution, caching and sandboxing.  A
    callable that raises is treated as an unavailable/unreadable artifact; the
    exception message is never exposed.

Return value
    An ordered, de-duplicated list of stable error strings such as
    ``"artifacts[0].sha256:mismatch"`` or ``"source_url:auth_secret"``.  An
    empty list means every check in this module passed.

Captured status is not a truth claim
------------------------------------
``status == "captured"`` is only checked for structural consistency: at least
one artifact has to pass the artifact checks (including a digest match against
the host-provided callable).  A passing result does not assert that the body is
complete, that the platform is real, or that the content is factually correct.

Derived ``has_screenshot``
--------------------------
``has_screenshot`` is not accepted as authority.  If it is present in the
input it is ignored.  The host should derive it from validated ``screenshot``
artifacts after :func:`validate_receipt` succeeds, and never copy it from an
unvalidated receipt.

Artifact binding and secret scanning
------------------------------------
Every artifact role (``text``, ``screenshot``, ``image``, ``subtitles``) is
bound to the receipt's ``capture_session_id`` and page ``source_url``; an
artifact's own ``source_url`` is the page source, never a CDN/file address, so
an artifact from another session or another page cannot count towards a
``captured`` result.

URL bearer data is scanned conservatively with one HTML-entity decode pass and
one percent-decode pass (standard-library ``html.unescape`` and
``urllib.parse.unquote``) before matching the fixed query-parameter names and
header forms.  URL userinfo (``https://user:pass@host/...``) is rejected on the
URL-typed fields without echoing credentials.  Double-encoded or recursively
encoded input is intentionally out of scope; see REPORT.md for the exact
recognition limits.

Security notes
--------------
Error strings contain only a fixed code plus a schema field path and list
index.  They never contain receipt values, URLs, hashes, token values, header
values or exception messages.  Unknown field names are sanitised before they
are echoed; if a name does not look like a plain identifier it is reported as
``unknown``.  This function never raises for malformed input (a last-resort
internal guard returns ``["receipt:internal_error"]`` instead of a traceback or
raw payload).

Error codes
-----------
``receipt:not_object`` / ``receipt:internal_error``
``file_digest:not_callable``
``unknown_field:<sanitised-name>``
``source_url:missing|type|empty|not_https|invalid_url|userinfo_forbidden|auth_secret``
``status:missing|type|empty|invalid|captured_requires_valid_artifact``
``capture_session_id:missing|type|empty|auth_secret``
``captured_at:missing|type|empty|not_iso8601|no_timezone``
``canonical_url_before:missing|type|empty|not_https|invalid_url|userinfo_forbidden|source_url_mismatch``
``canonical_url_after:missing|type|empty|not_https|invalid_url|userinfo_forbidden|source_url_mismatch``
``evidence_kind:missing|type|empty|invalid|synthetic_rights_scope_mismatch``
``rights_scope:missing|type|empty|invalid|synthetic_evidence_kind_mismatch``
``body_kind:missing|type|empty|invalid|blocked_with_success_body|text_artifact_required``
``artifacts:missing|type``
``artifacts[i]:type|unknown_field:<sanitised-name>|duplicate_reference``
``artifacts[i].role:missing|type|empty|invalid``
``artifacts[i].path:missing|type|empty|digest_failed|digest_invalid|auth_secret``
``artifacts[i].sha256:missing|type|empty|format_invalid|mismatch``
``artifacts[i].capture_session_id:missing|type|empty|mismatch``
``artifacts[i].source_url:missing|type|empty|not_https|invalid_url|userinfo_forbidden|mismatch``
``artifacts[i]:blocked_with_success_artifact``

Requires Python 3.8+ and the standard library only.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urlsplit

__all__ = ["validate_receipt"]

STATUS_VALUES = ("captured", "partial", "blocked")
EVIDENCE_KINDS = ("real", "synthetic")
RIGHTS_SCOPES = ("public_readonly", "authorized_local", "synthetic")
BODY_KINDS = ("none", "search_snippet", "metadata", "description", "body", "transcript")
ARTIFACT_ROLES = ("text", "screenshot", "image", "subtitles")

TOP_LEVEL_FIELDS = (
    "source_url",
    "status",
    "capture_session_id",
    "captured_at",
    "canonical_url_before",
    "canonical_url_after",
    "evidence_kind",
    "rights_scope",
    "body_kind",
    "artifacts",
)

# Derived value: accepted so a receipt can carry it, but never trusted.
DERIVED_INPUT_FIELDS = frozenset({"has_screenshot"})
ALLOWED_TOP_LEVEL_FIELDS = frozenset(TOP_LEVEL_FIELDS) | DERIVED_INPUT_FIELDS

ARTIFACT_FIELDS = ("role", "path", "sha256", "capture_session_id", "source_url")
ALLOWED_ARTIFACT_FIELDS = frozenset(ARTIFACT_FIELDS)

# Kinds that claim captured body text; they require a verified text artifact.
BODY_TEXT_KINDS = frozenset({"body", "transcript"})

# Roles that must be bound to the receipt's session and page source URL.
# Every artifact role is bound: a CDN/other-page file must not count as
# evidence for this capture.  receipt["source_url"] is the page source, not
# the artifact file URL.
IDENTITY_CHECKED_ROLES = frozenset(ARTIFACT_ROLES)

_MISSING = object()

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")

# Only query parameters with a non-empty value are secrets; the bare word
# "token" in prose, a path segment or a field name is not treated as a secret.
_SECRET_QUERY_NAMES = frozenset(
    {"token", "xsec_token", "access_token", "auth_token", "session", "sid"}
)
_QUERY_PAIR_RE = re.compile(r"[?&]([A-Za-z0-9_\-]+)=([^&#\s]*)")
_COOKIE_HEADER_RE = re.compile(r"(?i)\bcookie\s*:\s*[^\s;]")
_BEARER_HEADER_RE = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+")


class _ArtifactResult:
    """Small immutable-by-convention carrier for one artifact check result."""

    __slots__ = ("role", "path", "valid")

    def __init__(self, role: Optional[str], path: Optional[str], valid: bool) -> None:
        self.role = role
        self.path = path
        self.valid = valid


def validate_receipt(receipt: Any, *, file_digest: Callable[[str], str]) -> List[str]:
    """Validate one generic capture receipt without side effects.

    Parameters
    ----------
    receipt:
        Plain ``dict`` describing one capture attempt.  See the module
        docstring for the recognised fields.
    file_digest:
        Host-injected ``callable(path) -> sha256_hex`` used to verify declared
        artifact hashes.  It is called only for artifacts whose ``path`` and
        ``sha256`` are structurally valid.

    Returns
    -------
    list[str]
        Ordered, de-duplicated error codes; empty when all checks pass.  The
        function never raises for malformed input.
    """

    errors: List[str] = []
    try:
        _validate(receipt, file_digest, errors)
    except Exception:  # noqa: BLE001 - last-resort guard: never expose payloads
        return ["receipt:internal_error"]
    return _deduplicate(errors)


def _validate(receipt: Any, file_digest: Any, errors: List[str]) -> None:
    if not isinstance(receipt, dict):
        errors.append("receipt:not_object")
        return

    digest_available = callable(file_digest)
    if not digest_available:
        errors.append("file_digest:not_callable")

    for key in receipt:
        if key not in ALLOWED_TOP_LEVEL_FIELDS:
            errors.append("unknown_field:" + _safe_field_name(key))

    source_url = _check_string(_field(receipt, "source_url"), "source_url", errors)
    if source_url is not None:
        _check_https_url(source_url, "source_url", errors)

    status = _check_string(_field(receipt, "status"), "status", errors)
    if status is not None and status not in STATUS_VALUES:
        errors.append("status:invalid")
        status = None

    capture_session_id = _check_string(
        _field(receipt, "capture_session_id"), "capture_session_id", errors
    )
    _check_captured_at(_field(receipt, "captured_at"), "captured_at", errors)

    for canonical_field in ("canonical_url_before", "canonical_url_after"):
        value = _field(receipt, canonical_field)
        if value is _MISSING:
            if status == "captured":
                errors.append(canonical_field + ":missing")
            continue
        checked = _check_string(value, canonical_field, errors)
        if checked is None:
            continue
        if not _check_https_url(checked, canonical_field, errors):
            continue
        if source_url is not None and checked != source_url:
            errors.append(canonical_field + ":source_url_mismatch")

    evidence_kind = _check_string(
        _field(receipt, "evidence_kind"), "evidence_kind", errors
    )
    if evidence_kind is not None and evidence_kind not in EVIDENCE_KINDS:
        errors.append("evidence_kind:invalid")
        evidence_kind = None

    rights_scope = _check_string(
        _field(receipt, "rights_scope"), "rights_scope", errors
    )
    if rights_scope is not None and rights_scope not in RIGHTS_SCOPES:
        errors.append("rights_scope:invalid")
        rights_scope = None

    body_kind = _check_string(_field(receipt, "body_kind"), "body_kind", errors)
    if body_kind is not None and body_kind not in BODY_KINDS:
        errors.append("body_kind:invalid")
        body_kind = None

    artifact_results: List[_ArtifactResult] = []
    artifacts_value = _field(receipt, "artifacts")
    if artifacts_value is _MISSING:
        errors.append("artifacts:missing")
    elif isinstance(artifacts_value, bool) or not isinstance(artifacts_value, list):
        errors.append("artifacts:type")
    else:
        seen_paths: Dict[str, int] = {}
        for index, item in enumerate(artifacts_value):
            result = _validate_artifact(
                item,
                index,
                errors,
                receipt_session_id=capture_session_id,
                receipt_source_url=source_url,
                digest_available=digest_available,
                file_digest=file_digest,
            )
            artifact_results.append(result)
            if result.path is not None:
                normalized_path = _normalize_path(result.path)
                if normalized_path in seen_paths:
                    errors.append("artifacts[%d]:duplicate_reference" % index)
                else:
                    seen_paths[normalized_path] = index

    if evidence_kind is not None and rights_scope is not None:
        if evidence_kind == "synthetic" and rights_scope != "synthetic":
            errors.append("evidence_kind:synthetic_rights_scope_mismatch")
        elif rights_scope == "synthetic" and evidence_kind != "synthetic":
            errors.append("rights_scope:synthetic_evidence_kind_mismatch")

    if status == "blocked":
        if body_kind in BODY_TEXT_KINDS:
            errors.append("body_kind:blocked_with_success_body")
        for index, result in enumerate(artifact_results):
            if result.valid:
                errors.append("artifacts[%d]:blocked_with_success_artifact" % index)

    if status == "captured":
        if not any(result.valid for result in artifact_results):
            errors.append("status:captured_requires_valid_artifact")

    if body_kind in BODY_TEXT_KINDS:
        has_verified_text = any(
            result.valid and result.role == "text" for result in artifact_results
        )
        if not has_verified_text:
            errors.append("body_kind:text_artifact_required")

    _scan_strings(receipt, "", errors)


def _validate_artifact(
    item: Any,
    index: int,
    errors: List[str],
    *,
    receipt_session_id: Optional[str],
    receipt_source_url: Optional[str],
    digest_available: bool,
    file_digest: Any,
) -> _ArtifactResult:
    prefix = "artifacts[%d]" % index

    if not isinstance(item, dict):
        errors.append(prefix + ":type")
        return _ArtifactResult(None, None, False)

    for key in item:
        if key not in ALLOWED_ARTIFACT_FIELDS:
            errors.append(prefix + ":unknown_field:" + _safe_field_name(key))

    role = _check_string(_field(item, "role"), prefix + ".role", errors)
    if role is not None and role not in ARTIFACT_ROLES:
        errors.append(prefix + ".role:invalid")
        role = None

    path = _check_string(_field(item, "path"), prefix + ".path", errors)
    sha256_raw = _check_string(_field(item, "sha256"), prefix + ".sha256", errors)
    session_id = _check_string(
        _field(item, "capture_session_id"), prefix + ".capture_session_id", errors
    )
    artifact_source_url = _check_string(
        _field(item, "source_url"), prefix + ".source_url", errors
    )
    if artifact_source_url is not None:
        _check_https_url(artifact_source_url, prefix + ".source_url", errors)

    sha256 = None
    if sha256_raw is not None:
        stripped_sha256 = sha256_raw.strip()
        if _SHA256_RE.fullmatch(stripped_sha256):
            sha256 = stripped_sha256.lower()
        else:
            errors.append(prefix + ".sha256:format_invalid")

    identity_matches = True
    if role in IDENTITY_CHECKED_ROLES:
        if (
            session_id is not None
            and receipt_session_id is not None
            and session_id != receipt_session_id
        ):
            errors.append(prefix + ".capture_session_id:mismatch")
            identity_matches = False
        if (
            artifact_source_url is not None
            and receipt_source_url is not None
            and artifact_source_url != receipt_source_url
        ):
            errors.append(prefix + ".source_url:mismatch")
            identity_matches = False

    digest_matches = False
    if digest_available and path is not None and sha256 is not None:
        try:
            reported_digest = file_digest(path)
        except Exception:  # noqa: BLE001 - host-side failure is a validation code
            errors.append(prefix + ".path:digest_failed")
        else:
            if isinstance(reported_digest, str):
                normalized_digest = reported_digest.strip().lower()
            else:
                normalized_digest = ""
            if _SHA256_RE.fullmatch(normalized_digest):
                if normalized_digest == sha256:
                    digest_matches = True
                else:
                    errors.append(prefix + ".sha256:mismatch")
            else:
                errors.append(prefix + ".path:digest_invalid")

    valid = digest_matches and role is not None and identity_matches
    return _ArtifactResult(role, path, valid)


def _check_string(value: Any, path: str, errors: List[str]) -> Optional[str]:
    if value is _MISSING:
        errors.append(path + ":missing")
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        errors.append(path + ":type")
        return None
    if not value.strip():
        errors.append(path + ":empty")
        return None
    return value


def _check_https_url(value: str, path: str, errors: List[str]) -> bool:
    if any(character.isspace() for character in value):
        errors.append(path + ":invalid_url")
        return False
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        username = parts.username
        password = parts.password
    except ValueError:
        errors.append(path + ":invalid_url")
        return False
    if parts.scheme != "https":
        errors.append(path + ":not_https")
        return False
    if not parts.netloc or not hostname:
        errors.append(path + ":invalid_url")
        return False
    # A public canonical page URL must not carry credentials.  Report only the
    # code: the userinfo values are auth data and must never be echoed.
    if username is not None or password is not None:
        errors.append(path + ":userinfo_forbidden")
        return False
    return True


def _check_captured_at(value: Any, path: str, errors: List[str]) -> None:
    text = _check_string(value, path, errors)
    if text is None:
        return
    candidate = text.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except (TypeError, ValueError):
        errors.append(path + ":not_iso8601")
        return
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(path + ":no_timezone")


def _has_auth_secret(text: str) -> bool:
    # Bounded normalisation: one HTML-entity pass plus one percent-decode pass.
    # This is deliberately not recursive; doubly encoded input is out of scope
    # and this limit is documented in REPORT.md.
    decoded = unquote(html.unescape(text))
    for match in _QUERY_PAIR_RE.finditer(decoded):
        name = match.group(1).strip().lower()
        value = match.group(2).strip()
        if name in _SECRET_QUERY_NAMES and value:
            return True
    if _COOKIE_HEADER_RE.search(decoded):
        return True
    if _BEARER_HEADER_RE.search(decoded):
        return True
    return False


def _scan_strings(value: Any, path: str, errors: List[str]) -> None:
    if isinstance(value, str):
        if _has_auth_secret(value):
            errors.append(path + ":auth_secret")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_strings(item, _child_path(path, key), errors)
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_strings(item, "%s[%d]" % (path, index), errors)


def _child_path(parent: str, key: Any) -> str:
    if parent == "":
        if isinstance(key, str) and key in ALLOWED_TOP_LEVEL_FIELDS:
            return key
        return "unknown_field:" + _safe_field_name(key)
    return parent + "." + _safe_field_name(key)


def _safe_field_name(key: Any) -> str:
    if isinstance(key, str) and _SAFE_FIELD_NAME_RE.fullmatch(key):
        return key
    return "unknown"


def _field(mapping: Dict[Any, Any], name: str) -> Any:
    try:
        return mapping[name]
    except KeyError:
        return _MISSING


def _normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/").casefold()


def _deduplicate(errors: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for error in errors:
        if error not in seen:
            seen.add(error)
            result.append(error)
    return result
