import datetime as dt
from pathlib import Path

import pytest

from election_map_slovakia import cache, config, research, sources

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def allow() -> config.Sources:
    return config.load(REPO / "config").sources


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://korzar.sme.sk/c/123/clanok.html", "media-sk"),
        ("https://www.michalovce.sk/uradna-tabula", "official"),
        ("https://www.vucke.sk/sk/", "official"),
        # A look-alike domain is not a subdomain.
        ("https://notsme.sk/a", None),
        ("https://sme.sk.example.com/a", None),
        # User-generated sections.
        ("https://blog.sme.sk/autor/clanok", None),
        ("https://www.aktuality.sk/diskusia/750339/x/", None),
        ("https://www.pravda.sk/blog/x", None),
        ("ftp://sme.sk/a", None),
    ],
)
def test_allowlist(allow: config.Sources, url: str, expected: str | None):
    assert sources.category(url, allow) == expected


def test_blocklist_overrides_allowlist(allow: config.Sources):
    blocked = next(iter(sorted(allow.blocklist)))
    widened = config.Sources(
        **{**allow.__dict__, "categories": {**allow.categories, "x": (blocked,)}}
    )
    assert sources.category(f"https://www.{blocked}/a", widened) is None


TEXT = cache.normalize(
    "Primátor Miroslav Dufinec (Smer – sociálna demokracia) obhájil post. "
    "Podľa polície „ide o podozrenie“, uviedol hovorca. Starostka Nováková "
    "Kováčová potvrdila…"
)


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        # Typographic dashes, quotes and case need not match.
        ("primátor miroslav dufinec (smer - sociálna demokracia)", True),
        ('Podľa polície "ide o podozrenie", uviedol hovorca.', True),
        # An ellipsis joins parts in page order, not out of it.
        ("Primátor Miroslav Dufinec … uviedol hovorca.", True),
        ("uviedol hovorca … Primátor Miroslav Dufinec", False),
        # A changed word is a paraphrase.
        ("Primátor Miroslav Dufinec obhájil funkciu.", False),
    ],
)
def test_quote_check(quote: str, found: bool):
    assert research.quote_found(quote, TEXT) is found


@pytest.mark.parametrize(
    ("first", "surname", "named"),
    [
        ("Miroslav", "Dufinec", True),
        # Slovak declension: the page may say "Dufinca", "Novákovej".
        ("Miroslava", "Dufinca", True),
        ("Jana", "Nováková", True),
        # Results tables drop accents.
        ("Dominik", "Táncoš", True),
        ("Ján", "Kováč", False),
    ],
)
def test_page_names_person(first: str, surname: str, named: bool):
    text = cache.normalize(
        "Primátora Miroslava Dufinca a Janu Novákovú privítali. Zvolený: Dominik Tancoš"
    )
    assert research.names_person(text, first, surname) is named


def test_named_persons_keep_their_order_and_unknown_ones_fail():
    cfg = config.load(REPO / "config")
    data = {
        "persons": [{"id": "aaaaaaaaaaaa"}, {"id": "bbbbbbbbbbbb"}],
        "candidacies": [],
        "contests": [],
    }
    only = ["person:bbbbbbbbbbbb", "person:aaaaaaaaaaaa", "person:bbbbbbbbbbbb"]
    assert research.selected_persons(cfg, data, only) == [
        "bbbbbbbbbbbb",
        "aaaaaaaaaaaa",
    ]
    with pytest.raises(research.jobs.JobError, match="cccccccccccc"):
        research.selected_persons(cfg, data, ["person:cccccccccccc"])


def test_sanitized_copy_runs_nothing_and_loads_nothing_remote():
    markup = """<html lang="sk"><head><title>Článok</title>
    <meta property="article:published_time" content="2026-09-04T19:29:00+02:00">
    <script>alert(1)</script><link rel="stylesheet" href="https://x.example/s.css">
    </head><body onload="alert(2)"><p style="color:red" onclick="alert(3)">Text
    <a href="javascript:alert(4)">zlý</a> <a href="/iny">dobrý</a></p>
    <iframe src="https://x.example/f"></iframe><img src="https://x.example/a.svg" alt="foto">
    <img src="https://x.example/b.jpg"><svg><script>alert(5)</script></svg></body></html>"""
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 10

    def image(src: str) -> tuple[str, bytes] | None:
        data = jpeg if src.endswith(".jpg") else b"<svg onload=alert(6)>"
        kind = cache.image_type(data)
        return (kind, data) if kind else None

    page = cache.sanitize(
        markup, "https://www.sme.sk/c/1", "https://www.sme.sk/c/1", "2026-10-20", image
    )
    copy = page.html.decode()
    assert "alert" not in copy
    assert "x.example/s.css" not in copy and "<iframe" not in copy
    assert 'href="https://www.sme.sk/iny"' in copy
    # The SVG is not inlined (it could run script); it stays a link.
    assert 'href="https://x.example/a.svg"' in copy
    assert "data:image/jpeg;base64," in copy
    assert page.title == "Článok" and page.language == "sk"
    assert page.published == "2026-09-04"
    assert "Text zlý dobrý" in page.text


@pytest.mark.parametrize(
    ("cdx", "outcome"),
    [
        # The archive is asked too often: the page is not "without snapshot".
        (cache.CacheError("cannot fetch …: HTTP 429 Too Many Requests"), "try again"),
        (b"[]", "has no snapshot"),
        (b'[["timestamp"], ["20240201202642"]]', "copied"),
    ],
)
def test_page_turned_away_comes_from_the_archive(
    monkeypatch: pytest.MonkeyPatch, cdx: Exception | bytes, outcome: str
):
    url = "https://korzar.sme.sk/c/1/clanok.html"
    snapshot = f"https://web.archive.org/web/20240201202642id_/{url}"

    def download(_cfg: config.Config, src: str, _limit: int) -> cache.Response:
        if src.startswith(cache.WAYBACK_CDX):
            if isinstance(cdx, Exception):
                raise cdx
            return cache.Response(cdx, "application/json", None, src)
        if src == snapshot:
            body = "<html><body><p>Ján Novák z Michaloviec</p></body></html>"
            return cache.Response(body.encode(), "text/html", "utf-8", src)
        raise cache.CacheError(f"cannot fetch {src}: HTTP 403 Forbidden")

    monkeypatch.setattr(cache, "download", download)
    cfg = config.load(REPO / "config")
    fetched = dt.date(2026, 10, 22)
    if outcome == "copied":
        page = cache.archive(cfg, url, fetched)
        assert page.via == snapshot and page.url == url
        assert "Ján Novák z Michaloviec" in page.text
    else:
        with pytest.raises(cache.CacheError, match=outcome):
            cache.archive(cfg, url, fetched)
