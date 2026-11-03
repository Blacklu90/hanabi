"""Dictionary search: built-in JMdict (offline) + dictionaries you import.

Japanese / romaji queries use the indexed `dict_forms` table (exact, then prefix,
then substring as a last resort). English queries use SQLite FTS5 over the
glosses. Results are ranked: exact matches, then common words, then the rest.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile

from sqlalchemy import func, or_, select, text

from . import content, db
from .kana import romaji_to_hiragana, romanize, to_katakana

JP = re.compile(r"[぀-ヿ㐀-鿿豈-﫿々ー]")
MAX_DICT_UPLOAD = 60 * 1024 * 1024
MAX_DICT_UNZIPPED = 600 * 1024 * 1024
MAX_DICT_ENTRIES = 600_000
MAX_DICTS = 12


def _entry_view(row) -> dict:
    senses = json.loads(row.senses_json)
    chars = []
    for ch in dict.fromkeys(row.headword + "".join(row.other_forms.split("、"))):
        k = content.kanji_get(ch)
        if k:
            chars.append({"char": ch, "meaning": content.first_meaning(k)})
    return {"id": row.id, "headword": row.headword, "reading": row.reading if row.reading != row.headword else "",
            "romaji": romanize(row.reading), "others": [x for x in row.other_forms.split("、") if x],
            "common": bool(row.common), "senses": senses, "kanji": chars[:8],
            "sentence_jp": row.sentence_jp, "sentence_en": row.sentence_en}


_PAREN = re.compile(r"\s*\([^()]*\)")
_KATA_ONLY = re.compile(r"^[\u30a0-\u30ffー・]+$")


def _unparen(g: str) -> str:
    """'dog (Canis (lupus) familiaris)' -> 'dog'."""
    prev = None
    while prev != g:
        prev, g = g, _PAREN.sub("", g)
    return g.strip().lower()


def _kanji_rarity(word: str) -> float:
    """Average KANJIDIC newspaper-frequency rank of the word's kanji (lower = more everyday)."""
    ranks = [(content.kanji_get(ch) or {}).get("freq") or 2600 for ch in word if JP.match(ch) and not ("\u3040" <= ch <= "\u30ff")]
    return sum(ranks) / len(ranks) if ranks else 1500


def _fts_query(q: str) -> str | None:
    words = re.findall(r"[A-Za-z0-9']+", q.lower())
    if not words:
        return None
    return " ".join(f'"{w}"' for w in words[:8])


