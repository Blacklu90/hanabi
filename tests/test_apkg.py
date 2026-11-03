"""Anki package import/export. Fixtures were exported by the official Anki 26.09 engine
(one in its newest zstd 'anki21b' format, one in legacy format)."""
import io
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app import apkg

FIX = Path(__file__).parent / "fixtures"


def upload(user, name, data):
    return user.c.post("/api/import/apkg", files={"file": (name, data, "application/octet-stream")},
                       headers={"X-CSRF-Token": user._tok})


@pytest.mark.parametrize("fname", ["anki-modern.apkg", "anki-legacy.apkg"])
def test_import_real_anki_packages(user, fname):
    r = upload(user, fname, (FIX / fname).read_bytes())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["cards"] == 4 and j["skipped"] == 1 and j["deck"].startswith("JLPT N5 › Vocab")
    q = user.c.get("/api/review/queue", params={"deck": j["deck_id"]}).json()["cards"]
    by = {c["front"]: c for c in q}
    assert by["猫"]["answer"] == "cat" and by["猫"]["anki"]["back"].startswith("/anki-card/")  # shown with the deck's template
    assert by["犬"]["answer"] == "dog\nhound"                                  # <b> and <br> handled
    assert by["水"]["answer"] == "water"                                       # <script>, [sound:], &nbsp; removed
    assert by["Hello"]["answer"] == "こんにちは"


def test_import_rejects_bad_files(user):
    assert upload(user, "x.apkg", b"not a zip").json()["error"].startswith("That isn't")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "hi")
    assert "No Anki collection" in upload(user, "x.apkg", buf.getvalue()).json()["error"]
    assert user.c.post("/api/import/apkg", files={"file": ("x.apkg", b"x")}).status_code == 403  # CSRF


def test_export_round_trip(user, tmp_path):
    d = user.post("/api/decks", {"name": "Exp", "new_per_day": 5, "max_reviews": 50}).json()["id"]
    user.post(f"/api/decks/{d}/kanji", {"chars": ["日", "月"]})
    user.post("/api/notes", {"track": "kanji", "item": "日", "mnemonic": "sun <window>"})
    user.post(f"/api/decks/{d}/cards", {"front": "おはよう", "back": "Good morning"})
    r = user.c.get(f"/api/decks/{d}/export.apkg")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) == {"collection.anki2", "media"}
    (tmp_path / "c.anki2").write_bytes(z.read("collection.anki2"))
    con = sqlite3.connect(tmp_path / "c.anki2")
    assert con.execute("select ver from col").fetchone()[0] == 11
    flds = [r[0].split("\x1f") for r in con.execute("select flds from notes order by id")]
    assert flds[0][0] == "日" and "sun &lt;window&gt;" in flds[0][8] and flds[2][:2] == ["おはよう", "Good morning"]
    assert con.execute("select count(*) from cards").fetchone()[0] == 3
    # and Shuinkan can import its own export
    back = upload(user, "Exp.apkg", r.content).json()
    assert back["cards"] == 3 and back["deck"] == "Shuinkan › Exp"
    assert user.c.get("/api/decks/all-kanji/export.apkg").status_code == 200
    assert user.c.get("/api/decks/999999/export.apkg").status_code == 404


def test_strip_html():
    assert apkg.strip_html('<div>a</div><div>b</div><script>x()</script>&amp;[sound:a.mp3]') == "a\nb\n&"
