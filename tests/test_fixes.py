"""Regression tests for bugs found in code review (one section per bug)."""
from __future__ import annotations

import types
import warnings

import pytest
from lxml import etree

from bookcreator import clean as C
from bookcreator.fetch import Fetcher, decode_html
from bookcreator.markdown import to_xhtml
from bookcreator.model import WorkRef


def wellformed(fragment: str) -> None:
    etree.fromstring(f"<div>{fragment}</div>")


# ---------------------------------------------------------------- fake HTTP
class FakeResponse:
    def __init__(self, url, status=200, body=b"", headers=None):
        self.url, self.status_code, self.content = url, status, body
        self.text = body.decode("utf-8", "replace")
        self.headers = headers or {}
        self.ok = status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    """routes: url -> list of responses (consumed in order; last one repeats)."""
    def __init__(self, routes):
        self.routes, self.headers, self.calls = routes, {}, []

    def get(self, url, timeout=None):
        self.calls.append(url)
        rs = self.routes.get(url) or [FakeResponse(url, 404)]
        return rs.pop(0) if len(rs) > 1 else rs[0]


def fetcher(tmp_path, routes, robots=b"User-agent: *\nDisallow:\n"):
    routes.setdefault("https://e.org/robots.txt", [FakeResponse("https://e.org/robots.txt", 200, robots)])
    return Fetcher(tmp_path / "cache", delay=0, verbose=False, session=FakeSession(routes))


# -------------------------------------------- 1–2. Markdown well-formedness
@pytest.mark.parametrize("md", [
    "See [x](https://x.org/a/_b_/c).",          # underscores inside a URL
    "*a [b* c](https://x.org)",                 # emphasis straddling a link
    "**a *b** c*",                              # overlapping bold/italic
    "*italic [link](u) inside*",
])
def test_markdown_always_wellformed(md):
    wellformed(to_xhtml(md))


def test_markdown_url_not_double_escaped():
    assert 'href="https://x.org/?a=1&amp;b=2"' in to_xhtml("[d](https://x.org/?a=1&b=2)")


def test_markdown_url_keeps_underscores():
    assert 'href="https://x.org/a/_b_/c"' in to_xhtml("[x](https://x.org/a/_b_/c)")


def test_markdown_emphasis_still_works():
    out = to_xhtml("*italic [link](u) inside* and **bold**, snake_case_word")
    assert "<em>italic <a href=\"u\">link</a> inside</em>" in out
    assert "<strong>bold</strong>" in out and "snake_case_word" in out


# ---------------------------------------- 3–5. generic adapter
def test_generic_settings_do_not_leak_between_recipes():
    import bookcreator.sites.generic as g
    g.discover(None, {"source": {"index": "x", "site_name": "Site A", "junk_xpaths": ["//x"]},
                      "works": [{"url": "u1", "chapters": True}]})
    g.discover(None, {"source": {"index": "y"}, "works": []})
    assert g.SITE_NAME == "the source website"
    assert g.JUNK_XPATHS == [".//nav", ".//header", ".//footer"]
    assert g._CHAPTERS == set()


def test_generic_chapters_are_html_pages_only(tmp_path):
    import bookcreator.sites.generic as g
    toc = "https://e.org/a/toc.html"
    body = b'<a href="ch1.html">1</a><a href="ch2">2</a><a href="scan.pdf">p</a><a href="pic.jpg">i</a>'
    f = fetcher(tmp_path, {toc: [FakeResponse(toc, 200, body)]})
    g.discover(None, {"source": {"index": "x"}, "works": [{"url": toc, "chapters": True}]})
    w = WorkRef(url=toc, title="t")
    g.expand(f, w)
    assert [p.url.rsplit("/", 1)[1] for p in w.pages] == ["toc.html", "ch1.html", "ch2"]


def test_site_name_in_sentences_has_no_doubled_article():
    from bookcreator.build import site_ref
    import bookcreator.sites.generic as g
    import bookcreator.sites.marxists as m
    g.discover(None, {"source": {"index": "x"}, "works": []})
    assert f"Compiled from {site_ref(g)}" == "Compiled from the source website"
    assert f"Compiled from {site_ref(m)}" == "Compiled from the Marxists Internet Archive"


