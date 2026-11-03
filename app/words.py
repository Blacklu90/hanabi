"""Kanji through words: learn common words, and the kanji come with them.

The course is every common JMdict word written only with Jōyō kanji (plus kana), ordered
so that words made of the most frequent kanji come first. Each word is shown with the
reading each of its kanji uses (see readings.py), so readings are learned in context
instead of as long lists.
"""
from __future__ import annotations

import json
import random
import re
import threading

from sqlalchemy import select

from . import content, db, readings

DECK_NAME = "Kanji words"
_ODD = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ・＝〜～ー]")  # numbers, Latin letters, long-vowel marks: not kanji practice
_lock = threading.Lock()
_course: list[dict] | None = None
_by_id: dict[int, dict] = {}


def _rank(ch: str) -> int:
    k = content.kanji_get(ch)
    return k["freq"] if k and k["freq"] else 2500 + (k["idx"] if k else 3000)


def _gloss(senses_json: str, n: int = 3) -> str:
    senses = json.loads(senses_json)
    return "; ".join(senses[0]["g"][:n]) if senses else ""


def course() -> list[dict]:
    global _course
    with _lock:
        if _course is not None:
            return _course
        out = []
        with db.ro() as c:
            de = db.dict_entries.c
            rows = c.execute(select(de.id, de.headword, de.reading, de.senses_json, de.sentence_jp, de.sentence_en)
                             .where(de.common == 1)).all()
        seen = set()
        for r in rows:
            w = r.headword
            ks = [ch for ch in w if readings.is_kanji(ch)]
            if not ks or len(w) > 6 or _ODD.search(w) or w in seen:
                continue
            if not all(ch == "々" or content.kanji_get(ch) for ch in ks):
                continue
            seen.add(w)
            kanji = list(dict.fromkeys(ch for ch in ks if ch != "々"))
            if not kanji:
                continue
            senses = json.loads(r.senses_json)
            pos = set(senses[0]["p"]) if senses else set()
            out.append({"id": r.id, "word": w, "reading": r.reading, "meaning": "; ".join(senses[0]["g"][:3]) if senses else "",
                        "kanji": kanji, "rank": max(_rank(ch) for ch in kanji), "jp": r.sentence_jp, "en": r.sentence_en,
                        "q": (bool(pos & _MINOR_POS) or not pos & _MAIN_POS, not readings.is_kanji(w[0]), r.sentence_jp is None,
                              abs(len(w) - 2), r.id)})
        out = _order(out)
        for i, x in enumerate(out, 1):
            x["n"] = i
            del x["q"]
        _course = out
        _by_id.update({x["id"]: x for x in out})
        return _course


_MAIN_POS = {"noun", "noun or participle which takes the aux. verb suru", "adjective", "adjectival nouns or quasi-adjectives",
             "adverb", "Ichidan verb", "intransitive verb", "transitive verb", "pronoun"} | {
             p for p in ("Godan verb with 'ru' ending", "Godan verb with 'ku' ending", "Godan verb with 'u' ending",
                         "Godan verb with 'su' ending", "Godan verb with 'tsu' ending", "Godan verb with 'mu' ending",
                         "Godan verb with 'bu' ending", "Godan verb with 'gu' ending", "Godan verb with 'nu' ending")}
_MINOR_POS = {"prefix", "suffix", "counter", "particle", "auxiliary", "auxiliary verb", "auxiliary adjective", "copula"}
PER_KANJI = 3


def _order(ws: list[dict]) -> list[dict]:
    """Kanji by frequency; each new kanji arrives with its best few words that use only kanji met so far.
    Everything else follows, still most-frequent-kanji first."""
    by_kanji: dict[str, list[dict]] = {}
    for w in ws:
        for ch in w["kanji"]:
            by_kanji.setdefault(ch, []).append(w)
    for lst in by_kanji.values():
        lst.sort(key=lambda w: w["q"])
    met: set[str] = set()
    chosen: list[dict] = []
    taken: set[int] = set()
    for k in sorted(by_kanji, key=_rank):
        n = 0
        for w in by_kanji[k]:
            if n >= PER_KANJI:
                break
            if w["id"] not in taken and all(ch in met or ch == k for ch in w["kanji"]) and not w["q"][0]:
                w["first"] = True
                chosen.append(w)
                taken.add(w["id"])
                met.add(k)  # a kanji counts as met once a word has brought it in
                n += 1
    rest = sorted((w for w in ws if w["id"] not in taken), key=lambda w: (w["rank"], w["q"]))
    return chosen + rest


