"""The ``ems`` command line.

Each pipeline step is a subcommand registered in :func:`build_parser` with
``set_defaults(run=...)``; ``run`` receives the parsed arguments and returns
the exit code.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from election_map_slovakia import (
    __version__,
    addresses,
    basemap,
    build,
    bundle,
    candidates,
    check,
    commoncrawl,
    config,
    contests,
    crosswalk,
    division,
    fetch,
    geo,
    gpkg,
    incumbents,
    jobs,
    links,
    lists,
    lock,
    national,
    obvodrules,
    obvody,
    output,
    pages,
    progress,
    record,
    research,
    results,
    reuse,
    special,
    stamp,
    statoffice,
    store,
    xlsx,
)
from election_map_slovakia.config import ConfigError

_SKIPPED = (
    " Does nothing when its inputs, configuration and code are unchanged since"
    " it last succeeded and its output is in place, or when they are those"
    " data/outputs.toml records and its output is the one recorded there."
)


def _add_force(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even if the inputs are unchanged since the last successful run",
    )


def _add_election(
    parser: argparse.ArgumentParser,
    what: str = "run for this election only (its day or slug; default: every one)",
) -> None:
    parser.add_argument("--election", metavar="DAY", help=what)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser with every subcommand registered."""
    parser = argparse.ArgumentParser(
        prog="ems",
        description="Build the Election Map Slovakia static site from official data.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(
        title="commands", metavar="COMMAND", dest="command"
    )

    p = commands.add_parser(
        "fetch",
        help="download the official inputs into data/raw/",
        description=(
            "Download the inputs declared in config/inputs.toml into"
            " data/raw/<name>/ and record them in data/raw/manifest.json."
            " A pinned input is taken from the disk where it is there with"
            " its sha256, else from the input store, else from its source;"
            " any other is downloaded from its source, and kept as it is"
            " where the server reports it unchanged or its content is"
            " unchanged. Fails if an input fails, except an optional one"
            " (read by no step), which only warns."
        ),
    )
    p.add_argument(
        "--only",
        nargs="+",
        action="extend",
        default=[],
        metavar="NAME",
        help="fetch only these inputs",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="download without a conditional request and accept a drop in"
        " the address row count",
    )
    p.set_defaults(run=_run_fetch)

    p = commands.add_parser(
        "candidates",
        help="match the candidate lists to municipalities and merge persons",
        description=(
            "Read each election's candidate lists (config/elections.toml) and"
            " the ZBGIS municipality table from data/raw/, match every row to"
            " a municipality code, merge candidacies into persons and write"
            f" data/build/<election day>/{candidates.OUTPUT_FILE}. Fails"
            " listing every row that matches no municipality; fixes go to"
            " config/overrides.toml." + _SKIPPED
        ),
    )
    _add_force(p)
    _add_election(p)
    p.set_defaults(run=_run_candidates)

    p = commands.add_parser(
        "links",
        help="link each election's persons to those of the elections before",
        description=(
            "Read the candidates.json of every election and link the persons"
            " of each to the same persons standing in every earlier one, by"
            " name, age and area (src/election_map_slovakia/links.py), with"
            f" the corrections of config/{links.LINKS_FILE}; write"
            f" data/build/<election day>/{bundle.LINKS_DIR}/<earlier slug>.json."
            + _SKIPPED
        ),
    )
    _add_force(p)
    _add_election(p, "link this election's persons only (its day or slug)")
    p.set_defaults(run=_run_links)

    p = commands.add_parser(
        "geo",
        help="build the map geometry and obvod borders",
        description=(
            "Read ZBGIS boundary levels 0-2 from data/raw/, reproject them to"
            " WGS84 and write per-okres levels of detail of the obce and a"
            " coarse view, each a topology whose kraj, okres, regional council"
            " obvod and Bratislava and Košice city obvod borders are its obce"
            " borders, and the countries around Slovakia from Natural Earth,"
            " reaching under its ZBGIS border, to data/build/<election"
            f" day>/{geo.OUTPUT_DIR}/. Obvod membership comes from"
            " data/curated/elections/<election day>/obvody/ and is checked"
            f" against the election's {candidates.OUTPUT_FILE} (run `ems"
            " candidates` first). Council obvody and okrsky not made of"
            " cadastral areas are drawn from the addresses' points (run `ems"
            " addresses` first) by the street blocks of the election's"
            " OpenStreetMap extract. Fails if neighbouring areas do not share"
            " their borders, or the countries around leave a gap at Slovakia's."
            + _SKIPPED
        ),
    )
    p.add_argument(
        "--preview",
        metavar="OKRES",
        help="also write SVG previews (country, Bratislava, this okres and"
        " each obec in it cut by its address points, at full detail) to"
        f" data/build/<election day>/{geo.PREVIEW_DIR}/; implies --force",
    )
    _add_force(p)
    _add_election(p)
    p.set_defaults(run=_run_geo)

    p = commands.add_parser(
        "addresses",
        help="build the address search files",
        description=(
            "Read the MV SR address register from data/raw/, match every"
            " municipality to its code, assign the municipal council obvod"
            " where the municipality has only one, and write the search index"
            f" and one file per municipality to data/build/<election"
            f" day>/{addresses.OUTPUT_DIR}/. Checks every point against its"
            " municipality polygon (outliers in"
            f" {addresses.OUTSIDE_FILE} beside them) and resolves a random"
            " sample of addresses to their contests. Needs the election's"
            f" {candidates.OUTPUT_FILE} (run `ems candidates`"
            " first). Fails listing every municipality that matches no code;"
            " fixes go to config/overrides.toml." + _SKIPPED
        ),
    )
    _add_force(p)
    _add_election(p)
    p.set_defaults(run=_run_addresses)

    p = commands.add_parser(
        "basemap",
        help="build the faded base map: roads, railways, rivers, lakes, buildings",
        description=(
            "Read the OpenStreetMap extract of Slovakia from data/raw/ and"
            " write the roads by class, the railways, the rivers and larger"
            " streams and the water areas, simplified per level of detail of"
            " the obce shards and clipped to each okres (ZBGIS level 1), plus"
            " a coarse file of the motorways, major rivers and lakes for the"
            " country view, and the buildings of each obec (ZBGIS level 0), to"
            f" data/build/{config.BASE_DIR}/<extract>/{basemap.OUTPUT_DIR}/: once"
            " per extract, which every election on it shares. The layout is"
            " described in src/election_map_slovakia/basemap.py." + _SKIPPED
        ),
    )
    _add_force(p)
    _add_election(
        p,
        "run for the extract of this election only (its day or slug; default:"
        " every election's)",
    )
    p.set_defaults(run=_run_basemap)

    p = commands.add_parser(
        "build",
        help="assemble the static site in dist/, in its parts",
        description=(
            "Wipe dist/ and write the site in the parts deployed to Pages"
            " projects of their own: the app (dist/app/: the shells per"
            " language and election, the language picker, web/ assets, UI"
            " strings), each election's map bundle (dist/map/<slug>/: the"
            " geometry and address files) and data bundle"
            " (dist/data/<slug>/: the candidates split per okres, city and"
            " kraj, a name search index, research, the"
            " occupations), the base map of each extract"
            f" (dist/{bundle.BASE_PART}/<extract>/), the cached sources"
            " (dist/sources/) and the results (dist/results/). Needs the"
            " output of `candidates`, `links`, `geo` and `addresses` of every"
            " election and of `basemap` of every extract in"
            " data/build/. With --deployed, the app alone, for the data"
            f" parts deployed with the keys of {lock.LOCK_FILE}, and nothing"
            " of data/build/. The layout is described in"
            " src/election_map_slovakia/build.py and bundle.py."
        ),
    )
    p.add_argument(
        "--deployed",
        action="store_true",
        help="build the app for the deployed data parts (reads the Pages API"
        f" with the login of `npx wrangler login`, or {pages.TOKEN_ENV} and"
        f" {pages.ACCOUNT_ENV})",
    )
    p.set_defaults(run=_run_build)

    p = commands.add_parser(
        "check",
        help="verify dist/ before it is deployed",
        description=(
            "Check the site in dist/: each part's file count and the sizes"
            " against the budgets in config/site.toml, JSON validity, each"
            " part's _headers within the Cloudflare Pages limits, and for"
            " every election that every file the frontend can request"
            " exists, that every contest of its"
            f" {candidates.OUTPUT_FILE} is in the one area file the"
            " frontend looks in, that no HTML, JS or CSS of the app refers to"
            " an origin other than the data parts', and that address points"
            " lie within their municipality; an app built with --deployed is"
            " checked against the files the deployed bundles' manifests"
            " list. Prints a summary table and the first problems of each"
            " failed check; the exit code is 1 on any problem."
        ),
    )
    p.set_defaults(run=_run_check)
    p = commands.add_parser(
        "make",
        help="run every step after fetch: candidates to check",
        description=(
            f"Run {', '.join(_MAKE_STEPS)} in this order, as if each were run"
            " on its own, and stop at the first that fails. Run it after"
            " `ems fetch`, or after changing the configuration, the curated"
            " data or web/; then `ems serve` shows the result. The steps up"
            " to results run for every election of config/elections.toml, or"
            " with --election for that one; those whose inputs have not"
            " changed since they last succeeded are skipped, as are those"
            f" whose inputs and output are those {record.RECORD_FILE} records"
            " (a step that runs writes its entry there where its inputs are"
            " new); build and check always run, for the whole site."
            " `results` writes an election's final results from its"
            " `results` inputs where config/elections.toml names them;"
            " without, the election has none (`ems results` writes only"
            " live results, apart)."
        ),
    )
    _add_force(p)
    _add_election(p)
    # `geo` reads its --preview option, which `make` leaves out.
    p.set_defaults(run=_run_make, preview=None, deployed=False)

    p = commands.add_parser(
        "serve",
        help="serve dist/ over HTTP for local testing",
        description=(
            "Serve the parts in dist/ (run `ems build` first) as one site"
            " until interrupted: the app at the root, each election's bundles"
            " at /map/<slug>/ and /data/<slug>/, the final results at"
            " /results/, the live results at /live/, the cached sources at"
            " /cache/; each with the response headers of its _headers, as on"
            " Cloudflare Pages."
        ),
    )
    p.add_argument("--host", default="127.0.0.1", help="address to bind")
    p.add_argument("--port", type=int, default=8000, help="port to listen on")
    p.set_defaults(run=_run_serve)

    _add_job_parser(commands)
    _add_research_parser(commands)
    _add_results_parser(commands)
    _add_inputs_parser(commands)
    _add_data_parser(commands)
    _add_record_parser(commands)
    return parser


def _run_fetch(args: argparse.Namespace) -> int:
    cfg = config.load()
    names = [inp.name for inp in cfg.inputs.inputs]
    unknown = [name for name in args.only if name not in names]
    if unknown:
        _error(f"ems fetch: unknown input {unknown[0]!r}; known: {', '.join(names)}")
        return 2
    optional = {inp.name for inp in cfg.inputs.inputs if inp.optional}
    failed = False
    warned: list[str] = []
    width = max(map(len, names))
    try:
        for o in fetch.fetch(cfg.inputs, cfg.raw_dir, only=args.only, force=args.force):
            _print([_outcome(o, width)])
            if o.status == "failed" and o.name in optional:
                warned.append(o.name)
            elif o.status == "failed":
                failed = True
    except fetch.ManifestError as e:
        _error(f"ems: {e}")
        return 1
    if warned:
        # A record of a source that no step reads must not stop a release
        # because its server is down or turns the runner away.
        _error(
            f"ems fetch: warning: optional input(s) {', '.join(warned)} failed;"
            " no step reads them"
        )
    return 1 if failed else 0


