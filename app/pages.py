"""HTML pages."""
from __future__ import annotations

import json
import re
import smtplib
import time
from email.message import EmailMessage
import os

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import and_, delete, func, or_, select, update

from . import content, db, gamify, quiz
from .kana import SCRIPTS
from .security import DEV, DUMMY_HASH, hash_password, limiter, new_token, token_hash, verify_password
from . import cards, readings, srs, words
from .web import (check_csrf, create_session, mastery_cfg, page_user, redirect, render, set_session_cookie, user_of)

router = APIRouter()
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
TOTALS = {"hiragana": 104, "katakana": 134, "kanji": 2136}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def valid_tz(name: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name)
        return name
    except Exception:
        return "UTC"


def safe_next(nxt: str | None) -> str:
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else "/dashboard"


# ------------------------------------------------------------------ public
@router.get("/")
def landing(request: Request):
    if user_of(request):
        return redirect("/dashboard")
    m = content.meta()
    return render(request, "landing.html", {"kanji_count": m.get("kanji_count"), "vocab_count": m.get("kanji_vocab_count")})


@router.get("/about")
def about(request: Request):
    return render(request, "about.html", {"meta": content.meta(), "discrepancies": content.stroke_discrepancies(),
                                          "grades": json.loads(content.meta().get("grade_counts", "{}"))})


@router.get("/register")
def register_form(request: Request):
    if user_of(request):
        return redirect("/dashboard")
    return render(request, "auth/register.html", {"form": {}, "errors": []})


@router.post("/register")
def register(request: Request, username: str = Form(""), email: str = Form(""), display_name: str = Form(""),
             password: str = Form(""), timezone: str = Form("UTC"), csrf: str = Form("")):
    check_csrf(request, csrf)
    form = {"username": username, "email": email, "display_name": display_name}
    errors = []
    if not limiter.allow(f"reg:{client_ip(request)}", 10, 3600):
        errors.append("Too many sign-ups from this network. Try again later.")
    username, email, display_name = username.strip(), email.strip().lower(), display_name.strip()
    if not USERNAME_RE.match(username):
        errors.append("Username: 3–32 letters, numbers or underscores.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        errors.append("Please enter a valid email address.")
    if len(password) < 10:
        errors.append("Password: at least 10 characters (a short phrase works well).")
    if len(password) > 256:
        errors.append("Password is too long.")
    if not errors:
        with db.tx() as c:
            exists = c.execute(select(db.users.c.username, db.users.c.email).where(
                or_(func.lower(db.users.c.username) == username.lower(), db.users.c.email == email))).first()
            if exists:
                errors.append("That username or email is already registered.")
            else:
                uid = c.execute(db.users.insert().values(username=username, email=email, display_name=(display_name or username)[:64],
                                                         password_hash=hash_password(password), created_at=int(time.time()))).inserted_primary_key[0]
                c.execute(db.settings.insert().values(user_id=uid, timezone=valid_tz(timezone)))
                gamify.log(c, uid, "account", "Joined Shuinkan 🎉")
                tok, _ = create_session(c, uid)
        if not errors:
            resp = redirect("/dashboard?welcome=1")
            set_session_cookie(resp, tok)
            return resp
    return render(request, "auth/register.html", {"form": form, "errors": errors}, status=400)


@router.get("/login")
def login_form(request: Request, next: str = "/dashboard"):
    if user_of(request):
        return redirect(safe_next(next))
    return render(request, "auth/login.html", {"next": safe_next(next), "error": None, "login": ""})


@router.post("/login")
def login(request: Request, login: str = Form(""), password: str = Form(""), next: str = Form("/dashboard"), csrf: str = Form("")):
    check_csrf(request, csrf)
    ip = client_ip(request)
    ident = login.strip().lower()
    if not limiter.allow(f"login:{ip}", 20, 300) or not limiter.allow(f"login-id:{ident}", 8, 300):
        return render(request, "auth/login.html", {"next": safe_next(next), "error": "Too many attempts. Wait a few minutes and try again.", "login": login}, status=429)
    with db.ro() as c:
        row = c.execute(select(db.users.c.id, db.users.c.password_hash).where(
            or_(func.lower(db.users.c.username) == ident, db.users.c.email == ident))).first()
    if not verify_password(password, row.password_hash if row else DUMMY_HASH) or row is None:
        return render(request, "auth/login.html", {"next": safe_next(next), "error": "That login and password don't match.", "login": login}, status=400)
    with db.tx() as c:
        tok, _ = create_session(c, row.id)
    resp = redirect(safe_next(next))
    set_session_cookie(resp, tok)
    return resp


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    tok = request.cookies.get("shuinkan_session")
    if tok:
        with db.tx() as c:
            c.execute(delete(db.sessions).where(db.sessions.c.id_hash == token_hash(tok)))
    resp = redirect("/")
    resp.delete_cookie("shuinkan_session", path="/")
    return resp


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "auth/forgot.html", {"sent": False, "dev_link": None})


def send_reset_email(to: str, link: str) -> bool:
    host = os.environ.get("SHUINKAN_SMTP_HOST")
    if not host:
        return False
    msg = EmailMessage()
    msg["Subject"] = "Reset your Shuinkan password"
    msg["From"] = os.environ.get("SHUINKAN_SMTP_FROM", "no-reply@localhost")
    msg["To"] = to
    msg.set_content(f"Someone asked to reset your Shuinkan password.\n\nUse this link within 1 hour:\n{link}\n\nIf it wasn't you, ignore this email.")
    with smtplib.SMTP(host, int(os.environ.get("SHUINKAN_SMTP_PORT", "587")), timeout=10) as s:
        s.starttls()
        if os.environ.get("SHUINKAN_SMTP_USER"):
            s.login(os.environ["SHUINKAN_SMTP_USER"], os.environ.get("SHUINKAN_SMTP_PASSWORD", ""))
        s.send_message(msg)
    return True


