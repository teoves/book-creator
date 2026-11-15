# AGENTS.md

Instructions for AI agents (and humans) working in this repository: how to develop the tool,
and the process for writing a book's **editorial layer**: an introduction and an editor's
note before each work.

## The project in one paragraph

`bookcreator` compiles e-books from online archives (marxists.org first, other sites through
the generic adapter). A **recipe** (`recipes/<book>.toml`) describes a book. Downloaded pages are
cached in `cache/` and books are written to `output/`. Optional editorial Markdown lives in
`editorial/<book>/`. See `README.md` for usage. Personal book projects (their recipes and
`editorial/` folders) are listed in `.gitignore` and stay out of the public repo. Add new ones
there too.

## Working on the code

- Set up with `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- Run `.venv/bin/python -m pytest` before every commit. It runs offline unit tests plus full
  builds against saved pages in `tests/fixtures/`. `pytest -m live` hits the real sites;
  run it only when asked, or after changing a site recipe.
- Every bug fix gets a regression test (`tests/test_fixes.py` holds them by topic).
- After changing the cleaner or an adapter, rebuild an existing book and compare it with the
  previous EPUB. Only the intended files should change (`content.opf` always changes, because
  it has a timestamp).
- Be polite to the archives. Never bypass the cache or the fetcher's throttling, and check a
  site's terms before adding it (Project Gutenberg, for example, forbids crawling its HTML).
- Commit only when the user asks.

---

## Writing the editorial layer

This is the process we settled on after producing a full collected-writings volume: 47 works, about
320,000 words, a 2,600-word introduction and 47 notes totalling about 19,000 words. Follow it
for every book.

### 0. Agree on three things with the user first

1. **The angle.** The book's interpretive thread, for example "the author as an early
   philosopher of love" or "the author on democracy and spontaneity". The introduction is built around it and every note says how its work relates to
   it. **Never force the angle onto works it doesn't fit.** A war pamphlet gets a neutral note,
   with at most one sentence linking it, and only if the link is real.
2. **Lengths.** Scale them to the source (see the tiers below). A two-page note on a one-page
   decree is longer than the decree.
3. **Quota.** Reading the whole book is the expensive part. On a Claude Pro plan, a
   320k-word book took about 25% of the 5-hour window to draft, introduction and review included, and about 16% for one narrative
   rewrite. Larger books scale roughly linearly, so check usage, report it, and split the work
   across windows if needed.

Don't attribute views to living commentators, podcasts or scholars unless the user explicitly
asks for it. Write *in the spirit of* a framing without putting words in anyone's mouth.

### 1. Build the book, then export the texts

```bash
.venv/bin/bookcreator build recipes/<book>.toml
.venv/bin/bookcreator texts recipes/<book>.toml <scratch-dir>/texts --batches 5
```

`texts` writes one `<slug>.txt` per work, with a header giving its label, URL, slug and pages.
It also writes `works.json` (word counts) and `batches.json`: groups of similar total length,
each in book order. Aim for about 55–65k words per batch. A single work longer than that, such as
a 166k-word treatise, gets an agent of its own, which reads it
section by section and may write the note from per-section summaries. Keep these exports in a
scratch directory, not in the repo.

Add an `[editorial]` section to the recipe:

```toml
[editorial]
dir         = "editorial/<book>"
intro_title = "Introduction: <title built around the angle>"
note_label  = "Editor’s note"
attribution = "The introduction and editor’s notes were drafted with the assistance of Claude (Anthropic), working from the texts in this volume, and reviewed for this edition."
```

Keep the attribution line. The editorial material is new writing, released under the book's
licence, and readers should know how it was made.

### 2. Write one note yourself first, as the voice model

Before delegating, the lead agent writes the note for the most central work in full, in the
target voice described below. Store it at `editorial/<book>/<slug>.md`. It is the model every
other note imitates: register is far easier to copy from an example than from a description.

### 3. Delegate the notes in parallel, one agent per batch

- About 5 agents, each with one batch from `batches.json`, running in the background. A cheaper
  model (Sonnet) is enough for reading and drafting; the lead agent keeps the introduction and
  the final edit.
- Each agent receives the style guide below, the path of the voice-model note, its list of
  works (slug, label, word count, tier), any per-work guidance (for example "this is the second
  version of X; explain how it differs, don't summarise it again" or "novel: don't reveal the
  ending"), and the output paths.
- Each agent **reads every work in full** (short texts in one go, long ones in sections) and
  touches no files other than its own.
- **Every note comes with an evidence file**, `editorial/<book>/evidence/<slug>.json`. It lists
  each claim the note makes about the text (what is argued, depicted, said, and *by whom to
  whom*) with the verbatim passage(s) that support it. Historical context not stated in the
  text is listed too, marked `"basis": "context"`. See the format in `bookcreator/verify.py`.
  Writing the evidence is how authors catch their own paraphrase errors: if no passage says
  it, the sentence goes.
- Ask each agent for a report of at most 100 words: files written, word counts, and anything it
  left out because it couldn't be stated confidently. Don't let it paste the notes into its
  report.

### 4. The introduction is written by the lead agent

About 2,500–3,000 words (5–6 printed pages) of essayistic prose with `##` section headings. The
reference introduction followed this arc:

