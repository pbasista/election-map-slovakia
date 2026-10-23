"""Cached copies of the web pages the candidate research cites.

A cited page is fetched once (the project's User-Agent, a timeout, a size
cap), sanitized and kept as ``data/curated/cache/<sha256>.html``; ``build``
publishes it as ``cache/<sha256>.html`` next to the link to the original, so
a claim stays checkable when the original changes or disappears.

Sanitizing keeps what a reader needs to check a quote, the text, headings,
lists, tables, links and images, and drops everything active or remote:
scripts, styles, frames, embedded objects, forms and their controls, event
handlers and every other attribute but a few harmless ones. Links become
absolute; images are inlined as ``data:`` URIs, each up to
``cache_image_max_bytes`` (``site.toml``) and together up to
:data:`MAX_IMAGE_BYTES`; an image left out keeps a link to the original.
The copy starts with a banner naming the original URL, the day it was
fetched and, where the original turned the fetch away, the Internet Archive
snapshot it came from instead. Only HTML pages can be cited: other formats
would need a reader of their own, and the quote check needs the text.

The page's language (``<html lang>``) and publication date (article
metadata) are recorded where the page gives them.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import html
import http.client
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser

from election_map_slovakia import fetch
from election_map_slovakia.config import Config

TIMEOUT = 30
MAX_PAGE_BYTES = 8 << 20
MAX_IMAGE_BYTES = 512 << 10
"""Inlined image bytes per page, in document order: an article's own photos
come first, and the thumbnails of other articles that news pages carry by the
dozen would otherwise make every copy megabytes."""
MAX_IMAGES = 20
_ASIDE = frozenset({"nav", "aside", "footer", "header"})
STYLESHEET = "/assets/cache.css"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
_IMAGE_TYPES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
_DROP = frozenset(
    """script style iframe frame frameset object embed noscript template svg
    math canvas video audio select textarea button dialog title""".split()
)
"""Elements dropped with their content. Not ``head``: pages that never close
it would lose their body; what it holds is dropped element by element."""
_KEEP = frozenset(
    """a abbr address article aside b blockquote br caption cite code dd del
    dfn div dl dt em figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img
    ins kbd li main mark nav ol p pre q s section small span strong sub sup
    table tbody td tfoot th thead time tr u ul""".split()
)
"""Elements kept (without most attributes); others give only their content."""
_VOID = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_BLOCK = frozenset(
    """address article aside blockquote br caption dd div dl dt figcaption
    figure footer h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section
    table td th tr ul""".split()
)
_ATTRIBUTES = {
    "a": ("href",),
    "img": ("alt", "width", "height"),
    "td": ("colspan", "rowspan"),
    "th": ("colspan", "rowspan"),
    "time": ("datetime",),
    "ol": ("start",),
}
_GLOBAL_ATTRIBUTES = ("title", "lang", "dir")
_LAZY_SOURCES = ("data-src", "data-lazy-src", "data-original", "src")
_DATE_META = frozenset(
    """article:published_time og:published_time datepublished date pubdate
    publish-date publishdate dc.date dc.date.issued sailthru.date""".split()
)
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_JSON_LD_DATE = re.compile(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})')
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w-]+)""", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
# Typographic variants a quote may use where the page uses another.
_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "«": '"',
        "»": '"',
        "–": "-",
        "—": "-",
        "‐": "-",
        "‑": "-",
        "−": "-",
        "\u00ad": None,
    }
)


class CacheError(Exception):
    """A page cannot be fetched or is not one that can be cited."""


@dataclass(frozen=True)
class Response:
    """One downloaded resource."""

    data: bytes
    content_type: str
    charset: str | None
    url: str
    """After redirects."""


