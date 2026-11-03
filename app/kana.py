"""Hiragana and katakana curriculum.

Character sets follow the standard gojūon table (modern Hepburn romanisation).
Each lesson is deliberately small (3-6 characters) so a lesson fits in a
short focus burst.
"""
from __future__ import annotations

from .mnemonics import hook_for

# (kana, romaji) rows. Basic gojūon (46).
_BASIC_ROWS = [
    ("vowels", "Vowels", [("あ", "a"), ("い", "i"), ("う", "u"), ("え", "e"), ("お", "o")]),
    ("k", "K row", [("か", "ka"), ("き", "ki"), ("く", "ku"), ("け", "ke"), ("こ", "ko")]),
    ("s", "S row", [("さ", "sa"), ("し", "shi"), ("す", "su"), ("せ", "se"), ("そ", "so")]),
    ("t", "T row", [("た", "ta"), ("ち", "chi"), ("つ", "tsu"), ("て", "te"), ("と", "to")]),
    ("n", "N row", [("な", "na"), ("に", "ni"), ("ぬ", "nu"), ("ね", "ne"), ("の", "no")]),
    ("h", "H row", [("は", "ha"), ("ひ", "hi"), ("ふ", "fu"), ("へ", "he"), ("ほ", "ho")]),
    ("m", "M row", [("ま", "ma"), ("み", "mi"), ("む", "mu"), ("め", "me"), ("も", "mo")]),
    ("y", "Y row", [("や", "ya"), ("ゆ", "yu"), ("よ", "yo")]),
    ("r", "R row", [("ら", "ra"), ("り", "ri"), ("る", "ru"), ("れ", "re"), ("ろ", "ro")]),
    ("w", "W row + ん", [("わ", "wa"), ("を", "wo"), ("ん", "n")]),
]
# Voiced (dakuten) and semi-voiced (handakuten): 25.
_VOICED_ROWS = [
    ("g", "G row (dakuten)", [("が", "ga"), ("ぎ", "gi"), ("ぐ", "gu"), ("げ", "ge"), ("ご", "go")]),
    ("z", "Z row (dakuten)", [("ざ", "za"), ("じ", "ji"), ("ず", "zu"), ("ぜ", "ze"), ("ぞ", "zo")]),
    ("d", "D row (dakuten)", [("だ", "da"), ("ぢ", "ji"), ("づ", "zu"), ("で", "de"), ("ど", "do")]),
    ("b", "B row (dakuten)", [("ば", "ba"), ("び", "bi"), ("ぶ", "bu"), ("べ", "be"), ("ぼ", "bo")]),
    ("p", "P row (handakuten)", [("ぱ", "pa"), ("ぴ", "pi"), ("ぷ", "pu"), ("ぺ", "pe"), ("ぽ", "po")]),
]
# Combination sounds (yōon): 33.
_COMBO_ROWS = [
    ("ky", "KY combos", [("きゃ", "kya"), ("きゅ", "kyu"), ("きょ", "kyo")]),
    ("sh", "SH combos", [("しゃ", "sha"), ("しゅ", "shu"), ("しょ", "sho")]),
    ("ch", "CH combos", [("ちゃ", "cha"), ("ちゅ", "chu"), ("ちょ", "cho")]),
    ("ny", "NY combos", [("にゃ", "nya"), ("にゅ", "nyu"), ("にょ", "nyo")]),
    ("hy", "HY combos", [("ひゃ", "hya"), ("ひゅ", "hyu"), ("ひょ", "hyo")]),
    ("my", "MY combos", [("みゃ", "mya"), ("みゅ", "myu"), ("みょ", "myo")]),
    ("ry", "RY combos", [("りゃ", "rya"), ("りゅ", "ryu"), ("りょ", "ryo")]),
    ("gy", "GY combos", [("ぎゃ", "gya"), ("ぎゅ", "gyu"), ("ぎょ", "gyo")]),
    ("j", "J combos", [("じゃ", "ja"), ("じゅ", "ju"), ("じょ", "jo")]),
    ("by", "BY combos", [("びゃ", "bya"), ("びゅ", "byu"), ("びょ", "byo")]),
    ("py", "PY combos", [("ぴゃ", "pya"), ("ぴゅ", "pyu"), ("ぴょ", "pyo")]),
]
# Katakana-only special entries used for foreign sounds: 30.
_SPECIAL_ROWS = [
    ("sp1", "Small ッ, long ー, ヴ", [("ッ", "(small tsu)"), ("ー", "(long vowel)"), ("ヴ", "vu"), ("イェ", "ye")]),
    ("sp2", "F sounds", [("ファ", "fa"), ("フィ", "fi"), ("フェ", "fe"), ("フォ", "fo"), ("フュ", "fyu")]),
    ("sp3", "T / D sounds", [("ティ", "ti"), ("ディ", "di"), ("トゥ", "tu"), ("ドゥ", "du"), ("テュ", "tyu"), ("デュ", "dyu")]),
    ("sp4", "W sounds + クォ", [("ウィ", "wi"), ("ウェ", "we"), ("ウォ", "wo"), ("クォ", "kwo")]),
    ("sp5", "SH / J / CH + TS", [("シェ", "she"), ("ジェ", "je"), ("チェ", "che"), ("ツァ", "tsa"), ("ツィ", "tsi"), ("ツェ", "tse"), ("ツォ", "tso")]),
    ("sp6", "V sounds", [("ヴァ", "va"), ("ヴィ", "vi"), ("ヴェ", "ve"), ("ヴォ", "vo")]),
]

