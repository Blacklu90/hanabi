"""Shared web helpers: templates, current user, CSRF, responses."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from fastapi import HTTPException, Request
from markupsafe import Markup
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select, update

from . import content, db, gamify
from .kana import SCRIPTS
from .security import DEV, SECURE_COOKIES, SESSION_COOKIE, SESSION_DAYS, new_token, token_hash

ROOT = Path(os.environ.get("SHUINKAN_ROOT") or Path(__file__).resolve().parent.parent)
STATIC = ROOT / "static"
CSRF_COOKIE = "shuinkan_csrf"
SECTIONS = {"vocab": "learn", "hooks": "learn", "write": "quiz", "match": "quiz", "browse": "decks", "words": "kanji", "guess": "kanji"}

templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _static_state() -> tuple:
    return tuple(sorted((p.as_posix(), p.stat().st_mtime_ns) for p in STATIC.rglob("*") if p.is_file()))


def _build_id() -> str:
    h = hashlib.sha256()
    for p in sorted(STATIC.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(STATIC).as_posix().encode())
            h.update(p.read_bytes())
    return "b" + h.hexdigest()[:10]


_BUILD = {"state": _static_state(), "id": _build_id()}


def build_id() -> str:
    if DEV:  # pick up edited files during development
        st = _static_state()
        if st != _BUILD["state"]:
            _BUILD.update(state=st, id=_build_id())
    return _BUILD["id"]


def asset(path: str) -> str:
    """Cache-busted static URL: /static/<build>/<path>.

    The version lives in the *path* (not a ?v= query) so that ES-module relative
    imports like `import … from './app.js'` resolve to the very same URL as the
    <script> tag. Otherwise the browser would load and run app.js twice.
    """
    return f"/static/{build_id()}/{path}"


def jdump(obj) -> str:
    """JSON for embedding in <script type="application/json"> (safe against </script>)."""
    return Markup(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


templates.env.globals.update(asset=asset, SCRIPTS=SCRIPTS, GRADE_LABELS=content.GRADE_LABELS, DEV=DEV, jdump=jdump,
                             TRACKS=content.TRACKS)
templates.env.filters["level"] = gamify.level_for


# ------------------------------------------------------------------ users
USER_COLS = [db.users.c.id, db.users.c.username, db.users.c.email, db.users.c.display_name, db.users.c.xp,
             db.users.c.created_at]


def load_session(request: Request):
    """Resolve the session cookie to (user, settings, session row) in one query."""
    tok = request.cookies.get(SESSION_COOKIE)
    if not tok:
        return None
    th = token_hash(tok)
    now = int(time.time())
    with db.ro() as c:
        row = c.execute(
            select(db.sessions.c.id_hash, db.sessions.c.csrf, db.sessions.c.expires_at, db.sessions.c.last_seen,
                   *USER_COLS, *[col for col in db.settings.c if col.name != "user_id"])
            .join(db.users, db.users.c.id == db.sessions.c.user_id)
            .join(db.settings, db.settings.c.user_id == db.users.c.id)
            .where(db.sessions.c.id_hash == th)
        ).first()
    if row is None or row.expires_at < now:
        return None
    m = dict(row._mapping)
    if now - m["last_seen"] > 600:  # throttle writes: refresh at most every 10 minutes
        with db.tx() as c:
            exp = max(m["expires_at"], now + SESSION_DAYS * 86400) if m["expires_at"] - now < SESSION_DAYS * 43200 else m["expires_at"]
            c.execute(update(db.sessions).where(db.sessions.c.id_hash == th).values(last_seen=now, expires_at=exp))
    return m


def create_session(c, user_id: int) -> tuple[str, str]:
    tok, csrf = new_token(), new_token()
    now = int(time.time())
    c.execute(db.sessions.insert().values(id_hash=token_hash(tok), user_id=user_id, csrf=csrf, created_at=now,
                                          expires_at=now + SESSION_DAYS * 86400, last_seen=now))
    c.execute(delete(db.sessions).where(db.sessions.c.expires_at < now))
    return tok, csrf


def set_session_cookie(resp, tok: str):
    resp.set_cookie(SESSION_COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, secure=SECURE_COOKIES, samesite="lax", path="/")


def user_of(request: Request):
    return getattr(request.state, "user", None)


def require_user(request: Request):
    u = user_of(request)
    if u is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    return u


def page_user(request: Request):
    """For HTML pages: redirect anonymous visitors to the login page."""
    u = user_of(request)
    if u is None:
        nxt = request.url.path
        raise HTTPException(status_code=303, headers={"Location": f"/login?next={nxt}"})
    return u


# ------------------------------------------------------------------- CSRF
def csrf_token(request: Request) -> str:
    u = user_of(request)
    if u:
        return u["csrf"]
    return request.state.anon_csrf


def check_csrf(request: Request, token: str | None):
    expected = csrf_token(request)
    if not token or not expected or not hmac.compare_digest(str(token), expected):
        raise HTTPException(status_code=403, detail="Security check failed. Refresh the page and try again.")


def api_csrf(request: Request):
    check_csrf(request, request.headers.get("x-csrf-token"))


def render(request: Request, name: str, ctx: dict | None = None, status: int = 200):
    ctx = dict(ctx or {})
    u = user_of(request)
    ctx.setdefault("user", u)
    ctx["csrf"] = csrf_token(request)
    ctx["theme"] = (u or {}).get("theme", "system")
    ctx["path"] = request.url.path
    seg = request.url.path.strip("/").split("/")[0]
    ctx["section"] = SECTIONS.get(seg, seg)
    if u is not None and "due_count" not in ctx:
        with db.ro() as c:
            from . import srs
            ctx["due_count"] = srs.counts(c, u["id"], u["timezone"])["total"]
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def redirect(url: str):
    return RedirectResponse(url, status_code=303)


def ok(**data):
    return JSONResponse({"ok": True, **data})


def err(msg: str, status: int = 400):
    return JSONResponse({"ok": False, "error": msg}, status_code=status)


def mastery_cfg(u) -> dict:
    return {"mastery_reps": u["mastery_reps"], "mastery_accuracy": u["mastery_accuracy"], "mastery_interval": u["mastery_interval"]}