def _outcome(o: fetch.Outcome, width: int) -> str:
    """Return the line reporting what fetching an input did."""
    size = output.format_size(o.bytes) if o.status != "failed" else ""
    return f"{o.name:<{width}}  {o.status:<9} {size:>10}  {o.detail}".rstrip()


def _add_data_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "data",
        help="the keys of the data parts, and deploying those not deployed",
        description=(
            "The data parts of the site (each election's map and data"
            " bundles, the cached sources, the results) are deployed to Pages"
            " projects of their"
            " own, each when its key (src/election_map_slovakia/lock.py) is"
            f" not deployed yet. Their keys are locked in {lock.LOCK_FILE}"
            " (lock), compared with the deployments (status) and the parts"
            " built in dist/ deployed where not (deploy), to projects, the"
            " app's among them, created once beforehand (projects). See"
            " docs/deploy.md."
        ),
    )
    sub = p.add_subparsers(title="data commands", metavar="COMMAND", required=True)
    locking = sub.add_parser(
        "lock",
        help=f"write the keys of the data parts to {lock.LOCK_FILE}",
        description=(
            "Compute the key of each data part from the repository: the pinned"
            " inputs, the configuration, the curated data and the code that"
            f" makes the data; write them to {lock.LOCK_FILE}, which is"
            " committed with every change to them."
        ),
    )
    locking.add_argument(
        "--check",
        action="store_true",
        help=f"write nothing; fail if {lock.LOCK_FILE} is not those keys",
    )
    locking.set_defaults(run=_run_data_lock)
    status = sub.add_parser(
        "status",
        help="say which data parts are not deployed with their locked key",
        description=(
            f"Compare the keys of {lock.LOCK_FILE} with the deployments (the"
            " Pages API, with the login of `npx wrangler login` or"
            f" {pages.TOKEN_ENV} and {pages.ACCOUNT_ENV}): a bundle is"
            " deployed if a deployment of its project carries its key, the"
            " sources and the results if their current deployment does."
        ),
    )
    status.add_argument(
        "--github-output",
        action="store_true",
        help="also write to the file $GITHUB_OUTPUT names (a GitHub Actions"
        " step's outputs) stale=true or stale=false, elections=, a JSON"
        " array of the days of every election, whose steps a build of the data"
        " parts needs, and extracts=, a JSON array of the extracts whose base"
        " maps it needs",
    )
    status.set_defaults(run=_run_data_status)
    deploy = sub.add_parser(
        "deploy",
        help="deploy the data parts in dist/ whose locked key is not deployed",
        description=(
            "Deploy, with Wrangler, each data part in dist/ whose key in"
            f" {lock.LOCK_FILE} is not deployed (as `ems data status` says),"
            " carrying that key; each must have been built for it (`ems"
            " make`). Parts deployed with their key are left as they are."
        ),
    )
    deploy.set_defaults(run=_run_data_deploy)
    projects = sub.add_parser(
        "projects",
        help="list the Pages projects the site needs, creating the missing"
        " with --create and deleting those no release needs with --prune",
        description=(
            "List the Pages projects the site needs (config/site.toml: the"
            " app's, each election's map and data, the base maps', the"
            " sources', the results', the live results') and which of them"
            " the account lacks, reading the"
            " Pages API as `ems data status` does, changing nothing. With"
            " --create, create those it lacks with Wrangler, for direct"
            f" uploads with the production branch {pages.PRODUCTION_BRANCH};"
            " existing ones are left as they are. The custom domains the app,"
            " the sources, the results and the live results need, and a"
            " production branch other"
            f" than {pages.PRODUCTION_BRANCH}, are listed to be set by hand"
            " (docs/deploy.md). It lists too the projects of elections"
            f" config/{config.ELECTIONS_FILE} no longer has, those a version"
            " tag still lists kept (a rollback to that release needs them);"
            " with --prune, delete the others with their deployments. The"
            " app's project, the base maps', the sources', the results' and"
            " the live results' are"
            " never deleted, nor any project not named like an election's"
            " bundle."
        ),
    )
    projects.add_argument(
        "--create",
        action="store_true",
        help="create the projects the account lacks",
    )
    projects.add_argument(
        "--prune",
        action="store_true",
        help="delete the projects of elections no release has any more",
    )
    projects.set_defaults(run=_run_data_projects)


def _run_data_lock(args: argparse.Namespace) -> int:
    cfg = config.load()
    path = cfg.root / lock.LOCK_FILE
    try:
        keys = lock.keys(cfg)
        # Only the check reads the lock: writing replaces it, whatever it
        # held, even in a format of before.
        locked = lock.read(path) if args.check else None
    except lock.LockError as e:
        _error(f"ems data lock: {e}")
        return 1
    if args.check:
        if locked != keys:
            _error(
                f"ems data lock: {lock.LOCK_FILE} is not the keys of the data;"
                " run `ems data lock` and commit it"
            )
            return 1
        _print([f"{lock.LOCK_FILE} is up to date"])
        return 0
    output.write_file(path, lock.render(keys).encode())
    _print([lock.render(keys).rstrip()])
    return 0


class _Part(NamedTuple):
    """A data part, its locked key and whether that is deployed."""

    directory: str
    """Below dist/."""
    project: str
    key: str
    deployed: pages.Deployment | None
    """The deployment that carries the key, None if none does."""


def _parts(cfg: config.Config) -> list[_Part]:
    """Return the data parts, by the keys of the committed lock."""
    keys = lock.read(cfg.root / lock.LOCK_FILE)
    if keys is None:
        raise ConfigError(f"{lock.LOCK_FILE} missing; run `ems data lock`")
    parts = [
        _Part(f"{part}/{name}", project, key, pages.find(project, key))
        for part, name, project, key in pages.bundles(cfg, keys)
    ]
    for directory, project, key in (
        (bundle.SOURCES_PART, cfg.site.sources_project, keys.sources),
        (bundle.RESULTS_PART, cfg.site.results_project, keys.results),
    ):
        live = pages.current(project)
        parts.append(
            _Part(directory, project, key, live if live and live.key == key else None)
        )
    return parts


def _run_data_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        parts = _parts(cfg)
    except pages.PagesError as e:
        _error(f"ems data status: {e}")
        return 1
    width = max(len(p.directory) for p in parts)
    _print(
        f"{p.directory:<{width}}  {p.key}  "
        + (
            f"deployed {p.deployed.url}"
            if p.deployed
            else f"not deployed ({p.project})"
        )
        for p in parts
    )
    stale = any(p.deployed is None for p in parts)
    if args.github_output:
        days = [e.day.isoformat() for e in cfg.elections]
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as f:
            f.write(f"stale={'true' if stale else 'false'}\n")
            f.write(f"elections={json.dumps(days)}\n")
            f.write(f"extracts={json.dumps(list(cfg.bases))}\n")
    return 0


def _run_data_deploy(_args: argparse.Namespace) -> int:
    cfg = config.load()
    dist = cfg.root / build.OUTPUT_DIR
    try:
        parts = _parts(cfg)
    except pages.PagesError as e:
        _error(f"ems data deploy: {e}")
        return 1
    for part in parts:
        if part.deployed is not None:
            _print([f"{part.directory}: {part.key} deployed, {part.deployed.url}"])
            continue
        directory = dist / part.directory
        manifest = directory / bundle.MANIFEST
        built = json.loads(manifest.read_bytes()) if manifest.is_file() else {}
        if built.get("key") != part.key or "url" in built:
            _error(
                f"ems data deploy: dist/{part.directory} is not built for the key"
                f" {part.key}; run `ems make`"
            )
            return 1
        _print([f"{part.directory}: deploying {part.key} to {part.project}"])
        code = pages.deploy(directory, part.project, part.key)
        if code:
            _error(f"ems data deploy: Wrangler failed with exit code {code}")
            return code
    return 0


def _run_data_projects(args: argparse.Namespace) -> int:
    cfg = config.load()
    need = pages.needed(cfg)
    try:
        have = pages.projects()
        prunable, kept = pages.unneeded(cfg, have)
    except pages.PagesError as e:
        _error(f"ems data projects: {e}")
        return 1
    states = {
        **{name: "exists" if name in have else "missing" for name in need},
        **dict.fromkeys(kept, "kept (an earlier release has it)"),
        **dict.fromkeys(prunable, "unneeded"),
    }
    width = max(map(len, states))
    _print(f"{name:<{width}}  {state}" for name, state in states.items())
    missing = [name for name in need if name not in have]
    for names, wanted, option, act, verb, state in (
        (missing, args.create, "--create", pages.create, "creating", "missing"),
        (prunable, args.prune, "--prune", pages.delete, "deleting", "unneeded"),
    ):
        if names and not wanted:
            _print([f"{len(names)} {state}; `ems data projects {option}` for them"])
            continue
        for name in names:
            _print([f"{name}: {verb}"])
            if code := act(name):
                _error(f"ems data projects: Wrangler failed with exit code {code}")
                return code
    # Wrangler deploys every part as the production branch: elsewhere it
    # would be a preview, which neither the app nor the domains serve.
    manual = [
        f"{name}: production branch {project.production_branch}, not"
        f" {pages.PRODUCTION_BRANCH}"
        for name in need
        if (project := have.get(name))
        and project.production_branch != pages.PRODUCTION_BRANCH
    ]
    # The Pages token may not edit DNS, and a domain must not be attached
    # before its zone is on Cloudflare: domains stay a step by hand.
    manual += [
        f"{name}: custom domain {domain}"
        for name, domains in need.items()
        for domain in domains
        if name not in have or domain not in have[name].domains
    ]
    if manual:
        _print(["by hand (docs/deploy.md):", *(f"  {step}" for step in manual)])
    return 0


def _add_record_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "record",
        help=f"check {record.RECORD_FILE} against the commit, or the outputs"
        " against it",
        description=(
            f"{record.RECORD_FILE} records, for each step of `ems make` before"
            " build and each election (of basemap each extract), the digest of"
            " its inputs and of the output it made of them: `ems make` skips a"
            " step whose inputs and output are those recorded. The steps write"
            " it (docs/pipeline.md)."
        ),
    )
    sub = p.add_subparsers(title="record commands", metavar="COMMAND", required=True)
    checking = sub.add_parser(
        "check",
        help=f"fail if {record.RECORD_FILE} does not have the inputs of the commit",
        description=(
            "Compute the inputs of every step from the repository alone (the"
            " code, uv.lock, .python-version, the pins of config/inputs.toml,"
            " the configuration, the curated data, and the output of each"
            " upstream step as the record has it), without data/raw/ or"
            " data/build/, and fail naming each step, election and part of"
            " the inputs that is not as recorded: run `ems make` and commit"
            " the record. CI runs it."
        ),
    )
    checking.set_defaults(run=_run_record_check)
    comparing = sub.add_parser(
        "compare",
        help="say which outputs in data/build/ are not those"
        f" {record.RECORD_FILE} records",
        description=(
            "Compute the digest of each step's output in data/build/ and say"
            " where it is not the one recorded, and whether the step's inputs"
            " here are the recorded ones; succeed all the same. A release runs"
            " it after building every step (docs/deploy.md)."
        ),
    )
    comparing.add_argument(
        "--github",
        action="store_true",
        help="where any output differs, also write a GitHub Actions warning"
        " annotation and a job summary (to the file $GITHUB_STEP_SUMMARY names)",
    )
    comparing.set_defaults(run=_run_record_compare)


