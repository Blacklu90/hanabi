"""Wi-Fi sync: encryption, merging two devices' data, and a real host/join over a socket."""
import base64
import json
import time

import pytest
from sqlalchemy import func, select, update

from app import db, srs, sync


def _uid(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()


def _cards(uid, eng=None):
    with (eng or db.engine).connect() as c:
        return {(r.track, r.item): r for r in c.execute(select(db.srs_cards).where(db.srs_cards.c.user_id == uid))}


def test_seal_roundtrip_and_tamper_detection():
    salt = b"s" * 16
    keys = sync.derive("K7Q4M-2XDHP", salt)
    blob = sync.seal({"hello": "世界", "n": [1, 2, 3]}, keys, b"c2s")
    assert b"hello" not in blob and "世界".encode() not in blob  # encrypted, not just encoded
    assert sync.unseal(blob, keys, b"c2s") == {"hello": "世界", "n": [1, 2, 3]}
    assert sync.unseal(blob, sync.derive("k7q4m 2xdhp", salt), b"c2s")["n"] == [1, 2, 3]  # code typing is forgiving
    with pytest.raises(sync.SyncError):
        sync.unseal(blob, sync.derive("K7Q4M-2XDHQ", salt), b"c2s")  # wrong code
    with pytest.raises(sync.SyncError):
        sync.unseal(blob, keys, b"s2c")  # a reply can't be passed off as a request
    bad = bytearray(blob)
    bad[-1] ^= 1
    with pytest.raises(sync.SyncError):
        sync.unseal(bytes(bad), keys, b"c2s")
    assert len(sync.norm_code(sync.new_code())) == 10


def test_merge_between_two_devices(user, tmp_path):
    """Device A = the normal test database; device B = a second, separate database file."""
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    user.post("/api/words/add", {"count": 4})
    user.post("/api/notes", {"track": "kanji", "item": "学", "meaning": "learning", "mnemonic": "", "notes": "from A"})
    uid = _uid(user)
    # an imported/hand-made card with Anki media in a deck, and a quiz
    with db.tx() as c:
        did = srs.get_or_create_deck(c, uid, "Anki deck")
        cid = c.execute(db.custom_cards.insert().values(user_id=uid, front="犬", back="dog", created_at=1)).inserted_primary_key[0]
        srs.add_card(c, uid, "card", str(cid), deck_id=did)
        c.execute(db.anki_media.insert().values(user_id=uid, deck_id=did, name="dog.png", mime="image/png", data=b"\x89PNG..."))
        c.execute(db.quiz_attempts.insert().values(id="q" * 24, user_id=uid, kind="mixed", title="Quiz", mode="practice",
                                                   questions_json="[]", total=5, score=4, passed=1, started_at=5, finished_at=9))
    engine_b = db.make_engine(tmp_path / "phone.db")
    db.init_db(engine_b)
    with engine_b.begin() as c:
        ub = c.execute(db.users.insert().values(username="phone", email="p@example.com", display_name="P", password_hash="x",
                                               created_at=1)).inserted_primary_key[0]
        srs.add_card(c, ub, "kanji", "日", now=100)
        c.execute(db.lesson_completions.insert().values(user_id=ub, lesson="katakana-1", completed_at=50))
        c.execute(db.xp_events.insert().values(user_id=ub, source="lesson", dedupe_key="lesson:katakana-1", amount=10, day="2026-01-01", created_at=50))
    # A -> B
    with db.tx() as c:
        snap_a = sync.export(c, uid)
    json.dumps(snap_a)  # must be plain JSON
    with engine_b.begin() as c:
        st = sync.merge(c, ub, snap_a)
    assert st["cards_new"] == len(_cards(uid)) and st["media"] == 1 and st["custom"] == 1 and st["quizzes"] == 1
    b_cards = _cards(ub, engine_b)
    assert ("kanji", "日") in b_cards and len(b_cards) == len(_cards(uid)) + 1
    with engine_b.connect() as c:
        custom = c.execute(select(db.custom_cards).where(db.custom_cards.c.user_id == ub)).one()
        assert custom.front == "犬" and ("card", str(custom.id)) in b_cards  # card re-linked to B's own id
        assert c.execute(select(db.anki_media.c.data)).scalar() == b"\x89PNG..."
        assert c.execute(select(db.notes.c.notes).where(db.notes.c.user_id == ub)).scalar() == "from A"
        xp_b = c.execute(select(db.users.c.xp).where(db.users.c.id == ub)).scalar()
    # study a card on B (newer), then B -> A: A takes B's newer copy, and gets B's own things
    with engine_b.begin() as c:
        c.execute(update(db.srs_cards).where(db.srs_cards.c.user_id == ub, db.srs_cards.c.track == "hiragana", db.srs_cards.c.item == "あ")
                  .values(state="review", total_reviews=3, last_review_at=int(time.time()) + 5, interval_days=6))
        snap_b = sync.export(c, ub, sync.manifest(db.engine.connect(), uid))
    assert snap_b["media"] == []  # A already has that file: not sent back
    with db.tx() as c:
        st2 = sync.merge(c, uid, snap_b)
    a = _cards(uid)
    assert a[("hiragana", "あ")].interval_days == 6 and st2["cards_updated"] == 1
    assert ("kanji", "日") in a
    with db.ro() as c:
        assert c.execute(select(db.lesson_completions.c.lesson).where(db.lesson_completions.c.user_id == uid,
                                                                      db.lesson_completions.c.lesson == "katakana-1")).first()
        xp_a = c.execute(select(db.users.c.xp).where(db.users.c.id == uid)).scalar()
        assert c.execute(select(func.count()).select_from(db.custom_cards).where(db.custom_cards.c.user_id == uid)).scalar() == 1
    assert xp_a == xp_b  # same XP events on both now
    # merging again changes nothing
    with db.tx() as c:
        again = sync.merge(c, uid, snap_b)
    assert again["cards_new"] == again["cards_updated"] == again["reviews"] == again["xp"] == 0


def test_host_and_join_over_the_network(user, user2):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    user2.post("/api/lesson/complete", {"lesson": "katakana-2"})
    a, b = _uid(user), _uid(user2)
    sess = sync.start_host(a, bind="127.0.0.1")
    try:
        assert sync.host_status(a)["state"] == "waiting" and sess.port in sync.PORTS
        with pytest.raises(sync.SyncError, match="code"):
            sync.join(b, f"127.0.0.1:{sess.port}", "AAAAA-BBBBB")
        r = sync.join(b, f"127.0.0.1:{sess.port}", sess.code.lower())
        assert r["received"]["lessons"] == 1
        st = sync.host_status(a)
        assert st["state"] == "done" and st["result"]["lessons"] == 1
        with pytest.raises(sync.SyncError):  # one sync per code
            sync.join(b, f"127.0.0.1:{sess.port}", sess.code)
    finally:
        sync.stop_host(a)
    for uid in (a, b):
        with db.ro() as c:
            got = set(c.execute(select(db.lesson_completions.c.lesson).where(db.lesson_completions.c.user_id == uid)).scalars())
        assert {"hiragana-1", "katakana-2"} <= got


def test_too_many_wrong_codes_closes_the_session(user, user2):
    a, b = _uid(user), _uid(user2)
    sess = sync.start_host(a, bind="127.0.0.1")
    try:
        for _ in range(sync.MAX_BAD):
            with pytest.raises(sync.SyncError):
                sync.join(b, f"127.0.0.1:{sess.port}", "ZZZZZ-ZZZZZ")
        assert sync.host_status(a)["state"] == "closed"
        with pytest.raises(sync.SyncError):
            sync.join(b, f"127.0.0.1:{sess.port}", sess.code)  # even the right code no longer works
    finally:
        sync.stop_host(a)


def test_sync_api_and_page(user):
    assert user.c.get("/sync").status_code == 200
    r = user.post("/api/sync/join", {"address": "not an address!", "code": "AAAAA-BBBBB"})
    assert r.status_code == 400
    assert user.post("/api/sync/join", {"address": "127.0.0.1:8770", "code": "short"}).status_code == 400
