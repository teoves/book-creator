# Test fixtures

`cache/` mirrors book-creator's download cache (`cache/<host>/<path>.cache`) for the pages
used by the recipes in `tests/live/`. `tests/test_sites.py` copies it into a temporary
working directory, so full builds run offline against real-world markup.

The pages are **reduced copies**: scripts, stylesheets, comments, forms and site footers
have been removed, leaving the document text and the navigation markup the tests exercise.
They are third-party material. **They are not covered by this repository's MIT licence.**

| fixture | text | page |
|---|---|---|
| `avalon.law.yale.edu/…/fed01.asp`, `fed10.asp` | *The Federalist* Nos. 1 and 10 (1787), public domain | the Avalon Project, Yale Law School. The site's header and footer, the part under Yale's copyright, were removed |
| `theanarchistlibrary.org/…/emma-goldman-*` | Emma Goldman, *Marriage and Love* and *The Tragedy of Woman’s Emancipation*, public domain | The Anarchist Library (anti-copyright) |
| `en.wikisource.org/…/The_Soul_of_Man_Under_Socialism` | Oscar Wilde, *The Soul of Man Under Socialism* (1891), public domain | Wikisource contributors, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Source: <https://en.wikisource.org/wiki/The_Fortnightly_Review/Volume_49/The_Soul_of_Man_Under_Socialism>. Modified: scripts, styles and site chrome removed |

Pages were saved in November 2026. To refresh one after a site redesign:

1. run `pytest -m live` and fix the recipe in `tests/live/` if needed;
2. copy the newly cached page from `cache/` over the fixture;
3. reduce it the same way (remove scripts, styles and any copyrighted site template), and
   keep this table's attribution up to date.
