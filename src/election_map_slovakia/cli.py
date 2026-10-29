"""The ``ems`` command line.

Each pipeline step is a subcommand registered in :func:`build_parser` with
``set_defaults(run=...)``; ``run`` receives the parsed arguments and returns
the exit code.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import NamedTuple

from election_map_slovakia import (
    __version__,
    addresses,
    basemap,
    build,
    bundle,
    candidates,
    check,
    config,
    crosswalk,
    fetch,
    geo,
    gpkg,
    incumbents,
    jobs,
    links,
    lock,
    obvody,
    okrsokrules,
    output,
    pages,
    progress,
    research,
    results,
    reuse,
    stamp,
    statoffice,
    store,
    xlsx,
)
from election_map_slovakia.config import ConfigError

_SKIPPED = (
    " Does nothing when its inputs, configuration and code are unchanged since"
    " it last succeeded and its output is in place."
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
            " candidates` first). Fails if neighbouring areas do not share"
            " their borders, or the countries around leave a gap at Slovakia's."
            + _SKIPPED
        ),
    )
    p.add_argument(
        "--preview",
        metavar="OKRES",
        help="also write SVG previews (country, Bratislava, this okres at full"
        f" detail) to data/build/<election day>/{geo.PREVIEW_DIR}/; implies --force",
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
            f" data/build/<election day>/{basemap.OUTPUT_DIR}/. The layout is"
            " described in src/election_map_slovakia/basemap.py." + _SKIPPED
        ),
    )
    _add_force(p)
    _add_election(p)
    p.set_defaults(run=_run_basemap)

    p = commands.add_parser(
        "build",
        help="assemble the static site in dist/, in its parts",
        description=(
            "Wipe dist/ and write the site in the parts deployed to Pages"
            " projects of their own: the app (dist/app/: the shells per"
            " language and election, the language picker, web/ assets, UI"
            " strings), each election's map bundle (dist/map/<slug>/: the"
            " geometry and address files, the base map) and data bundle"
            " (dist/data/<slug>/: the candidates split per okres, city and"
            " kraj, a name search index, research, the"
            " occupations), the cached sources (dist/sources/) and the"
            " results (dist/results/). Needs the output of `candidates`,"
            " `links`, `geo`, `basemap` and `addresses` of every election in"
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
            " changed since they last succeeded are skipped; build and check"
            " always run, for the whole site. `results` writes an election's"
            " final results from its `results` inputs where"
            " config/elections.toml names them, and otherwise leaves the"
            " results as `ems results` left them."
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
            " at /map/<slug>/ and /data/<slug>/, the results at /results/, the"
            " cached sources"
            " at /cache/; each with the response headers of its _headers, as"
            " on Cloudflare Pages."
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
            " built in dist/ deployed where not (deploy). See docs/deploy.md."
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
        help="also write stale=true or stale=false to the file $GITHUB_OUTPUT"
        " names (a GitHub Actions step's outputs)",
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
        _Part(f"{part}/{slug}", project, key, pages.find(project, key))
        for part, slug, project, key in pages.bundles(cfg, keys)
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
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as f:
            f.write(f"stale={'true' if stale else 'false'}\n")
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


def _run_inputs_publish(_args: argparse.Namespace) -> int:
    cfg = config.load()
    uploaded = 0
    try:
        for inp in store.publish(cfg.inputs, cfg.raw_dir):
            _print([f"uploaded {store.Store.asset(inp)}"])
            uploaded += 1
    except store.StoreError as e:
        _error(f"ems inputs publish: {e}")
        return 1
    _print([f"{uploaded} file(s) uploaded" if uploaded else "the store has them all"])
    return 0


def _run_candidates(args: argparse.Namespace) -> int:
    return _per_election(args, _candidates)


def _candidates(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    lists = {name: _input(cfg, inp) for name, inp in election.candidates.inputs.items()}
    source = election.incumbents
    results = {name: _input(cfg, name) for name in source.inputs} if source else {}
    zbgis = _input(cfg, election.zbgis[0])
    out = cfg.election_build_dir(election) / candidates.OUTPUT_FILE
    overrides = cfg.overrides[election.slug]
    record = _stamp(
        cfg,
        election,
        "candidates",
        args.force,
        [out],
        inputs=[*lists.values(), *results.values(), zbgis],
        values={
            "overrides": overrides,
            "election": election.day,
            "candidates": election.candidates,
            "incumbents": source,
            # The lists of ŠÚ SR's packages are read by code of its own.
            **(
                {"code statoffice": stamp.code_digest("statoffice")}
                if election.candidates.format == "susr"
                else {}
            ),
        },
    )
    if record is None:
        return 0
    try:
        if election.candidates.format == "susr":
            with progress.stage("reading the candidates of ŠÚ SR's packages"):
                read = statoffice.read_candidates(
                    statoffice.open_package(lists["oso"].path),
                    statoffice.open_package(lists["osk"].path),
                )
        else:
            read = candidates.read_lists({k: raw.path for k, raw in lists.items()})
        result = candidates.build(
            read,
            _extract_gpkg(cfg, zbgis),
            overrides,
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
    record.record()
    _print(candidates.report(result))
    _print([f"wrote {out.relative_to(cfg.root)} ({output.format_size(size)})"])
    return 0


def _run_links(args: argparse.Namespace) -> int:
    return _per_election(args, _links)


def _links(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    """Link *election*'s persons to those of every election before it."""
    earlier = [e for e in cfg.elections if e.day < election.day]
    out = cfg.election_build_dir(election) / bundle.LINKS_DIR
    path = cfg.root / "config" / links.LINKS_FILE
    overrides = links.load_overrides(path, {e.slug: e.day for e in cfg.elections})
    built = {e.slug: _built_candidates(cfg, e) for e in [election, *earlier]}
    record = _stamp(
        cfg,
        election,
        "links",
        args.force,
        [out],
        files=list(built.values()),
        values={
            "earlier": [e.slug for e in earlier],
            "overrides": {
                e.slug: overrides.get((election.slug, e.slug)) for e in earlier
            },
        },
    )
    if record is None:
        return 0
    later = links.Candidates(
        election.day, json.loads(built[election.slug].read_bytes())
    )
    files: dict[str, bytes] = {}
    for e in earlier:
        with progress.stage(f"linking to the persons of {e.day}"):
            try:
                linked = links.match(
                    later,
                    links.Candidates(e.day, json.loads(built[e.slug].read_bytes())),
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
    record.record()
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(files)} files)"])
    return 0


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


