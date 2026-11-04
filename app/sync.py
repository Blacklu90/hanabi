"""Wi-Fi sync: merge your learning data between two devices on the same network.

One device *hosts*: it shows a one-time code and listens on the local network for a few
minutes (a separate tiny server that only knows the sync endpoints). The other device
*joins* with the host's address and the code. Then both merge each other's data, so both
end up with everything.

Security (Python standard library only):
  * key = PBKDF2-HMAC-SHA256(code, random salt, 200 000 rounds) -> encryption key + MAC key
  * every message: zlib-compressed JSON, XOR with a SHAKE-256 keystream (key + random nonce),
    then HMAC-SHA256 over direction + nonce + ciphertext (encrypt-then-MAC)
  * the code is ~50 bits and never sent; 5 bad messages close the session; one sync per code
Passwords, sessions, email and settings are never sent. Only learning data is.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
import zlib

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import db

VERSION = 1
PORTS = range(8770, 8790)
SESSION_SECONDS = 600
MAX_BAD = 5
MAX_BODY = 1_500_000_000  # 1.5 GB (big Anki decks with audio)
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L
PBKDF2_ROUNDS = 200_000


class SyncError(Exception):
    pass


# ------------------------------------------------------------------ crypto
def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def norm_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch in CODE_ALPHABET)


def derive(code: str, salt: bytes) -> tuple[bytes, bytes]:
    k = hashlib.pbkdf2_hmac("sha256", norm_code(code).encode(), salt, PBKDF2_ROUNDS, dklen=64)
    return k[:32], k[32:]


def _xor(data: bytes, key: bytes, nonce: bytes) -> bytes:
    if not data:
        return b""
    ks = hashlib.shake_256(key + nonce).digest(len(data))
    return (int.from_bytes(data, "big") ^ int.from_bytes(ks, "big")).to_bytes(len(data), "big")


def seal(obj, keys: tuple[bytes, bytes], direction: bytes) -> bytes:
    enc, mac = keys
    nonce = secrets.token_bytes(16)
    ct = _xor(zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), 6), enc, nonce)
    tag = hmac.new(mac, b"shuinkan-sync-v1|" + direction + b"|" + nonce + ct, hashlib.sha256).digest()
    return nonce + tag + ct


def unseal(blob: bytes, keys: tuple[bytes, bytes], direction: bytes):
    enc, mac = keys
    if len(blob) < 48:
        raise SyncError("Message too short.")
    nonce, tag, ct = blob[:16], blob[16:48], blob[48:]
    want = hmac.new(mac, b"shuinkan-sync-v1|" + direction + b"|" + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, want):
        raise SyncError("Wrong code (or the message was changed on the way).")
    return json.loads(zlib.decompress(_xor(ct, enc, nonce)))


# ---------------------------------------------------------------- snapshot
def device_name() -> str:
    if os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA"):
        return "Android phone"
    return (platform.node() or "Computer")[:60]


def _ensure_uids(c, uid: int) -> None:
    for t in (db.custom_cards, db.anki_models, db.user_dicts):
        for (rid,) in c.execute(select(t.c.id).where(t.c.user_id == uid, t.c.uid.is_(None))).all():
            c.execute(update(t).where(t.c.id == rid).values(uid=secrets.token_hex(16)))


def _rows(c, stmt) -> list[dict]:
    return [dict(r._mapping) for r in c.execute(stmt)]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def manifest(c, uid: int) -> dict:
    """What big things this device already has (so they're only sent when missing)."""
    _ensure_uids(c, uid)
    m, d = db.anki_media.c, db.decks.c
    media = [f"{r.deck}\x00{r.name}" for r in c.execute(select(d.name.label("deck"), m.name).join(db.decks, d.id == m.deck_id)
                                                       .where(m.user_id == uid))]
    dicts = list(c.execute(select(db.user_dicts.c.uid).where(db.user_dicts.c.user_id == uid)).scalars())
    return {"media": media, "dicts": dicts}


def export(c, uid: int, other: dict | None = None) -> dict:
    """Everything that is learning data, keyed so another device can match it up."""
    _ensure_uids(c, uid)
    other = other or {"media": [], "dicts": []}
    deck_names = dict(c.execute(select(db.decks.c.id, db.decks.c.name).where(db.decks.c.user_id == uid)).all())
    cc = db.custom_cards.c
    custom_uid = dict(c.execute(select(cc.id, cc.uid).where(cc.user_id == uid)).all())
    model_uid = dict(c.execute(select(db.anki_models.c.id, db.anki_models.c.uid).where(db.anki_models.c.user_id == uid)).all())

    def card_key(track, item):
        return [track, custom_uid.get(int(item)) if track == "card" else item]

    s = db.srs_cards.c
    cards, card_keys = [], {}
    for r in c.execute(select(db.srs_cards).where(s.user_id == uid)):
        k = card_key(r.track, r.item)
        if k[1] is None:
            continue
        card_keys[r.id] = k
        cards.append({"key": k, "deck": deck_names.get(r.deck_id), **{f: getattr(r, f) for f in (
            "ease", "interval_days", "reps", "lapses", "total_reviews", "total_correct", "state", "due_at", "last_review_at",
            "created_at", "position", "suspended", "buried_until", "introduced_at")}})
    rv = db.reviews.c
    reviews = [{"key": card_keys[r.card_id], "rating": r.rating, "interval_days": r.interval_days, "created_at": r.created_at}
               for r in c.execute(select(rv.card_id, rv.rating, rv.interval_days, rv.created_at).where(rv.user_id == uid))
               if r.card_id in card_keys]
    m, d = db.anki_media.c, db.decks.c
    have = set(other.get("media", []))
    media = [{"deck": r.deck, "name": r.name, "mime": r.mime, "data": _b64(r.data)}
             for r in c.execute(select(d.name.label("deck"), m.name, m.mime, m.data).join(db.decks, d.id == m.deck_id)
                                .where(m.user_id == uid))
             if f"{r.deck}\x00{r.name}" not in have]
    have_dicts = set(other.get("dicts", []))
    dicts = []
    for r in c.execute(select(db.user_dicts).where(db.user_dicts.c.user_id == uid)):
        if r.uid in have_dicts:
            continue
        e = db.user_dict_entries.c
        dicts.append({"uid": r.uid, "title": r.title, "kind": r.kind, "enabled": r.enabled, "created_at": r.created_at,
                      "entries": [list(x) for x in c.execute(select(e.term, e.reading, e.meaning).where(e.dict_id == r.id))]})
    qa = db.quiz_attempts
    quizzes = _rows(c, select(qa).where(qa.c.user_id == uid))
    qd = db.quiz_details.c
    for q in quizzes:
        q.pop("user_id")
        q["details"] = _rows(c, select(qd.idx, qd.answer, qd.correct, qd.answered_at).where(qd.attempt_id == q["id"]))
    games = _rows(c, select(db.game_sessions).where(db.game_sessions.c.user_id == uid))
    for g in games:
        g.pop("user_id")
    return {
        "v": VERSION, "device": device_name(), "manifest": manifest(c, uid),
        "decks": [{k: v for k, v in r.items() if k not in ("id", "user_id")} for r in _rows(c, select(db.decks).where(db.decks.c.user_id == uid))],
        "cards": cards, "reviews": reviews,
        "progress": [{k: v for k, v in r.items() if k != "user_id"} for r in _rows(c, select(db.progress).where(db.progress.c.user_id == uid))],
        "notes": [{k: v for k, v in r.items() if k != "user_id"} for r in _rows(c, select(db.notes).where(db.notes.c.user_id == uid))],
        "custom": [{"uid": r.uid, "front": r.front, "back": r.back, "extra": r.extra, "source": r.source, "created_at": r.created_at,
                    "model": model_uid.get(r.model_id), "fields_json": r.fields_json, "ord": r.ord, "tags": r.tags}
                   for r in c.execute(select(db.custom_cards).where(cc.user_id == uid))],
        "models": [{"uid": r.uid, "deck": deck_names.get(r.deck_id), "name": r.name, "kind": r.kind, "css": r.css,
                    "tmpls_json": r.tmpls_json, "flds_json": r.flds_json}
                   for r in c.execute(select(db.anki_models).where(db.anki_models.c.user_id == uid))],
        "media": media, "dicts": dicts, "quizzes": quizzes, "games": games,
        "lessons": [[r.lesson, r.completed_at] for r in c.execute(select(db.lesson_completions).where(db.lesson_completions.c.user_id == uid))],
        "xp": [[r.source, r.dedupe_key, r.amount, r.day, r.created_at] for r in c.execute(select(db.xp_events).where(db.xp_events.c.user_id == uid))],
        "activity": [[r.kind, r.text, r.created_at] for r in c.execute(select(db.activity).where(db.activity.c.user_id == uid))],
        "achievements": [[r.code, r.unlocked_at] for r in c.execute(select(db.achievements).where(db.achievements.c.user_id == uid))],
    }


# ------------------------------------------------------------------- merge
CARD_FIELDS = ("ease", "interval_days", "reps", "lapses", "total_reviews", "total_correct", "state", "due_at", "last_review_at",
               "position", "suspended", "buried_until", "introduced_at")


def merge(c, uid: int, snap: dict) -> dict:
    """Merge another device's snapshot into this account. Never deletes anything here."""
    if snap.get("v") != VERSION:
        raise SyncError("The other device runs a different version of Shuinkan. Update both, then try again.")
    _ensure_uids(c, uid)
    st = {k: 0 for k in ("cards_new", "cards_updated", "reviews", "notes", "decks", "custom", "media", "dicts", "quizzes",
                         "lessons", "xp", "achievements")}
    d = db.decks.c
    decks = dict(c.execute(select(d.name, d.id).where(d.user_id == uid)).all())

    def deck_id(name):
        if name is None:
            return None
        if name not in decks:
            src = next((x for x in snap["decks"] if x["name"] == name), {"name": name})
            decks[name] = c.execute(db.decks.insert().values(
                user_id=uid, name=name[:80], new_per_day=src.get("new_per_day", 10), max_reviews=src.get("max_reviews", 200),
                created_at=src.get("created_at") or int(time.time()))).inserted_primary_key[0]
            st["decks"] += 1
        return decks[name]

    for x in snap["decks"]:
        deck_id(x["name"])
    # Anki note types, then cards that use them
    am = db.anki_models.c
    models = dict(c.execute(select(am.uid, am.id).where(am.user_id == uid)).all())
    for x in snap["models"]:
        if x["uid"] not in models and x["deck"] is not None:
            models[x["uid"]] = c.execute(db.anki_models.insert().values(
                user_id=uid, deck_id=deck_id(x["deck"]), name=x["name"], kind=x["kind"], css=x["css"], tmpls_json=x["tmpls_json"],
                flds_json=x["flds_json"], uid=x["uid"])).inserted_primary_key[0]
    cc = db.custom_cards.c
    customs = dict(c.execute(select(cc.uid, cc.id).where(cc.user_id == uid)).all())
    for x in snap["custom"]:
        if x["uid"] and x["uid"] not in customs:
            customs[x["uid"]] = c.execute(db.custom_cards.insert().values(
                user_id=uid, front=x["front"], back=x["back"], extra=x["extra"], source=x["source"], created_at=x["created_at"],
                model_id=models.get(x["model"]), fields_json=x["fields_json"], ord=x["ord"], tags=x["tags"], uid=x["uid"])).inserted_primary_key[0]
            st["custom"] += 1
    # media
    m = db.anki_media.c
    for x in snap["media"]:
        if x["deck"] in decks or any(dk["name"] == x["deck"] for dk in snap["decks"]):
            r = c.execute(sqlite_insert(db.anki_media).values(user_id=uid, deck_id=deck_id(x["deck"]), name=x["name"], mime=x["mime"],
                                                              data=base64.b64decode(x["data"])).on_conflict_do_nothing())
            st["media"] += r.rowcount
    # cards: the copy reviewed most recently wins
    s = db.srs_cards.c
    local = {(r.track, r.item): r for r in c.execute(select(db.srs_cards).where(s.user_id == uid))}

    def local_item(key):
        track, item = key
        if track == "card":
            cid = customs.get(item)
            return str(cid) if cid else None
        return item

    card_ids = {}
    for x in snap["cards"]:
        item = local_item(x["key"])
        if item is None:
            continue
        track = x["key"][0]
        mine = local.get((track, item))
        vals = {f: x[f] for f in CARD_FIELDS}
        if mine is None:
            card_ids[(track, item)] = c.execute(db.srs_cards.insert().values(
                user_id=uid, track=track, item=item, created_at=x["created_at"], deck_id=deck_id(x["deck"]), **vals)).inserted_primary_key[0]
            st["cards_new"] += 1
        else:
            card_ids[(track, item)] = mine.id
            if (x["last_review_at"] or 0, x["total_reviews"]) > (mine.last_review_at or 0, mine.total_reviews):
                c.execute(update(db.srs_cards).where(s.id == mine.id).values(deck_id=deck_id(x["deck"]) if x["deck"] else mine.deck_id, **vals))
                st["cards_updated"] += 1
    for (track, item), r in local.items():
        card_ids.setdefault((track, item), r.id)
    # review history: union
    rv = db.reviews.c
    seen = {(r.card_id, r.created_at, r.rating) for r in c.execute(select(rv.card_id, rv.created_at, rv.rating).where(rv.user_id == uid))}
    for x in snap["reviews"]:
        item = local_item(x["key"])
        cid = card_ids.get((x["key"][0], item)) if item else None
        if cid and (cid, x["created_at"], x["rating"]) not in seen:
            c.execute(db.reviews.insert().values(user_id=uid, card_id=cid, rating=x["rating"], interval_days=x["interval_days"],
                                                 created_at=x["created_at"]))
            seen.add((cid, x["created_at"], x["rating"]))
            st["reviews"] += 1
    # per-item stats: keep the fuller record
    p = db.progress.c
    prog = {(r.track, r.item): r for r in c.execute(select(db.progress).where(p.user_id == uid))}
    for x in snap["progress"]:
        mine = prog.get((x["track"], x["item"]))
        if mine is None:
            c.execute(db.progress.insert().values(user_id=uid, **x))
        elif x["attempts"] > mine.attempts:
            c.execute(update(db.progress).where(p.user_id == uid, p.track == x["track"], p.item == x["item"]).values(
                attempts=x["attempts"], correct=x["correct"], updated_at=x["updated_at"],
                mastered_at=min(filter(None, (x["mastered_at"], mine.mastered_at)), default=None)))
    # notes: newest edit wins
    n = db.notes.c
    notes = {(r.track, r.item): r.updated_at for r in c.execute(select(n.track, n.item, n.updated_at).where(n.user_id == uid))}
    for x in snap["notes"]:
        k = (x["track"], x["item"])
        if k not in notes:
            c.execute(db.notes.insert().values(user_id=uid, **x))
            st["notes"] += 1
        elif x["updated_at"] > notes[k]:
            c.execute(update(db.notes).where(n.user_id == uid, n.track == x["track"], n.item == x["item"]).values(
                meaning=x["meaning"], mnemonic=x["mnemonic"], notes=x["notes"], updated_at=x["updated_at"]))
            st["notes"] += 1
    # your own dictionaries
    have_dicts = set(c.execute(select(db.user_dicts.c.uid).where(db.user_dicts.c.user_id == uid)).scalars())
    for x in snap["dicts"]:
        if x["uid"] in have_dicts:
            continue
        did = c.execute(db.user_dicts.insert().values(user_id=uid, title=x["title"], kind=x["kind"], entries=len(x["entries"]),
                                                      enabled=x["enabled"], created_at=x["created_at"], uid=x["uid"])).inserted_primary_key[0]
        for i in range(0, len(x["entries"]), 500):
            c.execute(db.user_dict_entries.insert(), [{"dict_id": did, "term": t, "reading": rd, "meaning": mn}
                                                      for t, rd, mn in x["entries"][i:i + 500]])
        st["dicts"] += 1
    # quiz and game history (ids are random, so they match across devices)
    for q in snap["quizzes"]:
        details = q.pop("details", [])
        if c.execute(sqlite_insert(db.quiz_attempts).values(user_id=uid, **q).on_conflict_do_nothing()).rowcount:
            st["quizzes"] += 1
            for dt in details:
                c.execute(sqlite_insert(db.quiz_details).values(attempt_id=q["id"], **dt).on_conflict_do_nothing())
    for g in snap["games"]:
        c.execute(sqlite_insert(db.game_sessions).values(user_id=uid, **g).on_conflict_do_nothing())
    for lesson, at in snap["lessons"]:
        st["lessons"] += c.execute(sqlite_insert(db.lesson_completions).values(user_id=uid, lesson=lesson, completed_at=at)
                                   .on_conflict_do_nothing()).rowcount
    for source, key, amount, day, at in snap["xp"]:
        st["xp"] += c.execute(sqlite_insert(db.xp_events).values(user_id=uid, source=source, dedupe_key=key, amount=amount, day=day,
                                                                 created_at=at).on_conflict_do_nothing()).rowcount
    a = db.activity.c
    acts = {(r.kind, r.text, r.created_at) for r in c.execute(select(a.kind, a.text, a.created_at).where(a.user_id == uid))}
    for kind, text_, at in snap["activity"]:
        if (kind, text_, at) not in acts:
            c.execute(db.activity.insert().values(user_id=uid, kind=kind, text=text_, created_at=at))
    for code, at in snap["achievements"]:
        st["achievements"] += c.execute(sqlite_insert(db.achievements).values(user_id=uid, code=code, unlocked_at=at)
                                        .on_conflict_do_nothing()).rowcount
    total = c.execute(select(func.coalesce(func.sum(db.xp_events.c.amount), 0)).where(db.xp_events.c.user_id == uid)).scalar()
    c.execute(update(db.users).where(db.users.c.id == uid).values(xp=total))
    return st


def log(c, uid: int, peer: str, role: str, stats: dict) -> None:
    c.execute(db.sync_log.insert().values(user_id=uid, peer=peer[:80], role=role, stats_json=json.dumps(stats), at=int(time.time())))


# ------------------------------------------------------------------ network
def lan_addresses() -> list[str]:
    ips = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outgoing interface
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]


