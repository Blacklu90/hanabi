"""Shuinkan — Japanese in short, focused bursts.  Entry point: uvicorn app.main:app"""
from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from . import db
from .security import ALLOWED_ORIGINS, SECURE_COOKIES, SECURITY_HEADERS, new_token
from .web import CSRF_COOKIE, ROOT, STATIC, load_session, render

log = logging.getLogger("shuinkan")
SAFE = {"GET", "HEAD", "OPTIONS"}
BUILD_SEG = re.compile(r"^b[0-9a-f]{10}[/\\\\]")  # / on Linux, \\ on Windows (Starlette uses OS separators)


class CachedStatic(StaticFiles):
    """Static files: versioned URLs are immutable; everything else revalidates."""

    def __init__(self, *a, max_age: int = 31536000, **kw):
        super().__init__(*a, **kw)
        self.max_age = max_age

    async def get_response(self, path, scope):
        # /static/b0123456789/js/app.js -> js/app.js (any build id is accepted, so old pages keep working)
        versioned = bool(BUILD_SEG.match(path))
        if versioned:
            path = BUILD_SEG.sub("", path, count=1)
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            if versioned or self.max_age < 31536000:
                resp.headers["Cache-Control"] = f"public, max-age={self.max_age}, immutable"
            else:
                resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp


def create_app() -> FastAPI:
    db.init_db()
    app = FastAPI(title="Shuinkan", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def core(request: Request, call_next):
        t0 = time.perf_counter()
        path = request.url.path
        is_static = path.startswith(("/static/", "/strokes/"))
        if request.method not in SAFE:
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                o = urlsplit(origin)
                here = f"{request.url.scheme}://{request.headers.get('host', '')}"
                if f"{o.scheme}://{o.netloc}" != here and f"{o.scheme}://{o.netloc}" not in ALLOWED_ORIGINS:
                    return JSONResponse({"ok": False, "error": "Cross-origin request blocked."}, status_code=403)
        set_anon = None
        if not is_static:
            request.state.user = load_session(request)
            anon = request.cookies.get(CSRF_COOKIE)
            if not anon:
                anon = set_anon = new_token()
            request.state.anon_csrf = anon
        resp: Response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if not is_static:
            # HTML may be kept for back/forward navigation but must be revalidated; API data is never stored.
            resp.headers.setdefault("Cache-Control", "no-store" if path.startswith("/api/") else "private, no-cache")
            if resp.headers.get("content-type", "").startswith("text/html"):
                resp.headers["Speculation-Rules"] = '"/speculation.json"'
            resp.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - t0) * 1000:.1f}"
        if set_anon:
            resp.set_cookie(CSRF_COOKIE, set_anon, httponly=True, secure=SECURE_COOKIES, samesite="lax", path="/")
        return resp

    app.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=5)
    app.mount("/static", CachedStatic(directory=str(STATIC)), name="static")
    # KanjiVG files never change for a given dataset build.
    app.mount("/strokes", CachedStatic(directory=str(ROOT / "data" / "strokes"), max_age=2592000), name="strokes")

    @app.get("/speculation.json", include_in_schema=False)
    def speculation():
        # Chromium prefetches a link when the pointer rests on it (about 200 ms), so pages open instantly.
        rules = {"prefetch": [{"where": {"and": [{"href_matches": "/*"}, {"not": {"href_matches": "/api/*"}},
                                                  {"not": {"href_matches": "/static/*"}}, {"not": {"selector_matches": "[data-no-prefetch]"}}]},
                               "eagerness": "moderate"}]}
        return JSONResponse(rules, media_type="application/speculationrules+json", headers={"Cache-Control": "public, max-age=86400"})

    from . import api, pages, words
    app.include_router(pages.router)
    # Build the word course in the background so the first visit to /words is instant.
    threading.Thread(target=words.course, name="warm-words", daemon=True).start()
    app.include_router(api.router)

    def wants_json(request: Request) -> bool:
        return request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", "")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if exc.status_code in (301, 302, 303, 307) and exc.headers:
            return Response(status_code=exc.status_code, headers=exc.headers)
        if wants_json(request):
            return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)
        titles = {401: "Please log in", 403: "Not allowed", 404: "Page not found", 429: "Slow down a little"}
        return render(request, "error.html", {"code": exc.status_code, "title": titles.get(exc.status_code, "Something went wrong"),
                                              "message": exc.detail if isinstance(exc.detail, str) else ""}, status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if wants_json(request):
            return JSONResponse({"ok": False, "error": "Some of the sent data was not valid."}, status_code=422)
        return render(request, "error.html", {"code": 422, "title": "That didn't look right", "message": "Some of the sent data was not valid."}, status=422)

    @app.exception_handler(Exception)
    async def crash(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        if wants_json(request):
            return JSONResponse({"ok": False, "error": "Something went wrong on our side."}, status_code=500)
        return render(request, "error.html", {"code": 500, "title": "Something went wrong", "message": "It's not you — it's us. Try again in a moment."}, status=500)

    return app


app = create_app()
