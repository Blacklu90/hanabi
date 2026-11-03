"""Test setup: each test session gets a private copy of the content database."""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = Path(tempfile.mkdtemp(prefix="hanabi-test-"))
TEST_DB = _tmp / "test.db"  # starts empty; the app fills content from data/content.db at startup, like a fresh install
os.environ["HANABI_DB"] = str(TEST_DB)
os.environ["HANABI_DEV"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.security import limiter  # noqa: E402

BASE = "http://testserver"


def _csrf(client):
    r = client.get("/login")
    import re
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


class User:
    def __init__(self, client, name):
        self.c, self.name = client, name

    @property
    def csrf(self):
        import re
        r = self.c.get("/settings")
        return re.search(r'<meta name="csrf" content="([^"]+)"', r.text).group(1)

    def post(self, url, json=None):
        return self.c.post(url, json=json or {}, headers={"X-CSRF-Token": self._tok})


def make_user(name="alice", password="correct horse battery"):
    c = TestClient(app, base_url=BASE)
    tok = _csrf(c)
    r = c.post("/register", data={"username": name, "email": f"{name}@example.com", "password": password,
                                   "display_name": name.title(), "timezone": "Europe/Berlin", "csrf": tok}, follow_redirects=False)
    assert r.status_code == 303, r.text
    u = User(c, name)
    u._tok = u.csrf
    return u


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app, base_url=BASE)


_counter = [0]


@pytest.fixture
def user():
    _counter[0] += 1
    return make_user(f"user{_counter[0]}")


@pytest.fixture
def user2():
    _counter[0] += 1
    return make_user(f"other{_counter[0]}")
