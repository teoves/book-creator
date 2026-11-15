"""Format conversion through Calibre's `ebook-convert` (and optional library import)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

class ConversionError(RuntimeError):
    """Calibre is missing or ebook-convert failed."""


_CANDIDATES = [
    "/Applications/calibre.app/Contents/MacOS/{tool}",
    "/usr/bin/{tool}",
    "C:/Program Files/Calibre2/{tool}.exe",
]


def calibre_tool(tool: str) -> str:
    found = shutil.which(tool)
    if found:
        return found
    for c in _CANDIDATES:
        p = c.format(tool=tool)
        if Path(p).exists():
            return p
    raise ConversionError(f"Calibre's '{tool}' not found – install Calibre from https://calibre-ebook.com/")


def convert(epub: Path, fmt: str, recipe: dict) -> Path:
    out = epub.with_suffix("." + fmt)
    b = recipe["book"]
    cmd = [calibre_tool("ebook-convert"), str(epub), str(out),
           "--authors", b["author"], "--title", b["title"],
           "--language", b.get("language", "en"),
           "--chapter-mark", "none", "--page-breaks-before", "/"]   # keep our own structure
    if fmt in ("azw3", "mobi"):
        cmd += ["--no-inline-toc"]
    if fmt == "pdf":
        cmd += ["--paper-size", "a5", "--pdf-page-numbers", "--preserve-cover-aspect-ratio"]
    cmd += recipe.get("output", {}).get("calibre_args", {}).get(fmt, [])
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-8:])
        raise ConversionError(f"ebook-convert failed converting {epub.name} to {fmt.upper()} "
                              f"(exit {r.returncode}):\n{tail}")
    return out


def add_to_library(path: Path) -> None:
    """Add the book to the default Calibre library (Calibre GUI must be closed)."""
    r = subprocess.run([calibre_tool("calibredb"), "add", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise ConversionError(f"calibredb add failed (is the Calibre app open?):\n{(r.stderr or '').strip()}")
