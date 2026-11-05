"""The site's parts on Cloudflare Pages: their projects, their deployments.

Every part of the site is a Pages project of its own (``config/site.toml``,
docs/deploy.md). A deployment of a data part carries its key
(:mod:`election_map_slovakia.lock`) as its commit message, which Wrangler
sets (:func:`deploy_command`) and the Pages API lists (:func:`deployments`):

- an election's bundles, its map and its data, and the base map of each
  extract (all in one project, ``base_project``) are each deployed once
  per key, and the app names the deployment that carries the key by its
  own address, ``https://<id>.<project>.pages.dev``, which keeps serving
  that deployment's files whatever is deployed later (:func:`locations`);
- the sources and the final results are served at their own domains by
  the project's current production deployment, which is deployed anew when
  it carries another key (:func:`current`).

The live results of an election night are a project of their own,
``live_project``, with no key: ``ems results deploy`` deploys them, never a
release, and they are served at their own domain likewise.

The API is read, and Wrangler deploys, with the credentials Wrangler uses
(:func:`credentials`): ``CLOUDFLARE_API_TOKEN`` (Account › Cloudflare
Pages › Edit) and ``CLOUDFLARE_ACCOUNT_ID`` where set, else the login of
``npx wrangler login``.

The projects themselves are made once each, before the first deployment to
them: :func:`needed` names those the site needs, :func:`projects` those the
account has, and :func:`create` creates one; :func:`unneeded` names the
bundles' projects no release needs any more, and :func:`delete` deletes one.
"""

from __future__ import annotations

import functools
import json
import os
import re
import subprocess
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from election_map_slovakia import build, bundle, config, fetch, lock
from election_map_slovakia.config import Config

API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
WRANGLER = "wrangler@4.156.1"
"""The Wrangler that deploys, the version release.yml pins as well."""
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


@dataclass(frozen=True)
class Project:
    """A Pages project of the account."""

    name: str
    production_branch: str
    domains: tuple[str, ...]
    """The domains it serves at besides its own ``pages.dev`` address."""


def deployments(project: str) -> Iterator[Deployment]:
    """Yield the successful production deployments of *project*, newest first."""
    for d in _results(f"/pages/projects/{project}/deployments?env=production"):
        if d.get("latest_stage", {}).get("status") == "success":
            yield _deployment(d)


def projects() -> dict[str, Project]:
    """Return the Pages projects of the account, by name."""
    return {
        p["name"]: Project(
            p["name"],
            p.get("production_branch") or "",
            tuple(p.get("domains") or ()),
        )
        for p in _results("/pages/projects")
    }


def needed(cfg: Config) -> dict[str, tuple[str, ...]]:
    """Return every Pages project the site needs, with the domains it serves at.

    The app at the host of ``base_url`` and that host with ``www.``, which
    redirects to it; the sources, the final results and the live results at
    the hosts of ``sources_url``, ``results_url`` and ``live_url``
    (docs/deploy.md). The bundles and the base maps need no domain: the app
    names the deployments that carry their keys.
    """
    site = cfg.site
    host = urlsplit(site.base_url).netloc if site.base_url else ""
    return {
        site.pages_project: (host, f"www.{host}") if host else (),
        **{site.map_project_of(e.slug): () for e in cfg.elections},
        **{site.data_project_of(e.slug): () for e in cfg.elections},
        site.base_project: (),
        site.sources_project: (urlsplit(site.sources_url).netloc,),
        site.results_project: (urlsplit(site.results_url).netloc,),
        site.live_project: (urlsplit(site.live_url).netloc,),
    }


def create(project: str) -> int:
    """Create the Pages project *project*; return Wrangler's exit code.

    For direct uploads, with the production branch :data:`PRODUCTION_BRANCH`
    that every deployment is made as (:func:`deploy`).
    """
    return wrangler(
        "pages",
        "project",
        "create",
        project,
        f"--production-branch={PRODUCTION_BRANCH}",
    )