# ------------------------------------------------- 6. cache path collision
def test_cache_paths_for_file_and_directory_do_not_collide(tmp_path):
    a, b = "https://e.org/books/x", "https://e.org/books/x/ch1"
    f = fetcher(tmp_path, {a: [FakeResponse(a, 200, b"A")], b: [FakeResponse(b, 200, b"B")]})
    assert f.get_bytes(a) == b"A" and f.get_bytes(b) == b"B"
    f.session.routes.clear()                     # served from cache now
    assert f.get_bytes(a) == b"A" and f.get_bytes(b) == b"B"


def test_legacy_cache_entries_are_migrated(tmp_path):
    f = fetcher(tmp_path, {})
    legacy = tmp_path / "cache" / "e.org" / "p.htm"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"old")
    assert f.get_bytes("https://e.org/p.htm") == b"old"
    assert not legacy.exists() and (legacy.parent / "p.htm.cache").exists()


# --------------------------------------------------- 7. dangerous schemes
@pytest.mark.parametrize("href", ["JavaScript:alert(1)", " java\tscript:x", "VBScript:x", "data:text/html,x"])
def test_dangerous_link_schemes_removed(href):
    doc = C.parse(f'<body><p><a href="{href}">x</a></p></body>')
    out = C.clean(doc, "https://e.org/a.htm", {}, lambda u: None, [])
    assert "href" not in out


# ----------------------------------------------------------- redirects
def test_redirect_recorded_and_used_for_link_resolution(tmp_path):
    src, final = "https://e.org/old/work.htm", "https://e.org/new/work.htm"
    f = fetcher(tmp_path, {src: [FakeResponse(final, 200, b"<a href='ch2.htm'>x</a>")]})
    f.get_bytes(src)
    assert f.final_url(src) == final
    f2 = Fetcher(tmp_path / "cache", verbose=False, session=FakeSession({}))
    assert f2.final_url(src) == final            # remembered across runs via the cache


# ------------------------------------------------------------- encoding
def test_declared_koi8r_is_honoured():
    html = '<meta charset="koi8-r"><p>Любовь</p>'.encode("koi8-r")
    assert "Любовь" in decode_html(html)


def test_utf8_wins_over_wrong_latin1_declaration():
    html = '<meta charset="iso-8859-1"><p>Любовь и мораль – “love”</p>'.encode("utf-8")
    assert "Любовь и мораль – “love”" in decode_html(html)


def test_undeclared_cp1252_fallback():
    assert "“quoted”" in decode_html("<p>“quoted”</p>".encode("cp1252"))


# ------------------------------------------------------ retries & robots
def test_retries_503_and_honours_retry_after(tmp_path):
    u = "https://e.org/p.htm"
    f = fetcher(tmp_path, {u: [FakeResponse(u, 503, headers={"Retry-After": "0"}), FakeResponse(u, 200, b"ok")]})
    assert f.get_bytes(u) == b"ok"
    assert f.session.calls.count(u) == 2


def test_unreachable_robots_txt_means_disallow(tmp_path):
    u = "https://e.org/p.htm"
    f = fetcher(tmp_path, {u: [FakeResponse(u, 200, b"x")],
                           "https://e.org/robots.txt": [FakeResponse("https://e.org/robots.txt", 503)]})
    with pytest.raises(PermissionError):
        f.get_bytes(u)


def test_missing_robots_txt_means_allow(tmp_path):
    u = "https://e.org/p.htm"
    f = fetcher(tmp_path, {u: [FakeResponse(u, 200, b"x")],
                           "https://e.org/robots.txt": [FakeResponse("https://e.org/robots.txt", 404)]})
    assert f.get_bytes(u) == b"x"


# ------------------------------------------------------ cleaner / HTML5
def test_obsolete_presentational_attributes_removed():
    doc = C.parse('<body><table width="80%" height="3"><tr><td width="20">a</td></tr></table>'
                  '<ul type="disc"><li type="a">x</li></ul><ol type="a" start="3"><li>y</li></ol>'
                  '<img src="i.png" width="10" height="20"></body>')
    out = C.clean(doc, "https://e.org/a.htm", {}, lambda u: "images/i.png", [])
    assert 'width="80%"' not in out and 'width="20"' not in out and 'type="disc"' not in out
    assert 'type="a" start="3"' in out or ('start="3"' in out and '<ol type="a"' in out)
    assert 'width="10"' in out and 'height="20"' in out


