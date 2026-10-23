"""The ``ems`` command line.

Each pipeline step is a subcommand registered in :func:`build_parser` with
``set_defaults(run=...)``; ``run`` receives the parsed arguments and returns
the exit code.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from election_map_slovakia import (
    __version__,
    addresses,
    build,
    candidates,
    check,
    config,
    fetch,
    geo,
    gpkg,
    incumbents,
    jobs,
    obvody,
    output,
    progress,
    research,
    stamp,
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
            " Files the server reports as unchanged, or whose content is"
            " unchanged, are kept as they are. When the server fails, a pinned"
            " input is taken from a copy with its sha256, on disk or in"
            " data/fallback/, with a warning. Fails if an input fails,"
            " except an optional one (read by no step), which only warns."
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
            "Read the four MV SR candidate lists and the ZBGIS municipality"
            " table from data/raw/, match every row to a municipality code,"
            " merge candidacies into persons and write"
            f" data/build/{candidates.OUTPUT_FILE}. Fails listing every row"
            " that matches no municipality; fixes go to config/overrides.toml."
            + _SKIPPED
        ),
    )
    _add_force(p)
    p.set_defaults(run=_run_candidates)

    p = commands.add_parser(
        "geo",
        help="build the map geometry and obvod borders",
        description=(
            "Read ZBGIS boundary levels 0-2 from data/raw/, reproject them to"
            " WGS84 and write per-okres levels of detail of the obce and a"
            " coarse view, each a topology whose kraj, okres, regional council"
            " obvod and Bratislava and Košice city obvod borders are its obce"
            " borders, and the countries around Slovakia from Natural Earth,"
            f" reaching under its ZBGIS border, to data/build/{geo.OUTPUT_DIR}/."
            " Obvod membership comes from data/curated/obvody/ and is checked"
            f" against data/build/{candidates.OUTPUT_FILE} (run `ems"
            " candidates` first). Fails if neighbouring areas do not share"
            " their borders, or the countries around leave a gap at Slovakia's."
            + _SKIPPED
        ),
    )
    p.add_argument(
        "--preview",
        metavar="OKRES",
        help="also write SVG previews (country, Bratislava, this okres at full"
        f" detail) to data/build/{geo.PREVIEW_DIR}/; implies --force",
    )
    _add_force(p)
    p.set_defaults(run=_run_geo)

    p = commands.add_parser(
        "addresses",
        help="build the address search files",
        description=(
            "Read the MV SR address register from data/raw/, match every"
            " municipality to its code, assign the municipal council obvod"
            " where the municipality has only one, and write the search index"
            f" and one file per municipality to data/build/{addresses.OUTPUT_DIR}/."
            " Checks every point against its municipality polygon (outliers"
            f" in data/build/{addresses.OUTSIDE_FILE}) and resolves a random"
            " sample of addresses to their contests. Needs"
            f" data/build/{candidates.OUTPUT_FILE} (run `ems candidates`"
            " first). Fails listing every municipality that matches no code;"
            " fixes go to config/overrides.toml." + _SKIPPED
        ),
    )
    _add_force(p)
    p.set_defaults(run=_run_addresses)

    p = commands.add_parser(
        "build",
        help="assemble the static site in dist/",
        description=(
            "Wipe dist/ and write the site: the app shell per language and"
            " the language picker, web/ assets, UI strings, the geometry and"
            " address files, and the candidates split per okres, city and"
            " kraj plus a name search index. Needs the output of"
            " `candidates`, `geo` and `addresses` in data/build/. The layout"
            " is described in src/election_map_slovakia/build.py."
        ),
    )
    p.set_defaults(run=_run_build)

    p = commands.add_parser(
        "check",
        help="verify dist/ before it is deployed",
        description=(
            "Check the site in dist/: file count and sizes against the budgets"
            " in config/site.toml, JSON validity, _headers within the"
            " Cloudflare Pages limits, that every file the frontend can"
            " request exists, that every contest of"
            f" data/build/{candidates.OUTPUT_FILE} is in the one area file the"
            " frontend looks in, that no HTML, JS or CSS refers to another"
            " origin, and that address points lie within their municipality."
            " Prints a summary table and the first problems of each failed"
            " check; the exit code is 1 on any problem."
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
            " data or web/; then `ems serve` shows the result. Steps whose"
            " inputs have not changed since they last succeeded are skipped;"
            " build and check always run."
        ),
    )
    _add_force(p)
    # `geo` reads its --preview option, which `make` leaves out.
    p.set_defaults(run=_run_make, preview=None)

    p = commands.add_parser(
        "serve",
        help="serve dist/ over HTTP for local testing",
        description=(
            "Serve dist/ (run `ems build` first) until interrupted, with"
            " the response headers of dist/_headers as on Cloudflare Pages."
        ),
    )
    p.add_argument("--host", default="127.0.0.1", help="address to bind")
    p.add_argument("--port", type=int, default=8000, help="port to listen on")
    p.set_defaults(run=_run_serve)

    _add_job_parser(commands)
    _add_research_parser(commands)
    return parser


def _run_fetch(args: argparse.Namespace) -> int:
    cfg = config.load()
    names = [inp.name for inp in cfg.inputs.inputs]
    unknown = [name for name in args.only if name not in names]
    if unknown:
        _error(f"ems fetch: unknown input {unknown[0]!r}; known: {', '.join(names)}")
        return 2
    optional = {inp.name for inp in cfg.inputs.inputs if inp.optional}
    failed, warned, copied = False, [], []
    width = max(map(len, names))
    try:
        for o in fetch.fetch(
            cfg.inputs,
            cfg.raw_dir,
            fallback_dir=cfg.fallback_dir,
            only=args.only,
            force=args.force,
        ):
            size = output.format_size(o.bytes) if o.status != "failed" else ""
            _print(
                [f"{o.name:<{width}}  {o.status:<9} {size:>10}  {o.detail}".rstrip()]
            )
            if o.status == "fallback":
                copied.append(o.name)
            if o.status != "failed":
                continue
            if o.name in optional:
                warned.append(o.name)
            else:
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
    if copied:
        _error(
            f"ems fetch: warning: the server of input(s) {', '.join(copied)}"
            " failed; their pinned copies are used"
        )
    return 1 if failed else 0


def _run_candidates(args: argparse.Namespace) -> int:
    cfg = config.load()
    lists = {kind: _input(cfg, name) for kind, name in candidates.INPUTS.items()}
    results = {name: _input(cfg, name) for name in incumbents.INPUTS}
    zbgis = _input(cfg, candidates.ZBGIS_INPUT)
    out = cfg.build_dir / candidates.OUTPUT_FILE
    record = _stamp(
        cfg,
        "candidates",
        args.force,
        [out],
        inputs=[*lists.values(), *results.values(), zbgis],
        values={"overrides": cfg.overrides, "election": cfg.site.election},
    )
    if record is None:
        return 0
    try:
        gpkg_path = _extract_gpkg(cfg, zbgis)
        paths = {kind: path for kind, (path, _) in lists.items()}
        result = candidates.build(
            paths,
            gpkg_path,
            cfg.overrides,
            {name: path for name, (path, _) in results.items()},
            cfg.site.election,
        )
    except (
        candidates.CandidatesError,
        incumbents.IncumbentsError,
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


_Raw = tuple[Path, config.Input]
"""A downloaded input file and its entry in config/inputs.toml."""


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
    path = cfg.raw_dir / name / inp.file
    if not path.is_file():
        raise ConfigError(f"{path} missing; run `ems fetch` first")
    return path, inp


def _extract_gpkg(cfg: config.Config, raw: _Raw) -> Path:
    """Return the GeoPackage of a ZBGIS input, unpacked into data/build/."""
    archive, inp = raw
    return gpkg.extract(archive, inp.members[0], cfg.build_dir)


def _stamp(
    cfg: config.Config,
    step: str,
    force: bool,
    outputs: list[Path],
    *,
    inputs: Iterable[_Raw] = (),
    files: Iterable[Path] = (),
    trees: Iterable[Path] = (),
    values: dict[str, object] | None = None,
) -> stamp.Stamp | None:
    """Return the stamp *step* records once done, or None if it is up to date.

    *inputs* are downloads (file and configuration), *files* and *trees*
    other files and directories it reads, *values* configuration it gets.
    """
    inputs = list(inputs)
    values = (values or {}) | {f"config input {inp.name}": inp for _, inp in inputs}
    with progress.stage("comparing the inputs with the last successful run"):
        record = stamp.Stamp(
            cfg.build_dir / f"{step}.stamp.json",
            stamp.inputs(
                cfg.root, step, [*(p for p, _ in inputs), *files], trees, values
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


def _run_geo(args: argparse.Namespace) -> int:
    cfg = config.load()
    zbgis = {level: _input(cfg, name) for level, name in geo.INPUTS.items()}
    countries = _input(cfg, geo.NEIGHBOURS_INPUT)
    built = _built_candidates(cfg)
    out = cfg.build_dir / geo.OUTPUT_DIR
    places = cfg.build_dir / addresses.OBVOD_DIR
    if not places.is_dir():
        raise ConfigError(f"{places} missing; run `ems addresses` first")
    record = _stamp(
        cfg,
        "geo",
        args.force or bool(args.preview),
        [out],
        inputs=[*zbgis.values(), countries],
        files=[built],
        trees=[cfg.curated_dir / obvody.DIRECTORY, places],
    )
    if record is None:
        return 0
    data = json.loads(built.read_bytes())
    counts = Counter(c["contest"] for c in data["candidacies"])
    try:
        paths = {level: _extract_gpkg(cfg, raw) for level, raw in zbgis.items()}
        result = geo.build(
            paths, countries[0], cfg.curated_dir, places, data["contests"], counts
        )
        previews = []
        if args.preview:
            with progress.stage("drawing the SVG previews"):
                previews = geo.preview(
                    result, args.preview, cfg.build_dir / geo.PREVIEW_DIR
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


def _run_addresses(args: argparse.Namespace) -> int:
    cfg = config.load()
    register = _input(cfg, addresses.INPUT)
    zbgis = _input(cfg, candidates.ZBGIS_INPUT)
    built = _built_candidates(cfg)
    out = cfg.build_dir / addresses.OUTPUT_DIR
    outside = cfg.build_dir / addresses.OUTSIDE_FILE
    places = cfg.build_dir / addresses.OBVOD_DIR
    record = _stamp(
        cfg,
        "addresses",
        args.force,
        [out, outside, places],
        inputs=[register, zbgis],
        files=[built],
        trees=[cfg.curated_dir / obvody.DIRECTORY],
        values={"overrides address": cfg.overrides.address},
    )
    if record is None:
        return 0
    contests = json.loads(built.read_bytes())["contests"]
    try:
        result = addresses.build(
            register[0],
            _extract_gpkg(cfg, zbgis),
            cfg.curated_dir,
            contests,
            cfg.overrides.address,
        )
    except (addresses.AddressesError, gpkg.GpkgError, obvody.ObvodyError) as e:
        _error(f"ems addresses: {e}")
        return 1
    sizes = addresses.write(result, out)
    addresses.write_outside(result, outside)
    obvody.write_places(result.places, places)
    record.record()
    _print(addresses.report(result, sizes))
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes):,} files)"])
    return 0


def _built_candidates(cfg: config.Config) -> Path:
    """Return data/build/candidates.json, which `candidates` must have written."""
    built = cfg.build_dir / candidates.OUTPUT_FILE
    if not built.is_file():
        raise ConfigError(f"{built} missing; run `ems candidates` first")
    return built


def _run_build(_args: argparse.Namespace) -> int:
    cfg = config.load()
    try:
        site = build.assemble(cfg)
        out = cfg.root / build.OUTPUT_DIR
        sizes = build.write(site, out)
    except build.BuildError as e:
        _error(f"ems build: {e}")
        return 1
    _print(build.report(sizes))
    _print(["translations:", *(f"  {line}" for line in site.log)])
    _print([f"wrote {out.relative_to(cfg.root)}/ ({len(sizes):,} files)"])
    return 0


def _run_check(_args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.root / build.OUTPUT_DIR
    if not out.is_dir():
        raise ConfigError(f"{out} missing; run `ems build` first")
    data = json.loads(_built_candidates(cfg).read_bytes())
    contests = [c["id"] for c in data["contests"]]
    checks = check.run(out, cfg.site, cfg.languages, contests)
    _print(check.report(checks))
    return 1 if any(c.problems for c in checks) else 0


_MAKE_STEPS = {
    "candidates": _run_candidates,
    "addresses": _run_addresses,
    "geo": _run_geo,
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
            skipped = (
                f" ({', '.join(names[i + 1 :])} not run)" if names[i + 1 :] else ""
            )
            _error(
                f"ems make: stopped at `{name}`{skipped}; fix the problem above"
                " and run `ems make` again"
            )
            return code
    return 0


def _run_serve(args: argparse.Namespace) -> int:
    cfg = config.load()
    out = cfg.root / build.OUTPUT_DIR
    needed = ("index.html", build.HEADERS, build.NOT_FOUND)
    if not all((out / name).is_file() for name in needed):
        raise ConfigError(f"{out} has no site; run `ems build` first")
    try:
        build.serve(out, args.host, args.port)
    except KeyboardInterrupt:
        pass
    except build.BuildError as e:
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


def _run_job_make(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.size is not None and args.size < 1:
        raise ConfigError("--size must be at least 1")
    try:
        made = jobs.make(
            cfg,
            jobs.kinds()[args.kind],
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
            "Count the candidates --only selects (places, research languages;"
            " as for `ems job make research`) researched with the current"
            " allowlist, with findings, in pending jobs and still to do."
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


def _print(lines: Iterable[str]) -> None:
    """Print *lines* to stdout, below any progress line still open."""
    progress.end_line()
    for line in lines:
        print(line)


def _error(message: str) -> None:
    progress.end_line()
    print(message, file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return the exit code.

    Every command but ``serve`` reports its progress as a stage of its own.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "run", None)
    if run is None:
        parser.print_help()
        return 2
    try:
        if run is _run_serve:
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
