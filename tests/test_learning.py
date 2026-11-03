import json
import time

from sqlalchemy import func, select, update

from app import db, gamify, srs
from app.quiz import KINDS


def uid_of(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.id).where(db.users.c.username == user.name)).scalar()


def xp_of(user):
    with db.ro() as c:
        return c.execute(select(db.users.c.xp).where(db.users.c.username == user.name)).scalar()


def test_lesson_complete_once(user):
    r = user.post("/api/lesson/complete", {"lesson": "hiragana-1"}).json()
    assert r["first"] and r["xp"] == 10 and r["cards_added"] == 5
    assert any(a["code"] == "first_lesson" for a in r["achievements"])
    r2 = user.post("/api/lesson/complete", {"lesson": "hiragana-1"}).json()
    assert not r2["first"] and r2["xp"] == 0 and r2["cards_added"] == 0 and r2["achievements"] == []
    assert user.post("/api/lesson/complete", {"lesson": "hiragana-27"}).status_code == 404
    assert user.post("/api/lesson/complete", {"lesson": "katakana-32"}).status_code == 200
    assert user.post("/api/lesson/complete", {"lesson": "nope-1"}).status_code == 404


def test_srs_scheduling_pure():
    cfg = {"mastery_reps": 3, "mastery_accuracy": 80, "mastery_interval": 5}
    card = {"ease": 2.5, "interval_days": 0, "reps": 0, "lapses": 0, "total_reviews": 0, "total_correct": 0, "state": "new"}
    now = 1_000_000
    a = srs.next_state(card, srs.AGAIN, cfg, now)
    assert a["state"] == "learning" and a["due_at"] - now == 600 and a["reps"] == 0
    g = srs.next_state(card, srs.GOOD, cfg, now)
    assert g["interval_days"] == 1 and g["state"] == "review"
    e = srs.next_state(card, srs.EASY, cfg, now)
    assert e["interval_days"] == 4 and e["ease"] > 2.5
    h = srs.next_state(card, srs.HARD, cfg, now)
    assert h["interval_days"] == 0.5 and h["ease"] < 2.5
    # chain of goods reaches mastery only when all three thresholds are met
    c = dict(card)
    states = []
    for _ in range(4):
        c = {**c, **srs.next_state(c, srs.GOOD, cfg, now)}
        states.append((c["state"], c["interval_days"], c["reps"]))
    assert states[0][0] == "review"
    assert c["state"] == "mastered" and c["interval_days"] >= 5 and c["reps"] >= 3
    lapse = srs.next_state(c, srs.AGAIN, cfg, now)
    assert lapse["state"] == "learning" and lapse["lapses"] == 1 and lapse["reps"] == 0
    assert srs.next_state({**c, "interval_days": 300}, srs.EASY, cfg, now)["interval_days"] <= 365


def test_review_flow_and_no_double_xp(user):
    user.post("/api/lesson/complete", {"lesson": "hiragana-2"})
    q = user.c.get("/api/review/queue").json()["cards"]
    assert len(q) == 5 and q[0]["front"] in "かきくけこ"
    before = xp_of(user)
    r = user.post("/api/review/submit", {"card_id": q[0]["id"], "rating": 3}).json()
    assert r["xp"] == 1 and r["state"] == "review" and r["interval_days"] == 1
    # replaying the same review is refused (not due anymore) -> no farming
    again = user.post("/api/review/submit", {"card_id": q[0]["id"], "rating": 3})
    assert again.status_code == 409
    assert xp_of(user) == before + 1 + sum(a["xp"] for a in r["achievements"])
    assert user.post("/api/review/submit", {"card_id": q[1]["id"], "rating": 9}).status_code == 422
    # state survives a new login (server-side)
    with db.ro() as c:
        row = c.execute(select(db.srs_cards).where(db.srs_cards.c.id == q[0]["id"])).one()
    assert row.state == "review" and row.total_reviews == 1 and row.due_at > time.time()


