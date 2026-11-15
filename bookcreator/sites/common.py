"""Helpers shared by site adapters."""
from __future__ import annotations

import re

_NOTICE = re.compile(r"\bcopyright\b|©|\(c\)\s*\d{4}", re.I)
_NOT_RESTRICTIVE = re.compile(
    r"public domain|copyleft|creative commons|\bcc[ -]by"
    r"|\bno copyright|copyright[- ]free|without (a )?copyright",      # "(no copyright)", "No copyright notice"
    re.I)


def copyright_notice(lines: list[str]) -> str | None:
    """First credit line asserting a copyright (e.g. "Copyright: … © Example Press
    1984", "Translation (c) 1977 …"), ignoring lines that only declare public-domain or
    copyleft status (e.g. "Copyright: Public Domain")."""
    for line in lines:
        if _NOTICE.search(line) and not _NOT_RESTRICTIVE.search(line):
            return line
    return None