def search(c, q: str, limit: int = 30) -> tuple[list[dict], int]:
    """Built-in dictionary. Returns (entries, total_found_upto_cap)."""
    q = q.strip()[:60]
    if not q:
        return [], 0
    de, df = db.dict_entries.c, db.dict_forms.c
    scores: dict[int, tuple] = {}

    def add(ids_with_rank):
        for eid, rank in ids_with_rank:
            if eid not in scores or rank < scores[eid]:
                scores[eid] = rank

    jp_terms = []
    if JP.search(q):
        jp_terms = list(dict.fromkeys([q, to_katakana(q)]))
    else:
        h = romaji_to_hiragana(q)
        if h:
            jp_terms = list(dict.fromkeys([h, to_katakana(h)]))
    typed_romaji = not JP.search(q)
    for t in jp_terms:
        # Exact Japanese matches come first; for romaji input, exact English matches ("go" -> 行く) rank just above them.
        exact_tier = 1.2 if typed_romaji else 0
        add((r.entry_id, (exact_tier, -r.common, len(r.form))) for r in c.execute(select(df.entry_id, df.common, df.form).where(df.form == t).limit(50)))
        add((r.entry_id, (2, -r.common, len(r.form))) for r in c.execute(
            select(df.entry_id, df.common, df.form).where(df.form > t, df.form < t + "￿").order_by(df.common.desc(), func.length(df.form)).limit(200)))
    if JP.search(q) and len(scores) < limit and len(q) >= 2:  # substring, e.g. 学校 inside 小学校
        add((r.entry_id, (4, -r.common, len(r.form))) for r in c.execute(
            select(df.entry_id, df.common, df.form).where(df.form.like(f"%{q}%")).order_by(df.common.desc()).limit(150)))
    fq = None if JP.search(q) else _fts_query(q)
    if fq:
        ql = _unparen(q)
        rows = c.execute(text("SELECT rowid, gloss, bm25(dict_fts) AS b FROM dict_fts WHERE dict_fts MATCH :q ORDER BY b LIMIT 400"), {"q": fq}).all()
        # Everyday words have many meanings, which lowers their text score; also take entries whose
        # first meaning *starts* with the query ("water" -> 水, "go" -> 行く "to go").
        phrase = " ".join(re.findall(r"[a-z0-9']+", ql))
        seen_ids = {r.rowid for r in rows}
        for start in dict.fromkeys([phrase, f"to {phrase}"]):
            for r in c.execute(text("SELECT rowid, gloss, bm25(dict_fts) AS b FROM dict_fts WHERE dict_fts MATCH :q LIMIT 300"),
                               {"q": f'gloss : ^"{start}"'}).all():
                if r.rowid not in seen_ids:
                    seen_ids.add(r.rowid)
                    rows.append(r)
        commons = dict(c.execute(select(de.id, de.common).where(de.id.in_([r.rowid for r in rows]))).all()) if rows else {}
        for r in rows:
            glosses = [_unparen(g) for g in r.gloss.split(" ; ")]
            exact_noun, exact_verb = ql in glosses, f"to {ql}" in glosses
            first = glosses[0] if glosses else ""
            if first in (ql, f"to {ql}"):
                tier = 1          # first meaning is exactly the query (noun or verb): everyday-ness decides below
            elif exact_noun or exact_verb:
                tier = 1.5
            else:
                tier = 3
            add([(r.rowid, (tier, -commons.get(r.rowid, 0), r.b))])
    if not scores:
        return [], 0
    heads = dict(c.execute(select(de.id, de.headword).where(de.id.in_(list(scores)))).all())

    def key(e):
        tier, neg_common, *rest = scores[e]
        h = heads.get(e, "")
        # within a tier: common words, then native words over katakana loanwords (English queries), then everyday kanji
        loan = 1 if (fq and _KATA_ONLY.match(h)) else 0
        return (tier, neg_common, loan, _kanji_rarity(h), *rest)

    ranked = sorted(scores, key=key)
    top = ranked[:limit]
    rows = {r.id: r for r in c.execute(select(db.dict_entries).where(de.id.in_(top)))}
    return [_entry_view(rows[e]) for e in top if e in rows], len(ranked)


def get_entry(c, eid: int) -> dict | None:
    row = c.execute(select(db.dict_entries).where(db.dict_entries.c.id == eid)).first()
    return _entry_view(row) if row else None


# ------------------------------------------------------------ your dictionaries
def search_user(c, user_id: int, q: str, limit: int = 20) -> list[dict]:
    q = q.strip()[:60]
    if not q:
        return []
    ud, ue = db.user_dicts.c, db.user_dict_entries.c
    dicts = {r.id: r.title for r in c.execute(select(ud.id, ud.title).where(ud.user_id == user_id, ud.enabled == 1))}
    if not dicts:
        return []
    terms = [q]
    if not JP.search(q):
        h = romaji_to_hiragana(q)
        if h:
            terms += [h, to_katakana(h)]
    else:
        terms.append(to_katakana(q))
    terms = list(dict.fromkeys(terms))
    found, out = set(), []

    def take(stmt, tier):
        for r in c.execute(stmt):
            if r.id not in found and len(out) < limit:
                found.add(r.id)
                out.append({"tier": tier, "dict": dicts[r.dict_id], "term": r.term, "reading": r.reading if r.reading != r.term else "",
                            "meaning": r.meaning})

    cols = (ue.id, ue.dict_id, ue.term, ue.reading, ue.meaning)
    ids = list(dicts)
    take(select(*cols).where(ue.dict_id.in_(ids), or_(ue.term.in_(terms), ue.reading.in_(terms))).limit(limit), 0)
    for t in terms:
        take(select(*cols).where(ue.dict_id.in_(ids), or_(ue.term.like(f"{t}%"), ue.reading.like(f"{t}%"))).limit(limit), 1)
    if not JP.search(q) and len(out) < limit and len(q) >= 2:
        take(select(*cols).where(ue.dict_id.in_(ids), ue.meaning.like(f"%{q}%")).limit(limit), 2)
    return out


class DictImportError(Exception):
    pass