def _input(cfg: config.Config, name: str) -> _Raw:
    inp = next((i for i in cfg.inputs.inputs if i.name == name), None)
    if inp is None:
        raise ConfigError(f"config/{config.INPUTS_FILE}: input {name!r} missing")
    # fetch lets an optional input fail, so no step may depend on one.
    if inp.optional:
        raise ConfigError(
            f"config/{config.INPUTS_FILE}: input {name!r} is optional, so no"
            " step may read it"
        )
    path = fetch.member_path(cfg.raw_dir, inp)
    if not path.is_file():
        raise ConfigError(f"{path} missing; run `ems fetch` first")
    return _Raw(path, inp)


def _extract_gpkg(cfg: config.Config, raw: _Raw) -> Path:
    """Return the GeoPackage of a ZBGIS input, unpacked into data/build/.

    Shared by every election that reads the input: it is the input's.
    """
    return gpkg.extract(raw.path, raw.inp.members[0], cfg.build_dir)


def _stamp(
    cfg: config.Config,
    election: config.Election,
    step: str,
    force: bool,
    outputs: list[Path],
    *,
    inputs: Iterable[_Raw] = (),
    files: Iterable[Path] = (),
    trees: Iterable[Path] = (),
    values: dict[str, object] | None = None,
) -> stamp.Stamp | None:
    """Return the stamp *step* of *election* records once done, or None if up to date.

    *inputs* are downloads (file and configuration), *files* and *trees*
    other files and directories it reads, *values* configuration it gets.
    """
    inputs = list(inputs)
    values = (values or {}) | {
        f"config input {raw.inp.name}": raw.inp for raw in inputs
    }
    with progress.stage("comparing the inputs with the last successful run"):
        record = stamp.Stamp(
            _stamp_path(cfg, election, step),
            stamp.inputs(
                cfg.root, step, [*(raw.path for raw in inputs), *files], trees, values
            ),
            outputs,
        )
        changes = record.changes()
    if not (changes or force):
        progress.note(f"up to date, skipped (`ems {step} --force` runs it anyway)")
        return None
    progress.note("running: " + ("--force" if force else "; ".join(changes)))
    record.forget()
    return record


