import pytest

from open_ng911 import db, registry


@pytest.fixture
def conn():
    return db.connect(s3=False)


@pytest.fixture
def vt():
    j = registry.job("us-vt")
    return j, registry.jurisdiction(j)