def unneeded(cfg: Config, names: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return the bundles' projects among *names* that the site needs no more.

    As (prunable, kept): the projects named like an election's map or data
    bundle (``map_project``, ``data_project``) of an election that
    ``config/elections.toml`` lists neither now nor at ``HEAD``, and those
    of an election that only a version tag (``v*``) lists, kept: a release
    rolled back to names its bundles' deployments (docs/deploy.md). Other
    projects of the account, the app's and the base maps' above all, are
    never among them.
    """
    site = cfg.site
    any_slug = f"({config.SLUG.pattern})"
    patterns = [
        re.compile(re.escape(template).replace(re.escape("{slug}"), any_slug))
        for template in (site.map_project, site.data_project)
    ]
    now = {e.slug for e in cfg.elections}
    # Named like a bundle's project, they are still no election's.
    never = (site.pages_project, site.base_project)
    gone: dict[str, str] = {}
    for name in names:
        slug = next((m[1] for p in patterns if (m := p.fullmatch(name))), None)
        if slug is not None and slug not in now and name not in never:
            gone[name] = slug
    # The releases' elections only where some project is not of one now.
    released = _released_slugs(cfg.root) if gone else set()
    prunable = [name for name, slug in gone.items() if slug not in released]
    kept = [name for name, slug in gone.items() if slug in released]
    return prunable, kept


def _released_slugs(root: Path) -> set[str]:
    """Return the elections of the releases.

    Those ``config/elections.toml`` lists at ``HEAD`` and at every version
    tag (``v*``) of the git repository at *root*.
    """
    slugs: set[str] = set()
    for ref in ["HEAD", *_git(root, "tag", "--list", "v*").split()]:
        path = f"{ref}:config/{config.ELECTIONS_FILE}"
        try:
            slugs |= set(tomllib.loads(_git(root, "show", path)).get("election", {}))
        except tomllib.TOMLDecodeError as e:
            raise PagesError(f"{path}: {e}") from None
    return slugs


def _git(root: Path, *args: str) -> str:
    """Run git in the repository at *root* with *args*; return its output."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        raise PagesError(
            "git not found: it tells which projects releases need"
        ) from None
    if done.returncode:
        raise PagesError(f"git {' '.join(args[:2])}: {done.stderr.strip()}")
    return done.stdout


def delete(project: str) -> int:
    """Delete the Pages project *project*; return Wrangler's exit code.

    Its deployments go with it, so nothing serves them any more.
    """
    return wrangler("pages", "project", "delete", project, "--yes")


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
    """Yield (part, name, project, key) of every election's bundles and base map.

    *part* is :data:`bundle.MAP_PART` or :data:`bundle.DATA_PART`, *name*
    an election's slug, or :data:`bundle.BASE_PART` and an extract; below
    ``dist/`` the part is at ``<part>/<name>``.
    """
    for part, project_of, by_slug in (
        (bundle.MAP_PART, cfg.site.map_project_of, keys.maps),
        (bundle.DATA_PART, cfg.site.data_project_of, keys.data),
    ):
        for election in cfg.elections:
            slug = election.slug
            yield part, slug, project_of(slug), by_slug[slug]
    for osm in cfg.bases:
        yield bundle.BASE_PART, osm, cfg.site.base_project, keys.bases[osm]


def locations(cfg: Config, keys: lock.Keys) -> build.Locations:
    """Return where the deployed data parts of *keys* are, for the app.

    Each election's bundles and each base map by the deployments that carry
    their keys, with their manifests read from there; the sources, the
    results and the live results at their domains (``site.toml``). Raises
    :class:`PagesError`
    where a part of its key is not deployed.
    """
    # *.pages.dev turns Python's own User-Agent away (403, error 1010).
    agent = {"User-Agent": fetch.user_agent(cfg.inputs.contact)}
    located: dict[str, dict[str, build.Located]] = {
        bundle.MAP_PART: {},
        bundle.DATA_PART: {},
        bundle.BASE_PART: {},
    }
    for part, name, project, key in bundles(cfg, keys):
        deployment = find(project, key)
        if deployment is None:
            raise PagesError(
                f"no deployment of {project} carries the key {key}; build and"
                " deploy the data first (`ems make`, `ems data deploy`)"
            )
        manifest = _read(f"{deployment.url}/{bundle.MANIFEST}", agent)
        if manifest.get("key") != key:
            raise PagesError(
                f"{deployment.url}/{bundle.MANIFEST}: key {manifest.get('key')},"
                f" not {key}"
            )
        located[part][name] = build.Located(deployment.url, manifest)
    return build.Locations(
        located[bundle.MAP_PART],
        located[bundle.DATA_PART],
        located[bundle.BASE_PART],
        cfg.site.results_url,
        cfg.site.live_url,
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


def _results(path: str) -> Iterator[dict[str, Any]]:
    """Yield the results of a paged list of the Pages API, page by page."""
    page = 1
    while True:
        reply = _get(f"{path}{'&' if '?' in path else '?'}page={page}")
        yield from reply["result"]
        info = reply.get("result_info") or {}
        if not reply["result"] or page >= info.get("total_pages", page):
            return
        page += 1


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
