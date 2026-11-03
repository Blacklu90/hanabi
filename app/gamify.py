"""XP, levels, streaks, achievements and the activity feed.

Every XP award goes through `award()` with a dedupe key, so refreshing a page
or replaying a request can never grant the same XP twice.
"""
from __future__ import annotations

import datetime as dt
import math
import time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import db

# XP from repeatable activities (quizzes, games, writing, bursts) is capped per day.
DAILY_ACTIVITY_CAP = 300
CAPPED_SOURCES = ("quiz", "game", "writing", "burst", "review")


def tz_of(tzname: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tzname or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def local_day(tzname: str | None, ts: float | None = None) -> str:
    return dt.datetime.fromtimestamp(ts or time.time(), tz_of(tzname)).date().isoformat()


def level_for(xp: int) -> dict:
    """Level L needs 25·L·(L−1) total XP: 0, 50, 150, 300, 500 …"""
    lvl = int((1 + math.sqrt(1 + 4 * xp / 25)) / 2)
    while 25 * (lvl + 1) * lvl <= xp:
        lvl += 1
    while lvl > 1 and 25 * lvl * (lvl - 1) > xp:
        lvl -= 1
    base, nxt = 25 * lvl * (lvl - 1), 25 * (lvl + 1) * lvl
    return {"level": lvl, "xp": xp, "into": xp - base, "span": nxt - base, "pct": round(100 * (xp - base) / (nxt - base))}


def award(c, user_id: int, source: str, key: str, amount: int, tzname: str) -> int:
    """Insert an XP event once per (user, key). Returns XP actually granted."""
    day = local_day(tzname)
    if source in CAPPED_SOURCES and amount > 0:
        used = c.execute(select(func.coalesce(func.sum(db.xp_events.c.amount), 0)).where(
            db.xp_events.c.user_id == user_id, db.xp_events.c.day == day, db.xp_events.c.source.in_(CAPPED_SOURCES))).scalar()
        amount = max(0, min(amount, DAILY_ACTIVITY_CAP - used))
    res = c.execute(sqlite_insert(db.xp_events).values(
        user_id=user_id, source=source, dedupe_key=key, amount=amount, day=day, created_at=int(time.time())
    ).on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"]))
    if res.rowcount != 1:
        return 0
    if amount:
        c.execute(update(db.users).where(db.users.c.id == user_id).values(xp=db.users.c.xp + amount))
    return amount


def log(c, user_id: int, kind: str, text: str) -> None:
    c.execute(db.activity.insert().values(user_id=user_id, kind=kind, text=text[:200], created_at=int(time.time())))


def study_days(c, user_id: int, limit: int = 400) -> list[str]:
    return [r[0] for r in c.execute(
        select(db.xp_events.c.day).where(db.xp_events.c.user_id == user_id).group_by(db.xp_events.c.day)
        .order_by(db.xp_events.c.day.desc()).limit(limit))]


def streak_info(c, user_id: int, tzname: str) -> dict:
    """Kind streak: one missed day in a row is a free rest day; two in a row resets.

    This keeps the motivation of a streak without the all-or-nothing pressure
    that tends to make people quit after a single bad day.
    """
    days = {dt.date.fromisoformat(d) for d in study_days(c, user_id)}
    today = dt.date.fromisoformat(local_day(tzname))
    cur, rests = streak_from(days, today)
    return {"current": cur, "studied_today": today in days, "rest_days": rests, "best": max(cur, best_streak(days))}


def streak_from(days: set, today: dt.date) -> tuple[int, int]:
    if not days:
        return 0, 0
    d = today if today in days else today - dt.timedelta(days=1)
    first = min(days)
    count = rests = gap = 0
    while d >= first:
        if d in days:
            count += 1
            rests += gap
            gap = 0
        else:
            gap += 1
            if gap >= 2:
                break
        d -= dt.timedelta(days=1)
    return count, rests


def best_streak(days: set) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and (d - prev).days <= 2 else 1
        best = max(best, run)
        prev = d
    return best


def today_xp(c, user_id: int, tzname: str) -> int:
    return c.execute(select(func.coalesce(func.sum(db.xp_events.c.amount), 0)).where(
        db.xp_events.c.user_id == user_id, db.xp_events.c.day == local_day(tzname))).scalar()


# ------------------------------------------------------------ achievements
# (code, title, description, icon, xp, predicate over stats)
ACHIEVEMENTS = [
    ("first_lesson", "First spark", "Finish your first lesson.", "✦", 10, lambda s: s["lessons"] >= 1),
    ("hira_5", "Getting the hang of it", "Finish 5 hiragana lessons.", "あ", 15, lambda s: s["hira_lessons"] >= 5),
    ("hira_basic", "Gojūon complete", "Finish all 10 basic hiragana lessons.", "ん", 30, lambda s: s["hira_basic"] >= 10),
    ("hira_all", "Hiragana hero", "Finish every hiragana lesson.", "ひ", 50, lambda s: s["hira_lessons"] >= 26),
    ("kata_5", "Katakana curious", "Finish 5 katakana lessons.", "ア", 15, lambda s: s["kata_lessons"] >= 5),
    ("kata_all", "Katakana hero", "Finish every katakana lesson.", "カ", 50, lambda s: s["kata_lessons"] >= 32),
    ("review_1", "Brain gym", "Do your first review.", "↻", 5, lambda s: s["reviews"] >= 1),
    ("review_100", "Hundred reps", "Complete 100 reviews.", "百", 25, lambda s: s["reviews"] >= 100),
    ("review_1000", "Thousand reps", "Complete 1,000 reviews.", "千", 75, lambda s: s["reviews"] >= 1000),
    ("quiz_1", "Quiz taker", "Finish a quiz.", "?", 5, lambda s: s["quizzes"] >= 1),
    ("quiz_perfect", "Flawless", "Score 100% on a quiz with at least 10 questions.", "◎", 20, lambda s: s["perfect"] >= 1),
    ("mastery_1", "Proven", "Pass a mastery test.", "合", 25, lambda s: s["mastery_passed"] >= 1),
    ("mastery_5", "Examiner", "Pass 5 mastery tests.", "格", 50, lambda s: s["mastery_passed"] >= 5),
    ("sprint_15", "Quick fingers", "Get 15 right in a 60-second sprint.", "⚡", 20, lambda s: s["sprint_best"] >= 15),
    ("sprint_30", "Lightning", "Get 30 right in a 60-second sprint.", "雷", 40, lambda s: s["sprint_best"] >= 30),
    ("kanji_1", "First kanji", "Add your first kanji to reviews.", "一", 5, lambda s: s["kanji_started"] >= 1),
    ("kanji_80", "Grade 1 explorer", "Start 80 kanji.", "八", 30, lambda s: s["kanji_started"] >= 80),
    ("kanji_500", "Kanji climber", "Start 500 kanji.", "山", 75, lambda s: s["kanji_started"] >= 500),
    ("kanji_m10", "Rooted", "Master 10 kanji.", "木", 30, lambda s: s["kanji_mastered"] >= 10),
    ("kanji_m100", "Forest", "Master 100 kanji.", "森", 100, lambda s: s["kanji_mastered"] >= 100),
    ("vocab_20", "Word collector", "Add 20 words to reviews.", "語", 15, lambda s: s["vocab_started"] >= 20),
    ("write_10", "Brush in hand", "Practise writing 10 characters.", "筆", 15, lambda s: s["writing"] >= 10),
    ("game_1", "Matchmaker", "Finish a matching game.", "♢", 5, lambda s: s["games"] >= 1),
    ("game_clean", "No misses", "Finish a matching game without a single miss.", "◇", 15, lambda s: s["clean_games"] >= 1),
    ("burst_1", "Burst!", "Finish a focus burst.", "花", 10, lambda s: s["bursts"] >= 1),
    ("burst_10", "Fireworks show", "Finish 10 focus bursts.", "火", 30, lambda s: s["bursts"] >= 10),
    ("streak_3", "Warming up", "Reach a 3-day streak.", "三", 15, lambda s: s["streak"] >= 3),
    ("streak_7", "One whole week", "Reach a 7-day streak.", "週", 30, lambda s: s["streak"] >= 7),
    ("streak_30", "Habit formed", "Reach a 30-day streak.", "月", 100, lambda s: s["streak"] >= 30),
    ("level_5", "Level 5", "Reach level 5.", "五", 0, lambda s: s["level"] >= 5),
    ("level_10", "Level 10", "Reach level 10.", "十", 0, lambda s: s["level"] >= 10),
]
ACH_BY_CODE = {a[0]: a for a in ACHIEVEMENTS}


def stats(c, user_id: int, tzname: str) -> dict:
    lc = db.lesson_completions.c
    lessons = [r[0] for r in c.execute(select(lc.lesson).where(lc.user_id == user_id))]
    hira = [x for x in lessons if x.startswith("hiragana-")]
    kata = [x for x in lessons if x.startswith("katakana-")]
    sc = db.srs_cards.c
    track_counts = {(r.track, r.state): r.n for r in c.execute(
        select(sc.track, sc.state, func.count().label("n")).where(sc.user_id == user_id).group_by(sc.track, sc.state))}
    qa = db.quiz_attempts.c
    q = c.execute(select(
        func.count().label("n"),
        db.count_if((qa.score == qa.total) & (qa.total >= 10)).label("perfect"),
        db.count_if((qa.mode == "mastery") & (qa.passed == 1)).label("mp"),
        func.max(func.iif(qa.mode == "sprint60", qa.score, 0)).label("sb"),
    ).where(qa.user_id == user_id, qa.finished_at.isnot(None))).one()
    gs = db.game_sessions.c
    g = c.execute(select(
        db.count_if(gs.deck != "burst").label("games"),
        db.count_if((gs.deck != "burst") & (gs.misses == 0)).label("clean"),
        db.count_if(gs.deck == "burst").label("bursts"),
    ).where(gs.user_id == user_id, gs.finished_at.isnot(None))).one()
    xe = db.xp_events.c
    writing = c.execute(select(func.count()).where(xe.user_id == user_id, xe.source == "writing")).scalar()
    reviews = c.execute(select(func.count()).select_from(db.reviews).where(db.reviews.c.user_id == user_id)).scalar()
    xp = c.execute(select(db.users.c.xp).where(db.users.c.id == user_id)).scalar() or 0

    def started(track):
        return sum(n for (t, _), n in track_counts.items() if t == track)

    return {
        "lessons": len(lessons), "hira_lessons": len(hira), "kata_lessons": len(kata),
        "hira_basic": sum(1 for x in hira if int(x.split("-")[1]) <= 10),
        "reviews": reviews, "quizzes": q.n or 0, "perfect": q.perfect or 0, "mastery_passed": q.mp or 0,
        "sprint_best": q.sb or 0, "kanji_started": started("kanji"),
        "kanji_mastered": track_counts.get(("kanji", "mastered"), 0),
        "vocab_started": started("hvocab") + started("kvocab"), "writing": writing,
        "games": g.games or 0, "clean_games": g.clean or 0, "bursts": g.bursts or 0,
        "streak": streak_info(c, user_id, tzname)["current"], "level": level_for(xp)["level"],
        "track_counts": track_counts, "lesson_ids": set(lessons),
    }


def check_achievements(c, user_id: int, tzname: str) -> list[dict]:
    """Unlock any newly earned achievements (each unlocks and pays out once)."""
    have = {r[0] for r in c.execute(select(db.achievements.c.code).where(db.achievements.c.user_id == user_id))}
    s = stats(c, user_id, tzname)
    new = []
    for code, title, desc, icon, xp, pred in ACHIEVEMENTS:
        if code in have or not pred(s):
            continue
        res = c.execute(sqlite_insert(db.achievements).values(user_id=user_id, code=code, unlocked_at=int(time.time()))
                        .on_conflict_do_nothing(index_elements=["user_id", "code"]))
        if res.rowcount == 1:
            award(c, user_id, "achievement", f"ach:{code}", xp, tzname)
            log(c, user_id, "achievement", f"Unlocked “{title}”")
            new.append({"code": code, "title": title, "icon": icon, "xp": xp})
    return new
