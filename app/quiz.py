"""Quiz generation. Answers stay on the server; the browser only sees options."""
from __future__ import annotations

import random

from . import content
from .kana import NON_SYLLABLE, SCRIPTS

OPTIONS = 4

# kind -> (title, description)
KINDS = {
    "hiragana-recognition": ("Hiragana → romaji", "See a hiragana, pick its sound."),
    "hiragana-reading": ("Romaji → hiragana", "See a sound, pick the hiragana."),
    "katakana-recognition": ("Katakana → romaji", "See a katakana, pick its sound."),
    "katakana-reading": ("Romaji → katakana", "See a sound, pick the katakana."),
    "hvocab-meaning": ("Hiragana words", "Read a word, pick its meaning."),
    "kvocab-meaning": ("Katakana words", "Read a loanword, pick its meaning."),
    "vocab-sentence": ("Fill the gap", "Pick the word that completes a real sentence."),
    "kanji-meaning": ("Kanji meaning", "See a kanji, pick its meaning."),
    "kanji-reading": ("Kanji reading", "See a kanji, pick a reading."),
    "kanji-vocab": ("Kanji words", "Read a kanji word, pick its reading."),
    "kanji-radical": ("Radicals", "Pick the kanji's radical."),
    "kanji-strokes": ("Stroke count", "How many strokes?"),
    "kanji-sentence": ("Kanji in sentences", "Pick the word that completes the sentence."),
    "mixed": ("Mixed bag", "A bit of everything you have started."),
}
KANJI_KINDS = [k for k in KINDS if k.startswith("kanji-")]


class NotEnough(Exception):
    pass


def _choices(correct: str, pool: list[str], rng: random.Random) -> tuple[list[str], int]:
    others = list(dict.fromkeys(p for p in pool if p != correct))
    if len(others) < OPTIONS - 1:
        raise NotEnough
    opts = rng.sample(others, OPTIONS - 1) + [correct]
    rng.shuffle(opts)
    return opts, opts.index(correct)


def _q(prompt, options, answer, *, track, item, kind, sub="", prompt_kind="jp", explain=""):
    return {"prompt": prompt, "prompt_kind": prompt_kind, "sub": sub, "options": options, "answer": answer,
            "track": track, "item": item, "kind": kind, "explain": explain}


def kana_pool(script: str, lessons: set[str] | None):
    chars = [c for c in SCRIPTS[script]["chars"] if c["kana"] not in NON_SYLLABLE]
    if lessons is not None:
        chars = [c for c in chars if f"{script}-{c['lesson']}" in lessons]
    return chars


def kanji_pool(grade: int | None, started: set[str] | None):
    ks = content.kanji_list()
    if grade:
        ks = [k for k in ks if k["grade"] == grade]
    if started is not None:
        ks = [k for k in ks if k["char"] in started]
    return ks