def _declarations(cfg: config.Config) -> Iterator[tuple[str, str, _Declared]]:
    """Yield each step of the record, its election's day (or extract), its declaration.

    In the order of `make`: an upstream step before the steps that read it.
    """
    for step, declare in (
        ("candidates", _candidates_declared),
        ("links", _links_declared),
        ("addresses", _addresses_declared),
        ("geo", _geo_declared),
    ):
        # A by-election's candidates read its term's (`_term_councils`).
        order = reversed(cfg.elections) if step == "candidates" else cfg.elections
        for e in order:
            yield step, e.day.isoformat(), declare(cfg, e)
    for osm, base in cfg.bases.items():
        yield "basemap", osm, _basemap_declared(cfg, base)
    for e in reversed(cfg.elections):
        declared = _results_declared(cfg, e)
        if declared is not None:
            yield "results", e.day.isoformat(), declared


def _run_record_check(_args: argparse.Namespace) -> int:
    cfg = config.load()
    recorded = record.read(cfg.root / record.RECORD_FILE)
    problems: list[str] = []
    checked = 0
    for step, key, declared in _declarations(cfg):
        checked += 1
        old = recorded.get((step, key))
        if old is None:
            problems.append(f"{step} {key}: no entry")
            continue
        try:
            now = record.entry(_inputs_of(cfg, step, declared, recorded), old.outputs)
        except record.RecordError as e:
            problems.append(f"{step} {key}: {e}")
            continue
        if now.inputs != old.inputs:
            differ = record.differing(old, now) or ["the inputs"]
            problems.append(f"{step} {key}: not as recorded: {', '.join(differ)}")
    if problems:
        _error(
            f"ems record check: {record.RECORD_FILE} does not have the inputs of"
            " these steps at this commit; run `ems make` and commit it:"
        )
        for problem in problems:
            _error(f"  {problem}")
        return 1
    _print([f"{record.RECORD_FILE} has the inputs of all {checked} steps"])
    stale = sorted(recorded.keys() - _record_keys(cfg))
    if stale:
        progress.note(
            "entries of no step, which the next step that runs drops: "
            + ", ".join(f"{step} {key}" for step, key in stale)
        )
    return 0


def _run_record_compare(args: argparse.Namespace) -> int:
    cfg = config.load()
    recorded = record.read(cfg.root / record.RECORD_FILE)
    differ: list[tuple[str, str, str]] = []
    count = 0
    for step, key, declared in _declarations(cfg):
        count += 1
        old = recorded.get((step, key))
        missing = [p.name for p in declared.outputs if not p.exists()]
        if old is None:
            differ.append((step, key, "no entry"))
        elif missing:
            differ.append((step, key, f"{', '.join(missing)} missing"))
        else:
            with progress.stage(f"{step} {key}"):
                outputs = _on_disk(cfg, step, key)
                if outputs == old.outputs:
                    continue
                here = record.entry(_inputs_of(cfg, step, declared), outputs)
                parts = record.differing(old, here)
            inputs = (
                f"its inputs too ({', '.join(parts)})" if parts else "not its inputs"
            )
            differ.append((step, key, f"the output differs, {inputs}"))
    _print(f"{step} {key}: {what}" for step, key, what in differ)
    _print([f"{count - len(differ)} of {count} outputs are those recorded"])
    if args.github and differ:
        # Not a failure: the release builds on x86-64, the record is written
        # where `ems make` ran, mostly aarch64, and output alike byte for
        # byte on both is not verified; the deployed parts are keyed by the
        # repository (lock.py), not by this record. A difference only means
        # the record does not let a machine like this one skip the step.
        _print(
            [
                f"::warning title={record.RECORD_FILE}::{len(differ)} of {count}"
                " step outputs built here are not those recorded (see the job"
                " summary)"
            ]
        )
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            rows = [f"| {step} | {key} | {what} |" for step, key, what in differ]
            text = [
                f"## Outputs not as `{record.RECORD_FILE}` records",
                "",
                f"{len(differ)} of {count} step outputs built here are not those"
                " recorded. Not a failure: the deployed parts are keyed by the"
                " repository, and output alike byte for byte on this runner and"
                " where the record was written is not verified; a difference"
                " only means the record does not let a machine like this one"
                " skip the step.",
                "",
                "| Step | Election or extract | Difference |",
                "|---|---|---|",
                *rows,
            ]
            with Path(summary).open("a", encoding="utf-8") as f:
                f.write("\n".join(text) + "\n")
    return 0


def _add_inputs_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "inputs",
        help="pin inputs anew and publish them to the input store",
        description=(
            "Pin what the sources of inputs serve now (update), and upload"
            " the pinned files the input store lacks (publish): the release"
            " named by `store` in config/inputs.toml. See docs/pipeline.md."
        ),
    )
    sub = p.add_subparsers(title="inputs commands", metavar="COMMAND", required=True)
    update = sub.add_parser(
        "update",
        help="download inputs from their sources and pin what they serve",
        description=(
            "Download each named input from its source, whatever its pin,"
            " check it as `ems fetch` does and keep it in data/raw/. If its"
            " sha256 differs from the pin, write the new sha256 and the day"
            " it was retrieved into config/inputs.toml. Then `ems inputs"
            " publish` uploads the new file and `ems data lock` records"
            " which data it changes."
        ),
    )
    update.add_argument("names", nargs="+", metavar="NAME", help="the inputs to pin")
    update.add_argument(
        "--force",
        action="store_true",
        help="download without a conditional request and accept a drop in"
        " the address row count",
    )
    update.set_defaults(run=_run_inputs_update)
    publish = sub.add_parser(
        "publish",
        help="upload the pinned files the input store lacks",
        description=(
            "Upload every pinned input whose file the input store lacks, from"
            " data/raw/, as the asset <sha256>-<file> of its release, with"
            " the GitHub CLI (`gh`, logged in as a user who may write to the"
            " repository's releases). Assets already there are left as they"
            " are, so running it again uploads nothing. Where the release does"
            " not exist yet, it is created first, as a pre-release."
        ),
    )
    publish.add_argument(
        "--prune",
        action="store_true",
        help="then delete the assets no build needs any more: those that"
        " config/inputs.toml pins neither now nor at HEAD nor at any version"
        " tag (v*)",
    )
    publish.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be uploaded (and with --prune deleted), changing nothing",
    )
    publish.set_defaults(run=_run_inputs_publish)


def _run_inputs_update(args: argparse.Namespace) -> int:
    cfg = config.load()
    known = {inp.name: inp for inp in cfg.inputs.inputs}
    unknown = [name for name in args.names if name not in known]
    if unknown:
        _error(f"ems inputs update: unknown input {unknown[0]!r}")
        return 2
    path = cfg.root / "config" / config.INPUTS_FILE
    width = max(map(len, args.names))
    pinned = 0
    for name in args.names:
        inp = known[name]
        try:
            outcome, entry = fetch.update(
                cfg.inputs, cfg.raw_dir, inp, force=args.force
            )
        except (fetch.FetchError, fetch.ManifestError) as e:
            _error(f"ems inputs update: {name}: {e}")
            return 1
        _print([_outcome(outcome, width)])
        if entry["sha256"] == inp.sha256:
            _print([f"  pin unchanged, retrieved {inp.retrieved}"])
            continue
        retrieved = dt.date.fromisoformat(entry["retrieved_at"][:10])
        store.write_pin(path, name, entry["sha256"], retrieved)
        _print(
            [
                f"  pinned {entry['sha256']}, retrieved {retrieved}",
                f"  (was {inp.sha256 or 'not pinned'})",
            ]
        )
        pinned += 1
    if pinned:
        _print(
            [
                f"wrote config/{config.INPUTS_FILE}; next `ems inputs publish`,"
                " `ems make`, `ems data lock`, then commit"
            ]
        )
    return 0


def _run_inputs_publish(args: argparse.Namespace) -> int:
    cfg = config.load()
    would = "would upload" if args.dry_run else "uploaded"
    uploaded = deleted = 0
    try:
        for inp in store.publish(cfg.inputs, cfg.raw_dir, args.dry_run):
            _print([f"{would} {store.Store.asset(inp)}"])
            uploaded += 1
        if args.prune:
            keep = store.kept(cfg.root, cfg.inputs)
            for name in store.prune(cfg.inputs, keep, args.dry_run):
                _print([f"{'would delete' if args.dry_run else 'deleted'} {name}"])
                deleted += 1
    except store.StoreError as e:
        _error(f"ems inputs publish: {e}")
        return 1
    lines = [f"{uploaded} file(s) {would}" if uploaded else "the store has them all"]
    if args.prune:
        verb = "would be deleted" if args.dry_run else "deleted"
        lines.append(f"{deleted} asset(s) {verb}" if deleted else "none to delete")
    _print(lines)
    return 0


def _run_candidates(args: argparse.Namespace) -> int:
    # A by-election reads its term's candidates (`_term_councils`).
    return _per_election(args, _candidates, oldest_first=True)