class HostSession:
    def __init__(self, uid: int):
        self.uid = uid
        self.code = new_code()
        self.salt = secrets.token_bytes(16)
        self.keys = derive(self.code, self.salt)
        self.expires = time.time() + SESSION_SECONDS
        self.bad = 0
        self.state = "waiting"  # waiting | syncing | done | closed
        self.result: dict | None = None
        self.error = ""
        self.peer = ""
        self.port = 0
        self.server = None
        self.lock = threading.Lock()

    def alive(self) -> bool:
        return self.state in ("waiting", "syncing") and time.time() < self.expires

    def strike(self):
        self.bad += 1
        if self.bad >= MAX_BAD:
            self.close("Too many wrong codes — sync was closed. Start again for a new code.")

    def close(self, error: str = ""):
        if self.state in ("waiting", "syncing"):
            self.state = "closed" if error else "done"
        if error:
            self.error = error
        if self.server:
            self.server.should_exit = True


def _later(seconds: float, fn) -> None:
    t = threading.Timer(seconds, fn)
    t.daemon = True  # never keeps the app from quitting
    t.start()


_host: dict[int, HostSession] = {}
_host_lock = threading.Lock()


def _listener_app(sess: HostSession):
    """A tiny ASGI app with only the sync endpoints, for the local network."""

    async def read_body(receive) -> bytes:
        chunks, size = [], 0
        while True:
            msg = await receive()
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY:
                raise SyncError("Too much data.")
            chunks.append(chunk)
            if not msg.get("more_body"):
                return b"".join(chunks)

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return

        async def reply(status, body: bytes, ctype="application/octet-stream"):
            await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", ctype.encode()),
                                                                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        path, method = scope["path"], scope["method"]
        if method != "POST" or not path.startswith("/shuinkan-sync/"):
            return await reply(404, b"Not found", "text/plain")
        if not sess.alive():
            return await reply(410, json.dumps({"error": "This sync code has expired. Start a new one."}).encode(), "application/json")
        try:
            body = await read_body(receive)
        except SyncError as e:
            return await reply(413, json.dumps({"error": str(e)}).encode(), "application/json")
        if path == "/shuinkan-sync/hello":
            return await reply(200, json.dumps({"v": VERSION, "salt": _b64(sess.salt), "device": device_name()}).encode(), "application/json")
        try:
            msg = unseal(body, sess.keys, b"c2s")
        except (SyncError, ValueError, zlib.error):
            sess.strike()
            return await reply(403, json.dumps({"error": "Wrong code."}).encode(), "application/json")
        import asyncio
        if path == "/shuinkan-sync/manifest":
            with db.tx() as c:  # may assign stable ids
                out = manifest(c, sess.uid)
            return await reply(200, seal(out, sess.keys, b"s2c"))
        if path == "/shuinkan-sync/exchange":
            with sess.lock:
                if sess.state != "waiting":
                    return await reply(409, json.dumps({"error": "This code was already used."}).encode(), "application/json")
                sess.state = "syncing"
            try:
                def work():
                    with db.tx() as c:
                        stats = merge(c, sess.uid, msg)
                        log(c, sess.uid, msg.get("device", "Other device"), "host", stats)
                        mine = export(c, sess.uid, msg.get("manifest"))
                    return stats, mine
                stats, mine = await asyncio.get_running_loop().run_in_executor(None, work)
                sess.peer, sess.result = msg.get("device", "Other device"), stats
                out = seal(mine, sess.keys, b"s2c")
                sess.state = "done"
                _later(3, sess.close)  # let the reply finish, then stop listening
                return await reply(200, out)
            except Exception as e:  # noqa: BLE001 — report any merge problem to both sides
                sess.close(f"Sync failed: {e}")
                return await reply(500, json.dumps({"error": f"Sync failed on the other device: {e}"}).encode(), "application/json")
        return await reply(404, b"Not found", "text/plain")

    return app


