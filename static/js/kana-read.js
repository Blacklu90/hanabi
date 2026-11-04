// Read it: read an unstudied kana word made of kana you know. The server checks every answer.
import { $, api, get, reward, toast } from './app.js';
import { h, kanaNotes, kanaRows } from './words-ui.js';
import { say, sayButton } from './speak.js';

const root = $('[data-read]');
const script = root.dataset.script;
const q = (s) => $(s, root);
const el = {
  word: q('[data-g-word]'), form: q('[data-g-form]'), skip: q('[data-g-skip]'), result: q('[data-g-result]'),
  verdict: q('[data-g-verdict]'), romaji: q('[data-g-romaji]'), meaning: q('[data-g-meaning]'), written: q('[data-g-written]'),
  rows: q('[data-g-rows]'), notes: q('[data-g-notes]'), hint: q('[data-g-hint]'), sentence: q('[data-g-sentence]'),
  add: q('[data-g-add]'), next: q('[data-g-next]'), score: $('[data-g-score]'),
};
let cur = null, answered = false, right = 0, total = 0;
const seen = [];

async function load() {
  answered = false;
  el.result.hidden = true; el.form.hidden = false; el.skip.hidden = false; el.form.answer.value = '';
  try {
    const r = await get(`/api/kana/${script}/read/next?skip=${seen.slice(-80).join(',')}`);
    if (!r.word) {
      el.word.textContent = '✓';
      el.form.hidden = true; el.skip.hidden = true;
      el.verdict.textContent = 'You can read every word we have for the kana you know. The next lesson unlocks more!';
      el.result.hidden = false; el.next.hidden = true;
      return;
    }
    cur = r; seen.push(r.id);
    el.word.textContent = r.word;
    el.form.answer.focus();
  } catch (e) { toast(e.message, 'err'); }
}

el.form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (answered || !cur) return;
  try {
    const r = await api(`/api/kana/${script}/read/answer`, { id: cur.id, answer: el.form.answer.value });
    answered = true; total += 1; right += r.correct ? 1 : 0;
    el.form.hidden = true; el.skip.hidden = true;
    el.verdict.textContent = r.correct ? 'Yes! You read it.' : `Not quite — it says ${r.romaji}.`;
    el.verdict.className = 'g-verdict ' + (r.correct ? 'ok' : 'no');
    el.romaji.textContent = r.romaji;
    el.meaning.textContent = r.meaning;
    el.written.textContent = r.written ? `Usually written ${r.written}` : '';
    el.rows.replaceChildren(kanaRows(r.rows), sayButton(r.word));
    say(r.word);
    el.notes.replaceChildren(kanaNotes(r.rows));
    el.hint.textContent = r.hint || '';
    el.sentence.replaceChildren();
    if (r.sentence_jp) el.sentence.append(h('p', 'sentence-jp', r.sentence_jp), h('p', 'small muted', r.sentence_en || ''));
    el.add.replaceChildren(r.in_deck ? h('span', 'pill good', 'In your deck')
      : Object.assign(h('button', 'btn', '+ Study this word'), { type: 'button', onclick: (ev) => addWord(ev.target) }));
    el.result.hidden = false; el.next.hidden = false;
    el.score.textContent = `${right} of ${total} read right this session`;
    el.next.focus();
    reward(r);
  } catch (err) { toast(err.message, 'err'); }
});

async function addWord(btn) {
  btn.disabled = true;
  try { const r = await api(`/api/kana/${script}/words/add`, { ids: [cur.id] }); btn.replaceWith(h('span', 'pill good', `Added to ${r.deck}`)); }
  catch (e) { btn.disabled = false; toast(e.message, 'err'); }
}

el.skip.addEventListener('click', load);
el.next.addEventListener('click', load);
document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && answered && !e.target.closest('input,textarea')) { e.preventDefault(); load(); } });
load();
