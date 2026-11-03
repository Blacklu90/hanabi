"""Render imported Anki cards with the deck's own templates and styling, like Anki does.

Supports what real decks use: {{Field}}, {{FrontSide}}, {{#Field}}…{{/Field}},
{{^Field}}…{{/Field}}, filters (furigana, kana, kanji, text, hint, type, cloze,
tts — chained like {{furigana:Reading}}), special fields ({{Tags}}, {{Deck}},
{{Subdeck}}, {{Card}}, {{Type}}), cloze deletions and media references.

The rendered HTML is shown inside a sandboxed iframe with a strict Content
Security Policy (no scripts, no outside requests), so deck HTML can't affect Shuinkan.
The deck's own recorded audio ([sound:file.mp3]) becomes a player; Shuinkan plays it
automatically like Anki (can be switched off in Settings).
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

TOKEN = re.compile(r"\{\{(.*?)\}\}", re.S)
FURI = re.compile(r" ?([^ >\[\]]+?)\[(.+?)\]")
SOUND = re.compile(r"\[sound:[^\]]*\]")
CLOZE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)
TAG = re.compile(r"<[^>]+>")
URL_ATTR = re.compile(r"""(\b(?:src|href)\s*=\s*)(["']?)([^"'>]+?)\2(?=[\s>/])""", re.I)
CSS_URL = re.compile(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", re.I)
SPECIAL = {"Tags", "Type", "Deck", "Subdeck", "Card", "CardFlag", "FrontSide"}


def strip_html(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1\s*>", "", s or "", flags=re.I | re.S)
    s = re.sub(r"<\s*(br|/div|/p|/li|hr)[^>]*>", "\n", s, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(TAG.sub("", SOUND.sub("", s))).replace("\xa0", " ")).strip()


def _nonempty(v: str) -> bool:
    return bool(strip_html(v).strip()) or "<img" in (v or "").lower()


# ------------------------------------------------------------ template parse
def _parse(tpl: str):
    """-> nested list of str | ("var", name) | ("sec", name, inverted, children)."""
    root, stack, pos = [], [], 0
    cur = root
    for m in TOKEN.finditer(tpl):
        if m.start() > pos:
            cur.append(tpl[pos:m.start()])
        tag = m.group(1).strip()
        if tag[:1] in "#^":
            node = ("sec", tag[1:].strip(), tag[0] == "^", [])
            cur.append(node)
            stack.append((cur, node[1]))
            cur = node[3]
        elif tag[:1] == "/":
            name = tag[1:].strip()
            if stack and stack[-1][1] == name:
                cur = stack.pop()[0]
        else:
            cur.append(("var", tag))
        pos = m.end()
    cur.append(tpl[pos:])
    return root


# --------------------------------------------------------------- filters
def furigana(s: str) -> str:
    return FURI.sub(lambda m: f"<ruby><rb>{m.group(1)}</rb><rt>{m.group(2)}</rt></ruby>", s)


def kana(s: str) -> str:
    return FURI.sub(lambda m: m.group(2), s)


def kanji(s: str) -> str:
    return FURI.sub(lambda m: m.group(1), s)


def cloze(text: str, n: int, back: bool) -> str:
    def rep(m):
        num, body, hint = int(m.group(1)), m.group(2), m.group(3)
        if num != n:
            return body
        if back:
            return f'<span class="cloze">{body}</span>'
        return f'<span class="cloze">[{html.escape(hint) if hint else "..."}]</span>'
    return CLOZE.sub(rep, text)


def cloze_numbers(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\{\{c(\d+)::", text or "")})


def _apply(filters: list[str], value: str, name: str, ctx: dict) -> str:
    for f in reversed(filters):  # Anki applies the filter nearest the field name first
        f = f.strip()
        if f == "furigana":
            value = furigana(value)
        elif f == "kana":
            value = kana(value)
        elif f == "kanji":
            value = kanji(value)
        elif f == "text":
            value = html.escape(strip_html(value))
        elif f == "hint":
            value = f"<details class=hint><summary>Show {html.escape(name)}</summary>{value}</details>" if _nonempty(value) else ""
        elif f == "type":
            value = ""  # typing answers isn't supported; the answer is shown on the back instead
        elif f in ("cloze", "cloze-only"):
            value = cloze(value, ctx["card_ord"] + 1, ctx["back"])
        elif f.startswith("tts"):
            value = ""
    return value


def _render(nodes, fields: dict, ctx: dict) -> str:
    out = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
        elif n[0] == "var":
            parts = n[1].split(":")
            name, filters = parts[-1].strip(), parts[:-1]
            if name == "FrontSide":
                out.append(ctx.get("front_html", ""))
                continue
            if name in SPECIAL:
                value = {"Tags": html.escape(ctx.get("tags", "")), "Type": html.escape(ctx.get("model", "")),
                         "Deck": html.escape(ctx.get("deck", "")), "Subdeck": html.escape(ctx.get("deck", "").split("::")[-1]),
                         "Card": html.escape(ctx.get("card_name", "")), "CardFlag": ""}[name]
            else:
                value = fields.get(name, "")
            out.append(_apply(filters, value, name, ctx))
        else:
            _, name, inverted, children = n
            name = name.split(":")[-1].strip()
            present = _nonempty(fields.get(name, "")) if name not in SPECIAL else bool(ctx.get(name.lower()))
            if present != inverted:
                out.append(_render(children, fields, ctx))
    return "".join(out)


def sounds(s: str) -> str:
    """[sound:file.mp3] -> Shuinkan's own ▶ button + a hidden audio element.
    The class names (replay-button, soundLink) are kept so decks that style or hide sound buttons still work.
    Shuinkan (the parent page) plays it on click and autoplays it."""
    return SOUND.sub(lambda m: (
        '<a class="replay-button soundLink" role="button" tabindex="0" aria-label="Play audio">'
        '<svg class="playImage" viewBox="0 0 40 40" aria-hidden="true"><rect class="pb-bg" x="1" y="1" width="38" height="38" rx="12"/>'
        '<path class="pb-arrow" d="M16 12.5 L28 20 L16 27.5 Z"/></svg></a>'
        f'<audio class="anki-sound" preload="auto" src="{html.escape(m.group(0)[7:-1], quote=True)}"></audio>'), s)


_SCRIPT = re.compile(r"<script\b[^>]*>.*?(</script\s*>|$)", re.I | re.S)
_ON_ATTR = re.compile(r"""\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)
_BAD_TAGS = re.compile(r"</?(iframe|object|embed|base|meta|link|form)\b[^>]*>", re.I)


def _clean(s: str) -> str:
    """Belt and braces: the card frame already blocks scripts, but don't even send them."""
    return _BAD_TAGS.sub("", _ON_ATTR.sub("", _SCRIPT.sub("", s)))


def media_url(deck_id: int, name: str) -> str:
    return f"/anki-media/{deck_id}/{quote(name)}"


def _rewrite_media(s: str, deck_id: int) -> str:
    def attr(m):
        url = html.unescape(m.group(3))
        if re.match(r"^[a-z][a-z0-9+.-]*:|^/|^#", url, re.I):
            if url.lower().startswith("data:image/"):
                return m.group(0)
            return f'{m.group(1)}"about:blank"'  # no outside requests, no javascript: links
        return f'{m.group(1)}"{media_url(deck_id, url)}"'
    return URL_ATTR.sub(attr, s)


def rewrite_css(css: str, deck_id: int) -> str:
    def u(m):
        url = m.group(2).strip()
        if re.match(r"^[a-z][a-z0-9+.-]*:|^/", url, re.I):
            return "url(about:blank)" if not url.lower().startswith("data:") else m.group(0)
        return f'url("{media_url(deck_id, url)}")'
    css = re.sub(r"@import[^;]*;", "", css, flags=re.I)
    return CSS_URL.sub(u, css)


def render_card(model: dict, fields: dict, card_ord: int, *, deck_id: int, deck: str = "", tags: str = "") -> dict:
    """-> {"front": html, "back": html, "front_text": str, "back_text": str, "class": "card cardN"}."""
    if model["kind"] == 1:
        tmpl = model["tmpls"][0]
        card_name = tmpl.get("name", "Cloze")
    else:
        tmpl = model["tmpls"][min(card_ord, len(model["tmpls"]) - 1)]
        card_name = tmpl.get("name", "")
    ctx = {"card_ord": card_ord, "deck": deck, "tags": tags.strip(), "model": model.get("name", ""), "card_name": card_name, "back": False}
    front = _render(_parse(tmpl["qfmt"]), fields, ctx)
    ctx.update(back=True, front_html=SOUND.sub("", front))  # like Anki: {{FrontSide}} doesn't repeat the question's audio
    back = _render(_parse(tmpl["afmt"]), fields, ctx)
    ft = strip_html(front)
    bt = strip_html(back.replace(front, "", 1))
    return {"front": _clean(_rewrite_media(sounds(front), deck_id)), "back": _clean(_rewrite_media(sounds(back), deck_id)),
            "front_text": ft, "back_text": bt,
            "class": f"card card{card_ord + 1}"}


BASE_CSS = """
html, body { margin: 0; }
body { padding: 20px 16px; font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif; font-size: 20px;
  line-height: 1.5; overflow-wrap: anywhere; }
.card { color: #1f1c19; background: #fffdf9; }
:where(.nightMode, .night_mode).card { color: #f1ece4; background: #1b1d25; }  /* low priority: a deck's own .card colours win */
img { max-width: 100%; height: auto; }
rt { font-size: .55em; }
hr#answer { border: 0; border-top: 1px solid rgba(128,128,128,.4); margin: 18px 0; }
.cloze { font-weight: bold; color: #2f5bd3; }
.nightMode .cloze { color: #8fb0ff; }
details.hint summary { cursor: pointer; color: #2f5bd3; }
audio.anki-sound { display: none; }
.replay-button { text-decoration: none; display: inline-flex; vertical-align: middle; margin: 4px; cursor: pointer; border-radius: 12px;
  transition: transform 80ms; }
.replay-button svg { width: 40px; height: 40px; display: block; }
.replay-button .pb-bg { fill: var(--hb-accent, #cc3f26); stroke: none; }
.replay-button .pb-arrow { fill: #fff; stroke: #fff; stroke-width: 2.5px; stroke-linejoin: round; }
.replay-button:hover .pb-bg { filter: brightness(.9); }
.replay-button:active { transform: scale(.94); }
.replay-button:focus-visible { outline: 3px solid #2f5bd3; outline-offset: 2px; }
.replay-button.playing .pb-bg { fill: #b97a0f; }
"""


def page(body_html: str, css: str, card_class: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<style>{BASE_CSS}\n{css}</style></head><body class=\"{html.escape(card_class)}\"><div id=qa>{body_html}</div></body></html>")


CARD_CSP = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src 'self' data:; media-src 'self'; "
            "script-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'; sandbox allow-same-origin")

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
               "svg": "image/svg+xml", "bmp": "image/bmp", "avif": "image/avif", "ttf": "font/ttf", "otf": "font/otf",
               "woff": "font/woff", "woff2": "font/woff2",
               "mp3": "audio/mpeg", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg", "wav": "audio/wav",
               "m4a": "audio/mp4", "aac": "audio/aac", "flac": "audio/flac", "webm": "audio/webm"}


def media_type(name: str) -> str | None:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return IMAGE_TYPES.get(ext)
