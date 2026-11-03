"""Measure real response times against a running Hanabi server.

Usage:  .venv/bin/python -m scripts.benchmark [base_url]
Registers a throw-away user, does a little study so pages have data, then
times each request (wall clock, from this client) and reads the server's own
`Server-Timing` header. Reports median and 95th percentile over N runs.
"""
from __future__ import annotations

import re
import secrets
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
N = 30


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main():
    c = httpx.Client(base_url=BASE, follow_redirects=True, timeout=10)
    tok = re.search(r'name="csrf" value="([^"]+)"', c.get("/register").text).group(1)
    name = "bench" + secrets.token_hex(3)
    c.post("/register", data={"username": name, "email": f"{name}@example.com", "password": "benchmark password", "csrf": tok})
    csrf = re.search(r'<meta name="csrf" content="([^"]+)"', c.get("/dashboard").text).group(1)
    h = {"X-CSRF-Token": csrf}
    for les in ("hiragana-1", "hiragana-2", "katakana-1"):
        c.post("/api/lesson/complete", json={"lesson": les}, headers=h)
    for ch in "日一人大学":
        c.post(f"/api/kanji/{ch}/study", headers=h)
    # a heavy account: every Jōyō kanji in decks, plus a dictionary word
    for g in (1, 2, 3, 4, 5, 6, 8):
        did = c.post("/api/decks", json={"name": f"Grade {g}", "new_per_day": 10, "max_reviews": 200}, headers=h).json()["id"]
        c.post(f"/api/decks/{did}/kanji", json={"grade": g}, headers=h)
    qid = c.post("/api/quiz/start", json={"kind": "kanji-meaning", "pool": "all"}, headers=h).json()["id"]

    targets = [
        ("Landing (anon)", None, "/"),
        ("Dashboard", c, "/dashboard"),
        ("Hiragana course", c, "/learn/hiragana"),
        ("Lesson page", c, "/learn/hiragana/3"),
        ("Vocabulary page", c, "/vocab/katakana"),
        ("Kanji library shell", c, "/kanji"),
        ("Kanji search: all, page 1", c, "/api/kanji/search"),
        ("Kanji search: 'water'", c, "/api/kanji/search?q=water"),
        ("Kanji search: 'にち'", c, "/api/kanji/search?q=にち"),
        ("Kanji search: grade 8, p10", c, "/api/kanji/search?grade=8&page=10"),
        ("Kanji search: status=learning", c, "/api/kanji/search?status=learning"),
        ("Kanji detail 学", c, "/kanji/学"),
        ("Review page", c, "/review"),
        ("Quiz centre", c, "/quiz"),
        ("Quiz runner", c, f"/quiz/{qid}"),
        ("Progress", c, "/progress"),
        ("Settings", c, "/settings"),
        ("Decks page (7 decks, 2136 cards)", c, "/decks"),
        ("Review queue in a deck", c, "/review?deck=2"),
        ("Card browser API (2136 cards)", c, "/api/cards"),
        ("Card browser search 'water'", c, "/api/cards?q=water"),
        ("Dictionary page 'cat'", c, "/dictionary?q=cat"),
        ("Dictionary API 'neko'", c, "/api/dictionary/search?q=neko"),
        ("Dictionary API '学校'", c, "/api/dictionary/search?q=%E5%AD%A6%E6%A0%A1"),
        ("Dictionary API 'to run'", c, "/api/dictionary/search?q=to%20run"),
        ("Export deck .apkg (80 kanji)", c, "/api/decks/1/export.apkg"),
        ("CSS (app.css)", c, "/static/css/app.css"),
        ("Stroke SVG", c, "/strokes/05b66.svg"),
    ]
    anon = httpx.Client(base_url=BASE, timeout=10)
    print(f"{'Request':34} {'median':>8} {'p95':>8} {'server':>8} {'bytes':>8}")
    for label, cl, path in targets:
        cl = cl or anon
        cl.get(path)  # warm
        walls, srv = [], []
        size = 0
        for _ in range(N):
            t0 = time.perf_counter()
            r = cl.get(path, headers={"Accept-Encoding": "gzip"})
            walls.append((time.perf_counter() - t0) * 1000)
            m = re.search(r"dur=([\d.]+)", r.headers.get("server-timing", ""))
            if m:
                srv.append(float(m.group(1)))
            size = len(r.content)
        s = f"{statistics.median(srv):7.1f}ms" if srv else "     —  "
        print(f"{label:34} {statistics.median(walls):6.1f}ms {pct(walls, 95):6.1f}ms {s} {size:8d}")
    # write paths
    walls = []
    qid = c.post("/api/quiz/start", json={"kind": "hiragana-recognition", "pool": "all", "mode": "sprint120"}, headers=h).json()["id"]
    for i in range(N):
        t0 = time.perf_counter()
        c.post(f"/api/quiz/{qid}/answer", json={"idx": i, "choice": 0}, headers=h)
        walls.append((time.perf_counter() - t0) * 1000)
    print(f"{'Quiz answer (POST, checked)':34} {statistics.median(walls):6.1f}ms {pct(walls, 95):6.1f}ms")
    walls = []
    for _ in range(10):
        t0 = time.perf_counter()
        c.post("/api/quiz/start", json={"kind": "mixed", "pool": "all"}, headers=h)
        walls.append((time.perf_counter() - t0) * 1000)
    print(f"{'Quiz start (POST, generate 10 Q)':34} {statistics.median(walls):6.1f}ms {pct(walls, 95):6.1f}ms")


if __name__ == "__main__":
    main()
