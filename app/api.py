"""JSON API. Every write is per-user, CSRF-checked, validated and idempotent where XP is involved."""
from __future__ import annotations

import json
import re
import random
import secrets
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import apkg, cards, content, db, gamify, quiz, srs
from .security import limiter
from .kana import NON_SYLLABLE, SCRIPTS, to_hiragana, to_katakana
from .web import api_csrf, err, mastery_cfg, ok, require_user

router = APIRouter(prefix="/api")
W = [Depends(api_csrf)]
GRACE = 2  # seconds of network grace after a timed deadline


def finish_up(c, u) -> dict:
    """Common tail for writes: unlock achievements and report fresh totals."""
    new = gamify.check_achievements(c, u["id"], u["timezone"])
    xp = c.execute(select(db.users.c.xp).where(db.users.c.id == u["id"])).scalar()
    return {"achievements": new, "level": gamify.level_for(xp), "today_xp": gamify.today_xp(c, u["id"], u["timezone"]),
            "goal": u["daily_goal"]}


# ------------------------------------------------------------------ lessons
class LessonIn(BaseModel):
    lesson: str = Field(max_length=32)


@router.post("/lesson/complete", dependencies=W)
def lesson_complete(body: LessonIn, u=Depends(require_user)):
    script, _, n = body.lesson.partition("-")
    if script not in SCRIPTS or not n.isdigit() or not 1 <= int(n) <= len(SCRIPTS[script]["lessons"]):
        return err("Unknown lesson.", 404)
    les = SCRIPTS[script]["lessons"][int(n) - 1]
    now = int(time.time())
    with db.tx() as c:
        res = c.execute(sqlite_insert(db.lesson_completions).values(user_id=u["id"], lesson=les["slug"], completed_at=now)
                        .on_conflict_do_nothing(index_elements=["user_id", "lesson"]))
        first = res.rowcount == 1
        added = sum(srs.add_card(c, u["id"], script, ch, now) for ch in les["chars"])
        xp = gamify.award(c, u["id"], "lesson", f"lesson:{les['slug']}", 10, u["timezone"]) if first else 0
        if first:
            gamify.log(c, u["id"], "lesson", f"Finished {SCRIPTS[script]['label']} · {les['title']}")
        tail = finish_up(c, u)
    return ok(first=first, xp=xp, cards_added=added, **tail)


# ------------------------------------------------------------- flashcards
class AddIn(BaseModel):
    track: str
    items: list[str] = Field(min_length=1, max_length=200)


@router.post("/srs/add", dependencies=W)
def srs_add(body: AddIn, u=Depends(require_user)):
    if body.track not in content.TRACKS:
        return err("Unknown track.")
    bad = [i for i in body.items if not content.valid_item(body.track, i)]
    if bad:
        return err(f"Not a valid item: {bad[0]}")
    with db.tx() as c:
        added = sum(srs.add_card(c, u["id"], body.track, i) for i in body.items)
        if added:
            gamify.log(c, u["id"], "srs", f"Added {added} {content.TRACKS[body.track].lower()} to reviews")
        tail = finish_up(c, u)
    return ok(added=added, **tail)


@router.get("/review/queue")
def review_queue(track: str = "", deck: int = 0, u=Depends(require_user)):
    now = int(time.time())
    with db.ro() as c:
        rows = srs.queue(c, u["id"], u["timezone"], now, track=track or None, deck_id=deck or None, limit=60)
        data = cards.build(c, u, rows, now)
    return ok(cards=data)


class ReviewIn(BaseModel):
    card_id: int
    rating: int = Field(ge=1, le=4)


@router.post("/review/submit", dependencies=W)
def review_submit(body: ReviewIn, u=Depends(require_user)):
    now = int(time.time())
    with db.tx() as c:
        sc = db.srs_cards.c
        cur = c.execute(select(sc.due_at, sc.suspended).where(sc.id == body.card_id, sc.user_id == u["id"])).first()
        if cur is None:
            return err("Card not found.", 404)
        if cur.due_at > now + 60 or cur.suspended:
            return err("This card isn't due yet.", 409)  # blocks double-submits / XP farming
        r = srs.review(c, u["id"], body.card_id, body.rating, mastery_cfg(u), now)
        xp = gamify.award(c, u["id"], "review", f"review:{r['review_id']}", 1, u["timezone"])
        if r["mastered_now"]:
            gamify.log(c, u["id"], "mastery", f"Mastered {r['item']} ({cards.TRACK_LABELS.get(r['track'], r['track'])})")
        tail = finish_up(c, u)
    return ok(xp=xp, review_id=r["review_id"], state=r["state"], interval_days=r["interval_days"], due_at=r["due_at"],
              mastered_now=r["mastered_now"], **tail)


class UndoIn(BaseModel):
    review_id: int


@router.post("/review/undo", dependencies=W)
def review_undo(body: UndoIn, u=Depends(require_user)):
    with db.tx() as c:
        r = srs.undo(c, u["id"], body.review_id)
        if r is None:
            return err("Only your most recent review can be undone.", 409)
        tail = finish_up(c, u)
    return ok(**r, **tail)


class CardIdsIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)


def _own_ids(c, uid, ids):
    sc = db.srs_cards.c
    return list(c.execute(select(sc.id).where(sc.user_id == uid, sc.id.in_(ids))).scalars())