def test_review_page_shows_due_cards(user):
    user.post("/api/lesson/complete", {"lesson": "katakana-1"})
    r = user.c.get("/review")
    assert 'id="review-data"' in r.text and "ア" in r.text
    assert "Nothing due" in user.c.get("/review?track=kanji").text


def test_quiz_server_scoring(user):
    r = user.post("/api/quiz/start", {"kind": "hiragana-recognition", "mode": "practice", "pool": "all"}).json()
    qid = r["id"]
    page = user.c.get(f"/quiz/{qid}").text
    data = json.loads(page.split('id="quiz-data">')[1].split("</script>")[0])
    assert len(data) == 10 and "answer" not in data[0] and "explain" not in data[0]
    with db.ro() as c:
        qs = json.loads(c.execute(select(db.quiz_attempts.c.questions_json).where(db.quiz_attempts.c.id == qid)).scalar())
    # answer 7 right, 1 wrong, leave 2 unanswered
    for i in range(8):
        choice = qs[i]["answer"] if i < 7 else (qs[i]["answer"] + 1) % 4
        a = user.post(f"/api/quiz/{qid}/answer", {"idx": i, "choice": choice}).json()
        assert a["correct"] == (i < 7) and a["answer"] == qs[i]["answer"]
    # out of order / repeat answers rejected
    assert user.post(f"/api/quiz/{qid}/answer", {"idx": 3, "choice": 0}).status_code == 409
    s = user.post("/api/quiz/submit", {"id": qid}).json()
    assert s["score"] == 7 and s["total"] == 10 and s["xp"] == 7 and not s["passed"]
    # double submit gives no extra XP
    s2 = user.post("/api/quiz/submit", {"id": qid}).json()
    assert s2["already"] and s2["xp"] == 0
    assert user.post(f"/api/quiz/{qid}/answer", {"idx": 8, "choice": 0}).status_code == 409
    res = user.c.get(f"/quiz/{qid}/results").text
    assert "7<span" in res and "no answer" in res


def test_mastery_test_pass(user):
    r = user.post("/api/quiz/start", {"kind": "katakana-reading", "mode": "mastery", "pool": "all"}).json()
    with db.ro() as c:
        qs = json.loads(c.execute(select(db.quiz_attempts.c.questions_json).where(db.quiz_attempts.c.id == r["id"])).scalar())
    assert len(qs) == 20
    for i, q in enumerate(qs):
        user.post(f"/api/quiz/{r['id']}/answer", {"idx": i, "choice": q["answer"] if i < 16 else (q["answer"] + 1) % 4})
    s = user.post("/api/quiz/submit", {"id": r["id"]}).json()
    assert s["score"] == 16 and s["passed"] and s["xp"] == 16 + 25  # 80% passes
    # a second pass of the same test doesn't pay the mastery bonus again
    r = user.post("/api/quiz/start", {"kind": "katakana-reading", "mode": "mastery", "pool": "all"}).json()
    with db.ro() as c:
        qs = json.loads(c.execute(select(db.quiz_attempts.c.questions_json).where(db.quiz_attempts.c.id == r["id"])).scalar())
    for i, q in enumerate(qs):
        user.post(f"/api/quiz/{r['id']}/answer", {"idx": i, "choice": q["answer"]})
    s = user.post("/api/quiz/submit", {"id": r["id"]}).json()
    assert s["passed"] and s["xp"] == 20


def test_sprint_unanswered_counts_wrong_and_deadline(user):
    r = user.post("/api/quiz/start", {"kind": "hiragana-recognition", "mode": "sprint60", "pool": "all"}).json()
    qid = r["id"]
    with db.ro() as c:
        qs = json.loads(c.execute(select(db.quiz_attempts.c.questions_json).where(db.quiz_attempts.c.id == qid)).scalar())
    for i in range(5):
        user.post(f"/api/quiz/{qid}/answer", {"idx": i, "choice": qs[i]["answer"]})
    # time runs out
    with db.tx() as c:
        c.execute(update(db.quiz_attempts).where(db.quiz_attempts.c.id == qid).values(deadline_at=int(time.time()) - 10))
    late = user.post(f"/api/quiz/{qid}/answer", {"idx": 5, "choice": qs[5]["answer"]}).json()
    assert late["expired"]
    s = user.post("/api/quiz/submit", {"id": qid}).json()
    assert s["score"] == 5 and s["total"] == 6  # the question on screen counts as wrong


