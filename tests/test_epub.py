from bookcreator.check import check_epub
from bookcreator.epub import EpubBuilder, TocNode, xhtml_page


def test_minimal_epub_is_valid(tmp_path):
    ep = EpubBuilder(identifier="urn:uuid:test", title="T", authors=["A"])
    ep.add("style.css", b"p{}", "text/css")
    ep.add("text/a.xhtml", xhtml_page("A", '<p id="x">hi <a href="b.xhtml#y">b</a></p>'), spine=True)
    ep.add("text/b.xhtml", xhtml_page("B", '<p id="y">there</p>'), spine=True)
    ep.add("text/w001_note.xhtml", xhtml_page("N", "<p>She wrote “hi there friend of mine”.</p>"), spine=True)
    ep.add("text/w001_00.xhtml", xhtml_page("W", "<p>Hi there friend of mine.</p>"), spine=True)
    ep.toc = [TocNode("A", "text/a.xhtml"), TocNode("B", "text/b.xhtml")]
    out = tmp_path / "t.epub"
    ep.write(out)

    import zipfile
    z = zipfile.ZipFile(out)
    assert z.namelist()[0] == "mimetype" and z.read("mimetype") == b"application/epub+zip"

    rep = check_epub(out)
    assert rep.ok and rep.quotes_checked == 1 and rep.quote_misses == []
