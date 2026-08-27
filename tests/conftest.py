import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ssa.models import Base


@pytest.fixture()
def engine():
    """In-memory SQLite engine with the full schema created."""
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()
