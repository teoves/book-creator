"""Generic adapter: for sites without a dedicated adapter.

The recipe lists the works explicitly:

    [source]
    site  = "generic"
    index = "https://example.org/author/"          # used for attribution only
    site_name    = "Example Archive (example.org)"
    license_name = "Public Domain"
    license_url  = "https://example.org/license"
    content_xpath = "//div[@id='main-text']"        # keep only this (string or list of XPaths)
    junk_xpaths  = [".//div[@id='nav']", ".//footer"]  # then strip these inside it
    credit_xpath = "//div[@class='credits']"           # provenance block (junk_xpaths applied inside)

    [[works]]
    url = "https://example.org/author/essay.html"
    title = "An Essay"
    year = "1910"
    chapters = false     # true: also include same-directory pages linked from this one
"""
from __future__ import annotations

import copy
import re
from urllib.parse import urljoin, urldefrag

from html import escape

from bs4 import BeautifulSoup

from ..model import PageRef, WorkRef
from .common import copyright_notice

NAME = "generic"

_DEFAULTS = dict(
    SITE_NAME="the source website",
    LICENSE_NAME="see the source website",
    LICENSE_URL="",
    TERMS_URL="",
    COPYRIGHT_URL="",
    JUNK_XPATHS=[".//nav", ".//header", ".//footer"],
)
SITE_NAME: str = _DEFAULTS["SITE_NAME"]
LICENSE_NAME: str = _DEFAULTS["LICENSE_NAME"]
LICENSE_URL: str = ""
TERMS_URL: str = ""
COPYRIGHT_URL: str = ""
JUNK_XPATHS: list[str] = list(_DEFAULTS["JUNK_XPATHS"])
CONTENT_XPATHS: list[str] = []
_CREDIT_XPATH: str | None = None
_CHAPTERS: set[str] = set()

# Same-directory links followed for `chapters = true`: HTML pages only.
_HTML_EXT = (".htm", ".html", ".xhtml", ".shtml", ".php", ".asp", ".aspx")


def _is_page(rest: str) -> bool:
    leaf = rest.rsplit("/", 1)[-1].lower()
    return leaf.endswith(_HTML_EXT) or "." not in leaf     # extensionless URLs are usually pages


def _configure(recipe) -> None:
    """(Re)initialise all adapter settings from this recipe. Every value is reset to its
    default first, so nothing leaks from one recipe to the next in the same process."""
    global SITE_NAME, LICENSE_NAME, LICENSE_URL, TERMS_URL, COPYRIGHT_URL, JUNK_XPATHS, CONTENT_XPATHS
    global _CREDIT_XPATH
    s = recipe["source"]
    SITE_NAME = s.get("site_name", _DEFAULTS["SITE_NAME"])
    LICENSE_NAME = s.get("license_name", _DEFAULTS["LICENSE_NAME"])
    LICENSE_URL = s.get("license_url", "")
    TERMS_URL = s.get("terms_url", LICENSE_URL)
    COPYRIGHT_URL = s.get("copyright_url", TERMS_URL)
    JUNK_XPATHS = list(s.get("junk_xpaths", _DEFAULTS["JUNK_XPATHS"]))
    content = s.get("content_xpath", [])
    CONTENT_XPATHS = [content] if isinstance(content, str) else list(content)
    _CREDIT_XPATH = s.get("credit_xpath")
    _CHAPTERS.clear()


CONTRIBUTORS: list[str] = []


def license_html(author: str, restricted: bool = False) -> str:
    lic = (f'<a href="{escape(LICENSE_URL)}">{escape(LICENSE_NAME)}</a>' if LICENSE_URL
           else escape(LICENSE_NAME))
    return (f"<p>This is a personal, non-commercial compilation of writings by {escape(author)} "
            f"taken from {escape(SITE_NAME)}. Only site navigation has been removed; every chapter "
            f"ends with the URL of the page it was taken from.</p>"
            f"<h2>Licence</h2><p>Source licence: {lic}.</p>"
            + ("<p>Some works in this compilation carry their own copyright notices (listed below); "
               "the compilation as a whole is therefore for private reading only.</p>" if restricted else ""))


def discover(fetcher, recipe) -> list[WorkRef]:
    _configure(recipe)
    refs = []
    for w in recipe.get("works", []):
        refs.append(WorkRef(url=w["url"], title=w.get("title", w["url"]), year=w.get("year")))
        if w.get("chapters"):
            _CHAPTERS.add(w["url"])
    return refs


def expand(fetcher, work: WorkRef) -> None:
    work.pages = [PageRef(url=work.url)]
    if work.url not in _CHAPTERS:
        return
    html = fetcher.get_text(work.url)
    page = fetcher.final_url(work.url)            # resolve links against where it was served from
    base = page.rsplit("/", 1)[0] + "/"
    soup = BeautifulSoup(html, "lxml")
    seen = {work.url, page}
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(page, a["href"]))[0]
        rest = url[len(base):] if url.startswith(base) else ""
        if (rest and "/" not in rest and _is_page(rest) and url not in seen
                and not rest.lower().startswith("index.")):
            seen.add(url)
            work.pages.append(PageRef(url=url, title=a.get_text(" ", strip=True) or None))


def credits_of(doc) -> tuple[str, str | None]:
    if not _CREDIT_XPATH:
        return "", None
    lines = []
    for el in doc.xpath(_CREDIT_XPATH):
        el = copy.deepcopy(el)                    # strip chrome inside the credit block too
        for xp in JUNK_XPATHS:
            for j in el.xpath(xp):
                j.drop_tree()
        lines.append(re.sub(r"\s+", " ", el.text_content()).strip())
    lines = [l for l in lines if l]
    return "\n".join(lines), copyright_notice(lines)
