"""
Single persistent thread for all Playwright operations.
Playwright's sync API must be used from the thread that created it,
so all browser calls are dispatched here via pw_run().
"""
import threading
import queue

class _Worker:
    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="playwright-worker")
        self._thread.start()

    def _run(self):
        while True:
            item = self._q.get()
            if item is None:
                return
            fn, event, box = item
            try:
                box["value"] = fn()
            except Exception as exc:
                box["error"] = exc
            finally:
                event.set()

    def submit(self, fn):
        box: dict = {}
        ev = threading.Event()
        self._q.put((fn, ev, box))
        ev.wait()
        if "error" in box:
            raise box["error"]
        return box["value"]


_worker = _Worker()


def pw_run(fn):
    """Run fn in the dedicated Playwright worker thread and return its result."""
    return _worker.submit(fn)
