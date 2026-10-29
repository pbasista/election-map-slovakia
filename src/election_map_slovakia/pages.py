"""The site's parts on Cloudflare Pages: their deployments, and deploying them.

Every part of the site is a Pages project of its own (``config/site.toml``,
docs/deploy.md). A deployment of a data part carries its key
(:mod:`election_map_slovakia.lock`) as its commit message, which Wrangler
sets (:func:`deploy_command`) and the Pages API lists (:func:`deployments`):

- an election's bundles, its map and its data, are each deployed once
  per key, and the app names the deployment that carries the key by its
  own address, ``https://<id>.<project>.pages.dev``, which keeps serving
  that deployment's files whatever is deployed later (:func:`locations`);
- the sources and the results are served at their own domains by the
  project's current production deployment, which is deployed anew when it
  carries another key (:func:`current`). Results deployed on an election
  night carry the key followed by ``live`` (:data:`LIVE`): a release with
  that key leaves them in place.

The API is read, and Wrangler deploys, with the credentials Wrangler uses
(:func:`credentials`): ``CLOUDFLARE_API_TOKEN`` (Account › Cloudflare
Pages › Edit) and ``CLOUDFLARE_ACCOUNT_ID`` where set, else the login of
``npx wrangler login``.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from election_map_slovakia import build, bundle, lock
from election_map_slovakia.config import Config

API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
WRANGLER = "wrangler@4.151.1"
"""The Wrangler that deploys, the version release.yml pins as well."""
LIVE = "live"
"""After the key in the commit message of results deployed on an election
night (``ems results deploy``)."""
PRODUCTION_BRANCH = "main"
"""The production branch of every project: a deployment to it is live."""
_TIMEOUT = 60


class PagesError(Exception):
    """The Pages API failed, or a part is not deployed as it must be."""


@dataclass(frozen=True)
class Deployment:
    """One deployment of a Pages project."""

    url: str
    """Its own address, which always serves its files."""
    message: str
    """Its commit message: the key it carries, for a data part."""

    @property
    def key(self) -> str:
        """Return the key it carries: the first word of its message."""
        return self.message.split(maxsplit=1)[0] if self.message else ""


def deployments(project: str) -> Iterator[Deployment]:
    """Yield the successful production deployments of *project*, newest first."""
    page = 1
    while True:
        reply = _get(
            f"/pages/projects/{project}/deployments?env=production&page={page}"
        )
        for d in reply["result"]:
            if d.get("latest_stage", {}).get("status") == "success":
                yield _deployment(d)
        info = reply.get("result_info") or {}
        if not reply["result"] or page >= info.get("total_pages", page):
            return
        page += 1


def find(project: str, key: str) -> Deployment | None:
    """Return the newest production deployment of *project* carrying *key*."""
    return next((d for d in deployments(project) if d.key == key), None)


def current(project: str) -> Deployment | None:
    """Return the deployment *project* serves at its domains, if any.

    The canonical one: the latest to production, or the one rolled back to.
    """
    deployment = _get(f"/pages/projects/{project}")["result"].get(
        "canonical_deployment"
    )
    return _deployment(deployment) if deployment else None


def bundles(cfg: Config, keys: lock.Keys) -> Iterator[tuple[str, str, str, str]]:
    """Yield (part, election slug, project, key) of every election's bundles.

    *part* is :data:`bundle.MAP_PART` or :data:`bundle.DATA_PART`, below
    ``dist/`` the bundle is at ``<part>/<slug>``.
    """
    for part, project_of, by_slug in (
        (bundle.MAP_PART, cfg.site.map_project_of, keys.maps),
        (bundle.DATA_PART, cfg.site.data_project_of, keys.data),
    ):
        for election in cfg.elections:
            slug = election.slug
            yield part, slug, project_of(slug), by_slug[slug]


def locations(cfg: Config, keys: lock.Keys) -> build.Locations:
    """Return where the deployed data parts of *keys* are, for the app.

    Each election's bundles by the deployments that carry their keys, with
    their manifests read from there; the sources and results at their
    domains (``site.toml``). Raises :class:`PagesError` where a bundle of
    its key is not deployed.
    """
    located: dict[str, dict[str, build.Located]] = {
        bundle.MAP_PART: {},
        bundle.DATA_PART: {},
    }
    for part, slug, project, key in bundles(cfg, keys):
        deployment = find(project, key)
        if deployment is None:
            raise PagesError(
                f"no deployment of {project} carries the key {key}; build and"
                " deploy the data first (`ems make`, `ems data deploy`)"
            )
        manifest = _read(f"{deployment.url}/{bundle.MANIFEST}")
        if manifest.get("key") != key:
            raise PagesError(
                f"{deployment.url}/{bundle.MANIFEST}: key {manifest.get('key')},"
                f" not {key}"
            )
        located[part][slug] = build.Located(deployment.url, manifest)
    return build.Locations(
        located[bundle.MAP_PART],
        located[bundle.DATA_PART],
        cfg.site.results_url,
        cfg.site.sources_url,
    )


@functools.cache
def credentials() -> tuple[str, str]:
    """Return the API token and the account the Pages API is read with.

    :data:`TOKEN_ENV` and :data:`ACCOUNT_ENV` where set, as for Wrangler;
    else Wrangler's own: the token of ``npx wrangler login``, which
    ``wrangler auth token`` renews where it expired, and the one account
    the token reaches (``wrangler whoami``). Where it reaches several,
    :data:`ACCOUNT_ENV` names the one.
    """
    token = os.environ.get(TOKEN_ENV)
    if not token:
        token = _wrangler_json("auth", "token", "--json").get("token")
        if not token:
            raise PagesError(
                f"Wrangler is logged in without a token; set {TOKEN_ENV}"
                " (docs/deploy.md)"
            )
    account = os.environ.get(ACCOUNT_ENV)
    if not account:
        accounts = _wrangler_json("whoami", "--json").get("accounts") or []
        if len(accounts) != 1:
            named = ", ".join(f"{a.get('name')} ({a.get('id')})" for a in accounts)
            raise PagesError(
                f"the Cloudflare login reaches {len(accounts)} accounts"
                f"{': ' + named if named else ''}; set {ACCOUNT_ENV} to the"
                " one of the site"
            )
        account = accounts[0]["id"]
    return token, account


def wrangler_command(*args: str) -> list[str]:
    """Return the command that runs Wrangler (:data:`WRANGLER`) with *args*."""
    return ["npx", "--yes", WRANGLER, *args]


def wrangler(*args: str) -> int:
    """Run Wrangler with *args* on the account of :func:`credentials`.

    Return its exit code. Named, so that a login reaching several accounts
    does not make Wrangler ask which one.
    """
    _, account = credentials()
    env = os.environ | {ACCOUNT_ENV: account}
    return subprocess.run(wrangler_command(*args), env=env, check=False).returncode


def _deploy_args(directory: Path, project: str, message: str) -> list[str]:
    """Return Wrangler's arguments to deploy *directory* to *project*.

    To production (``--branch``): without it Wrangler would make a preview
    deployment of the branch checked out, and of none on a tag.
    """
    return [
        "pages",
        "deploy",
        str(directory),
        f"--project-name={project}",
        f"--branch={PRODUCTION_BRANCH}",
        f"--commit-message={message}",
        "--commit-dirty=true",
    ]


def deploy_command(directory: Path, project: str, message: str) -> list[str]:
    """Return the command that deploys *directory* to *project* with *message*."""
    return wrangler_command(*_deploy_args(directory, project, message))


def deploy(directory: Path, project: str, message: str) -> int:
    """Deploy *directory* to *project* with *message*; return Wrangler's code."""
    return wrangler(*_deploy_args(directory, project, message))


