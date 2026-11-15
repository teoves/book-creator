"""Polite, cached HTTP fetcher.

* Every response is cached on disk under cache/<host>/<path>.cache, so re-running
  a build never re-downloads anything unless --refresh is given.
* Redirects are remembered (a sidecar <file>.url holds the final URL), so relative
  links can be resolved against the address the page was actually served from.
* robots.txt is honoured (Disallow rules and Crawl-delay), following RFC 9309:
  a 4xx robots.txt means "no rules"; an unreachable one (5xx / network error)
  means "fetch nothing".
* 429 and 5xx responses are retried with back-off, honouring Retry-After.
* A descriptive User-Agent is sent.
"""
from __future__ import annotations

import codecs
import hashlib
import re
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

import requests

USER_AGENT = "book-creator/0.1 (personal e-book compiler; respects robots.txt)"
DEFAULT_DELAY = 1.0
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 60.0
_RETRY_STATUS = {429, 500, 502, 503, 504}

# WHATWG: legacy single-byte labels are decoded as windows-1252 by browsers.
_ENCODING_ALIASES = {"iso-8859-1": "cp1252", "latin1": "cp1252", "latin-1": "cp1252",
                     "us-ascii": "cp1252", "ascii": "cp1252", "iso8859-1": "cp1252"}
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.I)
_XML_DECL = re.compile(rb"""^\s*<\?xml[^>]+encoding\s*=\s*["']([A-Za-z0-9._:-]+)""", re.I)


def declared_encoding(data: bytes) -> str | None:
    """Encoding declared in the document itself (BOM, XML declaration or <meta>)."""
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    head = data[:4096]
    m = _XML_DECL.match(head) or _META_CHARSET.search(head)
    if not m:
        return None
    label = m.group(1).decode("ascii", "ignore").lower()
    label = _ENCODING_ALIASES.get(label, label)
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def decode_html(data: bytes) -> str:
    """Decode a web page.

    Strictly valid UTF-8 is accepted first: it is very unlikely to be accidental,
    and many old pages declare ISO-8859-1 while actually serving UTF-8. Otherwise
    the declared charset (e.g. KOI8-R, Shift_JIS) is used, then a statistical guess,
    then windows-1252.
    """
    enc = declared_encoding(data)
    if enc in ("utf-8-sig", "utf-16"):
        return data.decode(enc, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if enc and enc != "utf-8":
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes   # installed with requests
        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except ImportError:
        pass
    return data.decode("cp1252", errors="replace")


class Fetcher:
    def __init__(self, cache_dir: Path, refresh: bool = False, delay: float | None = None,
                 verbose: bool = True, session: requests.Session | None = None):
        self.cache_dir = Path(cache_dir)
        self.refresh = refresh
        self.verbose = verbose
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}
        self._forced_delay = delay

    # ---------------------------------------------------------------- helpers
    def _cache_path(self, url: str) -> Path:
        """cache/<host>/<path>.cache – the suffix keeps /a/x (a file) and /a/x/y
        (which needs x to be a directory) from colliding."""
        parts = urlsplit(url)
        path = parts.path.lstrip("/")
        if not path or path.endswith("/"):
            path += "index"
        if parts.query:
            path += "_" + hashlib.sha1(parts.query.encode()).hexdigest()[:10]
        return self.cache_dir / parts.netloc / (path + ".cache")

    def _legacy_cache_path(self, url: str) -> Path:
        """Cache layout of book-creator <= 0.1 (no suffix); migrated on first read."""
        cp = self._cache_path(url)
        return cp.with_name(cp.name[: -len(".cache")])

    def _robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(root + "/robots.txt", timeout=30)
                if r.status_code >= 500:
                    rp.disallow_all = True           # unreachable: assume complete disallow
                elif r.status_code >= 400:
                    rp.allow_all = True              # no robots.txt: no restrictions
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp.disallow_all = True
            self._robots[root] = rp
        return self._robots[root]

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        rp = self._robots_for(url)
        delay = self._forced_delay
        if delay is None:
            delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*") or DEFAULT_DELAY
        wait = self._last_hit.get(host, 0) + float(delay) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    @staticmethod
    def _retry_after(r: requests.Response, attempt: int) -> float:
        ra = r.headers.get("Retry-After", "")
        if ra.strip().isdigit():
            return min(float(ra), MAX_RETRY_AFTER)
        return 3.0 * (attempt + 1)

    def _download(self, url: str) -> requests.Response:
        for attempt in range(MAX_ATTEMPTS):
            self._throttle(url)
            if self.verbose:
                print(f"  GET {url}")
            try:
                r = self.session.get(url, timeout=60)
            except requests.RequestException:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code in _RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
                time.sleep(self._retry_after(r, attempt))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable")

    # ------------------------------------------------------------------- API
    def get_bytes(self, url: str) -> bytes:
        cp = self._cache_path(url)
        if not self.refresh:
            if cp.is_file():
                return cp.read_bytes()
            legacy = self._legacy_cache_path(url)
            if legacy.is_file():                       # migrate old cache entries in place
                data = legacy.read_bytes()
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_bytes(data)
                legacy.unlink()
                return data
        if not self._robots_for(url).can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url} (or robots.txt is unreachable)")
        r = self._download(url)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(r.content)
        side = cp.with_name(cp.name + ".url")
        if r.url and r.url != url:
            side.write_text(r.url, encoding="utf-8")
        elif side.exists():
            side.unlink()
        return r.content

    def final_url(self, url: str) -> str:
        """The URL a (previously fetched) page was actually served from."""
        side = self._cache_path(url).with_name(self._cache_path(url).name + ".url")
        return side.read_text(encoding="utf-8").strip() if side.is_file() else url

    def get_text(self, url: str) -> str:
        return decode_html(self.get_bytes(url))
