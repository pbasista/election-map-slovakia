"""Which URLs the candidate research may cite (``config/sources.toml``).

A URL is allowed when its host is a listed host or a subdomain of one (the
host's category), or the official website of a municipality or region
(``municipal-domains.toml``, category ``official``), and

- no label of its host is an excluded one and no segment of its path is
  (user-generated sections: ``blog.sme.sk``, ``*.blog.pravda.sk``,
  ``/blog/...``), and
- neither the host nor any parent domain of it is on the blocklist, which
  overrides the allowlist.

Only http(s) URLs qualify.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable

from election_map_slovakia.config import Sources, is_blocked

OFFICIAL = "official"


def host_of(url: str) -> str:
    """Return the lowercase host of *url* without a trailing dot ("" if none)."""
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.rstrip(".").lower()


def _within(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def category(url: str, sources: Sources) -> str | None:
    """Return the category *url* is allowed under, or None if it is not."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    host = host_of(url)
    if not host or is_blocked(host, sources.blocklist):
        return None
    if set(host.split(".")) & set(sources.exclude_host_labels):
        return None
    segments = urllib.parse.unquote(parts.path).lower().split("/")
    if set(segments) & set(sources.exclude_path_segments):
        return None
    for name, hosts in sources.categories.items():
        if any(_within(host, h) for h in hosts):
            return name
    official = (*sources.municipal_sites.values(), *sources.regional_sites.values())
    if any(_within(host, h) for h in official):
        return OFFICIAL
    return None


def hosts(sources: Sources, categories: Iterable[str]) -> list[str]:
    """Return the listed hosts of *categories*, in order.

    Without the official websites of municipalities and regions, which depend
    on the person.
    """
    return [h for name in categories for h in sources.categories[name]]