def start_host(uid: int, bind: str = "0.0.0.0") -> HostSession:
    import uvicorn
    with _host_lock:
        old = _host.get(uid)
        if old:
            old.close("Replaced by a new code.")
        sess = HostSession(uid)
        for port in PORTS:
            with socket.socket() as s:
                try:
                    s.bind((bind, port))
                except OSError:
                    continue
            sess.port = port
            break
        else:
            raise SyncError("No free network port for syncing.")
        sess.server = uvicorn.Server(uvicorn.Config(_listener_app(sess), host=bind, port=sess.port, log_level="warning",
                                                    lifespan="off", loop="asyncio", http="h11", ws="none"))
        sess.server.install_signal_handlers = lambda: None  # we're not the main thread
        threading.Thread(target=sess.server.run, name="sync-listener", daemon=True).start()

        def expire():
            if sess.alive():
                return
            sess.close("" if sess.state == "done" else "The code expired.")
        _later(SESSION_SECONDS + 1, expire)
        _host[uid] = sess
        for _ in range(100):
            if sess.server.started:
                break
            time.sleep(0.03)
        return sess


def qr_link(sess: "HostSession") -> str:
    addrs = ",".join(f"{ip}:{sess.port}" for ip in lan_addresses())
    return f"shuinkan://sync?a={addrs}&c={norm_code(sess.code)}"


