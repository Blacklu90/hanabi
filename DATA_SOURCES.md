# Data sources, licences and validation

No Japanese content in Hanabi is invented. The only hand-written parts are the kana tables (standard gojūon, modern Hepburn romaji), which **words** to teach, and their categories. Each word's meaning and kanji spelling are looked up in JMdict by `scripts/build_content.py`, and the build fails if a word can't be matched.

| Dataset | Edition | Used for | Licence |
|---|---|---|---|
| KANJIDIC2 (EDRDG), via jmdict-simplified 3.6.2 | 2026-11-02 | Jōyō set, school grades, meanings, on/kun/nanori, radical number, stroke count, frequency, old JLPT | CC BY-SA 4.0 |
| JMdict common words (EDRDG), via jmdict-simplified | 2026-11-02 | Kanji vocabulary (up to 6 per kanji), kana word meanings and parts of speech | CC BY-SA 4.0 |
| JMdict + examples (Tatoeba), via jmdict-simplified | 2026-11-02 | The full dictionary (219,007 entries) and example sentences (up to 2 per kanji, 1 per word) | JMdict: CC BY-SA 4.0 · Tatoeba: CC BY 2.0 FR |
| KanjiVG (Ulrich Apel), `master` branch | fetched 2026-11-03 | Stroke-order SVGs for all 2,136 kanji and all single kana | CC BY-SA 3.0 |
| Unicode Kangxi Radicals block (Python `unicodedata`) | — | Radical character and English name from the radical number | Unicode licence |

Downloads came from `github.com/scriptin/jmdict-simplified/releases` (tag `3.6.2+20261102210542`) and `raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/`. `scripts/fetch_sources.sh` repeats the dataset download. The raw JSON (~160 MB) isn't shipped. The built SQLite tables and the stroke SVGs are.

**Official vs. community data:** the Jōyō list (Agency for Cultural Affairs, 2010) and the elementary grade allocation (MEXT, revised 2020) are official government data. The numbers here come from KANJIDIC2's community encoding of them, which matches the official grade totals exactly.

## Validation (from `data/content_report.json` and `tests/test_data.py`)

| Check | Result |
|---|---|
| Jōyō kanji | **2,136** unique, index 1–2136 with no gaps |
| Grades 1 / 2 / 3 / 4 / 5 / 6 / secondary | 80 / 160 / 200 / 202 / 193 / 191 / 1,110 ✓ (2020 allocation) |
| 2020 prefecture kanji (茨 媛 岡 潟 …) | All grade 4 ✓ |
| Unicode code points | All match `U+XXXX` of the character |
| Every kanji has meaning, a reading, radical, strokes | ✓ |
| Stroke SVG available | 2,136 / 2,136 kanji, all single kana |
| Kanji vocabulary | 10,099 words; 2,093 kanji have ≥1 (the other 43 appear in no common JMdict word) |
| Example sentences | 3,674; 1,999 kanji have ≥1 |
| Kana vocabulary | 188 (103 hiragana, 85 katakana), 182 with a sentence, 12 categories |
| KANJIDIC2 vs KanjiVG stroke counts | **9 differ**: 餌 14/15, 牙 5/4, 葛 11/12, 僅 12/13, 遡 13/14, 遜 13/14, 賭 15/16, 謎 16/17, 餅 14/15. The app shows the KANJIDIC2 count and notes KanjiVG's on the kanji page. |

Not included: old (kyūjitai) character forms. KANJIDIC2 only gives them as JIS code references, so mapping them reliably would need another dataset. Radical *readings* aren't included either; only the radical name comes from Unicode.