def _flatten(node) -> str:
    """Yomitan glossary items can be strings or structured content; keep only the text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_flatten(x) for x in node)
    if isinstance(node, dict):
        if node.get("type") == "image" or node.get("tag") in ("img", "rt", "rp"):
            return ""
        if "text" in node and isinstance(node["text"], str):
            return node["text"]
        sep = "\n" if node.get("tag") in ("li", "div", "p", "br", "tr") else ""
        inner = _flatten(node.get("content", ""))
        return (inner + sep) if inner else sep
    return ""


def parse_yomitan(data: bytes) -> tuple[str, list[tuple[str, str, str]]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise DictImportError("That .zip file couldn't be opened.") from None
    if sum(i.file_size for i in z.infolist()) > MAX_DICT_UNZIPPED:
        raise DictImportError("That dictionary is too big when unpacked.")
    names = z.namelist()
    if "index.json" not in names:
        raise DictImportError("This .zip isn't a Yomitan/Yomichan dictionary (no index.json).")
    try:
        index = json.loads(z.read("index.json"))
    except ValueError:
        raise DictImportError("The dictionary's index.json is broken.") from None
    title = str(index.get("title") or "Imported dictionary")[:120]
    banks = sorted((n for n in names if re.match(r"^term_bank_\d+\.json$", n.split("/")[-1])),
                   key=lambda n: int(re.findall(r"\d+", n.split("/")[-1])[0]))
    if not banks:
        raise DictImportError("This dictionary has no word entries (it may be a kanji or frequency dictionary).")
    out = []
    for b in banks:
        try:
            rows = json.loads(z.read(b))
        except ValueError:
            raise DictImportError(f"{b} in that dictionary is broken.") from None
        for e in rows:
            if not isinstance(e, list) or len(e) < 6:
                continue
            term, reading = str(e[0])[:200], str(e[1] or "")[:200]
            gloss = e[5] if len(e) >= 8 and isinstance(e[5], list) else e[5:]
            meaning = re.sub(r"\n{2,}", "\n", "\n".join(t.strip() for t in (_flatten(g) for g in gloss) if t.strip()))[:4000]
            if term and meaning:
                out.append((term, reading, meaning))
            if len(out) >= MAX_DICT_ENTRIES:
                return title, out
    return title, out


def parse_table(data: bytes, filename: str) -> tuple[str, list[tuple[str, str, str]]]:
    try:
        txt = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            txt = data.decode("shift_jis")
        except UnicodeDecodeError:
            raise DictImportError("Couldn't read that file. Save it as UTF-8 text (CSV or TSV).") from None
    sample = txt[:5000]
    delim = "\t" if sample.count("\t") >= sample.count(",") else ","
    if sample.count(";") > max(sample.count("\t"), sample.count(",")):
        delim = ";"
    rows = list(csv.reader(io.StringIO(txt), delimiter=delim))
    if rows and any(h.strip().lower() in ("term", "word", "expression", "japanese", "kanji", "front") for h in rows[0]):
        rows = rows[1:]
    out = []
    for r in rows:
        r = [x.strip() for x in r]
        if len(r) >= 3 and r[0] and r[2]:
            out.append((r[0][:200], r[1][:200], r[2][:4000]))
        elif len(r) == 2 and r[0] and r[1]:
            out.append((r[0][:200], "", r[1][:4000]))
        if len(out) >= MAX_DICT_ENTRIES:
            break
    if not out:
        raise DictImportError("No entries found. Use one entry per line: word, reading, meaning (or word, meaning).")
    title = re.sub(r"\.(csv|tsv|txt)$", "", filename or "My word list", flags=re.I)[:120] or "My word list"
    return title, out


def import_dictionary(c, user_id: int, data: bytes, filename: str) -> dict:
    if len(data) > MAX_DICT_UPLOAD:
        raise DictImportError("That file is too big (limit 60 MB).")
    n = c.execute(select(func.count()).select_from(db.user_dicts).where(db.user_dicts.c.user_id == user_id)).scalar()
    if n >= MAX_DICTS:
        raise DictImportError(f"You can keep up to {MAX_DICTS} dictionaries. Delete one first.")
    if data[:2] == b"PK":
        kind = "yomitan"
        title, entries = parse_yomitan(data)
    else:
        kind = "table"
        title, entries = parse_table(data, filename)
    if not entries:
        raise DictImportError("No usable entries found in that dictionary.")
    did = c.execute(db.user_dicts.insert().values(user_id=user_id, title=title, kind=kind, entries=len(entries),
                                                  created_at=int(time.time()))).inserted_primary_key[0]
    for i in range(0, len(entries), 20000):
        c.execute(db.user_dict_entries.insert(), [{"dict_id": did, "term": t, "reading": r, "meaning": m}
                                                  for t, r, m in entries[i:i + 20000]])
    return {"id": did, "title": title, "entries": len(entries), "kind": kind}
