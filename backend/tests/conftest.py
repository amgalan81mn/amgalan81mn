import os
import tempfile

os.environ["UNAA_DATABASE_URL"] = os.environ.get(
    "UNAA_TEST_DATABASE_URL", "postgresql+psycopg://unaa:unaa@localhost:5432/unaa_test"
)
os.environ["UNAA_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="unaa-uploads-")
os.environ["UNAA_SMS_MODE"] = "dev"
os.environ["UNAA_PAYMENTS_MODE"] = "dev"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app import models  # noqa: F401  (хүснэгтүүдийг бүртгэнэ)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean():
    yield
    with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def make_user(db):
    counter = iter(range(10_000_000, 99_999_999))

    def _make(**kw) -> models.User:
        user = models.User(phone=f"+976{next(counter)}", **kw)
        db.add(user)
        db.commit()
        return user

    return _make