GROUP_NOTES = {
    "basic": "The 46 basic sounds of the gojūon table. Every other kana is built from these.",
    "voiced": "Two small marks change a sound: ゛ (dakuten) voices it (k→g, s→z, t→d, h→b) and ゜ (handakuten) turns h into p.",
    "combo": "A full-size i-column kana plus a small ゃ/ゅ/ょ blends into one syllable: き + ゃ = きゃ (kya).",
    "special": "Katakana-only combinations for sounds that came in with foreign words. Small ッ doubles the next consonant; ー stretches the previous vowel.",
}

HIRA_TO_KATA = {chr(c): chr(c + 0x60) for c in range(0x3041, 0x3097)}


KATA_TO_HIRA = {v: k for k, v in HIRA_TO_KATA.items()}


def to_katakana(s: str) -> str:
    return "".join(HIRA_TO_KATA.get(ch, ch) for ch in s)


def to_hiragana(s: str) -> str:
    return "".join(KATA_TO_HIRA.get(ch, ch) for ch in s)


def _build(script: str):
    rows = [("basic", r) for r in _BASIC_ROWS] + [("voiced", r) for r in _VOICED_ROWS] + [("combo", r) for r in _COMBO_ROWS]
    if script == "katakana":
        rows += [("special", r) for r in _SPECIAL_ROWS]
    chars, lessons = [], []
    for n, (group, (row_id, title, items)) in enumerate(rows, start=1):
        lesson_chars = []
        for kana, romaji in items:
            k = to_katakana(kana) if script == "katakana" else kana
            chars.append({"kana": k, "romaji": romaji, "group": group, "row": row_id, "lesson": n, "script": script,
                          "hook": hook_for(script, k, romaji, group)})
            lesson_chars.append(k)
        lessons.append({"id": n, "slug": f"{script}-{n}", "title": title, "group": group, "chars": lesson_chars, "note": GROUP_NOTES[group]})
    return chars, lessons


HIRAGANA, HIRAGANA_LESSONS = _build("hiragana")
KATAKANA, KATAKANA_LESSONS = _build("katakana")
SCRIPTS = {
    "hiragana": {"chars": HIRAGANA, "lessons": HIRAGANA_LESSONS, "label": "Hiragana", "jp": "ひらがな"},
    "katakana": {"chars": KATAKANA, "lessons": KATAKANA_LESSONS, "label": "Katakana", "jp": "カタカナ"},
}
KANA_INDEX = {(c["script"], c["kana"]): c for c in HIRAGANA + KATAKANA}
# Characters that are not syllables; excluded from romaji multiple-choice.
NON_SYLLABLE = {"ッ", "ー"}

