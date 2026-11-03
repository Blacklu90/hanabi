import { $, api, reward, toast } from './app.js';
import { wireStrokes } from './strokes.js';

wireStrokes().then(() => $('[data-strokes]')?._player?.play());

const study = $('[data-study]');
study?.addEventListener('click', async () => {
  study.classList.add('is-busy');
  try {
    const deck = $('[data-study-deck]')?.value || 0;
    const r = await api(`/api/kanji/${encodeURIComponent(study.dataset.study)}/study?deck=${deck}`, {});
    const pill = document.createElement('span'); pill.className = 'pill gold';
    pill.textContent = r.added ? 'New · added to your deck' : 'Already in a deck';
    study.closest('.study-add').replaceWith(pill);
    reward(r);
  } catch (e) { study.classList.remove('is-busy'); toast(e.message, 'err'); }
});

// Keyboard: ← / → move between kanji
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input,textarea,select') || e.metaKey || e.ctrlKey || e.altKey) return;
  const dir = e.key === 'ArrowLeft' ? 'Previous' : e.key === 'ArrowRight' ? 'Next' : null;
  if (dir) document.querySelector(`a[aria-label^="${dir} kanji"]`)?.click();
});

// My notes
const nf = $('[data-kanji-note]');
nf?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const st = $('[data-note-status]', nf);
  try {
    await api('/api/notes', { track: 'kanji', item: nf.dataset.item, meaning: nf.meaning.value, mnemonic: nf.mnemonic.value, notes: nf.notes.value });
    st.textContent = 'Saved ✓';
  } catch (err) { st.textContent = err.message; }
});
nf?.addEventListener('input', () => { $('[data-note-status]', nf).textContent = 'Not saved yet'; });

// "+ Study this word" in the words list
import('./words-ui.js').then((m) => m.wireAddWord());