def qr_svg(uid: int) -> bytes | None:
    """The pairing link as a QR code (scan it with Shuinkan on the phone, or the phone's camera)."""
    import io as _io
    import segno
    sess = _host.get(uid)
    if not sess or not sess.alive():
        return None
    buf = _io.BytesIO()
    segno.make(qr_link(sess), error="m").save(buf, kind="svg", scale=7, border=3, dark="#1f1c19", light="#ffffff",
                                              title="Shuinkan sync code")
    return buf.getvalue()


def host_status(uid: int) -> dict | None:
    sess = _host.get(uid)
    if not sess:
        return None
    return {"state": sess.state if (sess.alive() or sess.state in ("done", "closed")) else "closed",
            "code": sess.code if sess.alive() else "", "port": sess.port, "addresses": lan_addresses(),
            "expires_in": max(0, int(sess.expires - time.time())), "result": sess.result, "peer": sess.peer,
            "error": sess.error or ("" if sess.alive() or sess.state == "done" else "The code expired.")}


def stop_host(uid: int) -> None:
    sess = _host.pop(uid, None)
    if sess:
        sess.close("Stopped.")


def _post(url: str, body: bytes, timeout: float) -> bytes:
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — plain http on your own network, by design
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:  # noqa: BLE001
            msg = None
        raise SyncError(msg or f"The other device answered with an error ({e.code}).") from None
    except (urllib.error.URLError, OSError) as e:
        raise SyncError("Couldn't reach the other device. Check that both are on the same Wi-Fi, the address is right, "
                        "and the other device is still showing its code.") from e


