"""Original memory hooks ("mnemonics") for every kana.

Written for Shuinkan. Each hook links the character's *shape* to its *sound*
(the sound word is in CAPS). Where a real fact helps, it's used: て/te is
"hand", 二/ni is "two", ロ looks like 口 "mouth", ヘ/へ are the same shape.
Voiced sounds, combinations and foreign-sound katakana get rule-based hooks
built from the basic characters, so all 238 entries have one.
"""
from __future__ import annotations

HIRAGANA = {
    "あ": "A cross with a big swirl: someone spinning a lasso on a pole, yelling “AH!”",
    "い": "Two short strokes side by side, like the number 11: double i, “EE”.",
    "う": "A small dash above one curve: a person bowing with a hat on, going “OOH”.",
    "え": "A dash over a zig-zag that kicks out: a dancer striking a pose, “EH?”",
    "お": "Like あ, but a dot flies off the side: “OH! My button popped off.”",
    "か": "Looks like 力 (power) plus a spark: a karate chop going “KA!”",
    "き": "A KEY: two bars across a shaft with a hooked end.",
    "く": "A beak opening sideways: a pigeon going “KUU”.",
    "け": "A post next to a little gate with a KEG hanging from it.",
    "こ": "Two COINS lying flat, one above the other.",
    "さ": "A cross with a spoon curving underneath: stirring SAuce.",
    "し": "A fishhook: SHE caught a fish!",
    "す": "A bar with a knot tied in the rope below: a SUspended rope.",
    "せ": "A shelf bracket on the wall holding a SErving tray.",
    "そ": "A zig-zag with a tail: a SOund wave leaving a speaker.",
    "た": "Reads like a cursive “t” and “a” written next to each other: TA.",
    "ち": "A backwards number 5 — it CHEats by facing the wrong way.",
    "つ": "One curve like a sideways smile: a quick sneeze, “TSU!”",
    "て": "One long arm reaching out. In Japanese, 手 TE means “hand”.",
    "と": "A TOrch: a little stick leaning on a curved base.",
    "な": "A cross and a dot, with a KNOT tied at the bottom: NA.",
    "に": "A stick with two short lines beside it: a KNEE brace with two straps.",
    "ぬ": "Like め, but with a NEW curl at the end of the tail.",
    "ね": "A post with a loop at the bottom: a NEcklace pendant.",
    "の": "A NO-entry sign: a circle with a slash through it.",
    "は": "Someone bent over beside a wall, laughing “HA-HA!”",
    "ひ": "A big wide grin: “HEE HEE!”",
    "ふ": "Four little strokes like mount FUji with puffs of smoke around it.",
    "へ": "A little roof: “HEY, come in out of the rain!”",
    "ほ": "Like は with one more bar on top: one more HOrizontal line, HO.",
    "ま": "A cross with two bars and a loop: MA with her hair tied in a bun.",
    "み": "A loop with a tail and a slash, like a music note: do-re-MI.",
    "む": "An arm flexing a MUscle, with a drop of sweat flying off.",
    "め": "A winking eye. In Japanese, 目 ME means “eye”. (ぬ is the same plus a curl.)",
    "も": "A fishing hook with two crossbars, to catch MOre fish.",
    "や": "A YAk's head: a curved horn, a crossbar and a dot.",
    "ゆ": "A U-turn sign with a line through it: “YOU can't turn here.”",
    "よ": "A YO-YO hanging on its string from a short bar.",
    "ら": "Like ち with a little dash on top: a RAcing car with its antenna.",
    "り": "Two strokes flowing down side by side: two RIvers.",
    "る": "A loopy path with a curl at the end, like a ROO's (kangaroo) curled tail.",
    "れ": "A post with a line that turns back: RE-turn.",
    "ろ": "Like る, but the loop at the end has been cut off: the ROpe snapped.",
    "わ": "Like ね, but the tail drops straight down: WAter pouring off.",
    "を": "Someone WObbling with a bar across their arms: “WOah!” (said like “o”)",
    "ん": "Looks just like a handwritten lowercase “n”.",
}

