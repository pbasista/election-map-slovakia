"""Captures of the Common Crawl, a web archive beside the Internet Archive.

The Common Crawl (https://commoncrawl.org) crawls the web every month or
two and publishes every capture in WARC files, with an index per crawl. A
municipality's document gone from its website that the Internet Archive
never captured may be in one of them (the regional elections of 2017: the
crawl of October 2017 holds election pages and files of many municipal
websites).

A capture is cited by the index server's query for it (:func:`capture`,
:func:`capture_url`)::

    https://index.commoncrawl.org/CC-MAIN-2017-43-index?url=<original URL>&from=<timestamp>&to=<timestamp>&output=json

a real URL that lists the capture where the server answers, and names the
crawl, the original URL and the time of the capture, as an Internet Archive
snapshot URL does. The server is often overloaded, so :func:`fetch` does
without it: it finds the capture in the crawl's own index on
data.commoncrawl.org, ``cluster.idx`` (one line per block of the sorted CDX
files: its first SURT key, file, offset and length) by binary search in
HTTP ranges, reads the block, and fetches the capture's WARC record by its
range; the payload is the HTTP response's body, de-chunked and unzipped as
served. A record the crawler cut short (``WARC-Truncated``, at 1 MiB in
these years) is no document.

:func:`captures` lists the captures of a website in a crawl the same way,
for finding documents (``ems job captures``).
"""

from __future__ import annotations

import gzip
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterator
from typing import NamedTuple

INDEX = "https://index.commoncrawl.org"
DATA = "https://data.commoncrawl.org"
CAPTURE = re.compile(
    r"https?://index\.commoncrawl\.org/(CC-MAIN-\d{4}-\d{2})-index\?(.+)"
)
"""A capture's URL (:func:`capture`): the crawl and the query."""
_CLUSTER_FIELDS = 4
"""Tab-separated fields of a ``cluster.idx`` line: key and time, file, offset,
length (a block number may follow)."""
MAX_BLOCKS = 6
"""Blocks of the index read in search of one capture: the one its key falls in
and the next ones whose first key is no later (one URL captured many times
fills several)."""
_LINE = 1 << 13
"""Bytes read at a time from ``cluster.idx``; its lines are far shorter."""

Ranges = Callable[[str, int, int], tuple[bytes, int]]
"""Reads bytes *start*..*end* (inclusive) of the file at a URL; returns them
and the file's whole size (from ``Content-Range``)."""


class CommonCrawlError(Exception):
    """A capture that cannot be had: not in the index, cut short, not a page."""


class Capture(NamedTuple):
    """A Common Crawl capture, as its URL names it."""

    crawl: str
    stamp: str
    """Its time, ``YYYYMMDDhhmmss``."""
    original: str
    """The URL it is a copy of."""


def capture(url: str) -> Capture | None:
    """Return capture *url* (:data:`CAPTURE`) taken apart, or None if not one.

    Its query has the original ``url`` and ``from`` and ``to`` the same full
    timestamp: one capture, not a range.
    """
    m = CAPTURE.fullmatch(url)
    if m is None:
        return None
    query = dict(urllib.parse.parse_qsl(m.group(2), keep_blank_values=True))
    stamp, original = query.get("from", ""), query.get("url", "")
    if not re.fullmatch(r"\d{14}", stamp) or query.get("to") != stamp or not original:
        return None
    if not re.match(r"https?://", original):
        return None
    return Capture(m.group(1), stamp, original)


def capture_url(crawl: str, original: str, stamp: str) -> str:
    """Return the URL that cites the capture of *original* at *stamp* in *crawl*."""
    query = urllib.parse.urlencode(
        {"url": original, "from": stamp, "to": stamp, "output": "json"}, safe=":/"
    )
    return f"{INDEX}/{crawl}-index?{query}"


def surt_host(url: str) -> str:
    """Return the start of the SURT keys of *url*'s website: ``sk,obec)``.

    As the Common Crawl's index writes them: the host's labels reversed,
    without a leading ``www``, a port only where not the scheme's own.
    """
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    host = re.sub(r"^www\d*\.", "", host)
    key = ",".join(reversed(host.split(".")))
    default = {"http": 80, "https": 443}.get(parts.scheme)
    if parts.port and parts.port != default:
        key += f":{parts.port}"
    return key + ")"


def surt(url: str) -> str:
    """Return about the SURT key of *url*: :func:`surt_host`, path and query.

    Lowercased, the query's parameters sorted, as the index sorts them; the
    search only needs it near the true key (:func:`_blocks`).
    """
    parts = urllib.parse.urlsplit(_quoted(url))
    query = "&".join(sorted(parts.query.split("&"))) if parts.query else ""
    path = parts.path or "/"
    return (surt_host(url) + path + (f"?{query}" if query else "")).lower()