@router.post("/cards/{action}", dependencies=W)
def card_action(action: str, body: CardIdsIn, deck_id: int = 0, u=Depends(require_user)):
    """Anki card actions: suspend, unsuspend, bury, forget (reset to new), move (to deck_id), delete."""
    now = int(time.time())
    sc = db.srs_cards.c
    with db.tx() as c:
        ids = _own_ids(c, u["id"], body.ids)
        if not ids:
            return err("No such cards.", 404)
        q = update(db.srs_cards).where(sc.id.in_(ids))
        if action == "suspend":
            c.execute(q.values(suspended=1))
        elif action == "unsuspend":
            c.execute(q.values(suspended=0))
        elif action == "bury":
            c.execute(q.values(buried_until=srs.next_day_start(u["timezone"], now)))
        elif action == "unbury":
            c.execute(q.values(buried_until=0))
        elif action == "forget":
            c.execute(q.values(ease=2.5, interval_days=0, reps=0, lapses=0, total_reviews=0, total_correct=0, state="new",
                               due_at=now, last_review_at=None, introduced_at=None))
        elif action == "move":
            if not c.execute(select(db.decks.c.id).where(db.decks.c.id == deck_id, db.decks.c.user_id == u["id"])).first():
                return err("Pick a deck to move to.", 400)
            c.execute(q.values(deck_id=deck_id))
        elif action == "delete":
            c.execute(delete(db.reviews).where(db.reviews.c.card_id.in_(ids)))
            c.execute(delete(db.srs_cards).where(sc.id.in_(ids)))
        else:
            return err("Unknown action.", 404)
    return ok(count=len(ids))


# -------------------------------------------------------------------- notes
class NoteIn(BaseModel):
    track: str = Field(max_length=16)
    item: str = Field(max_length=64)
    meaning: str = Field("", max_length=300)
    mnemonic: str = Field("", max_length=2000)
    notes: str = Field("", max_length=5000)


@router.post("/notes", dependencies=W)
def save_note(body: NoteIn, u=Depends(require_user)):
    if body.track not in cards.TRACK_LABELS:
        return err("Unknown item.")
    if body.track in content.TRACKS and not content.valid_item(body.track, body.item):
        return err("Unknown item.")
    vals = {"meaning": body.meaning.strip(), "mnemonic": body.mnemonic.strip(), "notes": body.notes.strip(), "updated_at": int(time.time())}
    with db.tx() as c:
        if not any(vals[k] for k in ("meaning", "mnemonic", "notes")):
            c.execute(delete(db.notes).where(db.notes.c.user_id == u["id"], db.notes.c.track == body.track, db.notes.c.item == body.item))
        else:
            c.execute(sqlite_insert(db.notes).values(user_id=u["id"], track=body.track, item=body.item, **vals)
                      .on_conflict_do_update(index_elements=["user_id", "track", "item"], set_=vals))
    return ok(**vals)


# -------------------------------------------------------------------- decks
class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    new_per_day: int = Field(10, ge=0, le=9999)
    max_reviews: int = Field(200, ge=0, le=9999)


@router.post("/decks", dependencies=W)
def deck_create(body: DeckIn, u=Depends(require_user)):
    with db.tx() as c:
        if c.execute(select(db.decks.c.id).where(db.decks.c.user_id == u["id"], db.decks.c.name == body.name.strip())).first():
            return err("You already have a deck with that name.", 409)
        did = c.execute(db.decks.insert().values(user_id=u["id"], name=body.name.strip(), new_per_day=body.new_per_day,
                                                 max_reviews=body.max_reviews, created_at=int(time.time()))).inserted_primary_key[0]
    return ok(id=did)


def _own_deck(c, uid, did):
    return c.execute(select(db.decks).where(db.decks.c.id == did, db.decks.c.user_id == uid)).first()


@router.post("/decks/{did}", dependencies=W)
def deck_update(did: int, body: DeckIn, u=Depends(require_user)):
    with db.tx() as c:
        if not _own_deck(c, u["id"], did):
            return err("Deck not found.", 404)
        if c.execute(select(db.decks.c.id).where(db.decks.c.user_id == u["id"], db.decks.c.name == body.name.strip(), db.decks.c.id != did)).first():
            return err("You already have a deck with that name.", 409)
        c.execute(update(db.decks).where(db.decks.c.id == did).values(name=body.name.strip(), new_per_day=body.new_per_day,
                                                                       max_reviews=body.max_reviews))
    return ok()


@router.post("/decks/{did}/delete", dependencies=W)
def deck_delete(did: int, u=Depends(require_user)):
    with db.tx() as c:
        if not _own_deck(c, u["id"], did):
            return err("Deck not found.", 404)
        sc = db.srs_cards.c
        ids = list(c.execute(select(sc.id).where(sc.deck_id == did)).scalars())
        customs = [int(i) for i in c.execute(select(sc.item).where(sc.deck_id == did, sc.track == "card")).scalars()]
        if ids:
            c.execute(delete(db.reviews).where(db.reviews.c.card_id.in_(ids)))
        if customs:
            c.execute(delete(db.custom_cards).where(db.custom_cards.c.id.in_(customs), db.custom_cards.c.user_id == u["id"]))
        # note types and media of an imported deck go with it (ON DELETE CASCADE)
        c.execute(delete(db.srs_cards).where(sc.deck_id == did))
        c.execute(delete(db.decks).where(db.decks.c.id == did))
    return ok(cards_deleted=len(ids))


class AddKanjiIn(BaseModel):
    chars: list[str] = Field(default_factory=list, max_length=2136)
    grade: int = 0


