"""Tiny Markdown → XHTML converter for editorial material (no dependencies).

Supports: #/##/### headings, paragraphs, > blockquotes, - / * / 1. lists,
*italic*, _italic_, **bold**, [text](url), and a line of --- / *** as a rule.

Output is guaranteed to be well-formed XML: links are swapped for opaque tokens
before emphasis is applied (so emphasis can never land inside an href or straddle
a link boundary), emphasis never spans existing tags, and any block that still
fails to parse falls back to escaped plain text.
"""
from __future__ import annotations

import re
import warnings
from html import escape

from lxml import etree

_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_TOK = "{}"                       # private-use characters: never in real text
_TOK_RE = re.compile("(\\d+)")


def _emphasis(s: str) -> str:
    """Apply **bold** / *italic* / _italic_ to already-escaped text. Matches never
    contain '<' or '>', so they cannot cross tags created by an earlier rule."""
    s = re.sub(r"\*\*([^<>*]+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^<>*]+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w_])_(?!\s)([^<>_]+?)(?<!\s)_(?![\w_])", r"<em>\1</em>", s)
    return s


def _inline(s: str) -> str:
    links: list[str] = []

    def stash(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        links.append(f'<a href="{escape(url, quote=True)}">{_emphasis(escape(label, quote=False))}</a>')
        return _TOK.format(len(links) - 1)

    s = _LINK.sub(stash, s)                   # raw URL captured before any escaping
    s = _emphasis(escape(s, quote=False))
    return _TOK_RE.sub(lambda m: links[int(m.group(1))], s)


def _safe(fragment: str, plain: str) -> str:
    try:
        etree.fromstring(f"<div>{fragment}</div>")
        return fragment
    except etree.XMLSyntaxError:
        warnings.warn(f"markdown formatting dropped (not well-formed): {plain[:60]!r}")
        return escape(plain, quote=False)


def _para(text: str, tag: str = "p") -> str:
    return f"<{tag}>" + _safe(_inline(text), text) + f"</{tag}>"


def to_xhtml(md: str, heading_offset: int = 0) -> str:
    out: list[str] = []
    blocks = re.split(r"\n\s*\n", md.strip().replace("\r\n", "\n"))
    for block in blocks:
        lines = [l.rstrip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue
        first = lines[0].lstrip()
        if re.fullmatch(r"(-{3,}|\*{3,})", first) and len(lines) == 1:
            out.append("<hr/>")
        elif m := re.match(r"(#{1,6})\s+(.*)", first):
            lvl = min(6, len(m.group(1)) + heading_offset)
            out.append(_para(m.group(2), f"h{lvl}"))
            if len(lines) > 1:
                out.append(_para(" ".join(l.strip() for l in lines[1:])))
        elif first.startswith(">"):
            inner = "\n".join(re.sub(r"^\s*>\s?", "", l) for l in lines)
            out.append(f"<blockquote>{to_xhtml(inner, heading_offset)}</blockquote>")
        elif re.match(r"([-*]|\d+\.)\s+", first):
            tag = "ol" if re.match(r"\d+\.", first) else "ul"
            items, cur = [], []
            for l in lines:
                if re.match(r"\s*([-*]|\d+\.)\s+", l):
                    if cur:
                        items.append(" ".join(cur))
                    cur = [re.sub(r"^\s*([-*]|\d+\.)\s+", "", l)]
                else:
                    cur.append(l.strip())
            if cur:
                items.append(" ".join(cur))
            out.append(f"<{tag}>" + "".join(_para(i, "li") for i in items) + f"</{tag}>")
        else:
            out.append(_para(" ".join(l.strip() for l in lines)))
    return "\n".join(out)
