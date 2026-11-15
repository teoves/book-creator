"""Turn an arbitrary (often 1990s tag-soup) HTML page into a clean XHTML fragment
that is valid inside an EPUB 3 package.

Site-specific decisions (which elements are "chrome" to throw away) are passed
in by the site adapter; everything here is generic.
"""
from __future__ import annotations

import copy
import re
from typing import Callable
from urllib.parse import urljoin, urldefrag

import lxml.html
from lxml import etree

# Tags we keep as-is. Anything else is either renamed (RENAME) or unwrapped.
ALLOWED = {
    "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code", "dd", "del", "dfn", "div",
    "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i",
    "img", "ins", "kbd", "li", "ol", "p", "pre", "q", "s", "samp", "small", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "var",
}
RENAME = {"center": "div", "font": "span", "tt": "code", "strike": "s", "big": "span",
          "address": "p", "nobr": "span", "listing": "pre", "xmp": "pre"}
DROP_WITH_CONTENT = {"script", "style", "noscript", "iframe", "object", "embed", "form", "input",
                     "button", "select", "textarea", "map", "area", "audio", "video", "link",
                     "meta", "head", "title", "frameset", "frame", "svg", "math"}
KEEP_ATTRS = {"id", "class", "href", "src", "alt", "title", "colspan", "rowspan", "lang", "start",
              "type", "width", "height"}
# Link schemes that must never survive into a book (matched case-insensitively,
# ignoring whitespace/control characters browsers also ignore).
_BAD_SCHEMES = ("javascript:", "vbscript:", "data:")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_id(raw: str) -> str:
    """Make an XML-valid ID (NCName) deterministically from any fragment/name."""
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", raw.strip())
    if not s or not re.match(r"[A-Za-z_]", s[0]):
        s = "n_" + s
    return s


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() if el is not None else "").strip()


def parse(html: str):
    html = _CTRL.sub("", html)
    # lxml chokes on an encoding declaration inside a unicode string
    html = re.sub(r"^<\?xml[^>]*\?>", "", html.lstrip())
    return lxml.html.document_fromstring(html)


def page_title(doc) -> str | None:
    for tag in ("h1", "h2", "h3"):
        el = doc.find(f".//{tag}")
        if el is not None and _text(el):
            return _text(el)
    t = doc.find(".//title")
    return _text(t) if t is not None and _text(t) else None


def select_content(doc, xpaths: list[str]) -> bool:
    """Keep only the page's main content: replace <body> with (copies of) the elements
    matched by `xpaths`, in order, skipping any nested inside an earlier match.
    Returns False – leaving the page untouched – when nothing matches, so a site
    redesign degrades to "too much text" with a warning rather than an empty chapter."""
    found = []
    for xp in xpaths:
        for el in doc.xpath(xp):
            if not any(el is f or f in el.iterancestors() for f in found):
                found.append(el)
    if not found:
        return False
    body = doc.find(".//body")
    if body is None:
        return False
    keep = [copy.deepcopy(el) for el in found]
    for k in keep:
        k.tail = None
    body.clear()
    for k in keep:
        body.append(k)
    return True


def clean(
    doc,
    page_url: str,
    url_map: dict[str, str],
    asset_cb: Callable[[str], str | None],
    junk_xpaths: list[str],
) -> str:
    """Return the cleaned <body> content as an XHTML string.

    url_map   – absolute page URL (no fragment) -> book-internal file name, used to
                turn links between included pages into internal EPUB links.
    asset_cb  – called with an absolute image URL, returns the in-book path or None.
    """
    body = doc.find(".//body")
    if body is None:
        body = doc

    for xp in junk_xpaths:
        for el in body.xpath(xp):
            el.drop_tree()
    # trailing separators left over once the footer chrome is gone
    while len(body) and body[-1].tag in ("hr", "br") and not (body[-1].tail or "").strip():
        body.remove(body[-1])

    for el in list(body.iter()):
        if not isinstance(el.tag, str):           # comments, processing instructions
            if el.getparent() is not None:
                el.getparent().remove(el) if el.tail is None else el.drop_tree()
            continue
        tag = el.tag.lower()
        if tag in DROP_WITH_CONTENT:
            el.drop_tree()
            continue
        if tag in RENAME:
            el.tag = tag = RENAME[tag]
        elif tag != el.tag:
            el.tag = tag

    for el in list(body.iter()):
        if not isinstance(el.tag, str) or el is body:
            continue
        if el.tag not in ALLOWED:
            el.drop_tag()

    seen_ids: set[str] = set()
    for el in body.iter():
        if not isinstance(el.tag, str):
            continue
        # legacy <a name="x"> -> id
        name = el.attrib.get("name")
        if name and "id" not in el.attrib:
            el.attrib["id"] = name
        for attr in list(el.attrib):
            if attr.lower() not in KEEP_ATTRS:
                del el.attrib[attr]
        # HTML5 (EPUB 3) only allows these where noted; elsewhere they are obsolete
        # and fail epubcheck. Presentation is left to the stylesheet.
        if el.tag != "img":
            for a in ("width", "height"):
                el.attrib.pop(a, None)
        if el.tag != "ol":
            for a in ("start", "type"):
                el.attrib.pop(a, None)
        for a in ("width", "height"):
            if a in el.attrib and not re.fullmatch(r"\d+", el.attrib[a].strip()):
                del el.attrib[a]
        if "id" in el.attrib:
            new = sanitize_id(el.attrib["id"])
            if new in seen_ids:
                del el.attrib["id"]
            else:
                el.attrib["id"] = new
                seen_ids.add(new)

        if el.tag == "a" and "href" in el.attrib:
            href = el.attrib["href"].strip()
            scheme = re.sub(r"[\s\x00-\x1f]", "", href).lower()
            if scheme.startswith(_BAD_SCHEMES + ("mailto:",)):
                del el.attrib["href"]
                continue
            absu, frag = urldefrag(urljoin(page_url, href))
            frag = sanitize_id(frag) if frag else ""
            if absu == urldefrag(page_url)[0] and frag:
                el.attrib["href"] = "#" + frag
            elif absu in url_map:
                target = url_map[absu].split("/")[-1]      # all chapters live in the same dir
                el.attrib["href"] = target + ("#" + frag if frag else "")
            else:
                el.attrib["href"] = absu + ("#" + frag if frag else "")
        elif el.tag == "img":
            src = el.attrib.get("src")
            local = asset_cb(urljoin(page_url, src)) if src else None
            if local:
                el.attrib["src"] = "../" + local
                if "alt" not in el.attrib:
                    el.attrib["alt"] = ""
            else:
                el.attrib["_drop"] = "1"

    for el in body.xpath(".//img[@_drop]"):
        el.drop_tree()
    # same-page links whose target was removed with the site chrome (e.g. "#top")
    for el in body.xpath(".//a[starts-with(@href, '#')]"):
        if el.attrib["href"][1:] not in seen_ids:
            del el.attrib["href"]
    # anchors that ended up with neither href nor id are pointless wrappers
    for el in body.xpath(".//a[not(@href) and not(@id)]"):
        el.drop_tag()

    parts = []
    if body.text and body.text.strip():
        parts.append(_escape(body.text))
    for child in body:
        parts.append(etree.tostring(child, method="xml", encoding="unicode", with_tail=True))
    out = "".join(parts)
    # html-namespace-free serialisation; tidy up some leftovers
    out = out.replace("&#13;", "")
    return out


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