@router.post("/forgot")
def forgot(request: Request, email: str = Form(""), csrf: str = Form("")):
    check_csrf(request, csrf)
    email = email.strip().lower()
    dev_link = None
    if limiter.allow(f"forgot:{client_ip(request)}", 5, 900) and limiter.allow(f"forgot-e:{email}", 3, 900):
        with db.tx() as c:
            uid = c.execute(select(db.users.c.id).where(db.users.c.email == email)).scalar()
            if uid:
                tok = new_token()
                c.execute(db.password_resets.insert().values(token_hash=token_hash(tok), user_id=uid, expires_at=int(time.time()) + 3600))
                link = f"{request.url.scheme}://{request.headers.get('host')}/reset/{tok}"
                try:
                    sent = send_reset_email(email, link)
                except Exception:
                    sent = False
                if not sent and DEV:
                    dev_link = link
    return render(request, "auth/forgot.html", {"sent": True, "dev_link": dev_link})


def _reset_row(c, tok: str):
    return c.execute(select(db.password_resets).where(db.password_resets.c.token_hash == token_hash(tok),
                                                       db.password_resets.c.used == 0,
                                                       db.password_resets.c.expires_at > int(time.time()))).first()


@router.get("/reset/{tok}")
def reset_form(request: Request, tok: str):
    with db.ro() as c:
        valid = _reset_row(c, tok) is not None
    return render(request, "auth/reset.html", {"tok": tok, "valid": valid, "error": None})


@router.post("/reset/{tok}")
def reset(request: Request, tok: str, password: str = Form(""), csrf: str = Form("")):
    check_csrf(request, csrf)
    if len(password) < 10 or len(password) > 256:
        return render(request, "auth/reset.html", {"tok": tok, "valid": True, "error": "Password: at least 10 characters."}, status=400)
    with db.tx() as c:
        row = _reset_row(c, tok)
        if row is None:
            return render(request, "auth/reset.html", {"tok": tok, "valid": False, "error": None}, status=400)
        c.execute(update(db.password_resets).where(db.password_resets.c.token_hash == row.token_hash).values(used=1))
        c.execute(update(db.users).where(db.users.c.id == row.user_id).values(password_hash=hash_password(password)))
        c.execute(delete(db.sessions).where(db.sessions.c.user_id == row.user_id))  # sign out everywhere
        gamify.log(c, row.user_id, "account", "Password reset")
    return redirect("/login?reset=1")


# --------------------------------------------------------------- dashboard
def next_step(s: dict, due: int) -> dict:
    if due:
        mins = max(1, round(due * 8 / 60))
        return {"title": f"Review {due} card{'s' if due != 1 else ''}", "sub": f"About {mins} min. Clears your queue.", "url": "/review", "icon": "↻"}
    for script in ("hiragana", "katakana"):
        for les in SCRIPTS[script]["lessons"]:
            if les["slug"] not in s["lesson_ids"]:
                return {"title": f"{SCRIPTS[script]['label']}: {les['title']}", "sub": f"{len(les['chars'])} new characters · about 3 min",
                        "url": f"/learn/{script}/{les['id']}", "icon": les["chars"][0]}
    started = s["kanji_started"]
    nxt = next((k for k in content.kanji_list()[started:started + 1]), None)
    if nxt:
        return {"title": f"Meet a new kanji: {nxt['char']}", "sub": content.first_meaning(nxt), "url": f"/kanji/{nxt['char']}", "icon": nxt["char"]}
    return {"title": "Take a mixed quiz", "sub": "Keep everything fresh.", "url": "/quiz", "icon": "?"}


def track_progress(s: dict) -> list[dict]:
    out = []
    tc = s["track_counts"]
    for t in ("hiragana", "katakana", "kanji"):
        started = sum(n for (tr, _), n in tc.items() if tr == t)
        mastered = tc.get((t, "mastered"), 0)
        total = TOTALS[t]
        out.append({"track": t, "label": content.TRACKS[t], "started": started, "mastered": mastered, "total": total,
                    "pct": round(100 * started / total, 1), "mpct": round(100 * mastered / total, 1)})
    return out