def _quoted(url: str) -> str:
    """Return *url* percent-encoded where agents copy it with spaces, diacritics."""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def _line_after(ranges: Ranges, url: str, pos: int) -> tuple[int, str, int]:
    """Return the start of the first whole line after *pos*, the line, the size."""
    data, total = ranges(url, pos, pos + _LINE - 1)
    start = 0 if pos == 0 else data.find(b"\n") + 1
    if pos and start == 0:
        return total, "", total
    end = data.find(b"\n", start)
    if end < 0:
        data, total = ranges(url, pos + start, pos + start + 16 * _LINE - 1)
        start, pos, end = 0, pos + start, data.find(b"\n")
        if end < 0:
            end = len(data)
    return pos + start, data[start:end].decode("utf-8", "replace"), total


def _blocks(ranges: Ranges, crawl: str, key: str) -> Iterator[tuple[str, list[str]]]:
    """Yield the ``cluster.idx`` lines of *crawl* from the block holding *key* on.

    Each as its first SURT key and its fields (file, offset, length); the
    caller stops when it has read far enough.
    """
    url = f"{DATA}/cc-index/collections/{crawl}/indexes/cluster.idx"
    _, total = ranges(url, 0, 0)
    lo, hi = 0, total
    while hi - lo > _LINE:
        mid = (lo + hi) // 2
        _, line, _ = _line_after(ranges, url, mid)
        if line and line.split(" ", 1)[0] < key:
            lo = mid
        else:
            hi = mid
    previous: tuple[str, list[str]] | None = None
    rest, pos = b"", lo
    while pos < total:
        data, _ = ranges(url, pos, min(pos + 8 * _LINE, total) - 1)
        lines = (rest + data).split(b"\n")
        if pos == lo and lo:
            lines = lines[1:]  # the line cut at lo
        pos += len(data)
        rest = lines.pop() if pos < total else b""
        for line in lines:
            fields = line.decode("utf-8", "replace").split("\t")
            if len(fields) < _CLUSTER_FIELDS:
                continue
            block = (fields[0].split(" ", 1)[0], fields[1:])
            if block[0] < key:
                previous = block
                continue
            if previous is not None:
                yield previous
                previous = None
            yield block
    if previous is not None:
        yield previous


def _cdx(
    ranges: Ranges, crawl: str, block: list[str]
) -> Iterator[tuple[str, str, dict]]:
    """Yield the key, timestamp and fields of each capture in index *block*."""
    name, offset, length = block[0], int(block[1]), int(block[2])
    url = f"{DATA}/cc-index/collections/{crawl}/indexes/{name}"
    data, _ = ranges(url, offset, offset + length - 1)
    for line in gzip.decompress(data).decode("utf-8", "replace").splitlines():
        key, stamp, fields = line.split(" ", 2)
        yield key, stamp, json.loads(fields)


def locate(ranges: Ranges, c: Capture) -> dict:
    """Return the index fields (``filename``, ``offset``, ``length``…) of *c*.

    Reads the block its key falls in and the next ones whose first key is no
    later, at most :data:`MAX_BLOCKS`. Raises CommonCrawlError if the
    crawl's index has no such capture.
    """
    wanted, key = _quoted(c.original), surt(c.original)
    for n, (first, block) in enumerate(_blocks(ranges, c.crawl, key)):
        if n >= MAX_BLOCKS or (n and first > key):
            break
        for _, stamp, fields in _cdx(ranges, c.crawl, block):
            if stamp == c.stamp and _quoted(fields.get("url", "")) == wanted:
                return fields
    raise CommonCrawlError(f"{c.crawl} has no capture of {c.original} at {c.stamp}")


def captures(ranges: Ranges, crawl: str, site: str) -> Iterator[tuple[str, dict]]:
    """Yield the timestamp and index fields of every capture of website *site*.

    *site* is a URL or a host (``obec.sk``); its subdomains are not included.
    """
    host = surt_host(site if "//" in site else f"http://{site}")
    for n, (first, block) in enumerate(_blocks(ranges, crawl, host)):
        if n and first > host and not first.startswith(host):
            return
        for key, stamp, fields in _cdx(ranges, crawl, block):
            if key.startswith(host + "/") or key == host:
                yield stamp, fields


