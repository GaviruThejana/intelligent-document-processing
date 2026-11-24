import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="idp-test-")
os.environ.update(DATABASE_URL=f"sqlite:///{_tmp}/test.db", UPLOAD_DIR=f"{_tmp}/uploads", QUEUE_MODE="inline",
                  MAX_UPLOAD_MB="1", ANTHROPIC_API_KEY="")  # must be set BEFORE importing the app

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class Api:
    def __init__(self, c): self.c = c

    def upload(self, data: bytes, name="inv.pdf", mime="application/pdf"):
        return self.c.post("/api/v1/documents", files={"file": (name, data, mime)})

    def doc(self, i): return self.c.get(f"/api/v1/documents/{i}").json()
    def audit(self, i): return self.c.get(f"/api/v1/documents/{i}/audit").json()


@pytest.fixture()
def api(client):
    return Api(client)