@router.post("/decks/{did}/kanji", dependencies=W)
def deck_add_kanji(did: int, body: AddKanjiIn, u=Depends(require_user)):
    """Add kanji to a deck as new cards (by list, or a whole school grade). Kanji already in another deck stay there."""
    if body.grade:
        chars = [k["char"] for k in content.kanji_list() if k["grade"] == body.grade]
    else:
        chars = [ch for ch in body.chars if content.kanji_get(ch)]
    if not chars:
        return err("No kanji to add.")
    now = int(time.time())
    with db.tx() as c:
        if not _own_deck(c, u["id"], did):
            return err("Deck not found.", 404)
        added = sum(srs.add_card(c, u["id"], "kanji", ch, now, deck_id=did, position=content.kanji_get(ch)["idx"]) for ch in chars)
        if added:
            gamify.log(c, u["id"], "kanji", f"Added {added} kanji to a deck")
        tail = finish_up(c, u)
    return ok(added=added, skipped=len(chars) - added, **tail)


# -------------------------------------------------------------------- kanji
@router.post("/kanji/{ch}/study", dependencies=W)
def kanji_study(ch: str, deck: int = 0, u=Depends(require_user)):
    k = content.kanji_get(ch)
    if not k:
        return err("Not a Jōyō kanji.", 404)
    with db.tx() as c:
        did = deck if deck and _own_deck(c, u["id"], deck) else srs.get_or_create_deck(c, u["id"])
        added = srs.add_card(c, u["id"], "kanji", ch, deck_id=did, position=k["idx"])
        xp = gamify.award(c, u["id"], "study", f"study:kanji:{ch}", 1, u["timezone"]) if added else 0
        if added:
            gamify.log(c, u["id"], "kanji", f"Started kanji {ch}")
        tail = finish_up(c, u)
    return ok(added=added, xp=xp, **tail)


