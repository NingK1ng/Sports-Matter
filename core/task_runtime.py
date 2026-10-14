"""Keep async clients on one event loop per Celery child process/thread."""
import asyncio
import os
import threading

_state = threading.local()


def run_async(coroutine):
    pid = os.getpid()
    if getattr(_state, "pid", None) != pid or _state.loop.is_closed():
        _state.pid = pid
        _state.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_state.loop)
    task = _state.loop.create_task(coroutine)
    try:
        return _state.loop.run_until_complete(task)
    except BaseException:
        # A Celery soft timeout must not leave network/DB work running into the
        # next task on this loop. Cancellation also runs coroutine finally blocks.
        task.cancel()
        _state.loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        raise
