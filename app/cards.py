"""Everything the review screen needs for a list of queue rows (one batch of queries)."""
from __future__ import annotations

import json
import time

from sqlalchemy import select

from . import content, db, kana_words, srs, words

TRACK_LABELS = {**content.TRACKS, "card": "Card", "dict": "Word", "hword": "Hiragana word", "kword": "Katakana word"}


def custom_view(row) -> dict:
    v = {"front": row.front, "front_kind": "text" if len(row.front) > 12 else "jp", "answer": row.back,
         "reading": "", "meaning": row.back, "extra": row.extra, "stroke": None}
    if getattr(row, "model_id", None):  # imported from Anki: shown with the deck's own template, images and audio
        v["anki"] = {"front": f"/anki-card/{row.id}?side=front", "back": f"/anki-card/{row.id}?side=back"}
    return v


def dict_view(row) -> dict:
    return words.card_view(row)


def build(c, u, rows: list[dict], now: int | None = None) -> list[dict]:
    now = now or int(time.time())
    cfg = {"mastery_reps": u["mastery_reps"], "mastery_accuracy": u["mastery_accuracy"], "mastery_interval": u["mastery_interval"]}
    uid = u["id"]
    custom_ids = [int(r["item"]) for r in rows if r["track"] == "card"]
    dict_ids = [int(r["item"]) for r in rows if r["track"] == "dict"]
    customs = {r.id: r for r in c.execute(select(db.custom_cards).where(db.custom_cards.c.user_id == uid,
                                                                         db.custom_cards.c.id.in_(custom_ids)))} if custom_ids else {}
    dicts = {r.id: r for r in c.execute(select(db.dict_entries).where(db.dict_entries.c.id.in_(dict_ids)))} if dict_ids else {}
    keys = [(r["track"], r["item"]) for r in rows]
    notes = {}
    if keys:
        n = db.notes.c
        for r in c.execute(select(db.notes).where(n.user_id == uid, n.item.in_([k[1] for k in keys]))):
            notes[(r.track, r.item)] = r
    deck_names = dict(c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == uid)).all())
    out = []
    for r in rows:
        t, item = r["track"], r["item"]
        if t == "card":
            row = customs.get(int(item))
            if row is None:
                continue
            v = custom_view(row)
        elif t in ("hword", "kword"):
            v = kana_words.card_view(kana_words.script_of_track(t), int(item))
            if v is None:
                continue
        elif t == "dict":
            row = dicts.get(int(item))
            if row is None:
                continue
            v = dict_view(row)
        else:
            v = content.card_view(t, item)
            if t == "kanji":  # show the kanji at work in real words
                v["words"] = [{"word": w["word"], "reading": w["reading"], "meaning": w["meaning"].split("; ")[0]}
                              for w in words.for_kanji(item, 3)]
        # What the ▶ button says (imported Anki cards play their own recordings instead).
        if t == "dict":
            v["say"] = {"text": row.headword, "reading": row.reading}
        elif t in ("hword", "kword", "hvocab", "kvocab", "hiragana", "katakana"):
            v["say"] = {"text": v["front"], "reading": ""}
        note = notes.get((t, item))
        if note and note.meaning:
            v["answer"] = note.meaning
        v.update({
            "id": r["id"], "track": t, "item": item, "state": r["state"], "is_new": r["total_reviews"] == 0,
            "label": TRACK_LABELS.get(t, t), "deck": deck_names.get(r["deck_id"]),
            "previews": srs.previews(r, cfg, now),
            "my_mnemonic": note.mnemonic if note else "", "my_notes": note.notes if note else "",
            "my_meaning": note.meaning if note else "",
        })
        out.append(v)
    return out
