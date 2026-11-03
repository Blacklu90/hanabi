# 日本語 Hanabi — Japanese in short, focused bursts (Linux & Windows)

[![CI](https://github.com/Blacklu90/hanabi/actions/workflows/ci.yml/badge.svg)](https://github.com/Blacklu90/hanabi/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Blacklu90/hanabi)](https://github.com/Blacklu90/hanabi/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Hanabi is a complete Japanese-learning web app: hiragana, katakana, vocabulary, and all **2,136 Jōyō kanji**. It's built around short study sessions, one clear next step and instant feedback.

## Install on Linux

### AppImage (any distribution — easiest)

1. Download `Hanabi-<version>-x86_64.AppImage` from the [Releases](https://github.com/Blacklu90/hanabi/releases/latest) page.
2. Make it runnable and start it:
   ```bash
   chmod +x Hanabi-*-x86_64.AppImage
   ./Hanabi-*-x86_64.AppImage
   ```
3. Optional, to put it in your app menu:
   ```bash
   ./Hanabi-*-x86_64.AppImage --install
   ```

Hanabi opens in its **own window** if you have a Chromium-based browser (Chromium, Chrome, Brave, Vivaldi or Edge). Closing the window stops Hanabi. Without one, it opens in your default browser. Python is bundled, so there's nothing else to install. On very new distros without `libfuse2`, run it with `--appimage-extract-and-run` or install `fuse2`.

Your progress lives in `~/.local/share/hanabi/` and is kept across updates. To update, download the new AppImage (and run `--install` again if you use the menu entry). Other commands: `--browser` (open in your normal browser), `--stop`, `--uninstall` (keeps your progress), `--version`.

## Install on Windows

1. Download **`Hanabi-Setup-<version>.exe`** from the [Releases](https://github.com/Blacklu90/hanabi/releases/latest) page.
2. Run it. It installs just for you, with no admin rights needed, and adds Hanabi to the Start menu (a desktop shortcut is optional).
3. Start **Hanabi** from the Start menu.

Hanabi opens in its own window using Microsoft Edge, which comes with Windows (or Chrome or Brave if you prefer those). Closing the window stops Hanabi. Your progress is saved in `%LOCALAPPDATA%\Hanabi` and is kept if you uninstall.

Prefer no installer? Download **`Hanabi-<version>-windows-portable.zip`**, unzip it anywhere and run `Hanabi.exe`.

> Windows may show a "Windows protected your PC" warning the first time, because the app isn't code-signed. Click **More info → Run anyway**.

### Arch Linux

```bash
cd packaging/arch && makepkg -si
```

This installs the release AppImage as the `hanabi` command, with a menu entry.

### From source (developers)

```bash
git clone https://github.com/Blacklu90/hanabi && cd hanabi
./run.sh            # or ./install.sh for a menu entry
```

The first run builds the kanji and dictionary database from KANJIDIC2, JMdict and Tatoeba. That's about 1 minute and a ~160 MB download. It needs Python 3.11+, `curl` and `unzip`. Then open **http://127.0.0.1:8000**. You don't need Node.js or a build step.

### Build the AppImage yourself

```bash
./scripts/fetch_sources.sh && python -m scripts.build_content   # makes data/content.db
./scripts/build_appimage.sh                                       # makes dist/Hanabi-<version>-x86_64.AppImage
```

GitHub Actions does this automatically. Every push runs the tests on Linux and Windows and builds the AppImage, the Windows installer and the portable zip. Pushing a tag like `v1.0.0` publishes a release with all three attached.

## How it helps you study

- **One next step:** the home screen shows one big "Your next step" button, so you can start right away.
- **Focus bursts:** pick 2–25 minutes. A timer follows you, with a natural stop and a break prompt at the end.
- **Short lessons:** 3–7 characters each (~3 min). Study screens hide the navigation (**focus mode**, `Esc` to leave).
- **Instant feedback:** right/wrong straight away, small sparks, XP toasts and progress bars. All can be turned off.
- **Forgiving streaks:** one missed day is a free rest day. Only two in a row resets.
- **Calm mode:** no motion, plus light, dark and system themes. `prefers-reduced-motion` is respected.
- **Keyboard shortcuts everywhere** (`Space` reveal, `1–4` answer/rate, `Enter` next), big touch targets and a bottom tab bar on phones.

## Features

- **Hiragana**: 104 entries (46 basic, 25 voiced, 33 combinations) in 26 lessons.
- **Katakana**: 134 entries (adds 30 foreign-sound entries: ッ, ー, ヴ, ファ, ティ, ディ, ウィ…) in 32 lessons. The 30 specials are split into 6 short lessons instead of one long one.
- **Lessons**: meet one character at a time (stroke animation, memory hook, example words), do a no-pressure quick check, then the characters go into reviews.
- **Vocabulary**: 103 hiragana and 85 katakana words across 12 categories. Instant search, category filters, add to reviews. Meanings come from JMdict, and 182 words have a real Tatoeba sentence.
- **Kanji library**: all 2,136 Jōyō kanji. Search by character, meaning, kana or romaji reading, or a word (学校), and filter by grade, strokes, radical, status or old JLPT level. Paginated and debounced, with the next page prefetched.
- **Kanji pages**: meanings, on/kun readings, nanori, radical (number, character, name), stroke count, KanjiVG stroke-order animation (play / step / reset), frequency, words, Tatoeba sentences, same-radical kanji, and your own progress.
- **Spaced repetition** (server-side SM-2 variant): Again / Hard / Good / Easy, oldest-due first, per-track filters, and review history. Mastery uses your own thresholds (accuracy, correct-in-a-row, interval).
- **Quizzes**: 14 types (kana both ways, word meaning, fill-the-gap sentences, kanji meaning / reading / words / radical / stroke count / sentences, mixed, due reviews). Formats: 10 questions, **mastery test** (20 questions, pass at 80%), **60-second sprint**, **120-second challenge**. History and question-by-question results pages.
- **Writing practice**: canvas for mouse, finger and stylus (pressure-aware), with the KanjiVG guide underneath, a stroke-order player, undo, clear and hide guide. You check your own writing; there's no handwriting recognition.
- **Matching game**: 4 decks, 6 pairs, timer, moves, matches and misses.
- **Gamification**: XP, levels, a daily goal ring, kind streaks, 31 achievements, an activity feed, and weekly and 30-day charts.
- **Accounts**: registration, login, logout, password change (signs out other devices), password reset (SMTP or a clearly labelled dev link), profile and settings.

## Anki-style study (Kanji, words, your own cards)

- **Decks** (`/decks`) with Anki-style **daily limits**: *new cards per day* and *max reviews per day*. Counts show new / learning / due, like Anki. Add a whole school grade at once, or any Kanji-library search ("add these results to a deck"), single kanji from their page, or dictionary words.
- **Review buttons show the next interval** (Again 10m · Hard 12h · Good 1d · Easy 4d).
- **Undo** (Z), **Bury until tomorrow** (-), **Suspend** (@) and **Edit my notes** (E) while reviewing.
- **Card browser** (`/browse`): search, filter by deck/state/type, sort by due/interval/ease/lapses, and bulk suspend, bury, reset, move or delete.
- **Your own notes** on every kanji: your meaning (replaces the answer on the card), your memory hook and notes.
- **Write your own cards** in any deck.
- **Anki packages**: export any deck (or all 2,136 kanji) as `.apkg` for Anki/AnkiDroid (checked by importing with the official Anki 26.09 engine), and import `.apkg` files from Anki (all three package formats, up to 1 GB).
- **Imported cards look like they do in Anki**: each deck's own card templates and styling, one card per Anki card (several templates per note, cloze), images, fonts, `{{furigana:…}}` (ruby above the kanji), `kana:`/`kanji:`/`text:`/`hint:`/`cloze:` filters, `{{#…}}`/`{{^…}}` sections, and night mode.
- **Deck audio**: `[sound:…]` recordings in a deck play automatically when the card (front) appears and when you reveal it (back), like Anki; **R** replays. You can switch autoplay off in Settings.
- **Safe**: imported cards are shown in a sandboxed frame with a strict security policy (no scripts, no outside requests); scripts and event handlers in decks are also stripped before sending. Video isn't imported.

## Dictionary

`/dictionary` searches all of **JMdict (≈219,000 entries)** offline: Japanese (猫), kana (ねこ), romaji (neko) or English (cat). Exact and everyday words come first. Each entry shows readings, meanings by sense, the kanji used (linked) and an example sentence, and you can add any word to a deck.

**Your own dictionaries:** import a **Yomitan/Yomichan** dictionary (`.zip`, e.g. Jitendex, JMdict, monolingual dictionaries) or a **word list** (`.csv`/`.tsv`/`.txt`: `word, reading, meaning` or `word, meaning`). Results from your dictionaries show above the built-in ones, and you can turn each one on or off, or delete it.

## Security

- scrypt password hashing. Sessions live in the database as SHA-256 hashes of random tokens, in HttpOnly SameSite=Lax cookies (Secure when `HANABI_SECURE_COOKIES=1`). 30-day expiry.
- CSRF tokens on every form and API write, plus an Origin/Referer check.
- Rate limits on login, registration, password reset and password change.
- Strict CSP: scripts and styles only from the same origin. Inline `style=""` attributes are allowed, but `<style>` blocks and inline scripts are not. Also nosniff, frame-deny, referrer and permissions policies. No third-party scripts, fonts, analytics or ads.
- Every query is scoped to the logged-in user (tested).
- **Server-side scoring**: the browser never receives quiz answers. Answers must arrive in order, timed answers after the deadline are rejected, and the question on screen when time runs out counts as wrong.
- **No XP farming**: every award has a unique dedupe key (lesson, quiz, game, burst, achievement and review IDs). Reviews of cards that aren't due are refused. Repeatable activities are capped at 300 XP per day.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `HANABI_DB` | `data/hanabi.db` | SQLite database path |
| `HANABI_DEV` | `1` | Dev mode: shows the reset link on screen when no SMTP server is set |
| `HANABI_SECURE_COOKIES` | `0` in dev, `1` otherwise | Secure cookies + HSTS (use behind HTTPS) |
| `HANABI_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM` | — | Password-reset email |
| `HANABI_ALLOWED_ORIGINS` | — | Extra origins allowed for POSTs (reverse proxies) |

For production: set `HANABI_DEV=0`, put it behind HTTPS, and run a single uvicorn worker (the rate limiter is in-memory).

## Project layout

```
app/        main.py (app, middleware), pages.py (HTML routes), api.py (JSON API),
            db.py (schema, SQLite WAL), srs.py (scheduling, decks, limits), cards.py, apkg.py (Anki),
            dictionary.py, anki_render.py, desktop.py (Linux app launcher), quiz.py, gamify.py, content.py,
            kana.py (curriculum), vocab_list.py, security.py, web.py
templates/  Jinja2 pages        static/  css/app.css, js/*.js (ES modules, no build)
data/       content.db (shipped content: kanji, words, dictionary; replaced on update)
            hanabi.db  (your account + progress; created on first start and never replaced; content is
                        copied in from content.db automatically when a newer one ships)
            strokes/ (KanjiVG SVGs), content_report.json
scripts/    build_content.py, fetch_sources.sh, build_appimage.sh, benchmark.py
packaging/  hanabi.desktop, hanabi.png, arch/PKGBUILD, windows/ (PyInstaller recipe, Inno Setup installer, icon)
.github/    CI: tests on every push; AppImage on version tags
tests/      pytest suite
```

## Tests and benchmark

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # 114 tests
.venv/bin/python -m scripts.benchmark  # against a running server on :8765
```

## License

Hanabi's code is open source under the [MIT License](LICENSE). The bundled learning data (KANJIDIC2, JMdict, KanjiVG, Tatoeba) keeps its own licences. See [DATA_SOURCES.md](DATA_SOURCES.md).

## Data

See [DATA_SOURCES.md](DATA_SOURCES.md) and the in-app **About** page for provenance, licences and validation numbers.