def make_question(kind: str, item, rng: random.Random) -> dict:
    """Build one question about `item` (a kana dict, vocab dict or kanji dict)."""
    if kind.endswith("-recognition"):
        script = kind.split("-")[0]
        pool = [c["romaji"] for c in SCRIPTS[script]["chars"] if c["kana"] not in NON_SYLLABLE and c["group"] == item["group"]]
        pool += [c["romaji"] for c in SCRIPTS[script]["chars"] if c["kana"] not in NON_SYLLABLE]
        opts, a = _choices(item["romaji"], pool, rng)
        return _q(item["kana"], opts, a, track=script, item=item["kana"], kind=kind,
                  explain=f"{item['kana']} is read “{item['romaji']}”. 💡 {item['hook']}")
    if kind.endswith("-reading") and not kind.startswith("kanji"):
        script = kind.split("-")[0]
        same = [c["kana"] for c in SCRIPTS[script]["chars"] if c["kana"] not in NON_SYLLABLE and c["romaji"] != item["romaji"]]
        opts, a = _choices(item["kana"], same, rng)
        return _q(item["romaji"], opts, a, track=script, item=item["kana"], kind=kind, prompt_kind="text",
                  explain=f"“{item['romaji']}” is written {item['kana']}. 💡 {item['hook']}")
    if kind in ("hvocab-meaning", "kvocab-meaning"):
        script = "hiragana" if kind.startswith("h") else "katakana"
        pool = [v["meaning"].split("; ")[0] for v in content.vocab_list(script)]
        opts, a = _choices(item["meaning"].split("; ")[0], pool, rng)
        track = "hvocab" if script == "hiragana" else "kvocab"
        return _q(item["word"], opts, a, track=track, item=item["word"], kind=kind, sub=item["romaji"],
                  explain=f"{item['word']} ({item['romaji']}) — {item['meaning']}")
    if kind == "vocab-sentence":
        sent = item["sentence_jp"]
        form = item["word"] if item["word"] in sent else (item["kanji_form"] if item["kanji_form"] and item["kanji_form"] in sent else None)
        if not form:
            raise NotEnough
        pool = [v["kanji_form"] if form == item["kanji_form"] and v["kanji_form"] else v["word"] for v in content.vocab_list(item["script"]) if v["word"] != item["word"]]
        opts, a = _choices(form, pool, rng)
        track = "hvocab" if item["script"] == "hiragana" else "kvocab"
        return _q(sent.replace(form, "＿＿", 1), opts, a, track=track, item=item["word"], kind=kind, sub=item["sentence_en"],
                  prompt_kind="sentence", explain=f"{sent} — {item['sentence_en']}")
    k = item
    ks = content.kanji_list()
    if kind == "kanji-meaning":
        near = [content.first_meaning(x) for x in ks if abs(x["grade"] - k["grade"]) <= 1]
        opts, a = _choices(content.first_meaning(k), near, rng)
        return _q(k["char"], opts, a, track="kanji", item=k["char"], kind=kind, explain=f"{k['char']}: {k['meanings']}")
    if kind == "kanji-reading":
        r = content.primary_reading(k)
        if not r:
            raise NotEnough
        own = {x.replace("-", "").replace(".", "") for x in (k["onyomi"] + "、" + k["kunyomi"]).split("、")}
        pool = [content.primary_reading(x) for x in ks if x["char"] != k["char"]]
        pool = [p for p in pool if p and p not in own]
        opts, a = _choices(r, pool, rng)
        return _q(k["char"], opts, a, track="kanji", item=k["char"], kind=kind, sub=content.first_meaning(k),
                  explain=f"On: {k['onyomi'] or '—'} · Kun: {k['kunyomi'] or '—'}")
    if kind == "kanji-vocab":
        words = content.kanji_vocab(k["char"])
        if not words:
            raise NotEnough
        w = rng.choice(words[:3])
        pool = [v["reading"] for x in rng.sample(ks, 40) for v in content.kanji_vocab(x["char"])[:1]]
        opts, a = _choices(w["reading"], pool, rng)
        return _q(w["word"], opts, a, track="kanji", item=k["char"], kind=kind, sub=w["meaning"].split("; ")[0],
                  explain=f"{w['word']} is read {w['reading']} — {w['meaning']}")
    if kind == "kanji-radical":
        if not k["radical_char"]:
            raise NotEnough
        label = lambda x: f"{x['radical_char']} {x['radical_name']}"
        pool = list({label(x) for x in ks if x["radical_char"] and x["radical_num"] != k["radical_num"]})
        opts, a = _choices(label(k), sorted(pool), rng)
        return _q(k["char"], opts, a, track="kanji", item=k["char"], kind=kind, sub="Which radical?",
                  explain=f"{k['char']} is filed under radical {k['radical_num']}: {label(k)}.")
    if kind == "kanji-strokes":
        n = k["strokes"]
        pool = [str(x) for x in range(max(1, n - 4), n + 5)]
        opts, a = _choices(str(n), pool, rng)
        return _q(k["char"], opts, a, track="kanji", item=k["char"], kind=kind, sub="How many strokes?",
                  explain=f"{k['char']} has {n} strokes.")
    if kind == "kanji-sentence":
        sents = content.kanji_sentences(k["char"])
        if not sents:
            raise NotEnough
        s = rng.choice(sents)
        if s["word"] not in s["jp"]:
            raise NotEnough
        pool = [v["word"] for x in rng.sample(ks, 60) for v in content.kanji_vocab(x["char"])[:2] if len(v["word"]) == len(s["word"])]
        opts, a = _choices(s["word"], pool, rng)
        return _q(s["jp"].replace(s["word"], "＿＿", 1), opts, a, track="kanji", item=k["char"], kind=kind, sub=s["en"],
                  prompt_kind="sentence", explain=f"{s['jp']} — {s['en']}")
    raise ValueError(kind)