def _candidates(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    declared = _candidates_declared(cfg, election)
    run = _stamp(cfg, "candidates", election.day.isoformat(), args.force, declared)
    if run is None:
        return 0
    named = election.candidates.inputs if election.candidates else {}
    lists_in = {name: _input(cfg, inp) for name, inp in named.items()}
    source = election.incumbents
    results = {name: _input(cfg, name) for name in source.inputs} if source else {}
    zbgis = _input(cfg, election.zbgis[0])
    [out] = declared.outputs
    try:
        with progress.stage("reading the candidate lists"):
            read = lists.read(
                election,
                {k: raw.path for k, raw in lists_in.items()},
                cfg.election_dir(election),
                urls={k: raw.inp.url for k, raw in lists_in.items()},
                term=_term_councils(cfg, election),
            )
        result = candidates.build(
            read,
            _extract_gpkg(cfg, zbgis),
            cfg.overrides[election.slug],
            (source, {name: raw.path for name, raw in results.items()})
            if source
            else None,
            election.day,
        )
    except (
        candidates.CandidatesError,
        incumbents.IncumbentsError,
        statoffice.StatOfficeError,
        gpkg.GpkgError,
        xlsx.XlsxError,
    ) as e:
        _error(f"ems candidates: {e}")
        return 1
    with progress.stage(f"writing {out.name}"):
        size = candidates.write(result, out)
    _done(run)
    _print(candidates.report(result))
    _print([f"wrote {out.relative_to(cfg.root)} ({output.format_size(size)})"])
    return 0


def _candidates_declared(cfg: config.Config, election: config.Election) -> _Declared:
    """Return what `candidates` reads and writes of *election*.

    Of a by-election also its term's candidates (:func:`_term_councils`).
    """
    named = election.candidates.inputs if election.candidates else {}
    source = election.incumbents
    curated = cfg.election_dir(election) / lists.CURATED_FILE
    files: list[Path] = []
    if election.candidates and election.candidates.format == "curated":
        if not curated.is_file():
            raise ConfigError(f"{curated} missing: the election's lists are curated")
        files.append(curated)
    elif (
        election.candidates
        and election.candidates.format == "susr-by"
        and curated.is_file()
    ):
        # A by-election's package of 2019–2022 may have a supplement.
        files.append(curated)
    uncontested = cfg.election_dir(election) / lists.UNCONTESTED_FILE
    if uncontested.is_file():
        files.append(uncontested)
    term = cfg.term(election)
    return _Declared(
        *_outputs(cfg, "candidates", election.day.isoformat()),
        pins=[
            _pin(cfg, name)
            for name in (
                *named.values(),
                *(source.inputs if source else ()),
                election.zbgis[0],
            )
        ],
        curated=files,
        values={
            "overrides": cfg.overrides[election.slug],
            "election": election.day,
            "kind": election.kind,
            "candidates": election.candidates,
            "incumbents": source,
            # What the configuration says of the contests (lists.read).
            "contests": [
                election.second_round,
                election.questions,
                election.seats,
                election.threshold,
                election.coalition_thresholds,
                election.preferences,
                election.preference_quota,
            ],
        },
        upstream=(("candidates", term.day.isoformat()),) if term else (),
    )


def _term_councils(cfg: config.Config, election: config.Election) -> lists.Term | None:
    """Return what a by-election's term's candidates say of its councils.

    Their obvody (the council whose seats a by-election proper fills was
    elected in them: its lists name where the seats called lie) and seats
    in all, which tell a council elected anew; None of any other election.
    """
    term = cfg.term(election)
    if term is None:
        return None
    data = json.loads(_built_candidates(cfg, term).read_bytes())
    return lists.Term(
        addresses.council_obvody(data["contests"]),
        {o["code"]: o["council_seats"] for o in data["obce"] if "council_seats" in o},
    )


def _run_links(args: argparse.Namespace) -> int:
    return _per_election(args, _links)


def _links(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    """Link *election*'s persons to those of every election before it."""
    earlier = [e for e in cfg.elections if e.day < election.day]
    built = {e.slug: _built_candidates(cfg, e) for e in [election, *earlier]}
    declared = _links_declared(cfg, election)
    run = _stamp(cfg, "links", election.day.isoformat(), args.force, declared)
    if run is None:
        return 0
    [out] = declared.outputs
    overrides = _links_overrides(cfg)
    later = links.read(built[election.slug], election.day)
    files: dict[str, bytes] = {}
    for e in earlier:
        with progress.stage(f"linking to the persons of {e.day}"):
            try:
                linked = links.match(
                    later,
                    links.read(built[e.slug], e.day),
                    overrides.get((election.slug, e.slug)),
                )
            except links.LinksError as err:
                _error(f"ems links: {err}")
                return 1
        files[f"{e.slug}.json"] = output.to_json(links.to_json(linked)) + b"\n"
        _print(links.report(linked))
    with output.replacing(out) as tmp:
        for name, blob in files.items():
            (tmp / name).write_bytes(blob)
    _done(run)
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(files)} files)"])
    return 0


def _links_declared(cfg: config.Config, election: config.Election) -> _Declared:
    """Return what `links` reads and writes of *election*.

    The candidates of the election and of every one before it.
    """
    earlier = [e for e in cfg.elections if e.day < election.day]
    overrides = _links_overrides(cfg)
    return _Declared(
        *_outputs(cfg, "links", election.day.isoformat()),
        pins=[],
        curated=[],
        values={
            "earlier": [e.slug for e in earlier],
            "overrides": {
                e.slug: overrides.get((election.slug, e.slug)) for e in earlier
            },
        },
        upstream=tuple(("candidates", e.day.isoformat()) for e in [election, *earlier]),
    )


def _links_overrides(
    cfg: config.Config,
) -> dict[tuple[str, str], links.Overrides]:
    """Return the corrections of config/links.toml, by later and earlier slug."""
    return links.load_overrides(
        cfg.root / "config" / links.LINKS_FILE, {e.slug: e.day for e in cfg.elections}
    )


def _per_election(
    args: argparse.Namespace,
    step: Callable[[config.Config, config.Election, argparse.Namespace], int],
    *,
    oldest_first: bool = False,
) -> int:
    """Run *step* for the election of ``--election``, else for every one.

    Each as a stage of its own, newest first unless *oldest_first* (a step
    that reads an earlier election's output); stops at the first that fails.
    """
    cfg = config.load()
    chosen = [cfg.election(args.election)] if args.election else cfg.elections
    for election in reversed(chosen) if oldest_first else chosen:
        with progress.stage(f"election {election.day}") as stage:
            code = step(cfg, election, args)
            stage.failed = code != 0
        if code:
            return code
    return 0


class _Raw(NamedTuple):
    """A downloaded input file and its entry in config/inputs.toml."""

    path: Path
    inp: config.Input


def _pin(cfg: config.Config, name: str) -> config.Input:
    """Return the entry of config/inputs.toml of input *name*, which a step reads."""
    inp = next((i for i in cfg.inputs.inputs if i.name == name), None)
    if inp is None:
        raise ConfigError(f"config/{config.INPUTS_FILE}: input {name!r} missing")
    # fetch lets an optional input fail, so no step may depend on one.
    if inp.optional:
        raise ConfigError(
            f"config/{config.INPUTS_FILE}: input {name!r} is optional, so no"
            " step may read it"
        )
    return inp


def _input(cfg: config.Config, name: str) -> _Raw:
    inp = _pin(cfg, name)
    path = fetch.member_path(cfg.raw_dir, inp)
    if not path.is_file():
        raise ConfigError(f"{path} missing; run `ems fetch` first")
    return _Raw(path, inp)


def _extract_gpkg(cfg: config.Config, raw: _Raw) -> Path:
    """Return the GeoPackage of a ZBGIS input, unpacked into data/build/.

    Shared by every election that reads the input: it is the input's.
    """
    return gpkg.extract(raw.path, raw.inp.members[0], cfg.build_dir)


def _shared_dir(build_dir: Path, name: str) -> Path:
    """Return the directory of cache *name*, shared by the elections and runs.

    data/build/shared/<name>/ (*build_dir* is data/build/): what several
    elections compute alike, made once (keyed on all it depends on).
    """
    return build_dir / "shared" / name


class _Declared(NamedTuple):
    """What a step reads and writes of one election, or of one extract.

    Declared from the configuration alone, without data/raw/ or
    data/build/, so that `ems record check` computes the inputs of every
    step from a commit (:func:`_inputs_of`). A step reads nothing else:
    an upstream output it reads and does not declare would leave it
    skipped where that output changed.
    """

    directory: Path
    """The build directory of the election or extract: its stamp's."""
    outputs: list[Path]
    """What it writes (:func:`_outputs`)."""
    pins: list[config.Input]
    """The downloads it reads, which enter by their pin."""
    curated: list[Path]
    """The curated files and directories it reads."""
    values: dict[str, object]
    """The configuration it gets, by name."""
    upstream: tuple[record.Key, ...] = ()
    """The steps whose output it reads, each with the election's day."""


# The outputs of the steps below the build directory of an election: files
# each run writes whole, and directories each run replaces whole
# (output.replacing), so that nothing of a run before stays in them.
_OUTPUTS = {
    "candidates": (candidates.OUTPUT_FILE,),
    "links": (bundle.LINKS_DIR,),
    "addresses": (addresses.OUTPUT_DIR, addresses.OUTSIDE_FILE, addresses.OBVOD_DIR),
    "geo": (geo.OUTPUT_DIR,),
}


def _outputs(cfg: config.Config, step: str, key: str) -> tuple[Path, list[Path]]:
    """Return the directory of the stamp of *step* for *key*, and its outputs.

    *key* is an election's day, of ``basemap`` an extract. The outputs are
    what the output record digests: what a run makes of its inputs alone,
    not the gzip sizes it measured (gzip-sizes/, a memo), `geo`'s previews
    nor the caches of data/build/shared/. `results` writes its directory
    whole (results.write) and the crosswalk to each election before beside
    it, a file each.
    """
    if step == "basemap":
        directory = cfg.base_build_dir(key)
        return directory, [directory / basemap.OUTPUT_DIR]
    election = cfg.election(key)
    directory = cfg.election_build_dir(election)
    if step != "results":
        return directory, [directory / name for name in _OUTPUTS[step]]
    walk = [_crosswalk_file(cfg, election, e) for e, _ in _earlier(cfg, election)]
    return directory, [cfg.results_dir(election), *walk]


def _inputs_of(
    cfg: config.Config,
    step: str,
    declared: _Declared,
    recorded: Mapping[record.Key, record.Entry] | None = None,
) -> dict[str, object]:
    """Return the inputs of *step* as *declared*, by part (:data:`stamp.PARTS`).

    As they are here (*recorded* None): the running Python, an upstream
    output as it is on disk, an input not pinned by its file. Else as a
    commit has them, for `ems record check`: the Python of .python-version
    and an upstream output as *recorded*; every input pinned.
    """
    if recorded is None:
        python = stamp.PYTHON
        upstream = {f"{s} {k}": _on_disk(cfg, s, k) for s, k in declared.upstream}
    else:
        python = stamp.pinned_python(cfg.root)
        upstream = {}
        for s, k in declared.upstream:
            if (s, k) not in recorded:
                raise record.RecordError(f"{s} {k}, whose output it reads, has none")
            upstream[f"{s} {k}"] = recorded[s, k].outputs
    curated: dict[str, str | None] = {}
    for p in declared.curated:
        name = p.relative_to(cfg.root).as_posix()
        # A directory by its files alone, and one with none as if missing (an
        # election may have no rule sets, obvody/, at all): git keeps no
        # empty directory, so one left here would make inputs no commit has.
        if p.is_dir() and any(f.is_file() for f in p.rglob("*")):
            curated[f"{name}/"] = stamp.tree_digest(p)
        else:
            curated[name] = stamp.file_digest(p) if p.is_file() else None
    return {
        "code": stamp.code_digest(step),
        "python": python,
        "libraries": stamp.json_digest(stamp.libraries(cfg.root / "uv.lock")),
        "pins": {
            inp.name: _pin_digest(cfg, inp, here=recorded is None)
            for inp in declared.pins
        },
        "curated": curated,
        "config": {name: stamp.json_digest(v) for name, v in declared.values.items()},
        "upstream": upstream,
    }


def _pin_digest(cfg: config.Config, inp: config.Input, *, here: bool) -> str:
    """Return the digest of input *inp* as a step's inputs have it.

    Its entry of config/inputs.toml with its pin: `ems fetch` makes the
    file the one pinned. An input not pinned yet is known *here* by its
    file too, and not at all from a commit.
    """
    if inp.sha256:
        return stamp.json_digest(inp)
    if not here:
        raise record.RecordError(f"input {inp.name} is not pinned")
    return stamp.json_digest([inp, stamp.file_digest(_input(cfg, inp.name).path)])


def _on_disk(cfg: config.Config, step: str, key: str) -> str:
    """Return the digest of the output of *step* for *key* as it is on disk.

    Read again only where its files are not those its stamp has
    (:func:`stamp.on_disk`).
    """
    directory, outputs = _outputs(cfg, step, key)
    recorded = stamp.recorded_outputs(_stamp_path(directory, step))
    return stamp.on_disk(directory, outputs, recorded)[0]


class _Run(NamedTuple):
    """A step about to run for an election or extract, and what it records then."""

    cfg: config.Config
    step: str
    key: str
    local: stamp.Stamp
    entry: record.Entry | None
    """The record's entry when the step was found to need running."""


