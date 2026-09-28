"""Keep blocking, process-global Matplotlib work off the Discord event loop."""

import asyncio
import threading
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")
_render_lock = threading.Lock()
_render_slot = asyncio.Lock()


def _render_locked(renderer: Callable[[], T]) -> T:
    with _render_lock:
        return renderer()


async def render_chart(renderer: Callable[[], T]) -> T:
    # Queue on the bot's event loop, before occupying a shared worker thread.
    await _render_slot.acquire()
    try:
        task = asyncio.create_task(asyncio.to_thread(_render_locked, renderer))
    except BaseException:
        _render_slot.release()
        raise

    def finished(task: asyncio.Task[T]) -> None:
        _render_slot.release()
        # A cancelled caller no longer retrieves a worker's eventual exception.
        if not task.cancelled():
            task.exception()

    task.add_done_callback(finished)
    # Cancellation cannot stop a running thread. Keep its slot until it finishes.
    return await asyncio.shield(task)