1. An opening **scene** that embodies the angle: a specific moment, place and person in which
   the book's central question is visibly at stake.
2. Why the angle matters, compared with the usual portrait of the author.
3. The life in brief, told as a story, with dates.
4. Three to five sections, each tracing one thread of the angle through specific works.
5. The material or political ground under the ideas.
6. The fiction or other genres, if there are any.
7. Reception and afterlives: how the work was received and later rediscovered, plus later
   thinkers who are commonly read alongside it. Only name well-established connections.
8. "About this collection": order, versions, a suggested reading path, and thanks to the
   archive's transcribers.

Take every quotation in the introduction from the exported texts. Search for each one with
`grep` before using it.

### 5. Verify: mechanical checks, then an independent review

Quotation checks alone are not enough. A note once said "Russia, she is told, is saving
herself from the tsar" when the text has *Germany* promising to free Russia from the tsar:
every quotation was exact, and the meaning was wrong. So verification has two layers.

1. **Mechanical:** `bookcreator verify recipes/<book>.toml`. It checks that every “quotation”
   in a note and every evidence passage occurs verbatim in that work. (It ignores quote marks
   and case, not spelling.) Fix every ✗ before going on.
2. **Independent review:** one *fresh* verifier agent per batch, never the note's author.
   It gets the note and the source text, and nothing else, with this brief:
   - Read the work in full. Then go through the note **sentence by sentence**. For every
     sentence that says anything about the text (who says what, to whom, in what order; what is
     argued or rejected; what happens in a story; how a work begins or ends), find the
     passage that supports it.
   - Be adversarial. Look especially for misattribution (the wrong speaker, country, party or
     character), inversion (the author *rejects* what the note says she argues), conflation
     of two passages, overstatement ("always", "every", "first"), invented detail, and
     context presented as if it came from the text.
   - Write `editorial/<book>/review/<slug>.json`: one entry per checked sentence, with
     verdict `ok`, `unsupported` or `wrong`, a one-line `problem`, and verbatim `evidence`.
     Context sentences that the text can't confirm are `unsupported` unless they are
     common knowledge (dates of wars, revolutions, offices held).
   - Don't edit the note.
3. **Fix and re-run.** The lead agent fixes every `wrong` and `unsupported` (rewrite or cut,
   never hedge), updates the evidence, and re-runs
   `bookcreator verify recipes/<book>.toml --require-review` until nothing is flagged. A
   corrected sentence needs a fresh `ok` in the review file, from the lead agent re-reading
   the passage. A model may not mark its own fix as verified without citing the passage.
4. Then `bookcreator build`, `bookcreator check --strict`, and a search for leftover hedging:
   `grep -n -i -E "credit block|does not say|does not state|readers should|this note|should be read|probably|perhaps|unknown|not known" editorial/<book>/*.md`
5. The introduction gets the same treatment. The lead agent writes
   `evidence/introduction.json`, quoting the works the claims come from, and a fresh verifier
   reviews it against the texts it cites.
6. `bookcreator preview` and a final report to the user: what was written, what the review
   caught, what was cut, and how much quota was used.