def _stamp(
    cfg: config.Config, step: str, key: str, force: bool, declared: _Declared
) -> _Run | None:
    """Return the run of *step* for *key*, or None if its output is up to date.

    *key* is the election's day, or the extract of a base map. Up to date
    as its stamp has it (the inputs of its last run here, and the output
    it wrote then), or as the output record has it: its inputs recorded
    there and its output on disk the one recorded, the stamp then taking
    the inputs (after a pull of a change that left its output as it was).
    """
    with progress.stage("comparing the inputs with the last successful run"):
        local = stamp.Stamp(
            _stamp_path(declared.directory, step),
            _inputs_of(cfg, step, declared),
            declared.directory,
            declared.outputs,
        )
        changes = local.changes()
        entry = record.read(cfg.root / record.RECORD_FILE).get((step, key))
        if not (changes or force):
            progress.note(f"up to date, skipped (`ems {step} --force` runs it anyway)")
            return None
        if (
            not force
            and entry is not None
            and entry.inputs == local.digest
            and not local.missing()
            and local.outputs_digest() == entry.outputs
        ):
            local.record()
            progress.note(
                f"up to date per {record.RECORD_FILE}, skipped (`ems {step}"
                " --force` runs it anyway)"
            )
            return None
    progress.note("running: " + ("--force" if force else "; ".join(changes)))
    local.forget()
    return _Run(cfg, step, key, local, entry)


def _done(run: _Run) -> None:
    """Record what *run* made: in its stamp, and in the record if its inputs are new.

    Where the record has its inputs already with another output, the step
    made something else of the same inputs: its output varies from run to
    run or from machine to machine, or the entry is wrong. A warning says
    so and the entry stays.
    """
    new = record.entry(run.local.inputs, run.local.record())
    old = run.entry
    if old is None or old.inputs != new.inputs:
        path = run.cfg.root / record.RECORD_FILE
        record.update(path, (run.step, run.key), new, _record_keys(run.cfg))
    elif old.outputs != new.outputs:
        _error(
            f"warning: ems {run.step} {run.key}: the output is not the one"
            f" {record.RECORD_FILE} records for the same inputs, which it keeps:"
            " the step's output varies, or the entry is wrong (remove it and run"
            " the step again to record this output)"
        )


def _record_keys(cfg: config.Config) -> set[record.Key]:
    """Return the steps and elections (or extracts) of the output record."""
    days = [e.day.isoformat() for e in cfg.elections]
    return {
        *((step, day) for step in _OUTPUTS for day in days),
        *(("basemap", osm) for osm in cfg.bases),
        *(("results", e.day.isoformat()) for e in cfg.elections if e.results.inputs),
    }


def _stamp_path(directory: Path, step: str) -> Path:
    """Return where *step* records its last successful run in *directory*."""
    return directory / f"{step}.stamp.json"


def _run_geo(args: argparse.Namespace) -> int:
    return _per_election(args, _geo)


def _geo(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    built = _built_candidates(cfg, election)
    directory = cfg.election_build_dir(election)
    places = directory / addresses.OBVOD_DIR
    if not places.is_dir():
        raise ConfigError(f"{places} missing; run `ems addresses` first")
    declared = _geo_declared(cfg, election)
    force = args.force or bool(args.preview)
    run = _stamp(cfg, "geo", election.day.isoformat(), force, declared)
    if run is None:
        return 0
    zbgis = {level: _input(cfg, name) for level, name in enumerate(election.zbgis)}
    countries = _input(cfg, geo.NEIGHBOURS_INPUT)
    osm = _input(cfg, election.osm)
    curated = cfg.election_dir(election)
    [out] = declared.outputs
    data = json.loads(built.read_bytes())
    counts = Counter(c["contest"] for c in data["candidacies"])
    # What the shared results of every election depend on: the code with
    # Python and the libraries, and the inputs they are made of, as the
    # stamp has them.
    inputs = run.local.inputs
    cache = geo.Cache(
        _shared_dir(cfg.build_dir, "geo"),
        stamp.json_digest([inputs["code"], inputs["python"], inputs["libraries"]]),
        stamp.json_digest(
            [
                _pin_digest(cfg, raw.inp, here=True)
                for raw in (*zbgis.values(), countries)
            ]
        ),
    )
    try:
        paths = {level: _extract_gpkg(cfg, raw) for level, raw in zbgis.items()}
        # As the review sheets read them (obvodrules.barriers); the stamp
        # has the extract's pin already.
        lines = basemap.barriers(
            osm.path, cfg.build_dir, _shared_dir(cfg.build_dir, basemap.BARRIERS_DIR)
        )
        result = geo.build(
            paths,
            countries.path,
            curated,
            places,
            data["contests"],
            counts,
            lines,
            partial=election.kind == config.BY_ELECTION,
            cache=cache,
        )
        previews = []
        if args.preview:
            with progress.stage("drawing the SVG previews"):
                previews = geo.preview(
                    result, args.preview, directory / geo.PREVIEW_DIR
                )
    except (
        basemap.BaseMapError,
        geo.GeoError,
        gpkg.GpkgError,
        obvody.ObvodyError,
    ) as e:
        _error(f"ems geo: {e}")
        return 1
    sizes = geo.write(result, out)
    _done(run)
    _print(geo.report(result, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes)} files)"])
    _print(f"wrote {path.relative_to(cfg.root)}" for path in previews)
    return 0


def _geo_declared(cfg: config.Config, election: config.Election) -> _Declared:
    """Return what `geo` reads and writes of *election*.

    The contests of its candidates and the addresses of the obce whose
    obvody or okrsky are drawn from them (obvod-addresses/).
    """
    day = election.day.isoformat()
    return _Declared(
        *_outputs(cfg, "geo", day),
        pins=[
            *(_pin(cfg, name) for name in election.zbgis),
            _pin(cfg, geo.NEIGHBOURS_INPUT),
            _pin(cfg, election.osm),
        ],
        curated=[
            *_okrsky_files(cfg, election),
            cfg.election_dir(election) / obvody.DIRECTORY,
        ],
        values={"partial": election.kind == config.BY_ELECTION},
        upstream=(("candidates", day), ("addresses", day)),
    )


def _run_basemap(args: argparse.Namespace) -> int:
    """Make the base map of each extract, or of ``--election``'s, once each."""
    cfg = config.load()
    chosen = [cfg.election(args.election)] if args.election else cfg.elections
    for osm in dict.fromkeys(e.osm for e in chosen):
        with progress.stage(f"extract {osm}") as stage:
            code = _basemap(cfg, cfg.bases[osm], args)
            stage.failed = code != 0
        if code:
            return code
    return 0


def _basemap(cfg: config.Config, base: config.Base, args: argparse.Namespace) -> int:
    declared = _basemap_declared(cfg, base)
    run = _stamp(cfg, "basemap", base.osm, args.force, declared)
    if run is None:
        return 0
    osm = _input(cfg, base.osm)
    okresy = _input(cfg, base.okresy)
    obce = _input(cfg, base.obce)
    [out] = declared.outputs
    try:
        files = basemap.build(
            osm.path,
            _extract_gpkg(cfg, okresy),
            _extract_gpkg(cfg, obce),
            cfg.build_dir,
        )
    except (basemap.BaseMapError, geo.GeoError, gpkg.GpkgError) as e:
        _error(f"ems basemap: {e}")
        return 1
    data = {path: file.data for path, file in files.items()}
    sizes = basemap.write(data, out, _gzip_memo(declared.directory, "basemap"))
    _done(run)
    _print(basemap.report(files, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes)} files)"])
    return 0


def _basemap_declared(cfg: config.Config, base: config.Base) -> _Declared:
    """Return what `basemap` reads and writes of extract *base*.

    libosmium, which assembles the water areas and multipolygon buildings,
    comes with pyosmium's wheel: a library of uv.lock like the others.
    """
    return _Declared(
        *_outputs(cfg, "basemap", base.osm),
        pins=[_pin(cfg, name) for name in (base.osm, base.okresy, base.obce)],
        curated=[],
        values={},
    )


def _run_addresses(args: argparse.Namespace) -> int:
    return _per_election(args, _addresses)


def _addresses(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    built = _built_candidates(cfg, election)
    declared = _addresses_declared(cfg, election)
    run = _stamp(cfg, "addresses", election.day.isoformat(), args.force, declared)
    if run is None:
        return 0
    # Without a territorial division no okrsky are counted.
    units = _input(cfg, election.units.input) if election.units else None
    out, outside, places = declared.outputs
    contests = json.loads(built.read_bytes())["contests"]
    try:
        result = addresses.build(
            _register(cfg, election),
            cfg.election_dir(election),
            contests,
            division.okrsok_counts(cfg, election) if units else {},
            partial=election.kind == config.BY_ELECTION,
            parts=addresses.council_parts(cfg, election, contests),
        )
    except (
        addresses.AddressesError,
        gpkg.GpkgError,
        obvody.ObvodyError,
        division.DivisionError,
    ) as e:
        _error(f"ems addresses: {e}")
        return 1
    sizes = addresses.write(result, out, _gzip_memo(declared.directory, "addresses"))
    addresses.write_outside(result, outside)
    obvody.write_places(result.places, places)
    _done(run)
    _print(addresses.report(result, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes):,} files)"])
    return 0


def _addresses_declared(cfg: config.Config, election: config.Election) -> _Declared:
    """Return what `addresses` reads and writes of *election*.

    The contests of its candidates, and of a by-election those of its term
    (whose council obvody it fills seats of); the okrsky of each obec come
    from the units input.
    """
    day = election.day.isoformat()
    overrides = cfg.overrides[election.slug]
    units = [_pin(cfg, election.units.input)] if election.units else []
    term = cfg.term(election)
    return _Declared(
        *_outputs(cfg, "addresses", day),
        pins=[_pin(cfg, election.addresses), _pin(cfg, election.zbgis[0]), *units],
        curated=[
            *_okrsky_files(cfg, election),
            cfg.election_dir(election) / obvody.DIRECTORY,
        ],
        values={
            "overrides address": overrides.address,
            "overrides address_skip": sorted(overrides.address_skip),
            "partial": election.kind == config.BY_ELECTION,
        },
        upstream=(
            ("candidates", day),
            *((("candidates", term.day.isoformat()),) if term else ()),
        ),
    )


def _register(cfg: config.Config, election: config.Election) -> addresses.Register:
    """Return what ``addresses`` makes of *election*'s address register alone.

    With ZBGIS level 0 and the election's overrides of the register, the
    same for every election that reads them: cached in
    data/build/shared/addresses/<register input>/, keyed on all of them and
    the code (:func:`addresses.register`).
    """
    raw = _input(cfg, election.addresses)
    zbgis = _input(cfg, election.zbgis[0])
    overrides = cfg.overrides[election.slug]
    key = stamp.json_digest(
        {
            "code": stamp.code_digest("addresses"),
            "runtime": stamp.RUNTIME,
            "inputs": [_pin_digest(cfg, r.inp, here=True) for r in (raw, zbgis)],
            "overrides address": overrides.address,
            "overrides address_skip": sorted(overrides.address_skip),
        }
    )
    return addresses.register(
        _shared_dir(cfg.build_dir, "addresses") / raw.inp.name,
        key,
        raw.path,
        _extract_gpkg(cfg, zbgis),
        overrides.address,
        overrides.address_skip,
    )


def _run_results(args: argparse.Namespace) -> int:
    """Run the results step of `make`: the final results of the pinned inputs.

    The oldest election first: a later one's are compared with it.
    """
    return _per_election(args, _results, oldest_first=True)