@router.get("/kanji/search")
def kanji_search(q: str = "", grade: int = 0, strokes: int = 0, radical: int = 0, status: str = "", jlpt: int = 0,
                 sort: str = "grade", page: int = 1, per: int = 60, all: int = 0, u=Depends(require_user)):
    t0 = time.perf_counter()
    per = max(12, min(per, 120))
    page = max(1, page)
    k = db.kanji.c
    cond = []
    q = q.strip()[:40]
    relevance = None
    if q:
        ql = q.lower()
        like = f"%{ql}%"
        cjk = [ch for ch in q if 0x3400 <= ord(ch) <= 0x9FFF]
        if len(cjk) > 1:  # a word like 学校: show each of its kanji (in order), plus kanji whose words contain it
            cond.append(or_(k.char.in_(cjk), k.char.in_(select(db.kanji_vocab.c.kanji).where(db.kanji_vocab.c.word.like(f"%{q}%")))))
            relevance = case(*[(k.char == ch, i) for i, ch in enumerate(cjk)], else_=len(cjk))
        elif len(q) == 1 and ord(q) > 0x3400:
            cond.append(or_(k.char == q, k.char.in_(select(db.kanji_vocab.c.kanji).where(db.kanji_vocab.c.word.like(f"%{q}%")))))
        else:
            kata = to_katakana(ql)
            hira = to_hiragana(ql)
            cond.append(or_(k.search_blob.like(like), k.search_blob.like(f"%{kata}%"), k.search_blob.like(f"%{hira}%"),
                            k.char.in_(select(db.kanji_vocab.c.kanji).where(or_(db.kanji_vocab.c.word == q, db.kanji_vocab.c.reading == hira)))))
            # Relevance: exact meaning first, then word-start matches, then everything else.
            relevance = case((func.lower(k.meanings) == ql, 0), (func.lower(k.meanings).like(f"{ql};%"), 0),
                             (k.search_blob.like(f"% {ql}%"), 1), else_=2)
    if grade in (1, 2, 3, 4, 5, 6, 8):
        cond.append(k.grade == grade)
    if 1 <= strokes <= 40:
        cond.append(k.strokes == strokes)
    if 1 <= radical <= 214:
        cond.append(k.radical_num == radical)
    if 1 <= jlpt <= 4:
        cond.append(k.jlpt_old == jlpt)
    sc = db.srs_cards.c
    mine = select(sc.item).where(sc.user_id == u["id"], sc.track == "kanji")
    if status == "new":
        cond.append(k.char.not_in(mine))
    elif status == "learning":
        cond.append(k.char.in_(mine.where(sc.state != "mastered")))
    elif status == "mastered":
        cond.append(k.char.in_(mine.where(sc.state == "mastered")))
    where = and_(*cond) if cond else True
    order = {"grade": [k.idx], "strokes": [k.strokes, k.idx], "freq": [func.coalesce(k.freq, 99999), k.idx]}.get(sort, [k.idx])
    if relevance is not None:
        order = [relevance, *order]
    if all:  # just the characters, for "add these results to a deck"
        with db.ro() as c:
            return ok(chars=list(c.execute(select(k.char).where(where).order_by(*order)).scalars()))
    with db.ro() as c:
        total = c.execute(select(func.count()).select_from(db.kanji).where(where)).scalar()
        rows = c.execute(select(k.char, k.grade, k.strokes, k.meanings, k.onyomi, k.kunyomi, k.jlpt_old)
                         .where(where).order_by(*order).limit(per).offset((page - 1) * per)).all()
        chars = [r.char for r in rows]
        states = {r.item: r.state for r in c.execute(select(sc.item, sc.state).where(sc.user_id == u["id"], sc.track == "kanji", sc.item.in_(chars)))} if chars else {}
    items = [{"char": r.char, "grade": r.grade, "strokes": r.strokes, "meaning": r.meanings.split("; ")[0],
              "on": r.onyomi.split("、")[0], "kun": r.kunyomi.split("、")[0].replace(".", ""), "jlpt": r.jlpt_old,
              "state": states.get(r.char)} for r in rows]
    return ok(items=items, total=total, page=page, pages=max(1, -(-total // per)), ms=round((time.perf_counter() - t0) * 1000, 2))


# -------------------------------------------------------------------- quiz
class QuizStart(BaseModel):
    kind: str
    mode: str = "practice"
    grade: int = 0
    pool: str = "learned"  # learned | all


MODES = {"practice": (10, None), "mastery": (20, None), "sprint60": (90, 60), "sprint120": (160, 120), "burst": (8, None)}


@router.post("/quiz/start", dependencies=W)
def quiz_start(body: QuizStart, u=Depends(require_user)):
    if body.kind not in quiz.KINDS and body.kind != "due":
        return err("Unknown quiz type.")
    if body.mode not in MODES:
        return err("Unknown quiz mode.")
    n, secs = MODES[body.mode]
    now = int(time.time())
    with db.ro() as c:
        lessons = set(c.execute(select(db.lesson_completions.c.lesson).where(db.lesson_completions.c.user_id == u["id"])).scalars())
        sc = db.srs_cards.c
        cards_ = c.execute(select(sc.track, sc.item, sc.due_at).where(sc.user_id == u["id"])).all()
        due_items = [(r["track"], r["item"]) for r in srs.queue(c, u["id"], u["timezone"], now, limit=200)]
    started_kanji = {r.item for r in cards_ if r.track == "kanji"}
    started_vocab = {(r.track, r.item) for r in cards_ if r.track in ("hvocab", "kvocab")}
    use_all = body.pool == "all"
    try:
        qs = quiz.build(body.kind, n, lessons=None if use_all or not lessons else lessons, grade=body.grade or None,
                        started_kanji=None if use_all else started_kanji, started_vocab=started_vocab | ({("hvocab", v["word"]) for v in content.vocab_list("hiragana")} if use_all else set()),
                        due_items=due_items, rng=random.Random(secrets.randbits(64)))
    except quiz.NotEnough:
        hint = {"due": "Nothing is due for review right now — nice!", "mixed": "Start a lesson or add some kanji first, or choose “All content”."}
        return err(hint.get(body.kind, "Not enough material yet. Try “All content”, or finish a lesson first."), 409)
    title = quiz.KINDS.get(body.kind, ("Due review", ""))[0]
    if body.grade and body.kind.startswith("kanji"):
        title += f" · {content.GRADE_LABELS.get(body.grade, '')}"
    label = {"mastery": "Mastery test", "sprint60": "60-second sprint", "sprint120": "120-second challenge"}.get(body.mode)
    if label:
        title = f"{label}: {title}"
    qid = secrets.token_hex(12)
    with db.tx() as c:
        c.execute(db.quiz_attempts.insert().values(
            id=qid, user_id=u["id"], kind=body.kind, title=title, mode=body.mode, questions_json=json.dumps(qs, ensure_ascii=False),
            total=len(qs), started_at=now, deadline_at=(now + secs) if secs else None))
    return ok(id=qid, url=f"/quiz/{qid}")


class AnswerIn(BaseModel):
    idx: int = Field(ge=0)
    choice: int = Field(ge=-1, le=10)


def _load_attempt(c, uid, qid):
    return c.execute(select(db.quiz_attempts).where(db.quiz_attempts.c.id == qid, db.quiz_attempts.c.user_id == uid)).first()


@router.post("/quiz/{qid}/answer", dependencies=W)
def quiz_answer(qid: str, body: AnswerIn, u=Depends(require_user)):
    now = time.time()
    with db.tx() as c:
        a = _load_attempt(c, u["id"], qid)
        if a is None:
            return err("Quiz not found.", 404)
        if a.finished_at:
            return err("This quiz is already finished.", 409)
        if a.deadline_at and now > a.deadline_at + GRACE:
            return ok(expired=True)
        answered = c.execute(select(func.count()).where(db.quiz_details.c.attempt_id == qid)).scalar()
        if body.idx != answered or body.idx >= a.total:
            return err("Answer questions in order, one at a time.", 409)
        q = json.loads(a.questions_json)[body.idx]
        correct = body.choice == q["answer"]
        c.execute(db.quiz_details.insert().values(attempt_id=qid, idx=body.idx, answer=str(body.choice), correct=int(correct), answered_at=int(now)))
        srs.record_progress(c, u["id"], q["track"], q["item"], correct, int(now))
    return ok(correct=correct, answer=q["answer"], explain=q["explain"], expired=False)


class SubmitIn(BaseModel):
    id: str = Field(max_length=32)


def finish_quiz(c, u, qid: str) -> dict | None:
    a = _load_attempt(c, u["id"], qid)
    if a is None:
        return None
    if a.finished_at:  # idempotent: never re-award
        return {"score": a.score, "total": a.total, "passed": bool(a.passed), "xp": 0, "already": True}
    answered = c.execute(select(func.count(), func.coalesce(func.sum(db.quiz_details.c.correct), 0)).where(db.quiz_details.c.attempt_id == qid)).one()
    n_answered, score = answered[0], answered[1]
    total = a.total
    if a.mode.startswith("sprint"):
        # Questions are dealt one at a time; the one on screen when time ran out counts as wrong.
        total = min(a.total, n_answered + 1) if n_answered < a.total else a.total
    passed = int(a.mode == "mastery" and total > 0 and score / total >= 0.8)
    now = int(time.time())
    res = c.execute(update(db.quiz_attempts).where(db.quiz_attempts.c.id == qid, db.quiz_attempts.c.finished_at.is_(None))
                    .values(finished_at=now, score=score, total=total, passed=passed))
    if res.rowcount != 1:
        return {"score": score, "total": total, "passed": bool(passed), "xp": 0, "already": True}
    xp = gamify.award(c, u["id"], "quiz", f"quiz:{qid}", min(score, 30), u["timezone"])
    if passed:
        scope = a.title
        xp += gamify.award(c, u["id"], "mastery", f"mastery:{scope}", 25, u["timezone"])
    pct = round(100 * score / total) if total else 0
    gamify.log(c, u["id"], "quiz", f"{a.title}: {score}/{total} ({pct}%)" + (" · passed ✓" if passed else ""))
    c.execute(update(db.quiz_attempts).where(db.quiz_attempts.c.id == qid).values(xp_awarded=xp))
    return {"score": score, "total": total, "passed": bool(passed), "xp": xp, "already": False}


@router.post("/quiz/submit", dependencies=W)
def quiz_submit(body: SubmitIn, u=Depends(require_user)):
    with db.tx() as c:
        r = finish_quiz(c, u, body.id)
        if r is None:
            return err("Quiz not found.", 404)
        tail = finish_up(c, u)
    return ok(url=f"/quiz/{body.id}/results", **r, **tail)


# ------------------------------------------------------------------ writing
class WritingIn(BaseModel):
    track: str
    item: str = Field(max_length=4)


@router.post("/writing/complete", dependencies=W)
def writing_complete(body: WritingIn, u=Depends(require_user)):
    if body.track not in ("hiragana", "katakana", "kanji") or not content.valid_item(body.track, body.item):
        return err("Unknown character.")
    with db.tx() as c:
        day = gamify.local_day(u["timezone"])
        xp = gamify.award(c, u["id"], "writing", f"writing:{body.track}:{body.item}:{day}", 2, u["timezone"])
        tail = finish_up(c, u)
    return ok(xp=xp, **tail)


# -------------------------------------------------------------------- games
class GameStart(BaseModel):
    deck: str


def _deck(deck: str, rng: random.Random, uid: int):
    if deck in ("hiragana", "katakana"):
        chars = [c for c in SCRIPTS[deck]["chars"] if c["kana"] not in NON_SYLLABLE]
        picks = rng.sample(chars, 30)
        out, seen = [], set()
        for c in picks:  # romaji must be unique on a board (ぢ/じ both read "ji")
            if c["romaji"] not in seen:
                seen.add(c["romaji"])
                out.append((c["kana"], c["romaji"]))
        return out[:6]
    if deck == "vocab":
        return [(v["word"], v["meaning"].split("; ")[0]) for v in rng.sample(content.vocab_list(), 6)]
    if deck == "kanji":
        with db.ro() as c:
            started = list(c.execute(select(db.srs_cards.c.item).where(db.srs_cards.c.user_id == uid, db.srs_cards.c.track == "kanji")).scalars())
        pool = [content.kanji_get(x) for x in started] if len(started) >= 6 else content.kanji_list()[:240]
        out, seen = [], set()
        for k in rng.sample(pool, len(pool)):
            m = content.first_meaning(k)
            if m not in seen:
                seen.add(m)
                out.append((k["char"], m))
            if len(out) == 6:
                break
        return out
    return None


@router.post("/game/start", dependencies=W)
def game_start(body: GameStart, u=Depends(require_user)):
    rng = random.Random(secrets.randbits(64))
    pairs = _deck(body.deck, rng, u["id"])
    if not pairs:
        return err("Unknown deck.")
    gid = secrets.token_hex(12)
    cards = [{"pair": i, "text": a, "side": "jp"} for i, (a, _) in enumerate(pairs)] + [{"pair": i, "text": b, "side": "en"} for i, (_, b) in enumerate(pairs)]
    rng.shuffle(cards)
    with db.tx() as c:
        c.execute(db.game_sessions.insert().values(id=gid, user_id=u["id"], deck=body.deck, pairs_json=json.dumps(pairs, ensure_ascii=False), started_at=int(time.time())))
    return ok(id=gid, cards=cards)


class GameDone(BaseModel):
    id: str = Field(max_length=32)
    moves: int = Field(ge=6, le=500)
    misses: int = Field(ge=0, le=500)


@router.post("/game/complete", dependencies=W)
def game_complete(body: GameDone, u=Depends(require_user)):
    now = time.time()
    with db.tx() as c:
        g = c.execute(select(db.game_sessions).where(db.game_sessions.c.id == body.id, db.game_sessions.c.user_id == u["id"])).first()
        if g is None or g.deck == "burst":
            return err("Game not found.", 404)
        if g.finished_at:
            return err("This game is already finished.", 409)
        secs = now - g.started_at
        if secs < 3 or body.moves != 6 + body.misses:
            return err("That result doesn't add up.", 400)
        xp = max(3, 10 - body.misses)
        c.execute(update(db.game_sessions).where(db.game_sessions.c.id == body.id).values(
            finished_at=int(now), moves=body.moves, misses=body.misses, seconds=round(secs, 1)))
        xp = gamify.award(c, u["id"], "game", f"game:{body.id}", xp, u["timezone"])
        c.execute(update(db.game_sessions).where(db.game_sessions.c.id == body.id).values(xp_awarded=xp))
        gamify.log(c, u["id"], "game", f"Matching ({g.deck}): {body.moves} moves, {body.misses} misses, {secs:.0f}s")
        tail = finish_up(c, u)
    return ok(xp=xp, seconds=round(secs, 1), **tail)


# -------------------------------------------------------------- focus burst
@router.post("/burst/start", dependencies=W)
def burst_start(u=Depends(require_user)):
    bid = secrets.token_hex(12)
    with db.tx() as c:
        c.execute(db.game_sessions.insert().values(id=bid, user_id=u["id"], deck="burst", pairs_json="[]", started_at=int(time.time())))
    return ok(id=bid, minutes=u["burst_minutes"])


class BurstDone(BaseModel):
    id: str = Field(max_length=32)


@router.post("/burst/complete", dependencies=W)
def burst_complete(body: BurstDone, u=Depends(require_user)):
    now = int(time.time())
    with db.tx() as c:
        g = c.execute(select(db.game_sessions).where(db.game_sessions.c.id == body.id, db.game_sessions.c.user_id == u["id"],
                                                     db.game_sessions.c.deck == "burst")).first()
        if g is None:
            return err("Burst not found.", 404)
        if g.finished_at:
            return err("Already finished.", 409)
        done = c.execute(select(func.count()).where(db.reviews.c.user_id == u["id"], db.reviews.c.created_at >= g.started_at)).scalar()
        done += c.execute(select(func.count()).select_from(db.quiz_details.join(db.quiz_attempts, db.quiz_attempts.c.id == db.quiz_details.c.attempt_id))
                          .where(db.quiz_attempts.c.user_id == u["id"], db.quiz_details.c.answered_at >= g.started_at)).scalar()
        if done < 3:
            return ok(counted=False, items=done, xp=0, message="Do at least 3 cards or questions to count a burst.")
        c.execute(update(db.game_sessions).where(db.game_sessions.c.id == body.id).values(finished_at=now, moves=done, seconds=now - g.started_at))
        xp = gamify.award(c, u["id"], "burst", f"burst:{body.id}", 5, u["timezone"])
        gamify.log(c, u["id"], "burst", f"Focus burst: {done} items in {round((now - g.started_at) / 60, 1)} min 🎆")
        tail = finish_up(c, u)
    return ok(counted=True, items=done, xp=xp, **tail)


class CardIn(BaseModel):
    front: str = Field(min_length=1, max_length=2000)
    back: str = Field(min_length=1, max_length=5000)
    extra: str = Field("", max_length=5000)


@router.post("/decks/{did}/cards", dependencies=W)
def deck_new_card(did: int, body: CardIn, u=Depends(require_user)):
    """Write your own card (like Anki's Add)."""
    now = int(time.time())
    with db.tx() as c:
        if not _own_deck(c, u["id"], did):
            return err("Deck not found.", 404)
        cid = c.execute(db.custom_cards.insert().values(user_id=u["id"], front=body.front.strip(), back=body.back.strip(),
                                                        extra=body.extra.strip(), source="manual", created_at=now)).inserted_primary_key[0]
        pos = (c.execute(select(func.max(db.srs_cards.c.position)).where(db.srs_cards.c.deck_id == did)).scalar() or 0) + 1
        srs.add_card(c, u["id"], "card", str(cid), now, deck_id=did, position=pos)
    return ok(id=cid)


# ------------------------------------------------------------- card browser
@router.get("/cards")
def browse_cards(q: str = "", deck: int = 0, state: str = "", track: str = "", sort: str = "due", desc: int = 0,
                 page: int = 1, per: int = 50, u=Depends(require_user)):
    t0 = time.perf_counter()
    now = int(time.time())
    per = max(10, min(per, 200))
    sc = db.srs_cards.c
    cond = [sc.user_id == u["id"]]
    if deck:
        cond.append(sc.deck_id == deck)
    if track in cards.TRACK_LABELS:
        cond.append(sc.track == track)
    if state == "suspended":
        cond.append(sc.suspended == 1)
    elif state == "buried":
        cond.append(sc.buried_until > now)
    elif state == "new":
        cond.append(sc.total_reviews == 0)
    elif state == "due":
        cond += [sc.due_at <= now, sc.total_reviews > 0, sc.suspended == 0]
    elif state in ("learning", "review", "mastered"):
        cond += [sc.state == state, sc.total_reviews > 0]
    with db.ro() as c:
        rows = [dict(r._mapping) for r in c.execute(select(db.srs_cards).where(*cond))]
        views = {v["id"]: v for v in cards.build(c, u, rows, now)}
    ql = q.strip().lower()
    items = []
    for r in rows:
        v = views.get(r["id"])
        if v is None:
            continue
        text = f"{v['front']} {v['answer']} {v.get('reading', '')} {v.get('my_mnemonic', '')} {v.get('my_notes', '')}".lower()
        if ql and ql not in text:
            continue
        items.append({"id": r["id"], "track": r["track"], "item": r["item"], "front": v["front"], "answer": v["answer"][:120],
                      "deck": v["deck"], "deck_id": r["deck_id"], "state": "suspended" if r["suspended"] else
                      ("buried" if r["buried_until"] > now else ("new" if r["total_reviews"] == 0 else r["state"])),
                      "due_at": r["due_at"], "interval": srs.fmt_interval(r["interval_days"]) if r["total_reviews"] else "—",
                      "interval_days": r["interval_days"], "ease": round(r["ease"] * 100), "lapses": r["lapses"],
                      "reviews": r["total_reviews"], "position": r["position"], "has_note": bool(v["my_mnemonic"] or v["my_notes"] or v["my_meaning"])})
    key = {"due": lambda x: (x["state"] == "new", x["due_at"]), "front": lambda x: x["front"], "interval": lambda x: x["interval_days"],
           "ease": lambda x: x["ease"], "lapses": lambda x: x["lapses"], "reviews": lambda x: x["reviews"],
           "order": lambda x: (x["deck"] or "", x["position"])}.get(sort, lambda x: x["due_at"])
    items.sort(key=key, reverse=bool(desc))
    total = len(items)
    page = max(1, min(page, max(1, -(-total // per))))
    return ok(items=items[(page - 1) * per: page * per], total=total, page=page, pages=max(1, -(-total // per)),
              ms=round((time.perf_counter() - t0) * 1000, 1))


# ------------------------------------------------------------ Anki packages
def _kanji_note(ch: str, note=None) -> dict:
    from html import escape as e
    k = content.kanji_get(ch)
    words = "<br>".join(f"{e(v['word'])} ({e(v['reading'])}) — {e(v['meaning'].split('; ')[0])}" for v in content.kanji_vocab(ch)[:4])
    sent = content.kanji_sentences(ch)
    example = f"{e(sent[0]['jp'])}<br><small>{e(sent[0]['en'])}</small>" if sent else ""
    meaning = e(note.meaning) if note and note.meaning else e(k["meanings"].replace("; ", ", "))
    return {"kind": "kanji", "key": f"kanji:{ch}", "tags": f"shuinkan kanji grade{k['grade']}",
            "fields": [ch, meaning, e(k["onyomi"]), e(k["kunyomi"]), str(k["strokes"]), e(content.GRADE_LABELS[k["grade"]]),
                       words, example, e(note.mnemonic) if note else "", e(note.notes).replace("\n", "<br>") if note else "",
                       f"Jōyō #{k['idx']}"]}


def _apkg_response(data: bytes, name: str):
    from urllib.parse import quote
    safe = re.sub(r"[^\w\- ]+", "", name).strip() or "deck"
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename=\"{safe}.apkg\"; filename*=UTF-8''{quote(name)}.apkg",
        "Cache-Control": "no-store"})


@router.get("/decks/all-kanji/export.apkg")
def export_all_kanji(u=Depends(require_user)):
    with db.ro() as c:
        notes = {r.item: r for r in c.execute(select(db.notes).where(db.notes.c.user_id == u["id"], db.notes.c.track == "kanji"))}
    data = apkg.build_apkg("Shuinkan::Jōyō kanji", [_kanji_note(k["char"], notes.get(k["char"])) for k in content.kanji_list()])
    return _apkg_response(data, "Shuinkan Joyo kanji")


@router.get("/decks/{did}/export.apkg")
def export_deck(did: int, u=Depends(require_user)):
    from html import escape as e
    with db.ro() as c:
        d = _own_deck(c, u["id"], did)
        if not d:
            return err("Deck not found.", 404)
        sc = db.srs_cards.c
        rows = [dict(r._mapping) for r in c.execute(select(db.srs_cards).where(sc.deck_id == did).order_by(sc.position, sc.id))]
        notes = {(r.track, r.item): r for r in c.execute(select(db.notes).where(db.notes.c.user_id == u["id"]))}
        views = {v["id"]: v for v in cards.build(c, u, rows)}
    out = []
    for r in rows:
        if r["track"] == "kanji":
            out.append(_kanji_note(r["item"], notes.get(("kanji", r["item"]))))
        elif r["id"] in views:
            v = views[r["id"]]
            extra = "\n".join(x for x in (v.get("reading"), v.get("extra"), v.get("my_mnemonic"), v.get("my_notes")) if x)
            out.append({"kind": "basic", "key": f"{r['track']}:{r['item']}", "tags": "shuinkan",
                        "fields": [e(v["front"]), e(v["answer"]).replace("\n", "<br>"), e(extra).replace("\n", "<br>")]})
    if not out:
        return err("This deck has no cards to export yet.", 409)
    return _apkg_response(apkg.build_apkg(f"Shuinkan::{d.name}", out), d.name)


@router.post("/import/apkg", dependencies=W)
async def import_apkg(request: Request, u=Depends(require_user)):
    """Import an Anki package with its note types (templates + styling), images, fonts and audio."""
    from starlette.concurrency import run_in_threadpool
    if not limiter.allow(f"import:{u['id']}", 10, 3600):
        return err("Too many imports in a short time. Try again later.", 429)
    form = await request.form(max_part_size=1024 * 1024)
    f = form.get("file")
    if f is None or not hasattr(f, "file"):
        return err("Choose an .apkg file first.")
    try:
        return await run_in_threadpool(_import_package, u, f.file, getattr(f, "filename", "") or "")
    except apkg.ImportError_ as ex:
        return err(str(ex))


def _import_package(u, fileobj, filename: str):
    from . import anki_render as ar
    pkg = apkg.parse_package(fileobj)  # streams from the spooled temp file on disk
    if not pkg["cards"]:
        raise apkg.ImportError_("No cards were found in that file.")
    now = int(time.time())
    base = (pkg["deck"] or filename or "Imported").replace("::", " › ")
    base = re.sub(r"\.(apkg|colpkg)$", "", base)[:70] or "Imported"
    with db.tx() as c:
        taken = set(c.execute(select(db.decks.c.name).where(db.decks.c.user_id == u["id"])).scalars())
        deck_name = apkg.free_name(base, taken)
        did = c.execute(db.decks.insert().values(user_id=u["id"], name=deck_name, created_at=now)).inserted_primary_key[0]
        model_ids = {}
        for mid, m in pkg["models"].items():
            if not m["tmpls"]:
                continue
            model_ids[mid] = c.execute(db.anki_models.insert().values(
                user_id=u["id"], deck_id=did, name=m["name"][:200], kind=int(m["kind"]), css=m["css"],
                tmpls_json=json.dumps(m["tmpls"], ensure_ascii=False), flds_json=json.dumps(m["flds"], ensure_ascii=False))).inserted_primary_key[0]
        media = images = audio = 0
        for name, mime, data in apkg.iter_media(pkg["zip"]):
            c.execute(sqlite_insert(db.anki_media).values(user_id=u["id"], deck_id=did, name=name[:400], mime=mime, data=data)
                      .on_conflict_do_nothing(index_elements=["deck_id", "name"]))
            media += 1
            images += mime.startswith("image/")
            audio += mime.startswith("audio/")
        src = (filename or "apkg")[:120]
        added = skipped = 0
        for card in pkg["cards"]:
            m = pkg["models"][card["mid"]]
            if card["mid"] not in model_ids:
                skipped += 1
                continue
            r = ar.render_card(m, card["fields"], card["ord"], deck_id=did, deck=pkg["deck"] or "", tags=card["tags"])
            if not r["front_text"] and "<img" not in r["front"] and "<audio" not in r["front"]:
                skipped += 1  # Anki doesn't show empty cards either
                continue
            cid = c.execute(db.custom_cards.insert().values(
                user_id=u["id"], front=(r["front_text"] or "🖼")[:2000], back=(r["back_text"] or "")[:5000], extra="", source=src,
                created_at=now, model_id=model_ids[card["mid"]], fields_json=json.dumps(card["fields"], ensure_ascii=False),
                ord=card["ord"], tags=card["tags"][:500])).inserted_primary_key[0]
            added += 1
            c.execute(db.srs_cards.insert().values(user_id=u["id"], track="card", item=str(cid), due_at=now, created_at=now,
                                                   state="new", deck_id=did, position=added))
        if not added:
            raise apkg.ImportError_("No cards with content were found in that file.")
        gamify.log(c, u["id"], "import", f"Imported {added} cards from Anki into “{deck_name}”")
    return ok(deck=deck_name, deck_id=did, cards=added, skipped=skipped, media=media, images=images, audio=audio)


# --------------------------------------------------------------- dictionary
@router.get("/dictionary/search")
def dict_search(q: str = "", limit: int = 30, u=Depends(require_user)):
    from . import dictionary as dic
    t0 = time.perf_counter()
    with db.ro() as c:
        res, total = dic.search(c, q, max(1, min(limit, 100)))
        mine = dic.search_user(c, u["id"], q)
    return ok(results=res, total=total, mine=mine, ms=round((time.perf_counter() - t0) * 1000, 1))


@router.post("/dictionary/{eid}/add", dependencies=W)
def dict_add(eid: int, deck: int = 0, u=Depends(require_user)):
    with db.tx() as c:
        if not c.execute(select(db.dict_entries.c.id).where(db.dict_entries.c.id == eid)).first():
            return err("Word not found.", 404)
        did = deck if deck and _own_deck(c, u["id"], deck) else srs.get_or_create_deck(c, u["id"], "My words")
        pos = (c.execute(select(func.max(db.srs_cards.c.position)).where(db.srs_cards.c.deck_id == did)).scalar() or 0) + 1
        added = srs.add_card(c, u["id"], "dict", str(eid), deck_id=did, position=pos)
        name = c.execute(select(db.decks.c.name).where(db.decks.c.id == did)).scalar()
    return ok(added=added, deck=name)


@router.post("/dictionaries/import", dependencies=W)
async def dict_import(request: Request, u=Depends(require_user)):
    from . import dictionary as dic
    if not limiter.allow(f"dictimport:{u['id']}", 10, 3600):
        return err("Too many imports in a short time. Try again later.", 429)
    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "read"):
        return err("Choose a dictionary file first.")
    data = await f.read(dic.MAX_DICT_UPLOAD + 1)
    try:
        with db.tx() as c:
            r = dic.import_dictionary(c, u["id"], data, getattr(f, "filename", "") or "")
    except dic.DictImportError as ex:
        return err(str(ex))
    return ok(**r)


@router.post("/dictionaries/{did}/{action}", dependencies=W)
def dict_manage(did: int, action: str, u=Depends(require_user)):
    ud = db.user_dicts.c
    with db.tx() as c:
        if not c.execute(select(ud.id).where(ud.id == did, ud.user_id == u["id"])).first():
            return err("Dictionary not found.", 404)
        if action == "delete":
            c.execute(delete(db.user_dict_entries).where(db.user_dict_entries.c.dict_id == did))
            c.execute(delete(db.user_dicts).where(ud.id == did))
        elif action in ("enable", "disable"):
            c.execute(update(db.user_dicts).where(ud.id == did).values(enabled=int(action == "enable")))
        else:
            return err("Unknown action.", 404)
    return ok()
