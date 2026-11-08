"""Take the README's screenshot, docs/img/main.png, from the built site.

    uv run ems build
    python3 scripts/screenshot.py [--browser PATH] [-- BROWSER-ARGS...]

It needs only the standard library and a Chromium-family browser (Chromium,
Google Chrome, Chrome's headless shell): it serves the parts in dist/ on a
free port as `ems serve` does, starts the browser headless and drives it
over the DevTools protocol, so the project gains no dependency for an image
regenerated once a release.
Without --browser it looks for one on PATH. Arguments after `--` go to the
browser as they are (e.g. `-- --no-sandbox` where its sandbox cannot run).

The scene: the English page in the dark theme, 1280×800 at twice the pixel
density, Banská Bystrica clicked in its council constituency No. 1, so the
pane lists the ballots there beside the map with the final results: the
council's turnout, the candidates by votes with their shares and the
elected marked; the map shows who got the most votes in each polling
district of the constituency, with its legend. Whenever it is taken, it
shows the same moment after the latest elections: the page's clock is set
to noon of the day after the app stops polling for results (live_days after
the polls close), so the app reads the final results and shows no voting
or counting line. It waits for the results to be drawn and fails on any
error the page reports.
"""

import argparse
import base64
import datetime as dt
import http.server
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = ROOT / "docs/img/main.png"
ELECTIONS = ROOT / "config/elections.toml"
WIDTH, HEIGHT, SCALE = 1280, 800, 2
# Banská Bystrica (obec 508438), a point in its council constituency No. 1;
# `~`: the constituency of a clicked point, as the map marks it. `mr`: the
# map shows who got the most votes in each polling district of that
# council contest (`winner:<contest>`), with its legend; `m`: zoomed to the
# constituency, as its "most votes" button fits it, a little south so that
# the legend leaves the coloured districts in view (a link's view is kept,
# where the mode alone would fit the whole obec).
HASH = (
    "#o=508438&ll=48.73850,19.14650&n=1~"
    "&m=13.62/48.73900/19.13530&mr=winner:oz:508438/1"
)
# The pane has loaded the ballots of the point when it shows this.
READY = "Municipal council of Banská Bystrica, constituency 1"
# Null until the pane is READY and the legend counts the districts each
# leader won, which it does once the results are in and on the map; then
# a digest of the map's canvas after the next frames, to tell when the
# map has stopped moving and drawing.
DRAWN = """(async () => {
  if (!document.body.innerText.includes(%s)) return null;
  if (!document.querySelector('.map-legend .map-legend-count')) return null;
  await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
  const png = new TextEncoder().encode(document.querySelector('canvas.km-canvas').toDataURL());
  const digest = await crypto.subtle.digest('SHA-256', png);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
})()""" % json.dumps(READY)
# The map counts as drawn once its canvas is unchanged this many times in a
# row, CHECK_EVERY seconds apart.
STILL = 4
CHECK_EVERY = 0.25
# Shifts the page's clock (Date) to the time filled in (ms since the epoch),
# running on from there. Injected over DevTools (which needs the Page
# domain enabled for it), it runs before the page's own scripts and outside
# its CSP.
CLOCK = """(() => {
  const shift = %d - Date.now();
  const RealDate = Date;
  class ShiftedDate extends RealDate {
    constructor(...args) {
      super(...(args.length ? args : [RealDate.now() + shift]));
    }
    static now() {
      return RealDate.now() + shift;
    }
  }
  globalThis.Date = ShiftedDate;
})();"""
TIMEOUT = 60.0
BROWSERS = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "headless_shell",
)
# RFC 6455 payload lengths: up to 125 in the header, these two markers for a
# 16- or 64-bit length after it.
LENGTH_16 = 126
LENGTH_64 = 127
# The browser's output, in its profile directory.
LOG = "browser.log"