def _results(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    declared = _results_declared(cfg, election)
    if declared is None:
        progress.note(
            f"config/{config.ELECTIONS_FILE} names no final results of the"
            " election: it has none yet"
        )
        return 0
    _built_candidates(cfg, election)
    run = _stamp(cfg, "results", election.day.isoformat(), args.force, declared)
    if run is None:
        return 0
    packages = [_input(cfg, name) for name in election.results.inputs]
    out = cfg.results_dir(election)
    try:
        written = _write_final(cfg, election, [raw.path for raw in packages], out)
    except (results.ResultsError, OSError, KeyError, ValueError) as e:
        _error(f"ems results: {e}")
        return 1
    _done(run)
    _report_written(out, written)
    return 0


def _results_declared(
    cfg: config.Config, election: config.Election
) -> _Declared | None:
    """Return what `results` reads and writes of *election*; None if it has none.

    Its candidates and geometry (:func:`_reference`), a by-election's term's
    candidates (:func:`_council_parts`), and what its results are compared
    with (:func:`_compare`), with the special okrsky of both elections
    (:func:`_special_declared`).
    """
    if not election.results.inputs:
        return None
    day = election.day.isoformat()
    compare = _compare(cfg, election)
    term = cfg.term(election)
    walked = [election, *(c.earlier for c in compare)] if compare else []
    special_pins, special_files = _special_declared(cfg, walked)
    return _Declared(
        *_outputs(cfg, "results", day),
        pins=[
            *(_pin(cfg, name) for name in election.results.inputs),
            *(pin for c in compare for pin in c.pins),
            *special_pins,
        ],
        curated=[cfg.election_dir(election) / obvody.DIRECTORY, *special_files],
        values={
            "results": election.results,
            "kind": election.kind,
            # The names of ŠÚ SR's packages of 2022 and before (_write_final).
            "candidates": sorted(election.candidates.inputs)
            if election.candidates
            else [],
            "members": _members(cfg),
            **{k: v for c in compare for k, v in c.values.items()},
            "units": [e.units for e in walked],
        },
        upstream=(
            ("candidates", day),
            ("geo", day),
            *((("candidates", term.day.isoformat()),) if term else ()),
            *(key for c in compare for key in c.upstream),
        ),
    )


def _special_declared(
    cfg: config.Config, elections: Sequence[config.Election]
) -> tuple[list[config.Input], list[Path]]:
    """Return the pins and curated files the special okrsky of *elections* come from.

    Their territorial divisions and ``special-okrsky.toml`` where they have
    one (:func:`division.special_okrsky`).
    """
    pins = [_pin(cfg, e.units.input) for e in elections if e.units]
    files = [cfg.election_dir(e) / special.FILE for e in elections]
    return list({p.name: p for p in pins}.values()), [f for f in files if f.is_file()]


def _okrsky_files(cfg: config.Config, election: config.Election) -> list[Path]:
    """Return the okrsky files of *election*; not-found.json beside them is not read."""
    directory = cfg.election_dir(election) / obvody.OKRSKY_DIRECTORY
    return sorted(directory.glob("*.toml"))


def _built_candidates(cfg: config.Config, election: config.Election) -> Path:
    """Return *election*'s candidates.json, which `candidates` must have written."""
    built = cfg.election_build_dir(election) / candidates.OUTPUT_FILE
    if not built.is_file():
        raise ConfigError(f"{built} missing; run `ems candidates` first")
    return built


def _run_build(args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.root / build.OUTPUT_DIR
    try:
        if args.deployed:
            site = build.assemble_deployed(cfg, pages.locations(cfg, lock.keys(cfg)))
        else:
            site = build.assemble(cfg, _keys(cfg))
        # data/build/ holds every step's output: the bundles link to it.
        sizes = build.write(
            site, out, _gzip_memo(cfg.build_dir, "build"), link_below=cfg.build_dir
        )
    except (bundle.BuildError, lock.LockError, pages.PagesError) as e:
        _error(f"ems build: {e}")
        return 1
    _print(build.report(sizes))
    _print(["translations:", *(f"  {line}" for line in site.log)])
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes):,} files)"])
    return 0


def _keys(cfg: config.Config) -> lock.Keys | None:
    """Return the keys of the data parts, noting where the lock is not them.

    None, with a note, where the repository does not determine them.
    """
    try:
        keys = lock.keys(cfg)
    except lock.LockError as e:
        progress.note(f"the data parts have no key: {e}")
        return None
    if lock.read(cfg.root / lock.LOCK_FILE) != keys:
        progress.note(
            f"{lock.LOCK_FILE} is not the keys of the data built; `ems data lock`"
            " writes them, to be committed with the change"
        )
    return keys