def _wrangler_json(*args: str) -> dict[str, Any]:
    """Return the JSON object Wrangler with *args* prints (``--json``)."""
    done = subprocess.run(
        wrangler_command(*args), capture_output=True, text=True, check=False
    )
    start = done.stdout.find("{")
    try:
        reply = json.loads(done.stdout[start:]) if start >= 0 else None
    except ValueError:
        reply = None
    if done.returncode or not isinstance(reply, dict):
        raise PagesError(
            f"no Cloudflare credentials (`wrangler {' '.join(args)}` failed): log"
            f" in with `npx wrangler login`, or set {TOKEN_ENV} and"
            f" {ACCOUNT_ENV} (docs/deploy.md)"
        )
    return reply


def _deployment(d: dict[str, Any]) -> Deployment:
    trigger = d.get("deployment_trigger") or {}
    message = (trigger.get("metadata") or {}).get("commit_message") or ""
    return Deployment(d["url"], message.strip())


def _get(path: str) -> dict[str, Any]:
    """Return the reply of the Pages API to a GET of *path* of the account."""
    token, account = credentials()
    reply = _read(
        f"{API}/accounts/{account}{path}", {"Authorization": f"Bearer {token}"}
    )
    if not reply.get("success"):
        raise PagesError(f"Pages API {path}: {reply.get('errors')}")
    return reply


def _read(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the JSON object at *url*."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        raise PagesError(f"{url}: HTTP {e.code} {e.reason}: {body}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PagesError(f"{url}: {e}") from e
