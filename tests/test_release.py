import re
from pathlib import Path
from typing import NamedTuple

from election_map_slovakia import cli, config

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
# A job (two spaces in, below `jobs:`), the jobs it needs, and a command
# running a step of every election or, with --election "$ELECTION", of the
# election of its matrix alone; any other argument is no such command.
_JOB = re.compile(r"^  ([\w-]+):\s*$")
_NEEDS = re.compile(r"^    needs:\s*(.+?)\s*$")
_EMS = re.compile(r"\buv run ems (\w+)( --election \"\$ELECTION\")?\s*$")


class _Job(NamedTuple):
    needs: list[str]
    commands: list[tuple[str, bool]]
    """Each step it runs, and whether of the election of its matrix alone."""


def _jobs(text: str) -> dict[str, _Job]:
    jobs: dict[str, _Job] = {}
    lines = iter(text.splitlines())
    for line in lines:
        if line == "jobs:":
            break
    job = None
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        if m := _JOB.match(line):
            job = jobs[m[1]] = _Job([], [])
        elif job is None:
            continue
        elif m := _NEEDS.match(line):
            job.needs.extend(n.strip() for n in m[1].strip("[]").split(","))
        elif m := _EMS.search(line):
            job.commands.append((m[1], m[2] is not None))
    return jobs


def _before(jobs: dict[str, _Job], name: str) -> set[str]:
    """Return the jobs *name* runs after: those it needs, and theirs."""
    seen: set[str] = set()
    todo = list(jobs[name].needs)
    while todo:
        if (job := todo.pop()) not in seen:
            seen.add(job)
            todo += jobs[job].needs
    return seen


def _made(commands: list[tuple[str, bool]], steps: set[str]) -> set[str]:
    """Return the steps of *commands* made of every election (`make`: all)."""
    made: set[str] = set()
    for step, alone in commands:
        if not alone:
            made |= steps if step == "make" else {step}
    return made


def _reads(
    cfg: config.Config, declared: dict[tuple[str, str], cli._Declared], step: str
) -> list[tuple[str, str, str]]:
    """Return each election's day with each upstream step and key it reads."""
    return [
        (e.day.isoformat(), s, k)
        for e in cfg.elections
        if (d := declared.get((step, e.day.isoformat()))) is not None
        for s, k in d.upstream
    ]


def _unmade(cfg: config.Config, text: str) -> tuple[int, list[str]]:
    """Return how many steps the jobs of workflow *text* run per election, and
    each upstream output (cli._declarations) a step reads where it runs that
    neither a job before made for every election nor, for the same
    election, a step before it in the job."""
    declared = {(s, k): d for s, k, d in cli._declarations(cfg)}
    steps = {s for s, _ in declared}
    jobs = _jobs(text)
    per_election = 0
    unmade = []
    for name, job in jobs.items():
        made = _made([c for j in _before(jobs, name) for c in jobs[j].commands], steps)
        alone_here: set[str] = set()
        for step, alone in job.commands:
            if step not in steps:
                continue
            per_election += alone
            for key, s, k in _reads(cfg, declared, step):
                # A step of every election runs them in the order their
                # reads of each other need (cli._per_election).
                if not (
                    s in made
                    or (s == step and not alone)
                    or (alone and k == key and s in alone_here)
                ):
                    unmade.append(f"{name}: ems {step} of {key} reads {s} of {k}")
            (alone_here if alone else made).add(step)
    return per_election, unmade


def test_each_release_job_has_made_what_its_steps_read():
    """Each election's steps job runs on a runner of its own: an output of
    another election its steps read must come from a job before it (the
    candidates job), or the release fails (`... missing; run ems candidates
    first`)."""
    cfg = config.load(REPO / "config")
    per_election, unmade = _unmade(cfg, WORKFLOW.read_text(encoding="utf-8"))
    # The steps job's commands were found: a workflow the parser no longer
    # reads fails here rather than passing on nothing.
    assert per_election >= 2
    assert unmade == []
