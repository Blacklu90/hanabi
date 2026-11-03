"""Anki .apkg export and import (no Anki installation needed).

Export writes a classic Anki "collection.anki2" (schema 11) package, which current
Anki, AnkiDroid and AnkiMobile all import. Kanji become notes of a "Hanabi Kanji"
note type with separate fields, so they can be restyled in Anki.

Import reads all three package flavours: collection.anki21b (zstd-compressed,
newest), collection.anki21 and collection.anki2. Field HTML is converted to plain
text (no scripts, styles or remote images ever reach Hanabi). Media is skipped.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import secrets
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

MAX_UPLOAD = 1024 * 1024 * 1024        # 1 GB: decks with recorded audio are big
MAX_UNZIPPED = 4 * 1024 * 1024 * 1024  # guard against zip bombs
MAX_NOTES = 50_000

KANJI_FIELDS = ["Kanji", "Meaning", "Onyomi", "Kunyomi", "Strokes", "Grade", "Words", "Example", "MyHook", "MyNotes", "Hanabi"]
KANJI_FRONT = '<div class="k">{{Kanji}}</div>'
KANJI_BACK = """{{FrontSide}}
<hr id=answer>
<div class="m">{{Meaning}}</div>
<div class="r"><span class="lbl">On</span> {{Onyomi}}<br><span class="lbl">Kun</span> {{Kunyomi}}</div>
<div class="s">{{Strokes}} strokes · {{Grade}}</div>
{{#Words}}<div class="w">{{Words}}</div>{{/Words}}
{{#Example}}<div class="x">{{Example}}</div>{{/Example}}
{{#MyHook}}<div class="h">💡 {{MyHook}}</div>{{/MyHook}}
{{#MyNotes}}<div class="h">✎ {{MyNotes}}</div>{{/MyNotes}}"""
KANJI_CSS = """.card { font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", sans-serif; font-size: 20px; text-align: center; color: #1f1c19; background: #fffdf9; }
.nightMode.card, .night_mode .card { color: #f1ece4; background: #1b1d25; }
.k { font-family: "Noto Serif JP", "Hiragino Mincho ProN", "Yu Mincho", serif; font-size: 110px; line-height: 1.2; }
.m { font-size: 26px; font-weight: bold; margin: 8px 0; }
.r { font-size: 20px; line-height: 1.7; } .lbl { font-size: 13px; opacity: .6; text-transform: uppercase; margin-right: 4px; }
.s { font-size: 14px; opacity: .65; margin: 6px 0; }
.w, .x, .h { font-size: 17px; margin: 10px auto; max-width: 34em; text-align: left; }
.h { background: rgba(185,122,15,.12); border-radius: 10px; padding: 8px 12px; }"""

BASIC_FIELDS = ["Front", "Back", "Extra"]


def _guid() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&()*+,-./:;<=>?@[]^_`{|}~"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _stable_guid(key: str) -> str:
    """Same kanji -> same GUID, so re-importing an updated export updates notes instead of duplicating them."""
    return "hanabi" + hashlib.sha1(key.encode()).hexdigest()[:10]


def _csum(first_field: str) -> int:
    return int(hashlib.sha1(strip_html(first_field).encode()).hexdigest()[:8], 16)


def _model(mid: int, name: str, fields: list[str], qfmt: str, afmt: str, css: str, did: int, now: int) -> dict:
    return {
        "id": mid, "name": name, "type": 0, "mod": now, "usn": -1, "sortf": 0, "did": did,
        "tmpls": [{"name": "Recognition", "ord": 0, "qfmt": qfmt, "afmt": afmt, "bqfmt": "", "bafmt": "", "did": None,
                   "bfont": "", "bsize": 0}],
        "flds": [{"name": f, "ord": i, "sticky": False, "rtl": False, "font": "Arial", "size": 20, "media": []}
                 for i, f in enumerate(fields)],
        "css": css, "latexPre": "\\documentclass[12pt]{article}\n\\begin{document}\n", "latexPost": "\\end{document}",
        "latexsvg": False, "req": [[0, "any", [0]]], "tags": [], "vers": [],
    }


def _deck(did: int, name: str, now: int) -> dict:
    return {"id": did, "name": name, "mod": now, "usn": -1, "lrnToday": [0, 0], "revToday": [0, 0], "newToday": [0, 0],
            "timeToday": [0, 0], "collapsed": False, "browserCollapsed": False, "desc": "Made with Hanabi.", "dyn": 0,
            "conf": 1, "extendNew": 0, "extendRev": 0}


DCONF = {"1": {"id": 1, "mod": 0, "name": "Default", "usn": 0, "maxTaken": 60, "autoplay": True, "timer": 0, "replayq": True,
               "new": {"bury": False, "delays": [1.0, 10.0], "initialFactor": 2500, "ints": [1, 4, 0], "order": 1, "perDay": 20},
               "rev": {"bury": False, "ease4": 1.3, "ivlFct": 1.0, "maxIvl": 36500, "perDay": 200, "hardFactor": 1.2},
               "lapse": {"delays": [10.0], "leechAction": 1, "leechFails": 8, "minInt": 1, "mult": 0.0}, "dyn": False}}

SCHEMA = """
CREATE TABLE col (id integer primary key, crt integer not null, mod integer not null, scm integer not null, ver integer not null,
  dty integer not null, usn integer not null, ls integer not null, conf text not null, models text not null, decks text not null,
  dconf text not null, tags text not null);
CREATE TABLE notes (id integer primary key, guid text not null, mid integer not null, mod integer not null, usn integer not null,
  tags text not null, flds text not null, sfld integer not null, csum integer not null, flags integer not null, data text not null);
CREATE TABLE cards (id integer primary key, nid integer not null, did integer not null, ord integer not null, mod integer not null,
  usn integer not null, type integer not null, queue integer not null, due integer not null, ivl integer not null,
  factor integer not null, reps integer not null, lapses integer not null, left integer not null, odue integer not null,
  odid integer not null, flags integer not null, data text not null);
CREATE TABLE revlog (id integer primary key, cid integer not null, usn integer not null, ease integer not null, ivl integer not null,
  lastIvl integer not null, factor integer not null, time integer not null, type integer not null);
CREATE TABLE graves (usn integer not null, oid integer not null, type integer not null);
CREATE INDEX ix_notes_usn on notes (usn); CREATE INDEX ix_cards_usn on cards (usn); CREATE INDEX ix_revlog_usn on revlog (usn);
CREATE INDEX ix_cards_nid on cards (nid); CREATE INDEX ix_cards_sched on cards (did, queue, due);
CREATE INDEX ix_revlog_cid on revlog (cid); CREATE INDEX ix_notes_csum on notes (csum);
"""


def build_apkg(deck_name: str, notes: list[dict]) -> bytes:
    """notes: [{"kind": "kanji"|"basic", "fields": [...], "tags": "...", "key": "stable id"}] -> .apkg bytes."""
    now = int(time.time())
    base_ms = now * 1000
    did = base_ms + 1
    mids = {"kanji": 1_700_000_000_001, "basic": 1_700_000_000_002}  # fixed per note type so re-imports match
    models = {}
    if any(n["kind"] == "kanji" for n in notes):
        models[str(mids["kanji"])] = _model(mids["kanji"], "Hanabi Kanji", KANJI_FIELDS, KANJI_FRONT, KANJI_BACK, KANJI_CSS, did, now)
    if any(n["kind"] == "basic" for n in notes) or not models:
        models[str(mids["basic"])] = _model(mids["basic"], "Hanabi Basic", BASIC_FIELDS, "{{Front}}",
                                            "{{FrontSide}}\n<hr id=answer>\n{{Back}}{{#Extra}}<br><br><small>{{Extra}}</small>{{/Extra}}",
                                            ".card { font-family: sans-serif; font-size: 24px; text-align: center; white-space: pre-wrap; }", did, now)
    decks = {"1": _deck(1, "Default", now), str(did): _deck(did, deck_name, now)}
    conf = {"nextPos": len(notes) + 1, "estTimes": True, "activeDecks": [1], "sortType": "noteFld", "timeLim": 0,
            "sortBackwards": False, "addToCur": True, "curDeck": 1, "newSpread": 0, "dueCounts": True,
            "curModel": next(iter(models)), "collapseTime": 1200, "schedVer": 2}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "collection.anki2"
        con = sqlite3.connect(path)
        con.executescript(SCHEMA)
        con.execute("INSERT INTO col VALUES (1,?,?,?,11,0,0,0,?,?,?,?,?)",
                    (now - now % 86400, base_ms, base_ms, json.dumps(conf), json.dumps(models), json.dumps(decks),
                     json.dumps(DCONF), "{}"))
        rows_n, rows_c = [], []
        for i, n in enumerate(notes):
            nid = base_ms + 10 + i * 2
            flds = [str(f or "") for f in n["fields"]]
            tags = f" {n['tags'].strip()} " if n.get("tags") else ""
            rows_n.append((nid, _stable_guid(n["key"]) if n.get("key") else _guid(), mids[n["kind"]], now, -1, tags,
                           "\x1f".join(flds), strip_html(flds[0]), _csum(flds[0]), 0, ""))
            rows_c.append((nid + 1, nid, did, 0, now, -1, 0, 0, i + 1, 0, 0, 0, 0, 0, 0, 0, 0, ""))
        con.executemany("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows_n)
        con.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows_c)
        con.commit()
        con.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(path, "collection.anki2")
            z.writestr("media", "{}")
        return buf.getvalue()


# ------------------------------------------------------------------ import
_BR = re.compile(r"<\s*(br|/div|/p|/li|/tr|hr)[^>]*>", re.I)
_DROP = re.compile(r"<(script|style)[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SOUND = re.compile(r"\[sound:[^\]]*\]")


def strip_html(s: str) -> str:
    s = _DROP.sub("", s or "")
    s = _BR.sub("\n", s)
    s = _TAG.sub("", s)
    s = _SOUND.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


class ImportError_(Exception):
    pass


def open_zip(src) -> zipfile.ZipFile:
    """src: bytes or a seekable file (uploads are streamed to disk, so big decks don't fill memory)."""
    f = io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src
    f.seek(0, 2)
    if f.tell() > MAX_UPLOAD:
        raise ImportError_("That file is too big (limit 1 GB).")
    f.seek(0)
    try:
        z = zipfile.ZipFile(f)
    except zipfile.BadZipFile:
        raise ImportError_("That isn't an Anki package (.apkg).") from None
    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
        raise ImportError_("That package is too big when unpacked.")
    return z


def _open_collection(src, tmp: Path) -> sqlite3.Connection:
    z = src if isinstance(src, zipfile.ZipFile) else open_zip(src)
    names = set(z.namelist())
    target = tmp / "collection.db"
    if "collection.anki21b" in names:
        try:
            import zstandard
        except ImportError:
            raise ImportError_("This package uses Anki's newest format; reinstall Hanabi to add support for it.") from None
        raw = z.read("collection.anki21b")
        target.write_bytes(zstandard.ZstdDecompressor().decompressobj().decompress(raw))
    elif "collection.anki21" in names:
        target.write_bytes(z.read("collection.anki21"))
    elif "collection.anki2" in names:
        target.write_bytes(z.read("collection.anki2"))
    else:
        raise ImportError_("No Anki collection found inside that file.")
    con = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    # Newer Anki schemas use a custom "unicase" collation; register a compatible one.
    con.create_collation("unicase", lambda x, y: (x.casefold() > y.casefold()) - (x.casefold() < y.casefold()))
    try:
        con.execute("SELECT count(*) FROM notes").fetchone()
    except sqlite3.DatabaseError:
        raise ImportError_("The Anki collection inside that file couldn't be read.") from None
    return con


def _field_names(con: sqlite3.Connection) -> dict[int, list[str]]:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "fields" in tables:  # schema 15+
        out: dict[int, list[str]] = {}
        for ntid, ord_, name in sorted(con.execute("SELECT ntid, ord, name FROM fields")):
            out.setdefault(ntid, []).append(name)
        return out
    models = json.loads(con.execute("SELECT models FROM col").fetchone()[0] or "{}")
    return {int(k): [f["name"] for f in sorted(m["flds"], key=lambda f: f["ord"])] for k, m in models.items()}


def _deck_name(con: sqlite3.Connection) -> str | None:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        dids = [r[0] for r in con.execute("SELECT did, count(*) n FROM cards GROUP BY did ORDER BY n DESC LIMIT 1")]
        if not dids:
            return None
        if "decks" in tables:
            r = con.execute("SELECT name FROM decks WHERE id=?", (dids[0],)).fetchone()
            return r[0].replace("\x1f", "::") if r else None
        decks = json.loads(con.execute("SELECT decks FROM col").fetchone()[0] or "{}")
        return decks.get(str(dids[0]), {}).get("name")
    except (sqlite3.DatabaseError, ValueError):
        return None


FRONT_NAMES = ("front", "kanji", "expression", "word", "vocab", "japanese", "question", "term", "character")
BACK_NAMES = ("back", "meaning", "answer", "english", "definition", "translation", "glossary")
READ_NAMES = ("reading", "kana", "furigana", "pronunciation", "onyomi", "kunyomi", "hiragana")


def _pick(names: list[str], prefs: tuple, default: int | None) -> int | None:
    low = [n.lower() for n in names]
    for p in prefs:
        for i, n in enumerate(low):
            if n == p or n.startswith(p):
                return i
    return default


def parse_apkg(data: bytes) -> tuple[str | None, list[dict], int]:
    """Returns (deck name, [{front, back, extra}], skipped)."""
    with tempfile.TemporaryDirectory() as tmp:
        con = _open_collection(data, Path(tmp))
        try:
            fields = _field_names(con)
            name = _deck_name(con)
            out, skipped = [], 0
            for mid, flds in con.execute("SELECT mid, flds FROM notes ORDER BY id LIMIT ?", (MAX_NOTES,)):
                vals = flds.split("\x1f")
                names = fields.get(mid) or [f"Field {i + 1}" for i in range(len(vals))]
                fi = _pick(names, FRONT_NAMES, 0)
                bi = _pick(names, BACK_NAMES, 1 if len(vals) > 1 else None)
                ri = _pick(names, READ_NAMES, None)
                front = strip_html(vals[fi]) if fi is not None and fi < len(vals) else ""
                back = strip_html(vals[bi]) if bi is not None and bi < len(vals) and bi != fi else ""
                extra_parts = []
                if ri is not None and ri < len(vals) and ri not in (fi, bi) and strip_html(vals[ri]):
                    extra_parts.append(strip_html(vals[ri]))
                for i, v in enumerate(vals):
                    if i not in (fi, bi, ri) and strip_html(v):
                        extra_parts.append(f"{names[i] if i < len(names) else 'Field'}: {strip_html(v)}")
                if not front or (not back and not extra_parts):
                    skipped += 1
                    continue
                if not back:
                    back, extra_parts = extra_parts[0], extra_parts[1:]
                out.append({"front": front[:2000], "back": back[:5000], "extra": "\n".join(extra_parts)[:5000]})
            return name, out, skipped
        finally:
            con.close()


def free_name(base: str, taken: set[str]) -> str:
    name, n = base, 2
    while name in taken:
        name = f"{base} ({n})"
        n += 1
    return name


# ------------------------------------------------------- full import (v5)
def _pb(buf: bytes) -> dict[int, list]:
    """Minimal protobuf decoder: {field_number: [values]} (varints as int, length-delimited as bytes)."""
    out: dict[int, list] = {}
    i, n = 0, len(buf)

    def varint():
        nonlocal i
        shift = result = 0
        while True:
            b = buf[i]
            i += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result
            shift += 7

    while i < n:
        key = varint()
        field, wt = key >> 3, key & 7
        if wt == 0:
            v = varint()
        elif wt == 2:
            ln = varint()
            v = buf[i:i + ln]
            i += ln
        elif wt == 1:
            v = buf[i:i + 8]
            i += 8
        elif wt == 5:
            v = buf[i:i + 4]
            i += 4
        else:
            raise ValueError("unsupported protobuf wire type")
        out.setdefault(field, []).append(v)
    return out


def _s(v, default=""):
    return v[0].decode("utf-8", "replace") if v else default


def _models(con: sqlite3.Connection) -> dict[int, dict]:
    """Note types with their templates and CSS, from either schema."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out: dict[int, dict] = {}
    if "notetypes" in tables:  # schema 15+ (Anki 2.1.28+): protobuf configs
        for ntid, name, config in con.execute("SELECT id, name, config FROM notetypes"):
            cfg = _pb(config or b"")
            out[ntid] = {"name": name, "kind": (cfg.get(1) or [0])[0], "css": _s(cfg.get(3)), "tmpls": [], "flds": []}
        for ntid, ord_, name, config in sorted(con.execute("SELECT ntid, ord, name, config FROM templates")):
            if ntid in out:
                cfg = _pb(config or b"")
                out[ntid]["tmpls"].append({"name": name, "ord": ord_, "qfmt": _s(cfg.get(1)), "afmt": _s(cfg.get(2))})
        for ntid, ord_, name in sorted(con.execute("SELECT ntid, ord, name FROM fields")):
            if ntid in out:
                out[ntid]["flds"].append(name)
        return out
    models = json.loads(con.execute("SELECT models FROM col").fetchone()[0] or "{}")
    for k, m in models.items():
        out[int(k)] = {"name": m.get("name", ""), "kind": int(m.get("type", 0)), "css": m.get("css", ""),
                       "tmpls": [{"name": t.get("name", ""), "ord": t.get("ord", i), "qfmt": t.get("qfmt", ""), "afmt": t.get("afmt", "")}
                                 for i, t in enumerate(sorted(m.get("tmpls", []), key=lambda t: t.get("ord", 0)))],
                       "flds": [f["name"] for f in sorted(m.get("flds", []), key=lambda f: f.get("ord", 0))]}
    return out


MAX_MEDIA = 3 * 1024 * 1024 * 1024


def iter_media(z: zipfile.ZipFile):
    """Yield (name, mime, bytes) for the package's images, fonts and audio (video is skipped)."""
    from .anki_render import media_type
    names = set(z.namelist())
    if "media" not in names:
        return
    version = (_pb(z.read("meta")).get(1) or [0])[0] if "meta" in names else 0
    raw = z.read("media")
    entries: list[tuple[str, str]] = []  # (name, zip member)
    if version >= 3:
        import zstandard
        listing = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
        for idx, e in enumerate(_pb(listing).get(1, [])):
            f = _pb(e)
            entries.append((_s(f.get(1)), str((f.get(255) or [idx])[0])))
    else:
        try:
            entries = [(name, member) for member, name in json.loads(raw.decode("utf-8") or "{}").items()]
        except ValueError:
            return
    total = 0
    for name, member in entries:
        mime = media_type(name) if name and "/" not in name and "\\" not in name else None
        if not mime or member not in names:
            continue
        data = z.read(member)
        if version >= 3:
            import zstandard
            data = zstandard.ZstdDecompressor().decompressobj().decompress(data)
        total += len(data)
        if total > MAX_MEDIA:
            return
        yield name, mime, data


def parse_package(src) -> dict:
    """Everything needed to show the deck like Anki: note types and one entry per Anki card.
    Media is read separately with iter_media(result["zip"])."""
    z = src if isinstance(src, zipfile.ZipFile) else open_zip(src)
    with tempfile.TemporaryDirectory() as tmp:
        con = _open_collection(z, Path(tmp))
        try:
            models = _models(con)
            name = _deck_name(con)
            notes = {}
            for nid, mid, flds, tags in con.execute("SELECT id, mid, flds, tags FROM notes"):
                m = models.get(mid)
                if not m:
                    continue
                vals = flds.split("\x1f")
                notes[nid] = {"mid": mid, "fields": {f: (vals[i] if i < len(vals) else "") for i, f in enumerate(m["flds"])},
                              "tags": (tags or "").strip()}
            cards = []
            for nid, ord_ in con.execute("SELECT nid, ord FROM cards ORDER BY due, id LIMIT ?", (MAX_NOTES,)):
                if nid in notes:
                    cards.append({"nid": nid, "ord": ord_, **notes[nid]})
        finally:
            con.close()
    return {"deck": name, "models": models, "cards": cards, "zip": z}
