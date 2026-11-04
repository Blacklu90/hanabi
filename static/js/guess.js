// Guess the reading of an unstudied word made of kanji you know. The server checks every answer.
import { $, api, get, reward, toast } from './app.js';
import { furigana, h, kanjiRows } from './words-ui.js';
import { say, sayButton } from './speak.js';

const root = $('[data-guess]');
const el = {
  word: $('[data-g-word]', root), meaning: $('[data-g-meaning]', root), form: $('[data-g-form]', root),
  cluesBtn: $('[data-g-clues-btn]', root), skip: $('[data-g-skip]', root), clues: $('[data-g-clues]', root),
  result: $('[data-g-result]', root), verdict: $('[data-g-verdict]', root), furi: $('[data-g-furi]', root),
  rows: $('[data-g-rows]', root), hint: $('[data-g-hint]', root), sentence: $('[data-g-sentence]', root),
  add: $('[data-g-add]', root), next: $('[data-g-next]', root), score: $('[data-g-score]'),
};
let cur = null, answered = false;
const seen = [];
let right = 0, total = 0;

function showClues(clues) {
  el.clues.replaceChildren();
  for (const c of clues) {
    const p = h('p', 'small');
    const k = h('b', 'jp', c.char); p.append(k, ' — ');
    if (c.word) {
      p.append('you know it from ', h('span', 'jp', c.word), ' (', h('span', 'jp', c.reading), ')');
      if (c.part) p.append(', where it reads ', h('b', 'jp', c.part), c.kind ? ` (${c.kind})` : '');
    } else p.append('readings: ', h('span', 'jp', c.readings || '—'));
    el.clues.append(p);
  }
}

async function load() {
  answered = false;
  el.result.hidden = true; el.clues.hidden = true; el.form.hidden = false;
  el.cluesBtn.hidden = false; el.skip.hidden = false;
  el.form.answer.value = '';
  try {
    const r = await get(`/api/guess/next?skip=${seen.slice(-80).join(',')}`);
    if (!r.word) {
      el.word.textContent = '✓';
      el.meaning.textContent = 'You can read every word we can build from your kanji so far. Learn more words and come back!';
      el.form.hidden = true; el.cluesBtn.hidden = true; el.skip.hidden = true;
      return;
    }
    cur = r; seen.push(r.id);
    el.word.textContent = r.word;
    el.meaning.textContent = r.meaning;
    showClues(r.clues);
    el.form.answer.focus();
  } catch (e) { toast(e.message, 'err'); }
}

el.form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (answered || !cur) return;
  try {
    const r = await api('/api/guess/answer', { id: cur.id, answer: el.form.answer.value });
    answered = true; total += 1; right += r.correct ? 1 : 0;
    el.form.hidden = true; el.cluesBtn.hidden = true; el.skip.hidden = true; el.clues.hidden = true;
    el.verdict.textContent = r.correct ? 'Yes! You read it.' : `Not quite — you wrote ${r.guess}.`;
    el.verdict.className = 'g-verdict ' + (r.correct ? 'ok' : 'no');
    el.furi.replaceChildren(furigana(r.parts), sayButton(r.word, r.reading));
    say(r.word, r.reading);
    el.rows.replaceChildren(kanjiRows(r.kanji));
    el.hint.textContent = r.hint || '';
    el.sentence.replaceChildren();
    if (r.sentence_jp) el.sentence.append(h('p', 'sentence-jp', r.sentence_jp), h('p', 'small muted', r.sentence_en));
    el.add.replaceChildren(r.in_deck ? h('span', 'pill good', 'In your deck') : Object.assign(h('button', 'btn', '+ Study this word'), { type: 'button', onclick: (ev) => addWord(ev.target) }));
    el.result.hidden = false;
    el.score.textContent = `${right} of ${total} read right this session`;
    el.next.focus();
    reward(r);
  } catch (err) { toast(err.message, 'err'); }
});

async function addWord(btn) {
  btn.disabled = true;
  try { const r = await api('/api/words/add', { ids: [cur.id] }); btn.replaceWith(h('span', 'pill good', `Added to ${r.deck}`)); }
  catch (e) { btn.disabled = false; toast(e.message, 'err'); }
}

el.cluesBtn.addEventListener('click', () => { el.clues.hidden = !el.clues.hidden; el.cluesBtn.textContent = el.clues.hidden ? 'Show clues' : 'Hide clues'; });
el.skip.addEventListener('click', load);
el.next.addEventListener('click', load);
document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && answered && !e.target.closest('input,textarea')) { e.preventDefault(); load(); } });
load();