def _stamp_path(cfg: config.Config, election: config.Election, step: str) -> Path:
    """Return where *step* records its last successful run for *election*."""
    return cfg.election_build_dir(election) / f"{step}.stamp.json"


def _run_geo(args: argparse.Namespace) -> int:
    return _per_election(args, _geo)


def _geo(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    zbgis = {level: _input(cfg, name) for level, name in enumerate(election.zbgis)}
    countries = _input(cfg, geo.NEIGHBOURS_INPUT)
    built = _built_candidates(cfg, election)
    directory = cfg.election_build_dir(election)
    curated = cfg.election_dir(election)
    out = directory / geo.OUTPUT_DIR
    places = directory / addresses.OBVOD_DIR
    if not places.is_dir():
        raise ConfigError(f"{places} missing; run `ems addresses` first")
    record = _stamp(
        cfg,
        election,
        "geo",
        args.force or bool(args.preview),
        [out],
        inputs=[*zbgis.values(), countries],
        files=[built, *_okrsky_files(cfg, election)],
        trees=[curated / obvody.DIRECTORY, places],
    )
    if record is None:
        return 0
    data = json.loads(built.read_bytes())
    counts = Counter(c["contest"] for c in data["candidacies"])
    try:
        paths = {level: _extract_gpkg(cfg, raw) for level, raw in zbgis.items()}
        result = geo.build(
            paths, countries.path, curated, places, data["contests"], counts
        )
        previews = []
        if args.preview:
            with progress.stage("drawing the SVG previews"):
                previews = geo.preview(
                    result, args.preview, directory / geo.PREVIEW_DIR
                )
    except (geo.GeoError, gpkg.GpkgError, obvody.ObvodyError) as e:
        _error(f"ems geo: {e}")
        return 1
    sizes = geo.write(result, out)
    record.record()
    _print(geo.report(result, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes)} files)"])
    _print(f"wrote {path.relative_to(cfg.root)}" for path in previews)
    return 0


def _run_basemap(args: argparse.Namespace) -> int:
    return _per_election(args, _basemap)


def _basemap(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    osm = _input(cfg, election.osm)
    okresy = _input(cfg, election.zbgis[1])
    obce = _input(cfg, election.zbgis[0])
    directory = cfg.election_build_dir(election)
    out = directory / basemap.OUTPUT_DIR
    record = _stamp(
        cfg,
        election,
        "basemap",
        args.force,
        [out],
        inputs=[osm, okresy, obce],
        # libosmium assembles the water areas and multipolygon buildings.
        values={"osmium": basemap.LIBRARY},
    )
    if record is None:
        return 0
    try:
        files = basemap.build(
            osm.path, _extract_gpkg(cfg, okresy), _extract_gpkg(cfg, obce)
        )
    except (basemap.BaseMapError, geo.GeoError, gpkg.GpkgError) as e:
        _error(f"ems basemap: {e}")
        return 1
    sizes = basemap.write(files, out, _gzip_memo(directory, "basemap"))
    record.record()
    _print(basemap.report(files, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes)} files)"])
    return 0


def _run_addresses(args: argparse.Namespace) -> int:
    return _per_election(args, _addresses)


def _addresses(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    register = _input(cfg, election.addresses)
    overrides = cfg.overrides[election.slug]
    zbgis = _input(cfg, election.zbgis[0])
    units = _input(cfg, election.units.input)
    built = _built_candidates(cfg, election)
    directory = cfg.election_build_dir(election)
    curated = cfg.election_dir(election)
    out = directory / addresses.OUTPUT_DIR
    outside = directory / addresses.OUTSIDE_FILE
    places = directory / addresses.OBVOD_DIR
    record = _stamp(
        cfg,
        election,
        "addresses",
        args.force,
        [out, outside, places],
        inputs=[register, zbgis, units],
        files=[built, *_okrsky_files(cfg, election)],
        trees=[curated / obvody.DIRECTORY],
        values={
            "overrides address": overrides.address,
            "overrides address_skip": sorted(overrides.address_skip),
            # The okrsky of each obec, from the units input.
            "code okrsokrules": stamp.code_digest("okrsokrules"),
        },
    )
    if record is None:
        return 0
    contests = json.loads(built.read_bytes())["contests"]
    try:
        result = addresses.build(
            register.path,
            _extract_gpkg(cfg, zbgis),
            curated,
            contests,
            overrides.address,
            overrides.address_skip,
            okrsokrules.okrsok_counts(cfg, election),
        )
    except (
        addresses.AddressesError,
        gpkg.GpkgError,
        obvody.ObvodyError,
        jobs.JobError,
    ) as e:
        _error(f"ems addresses: {e}")
        return 1
    sizes = addresses.write(result, out, _gzip_memo(directory, "addresses"))
    addresses.write_outside(result, outside)
    obvody.write_places(result.places, places)
    record.record()
    _print(addresses.report(result, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes):,} files)"])
    return 0


