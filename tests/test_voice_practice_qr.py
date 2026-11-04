"""Pronunciation (deck recordings, built-in voice, device fallback), practice mode, and QR-code sync."""
import json
import re
import sys
from pathlib import Path

from sqlalchemy import select

from app import db, sync, voice

FIX = Path(__file__).parent / "fixtures"


def upload(user, name):
    r = user.c.post("/api/import/apkg", files={"file": (name, (FIX / name).read_bytes())}, headers={"X-CSRF-Token": user._tok})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- pronunciation
def test_pins_match_requirements_file():
    lines = [l.split("#")[0].strip() for l in (Path(__file__).parent.parent / "requirements-voice.txt").read_text().splitlines()]
    pins = [tuple(l.split("==")) for l in lines if l]
    assert pins == [(n, v) for n, v in voice.PINNED]


def test_wheel_choice_for_this_computer(monkeypatch):
    tag = f"cp{sys.version_info[0]}{sys.version_info[1]}"
    monkeypatch.setattr(sys, "platform", "linux")
    import platform
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    files = [{"filename": f"x-1-{tag}-{tag}-win_amd64.whl"}, {"filename": f"x-1-{tag}-{tag}-manylinux_2_28_aarch64.whl"},
             {"filename": f"x-1-{tag}-{tag}-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl"}, {"filename": "x-1.tar.gz"}]
    assert voice.pick_wheel(files)["filename"].endswith("manylinux_2_28_x86_64.whl")
    assert voice.pick_wheel([{"filename": "y-1-py3-none-any.whl"}])["filename"] == "y-1-py3-none-any.whl"
    assert voice.pick_wheel([{"filename": "z-1-cp310-abi3-manylinux_2_28_x86_64.whl"}])  # stable ABI works on newer Pythons
    assert voice.pick_wheel([{"filename": "w-1-cp39-cp39-manylinux_2_28_x86_64.whl"}]) is None


def test_deck_recording_is_used_for_the_word(user):
    j = upload(user, "anki-two-sounds.apkg")  # a Kaishi-style note: 私 with a word and a sentence recording
    r = user.c.get("/api/say", params={"text": "私"}).json()
    assert r["source"] == "deck" and r["url"] == f"/anki-media/{j['deck_id']}/watashi_word.wav"  # the word, not the sentence
    assert user.c.get("/api/say", params={"text": "わたし"}).json()["url"].endswith("watashi_word.wav")  # by reading too
    assert user.c.get(r["url"]).status_code == 200


def test_other_words_use_the_builtin_or_device_voice(user):
    r = user.c.get("/api/say", params={"text": "学校", "reading": "がっこう"}).json()
    if voice.available():
        assert r["source"] == "builtin"
        wav = user.c.get(r["url"])
        assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    else:
        assert r["source"] == "device" and r["text"] == "がっこう"  # the reading, so the phone says the right word
    assert user.c.get("/api/say", params={"text": ""}).status_code == 400
    assert user.c.get("/api/voice").json()["ok"]


def test_recordings_are_private(user, user2):
    upload(user, "anki-two-sounds.apkg")
    assert user2.c.get("/api/say", params={"text": "私"}).json()["source"] != "deck"


def test_builtin_voice_speaks_when_installed():
    if not voice.available():
        return  # installed on the Windows CI runner (bundled there); optional elsewhere
    data = voice.synth("がっこう")
    assert data[:4] == b"RIFF" and len(data) > 10000
    assert voice.synth("がっこう") == data  # cached


# ------------------------------------------------------------------- practice
def _deck_with_words(user, n=12):
    r = user.post("/api/words/add", {"count": n}).json()
    return r["deck_id"]


def _state(uid_cards):
    with db.ro() as c:
        return [tuple(r) for r in c.execute(select(db.srs_cards.c.id, db.srs_cards.c.state, db.srs_cards.c.due_at,
                                                   db.srs_cards.c.total_reviews).order_by(db.srs_cards.c.id))]


def _cards_in(page: str) -> list:
    return json.loads(re.search(r'<script type="application/json" id="review-data">(.*?)</script>', page, re.S).group(1))


def test_practice_picks_sizes_and_never_changes_the_schedule(user):
    deck = _deck_with_words(user)
    before = _state(None)
    page = user.c.get("/practice", params={"deck": deck, "n": 5, "pick": "new"}).text
    cards = _cards_in(page)
    assert len(cards) == 5 and 'data-practice="1"' in page and "Got it" in page and "Repeat these 5" in page
    assert len(_cards_in(user.c.get("/practice", params={"deck": deck, "n": 1, "pick": "new"}).text)) == 1
    assert len(_cards_in(user.c.get("/practice", params={"deck": deck, "n": 99, "pick": "new"}).text)) == 12  # capped at 20, deck has 12
    nxt = _cards_in(user.c.get("/practice", params={"deck": deck, "n": 5, "pick": "new", "start": 5}).text)
    assert {c["id"] for c in nxt}.isdisjoint({c["id"] for c in cards})  # "Next 5" is a different set
    # nothing studied today yet: "today" falls back to the next new words
    today = user.c.get("/practice", params={"deck": deck, "n": 5}).text
    assert "here are your next new words" in today and len(_cards_in(today)) == 5
    rnd = _cards_in(user.c.get("/practice", params={"deck": deck, "n": 4, "pick": "random"}).text)
    assert len(rnd) == 4
    assert all(c.get("say") for c in cards)  # every word has a ▶
    assert _state(None) == before  # practising changed nothing


def test_practice_xp_once_a_day(user):
    a = user.post("/api/practice/done", {"n": 5}).json()
    b = user.post("/api/practice/done", {"n": 5}).json()
    assert a["xp"] == 3 and b["xp"] == 0
    assert user.post("/api/practice/done", {"n": 50}).status_code == 422


def test_practice_after_studying_today_shows_todays_words(user):
    deck = _deck_with_words(user, 6)
    q = user.c.get("/api/review/queue", params={"deck": deck}).json()["cards"]
    for c in q[:2]:
        user.post("/api/review/submit", {"card_id": c["id"], "rating": 3})
    got = _cards_in(user.c.get("/practice", params={"deck": deck, "n": 5}).text)
    assert sorted(c["id"] for c in got) == sorted(c["id"] for c in q[:2])


# -------------------------------------------------------------------- QR sync
def _uid(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()


def test_qr_code_and_multi_address_join(user, user2):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    a, b = _uid(user), _uid(user2)
    assert user.c.get("/api/sync/qr.svg").status_code == 404  # nothing to show yet
    sess = sync.start_host(a, bind="127.0.0.1")
    try:
        svg = user.c.get("/api/sync/qr.svg")
        assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg") and b"<svg" in svg.content
        link = sync.qr_link(sess)
        assert link.startswith("shuinkan://sync?a=") and f"c={sync.norm_code(sess.code)}" in link
        # a QR code lists every address the computer has; unreachable ones are skipped
        r = sync.join(b, f"127.0.0.1:1,127.0.0.1:{sess.port}", sess.code)
        assert r["received"]["lessons"] == 1
    finally:
        sync.stop_host(a)
