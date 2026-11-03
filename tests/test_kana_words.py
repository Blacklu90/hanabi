"""Kana through words: each lesson unlocks real words that only use kana you know."""
from sqlalchemy import update

from app import db, kana_words as K
from app.kana import SCRIPTS


def test_words_only_use_kana_from_their_lesson_or_earlier():
    for script in ("hiragana", "katakana"):
        ul = K._unit_lessons(script)
        ws = K.course(script)["words"]
        assert len(ws) > 3000
        for w in ws[:2000]:
            us = K.units(w["word"], ul)
            assert us and max(ul[u] for u in us) == w["lesson"]
        first = [w for w in ws if w.get("first")]
        assert [w["lesson"] for w in first] == sorted(w["lesson"] for w in first)  # lesson order
    # lesson 2 of hiragana is the K row: its words use only vowels + k sounds
    allowed = set("あいうえおかきくけこ")
    assert all(set(w["word"]) <= allowed for w in K.for_lesson("hiragana", 2))


def test_breakdown_and_answers():
    b = K.breakdown("がっこう", "hiragana")
    assert [r["kana"] for r in b["rows"]] == ["が", "っ", "こ", "う"] and b["romaji"] == "gakkou"
    assert b["rows"][0]["note"] == "か + ゛" and "kk" in b["rows"][1]["note"]
    assert set(b["notes"]) == {"dakuten", "small-tsu", "long-vowel"}
    assert [r["kana"] for r in K.breakdown("きょう", "hiragana")["rows"]] == ["きょ", "う"]
    assert K.breakdown("コーヒー", "katakana")["notes"] == ["long"]
    for a in ("gakkou", "gakkō", "がっこう", "ガッコウ", " Gakkou "):
        assert K.answer_ok(a, "がっこう"), a
    for a in ("gako", "gakou", ""):
        assert not K.answer_ok(a, "がっこう"), a
    for a in ("koohii", "kōhī", "ko-hi-", "コーヒー"):
        assert K.answer_ok(a, "コーヒー"), a


def test_add_only_readable_words(user):
    r = user.post("/api/kana/hiragana/words/add", {"count": 10})
    assert r.status_code == 400  # no lessons yet: nothing you can read
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    user.post("/api/lesson/complete", {"lesson": "hiragana-2"})
    r = user.post("/api/kana/hiragana/words/add", {"count": 10}).json()
    assert r["added"] >= 5 and r["deck"] == "Hiragana words"
    with db.ro() as c:
        from sqlalchemy import select
        items = [int(x) for x in c.execute(select(db.srs_cards.c.item).where(db.srs_cards.c.track == "hword")).scalars()]
    allowed = set("あいうえおかきくけこ")
    assert all(set(K.get("hiragana", i)["word"]) <= allowed for i in items)
    page = user.c.get(f"/review?deck={r['deck_id']}").text
    assert '"kana_rows"' in page


def test_read_it_checks_on_the_server(user):
    assert user.c.get("/api/kana/katakana/read/next").json()["word"] is None
    for n in range(1, 4):
        user.post("/api/lesson/complete", {"lesson": f"katakana-{n}"})
    g = user.c.get("/api/kana/katakana/read/next").json()
    w = K.get("katakana", g["id"])
    assert set(w["word"]) <= set(k for les in SCRIPTS["katakana"]["lessons"][:3] for k in les["chars"])
    bad = user.post("/api/kana/katakana/read/answer", {"id": g["id"], "answer": "zzz"}).json()
    assert not bad["correct"] and bad["xp"] == 0 and bad["romaji"]
    good = user.post("/api/kana/katakana/read/answer", {"id": g["id"], "answer": bad["romaji"]}).json()
    assert good["correct"] and good["xp"] == 1
    again = user.post("/api/kana/katakana/read/answer", {"id": g["id"], "answer": w["word"]}).json()
    assert again["correct"] and again["xp"] == 0
    assert user.post("/api/kana/nope/read/answer", {"id": 1, "answer": "a"}).status_code == 404


def test_kana_pages(user):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    for url in ("/learn/hiragana", "/learn/hiragana/words", "/learn/hiragana/read", "/learn/hiragana/guide",
                "/learn/katakana/words", "/learn/katakana/read", "/learn/katakana/guide", "/learn/hiragana/2"):
        assert user.c.get(url).status_code == 200, url
    assert "You can now read these words" in user.c.get("/learn/hiragana/2").text
    assert user.c.get("/learn/klingon/words").status_code == 404