# ---------------------------------------------------------------- romaji
_ROMAJI = {}
for c in HIRAGANA:
    _ROMAJI[c["kana"]] = c["romaji"]
for c in KATAKANA:
    if c["kana"] not in NON_SYLLABLE:
        _ROMAJI[c["kana"]] = c["romaji"]
_ROMAJI.update({"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o", "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ャ": "ya", "ュ": "yu", "ョ": "yo", "ゎ": "wa", "ヮ": "wa", "ゐ": "i", "ゑ": "e", "ヰ": "i", "ヱ": "e", "ヶ": "ke", "ヵ": "ka", "・": " ", "　": " "})


def romanize(text: str) -> str:
    """Modern Hepburn romanisation of a kana string (best effort, deterministic)."""
    out: list[str] = []
    i, double = 0, False
    while i < len(text):
        two, one = text[i:i + 2], text[i]
        if one in ("っ", "ッ"):
            double = True
            i += 1
            continue
        if one == "ー":
            if out and out[-1]:
                out.append(out[-1][-1])
            i += 1
            continue
        if two in _ROMAJI and len(two) == 2:
            r = _ROMAJI[two]
            i += 2
        elif one in _ROMAJI:
            r = _ROMAJI[one]
            i += 1
        else:
            r = one
            i += 1
        if double and r and r[0] not in "aeiou":
            r = ("t" + r) if r.startswith("ch") else (r[0] + r)
        double = False
        out.append(r)
    return "".join(out)


# ------------------------------------------------------------ romaji → kana
def _build_r2k() -> dict[str, str]:
    t = {}
    for c in HIRAGANA:
        t.setdefault(c["romaji"], c["kana"])
    t.update({"si": "し", "ti": "ち", "tu": "つ", "hu": "ふ", "zi": "じ", "di": "ぢ", "du": "づ", "wo": "を", "ji": "じ", "zu": "ず",
              "sya": "しゃ", "syu": "しゅ", "syo": "しょ", "tya": "ちゃ", "tyu": "ちゅ", "tyo": "ちょ", "cya": "ちゃ", "cyu": "ちゅ", "cyo": "ちょ",
              "zya": "じゃ", "zyu": "じゅ", "zyo": "じょ", "jya": "じゃ", "jyu": "じゅ", "jyo": "じょ", "she": "しぇ", "che": "ちぇ", "je": "じぇ",
              "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "ti-": "てぃ", "thi": "てぃ", "dhi": "でぃ", "wi": "うぃ", "we": "うぇ",
              "va": "ゔぁ", "vi": "ゔぃ", "vu": "ゔ", "ve": "ゔぇ", "vo": "ゔぉ", "xtu": "っ", "ltu": "っ", "xa": "ぁ", "xi": "ぃ", "xu": "ぅ",
              "xe": "ぇ", "xo": "ぉ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "nn": "ん", "n'": "ん", "-": "ー"})
    return t


_R2K = _build_r2k()
_R2K_MAX = max(len(k) for k in _R2K)


def romaji_to_hiragana(text: str) -> str | None:
    """'neko' -> 'ねこ', 'gakkou' -> 'がっこう', 'kon'nichiha' -> 'こんにちは'. None if it isn't romaji."""
    s = text.lower().strip()
    if not s or not all(ch.isascii() and (ch.isalpha() or ch in "-'") for ch in s):
        return None
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "n" and i + 2 < len(s) and s[i + 1] == "n" and s[i + 2] in "aiueoy":  # "konnichi" -> こん + にち
            out.append("ん")
            i += 1
            continue
        if ch == "n" and (i + 1 == len(s) or (s[i + 1] not in "aiueoy'n")):
            out.append("ん")
            i += 1
            continue
        if i + 1 < len(s) and ch == s[i + 1] and ch not in "aiueon-":  # doubled consonant -> small tsu
            out.append("っ")
            i += 1
            continue
        for L in range(min(_R2K_MAX, len(s) - i), 0, -1):
            piece = s[i:i + L]
            if piece in _R2K:
                out.append(_R2K[piece])
                i += L
                break
        else:
            return None  # not convertible: probably English
    return "".join(out)
