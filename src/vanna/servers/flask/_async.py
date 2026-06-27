"""Sync bridges for running async agent code from Flask's WSGI threads.

Uses a single dedicated event loop running in a background thread, avoiding
the fragile per-request ``asyncio.new_event_loop()`` pattern.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, AsyncGenerator, Coroutine, Generator, Iterator, TypeVar

_T = TypeVar("_T")

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, name="vanna-async", daemon=True)
_thread.start()


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine to completion on the shared background loop."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result()


def iter_async(agen: AsyncGenerator[_T, None]) -> Iterator[_T]:
    """Iterate an async generator synchronously via the shared loop."""
    while True:
        try:
            yield asyncio.run_coroutine_threadsafe(agen.__anext__(), _loop).result()
        except StopAsyncIteration:
            return