class DevTools:
    """A client of one page's DevTools WebSocket (RFC 6455, text frames)."""

    def __init__(self, url: str) -> None:
        """Connect to *url*, a ``ws://host:port/path`` of DevTools."""
        rest = url.removeprefix("ws://")
        address, path = rest.split("/", 1)
        host, port = address.rsplit(":", 1)
        self.sock = socket.create_connection((host, int(port)), timeout=TIMEOUT)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET /{path} HTTP/1.1\r\nHost: {address}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        head, self.buffer = response.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"DevTools refused the WebSocket: {head[:200]!r}")
        self.next_id = 0
        # The page's errors told meanwhile (with the Runtime and Log domains
        # enabled): uncaught exceptions, console.error, failed loads.
        self.errors: list[str] = []

    def _note(self, message: dict) -> None:
        """Keep *message*, an event, in `errors` if it tells of one."""
        params = message.get("params", {})
        match message.get("method"):
            case "Runtime.exceptionThrown":
                details = params["exceptionDetails"]
                exception = details.get("exception", {})
                self.errors.append(exception.get("description") or details["text"])
            case "Runtime.consoleAPICalled" if params["type"] == "error":
                args = params["args"]
                texts = (str(a.get("value", a.get("description", ""))) for a in args)
                self.errors.append(f"console.error: {' '.join(texts)}")
            case "Log.entryAdded" if params["entry"]["level"] == "error":
                entry = params["entry"]
                self.errors.append(f"{entry['text']} {entry.get('url', '')}".strip())

    def _read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(1 << 16)
            if not chunk:
                raise RuntimeError("DevTools closed the connection")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def _message(self) -> dict:
        payload = b""
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == LENGTH_16:
                (length,) = struct.unpack(">H", self._read(2))
            elif length == LENGTH_64:
                (length,) = struct.unpack(">Q", self._read(8))
            payload += self._read(length)
            if first & 0x80:  # the last frame of the message
                return json.loads(payload)

    def call(self, method: str, **params) -> dict:
        """Send a command and return its result, noting events meanwhile."""
        self.next_id += 1
        request = {"id": self.next_id, "method": method, "params": params}
        body = json.dumps(request).encode()
        mask = os.urandom(4)
        n = len(body)
        if n < LENGTH_16:
            header = struct.pack(">BB", 0x81, 0x80 | n)
        elif n < 1 << 16:
            header = struct.pack(">BBH", 0x81, 0x80 | LENGTH_16, n)
        else:
            header = struct.pack(">BBQ", 0x81, 0x80 | LENGTH_64, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(body))
        self.sock.sendall(header + mask + masked)
        while True:
            message = self._message()
            if message.get("id") != self.next_id:
                self._note(message)
                continue
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message["result"]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the parts of dist/ as one site, as `ems serve` does.

    Where `ems build` points the app (src/election_map_slovakia/build.py,
    `mounts`): the bundles below /map/ and /data/, the base maps below /base/,
    the final results below /results/, the live results below /live/, the
    cached sources' files where the app has none, the app everywhere else.
    """

    def translate_path(self, path: str) -> str:
        rel = urllib.parse.unquote(urllib.parse.urlsplit(path).path).lstrip("/")
        if rel.startswith(("map/", "data/", "base/", "results/", "live/")):
            return str(DIST / rel)
        app = DIST / "app" / rel
        sources = DIST / "sources" / rel
        return str(app if app.exists() or not sources.exists() else sources)

    def log_message(self, format: str, *args: object) -> None:
        """Log nothing: the base class logs every request to stderr."""


def serve() -> http.server.ThreadingHTTPServer:
    """Serve dist/ on a free local port, in a background thread."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def find_browser(given: str | None) -> str:
    """Return the browser to run: *given*, else the first of BROWSERS on PATH."""
    found = given or next(filter(None, map(shutil.which, BROWSERS)), None)
    if not found:
        sys.exit(
            f"screenshot: no browser on PATH ({', '.join(BROWSERS)}); pass --browser"
        )
    return found