@router.get("/dashboard")
def dashboard(request: Request, welcome: int = 0):
    u = page_user(request)
    uid, tz = u["id"], u["timezone"]
    now = int(time.time())
    with db.ro() as c:
        s = gamify.stats(c, uid, tz)
        sc = db.srs_cards.c
        due = srs.counts(c, uid, tz, now)["total"]
        upcoming = {r.d: r.n for r in c.execute(
            select(((sc.due_at - now) / 86400).label("d"), func.count().label("n"))
            .where(sc.user_id == uid, sc.due_at > now, sc.due_at <= now + 7 * 86400, sc.suspended == 0, sc.total_reviews > 0)
            .group_by("d"))}
        streak = gamify.streak_info(c, uid, tz)
        txp = gamify.today_xp(c, uid, tz)
        qa = db.quiz_attempts.c
        quizzes = c.execute(select(qa.id, qa.title, qa.mode, qa.score, qa.total, qa.passed, qa.finished_at)
                            .where(qa.user_id == uid, qa.finished_at.isnot(None)).order_by(qa.finished_at.desc()).limit(4)).all()
        acts = c.execute(select(db.activity.c.text, db.activity.c.created_at).where(db.activity.c.user_id == uid)
                         .order_by(db.activity.c.id.desc()).limit(6)).all()
        ach = c.execute(select(db.achievements.c.code).where(db.achievements.c.user_id == uid)
                        .order_by(db.achievements.c.unlocked_at.desc()).limit(4)).scalars().all()
        n_ach = c.execute(select(func.count()).select_from(db.achievements).where(db.achievements.c.user_id == uid)).scalar()
    xp = gamify.level_for(u["xp"])
    return render(request, "dashboard.html", {
        "s": s, "due": due, "upcoming": [upcoming.get(i, 0) for i in range(7)], "streak": streak, "today_xp": txp,
        "goal": u["daily_goal"], "goal_pct": min(100, round(100 * txp / max(1, u["daily_goal"]))), "lvl": xp,
        "next": next_step(s, due), "tracks": track_progress(s), "quizzes": quizzes, "acts": acts, "welcome": welcome,
        "recent_ach": [gamify.ACH_BY_CODE[a] for a in ach if a in gamify.ACH_BY_CODE], "n_ach": n_ach,
        "n_ach_total": len(gamify.ACHIEVEMENTS),
    })


# ------------------------------------------------------------------ courses
def _script_or_404(script: str):
    if script not in SCRIPTS:
        raise HTTPException(404, "There's no course with that name.")
    return SCRIPTS[script]


@router.get("/learn/{script}")
def course(request: Request, script: str):
    u = page_user(request)
    sc = _script_or_404(script)
    with db.ro() as c:
        done = set(c.execute(select(db.lesson_completions.c.lesson).where(db.lesson_completions.c.user_id == u["id"])).scalars())
        states = {r.item: r.state for r in c.execute(select(db.srs_cards.c.item, db.srs_cards.c.state).where(
            db.srs_cards.c.user_id == u["id"], db.srs_cards.c.track == script))}
    nxt = next((l for l in sc["lessons"] if l["slug"] not in done), None)
    return render(request, "course.html", {"script": script, "sc": sc, "done": done, "states": states, "nxt": nxt,
                                           "groups": [("basic", "Basic sounds"), ("voiced", "Voiced sounds"), ("combo", "Combinations"), ("special", "Foreign sounds")]})


@router.get("/learn/{script}/{n}")
def lesson(request: Request, script: str, n: int):
    u = page_user(request)
    sc = _script_or_404(script)
    if not 1 <= n <= len(sc["lessons"]):
        raise HTTPException(404, "That lesson doesn't exist.")
    les = sc["lessons"][n - 1]
    vocab = content.vocab_list(script)
    chars = []
    for k in les["chars"]:
        ch = next(c for c in sc["chars"] if c["kana"] == k)
        examples = [v for v in vocab if k in v["word"]][:3]
        chars.append({**ch, "stroke": content.stroke_file(k) if len(k) == 1 and k != "ー" else None,
                      "parts": [content.stroke_file(x) for x in k] if len(k) > 1 else None,
                      "examples": [{"word": v["word"], "romaji": v["romaji"], "meaning": v["meaning"].split("; ")[0]} for v in examples]})
    with db.ro() as c:
        done = c.execute(select(db.lesson_completions.c.lesson).where(db.lesson_completions.c.user_id == u["id"],
                                                                       db.lesson_completions.c.lesson == les["slug"])).first() is not None
    nxt = sc["lessons"][n] if n < len(sc["lessons"]) else None
    pool = [c["romaji"] for c in sc["chars"] if c["group"] == les["group"] and c["kana"] not in ("ッ", "ー")]
    return render(request, "lesson.html", {"script": script, "sc": sc, "les": les, "chars": chars, "done": done, "nxt": nxt,
                                           "pool": pool})


@router.get("/vocab/{script}")
def vocab(request: Request, script: str):
    u = page_user(request)
    _script_or_404(script)
    track = "hvocab" if script == "hiragana" else "kvocab"
    words = content.vocab_list(script)
    with db.ro() as c:
        states = {r.item: r.state for r in c.execute(select(db.srs_cards.c.item, db.srs_cards.c.state).where(
            db.srs_cards.c.user_id == u["id"], db.srs_cards.c.track == track))}
    cats = sorted({w["category"] for w in words})
    return render(request, "vocab.html", {"script": script, "track": track, "words": words, "states": states, "cats": cats})


# -------------------------------------------------------------------- kanji
@router.get("/kanji")
def kanji_library(request: Request):
    u = page_user(request)
    with db.ro() as c:
        decks = c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
    return render(request, "kanji_library.html", {"radicals": _radicals(), "decks": decks})


_RADICALS = None


def _radicals():
    global _RADICALS
    if _RADICALS is None:
        seen = {}
        for k in content.kanji_list():
            if k["radical_num"]:
                seen.setdefault(k["radical_num"], (k["radical_char"], k["radical_name"], 0))
                ch, nm, n = seen[k["radical_num"]]
                seen[k["radical_num"]] = (ch, nm, n + 1)
        _RADICALS = [(num, ch, nm, n) for num, (ch, nm, n) in sorted(seen.items())]
    return _RADICALS


