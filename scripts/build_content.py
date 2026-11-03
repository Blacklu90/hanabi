"""Build Shuinkan's read-only content tables from the original datasets.

Sources (see DATA_SOURCES.md):
  data/source/kanjidic2-en-*.json        KANJIDIC2 (EDRDG, CC BY-SA 4.0) via jmdict-simplified
  data/source/jmdict-eng-common-*.json   JMdict common words (EDRDG, CC BY-SA 4.0)
  data/source/jmdict-examples-eng-*.json JMdict + Tatoeba example sentences (CC BY 2.0 FR)
  data/strokes/*.svg                     KanjiVG stroke order (CC BY-SA 3.0)

Only content tables are replaced (inside one transaction). User tables are never touched.
Run:  .venv/bin/python -m scripts.build_content
"""
from __future__ import annotations

import glob
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, insert  # noqa: E402

from app import db  # noqa: E402
from app.kana import romanize  # noqa: E402
from app.vocab_list import HIRAGANA_WORDS, KATAKANA_WORDS  # noqa: E402

SRC = ROOT / "data" / "source"
STROKES = ROOT / "data" / "strokes"
JOYO_GRADES = (1, 2, 3, 4, 5, 6, 8)
EXPECTED_GRADES = {1: 80, 2: 160, 3: 200, 4: 202, 5: 193, 6: 191, 8: 1110}
VOCAB_PER_KANJI = 6
SENTENCES_PER_KANJI = 2
KANA_RE = re.compile(r"^[぀-ヿ]+$")


def one(pattern: str) -> Path:
    files = sorted(glob.glob(str(SRC / pattern)))
    if not files:
        sys.exit(f"missing dataset: data/source/{pattern}")
    return Path(files[-1])


def kvg_stroke_count(cp: str) -> int | None:
    p = STROKES / f"{cp}.svg"
    if not p.exists():
        return None
    return len(re.findall(r'<path[^>]*id="kvg:[0-9a-f]+-s\d+"', p.read_text(encoding="utf-8")))


def radical_info(num: int | None):
    if not num or not 1 <= num <= 214:
        return None, None
    ch = chr(0x2F00 + num - 1)  # Unicode Kangxi Radicals block
    name = unicodedata.name(ch).removeprefix("KANGXI RADICAL ").lower()
    return unicodedata.normalize("NFKC", ch), name


def strip_reading(r: str) -> str:
    return r.replace(".", "").replace("-", "")


