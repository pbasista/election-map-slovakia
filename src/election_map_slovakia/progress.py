"""Tell the user on stderr what the pipeline is doing, so it never looks stuck.

A :func:`stage` prints its message when it starts and how long it took when
it ends; stages nest, indented. A stage that counts its items with
:meth:`Stage.advance` also shows how far it is. On a terminal the count
updates in place, and a stage that printed nothing else ends on its own
line (``reading … done in 1.2 s``); elsewhere, as in a log file, every
message is a line of its own and the count is printed every
:data:`LOG_INTERVAL` seconds. The summaries of the commands go to stdout.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Generator, Iterable, Iterator
from contextlib import contextmanager
from typing import TypeVar

LOG_INTERVAL = 5.0
"""Seconds between progress lines when stderr is not a terminal."""
_TTY_INTERVAL = 0.1
_MINUTE = 60
_ERASE_LINE = "\r\033[K"
_T = TypeVar("_T")

_depth = 0
_open: Stage | None = None
"""The stage whose line on the terminal is not ended yet."""


class Stage:
    """A running :func:`stage`."""

    def __init__(
        self, message: str, total: int | None, show: Callable[[int], str]
    ) -> None:
        """Set up *message* at the current depth; see :func:`stage`."""
        self.message = message
        self.total = total
        self.show = show
        self.done = 0
        self.failed = False
        """Set where the block fails without raising, to say so at the end."""
        self.indent = "  " * _depth
        self.tty = sys.stderr.isatty()
        self.start = self.shown = time.monotonic()

    def advance(self, n: int = 1) -> None:
        """Count *n* more items done; show the count when it is time to."""
        self.update(self.done + n)

    def update(self, done: int) -> None:
        """Set the count of items done; show it when it is time to."""
        global _open
        self.done = done
        now = time.monotonic()
        if now - self.shown < (_TTY_INTERVAL if self.tty else LOG_INTERVAL):
            return
        self.shown = now
        if self.tty:
            if _open is not self:
                end_line()
            _print(f"{_ERASE_LINE}{self.indent}{self.message} … {self._count()}")
            _open = self
        else:
            _print(f"{self.indent}{self.message}: {self._count()}\n")

    def track(self, items: Iterable[_T]) -> Iterator[_T]:
        """Yield *items*, counting each as done when the next is asked for."""
        for item in items:
            yield item
            self.advance()

    def _count(self) -> str:
        if not self.total:
            return self.show(self.done)
        return (
            f"{self.done / self.total:.0%}"
            f" ({self.show(self.done)} of {self.show(self.total)})"
        )


@contextmanager
def stage(
    message: str,
    total: int | None = None,
    show: Callable[[int], str] = "{:,}".format,
) -> Generator[Stage]:
    """Print *message* now and, when the block ends, how long it took.

    *total* is the number of items the block will count with
    :meth:`Stage.advance`, where known; *show* formats a count.
    """
    global _depth, _open
    current = Stage(message, total, show)
    end_line()
    if current.tty:
        _print(f"{current.indent}{message} …")
        _open = current
    else:
        _print(f"{current.indent}{message} …\n")
    _depth += 1
    raised = True
    try:
        yield current
        raised = False
    finally:
        _depth -= 1
        outcome = "failed after" if raised or current.failed else "done in"
        took = f"{outcome} {_duration(time.monotonic() - current.start)}"
        if _open is current:
            _print(f"{_ERASE_LINE}{current.indent}{message} … {took}\n")
            _open = None
        else:
            end_line()
            _print(f"{current.indent}{message}: {took}\n")


def note(message: str) -> None:
    """Print *message* as a line of its own, indented as a stage at this depth."""
    end_line()
    _print(f"{'  ' * _depth}{message}\n")


def end_line() -> None:
    """End the open stage line on the terminal, so other output starts afresh."""
    global _open
    if _open is not None:
        _print("\n")
        _open = None


def _print(text: str) -> None:
    sys.stderr.write(text)
    sys.stderr.flush()


def _duration(seconds: float) -> str:
    if seconds < _MINUTE:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), _MINUTE)
    return f"{minutes} min {rest:02d} s"
