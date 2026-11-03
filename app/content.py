"""Read-only learning content, cached in memory after first use.

Content tables are small (2,136 kanji, 188 kana words) so keeping a compact
copy in memory makes quizzes and lookups instant. Related vocabulary and
sentences are loaded from SQLite only when a page asks for them.
"""
from __future__ import annotations

import json
import threading
from functools import lru_cache

from sqlalchemy import select

from . import db
from .kana import KANA_INDEX, SCRIPTS

_lock = threading.Lock()
_cache: dict = {}

GRADE_LABELS = {1: "Grade 1", 2: "Grade 2", 3: "Grade 3", 4: "Grade 4", 5: "Grade 5", 6: "Grade 6", 8: "Secondary school"}
TRACKS = {
    "hiragana": "Hiragana", "katakana": "Katakana", "hvocab": "Hiragana words",
    "kvocab": "Katakana words", "kanji": "Kanji",
}


def _load():
    with _lock:
        if _cache:
            return _cache
        with db.ro() as c:
            kanji_rows = [dict(r._mapping) for r in c.execute(select(
                db.kanji.c.idx, db.kanji.c.char, db.kanji.c.codepoint, db.kanji.c.grade, db.kanji.c.strokes,
                db.kanji.c.freq, db.kanji.c.jlpt_old, db.kanji.c.meanings, db.kanji.c.onyomi, db.kanji.c.kunyomi,
                db.kanji.c.radical_num, db.kanji.c.radical_char, db.kanji.c.radical_name,
            ).order_by(db.kanji.c.idx))]
            vocab = [dict(r._mapping) for r in c.execute(select(db.kana_vocab).order_by(db.kana_vocab.c.id))]
            meta = {r.key: r.value for r in c.execute(select(db.content_meta))}
            # One quiz-friendly vocab word per kanji (shortest common word, first listed).
            kv = {}
            for r in c.execute(select(db.kanji_vocab.c.kanji, db.kanji_vocab.c.word, db.kanji_vocab.c.reading, db.kanji_vocab.c.meaning).order_by(db.kanji_vocab.c.id)):
                kv.setdefault(r.kanji, []).append(dict(r._mapping))
            sents = {}
            for r in c.execute(select(db.kanji_sentences.c.kanji, db.kanji_sentences.c.word, db.kanji_sentences.c.jp, db.kanji_sentences.c.en).order_by(db.kanji_sentences.c.id)):
                sents.setdefault(r.kanji, []).append(dict(r._mapping))
        _cache["kanji"] = kanji_rows
        _cache["kanji_by_char"] = {k["char"]: k for k in kanji_rows}
        _cache["vocab"] = vocab
        _cache["vocab_by_key"] = {("hvocab" if v["script"] == "hiragana" else "kvocab", v["word"]): v for v in vocab}
        _cache["meta"] = meta
        _cache["kanji_vocab"] = kv
        _cache["kanji_sents"] = sents
        return _cache


def reset_cache():
    with _lock:
        _cache.clear()


def kanji_list():
    return _load()["kanji"]


def kanji_get(ch: str):
    return _load()["kanji_by_char"].get(ch)


def kanji_vocab(ch: str):
    return _load()["kanji_vocab"].get(ch, [])


def kanji_sentences(ch: str):
    return _load()["kanji_sents"].get(ch, [])


def vocab_list(script: str | None = None):
    v = _load()["vocab"]
    return [x for x in v if script is None or x["script"] == script]


def vocab_get(track: str, word: str):
    return _load()["vocab_by_key"].get((track, word))


def meta():
    return _load()["meta"]


def stroke_discrepancies():
    return json.loads(meta().get("stroke_discrepancies", "[]"))


def first_meaning(k) -> str:
    return k["meanings"].split("; ")[0]


def primary_reading(k) -> str:
    """The most useful single reading for quizzes: first on'yomi, else first kun'yomi."""
    for field in ("onyomi", "kunyomi"):
        if k[field]:
            return k[field].split("、")[0].replace("-", "")
    return ""


def kana_char(track: str, kana: str):
    return KANA_INDEX.get((track, kana))


def valid_item(track: str, item: str) -> bool:
    if track in ("hiragana", "katakana"):
        return (track, item) in KANA_INDEX
    if track in ("hvocab", "kvocab"):
        return vocab_get(track, item) is not None
    if track == "kanji":
        return kanji_get(item) is not None
    return False


@lru_cache(maxsize=4096)
def stroke_file(ch: str) -> str:
    """KanjiVG file name: first code point, 5 lowercase hex digits."""
    return f"{ord(ch[0]):05x}.svg"


def card_view(track: str, item: str) -> dict:
    """Everything the flashcard / quiz UI needs to show one item."""
    if track in ("hiragana", "katakana"):
        c = KANA_INDEX[(track, item)]
        return {"track": track, "item": item, "front": item, "front_kind": "jp", "answer": c["romaji"], "reading": c["romaji"],
                "meaning": "", "extra": SCRIPTS[track]["label"], "hook": c["hook"],
                "stroke": stroke_file(item) if len(item) == 1 else None}
    if track in ("hvocab", "kvocab"):
        v = vocab_get(track, item)
        return {"track": track, "item": item, "front": item, "front_kind": "jp", "answer": v["meaning"], "reading": v["romaji"],
                "meaning": v["meaning"], "extra": (f"Kanji: {v['kanji_form']}" if v["kanji_form"] else v["category"].title()),
                "stroke": None}
    k = kanji_get(item)
    return {"track": "kanji", "item": item, "front": item, "front_kind": "jp", "answer": k["meanings"],
            "reading": " · ".join(x for x in (k["onyomi"], k["kunyomi"]) if x), "meaning": k["meanings"],
            "extra": GRADE_LABELS[k["grade"]], "stroke": stroke_file(item)}
