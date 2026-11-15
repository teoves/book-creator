"""Adapter for the Marxists Internet Archive (www.marxists.org).

MIA author archives follow a stable convention:

* the author index (e.g. /archive/<author>/index.htm) lists works inside
  <p class="information"> blocks as  "1921: <a href=...>Title</a><br>";
* a work is either a single page, or a directory whose index.htm links to its
  chapters in the same directory;
* every work page carries a <p class="information"> block with Source,
  Translation, Transcription/Markup, Copyleft / Copyright / Public Domain notes —
  these are the credits we must preserve.
"""
from __future__ import annotations

import copy
import re
from urllib.parse import urljoin, urldefrag

from html import escape

from bs4 import BeautifulSoup, NavigableString

from ..model import PageRef, WorkRef
from .common import copyright_notice

NAME = "marxists"

LICENSE_NAME = "Creative Commons Attribution-ShareAlike 2.0 (CC BY-SA 2.0)"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/2.0/"
SITE_NAME = "Marxists Internet Archive (marxists.org)"
SITE_NAME_IN_SENTENCE = "the Marxists Internet Archive"
TERMS_URL = "https://www.marxists.org/admin/legal/terms-of-use.htm"
COPYRIGHT_URL = "https://www.marxists.org/admin/legal/corights.htm"
CONTRIBUTORS = ["Marxists Internet Archive volunteers (transcription, markup, proofreading)"]


def license_html(author: str, restricted: bool = False) -> str:
    """'About This Edition' text, reflecting MIA's Terms of Use and copyright policy:
    credit MIA, give the URL of each work, credit transcribers/proofreaders, keep
    volunteer-made material under CC BY-SA, respect works marked as copyrighted."""
    e = escape
    return "\n".join([
        f"<p>This is a personal, non-commercial compilation of writings by {e(author)} as published "
        f"online by the <a href=\"https://www.marxists.org/\">{e(SITE_NAME)}</a> (MIA). Texts are "
        f"reproduced as transcribed by MIA volunteers; only site navigation has been removed and "
        f"formatting adapted for e-readers. All original source, translation, transcription, markup "
        f"and proofreading credits are retained at the head of each work, and every chapter ends with "
        f"the URL of the page it was taken from.</p>",
        "<h2>Licence</h2>",
        f"<p>Material created by MIA volunteers (transcriptions, markup, editorial notes) is "
        f"<em>copyleft</em>, licensed under the <a href=\"{LICENSE_URL}\">{e(LICENSE_NAME)}</a> "
        f"licence. Works in the public domain remain in the public domain.</p>",
        (f"<p>This compilation also contains works marked as <strong>copyrighted</strong> (listed below): "
         f"translations published on MIA <em>with permission</em> of their translators or publishers, "
         f"which MIA cannot sublicense. The compilation as a whole is therefore for private reading only "
         f"and must not be redistributed; the CC BY-SA material in it may still be reused under that "
         f"licence, with these credits.</p>"
         if restricted else
         f"<p>This compilation is distributed under the same licence (ShareAlike): you may copy and "
         f"redistribute it provided you keep these credits and licence terms. Some translations not "
         f"explicitly marked here may still be in copyright; check before republishing.</p>"),
        f"<p>See the <a href=\"{TERMS_URL}\">MIA Terms of Use</a> and "
        f"<a href=\"{COPYRIGHT_URL}\">MIA Copyright policy</a>.</p>",
    ])

# Site chrome that should never end up in the book.
JUNK_XPATHS = [
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' toplink ')]",
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' footer ')]",
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' updat ')]",
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' title ')]",   # breadcrumb header
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' skip ')]",
    ".//p[contains(concat(' ', normalize-space(@class), ' '), ' next ')]",   # "Next: …" / "<<< Last | Next >>>"
    # the same bars in other markup (e.g. <h4><small><< Last Chapter | Next Chapter >></small></h4>);
    # the length limit keeps real paragraphs that merely mention a chapter
    ".//*[self::p or self::div or self::h3 or self::h4 or self::h5 or self::h6 or self::center]"
    "[.//a][contains(., 'Next Chapter') or contains(., 'Last Chapter') or contains(., 'Previous Chapter')]"
    "[string-length(normalize-space(.)) < 80]",
    # "Top of the page" / "Back to top" lines (e.g. <h5><a href="#top">Top of the page</a></h5>)
    ".//*[self::p or self::div or self::h3 or self::h4 or self::h5 or self::h6 or self::center]"
    "[.//a[translate(@href, 'TOP', 'top') = '#top']][string-length(normalize-space(.)) < 40]",
]

CONTENT_XPATHS: list[str] = []          # MIA pages are mostly content; chrome is stripped instead

CREDIT_XPATH = ".//p[contains(concat(' ', normalize-space(@class), ' '), ' information ')]"