KATAKANA = {
    "ア": "An A-frame tent with one side missing: “AH, where's the wall?”",
    "イ": "A person leaning on a post, sighing “EE…”",
    "ウ": "Like う with a roof added: “OOH, a hat with a brim.”",
    "エ": "An EMPTY spool, or a capital I: E.",
    "オ": "A cross with a slash: an OAR crossed over a mast.",
    "カ": "Same shape as か without the dot: 力 power, “KA!”",
    "キ": "A KEY with two teeth, just like き without the curl.",
    "ク": "A half-open umbrella blown sideways: “KU, too windy!”",
    "ケ": "Like ク with an extra leg: a KEg on a stand.",
    "コ": "A COntainer, open on the left side.",
    "サ": "A bench with two legs, one bent: SAt on it too hard.",
    "シ": "SHE looks sideways. Two dots on the LEFT and a stroke sweeping UP. (Compare ツ.)",
    "ス": "A person SUrfing on one leg, arm out for balance.",
    "セ": "Like せ, but with straight sharp lines: SE.",
    "ソ": "Two strokes falling DOWN from the top: SO the rain falls. (Compare ン.)",
    "タ": "Like ク with an extra stroke inside: a TAg tucked onto a hook.",
    "チ": "A CHIef with a flat hat and both arms out.",
    "ツ": "Two dots on TOP and a stroke falling DOWN: TSU rain from above. (Compare シ.)",
    "テ": "Like て (hand), but squared off: same TE sound, sharper corners.",
    "ト": "A TOggle switch: a post with a lever sticking out.",
    "ナ": "A cross leaning over: a NAil bent at the tip.",
    "ニ": "Two lines: 二 means “two”, read NI.",
    "ヌ": "Like フ with a slash: NUnchucks swinging.",
    "ネ": "A person with arms out and a dot on the NEck.",
    "ノ": "One slash, like crossing something out: “NO!”",
    "ハ": "Two lines spreading apart like a big laugh: “HA!”",
    "ヒ": "The HEEl of a shoe, seen from the side.",
    "フ": "A hook on the wall to hang your FUton.",
    "ヘ": "Same shape as hiragana へ, “HEY”. Nothing new to learn!",
    "ホ": "A cross with two little legs: HOlding up a table.",
    "マ": "A MArtini glass tipped over.",
    "ミ": "Three slanted lines: “ME, ME, ME!”",
    "ム": "An arm bent to flex a MUscle.",
    "メ": "An X mark: MEss up and it gets crossed out.",
    "モ": "Like も, but drawn with straight lines: a MOdel of も.",
    "ヤ": "Like や without the dot: a YArdstick with a hook.",
    "ユ": "A U-bolt lying on its side: “YOU”.",
    "ヨ": "A backwards capital E: “YO, it's flipped!”",
    "ラ": "Like フ with a lid on top: an old RAdio.",
    "リ": "Same idea as り: two RIvers, just straighter.",
    "ル": "Two legs walking: RU-n!",
    "レ": "Looks like a capital L. Japanese doesn't separate L and R: RE.",
    "ロ": "A box, like 口 “mouth”: a little ROom.",
    "ワ": "Like ウ without the top dash: a WAsh basin.",
    "ヲ": "Like ワ with an extra bar: “WOah, too many lines!” (said like “o”)",
    "ン": "Two strokes rising UP from the bottom left, like a sideways smile: N. (Compare ソ.)",
}

_DAKUTEN = {"g": "k → g", "z": "s → z", "d": "t → d", "b": "h → b"}


def _base_of(ch: str) -> str | None:
    """Undo dakuten/handakuten via Unicode decomposition (が → か)."""
    import unicodedata
    d = unicodedata.normalize("NFD", ch)
    return d[0] if len(d) == 2 else None


def hook_for(script: str, kana: str, romaji: str, group: str) -> str:
    table = HIRAGANA if script == "hiragana" else KATAKANA
    if kana in table:
        return table[kana]
    if kana == "ッ":
        return "Small ッ is a tiny pause: it doubles the next consonant. マッチ = ma-t-chi (“match”)."
    if kana == "ー":
        return "A long dash stretches the vowel before it: コーヒー = koohii (“coffee”)."
    if kana == "ヴ":
        return "ウ (u) with the two voicing dots ゛: a “V” sound, VU."
    if group == "voiced" and len(kana) == 1:
        base = _base_of(kana)
        if base:
            if kana in ("ぢ", "ヂ", "づ", "ヅ"):
                same = {"ぢ": "じ", "ヂ": "ジ", "づ": "ず", "ヅ": "ズ"}[kana]
                return f"{base} + ゛. Sounds the same as {same} ({romaji.upper()}); you'll rarely see it."
            if romaji.startswith("p"):
                return f"{base} + ゜ (a little circle): the circle pops h → p, like a balloon. {romaji.upper()}."
            return f"{base} + ゛ (two dots): the dots make it voiced ({_DAKUTEN.get(romaji[0], '')}). {romaji.upper()}."
    if len(kana) == 2:
        first = kana[0]
        small = kana[1]
        return f"Big {first} + small {small}, said together quickly as one beat: {romaji.upper()}."
    return ""
