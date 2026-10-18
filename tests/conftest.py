import pytest

from arl.env.seed import new_store


@pytest.fixture
def conn():
    store = new_store()
    yield store
    store.close()
