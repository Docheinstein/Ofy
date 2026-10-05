import json
from pathlib import Path

import pytest
from sqlmodel import create_engine

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from offliner import db

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    db.set_engine(engine)
    yield engine
    db._engine = None
