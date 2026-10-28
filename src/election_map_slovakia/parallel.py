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

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from typing import Any, TypeVar

_R = TypeVar("_R")


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
    """
    tasks = list(tasks)
    if len(tasks) <= 1:
        yield from (fn(*task) for task in tasks)
        return
    order = list(range(len(tasks)))
    if cost is not None:
        order.sort(key=lambda i: -cost(tasks[i]))
    with ProcessPoolExecutor() as pool:
        futures = {i: pool.submit(fn, *tasks[i]) for i in order}
        try:
            yield from (futures[i].result() for i in range(len(tasks)))
        finally:
            pool.shutdown(cancel_futures=True)


def call(fn: Callable[..., _R], *args: Any) -> _R:
    """Return ``fn(*args)``.

    As the function of :func:`each`, it runs tasks ``(fn, *args)``
    of different functions in one pool.
    """
    return fn(*args)
