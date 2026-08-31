from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ssa.config import Settings

# Neon is serverless and recycles idle connections. Ingestion holds a session open
# across minutes of slow model calls, so its connection is idle exactly when the
# server decides to drop it — and a dropped connection mid-run poisons the Session,
# losing the rest of an extraction that has already been paid for.
#
# pre_ping costs one cheap round trip per checkout and transparently replaces a
# dead connection; recycle retires connections before the server does it for us.
POOL_PRE_PING = True
POOL_RECYCLE_SECONDS = 280


def make_engine(database_url: str | None = None):
    """Create a SQLAlchemy engine. Falls back to Settings when no URL is given.

    Configured to tolerate serverless connection recycling — see above.
    """
    url = database_url or Settings().database_url
    kwargs: dict = {"future": True}
    if not url.startswith("sqlite"):
        kwargs["pool_pre_ping"] = POOL_PRE_PING
        kwargs["pool_recycle"] = POOL_RECYCLE_SECONDS
    return create_engine(url, **kwargs)


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
