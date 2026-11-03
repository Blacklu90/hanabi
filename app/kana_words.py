"""Kana through words: read real words as soon as you know their kana.

Like the kanji course (words.py), but for hiragana and katakana. Every common JMdict
word is split into kana units (か, きゃ, っ, ー, ファ…). A word unlocks at the first lesson
after which you know all of its units, so each lesson comes with words you can read right away.
Hiragana words are the reading of common words (ねこ, usually written 猫); katakana words
are the common words written in katakana (mostly loanwords).
"""
from __future__ import annotations

import json
import random
import re
import threading

from sqlalchemy import select

from . import db
from .kana import SCRIPTS, romanize, romaji_to_hiragana, to_hiragana

PER_LESSON = 10
_HIRA = re.compile(r"^[ぁ-ゔー]+$")
_KATA = re.compile(r"^[ァ-ヴー]+$")
SMALL_Y = set("ゃゅょャュョ")
SMALL_VOWELS = set("ァィゥェォ")
_lock = threading.Lock()
_cache: dict[str, dict] = {}

DAKUTEN = {**{b: a for a, b in zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ")},
           **{b: a for a, b in zip("はひふへほ", "ぱぴぷぺぽ")}}
LONG_PAIRS = {("a", "a"), ("i", "i"), ("u", "u"), ("e", "e"), ("o", "o"), ("o", "u"), ("e", "i")}


def _unit_lessons(script: str) -> dict[str, int]:
    """Each kana unit -> the lesson that teaches it."""
    out = {c["kana"]: c["lesson"] for c in SCRIPTS[script]["chars"]}
    small_tsu = "っ" if script == "hiragana" else "ッ"
    tsu = "つ" if script == "hiragana" else "ツ"
    out.setdefault(small_tsu, out[tsu])  # small っ is taught with つ (hiragana has no separate lesson for it)
    return out


def units(word: str, known: dict[str, int]) -> list[str] | None:
    """Split a kana word into lesson units; None if it uses something no lesson teaches."""
    out, i = [], 0
    while i < len(word):
        two = word[i:i + 2]
        if len(two) == 2 and two in known:
            out.append(two)
            i += 2
        elif word[i] in known:
            out.append(word[i])
            i += 1
        else:
            return None
    return out


def _romaji(unit: str) -> str:
    return romanize(unit) if unit not in ("っ", "ッ", "ー") else ""


def breakdown(word: str, script: str) -> dict:
    """One row per unit with its romaji, plus notes on what's special in this word."""
    ul = _unit_lessons(script)
    us = units(word, ul) or list(word)
    rows, notes = [], []
    rom = romanize(word)
    for i, u in enumerate(us):
        hira = to_hiragana(u)
        r = {"kana": u, "romaji": _romaji(u), "note": ""}
        if u in ("っ", "ッ"):
            nxt = romanize(us[i + 1])[:1] if i + 1 < len(us) else ""
            r["note"] = f"small っ: doubles the next sound ({nxt}{nxt})" if nxt else "small っ: a short stop"
            notes.append("small-tsu")
        elif u == "ー":
            prev = romanize(us[i - 1])[-1:] if i else ""
            r["note"] = f"ー makes the {prev} long" if prev else "ー makes the vowel long"
            notes.append("long")
        elif len(u) == 2 and u[1] in SMALL_Y | {"ゃ", "ゅ", "ょ"}:
            r["note"] = f"{u[0]} + small {u[1]} = one sound"
            notes.append("combo")
        elif len(u) == 2 and u[1] in SMALL_VOWELS:
            r["note"] = f"{u[0]} + small {u[1]}: a sound from foreign words"
            notes.append("foreign")
        elif hira[:1] in DAKUTEN:
            base = DAKUTEN[hira[0]]
            mark = "゜" if hira[0] in "ぱぴぷぺぽ" else "゛"
            base = base if script == "hiragana" else chr(ord(base) + 0x60)
            r["note"] = f"{base} + {mark}"
            notes.append("dakuten")
        rows.append(r)
    # long vowels written with a second vowel (おう, えい, ああ…)
    for a, b in zip(us, us[1:]):
        ra, rb = romanize(a), romanize(b)
        if ra and rb in ("a", "i", "u", "e", "o") and (ra[-1], rb) in LONG_PAIRS and len(b) == 1:
            notes.append("long-vowel")
            break
    return {"rows": rows, "romaji": rom, "notes": list(dict.fromkeys(notes))}


NOTE_TEXT = {
    "dakuten": "゛ voices a sound (か→が) and ゜ turns h into p (は→ぱ).",
    "combo": "A small ゃ/ゅ/ょ joins the kana before it into one sound.",
    "small-tsu": "A small っ means a short pause: the next consonant is doubled.",
    "long": "ー stretches the vowel before it.",
    "long-vowel": "Two vowels in a row (おう, えい, ああ…) are read as one long vowel.",
    "foreign": "Small ァィゥェォ make sounds that came in with foreign words.",
}


def _is_minor(pos: set) -> bool:
    return bool(pos & {"prefix", "suffix", "counter", "particle", "auxiliary", "auxiliary verb", "copula"})


def course(script: str) -> dict:
    """{'words': [...], 'by_id': {...}} for one script, ordered by the lesson that unlocks each word."""
    with _lock:
        if script in _cache:
            return _cache[script]
        ul = _unit_lessons(script)
        de = db.dict_entries.c
        with db.ro() as c:
            rows = c.execute(select(de.id, de.headword, de.reading, de.senses_json, de.sentence_jp, de.sentence_en)
                             .where(de.common == 1)).all()
        cands, seen = [], set()
        for r in rows:
            if script == "hiragana":
                word = r.reading
                if not _HIRA.match(word) or "ー" in word:
                    continue
                written = r.headword if r.headword != r.reading else ""
            else:
                word = r.headword
                if not _KATA.match(word):
                    continue
                written = ""
            if word in seen or len(word) > 8:
                continue
            us = units(word, ul)
            if not us or len(us) < 2:
                continue
            senses = json.loads(r.senses_json)
            if not senses:
                continue
            pos = set(senses[0]["p"])
            seen.add(word)
            usually_kana = any("usually written using kana alone" in m for s in senses for m in s.get("m", []))
            cands.append({
                "id": r.id, "word": word, "written": written, "meaning": "; ".join(senses[0]["g"][:3]),
                "lesson": max(ul[u] for u in us), "jp": r.sentence_jp, "en": r.sentence_en,
                "q": (_is_minor(pos), not (usually_kana or not written), r.sentence_jp is None, abs(len(us) - 3), r.id),
            })
        cands.sort(key=lambda w: (w["lesson"], w["q"]))
        # Each lesson brings its best few words first; the rest follow in lesson order.
        first, rest, per = [], [], {}
        for w in cands:
            n = per.get(w["lesson"], 0)
            if n < PER_LESSON and not w["q"][0]:
                per[w["lesson"]] = n + 1
                w["first"] = True
                first.append(w)
            else:
                rest.append(w)
        ordered = first + sorted(rest, key=lambda w: (w["lesson"], w["q"]))
        for i, w in enumerate(ordered, 1):
            w["n"] = i
            del w["q"]
        _cache[script] = {"words": ordered, "by_id": {w["id"]: w for w in ordered}}
        return _cache[script]


def get(script: str, eid: int) -> dict | None:
    return course(script)["by_id"].get(eid)


def track(script: str) -> str:
    return "hword" if script == "hiragana" else "kword"


def script_of_track(t: str) -> str | None:
    return {"hword": "hiragana", "kword": "katakana"}.get(t)


def for_lesson(script: str, lesson: int, limit: int = PER_LESSON) -> list[dict]:
    return [w for w in course(script)["words"] if w["lesson"] == lesson and w.get("first")][:limit]


# ------------------------------------------------------------ your kana
def known_kana(c, uid: int, script: str) -> set[str]:
    """Kana you've learned: lessons you finished, plus kana cards you've reviewed."""
    sc = SCRIPTS[script]
    done = set(c.execute(select(db.lesson_completions.c.lesson).where(
        db.lesson_completions.c.user_id == uid, db.lesson_completions.c.lesson.like(f"{script}-%"))).scalars())
    out = {k for les in sc["lessons"] if les["slug"] in done for k in les["chars"]}
    s = db.srs_cards.c
    out |= set(c.execute(select(s.item).where(s.user_id == uid, s.track == script, s.total_reviews > 0)).scalars())
    tsu, small = ("つ", "っ") if script == "hiragana" else ("ツ", "ッ")
    if tsu in out:
        out.add(small)
    return out


def can_read(w: dict, known: set[str], script: str) -> bool:
    us = units(w["word"], _unit_lessons(script))
    return bool(us) and all(u in known for u in us)


def user_ids(c, uid: int, script: str) -> dict[int, dict]:
    s = db.srs_cards.c
    return {int(r.item): r._mapping for r in c.execute(select(s.item, s.state, s.total_reviews).where(
        s.user_id == uid, s.track == track(script)))}


def next_words(script: str, known: set[str], have: set[int], n: int) -> list[dict]:
    out = []
    for w in course(script)["words"]:
        if w["id"] not in have and can_read(w, known, script):
            out.append(w)
            if len(out) >= n:
                break
    return out


def pick_read(script: str, known: set[str], have: set[int], exclude: set[int] = frozenset(), rng=random) -> dict | None:
    pool = [w for w in course(script)["words"] if w["id"] not in have and w["id"] not in exclude and can_read(w, known, script)]
    return rng.choice(pool[:300]) if pool else None


_MACRONS = {"ā": ("aa",), "ī": ("ii",), "ū": ("uu",), "ē": ("ee", "ei"), "ō": ("ou", "oo")}


def answer_ok(answer: str, word: str) -> bool:
    """Kana (either script) or romaji, Hepburn or the usual typing spellings; macrons are fine."""
    a = answer.strip().replace(" ", "").lower()
    if not a:
        return False
    target = to_hiragana(word)
    if not a.isascii() and not any(ch in _MACRONS for ch in a):
        return to_hiragana(a) == target
    variants = {a}
    for mac, subs in _MACRONS.items():
        variants = {v.replace(mac, s) for v in variants for s in subs}
    for v in variants:
        if v == romanize(word).lower() or romaji_to_hiragana(v) == target:
            return True
    return False


def card_view(script: str, eid: int) -> dict | None:
    w = get(script, eid)
    if not w:
        return None
    b = breakdown(w["word"], script)
    v = {"front": w["word"], "front_kind": "jp", "answer": w["meaning"], "reading": b["romaji"], "meaning": w["meaning"],
         "extra": f"Usually written {w['written']}" if w["written"] else "", "stroke": None,
         "kana_rows": b["rows"], "hint": " ".join(NOTE_TEXT[n] for n in b["notes"])}
    if w["jp"]:
        v.update(sentence_jp=w["jp"], sentence_en=w["en"] or "")
    return v
