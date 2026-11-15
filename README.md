# book-creator

Compile your own e-books from online archives of public-domain and copyleft writings,
starting with the [Marxists Internet Archive](https://www.marxists.org/), and keep every
credit and licence notice the source requires.

Point it at an author's archive and it will:

1. find every work listed there, including multi-chapter works;
2. download the pages politely, honouring `robots.txt` and `Crawl-delay` and caching everything;
3. turn 1990s tag-soup HTML into clean, valid XHTML, with footnotes and cross-links made internal and images embedded;
4. assemble an EPUB 3 with a cover, title page, licence page, nested table of contents,
   a source URL at the end of every chapter and a *Sources and Credits* appendix;
5. convert it with [Calibre](https://calibre-ebook.com/) to Kindle AZW3, MOBI, PDF or DOCX;
6. optionally add your own **introduction and editor's notes** as Markdown files.

## Install

```bash
git clone <this repo> && cd book-creator
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"      # installs the `bookcreator` command
```

Python 3.11+ is required. For formats other than EPUB, install Calibre. Its `ebook-convert` is
found automatically on `PATH` or in `/Applications/calibre.app`.

## Use

```bash
.venv/bin/bookcreator list  recipes/example-luxemburg.toml   # dry run: what would be included
.venv/bin/bookcreator build recipes/example-luxemburg.toml   # -> output/*.epub, *.azw3, *.report.json
.venv/bin/bookcreator check output/rosa-luxemburg-works.epub # validate links + editorial quotations
.venv/bin/bookcreator preview output/rosa-luxemburg-works.epub # first/last words of every chapter
```

`check` validates structure. `preview` is for your eyes: leftover site menus, footers or the
wrong page show up immediately at the start or end of a chapter. Builds also warn about works
under 150 words (`[book] min_work_words`), which usually means an index or "versions" page, and
fail outright if not a single page could be fetched.

`build` options: `--formats epub,azw3,pdf`, `--refresh` to re-download instead of using `cache/`,
`--out DIR`, and `--add-to-calibre` to import into your Calibre library (close the Calibre app first).

Run commands from the project root. `cache/`, `output/` and editorial directories are resolved
against the current directory.

### Getting it onto a Kindle

* **EPUB** works with Amazon's *Send to Kindle* (email, app or web upload).
* **AZW3** is for USB sideloading: copy it into the Kindle's `documents/` folder.

## Recipes

A book is described by a TOML recipe. [`recipes/example-luxemburg.toml`](recipes/example-luxemburg.toml)
is a commented template. To make a new book from marxists.org:

1. copy the example and set `[book]`, plus `[source].index` and `scope` for the author's archive;
2. run `list`. If works are missing, change `link_selector` (a CSS selector for the links on the
   index page; author indexes differ, e.g. `p.information a` or `p.indentb a`);
3. use `exclude = ["…"]` to drop duplicates or variants, and `[[extra]]` to add works hosted elsewhere;
4. run `build`.

### Other websites

For other sites, use `site = "generic"` and list the pages yourself. Three working recipes are in
[`tests/live/`](tests/live/): Wikisource, the Avalon Project (Yale) and the Anarchist Library.

```toml
[source]
site          = "generic"
index         = "https://theanarchistlibrary.org/"      # for attribution
site_name     = "The Anarchist Library"                 # used in sentences, as written
license_name  = "Public domain / anti-copyright"
content_xpath = "//div[@id='thework']"                  # keep only the text (string or list)
junk_xpaths   = [".//div[@class='share-buttons']"]      # then strip these inside it
credit_xpath  = "//div[@id='preamblesrc']"              # provenance to keep in the credits

[[works]]
url      = "https://theanarchistlibrary.org/library/emma-goldman-marriage-and-love"
title    = "Marriage and Love"
year     = "1914"
chapters = false        # true: also follow same-directory HTML pages linked from this one
```

To configure a new site:

1. Open a work in your browser's developer tools and find the element that wraps only the
   text. That is your `content_xpath`.
2. Build one or two works and run `bookcreator preview`.
3. Add `junk_xpaths` for anything still visible at the edges of chapters, such as
   "Next / Previous" bars or notice boxes. They are also applied inside `credit_xpath`.
4. Repeat until every chapter starts and ends with the work itself.

If `content_xpath` matches nothing on a page, for example after a site redesign, the whole page
is kept and the build warns you. A site you use a lot may deserve a dedicated adapter (see below).

**Check the site's terms first.** Some sites forbid crawling their HTML pages. Project Gutenberg,
for example, asks automated tools to use its mirrors and bulk downloads instead. The fetcher obeys
`robots.txt`, but that is not the only rule a site may have.

## Editorial layer (optional)

Add an `[editorial]` section to the recipe and put Markdown files in its `dir`:

```
editorial/<book>/introduction.md     → "Introduction" after the licence page
editorial/<book>/<work-slug>.md      → an "Editor's note" before that work
```

A work's slug is its URL path inside `scope`, with `/` replaced by `-` and `index.htm` dropped.
For example, `…/luxemburg/1915/junius/index.htm` becomes `1915-junius`. Works without a note are
listed as warnings at build time. Editorial pages are styled apart from the source texts, and
the licence page states that they are new material.

The full process we use for writing these with AI agents is described in
[`AGENTS.md`](AGENTS.md): agreeing an angle, exporting the texts
(`bookcreator texts recipes/<book>.toml DIR --batches 5`), drafting in parallel batches, the
narrative style guide, and verification.

`bookcreator check` verifies that every “quoted passage” in a note appears verbatim in the work
it introduces. Run it whenever notes are drafted or edited, by hand or with AI assistance.
With `--strict` it exits non-zero if a quotation is found nowhere in the book (useful in CI).

## Layout

| path | role |
|---|---|
| `bookcreator/sites/marxists.py` | marxists.org adapter: author index → works → chapters, credit blocks, MIA licence text |
| `bookcreator/sites/generic.py`  | any site: URLs listed in the recipe, XPaths for chrome to strip and credits to keep |
| `bookcreator/clean.py`          | site-independent HTML → XHTML sanitiser |
| `bookcreator/epub.py`           | dependency-free EPUB 3 writer (with NCX) |
| `bookcreator/build.py`          | pipeline, front and back matter, editorial layer |
| `bookcreator/markdown.py`       | small Markdown → XHTML converter for editorial files |
| `bookcreator/cover.py`          | typographic cover generator (optional portrait) |
| `bookcreator/convert.py`        | Calibre bridge |
| `bookcreator/check.py`          | EPUB validator (structure, links, editorial quotations) |
| `recipes/`                      | book recipes |
| `editorial/`                    | introductions and notes per book |

### Writing a site adapter

Create `bookcreator/sites/<name>.py` exposing:

* `discover(fetcher, recipe) -> list[WorkRef]`
* `expand(fetcher, work)`
* `credits_of(doc) -> (credits, copyright_notice)`
* `license_html(author, restricted)`, where `restricted` is true when the book contains works with a
  copyright notice, so the licence text can't promise redistribution rights it doesn't have;
* the constants `JUNK_XPATHS`, `SITE_NAME`, `LICENSE_NAME`, `LICENSE_URL`, `TERMS_URL`, `COPYRIGHT_URL`,
  and optionally `CONTRIBUTORS` and `SITE_NAME_IN_SENTENCE` (e.g. "the Marxists Internet Archive").

Resolve relative links against `fetcher.final_url(url)`, not the requested URL, so redirects are
handled. `sites/common.py` has the shared `copyright_notice()` detector.

Then use `site = "<name>"` in a recipe.

## Licensing of generated books

The code is MIT-licensed (see `LICENSE`). **Books you generate carry the licences of their sources.**
For marxists.org, the [Terms of Use](https://www.marxists.org/admin/legal/terms-of-use.htm) and
[copyright page](https://www.marxists.org/admin/legal/corights.htm) ask that reuse credits MIA,
includes the URL of each work and credits transcribers and proofreaders. Volunteer-created
material is [CC BY-SA 2.0](https://creativecommons.org/licenses/by-sa/2.0/), so compilations must
stay CC BY-SA. Every build does this automatically:

* each work keeps MIA's original *Source / Translated / Transcribed / Copyleft* block verbatim;
* each chapter ends with its source URL;
* an *About This Edition* page states the licence and lists works that carry an explicit
  **Copyright** notice. These are translations MIA hosts *with permission*: fine for private
  reading, but not redistributable;
* a *Sources and Credits* appendix lists every work, its credits and URLs, and anything listed
  on the archive but not included (PDF-only items, items hosted elsewhere).

This is not legal advice. For anything beyond personal use, check each work's status yourself.

## Being a good citizen

The fetcher identifies itself, obeys `robots.txt` and the site's `Crawl-delay` (1 s on marxists.org),
backs off on `429`/`5xx` responses (honouring `Retry-After`), treats an unreachable `robots.txt`
as "fetch nothing", and caches every page, so rebuilding a book never touches the network again. Please keep it that
way. These archives are volunteer-run.

## Tests

```bash
.venv/bin/python -m pytest            # offline: unit tests + full builds against saved pages
.venv/bin/python -m pytest -m live    # opt-in: the same builds against the real websites
```

`tests/test_sites.py` builds every recipe in `tests/live/` against real pages saved in
`tests/fixtures/cache/`, with the network disabled. It asserts that each chapter starts and ends
with the actual text and that none of the site's chrome survives. The live tests run the same
assertions against the current sites. When a live test fails and the offline one passes, the
site has been redesigned: fix the recipe, then refresh the fixtures (see `tests/fixtures/README.md`).

To add a site, write a recipe in `tests/live/`, save its pages into the fixture cache, and add
the expected first and last words and chrome strings to `SITES` in `tests/test_sites.py`.