# --------------------------------------------- copyright notice detection
@pytest.mark.parametrize("line,expected", [
    ("Copyright: English translation © Example Press 1984", True),
    ("Translation (c) 1977 Example Books", True),
    ("Source: Selected Writings; © A. Translator", True),
    ("Copyright: Public Domain", False),
    ("Copyleft: Some Internet Archive 2002", False),
    ("Transcribed: by a volunteer", False),
    ("Publisher: Example Publications, London, 1986 (no copyright)", False),
    ("Source: … Example House, 1951. No copyright notice.", False),
    ("Translated: … copyright free translations from the original would be preferred.", False),
    ("Source: … Copyright free status is verified … without Copyright notice.", False),
    ("Source: Selected Writings. Example Review Press © 1971.", True),
])
def test_copyright_notice_detection(line, expected):
    from bookcreator.sites.common import copyright_notice
    assert (copyright_notice(["Source: x", line]) == line) is expected


# ------------------------------------------- licence wording consistency
def test_licence_text_depends_on_copyrighted_content():
    from bookcreator.sites import marxists
    free, restricted = marxists.license_html("A"), marxists.license_html("A", restricted=True)
    assert "distributed under the same licence" in free and "private reading only" not in free
    assert "private reading only" in restricted and "distributed under the same licence" not in restricted


# ------------------------------------------- one bad work doesn't sink the build
def test_failing_work_is_skipped_not_fatal(tmp_path, monkeypatch):
    from bookcreator.build import Build
    monkeypatch.chdir(tmp_path)
    good, bad = WorkRef(url="https://e.org/a.htm", title="A"), WorkRef(url="https://e.org/b/index.htm", title="B")

    def expand(fetcher, w):
        if w is bad:
            raise ConnectionError("boom")
        w.pages = []

    b = Build({"source": {"site": "generic", "index": "https://e.org/"}, "book": {}}, tmp_path / "r.toml",
              verbose=False)
    b.site = types.SimpleNamespace(discover=lambda f, r: [good, bad], expand=expand)
    b.discover()
    assert [w.ref.title for w in b.works] == ["A"]
    assert b.skipped == [bad] and "boom" in bad.skipped_reason and b.warnings


# ---------------------------------------------------------- check command
def test_check_handles_four_digit_work_numbers_and_strict(tmp_path):
    from bookcreator.check import check_epub
    from bookcreator.epub import EpubBuilder, xhtml_page
    ep = EpubBuilder(identifier="urn:uuid:t", title="T", authors=["A"])
    ep.add("style.css", b"", "text/css")
    ep.add("text/w1000_note.xhtml", xhtml_page("N", "<p>“an invented quotation here”</p>"), spine=True)
    ep.add("text/w1000_00.xhtml", xhtml_page("W", "<p>Real text.</p>"), spine=True)
    out = tmp_path / "t.epub"
    ep.write(out)
    rep = check_epub(out)
    assert rep.quotes_checked == 1 and len(rep.quote_misses) == 1
    assert rep.ok and not rep.ok_strict()


# ------------------------------------------------------------- cover fit
def test_long_cover_title_fits_inside_frame():
    from PIL import Image, ImageDraw
    from bookcreator import cover
    d = ImageDraw.Draw(Image.new("RGB", (cover.W, cover.H)))
    title = "The Extraordinarily Long and Winding Title of a Collected Edition of Pamphlets 1907–1946"
    font, lines = cover._fit(d, title, "bold", 128, max_lines=4)
    assert len(lines) <= 4
    assert all(d.textlength(l, font=font) <= cover.W - 2 * cover.MARGIN for l in lines)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert cover.make_cover("Author", title, "Sub", "Footer")[:2] == b"\xff\xd8"   # JPEG


