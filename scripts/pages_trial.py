"""Try out on Cloudflare Pages what the deployment of the data parts relies on.

    uv run python scripts/pages_trial.py

With the credentials of `npx wrangler login`, or CLOUDFLARE_API_TOKEN and
CLOUDFLARE_ACCOUNT_ID where set (``pages.credentials``).

It creates a throwaway Pages project, deploys to it twice and checks
(docs/deploy.md):

1. that the API lists both deployments with the key each carries as its
   commit message, and the second as the project's current one;
2. that the first deployment's own address still serves its files after the
   second, which is what the app's naming of a bundle by deployment needs;
3. that the headers of the deployment's ``_headers`` reach the browser:
   ``Access-Control-Allow-Origin``, which the app's cross-origin fetches
   need, and the status 404 of a missing file (``404.html``);
4. whether a byte range of a binary file comes back as such (206), as a
   packed archive of data files would need, and of a JSON file.

Then it deletes the project, unless --keep. A token needs Account ›
Cloudflare Pages › Edit; Wrangler comes by npx, as for `ems data deploy`.
"""

import argparse
import json
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

from election_map_slovakia import config, fetch, pages

# A new project's addresses may take a while to resolve.
PATIENCE = 180
HEADERS = "/*\n  Access-Control-Allow-Origin: *\n"
RANGE = 100
"""The bytes asked for of a file, from its start."""


def wrangler(*args: str) -> None:
    """Run Wrangler with *args*; exit if it fails."""
    if code := pages.wrangler(*args):
        sys.exit(f"wrangler {' '.join(args[:3])}: exit {code}")


def deployment(directory: Path, content: str, key: str, project: str) -> None:
    """Deploy *directory*, holding a.json with *content*, as carrying *key*."""
    directory.mkdir()
    (directory / "_headers").write_text(HEADERS)
    (directory / "404.html").write_text("<!DOCTYPE html><title>404</title>\n")
    (directory / "a.json").write_text(json.dumps({"content": content}))
    (directory / "b.bin").write_bytes(secrets.token_bytes(1 << 16))
    if pages.deploy(directory, project, key):
        sys.exit("wrangler pages deploy failed")


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict, bytes]:
    """Return status, headers and body of a GET of *url*, waiting for DNS."""
    # *.pages.dev turns Python's own User-Agent away (403, error 1010).
    agent = fetch.user_agent(config.load().inputs.contact)
    deadline = time.monotonic() + PATIENCE
    while True:
        request = urllib.request.Request(
            url, headers={"User-Agent": agent} | (headers or {})
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
        except urllib.error.URLError:
            if time.monotonic() > deadline:
                raise
            time.sleep(5)


def main() -> None:
    """Run the trial."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--keep", action="store_true", help="keep the project")
    args = parser.parse_args()
    project = f"ems-trial-{secrets.token_hex(3)}"
    wrangler("pages", "project", "create", project, "--production-branch=main")
    results = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            deployment(Path(tmp) / "1", "first", "key1", project)
            deployment(Path(tmp) / "2", "second", "key2", project)
        first, second = pages.find(project, "key1"), pages.find(project, "key2")
        current = pages.current(project)
        results["1. the API lists each deployment by its key"] = bool(
            first and second and first.url != second.url
        )
        results["1. the second is the current one"] = bool(
            current and current.key == "key2"
        )
        if first and second:
            _, head, body = get(f"{first.url}/a.json")
            results["2. the first address serves the first files"] = (
                json.loads(body)["content"] == "first"
            )
            results["3. Access-Control-Allow-Origin reaches the browser"] = (
                head.get("Access-Control-Allow-Origin") == "*"
            )
            status, _, _ = get(f"{second.url}/missing.json")
            results["3. a missing file is a 404"] = status == HTTPStatus.NOT_FOUND
            for name in ("b.bin", "a.json"):
                status, head, body = get(
                    f"{second.url}/{name}",
                    {"Range": f"bytes=0-{RANGE - 1}", "Accept-Encoding": "identity"},
                )
                results[f"4. a byte range of {name} is a 206"] = (
                    status == HTTPStatus.PARTIAL_CONTENT and len(body) == RANGE
                )
    finally:
        if not args.keep:
            wrangler("pages", "project", "delete", project, "--yes")
    for check, ok in results.items():
        print(f"{'ok  ' if ok else 'FAIL'} {check}")


if __name__ == "__main__":
    try:
        main()
    except pages.PagesError as e:
        sys.exit(str(e))