@router.get("/words")
def words_course(request: Request):
    """Kanji through words: the main way to learn kanji here."""
    u = page_user(request)
    with db.ro() as c:
        have = words.user_word_ids(c, u["id"])
        known = words.known_kanji(c, u["id"])
        deck = c.execute(select(db.decks).where(db.decks.c.user_id == u["id"], db.decks.c.name == words.DECK_NAME)).first()
        decks = c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
    course = words.course()
    upcoming = [{**w, **words.breakdown(w["word"], w["reading"])} for w in words.next_words(set(have), 12)]
    in_course = sum(1 for i in have if words.get(i))
    learned = sum(1 for i, r in have.items() if r["state"] in ("review", "mastered") and words.get(i))
    return render(request, "words.html", {
        "total": len(course), "in_course": in_course, "learned": learned, "upcoming": upcoming, "deck": deck, "decks": decks,
        "kanji_known": sum(1 for v in known.values() if v == "known"), "kanji_met": len(known), "kanji_total": len(content.kanji_list()),
    })


@router.get("/guess")
def guess_page(request: Request):
    u = page_user(request)
    with db.ro() as c:
        met = len(words.known_kanji(c, u["id"]))
    return render(request, "guess.html", {"met": met})


@router.get("/kanji/grid")
def kanji_grid(request: Request, by: str = "grade"):
    """Every Jōyō kanji, coloured by whether you've met it in your words (like Anki's Kanji Grid add-on)."""
    u = page_user(request)
    with db.ro() as c:
        known = words.known_kanji(c, u["id"])
    ks = content.kanji_list()
    if by == "freq":
        ordered = sorted(ks, key=lambda k: k["freq"] or 9999)
        groups = [(f"Most common {lo + 1}–{min(lo + 500, 2500)}" if lo < 2500 else "Less common", ordered[lo:lo + 500] if lo < 2000 else ordered[lo:])
                  for lo in range(0, 2500, 500)]
        groups = [(t, g) for t, g in groups if g]
    elif by == "jlpt" and u["show_jlpt"]:
        groups = [(f"Old JLPT level {n}", [k for k in ks if k["jlpt_old"] == n]) for n in (4, 3, 2, 1)]
        groups.append(("Not on the old JLPT list", [k for k in ks if not k["jlpt_old"]]))
    else:
        by = "grade"
        groups = [(label, [k for k in ks if k["grade"] == g]) for g, label in content.GRADE_LABELS.items()]
    groups = [{"title": t, "kanji": g, "known": sum(1 for k in g if known.get(k["char"]) == "known"),
               "met": sum(1 for k in g if k["char"] in known)} for t, g in groups]
    return render(request, "kanji_grid.html", {"groups": groups, "known": known, "by": by,
                                               "n_known": sum(1 for v in known.values() if v == "known"), "n_met": len(known),
                                               "total": len(ks)})


_GUIDE = None


def _guide_examples():
    """Real examples for the reading guide, taken from the start of the word course."""
    global _GUIDE
    if _GUIDE is None:
        buckets = {k: [] for k in ("on_compound", "kun_okurigana", "kun_compound", "on_okurigana", "special", "voiced", "sokuon")}
        totals = {"compound": [0, 0], "okurigana": [0, 0]}
        for w in words.course():
            a = readings.analyse(w["word"], w["reading"])
            h = readings.hint(w["word"], w["reading"])
            if h["rule"] in totals:
                totals[h["rule"]][0] += 1
                totals[h["rule"]][1] += bool(h["followed"])
            kinds = {p["kind"] for p in a["parts"] if p["kind"] in ("on", "kun")}
            key = None
            if a["special"]:
                key = "special"
            elif any(p.get("change") == "small っ" for p in a["parts"]):
                key = "sokuon"
            elif any(p.get("change") == "voiced" for p in a["parts"]):
                key = "voiced"
            elif h["rule"] == "compound":
                key = "on_compound" if kinds == {"on"} else ("kun_compound" if kinds == {"kun"} else None)
            elif h["rule"] == "okurigana":
                key = "kun_okurigana" if h["followed"] else "on_okurigana"
            # Clean examples: guided-pass words, short, and (for special readings) kanji only.
            if key == "special" and (not w.get("first") or len(w["word"]) > 2 or any(not readings.is_kanji(ch) for ch in w["word"])):
                continue
            if key and len(buckets[key]) < 6 and len(w["word"]) <= 4:
                buckets[key].append({**w, **words.breakdown(w["word"], w["reading"])})
        _GUIDE = {"ex": buckets, "totals": {k: {"n": n, "pct": round(100 * f / n) if n else 0} for k, (n, f) in totals.items()},
                  "n_words": len(words.course())}
    return _GUIDE


@router.get("/kanji/readings")
def kanji_readings_guide(request: Request):
    page_user(request)
    return render(request, "kanji_readings.html", _guide_examples())


def _kanji_words(ch: str, uid: int) -> list[dict]:
    ws = words.for_kanji(ch, 10)
    with db.ro() as c:
        have = words.user_word_ids(c, uid)
    out = []
    for w in ws:
        b = words.breakdown(w["word"], w["reading"])
        mine = next((r for r in b["kanji"] if r["char"] == ch), None)
        out.append({**w, **b, "this": mine, "added": w["id"] in have})
    return out


