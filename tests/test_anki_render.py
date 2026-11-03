"""Imported Anki cards look like they do in Anki: templates, furigana, cloze, images, fonts and recorded audio.
Fixtures were made with the official Anki 26.09 engine (newest + legacy package formats)."""
from pathlib import Path

import pytest

from app import anki_render as ar

FIX = Path(__file__).parent / "fixtures"


def upload(user, name):
    r = user.c.post("/api/import/apkg", files={"file": (name, (FIX / name).read_bytes())}, headers={"X-CSRF-Token": user._tok})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("fname", ["anki-media-modern.apkg", "anki-media-legacy.apkg"])
def test_import_cards_media_and_templates(user, fname):
    j = upload(user, fname)
    assert j["cards"] == 6 and j["images"] == 1 and j["audio"] == 1 and j["media"] == 3  # 2 notes x 2 templates + 2 cloze
    q = user.c.get("/api/review/queue", params={"deck": j["deck_id"]}).json()["cards"]
    fronts = [c["front"] for c in q]
    assert fronts == ["全然", "not at all", "私", "I (polite)", "[city]は日本の首都です。", "東京は[...]の首都です。"]
    back = user.c.get(q[0]["anki"]["back"])
    assert back.status_code == 200
    csp = back.headers["content-security-policy"]
    assert "script-src 'none'" in csp and "sandbox" in csp and back.headers["x-frame-options"] == "SAMEORIGIN"
    h = back.text
    assert "<ruby><rb>全然</rb><rt>ぜんぜん</rt></ruby>" in h                      # {{furigana:...}}
    assert f'src="/anki-media/{j["deck_id"]}/boy.png"' in h                       # image
    assert 'class="replay-button soundLink"' in h and '<audio class="anki-sound"' in h and "word.mp3" in h  # ▶ button + audio
    assert f'url("/anki-media/{j["deck_id"]}/_jpfont.ttf")' in h                  # deck font
    assert "<script" not in h and "onclick" not in h and "javascript:" not in h   # deck scripts never sent
    assert "no notes" not in h                                                    # {{^Notes}} hidden when Notes has text
    # {{FrontSide}} doesn't repeat the question's audio (like Anki); the front itself has none here
    img = user.c.get(f"/anki-media/{j['deck_id']}/boy.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content.startswith(b"\x89PNG")
    aud = user.c.get(f"/anki-media/{j['deck_id']}/word.mp3", headers={"Range": "bytes=0-2"})
    assert aud.status_code == 206 and aud.headers["content-range"].startswith("bytes 0-2/") and aud.content == b"ID3"
    cloze_back = user.c.get(q[4]["anki"]["back"]).text
    assert '<span class="cloze">東京</span>' in cloze_back
    night = user.c.get(q[0]["anki"]["front"] + "&night=1").text
    assert 'class="card card1 nightMode night_mode"' in night


def test_real_audio_deck(user):
    j = upload(user, "anki-audio.apkg")
    assert j["audio"] == 1 and j["cards"] == 1
    c = user.c.get("/api/review/queue", params={"deck": j["deck_id"]}).json()["cards"][0]
    front = user.c.get(c["anki"]["front"]).text
    assert "<audio" in front and "tone.wav" in front
    wav = user.c.get(f"/anki-media/{j['deck_id']}/tone.wav")
    assert wav.headers["content-type"] == "audio/wav" and wav.content[:4] == b"RIFF"


def test_media_and_cards_are_private_and_deleted_with_deck(user, user2):
    j = upload(user, "anki-media-modern.apkg")
    c = user.c.get("/api/review/queue", params={"deck": j["deck_id"]}).json()["cards"][0]
    assert user2.c.get(c["anki"]["back"]).status_code == 404
    assert user2.c.get(f"/anki-media/{j['deck_id']}/boy.png").status_code == 404
    assert user.post(f"/api/decks/{j['deck_id']}/delete").json()["ok"]
    assert user.c.get(f"/anki-media/{j['deck_id']}/boy.png").status_code == 404
    assert user.c.get(c["anki"]["back"]).status_code == 404


def test_template_engine():
    model = {"name": "T", "kind": 0, "tmpls": [{"name": "C1", "qfmt": "{{Front}}{{#Pic}}<p>has pic</p>{{/Pic}}{{^Pic}}<p>no pic</p>{{/Pic}}",
                                                 "afmt": "{{FrontSide}}<hr id=answer>{{kana:R}}|{{kanji:R}}|{{text:B}}|{{hint:H}}|{{type:B}}|{{Tags}}|{{Deck}}|{{Card}}"}]}
    r = ar.render_card(model, {"Front": "猫 [sound:a.mp3]", "Pic": "", "R": "猫[ねこ]", "B": "<b>cat</b>", "H": "pet"}, 0,
                       deck_id=1, deck="A::B", tags="animal")
    assert "<p>no pic</p>" in r["front"] and "has pic" not in r["front"]
    assert r["front"].count("<audio") == 1 and r["back"].count("<audio") == 0     # FrontSide drops question audio
    assert "|ねこ|" not in r["back"] and "ねこ|猫|cat|" in r["back"]
    assert "<details class=hint>" in r["back"] and "|animal|A::B|C1" in r["back"]
    assert ar.furigana(" 日本語[にほんご]") == "<ruby><rb>日本語</rb><rt>にほんご</rt></ruby>"
    assert ar.cloze("{{c1::a}} {{c2::b::hint}}", 2, back=False) == 'a <span class="cloze">[hint]</span>'
    assert ar._rewrite_media('<img src="http://evil.example/x.png"><a href="javascript:alert(1)">x</a>', 3).count("about:blank") == 2
    assert ar.rewrite_css('@import url("http://x/y.css"); .a{background:url(bg.png)}', 3).strip() == '.a{background:url("/anki-media/3/bg.png")}'


def test_two_recordings_become_two_round_buttons(user):
    j = upload(user, "anki-two-sounds.apkg")
    assert j["audio"] == 2 and j["images"] == 1
    c = user.c.get("/api/review/queue", params={"deck": j["deck_id"]}).json()["cards"][0]
    back = user.c.get(c["anki"]["back"]).text
    assert back.count('class="replay-button soundLink"') == 2 and back.count("<audio") == 2
    assert back.index("watashi_word.wav") < back.index("watashi_sentence.wav")  # played in this order
    assert "<ruby><rb>私</rb><rt>わたし</rt></ruby>はアンです。" in back and "watashi.png" in back
    assert "Note: Can also be read" in back
    assert user.c.get(c["anki"]["front"]).text.count("<audio") == 0  # this deck's front has no sound
