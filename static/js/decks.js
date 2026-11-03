// Decks: create/edit decks, add kanji by grade, write cards, delete, import .apkg.
import { $, $$, api, reward, toast } from './app.js';

const csrf = () => document.querySelector('meta[name="csrf"]').content;
const reload = (msg) => { location.href = '/decks' + (msg ? `?saved=${encodeURIComponent(msg)}` : ''); };

document.addEventListener('click', (e) => {
  const open = e.target.closest('[data-open]');
  if (open) {
    const dlg = document.getElementById(open.dataset.open);
    dlg?.showModal();
    dlg?.querySelector('input,select,textarea')?.focus();
    open.closest('[data-menu]')?.classList.remove('open');
  }
  const empty = e.target.closest('[data-empty]');
  if (empty) { e.preventDefault(); toast('Nothing to study in this deck right now. Come back tomorrow, or add more cards.'); }
  const del = e.target.closest('[data-delete-deck]');
  if (del) {
    const n = +del.dataset.count;
    if (!confirm(`Delete the deck “${del.dataset.name}”${n ? ` and its ${n} card${n === 1 ? '' : 's'} (with their review history)` : ''}? This can't be undone.`)) return;
    api(`/api/decks/${del.dataset.deleteDeck}/delete`, {}).then(() => reload('Deck deleted.')).catch(err => toast(err.message, 'err'));
  }
});

function values(form) { return Object.fromEntries(new FormData(form)); }

for (const f of $$('[data-deck-form]')) {
  f.addEventListener('submit', async (e) => {
    if (e.submitter?.value !== 'ok') return;
    e.preventDefault();
    const v = values(f);
    const body = { name: v.name, new_per_day: +v.new_per_day, max_reviews: +v.max_reviews };
    try {
      await api(f.dataset.id ? `/api/decks/${f.dataset.id}` : '/api/decks', body);
      reload(f.dataset.id ? 'Deck saved.' : `Deck “${v.name}” created.`);
    } catch (err) { toast(err.message, 'err'); }
  });
}

for (const f of $$('[data-grade-form]')) {
  f.addEventListener('submit', async (e) => {
    if (e.submitter?.value !== 'ok') return;
    e.preventDefault();
    e.submitter.classList.add('is-busy');
    try {
      const r = await api(`/api/decks/${f.dataset.id}/kanji`, { grade: +values(f).grade });
      reward(r);
      reload(`Added ${r.added} kanji${r.skipped ? ` (${r.skipped} were already in a deck)` : ''}.`);
    } catch (err) { e.submitter.classList.remove('is-busy'); toast(err.message, 'err'); }
  });
}

for (const f of $$('[data-card-form]')) {
  f.addEventListener('submit', async (e) => {
    if (e.submitter?.value !== 'ok') return;
    e.preventDefault();
    try {
      await api(`/api/decks/${f.dataset.id}/cards`, values(f));
      toast('Card added ✓ Write another, or press Done.');
      f.reset();
      f.querySelector('textarea').focus();
    } catch (err) { toast(err.message, 'err'); }
  });
  f.closest('dialog').addEventListener('close', () => { if (f.closest('dialog').returnValue === 'cancel') reload(); });
}

const imp = $('[data-import-apkg]');
imp?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = imp.file.files[0];
  if (!file) return;
  const msg = $('[data-import-msg]', imp), btn = imp.querySelector('button[type=submit]');
  btn.classList.add('is-busy'); msg.textContent = `Importing ${file.name}…`;
  const fd = new FormData(); fd.append('file', file);
  try {
    const res = await fetch('/api/import/apkg', { method: 'POST', body: fd, headers: { 'X-CSRF-Token': csrf() } });
    const r = await res.json();
    if (!r.ok) throw new Error(r.error);
    reload(`Imported ${r.cards} cards into “${r.deck}”.${r.skipped ? ` ${r.skipped} empty notes were skipped.` : ''}`);
  } catch (err) { msg.textContent = err.message; btn.classList.remove('is-busy'); }
});
