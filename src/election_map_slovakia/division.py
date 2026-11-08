"""An election's territorial division: how many okrsky each obec votes in.

ŠÚ SR's territorial division of a vote, the election's ``units`` input
(:class:`election_map_slovakia.config.Units`), counts the okrsky (polling
districts) of every obec, the special ones without territory among them
(:mod:`election_map_slovakia.special`). The ``addresses`` step shares an
obec's addresses among that many okrsky, the bundles name the special okrsky
that voted, and the ``okrsok-rules`` and ``obvod-rules`` jobs
(:mod:`election_map_slovakia.okrsokrules`,
:mod:`election_map_slovakia.obvodrules`) read it too. Apart from the jobs,
so that the key of an election's map, which counts the code of its steps
(:data:`election_map_slovakia.lock.MAP_MODULES`), does not count theirs.
"""

from __future__ import annotations

import datetime as dt
import functools
from pathlib import Path

from election_map_slovakia import config, special, statoffice, tables, xlsx
from election_map_slovakia.config import Config, Election, Units


class DivisionError(Exception):
    """An election's territorial division is missing or unreadable."""


def units_of(election: Election) -> Units:
    """Return where *election*'s territorial division comes from.

    Every regular election, which the jobs are of, has one; fail for an
    election without (a country-wide one may have none).
    """
    if election.units is None:
        raise DivisionError(
            f"the {election.slug} election has no territorial division (units)"
        )
    return election.units


def units_path(cfg: Config, election: Election) -> Path:
    """Return the file of *election*'s territorial division (its ``units`` input)."""
    name = units_of(election).input
    # The configuration checks that the election's inputs exist.
    inp = next(i for i in cfg.inputs.inputs if i.name == name)
    path = cfg.raw_dir / inp.name / inp.file
    if not path.is_file():
        raise DivisionError(f"{path} missing; run `ems fetch` first")
    return path


@functools.cache
def units_package(path: Path) -> statoffice.Package:
    """Return the 2022 package at *path* (:func:`units_path`), read once per process."""
    try:
        return statoffice.open_package(path)
    except statoffice.StatOfficeError as e:
        raise DivisionError(str(e)) from None


def okrsok_counts(cfg: Config, election: Election) -> dict[str, int]:
    """Return obec → its number of okrsky in *election* (its ``units`` input)."""
    path = units_path(cfg, election)
    units = units_of(election)
    if units.format == "susr":
        try:
            return statoffice.okrsok_counts(units_package(path))
        except (statoffice.StatOfficeError, ValueError) as e:
            raise DivisionError(f"{path}: {e}") from None
    if units.format == "volbysr":
        try:
            package = tables.open_package([path], dt.UTC)
            t = package.table(units.table or "")
            code = t.column("Kód obce")
            count = t.column("Počet volebných okrskov", "Počet okrskov")
            return {r[code]: int(r[count]) for r in t.rows}
        except (tables.TableError, ValueError) as e:
            raise DivisionError(f"{path}: {e}") from None
    try:
        header, rows = xlsx.find_header(xlsx.read_rows(path), "Kód kraja")
        code, count = header.index("Kód obce"), header.index("Počet okrskov")
        return {r[code]: int(r[count]) for r in rows}
    except (xlsx.XlsxError, ValueError, IndexError) as e:
        raise DivisionError(f"{path}: {e}") from None


def special_okrsky(cfg: Config, election: Election) -> special.Specials:
    """Return *election*'s special okrsky (:mod:`election_map_slovakia.special`).

    Empty without a territorial division, which counts no okrsky, and
    where neither its package nor ``special-okrsky.toml`` declares any (the
    division is then not read).
    """
    path = cfg.election_dir(election) / special.FILE
    if election.units is None or (not election.units.special and not path.is_file()):
        return {}
    return special.read(
        units_path(cfg, election),
        election.units,
        config.load_special(path) if path.is_file() else None,
        okrsok_counts(cfg, election),
        str(path.relative_to(cfg.root)),
    )


def territorial_counts(cfg: Config, election: Election) -> dict[str, int]:
    """Return obec → its okrsky with territory in *election*.

    Those of the territorial division (:func:`okrsok_counts`) less its
    special okrsky (:func:`special_okrsky`): a document numbers its own
    okrsky 1..N, the special ones counted after them.
    """
    return special.territorial(
        okrsok_counts(cfg, election), special_okrsky(cfg, election)
    )
