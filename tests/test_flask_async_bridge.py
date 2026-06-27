import pytest

pytest.importorskip("flask")

from vanna.servers.flask._async import run_async, iter_async  # noqa: E402


def test_run_async_executes_coroutine():
    async def coro():
        return 42

    assert run_async(coro()) == 42


def test_iter_async_collects_generator():
    async def agen():
        for i in range(3):
            yield i

    assert list(iter_async(agen())) == [0, 1, 2]


def test_iter_async_closes_generator_on_early_exit():
    closed = []

    async def agen():
        try:
            for i in range(10):
                yield i
        finally:
            closed.append(True)

    it = iter_async(agen())
    assert next(it) == 0
    it.close()  # consumer stops early (e.g. SSE client disconnect)
    assert closed == [True]
