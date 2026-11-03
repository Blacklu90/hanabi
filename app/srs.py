"""Server-side spaced repetition (an SM-2 variant with four ratings) with Anki-style decks.

Cards outside a deck (kana lessons, words) are due as soon as their time comes.
Cards in a deck (kanji, imported Anki cards, dictionary words) follow the deck's
daily limits, like Anki: at most `new_per_day` new cards are introduced per day
(in deck order), and at most `max_reviews` reviews are shown per day.
Suspended cards never show; buried cards come back the next day.
"""
from __future__ import annotations

import datetime as dt
import json
import time

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import db

DAY = 86400
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
MAX_INTERVAL = 365.0
CARD_FIELDS = ("ease", "interval_days", "reps", "lapses", "total_reviews", "total_correct", "state", "due_at",
               "last_review_at", "introduced_at")


def day_start(tzname: str | None, now: float | None = None) -> int:
    from .gamify import tz_of
    t = dt.datetime.fromtimestamp(now or time.time(), tz_of(tzname))
    return int(t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def next_day_start(tzname: str | None, now: float | None = None) -> int:
    from .gamify import tz_of
    t = dt.datetime.fromtimestamp(now or time.time(), tz_of(tzname)).date() + dt.timedelta(days=1)
    return int(dt.datetime.combine(t, dt.time(), tz_of(tzname)).timestamp())


# ------------------------------------------------------------------ decks
def get_or_create_deck(c, user_id: int, name: str = "My kanji") -> int:
    d = c.execute(select(db.decks.c.id).where(db.decks.c.user_id == user_id, db.decks.c.name == name)).scalar()
    if d:
        return d
    return c.execute(db.decks.insert().values(user_id=user_id, name=name, created_at=int(time.time()))).inserted_primary_key[0]


def add_card(c, user_id: int, track: str, item: str, now: int | None = None, deck_id: int | None = None,
             position: int = 0) -> bool:
    """Add an item to the review queue (no-op when it already exists). Returns True if added."""
    now = now or int(time.time())
    res = c.execute(sqlite_insert(db.srs_cards).values(
        user_id=user_id, track=track, item=item, due_at=now, created_at=now, state="new", deck_id=deck_id, position=position,
    ).on_conflict_do_nothing(index_elements=["user_id", "track", "item"]))
    return res.rowcount == 1


# -------------------------------------------------------------- scheduling
def next_state(card: dict, rating: int, cfg: dict, now: int) -> dict:
    """Pure scheduling function: returns the updated card fields."""
    ease, interval, reps, lapses = card["ease"], card["interval_days"], card["reps"], card["lapses"]
    total, correct = card["total_reviews"] + 1, card["total_correct"] + (rating >= HARD)
    if rating == AGAIN:
        reps, lapses = 0, lapses + (card["state"] in ("review", "mastered"))
        ease = max(1.3, ease - 0.2)
        interval = 10 / 1440  # see it again in ten minutes
    else:
        reps += 1
        if interval < 1:  # new or learning
            interval = {HARD: 0.5, GOOD: 1.0, EASY: 4.0}[rating]
        else:
            interval = {HARD: interval * 1.2, GOOD: interval * ease, EASY: interval * ease * 1.3}[rating]
        ease = {HARD: max(1.3, ease - 0.15), GOOD: ease, EASY: ease + 0.15}[rating]
    interval = min(interval, MAX_INTERVAL)
    accuracy = 100 * correct / total
    if rating >= HARD and reps >= cfg["mastery_reps"] and accuracy >= cfg["mastery_accuracy"] and interval >= cfg["mastery_interval"]:
        state = "mastered"
    elif interval >= 1:
        state = "review"
    else:
        state = "learning"
    return {"ease": round(ease, 3), "interval_days": round(interval, 4), "reps": reps, "lapses": lapses,
            "total_reviews": total, "total_correct": correct, "state": state,
            "due_at": now + int(interval * DAY), "last_review_at": now,
            "introduced_at": card.get("introduced_at") or now}


def fmt_interval(days: float) -> str:
    mins = days * 1440
    if mins < 60:
        return f"{max(1, round(mins))}m"
    if days < 1:
        return f"{round(mins / 60)}h"
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        return f"{days / 30:.1f}mo".replace(".0mo", "mo")
    return f"{days / 365:.1f}y".replace(".0y", "y")


def previews(card: dict, cfg: dict, now: int) -> dict:
    """What each button would do, e.g. {1: '10m', 2: '12h', 3: '1d', 4: '4d'} (shown on the buttons)."""
    return {r: fmt_interval(next_state(card, r, cfg, now)["interval_days"]) for r in (AGAIN, HARD, GOOD, EASY)}


# ------------------------------------------------------------------- queue
QUEUE_COLS = ("id", "track", "item", "state", "due_at", "interval_days", "lapses", "ease", "reps", "total_reviews",
              "total_correct", "deck_id", "position", "introduced_at", "last_review_at")


def _deck_usage(c, user_id: int, since: int) -> dict[int, tuple[int, int]]:
    """Per deck: (new cards introduced today, reviews of older cards done today)."""
    sc, rv = db.srs_cards.c, db.reviews.c
    intro = dict(c.execute(select(sc.deck_id, func.count()).where(sc.user_id == user_id, sc.deck_id.isnot(None),
                                                                 sc.introduced_at >= since).group_by(sc.deck_id)).all())
    revs = dict(c.execute(select(sc.deck_id, func.count()).select_from(db.reviews.join(db.srs_cards, sc.id == rv.card_id))
                          .where(rv.user_id == user_id, sc.deck_id.isnot(None), rv.created_at >= since,
                                 or_(sc.introduced_at < since, sc.introduced_at.is_(None))).group_by(sc.deck_id)).all())
    return {d: (intro.get(d, 0), revs.get(d, 0)) for d in set(intro) | set(revs)}


def queue(c, user_id: int, tzname: str, now: int | None = None, track: str | None = None, deck_id: int | None = None,
          limit: int = 60) -> list[dict]:
    """Cards to study now, respecting deck limits. Reviews (most overdue first), then new cards in deck order."""
    now = now or int(time.time())
    since = day_start(tzname, now)
    sc = db.srs_cards.c
    cols = [getattr(sc, k) for k in QUEUE_COLS]
    base = [sc.user_id == user_id, sc.suspended == 0, sc.buried_until <= now]
    if track:
        base.append(sc.track == track)
    if deck_id is not None:
        base.append(sc.deck_id == deck_id)
    out = []
    if deck_id is None:  # cards that aren't in any deck: no limits
        out += [dict(r._mapping) for r in c.execute(select(*cols).where(*base, sc.deck_id.is_(None), sc.due_at <= now)
                                                    .order_by(sc.due_at).limit(limit))]
    usage = _deck_usage(c, user_id, since)
    dq = select(db.decks.c.id, db.decks.c.new_per_day, db.decks.c.max_reviews).where(db.decks.c.user_id == user_id)
    if deck_id is not None:
        dq = dq.where(db.decks.c.id == deck_id)
    news = []
    for d in c.execute(dq).all():
        intro, done = usage.get(d.id, (0, 0))
        rev_left, new_left = max(0, d.max_reviews - done), max(0, d.new_per_day - intro)
        if rev_left:
            out += [dict(r._mapping) for r in c.execute(select(*cols).where(*base, sc.deck_id == d.id, sc.total_reviews > 0,
                                                                            sc.due_at <= now).order_by(sc.due_at).limit(min(rev_left, limit)))]
        if new_left:
            news += [dict(r._mapping) for r in c.execute(select(*cols).where(*base, sc.deck_id == d.id, sc.total_reviews == 0)
                                                         .order_by(sc.position, sc.id).limit(min(new_left, limit)))]
    out.sort(key=lambda r: r["due_at"])
    return (out + news)[:limit]


def _limited_counts(c, user_id: int, tzname: str, now: int) -> tuple[dict, dict[int, dict]]:
    """Same numbers as len(queue(...)), from one grouped query instead of two queries per deck."""
    sc = db.srs_cards.c
    base = [sc.user_id == user_id, sc.suspended == 0, sc.buried_until <= now]
    loose = c.execute(select(func.count(), db.count_if(sc.total_reviews == 0), db.count_if((sc.total_reviews > 0) & (sc.interval_days < 1)))
                      .where(*base, sc.deck_id.is_(None), sc.due_at <= now)).one()
    total = {"new": loose[1] or 0, "learn": loose[2] or 0}
    total["review"] = (loose[0] or 0) - total["new"] - total["learn"]
    per = {r.deck_id: r for r in c.execute(
        select(sc.deck_id,
               db.count_if((sc.total_reviews > 0) & (sc.due_at <= now)).label("due"),
               db.count_if((sc.total_reviews > 0) & (sc.due_at <= now) & (sc.interval_days < 1)).label("learn"),
               db.count_if(sc.total_reviews == 0).label("new"))
        .where(*base, sc.deck_id.isnot(None)).group_by(sc.deck_id))}
    usage = _deck_usage(c, user_id, day_start(tzname, now))
    decks = {}
    for d in c.execute(select(db.decks.c.id, db.decks.c.new_per_day, db.decks.c.max_reviews).where(db.decks.c.user_id == user_id)):
        r = per.get(d.id)
        intro, done = usage.get(d.id, (0, 0))
        due = min(r.due or 0, max(0, d.max_reviews - done)) if r else 0
        learn = min(r.learn or 0, due) if r else 0
        new = min(r.new or 0, max(0, d.new_per_day - intro)) if r else 0
        decks[d.id] = {"new": new, "learn": learn, "review": due - learn}
        for k in ("new", "learn", "review"):
            total[k] += decks[d.id][k]
    total["total"] = total["new"] + total["learn"] + total["review"]
    return total, decks


def counts(c, user_id: int, tzname: str, now: int | None = None) -> dict:
    """Anki-style counts for everything due now: new / learning / review, plus a total."""
    return _limited_counts(c, user_id, tzname, now or int(time.time()))[0]


def deck_counts(c, user_id: int, tzname: str, now: int | None = None) -> dict[int, dict]:
    return _limited_counts(c, user_id, tzname, now or int(time.time()))[1]


# ------------------------------------------------------------------ review
def review(c, user_id: int, card_id: int, rating: int, cfg: dict, now: int | None = None):
    now = now or int(time.time())
    row = c.execute(select(db.srs_cards).where(db.srs_cards.c.id == card_id, db.srs_cards.c.user_id == user_id)).first()
    if row is None:
        return None
    card = dict(row._mapping)
    new = next_state(card, rating, cfg, now)
    c.execute(update(db.srs_cards).where(db.srs_cards.c.id == card_id).values(**new))
    prev = {k: card[k] for k in CARD_FIELDS}
    rid = c.execute(db.reviews.insert().values(user_id=user_id, card_id=card_id, rating=rating, interval_days=new["interval_days"],
                                               created_at=now, prev_json=json.dumps(prev))).inserted_primary_key[0]
    mastered_now = new["state"] == "mastered" and card["state"] != "mastered"
    record_progress(c, user_id, card["track"], card["item"], rating >= HARD, now, mastered=new["state"] == "mastered")
    return {**card, **new, "mastered_now": mastered_now, "review_id": rid}


def undo(c, user_id: int, review_id: int):
    """Undo the user's most recent review: restore the card, remove the review and its XP."""
    rv = db.reviews.c
    last = c.execute(select(db.reviews).where(rv.user_id == user_id).order_by(rv.id.desc()).limit(1)).first()
    if last is None or last.id != review_id or not last.prev_json:
        return None
    prev = json.loads(last.prev_json)
    card = c.execute(select(db.srs_cards).where(db.srs_cards.c.id == last.card_id)).first()
    c.execute(update(db.srs_cards).where(db.srs_cards.c.id == last.card_id).values(**prev))
    c.execute(delete(db.reviews).where(rv.id == review_id))
    p = db.progress.c
    c.execute(update(db.progress).where(p.user_id == user_id, p.track == card.track, p.item == card.item)
              .values(attempts=func.max(0, p.attempts - 1), correct=func.max(0, p.correct - int(last.rating >= HARD)),
                      mastered_at=None if prev["state"] != "mastered" else p.mastered_at))
    xe = db.xp_events.c
    amt = c.execute(select(xe.amount).where(xe.user_id == user_id, xe.dedupe_key == f"review:{review_id}")).scalar() or 0
    c.execute(delete(db.xp_events).where(xe.user_id == user_id, xe.dedupe_key == f"review:{review_id}"))
    if amt:
        c.execute(update(db.users).where(db.users.c.id == user_id).values(xp=db.users.c.xp - amt))
    return {"card_id": last.card_id, "track": card.track, "item": card.item, "xp_removed": amt}


def record_progress(c, user_id: int, track: str, item: str, correct: bool, now: int, mastered: bool | None = None):
    p = db.progress
    stmt = sqlite_insert(p).values(user_id=user_id, track=track, item=item, attempts=1, correct=int(correct), updated_at=now,
                                   mastered_at=now if mastered else None)
    set_ = {"attempts": p.c.attempts + 1, "correct": p.c.correct + int(correct), "updated_at": now}
    if mastered is True:
        set_["mastered_at"] = func.coalesce(p.c.mastered_at, now)
    elif mastered is False:
        set_["mastered_at"] = None
    c.execute(stmt.on_conflict_do_update(index_elements=["user_id", "track", "item"], set_=set_))


# kept for older imports
def due_cards(c, user_id: int, now: int, track: str | None = None, limit: int = 50, tzname: str = "UTC"):
    return queue(c, user_id, tzname, now, track=track, limit=limit)
