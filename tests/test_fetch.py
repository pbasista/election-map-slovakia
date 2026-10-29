import datetime as dt
import hashlib
import io
import json
import re
import threading
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from election_map_slovakia import fetch, store
from election_map_slovakia.config import Input, Inputs, Store

HEADER = "IDENTIFIKATOR;KRAJ;OBEC;ADRBOD_X;ADRBOD_Y"


@dataclass
class Resource:
    body: bytes
    etag: str | None = None


@dataclass
class Stub:
    base: str
    resources: dict[str, Resource] = field(default_factory=dict)
    statuses: list[int] = field(default_factory=list)
    conditional: list[bool] = field(default_factory=list)


@pytest.fixture
def stub() -> Iterator[Stub]:
    state: Stub

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            res = state.resources.get(self.path)
            if res is None:
                state.statuses.append(404)
                self.send_error(404)
                return
            match = res.etag is not None and self.headers["If-None-Match"] == res.etag
            state.conditional.append(self.headers["If-None-Match"] is not None)
            state.statuses.append(304 if match else 200)
            if match:
                self.send_response(304)
                self.end_headers()
                return
            self.send_response(200)
            if res.etag:
                self.send_header("ETag", res.etag)
            self.send_header("Content-Length", str(len(res.body)))
            self.end_headers()
            self.wfile.write(res.body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state = Stub(f"http://127.0.0.1:{server.server_port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()


def make_input(stub: Stub, name: str, kind: str, **kw) -> Input:
    defaults = {
        "members": (),
        "expect": "",
        "volatile": None,
        "sha256": "",
        "optional": False,
    }
    defaults.update(kw)
    return Input(name, f"{stub.base}/{name}", f"{name}.{kind}", kind, **defaults)


@dataclass(frozen=True)
class StubStore(Store):
    """The input store, served by the stub below /store/."""

    base: str = ""

    def url(self, inp: Input) -> str:
        return f"{self.base}/store/{self.asset(inp)}"


def run(
    tmp_path: Path,
    *inputs: Input,
    force: bool = False,
    store: Store | None = None,
) -> dict[str, fetch.Outcome]:
    cfg = Inputs("test@example.org", (), inputs, store)
    outcomes = fetch.fetch(cfg, tmp_path, force=force)
    return {o.name: o for o in outcomes}


def csv_body(rows: int) -> bytes:
    lines = [HEADER] + [f"{i};Bratislavský;Ružinov;-1;-2" for i in range(rows)]
    return ("\n".join(lines) + "\n").encode()


def manifest(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "manifest.json").read_text())["inputs"]


def test_etag_turns_second_run_into_not_modified(stub: Stub, tmp_path: Path):
    stub.resources["/a"] = Resource(b"%PDF-1.7 one", etag='"v1"')
    inp = make_input(stub, "a", "pdf")

    assert run(tmp_path, inp)["a"].status == "new"
    assert run(tmp_path, inp)["a"].status == "unchanged"
    assert stub.statuses == [200, 304]
    assert stub.conditional == [False, True]

    stub.resources["/a"] = Resource(b"%PDF-1.7 two", etag='"v2"')
    assert run(tmp_path, inp)["a"].status == "updated"
    assert (tmp_path / "a" / "a.pdf").read_bytes() == b"%PDF-1.7 two"
    assert manifest(tmp_path)["a"]["etag"] == '"v2"'


def test_force_skips_the_conditional_request(stub: Stub, tmp_path: Path):
    stub.resources["/a"] = Resource(b"%PDF-1.7", etag='"v1"')
    inp = make_input(stub, "a", "pdf")
    run(tmp_path, inp)
    assert run(tmp_path, inp, force=True)["a"].status == "unchanged"
    assert stub.conditional == [False, False]


def test_same_content_without_validators_keeps_the_file(stub: Stub, tmp_path: Path):
    stub.resources["/a"] = Resource(b"%PDF-1.7")
    inp = make_input(stub, "a", "pdf")
    run(tmp_path, inp)
    target = tmp_path / "a" / "a.pdf"
    inode = target.stat().st_ino
    first = manifest(tmp_path)["a"]["retrieved_at"]

    assert run(tmp_path, inp)["a"].status == "unchanged"
    assert target.stat().st_ino == inode
    assert manifest(tmp_path)["a"]["retrieved_at"] == first
    assert list((tmp_path / "a").iterdir()) == [target]


def test_volatile_difference_is_not_a_change(stub: Stub, tmp_path: Path):
    volatile = re.compile(rb"\(HA\d+\)")
    inp = make_input(stub, "n", "html", expect="obvod", volatile=volatile)
    stub.resources["/n"] = Resource("<p>obvod</p>(HA1)".encode())
    run(tmp_path, inp)
    stub.resources["/n"] = Resource("<p>obvod</p>(HA2)".encode())
    assert run(tmp_path, inp)["n"].status == "unchanged"
    stub.resources["/n"] = Resource("<p>obvod 2</p>(HA2)".encode())
    assert run(tmp_path, inp)["n"].status == "updated"


def test_address_row_drop_over_one_percent_keeps_previous(stub: Stub, tmp_path: Path):
    inp = make_input(stub, "adr", "csv", expect=HEADER)
    stub.resources["/adr"] = Resource(csv_body(1000))
    assert run(tmp_path, inp)["adr"].detail == "1,000 rows"
    target = tmp_path / "adr" / "adr.csv"
    good = target.read_bytes()

    stub.resources["/adr"] = Resource(csv_body(989))
    outcome = run(tmp_path, inp)["adr"]
    assert outcome.status == "failed"
    assert "989 rows, down from 1,000" in outcome.detail
    assert target.read_bytes() == good
    assert manifest(tmp_path)["adr"]["rows"] == 1000

    stub.resources["/adr"] = Resource(csv_body(990))
    assert run(tmp_path, inp)["adr"].status == "updated"
    assert manifest(tmp_path)["adr"]["rows"] == 990


def test_force_accepts_a_row_drop(stub: Stub, tmp_path: Path):
    inp = make_input(stub, "adr", "csv", expect=HEADER)
    stub.resources["/adr"] = Resource(csv_body(1000))
    run(tmp_path, inp)
    stub.resources["/adr"] = Resource(csv_body(500))
    assert run(tmp_path, inp, force=True)["adr"].status == "updated"


def test_corrupt_download_leaves_no_file(stub: Stub, tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.gpkg", b"x")
    stub.resources["/z"] = Resource(buf.getvalue())
    stub.resources["/p"] = Resource(b"<html>error</html>")
    outcomes = run(
        tmp_path,
        make_input(stub, "z", "zip", members=("USJ_hranice_0.gpkg",)),
        make_input(stub, "p", "pdf"),
    )
    assert outcomes["z"].status == "failed"
    assert "USJ_hranice_0.gpkg" in outcomes["z"].detail
    assert outcomes["p"].detail == "not a PDF"
    assert list((tmp_path / "z").iterdir()) == []
    assert list((tmp_path / "p").iterdir()) == []


def test_pinned_digest_rejects_other_content(stub: Stub, tmp_path: Path):
    stub.resources["/g"] = Resource(b'{"type": "FeatureCollection", "features": [{}]}')
    outcome = run(tmp_path, make_input(stub, "g", "geojson", sha256="0" * 64))["g"]
    assert outcome.status == "failed"
    assert "is pinned" in outcome.detail
    assert list((tmp_path / "g").iterdir()) == []


def pinned_pdf(stub: Stub, body: bytes) -> Input:
    return make_input(stub, "r", "pdf", sha256=hashlib.sha256(body).hexdigest())


def test_a_pinned_input_on_disk_is_asked_of_nobody(stub: Stub, tmp_path: Path):
    body = b"%PDF-1.7 results"
    pinned = pinned_pdf(stub, body)
    stub.resources["/r"] = Resource(body)
    assert run(tmp_path, pinned)["r"].status == "new"
    stub.resources.clear()
    requests = len(stub.statuses)

    outcome = run(tmp_path, pinned)["r"]
    assert (outcome.status, outcome.detail) == ("unchanged", "on disk")
    assert len(stub.statuses) == requests

    # Without the manifest, the file on disk counts by its digest: one
    # copied in by hand is taken, and asked of nobody.
    (tmp_path / "manifest.json").unlink()
    outcome = run(tmp_path, pinned)["r"]
    assert (outcome.status, outcome.detail) == ("new", "found on disk")
    assert len(stub.statuses) == requests
    assert manifest(tmp_path)["r"]["sha256"] == pinned.sha256

    # Another file there is not: it is fetched, and replaced only by the
    # pinned one.
    (tmp_path / "r" / "r.pdf").write_bytes(b"%PDF-1.7 other")
    assert run(tmp_path, pinned)["r"].status == "failed"
    assert (tmp_path / "r" / "r.pdf").read_bytes() == b"%PDF-1.7 other"


def test_a_pinned_input_comes_from_the_store_before_its_source(
    stub: Stub, tmp_path: Path
):
    body = b"%PDF-1.7 results"
    pinned = pinned_pdf(stub, body)
    stored = StubStore("o/inputs", "inputs", stub.base)
    stub.resources[f"/store/{stored.asset(pinned)}"] = Resource(body, etag='"s"')
    # What the source serves now is no longer the pinned file.
    stub.resources["/r"] = Resource(b"%PDF-1.7 revised")

    outcome = run(tmp_path, pinned, store=stored)["r"]
    assert (outcome.status, outcome.detail) == ("new", "from the store")
    assert (tmp_path / "r" / "r.pdf").read_bytes() == body
    entry = manifest(tmp_path)["r"]
    # Recorded as the source's file, without the store's validators.
    assert entry["url"] == pinned.url
    assert "etag" not in entry


def test_a_pinned_input_the_store_lacks_comes_from_its_source(
    stub: Stub, tmp_path: Path
):
    body = b"%PDF-1.7 results"
    stub.resources["/r"] = Resource(body)
    stored = StubStore("o/inputs", "inputs", stub.base)
    outcome = run(tmp_path, pinned_pdf(stub, body), store=stored)["r"]
    assert (outcome.status, outcome.detail) == ("new", "from the source")


def test_a_store_copy_that_is_not_the_pinned_one_is_refused(stub: Stub, tmp_path: Path):
    pinned = pinned_pdf(stub, b"%PDF-1.7 results")
    stored = StubStore("o/inputs", "inputs", stub.base)
    stub.resources[f"/store/{stored.asset(pinned)}"] = Resource(b"%PDF-1.7 other")

    outcome = run(tmp_path, pinned, store=stored)["r"]
    assert outcome.status == "failed"
    assert outcome.detail.startswith("the store: sha256 ")
    assert "the source: HTTP 404" in outcome.detail
    assert list((tmp_path / "r").iterdir()) == []


def test_update_pins_what_the_source_serves_now(stub: Stub, tmp_path: Path):
    body = b"%PDF-1.7 results"
    pinned = pinned_pdf(stub, body)
    stub.resources["/r"] = Resource(body)
    run(tmp_path, pinned)
    cfg = Inputs("test@example.org", (), (pinned,))

    outcome, entry = fetch.update(cfg, tmp_path, pinned)
    assert outcome.status == "unchanged"
    assert entry["sha256"] == pinned.sha256

    stub.resources["/r"] = Resource(b"%PDF-1.7 revised")
    outcome, entry = fetch.update(cfg, tmp_path, pinned)
    assert outcome.status == "updated"
    assert entry["sha256"] == hashlib.sha256(b"%PDF-1.7 revised").hexdigest()
    assert manifest(tmp_path)["r"] == entry


INPUTS = """\
[input.a]
url = "https://example.org/a"
file = "a.pdf"
kind = "pdf"
optional = true

# The next input.
[input.b]
url = "https://example.org/b"
file = "b.zip"
kind = "zip"
members = ["x"]
sha256 = "old"
retrieved = 2026-01-01
"""


def test_write_pin_keeps_the_rest_of_the_file(tmp_path: Path):
    path = tmp_path / "inputs.toml"
    path.write_text(INPUTS)
    store.write_pin(path, "a", "1" * 64, dt.date(2026, 10, 1))
    store.write_pin(path, "b", "2" * 64, dt.date(2026, 10, 2))
    expected = INPUTS.replace(
        'kind = "pdf"\n',
        f'kind = "pdf"\nsha256 = "{"1" * 64}"\nretrieved = 2026-10-01\n',
    ).replace(
        'sha256 = "old"\nretrieved = 2026-01-01\n',
        f'sha256 = "{"2" * 64}"\nretrieved = 2026-10-02\n',
    )
    assert path.read_text() == expected


def pinned_files(tmp_path: Path, bodies: dict[str, bytes]) -> list[Input]:
    inputs = []
    for name, body in bodies.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.pdf").write_bytes(body)
        inputs.append(
            Input(
                name,
                f"https://example.org/{name}",
                f"{name}.pdf",
                "pdf",
                (),
                "",
                None,
                hashlib.sha256(body).hexdigest(),
                False,
            )
        )
    return inputs


class FakeGitHub:
    """The GitHub CLI over one repository, whose releases are *releases*."""

    def __init__(self, releases: dict[str, dict]):
        self.releases = releases
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args[:2])
        if args[:2] == ("release", "list"):
            return json.dumps(
                [
                    {"tagName": t, "isDraft": r["draft"]}
                    for t, r in self.releases.items()
                ]
            )
        if args[:2] == ("release", "view"):
            return "".join(f"{a}\n" for a in self.releases[args[2]]["assets"])
        if args[:2] == ("release", "create"):
            assert "--prerelease" in args
            self.releases[args[2]] = {"draft": False, "assets": {}}
            return ""
        assert args[:2] == ("release", "upload")
        path = Path(args[3])
        self.releases[args[2]]["assets"][path.name] = path.read_bytes()
        return ""


def test_publish_uploads_only_what_the_store_lacks(monkeypatch, tmp_path: Path):
    there, missing = b"%PDF-1.7 there", b"%PDF-1.7 missing"
    inputs = pinned_files(tmp_path, {"t": there, "m": missing})
    stored = Store("o/inputs", "inputs")
    github = FakeGitHub(
        {"inputs": {"draft": False, "assets": {stored.asset(inputs[0]): there}}}
    )
    monkeypatch.setattr(store, "_gh", github)
    cfg = Inputs("test@example.org", (), tuple(inputs), stored)
    assert [inp.name for inp in store.publish(cfg, tmp_path)] == ["m"]
    assert github.releases["inputs"]["assets"] == {
        stored.asset(inputs[0]): there,
        stored.asset(inputs[1]): missing,
    }
    assert ("release", "create") not in github.calls
    # Run again, it uploads nothing.
    assert list(store.publish(cfg, tmp_path)) == []

    # A file on disk that is not the pinned one is not uploaded.
    (tmp_path / "m" / "m.pdf").write_bytes(b"%PDF-1.7 other")
    del github.releases["inputs"]["assets"][stored.asset(inputs[1])]
    with pytest.raises(store.StoreError, match="not the pinned file"):
        list(store.publish(cfg, tmp_path))


def test_publish_creates_the_release_where_there_is_none(monkeypatch, tmp_path: Path):
    inputs = pinned_files(tmp_path, {"a": b"%PDF-1.7 a"})
    stored = Store("o/inputs", "inputs")
    github = FakeGitHub({"v0.7.0": {"draft": False, "assets": {}}})
    monkeypatch.setattr(store, "_gh", github)
    cfg = Inputs("test@example.org", (), tuple(inputs), stored)
    assert [inp.name for inp in store.publish(cfg, tmp_path)] == ["a"]
    assert list(github.releases["inputs"]["assets"]) == [stored.asset(inputs[0])]

    # Not where a file to upload is not the pinned one.
    del github.releases["inputs"]
    (tmp_path / "a" / "a.pdf").write_bytes(b"%PDF-1.7 other")
    with pytest.raises(store.StoreError, match="not the pinned file"):
        list(store.publish(cfg, tmp_path))
    assert "inputs" not in github.releases

    # A draft's assets are not public: it is not taken for the store.
    github.releases["inputs"] = {"draft": True, "assets": {}}
    with pytest.raises(store.StoreError, match="is a draft"):
        list(store.publish(cfg, tmp_path))