def _run_results(args: argparse.Namespace) -> int:
    """Run the results step of `make`: the final results of the pinned inputs.

    The oldest election first: a later one's are compared with it.
    """
    return _per_election(args, _results, oldest_first=True)


def _results(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> int:
    out = cfg.results_dir(election)
    if not election.results.inputs:
        progress.note(
            f"config/{config.ELECTIONS_FILE} names no final results of the"
            " election: they stay as `ems results` left them"
        )
        return 0
    packages = [_input(cfg, name) for name in election.results.inputs]
    curated = cfg.election_dir(election)
    compare = _compare(cfg, election)
    record = _stamp(
        cfg,
        election,
        "results",
        args.force,
        [out, *([compare.out] if compare else [])],
        inputs=[*packages, *(compare.inputs if compare else [])],
        files=[_built_candidates(cfg, election), *([compare.links] if compare else [])],
        trees=[
            cfg.election_build_dir(election) / geo.OUTPUT_DIR,
            curated / obvody.DIRECTORY,
            *(compare.trees if compare else []),
        ],
        values={"results": election.results} | (compare.values if compare else {}),
    )
    if record is None:
        return 0
    try:
        written = _write_final(
            cfg, election, [raw.path for raw in packages], out, merge=False
        )
    except (results.ResultsError, OSError, KeyError, ValueError) as e:
        _error(f"ems results: {e}")
        return 1
    record.record()
    _report_written(out, written)
    return 0


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
        sizes = build.write(site, out, _gzip_memo(cfg.build_dir, "build"))
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
    # The contests of the elections built here; a deployed bundle passed
    # its checks where it was built.
    contests = {
        election.slug: [c["id"] for c in json.loads(built.read_bytes())["contests"]]
        for election in cfg.elections
        if (
            built := cfg.election_build_dir(election) / candidates.OUTPUT_FILE
        ).is_file()
    }
    checks = check.run(out, cfg, contests)
    _print(check.report(checks))
    return 1 if any(c.problems for c in checks) else 0


def _gzip_memo(directory: Path, step: str) -> Path:
    """Return where *step* keeps the gzip sizes it measured last.

    *directory* is the election's build directory, or for the site's own
    (``build``) data/build/.
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
        "for kinds that read an election's data (obvod-rules, okrsok-rules):"
        " that election, its day or slug (default: the latest); research is"
        " of the latest only",
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
        help="give an earlier election the latest's obvod and okrsok rules where they fit",
        description=(
            "Where the obvod-rules and okrsok-rules jobs of an earlier"
            " election found no document, copy the latest election's rules"
            " into its data/curated/ if the obvody, seats and okrsky provably"
            " match, marked reused; for the obce listed in its adopt.toml,"
            " whose documents place no address, draw the units with them"
            " where their numbers and seats are the earlier election's,"
            " marked adopted (see src/election_map_slovakia/reuse.py)."
        ),
    )
    _add_election(reuse_parser, "the earlier election, its day or slug")
    reuse_parser.set_defaults(run=_run_job_reuse)


def _run_job_make(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.size is not None and args.size < 1:
        raise ConfigError("--size must be at least 1")
    kind = jobs.kinds()[args.kind]
    if args.election and not kind.per_election:
        raise ConfigError(
            f"--election: {kind.name} jobs are of the latest election only"
            + (
                "; an earlier one reuses its findings dated before its day"
                if kind.name == research.NAME
                else ""
            )
        )
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
    except jobs.JobError as e:
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
        except jobs.JobError as e:
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
    except jobs.JobError as e:
        _error(f"ems job reuse: {e}")
        return 1
    _print(lines)
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
            "Count the latest election's candidates --only selects (places,"
            " research languages; as for `ems job make research`) researched"
            " with the current allowlist, with findings, in pending jobs and"
            " still to do."
        ),
    )
    status.add_argument(
        "--only", nargs="+", action="extend", default=[], metavar="NAME"
    )
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
        _print(research.coverage(cfg, args.only))
    except jobs.JobError as e:
        _error(f"ems research status: {e}")
        return 1
    return 0


def _add_results_parser(commands: argparse._SubParsersAction) -> None:
    p = commands.add_parser(
        "results",
        help="election results: poll, final, fake, deploy",
        description=(
            "Write an election's results, data/build/<election day>/results/"
            " (which `ems build` copies into the site), from volbysr.sk"
            " (poll), the definitive CSV tables (final) or dummy data (fake);"
            " deploy the results on an election night (deploy). See"
            " docs/results.md and src/election_map_slovakia/results.py."
        ),
    )
    sub = p.add_subparsers(title="results commands", metavar="COMMAND", required=True)

    def directory(parser: argparse.ArgumentParser) -> None:
        _add_election(parser, "whose results to write (default: the latest)")
        parser.add_argument(
            "--dir",
            type=Path,
            default=None,
            help="the results directory (default: data/build/<election day>/results/)",
        )

    poll = sub.add_parser(
        "poll",
        help="poll volbysr.sk and rewrite the results whenever the counting moves on",
        description=(
            "Fetch the progress files of volbysr.sk every INTERVAL seconds"
            " (conditional requests), and when one changed the per-unit"
            " files; keep every file fetched under data/raw/results/<UTC"
            " time>/ and rewrite the results when their content changed."
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
        help="deploy the results after every change (as `results deploy --yes`)",
    )
    directory(poll)
    poll.set_defaults(run=_run_results_poll)
    final = sub.add_parser(
        "final",
        help="write the definitive results (CSV zips of volbysr.sk)",
        description=(
            "Read the definitive results, the zips of CSV tables of the"
            " municipal and the regional election: the zips or directories"
            " of them given; else the election's `results` inputs where"
            " config/elections.toml names them (`ems"
            " fetch` downloads them); else downloaded from"
            " https://volbysr.sk/oso/files/OSO<year>_SK_csv.zip and"
            " osk/files/OSK<year>_SK_csv.zip and kept under"
            " data/raw/results/<UTC time>/. They replace the contests they"
            " have in the results; with both elections the phase becomes"
            " final."
        ),
    )
    final.add_argument(
        "packages",
        nargs="*",
        type=Path,
        metavar="ZIP_OR_DIR",
        help="read these instead of the inputs or the downloaded packages",
    )
    directory(final)
    final.set_defaults(run=_run_results_final)
    fake = sub.add_parser(
        "fake",
        help="write dummy results for testing the app",
        description=(
            "Write deterministic dummy results of the counting at STAGE"
            " (none, early, mid, late, final) from the election's"
            " data/build/<election day>/; the counts"
            " only grow from stage to stage for the same --seed."
        ),
    )
    fake.add_argument("stage", choices=list(results.STAGES), metavar="STAGE")
    fake.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    directory(fake)
    fake.set_defaults(run=_run_results_fake)
    deploy = sub.add_parser(
        "deploy",
        help="deploy the results of every election to their Pages project",
        description=(
            "Show what the election's results hold and check them, write the"
            " results part of the site (dist/results/: every election's) and"
            " deploy it with Wrangler to the Pages project results_project"
            " of config/site.toml as a production deployment, after asking"
            " unless --yes. The deployment carries the results key of"
            f" {lock.LOCK_FILE} marked live, so that a release of that key"
            " leaves it in place; the app and the bundles stay as they are."
        ),
    )
    deploy.add_argument("--yes", action="store_true", help="do not ask")
    _add_election(deploy, "whose results to show and check (default: the latest)")
    deploy.set_defaults(run=_run_results_deploy)


def _results_dir(
    cfg: config.Config, election: config.Election, args: argparse.Namespace
) -> Path:
    """Return the directory a results command writes; see :func:`_written`."""
    return args.dir if args.dir is not None else cfg.results_dir(election)


def _written(
    cfg: config.Config, election: config.Election, directory: Path, written: dict | None
) -> None:
    """Note that a results command wrote *directory*, unless *written* is None.

    The results step of `make` would take the election's results directory
    for its own output, up to date, and keep what poll, fake or final wrote
    there instead of the results of the inputs: its stamp goes.
    """
    if (
        written is not None
        and directory.resolve() == cfg.results_dir(election).resolve()
    ):
        _stamp_path(cfg, election, "results").unlink(missing_ok=True)


def _reference(cfg: config.Config, election: config.Election) -> results.Reference:
    try:
        return results.load_reference(
            cfg.election_build_dir(election), cfg.election_dir(election)
        )
    except results.ResultsError as e:
        raise ConfigError(str(e)) from e


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
    *,
    merge: bool,
) -> dict | None:
    """Write the definitive results of *packages* to *out*; return the status.

    With *merge*, into the results there, replacing the contests the
    packages have; else in their place. Written as of the packages' newest
    data, so that the same packages give the same files, and only if they
    keep the contract (``results.check``): a unit whose votes do not add up
    stops it. ŠÚ SR's packages of 2022 (format ``susr``) hold every contest,
    so they always replace what is there. The okrsky get the figures of the
    election before, if any (:func:`_past`).
    """
    if election.results.format == "susr":
        if len(packages) != len(config.RESULT_FORMATS["susr"] or ()):
            raise results.ResultsError("the 2022 results are two packages, oso, osk")
        try:
            oso, osk = (statoffice.open_package(Path(p)) for p in packages)
            final = statoffice.read_results(oso, osk)
        except statoffice.StatOfficeError as e:
            raise results.ResultsError(str(e)) from e
        merged = final.live
    else:
        ref = _reference(cfg, election)
        live, elections = results.read_final(packages, ref.contests)
        old = results.read_live(out) if merge else None
        merged = results.merge(old, live, elections)
    merged.past = _past(cfg, election, merged)
    return results.write(out, merged, results.data_time(merged), checked=True)


class _Compare(NamedTuple):
    """The election before one, which its results are compared with.

    And what the comparison reads (:mod:`crosswalk`) and writes (*out*).
    """

    earlier: config.Election
    registers: tuple[_Raw, _Raw]
    """The address registers of the earlier election and of this one."""
    zbgis: tuple[_Raw, _Raw]
    """Their boundaries, level 0, which name the obce of the registers."""
    links: Path
    trees: list[Path]
    """Both elections' addr/ output and the earlier one's results."""
    values: dict[str, object]
    out: Path

    @property
    def inputs(self) -> list[_Raw]:
        """Return the downloads read."""
        return [*self.registers, *self.zbgis]


def _compare(cfg: config.Config, election: config.Election) -> _Compare | None:
    """Return what *election*'s results are compared with; None if nothing."""
    earlier = next((e for e in cfg.elections if e.day < election.day), None)
    if earlier is None:
        return None
    both = (earlier, election)
    built = cfg.election_build_dir(election)
    return _Compare(
        earlier,
        (_input(cfg, earlier.addresses), _input(cfg, election.addresses)),
        (_input(cfg, earlier.zbgis[0]), _input(cfg, election.zbgis[0])),
        built / bundle.LINKS_DIR / f"{earlier.slug}.json",
        [
            *(cfg.election_build_dir(e) / addresses.OUTPUT_DIR for e in both),
            cfg.results_dir(earlier),
        ],
        {
            "crosswalk code": stamp.code_digest("crosswalk"),
            **{
                f"overrides {e.slug} address": (
                    cfg.overrides[e.slug].address,
                    sorted(cfg.overrides[e.slug].address_skip),
                )
                for e in both
            },
        },
        built / crosswalk.OUTPUT_DIR / f"{earlier.slug}.json",
    )


def _past(
    cfg: config.Config, election: config.Election, live: results.Live
) -> results.Past:
    """Return the ``past`` of *election*'s results *live*: the election before's.

    Mapped onto its okrsky by the crosswalk, which is written beside them.
    """
    compare = _compare(cfg, election)
    if compare is None:
        return results.Past()
    earlier = compare.earlier
    before = results.read_live(cfg.results_dir(earlier))
    if before is None:
        raise ConfigError(
            f"{cfg.results_dir(earlier)} has no results; run `ems make"
            f" --election {earlier.slug}` first"
        )
    if not compare.links.is_file():
        raise ConfigError(f"{compare.links} missing; run `ems links` first")
    admins: dict[Path, candidates.Admin] = {}
    registers = []
    for e, register, zbgis in zip(
        (earlier, election), compare.registers, compare.zbgis, strict=True
    ):
        gpkg = _extract_gpkg(cfg, zbgis)
        if gpkg not in admins:
            admins[gpkg] = candidates.load_admin(gpkg)
        overrides = cfg.overrides[e.slug]
        registers.append(
            crosswalk.Register(
                register.path,
                admins[gpkg],
                overrides.address,
                overrides.address_skip,
                cfg.election_build_dir(e) / addresses.OUTPUT_DIR,
            )
        )
    walk = crosswalk.make(live, before, registers, earlier.day)
    linked = json.loads(compare.links.read_bytes())["candidacies"]
    past = crosswalk.past(live, before, walk, linked)
    output.write_file(compare.out, output.to_json(crosswalk.to_json(walk)) + b"\n")
    _print(crosswalk.report(walk, past))
    _print([f"wrote {compare.out.relative_to(cfg.root)}"])
    return past


def _run_results_poll(args: argparse.Namespace) -> int:
    cfg = config.load()
    election = cfg.election(args.election)
    if election.results.format != "volbysr":
        raise ConfigError(
            f"results poll: the {election.slug} election's results are not"
            f" on volbysr.sk ({election.results.format}): its final results"
            " come from its inputs (`ems make`)"
        )
    out = _results_dir(cfg, election, args)
    client = _client(cfg)
    poller = results.Poller(client, _reference(cfg, election), out, _log)
    project = cfg.site.results_project
    try:
        while True:
            started = time.monotonic()
            try:
                written = poller.cycle()
            except OSError as e:
                _log(f"poll failed: {e}")
                written = None
            _written(cfg, election, out, written)
            if written is not None and args.deploy:
                code = _deploy_results(cfg, ask=False)
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


def _run_results_final(args: argparse.Namespace) -> int:
    cfg = config.load()
    election = cfg.election(args.election)
    out = _results_dir(cfg, election, args)
    try:
        packages = (
            args.packages
            or [_input(cfg, name).path for name in election.results.inputs]
            or results.fetch_final(_client(cfg), election.day.year)
        )
        _print([f"reading {p}" for p in packages])
        written = _write_final(cfg, election, packages, out, merge=True)
    except (results.ResultsError, OSError, KeyError, ValueError) as e:
        _error(f"ems results final: {e}")
        return 1
    _written(cfg, election, out, written)
    _report_written(out, written)
    return 0


def _run_results_fake(args: argparse.Namespace) -> int:
    cfg = config.load()
    election = cfg.election(args.election)
    if election != cfg.latest:
        raise ConfigError(
            f"results fake: only the latest election ({cfg.latest.slug})"
            f" has results to fake; the {election.slug} election's are final"
        )
    out = _results_dir(cfg, election, args)
    try:
        counts = okrsokrules.okrsok_counts(cfg, election)
        rule_sets = obvody.okrsok_rule_sets(cfg.election_dir(election))
    except (jobs.JobError, obvody.ObvodyError) as e:
        _error(f"ems results fake: {e}")
        return 1
    live = results.fake(
        _reference(cfg, election),
        args.stage,
        args.seed,
        counts,
        {obec: rules.okrsky for obec, rules in rule_sets.items()},
    )
    written = results.write(out, live)
    _written(cfg, election, out, written)
    _report_written(out, written)
    return 0


def _run_results_deploy(args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.results_dir(cfg.election(args.election))
    _print(results.describe(out))
    problems = results.check(out)
    if problems:
        _print([f"  {p}" for p in problems])
        _error(f"ems results deploy: {out} breaks the contract; not deployed")
        return 1
    return _deploy_results(cfg, ask=not args.yes)


def _deploy_results(cfg: config.Config, *, ask: bool) -> int:
    """Write the results part and deploy it, asking first if *ask*.

    Its deployment carries the results key of the committed lock, marked
    live (``pages.LIVE``): a release of that key leaves it in place.
    """
    keys = lock.read(cfg.root / lock.LOCK_FILE)
    if keys is None:
        raise ConfigError(f"{lock.LOCK_FILE} missing; run `ems data lock`")
    part = bundle.results_part(cfg, keys.results)
    out = cfg.root / build.OUTPUT_DIR / bundle.RESULTS_PART
    build.write(build.Site(part.files, part.copies, []), out)
    project = cfg.site.results_project
    message = f"{keys.results} {pages.LIVE}"
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
        if run in _UNSTAGED:
            return run(args)
        with progress.stage(args.command) as stage:
            code = run(args)
            stage.failed = code != 0
        return code
    except ConfigError as e:
        _error(f"ems: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
