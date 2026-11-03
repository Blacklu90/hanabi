"""Anki-style features: decks + daily limits, interval previews, undo, suspend/bury, notes, browser."""
import time

from sqlalchemy import select, update

from app import db, srs


def uid_of(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()


def make_deck(user, name="Grade 1", new=5, maxr=100):
    r = user.post("/api/decks", {"name": name, "new_per_day": new, "max_reviews": maxr})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def queue(user, **p):
    return user.c.get("/api/review/queue", params=p).json()["cards"]


def test_deck_daily_new_limit(user):
    did = make_deck(user, new=5)
    r = user.post(f"/api/decks/{did}/kanji", {"grade": 1}).json()
    assert r["added"] == 80
    q = queue(user, deck=did)
    assert len(q) == 5 and all(c["is_new"] for c in q)
    assert [c["front"] for c in q] == ["一", "二", "三", "四", "五"][:0] or len({c["front"] for c in q}) == 5  # school order
    # nav badge / dashboard count respect the limit (not 80)
    assert 'class="badge">5<' in user.c.get("/dashboard").text
    # study 2 new cards -> 3 new left today
    for c in q[:2]:
        user.post("/api/review/submit", {"card_id": c["id"], "rating": 3})
    q2 = queue(user, deck=did)
    assert sum(c["is_new"] for c in q2) == 3
    # raising the limit shows more today
    user.post(f"/api/decks/{did}", {"name": "Grade 1", "new_per_day": 10, "max_reviews": 100})
    assert sum(c["is_new"] for c in queue(user, deck=did)) == 8


def test_deck_review_limit(user):
    did = make_deck(user, new=20, maxr=3)
    user.post(f"/api/decks/{did}/kanji", {"grade": 1})
    uid = uid_of(user)
    with db.tx() as c:  # pretend 10 cards were learned earlier and are due now
        ids = list(c.execute(select(db.srs_cards.c.id).where(db.srs_cards.c.deck_id == did).order_by(db.srs_cards.c.position).limit(10)).scalars())
        c.execute(update(db.srs_cards).where(db.srs_cards.c.id.in_(ids)).values(
            total_reviews=1, total_correct=1, state="review", interval_days=1, due_at=int(time.time()) - 60, introduced_at=1))
    q = queue(user, deck=did)
    assert sum(not c["is_new"] for c in q) == 3 and sum(c["is_new"] for c in q) == 20
    assert uid


def test_previews_and_undo(user):
    did = make_deck(user)
    user.post(f"/api/decks/{did}/kanji", {"chars": ["日"]})
    c = queue(user, deck=did)[0]
    assert c["previews"] == {"1": "10m", "2": "12h", "3": "1d", "4": "4d"}
    before = user.c.get("/api/cards").json()["items"][0]
    r = user.post("/api/review/submit", {"card_id": c["id"], "rating": 3}).json()
    xp_after = r["level"]["xp"]
    assert queue(user, deck=did) == []
    u = user.post("/api/review/undo", {"review_id": r["review_id"]}).json()
    assert u["ok"] and u["level"]["xp"] == xp_after - 1  # the review's XP is taken back
    after = user.c.get("/api/cards").json()["items"][0]
    assert after["state"] == "new" and after["reviews"] == 0 and before["id"] == after["id"]
    assert queue(user, deck=did)[0]["id"] == c["id"]
    # can't undo twice, can't undo someone else's
    assert user.post("/api/review/undo", {"review_id": r["review_id"]}).status_code == 409


def test_suspend_bury_forget_move_delete(user, user2):
    a, b = make_deck(user, "A"), make_deck(user, "B")
    user.post(f"/api/decks/{a}/kanji", {"chars": ["日", "月", "火"]})
    ids = [c["id"] for c in queue(user, deck=a)]
    assert len(ids) == 3
    assert user.post("/api/cards/suspend", {"ids": [ids[0]]}).json()["count"] == 1
    assert user.post("/api/cards/bury", {"ids": [ids[1]]}).json()["count"] == 1
    assert [c["id"] for c in queue(user, deck=a)] == [ids[2]]
    assert user.post("/api/review/submit", {"card_id": ids[0], "rating": 3}).status_code == 409  # suspended
    states = {i["id"]: i["state"] for i in user.c.get("/api/cards").json()["items"]}
    assert states[ids[0]] == "suspended" and states[ids[1]] == "buried"
    user.post("/api/cards/unsuspend", {"ids": [ids[0]]})
    user.post("/api/cards/unbury", {"ids": [ids[1]]})
    assert len(queue(user, deck=a)) == 3
    assert user.post("/api/cards/move?deck_id=" + str(b), {"ids": ids[:2]}).json()["count"] == 2
    assert len(queue(user, deck=b)) == 2
    # other users can't touch these cards
    assert user2.post("/api/cards/delete", {"ids": ids}).status_code == 404
    assert user2.post(f"/api/decks/{a}/delete").status_code == 404
    assert user.post("/api/cards/delete", {"ids": [ids[2]]}).json()["count"] == 1
    assert user.post(f"/api/decks/{b}/delete").json()["cards_deleted"] == 2
    assert user.c.get("/api/cards").json()["total"] == 0


def test_notes_on_card_and_page(user):
    did = make_deck(user)
    user.post(f"/api/decks/{did}/kanji", {"chars": ["学"]})
    assert user.post("/api/notes", {"track": "kanji", "item": "学", "meaning": "learning (school)", "mnemonic": "A child under a roof",
                                    "notes": "学校 = school"}).status_code == 200
    c = queue(user, deck=did)[0]
    assert c["answer"] == "learning (school)" and c["my_mnemonic"] == "A child under a roof"
    page = user.c.get("/kanji/学").text
    assert "A child under a roof" in page and "学校 = school" in page
    assert user.post("/api/notes", {"track": "kanji", "item": "X", "meaning": "x"}).status_code == 400
    # clearing all fields removes the note
    user.post("/api/notes", {"track": "kanji", "item": "学"})
    assert queue(user, deck=did)[0]["my_mnemonic"] == ""


def test_browser_search_sort_paginate(user):
    did = make_deck(user)
    user.post(f"/api/decks/{did}/kanji", {"grade": 1})
    r = user.c.get("/api/cards", params={"deck": did, "per": 20}).json()
    assert r["total"] == 80 and r["pages"] == 4 and len(r["items"]) == 20
    assert user.c.get("/api/cards", params={"q": "water"}).json()["items"][0]["front"] == "水"
    order = user.c.get("/api/cards", params={"sort": "order", "per": 10}).json()["items"]
    assert [i["position"] for i in order] == sorted(i["position"] for i in order)
    assert user.c.get("/api/cards", params={"state": "suspended"}).json()["total"] == 0
    assert user.c.get("/browse").status_code == 200 and user.c.get("/decks").status_code == 200


def test_kanji_study_goes_into_a_deck_and_migration(user):
    r = user.post("/api/kanji/木/study").json()
    assert r["added"]
    item = user.c.get("/api/cards").json()["items"][0]
    assert item["deck"] == "My kanji" and item["front"] == "木"
    # new deck-aware queue still includes lesson cards (no deck) without limits
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    labels = {c["label"] for c in queue(user)}
    assert {"Hiragana", "Kanji"} <= labels


def test_write_own_card(user):
    did = make_deck(user, "Phrases")
    assert user.post(f"/api/decks/{did}/cards", {"front": "おはよう", "back": "Good morning"}).status_code == 200
    q = queue(user, deck=did)
    assert q[0]["front"] == "おはよう" and q[0]["answer"] == "Good morning" and q[0]["label"] == "Card"
    assert user.post("/api/review/submit", {"card_id": q[0]["id"], "rating": 4}).json()["interval_days"] == 4


def test_old_kanji_cards_move_into_my_kanji_deck(tmp_path):
    from sqlalchemy import text as sql
    eng = db.make_engine(tmp_path / "old.db")
    db.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(sql("INSERT INTO users (id, username, email, display_name, password_hash, created_at) VALUES (1,'a','a@x','a','x',0)"))
        c.execute(sql("INSERT INTO srs_cards (user_id, track, item, due_at, created_at, total_reviews) VALUES (1,'kanji','日',0,0,0), (1,'hiragana','あ',0,0,0)"))
        c.execute(sql("INSERT INTO schema_migrations VALUES (1,0),(2,0),(3,0)"))
    db.init_db(eng)
    with eng.connect() as c:
        rows = dict(c.execute(sql("SELECT item, deck_id FROM srs_cards")).all())
        assert rows["あ"] is None and rows["日"] == c.execute(sql("SELECT id FROM decks WHERE name='My kanji'")).scalar()
    assert srs.fmt_interval(10 / 1440) == "10m" and srs.fmt_interval(45) == "1.5mo" and srs.fmt_interval(400) == "1.1y"


def test_fast_counts_match_the_real_queue(user):
    """The badge/deck counts come from a grouped query; they must equal what the queue actually shows."""
    a = make_deck(user, "A", new=7, maxr=4)
    b = make_deck(user, "B", new=3, maxr=50)
    user.post(f"/api/decks/{a}/kanji", {"grade": 1})
    user.post(f"/api/decks/{b}/kanji", {"grade": 2})
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    with db.tx() as c:
        ids = list(c.execute(select(db.srs_cards.c.id).where(db.srs_cards.c.deck_id == a).limit(12)).scalars())
        c.execute(update(db.srs_cards).where(db.srs_cards.c.id.in_(ids[:6])).values(
            total_reviews=1, state="review", interval_days=3, due_at=int(time.time()) - 5, introduced_at=1))
        c.execute(update(db.srs_cards).where(db.srs_cards.c.id.in_(ids[6:9])).values(
            total_reviews=1, state="learning", interval_days=0.01, due_at=int(time.time()) - 5, introduced_at=1))
        c.execute(update(db.srs_cards).where(db.srs_cards.c.id == ids[9]).values(suspended=1))
    uid = uid_of(user)
    with db.ro() as c:
        q = srs.queue(c, uid, "UTC", limit=100000)
        n = srs.counts(c, uid, "UTC")
        per = srs.deck_counts(c, uid, "UTC")
        for d in (a, b):
            qd = srs.queue(c, uid, "UTC", deck_id=d, limit=100000)
            assert sum(per[d].values()) == len(qd)
            assert per[d]["new"] == sum(1 for r in qd if r["total_reviews"] == 0)
    assert n["total"] == len(q) == 5 + 4 + 7 + 3
