"""Reset progress keeps the account; delete account removes everything. Both need the password and a typed word."""
import re

from sqlalchemy import func, select

from app import db


def _uid(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()


def _count(table, uid):
    t = db.metadata.tables[table]
    with db.ro() as c:
        return c.execute(select(func.count()).select_from(t).where(t.c.user_id == uid)).scalar()


def _form(user, url, **data):
    return user.c.post(url, data={"csrf": user._tok, **data}, follow_redirects=False)


def _some_progress(user):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    user.post("/api/words/add", {"count": 5})


def test_reset_needs_password_and_word_and_keeps_account(user, user2):
    _some_progress(user)
    _some_progress(user2)
    uid, other = _uid(user), _uid(user2)
    assert _count("srs_cards", uid) == 10 and _count("xp_events", uid) > 0
    assert _form(user, "/profile/reset", password="wrong password!", confirm="RESET").status_code == 400
    assert _form(user, "/profile/reset", password="correct horse battery", confirm="nope").status_code == 400
    assert _count("srs_cards", uid) == 10  # nothing happened
    r = _form(user, "/profile/reset", password="correct horse battery", confirm="reset")
    assert r.status_code == 303 and r.headers["location"] == "/profile?saved=reset"
    for t in ("srs_cards", "decks", "lesson_completions", "xp_events", "achievements", "reviews", "progress"):
        assert _count(t, uid) == 0, t
    with db.ro() as c:
        assert c.execute(select(db.users.c.xp).where(db.users.c.id == uid)).scalar() == 0
        assert c.execute(select(db.settings.c.user_id).where(db.settings.c.user_id == uid)).first()  # settings kept
    assert user.c.get("/dashboard").status_code == 200  # still signed in
    assert _count("srs_cards", other) == 10  # other people untouched


def test_delete_account_removes_everything_and_signs_out(user, user2):
    _some_progress(user)
    _some_progress(user2)
    uid, other = _uid(user), _uid(user2)
    assert _form(user, "/profile/delete", password="correct horse battery", confirm="RESET").status_code == 400
    r = _form(user, "/profile/delete", password="correct horse battery", confirm="DELETE")
    assert r.status_code == 303 and r.headers["location"] == "/?deleted=1"
    with db.ro() as c:
        assert c.execute(select(db.users.c.id).where(db.users.c.id == uid)).first() is None
    for name, t in db.metadata.tables.items():
        if "user_id" in t.c:
            assert _count(name, uid) == 0, name
    assert user.c.get("/dashboard", follow_redirects=False).status_code in (302, 303)
    assert _count("srs_cards", other) == 10


def test_profile_shows_the_buttons(user):
    page = user.c.get("/profile").text
    assert "Reset all my progress" in page and "Delete my account and data" in page
    assert re.search(r'action="/profile/delete"', page)
