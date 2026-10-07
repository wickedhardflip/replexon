"""Pytest fixtures for RePlexOn."""
import os
import tempfile

# Before any app import: a fixed test key and a throwaway data dir (never the repo's data/).
os.environ.setdefault("SECRET_KEY", "test-only-" + "0" * 54)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="replexon-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(os.environ["DATA_DIR"], "app.db")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401  (registers the tables)


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