def main() -> None:
    t0 = time.time()
    kd_path, common_path, ex_path = one("kanjidic2-en-*.json"), one("jmdict-eng-common-*.json"), one("jmdict-examples-eng-*.json")
    kd = json.loads(kd_path.read_text(encoding="utf-8"))
    common = json.loads(common_path.read_text(encoding="utf-8"))
    print(f"loaded KANJIDIC2 {kd['dictDate']} and JMdict common {common['dictDate']} ({time.time()-t0:.1f}s)")
    tags = common["tags"]

    # ------------------------------------------------------------ kanji
    rows, report = [], {"stroke_discrepancies": [], "missing_svg": []}
    for ch in kd["characters"]:
        misc = ch["misc"]
        if misc.get("grade") not in JOYO_GRADES:
            continue
        lit = ch["literal"]
        cp = next(c["value"] for c in ch["codepoints"] if c["type"] == "ucs")
        cp5 = cp.lower().rjust(5, "0")
        groups = (ch.get("readingMeaning") or {}).get("groups", [])
        on = [r["value"] for g in groups for r in g["readings"] if r["type"] == "ja_on"]
        kun = [r["value"] for g in groups for r in g["readings"] if r["type"] == "ja_kun"]
        meanings = [m["value"] for g in groups for m in g["meanings"] if m["lang"] == "en"]
        nanori = (ch.get("readingMeaning") or {}).get("nanori", [])
        rad = next((r["value"] for r in ch["radicals"] if r["type"] == "classical"), None)
        rchar, rname = radical_info(rad)
        strokes = misc["strokeCounts"][0]
        kvg = kvg_stroke_count(cp5)
        if kvg is None:
            report["missing_svg"].append(lit)
        elif kvg != strokes:
            report["stroke_discrepancies"].append({"kanji": lit, "kanjidic": strokes, "kanjivg": kvg})
        readings_plain = [strip_reading(x) for x in on + kun]
        blob = " ".join([lit] + [m.lower() for m in meanings] + readings_plain + [romanize(x) for x in readings_plain] + ([rname] if rname else []))
        rows.append(dict(
            char=lit, codepoint=f"U+{cp.upper()}", grade=misc["grade"], strokes=strokes, kvg_strokes=kvg,
            freq=misc.get("frequency"), jlpt_old=misc.get("jlptLevel"), meanings="; ".join(meanings),
            onyomi="、".join(on), kunyomi="、".join(kun), nanori="、".join(nanori), radical_num=rad,
            radical_char=rchar, radical_name=rname, search_blob=blob,
        ))
    # Stable order: grade then frequency (common first) then code point.
    rows.sort(key=lambda r: (r["grade"], r["freq"] or 99999, r["char"]))
    for i, r in enumerate(rows, 1):
        r["idx"] = i
    chars = [r["char"] for r in rows]
    grades = Counter(r["grade"] for r in rows)
    assert len(rows) == 2136, len(rows)
    assert len(set(chars)) == 2136, "duplicate kanji"
    assert dict(grades) == EXPECTED_GRADES, grades
    joyo = set(chars)

    # ------------------------------------------------------- kanji vocab
    cand = defaultdict(list)
    for w in common["words"]:
        kforms = [k for k in w["kanji"] if k["common"]]
        kanas = [k for k in w["kana"] if k["common"]] or w["kana"]
        if not kforms or not kanas:
            continue
        word, reading = kforms[0]["text"], kanas[0]["text"]
        if len(word) > 6 or not all(c in joyo or KANA_RE.match(c) for c in word):
            continue
        sense = w["sense"][0]
        meaning = "; ".join(g["text"] for g in sense["gloss"][:3])
        for c in set(word):
            if c in joyo:
                cand[c].append((len(word), int(w["id"]), word, reading, meaning, w["id"]))
    vocab_rows = []
    for c in chars:
        seen = set()
        for _, _, word, reading, meaning, wid in sorted(cand[c]):
            if word in seen:
                continue
            seen.add(word)
            vocab_rows.append(dict(kanji=c, word=word, reading=reading, meaning=meaning, jmdict_id=wid))
            if len(seen) >= VOCAB_PER_KANJI:
                break
    del common

    # --------------------------------------------- examples + kana vocab
    t1 = time.time()
    full = json.loads(ex_path.read_text(encoding="utf-8"))
    print(f"loaded JMdict examples {full['dictDate']} ({time.time()-t1:.1f}s)")
    by_id, by_kana = {}, defaultdict(list)
    for w in full["words"]:
        by_id[w["id"]] = w
        for k in w["kana"]:
            by_kana[k["text"]].append(w)

    def first_example(w):
        for s in w["sense"]:
            for ex in s.get("examples") or []:
                jp = next((x["text"] for x in ex["sentences"] if x["lang"] == "jpn"), None)
                en = next((x["text"] for x in ex["sentences"] if x["lang"] == "eng"), None)
                if jp and en and ex["source"]["type"] == "tatoeba" and len(jp) <= 40:
                    return jp, en, ex["source"]["value"]
        return None

    sent_rows = []
    vocab_by_kanji = defaultdict(list)
    for v in vocab_rows:
        vocab_by_kanji[v["kanji"]].append(v)
    for c in chars:
        used = set()
        for v in vocab_by_kanji[c]:
            w = by_id.get(v["jmdict_id"])
            ex = first_example(w) if w else None
            if ex and ex[2] not in used:
                used.add(ex[2])
                sent_rows.append(dict(kanji=c, word=v["word"], jp=ex[0], en=ex[1], tatoeba_id=ex[2]))
                if len(used) >= SENTENCES_PER_KANJI:
                    break

    def pos_label(code: str) -> str:
        label = tags.get(code, code)
        return re.sub(r"\s*\(.*?\)", "", label).split(",")[0].strip()

    kana_rows, problems = [], []
    for script, words in (("hiragana", HIRAGANA_WORDS), ("katakana", KATAKANA_WORDS)):
        for word, key, cat in words:
            best = None
            for w in by_kana.get(word, []):
                common_kana = any(k["text"] == word and k["common"] for k in w["kana"])
                for si, s in enumerate(w["sense"]):
                    gl = [g["text"] for g in s["gloss"] if g["lang"] == "eng"]
                    if any(key.lower() in g.lower() for g in gl):
                        score = (0 if common_kana else 1, si, int(w["id"]))
                        if best is None or score < best[0]:
                            best = (score, w, s, gl)
                        break
            if best is None:
                problems.append(f"{script}: {word} ({key}) not found in JMdict")
                continue
            _, w, s, gl = best
            kforms = [k["text"] for k in w["kanji"] if k["common"]] or [k["text"] for k in w["kanji"]]
            ex = first_example(w)
            kana_rows.append(dict(
                script=script, word=word, romaji=romanize(word), kanji_form=(kforms[0] if kforms and script == "hiragana" else None),
                meaning="; ".join(gl[:3]), pos=pos_label(s["partOfSpeech"][0]) if s["partOfSpeech"] else "",
                category=cat, sentence_jp=ex[0] if ex else None, sentence_en=ex[1] if ex else None,
                tatoeba_id=ex[2] if ex else None, jmdict_id=w["id"],
            ))
    if problems:
        print("\n".join(problems))
        sys.exit("vocabulary validation failed")

    # ------------------------------------------------------- dictionary
    t2 = time.time()
    dict_rows, form_rows, fts_rows = [], [], []
    misc_tags = full["tags"]
    for w in full["words"]:
        kanji_forms = [k for k in w["kanji"] if "iK" not in k.get("tags", []) and "sK" not in k.get("tags", [])]
        kana_forms = [k for k in w["kana"] if "ik" not in k.get("tags", []) and "sk" not in k.get("tags", [])]
        if not kana_forms:
            continue
        common = any(k["common"] for k in w["kanji"] + w["kana"])
        usually_kana = bool(w["sense"]) and "uk" in w["sense"][0].get("misc", [])
        kf = sorted(kanji_forms, key=lambda k: not k["common"])
        rf = sorted(kana_forms, key=lambda k: not k["common"])
        headword = rf[0]["text"] if (usually_kana or not kf) else kf[0]["text"]
        reading = rf[0]["text"]
        others = [k["text"] for k in kf + rf if k["text"] not in (headword, reading)]
        senses = []
        for sn in w["sense"][:8]:
            gl = [g["text"] for g in sn["gloss"] if g["lang"] == "eng"][:6]
            if not gl:
                continue
            senses.append({"p": [pos_label(x) for x in sn["partOfSpeech"][:2]],
                           "m": [re.sub(r"\s*\(.*?\)", "", misc_tags.get(x, x)) for x in sn.get("misc", [])[:2]],
                           "g": gl, "i": "; ".join(sn.get("info", [])[:1])})
        if not senses:
            continue
        ex = first_example(w)
        wid = int(w["id"])
        dict_rows.append(dict(id=wid, headword=headword, reading=reading, other_forms="、".join(others[:8]), common=int(common),
                              senses_json=json.dumps(senses, ensure_ascii=False, separators=(",", ":")),
                              sentence_jp=ex[0] if ex else None, sentence_en=ex[1] if ex else None))
        seen = set()
        for k in kf + rf:
            if k["text"] not in seen:
                seen.add(k["text"])
                form_rows.append(dict(entry_id=wid, form=k["text"], common=int(k["common"])))
        fts_rows.append((wid, " ; ".join(g for sn in senses for g in sn["g"])))
    print(f"dictionary: {len(dict_rows)} entries, {len(form_rows)} forms ({time.time()-t2:.1f}s)")

    # ------------------------------------------------------------ write
    meta = {
        "kanjidic2_date": kd["dictDate"], "jmdict_date": full["dictDate"], "built_at": str(int(time.time())),
        "kanji_count": str(len(rows)), "grade_counts": json.dumps({str(k): v for k, v in sorted(grades.items())}),
        "kanji_vocab_count": str(len(vocab_rows)), "kanji_sentence_count": str(len(sent_rows)),
        "kanji_with_sentence": str(len({s["kanji"] for s in sent_rows})),
        "kanji_with_vocab": str(len({v["kanji"] for v in vocab_rows})),
        "kana_vocab_count": str(len(kana_rows)),
        "dict_entries": str(len(dict_rows)), "dict_with_sentence": str(sum(1 for d in dict_rows if d["sentence_jp"])),
        "kana_vocab_with_sentence": str(sum(1 for k in kana_rows if k["sentence_jp"])),
        "stroke_discrepancies": json.dumps(report["stroke_discrepancies"], ensure_ascii=False),
        "missing_svg": json.dumps(report["missing_svg"], ensure_ascii=False),
    }
    target = db.CONTENT_DB
    if target.exists():  # safety copy before touching an existing database
        import sqlite3
        bdir = target.parent / "backups"
        bdir.mkdir(exist_ok=True)
        dest = bdir / f"content-{time.strftime('%Y%m%d-%H%M%S')}.db"
        with sqlite3.connect(target) as s, sqlite3.connect(dest) as d:
            s.backup(d)
        print(f"backup written to {dest}")
    eng = db.make_engine(target)
    db.metadata.create_all(eng, tables=db.CONTENT_TABLES)
    with eng.begin() as c:
        for t in db.CONTENT_TABLES:
            c.execute(delete(t))
        c.execute(insert(db.kanji), rows)
        c.execute(insert(db.kanji_vocab), vocab_rows)
        c.execute(insert(db.kanji_sentences), sent_rows)
        c.execute(insert(db.kana_vocab), kana_rows)
        for i in range(0, len(dict_rows), 20000):
            c.execute(insert(db.dict_entries), dict_rows[i:i + 20000])
        for i in range(0, len(form_rows), 50000):
            c.execute(insert(db.dict_forms), form_rows[i:i + 50000])
        raw = c.connection.dbapi_connection
        raw.execute("CREATE VIRTUAL TABLE IF NOT EXISTS dict_fts USING fts5(gloss, tokenize='unicode61 remove_diacritics 2')")
        raw.execute("DELETE FROM dict_fts")
        raw.executemany("INSERT INTO dict_fts(rowid, gloss) VALUES (?, ?)", fts_rows)
        raw.execute("INSERT INTO dict_fts(dict_fts) VALUES ('optimize')")
        c.execute(insert(db.content_meta), [{"key": k, "value": v} for k, v in meta.items()])
    out = {k: (json.loads(v) if k in ("grade_counts", "stroke_discrepancies", "missing_svg") else v) for k, v in meta.items()}
    (ROOT / "data" / "content_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "stroke_discrepancies"}, ensure_ascii=False, indent=1))
    print(f"stroke-count discrepancies (KANJIDIC2 vs KanjiVG): {len(report['stroke_discrepancies'])}")
    with eng.connect() as c:
        c.exec_driver_sql("VACUUM")
    eng.dispose()
    # Ship content.db in rollback-journal mode so it can be read from read-only places (the AppImage).
    import sqlite3
    with sqlite3.connect(target) as raw:
        raw.execute("PRAGMA journal_mode=DELETE")
    # Bring the local development database up to date too.
    db.init_db()
    print(f"content.db: {target.stat().st_size / 1e6:.1f} MB")
    print(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
