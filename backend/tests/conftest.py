import os
import tempfile

# Must be set before the app is imported: settings are read at import time.
_tmp = tempfile.mkdtemp()
# Set TEST_DATABASE_URL=postgresql://... to run the suite against PostgreSQL.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["APP_ENV"] = "development"
os.environ["PAYMENT_PROVIDER"] = "mock"
os.environ["APP_BASE_URL"] = "http://localhost:5173"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.routers import auth as auth_router, billing as billing_router  # noqa: E402

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    auth_router.reset_limiters()
    billing_router.reset_limiters()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_client():
    """Factory for independent cookie jars (several users at once)."""
    clients = []

    def _make():
        c = TestClient(app)
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.close()


def register(c, email="ana@example.com", password=PASSWORD, name="Ana Reyes"):
    return c.post("/api/auth/register", json={"email": email, "password": password, "full_name": name})
