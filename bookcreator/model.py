"""Plain data structures shared by the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageRef:
    url: str
    title: str | None = None          # title as given by the linking page (e.g. "Chapter 3")


@dataclass
class WorkRef:
    url: str
    title: str
    year: str | None = None
    pages: list[PageRef] = field(default_factory=list)   # filled by the site adapter
    skipped_reason: str | None = None                     # e.g. "PDF only"
    contents_page: bool = False                           # follow its in-archive links as chapters


@dataclass
class Chapter:
    """One XHTML file inside the EPUB."""
    url: str
    file: str                       # e.g. "text/w012_03.xhtml"
    title: str
    body: str = ""                  # cleaned XHTML body content
    credits: str = ""               # plain-text credit / provenance lines found on the page
    copyright_notice: str | None = None


@dataclass
class Work:
    ref: WorkRef
    chapters: list[Chapter] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.ref.year} – {self.ref.title}" if self.ref.year else self.ref.title
