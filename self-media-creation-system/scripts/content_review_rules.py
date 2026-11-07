"""Shared text checks for early diagnosis and final packaging validation.

Callers decide the stage-specific finding or failure; the text rule stays the
same so a late gate does not introduce a different definition of dependency.
"""
from __future__ import annotations

import re
import unicodedata


SERIES_DEPENDENCY_RE = re.compile(
    r"(?:"
    r"(?:接着|承接|延续)\s*(?:上|前)(?:一)?(?:期|集|篇|条)"
    r"|(?:先|请先|需要先)\s*(?:看|补)(?:完)?\s*(?:上|前)(?:一)?(?:期|集|篇|条)"
    r"|(?:没|未)(?:有)?看(?:过)?\s*(?:上|前)(?:一)?(?:期|集|篇|条)\s*(?:就|的话)?\s*(?:看不懂|无法理解|不明白)"
    r"|(?:答案|结论|具体做法|关键步骤).{0,12}(?:下|后)(?:一)?(?:期|集|篇|条).{0,8}(?:揭晓|公布|再讲|再说|告诉)"
    r"|欲知后事|未完待续"
    r"|(?:watch|read)\s+(?:episode|part)\s*\d+\s+first"
    r"|continued\s+from\s+(?:the\s+)?(?:previous|last)\s+(?:episode|part)"
    r"|(?:answer|conclusion).{0,20}(?:next|following)\s+(?:episode|part)"
    r"|to\s+be\s+continued"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def has_series_dependency(text: str) -> bool:
    """Detect explicit dependence, not a mention of a separate future topic."""
    return bool(SERIES_DEPENDENCY_RE.search(unicodedata.normalize("NFKC", text)))
