"""book-creator command line.

    bookcreator list  recipes/my-book.toml          # dry run: what would be included
    bookcreator build recipes/my-book.toml          # EPUB (+ formats from the recipe)
    bookcreator build recipes/my-book.toml --formats epub,azw3,pdf --refresh
    bookcreator check output/my-book.epub           # validate structure + editorial quotes
    bookcreator preview output/my-book.epub         # first/last words of each chapter
    bookcreator texts recipes/my-book.toml DIR --batches 5   # plain texts for editorial work

Paths (cache/, output/, editorial dirs) are relative to the current directory.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from .build import Build, BuildError, run
from .convert import ConversionError


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bookcreator", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the book")
    b.add_argument("recipe", type=Path)
    b.add_argument("--formats", help="comma list: epub,azw3,mobi,pdf,docx (default from recipe)")
    b.add_argument("--out", type=Path, default=Path("output"))
    b.add_argument("--refresh", action="store_true", help="ignore the download cache")
    b.add_argument("--add-to-calibre", action="store_true", help="import result into the Calibre library")

    l = sub.add_parser("list", help="show discovered works without building")
    l.add_argument("recipe", type=Path)
    l.add_argument("--refresh", action="store_true")

    c = sub.add_parser("check", help="validate a built EPUB")
    c.add_argument("epub", type=Path)
    c.add_argument("--strict", action="store_true",
                   help="also fail if an editorial quotation is not found anywhere in the book")
    t = sub.add_parser("texts", help="export each work as plain text (for writing editorial notes)")
    t.add_argument("recipe", type=Path)
    t.add_argument("out", type=Path)
    t.add_argument("--batches", type=int, default=0,
                   help="also split the works into N groups of similar length (batches.json)")
    t.add_argument("--refresh", action="store_true")

    pv = sub.add_parser("preview", help="print the start and end of every chapter (spot leftover site chrome)")
    pv.add_argument("epub", type=Path)
    pv.add_argument("-n", "--words", type=int, default=40)
    pv.add_argument("--all", action="store_true", help="include front matter and editorial pages")
    a = ap.parse_args(argv)

    if a.cmd == "texts":
        from .build import export
        res = export(a.recipe, a.out, a.batches, refresh=a.refresh)
        total = sum(w["words"] for w in res["works"])
        print(f"{len(res['works'])} works, {total:,} words -> {a.out}/")
        for i, (words, group) in enumerate(res.get("batches", [])):
            print(f"  batch {i}: {words:>7,} words, {len(group):>3} works")
        return 0

    if a.cmd == "preview":
        from .check import preview
        preview(a.epub, a.words, texts_only=not a.all)
        return 0

    if a.cmd == "check":
        from .check import check_epub, print_report
        rep = check_epub(a.epub)
        print_report(rep, a.epub)
        return 0 if (rep.ok_strict() if a.strict else rep.ok) else 1

    r = _load(a.recipe)
    if a.cmd == "list":
        bd = Build(r, a.recipe, refresh=a.refresh, verbose=False)
        bd.discover()
        for i, w in enumerate(bd.works, 1):
            print(f"{i:3d}. {w.label}  [{len(w.ref.pages)} page(s)]  {w.ref.url}")
        for s in bd.skipped:
            print(f"  –  SKIPPED ({s.skipped_reason}): {s.title}  {s.url}")
        return 0

    formats = a.formats.split(",") if a.formats else r.get("output", {}).get("formats", ["epub", "azw3"])
    try:
        outs = run(a.recipe, a.out, formats, refresh=a.refresh)
        if a.add_to_calibre:
            from .convert import add_to_library
            add_to_library(outs[0])
    except (BuildError, ConversionError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
