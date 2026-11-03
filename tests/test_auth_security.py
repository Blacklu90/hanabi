import re
import time

from conftest import BASE, _csrf, make_user
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.security import hash_password, verify_password
from sqlalchemy import select


def test_password_hashing():
    h = hash_password("hunter2hunter2")
    assert h.startswith("scrypt$") and "hunter2" not in h
    assert verify_password("hunter2hunter2", h) and not verify_password("wrong", h)
    assert hash_password("x" * 12) != hash_password("x" * 12)  # salted


def test_register_login_logout(client):
    tok = _csrf(client)
    r = client.post("/register", data={"username": "zed", "email": "zed@example.com", "password": "short", "csrf": tok})
    assert r.status_code == 400 and "at least 10" in r.text
    r = client.post("/register", data={"username": "zed", "email": "zed@example.com", "password": "long enough pw", "csrf": tok}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.cookies.get("shuinkan_session") or client.cookies.get("shuinkan_session")
    assert cookie
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    page = client.get("/dashboard")
    assert page.status_code == 200
    csrf = re.search(r'<meta name="csrf" content="([^"]+)"', page.text).group(1)
    assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
    assert client.get("/dashboard", follow_redirects=False).status_code == 303
    # duplicate
    c2 = TestClient(app, base_url=BASE)
    r = c2.post("/register", data={"username": "ZED", "email": "other@example.com", "password": "long enough pw", "csrf": _csrf(c2)})
    assert r.status_code == 400 and "already registered" in r.text
    # login with email or username
    c3 = TestClient(app, base_url=BASE)
    t3 = _csrf(c3)
    assert c3.post("/login", data={"login": "zed@example.com", "password": "nope nope nope", "csrf": t3}).status_code == 400
    assert c3.post("/login", data={"login": "Zed", "password": "long enough pw", "csrf": t3}, follow_redirects=False).status_code == 303


def test_csrf_required(user):
    # form without token
    assert user.c.post("/settings", data={"daily_goal": "50"}).status_code == 403
    # API without header
    assert user.c.post("/api/lesson/complete", json={"lesson": "hiragana-1"}).status_code == 403
    assert user.c.post("/api/lesson/complete", json={"lesson": "hiragana-1"}, headers={"X-CSRF-Token": "bogus"}).status_code == 403
    assert user.post("/api/lesson/complete", {"lesson": "hiragana-1"}).status_code == 200


def test_origin_check(user):
    r = user.c.post("/api/lesson/complete", json={"lesson": "hiragana-1"}, headers={"X-CSRF-Token": user._tok, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_login_rate_limit(client):
    make_user("ratey")
    tok = _csrf(client)
    codes = [client.post("/login", data={"login": "ratey", "password": "wrong password!", "csrf": tok}).status_code for _ in range(10)]
    assert codes[0] == 400 and codes[-1] == 429


def test_password_reset_flow(client):
    make_user("resetme", password="first password")
    tok = _csrf(client)
    r = client.post("/forgot", data={"email": "resetme@example.com", "csrf": tok})
    assert "Development mode" in r.text
    link = re.search(r'href="(http://testserver/reset/[^"]+)"', r.text).group(1)
    path = link.replace("http://testserver", "")
    assert "Choose a new password" in client.get(path).text
    assert client.post(path, data={"password": "brand new password", "csrf": tok}, follow_redirects=False).status_code == 303
    # token is single-use
    assert client.post(path, data={"password": "another new password", "csrf": tok}).status_code == 400
    assert client.post("/login", data={"login": "resetme", "password": "brand new password", "csrf": tok}, follow_redirects=False).status_code == 303
    # unknown email: same response, no link (fresh anonymous browser)
    anon = TestClient(app, base_url=BASE)
    r = anon.post("/forgot", data={"email": "nobody@example.com", "csrf": _csrf(anon)})
    assert "If that email has an account" in r.text and "/reset/" not in r.text


def test_password_change_signs_out_other_sessions():
    u = make_user("pwchange", password="old password here")
    other = TestClient(app, base_url=BASE)
    t = _csrf(other)
    assert other.post("/login", data={"login": "pwchange", "password": "old password here", "csrf": t}, follow_redirects=False).status_code == 303
    assert other.get("/dashboard").status_code == 200
    page = u.c.get("/profile")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = u.c.post("/profile/password", data={"current": "wrong", "new": "new password here", "csrf": csrf})
    assert r.status_code == 400
    r = u.c.post("/profile/password", data={"current": "old password here", "new": "new password here", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert u.c.get("/dashboard").status_code == 200  # this browser stays signed in
    assert other.get("/dashboard", follow_redirects=False).status_code == 303  # the other is signed out


def test_session_expiry(user):
    from sqlalchemy import update
    with db.tx() as c:
        uid = c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()
        c.execute(update(db.sessions).where(db.sessions.c.user_id == uid).values(expires_at=int(time.time()) - 1))
    assert user.c.get("/dashboard", follow_redirects=False).status_code == 303


def test_user_isolation(user, user2):
    r = user.post("/api/quiz/start", {"kind": "hiragana-recognition", "pool": "all"})
    qid = r.json()["id"]
    # other user can't see or answer it
    assert user2.c.get(f"/quiz/{qid}").status_code == 404
    assert user2.post(f"/api/quiz/{qid}/answer", {"idx": 0, "choice": 0}).status_code == 404
    assert user2.post("/api/quiz/submit", {"id": qid}).status_code == 404
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    q = user.c.get("/api/review/queue").json()["cards"]
    assert q
    assert user2.post("/api/review/submit", {"card_id": q[0]["id"], "rating": 3}).status_code == 404
    assert user2.c.get("/api/review/queue").json()["cards"] == []
    g = user.post("/api/game/start", {"deck": "hiragana"}).json()
    assert user2.post("/api/game/complete", {"id": g["id"], "moves": 6, "misses": 0}).status_code == 404


def test_settings_validation_and_persistence(user):
    page = user.c.get("/settings")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    base = {"csrf": csrf, "daily_goal": "50", "mastery_accuracy": "90", "mastery_reps": "5",
            "mastery_interval": "30", "burst_minutes": "10", "theme": "dark", "show_romaji": "1", "timezone": "Asia/Tokyo"}
    assert user.c.post("/settings", data={**base, "daily_goal": "5"}).status_code == 400
    assert user.c.post("/settings", data={**base, "burst_minutes": "99"}).status_code == 400
    assert user.c.post("/settings", data={**base, "mastery_interval": "400"}).status_code == 400
    assert user.c.post("/settings", data=base, follow_redirects=False).status_code == 303
    with db.ro() as c:
        uid = c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()
        s = c.execute(select(db.settings).where(db.settings.c.user_id == uid)).one()
    assert (s.daily_goal, s.theme, s.show_romaji, s.show_jlpt, s.mastery_reps, s.burst_minutes, s.timezone) == (50, "dark", 1, 0, 5, 10, "Asia/Tokyo")
    assert 'data-theme="dark"' in user.c.get("/dashboard").text


def test_profile_update(user, user2):
    page = user.c.get("/profile")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = user.c.post("/profile", data={"display_name": "New Name", "username": user2.name, "email": "x@example.com", "csrf": csrf})
    assert r.status_code == 400 and "already used" in r.text
    r = user.c.post("/profile", data={"display_name": "New Name", "username": user.name + "x", "email": "fresh@example.com", "csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303
    assert "New Name" in user.c.get("/dashboard").text


def test_palette_setting(user):
    page = user.c.get("/settings")
    assert 'data-palette="shuinkan"' in page.text and 'id="pal-sakura"' in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    base = {"csrf": csrf, "daily_goal": "20", "mastery_accuracy": "85", "mastery_reps": "4", "mastery_interval": "21",
            "burst_minutes": "5", "theme": "system", "timezone": "UTC"}
    assert user.c.post("/settings", data={**base, "palette": "matcha"}, follow_redirects=False).status_code == 303
    assert 'data-palette="matcha"' in user.c.get("/dashboard").text
    user.c.post("/settings", data={**base, "palette": "<script>"}, follow_redirects=False)
    assert 'data-palette="shuinkan"' in user.c.get("/dashboard").text  # unknown values fall back safely
    assert "日本語" in user.c.get("/dashboard").text  # the logo
