"""Post-build validation of a generated EPUB.

* structure: every XHTML/OPF/NCX file is well-formed XML, every internal link
  points to an existing file and (if it has a #fragment) an existing id;
* quotations: every “quoted passage” in an editor's note must appear verbatim in
  the work it introduces (or, failing that, elsewhere in the book). This guards
  against paraphrases or invented quotations slipping into editorial material.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

XHTML_NS = {"x": "http://www.w3.org/1999/xhtml"}
_NOTE_RE = re.compile(r"OEBPS/text/(w\d+)_note\.xhtml$")


@dataclass
class Report:
    xml_errors: list[str] = field(default_factory=list)
    broken_links: list[tuple[str, str]] = field(default_factory=list)
    quotes_checked: int = 0
    quote_misses: list[tuple[str, str, bool]] = field(default_factory=list)   # (note, quote, found elsewhere)

    @property
    def ok(self) -> bool:
        return not self.xml_errors and not self.broken_links

    def ok_strict(self) -> bool:
        """Also fail when an editorial quotation is not found verbatim anywhere in the book."""
        return self.ok and not any(not elsewhere for _, _, elsewhere in self.quote_misses)


def _norm(s: str) -> str:
    # quote marks and apostrophes vary between transcriptions (“ ” " ‘ ’ '), so ignore them
    s = re.sub(r"[“”\"«»‘’'`´]", "", s)
    return re.sub(r"\s+", " ", s).lower()


def _text(tree) -> str:
    body = tree.find(".//x:body", XHTML_NS)
    return " ".join((body if body is not None else tree).itertext())


def check_epub(path: Path, min_quote_len: int = 12) -> Report:
    rep = Report()
    z = zipfile.ZipFile(path)
    names = set(z.namelist())
    trees: dict[str, etree._Element] = {}
    for n in sorted(names):
        if n.endswith((".xhtml", ".opf", ".ncx")):
            try:
                trees[n] = etree.fromstring(z.read(n))
            except etree.XMLSyntaxError as e:
                rep.xml_errors.append(f"{n}: {e}")

    ids = {n: set(t.xpath("//@id")) for n, t in trees.items() if n.endswith(".xhtml")}
    for n, t in trees.items():
        if not n.endswith(".xhtml"):
            continue
        for href in t.xpath("//x:a/@href", namespaces=XHTML_NS):
            if href.startswith(("http:", "https:", "mailto:")):
                continue
            f, _, frag = href.partition("#")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(n), f)) if f else n
            if target not in names or (frag and frag not in ids.get(target, set())):
                rep.broken_links.append((n, href))

    # editorial quotations
    texts = {n: _norm(_text(t)) for n, t in trees.items() if n.endswith(".xhtml")}
    whole = " ".join(v for k, v in texts.items() if "_note" not in k and "introduction" not in k)
    for n, t in trees.items():
        m = _NOTE_RE.search(n)
        if not m:
            continue
        work = " ".join(v for k, v in texts.items() if k.startswith(f"OEBPS/text/{m.group(1)}_") and "_note" not in k)
        for q in re.findall(r"“([^”]+)”", _text(t)):
            if len(q) < min_quote_len:
                continue
            rep.quotes_checked += 1
            parts = [p.strip(" .,;:!?\"'") for p in re.split(r"\s*(?:\.\.\.|…)\s*", _norm(q))]
            parts = [p for p in parts if len(p) > 3]
            if not all(p in work for p in parts):
                rep.quote_misses.append((n.rsplit("/", 1)[-1], q, all(p in whole for p in parts)))
    return rep


def print_report(rep: Report, path: Path) -> None:
    print(f"Checked {path}")
    print(f"  XML errors:    {len(rep.xml_errors)}")
    for e in rep.xml_errors[:20]:
        print("    ", e)
    print(f"  broken links:  {len(rep.broken_links)}")
    for f, h in rep.broken_links[:20]:
        print(f"     {f} -> {h}")
    if rep.quotes_checked:
        print(f"  editorial quotes: {rep.quotes_checked} checked, {len(rep.quote_misses)} not found verbatim in their work")
        for note, q, elsewhere in rep.quote_misses:
            print(f"     {note}: “{q}”" + ("  (found elsewhere in the book)" if elsewhere else ""))


def spine_documents(path: Path) -> list[str]:
    """XHTML files of an EPUB in reading order."""
    z = zipfile.ZipFile(path)
    container = etree.fromstring(z.read("META-INF/container.xml"))
    opf_path = container.xpath("//*[local-name()='rootfile']/@full-path")[0]
    opf = etree.fromstring(z.read(opf_path))
    base = posixpath.dirname(opf_path)
    hrefs = {i.get("id"): i.get("href") for i in opf.xpath("//*[local-name()='item']")}
    return [posixpath.join(base, hrefs[r]) for r in opf.xpath("//*[local-name()='itemref']/@idref")]


def preview(path: Path, words: int = 40, texts_only: bool = True) -> None:
    """Print the first and last `words` words of every document in reading order.

    `check` validates structure; this is for eyes: leftover site menus, footers,
    cookie banners or the wrong page show up immediately at the edges of a chapter."""
    z = zipfile.ZipFile(path)
    for name in spine_documents(path):
        leaf = name.rsplit("/", 1)[-1]
        if texts_only and not re.match(r"w\d+_\d+\.xhtml$", leaf):
            continue
        tree = etree.fromstring(z.read(name))
        for p in tree.xpath("//x:p[@class='source-url']", namespaces=XHTML_NS):
            p.getparent().remove(p)
        toks = " ".join(_text(tree).split()).split(" ")
        head = " ".join(toks[:words])
        tail = " ".join(toks[-words:]) if len(toks) > 2 * words else ""
        print(f"── {leaf}  ({len(toks)} words)")
        print(f"   START: {head}")
        if tail:
            print(f"   END:   {tail}")
