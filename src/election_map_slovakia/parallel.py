"""Run the independent pieces of a step on every CPU.

The steps spend most of their time in Python code and in shapely calls
that hold the GIL, on pieces that do not depend on each other:
the obce and levels of detail of ``geo``, the levels and okresy of
``basemap``, the parts of ``check``.
So the pieces run in worker processes.
Their results come back in the order of the tasks,
so the output is the same as if they ran one by one.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import contextmanager
from typing import Any, TypeVar

_R = TypeVar("_R")

_shared: Executor | None = None
"""The worker processes the calls of :func:`each` run in, within :func:`shared`."""


def each(
    fn: Callable[..., _R],
    tasks: Iterable[tuple[Any, ...]],
    cost: Callable[[tuple[Any, ...]], float] | None = None,
) -> Iterator[_R]:
    """Yield ``fn(*task)`` for each of *tasks*, in order, run in worker processes.

    *fn* must be a module-level function, and the tasks and results picklable
    (a ``pyproj.Transformer`` is not: a worker makes its own).
    A single task runs here, without starting workers.
    With *cost*, an estimate of each task's time, the costliest start first,
    so that no worker is left with a long task when the others are done; the
    results still come in the order of the tasks.
    The first exception a task raises is raised here,
    and the tasks not yet started are cancelled.
    Within :func:`shared`, the workers are those it started.
    """
    tasks = list(tasks)
    if len(tasks) <= 1:
        yield from (fn(*task) for task in tasks)
        return
    order = list(range(len(tasks)))
    if cost is not None:
        order.sort(key=lambda i: -cost(tasks[i]))
    if _shared is not None:
        yield from _ordered(_shared, fn, tasks, order)
        return
    with ProcessPoolExecutor() as workers:
        try:
            yield from _ordered(workers, fn, tasks, order)
        finally:
            workers.shutdown(cancel_futures=True)


def _ordered(
    workers: Executor,
    fn: Callable[..., _R],
    tasks: list[tuple[Any, ...]],
    order: list[int],
) -> Iterator[_R]:
    """Yield ``fn(*task)`` of *tasks* run by *workers*, submitted in *order*.

    The tasks not yet started when it stops (by an exception) are cancelled.
    """
    futures = {i: workers.submit(fn, *tasks[i]) for i in order}
    try:
        yield from (futures[i].result() for i in range(len(tasks)))
    finally:
        for future in futures.values():
            future.cancel()


@contextmanager
def shared() -> Generator[None]:
    """Within, run every call of :func:`each` in one set of worker processes.

    For a step that calls it several times in turn: starting the workers,
    each importing the modules, took a third of a second each time.
    """
    global _shared
    if _shared is not None:
        yield
        return
    with pool() as workers:
        _shared = workers
        try:
            yield
        finally:
            _shared = None


@contextmanager
def pool() -> Generator[Executor]:
    """Yield the worker processes, one per CPU, as :func:`each` runs them.

    For tasks that depend on others' results: submit each once its inputs
    are in. On exit, also by an exception, the tasks not started are
    cancelled.
    """
    with ProcessPoolExecutor() as workers:
        try:
            yield workers
        finally:
            workers.shutdown(cancel_futures=True)


def call(fn: Callable[..., _R], *args: Any) -> _R:
    """Return ``fn(*args)``.

    As the function of :func:`each`, it runs tasks ``(fn, *args)``
    of different functions in one pool.
    """
    return fn(*args)
