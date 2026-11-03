"""Built-in JMdict search, romaji input, imported dictionaries (Yomitan zip, CSV/TSV)."""
import io
import json
import zipfile

import pytest

from app import db, dictionary
from app.kana import romaji_to_hiragana


def heads(user, q, n=3):
    return [e["headword"] for e in user.c.get("/api/dictionary/search", params={"q": q}).json()["results"][:n]]


@pytest.mark.parametrize("q,expect", [
    ("猫", "猫"), ("ねこ", "猫"), ("neko", "猫"), ("cat", "猫"), ("dog", "犬"), ("book", "本"), ("tree", "木"),
    ("eat", "食べる"), ("taberu", "食べる"), ("go", "行く"), ("school", "学校"), ("konnichiha", "こんにちは"), ("コーヒー", "コーヒー"),
])
def test_search_finds_the_everyday_word_first(user, q, expect):
    assert heads(user, q, 1) == [expect]


def test_search_details_and_counts(user):
    r = user.c.get("/api/dictionary/search", params={"q": "学校"}).json()
    e = r["results"][0]
    assert e["reading"] == "がっこう" and e["romaji"] == "gakkou" and e["common"]
    assert {k["char"] for k in e["kanji"]} == {"学", "校"}
    assert "小学校" in heads(user, "学校", 30)  # substring matches too
    assert user.c.get("/api/dictionary/search", params={"q": ""}).json()["results"] == []
    assert user.c.get("/api/dictionary/search", params={"q": "qqqzzzx"}).json()["results"] == []
    assert user.c.get("/dictionary", params={"q": "猫"}).status_code == 200


def test_romaji_conversion():
    assert romaji_to_hiragana("gakkou") == "がっこう" and romaji_to_hiragana("konnichiha") == "こんにちは"
    assert romaji_to_hiragana("shinbun") == "しんぶん" and romaji_to_hiragana("kon'ya") == "こんや"
    assert romaji_to_hiragana("cat") is None and romaji_to_hiragana("日本") is None


def test_add_word_to_deck(user):
    eid = user.c.get("/api/dictionary/search", params={"q": "犬"}).json()["results"][0]["id"]
    r = user.post(f"/api/dictionary/{eid}/add").json()
    assert r["added"] and r["deck"] == "My words"
    assert user.post(f"/api/dictionary/{eid}/add").json()["added"] is False
    card = user.c.get("/api/review/queue").json()["cards"][0]
    assert card["front"] == "犬" and card["reading"] == "いぬ" and card["label"] == "Word"
    assert user.post("/api/dictionary/1/add").status_code == 404


def yomitan_zip(entries, title="Test Yomi"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.json", json.dumps({"title": title, "format": 3, "revision": "1"}))
        z.writestr("term_bank_1.json", json.dumps(entries, ensure_ascii=False))
    return buf.getvalue()


def upload(user, name, data):
    return user.c.post("/api/dictionaries/import", files={"file": (name, data)}, headers={"X-CSRF-Token": user._tok})


def test_import_yomitan_and_search(user, user2):
    structured = {"type": "structured-content", "content": [{"tag": "ul", "content": [
        {"tag": "li", "content": "a sweet bean paste"}, {"tag": "li", "content": ["used in ", {"tag": "b", "content": "wagashi"}]}]},
        {"tag": "img", "path": "x.png"}]}
    data = yomitan_zip([["餡子", "あんこ", "n", "", 5, [structured], 1, ""],
                        ["ねこ", "ねこ", "", "", 1, ["(my dict) kitty"], 2, ""],
                        ["古い", "ふるい", "adj-i", "adj-i", 3, ["old (my dict)"], 3, ""]])
    r = upload(user, "test.zip", data).json()
    assert r["ok"] and r["entries"] == 3 and r["title"] == "Test Yomi"
    mine = user.c.get("/api/dictionary/search", params={"q": "あんこ"}).json()["mine"]
    assert mine[0]["term"] == "餡子" and "sweet bean paste" in mine[0]["meaning"] and "wagashi" in mine[0]["meaning"]
    assert user.c.get("/api/dictionary/search", params={"q": "neko"}).json()["mine"][0]["meaning"] == "(my dict) kitty"
    assert user.c.get("/api/dictionary/search", params={"q": "bean paste"}).json()["mine"][0]["term"] == "餡子"
    # private to its owner
    assert user2.c.get("/api/dictionary/search", params={"q": "あんこ"}).json()["mine"] == []
    with db.ro() as c:
        did = c.execute(db.user_dicts.select()).first().id
    assert user2.post(f"/api/dictionaries/{did}/delete").status_code == 404
    user.post(f"/api/dictionaries/{did}/disable")
    assert user.c.get("/api/dictionary/search", params={"q": "あんこ"}).json()["mine"] == []
    user.post(f"/api/dictionaries/{did}/enable")
    assert user.post(f"/api/dictionaries/{did}/delete").json()["ok"]
    assert user.c.get("/api/dictionary/search", params={"q": "あんこ"}).json()["mine"] == []


def test_import_csv_tsv_and_errors(user):
    csv_data = "word,reading,meaning\n猫,ねこ,my cat note\n水,みず,my water note\n".encode()
    r = upload(user, "Vocab list.csv", csv_data).json()
    assert r["entries"] == 2 and r["title"] == "Vocab list"
    assert user.c.get("/api/dictionary/search", params={"q": "みず"}).json()["mine"][0]["meaning"] == "my water note"
    tsv = "花\tflower\n山\tmountain\n".encode()
    assert upload(user, "two.tsv", tsv).json()["entries"] == 2
    assert "No entries" in upload(user, "empty.csv", b"\n\n").json()["error"]
    assert "index.json" in upload(user, "bad.zip", yomitan_zip([]).replace(b"index.json", b"indexxjson")).json()["error"]


def test_flatten_structured_content():
    node = {"tag": "div", "content": [{"tag": "span", "content": "a"}, {"tag": "ruby", "content": ["漢", {"tag": "rt", "content": "かん"}]}]}
    assert dictionary._flatten(node).strip() == "a漢"


@pytest.mark.parametrize("q,expect", [("cat", "猫"), ("dog", "犬"), ("eat", "食べる"), ("water", "水"), ("to run", "走る")])
def test_english_search_without_fts5(user, monkeypatch, q, expect):
    """Some SQLite builds (Android) have no FTS5: English search must still work (plain substring search)."""
    monkeypatch.setattr(db, "HAS_FTS", False)
    assert expect in heads(user, q, 5)
