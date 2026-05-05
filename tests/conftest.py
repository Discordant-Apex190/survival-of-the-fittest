from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

# Ensure tests use an isolated sqlite database before app import.
test_db_path = Path("data") / f"test_{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{test_db_path.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    from backend.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    from backend.db.session import engine, init_db

    init_db()
    with Session(engine) as session:
        yield session


@pytest.fixture
def sim_settings():
    from backend.core.config import Settings

    return Settings(min_population=2)
