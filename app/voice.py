"""How does this word sound? Three sources, best first:

1. A recording from one of *your* imported Anki decks (e.g. a 1.5k deck with native audio):
   each note's first field (the word) and any reading/furigana field are matched to the note's
   word recording (a field with "audio"/"sound" in its name that isn't a sentence, else the first sound).
2. The built-in offline voice: Open JTalk with the "Mei" voice (pyopenjtalk-plus). On Linux it is
   installed once into the data folder (`shuinkan --install-voice`, the installer, or Settings); the
   Windows build ships with it.
3. Otherwise the page uses the device's own Japanese voice (Android's text-to-speech).
"""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import wave
import zipfile
from pathlib import Path

from sqlalchemy import String, cast, func, select

from . import db

# ------------------------------------------------------------- deck audio
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_TAG = re.compile(r"<[^>]+>")
_FURI = re.compile(r" ?([^ \[\]]+)\[([^\]]+)\]")
_SENTENCE = re.compile(r"sentence|example|例文|文", re.I)
_AUDIO_NAME = re.compile(r"audio|sound|音声|発音", re.I)
_READING_NAME = re.compile(r"reading|kana|furigana|読み|かな", re.I)
_index_lock = threading.Lock()
_index: dict[int, tuple[tuple, dict]] = {}  # user -> (signature, {text: (deck_id, media name)})


def _plain(s: str) -> str:
    s = _SOUND.sub("", s or "")
    s = re.sub(r"<br\s*/?>|&nbsp;", " ", s, flags=re.I)
    s = _TAG.sub("", s)
    return re.sub(r"\s+", "", s).strip()


def _furi_forms(s: str) -> list[str]:
    """'私[わたし]は' -> ['私は', 'わたしは']."""
    s = _TAG.sub("", _SOUND.sub("", s or ""))
    if "[" not in s:
        return []
    base = _FURI.sub(lambda m: m.group(1), s)
    kana = _FURI.sub(lambda m: m.group(2), s)
    return [re.sub(r"\s+", "", base), re.sub(r"\s+", "", kana)]


def _word_sound(fields: dict) -> str | None:
    named = [(k, _SOUND.findall(v or "")) for k, v in fields.items()]
    for k, snds in named:  # a field named like "Word Audio"
        if snds and _AUDIO_NAME.search(k) and not _SENTENCE.search(k):
            return snds[0]
    for k, snds in named:  # else the first sound outside sentence fields
        if snds and not _SENTENCE.search(k):
            return snds[0]
    return None


def deck_index(c, uid: int) -> dict:
    cc = db.custom_cards.c
    sig = tuple(c.execute(select(func.count(), func.max(cc.id)).where(cc.user_id == uid, cc.fields_json.isnot(None))).one())
    with _index_lock:
        hit = _index.get(uid)
        if hit and hit[0] == sig:
            return hit[1]
    idx: dict[str, tuple[int, str]] = {}
    sc = db.srs_cards.c
    rows = c.execute(select(cc.id, cc.fields_json, sc.deck_id).join(db.srs_cards, (sc.item == cast(cc.id, String)) & (sc.track == "card")
                                                                      & (sc.user_id == uid))
                     .where(cc.user_id == uid, cc.fields_json.isnot(None))).all()
    for r in rows:
        try:
            fields = json.loads(r.fields_json)
        except ValueError:
            continue
        snd = _word_sound(fields)
        if not snd or r.deck_id is None:
            continue
        keys = []
        vals = list(fields.items())
        if vals:
            keys.append(_plain(vals[0][1]))
            keys += _furi_forms(vals[0][1])
        for k, v in vals[1:]:
            if _SENTENCE.search(k):
                continue
            if _READING_NAME.search(k):
                keys += _furi_forms(v) or [_plain(v)]
        for key in keys:
            if key and len(key) <= 20:
                idx.setdefault(key, (r.deck_id, snd))
    with _index_lock:
        _index[uid] = (sig, idx)
    return idx


def deck_audio(c, uid: int, *texts: str) -> tuple[int, str] | None:
    idx = deck_index(c, uid)
    for t in texts:
        t = re.sub(r"\s+", "", t or "")
        if t and t in idx:
            return idx[t]
    return None


# ---------------------------------------------------------- built-in voice
PINNED = [  # (package, version) — exact versions, checked against PyPI's sha256
    ("pyopenjtalk-plus", "0.4.1.post10"),
    ("sudachipy", "0.7.0"),
    ("sudachidict_core", "20261015"),
    ("numpy", "2.5.4"),
    ("typing_extensions", "4.16.0"),
]
CREDIT = 'Built-in voice: HTS Voice "Mei" © Nagoya Institute of Technology (CC BY 3.0), via Open JTalk / pyopenjtalk-plus.'
_engine = None
_engine_lock = threading.Lock()
_install = {"state": "idle", "message": "", "done": 0, "total": 0}


def voice_root() -> Path:
    env = os.environ.get("SHUINKAN_VOICE_DIR")
    if env:
        return Path(env)
    return Path(db.DB_PATH).resolve().parent / "voice"


def voice_dir() -> Path:
    return voice_root() / f"py{sys.version_info[0]}{sys.version_info[1]}"


def can_install() -> bool:
    """Linux/macOS installs (not the frozen Windows build, which ships the voice; not Android, which uses the phone's voice)."""
    return not getattr(sys, "frozen", False) and not os.environ.get("ANDROID_DATA") and sys.platform != "win32"