def parse_address(addr: str) -> tuple[str, int]:
    a = addr.strip().removeprefix("http://").split("/")[0]
    host, _, port = a.rpartition(":") if ":" in a else (a, "", "")
    if not host:
        host, port = a, ""
    try:
        socket.inet_aton(host)
    except OSError:
        if not host.replace("-", "").replace(".", "").isalnum():
            raise SyncError("That doesn't look like an address. It looks like 192.168.1.23:8770.") from None
    return host, int(port) if port.isdigit() else PORTS[0]


def join(uid: int, address: str, code: str) -> dict:
    """Connect to a hosting device, send our data, merge theirs. Returns {'peer', 'received'}.

    `address` may list several addresses separated by commas (a QR code carries all of the host's); the first one
    that answers is used."""
    if len(norm_code(code)) != 10:
        raise SyncError("The code has 10 letters and numbers, like K7Q4M-2XDHP.")
    candidates = [a for a in (x.strip() for x in address.split(",")) if a][:6] or [address]
    last = None
    for a in candidates:
        host, port = parse_address(a)
        base = f"http://{host}:{port}/shuinkan-sync"
        try:
            hello = json.loads(_post(base + "/hello", b"{}", 6 if len(candidates) > 1 else 10))
            break
        except SyncError as e:
            last = e
    else:
        raise last or SyncError("Couldn't reach the other device.")
    if hello.get("v") != VERSION:
        raise SyncError("The other device runs a different version of Shuinkan. Update both, then try again.")
    keys = derive(code, base64.b64decode(hello["salt"]))
    their_manifest = unseal(_post(base + "/manifest", seal({}, keys, b"c2s"), 30), keys, b"s2c")
    with db.tx() as c:  # may assign stable ids
        mine = export(c, uid, their_manifest)
    theirs = unseal(_post(base + "/exchange", seal(mine, keys, b"c2s"), 600), keys, b"s2c")
    with db.tx() as c:
        received = merge(c, uid, theirs)
        log(c, uid, hello.get("device", "Other device"), "join", received)
    return {"peer": hello.get("device", "Other device"), "received": received}
