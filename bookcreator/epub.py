"""Minimal, standards-compliant EPUB 3 writer (with an EPUB 2 NCX for older readers
and for Calibre's Kindle conversion). No third-party dependencies."""
from __future__ import annotations

import datetime as _dt
import mimetypes
import zipfile
from dataclasses import dataclass, field
from html import escape
from pathlib import Path


@dataclass
class TocNode:
    title: str
    href: str
    children: list["TocNode"] = field(default_factory=list)


@dataclass
class Item:
    href: str              # path inside OEBPS/
    data: bytes
    media_type: str
    id: str
    properties: str | None = None


XHTML_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="{lang}" xml:lang="{lang}">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body{body_attr}>
{body}
</body>
</html>
"""


def xhtml_page(title: str, body: str, lang: str = "en", body_class: str | None = None) -> bytes:
    attr = f' class="{escape(body_class)}"' if body_class else ""
    return XHTML_TMPL.format(title=escape(title), body=body, lang=lang, body_attr=attr).encode("utf-8")


class EpubBuilder:
    def __init__(self, *, identifier: str, title: str, authors: list[str], language: str = "en",
                 description: str = "", publisher: str = "", rights: str = "", source: str = "",
                 subjects: list[str] | None = None, contributors: list[str] | None = None):
        self.meta = dict(identifier=identifier, title=title, authors=authors, language=language,
                         description=description, publisher=publisher, rights=rights,
                         source=source, subjects=subjects or [], contributors=contributors or [])
        self.items: list[Item] = []
        self.spine: list[str] = []          # item ids, reading order
        self.toc: list[TocNode] = []
        self.cover_id: str | None = None
        self.nav_position: int | None = None   # spine index for a visible Contents page
        self._n = 0

    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:04d}"

    def add(self, href: str, data: bytes, media_type: str | None = None, *, spine: bool = False,
            properties: str | None = None) -> str:
        mt = media_type or mimetypes.guess_type(href)[0] or "application/octet-stream"
        item = Item(href=href, data=data, media_type=mt, id=self._id("x" if spine else "r"),
                    properties=properties)
        self.items.append(item)
        if spine:
            self.spine.append(item.id)
        return item.id

    def set_cover(self, jpeg: bytes, lang: str = "en") -> None:
        self.cover_id = self.add("images/cover.jpg", jpeg, "image/jpeg", properties="cover-image")
        body = ('<div class="cover"><img src="../images/cover.jpg" alt="Cover"/></div>')
        page = xhtml_page("Cover", body, lang, body_class="cover")
        cid = self.add("text/cover.xhtml", page, "application/xhtml+xml")
        self.spine.insert(0, cid)

    # ------------------------------------------------------------ rendering
    def _nav(self) -> bytes:
        def ol(nodes):
            out = ["<ol>"]
            for n in nodes:
                out.append(f'<li><a href="{escape(n.href)}">{escape(n.title)}</a>')
                if n.children:
                    out.append(ol(n.children))
                out.append("</li>")
            out.append("</ol>")
            return "\n".join(out)

        # nav.xhtml lives in OEBPS/, hrefs in TocNode are relative to OEBPS/
        body = (f'<nav epub:type="toc" id="toc"><h1>Contents</h1>\n{ol(self.toc)}\n</nav>')
        lang = self.meta["language"]
        return (XHTML_TMPL.replace('href="../style.css"', 'href="style.css"')
                .format(title="Contents", body=body, lang=lang, body_attr="").encode("utf-8"))

    def _ncx(self) -> bytes:
        counter = [0]

        def points(nodes, depth=1):
            out = []
            for n in nodes:
                counter[0] += 1
                out.append(f'<navPoint id="np{counter[0]}" playOrder="{counter[0]}">'
                           f'<navLabel><text>{escape(n.title)}</text></navLabel>'
                           f'<content src="{escape(n.href)}"/>')
                out.extend(points(n.children, depth + 1))
                out.append("</navPoint>")
            return out

        def depth(nodes):
            return 1 + max((depth(n.children) for n in nodes), default=0) if nodes else 0

        m = self.meta
        return ("""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<head><meta name="dtb:uid" content="{uid}"/><meta name="dtb:depth" content="{d}"/>
<meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>
<docTitle><text>{t}</text></docTitle>
<navMap>
{p}
</navMap>
</ncx>
""".format(uid=escape(m["identifier"]), d=depth(self.toc), t=escape(m["title"]),
           p="\n".join(points(self.toc)))).encode("utf-8")

    def _opf(self, nav_id: str, ncx_id: str) -> bytes:
        m = self.meta
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        md = [f'<dc:identifier id="bookid">{escape(m["identifier"])}</dc:identifier>',
              f'<dc:title>{escape(m["title"])}</dc:title>',
              f'<dc:language>{escape(m["language"])}</dc:language>',
              f'<meta property="dcterms:modified">{now}</meta>']
        for i, a in enumerate(m["authors"]):
            md.append(f'<dc:creator id="creator{i}">{escape(a)}</dc:creator>')
            md.append(f'<meta refines="#creator{i}" property="role" scheme="marc:relators">aut</meta>')
        for i, c in enumerate(m["contributors"]):
            md.append(f'<dc:contributor id="contrib{i}">{escape(c)}</dc:contributor>')
        for key in ("description", "publisher", "rights", "source"):
            if m[key]:
                md.append(f"<dc:{key}>{escape(m[key])}</dc:{key}>")
        for s in m["subjects"]:
            md.append(f"<dc:subject>{escape(s)}</dc:subject>")
        if self.cover_id:
            md.append(f'<meta name="cover" content="{self.cover_id}"/>')

        manifest = []
        for it in self.items:
            props = f' properties="{it.properties}"' if it.properties else ""
            manifest.append(f'<item id="{it.id}" href="{escape(it.href)}" media-type="{it.media_type}"{props}/>')
        spine = "\n".join(f'<itemref idref="{i}"/>' for i in self.spine)
        guide = ""
        if self.cover_id:
            guide = '<guide><reference type="cover" title="Cover" href="text/cover.xhtml"/></guide>'
        return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{m['language']}">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
{chr(10).join(md)}
</metadata>
<manifest>
{chr(10).join(manifest)}
</manifest>
<spine toc="{ncx_id}">
{spine}
</spine>
{guide}
</package>
""".encode("utf-8")

    def write(self, path: Path) -> None:
        nav_id = self.add("nav.xhtml", self._nav(), "application/xhtml+xml", properties="nav")
        if self.nav_position is not None:
            self.spine.insert(self.nav_position, nav_id)
        ncx_id = self.add("toc.ncx", self._ncx(), "application/x-dtbncx+xml")
        opf = self._opf(nav_id, ncx_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            z.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
""", compress_type=zipfile.ZIP_DEFLATED)
            z.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
            for it in self.items:
                z.writestr("OEBPS/" + it.href, it.data, compress_type=zipfile.ZIP_DEFLATED)
