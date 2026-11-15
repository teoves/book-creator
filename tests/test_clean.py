from bookcreator import clean as C
from bookcreator.sites import marxists

PAGE = """<HTML><HEAD><TITLE>t</TITLE></HEAD><BODY>
<p class="toplink"><a href="../index.htm" name="top">MIA</a></p>
<p class="title">Breadcrumb</p>
<H1>A Work</H1>
<p class="information"><span class="info">Source:</span> A Book, 1921;<br>
<span class="info">Transcribed:</span> A Volunteer</p>
<P>First para with a note<a href="#1" name="a1">[1]</a>
<P>Second para linking to <a href="ch02.htm#n3">chapter two</a> and <a href="#top">top</a>.
<CENTER><FONT color=red>centred</FONT></CENTER>
<script>alert(1)</script>
<p><a name="1">[1]</a> The note.</p>
<p class="footer"><a href="../index.htm">Archive</a></p>
</BODY></HTML>"""

URL = "https://example.org/archive/a/1921/work.htm"


def _clean():
    doc = C.parse(PAGE)
    url_map = {"https://example.org/archive/a/1921/ch02.htm": "text/w001_01.xhtml"}
    return doc, C.clean(doc, URL, url_map, lambda u: None, marxists.JUNK_XPATHS)


def test_chrome_and_scripts_removed():
    _, out = _clean()
    assert "Breadcrumb" not in out and "Archive" not in out and "alert" not in out


def test_tag_soup_becomes_wellformed_xhtml():
    from lxml import etree
    _, out = _clean()
    etree.fromstring(f"<body>{out}</body>")          # raises if not well-formed
    assert "<center" not in out.lower() and "<font" not in out.lower()


def test_ids_sanitised_and_links_rewritten():
    _, out = _clean()
    assert 'id="n_1"' in out and 'href="#n_1"' in out          # numeric anchor made a valid XML id
    assert 'href="w001_01.xhtml#n3"' in out                    # link to an included page becomes internal
    assert 'href="#top"' not in out                             # dangling anchor (target was chrome) dropped


def test_credits_extracted():
    doc = C.parse(PAGE)
    credits, notice = marxists.credits_of(doc)
    assert credits.splitlines() == ["Source: A Book, 1921;", "Transcribed: A Volunteer"]
    assert notice is None