def build(kind: str, n: int, *, lessons: set[str] | None = None, grade: int | None = None,
          started_kanji: set[str] | None = None, started_vocab: set | None = None, rng: random.Random | None = None,
          due_items: list[tuple[str, str]] | None = None) -> list[dict]:
    """Generate up to n questions. Raises NotEnough if the pool is too small."""
    rng = rng or random.Random()
    if kind == "due":
        return _build_due(due_items or [], n, rng)
    if kind == "mixed":
        return _build_mixed(n, lessons or set(), started_kanji or set(), started_vocab or set(), rng)
    if kind.startswith(("hiragana", "katakana")):
        items = kana_pool(kind.split("-")[0], lessons)
    elif kind in ("hvocab-meaning", "kvocab-meaning"):
        items = content.vocab_list("hiragana" if kind[0] == "h" else "katakana")
    elif kind == "vocab-sentence":
        items = [v for v in content.vocab_list() if v["sentence_jp"]]
    elif kind in KANJI_KINDS:
        items = kanji_pool(grade, started_kanji if started_kanji else None)
    else:
        raise ValueError(kind)
    if len(items) < 4:
        raise NotEnough
    return _fill(lambda it: make_question(kind, it, rng), items, n, rng)


def _fill(maker, items, n, rng):
    out, seen = [], set()
    order = items[:]
    rng.shuffle(order)
    i = 0
    while len(out) < n and i < len(order) * 3:
        it = order[i % len(order)]
        i += 1
        try:
            q = maker(it)
        except NotEnough:
            continue
        key = (q["kind"], q["item"], q["prompt"])
        if key in seen and len(seen) < len(order):
            continue
        seen.add(key)
        out.append(q)
    if len(out) < min(n, 4):
        raise NotEnough
    return out


def _build_mixed(n, lessons, started_kanji, started_vocab, rng):
    makers = []
    for script in ("hiragana", "katakana"):
        pool = kana_pool(script, lessons)
        if len(pool) >= 4:
            makers += [(f"{script}-recognition", pool), (f"{script}-reading", pool)]
    vocab = [v for v in content.vocab_list() if ("hvocab" if v["script"] == "hiragana" else "kvocab", v["word"]) in started_vocab]
    if vocab:
        for s, kind in (("hiragana", "hvocab-meaning"), ("katakana", "kvocab-meaning")):
            vs = [v for v in vocab if v["script"] == s]
            if vs:
                makers.append((kind, vs))
    kanji = [k for k in content.kanji_list() if k["char"] in started_kanji]
    if kanji:
        makers += [("kanji-meaning", kanji), ("kanji-reading", kanji), ("kanji-vocab", kanji)]
    if not makers:
        raise NotEnough
    out = []
    for _ in range(n * 3):
        if len(out) >= n:
            break
        kind, pool = rng.choice(makers)
        try:
            out.append(make_question(kind, rng.choice(pool), rng))
        except NotEnough:
            continue
    if len(out) < 4:
        raise NotEnough
    return out


def _build_due(due_items, n, rng):
    out = []
    for track, item in due_items[: n * 2]:
        if len(out) >= n:
            break
        try:
            if track in ("hiragana", "katakana"):
                c = content.kana_char(track, item)
                if c["kana"] in NON_SYLLABLE:
                    continue
                out.append(make_question(f"{track}-recognition", c, rng))
            elif track in ("hvocab", "kvocab"):
                out.append(make_question(f"{track}-meaning", content.vocab_get(track, item), rng))
            elif track == "kanji":
                out.append(make_question(rng.choice(["kanji-meaning", "kanji-reading"]), content.kanji_get(item), rng))
        except NotEnough:
            continue
    if len(out) < 4:
        raise NotEnough
    return out


def public(q: dict) -> dict:
    """The browser-safe view of a question (no answer, no explanation)."""
    return {k: q[k] for k in ("prompt", "prompt_kind", "sub", "options")}
