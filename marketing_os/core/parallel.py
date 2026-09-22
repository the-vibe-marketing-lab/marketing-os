"""Run independent filesystem reads at the same time.

Nearly everything this program costs on a mounted filesystem is round-trip latency, not
computation. On a Windows drive seen from Linux a stat costs about 2.5 milliseconds and a
read about 3.4, whatever the file holds; a brain of fifteen hundred documents therefore
spends seconds waiting on the kernel and about a second thinking. Waiting is what an
operator feels when a dashboard takes a minute to appear, and profiling agrees: a status
run that takes 34 seconds of wall time burns 1.4 seconds of it on the processor.

Waiting is the one cost threads fix. Every call below releases the interpreter lock while
the kernel works, so many of them in flight cost about what one costs. Measured on a real
brain of 1,524 documents on such a mount: walking its 606 folders falls from 2.97 seconds
to 0.41, stat-ing every document falls from 4.92 to 0.39, and reading all of them falls
from 10.51 to 1.05.

Both helpers preserve order and neither touches shared state, so an answer computed across
threads is the same answer computed one at a time, in the same order. That is what lets
``mos status`` be quick without ceasing to be deterministic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

Item = TypeVar("Item")
Result = TypeVar("Result")

#: How many reads to keep in flight. Chosen against measurement rather than core count:
#: on the mount above, 8 workers already recover most of the loss and 32 recovers the
#: rest, with nothing to gain past it because the bottleneck is the remote filesystem
#: rather than this process.
WORKERS = 32


def pmap(function: Callable[[Item], Result], items: Iterable[Item]) -> list[Result]:
    """``[function(item) for item in items]``, with the waiting overlapped.

    Results come back in the order the items were given, so a caller that sorted its
    input is still sorted. One item is done on this thread: a pool costs more to start
    than a single call costs to make.
    """
    values = list(items)
    if len(values) < 2:
        return [function(value) for value in values]
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(values))) as pool:
        return list(pool.map(function, values))


def gather(*calls: Callable[[], Result]) -> tuple[Result, ...]:
    """Run each argument-free call at the same time and return the answers in order.

    For the handful of independent questions a status check asks of one brain — what does
    validation say, what context is answered, are the runtimes wired — where each is its
    own walk of its own part of the tree.

    An exception in any call is raised from here, and the earliest failing call in
    argument order is the one that raises, so a caller sees the same failure it would have
    seen running them one after another. The rest still finish first: these are reads, so
    letting them complete costs time and changes nothing.
    """
    if len(calls) < 2:
        return tuple(call() for call in calls)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        return tuple(future.result() for future in futures)
