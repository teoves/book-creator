"""Live smoke tests: build each recipe in tests/live/ against the real website.

Skipped by default. Run them occasionally (they fetch a handful of pages, politely):

    pytest -m live

A failure here but not in test_sites.py means the site has changed: adjust the
recipe's content_xpath / junk_xpaths, then refresh tests/fixtures/ (see its README).
"""
from __future__ import annotations

import pytest

from bookcreator.check import check_epub

from test_sites import LIVE, SITES, build, text

pytestmark = pytest.mark.live


@pytest.mark.parametrize("site", sorted(SITES))
def test_site_live(site, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # fresh cache: really fetch
    exp = SITES[site]
    b, epub = build(LIVE / f"{site}.toml", tmp_path)
    assert b.warnings == [], b.warnings
    for ch, start, end in zip([c for w in b.works for c in w.chapters], exp["starts"], exp["ends"]):
        t = text(ch.body)
        assert t.startswith(start), f"{ch.url} now starts with: {t[:160]!r}"
        assert t.endswith(end), f"{ch.url} now ends with: {t[-160:]!r}"
        for junk in exp["chrome"]:
            assert junk not in t, f"site chrome {junk!r} appeared in {ch.url}"
    assert check_epub(epub).ok