def test_every_quiz_kind_builds(user):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    for kind in KINDS:
        r = user.post("/api/quiz/start", {"kind": kind, "pool": "all"})
        assert r.status_code == 200, (kind, r.text)
    r = user.post("/api/quiz/start", {"kind": "kanji-meaning", "pool": "all", "grade": 1}).json()
    with db.ro() as c:
        qs = json.loads(c.execute(select(db.quiz_attempts.c.questions_json).where(db.quiz_attempts.c.id == r["id"])).scalar())
    from app import content
    assert all(content.kanji_get(q["item"])["grade"] == 1 for q in qs)
    for q in qs:
        assert len(q["options"]) == 4 and len(set(q["options"])) == 4
    assert user.post("/api/quiz/start", {"kind": "bogus"}).status_code == 400
    assert user.post("/api/quiz/start", {"kind": "kanji-meaning", "mode": "bogus"}).status_code == 400


def test_due_quiz(user):
    assert user.post("/api/quiz/start", {"kind": "due"}).status_code == 409
    user.post("/api/lesson/complete", {"lesson": "hiragana-3"})
    assert user.post("/api/quiz/start", {"kind": "due"}).status_code == 200


def test_writing_xp_once_per_day(user):
    r = user.post("/api/writing/complete", {"track": "hiragana", "item": "あ"}).json()
    assert r["xp"] == 2
    assert user.post("/api/writing/complete", {"track": "hiragana", "item": "あ"}).json()["xp"] == 0
    assert user.post("/api/writing/complete", {"track": "kanji", "item": "日"}).json()["xp"] == 2
    assert user.post("/api/writing/complete", {"track": "kanji", "item": "Q"}).status_code == 400


def test_matching_game(user):
    g = user.post("/api/game/start", {"deck": "hiragana"}).json()
    assert len(g["cards"]) == 12 and len({c["pair"] for c in g["cards"]}) == 6
    # too fast -> rejected
    assert user.post("/api/game/complete", {"id": g["id"], "moves": 6, "misses": 0}).status_code == 400
    with db.tx() as c:
        c.execute(update(db.game_sessions).where(db.game_sessions.c.id == g["id"]).values(started_at=int(time.time()) - 20))
    assert user.post("/api/game/complete", {"id": g["id"], "moves": 9, "misses": 2}).status_code == 400  # inconsistent
    r = user.post("/api/game/complete", {"id": g["id"], "moves": 8, "misses": 2}).json()
    assert r["xp"] == 8 and 19 <= r["seconds"] <= 25
    assert user.post("/api/game/complete", {"id": g["id"], "moves": 6, "misses": 0}).status_code == 409
    for deck in ("katakana", "vocab", "kanji"):
        cards = user.post("/api/game/start", {"deck": deck}).json()["cards"]
        en = [c["text"] for c in cards if c["side"] == "en"]
        assert len(cards) == 12 and len(set(en)) == 6


def test_daily_activity_cap(user):
    uid = uid_of(user)
    with db.tx() as c:
        total = sum(gamify.award(c, uid, "quiz", f"t:{i}", 30, "UTC") for i in range(20))
    assert total == gamify.DAILY_ACTIVITY_CAP


