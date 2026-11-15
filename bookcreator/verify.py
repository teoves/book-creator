"""Mechanical verification of editorial notes against the texts they introduce.

Editorial notes paraphrase. A paraphrase can be wrong while every quotation in it is
exact – e.g. "Russia is saving herself from the tsar" for a passage where *Germany*
promises to free Russia from the tsar. Two sidecar files per note make such errors
checkable:

editorial/<book>/evidence/<slug>.json   – written by the note's author
    [{"claim": "<one claim the note makes about the text>",
      "quotes": ["<verbatim passage from the work that supports it>", ...]},
     {"claim": "<historical context not stated in the text>", "basis": "context"},
     {"claim": "<why a phrase not from the text is quoted>", "basis": "context",
      "external_quote": "<the quoted phrase, e.g. a label or another author's title>"}]

(the introduction uses the slug "introduction"; its passages may come from any work)

editorial/<book>/review/<slug>.json     – written by an independent verifier
    [{"sentence": "<sentence from the note>",
      "verdict": "ok" | "unsupported" | "wrong",
      "problem": "<what is wrong, if anything>",
      "evidence": ["<verbatim passage(s) from the work>"]}]

This module checks what a machine can check: that the files exist and are well formed,
that every cited passage really occurs verbatim in that work (so neither author nor
verifier can invent support), that every “quotation” in the note is verbatim, and it
lists every claim the verifier did not pass. Whether a passage *supports* a claim is the
verifier's job, not this module's.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_QUOTE_CHARS = re.compile(r"[“”\"«»‘’'`´]")


def norm(s: str) -> str:
    """Comparison form: no quote marks/apostrophes, collapsed whitespace, lower case."""
    return re.sub(r"\s+", " ", _QUOTE_CHARS.sub("", s)).strip().lower()


def found(passage: str, text_norm: str) -> bool:
    """Is `passage` in the (normalised) text? Ellipses (… or ...) may join pieces."""
    pieces = [p.strip(" .,;:!?") for p in re.split(r"\s*(?:\.\.\.|…|\[…\]|\[\.\.\.\])\s*", norm(passage))]
    pieces = [p for p in pieces if len(p) > 3]
    return bool(pieces) and all(p in text_norm for p in pieces)


@dataclass
class NoteResult:
    slug: str
    problems: list[str] = field(default_factory=list)       # mechanical failures
    flagged: list[dict] = field(default_factory=list)       # verifier verdicts other than "ok"
    claims: int = 0
    context_claims: int = 0
    reviewed: int = 0


def _load(path: Path, problems: list[str]) -> list | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        problems.append(f"{path.name}: invalid JSON ({e})")
        return None
    if not isinstance(data, list):
        problems.append(f"{path.name}: expected a JSON list")
        return None
    return data


def verify_note(slug: str, note: str, text: str, ed_dir: Path, require_review: bool) -> NoteResult:
    res = NoteResult(slug)
    tn = norm(text)

    ev = _load(ed_dir / "evidence" / f"{slug}.json", res.problems)
    # phrases the note quotes from elsewhere (a label, another author) are declared in the evidence
    external = {norm(c["external_quote"]) for c in (ev or []) if isinstance(c, dict) and c.get("external_quote")}

    for q in re.findall(r"“([^”]{12,})”", note):                       # quotations in the note
        if norm(q) not in external and not found(q, tn):
            res.problems.append(f"quotation not verbatim in the work: “{q[:90]}”")

    if ev is None:
        if not any(p.startswith("evidence") for p in res.problems):
            res.problems.append("no evidence file (evidence/<slug>.json)")
    else:
        for i, c in enumerate(ev):
            if not isinstance(c, dict) or not c.get("claim"):
                res.problems.append(f"evidence[{i}]: missing 'claim'")
                continue
            if c.get("basis") == "context":
                res.context_claims += 1
                continue
            res.claims += 1
            quotes = c.get("quotes") or []
            if not quotes:
                res.problems.append(f"claim without quotes: {c['claim'][:90]}")
            for q in quotes:
                if not found(q, tn):
                    res.problems.append(f"evidence not found in the work: “{q[:90]}” (claim: {c['claim'][:60]})")

    rv = _load(ed_dir / "review" / f"{slug}.json", res.problems)
    if rv is None:
        if require_review:
            res.problems.append("no review file (review/<slug>.json)")
    else:
        for i, r in enumerate(rv):
            if not isinstance(r, dict) or r.get("verdict") not in ("ok", "unsupported", "wrong"):
                res.problems.append(f"review[{i}]: verdict must be ok/unsupported/wrong")
                continue
            res.reviewed += 1
            for q in r.get("evidence") or []:
                if not found(q, tn):
                    res.problems.append(f"review evidence not found in the work: “{q[:90]}”")
            if r["verdict"] != "ok":
                res.flagged.append(r)
    return res


def verify_book(build, require_review: bool = False) -> list[NoteResult]:
    """Verify every editor's note of a converted Build (convert_pages() must have run)."""
    if not build.ed_dir:
        raise ValueError("recipe has no [editorial] dir")
    results = []
    texts = build.work_texts()
    for slug, _w, text in texts:
        f = build.ed_dir / f"{slug}.md"
        if f.exists():
            results.append(verify_note(slug, f.read_text(encoding="utf-8"), text, build.ed_dir, require_review))
    intro = build.ed_dir / "introduction.md"
    if intro.exists():          # the introduction draws on every work: check against all of them
        everything = "\n\n".join(t for _s, _w, t in texts)
        results.insert(0, verify_note("introduction", intro.read_text(encoding="utf-8"), everything,
                                      build.ed_dir, require_review))
    return results


def print_results(results: list[NoteResult]) -> bool:
    bad = [r for r in results if r.problems or r.flagged]
    claims = sum(r.claims for r in results)
    ctx = sum(r.context_claims for r in results)
    reviewed = sum(r.reviewed for r in results)
    print(f"{len(results)} notes · {claims} evidenced claims · {ctx} context claims · "
          f"{reviewed} reviewed sentences · {sum(len(r.flagged) for r in results)} flagged")
    for r in bad:
        print(f"── {r.slug}")
        for p in r.problems:
            print(f"   ✗ {p}")
        for f in r.flagged:
            print(f"   ⚑ [{f['verdict']}] {f.get('sentence', '')[:110]}")
            if f.get("problem"):
                print(f"       → {f['problem'][:220]}")
    if not bad:
        print("all notes verified")
    return not bad
