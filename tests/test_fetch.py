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

from election_map_slovakia import fetch
from election_map_slovakia.config import Input, Inputs

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

        def log_message(self, *args):
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


def run(
    tmp_path: Path,
    *inputs: Input,
    force: bool = False,
    fallback_dir: Path | None = None,
) -> dict[str, fetch.Outcome]:
    cfg = Inputs("test@example.org", (), inputs)
    outcomes = fetch.fetch(cfg, tmp_path, fallback_dir=fallback_dir, force=force)
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


def test_server_failure_keeps_only_a_pinned_copy_on_disk(stub: Stub, tmp_path: Path):
    body = b"%PDF-1.7 results"
    pinned = make_input(stub, "r", "pdf", sha256=hashlib.sha256(body).hexdigest())
    unpinned = make_input(stub, "u", "pdf")
    stub.resources["/r"] = Resource(body)
    stub.resources["/u"] = Resource(body)
    run(tmp_path, pinned, unpinned)
    before = manifest(tmp_path)
    stub.resources.clear()

    outcomes = run(tmp_path, pinned, unpinned)
    assert outcomes["r"].status == "fallback"
    assert outcomes["r"].detail == "HTTP 404 Not Found; copy on disk"
    assert outcomes["u"].status == "failed"
    assert manifest(tmp_path) == before

    # A copy changed on disk is not the pinned content, even at the same size.
    (tmp_path / "r" / "r.pdf").write_bytes(b"%PDF-1.7 RESULTS")
    assert run(tmp_path, pinned)["r"].status == "failed"


def test_server_failure_installs_the_committed_pinned_copy(stub: Stub, tmp_path: Path):
    body = b"%PDF-1.7 results"
    pinned = make_input(stub, "r", "pdf", sha256=hashlib.sha256(body).hexdigest())
    fallback = tmp_path / "fallback"
    (fallback / "r").mkdir(parents=True)
    (fallback / "r" / "r.pdf").write_bytes(body)
    entry = {
        "url": pinned.url,
        "path": "r/r.pdf",
        "sha256": pinned.sha256,
        "bytes": len(body),
        "retrieved_at": "2026-10-19T21:38:25+00:00",
    }
    (fallback / "manifest.json").write_text(json.dumps({"inputs": {"r": entry}}))
    raw = tmp_path / "raw"

    outcome = run(raw, pinned, fallback_dir=fallback)["r"]
    assert outcome.status == "fallback"
    assert outcome.detail == "HTTP 404 Not Found; committed copy"
    assert (raw / "r" / "r.pdf").read_bytes() == body
    # The entry says when the copy was downloaded, not when it was copied.
    assert manifest(raw)["r"] == entry

    # A committed copy that is not the pinned content is refused.
    (raw / "r" / "r.pdf").unlink()
    (fallback / "r" / "r.pdf").write_bytes(b"%PDF-1.7 RESULTS")
    outcome = run(raw, pinned, fallback_dir=fallback)["r"]
    assert outcome.status == "failed"
    assert "not the pinned one" in outcome.detail
