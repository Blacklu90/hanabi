"""Kanji through words: reading analysis, the course order, adding words, guess-the-reading, pages."""
from sqlalchemy import select, update

from app import db, readings, words


def parts(word, reading):
    return [(p["text"], p["reading"], p["kind"]) for p in readings.analyse(word, reading)["parts"]]


def test_reading_split_uses_dictionary_readings():
    assert parts("学生", "がくせい") == [("学", "がく", "on"), ("生", "せい", "on")]
    assert parts("学ぶ", "まなぶ") == [("学", "まな", "kun"), ("ぶ", "ぶ", "kana")]
    # small っ and voicing are recognised, and say where they came from
    a = readings.analyse("学校", "がっこう")["parts"][0]
    assert (a["reading"], a["base"], a["change"]) == ("がっ", "ガク", "small っ")
    b = readings.analyse("手紙", "てがみ")["parts"][1]
    assert (b["reading"], b["kind"], b["change"]) == ("がみ", "kun", "voiced")
    assert parts("人々", "ひとびと")[1] == ("々", "びと", "kun")
    # whole-word readings aren't forced into pieces
    assert readings.analyse("今日", "きょう")["special"] and readings.analyse("大人", "おとな")["special"]


def test_reading_hints():
    assert readings.hint("学生", "がくせい")["followed"] is True
    assert readings.hint("学ぶ", "まなぶ")["rule"] == "okurigana" and readings.hint("学ぶ", "まなぶ")["followed"]
    assert readings.hint("手紙", "てがみ")["followed"] is False
    assert readings.hint("今日", "きょう")["rule"] == "special"


def test_course_order_introduces_kanji_gradually():
    c = words.course()
    assert len(c) > 15000 and [w["n"] for w in c[:3]] == [1, 2, 3]
    assert c[0]["word"] == "日"  # the most frequent kanji comes first
    first = [w for w in c if w.get("first")]
    assert len(first) > 3000 and c[:len(first)] == first  # the guided first pass comes first
    met = set()
    for w in first:
        new = [ch for ch in w["kanji"] if ch not in met]
        assert len(new) <= 1, w  # never more than one new kanji per word in the guided pass
        met.update(w["kanji"])
    assert not any(ch.isascii() for w in c for ch in w["word"])


def test_add_words_in_order_and_review_shows_breakdown(user):
    r = user.post("/api/words/add", {"count": 5}).json()
    assert r["ok"] and r["added"] == 5 and r["deck"] == words.DECK_NAME
    again = user.post("/api/words/add", {"count": 5}).json()
    assert again["added"] == 5  # the next five, not the same ones
    with db.ro() as c:
        ids = sorted(int(x) for x in c.execute(select(db.srs_cards.c.item).where(db.srs_cards.c.track == "dict")).scalars())
    assert set(ids) >= {w["id"] for w in words.course()[:10]}
    page = user.c.get(f"/review?deck={r['deck_id']}").text
    assert '"parts"' in page and '"kanji"' in page and "on'yomi" in page or "kun'yomi" in page
    # adding a chosen word twice is refused politely
    w = words.course()[0]
    assert user.post("/api/words/add", {"ids": [w["id"]]}).status_code == 400


def test_guess_needs_known_kanji_and_scores_on_the_server(user):
    assert user.c.get("/api/guess/next").json()["word"] is None  # nothing met yet
    user.post("/api/words/add", {"count": 60})
    with db.tx() as c:  # pretend these were reviewed and passed
        c.execute(update(db.srs_cards).where(db.srs_cards.c.track == "dict").values(state="review", total_reviews=1))
    g = user.c.get("/api/guess/next").json()
    assert g["word"] and g["clues"]
    w = words.get(g["id"])
    with db.ro() as c:
        have = words.user_word_ids(c, 0)
    assert g["id"] not in have
    assert all(cl["word"] for cl in g["clues"])  # every kanji was met in one of your words
    wrong = user.post("/api/guess/answer", {"id": g["id"], "answer": "zzz"}).json()
    assert wrong["correct"] is False and wrong["xp"] == 0 and wrong["reading"] == w["reading"]
    from app.kana import to_katakana
    right = user.post("/api/guess/answer", {"id": g["id"], "answer": to_katakana(w["reading"])}).json()
    assert right["correct"] is True and right["xp"] == 2 and right["parts"]
    twice = user.post("/api/guess/answer", {"id": g["id"], "answer": w["reading"]}).json()
    assert twice["correct"] and twice["xp"] == 0  # XP only once per word
    assert user.post("/api/guess/answer", {"id": 1, "answer": "a"}).status_code == 404


def test_romaji_answers(user):
    w = next(x for x in words.course() if x["reading"] == "がっこう")
    r = user.post("/api/guess/answer", {"id": w["id"], "answer": "gakkou"}).json()
    assert r["correct"]


def test_pages_render(user):
    for url in ("/words", "/guess", "/kanji/grid", "/kanji/grid?by=freq", "/kanji/readings", "/kanji/学", "/kanji"):
        r = user.c.get(url)
        assert r.status_code == 200, url
    assert "Kanji through words" in user.c.get("/words").text
    guide = user.c.get("/kanji/readings").text
    assert "<ruby>" in guide and "%" in guide
    detail = user.c.get("/kanji/学").text
    assert "Learn 学 in words" in detail and "data-add-word" in detail
    user.post("/api/words/add", {"count": 3})
    grid = user.c.get("/kanji/grid").text
    assert 'kg-cell learning' in grid