_YEAR_RE = re.compile(r"(\d{4}(?:\s*[-–]\s*\d{4})?)\s*:\s*$")
_HTML_EXT = (".htm", ".html")
_INLINE = {"span", "em", "i", "b", "strong", "cite", "font", "small"}


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _preceding_text(a) -> str:
    """Text between the previous <br>/block start and this link (e.g. '1921: ')."""
    chunks = []
    # climb out of inline wrappers such as <span class="info"><a …></span>
    while a.previous_sibling is None and a.parent is not None and a.parent.name in _INLINE:
        a = a.parent
    node = a.previous_sibling
    while node is not None:
        if getattr(node, "name", None) == "br":
            break
        chunks.append(node if isinstance(node, NavigableString) else node.get_text())
        node = node.previous_sibling
    return "".join(reversed(chunks))


def discover(fetcher, recipe) -> list[WorkRef]:
    """Read the author index and return the list of works, in index order."""
    src = recipe["source"]
    index = src["index"]
    scope = src.get("scope") or index.rsplit("/", 1)[0] + "/"
    selector = src.get("link_selector", "p.information a")
    soup = BeautifulSoup(fetcher.get_text(index), "lxml")
    base_url = fetcher.final_url(index)            # resolve links against where it was served from

    # works whose page is only a list of links to pages elsewhere in the archive
    # (e.g. a collection of letters filed by date): follow those links as chapters
    contents = {urljoin(scope, c) for c in src.get("contents_pages", [])}
    works: list[WorkRef] = []
    seen: set[str] = set()
    last: WorkRef | None = None
    for a in soup.select(selector):
        href = a.get("href")
        if not href:
            continue
        url = urldefrag(urljoin(base_url, href))[0]
        if url in seen:
            continue
        seen.add(url)
        text = _clean_text(a.get_text())
        before = _clean_text(_preceding_text(a))
        m = _YEAR_RE.search(before)                               # "1921: "
        year = m.group(1).replace(" ", "") if m else None
        variant = re.search(r"\(([^()]*)$", before)                  # an unclosed "(" before the link
        if year is None and last is not None and variant:
            # "Title (<a>Alternative unabridged version</a>)" or
            # "Title (Alternate Translation: <a>Other Title</a>)" -> a variant of the previous work
            desc = variant.group(1).strip()
            year, text = last.year, f"{last.title} ({desc + ' ' if desc else ''}{text})"
        if not url.startswith(scope) and year is None:
            continue                        # credits / navigation links, not works
        ref = WorkRef(url=url, title=text, year=year, contents_page=url in contents)
        if not url.startswith(scope):
            ref.skipped_reason = "hosted outside this author archive"
        elif not url.lower().endswith(_HTML_EXT):
            ref.skipped_reason = "not an HTML page (" + url.rsplit(".", 1)[-1].upper() + ")"
        works.append(ref)
        last = ref
    return works


def expand(fetcher, work: WorkRef) -> None:
    """Fill work.pages. Directory-style works (…/index.htm) get their chapters."""
    work.pages = [PageRef(url=work.url, title=None)]
    leaf = work.url.rsplit("/", 1)[1].lower()
    if work.contents_page:
        _expand_contents(fetcher, work)
        return
    if not leaf.startswith("index."):
        return
    html = fetcher.get_text(work.url)
    page = fetcher.final_url(work.url)
    base = page.rsplit("/", 1)[0] + "/"
    soup = BeautifulSoup(html, "lxml")
    seen = {work.url, page}
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(page, a["href"]))[0]
        rest = url[len(base):] if url.startswith(base) else None
        if not rest or "/" in rest or not rest.lower().endswith(_HTML_EXT):
            continue
        if rest.lower().startswith("index.") or url in seen:
            continue
        seen.add(url)
        work.pages.append(PageRef(url=url, title=_clean_text(a.get_text()) or None))


def _expand_contents(fetcher, work: WorkRef) -> None:
    """Chapters = every HTML page in the same author archive linked from the contents page,
    in link order (not just same-directory links, unlike index.htm works)."""
    html = fetcher.get_text(work.url)
    page = fetcher.final_url(work.url)
    root = re.match(r"(https?://[^/]+/archive/[^/]+/)", page)
    root = root.group(1) if root else page.rsplit("/", 1)[0] + "/"
    soup = BeautifulSoup(html, "lxml")
    seen = {work.url, page}
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(page, a["href"]))[0]
        if (url in seen or not url.startswith(root) or not url.lower().endswith(_HTML_EXT)
                or url.rsplit("/", 1)[1].lower().startswith("index.")):
            continue
        seen.add(url)
        work.pages.append(PageRef(url=url, title=_clean_text(a.get_text()) or None))


def credits_of(doc) -> tuple[str, str | None]:
    """Return (credit text, explicit copyright notice or None) from a parsed lxml page."""
    lines: list[str] = []
    for p in doc.xpath(CREDIT_XPATH):
        p = copy.deepcopy(p)
        # keep the line structure given by <br>
        for br in p.xpath(".//br"):
            br.tail = "\n" + (br.tail or "")
        for line in p.text_content().split("\n"):
            line = _clean_text(line)
            if line:
                lines.append(line)
    return "\n".join(lines), copyright_notice(lines)
