import json
import unicodedata
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select

from app import content, db
from app.kana import HIRAGANA, HIRAGANA_LESSONS, KATAKANA, KATAKANA_LESSONS, romanize

ROOT = Path(__file__).resolve().parent.parent


def test_hiragana_curriculum():
    assert len(HIRAGANA) == 104 and len({c["kana"] for c in HIRAGANA}) == 104
    assert Counter(c["group"] for c in HIRAGANA) == {"basic": 46, "voiced": 25, "combo": 33}
    assert len(HIRAGANA_LESSONS) == 26
    assert all(3 <= len(l["chars"]) <= 7 for l in HIRAGANA_LESSONS)
    by = {c["kana"]: c["romaji"] for c in HIRAGANA}
    assert (by["し"], by["ち"], by["つ"], by["ふ"], by["を"], by["ん"], by["じゃ"], by["ぴょ"]) == ("shi", "chi", "tsu", "fu", "wo", "n", "ja", "pyo")


def test_katakana_curriculum():
    assert len(KATAKANA) == 134 and len({c["kana"] for c in KATAKANA}) == 134
    assert Counter(c["group"] for c in KATAKANA) == {"basic": 46, "voiced": 25, "combo": 33, "special": 30}
    ks = {c["kana"] for c in KATAKANA}
    for must in ("ッ", "ー", "ファ", "ティ", "ディ", "ウィ", "ヴ"):
        assert must in ks
    assert len(KATAKANA_LESSONS) == 32


def test_romanize():
    assert romanize("がっこう") == "gakkou" and romanize("マッチ") == "matchi" and romanize("きょう") == "kyou"
    assert romanize("コーヒー") == "koohii" and romanize("ファイル") == "fairu"


def test_joyo_kanji_dataset():
    with db.ro() as c:
        n = c.execute(select(func.count()).select_from(db.kanji)).scalar()
        chars = list(c.execute(select(db.kanji.c.char)).scalars())
        grades = dict(c.execute(select(db.kanji.c.grade, func.count()).group_by(db.kanji.c.grade)).all())
        idxs = list(c.execute(select(db.kanji.c.idx).order_by(db.kanji.c.idx)).scalars())
        rows = c.execute(select(db.kanji)).all()
    assert n == 2136 and len(set(chars)) == 2136
    assert grades == {1: 80, 2: 160, 3: 200, 4: 202, 5: 193, 6: 191, 8: 1110}
    assert idxs == list(range(1, 2137))
    for r in rows:
        assert r.codepoint == f"U+{ord(r.char):04X}"
        assert unicodedata.category(r.char) == "Lo"
        assert r.meanings and r.strokes > 0
        assert r.onyomi or r.kunyomi
        assert r.radical_num and 1 <= r.radical_num <= 214 and r.radical_char
    # Kanji added to grade 4 in the 2020 revision (prefecture names)
    for ch in "茨媛岡潟岐熊香佐埼崎滋鹿縄井沖栃奈梨阪阜":
        assert content.kanji_get(ch)["grade"] == 4, ch


def test_stroke_svgs_present():
    with db.ro() as c:
        chars = list(c.execute(select(db.kanji.c.char)).scalars())
    missing = [ch for ch in chars if not (ROOT / "data" / "strokes" / content.stroke_file(ch)).exists()]
    assert missing == []
    for k in HIRAGANA + KATAKANA:
        if len(k["kana"]) == 1:
            assert (ROOT / "data" / "strokes" / content.stroke_file(k["kana"])).exists(), k["kana"]


def test_vocab_and_sentence_references():
    with db.ro() as c:
        joyo = set(c.execute(select(db.kanji.c.char)).scalars())
        bad_v = c.execute(select(func.count()).select_from(db.kanji_vocab).where(db.kanji_vocab.c.kanji.not_in(joyo))).scalar()
        bad_w = c.execute(select(db.kanji_vocab.c.kanji, db.kanji_vocab.c.word)).all()
        sents = c.execute(select(db.kanji_sentences)).all()
        kana = c.execute(select(db.kana_vocab)).all()
        meta = {r.key: r.value for r in c.execute(select(db.content_meta))}
    assert bad_v == 0
    assert all(k in w for k, w in bad_w)
    assert all(s.kanji in joyo and s.jp and s.en and s.tatoeba_id for s in sents)
    assert len(kana) == 188
    cats = {k.category for k in kana}
    for c_ in ("food", "animals", "daily life", "nature", "people", "time", "transport", "technology", "countries", "travel", "hobbies", "clothing"):
        assert c_ in cats
    assert all(k.meaning and k.jmdict_id for k in kana)
    report = json.loads((ROOT / "data" / "content_report.json").read_text(encoding="utf-8"))
    assert int(meta["kanji_vocab_count"]) == len(bad_w) == int(report["kanji_vocab_count"])
    assert int(meta["kanji_sentence_count"]) == len(sents)


def test_every_kana_has_a_memory_hook():
    from app.mnemonics import HIRAGANA as H, KATAKANA as K
    assert len(H) == 46 and len(K) == 46
    for c in HIRAGANA + KATAKANA:
        assert c["hook"], c["kana"]
    by = {c["kana"]: c["hook"] for c in HIRAGANA + KATAKANA}
    assert by["が"].startswith("か + ゛") and "PA" in by["ぱ"] and "KYA" in by["きゃ"] and "doubles" in by["ッ"]
    assert "JI" in by["ぢ"] and "ZU" not in by["ぢ"]
