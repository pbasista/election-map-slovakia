import datetime as dt
import gzip
import json
import urllib.error
from pathlib import Path

import pytest

from election_map_slovakia import commoncrawl, config, obvodrules

_CFG = config.load(Path(__file__).resolve().parent.parent / "config")
_EARLIER = _CFG.election("2017")

CRAWL = "CC-MAIN-2017-43"
INDEXES = f"{commoncrawl.DATA}/cc-index/collections/{CRAWL}/indexes/"
WARC = "crawl-data/CC-MAIN-2017-43/segments/1/warc/a.warc.gz"
PDF = b"%PDF-1.5 the okrsky"
ORIGINAL = "http://www.obec.sk/download_file_f.php?id=868136"
STAMP = "20171019141751"


def _record(url: str, body: bytes, http: str = "", warc: str = "") -> bytes:
    """A gzipped WARC response record of *body* served for *url*."""
    response = (
        "HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n" + http + "\r\n"
    ).encode() + body
    head = (
        "WARC/1.0\r\nWARC-Type: response\r\n"
        f"WARC-Target-URI: {url}\r\n{warc}"
        f"Content-Length: {len(response)}\r\n\r\n"
    ).encode()
    return gzip.compress(head + response + b"\r\n\r\n")


class Files:
    """data.commoncrawl.org in memory: one crawl's index and a WARC file."""

    def __init__(self, captures: list[tuple[str, str, str, bytes]]):
        """*captures*: SURT key, timestamp, URL and the record of each, sorted.

        Two captures per index block, so a search must find the right one.
        """
        # Many blocks of other websites before and after, as in a real index.
        filler = gzip.compress(b'ar,a)/ 2017 {"url": "http://a.ar/"}\n')
        warc, blocks, cluster, cdx = b"", [], [], filler
        for i in range(0, len(captures), 2):
            lines = []
            for key, stamp, url, rec in captures[i : i + 2]:
                fields = {"url": url, "status": "200", "mime": "application/pdf"}
                fields |= {
                    "filename": WARC,
                    "offset": str(len(warc)),
                    "length": str(len(rec)),
                }
                lines.append(f"{key} {stamp} {json.dumps(fields)}")
                warc += rec
            blocks.append(gzip.compress(("\n".join(lines) + "\n").encode()))
        for n, block in enumerate(blocks):
            key, stamp = captures[2 * n][:2]
            cluster.append(
                f"{key} {stamp}\tcdx-00000.gz\t{len(cdx)}\t{len(block)}\t{n + 1}"
            )
            cdx += block
        other = f"\tcdx-00000.gz\t0\t{len(filler)}\t0"
        before = [f"ar,a{n:05d})/ 2017{other}" for n in range(3000)]
        after = [f"uk,z{n:05d})/ 2017{other}" for n in range(3000)]
        self.files = {
            INDEXES + "cluster.idx": (
                "\n".join(before + cluster + after) + "\n"
            ).encode(),
            INDEXES + "cdx-00000.gz": cdx,
            f"{commoncrawl.DATA}/{WARC}": warc,
        }
        self.requests = 0

    def __call__(self, url: str, start: int, end: int) -> tuple[bytes, int]:
        self.requests += 1
        if url not in self.files:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]
        data = self.files[url]
        return data[start : end + 1], len(data)


def _site(*extra: tuple[str, str, str, bytes]) -> Files:
    captures = [
        (
            "sk,obec)/",
            "20171019141700",
            "http://www.obec.sk/",
            _record("http://www.obec.sk/", b"<html>"),
        ),
        (
            "sk,obec)/download_file_f.php?id=868135",
            STAMP,
            ORIGINAL[:-1] + "5",
            _record("x", b"other"),
        ),
        (
            "sk,obec)/download_file_f.php?id=868136",
            "20171012000000",
            ORIGINAL,
            _record(ORIGINAL, b"older"),
        ),
        (
            "sk,obec)/download_file_f.php?id=868136",
            STAMP,
            ORIGINAL,
            _record(ORIGINAL, PDF),
        ),
        (
            "sk,obec)/volby",
            "20171019141800",
            "http://obec.sk/volby",
            _record("y", b"<html>"),
        ),
        ("sk,obecny)/", "20171019141900", "http://obecny.sk/", _record("z", b"<html>")),
        *extra,
    ]
    return Files(sorted(captures))


def test_capture_url_round_trip():
    url = commoncrawl.capture_url(CRAWL, ORIGINAL, STAMP)
    assert url.startswith("https://index.commoncrawl.org/CC-MAIN-2017-43-index?url=")
    assert commoncrawl.capture(url) == commoncrawl.Capture(CRAWL, STAMP, ORIGINAL)
    # It stands for the page it copies, captured that day.
    s = obvodrules.snapshot(url)
    assert s is not None and s.day == dt.date(2017, 10, 19) and s.original == ORIGINAL
    assert obvodrules.original_url(url) == ORIGINAL


