"""Offline end-to-end builds against saved pages from real sites (tests/fixtures/cache).

Each recipe in tests/live/ is built with the network disabled; the fixture cache stands
in for the live site. The assertions are about *content*: the text must start and end
where the work does, and none of the site's chrome may survive. That is what `check`
cannot see.
"""
from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

import pytest
import requests

from bookcreator.build import Build, BuildError
from bookcreator.check import check_epub, preview

HERE = Path(__file__).parent
LIVE = HERE / "live"
FIXTURES = HERE / "fixtures" / "cache"

SITES = {
    "avalon": dict(
        starts=["The Federalist Papers : No. 1 General Introduction",
                "The Federalist Papers : No. 10 The Same Subject Continued"],
        ends=["held out in several of the late publications against the new Constitution. Return to the Text",
              "supporting the character of Federalists. PUBLIUS."],
        chrome=["Avalon Home", "Document Collections", "Next Document", "Previous Document",
                "Lillian Goldman", "Statement of Purpose"],
        credits=None,
    ),
    "anarchist-library": dict(
        starts=["The popular notion about marriage and love is that they are synonymous",
                "I begin my article with an admission"],
        ends=["not marriage, but love will be the parent.",
              "the tragedy of woman’s emancipation with joy, limitless joy."],
        chrome=["Table of Contents", "Latest entries", "Donate", "RSS feed", "Bibliothèque Anarchiste",
                "anarchistnews.org"],
        credits=["retrieved on 2/8/17 from https://www.marxists.org/",
                 "Anarchy and the Sex Question: Essays on Women and Emancipation"],
    ),
    "wikisource": dict(
        starts=["The chief advantage that would result from the establishment of Socialism"],
        ends=["The new Individualism is the new Hellenism. Oscar Wilde"],
        chrome=["Jump to content", "not backed by a scanned copy", "For other versions of this work",
                "public domain worldwide", "falsefalse", "[edit]"],
        credits=["is in the public domain worldwide because the author died at least 100 years ago."],
    ),
}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """Work in a temp dir whose cache/ holds the fixtures; any network access fails."""
    shutil.copytree(FIXTURES, tmp_path / "cache")
    monkeypatch.chdir(tmp_path)

    def no_network(*a, **k):
        raise requests.ConnectionError("network disabled in tests")

    monkeypatch.setattr(requests.Session, "get", no_network)
    return tmp_path


def build(recipe_path: Path, tmp_path: Path) -> tuple[Build, Path]:
    recipe = tomllib.loads(recipe_path.read_text(encoding="utf-8"))
    b = Build(recipe, recipe_path, verbose=False)
    b.discover()
    b.convert_pages()
    out = b.write_epub(tmp_path / "book.epub")
    return b, out


def text(xhtml: str) -> str:
    xhtml = xhtml.rsplit('<p class="source-url">', 1)[0]
    return " ".join(re.sub(r"<[^>]+>", " ", xhtml).replace("&amp;", "&").split())


@pytest.mark.parametrize("site", sorted(SITES))
def test_site_builds_clean_text_offline(site, offline):
    exp = SITES[site]
    b, epub = build(LIVE / f"{site}.toml", offline)
    assert b.warnings == []
    chapters = [c for w in b.works for c in w.chapters]
    assert len(chapters) == len(exp["starts"])
    for ch, start, end in zip(chapters, exp["starts"], exp["ends"]):
        t = text(ch.body)
        assert t.startswith(start), f"{ch.url} starts with: {t[:120]!r}"
        assert t.endswith(end), f"{ch.url} ends with: {t[-120:]!r}"
        for junk in exp["chrome"]:
            assert junk not in t, f"site chrome {junk!r} left in {ch.url}"
    if exp["credits"]:                               # provenance survives, chapter by chapter
        for ch, credit in zip(chapters, exp["credits"]):
            assert credit in ch.credits, f"{ch.url} credits: {ch.credits!r}"
    rep = check_epub(epub)
    assert rep.ok, (rep.xml_errors, rep.broken_links)


def test_build_fails_when_no_page_can_be_fetched(offline, tmp_path):
    r = tmp_path / "r.toml"
    r.write_text('[book]\ntitle="T"\nauthor="A"\n[source]\nsite="generic"\nindex="https://nowhere.example/"\n'
                 '[[works]]\nurl="https://nowhere.example/missing.html"\ntitle="Missing"\n', encoding="utf-8")
    with pytest.raises(BuildError, match="none of the 1 page"):
        build(r, tmp_path)


def test_tiny_work_is_flagged(offline, tmp_path):
    page = tmp_path / "cache" / "e.example" / "versions.cache"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body><p>Versions of this work include: one, two.</p></body></html>")
    r = tmp_path / "r.toml"
    r.write_text('[book]\ntitle="T"\nauthor="A"\n[source]\nsite="generic"\nindex="https://e.example/"\n'
                 '[[works]]\nurl="https://e.example/versions"\ntitle="Versions"\n', encoding="utf-8")
    b, _ = build(r, tmp_path)
    assert any("only 7 words" in w and "right page" in w for w in b.warnings)


def test_content_xpath_that_matches_nothing_keeps_page_and_warns(offline, tmp_path):
    recipe = (LIVE / "anarchist-library.toml").read_text(encoding="utf-8")
    recipe = recipe.replace("//div[@id='thework']", "//div[@id='renamed-in-a-redesign']")
    r = tmp_path / "r.toml"
    r.write_text(recipe, encoding="utf-8")
    b, _ = build(r, tmp_path)
    assert sum("matched nothing" in w for w in b.warnings) == 2
    assert all(len(text(c.body).split()) > 3000 for w in b.works for c in w.chapters)


def test_preview_prints_chapter_edges(offline, capsys):
    _, epub = build(LIVE / "anarchist-library.toml", offline)
    preview(epub, words=8)
    out = capsys.readouterr().out
    assert "START: The popular notion about marriage and love is" in out
    assert "END:   tragedy of woman’s emancipation with joy, limitless joy." in out


def test_texts_export_and_batches(offline, tmp_path):
    from bookcreator.build import export
    import json
    res = export(LIVE / "anarchist-library.toml", tmp_path / "texts", batches=2)
    assert [w["slug"] for w in res["works"]] == ["library-emma-goldman-marriage-and-love",
                                               "library-emma-goldman-the-tragedy-of-woman-s-emancipation"]
    txt = (tmp_path / "texts" / "library-emma-goldman-marriage-and-love.txt").read_text(encoding="utf-8")
    assert txt.startswith("WORK: 1914 – Marriage and Love\nURL: ") and "SLUG: library-emma-goldman" in txt
    assert "The popular notion about marriage and love" in txt and "<p" not in txt and "Source: https" not in txt
    batches = json.loads((tmp_path / "texts" / "batches.json").read_text(encoding="utf-8"))
    assert len(batches) == 2 and sorted(len(b["works"]) for b in batches) == [1, 1]
