from lxml import etree

from bookcreator.markdown import to_xhtml


def test_basic_blocks_and_inline():
    out = to_xhtml("## Head\n\nA *titled* work and **bold** [link](https://x.org).\n\n> quoted\n\n- one\n- two")
    etree.fromstring(f"<div>{out}</div>")
    assert "<h2>Head</h2>" in out
    assert "<em>titled</em>" in out and "<strong>bold</strong>" in out
    assert '<a href="https://x.org">link</a>' in out
    assert "<blockquote><p>quoted</p></blockquote>" in out
    assert "<ul><li>one</li><li>two</li></ul>" in out


def test_heading_offset_and_escaping():
    out = to_xhtml("# Title\n\nFish & chips < 5", heading_offset=1)
    assert "<h2>Title</h2>" in out and "Fish &amp; chips &lt; 5" in out