@router.get("/kanji/{ch}")
def kanji_detail(request: Request, ch: str):
    u = page_user(request)
    k = content.kanji_get(ch)
    if not k:
        raise HTTPException(404, "That character isn't one of the 2,136 Jōyō kanji.")
    with db.ro() as c:
        full = c.execute(select(db.kanji.c.nanori, db.kanji.c.kvg_strokes).where(db.kanji.c.char == ch)).first()
        card = c.execute(select(db.srs_cards).where(db.srs_cards.c.user_id == u["id"], db.srs_cards.c.track == "kanji",
                                                    db.srs_cards.c.item == ch)).first()
        prog = c.execute(select(db.progress.c.attempts, db.progress.c.correct).where(
            db.progress.c.user_id == u["id"], db.progress.c.track == "kanji", db.progress.c.item == ch)).first()
        decks = c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
        note = c.execute(select(db.notes).where(db.notes.c.user_id == u["id"], db.notes.c.track == "kanji", db.notes.c.item == ch)).first()
    related = [x for x in content.kanji_list() if x["radical_num"] == k["radical_num"] and x["char"] != ch]
    related.sort(key=lambda x: x["freq"] or 99999)
    idx = k["idx"]
    ks = content.kanji_list()
    return render(request, "kanji_detail.html", {
        "k": k, "nanori": full.nanori, "kvg_strokes": full.kvg_strokes, "vocab": content.kanji_vocab(ch),
        "course_words": _kanji_words(ch, u["id"]),
        "sentences": content.kanji_sentences(ch), "related": related[:10], "card": card._mapping if card else None,
        "prog": prog, "stroke": content.stroke_file(ch),
        "decks": decks, "note": note, "deck_name": dict(decks).get(card.deck_id) if card else None,
        "prev": ks[idx - 2] if idx > 1 else None, "nextk": ks[idx] if idx < len(ks) else None, "cfg": mastery_cfg(u),
    })


# ------------------------------------------------------------- study pages
@router.get("/review")
def review_page(request: Request, track: str = "", burst: int = 0, deck: int = 0):
    u = page_user(request)
    if track and track not in cards.TRACK_LABELS:
        track = ""
    now = int(time.time())
    with db.ro() as c:
        deck_row = c.execute(select(db.decks).where(db.decks.c.id == deck, db.decks.c.user_id == u["id"])).first() if deck else None
        rows = srs.queue(c, u["id"], u["timezone"], now, track=track or None, deck_id=deck_row.id if deck_row else None, limit=60)
        data = cards.build(c, u, rows, now)
        everything = srs.queue(c, u["id"], u["timezone"], now, limit=100000)
        counts = {}
        for r in everything:
            counts[r["track"]] = counts.get(r["track"], 0) + 1
        sc = db.srs_cards.c
        nxt = c.execute(select(func.min(sc.due_at)).where(sc.user_id == u["id"], sc.due_at > now, sc.suspended == 0,
                                                          sc.total_reviews > 0)).scalar()
    return render(request, "review.html", {"cards": data, "track": track, "counts": counts, "burst": bool(burst),
                                           "next_due": nxt, "now": now, "burst_minutes": u["burst_minutes"],
                                           "deck": deck_row, "labels": cards.TRACK_LABELS})


@router.get("/quiz")
def quiz_center(request: Request):
    u = page_user(request)
    with db.ro() as c:
        qa = db.quiz_attempts.c
        history = c.execute(select(qa.id, qa.title, qa.mode, qa.score, qa.total, qa.passed, qa.finished_at, qa.xp_awarded)
                            .where(qa.user_id == u["id"], qa.finished_at.isnot(None)).order_by(qa.finished_at.desc()).limit(15)).all()
        due = srs.counts(c, u["id"], u["timezone"])["total"]
    groups = [
        ("Kana", ["hiragana-recognition", "hiragana-reading", "katakana-recognition", "katakana-reading"]),
        ("Words", ["hvocab-meaning", "kvocab-meaning", "vocab-sentence"]),
        ("Kanji", ["kanji-meaning", "kanji-reading", "kanji-vocab", "kanji-radical", "kanji-strokes", "kanji-sentence"]),
        ("Everything", ["mixed"]),
    ]
    return render(request, "quiz_center.html", {"groups": groups, "kinds": quiz.KINDS, "history": history, "due": due})


def _attempt(c, uid, qid):
    row = c.execute(select(db.quiz_attempts).where(db.quiz_attempts.c.id == qid, db.quiz_attempts.c.user_id == uid)).first()
    if row is None:
        raise HTTPException(404, "That quiz doesn't exist (or isn't yours).")
    return row


@router.get("/quiz/{qid}")
def quiz_run(request: Request, qid: str):
    u = page_user(request)
    with db.ro() as c:
        a = _attempt(c, u["id"], qid)
        answered = c.execute(select(func.count()).where(db.quiz_details.c.attempt_id == qid)).scalar()
    if a.finished_at:
        return redirect(f"/quiz/{qid}/results")
    qs = json.loads(a.questions_json)
    now = int(time.time())
    return render(request, "quiz_run.html", {"a": a, "questions": [quiz.public(q) for q in qs], "answered": answered,
                                             "remaining": (a.deadline_at - now) if a.deadline_at else None})


@router.get("/quiz/{qid}/results")
def quiz_results(request: Request, qid: str):
    u = page_user(request)
    with db.ro() as c:
        a = _attempt(c, u["id"], qid)
        details = {r.idx: r for r in c.execute(select(db.quiz_details).where(db.quiz_details.c.attempt_id == qid))}
    if not a.finished_at:
        return redirect(f"/quiz/{qid}")
    qs = json.loads(a.questions_json)
    rows = []
    for i, q in enumerate(qs[: a.total]):
        d = details.get(i)
        your = None
        if d is not None and d.answer is not None and d.answer.isdigit() and int(d.answer) < len(q["options"]):
            your = q["options"][int(d.answer)]
        rows.append({"q": q, "your": your, "correct": bool(d and d.correct), "right": q["options"][q["answer"]]})
    pct = round(100 * (a.score or 0) / a.total) if a.total else 0
    return render(request, "quiz_results.html", {"a": a, "rows": rows, "pct": pct})