@pytest.mark.parametrize(
    "url",
    [
        # A range of time, not one capture.
        f"https://index.commoncrawl.org/{CRAWL}-index?url={ORIGINAL}&from=2017&to=2018",
        f"https://index.commoncrawl.org/{CRAWL}-index?url={ORIGINAL}&from={STAMP}",
        f"https://index.commoncrawl.org/{CRAWL}-index?from={STAMP}&to={STAMP}",
        f"https://index.commoncrawl.org/{CRAWL}-index?url=obec.sk&from={STAMP}&to={STAMP}",
        f"https://index.commoncrawl.org/collinfo.json?url={ORIGINAL}&from={STAMP}&to={STAMP}",
    ],
)
def test_not_a_capture(url: str):
    assert commoncrawl.capture(url) is None


def test_capture_of_the_official_website_is_official():
    url = commoncrawl.capture_url(CRAWL, "http://www.pezinok.sk/u.pdf", STAMP)
    assert (
        obvodrules.official_problems("Pezinok", "https://www.pezinok.sk/", [url]) == []
    )
    other = commoncrawl.capture_url(CRAWL, "http://www.sme.sk/u.pdf", STAMP)
    assert obvodrules.official_problems("Pezinok", "https://www.pezinok.sk/", [other])


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("http://www.obec.sk/", "sk,obec)/"),
        ("https://obec.sk:8080/A b.pdf", "sk,obec:8080)/a%20b.pdf"),
        ("http://www.obec.sk/x.php?b=2&a=1", "sk,obec)/x.php?a=1&b=2"),
        ("http://mesto.obec.sk", "sk,obec,mesto)/"),
    ],
)
def test_surt(url: str, key: str):
    assert commoncrawl.surt(url) == key


def test_fetch_finds_the_capture_of_its_time():
    files = _site()
    url = commoncrawl.capture_url(CRAWL, ORIGINAL, STAMP)
    assert commoncrawl.fetch(files, url, 1 << 20) == PDF
    # A binary search, not a read of the whole index.
    assert files.requests < 40


def test_fetch_takes_off_transfer_and_content_codings():
    body = gzip.compress(PDF)
    chunked = b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body)
    http = "Transfer-Encoding: chunked\r\nContent-Encoding: gzip\r\n"
    rec = _record(ORIGINAL, chunked, http=http)
    files = Files([("sk,obec)/download_file_f.php?id=868136", STAMP, ORIGINAL, rec)])
    url = commoncrawl.capture_url(CRAWL, ORIGINAL, STAMP)
    assert commoncrawl.fetch(files, url, 1 << 20) == PDF


def test_fetch_refuses_what_is_not_a_whole_document():
    url = commoncrawl.capture_url(CRAWL, ORIGINAL, STAMP)
    key = "sk,obec)/download_file_f.php?id=868136"
    cut = _record(ORIGINAL, PDF, warc="WARC-Truncated: length\r\n")
    with pytest.raises(commoncrawl.CommonCrawlError, match="cut the capture short"):
        commoncrawl.fetch(Files([(key, STAMP, ORIGINAL, cut)]), url, 1 << 20)
    whole = _record(ORIGINAL, PDF)
    with pytest.raises(commoncrawl.CommonCrawlError, match="larger than"):
        commoncrawl.fetch(Files([(key, STAMP, ORIGINAL, whole)]), url, 4)
    with pytest.raises(commoncrawl.CommonCrawlError, match="has no capture"):
        missing = commoncrawl.capture_url(CRAWL, ORIGINAL, "20171019000000")
        commoncrawl.fetch(_site(), missing, 1 << 20)


def test_captures_lists_one_website():
    files = _site()
    urls = [f["url"] for _, f in commoncrawl.captures(files, CRAWL, "obec.sk")]
    assert sorted(urls) == sorted(
        [
            "http://www.obec.sk/",
            ORIGINAL[:-1] + "5",
            ORIGINAL,
            ORIGINAL,
            "http://obec.sk/volby",
        ]
    )


def test_crawls_are_found_by_their_indexes():
    files = _site()
    assert commoncrawl.crawls(files, range(2017, 2018)) == [CRAWL]


def test_a_capture_dates_documents():
    captured = commoncrawl.capture_url(CRAWL, "https://obec.sk/volby-2017", STAMP)
    out = {
        "documents": [{"url": "https://obec.sk/u.pdf", "title": "t"}],
        "date_approximate": "archived",
        "date_basis": "b",
        "date_seen": "2017-10-19",
        "date_source": captured,
    }
    assert obvodrules.dating_problems(_CFG, _EARLIER, out, dt.date(2017, 11, 4)) == []
    late = out | {"date_seen": "2017-10-20"}
    assert obvodrules.dating_problems(_CFG, _EARLIER, late, dt.date(2017, 11, 4))


def test_a_throttled_host_is_no_empty_listing():
    def refused(url: str, start: int, end: int) -> tuple[bytes, int]:
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)  # type: ignore[arg-type]

    with pytest.raises(commoncrawl.CommonCrawlError, match="403"):
        commoncrawl.crawls(refused, range(2017, 2018))