def page_socket(browser: subprocess.Popen, profile: Path, deadline: float) -> str:
    """Return the WebSocket URL of the browser's first page, once it is up."""
    port_file = profile / "DevToolsActivePort"
    while time.monotonic() < deadline:
        if browser.poll() is not None:
            log = (profile / LOG).read_text(errors="replace").strip()
            sys.exit(f"screenshot: the browser exited ({browser.returncode}):\n{log}")
        if port_file.exists() and (lines := port_file.read_text().split()):
            with urllib.request.urlopen(f"http://127.0.0.1:{lines[0]}/json/list") as r:
                pages = [t for t in json.load(r) if t["type"] == "page"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        time.sleep(0.1)
    sys.exit("screenshot: the browser did not start its DevTools")


def wait_until_drawn(tools: DevTools, deadline: float) -> None:
    """Wait until the results are in the pane and still on the map (DRAWN)."""
    last, still = None, 0
    while time.monotonic() < deadline:
        result = tools.call("Runtime.evaluate", expression=DRAWN, awaitPromise=True)
        drawn = result["result"].get("value")
        still = still + 1 if drawn and drawn == last else 0
        if still == STILL:
            return
        last = drawn
        time.sleep(CHECK_EVERY)
    sys.exit(
        f"screenshot: no results drawn in {TIMEOUT:.0f} s (pane {READY!r}, the "
        "legend's counts, a still map); does dist/ have the final results?"
    )


def after_results() -> int:
    """Return noon once the home election's results are final, in ms (epoch).

    The home election is the newest one that is not a by-election, the one
    /en/ shows (config.py `Config.home`). The noon is that of the day after
    the app's polling window (the polls' closing plus live_days): past it the
    app reads the final results once per page load and shows no voting or
    counting line, whatever the build's `live`. Unlike the real time, it
    keeps the screenshot the same whenever it is taken.
    """
    elections = tomllib.loads(ELECTIONS.read_text())["election"].values()
    home = max(
        (e for e in elections if e["kind"] != "by-election"), key=lambda e: e["day"]
    )
    close = dt.datetime.combine(home["day"], home["polls_close"])
    last = (close + dt.timedelta(days=home["live_days"])).date()
    noon = dt.datetime.combine(
        last + dt.timedelta(days=1), dt.time(12), ZoneInfo("Europe/Bratislava")
    )
    return int(noon.timestamp() * 1000)


def main() -> None:
    """Take the screenshot."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--browser", help="Chromium-family browser executable")
    parser.add_argument("browser_args", nargs="*", help="extra browser arguments")
    args = parser.parse_args()
    if not (DIST / "app/en/index.html").exists():
        sys.exit("screenshot: no dist/app/en/index.html; run `uv run ems build` first")
    server = serve()
    noon = after_results()
    url = f"http://127.0.0.1:{server.server_port}/en/{HASH}"
    deadline = time.monotonic() + TIMEOUT
    # The browser's helpers may still be writing to the profile as it goes;
    # a leftover in /tmp is no reason to fail after the shot.
    with tempfile.TemporaryDirectory(
        prefix="ems-screenshot-", ignore_cleanup_errors=True
    ) as profile:
        command = [
            find_browser(args.browser),
            "--headless",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            *args.browser_args,
            "about:blank",
        ]
        # Its log goes to a file, shown only if it fails to start: a working
        # browser chatters too (GPU and sandbox warnings).
        with (Path(profile) / LOG).open("wb") as log:
            try:
                browser = subprocess.Popen(command, stdout=log, stderr=log)
            except OSError as e:
                sys.exit(f"screenshot: {command[0]}: {e.strerror}")
        try:
            tools = DevTools(page_socket(browser, Path(profile), deadline))
            tools.call(
                "Emulation.setDeviceMetricsOverride",
                width=WIDTH,
                height=HEIGHT,
                deviceScaleFactor=SCALE,
                mobile=False,
            )
            tools.call(
                "Emulation.setEmulatedMedia",
                features=[{"name": "prefers-color-scheme", "value": "dark"}],
            )
            tools.call("Page.enable")
            tools.call("Runtime.enable")
            tools.call("Log.enable")
            tools.call("Page.addScriptToEvaluateOnNewDocument", source=CLOCK % noon)
            tools.call("Page.navigate", url=url)
            wait_until_drawn(tools, deadline)
            shot = tools.call("Page.captureScreenshot", format="png")
        finally:
            browser.terminate()
            browser.wait()
            server.shutdown()
    if tools.errors:
        sys.exit("screenshot: the page had errors:\n" + "\n".join(tools.errors))
    OUT.write_bytes(base64.b64decode(shot["data"]))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
