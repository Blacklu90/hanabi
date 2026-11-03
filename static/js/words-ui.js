// Furigana + per-kanji reading breakdown, built with DOM methods (never innerHTML), and "+ Study this word" buttons.
import { $$, api, reward, toast } from './app.js';

const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

export function furigana(parts) {
  const out = h('span', 'furi'); out.lang = 'ja';
  for (const p of parts || []) {
    if (!p.ruby) { out.append(p.text); continue; }
    const r = h('ruby'); r.append(p.text, h('rt', '', p.ruby)); out.append(r);
  }
  return out;
}

export function kanjiRows(rows) {
  const ul = h('ul', 'kb');
  for (const r of rows || []) {
    const li = h('li');
    const a = h('a', 'kb-char jp', r.char); a.href = `/kanji/${encodeURIComponent(r.char)}`;
    li.append(a);
    if (r.reading) { const b = h('b', 'jp', r.reading); li.append(b); }
    li.append(h('span', `kind kind-${r.kind}`, r.label));
    if (r.base) li.append(h('span', 'tiny muted', `from ${r.base}${r.change ? ' · ' + r.change : ''}`));
    li.append(h('span', 'small muted', r.meaning));
    ul.append(li);
  }
  return ul;
}

export function wireAddWord(root = document) {
  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-add-word]');
    if (!btn) return;
    btn.disabled = true;
    try {
      const r = await api('/api/words/add', { ids: [Number(btn.dataset.addWord)] });
      const pill = h('span', 'pill good', `Added to ${r.deck}`);
      btn.replaceWith(pill);
      reward(r);
    } catch (err) { btn.disabled = false; toast(err.message, 'err'); }
  });
}
export { h };