def _load():
    global _engine
    with _engine_lock:
        if _engine is not None:
            return _engine or None
        d = voice_dir()
        if (d / ".complete").exists() and str(d) not in sys.path:
            sys.path.insert(0, str(d))
        try:
            import contextlib
            import warnings
            with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):  # it prints an optional-feature note
                warnings.simplefilter("ignore")
                _engine = importlib.import_module("pyopenjtalk")
        except Exception:  # noqa: BLE001 — not installed (or broken): fall back to other sources
            _engine = False
        return _engine or None


def available() -> bool:
    return _load() is not None


def _cache_dir() -> Path:
    p = voice_root() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def clip_id(text: str) -> str:
    return hashlib.sha256(("mei1|" + text).encode()).hexdigest()[:32]


def synth(text: str) -> bytes | None:
    """WAV bytes for a short Japanese text (cached on disk)."""
    text = text.strip()[:120]
    if not text:
        return None
    f = _cache_dir() / f"{clip_id(text)}.wav"
    if f.exists():
        return f.read_bytes()
    eng = _load()
    if eng is None:
        return None
    with _engine_lock:  # Open JTalk isn't thread-safe
        x, sr = eng.tts(text)
    import numpy as np
    pcm = np.clip(x, -32768, 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm)
    data = buf.getvalue()
    tmp = f.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, f)
    return data


# ---------------------------------------------------------------- installer
def _platform_ok(fname: str) -> bool:
    import platform
    m = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(m, m)
    if fname.endswith("-none-any.whl"):
        return True
    if sys.platform.startswith("linux"):
        return "manylinux" in fname and fname.endswith(f"{arch}.whl")
    if sys.platform == "darwin":
        return "macosx" in fname and ("universal2" in fname or arch in fname)
    if sys.platform == "win32":
        return fname.endswith("win_amd64.whl") and arch == "x86_64"
    return False


def pick_wheel(files: list[dict]) -> dict | None:
    """The wheel for this Python and computer from a PyPI release's file list."""
    tag = f"cp{sys.version_info[0]}{sys.version_info[1]}"
    best = None
    for f in files:
        n = f["filename"]
        if not n.endswith(".whl") or not _platform_ok(n):
            continue
        py = n.split("-")[-3]
        abi = n.split("-")[-2]
        if (py == tag and abi == tag) or abi == "none" and py.startswith("py3"):
            return f
        if abi == "abi3" and py.startswith("cp3") and int(py[3:]) <= sys.version_info[1]:
            best = best or f
    return best


def install_status() -> dict:
    return {**_install, "installed": available(), "can_install": can_install()}


def install(progress=print) -> bool:
    """Download the pinned wheels from PyPI (sha256-checked) and unpack them into the voice folder."""
    if available():
        progress("The Japanese voice is already installed.")
        return True
    if not can_install():
        progress("The built-in voice can't be installed here.")
        return False
    _install.update(state="working", message="Finding the voice files…", done=0, total=len(PINNED))
    target = voice_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="voice-", dir=target.parent))
    try:
        for i, (name, version) in enumerate(PINNED, 1):
            with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as r:
                meta = json.load(r)
            f = pick_wheel(meta["urls"])
            if not f:
                raise RuntimeError(f"No {name} build for this computer (Python {sys.version_info[0]}.{sys.version_info[1]}).")
            msg = f"Downloading {name} ({f['size'] / 1e6:.0f} MB, {i}/{len(PINNED)})…"
            _install.update(message=msg, done=i - 1)
            progress(msg)
            h = hashlib.sha256()
            whl = tmp / f["filename"]
            with urllib.request.urlopen(f["url"], timeout=60) as r, open(whl, "wb") as out:
                while chunk := r.read(1 << 20):
                    h.update(chunk)
                    out.write(chunk)
            if h.hexdigest() != f["digests"]["sha256"]:
                raise RuntimeError(f"{name} didn't download correctly (checksum mismatch). Try again.")
            with zipfile.ZipFile(whl) as z:
                for member in z.namelist():
                    dest = (tmp / "site" / member).resolve()
                    if not str(dest).startswith(str((tmp / "site").resolve())):
                        raise RuntimeError("Unsafe file in download.")
                z.extractall(tmp / "site")
            whl.unlink()
        site = tmp / "site"
        for data in site.glob("*.data"):  # wheels may put code under name.data/purelib|platlib
            for sub in ("purelib", "platlib"):
                if (data / sub).is_dir():
                    for item in (data / sub).iterdir():
                        shutil.move(str(item), site / item.name)
        (site / ".complete").write_text(time.strftime("%Y-%m-%d"), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        os.replace(site, target)
        global _engine
        _engine = None
        if not available():
            raise RuntimeError("The voice was downloaded but doesn't start on this computer.")
        synth("こんにちは")  # warm up (loads the dictionary once)
        _install.update(state="done", message="The Japanese voice is ready.", done=len(PINNED))
        progress("The Japanese voice is ready. ✓")
        return True
    except Exception as e:  # noqa: BLE001
        msg = f"Couldn't install the voice: {e}"
        _install.update(state="error", message=msg)
        progress(msg)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_in_background() -> dict:
    if _install["state"] != "working":
        _install.update(state="working", message="Starting…")
        threading.Thread(target=install, kwargs={"progress": lambda m: None}, name="voice-install", daemon=True).start()
    return install_status()


if __name__ == "__main__":  # python -m app.voice --install
    if "--install" in sys.argv:
        sys.exit(0 if install() else 1)
    print("available:", available())