def _run_check(_args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.root / build.OUTPUT_DIR
    if not out.is_dir():
        raise ConfigError(f"{out} missing; run `ems build` first")
    # Of the candidates.json of the elections built here, the contests their
    # bundles and results are checked against and the obce their results
    # are summed by, with those whose council contests are part of more
    # (their council obvody) and the elections before their results are
    # compared with; a deployed bundle passed its checks where it was built.
    candidates_of = {
        election.slug: {k: data[k] for k in ("contests", "obce")}
        | {
            "parts": sorted(_council_parts(cfg, election, data)),
            "past": _past_days(
                cfg, election, results.sources_of(c["id"] for c in data["contests"])
            ),
        }
        for election in cfg.elections
        if (
            built := cfg.election_build_dir(election) / candidates.OUTPUT_FILE
        ).is_file()
        and (data := json.loads(built.read_bytes()))
    }
    memo = _shared_dir(cfg.build_dir, "check") / check.MEMO_FILE
    checks = check.run(out, cfg, candidates_of, memo)
    _print(check.report(checks))
    return 1 if any(c.problems for c in checks) else 0


def _gzip_memo(directory: Path, step: str) -> Path:
    """Return where *step* keeps the gzip sizes it measured last.

    *directory* is the build directory of the election or extract it runs
    for, or for the site's own (``build``) data/build/.
    """
    return directory / output.GZIP_MEMO_DIR / f"{step}.json"


_MAKE_STEPS = {
    "candidates": _run_candidates,
    "links": _run_links,
    "addresses": _run_addresses,
    "geo": _run_geo,
    "basemap": _run_basemap,
    "results": _run_results,
    "build": _run_build,
    "check": _run_check,
}


def _run_make(args: argparse.Namespace) -> int:
    names = list(_MAKE_STEPS)
    for i, (name, run) in enumerate(_MAKE_STEPS.items()):
        with progress.stage(name) as stage:
            try:
                code = run(args)
            except ConfigError as e:
                _error(f"ems: {e}")
                code = 1
            stage.failed = code != 0
        if code:
            rest = names[i + 1 :]
            skipped = f" ({', '.join(rest)} not run)" if rest else ""
            _error(
                f"ems make: stopped at `{name}`{skipped}; fix the problem above"
                " and run `ems make` again"
            )
            return code
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.root / build.OUTPUT_DIR
    app = out / build.APP_PART
    needed = ("index.html", bundle.HEADERS, bundle.NOT_FOUND)
    if not all((app / name).is_file() for name in needed):
        raise ConfigError(f"{out} has no app; run `ems build` first")
    try:
        build.serve(out, args.host, args.port)
    except KeyboardInterrupt:
        pass
    except bundle.BuildError as e:
        _error(f"ems serve: {e}")
        return 1
    except OSError as e:
        _error(f"ems serve: {args.host}:{args.port}: {e.strerror}")
        return 1
    return 0


def _add_job_parser(commands: argparse._SubParsersAction) -> None:
    kinds = jobs.kinds()
    p = commands.add_parser(
        "job",
        help="make and ingest jobs for AI agents (translation, ...)",
        description=(
            "Work that needs an AI agent goes out as job directories in"
            " data/jobs/ (git-ignored) and comes back through ingest into"
            " data/curated/ (committed). See src/election_map_slovakia/jobs.py."
        ),
    )
    sub = p.add_subparsers(title="job commands", metavar="COMMAND", required=True)
    make = sub.add_parser(
        "make",
        help="write job directories for the work still to do",
        description=(
            "Write data/jobs/<kind>-NNN/ (input.json, schema.json, prompt.md,"
            " README.md) for the items of KIND that are neither curated nor in"
            " a job not ingested yet, and list them. Kinds: "
            + "; ".join(f"{k.name}: {k.summary}" for k in kinds.values())
            + "."
        ),
    )
    make.add_argument("kind", choices=sorted(kinds), metavar="KIND")
    make.add_argument(
        "--size", type=int, help="items per job (default: the kind's)", metavar="N"
    )
    make.add_argument(
        "--priority",
        metavar="ORDER",
        help="order of the items, if the kind has several",
    )
    make.add_argument(
        "--only",
        nargs="+",
        action="extend",
        default=[],
        metavar="NAME",
        help=(
            "restrict to these (translation: language codes, ui, occupations;"
            " research: research languages and places, e.g. sk okres:807)"
        ),
    )
    make.add_argument(
        "--limit", type=int, metavar="N", help="write at most N jobs, the first ones"
    )
    _add_election(
        make,
        "for kinds that read an election's data (obvod-rules, okrsok-rules,"
        " research): that election, its day or slug (default: the latest)",
    )
    make.set_defaults(run=_run_job_make)
    ingest = sub.add_parser(
        "ingest",
        help="check the output of jobs and merge it into data/curated/",
        description=(
            "Validate output.json of each job against its schema.json and the"
            " checks of its kind, merge the accepted items into data/curated/"
            " and write ingest-report.md in the job directory. Ingesting"
            " again is harmless. The exit code is 1 if any item was rejected"
            " or missing."
        ),
    )
    ingest.add_argument("dirs", nargs="+", type=Path, metavar="DIR")
    ingest.set_defaults(run=_run_job_ingest)
    reuse_parser = sub.add_parser(
        "reuse",
        help="give an election another vote's obvod and okrsok rules where it has none",
        description=(
            "Where the obvod-rules and okrsok-rules jobs of an earlier"
            " election found no document, copy the latest election's rules"
            " into its data/curated/ if the obvody, seats and okrsky provably"
            " match, marked reused. A country-wide election or a by-election"
            " gets the okrsky (and a by-election the council obvody that"
            " voted) of the regular election nearest in time that proves"
            " them by their numbers and voters, marked reused, where it has"
            " none. Then, for any election, the latest too, the units still"
            " unknown are drawn with those of the vote nearest in time,"
            " either way, that has its own of the same structure (obvod"
            " numbers and seats; okrsky per obvod) with voters within 25 %"
            " where known, marked adopted: a stand-in, indicative only"
            " (see src/election_map_slovakia/reuse.py)."
        ),
    )
    _add_election(reuse_parser, "the election, its day or slug")
    reuse_parser.set_defaults(run=_run_job_reuse)
    captures_parser = sub.add_parser(
        "captures",
        help="list a website's captures in the Common Crawl, or read one",
        description=(
            "For the obvod-rules and okrsok-rules jobs: list the captures of"
            " SITE (a host such as obec.sk, or a URL) in the Common Crawl's"
            " crawls of the given years, one line each: time, HTTP status, type"
            " and the URL that cites the capture as a document. Given such a"
            " URL instead, write the document it holds to --out. Reads the"
            " crawls' own index files, not the often overloaded index server"
            " (see src/election_map_slovakia/commoncrawl.py)."
        ),
    )
    captures_parser.add_argument("site", metavar="SITE")
    captures_parser.add_argument(
        "--years",
        default="",
        metavar="YYYY[-YYYY]",
        help="the crawls of these years (required for a listing)",
    )
    captures_parser.add_argument(
        "--match", default="", metavar="REGEX", help="only the URLs it finds in"
    )
    captures_parser.add_argument(
        "--out", type=Path, metavar="FILE", help="where to write a capture's document"
    )
    captures_parser.set_defaults(run=_run_job_captures)


def _run_job_make(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.size is not None and args.size < 1:
        raise ConfigError("--size must be at least 1")
    kind = jobs.kinds()[args.kind]
    if args.election and not kind.per_election:
        raise ConfigError(f"--election: {kind.name} jobs serve every election at once")
    try:
        made = jobs.make(
            cfg,
            kind,
            election=cfg.election(args.election),
            size=args.size,
            priority=args.priority,
            only=args.only,
            limit=args.limit,
        )
    except (jobs.JobError, division.DivisionError) as e:
        _error(f"ems job make: {e}")
        return 1
    _print(
        f"{job.path.relative_to(cfg.root)}: {len(job.items):,} items" for job in made
    )
    _print([f"{len(made):,} jobs written" if made else "nothing to do"])
    return 0


def _run_job_ingest(args: argparse.Namespace) -> int:
    cfg = config.load()
    failed = False
    for directory in args.dirs:
        try:
            report = jobs.ingest(cfg, directory)
        except (jobs.JobError, division.DivisionError) as e:
            _error(f"ems job ingest: {directory}: {e}")
            failed = True
            continue
        _print([report.summary(), *(f"  {line}" for line in report.curated)])
        failed |= not report.ok
    return 1 if failed else 0


def _run_job_reuse(args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        lines = reuse.run(cfg, cfg.election(args.election))
    except (jobs.JobError, division.DivisionError) as e:
        _error(f"ems job reuse: {e}")
        return 1
    _print(lines)
    return 0


def _run_job_captures(args: argparse.Namespace) -> int:
    cfg = config.load()
    ranges = commoncrawl.http_ranges(
        fetch.user_agent(cfg.inputs.contact),
        fetch.ssl_context(cfg.inputs.ca_certificates),
        obvodrules.TIMEOUT,
    )
    try:
        if commoncrawl.capture(args.site):
            if args.out is None:
                raise ConfigError("--out: where to write the capture's document")
            data = commoncrawl.fetch(ranges, args.site, obvodrules.MAX_DOCUMENT)
            args.out.write_bytes(data)
            _print([f"{args.out}: {len(data):,} bytes"])
            return 0
        m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", args.years)
        if m is None:
            raise ConfigError("--years: a year or a range of years, e.g. 2017-2018")
        years = range(int(m.group(1)), int(m.group(2) or m.group(1)) + 1)
        match = re.compile(args.match) if args.match else None
        for crawl in commoncrawl.crawls(ranges, years):
            _print(
                f"{stamp} {fields.get('status', '-')} {fields.get('mime', '-')}"
                f" {commoncrawl.capture_url(crawl, fields['url'], stamp)}"
                for stamp, fields in commoncrawl.captures(ranges, crawl, args.site)
                if match is None or match.search(fields["url"])
            )
    except commoncrawl.CommonCrawlError as e:
        _error(f"ems job captures: {e}")
        return 1
    except (urllib.error.URLError, OSError) as e:
        _error(f"ems job captures: {e}")
        return 1
    return 0


def _add_research_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "research",
        help="tools for research jobs: read a page, submit an item, coverage",
        description=(
            "Helpers for agents working on `research` jobs (see"
            " src/election_map_slovakia/research.py) and for the maintainer."
        ),
    )
    sub = p.add_subparsers(title="research commands", metavar="COMMAND", required=True)
    read = sub.add_parser(
        "read",
        help="check that a page may be cited, cache it, print it as JSON",
        description=(
            "Print as JSON whether URL is allowed for the job's categories,"
            " its title, date and language and the passages naming the"
            " person; the cached copy is kept in the job for the check."
        ),
    )
    read.add_argument("job", type=Path, metavar="JOB")
    read.add_argument("url", metavar="URL")
    read.add_argument("--person", metavar="ID", help="an item id of the job")
    read.set_defaults(run=_run_research_read)
    submit = sub.add_parser(
        "submit",
        help="check output items (JSON on stdin) and add them to output.json",
        description=(
            "Read one output item, or an array of them, from stdin, run the"
            " checks of ingest on each and put each that passes into the"
            " job's output.json (replacing an item of the same id). Prints"
            " the problems; exit code 1 if any."
        ),
    )
    submit.add_argument("job", type=Path, metavar="JOB")
    submit.set_defaults(run=_run_research_submit)
    status = sub.add_parser(
        "status",
        help="how many candidates of a place are researched, per language",
        description=(
            "Count the candidates of an election (the latest, or --election)"
            " --only selects (places, research languages; as for `ems job make"
            " research`) researched with the current allowlist, with findings,"
            " in pending jobs and still to do."
        ),
    )
    status.add_argument(
        "--only", nargs="+", action="extend", default=[], metavar="NAME"
    )
    _add_election(status, "the election, its day or slug (default: the latest)")
    status.set_defaults(run=_run_research_status)


def _research_job(path: Path) -> jobs.Job:
    job = jobs.load_job(path)
    if job.kind != research.NAME:
        raise jobs.JobError(f"{path} is a {job.kind} job, not {research.NAME}")
    return job


def _run_research_read(args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        answer = research.read(cfg, _research_job(args.job), args.url, args.person)
    except jobs.JobError as e:
        _error(f"ems research read: {e}")
        return 1
    _print([json.dumps(answer, ensure_ascii=False, indent=1)])
    return 0


def _run_research_submit(args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        job = _research_job(args.job)
        content = json.loads(sys.stdin.read())
    except (jobs.JobError, ValueError) as e:
        _error(f"ems research submit: {e}")
        return 1
    items = content if isinstance(content, list) else [content]
    failed = False
    for item in items:
        if not isinstance(item, dict):
            _print(["not a JSON object: " + json.dumps(item, ensure_ascii=False)[:80]])
            failed = True
            continue
        problems = research.submit(cfg, job, item)
        label = item.get("id", "?")
        _print([f"{label}: {p}" for p in problems] or [f"{label}: accepted"])
        failed |= bool(problems)
    return 1 if failed else 0


def _run_research_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        _print(research.coverage(cfg, cfg.election(args.election), args.only))
    except jobs.JobError as e:
        _error(f"ems research status: {e}")
        return 1
    return 0


def _add_results_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "results",
        help="live results of an election night: poll, fake, deploy",
        description=(
            "Write an election's live results, data/build/<election day>/live/"
            " (which `ems build` copies into the site beside the final"
            " results), from volbysr.sk (poll) or dummy data (fake), and"
            " deploy them on an election night (deploy). The final results"
            " come only from the election's pinned results inputs, through"
            " `ems make` and a release. See docs/results.md and"
            " src/election_map_slovakia/results.py."
        ),
    )
    sub = p.add_subparsers(title="results commands", metavar="COMMAND", required=True)

    def directory(parser: argparse.ArgumentParser) -> None:
        _add_election(parser, "whose live results to write (default: the latest)")
        parser.add_argument(
            "--dir",
            type=Path,
            default=None,
            help="the directory to write (default: data/build/<election day>/live/)",
        )

    poll = sub.add_parser(
        "poll",
        help="poll volbysr.sk and rewrite the live results as the counting moves on",
        description=(
            "Fetch the progress files of volbysr.sk every INTERVAL seconds"
            " (conditional requests), and when one changed the per-unit"
            " files; keep every file fetched under data/raw/results/<UTC"
            " time>/ and rewrite the live results when their content changed."
        ),
    )
    poll.add_argument(
        "--interval",
        type=int,
        default=results.INTERVAL,
        help=f"seconds between polls (default {results.INTERVAL})",
    )
    poll.add_argument("--once", action="store_true", help="poll once and stop")
    poll.add_argument(
        "--deploy",
        action="store_true",
        help="deploy the live results after every change (as `results deploy --yes`)",
    )
    directory(poll)
    poll.set_defaults(run=_run_results_poll)
    fake = sub.add_parser(
        "fake",
        help="write dummy live results for testing the app",
        description=(
            "Write deterministic dummy results of the counting at STAGE"
            " (none, early, mid, late, final) from the election's"
            " data/build/<election day>/ as its live results; the counts only"
            " grow from stage to stage for the same --seed. The app reads them"
            " only where the election has no final results."
        ),
    )
    fake.add_argument("stage", choices=list(results.STAGES), metavar="STAGE")
    fake.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    directory(fake)
    fake.set_defaults(run=_run_results_fake)
    deploy = sub.add_parser(
        "deploy",
        help="deploy the live results of every election to their Pages project",
        description=(
            "Write the live part of the site (dist/live/: the live results of"
            " every election that has some), show what each election's hold"
            " and check them, and deploy the part with Wrangler to the Pages"
            " project live_project of config/site.toml as a production"
            " deployment, after asking unless --yes. The final results, the"
            " app and the bundles stay as they are: only a release deploys"
            " them."
        ),
    )
    deploy.add_argument("--yes", action="store_true", help="do not ask")
    deploy.set_defaults(run=_run_results_deploy)


def _live_dir(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> Path:
    """Return the directory a results command writes: the live results'.

    Never the final results' (``Config.results_dir``), which only the
    results step of `make` writes.
    """
    return args.dir if args.dir is not None else cfg.live_dir(election)


def _reference(cfg: config.Config, election: config.Election) -> results.Reference:
    try:
        return results.load_reference(
            cfg.election_build_dir(election),
            cfg.election_dir(election),
            _members(cfg),
            _council_parts(cfg, election),
        )
    except results.ResultsError as e:
        raise ConfigError(str(e)) from e


def _expect(cfg: config.Config, election: config.Election) -> results.Expect:
    """Return what *election*'s results are held to, from its built candidates."""
    data = json.loads(_built_candidates(cfg, election).read_bytes())
    sources = results.sources_of(c["id"] for c in data["contests"])
    return results.Expect.of(
        data, _council_parts(cfg, election, data), _past_days(cfg, election, sources)
    )


def _council_parts(
    cfg: config.Config, election: config.Election, data: Any = None
) -> set[str]:
    """Return :func:`addresses.council_parts` of *election*'s built candidates.

    *data*, where read already; the results' council obvody follow it as
    the app's do.
    """
    if data is None:
        data = json.loads(_built_candidates(cfg, election).read_bytes())
    return addresses.council_parts(cfg, election, data["contests"])


def _members(cfg: config.Config) -> dict[str, int]:
    """Return party → its number of member parties (config/parties.toml)."""
    return {name: len(party.members) for name, party in cfg.parties.items()}


def _report_written(directory: Path, written: dict | None) -> None:
    if written is None:
        _print([f"{directory}: unchanged"])
    else:
        _print(results.describe(directory))


def _client(cfg: config.Config) -> results.Client:
    """Return the client of volbysr.sk, archiving into data/raw/results/."""
    return results.Client(
        results.BASE_URL,
        results.browser_agent(cfg.inputs.contact),
        fetch.ssl_context(cfg.inputs.ca_certificates),
        cfg.raw_dir / results.RAW_DIR,
    )


def _write_final(
    cfg: config.Config,
    election: config.Election,
    packages: Sequence[Path],
    out: Path,
) -> dict | None:
    """Write the definitive results of *packages* to *out*; return the status.

    In place of what is there, as of the packages' newest data, so that the
    same packages give the same files, and only if they keep the contract
    (``results.check``): a unit whose votes do not add up stops it. ŠÚ SR's
    packages of 2022, 2018 and 2017 (format ``susr``) hold every contest. A
    national election's packages are its tables (:mod:`national`), a
    by-election's its package (``susr-by``). The okrsky get the figures of
    the election before, if any (:func:`_past`).
    """
    if election.results.format == "susr":
        # The configuration has them be the packages the candidates name.
        named = list(election.candidates.inputs) if election.candidates else []
        if len(packages) != len(named):
            raise results.ResultsError(
                f"the {election.slug} results are the packages {', '.join(named)}"
            )
        try:
            final = statoffice.read_final(dict(zip(named, packages, strict=True)))
        except statoffice.StatOfficeError as e:
            raise results.ResultsError(str(e)) from e
        merged = final.live
    else:
        ref = _reference(cfg, election)
        if election.kind in contests.NATIONAL:
            live, done = national.read_final(packages, ref)
        elif election.results.format == "susr-by":
            live, done = results.read_by_election(packages, ref)
        else:
            live, done = results.read_final(packages, ref.contests)
        merged = results.finalize(live, done, ref.sources)
    merged.past = _past(cfg, election, merged)
    expect = _expect(cfg, election)
    return results.write(
        out, merged, expect.divisions, results.data_time(merged), expect=expect
    )


class _Compare(NamedTuple):
    """An election before one, which (some of) its results are compared with.

    And what the comparison reads (:mod:`crosswalk`) and writes (*out*).
    """

    earlier: config.Election
    halves: tuple[str, ...]
    """The halves of a regular election compared with it (keys of
    :data:`config.HALVES`, its contests' sources); () for every contest of
    an election of another kind."""
    pins: list[config.Input]
    """The address registers of both elections and their boundaries, level
    0, which name the obce of the registers."""
    upstream: tuple[record.Key, ...]
    """The links of this election, the addresses (addr/) of both and the
    results of the earlier one."""
    values: dict[str, object]
    links: Path
    out: Path

    def sources(self, of: Iterable[str]) -> tuple[str, ...]:
        """Return the sources compared with it of those *of* the election."""
        return tuple(s for s in of if not self.halves or s in self.halves)


def _compare(cfg: config.Config, election: config.Election) -> list[_Compare]:
    """Return what *election*'s results are compared with, oldest first."""
    out = []
    for earlier, halves in _earlier(cfg, election):
        both = (earlier, election)
        day, before = election.day.isoformat(), earlier.day.isoformat()
        links = cfg.election_build_dir(election) / bundle.LINKS_DIR
        out.append(
            _Compare(
                earlier,
                halves,
                [
                    *(_pin(cfg, e.addresses) for e in both),
                    *(_pin(cfg, e.zbgis[0]) for e in both),
                ],
                (
                    ("links", day),
                    ("addresses", before),
                    ("addresses", day),
                    ("results", before),
                ),
                {
                    f"compared {earlier.slug}": list(halves),
                    **{
                        f"overrides {e.slug} address": (
                            cfg.overrides[e.slug].address,
                            sorted(cfg.overrides[e.slug].address_skip),
                        )
                        for e in both
                    },
                },
                links / f"{earlier.slug}.json",
                _crosswalk_file(cfg, election, earlier),
            )
        )
    return out


def _earlier(
    cfg: config.Config, election: config.Election
) -> list[tuple[config.Election, tuple[str, ...]]]:
    """Return the elections *election*'s results are compared with, oldest first.

    Each with the halves compared with it (:attr:`_Compare.halves`): the
    newest earlier election of its kind, of a regular one for each half the
    newest that held it (before 2022 the municipal and the regional
    elections were held apart: 2022's municipal contests are compared with
    2018's, its regional ones with 2017's); none of a by-election, whose
    contests are in other places each time.
    """
    if election.kind == "by-election":
        return []
    before = [
        e for e in cfg.elections if e.day < election.day and e.kind == election.kind
    ]
    if not election.halves:
        return [(before[0], ())] if before else []
    nearest = {
        half: next((e.slug for e in before if half in e.halves), None)
        for half in election.halves
    }
    return [
        (e, halves)
        for e in reversed(before)
        if (halves := tuple(h for h in election.halves if nearest[h] == e.slug))
    ]


def _past_days(
    cfg: config.Config, election: config.Election, sources: Iterable[str]
) -> dict[str, str]:
    """Return source → day of the election before it is compared with.

    Of *sources*, those of *election*'s contests (:attr:`results.Expect.past`).
    """
    of = tuple(sources)
    return {
        s: c.earlier.day.isoformat()
        for c in _compare(cfg, election)
        for s in c.sources(of)
    }


def _crosswalk_file(
    cfg: config.Config, election: config.Election, earlier: config.Election
) -> Path:
    """Return the crosswalk from *earlier*'s okrsky to *election*'s, beside its results."""
    return (
        cfg.election_build_dir(election) / crosswalk.OUTPUT_DIR / f"{earlier.slug}.json"
    )


def _past(
    cfg: config.Config, election: config.Election, live: results.Live
) -> dict[str, results.Past]:
    """Return the ``past`` of *election*'s results *live*: the elections before's.

    By source (:attr:`results.Live.past`): the contests compared with each
    election before (:func:`_compare`) mapped onto its okrsky by a
    crosswalk of their own, which is written beside the results.
    """
    out: dict[str, results.Past] = {}
    for compare in _compare(cfg, election):
        earlier = compare.earlier
        before = results.read_live(cfg.results_dir(earlier))
        if before is None:
            raise ConfigError(
                f"{cfg.results_dir(earlier)} has no results; run `ems make"
                f" --election {earlier.slug}` first"
            )
        if not compare.links.is_file():
            raise ConfigError(f"{compare.links} missing; run `ems links` first")
        registers = [
            crosswalk.Register(
                _register(cfg, e).houses,
                cfg.election_build_dir(e) / addresses.OUTPUT_DIR,
            )
            for e in (earlier, election)
        ]
        sources = compare.sources(live.source)
        compared = live.part(sources)
        walk = crosswalk.make(
            compared,
            before,
            registers,
            earlier.day,
            (
                special.keys(division.special_okrsky(cfg, election)),
                special.keys(division.special_okrsky(cfg, earlier)),
            ),
        )
        linked = json.loads(compare.links.read_bytes())["candidacies"]
        past = crosswalk.past(compared, before, walk, linked)
        out |= dict.fromkeys(sources, past)
        output.write_file(compare.out, output.to_json(crosswalk.to_json(walk)) + b"\n")
        _print(crosswalk.report(walk, past))
        _print([f"wrote {compare.out.relative_to(cfg.root)}"])
    return out


def _run_results_poll(args: argparse.Namespace) -> int:
    cfg = config.load()
    election = cfg.election(args.election)
    # The night's files of the other kinds differ; their results come final.
    if election.kind != "municipal-regional" or election.results.format != "volbysr":
        raise ConfigError(
            f"results poll: only the night of a municipal and regional election"
            f" on volbysr.sk is polled; the {election.slug} election"
            f" ({election.kind}, {election.results.format}) gets its results"
            " from its inputs (`ems make`)"
        )
    out = _live_dir(cfg, election, args)
    client = _client(cfg)
    poller = results.Poller(client, _reference(cfg, election), out, _log)
    project = cfg.site.live_project
    try:
        while True:
            started = time.monotonic()
            try:
                written = poller.cycle()
            except OSError as e:
                _log(f"poll failed: {e}")
                written = None
            if written is not None and args.deploy:
                code = _deploy_live(cfg, ask=False)
                _log(
                    f"deploy to {project}: " + ("done" if code == 0 else f"exit {code}")
                )
            if args.once:
                return 0
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


def _log(message: str) -> None:
    _error(f"{dt.datetime.now(results.TIMEZONE):%H:%M:%S} {message}")


def _run_results_fake(args: argparse.Namespace) -> int:
    cfg = config.load()
    election = cfg.election(args.election)
    out = _live_dir(cfg, election, args)
    ref = _reference(cfg, election)
    try:
        counts = division.okrsok_counts(cfg, election) if election.units else {}
        if election.kind in contests.NATIONAL:
            live = national.fake(ref, args.stage, election.day, args.seed, counts)
        else:
            rule_sets = obvody.okrsok_rule_sets(cfg.election_dir(election))
            live = results.fake(
                ref,
                args.stage,
                args.seed,
                counts,
                {obec: rules.okrsky for obec, rules in rule_sets.items()},
                _past_days(cfg, election, ref.sources),
            )
    except (division.DivisionError, obvody.ObvodyError) as e:
        _error(f"ems results fake: {e}")
        return 1
    written = results.write(out, live, ref.divisions)
    _report_written(out, written)
    return 0


def _run_results_deploy(args: argparse.Namespace) -> int:
    return _deploy_live(config.load(), ask=not args.yes)


def _deploy_live(cfg: config.Config, *, ask: bool) -> int:
    """Write the live part, check it and deploy it, asking first if *ask*.

    Only if every election's live results in it keep the contract
    (``results.check``), each against its built candidates; the commit
    message of the deployment names their versions (the part's manifest).
    """
    part = bundle.live_part(cfg)
    if not part.copies:
        _error("ems results deploy: no election has live results; nothing deployed")
        return 1
    out = cfg.root / build.OUTPUT_DIR / bundle.LIVE_PART
    build.write(build.Site(part.files, part.copies, []), out)
    by_day = {e.day.isoformat(): e for e in cfg.elections}
    problems = []
    for day in part.copies:
        election = by_day[day]
        _print([f"{election.slug} ({day}):", *results.describe(out / day)])
        expect = _expect(cfg, election)
        problems += [f"{day}/{p}" for p in results.check(out / day, expect)]
    if problems:
        _print([f"  {p}" for p in problems])
        _error(f"ems results deploy: {out} breaks the contract; not deployed")
        return 1
    versions = json.loads(part.files[bundle.MANIFEST])["versions"]
    message = " ".join(["live", *(f"{day}@{v}" for day, v in versions.items())])
    project = cfg.site.live_project
    _print([" ".join(pages.deploy_command(out, project, message))])
    if ask and input(f"deploy to {project}? [y/N] ").strip().lower() != "y":
        _print(["not deployed"])
        return 1
    try:
        return pages.deploy(out, project, message)
    except pages.PagesError as e:
        _error(f"ems results deploy: {e}")
        return 1


def _print(lines: Iterable[str]) -> None:
    """Print *lines* to stdout, below any progress line still open."""
    progress.end_line()
    for line in lines:
        print(line)


def _error(message: str) -> None:
    progress.end_line()
    print(message, file=sys.stderr)


# Commands that run until interrupted or wait for an answer: a progress
# stage around them would stay open the whole time.
_UNSTAGED = frozenset({_run_serve, _run_results_poll, _run_results_deploy})


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit code.

    Every command but serve, results poll and results deploy reports its
    progress as a stage of its own.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "run", None)
    if run is None:
        parser.print_help()
        return 2
    try:
        with _scans_kept():
            if run in _UNSTAGED:
                return run(args)
            with progress.stage(args.command) as stage:
                code = run(args)
                stage.failed = code != 0
            return code
    except ConfigError as e:
        _error(f"ems: {e}")
        return 1


def _scans_kept() -> contextlib.AbstractContextManager[None]:
    """Keep the imports of the code digests in data/build/shared/stamp/.

    For the commands that digest code (:func:`stamp.scans_kept`); nothing
    outside a project, which a command that needs one reports.
    """
    try:
        root = config.find_config_dir().parent
    except ConfigError:
        return contextlib.nullcontext()
    return stamp.scans_kept(_shared_dir(config.build_dir_of(root), "stamp"))


if __name__ == "__main__":
    sys.exit(main())
