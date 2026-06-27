import pytest
from vanna.servers.flask._async import run_async, iter_async


def test_run_async_executes_coroutine():
    async def coro():
        return 42

    assert run_async(coro()) == 42


def test_iter_async_collects_generator():
    async def agen():
        for i in range(3):
            yield i

    assert list(iter_async(agen())) == [0, 1, 2]