@dataclass(frozen=True)
class Page:
    """A sanitized copy of a web page."""

    url: str
    """The URL cited (not the one redirected to)."""
    html: bytes
    text: str
    """Its visible text, whitespace collapsed, for the quote check."""
    title: str
    language: str
    """Primary language subtag of the page, "" if it names none."""
    published: str
    """YYYY-MM-DD from the page's metadata, "" if it gives none."""
    fetched: str
    """YYYY-MM-DD."""
    via: str
    """The Internet Archive snapshot the copy was made from, "" if from the
    original."""

    @property
    def sha256(self) -> str:
        """Return the hex digest of the copy, its name in the cache."""
        return hashlib.sha256(self.html).hexdigest()


def download(cfg: Config, url: str, limit: int) -> Response:
    """Return the resource at *url*, at most *limit* bytes; raise CacheError."""
    request = urllib.request.Request(
        _uri(url), headers={"User-Agent": fetch.user_agent(cfg.inputs.contact)}
    )
    context = fetch.ssl_context(cfg.inputs.ca_certificates)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as r:
            data = r.read(limit + 1)
            content_type = r.headers.get_content_type()
            charset = r.headers.get_content_charset()
            final = r.geturl()
    except urllib.error.HTTPError as e:
        e.close()
        raise CacheError(f"cannot fetch {url}: HTTP {e.code} {e.reason}") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise CacheError(f"cannot fetch {url}: {e}") from None
    if len(data) > limit:
        raise CacheError(f"{url}: larger than {limit >> 20} MiB")
    if not data:
        raise CacheError(f"{url}: empty ({content_type})")
    return Response(data, content_type, charset, final)


