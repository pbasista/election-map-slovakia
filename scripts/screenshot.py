"""Take the README's screenshot, docs/img/main.png, from the built site.

    uv run ems build
    python3 scripts/screenshot.py [--browser PATH] [-- BROWSER-ARGS...]

It needs only the standard library and a Chromium-family browser (Chromium,
Google Chrome, Chrome's headless shell): it serves dist/ on a free port,
starts the browser headless and drives it over the DevTools protocol, so
the project gains no dependency for an image regenerated once a release.
Without --browser it looks for one on PATH. Arguments after `--` go to the
browser as they are (e.g. `-- --no-sandbox` where its sandbox cannot run).

The scene: the English page in the dark theme, 1280×800 at twice the pixel
density, Banská Bystrica clicked in its council constituency No. 1, so the
pane lists the ballots there beside the map; as on the day before the
elections whenever it is taken: the page's clock set to noon that day, so
no voting line, and the live results' origin blocked, so no results.
"""

import argparse
import base64
import datetime as dt
import functools
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
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT = ROOT / "docs/img/main.png"
SITE = ROOT / "config/site.toml"
# As the build reads it (config.py LIVE_URL_ENV).
LIVE_URL_ENV = "EMS_LIVE_URL"
WIDTH, HEIGHT, SCALE = 1280, 800, 2
# Banská Bystrica (obec 508438), a point in its council constituency No. 1;
# `~`: the constituency of a clicked point, as the map marks it.
HASH = "#o=508438&ll=48.73850,19.14650&n=1~"
# The pane has loaded the ballots of the point when it shows this.
READY = "Municipal council of Banská Bystrica, constituency 1"
# After the pane is ready: time for the map to fit the constituency and draw.
SETTLE = 3.0
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
        """Send a command and return its result, skipping events meanwhile."""
        self.next_id += 1
        data = json.dumps({"id": self.next_id, "method": method, "params": params})
        body = data.encode()
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
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message["result"]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        """Log nothing: the base class logs every request to stderr."""


def serve(directory: Path) -> http.server.ThreadingHTTPServer:
    """Serve *directory* on a free local port, in a background thread."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
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


def wait_until_ready(tools: DevTools, deadline: float) -> None:
    """Wait until the pane shows the ballots of the point (READY)."""
    check = f"document.body.innerText.includes({json.dumps(READY)})"
    while time.monotonic() < deadline:
        if tools.call("Runtime.evaluate", expression=check)["result"].get("value"):
            return
        time.sleep(0.2)
    sys.exit(f"screenshot: the pane did not show {READY!r} in {TIMEOUT:.0f} s")


def day_before() -> tuple[int, str | None]:
    """Return noon of the day before the elections and the live origin.

    Noon in Slovak time, in ms since the epoch; the live results' origin as
    the build has it (config/site.toml, EMS_LIVE_URL), or None.
    """
    site = tomllib.loads(SITE.read_text())
    noon = dt.datetime.combine(
        site["election"] - dt.timedelta(days=1),
        dt.time(12),
        ZoneInfo("Europe/Bratislava"),
    )
    live = os.environ.get(LIVE_URL_ENV, site["live_url"]).rstrip("/")
    return int(noon.timestamp() * 1000), live or None


def main() -> None:
    """Take the screenshot."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--browser", help="Chromium-family browser executable")
    parser.add_argument("browser_args", nargs="*", help="extra browser arguments")
    args = parser.parse_args()
    if not (DIST / "en/index.html").exists():
        sys.exit("screenshot: no dist/en/index.html; run `uv run ems build` first")
    server = serve(DIST)
    noon, live = day_before()
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
            tools.call("Page.addScriptToEvaluateOnNewDocument", source=CLOCK % noon)
            if live:
                tools.call("Network.enable")
                tools.call("Network.setBlockedURLs", urls=[f"{live}/*"])
            tools.call("Page.navigate", url=url)
            wait_until_ready(tools, deadline)
            time.sleep(SETTLE)
            shot = tools.call("Page.captureScreenshot", format="png")
        finally:
            browser.terminate()
            browser.wait()
            server.shutdown()
    OUT.write_bytes(base64.b64decode(shot["data"]))
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
