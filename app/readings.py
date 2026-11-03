"""Which reading does each kanji use in a word?

Given a word and its reading (both from JMdict), split the reading across the word's
kanji using each kanji's on'yomi and kun'yomi from KANJIDIC2. Two sound changes are
handled, because they hide the reading otherwise:
  * rendaku: the first sound of a later kanji becomes voiced (ひと + ひと → ひとびと)
  * small っ: a reading ending in く/き/ち/つ shrinks before the next kanji (がく + こう → がっこう)
If no split works, the reading belongs to the word as a whole (jukujikun / special reading).
Nothing here is guessed: every label comes from matching the dictionary data.
"""
from __future__ import annotations

from functools import lru_cache

from . import content
from .kana import to_hiragana

VOICED = {a: [b] for a, b in zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ")}
VOICED["ち"].append("じ")  # voiced ち/つ are written ぢ/づ (間近 まぢか) or じ/ず
VOICED["つ"].append("ず")
for _a, _b in zip("はひふへほ", "ぱぴぷぺぽ"):
    VOICED[_a].append(_b)  # h → p after small っ (出発 しゅっぱつ)
I_ROW = dict(zip("うくぐすつぬぶむる", "いきぎしちにびみり"))
SOKUON_ENDS = set("くきちつ")


def is_kanji(ch: str) -> bool:
    return "㐀" <= ch <= "鿿" or ch == "々"


@lru_cache(maxsize=4096)
def candidates(ch: str) -> tuple:
    """(reading in hiragana, 'on' | 'kun', dictionary form) for one kanji."""
    k = content.kanji_get(ch)
    if not k:
        return ()
    out: dict[str, tuple] = {}
    for r in filter(None, k["onyomi"].split("、")):
        r = r.replace("-", "")
        out.setdefault(to_hiragana(r), ("on", r))
    for r in filter(None, k["kunyomi"].split("、")):
        r = r.replace("-", "")
        stem, _, okuri = r.partition(".")
        forms = [stem, stem + okuri]
        if okuri:
            if okuri.endswith("る") and len(okuri) >= 2:   # ichidan verb: う.ける → うけ (受付 うけつけ)
                forms.append(stem + okuri[:-1])
            if okuri[-1] in I_ROW:                          # godan verb stem: い.く → いき (行き先)
                forms.append(stem + okuri[:-1] + I_ROW[okuri[-1]])
        for f in forms:
            if f:
                out.setdefault(f, ("kun", r))
    return tuple((r, kind, base) for r, (kind, base) in out.items())


def _variants(r: str, first: bool, last: bool):
    """Each reading as written, plus its sound-changed forms (with a short note)."""
    yield r, None
    voiced = VOICED.get(r[0], []) if not first else []
    for v in voiced:
        yield v + r[1:], "voiced"
    if not last and len(r) > 1 and r[-1] in SOKUON_ENDS:
        yield r[:-1] + "っ", "small っ"
        for v in voiced:
            yield v + r[1:-1] + "っ", "voiced, small っ"


@lru_cache(maxsize=20000)
def analyse(word: str, reading: str) -> dict:
    """{'parts': [{'text','reading','kind','base','change'}], 'special': bool}.

    kind is 'on', 'kun', 'kana' (okurigana / kana in the word) or 'special' (the whole word)."""
    reading = to_hiragana(reading)
    n, m = len(word), len(reading)
    kanji_pos = [i for i, ch in enumerate(word) if is_kanji(ch)]
    best: dict[tuple, tuple] = {}  # (i, j) -> (cost, parts) ; best split of word[i:] and reading[j:]

    def go(i: int, j: int, prev: str | None):
        if i == n:
            return (0, []) if j == m else None
        key = (i, j, prev if word[i] == "々" else None)
        if key in best:
            return best[key]
        ch = word[i]
        res = None
        if not is_kanji(ch):
            if j < m and to_hiragana(ch) == reading[j]:
                rest = go(i + 1, j + 1, ch)
                if rest:
                    res = (rest[0], [{"text": ch, "reading": reading[j], "kind": "kana"}] + rest[1])
        else:
            src = prev if ch == "々" else ch
            for r, kind, base in (candidates(src) if src else ()):
                for form, change in _variants(r, i == 0, i == n - 1):
                    if reading.startswith(form, j):
                        rest = go(i + 1, j + len(form), src)
                        if rest:
                            cost = rest[0] + (1 if change else 0) + (0 if kind == "on" else 0.01)
                            if res is None or cost < res[0]:
                                res = (cost, [{"text": ch, "reading": form, "kind": kind, "base": base, "change": change}] + rest[1])
        best[key] = res
        return res

    found = go(0, 0, None) if kanji_pos else None
    if not found:
        return {"parts": [{"text": word, "reading": reading, "kind": "special", "base": None, "change": None}], "special": True}
    return {"parts": found[1], "special": False}


def hint(word: str, reading: str) -> dict:
    """The reading pattern this word shows, said plainly. {'rule','followed','text'}"""
    a = analyse(word, reading)
    kanji = [p for p in a["parts"] if p["kind"] in ("on", "kun")]
    has_kana = any(not is_kanji(ch) for ch in word)
    if a["special"]:
        return {"rule": "special", "followed": None,
                "text": "Special reading: it doesn't split into the kanji's usual readings, so learn it as a whole word."}
    kinds = {p["kind"] for p in kanji}
    if len(kanji) >= 2 and not has_kana:
        if kinds == {"on"}:
            return {"rule": "compound", "followed": True, "text": "Kanji compound read with on'yomi — the usual pattern."}
        if kinds == {"kun"}:
            return {"rule": "compound", "followed": False, "text": "Exception: a kanji compound read with kun'yomi (a native Japanese word)."}
        return {"rule": "compound", "followed": False, "text": "Mixed: this compound uses both an on'yomi and a kun'yomi."}
    if has_kana and kanji:
        if kinds == {"kun"}:
            return {"rule": "okurigana", "followed": True, "text": "Kanji + kana ending (okurigana) read with kun'yomi — the usual pattern."}
        return {"rule": "okurigana", "followed": False, "text": "Exception: it has a kana ending but uses on'yomi."}
    if len(kanji) == 1:
        if kinds == {"kun"}:
            return {"rule": "single", "followed": True, "text": "A kanji on its own is often a native word, read with kun'yomi."}
        return {"rule": "single", "followed": False, "text": "This kanji on its own is read with its on'yomi."}
    return {"rule": "other", "followed": None, "text": ""}


KIND_LABELS = {"on": "on'yomi", "kun": "kun'yomi", "special": "special", "kana": ""}