@router.get("/write")
def writing(request: Request, track: str = "hiragana", item: str = ""):
    u = page_user(request)
    if track not in ("hiragana", "katakana", "kanji"):
        track = "hiragana"
    if track == "kanji":
        with db.ro() as c:
            started = list(c.execute(select(db.srs_cards.c.item).where(db.srs_cards.c.user_id == u["id"], db.srs_cards.c.track == "kanji")
                                     .order_by(db.srs_cards.c.created_at)).scalars())
        chars = started or [k["char"] for k in content.kanji_list()[:80]]
        chars = [{"kana": ch, "romaji": content.first_meaning(content.kanji_get(ch))} for ch in chars]
    else:
        chars = [c for c in SCRIPTS[track]["chars"] if len(c["kana"]) == 1 and c["kana"] != "ー"]
    if not item or not any(c["kana"] == item for c in chars):
        if track == "kanji" and content.kanji_get(item):
            chars.insert(0, {"kana": item, "romaji": content.first_meaning(content.kanji_get(item))})
        else:
            item = chars[0]["kana"]
    cur = next(c for c in chars if c["kana"] == item)
    return render(request, "writing.html", {"track": track, "chars": chars, "cur": cur, "stroke": content.stroke_file(item)})


@router.get("/match")
def match(request: Request):
    page_user(request)
    return render(request, "match.html", {"decks": [("hiragana", "Hiragana ↔ romaji"), ("katakana", "Katakana ↔ romaji"),
                                                    ("vocab", "Words ↔ meaning"), ("kanji", "Kanji ↔ meaning")]})