# ------------------------------------------- MIA: alternate translations on the index
def test_marxists_variants_attach_to_previous_work():
    from bookcreator.sites import marxists

    class F:
        def get_text(self, u):
            return ('<p class="information">'
                    '1918: <a href="1918/12/31.htm">Our Program</a> '
                    '(Alternate Translation: <a href="1918/12/30.htm">On the Spartacus Programme</a>)<br/>'
                    '1921: <a href="1921/wo/index.htm">A Pamphlet</a> '
                    '(<a href="1921/wo-alt/index.html">Alternative unabridged version</a>)<br/>'
                    '1922: <a href="1922/essay.htm">An Essay</a></p>')

        def final_url(self, u):
            return u

    refs = marxists.discover(F(), {"source": {"index": "https://www.marxists.org/archive/x/index.htm"}})
    assert [(r.year, r.title) for r in refs] == [
        ("1918", "Our Program"),
        ("1918", "Our Program (Alternate Translation: On the Spartacus Programme)"),
        ("1921", "A Pamphlet"),
        ("1921", "A Pamphlet (Alternative unabridged version)"),
        ("1922", "An Essay"),
    ]


def test_marxists_chapter_navigation_removed():
    from bookcreator.sites import marxists
    doc = C.parse('<body><p>Text.</p><p class="next">Next: <a href="ch03.htm">Part 3</a></p>'
                  '<p class="next">&lt;&lt;&lt; <a href="ch04.htm">Last Chapter</a> | '
                  '<a href="ch06.htm">Next Chapter</a> &gt;&gt;&gt;</p>'
                  '<h4><small>&lt;&lt; <a href="a.htm">Last Chapter</a> | <a href="b.htm">Next Chapter</a> &gt;&gt;'
                  '</small></h4><p>A long paragraph that refers the reader to the Next Chapter, where '
                  '<a href="b.htm">the argument</a> continues at considerable length.</p></body>')
    out = C.clean(doc, "https://www.marxists.org/archive/x/ch02.htm", {}, lambda u: None, marxists.JUNK_XPATHS)
    assert "Last Chapter" not in out and "Next:" not in out and "Text." in out
    assert "refers the reader to the Next Chapter" in out          # real prose is kept


def test_marxists_back_to_top_lines_removed():
    from bookcreator.sites import marxists
    doc = C.parse('<body><p>Real text, see <a href="#top">the top</a> of this long paragraph for '
                  'the argument that follows at some length.</p><hr/>'
                  '<h5><a href="#top">Top of the page</a></h5><p><a href="#Top">Back to top</a></p>'
                  '<p>More text.</p></body>')
    out = C.clean(doc, "https://www.marxists.org/archive/x/a.htm", {}, lambda u: None, marxists.JUNK_XPATHS)
    assert "Top of the page" not in out and "Back to top" not in out
    assert "Real text" in out and "More text." in out          # prose that merely links to #top is kept


# ------------------------------------------- the tool is credited in every book
@pytest.mark.parametrize("editorial", [False, True])
def test_book_creator_credited_before_editorial_attributions(editorial, tmp_path, monkeypatch):
    from bookcreator import __url__
    from bookcreator.build import Build
    monkeypatch.chdir(tmp_path)
    recipe = {"book": {"title": "T", "author": "A"},
              "source": {"site": "generic", "index": "https://e.example/"}}
    if editorial:
        recipe["editorial"] = {"dir": "ed", "attribution": "Notes drafted with the assistance of an LLM."}
    b = Build(recipe, tmp_path / "r.toml", verbose=False)
    b.site.discover(None, recipe)                       # configure the generic adapter
    page = b._license_page()
    assert f'href="{__url__}"' in page and "book-creator" in page
    if editorial:
        assert page.index(__url__) < page.index("Editorial material") < page.index("assistance of an LLM")
    else:
        assert "Editorial material" not in page


def test_marxists_contents_page_follows_links_across_directories():
    from bookcreator.sites import marxists
    from bookcreator.model import WorkRef

    class F:
        def get_text(self, u):
            return ('<p><a href="../../index.htm">Archive</a> <a href="../1916/07/07.htm">7 July 1916</a> '
                    '<a href="../1917/01/15.htm">15 January 1917</a> <a href="../../../trotsky/x.htm">other</a> '
                    '<a href="index.htm">index</a> <a href="../1916/07/07.htm#p2">again</a></p>')

        def final_url(self, u):
            return u

    w = WorkRef(url="https://www.marxists.org/archive/lux/1918/letters.htm", title="Letters", contents_page=True)
    marxists.expand(F(), w)
    assert [p.url.split("/lux/")[1] for p in w.pages] == ["1918/letters.htm", "1916/07/07.htm", "1917/01/15.htm"]
    assert w.pages[1].title == "7 July 1916"
