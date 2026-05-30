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
        # Playwright sync API 는 asyncio 루프가 실행 중이지 않은 스레드에서만 동작한다.
        # WindowsSelectorEventLoopPolicy 는 쓰지 않는다 — SelectorEventLoop 는
        # Windows 에서 subprocess 를 지원하지 않아 NotImplementedError 가 발생한다.
        # 대신 현재 스레드의 이벤트 루프를 완전히 제거해 Playwright 가 자체 루프를 만들게 한다.
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.close()
        except RuntimeError:
            pass
        asyncio.set_event_loop(None)

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