def _uri(url: str) -> str:
    """Return *url* with the characters HTTP does not allow percent-encoded.

    Pages link to files named "big_slávnostné zasadnutie.jpg".
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        parts._replace(
            netloc=parts.netloc.encode("idna").decode("ascii")
            if not parts.netloc.isascii()
            else parts.netloc,
            path=urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~-._"),
            query=urllib.parse.quote(parts.query, safe="/%:@!$&'()*+,;=?~-._"),
        )
    )


def archive(cfg: Config, url: str, fetched: dt.date) -> Page:
    """Fetch *url* and return its sanitized copy; raise CacheError.

    Some news sites turn away every client that does not run their bot
    check's JavaScript (sme.sk answers 403 even to headless Chrome); for
    those the copy comes from the Internet Archive's latest snapshot of the
    page, if it has one, and says so.
    """
    via = ""
    try:
        response = download(cfg, url, MAX_PAGE_BYTES)
    except CacheError as e:
        try:
            snapshot = _snapshot(cfg, url)
        except CacheError as lookup:
            raise CacheError(
                f"{e}; the Internet Archive could not be asked for a snapshot"
                f" ({lookup}); try again later"
            ) from None
        if not snapshot:
            raise CacheError(f"{e}; the Internet Archive has no snapshot") from None
        response, via = download(cfg, snapshot, MAX_PAGE_BYTES), snapshot
    if response.content_type not in ("text/html", "application/xhtml+xml"):
        raise CacheError(
            f"{url}: {response.content_type}, not a web page; only HTML pages"
            " can be cited"
        )
    each = cfg.site.cache_image_max_bytes

    def image(src: str) -> tuple[str, bytes] | None:
        try:
            r = download(cfg, src, each)
        except CacheError:
            return None
        kind = image_type(r.data)
        return (kind, r.data) if kind else None

    # A raw snapshot (id_) keeps the page's own links, relative to the original.
    base = url if via else response.url
    return sanitize(decode(response), url, base, fetched.isoformat(), image, via)


def _snapshot(cfg: Config, url: str) -> str:
    """Return the raw URL of the latest Internet Archive snapshot of *url*.

    "" if it has none; raise CacheError if the archive cannot be asked.

    A failed lookup is not "no snapshot": the archive limits the request
    rate (HTTP 429), and a page turned away for want of a snapshot it has
    would cost a finding.
    """
    query = urllib.parse.urlencode(
        {
            "url": url,
            "filter": "statuscode:200",
            "limit": "-1",  # the latest capture only
            "fl": "timestamp",
            "output": "json",  # "[]" for none; plain text would be empty
        }
    )
    answer = download(cfg, f"{WAYBACK_CDX}?{query}", 1 << 16)
    try:
        rows = json.loads(answer.data)
        # A header row, then the captures.
        return f"https://web.archive.org/web/{rows[-1][0]}id_/{url}" if rows[1:] else ""
    except (ValueError, IndexError, TypeError, KeyError):
        raise CacheError(f"{WAYBACK_CDX}: not a CDX answer") from None


def decode(response: Response) -> str:
    """Return the text of an HTML response.

    The declared charset, else UTF-8, else windows-1250 (what older Slovak
    sites use without saying so).
    """
    declared = response.charset
    if not declared and (m := _CHARSET.search(response.data[:4096])):
        declared = m.group(1).decode("ascii", "replace")
    for charset in filter(None, (declared, "utf-8")):
        try:
            return response.data.decode(charset)
        except (LookupError, UnicodeDecodeError):
            continue
    return response.data.decode("cp1250", "replace")


def image_type(data: bytes) -> str | None:
    """Return the MIME type of a JPEG, PNG, GIF or WebP image, else None.

    By content, not by the server's word: a ``data:`` URI must not carry
    anything a browser would run (SVG may hold scripts, so it is not one).
    """
    for magic, kind in _IMAGE_TYPES.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize(
    markup: str,
    url: str,
    base: str,
    fetched: str,
    image: Callable[[str], tuple[str, bytes] | None],
    via: str = "",
) -> Page:
    """Return the sanitized copy of *markup*; see the module doc.

    *base* is the URL relative links resolve against (where the page was
    fetched from after redirects); *image* returns an image's type and bytes,
    or None to leave it out; *via* is the snapshot the markup came from.
    """
    parser = _Sanitizer(base, image)
    parser.feed(markup)
    parser.close()
    published = parser.published or _json_ld_date(markup)
    title = " ".join(parser.title.split())
    source = (
        f' · <a href="{html.escape(via)}" rel="noopener noreferrer">'
        "Internet Archive</a>"
        if via
        else ""
    )
    banner = (
        '<header class="cache-banner"><p>Kópia stránky · Cached copy · '
        f'<a href="{html.escape(url)}" rel="noopener noreferrer">'
        f"{html.escape(url)}</a> · {fetched}{source}</p></header>"
    )
    head = (
        '<meta charset="utf-8"><meta name="robots" content="noindex, nofollow">'
        f"<title>{html.escape(title or url)}</title>"
        f'<link rel="stylesheet" href="{STYLESHEET}">'
    )
    lang = f' lang="{html.escape(parser.lang)}"' if parser.lang else ""
    document = (
        f"<!doctype html>\n<html{lang}><head>{head}</head><body>{banner}"
        f'<main class="cache-page">{parser.body()}</main></body></html>\n'
    )
    return Page(
        url=url,
        html=document.encode(),
        text=_SPACE.sub(" ", "".join(parser.text)).strip(),
        title=title,
        language=parser.lang.split("-")[0].lower(),
        published=published,
        fetched=fetched,
        via=via,
    )


def normalize(text: str) -> str:
    """Return *text* as the quote check compares it.

    NFKC, typographic quotes and dashes folded, whitespace collapsed, case
    folded.
    """
    text = unicodedata.normalize("NFKC", text).translate(_FOLD)
    return _SPACE.sub(" ", text).strip().casefold()


def _json_ld_date(markup: str) -> str:
    m = _JSON_LD_DATE.search(markup)
    return m.group(1) if m and _valid_date(m.group(1)) else ""


def _valid_date(text: str) -> bool:
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


class _Sanitizer(HTMLParser):
    def __init__(
        self, base: str, image: Callable[[str], tuple[str, bytes] | None]
    ) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.image = image
        self.out: list[str] = []
        self.text: list[str] = []
        self.open: list[str] = []
        self.skip: list[str] = []
        self.in_title = False
        self.title = ""
        self.lang = ""
        self.published = ""
        self.images: dict[str, str | None] = {}
        self.image_bytes = 0

    def body(self) -> str:
        return "".join(self.out) + "".join(f"</{t}>" for t in reversed(self.open))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v or "" for k, v in attrs}
        self._head(tag, a)
        if self.skip:
            if tag == self.skip[-1] and tag not in _VOID:
                self.skip.append(tag)
            return
        if tag in _DROP:
            if tag not in _VOID:
                self.skip.append(tag)
            return
        if tag in _BLOCK:
            self.text.append(" ")
        if tag == "img":
            self._img(a)
            return
        if tag not in _KEEP:
            return
        kept = self._attributes(tag, a)
        self.out.append(f"<{tag}{kept}>")
        if tag not in _VOID:
            self.open.append(tag)

    def _head(self, tag: str, a: dict[str, str]) -> None:
        """Note what the page says about itself (wherever the tag is)."""
        if tag == "html":
            self.lang = self.lang or a.get("lang", "").strip()
        elif tag == "base" and a.get("href"):
            self.base = urllib.parse.urljoin(self.base, a["href"])
        elif tag == "meta":
            self._meta(a)
        elif tag == "title" and not self.title:
            # The page's title; later ones belong to embedded SVG and the like.
            self.in_title = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in _BLOCK:
            self.text.append(" ")
        if tag not in self.open:
            return
        while self.open:
            last = self.open.pop()
            self.out.append(f"</{last}>")
            if last == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
            return
        if self.skip:
            return
        self.out.append(html.escape(data, quote=False))
        self.text.append(data)

    def _meta(self, a: dict[str, str]) -> None:
        key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
        if self.published or key not in _DATE_META:
            return
        m = _DATE.search(a.get("content", ""))
        if m and _valid_date(m.group(0)):
            self.published = m.group(0)

    def _attributes(self, tag: str, a: dict[str, str]) -> str:
        out = []
        for name in (*_GLOBAL_ATTRIBUTES, *_ATTRIBUTES.get(tag, ())):
            value = a.get(name)
            if value is None:
                continue
            if name == "href":
                value = self._link(value)
                if not value:
                    continue
            out.append(f' {name}="{html.escape(value)}"')
        if tag == "a" and "href" in a:
            out.append(' rel="noopener noreferrer"')
        return "".join(out)

    def _link(self, href: str) -> str:
        href = href.strip()
        if not href or href.startswith("#"):
            return ""
        absolute = urllib.parse.urljoin(self.base, href)
        scheme = urllib.parse.urlsplit(absolute).scheme
        return absolute if scheme in ("http", "https", "mailto") else ""

    def _img(self, a: dict[str, str]) -> None:
        src = next(
            (
                a[k].strip()
                for k in _LAZY_SOURCES
                if a.get(k, "").strip() and not a[k].strip().startswith("data:")
            ),
            "",
        )
        if not src and a.get("srcset"):
            src = a["srcset"].split(",")[0].strip().split(" ")[0]
        link = self._link(src) if src else ""
        if not link.startswith(("http://", "https://")):
            return
        alt = a.get("alt", "").strip()
        # Images in navigation, sidebars and footers are other articles'
        # thumbnails and logos; only their links are kept.
        inline = None if _ASIDE & set(self.open) else self._inline(link)
        if inline is None:
            label = html.escape(alt or link.rsplit("/", 1)[-1] or "image")
            self.out.append(
                f'<a href="{html.escape(link)}" rel="noopener noreferrer">[{label}]</a>'
            )
            return
        kept = self._attributes("img", a)
        self.out.append(f'<img src="{inline}"{kept}>')

    def _inline(self, link: str) -> str | None:
        if link in self.images:
            return self.images[link]
        result = None
        if len(self.images) < MAX_IMAGES and self.image_bytes < MAX_IMAGE_BYTES:
            got = self.image(link)
            if got and self.image_bytes + len(got[1]) <= MAX_IMAGE_BYTES:
                self.image_bytes += len(got[1])
                result = f"data:{got[0]};base64,{base64.b64encode(got[1]).decode()}"
        self.images[link] = result
        return result