def get(eid: int) -> dict | None:
    course()
    return _by_id.get(eid)


def for_kanji(ch: str, limit: int = 8) -> list[dict]:
    return [w for w in course() if ch in w["kanji"]][:limit]


def breakdown(word: str, reading: str) -> dict:
    """Furigana parts + one row per kanji (reading, on/kun, meaning) + the pattern hint."""
    a = readings.analyse(word, reading)
    parts, rows = [], []
    for p in a["parts"]:
        parts.append({"text": p["text"], "ruby": p["reading"] if p["kind"] != "kana" else ""})
        if p["kind"] in ("on", "kun"):
            k = content.kanji_get(p["text"])
            base = p["base"] or ""
            rows.append({"char": p["text"], "reading": p["reading"], "kind": p["kind"],
                         "label": readings.KIND_LABELS[p["kind"]],
                         "base": base.replace(".", "") if base and readings.to_hiragana(base.replace(".", "")) != p["reading"] else "",
                         "change": p["change"] or "", "meaning": content.first_meaning(k) if k else ""})
    if a["special"]:
        for ch in dict.fromkeys(ch for ch in word if readings.is_kanji(ch) and ch != "々"):
            k = content.kanji_get(ch)
            if k:
                rows.append({"char": ch, "reading": "", "kind": "special", "label": "part of a special reading",
                             "base": "", "change": "", "meaning": content.first_meaning(k)})
    return {"parts": parts, "kanji": rows, "hint": readings.hint(word, reading), "special": a["special"]}


def card_view(row) -> dict:
    """Review-card view of a dictionary word (track 'dict'), with the reading breakdown on the back."""
    w = get(row.id)
    gl = w["meaning"] if w else _gloss(row.senses_json)
    v = {"front": row.headword, "front_kind": "jp", "answer": gl, "reading": row.reading if row.reading != row.headword else "",
         "meaning": gl, "extra": "", "stroke": None}
    if any(readings.is_kanji(ch) for ch in row.headword):
        b = breakdown(row.headword, row.reading)
        v.update(parts=b["parts"], kanji=b["kanji"], hint=b["hint"]["text"])
    if row.sentence_jp:
        v.update(sentence_jp=row.sentence_jp, sentence_en=row.sentence_en or "")
    return v


# ------------------------------------------------------------ your kanji
def user_word_ids(c, uid: int) -> dict[int, dict]:
    sc = db.srs_cards.c
    return {int(r.item): r._mapping for r in c.execute(select(sc.item, sc.state, sc.total_reviews, sc.deck_id).where(
        sc.user_id == uid, sc.track == "dict"))}


def known_kanji(c, uid: int) -> dict[str, str]:
    """Each kanji you've met: 'known' (in a word or kanji card you've passed) or 'learning'."""
    out: dict[str, str] = {}

    def mark(ch, state, reviewed):
        level = "known" if state in ("review", "mastered") else ("learning" if reviewed or state else None)
        if level and out.get(ch) != "known":
            out[ch] = level

    sc = db.srs_cards.c
    rows = c.execute(select(sc.track, sc.item, sc.state, sc.total_reviews).where(
        sc.user_id == uid, sc.track.in_(["dict", "kanji"]), sc.suspended == 0)).all()
    dict_ids = [int(r.item) for r in rows if r.track == "dict"]
    heads = {}
    if dict_ids:
        de = db.dict_entries.c
        for i in range(0, len(dict_ids), 900):
            heads.update(dict(c.execute(select(de.id, de.headword).where(de.id.in_(dict_ids[i:i + 900]))).all()))
    for r in rows:
        chars = [r.item] if r.track == "kanji" else [ch for ch in heads.get(int(r.item), "") if readings.is_kanji(ch) and ch != "々"]
        for ch in chars:
            mark(ch, r.state, r.total_reviews)
    return out


def next_words(have: set[int], n: int) -> list[dict]:
    out = []
    for w in course():
        if w["id"] not in have:
            out.append(w)
            if len(out) >= n:
                break
    return out


def pick_guess(known: dict[str, str], have: set[int], exclude: set[int] = frozenset(), rng=random) -> dict | None:
    """A word you haven't studied whose kanji you've all met in other words — so the reading can be worked out."""
    seen = set(known)
    pool = [w for w in course() if w["id"] not in have and w["id"] not in exclude and len(w["kanji"]) >= 1
            and all(ch in seen for ch in w["kanji"]) and not readings.analyse(w["word"], w["reading"])["special"]]
    if not pool:
        return None
    pool = pool[:400]  # stay with the more common words
    return rng.choice(pool)