def test_kanji_study_and_search(user):
    r = user.post("/api/kanji/日/study").json()
    assert r["added"] and r["xp"] == 1
    assert user.post("/api/kanji/日/study").json()["xp"] == 0
    assert user.post("/api/kanji/X/study").status_code == 404
    s = lambda **p: user.c.get("/api/kanji/search", params=p).json()
    assert s()["total"] == 2136
    assert s(grade=1)["total"] == 80 and s(grade=8)["total"] == 1110
    assert s(q="日")["items"][0]["char"] == "日"
    assert "日" in [i["char"] for i in s(q="sun")["items"]]
    assert "日" in [i["char"] for i in s(q="にち")["items"]]
    assert "日" in [i["char"] for i in s(q="nichi")["items"]]
    assert "学" in [i["char"] for i in s(q="学校")["items"]]
    assert all(i["strokes"] == 4 for i in s(strokes=4, per=120)["items"])
    assert s(radical=72)["total"] > 10
    assert s(status="learning")["total"] == 1 and s(status="new")["total"] == 2135
    p2 = s(page=2, per=60)
    assert p2["page"] == 2 and len(p2["items"]) == 60 and p2["pages"] == 36
    assert s(q="zzzzqqq")["total"] == 0


def test_achievements_unlock_once(user):
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    uid = uid_of(user)
    with db.tx() as c:
        assert gamify.check_achievements(c, uid, "UTC") == []
        n = c.execute(select(func.count()).select_from(db.xp_events).where(db.xp_events.c.user_id == uid, db.xp_events.c.source == "achievement")).scalar()
    assert n == 1
    assert "First spark" in user.c.get("/achievements").text


def test_burst_requires_work(user):
    b = user.post("/api/burst/start").json()
    r = user.post("/api/burst/complete", {"id": b["id"]}).json()
    assert r["counted"] is False
    user.post("/api/lesson/complete", {"lesson": "hiragana-4"})
    for card in user.c.get("/api/review/queue").json()["cards"][:3]:
        user.post("/api/review/submit", {"card_id": card["id"], "rating": 3})
    r = user.post("/api/burst/complete", {"id": b["id"]}).json()
    assert r["counted"] and r["xp"] == 5
    assert user.post("/api/burst/complete", {"id": b["id"]}).status_code == 409


def test_vocab_add(user):
    r = user.post("/api/srs/add", {"track": "kvocab", "items": ["コーヒー", "パン"]}).json()
    assert r["added"] == 2
    assert user.post("/api/srs/add", {"track": "kvocab", "items": ["コーヒー"]}).json()["added"] == 0
    assert user.post("/api/srs/add", {"track": "kvocab", "items": ["notaword"]}).status_code == 400


def test_dashboard_numbers_are_real(user):
    html = user.c.get("/dashboard").text
    assert "0 started" in html
    user.post("/api/lesson/complete", {"lesson": "hiragana-1"})
    html = user.c.get("/dashboard").text
    assert "5 started" in html and "Review 5 cards" in html


def test_streak_logic():
    import datetime as dt
    D = lambda *xs: {dt.date(2026, 11, x) for x in xs}
    t = dt.date(2026, 11, 10)
    assert gamify.streak_from(D(10, 9, 8), t) == (3, 0)
    assert gamify.streak_from(D(9, 8), t) == (2, 0)          # today not done yet
    assert gamify.streak_from(D(10, 8, 7), t) == (3, 1)      # one rest day is fine
    assert gamify.streak_from(D(10, 7, 6), t) == (1, 0)      # two missed days reset
    assert gamify.streak_from(set(), t) == (0, 0)
    assert gamify.level_for(0)["level"] == 1 and gamify.level_for(50)["level"] == 2 and gamify.level_for(500)["level"] == 5


def test_stats_count_past_one(user):
    """Regression: summing a condition used to come back as True, so counts stopped at 1 (e.g. 'Pass 5 mastery tests')."""
    uid = uid_of(user)
    now = int(time.time())
    with db.tx() as c:
        for i in range(6):
            c.execute(db.quiz_attempts.insert().values(id=f"m{uid}x{i}", user_id=uid, kind="kanji-meaning", title="t", mode="mastery",
                                                       questions_json="[]", total=20, score=20, passed=1, started_at=now, finished_at=now))
        s = gamify.stats(c, uid, "UTC")
    assert s["mastery_passed"] == 6 and s["perfect"] == 6 and s["quizzes"] == 6
    with db.tx() as c:
        new = {a["code"] for a in gamify.check_achievements(c, uid, "UTC")}
    assert {"mastery_1", "mastery_5", "quiz_perfect"} <= new
