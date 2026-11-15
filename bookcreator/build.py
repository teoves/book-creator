"""Recipe -> EPUB pipeline.

    discover works  ->  expand chapters  ->  fetch & clean pages
    -> front matter (title page, licence & sources)  ->  EPUB  ->  (Calibre) AZW3/MOBI/…
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import json
import re
import uuid
from html import escape
from html import unescape as _html_unescape
from pathlib import Path
from urllib.parse import urlsplit

from . import clean as C
from .cover import make_cover
from .epub import EpubBuilder, TocNode, xhtml_page
from .fetch import Fetcher
from .markdown import to_xhtml
from .model import Chapter, Work, WorkRef

# Working paths (cache/, output/, editorial dirs) are resolved against the current
# directory, so the tool works the same from a git checkout or a pip install.
def workdir() -> Path:
    return Path.cwd()

CSS = (Path(__file__).parent / "style.css").read_bytes()


def load_site(name: str):
    return importlib.import_module(f".sites.{name}", __package__)


class BuildError(RuntimeError):
    """The book cannot be built (e.g. not a single page could be fetched)."""


def _words(xhtml: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", xhtml).split())


def site_ref(site) -> str:
    """The site's name as used inside a sentence ("Compiled from …"). Adapters may set
    SITE_NAME_IN_SENTENCE (e.g. "the Marxists Internet Archive"); otherwise SITE_NAME is
    used as written, so it never gets a doubled article."""
    return getattr(site, "SITE_NAME_IN_SENTENCE", None) or site.SITE_NAME


def _matches(url: str, patterns: list[str]) -> bool:
    return any(p in url for p in patterns)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower() or "book"


class Build:
    def __init__(self, recipe: dict, recipe_path: Path, refresh: bool = False, verbose: bool = True):
        self.r = recipe
        self.path = recipe_path
        self.verbose = verbose
        self.site = load_site(recipe["source"].get("site", "generic"))
        self.fetch = Fetcher(workdir() / "cache", refresh=refresh)
        self.works: list[Work] = []
        self.skipped: list[WorkRef] = []
        self.assets: dict[str, str] = {}       # remote url -> in-book href
        self.asset_data: dict[str, bytes] = {}
        self.warnings: list[str] = []
        ed = recipe.get("editorial", {})
        self.ed_dir = (workdir() / ed["dir"]) if ed.get("dir") else None

    def log(self, *a):
        if self.verbose:
            print(*a)

    # -------------------------------------------------------------- stages
    def discover(self) -> None:
        src = self.r["source"]
        refs = self.site.discover(self.fetch, self.r)
        for extra in self.r.get("extra", []):
            refs.append(WorkRef(url=extra["url"], title=extra.get("title", extra["url"]),
                                year=extra.get("year")))
        excl = src.get("exclude", [])
        for ref in refs:
            if _matches(ref.url, excl):
                ref.skipped_reason = "excluded by recipe"
            if ref.skipped_reason:
                self.skipped.append(ref)
                continue
            try:
                self.site.expand(self.fetch, ref)
            except Exception as e:              # one unreachable work must not sink the book
                ref.skipped_reason = f"could not be fetched ({e.__class__.__name__}: {e})"
                self.skipped.append(ref)
                self.warnings.append(f"skipped {ref.url}: {ref.skipped_reason}")
                continue
            self.works.append(Work(ref=ref))
        if self.r.get("book", {}).get("order") == "chronological":
            self.works.sort(key=lambda w: (w.ref.year or "9999"))
        n_pages = sum(len(w.ref.pages) for w in self.works)
        self.log(f"Discovered {len(self.works)} works / {n_pages} pages "
                 f"({len(self.skipped)} skipped)")

    def _asset(self, url: str) -> str | None:
        if url in self.assets:
            return self.assets[url]
        if not self.r.get("book", {}).get("images", True):
            return None
        ext = Path(urlsplit(url).path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"):
            return None
        try:
            data = self.fetch.get_bytes(url)
        except Exception as e:                  # missing images shouldn't kill the build
            self.warnings.append(f"image not fetched: {url} ({e})")
            self.assets[url] = None
            return None
        href = f"images/{hashlib.sha1(url.encode()).hexdigest()[:12]}{'.jpg' if ext == '.jpeg' else ext}"
        self.assets[url] = href
        self.asset_data[href] = data
        return href

    def convert_pages(self) -> None:
        # 1. assign file names first, so links between included pages can be made internal
        url_map: dict[str, str] = {}
        for wi, w in enumerate(self.works, 1):
            for pi, p in enumerate(w.ref.pages):
                f = f"text/w{wi:03d}_{pi:02d}.xhtml"
                url_map.setdefault(p.url, f)
                w.chapters.append(Chapter(url=p.url, file=f, title=p.title or ""))
        # 2. fetch everything; a page that redirected is also known under its final URL,
        #    so links pointing at either address become internal
        pages: dict[str, tuple[str, str]] = {}          # requested url -> (final url, html)
        for w in self.works:
            for ch in w.chapters:
                try:
                    html = self.fetch.get_text(ch.url)
                except Exception as e:
                    self.warnings.append(f"page not fetched: {ch.url} ({e})")
                    continue
                final = self.fetch.final_url(ch.url)
                pages[ch.url] = (final, html)
                url_map.setdefault(final, url_map[ch.url])
        # 3. clean, resolving relative links against the URL each page was served from
        for w in self.works:
            for ch in w.chapters:
                if ch.url not in pages:
                    ch.body = (f'<p class="missing">This page could not be retrieved: '
                               f'<a href="{escape(ch.url)}">{escape(ch.url)}</a></p>')
                    continue
                final, html = pages[ch.url]
                doc = C.parse(html)
                ch.credits, ch.copyright_notice = self.site.credits_of(doc)   # before trimming
                if not ch.title:
                    ch.title = C.page_title(doc) or w.ref.title
                content = getattr(self.site, "CONTENT_XPATHS", None)
                if content and not C.select_content(doc, content):
                    self.warnings.append(f"content_xpath matched nothing on {ch.url}; kept the whole page")
                ch.body = C.clean(doc, final, url_map, self._asset, self.site.JUNK_XPATHS)
                ch.body += (f'\n<p class="source-url">Source: <a href="{escape(ch.url)}">'
                            f'{escape(ch.url)}</a> — {escape(self.site.SITE_NAME)}</p>')
            if len(w.chapters) == 1:
                w.chapters[0].title = w.label

        if self.works and not pages:
            raise BuildError(f"none of the {sum(len(w.chapters) for w in self.works)} page(s) could be "
                             f"fetched – check the URLs in the recipe (details: {self.warnings[:3]})")
        # A tiny work usually means the wrong page (an index, a "versions" or disambiguation page)
        # or a content_xpath that grabbed the wrong element.
        min_words = int(self.r.get("book", {}).get("min_work_words", 150))
        for w in self.works:
            n = sum(_words(c.body.rsplit('<p class="source-url">', 1)[0]) for c in w.chapters if c.url in pages)
            if 0 < min_words and n < min_words and any(c.url in pages for c in w.chapters):
                self.warnings.append(f"'{w.label}' has only {n} words – is {w.ref.url} the right page?")

    # ------------------------------------------------------------ editorial
    def work_slug(self, w: Work) -> str:
        """Stable file name for a work's editor's note, derived from its URL:
        …/archive/<author>/1921/some-work/index.htm -> 1921-some-work"""
        scope = self.r["source"].get("scope") or self.r["source"]["index"].rsplit("/", 1)[0] + "/"
        u = w.ref.url
        rel = u[len(scope):] if u.startswith(scope) else urlsplit(u).path.lstrip("/")
        rel = re.sub(r"\.html?$", "", rel)
        rel = re.sub(r"(^|/)index$", "", rel)
        return rel.replace("/", "-") or "index"

    def editorial(self, name: str) -> str | None:
        if not self.ed_dir:
            return None
        f = self.ed_dir / f"{name}.md"
        return f.read_text(encoding="utf-8") if f.exists() else None

    # --------------------------------------------------------- front matter
    def _title_page(self) -> str:
        b = self.r["book"]
        return (f'<div class="titlepage"><h1 class="book-title">{escape(b["title"])}</h1>'
                + (f'<p class="book-subtitle">{escape(b["subtitle"])}</p>' if b.get("subtitle") else "")
                + f'<p class="book-author">{escape(b["author"])}</p>'
                + f'<p class="book-imprint">Compiled from {escape(site_ref(self.site))}<br/>'
                + f'{_dt.date.today():%B %Y}</p></div>')

    def copyright_notices(self) -> list[tuple[Work, Chapter]]:
        """One (work, first chapter with a notice) pair per work that carries a copyright notice."""
        out = []
        for w in self.works:
            ch = next((c for c in w.chapters if c.copyright_notice), None)
            if ch:
                out.append((w, ch))
        return out

    def _license_page(self) -> str:
        s = self.site
        b = self.r["book"]
        notices = self.copyright_notices()
        out = ["<h1>About This Edition</h1>", s.license_html(b["author"], restricted=bool(notices))]
        if notices:
            out.append("<h3>Works carrying an explicit copyright notice</h3><ul>")
            for w, ch in notices:
                out.append(f'<li><a href="{ch.file.split("/")[-1]}">{escape(w.label)}</a>: '
                           f"{escape(ch.copyright_notice)}</li>")
            out.append("</ul>")
        ed = self.r.get("editorial", {})
        if self.ed_dir:
            out.append("<h2>Editorial material</h2>")
            out.append("<p>The Introduction and the editor’s notes that precede each work are new material "
                       "written for this edition. They are not part of the texts published by the archive, "
                       "and are set apart typographically. They are released under the same licence as the "
                       "compilation.</p>")
            if ed.get("attribution"):
                out.append(f"<p>{escape(ed['attribution'])}</p>")
        if self.r.get("book", {}).get("compiler"):
            out.append(f"<p>Compiled by {escape(b['compiler'])}.</p>")
        out.append(f'<p class="small">Compiled with book-creator on {_dt.date.today():%d %B %Y}. '
                   f'Source index: <a href="{escape(self.r["source"]["index"])}">'
                   f'{escape(self.r["source"]["index"])}</a></p>')
        return "\n".join(out)

    def _sources_page(self) -> str:
        out = ["<h1>Sources and Credits</h1>",
               "<p>For each work: the page(s) it was taken from and the provenance notes as given on "
               f"{escape(site_ref(self.site))}.</p>"]
        for w in self.works:
            first = w.chapters[0]
            out.append(f'<h3><a href="{first.file.split("/")[-1]}">{escape(w.label)}</a></h3>')
            credits = next((c.credits for c in w.chapters if c.credits), "")
            if credits:
                out.append('<p class="credits">' + "<br/>".join(escape(l) for l in credits.split("\n")) + "</p>")
            out.append('<p class="credits-url">' + "<br/>".join(
                f'<a href="{escape(c.url)}">{escape(c.url)}</a>' for c in w.chapters) + "</p>")
        if self.skipped:
            out.append("<h2>Listed on the archive but not included</h2><ul>")
            for ref in self.skipped:
                lab = f"{ref.year} – {ref.title}" if ref.year else ref.title
                out.append(f'<li>{escape(lab)} — {escape(ref.skipped_reason or "")}: '
                           f'<a href="{escape(ref.url)}">{escape(ref.url)}</a></li>')
            out.append("</ul>")
        return "\n".join(out)

    # ------------------------------------------------------------ assembly
    def write_epub(self, out_path: Path) -> Path:
        b = self.r["book"]
        lang = b.get("language", "en")
        ident = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, self.r["source"]["index"] + b["title"]))
        s = self.site
        ep = EpubBuilder(
            identifier=ident, title=b["title"], authors=[b["author"]], language=lang,
            description=b.get("description", ""),
            publisher=f"Compiled from {site_ref(s)}",
            rights=f"{s.LICENSE_NAME} {s.LICENSE_URL}. Individual works may carry their own "
                   f"copyright notices (see 'About This Edition').",
            source=self.r["source"]["index"], subjects=b.get("subjects", []),
            contributors=getattr(s, "CONTRIBUTORS", []),
        )
        ep.add("style.css", CSS, "text/css")

        cov = self.r.get("cover", {})
        if cov.get("enabled", True):
            portrait = None
            if cov.get("portrait"):
                try:
                    portrait = self.fetch.get_bytes(cov["portrait"])
                except Exception as e:
                    self.warnings.append(f"cover portrait not fetched: {e}")
            ep.set_cover(make_cover(b["author"], cov.get("title", b.get("short_title", b["title"])),
                                    cov.get("subtitle", b.get("subtitle", "")),
                                    cov.get("footer", f"From {site_ref(s)}"),
                                    bg=cov.get("background", "#7a1712"), portrait=portrait), lang)

        ep.add("text/title.xhtml", xhtml_page(b["title"], self._title_page(), lang, "front"), spine=True)
        ep.add("text/about.xhtml", xhtml_page("About This Edition", self._license_page(), lang, "front"), spine=True)
        ep.nav_position = len(ep.spine)     # visible Contents page right after the front matter
        ep.toc.append(TocNode("About This Edition", "text/about.xhtml"))

        ed = self.r.get("editorial", {})
        intro = self.editorial("introduction")
        if intro:
            t = ed.get("intro_title", "Introduction")
            body = f'<div class="editorial intro"><h1>{escape(t)}</h1>\n{to_xhtml(intro, heading_offset=1)}</div>'
            ep.add("text/introduction.xhtml", xhtml_page(t, body, lang, "editorial"), spine=True)
            ep.toc.append(TocNode(t, "text/introduction.xhtml"))

        missing = []
        for wi, w in enumerate(self.works, 1):
            note = self.editorial(self.work_slug(w))
            note_file = None
            if note:
                note_file = f"text/w{wi:03d}_note.xhtml"
                label = ed.get("note_label", "Editor’s note")
                body = (f'<div class="editorial note"><p class="ed-label">{escape(label)}</p>'
                        f'<h1 class="ed-title">{escape(w.label)}</h1>\n{to_xhtml(note, heading_offset=1)}</div>')
                ep.add(note_file, xhtml_page(f"{label}: {w.ref.title}", body, lang, "editorial"), spine=True)
            elif self.ed_dir:
                missing.append(self.work_slug(w))
            for ch in w.chapters:
                ep.add(ch.file, xhtml_page(ch.title, ch.body, lang), spine=True)
            node = TocNode(w.label, note_file or w.chapters[0].file)
            if len(w.chapters) > 1:
                start = 0 if note_file else 1
                node.children = [TocNode(c.title, c.file) for c in w.chapters[start:]]
            ep.toc.append(node)
        if missing:
            self.warnings.append(f"no editor's note for {len(missing)} work(s): " + ", ".join(missing))

        for href, data in self.asset_data.items():
            ep.add(href, data)
        ep.add("text/sources.xhtml", xhtml_page("Sources and Credits", self._sources_page(), lang, "back"), spine=True)
        ep.toc.append(TocNode("Sources and Credits", "text/sources.xhtml"))
        ep.write(out_path)
        return out_path

    def export_texts(self, out_dir: Path, batches: int = 0) -> dict:
        """Write one plain-text file per work (for reading/drafting editorial notes) plus
        works.json, and optionally batches.json: works split into `batches` groups of similar
        total length, each group in book order. Requires convert_pages() to have run."""
        out_dir.mkdir(parents=True, exist_ok=True)
        works = []
        for w in self.works:
            slug = self.work_slug(w)
            parts = []
            for c in w.chapters:
                body = c.body.rsplit('<p class="source-url">', 1)[0]
                body = re.sub(r"</(p|h\d|li|tr|blockquote|div)>|<br\s*/?>", "\n", body)
                parts.append(re.sub(r"\n\s*\n+", "\n\n", _html_unescape(re.sub(r"<[^>]+>", "", body))).strip())
            text = "\n\n".join(parts)
            header = (f"WORK: {w.label}\nURL: {w.ref.url}\nSLUG: {slug}\n"
                      + "".join(f"PAGE: {c.url}\n" for c in w.chapters[1:]))
            (out_dir / f"{slug}.txt").write_text(f"{header}\n{text}\n", encoding="utf-8")
            works.append({"slug": slug, "label": w.label, "words": len(text.split()), "pages": len(w.chapters)})
        (out_dir / "works.json").write_text(json.dumps(works, indent=1, ensure_ascii=False), encoding="utf-8")
        result = {"works": works}
        if batches > 0:
            groups: list[list[dict]] = [[] for _ in range(batches)]
            totals = [0] * batches
            for wk in sorted(works, key=lambda x: -x["words"]):          # greedy: largest first
                i = totals.index(min(totals))
                groups[i].append(wk)
                totals[i] += wk["words"]
            order = {wk["slug"]: i for i, wk in enumerate(works)}
            groups = [sorted(g, key=lambda x: order[x["slug"]]) for g in groups]
            (out_dir / "batches.json").write_text(
                json.dumps([{"words": t, "works": g} for t, g in zip(totals, groups)], indent=1, ensure_ascii=False),
                encoding="utf-8")
            result["batches"] = list(zip(totals, groups))
        return result

    def write_report(self, path: Path) -> None:
        rep = {
            "title": self.r["book"]["title"],
            "works": [{"label": w.label, "pages": [c.url for c in w.chapters],
                       "copyright_notice": next((c.copyright_notice for c in w.chapters if c.copyright_notice), None)}
                      for w in self.works],
            "skipped": [{"title": r.title, "url": r.url, "reason": r.skipped_reason} for r in self.skipped],
            "warnings": self.warnings,
        }
        path.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")


def run(recipe_path: Path, out_dir: Path, formats: list[str], refresh: bool = False) -> list[Path]:
    import tomllib
    from .convert import convert

    recipe = tomllib.loads(recipe_path.read_text(encoding="utf-8"))
    b = Build(recipe, recipe_path, refresh=refresh)
    b.discover()
    b.convert_pages()
    stem = recipe.get("output", {}).get("filename") or _slug(recipe["book"]["title"])
    out_dir.mkdir(parents=True, exist_ok=True)
    epub = b.write_epub(out_dir / f"{stem}.epub")
    b.write_report(out_dir / f"{stem}.report.json")
    outputs = [epub]
    print(f"EPUB written: {epub}")
    for fmt in formats:
        if fmt == "epub":
            continue
        outputs.append(convert(epub, fmt, recipe))
        print(f"{fmt.upper()} written: {outputs[-1]}")
    for w in b.warnings:
        print("WARNING:", w)
    return outputs


def export(recipe_path: Path, out_dir: Path, batches: int = 0, refresh: bool = False) -> dict:
    """Plain-text export of every work in a recipe (see Build.export_texts)."""
    import tomllib

    recipe = tomllib.loads(recipe_path.read_text(encoding="utf-8"))
    b = Build(recipe, recipe_path, refresh=refresh, verbose=False)
    b.discover()
    b.convert_pages()
    return b.export_texts(out_dir, batches)