@router.get("/progress")
def progress_page(request: Request):
    u = page_user(request)
    uid, tz = u["id"], u["timezone"]
    import datetime as dt
    today = dt.date.fromisoformat(gamify.local_day(tz))
    days30 = [(today - dt.timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    with db.ro() as c:
        s = gamify.stats(c, uid, tz)
        xe = db.xp_events.c
        by_day = {r.day: r.xp for r in c.execute(select(xe.day, func.sum(xe.amount).label("xp")).where(
            xe.user_id == uid, xe.day >= days30[0]).group_by(xe.day))}
        since = int(time.time()) - 30 * 86400
        rv = c.execute(select(func.count(), db.count_if(db.reviews.c.rating >= 2)).where(db.reviews.c.user_id == uid, db.reviews.c.created_at >= since)).one()
        qa = db.quiz_attempts.c
        qz = c.execute(select(func.count(), func.sum(qa.score), func.sum(qa.total)).where(
            qa.user_id == uid, qa.finished_at >= since)).one()
        acts = c.execute(select(db.activity.c.text, db.activity.c.created_at, db.activity.c.kind).where(db.activity.c.user_id == uid)
                         .order_by(db.activity.c.id.desc()).limit(30)).all()
        streak = gamify.streak_info(c, uid, tz)
        ps = c.execute(select(db.progress.c.track, func.sum(db.progress.c.attempts), func.sum(db.progress.c.correct))
                       .where(db.progress.c.user_id == uid).group_by(db.progress.c.track)).all()
    week = [{"day": d, "label": dt.date.fromisoformat(d).strftime("%a"), "xp": by_day.get(d, 0)} for d in days30[-7:]]
    month = [{"day": d, "xp": by_day.get(d, 0)} for d in days30]
    return render(request, "progress.html", {
        "s": s, "tracks": track_progress(s), "week": week, "week_max": max([w["xp"] for w in week] + [1]),
        "month": month, "month_max": max([m["xp"] for m in month] + [1]), "month_xp": sum(m["xp"] for m in month),
        "active_days": sum(1 for m in month if m["xp"]), "reviews30": rv[0] or 0,
        "review_acc": round(100 * (rv[1] or 0) / rv[0]) if rv[0] else None, "quizzes30": qz[0] or 0,
        "quiz_acc": round(100 * (qz[1] or 0) / qz[2]) if qz[2] else None, "acts": acts, "streak": streak,
        "accuracy": [{"track": t, "label": content.TRACKS.get(t, t), "attempts": a or 0, "pct": round(100 * (cr or 0) / a) if a else 0} for t, a, cr in ps],
        "lvl": gamify.level_for(u["xp"]),
    })


@router.get("/achievements")
def achievements_page(request: Request):
    u = page_user(request)
    with db.ro() as c:
        have = {r.code: r.unlocked_at for r in c.execute(select(db.achievements).where(db.achievements.c.user_id == u["id"]))}
    items = [{"code": a[0], "title": a[1], "desc": a[2], "icon": a[3], "xp": a[4], "at": have.get(a[0])} for a in gamify.ACHIEVEMENTS]
    items.sort(key=lambda x: (x["at"] is None, -(x["at"] or 0)))
    return render(request, "achievements.html", {"items": items, "n": len(have)})


# ----------------------------------------------------------------- settings
# id -> (name, meaning, light swatch, dark swatch); must match the palettes in static/css/app.css
PALETTES = {
    "shuinkan": ("Shuinkan", "朱 vermilion", "#cc3f26", "#ff6a4d"),
    "sakura": ("Sakura", "桜 cherry blossom", "#c9457c", "#ff8cba"),
    "matcha": ("Matcha", "抹茶 green tea", "#3d7f3a", "#86cf78"),
    "ai": ("Ai", "藍 indigo", "#2f55c4", "#86a2ff"),
    "fuji": ("Fuji", "藤 wisteria", "#7448bd", "#b796ff"),
    "yuzu": ("Yuzu", "柚子 citrus", "#a85c08", "#ffb347"),
    "umi": ("Umi", "海 sea", "#12808a", "#5fd3dc"),
    "sumi": ("Sumi", "墨 ink", "#2b2926", "#ece6dc"),
}
SETTING_RANGES = {"daily_goal": (10, 500), "mastery_accuracy": (70, 100), "mastery_reps": (1, 10),
                  "mastery_interval": (1, 365), "burst_minutes": (2, 25)}


@router.get("/settings")
def settings_page(request: Request, saved: int = 0):
    page_user(request)
    return render(request, "settings.html", {"saved": saved, "ranges": SETTING_RANGES, "errors": [], "palettes": PALETTES})


@router.post("/settings")
async def settings_save(request: Request):
    u = page_user(request)
    form = await request.form()
    check_csrf(request, form.get("csrf"))
    vals, errors = {}, []
    for key, (lo, hi) in SETTING_RANGES.items():
        try:
            v = float(form.get(key, ""))
        except ValueError:
            errors.append(f"{key.replace('_', ' ').capitalize()} must be a number.")
            continue
        if not lo <= v <= hi:
            errors.append(f"{key.replace('_', ' ').capitalize()} must be between {lo} and {hi}.")
            continue
        vals[key] = int(v)
    pal = form.get("palette", "shuinkan")
    vals["palette"] = pal if pal in PALETTES else "shuinkan"
    theme = form.get("theme", "system")
    vals["theme"] = theme if theme in ("system", "light", "dark") else "system"
    for flag in ("show_romaji", "show_jlpt", "calm_mode", "celebrations", "anki_autoplay"):
        vals[flag] = 1 if form.get(flag) == "1" else 0
    vals["timezone"] = valid_tz(str(form.get("timezone", "UTC")))
    if errors:
        return render(request, "settings.html", {"saved": 0, "ranges": SETTING_RANGES, "errors": errors, "palettes": PALETTES}, status=400)
    with db.tx() as c:
        c.execute(update(db.settings).where(db.settings.c.user_id == u["id"]).values(**vals))
    return redirect("/settings?saved=1")


@router.get("/profile")
def profile_page(request: Request, saved: str = ""):
    u = page_user(request)
    with db.ro() as c:
        n_sessions = c.execute(select(func.count()).where(db.sessions.c.user_id == u["id"], db.sessions.c.expires_at > int(time.time()))).scalar()
    return render(request, "profile.html", {"saved": saved, "errors": [], "n_sessions": n_sessions})


@router.post("/profile")
def profile_save(request: Request, display_name: str = Form(""), username: str = Form(""), email: str = Form(""), csrf: str = Form("")):
    u = page_user(request)
    check_csrf(request, csrf)
    username, email, display_name = username.strip(), email.strip().lower(), display_name.strip()
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Username: 3–32 letters, numbers or underscores.")
    if not EMAIL_RE.match(email):
        errors.append("Please enter a valid email address.")
    if not 1 <= len(display_name) <= 64:
        errors.append("Display name: 1–64 characters.")
    with db.tx() as c:
        if not errors and c.execute(select(db.users.c.id).where(or_(func.lower(db.users.c.username) == username.lower(), db.users.c.email == email),
                                                                 db.users.c.id != u["id"])).first():
            errors.append("That username or email is already used by someone else.")
        if not errors:
            c.execute(update(db.users).where(db.users.c.id == u["id"]).values(username=username, email=email, display_name=display_name))
    if errors:
        return render(request, "profile.html", {"saved": "", "errors": errors, "n_sessions": 1}, status=400)
    return redirect("/profile?saved=profile")


@router.post("/profile/password")
def password_change(request: Request, current: str = Form(""), new: str = Form(""), csrf: str = Form("")):
    u = page_user(request)
    check_csrf(request, csrf)
    if not limiter.allow(f"pw:{u['id']}", 5, 900):
        return render(request, "profile.html", {"saved": "", "errors": ["Too many attempts. Try again later."], "n_sessions": 1}, status=429)
    with db.tx() as c:
        h = c.execute(select(db.users.c.password_hash).where(db.users.c.id == u["id"])).scalar()
        if not verify_password(current, h):
            errors = ["Your current password isn't right."]
        elif not 10 <= len(new) <= 256:
            errors = ["New password: at least 10 characters."]
        else:
            errors = []
            c.execute(update(db.users).where(db.users.c.id == u["id"]).values(password_hash=hash_password(new)))
            # Keep this browser signed in; sign out everywhere else.
            c.execute(delete(db.sessions).where(db.sessions.c.user_id == u["id"], db.sessions.c.id_hash != u["id_hash"]))
            gamify.log(c, u["id"], "account", "Password changed")
    if errors:
        return render(request, "profile.html", {"saved": "", "errors": errors, "n_sessions": 1}, status=400)
    return redirect("/profile?saved=password")


@router.get("/hooks")
def hooks_chart(request: Request, script: str = "hiragana"):
    page_user(request)
    if script not in SCRIPTS:
        script = "hiragana"
    chars = SCRIPTS[script]["chars"]
    groups = [("basic", "Basic sounds"), ("voiced", "Voiced sounds ゛ ゜"), ("combo", "Combinations"), ("special", "Foreign sounds")]
    return render(request, "hooks.html", {"script": script, "sc": SCRIPTS[script],
                                          "groups": [(name, [c for c in chars if c["group"] == g]) for g, name in groups
                                                     if any(c["group"] == g for c in chars)]})


@router.get("/decks")
def decks_page(request: Request):
    u = page_user(request)
    now = int(time.time())
    with db.ro() as c:
        sc = db.srs_cards.c
        rows = c.execute(select(db.decks).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
        totals = {r.deck_id: (r.n, r.susp) for r in c.execute(select(sc.deck_id, func.count().label("n"), func.sum(sc.suspended).label("susp"))
                                                               .where(sc.user_id == u["id"], sc.deck_id.isnot(None)).group_by(sc.deck_id))}
        counts = srs.deck_counts(c, u["id"], u["timezone"], now)
        dicts = c.execute(select(db.user_dicts).where(db.user_dicts.c.user_id == u["id"]).order_by(db.user_dicts.c.created_at)).all()
    decks = [{"d": d, "total": totals.get(d.id, (0, 0))[0], "suspended": totals.get(d.id, (0, 0))[1] or 0,
              **counts.get(d.id, {"new": 0, "learn": 0, "review": 0})} for d in rows]
    return render(request, "decks.html", {"decks": decks, "saved": request.query_params.get("saved", "")})


@router.get("/browse")
def browse_page(request: Request):
    u = page_user(request)
    with db.ro() as c:
        decks = c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
    return render(request, "browse.html", {"decks": decks})


@router.get("/dictionary")
def dictionary_page(request: Request, q: str = ""):
    u = page_user(request)
    from . import dictionary as dic
    t0 = time.perf_counter()
    with db.ro() as c:
        results, total = dic.search(c, q) if q.strip() else ([], 0)
        mine = dic.search_user(c, u["id"], q) if q.strip() else []
        dicts = c.execute(select(db.user_dicts).where(db.user_dicts.c.user_id == u["id"]).order_by(db.user_dicts.c.created_at)).all()
        decks = c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == u["id"]).order_by(db.decks.c.name)).all()
        have = set(c.execute(select(db.srs_cards.c.item).where(db.srs_cards.c.user_id == u["id"], db.srs_cards.c.track == "dict")).scalars())
    ctx = {"q": q, "results": results, "total": total, "mine": mine, "dicts": dicts, "decks": decks, "have": have,
           "ms": round((time.perf_counter() - t0) * 1000, 1), "entries": content.meta().get("dict_entries")}
    if request.headers.get("x-partial") == "1":
        return render(request, "_dict_results.html", ctx)
    return render(request, "dictionary.html", ctx)


# ------------------------------------------------------- imported Anki cards
def _anki_card(c, uid: int, cid: int):
    cc = db.custom_cards.c
    row = c.execute(select(db.custom_cards, db.anki_models.c.kind, db.anki_models.c.css, db.anki_models.c.tmpls_json,
                           db.anki_models.c.name.label("model_name"), db.anki_models.c.deck_id)
                    .join(db.anki_models, db.anki_models.c.id == cc.model_id)
                    .where(cc.id == cid, cc.user_id == uid)).first()
    return row


@router.get("/anki-card/{cid}")
def anki_card(request: Request, cid: int, side: str = "front", night: int = 0):
    """One imported Anki card, rendered with its deck's templates + CSS. Shown in a sandboxed iframe."""
    from fastapi.responses import HTMLResponse

    from . import anki_render as ar
    u = user_of(request)
    if u is None:
        raise HTTPException(404, "Not found.")
    with db.ro() as c:
        row = _anki_card(c, u["id"], cid)
        deck = c.execute(select(db.decks.c.name).where(db.decks.c.id == row.deck_id)).scalar() if row else None
    if row is None:
        raise HTTPException(404, "Card not found.")
    model = {"name": row.model_name, "kind": row.kind, "tmpls": json.loads(row.tmpls_json)}
    r = ar.render_card(model, json.loads(row.fields_json or "{}"), row.ord, deck_id=row.deck_id, deck=deck or "", tags=row.tags)
    cls = r["class"] + (" nightMode night_mode" if night else "")
    body = r["back"] if side == "back" else r["front"]
    return HTMLResponse(ar.page(body, ar.rewrite_css(row.css, row.deck_id), cls), headers={
        "Content-Security-Policy": ar.CARD_CSP, "X-Frame-Options": "SAMEORIGIN", "Cache-Control": "private, no-cache",
        "Referrer-Policy": "no-referrer"})


@router.get("/anki-media/{deck_id}/{name:path}")
def anki_media(request: Request, deck_id: int, name: str):
    from fastapi.responses import Response
    u = user_of(request)
    if u is None:
        raise HTTPException(404, "Not found.")
    with db.ro() as c:
        row = c.execute(select(db.anki_media.c.mime, db.anki_media.c.data).where(
            db.anki_media.c.deck_id == deck_id, db.anki_media.c.user_id == u["id"], db.anki_media.c.name == name)).first()
    if row is None:
        raise HTTPException(404, "Not found.")
    data = bytes(row.data)
    headers = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "bytes",
               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}
    rng = request.headers.get("range", "")
    m = re.match(r"bytes=(\d*)-(\d*)$", rng)
    if m and data and (m.group(1) or m.group(2)):  # audio seeking (Safari needs ranges)
        if m.group(1):
            start, end = int(m.group(1)), int(m.group(2) or len(data) - 1)
        else:
            start, end = max(0, len(data) - int(m.group(2))), len(data) - 1
        end = min(end, len(data) - 1)
        if start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{len(data)}"})
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        return Response(data[start:end + 1], status_code=206, media_type=row.mime, headers=headers)
    return Response(data, media_type=row.mime, headers=headers)