def crawls(ranges: Ranges, years: range) -> list[str]:
    """Return the crawls of *years*, oldest first, by asking for their indexes.

    A crawl is named by its year and week; the weeks without one answer
    403 or 404 (the index server's list of crawls needs the server). The
    host answers 403 to everything while it throttles a client, so finding
    no crawl where some answered 403 is an error, not an empty list.
    """
    found, refused = [], False
    for year in years:
        for week in range(1, 54):
            crawl = f"CC-MAIN-{year}-{week:02d}"
            try:
                ranges(f"{DATA}/cc-index/collections/{crawl}/indexes/cluster.idx", 0, 0)
            except urllib.error.HTTPError as e:
                if e.code in (403, 404):
                    refused |= e.code == 403  # noqa: PLR2004
                    continue
                raise
            found.append(crawl)
    if not found and refused:
        raise CommonCrawlError(
            f"{DATA} refused every crawl of {years.start}-{years.stop - 1} (HTTP 403:"
            " it throttles clients that ask too much); try again later"
        )
    return found


def http_ranges(
    user_agent: str, context: ssl.SSLContext | None, timeout: float
) -> Ranges:
    """Return a :data:`Ranges` over HTTP with *user_agent*, TLS *context*, *timeout*."""

    def ranges(url: str, start: int, end: int) -> tuple[bytes, int]:
        request = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Range": f"bytes={start}-{end}"}
        )
        with urllib.request.urlopen(request, timeout=timeout, context=context) as r:
            data = r.read(end - start + 1)
            whole = r.headers.get("Content-Range", "").rpartition("/")[2]
        return data, int(whole) if whole.isdigit() else start + len(data)

    return ranges


def record(ranges: Ranges, fields: dict, limit: int) -> tuple[dict[str, str], bytes]:
    """Return the WARC headers and the HTTP body of the capture at index *fields*.

    Raises CommonCrawlError if it is not a whole HTTP 200 response of at most
    *limit* bytes.
    """
    url = f"{DATA}/{fields['filename']}"
    offset, length = int(fields["offset"]), int(fields["length"])
    data, _ = ranges(url, offset, offset + length - 1)
    try:
        data = gzip.decompress(data)
    except (OSError, EOFError) as e:
        raise CommonCrawlError(f"{url} at {offset}: not a WARC record ({e})") from None
    head, _, rest = data.partition(b"\r\n\r\n")
    warc = _headers(head)
    if warc.get("warc-type") != "response":
        raise CommonCrawlError(f"{fields.get('url')}: not a response record")
    if warc.get("warc-truncated"):
        raise CommonCrawlError(
            f"{fields.get('url')}: the crawler cut the capture short"
            f" ({warc['warc-truncated']})"
        )
    # The record's block ends at its Content-Length; two CRLF follow.
    size = warc.get("content-length", "")
    if size.isdigit():
        rest = rest[: int(size)]
    status, _, body = rest.partition(b"\r\n\r\n")
    status_line, _, _ = status.partition(b"\r\n")
    if b" 200" not in status_line[:13]:
        raise CommonCrawlError(f"{fields.get('url')}: {status_line.decode('latin-1')}")
    http = _headers(status)
    if "chunked" in http.get("transfer-encoding", "").lower():
        body = _dechunk(body)
    if http.get("content-encoding", "").lower() in ("gzip", "x-gzip", "deflate"):
        try:
            body = zlib.decompress(body, zlib.MAX_WBITS | 32)
        except zlib.error:
            pass  # the crawler stored it decoded already
    if len(body) > limit:
        raise CommonCrawlError(f"{fields.get('url')}: larger than {limit >> 20} MiB")
    return warc, body


def fetch(ranges: Ranges, url: str, limit: int) -> bytes:
    """Return the document that capture *url* (:func:`capture`) holds.

    Raises CommonCrawlError where it cannot be had, ValueError if *url* is
    not a capture.
    """
    c = capture(url)
    if c is None:
        raise ValueError(f"not a Common Crawl capture: {url}")
    _, body = record(ranges, locate(ranges, c), limit)
    return body


def _headers(block: bytes) -> dict[str, str]:
    """Return the headers of a WARC or HTTP header *block*, names lowercased."""
    headers = {}
    for line in block.decode("latin-1").split("\r\n")[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers


def _dechunk(body: bytes) -> bytes:
    """Return *body* without its HTTP chunked transfer coding, as far as it is."""
    out, rest = [], body
    while rest:
        size, sep, rest = rest.partition(b"\r\n")
        try:
            n = int(size.split(b";")[0], 16)
        except ValueError:
            return body  # not chunked after all
        if not sep or n == 0:
            break
        out.append(rest[:n])
        rest = rest[n + 2 :]
    return b"".join(out)
