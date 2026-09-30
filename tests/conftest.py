"""Pytest fixtures for RePlexOn."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-" + "0" * 54)  # the app refuses to start without one

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import user as _user_models  # noqa: F401  (registers the tables)


@pytest.fixture
def db():
    """An in-memory SQLite database with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
