// Dictionary: live search as you type (server-rendered results, debounced, cancellable), add words, manage your dictionaries.
import { $, api, toast } from './app.js';

const form = $('[data-dict-form]'), input = $('#dq'), out = $('[data-dict-results]');
const csrf = () => document.querySelector('meta[name="csrf"]').content;
let timer = null, ctrl = null, last = input.value.trim();
const cache = new Map();

async function run(q, push) {
  last = q;
  const url = q ? `/dictionary?q=${encodeURIComponent(q)}` : '/dictionary';
  history[push ? 'pushState' : 'replaceState'](null, '', url);
  document.title = `${q ? q + ' · ' : ''}Dictionary · 花火`;
  $('[data-dict-tips]')?.toggleAttribute('hidden', !!q);
  if (!q) { out.replaceChildren(); return; }
  if (cache.has(q)) { out.innerHTML = cache.get(q); return; }
  ctrl?.abort(); ctrl = new AbortController();
  out.setAttribute('aria-busy', 'true');
  try {
    const res = await fetch(url, { signal: ctrl.signal, headers: { 'X-Partial': '1' } });
    const html = await res.text();
    cache.set(q, html);
    if (q === last) out.innerHTML = html;  // our own server-rendered, escaped HTML
  } catch (e) { if (e.name !== 'AbortError') toast('Search failed. Check your connection.', 'err'); }
  out.removeAttribute('aria-busy');
}

input.addEventListener('input', () => {
  clearTimeout(timer);
  const q = input.value.trim();
  if (q === last) return;
  timer = setTimeout(() => run(q, false), 180);
});
input.addEventListener('compositionend', () => input.dispatchEvent(new Event('input')));  // Japanese IME
form.addEventListener('submit', (e) => { e.preventDefault(); clearTimeout(timer); run(input.value.trim(), true); });
addEventListener('popstate', () => { input.value = new URL(location.href).searchParams.get('q') || ''; run(input.value.trim(), false); });

// Add a word to a deck
out.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-add-word]');
  if (!b) return;
  const deck = b.parentElement.querySelector('[data-add-deck]')?.value || 0;
  b.classList.add('is-busy');
  try {
    const r = await api(`/api/dictionary/${b.dataset.addWord}/add?deck=${deck}`, {});
    const pill = Object.assign(document.createElement('span'), { className: 'pill gold', textContent: `✓ In “${r.deck}”` });
    b.parentElement.replaceChildren(pill);
    cache.clear();
    toast(r.added ? `Added to “${r.deck}”. It shows up as a new card.` : 'Already in a deck.');
  } catch (err) { b.classList.remove('is-busy'); toast(err.message, 'err'); }
});

// Your dictionaries
const imp = $('[data-dict-import]');
imp.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = imp.file.files[0];
  if (!file) return;
  const msg = $('[data-dict-msg]'), btn = imp.querySelector('button');
  btn.classList.add('is-busy'); msg.textContent = `Importing ${file.name}… big dictionaries take a minute.`;
  const fd = new FormData(); fd.append('file', file);
  try {
    const res = await fetch('/api/dictionaries/import', { method: 'POST', body: fd, headers: { 'X-CSRF-Token': csrf() } });
    const r = await res.json();
    if (!r.ok) throw new Error(r.error);
    location.href = `/dictionary${last ? `?q=${encodeURIComponent(last)}` : ''}#my-dicts`;
    toast(`Imported “${r.title}”: ${r.entries.toLocaleString()} entries ✓`, 'gold', 5000);
  } catch (err) { msg.textContent = err.message; btn.classList.remove('is-busy'); }
});
document.addEventListener('change', async (e) => {
  const t = e.target.closest('[data-dict-toggle]');
  if (!t) return;
  try { await api(`/api/dictionaries/${t.dataset.dictToggle}/${t.checked ? 'enable' : 'disable'}`, {}); cache.clear(); if (last) run(last, false); }
  catch (err) { t.checked = !t.checked; toast(err.message, 'err'); }
});
document.addEventListener('click', async (e) => {
  const d = e.target.closest('[data-dict-delete]');
  if (!d) return;
  if (!confirm(`Delete the dictionary “${d.dataset.title}”? You can import it again later.`)) return;
  try { await api(`/api/dictionaries/${d.dataset.dictDelete}/delete`, {}); location.reload(); } catch (err) { toast(err.message, 'err'); }
});