Verification is expensive, because every work is read again by someone new. For the 320k-word
reference book, the full pass took nearly 90% of a Claude Pro 5-hour window: rewriting with evidence
(5 agents), independent review (6 agents), and one fixer. It caught 70+ real errors that quotation
checks had missed. Budget for it from the start, and split a large book across two windows.

### Length tiers

| source text | note |
|---|---|
| under 1,500 words | 150–250 words: a vignette |
| 1,500–5,000 words | 300–450 words |
| over 5,000 words, or a core work for the angle | 500–800 words |
| second version of a work already noted | 150–300 words, only what differs |

### Style guide for every editorial note (give this to the agents)

The notes introduce works in a literary edition, in the manner of NYRB Classics or Penguin
Classics. They tell the story of a person, a moment and an idea. They are not a report on
work done. Readers are intelligent non-specialists.

**Voice**
- **Open with a scene, a situation or a question**, never with "X wrote this in…". Put the
  reader in the moment: where the author was, what was at stake, and whom they were addressing.
- **Use varied, flowing sentences.** Mix long, rhythmic sentences with short ones for emphasis,
  and use transitions that carry the reader from one idea to the next ("But…", "What she does
  next…"). Avoid bullet-point thinking dressed as prose.
- **Tell the argument as a movement of thought**, with its moves and turns, not as a list of
  claims. For fiction, tell the drama and the moral problem, and **never reveal the ending**.
- **Earn your interpretation.** Say what is striking, moving, strange or unresolved, but ground
  it in the text.

**Content of each note**
1. Context: when and where the work was written, what was happening, and whom it addressed.
2. The argument or story, in the author's own terms.
3. Why it matters: its place in the author's thought, its links to other works *in this
   collection* (by title), its relation to the book's angle (only if real), and reception
   where well established.

**Accuracy**
- Use only facts that appear in the source text or its credit block, or that are well
  established. **If unsure, leave it out, silently.** Never invent quotations, statistics, dates
  or reception history.
- Quote the author **verbatim, from the exported text only**, briefly (under about 30 words), in
  curly quotes “…”. Don't quote other authors.
- Where historians genuinely disagree, one natural clause is enough ("a charge her critics
  never quite proved"). Don't adjudicate.
- **No hedging or meta-commentary:** nothing about what "the credit block says", "the text does
  not state", "this note", or what readers "should" do.

**Format**
- Markdown body only. No title (the book adds it), no headings, no bullet lists. Separate
  paragraphs with blank lines, put titles of works in *italics*, and use curly punctuation
  (“ ” ’ –).
- Put publication and translation details in a single short italic line at the very end, for
  example `*First published in the* Fortnightly Review, *February 1891.*`. Give
  bibliographic detail in the body only when it is part of the story (for example, passages
  the author struck out of her own autobiography).

**Example opening** (for a note on Oscar Wilde’s *The Soul of Man Under Socialism*)

> In February 1891 the readers of the *Fortnightly Review*, a serious monthly given to essays on
> politics and philosophy, turned the page to find an unlikely contributor. Oscar Wilde was then
> best known as a wit, a dandy and the author of a novel his critics called unwholesome. Now he
> had written on socialism, and not to denounce it. But this was no ordinary case for it. Wilde
> wanted socialism for the sake of the individual: to free each person from poverty, and from
> charity too, so that they could at last become themselves.

### Lessons learned

- The first draft, written to a "clarity" brief, came out dry and hedged: short declarative
  sentences full of "the credit block states…". The user wanted narrative. **Start in the
  narrative voice** to avoid paying for a rewrite.
- Agents' notes caught a factual slip in the introduction (a misdescribed argument in an
  early essay). Cross-check the introduction against the notes.
- Volumes bundle extra pieces (a novella published together with two short stories). Read the whole
  export, not only the title piece, and mention bundled pieces in both the note and the
  introduction.
- Agents add apostrophes and change spelling inside quotations. `check --strict` catches this;
  fix each miss to the source's exact wording.
- A note can be wrong while every quotation in it is exact. A reader caught "Russia is saving
  herself from the tsar" for a passage about *German* propaganda. Hence evidence files and the
  independent review: paraphrase is where the errors hide.
